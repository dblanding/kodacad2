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
  Angular Frame row as above; Axis picks one of the frame's axes (the
          rotation axis passes through the frame's ORIGIN: World = the
          world origin); Angle is the step between neighbouring items,
          right-hand rule about the axis; 'Full circle' sets the step
          to 360 / Number (6 items -> 60 degrees).

The check mark creates the array as ONE undo step and closes the dialog;
the cross closes it. New items go under the same parent as the source
(docmodel.create_array).

Preview (Doug: the axis was invisible, so the sign of the angle was a
guess): while the dialog is open the viewport shows
  * a non-interactive RGB triad at the frame's origin, like the Position
    gizmo's axes (X / U red, Y / V green, Z / W blue); the chosen axis is
    longer and heavier, every tip is that axis' + end (a positive angle
    turns counter-clockwise seen from the tip), and
  * the items to be created as translucent cyan GHOSTS (the same look as
    Move Face's ghost), refreshed on every change. Ghosts are the source's
    shapes moved with TopoDS_Shape.Moved (a location only: no geometry is
    copied), never pickable, and removed when the dialog closes.
"""

import math

from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location
from PySide6.QtCore import QLocale
from PySide6.QtGui import QDoubleValidator, QFont, QIntValidator
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QGridLayout,
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
        self._ghost = None          # AIS of the ghost items
        self._axis_list = []        # AIS of the three triad arrows
        self._preview_note = ""
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
        self.linear_rb.clicked.connect(self._on_type_changed)
        self.angular_rb.clicked.connect(self._on_type_changed)
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

        # the axis source, common to both types
        lay.addLayout(self._fc.row_layout())
        self._frame_name_label = QLabel("")
        bold = QFont()
        bold.setBold(True)
        self._frame_name_label.setFont(bold)
        self._frame_name_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                             QSizePolicy.Policy.Preferred)
        lay.addWidget(self._frame_name_label)

        # one page per type
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_linear_page())
        self._stack.addWidget(self._build_angular_page())
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
        g.addWidget(dialog_style.row_label("Direction"), 0, 0)
        drow = QHBoxLayout()
        self._dir_group = QButtonGroup(self)
        self._dir_rbs = []
        for i in range(3):
            rb = QRadioButton("XYZ"[i])
            self._dir_group.addButton(rb, i)
            drow.addWidget(rb)
            self._dir_rbs.append(rb)
        self._dir_rbs[0].setChecked(True)
        self._dir_group.idClicked.connect(self._on_axis_clicked)
        drow.addStretch(1)
        g.addLayout(drow, 0, 1, 1, 2)

        g.addWidget(dialog_style.row_label("Offset"), 1, 0)
        self.offset_edit = QLineEdit()
        dv = QDoubleValidator(-1.0e6, 1.0e6, 4, self.offset_edit)
        dv.setNotation(QDoubleValidator.Notation.StandardNotation)
        dv.setLocale(QLocale.c())          # '.' as the decimal point
        self.offset_edit.setValidator(dv)
        self.offset_edit.setToolTip("Spacing between items along the "
                                    "direction; negative runs the other "
                                    "way.")
        self.offset_edit.textChanged.connect(self._edited)
        g.addWidget(self.offset_edit, 1, 1)
        self.units_label = QLabel(self.main_win.units)
        g.addWidget(self.units_label, 1, 2)
        g.setColumnStretch(1, 1)
        # the RPN calculator can fill the offset (click the field first)
        dialog_style.accept_calc_value(self.main_win, self.offset_edit)
        return page

    def _build_angular_page(self):
        page = QWidget()
        g = QGridLayout(page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(4)
        g.setVerticalSpacing(4)
        g.addWidget(dialog_style.row_label("Axis"), 0, 0)
        arow = QHBoxLayout()
        self._axis_group = QButtonGroup(self)
        self._axis_rbs = []
        for i in range(3):
            rb = QRadioButton("XYZ"[i])
            self._axis_group.addButton(rb, i)
            arow.addWidget(rb)
            self._axis_rbs.append(rb)
        self._axis_rbs[2].setChecked(True)     # Z / W: the usual axis
        self._axis_group.idClicked.connect(self._on_axis_clicked)
        arow.addStretch(1)
        g.addLayout(arow, 0, 1, 1, 2)

        g.addWidget(dialog_style.row_label("Angle"), 1, 0)
        self.angle_edit = QLineEdit()
        av = QDoubleValidator(-3600.0, 3600.0, 4, self.angle_edit)
        av.setNotation(QDoubleValidator.Notation.StandardNotation)
        av.setLocale(QLocale.c())              # '.' as the decimal point
        self.angle_edit.setValidator(av)
        self.angle_edit.setToolTip("Step between neighbouring items, in "
                                   "degrees (right-hand rule about the "
                                   "axis: positive turns counter-"
                                   "clockwise seen from the tip of the "
                                   "chosen (heavier) arrow; negative turns the "
                                   "other way).")
        self.angle_edit.textChanged.connect(self._edited)
        g.addWidget(self.angle_edit, 1, 1)
        g.addWidget(QLabel("\u00b0"), 1, 2)
        dialog_style.accept_calc_value(self.main_win, self.angle_edit)

        self.full_cb = QCheckBox("Full circle")
        self.full_cb.setToolTip("Space the items evenly round a full "
                                "circle: the step is 360 / Number (6 "
                                "items -> 60\u00b0).")
        self.full_cb.clicked.connect(self._on_full_toggled)
        g.addWidget(self.full_cb, 2, 1, 1, 2)
        g.setColumnStretch(1, 1)
        return page

    def _on_axis_clicked(self, _id=0):
        self._update_status()

    def _on_type_changed(self, _checked=False):
        self._stack.setCurrentIndex(
            _PAGE_ANGULAR if self.angular_rb.isChecked() else _PAGE_LINEAR)
        self._update_status()

    def _on_full_toggled(self, _checked=False):
        self._sync_full()
        self._update_status()

    def _sync_full(self):
        """'Full circle' ticked: the Angle field shows 360 / Number and
        cannot be edited (it follows Number)."""
        on = self.full_cb.isChecked()
        self.angle_edit.setEnabled(not on)
        if on and self._number() >= 2:
            txt = f"{array_math.full_circle_angle(self._number()):.4f}"
            txt = txt.rstrip("0").rstrip(".")
            if self.angle_edit.text() != txt:
                self.angle_edit.setText(txt)

    def _frame_changed(self):
        """FrameChooser hook: relabel Direction (X Y Z for World, U V W
        for a workplane / picked frame) and show where the frame came
        from."""
        names = "XYZ" if self._fc.frame is None else "UVW"
        for rb, n in zip(self._dir_rbs + self._axis_rbs, names * 2):
            rb.setText(n)
        self._frame_name_label.setText(
            "" if self._fc.frame is None else self._fc.name)
        self._refresh_preview()

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

    def _angle(self):
        try:
            return float(self.angle_edit.text())
        except ValueError:
            return 0.0

    def _update_status(self, extra=""):
        angular = self.angular_rb.isChecked()
        self._sync_full()
        self._refresh_preview()          # also sets self._preview_note
        n_ok = self._number() >= 2
        off_ok = abs(self._offset()) > 1.0e-9
        ang_ok = abs(self._angle()) > 1.0e-9
        dialog_style.set_awaiting(self.number_edit, not n_ok)
        dialog_style.set_awaiting(self.offset_edit,
                                  not angular and not off_ok)
        dialog_style.set_awaiting(self.angle_edit,
                                  angular and not ang_ok)
        self.ok_btn.setEnabled(n_ok and (ang_ok if angular else off_ok))
        if extra:
            self.status_label.setText(extra)
        elif not n_ok:
            self.status_label.setText("Number must be 2 or more "
                                      "(the original counts).")
        elif angular and not ang_ok:
            self.status_label.setText("Enter the angle.")
        elif not angular and not off_ok:
            self.status_label.setText("Enter the offset.")
        elif self._preview_note:
            self.status_label.setText(self._preview_note)
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
            "edge or a flat face (its axis is W).</p>"
            "<p><b>Linear</b>: <b>Direction</b> picks one of the "
            "frame's axes; <b>Offset</b> is the spacing between items "
            "(negative runs the other way).</p>"
            "<p><b>Angular</b>: <b>Axis</b> picks one of the frame's "
            "axes; the items turn about it THROUGH THE FRAME'S ORIGIN "
            "(World: the world origin; Pick: a point on the picked "
            "axis, so picking a hub's cylinder spins the items about "
            "the hub). <b>Angle</b> is the step between neighbours "
            "(right-hand rule); <b>Full circle</b> makes it 360 / "
            "Number, so Number 6 gives 60\u00b0.</p>"
            "<p>The calculator can fill Offset and Angle -- click the "
            "field first.</p>"
            "<p><b>Preview</b>: the red / green / blue triad shows the "
            "frame's axes (X / U red, Y / V green, Z / W blue, like the "
            "Position gizmo); the chosen one is longer and heavier. Each "
            "arrow points to its + end, and a positive Angle turns "
            "counter-clockwise seen from the tip. The "
            "translucent cyan ghosts are the items that the check mark "
            "will create (the first %d at most).</p>"
            "<p><b>Source</b>:<br>%s</p>" % (self.PREVIEW_MAX, full))
        self._info.toggle(self.main_win)

    # -- the items, as world-space location deltas ---------------------
    def _chosen_axis(self):
        """(origin, axis) in world xyz: the frame's origin and the
        direction (Linear) / rotation axis (Angular) picked on the
        visible page."""
        origin, u, v, w = self._fc.triad()
        grp = self._axis_group if self.angular_rb.isChecked() \
            else self._dir_group
        return origin, (u, v, w)[max(grp.checkedId(), 0)]

    def _build_moves(self):
        """The world-space TopLoc_Location delta of each NEW item (items
        1 .. n-1). Raises ValueError for a bad Number / zero offset."""
        n = self._number()
        origin, axis = self._chosen_axis()
        moves = []
        step = self._angle() if self.angular_rb.isChecked() \
            else self._offset()
        if n < 2 or abs(step) <= 1.0e-9:
            raise ValueError("Enter Number (2 or more) and a non-zero "
                             "offset / angle.")
        if self.angular_rb.isChecked():
            ax1 = gp_Ax1(gp_Pnt(*origin), gp_Dir(*axis))
            for a in array_math.angular_angles(n, self._angle()):
                t = gp_Trsf()
                t.SetRotation(ax1, math.radians(a))
                moves.append(TopLoc_Location(t))
        else:
            for (x, y, z) in array_math.linear_offsets(
                    n, self._offset() * self.main_win.unitscale, axis):
                t = gp_Trsf()
                t.SetTranslation(gp_Vec(x, y, z))
                moves.append(TopLoc_Location(t))
        return moves

    # -- preview: axis arrow + ghost items ---------------------------
    PREVIEW_MAX = 60                  # ghosts drawn at most

    def _source_shapes(self):
        """The source's displayed (world-placed) shapes: its own leaf
        parts, or those of every part under an assembly."""
        pd = self.dm.part_dict
        return [pd[u]['shape'] for u in self.dm.get_descendant_part_uids(
            self.uid) if u in pd and pd[u].get('shape') is not None]

    def _refresh_preview(self):
        """Redraw the axis arrow and the ghosts for the current inputs.
        Never raises: a preview problem must not break the dialog."""
        try:
            self._erase_preview(update=False)
            if not self.isVisible():
                # (called from __init__ before show(): draw nothing yet;
                # show_array_dialog refreshes after show)
                return
            shapes = self._source_shapes()
            if not shapes:
                return
            self._preview_note = ""
            self._draw_axis(shapes)
            try:
                moves = self._build_moves()
            except ValueError:
                moves = []
            if len(moves) > self.PREVIEW_MAX:
                moves = moves[:self.PREVIEW_MAX]
                self._preview_note = (f"Preview shows the first "
                                      f"{self.PREVIEW_MAX} items.")
            if moves:
                self._draw_ghosts(shapes, moves)
            self.main_win.canvas._display.Context.UpdateCurrentViewer()
        except Exception as e:
            print(f"[array] preview failed: {type(e).__name__}: {e}")

    def _draw_ghosts(self, shapes, moves):
        from OCP.AIS import AIS_Shape
        from OCP.BRep import BRep_Builder
        from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
        from OCP.TopoDS import TopoDS_Compound
        bld = BRep_Builder()
        comp = TopoDS_Compound()
        bld.MakeCompound(comp)
        for mv in moves:
            for sh in shapes:
                bld.Add(comp, sh.Moved(mv))      # a location only
        disp = self.main_win.canvas._display
        ctx = disp.Context
        ais = AIS_Shape(comp)
        ctx.Display(ais, False)
        disp.add_never_pick(ais)                 # clicks pass through
        ctx.SetColor(ais, Quantity_Color(
            0.05, 0.75, 0.95, Quantity_TypeOfColor.Quantity_TOC_RGB), False)
        ctx.SetTransparency(ais, 0.6, False)
        self._ghost = ais

    # the gizmo's colours: X / U red, Y / V green, Z / W blue
    TRIAD_RGB = ((0.90, 0.10, 0.10), (0.10, 0.70, 0.10),
                 (0.15, 0.30, 0.95))

    def _draw_axis(self, shapes):
        """A non-interactive RGB triad at the frame's origin, like the
        Position gizmo's axes: three arrows (X / U red, Y / V green,
        Z / W blue). The CHOSEN axis (Direction / Axis radio) is longer
        and heavier; every arrow's tip is its + end."""
        from OCP.AIS import AIS_Shape
        from OCP.Bnd import Bnd_Box
        from OCP.BRep import BRep_Builder
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone
        from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost
        from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
        from OCP.TopoDS import TopoDS_Compound
        from OCP.gp import gp_Ax2
        box = Bnd_Box()
        for sh in shapes:
            BRepBndLib.Add_s(sh, box)
        if box.IsVoid():
            return
        x0, y0, z0, x1, y1, z1 = box.Get()
        diag = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2)
        base_len = max(0.6 * diag, 8.0)
        origin, u, v, w = self._fc.triad()
        _o, chosen = self._chosen_axis()
        disp = self.main_win.canvas._display
        ctx = disp.Context
        for ax, rgb in zip((u, v, w), self.TRIAD_RGB):
            is_chosen = all(abs(ax[i] - chosen[i]) < 1.0e-9
                            for i in range(3))
            length = base_len * (1.4 if is_chosen else 1.0)
            head = 0.14 * length
            base = gp_Pnt(*(origin[i] + (length - head) * ax[i]
                            for i in range(3)))
            bld = BRep_Builder()
            comp = TopoDS_Compound()
            bld.MakeCompound(comp)
            bld.Add(comp, BRepBuilderAPI_MakeEdge(
                gp_Pnt(*origin), base).Edge())
            bld.Add(comp, BRepPrimAPI_MakeCone(
                gp_Ax2(base, gp_Dir(*ax)), (0.4 if is_chosen else 0.3)
                * head, 0.0, head).Shape())
            ais = AIS_Shape(comp)
            ctx.Display(ais, False)
            disp.add_never_pick(ais)
            ctx.SetColor(ais, Quantity_Color(
                *rgb, Quantity_TypeOfColor.Quantity_TOC_RGB), False)
            ctx.SetWidth(ais, 5.0 if is_chosen else 2.0, False)
            ctx.SetZLayer(ais, Graphic3d_ZLayerId_Topmost)
            self._axis_list.append(ais)

    def _erase_preview(self, update=True):
        disp = None
        try:
            disp = self.main_win.canvas._display
        except Exception:
            return
        olds = [self._ghost] + list(self._axis_list)
        self._ghost = None
        self._axis_list = []
        gone = False
        for ais in olds:
            if ais is None:
                continue
            gone = True
            try:
                disp.remove_never_pick(ais)
                disp.Context.Remove(ais, False)
            except Exception as e:
                print(f"[array] preview erase failed: {e}")
        if gone and update:
            try:
                disp.Context.UpdateCurrentViewer()
            except Exception:
                pass

    # -- apply -------------------------------------------------------
    def _on_apply(self):
        dm = self.dm
        if self.uid not in dm.label_dict:
            self._update_status("The source is no longer available -- "
                                "close and reopen the dialog.")
            return
        n = self._number()
        angular = self.angular_rb.isChecked()
        dist = self._offset()
        angle = self._angle()
        if n < 2 or abs(angle if angular else dist) <= 1.0e-9:
            self._update_status()
            return
        share = self.share_rb.isChecked()
        try:
            moves = self._build_moves()
        except ValueError as e:
            self._update_status(str(e))
            return

        self._erase_preview()
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
        self._erase_preview()
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
    dlg._refresh_preview()            # now visible: draw the first preview
