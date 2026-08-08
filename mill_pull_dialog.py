"""
mill_pull_dialog.py -- the combined Mill/Pull dialog (Session 63).

Modeled on the banked Creo Elements/Direct 'Pull' dialog per Doug's
spec, kept LEAN: three fields --
    Operation:  Remove material (Mill)  /  Add material (Pull)
    Direction:  +W  /  -W
    Distance:   millimeters
with ONE '\u2705 Done' button per the Position dialog's convention
(Doug: Apply exists nowhere else in the project). Done validates,
performs the operation as its own undo transaction, and closes;
Ctrl+Z peels back one operation at a time. The header matches
Position's: caption + bold full-path breadcrumb.

Multi-profile: profiles come from wp.make_faces() -- every closed
loop on the active workplane participates, outer loops with their
contained loops as holes. A plate outline plus six hole circles is
ONE Apply.
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QComboBox, QLineEdit,
                               QPushButton)

from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

import docmodel
# dm is created in mainwindow (module-global there); importing it at
# module level here would be circular-adjacent -- fetch lazily.
from mainwindow import dm


class MillPullDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.setWindowTitle("Mill / Pull")
        self.setModal(False)

        lay = QVBoxLayout(self)

        # Header matches the Position dialog (Session 63, Doug:
        # side-by-side the two dialogs should share one look):
        # caption line + BOLD full-path breadcrumb.
        lay.addWidget(QLabel("Modifying part:"))
        self.part_label = QLabel()
        from PySide6.QtGui import QFont
        _bold = QFont()
        _bold.setBold(True)
        self.part_label.setFont(_bold)
        self.part_label.setWordWrap(True)
        lay.addWidget(self.part_label)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Operation:"))
        self.op_combo = QComboBox()
        self.op_combo.addItems(["Remove material (Mill)",
                                "Add material (Pull)"])
        row1.addWidget(self.op_combo)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Direction:"))
        self.dir_combo = QComboBox()
        self.dir_combo.addItems(["+W", "-W"])
        # Milling most often goes INTO the part (-W when sketching on
        # its top face); pulling most often grows outward (+W).
        # Default follows the operation choice until the user touches
        # the direction themselves.
        self.dir_combo.setCurrentText("-W")
        self._dir_touched = False
        self.dir_combo.activated.connect(self._mark_dir_touched)
        self.op_combo.currentIndexChanged.connect(self._op_changed)
        row2.addWidget(self.dir_combo)
        lay.addLayout(row2)

        row3 = QHBoxLayout()
        # Label follows the app's CURRENT units (Doug's reminder --
        # Kodacad also works in inches). The math was already
        # unit-correct: entered value * win.unitscale = mm internal.
        self.dist_units_label = QLabel(
            f"Distance ({getattr(main_win, 'units', 'mm')}):")
        row3.addWidget(self.dist_units_label)
        self.dist_edit = QLineEdit()
        self.dist_edit.setPlaceholderText("e.g. 12.0")
        row3.addWidget(self.dist_edit)
        lay.addLayout(row3)

        self.msg_label = QLabel("")
        self.msg_label.setWordWrap(True)
        lay.addWidget(self.msg_label)

        # ONE '\u2705 Done' button, Position's convention exactly
        # (Session 63, Doug: Apply retired -- it exists nowhere else
        # in the project). Done VALIDATES, PERFORMS the operation,
        # and closes on success; validation problems keep the dialog
        # open with the message. Another operation = reopen from the
        # menu; Ctrl+Z undoes one operation at a time as before.
        self.done_btn = QPushButton("\u2705 Done")
        self.done_btn.clicked.connect(self._on_done)
        lay.addWidget(self.done_btn)

        self._refresh_part_label()
        self.dist_edit.setFocus()

    # ------------------------------------------------------------------

    def _mark_dir_touched(self, *_):
        self._dir_touched = True

    def _op_changed(self, *_):
        if not self._dir_touched:
            self.dir_combo.setCurrentText(
                "-W" if self.op_combo.currentIndex() == 0 else "+W")

    def _refresh_units_label(self):
        self.dist_units_label.setText(
            f"Distance ({getattr(self.main_win, 'units', 'mm')}):")

    def _refresh_part_label(self):
        uid = self.main_win.activePartUID
        name = None
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

    def _say(self, text):
        self.msg_label.setText(text)
        self.main_win.statusBar().showMessage(text, 5000)

    # ------------------------------------------------------------------

    def _on_done(self):
        win = self.main_win
        self._refresh_part_label()
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

        sign = 1.0 if self.dir_combo.currentText() == "+W" else -1.0
        vec = wp.wVec * (sign * dist * win.unitscale)

        try:
            tool = None
            for f in faces:
                prism = BRepPrimAPI_MakePrism(f, vec).Shape()
                tool = prism if tool is None else \
                    BRepAlgoAPI_Fuse(tool, prism).Shape()
            removing = (self.op_combo.currentIndex() == 0)
            if removing:
                newPart = BRepAlgoAPI_Cut(part, tool).Shape()
            else:
                newPart = BRepAlgoAPI_Fuse(part, tool).Shape()
        except Exception as be:
            self._say(f"Boolean failed: {be}")
            return

        # Each Apply = ONE undo transaction (a complete operation)
        win.erase_shape(uid)
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        win.draw_shape(uid)
        win.setActivePart(uid)
        n_prof = len(faces)
        verb = "Milled" if removing else "Pulled"
        win.statusBar().showMessage(
            f"{verb} {n_prof} profile(s), {dist:g} "
            f"{getattr(win, 'units', 'mm')} "
            f"{self.dir_combo.currentText()} (Ctrl+Z undoes).", 6000)
        self.close()


def show_mill_pull_dialog(main_win):
    """Launcher -- one dialog instance, raised if already open."""
    dlg = getattr(main_win, "_mill_pull_dlg", None)
    if dlg is not None and dlg.isVisible():
        dlg.raise_()
        dlg.activateWindow()
        return
    dlg = MillPullDialog(main_win)
    main_win._mill_pull_dlg = dlg
    dlg.show()
