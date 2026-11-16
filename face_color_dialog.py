"""
face_color_dialog.py -- DISPLAY-ONLY per-face coloring (Session 145).

For preparing tutorial illustrations (e.g. highlighting the faces a
Defeaturing step will remove). Colors live only in the session's
display (MainWindow.face_colors); they are NOT stored in the document,
NOT saved to STEP, and vanish when the part's shape changes or it is
redrawn from a modified shape. Non-modal, face-pick pattern modeled on
DefeaturingDialog.
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QColorDialog, QGridLayout,
                               QLineEdit)
from PySide6.QtGui import QColor

from OCP.TopoDS import TopoDS
from OCCUtils import Topology

import dialog_style


class FaceColorDialog(QDialog):
    """Minimalist layout (Session 179, the Creo E/D model): Part (the
    active part), Faces (yellow until some are picked) and Color rows;
    the check mark APPLIES the color and leaves the dialog open so more
    faces can be colored (the old Apply/Done flow); the cross closes it.
    The explanatory text is in the '?' info window."""

    def __init__(self, main_win):
        super().__init__(main_win)
        self.win = main_win
        self.setWindowTitle("Color Faces")
        self.setModal(False)
        self.faces = []
        self.color = QColor(255, 0, 0)
        self._info = dialog_style.InfoWindow(main_win, "Color Faces details")

        lay = QVBoxLayout(self)
        bar, self.ok_btn, self.cancel_btn, self.help_btn = \
            dialog_style.icon_bar(self._apply, self._done,
                                  self._toggle_info)
        self.ok_btn.setToolTip("Apply the color to the picked faces "
                               "(the dialog stays open)")
        self.cancel_btn.setToolTip("Close")
        lay.addLayout(bar)

        rows = QGridLayout()
        rows.addWidget(dialog_style.row_label("Part"), 0, 0)
        self.part_edit = QLineEdit()
        self.part_edit.setReadOnly(True)
        rows.addWidget(self.part_edit, 0, 1)
        rows.addWidget(dialog_style.row_label("Faces"), 1, 0)
        self.faces_edit = QLineEdit()
        self.faces_edit.setReadOnly(True)
        rows.addWidget(self.faces_edit, 1, 1)
        rows.addWidget(dialog_style.row_label("Color"), 2, 0)
        self.color_btn = QPushButton("")
        self.color_btn.setToolTip("Choose the color...")
        self.color_btn.clicked.connect(self._choose)
        rows.addWidget(self.color_btn, 2, 1)
        rows.setColumnStretch(1, 1)
        lay.addLayout(rows)

        row2 = QHBoxLayout()
        self.reset_btn = QPushButton("Clear Picks")
        self.reset_btn.clicked.connect(self._clear_sel)
        row2.addWidget(self.reset_btn)
        self.clear_btn = QPushButton("Clear Colors")
        self.clear_btn.setToolTip("Remove all face colors from the part")
        self.clear_btn.clicked.connect(self._clear_colors)
        row2.addWidget(self.clear_btn)
        lay.addLayout(row2)

        self.status = QLabel("")
        self.status.setObjectName("KcStatus")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        dialog_style.apply_minimal(self)
        self.setMinimumWidth(240)
        self._swatch()
        self._refresh()
        self._start()
        self.win._history_listeners.append(self._after_history)

    def _toggle_info(self):
        self._info.toggle(self.win)

    def _set_info(self, part_path):
        self._info.set_html(
            "<h3>Color Faces</h3>"
            "<p>Click faces in the viewport to pick them (they are added "
            "to <b>Faces</b>), choose a <b>Color</b>, then press the "
            "check mark to apply. The dialog stays open so you can color "
            "more faces.</p>"
            "<p><b>Display only:</b> these colors are not stored in the "
            "document, not saved to STEP, and vanish when the part's "
            "shape changes or it is redrawn from a modified shape.</p>"
            "<p><b>Part</b> (the active part):<br>%s</p>"
            "<p>Clear Picks drops the current picks; Clear Colors removes "
            "every face color from the part.</p>" % (part_path or "(none)"))

    def _after_history(self):
        # Undo/Redo redraws parts and ends face picking: re-arm it
        # (unless another tool took over) and drop stale picks.
        cb = self.win.registeredCallback
        if cb is None or cb == self._on_pick:
            self.faces = []
            self._refresh()
            self._start()

    def _detach_history(self):
        try:
            self.win._history_listeners.remove(self._after_history)
        except ValueError:
            pass

    def _uid(self):
        return self.win.activePartUID

    def _swatch(self):
        self.color_btn.setStyleSheet(
            f"background-color: {self.color.name()}; "
            f"border: 1px solid #777777; min-height: 16px;")

    def _refresh(self, extra=""):
        uid = self._uid()
        path = ""
        if uid:
            try:
                from mainwindow import dm
                path = dm.get_full_path_name(uid)
                leaf = dm.label_dict.get(uid, {}).get('name', path)
            except Exception:
                path = leaf = str(uid)
        else:
            leaf = ""
        self.part_edit.setText(leaf)
        self.part_edit.setToolTip(path)
        n = len(self.faces)
        self.faces_edit.setText(f"{n} selected" if n else "")
        dialog_style.set_awaiting(self.faces_edit, bool(uid) and n == 0)
        self.ok_btn.setEnabled(bool(uid) and n > 0)
        self.status.setText(extra if extra else
                            ("" if n else "Click faces in the viewport."))
        self._set_info(path)

    def _start(self):
        self.win.registerCallback(self._on_pick)
        self.win.canvas._display.SetSelectionModeFace()

    def _on_pick(self, shapeList, *args):
        if not shapeList:
            return
        uid = self._uid()
        cached = self.win._display_prep_cache.get(uid)
        if cached is None:
            self._refresh("Part is not displayed.")
            return
        ref_faces = list(Topology.Topo(cached[1]).faces())
        for shape in shapeList:
            try:
                face = TopoDS.Face_s(shape)
            except Exception:
                self._refresh("Pick a face (not an edge or vertex).")
                return
            if not any(face.IsSame(f) for f in ref_faces):
                self._refresh("Selected face must be in the active "
                              "part.")
                return
            if not any(face.IsSame(f) for f in self.faces):
                self.faces.append(face)
        self._refresh()

    def _choose(self):
        c = QColorDialog.getColor(self.color, self, "Face Color")
        if c.isValid():
            self.color = c
            self._swatch()

    def _apply(self):
        uid = self._uid()
        if not self.faces:
            self._refresh("Pick at least one face first.")
            return
        rgb = (self.color.redF(), self.color.greenF(), self.color.blueF())
        ok = self.win.set_face_colors(uid, self.faces, rgb)
        self.faces = []
        self._refresh("Colored." if ok else "Part is not displayed.")
        self._start()

    def _clear_sel(self):
        self.faces = []
        self._refresh()

    def _clear_colors(self):
        self.win.clear_face_colors(self._uid())
        self.faces = []
        self._refresh("Face colors cleared.")
        self._start()

    def _done(self):
        self.close()

    def closeEvent(self, event):
        self._detach_history()
        self.win.clearCallback()
        try:
            self._info.hide()
            self._info.deleteLater()
        except Exception:
            pass
        super().closeEvent(event)


def show_face_color_dialog(main_win):
    dlg = getattr(main_win, "_face_color_dlg", None)
    if dlg is not None and dlg.isVisible():
        dlg.raise_()
        dlg.activateWindow()
        return
    dlg = FaceColorDialog(main_win)
    main_win._face_color_dlg = dlg
    dlg.show()
    dialog_style.place_top_left(dlg, main_win)
