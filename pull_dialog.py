"""
pull_dialog.py -- the Pull dialog, under the Create/Modify menu.
Built from Doug's own Pull_Dialog_Specification.pdf across Steps 2-3
of the integrated Create/Modify dialog plan; Session 96 completed the
plan's own "crystal ball" end state -- Create 3D and Modify Active
Part are gone, folded into one Create/Modify menu (Pull, Fillet,
Shell together), and the code Pull fully supersedes (extrude(), the
old mill()/pull(), and mill_pull_dialog.py) was removed rather than
left as orphaned, unreferenced code.

Linear mode reuses the old, now-removed mill_pull_dialog.py's own,
already-proven Add/Remove Material + tool-building logic exactly,
plus one real addition: createEmptyPart() means parts routinely start
genuinely empty now, so Add Material on an empty part skips the
degenerate boolean entirely and uses the tool's own shape directly --
the same, already-verified fix from the Session 90/91 empty-part
investigation, carried into the dialog meant to be its permanent home
rather than re-proven from scratch.

Angular mode's axis-picking ("Select Axis") picks two points -- tail,
then head -- reusing position_dialog.py's own proven "2 Points"
pattern exactly (engine-path-first: a workplane catch becomes a world
point; a genuine 3D vertex is the fallback). The second point gives
the user explicit control over which way a positive angle rotates
(the right-hand rule), rather than an implicit sign derived from a
single picked line -- an earlier, single-cline-pick design was tried
and replaced after Doug's own live testing found exactly this
ambiguity. Hover feedback on both picks reuses mainwindow's own
_preview_start_meas/_pick_marker mechanism directly (already used by
radMeasC/angMeasC for the same purpose) -- confirmed mainwindow-
native, not a2d-toolset-only, so no reimplementation was needed for
this part at all. Direction (+W/-W) is deliberately absent from
Angular's own page entirely -- Doug's own live test (a 180-degree
pull swept into the -W half-plane with Direction still set to +W)
proved it inert once the axis has an explicit, user-picked direction:
the right-hand rule already fully determines rotation, with no second,
independent choice left to make the way there is for Linear.

Layout follows the spec's own 4-section structure:
    Top:           Active Part / Active Workplane (bold, read-only)
    Upper Middle:  "Method" -- Operation / Mode
    Lower Middle:  unlabeled, swaps with Mode -- Linear: Direction,
                   then Distance. Angular: Angle + Select Axis, no
                   Direction control at all.
    Bottom:        one '\u2705 Done' button only -- no Reverse/Back,
                   no Keep WP/Keep Prof (Doug: shortcuts, not needed
                   yet)
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QComboBox, QLineEdit,
                               QPushButton, QRadioButton, QButtonGroup,
                               QStackedWidget, QWidget)
from PySide6.QtGui import QFont

import math

from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.gp import gp_Ax1, gp_Dir, gp_Vec

import docmodel
# dm is created in mainwindow (module-global there); importing it at
# module level here would be circular-adjacent -- fetch lazily, same
# precedent as the old, now-removed mill_pull_dialog.py.
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

        # Direction lives on the Linear page only, in the Lower
        # Middle section below -- NOT here. Doug's own live test:
        # once the axis has an explicit, user-picked direction (tail
        # -> head), the right-hand rule already fully determines
        # which way a positive angle rotates. There's no second,
        # independent "+W/-W" choice left to make the way there is
        # for Linear, where the same axis vector can push material
        # two genuinely different ways. Confirmed directly -- a
        # 180-degree pull swept into the -W half-plane with Direction
        # still set to +W, proving it was inert for Angular, not
        # merely redundant. Matches Creo's own reference screenshot:
        # its Angular configuration shows no Direction row at all.
        self.dir_combo = QComboBox()
        self.dir_combo.addItems(["+W", "-W"])
        self._dir_touched = False
        self.dir_combo.activated.connect(self._mark_dir_touched)
        self.op_combo.currentIndexChanged.connect(self._op_changed)

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

        # Page 0: Linear -- Direction, then Distance
        linear_page = QWidget()
        linear_lay = QVBoxLayout(linear_page)
        linear_lay.setContentsMargins(0, 0, 0, 0)
        row_dir = QHBoxLayout()
        row_dir.addWidget(QLabel("Direction:"))
        row_dir.addWidget(self.dir_combo)
        linear_lay.addLayout(row_dir)
        dist_row = QHBoxLayout()
        self.dist_units_label = QLabel(
            f"Distance ({getattr(main_win, 'units', 'mm')}):")
        dist_row.addWidget(self.dist_units_label)
        self.dist_edit = QLineEdit()
        self.dist_edit.setPlaceholderText("e.g. 12.0")
        self.dist_edit.textChanged.connect(self._dist_changed)
        dist_row.addWidget(self.dist_edit)
        linear_lay.addLayout(dist_row)
        self.mode_stack.addWidget(linear_page)

        # Page 1: Angular -- real (Step 3). No Direction control here
        # at all -- see the note above self.dir_combo's construction.
        angular_page = QWidget()
        angular_lay = QVBoxLayout(angular_page)
        angular_lay.setContentsMargins(0, 0, 0, 0)
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("Angle (Degrees):"))
        self.angle_edit = QLineEdit()
        self.angle_edit.setPlaceholderText("e.g. 90")
        angle_row.addWidget(self.angle_edit)
        angular_lay.addLayout(angle_row)
        self.select_axis_btn = QPushButton("Select Axis")
        self.select_axis_btn.clicked.connect(self._start_axis_pick)
        angular_lay.addWidget(self.select_axis_btn)
        self.axis_status_label = QLabel("No axis selected.")
        angular_lay.addWidget(self.axis_status_label)
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

        self._picked_axis = None  # gp_Ax1, set once both points picked
        self._axis_pt1 = None  # gp_Pnt, set after the first pick
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
                "Enter an angle, then click Select Axis.", 5000)

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
    # Angular axis picking (Step 3) -- two points, tail then head
    # ------------------------------------------------------------------
    #
    # Redesigned from an initial single-cline-pick version (Doug,
    # after live testing): picking one existing construction line
    # gave no way to apply the right-hand rule in advance -- the
    # axis's own direction sign came from the line's coefficients,
    # arbitrary from the user's own point of view. Two points, with
    # the second toward the intended "head", gives the user explicit,
    # predictable control over which way a positive angle rotates --
    # the same "two points define an axis" formula the old, unrelated
    # revolveC() already used: gp_Ax1(p1, gp_Dir(gp_Vec(p1, p2))).
    #
    # Point-picking itself reuses position_dialog.py's own proven
    # "2 Points" pattern exactly (_point_pick_callback): engine path
    # first (a workplane catch -- endpoint, intersection, Ctrl+Shift
    # center -- becomes a world point via uv_to_world), a genuine 3D
    # vertex pick as fallback. Hover feedback (Doug's own follow-up
    # request) reuses mainwindow's own _preview_start_meas/_pick_
    # marker mechanism directly -- confirmed mainwindow-native, not
    # a2d-toolset-only (radMeasC/angMeasC already use it the same
    # way), so no reimplementation needed here at all.

    def _start_axis_pick(self):
        wp = self.main_win.activeWp
        if wp is None:
            self._say("No active workplane.")
            return
        self._axis_pt1 = None
        self.main_win.registerCallback(self._axis_pick_callback)
        self.main_win._preview_start_meas(
            self._axis_pick_callback, self._axis_marker_builder,
            style="geom")
        self.main_win.statusBar().showMessage(
            "Pick point 1 -- the axis's tail (need not be on "
            "the part).")

    def _axis_pick_callback(self, shapeList, *args):
        """Same engine-path-first, 3D-vertex-fallback logic as
        position_dialog.py's own _point_pick_callback -- a workplane
        catch (endpoint, intersection, Ctrl+Shift center/midpoint)
        or a genuine 3D vertex, used interchangeably as either point.
        """
        from OCP.BRep import BRep_Tool
        from OCP.TopoDS import TopoDS
        win = self.main_win
        wp = win.activeWp
        if wp is None:
            self._say("No active workplane.")
            win.clearCallback()
            return
        pt = None
        try:
            click_xy = args[1] if len(args) > 1 else None
            if (click_xy is not None and click_xy[0] is not None
                    and wp is not None):
                from snap_engine import (screen_to_uv, find_snap,
                                         uv_to_world, SNAP_PIXELS,
                                         current_snap_mode)
                uv = screen_to_uv(win.canvas.view, click_xy[0],
                                  click_xy[1], wp.gpPlane)
                if uv is not None:
                    tol = abs(win.canvas.view.Convert(SNAP_PIXELS))
                    snap = find_snap(wp, uv, tol, current_snap_mode())
                    if snap is not None:
                        pt = uv_to_world(wp.gpPlane, snap[1][0],
                                         snap[1][1])
        except Exception as se:
            self._say(f"Pick failed: {se}")
        if pt is None:
            for shape in shapeList:
                if shape is None:
                    continue
                try:
                    vrtx = TopoDS.Vertex_s(shape)
                    pt = BRep_Tool.Pnt_s(vrtx)
                    break
                except Exception:
                    continue
        if pt is None:
            self._say("No catch or vertex there -- click a "
                      "workplane catch or a part vertex.")
            return
        if self._axis_pt1 is None:
            self._axis_pt1 = pt
            self.axis_status_label.setText(
                "Point 1 picked -- pick point 2 (the axis's head).")
            self._say("Point 1 picked. Pick point 2 (the axis's "
                      "head).")
        else:
            self._picked_axis = gp_Ax1(
                self._axis_pt1, gp_Dir(gp_Vec(self._axis_pt1, pt)))
            win.clearCallback()
            win._preview_stop_meas()
            self.axis_status_label.setText("Axis selected.")
            self._say("Axis selected -- click Done.")

    def _axis_marker_builder(self, wp, uv):
        """Hover-feedback builder for _preview_start_meas -- a marker
        at the nearest snap catch, same structure as mainwindow's own
        _marker_straight_meas/_marker_circle_meas (radMeasC/angMeasC's
        own hover feedback), just for a POINT catch instead of a line
        or circle.
        """
        try:
            from snap_engine import find_snap, current_snap_mode, \
                SNAP_PIXELS
            tol = abs(self.main_win.canvas.view.Convert(SNAP_PIXELS))
            snap = find_snap(wp, uv, tol, current_snap_mode())
        except Exception:
            return None
        if snap is None:
            return None
        mk = self.main_win._pick_marker(wp, snap[1])
        return (mk, "geom") if mk is not None else None

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

        adding = (self.op_combo.currentText() == "Add Material")
        angular = self.angular_radio.isChecked()

        faces, err = wp.make_faces()
        if err is not None:
            self._say(f"Profile problem: {err}")
            return

        if angular:
            if self._picked_axis is None:
                self._say("Select an axis first (click Select Axis).")
                return
            try:
                angle_deg = float(self.angle_edit.text())
            except ValueError:
                self._say("Enter a numeric angle.")
                return
            if angle_deg <= 0.0:
                self._say("Angle must be positive -- pick the axis "
                          "points in the other order for the "
                          "opposite rotation.")
                return
            # No Direction/sign here -- see the note where
            # self.dir_combo is built. The picked axis's own
            # direction (tail -> head) already fully determines
            # rotation via the right-hand rule.
            angle_rad = math.radians(angle_deg)
            summary = f"{angle_deg:g} degrees"
        else:
            sign = 1.0 if self.dir_combo.currentText() == "+W" else -1.0
            try:
                dist = float(self.dist_edit.text())
            except ValueError:
                self._say("Enter a numeric distance.")
                return
            if dist <= 0.0:
                self._say("Distance must be positive (choose -W for "
                          "the other direction).")
                return
            vec = wp.wVec * (sign * dist * win.unitscale)
            summary = (f"{dist:g} {getattr(win, 'units', 'mm')} "
                      f"{self.dir_combo.currentText()}")

        try:
            tool = None
            for f in faces:
                if angular:
                    piece = BRepPrimAPI_MakeRevol(
                        f, self._picked_axis, angle_rad).Shape()
                else:
                    piece = BRepPrimAPI_MakePrism(f, vec).Shape()
                tool = piece if tool is None else \
                    BRepAlgoAPI_Fuse(tool, piece).Shape()

            # Session 90/91's own, verified fix: createEmptyPart()
            # means a part routinely starts genuinely empty (zero
            # faces) -- a boolean against a degenerate, empty solid
            # silently produced the wrong shape type (Compound
            # instead of Solid) rather than failing outright. Check
            # emptiness BEFORE reaching for the boolean, same as the
            # verified-working test utility this dialog is the real,
            # permanent replacement for. Shared between Linear and
            # Angular -- only how 'tool' itself gets built differs.
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
            f"{verb} material, {n_prof} profile(s), {summary} "
            f"(Ctrl+Z undoes).", 6000)
        # Reset axis state -- a stale axis (or a mid-pick point 1)
        # from a prior Angular operation shouldn't silently carry
        # into the next one.
        self._picked_axis = None
        self._axis_pt1 = None
        self.axis_status_label.setText("No axis selected.")
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
