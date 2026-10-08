"""Boolean dialog (Create/Modify > Boolean...) -- Session 141, extended
in Session 143 from Fuse-only to Fuse / Subtract.

Combine a TOOL part with the ACTIVE part (the target / blank): Fuse
unions them; Subtract removes the tool's volume from the target. The
tool is then removed from the assembly -- it is consumed, as in the
usual CAD "join"/"cut with a tool body". One undo step: Ctrl+Z restores
both parts.

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

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox, QPushButton, QCheckBox)
from PySide6.QtGui import QFont

from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut
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
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Target (Active Part):"))
        self.target_label = QLabel()
        f = QFont()
        f.setBold(True)
        self.target_label.setFont(f)
        lay.addWidget(self.target_label)

        row_op = QHBoxLayout()
        row_op.addWidget(QLabel("Operation:"))
        self.op_combo = QComboBox()
        self.op_combo.addItems(["Fuse", "Subtract"])
        row_op.addWidget(self.op_combo)
        lay.addLayout(row_op)

        row = QHBoxLayout()
        row.addWidget(QLabel("Tool part:"))
        self.tool_combo = QComboBox()
        row.addWidget(self.tool_combo)
        lay.addLayout(row)

        self.unify_check = QCheckBox("Merge seam faces")
        self.unify_check.setChecked(True)
        lay.addWidget(self.unify_check)
        lay.addWidget(QLabel("The tool part will be consumed by this operation."))

        self.msg_label = QLabel("")
        self.msg_label.setWordWrap(True)
        lay.addWidget(self.msg_label)

        self.done_btn = QPushButton("✅ Done")
        self.done_btn.clicked.connect(self._on_done)
        lay.addWidget(self.done_btn)

        self._populate()

    def _populate(self):
        win = self.main_win
        uid = win.activePartUID
        self.tool_combo.clear()
        if not uid or uid not in dm.part_dict:
            self.target_label.setText("(none)")
            self.done_btn.setEnabled(False)
            self.msg_label.setText(
                "Set an Active Part first (RMB > Set Active).")
            return
        self.target_label.setText(dm.get_full_path_name(uid))
        target_ref = dm.label_dict.get(uid, {}).get('ref_entry')
        for u in dm.part_dict:
            if u == uid:
                continue
            # A shared instance of the target is the same shape --
            # fusing a part into itself is meaningless.
            if target_ref and dm.label_dict.get(u, {}).get(
                    'ref_entry') == target_ref:
                continue
            self.tool_combo.addItem(dm.get_full_path_name(u), u)
        if self.tool_combo.count() == 0:
            self.done_btn.setEnabled(False)
            self.msg_label.setText("No other part to fuse with.")

    def _say(self, text):
        self.msg_label.setText(text)
        self.main_win.statusBar().showMessage(text, 6000)

    def _on_done(self):
        win = self.main_win
        uid = win.activePartUID
        tool_uid = self.tool_combo.currentData()
        if (not uid or uid not in dm.part_dict
                or tool_uid not in dm.part_dict):
            self._say("Target or tool part no longer exists.")
            return
        part = dm.part_dict[uid]['shape']
        tool = dm.part_dict[tool_uid]['shape']
        tool_name = dm.label_dict.get(tool_uid, {}).get('name', tool_uid)
        subtracting = (self.op_combo.currentText() == "Subtract")
        verb = "Subtract" if subtracting else "Fuse"

        try:
            if subtracting:
                if _count(part, TopAbs_FACE) == 0:
                    self._say("Target is empty -- nothing to subtract from.")
                    return
                op = BRepAlgoAPI_Cut(part, tool)
                if not op.IsDone():
                    self._say("Subtract failed -- the parts could not be "
                              "combined.")
                    return
                newPart = op.Shape()
                if _count(newPart, TopAbs_FACE) == 0:
                    self._say("Subtract would remove the entire target -- "
                              "nothing changed.")
                    return
            elif _count(part, TopAbs_FACE) == 0:
                newPart = tool
            else:
                op = BRepAlgoAPI_Fuse(part, tool)
                if not op.IsDone():
                    self._say("Fuse failed -- the parts could not be "
                              "combined.")
                    return
                newPart = op.Shape()
        except Exception as e:
            self._say(f"{verb} failed: {e}")
            return

        note = ""
        if subtracting:
            v0, v1 = _volume(part), _volume(newPart)
            if v0 is not None and v1 is not None and abs(v0 - v1) <= \
                    1e-9 * max(abs(v0), 1.0):
                self._say("The tool does not overlap the target -- "
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
                     f"(the {'cut split the target in two' if subtracting else 'parts do not touch or overlap'}).")

        # Capture stable info BEFORE changing the document: uids are
        # entry+per-entry serial, but the shared-prototype entry and
        # the pre-change uid set are what the redraw needs.
        ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
        old_uids = set(dm.part_dict.keys())
        win.erase_shape(uid)
        # ONE undo step covers both the target's new shape and the
        # tool's removal.
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
            deleted = dm.delete_component(tool_uid)
        if deleted:
            if tool_uid == win.activePartUID:
                win.activePartUID = 0
                win.activePart = None
            if tool_uid == win.activeAsyUID:
                win.activeAsyUID = 0
        win.redraw_after_shape_replace(ref_entry, old_uids)
        win.setActivePart(uid)
        self.main_win.statusBar().showMessage(
            f"{'Subtracted' if subtracting else 'Fused'} '{tool_name}' "
            f"{'from' if subtracting else 'into'} the active part{note} "
            f"(Ctrl+Z undoes).", 8000)
        self.accept()


def show_boolean_dialog(main_win):
    BooleanDialog(main_win).exec()
