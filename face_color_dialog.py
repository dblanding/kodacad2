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
                               QPushButton, QColorDialog)
from PySide6.QtGui import QFont, QColor

from OCP.TopoDS import TopoDS
from OCCUtils import Topology


class FaceColorDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.win = main_win
        self.setWindowTitle("Color Faces (display only)")
        self.setModal(False)
        self.faces = []
        self.color = QColor(255, 0, 0)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Coloring faces of part:"))
        self.part_label = QLabel()
        f = QFont(); f.setBold(True)
        self.part_label.setFont(f)
        self.part_label.setWordWrap(True)
        lay.addWidget(self.part_label)
        lay.addWidget(QLabel("Click faces to select, choose a color, "
                             "then Apply. Display only -- not saved."))
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.color_btn = QPushButton("Choose Color...")
        self.color_btn.clicked.connect(self._choose)
        row.addWidget(self.color_btn)
        self.apply_btn = QPushButton("✅ Apply")
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.reset_btn = QPushButton("Clear Selection")
        self.reset_btn.clicked.connect(self._clear_sel)
        row2.addWidget(self.reset_btn)
        self.clear_btn = QPushButton("Clear Face Colors")
        self.clear_btn.clicked.connect(self._clear_colors)
        row2.addWidget(self.clear_btn)
        lay.addLayout(row2)
        self.done_btn = QPushButton("⏹ Done")
        self.done_btn.clicked.connect(self._done)
        lay.addWidget(self.done_btn)

        self._swatch()
        self._refresh()
        self._start()

    def _uid(self):
        return self.win.activePartUID

    def _swatch(self):
        self.color_btn.setStyleSheet(
            f"background-color: {self.color.name()};")

    def _refresh(self, extra=""):
        uid = self._uid()
        name = ""
        if uid:
            try:
                from mainwindow import dm
                name = dm.get_full_path_name(uid)
            except Exception:
                name = str(uid)
        self.part_label.setText(name)
        base = f"{len(self.faces)} face(s) selected."
        self.status.setText(f"{extra}  {base}" if extra else base)

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
        self.win.clearCallback()
        self.close()

    def closeEvent(self, event):
        self.win.clearCallback()
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
