"""
face_color_dialog.py -- DISPLAY-ONLY per-face coloring (Session 145).
Session 179: faces may be picked on ANY displayed part (not just the
active one) and the dialog never changes the active part.

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
        self.faces = {}   # uid -> [picked TopoDS_Face, ...]
        self._face_cache = {}  # uid -> (display shape, its faces); a
        # box-select calls _on_pick once per face, so listing every
        # part's faces each time would be slow on a big model
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
        rows.addWidget(dialog_style.row_label("Parts"), 0, 0)
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
        self.clear_btn.setToolTip("Remove ALL face colors from every part")
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

    def _set_info(self, paths):
        plist = "".join("<li>%s (%d face%s)</li>" % (
            p, n, "" if n == 1 else "s") for p, n in paths)
        self._info.set_html(
            "<h3>Color Faces</h3>"
            "<p>Click faces in the viewport to pick them -- on ANY "
            "displayed part, not only the active one (nothing here "
            "changes which part is active). Choose a <b>Color</b>, then "
            "press the check mark to apply. The dialog stays open so you "
            "can color more faces.</p>"
            "<p><b>Display only:</b> these colors are not stored in the "
            "document, not saved to STEP, and vanish when a part's "
            "shape changes or it is redrawn from a modified shape.</p>"
            "<p><b>Parts</b> with picked faces:</p>%s"
            "<p>Clear Picks drops the current picks; Clear Colors removes "
            "every face color from every part.</p>"
            % (("<ul>%s</ul>" % plist) if plist else "<p>(none yet)</p>"))

    def _after_history(self):
        # Undo/Redo redraws parts and ends face picking: re-arm it
        # (unless another tool took over) and drop stale picks.
        cb = self.win.registeredCallback
        if cb is None or cb == self._on_pick:
            self.faces = {}
            self._refresh()
            self._start()

    def _detach_history(self):
        try:
            self.win._history_listeners.remove(self._after_history)
        except ValueError:
            pass

    def _name(self, uid):
        from mainwindow import dm
        return dm.label_dict.get(uid, {}).get('name', str(uid))

    def _swatch(self):
        self.color_btn.setStyleSheet(
            f"background-color: {self.color.name()}; "
            f"border: 1px solid #777777; min-height: 16px;")

    def _refresh(self, extra=""):
        from mainwindow import dm
        n = sum(len(f) for f in self.faces.values())
        uids = list(self.faces)
        if len(uids) == 1:
            ptxt = self._name(uids[0])
        elif uids:
            ptxt = f"{len(uids)} parts"
        else:
            ptxt = ""
        self.part_edit.setText(ptxt)
        self.part_edit.setToolTip("\n".join(
            dm.get_full_path_name(u) for u in uids))
        self.faces_edit.setText(f"{n} selected" if n else "")
        dialog_style.set_awaiting(self.faces_edit, n == 0)
        self.ok_btn.setEnabled(n > 0)
        self.status.setText(extra if extra else
                            ("" if n else "Click faces in the viewport."))
        self._set_info([(dm.get_full_path_name(u), len(self.faces[u]))
                        for u in uids])

    def _start(self):
        self.win.registerCallback(self._on_pick)
        self.win.canvas._display.SetSelectionModeFace()

    def _owner_uid(self, face, ais_obj, ref_cache):
        """Which displayed part does a picked face belong to? A single
        click reports the AIS object it hit (exact, and correct for
        shared instances); a box-select reports none, so then every
        shown part is searched. A part's faces are listed once per
        pick or box (ref_cache is kept on the dialog)."""
        from OCCUtils import Topology
        win = self.win

        def faces_of(uid):
            cached = win._display_prep_cache.get(uid)
            if cached is None:
                return []
            hit = ref_cache.get(uid)
            if hit is None or not hit[0].IsSame(cached[1]):
                hit = (cached[1], list(Topology.Topo(cached[1]).faces()))
                ref_cache[uid] = hit   # re-listed only if the shape changed
            return hit[1]

        uid = win._uid_for_ais(ais_obj) if ais_obj is not None else None
        if uid is not None and any(face.IsSame(f) for f in faces_of(uid)):
            return uid
        hidden = set(win.hide_list)
        for u in list(win.ais_shape_dict):
            if u in hidden or u == uid:
                continue
            if any(face.IsSame(f) for f in faces_of(u)):
                return u
        return None

    def _on_pick(self, shapeList, *args):
        if not shapeList:
            return
        ais_obj = args[0] if args else None
        cache = self._face_cache
        for shape in shapeList:
            try:
                face = TopoDS.Face_s(shape)
            except Exception:
                self._refresh("Pick a face (not an edge or vertex).")
                return
            uid = self._owner_uid(face, ais_obj, cache)
            if uid is None:
                self._refresh("That face is not on a displayed part.")
                return
            mine = self.faces.setdefault(uid, [])
            if not any(face.IsSame(f) for f in mine):
                mine.append(face)
        self._refresh()

    def _choose(self):
        c = QColorDialog.getColor(self.color, self, "Face Color")
        if c.isValid():
            self.color = c
            self._swatch()

    def _apply(self):
        if not self.faces:
            self._refresh("Pick at least one face first.")
            return
        rgb = (self.color.redF(), self.color.greenF(), self.color.blueF())
        failed = 0
        # one redraw per part (a big part takes about a second)
        for uid, faces in list(self.faces.items()):
            if not self.win.set_face_colors(uid, faces, rgb):
                failed += 1
        self.faces = {}
        self._refresh("Colored." if not failed else
                      f"{failed} part(s) are not displayed.")
        self._start()

    def _clear_sel(self):
        self.faces = {}
        self._refresh()

    def _clear_colors(self):
        for uid in list(self.win.face_colors):
            self.win.clear_face_colors(uid)
        self.faces = {}
        self._refresh("All face colors cleared.")
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
