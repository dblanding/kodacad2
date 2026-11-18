"""array_dialog.py -- 3D arrays of parts / assemblies (Session 180).

Launched from the tree's RMB menu ('Create Array...'): the array source
is the clicked component. Minimal dialog style (dialog_style.py), laid
out like Position: Linear | Angular radios on top, a common block
(Source, Copy | Share, Number), and a stacked lower page per type.

  Number  the TOTAL, including the original (Doug): 6 angular items 60
          degrees apart = Number 6, Angle 60. Only items 1 .. n-1 are
          created; the original does not move.
  Share   more instances of ONE prototype (parts and assemblies) --
          the default; Copy = independent parts (simple parts only,
          so the Copy radio is greyed out for an assembly).
  Linear  Frame row (World | Workplane | Pick, the shared FrameChooser)
          gives the axes; Direction picks one of them (X/Y/Z, or U/V/W
          in a workplane / picked frame); Offset is the spacing between
          items (negative runs the other way; the RPN calculator can
          fill it).
  Angular (next step -- the radio is present but greyed out)

The check mark creates the array as ONE undo step and closes the dialog;
the cross closes it. New items go under the same parent as the source
(docmodel.create_array). A ghost preview of the items is planned.
"""

from OCP.gp import gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location
from PySide6.QtCore import QLocale
from PySide6.QtGui import QDoubleValidator, QFont, QIntValidator
from PySide6.QtWidgets import (QButtonGroup, QDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit,
                               QRadioButton, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

import array_math
import dialog_style
import docmodel
from frame_chooser import FrameChooser

_PAGE_LINEAR, _PAGE_ANGULAR = 0, 1


class ArrayDialog(QDialog):
    def __init__(self, main_win, dm, uid):
        super().__init__(main_win)
        self.main_win = main_win
        self.dm = dm
        self.uid = uid
        self.setWindowTitle("Create Array")
        self.setModal(False)
        self._info = dialog_style.InfoWindow(main_win, "Array details")
        # The Frame row: an axis source only -- no gizmo, so no hooks
        # except the one that relabels Direction (X Y Z / U V W).
        self._fc = FrameChooser(
            main_win, parent=self, on_changed=self._frame_changed,
            pick_hint=("Pick a cylindrical face, a circular or straight "
                       "edge, or a flat face -- its axis is a choice "
                       "for Direction."))

        info = dm.label_dict.get(uid, {})
        self._is_assy = bool(info.get('is_assy', False))

        lay = QVBoxLayout(self)
        bar, self.ok_btn, self.cancel_btn, self.help_btn = \
            dialog_style.icon_bar(self._on_apply, self.close,
                                  self._toggle_info)
        self.ok_btn.setToolTip("Create the array")
        self.cancel_btn.setToolTip("Close without creating anything")
        lay.addLayout(bar)

        # type
        trow = QHBoxLayout()
        self.linear_rb = QRadioButton("Linear")
        self.angular_rb = QRadioButton("Angular")
        self.linear_rb.setChecked(True)
        self.angular_rb.setEnabled(False)
        self.angular_rb.setToolTip("Angular arrays: the next step.")
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self.linear_rb)
        self._type_group.addButton(self.angular_rb)
        trow.addWidget(self.linear_rb)
        trow.addWidget(self.angular_rb)
        trow.addStretch(1)
        lay.addLayout(trow)

        # common block
        rows = QGridLayout()
        rows.addWidget(dialog_style.row_label("Source"), 0, 0)
        self.source_edit = QLineEdit()
        self.source_edit.setReadOnly(True)
        try:
            full = dm.get_full_path_name(uid)
        except Exception:
            full = str(uid)
        self.source_edit.setText(str(info.get('name', full)))
        self.source_edit.setToolTip(full)
        rows.addWidget(self.source_edit, 0, 1)
        cs = QHBoxLayout()
        self.copy_rb = QRadioButton("Copy")
        self.share_rb = QRadioButton("Share")
        self.share_rb.setChecked(True)
        self.share_rb.setToolTip("More instances of the SAME part / "
                                 "assembly: change the source and every "
                                 "item changes with it.")
        self.copy_rb.setToolTip("Independent copies of the part.")
        if self._is_assy:
            self.copy_rb.setEnabled(False)
            self.copy_rb.setToolTip("Copy needs a simple part -- an "
                                    "assembly can only be shared.")
        self._cs_group = QButtonGroup(self)
        self._cs_group.addButton(self.copy_rb)
        self._cs_group.addButton(self.share_rb)
        cs.addWidget(self.copy_rb)
        cs.addWidget(self.share_rb)
        cs.addStretch(1)
        rows.addLayout(cs, 1, 1)
        rows.addWidget(dialog_style.row_label("Number"), 2, 0)
        self.number_edit = QLineEdit("3")
        self.number_edit.setValidator(QIntValidator(2, 999, self.number_edit))
        self.number_edit.setToolTip("Total number of items, INCLUDING the "
                                    "original.")
        self.number_edit.textChanged.connect(self._edited)
        rows.addWidget(self.number_edit, 2, 1)
        rows.setColumnStretch(1, 1)
        lay.addLayout(rows)

        # one page per type
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_linear_page())
        lay.addWidget(self._stack)

        self.status_label = QLabel()
        self.status_label.setObjectName("KcStatus")
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                        QSizePolicy.Policy.Preferred)
        lay.addWidget(self.status_label)

        dialog_style.apply_minimal(self)
        self.setMinimumWidth(300)
        self._frame_changed()
        self._update_status()

    # -- pages -------------------------------------------------------
    def _build_linear_page(self):
        page = QWidget()
        g = QGridLayout(page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(4)
        g.setVerticalSpacing(4)
        g.addLayout(self._fc.row_layout(), 0, 0, 1, 3)

        self._frame_name_label = QLabel("")
        bold = QFont()
        bold.setBold(True)
        self._frame_name_label.setFont(bold)
        self._frame_name_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                             QSizePolicy.Policy.Preferred)
        g.addWidget(self._frame_name_label, 1, 0, 1, 3)

        g.addWidget(dialog_style.row_label("Direction"), 2, 0)
        drow = QHBoxLayout()
        self._dir_group = QButtonGroup(self)
        self._dir_rbs = []
        for i in range(3):
            rb = QRadioButton("XYZ"[i])
            self._dir_group.addButton(rb, i)
            drow.addWidget(rb)
            self._dir_rbs.append(rb)
        self._dir_rbs[0].setChecked(True)
        drow.addStretch(1)
        g.addLayout(drow, 2, 1, 1, 2)

        g.addWidget(dialog_style.row_label("Offset"), 3, 0)
        self.offset_edit = QLineEdit()
        dv = QDoubleValidator(-1.0e6, 1.0e6, 4, self.offset_edit)
        dv.setNotation(QDoubleValidator.Notation.StandardNotation)
        dv.setLocale(QLocale.c())          # '.' as the decimal point
        self.offset_edit.setValidator(dv)
        self.offset_edit.setToolTip("Spacing between items along the "
                                    "direction; negative runs the other "
                                    "way.")
        self.offset_edit.textChanged.connect(self._edited)
        g.addWidget(self.offset_edit, 3, 1)
        self.units_label = QLabel(self.main_win.units)
        g.addWidget(self.units_label, 3, 2)
        g.setColumnStretch(1, 1)
        # the RPN calculator can fill the offset (click the field first)
        dialog_style.accept_calc_value(self.main_win, self.offset_edit)
        return page

    def _frame_changed(self):
        """FrameChooser hook: relabel Direction (X Y Z for World, U V W
        for a workplane / picked frame) and show where the frame came
        from."""
        names = "XYZ" if self._fc.frame is None else "UVW"
        for rb, n in zip(self._dir_rbs, names):
            rb.setText(n)
        self._frame_name_label.setText(
            "" if self._fc.frame is None else self._fc.name)

    # -- state -------------------------------------------------------
    def _number(self):
        try:
            return int(self.number_edit.text())
        except ValueError:
            return 0

    def _offset(self):
        try:
            return float(self.offset_edit.text())
        except ValueError:
            return 0.0

    def _edited(self, _text=""):
        # textChanged passes the new text: it must not become the status
        self._update_status()

    def _update_status(self, extra=""):
        n_ok = self._number() >= 2
        off_ok = abs(self._offset()) > 1.0e-9
        dialog_style.set_awaiting(self.number_edit, not n_ok)
        dialog_style.set_awaiting(self.offset_edit, not off_ok)
        self.ok_btn.setEnabled(n_ok and off_ok)
        if extra:
            self.status_label.setText(extra)
        elif not n_ok:
            self.status_label.setText("Number must be 2 or more "
                                      "(the original counts).")
        elif not off_ok:
            self.status_label.setText("Enter the offset.")
        else:
            self.status_label.setText("")

    def _toggle_info(self):
        try:
            full = self.dm.get_full_path_name(self.uid)
        except Exception:
            full = str(self.uid)
        self._info.set_html(
            "<h3>Create Array</h3>"
            "<p>Makes a row of items from the component you "
            "right-clicked (the <b>Source</b>), all under the same "
            "parent. The result is one undo step.</p>"
            "<p><b>Number</b> is the TOTAL, including the original "
            "(which stays where it is).</p>"
            "<p><b>Share</b>: every item is another instance of the "
            "same part or assembly, so a change to the source shows in "
            "all of them. <b>Copy</b>: independent copies (simple parts "
            "only).</p>"
            "<p><b>Frame</b> gives the axes: <i>World</i> X/Y/Z; "
            "<i>Workplane</i> the active workplane's U/V/W; "
            "<i>Pick</i> a cylindrical face, a circular or straight "
            "edge or a flat face (its axis is W). <b>Direction</b> picks "
            "one of them; <b>Offset</b> is the spacing between items "
            "(negative runs the other way; the calculator can fill it "
            "-- click the field first).</p>"
            "<p>Angular arrays and a ghost preview are planned.</p>"
            "<p><b>Source</b>:<br>%s</p>" % full)
        self._info.toggle(self.main_win)

    # -- apply -------------------------------------------------------
    def _on_apply(self):
        dm = self.dm
        if self.uid not in dm.label_dict:
            self._update_status("The source is no longer available -- "
                                "close and reopen the dialog.")
            return
        n = self._number()
        dist = self._offset()
        if n < 2 or abs(dist) <= 1.0e-9:
            self._update_status()
            return
        share = self.share_rb.isChecked()
        _o, u, v, w = self._fc.triad()
        direction = (u, v, w)[max(self._dir_group.checkedId(), 0)]
        try:
            offsets = array_math.linear_offsets(
                n, dist * self.main_win.unitscale, direction)
        except ValueError as e:
            self._update_status(str(e))
            return
        moves = []
        for (x, y, z) in offsets:
            t = gp_Trsf()
            t.SetTranslation(gp_Vec(x, y, z))
            moves.append(TopLoc_Location(t))

        old_uids = set(dm.part_dict.keys())
        try:
            with docmodel.undo_transaction(dm):
                names = dm.create_array(self.uid, moves, share=share)
        except Exception as e:
            print(f"[array] failed: {e}")
            self._update_status(f"Could not create the array: {e}")
            return
        # same refresh as Create Shared Instance: only genuinely new
        # components are drawn
        self.main_win.build_tree()
        self.main_win._incremental_reconcile(old_uids)
        self.main_win.treeView.clearSelection()
        self.main_win.statusBar().showMessage(
            f"Array created: {len(names)} new item(s) "
            f"({'shared' if share else 'copied'}).", 6000)
        self.close()

    def closeEvent(self, event):
        if self._fc.picking:
            self.main_win.clearCallback()
        try:
            self._info.hide()
            self._info.deleteLater()
        except Exception:
            pass
        super().closeEvent(event)


def show_array_dialog(main_win, dm, uid):
    """Launcher -- one dialog at a time (a new request replaces it)."""
    if uid not in dm.label_dict:
        main_win.statusBar().showMessage(
            "That item cannot be arrayed.", 5000)
        return
    if not dm.label_dict[uid].get('parent_uid'):
        main_win.statusBar().showMessage(
            "The root cannot be arrayed.", 5000)
        return
    old = getattr(main_win, "_array_dlg", None)
    if old is not None and old.isVisible():
        old.close()
    dlg = ArrayDialog(main_win, dm, uid)
    main_win._array_dlg = dlg
    dlg.show()
    dialog_style.place_top_left(dlg, main_win)
