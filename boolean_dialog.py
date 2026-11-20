"""Boolean dialog (Create/Modify > Boolean...) -- Session 141, extended
in Session 143 from Fuse-only to Fuse / Subtract.

Combine one or more TOOL parts with the ACTIVE part (the blank): Fuse
unions them; Subtract removes each tool's volume from the blank.
Session 179 (Doug's Creo E/D model): the dialog is small, modeless and
sits in the viewport's upper-left corner; the tools are PICKED -- in the
tree (Ctrl/Shift-click) or by box-select in the viewport, both of which
end up as the tree's selection, which the dialog watches -- instead of
chosen from a long combo of every part; and 'Keep tool' says whether the
tools survive. Without it the tools are consumed, as in the usual CAD
"join"/"cut with a tool body". One undo step: Ctrl+Z restores
everything. The detail text lives in the '?' info window, not the
dialog.

Doug's use case: lengthen a part by copying it, trimming the bottom off
one copy and the top off the other, then fusing the two halves.
Subtract's motivating use (Session 143): loft an outer and an inner
profile set as two separate parts and subtract the inner from the
outer, making a hollow body whose inner surface is an ordinary cut.
Because a join leaves a visible seam where the halves meet (same-surface
faces split in two), "Merge seam faces" (on by default) runs
ShapeUpgrade_UnifySameDomain on the result; if that fails or returns an
invalid shape the plain fuse is kept and the status line says so.

Geometry is fused in WORLD space (part_dict shapes already carry their
placement); replace_shape() un-does the target's own location when it
stores the result, same as Pull.
"""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox, QLineEdit, QCheckBox,
                               QGridLayout)

import safe_boolean
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.BRepCheck import BRepCheck_Analyzer

import docmodel
# dm lives in mainwindow (module-global there) -- same import as
# pull_dialog.py.
from mainwindow import dm
import dialog_style


def _count(shape, kind):
    n = 0
    exp = TopExp_Explorer(shape, kind)
    while exp.More():
        n += 1
        exp.Next()
    return n


def _volume(shape):
    """Volume of shape, or None if it can't be computed."""
    try:
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        return props.Mass()
    except Exception:
        return None


def _unify(shape):
    """Merge faces/edges lying on the same surface/curve. Returns the
    unified shape, or None if it failed or produced an invalid shape."""
    try:
        u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
        u.Build()
        out = u.Shape()
        if out.IsNull() or not BRepCheck_Analyzer(out).IsValid():
            return None
        return out
    except Exception as e:
        print(f"[Fuse] UnifySameDomain failed: {e}")
        return None


class BooleanDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.setWindowTitle("Boolean")
        self.setModal(False)
        self._busy = False
        self._tools = []          # uids currently picked as tools
        self._info = dialog_style.InfoWindow(main_win, "Boolean details")

        lay = QVBoxLayout(self)

        # --- Creo-style rows: Blank (read-only, the active part) and
        # Tools (yellow until something is picked) -------------------
        rows = QGridLayout()
        rows.addWidget(dialog_style.row_label("Blank"), 0, 0)
        self.blank_edit = QLineEdit()
        self.blank_edit.setReadOnly(True)
        rows.addWidget(self.blank_edit, 0, 1)
        rows.addWidget(dialog_style.row_label("Tools"), 1, 0)
        self.tools_edit = QLineEdit()
        self.tools_edit.setReadOnly(True)
        rows.addWidget(self.tools_edit, 1, 1)
        rows.addWidget(dialog_style.row_label("Operation"), 2, 0)
        self.op_combo = QComboBox()
        self.op_combo.addItems(["Fuse", "Subtract"])
        self.op_combo.currentIndexChanged.connect(self._refresh_info)
        rows.addWidget(self.op_combo, 2, 1)
        rows.setColumnStretch(1, 1)
        lay.addLayout(rows)

        checks = QHBoxLayout()
        self.keep_check = QCheckBox("Keep Tool")
        self.keep_check.setToolTip(
            "Leave the tool parts in the assembly (otherwise they are "
            "consumed by the operation).")
        self.keep_check.toggled.connect(self._refresh_info)
        self.unify_check = QCheckBox("Merge Seams")
        self.unify_check.setChecked(True)
        self.unify_check.setToolTip(
            "Merge faces split by the join (ShapeUpgrade_UnifySameDomain).")
        checks.addWidget(self.keep_check)
        checks.addWidget(self.unify_check)
        lay.addLayout(checks)

        bar, self.ok_btn, self.cancel_btn, self.help_btn = \
            dialog_style.icon_bar(self._on_done, self.close,
                                  self._toggle_info)
        lay.insertLayout(0, bar)

        self.msg_label = QLabel("")
        self.msg_label.setObjectName("KcStatus")
        self.msg_label.setWordWrap(True)
        lay.addWidget(self.msg_label)

        dialog_style.apply_minimal(self)
        self.setMinimumWidth(260)

        # The tree's selection IS the tool list (viewport box-select
        # already mirrors into the tree).
        main_win.treeView.itemSelectionChanged.connect(self._refresh)
        self._refresh()

    # ------------------------------------------------------------------
    def _toggle_info(self):
        self._refresh_info()
        self._info.toggle(self.main_win)

    def event(self, ev):
        # Re-read the active part whenever the dialog is activated
        # (RMB > Set Active happens in the tree, not here).
        if ev.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._refresh()
        return super().event(ev)

    def done(self, r):
        try:
            self.main_win.treeView.itemSelectionChanged.disconnect(
                self._refresh)
        except Exception:
            pass
        try:
            self._info.hide()
            self._info.deleteLater()
        except Exception:
            pass
        super().done(r)

    def _blank_uid(self):
        uid = self.main_win.activePartUID
        return uid if uid and uid in dm.part_dict else None

    def _parts_under(self, uid):
        """uid itself if it is a part, else every part below an
        assembly row."""
        if uid in dm.part_dict:
            return [uid]
        out = []
        stack = [uid]
        while stack:
            cur = stack.pop()
            for u, info in dm.label_dict.items():
                if info.get('parent_uid') == cur:
                    if u in dm.part_dict:
                        out.append(u)
                    else:
                        stack.append(u)
        return out

    def _picked_tools(self, blank):
        """Parts in the tree's current selection, minus the blank and
        any shared instance of it (fusing a part into itself is
        meaningless)."""
        blank_ref = dm.label_dict.get(blank, {}).get('ref_entry') \
            if blank else None
        tools, seen = [], set()
        for it in self.main_win.treeView.selectedItems():
            u = it.text(1)
            if u not in dm.label_dict:
                continue
            for p in self._parts_under(u):
                if p in seen or p == blank:
                    continue
                if blank_ref and dm.label_dict.get(p, {}).get(
                        'ref_entry') == blank_ref:
                    continue
                seen.add(p)
                tools.append(p)
        return tools

    def _name(self, uid):
        return dm.label_dict.get(uid, {}).get('name', str(uid))

    def _refresh(self, *_):
        if self._busy:
            return
        blank = self._blank_uid()
        self._tools = self._picked_tools(blank) if blank else []
        self.blank_edit.setText(self._name(blank) if blank else "")
        if self._tools:
            txt = (self._name(self._tools[0]) if len(self._tools) == 1
                   else f"{len(self._tools)} parts")
        else:
            txt = ""
        self.tools_edit.setText(txt)
        self.tools_edit.setToolTip("\n".join(
            dm.get_full_path_name(u) for u in self._tools))
        dialog_style.set_awaiting(self.tools_edit,
                                  blank is not None and not self._tools)
        self.ok_btn.setEnabled(blank is not None and bool(self._tools))
        if blank is None:
            self.msg_label.setText(
                "Set an Active Part first (RMB > Set Active).")
        elif not self._tools:
            self.msg_label.setText(
                "Pick the tool part(s) in the tree or the viewport.")
        else:
            self.msg_label.setText("")
        self._refresh_info()

    def _refresh_info(self, *_):
        blank = self._blank_uid()
        op = self.op_combo.currentText()
        keep = self.keep_check.isChecked()
        h = ["<h3>Boolean - %s</h3>" % op]
        if op == "Fuse":
            h.append("<p>Joins every tool into the blank, giving one "
                     "part.</p>")
        else:
            h.append("<p>Removes each tool's volume from the blank. A "
                     "tool that does not overlap the blank changes "
                     "nothing.</p>")
        h.append("<p>Tools are <b>%s</b> by the operation.</p>" %
                 ("kept" if keep else "consumed (removed from the "
                  "assembly)"))
        h.append("<p><b>Blank</b> (the active part):<br>%s</p>" %
                 (dm.get_full_path_name(blank) if blank else "(none)"))
        if self._tools:
            h.append("<p><b>Tools</b> (%d):</p><ul>" % len(self._tools))
            for u in self._tools:
                h.append("<li>%s</li>" % dm.get_full_path_name(u))
            h.append("</ul>")
        else:
            h.append("<p><b>Tools:</b> none picked yet. Select parts in "
                     "the tree (Ctrl/Shift-click) or box-select them in "
                     "the viewport; selecting an assembly row picks all "
                     "of its parts.</p>")
        h.append("<p>One undo step (Ctrl+Z) restores everything.</p>")
        self._info.set_html("".join(h))

    def _say(self, text):
        self.msg_label.setText(text)
        self.main_win.statusBar().showMessage(text, 6000)

    def _on_done(self):
        win = self.main_win
        uid = self._blank_uid()
        tool_uids = [t for t in self._tools if t in dm.part_dict]
        if not uid or not tool_uids:
            self._say("Blank or tool part(s) no longer exist.")
            return
        part = dm.part_dict[uid]['shape']
        subtracting = (self.op_combo.currentText() == "Subtract")
        verb = "Subtract" if subtracting else "Fuse"
        keep = self.keep_check.isChecked()

        # Everything is computed BEFORE the document is touched, so a
        # failure part-way leaves it unchanged.
        newPart = part
        try:
            if subtracting and _count(part, TopAbs_FACE) == 0:
                self._say("Blank is empty -- nothing to subtract from.")
                return
            for t in tool_uids:
                tool = dm.part_dict[t]['shape']
                tname = self._name(t)
                if subtracting:
                    res, msg = safe_boolean.run_boolean(
                        "cut", newPart, tool, parent=win,
                        label=f"Subtracting '{tname}'...")
                    if res is None:
                        self._say(f"'{tname}': {msg}")
                        return
                    newPart = res
                    if _count(newPart, TopAbs_FACE) == 0:
                        self._say("Subtract would remove the entire "
                                  "blank -- nothing changed.")
                        return
                elif _count(newPart, TopAbs_FACE) == 0:
                    newPart = tool
                else:
                    res, msg = safe_boolean.run_boolean(
                        "fuse", newPart, tool, parent=win,
                        label=f"Fusing '{tname}'...")
                    if res is None:
                        self._say(f"'{tname}': {msg}")
                        return
                    newPart = res
        except Exception as e:
            self._say(f"{verb} failed: {e}")
            return

        note = ""
        if subtracting:
            v0, v1 = _volume(part), _volume(newPart)
            if v0 is not None and v1 is not None and abs(v0 - v1) <= \
                    1e-9 * max(abs(v0), 1.0):
                self._say("The tool(s) do not overlap the blank -- "
                          "nothing was removed, nothing changed.")
                return
        if self.unify_check.isChecked():
            merged = _unify(newPart)
            if merged is not None:
                newPart = merged
            else:
                note = " (seam merge skipped)"

        n_solids = _count(newPart, TopAbs_SOLID)
        if n_solids != 1:
            note += (f" Note: result has {n_solids} separate solids "
                     f"(the {'cut split the blank in two' if subtracting else 'parts do not touch or overlap'}).")

        # Capture stable info BEFORE changing the document (uids are
        # entry+per-entry serial and parse_doc() re-issues serials).
        ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
        old_uids = set(dm.part_dict.keys())
        # Deleting shared instances can renumber the survivors, so then
        # they must all be redrawn (same rule as _delete_selected).
        shared = (not keep) and win._delete_renumbers_uids(tool_uids)
        n_tools = len(tool_uids)
        self._busy = True
        try:
            win.erase_shape(uid)
            # ONE undo step covers the blank's new shape and the
            # tools' removal.
            with docmodel.undo_transaction(dm):
                dm.replace_shape(uid, newPart)
                if not keep:
                    dm.delete_components(tool_uids)
            # activePartUID follows parse_doc()'s renumbering through
            # the uid-remap listener; fall back to the old uid.
            if win.activePartUID not in dm.part_dict:
                win.activePartUID = 0
                win.activePart = None
            if win.activeAsyUID and win.activeAsyUID not in dm.label_dict:
                win.activeAsyUID = 0
            win.build_tree()
            force = ({u for u, info in dm.label_dict.items()
                      if info.get('ref_entry') == ref_entry
                      and u in dm.part_dict} if ref_entry else set())
            win._incremental_reconcile(old_uids, force_redraw_uids=force,
                                       redraw_all_survivors=shared)
            target = win.activePartUID if win.activePartUID in \
                dm.part_dict else uid
            if target in dm.part_dict:
                win.setActivePart(target)
        finally:
            self._busy = False
        what = (f"'{self._name(tool_uids[0])}'" if n_tools == 1
                else f"{n_tools} parts")
        win.statusBar().showMessage(
            f"{'Subtracted' if subtracting else 'Fused'} {what} "
            f"{'from' if subtracting else 'into'} the active part"
            f"{'' if not keep else ' (tools kept)'}{note} "
            f"(Ctrl+Z undoes).", 8000)
        self.close()


def show_boolean_dialog(main_win):
    """Launcher -- one dialog instance, raised if already open."""
    dlg = getattr(main_win, "_boolean_dlg", None)
    if dlg is not None and dlg.isVisible():
        dlg.raise_()
        dlg.activateWindow()
        return
    dlg = BooleanDialog(main_win)
    main_win._boolean_dlg = dlg
    dlg.show()
    dialog_style.place_top_left(dlg, main_win)
