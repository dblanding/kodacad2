"""
pull_dialog.py -- the new, integrated Pull dialog (Step 2 of the
Create/Modify 3D plan; Doug's Pull_Dialog_Specification.pdf).

Added ALONGSIDE the existing Extrude / Mill-Pull / Fillet / Shell menu
structure, not replacing it yet -- Doug's own explicit call: the
spec's "Create/Modify 3D replaces Create 3D and Modify Active Part"
is a "crystal ball" end state, not this step. Nothing existing is
touched; this is purely additive, so every current tutorial keeps
working unchanged.

Linear mode is fully functional -- reuses mill_pull_dialog.py's own,
already-proven Add/Remove Material + tool-building logic exactly,
plus one real addition: createEmptyPart() means parts routinely start
genuinely empty now, so Add Material on an empty part skips the
degenerate boolean entirely and uses the tool's own shape directly --
the same, already-verified fix from the Session 90/91 empty-part
investigation, carried into the dialog meant to be its permanent home
rather than re-proven from scratch.

Angular mode is deliberately a stub, per Doug's own instruction --
selectable, its own section of the dialog fully laid out, but Done
refuses it with a plain, honest status message rather than attempt a
half-built operation. Axis-picking (Step 3) is what turns this from a
stub into a real, working mode.

Layout follows the spec's own 4-section structure exactly:
    Top:           Active Part / Active Workplane (bold, read-only)
    Upper Middle:  "Method" -- Operation / Direction / Mode
    Lower Middle:  unlabeled, swaps with Mode (Distance, or the
                   Angular stub)
    Bottom:        one '\u2705 Done' button only -- no Reverse/Back,
                   no Keep WP/Keep Prof (Doug: shortcuts, not needed
                   yet)
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QComboBox, QLineEdit,
                               QPushButton, QRadioButton, QButtonGroup,
                               QStackedWidget, QWidget)
from PySide6.QtGui import QFont

from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE

import docmodel
# dm is created in mainwindow (module-global there); importing it at
# module level here would be circular-adjacent -- fetch lazily, same
# precedent as mill_pull_dialog.py.
from mainwindow import dm


def _bold_label(text=""):
    lbl = QLabel(text)
    f = QFont()
    f.setBold(True)
    lbl.setFont(f)
    lbl.setWordWrap(True)
    return lbl


class PullDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.setWindowTitle("Pull")
        self.setModal(False)

        lay = QVBoxLayout(self)

        # --- Top section: Active Part / Active Workplane, read-only ---
        lay.addWidget(QLabel("Active Part:"))
        self.part_label = _bold_label()
        lay.addWidget(self.part_label)
        lay.addWidget(QLabel("Active Workplane:"))
        self.wp_label = _bold_label()
        lay.addWidget(self.wp_label)

        # --- Upper middle section: Method ---
        lay.addWidget(_bold_label("Method"))

        row_op = QHBoxLayout()
        row_op.addWidget(QLabel("Operation:"))
        self.op_combo = QComboBox()
        self.op_combo.addItems(["Add Material", "Remove Material"])
        row_op.addWidget(self.op_combo)
        lay.addLayout(row_op)

        row_dir = QHBoxLayout()
        row_dir.addWidget(QLabel("Direction:"))
        self.dir_combo = QComboBox()
        self.dir_combo.addItems(["+W", "-W"])
        # Same smart default as the proven mill_pull_dialog.py: +W for
        # Add, -W for Remove, until the user touches Direction
        # themselves. Add Material is index 0 here (spec's own
        # default), unlike the old dialog's ordering -- matched by
        # combo TEXT, not index, to avoid an ordering mixup.
        self._dir_touched = False
        self.dir_combo.activated.connect(self._mark_dir_touched)
        self.op_combo.currentIndexChanged.connect(self._op_changed)
        row_dir.addWidget(self.dir_combo)
        lay.addLayout(row_dir)

        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("Mode:"))
        self.linear_radio = QRadioButton("Linear")
        self.angular_radio = QRadioButton("Angular")
        self.linear_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.linear_radio)
        self.mode_group.addButton(self.angular_radio)
        self.linear_radio.toggled.connect(self._mode_changed)
        row_mode.addWidget(self.linear_radio)
        row_mode.addWidget(self.angular_radio)
        lay.addLayout(row_mode)

        # --- Lower middle section: unlabeled, swaps with Mode ---
        self.mode_stack = QStackedWidget()

        # Page 0: Linear -- Distance
        linear_page = QWidget()
        linear_lay = QHBoxLayout(linear_page)
        linear_lay.setContentsMargins(0, 0, 0, 0)
        self.dist_units_label = QLabel(
            f"Distance ({getattr(main_win, 'units', 'mm')}):")
        linear_lay.addWidget(self.dist_units_label)
        self.dist_edit = QLineEdit()
        self.dist_edit.setPlaceholderText("e.g. 12.0")
        self.dist_edit.textChanged.connect(self._dist_changed)
        linear_lay.addWidget(self.dist_edit)
        self.mode_stack.addWidget(linear_page)

        # Page 1: Angular -- STUB (Step 3 makes this real)
        angular_page = QWidget()
        angular_lay = QVBoxLayout(angular_page)
        angular_lay.setContentsMargins(0, 0, 0, 0)
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("Angle (Degrees):"))
        self.angle_edit = QLineEdit()
        self.angle_edit.setPlaceholderText("e.g. 90")
        self.angle_edit.setEnabled(False)
        angle_row.addWidget(self.angle_edit)
        angular_lay.addLayout(angle_row)
        self.select_axis_btn = QPushButton("Select Axis")
        self.select_axis_btn.setEnabled(False)
        angular_lay.addWidget(self.select_axis_btn)
        angular_lay.addWidget(QLabel(
            "Angular pull is under construction -- coming in a "
            "future step."))
        self.mode_stack.addWidget(angular_page)

        lay.addWidget(self.mode_stack)

        self.msg_label = QLabel("")
        self.msg_label.setWordWrap(True)
        lay.addWidget(self.msg_label)

        # --- Bottom section: one Done button only (spec: no Reverse/
        # Back, no Keep WP/Keep Prof -- shortcuts, not needed yet) ---
        self.done_btn = QPushButton("\u2705 Done")
        self.done_btn.clicked.connect(self._on_done)
        lay.addWidget(self.done_btn)

        self._refresh_labels()
        self.dist_edit.setFocus()

    # ------------------------------------------------------------------

    def _mark_dir_touched(self, *_):
        self._dir_touched = True

    def _op_changed(self, *_):
        if not self._dir_touched:
            self.dir_combo.setCurrentText(
                "+W" if self.op_combo.currentText() == "Add Material"
                else "-W")

    def _mode_changed(self, *_):
        self.mode_stack.setCurrentIndex(
            0 if self.linear_radio.isChecked() else 1)
        if self.angular_radio.isChecked():
            self.main_win.statusBar().showMessage(
                "Angular pull is under construction.", 5000)

    def _dist_changed(self, text):
        # Spec: "acknowledge value entered, prompt user to click
        # Done" -- brief status-bar note once a valid, positive
        # number is present, nothing louder than that.
        try:
            v = float(text)
            if v > 0.0:
                self.main_win.statusBar().showMessage(
                    f"Distance set -- click Done.", 4000)
        except ValueError:
            pass

    def _refresh_units_label(self):
        self.dist_units_label.setText(
            f"Distance ({getattr(self.main_win, 'units', 'mm')}):")

    def _refresh_labels(self):
        win = self.main_win
        uid = win.activePartUID
        if uid:
            try:
                text = dm.get_full_path_name(uid)
            except Exception:
                try:
                    text = dm.label_dict.get(uid, {}).get('name') or uid
                except Exception:
                    text = uid
            self.part_label.setText(text)
        else:
            self.part_label.setText("NONE -- set one (RMB in the "
                                    "tree)")
        wp_uid = getattr(win, "activeWpUID", 0)
        # Workplanes aren't XDE-backed like parts -- their own uid IS
        # their display name (e.g. "wp1"), confirmed directly against
        # this project's own terminal output convention ("Part
        # selected: wp1, UID: wp1" -- identical string both times).
        self.wp_label.setText(str(wp_uid) if wp_uid else
                              "NONE -- create and activate one first")

    def _say(self, text):
        self.msg_label.setText(text)
        self.main_win.statusBar().showMessage(text, 5000)

    # ------------------------------------------------------------------

    def _on_done(self):
        win = self.main_win
        self._refresh_labels()
        self._refresh_units_label()
        uid = win.activePartUID
        part = win.activePart
        wp = win.activeWp
        if not uid or part is None:
            self._say("No active part -- set one first "
                      "(RMB in the tree).")
            return
        if wp is None:
            self._say("No active workplane.")
            return

        if self.angular_radio.isChecked():
            # Stub (Step 3 makes this real) -- refuse plainly rather
            # than attempt a half-built operation.
            self._say("Angular pull isn't implemented yet -- use "
                      "Linear mode for now.")
            return

        try:
            dist = float(self.dist_edit.text())
        except ValueError:
            self._say("Enter a numeric distance.")
            return
        if dist <= 0.0:
            self._say("Distance must be positive (choose -W for the "
                      "other direction).")
            return

        faces, err = wp.make_faces()
        if err is not None:
            self._say(f"Profile problem: {err}")
            return

        adding = (self.op_combo.currentText() == "Add Material")
        sign = 1.0 if self.dir_combo.currentText() == "+W" else -1.0
        vec = wp.wVec * (sign * dist * win.unitscale)

        try:
            tool = None
            for f in faces:
                prism = BRepPrimAPI_MakePrism(f, vec).Shape()
                tool = prism if tool is None else \
                    BRepAlgoAPI_Fuse(tool, prism).Shape()

            # Session 90/91's own, verified fix: createEmptyPart()
            # means a part routinely starts genuinely empty (zero
            # faces) -- a boolean against a degenerate, empty solid
            # silently produced the wrong shape type (Compound
            # instead of Solid) rather than failing outright. Check
            # emptiness BEFORE reaching for the boolean, same as the
            # verified-working test utility this dialog is the real,
            # permanent replacement for.
            n_faces = 0
            exp = TopExp_Explorer(part, TopAbs_FACE)
            while exp.More():
                n_faces += 1
                exp.Next()
            part_is_empty = (n_faces == 0)

            if part_is_empty and not adding:
                self._say("Active part is empty -- nothing to "
                          "remove material from.")
                return
            elif part_is_empty:
                newPart = tool
            elif adding:
                newPart = BRepAlgoAPI_Fuse(part, tool).Shape()
            else:
                newPart = BRepAlgoAPI_Cut(part, tool).Shape()
        except Exception as be:
            self._say(f"Boolean failed: {be}")
            return

        # Each Done = ONE undo transaction (a complete operation)
        win.erase_shape(uid)
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        win.draw_shape(uid)
        win.setActivePart(uid)
        n_prof = len(faces)
        verb = "Added" if adding else "Removed"
        win.statusBar().showMessage(
            f"{verb} material, {n_prof} profile(s), {dist:g} "
            f"{getattr(win, 'units', 'mm')} "
            f"{self.dir_combo.currentText()} (Ctrl+Z undoes).", 6000)
        self.close()


def show_pull_dialog(main_win):
    """Launcher -- one dialog instance, raised if already open."""
    dlg = getattr(main_win, "_pull_dlg", None)
    if dlg is not None and dlg.isVisible():
        dlg.raise_()
        dlg.activateWindow()
        return
    dlg = PullDialog(main_win)
    main_win._pull_dlg = dlg
    dlg.show()
