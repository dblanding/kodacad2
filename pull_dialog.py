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

Angular mode's axis-picking ("Define Axis (2 points)") picks two
points -- tail, then head -- reusing position_dialog.py's own proven
"2 Points" pattern exactly (engine-path-first: a workplane catch
becomes a world point; a genuine 3D vertex is the fallback). The
second point gives the user explicit control over which way a
positive angle rotates (the right-hand rule), rather than an implicit
sign derived from a single picked line -- an earlier, single-cline-pick
design was tried and replaced after Doug's own live testing found
exactly this ambiguity. Hover feedback on both picks reuses
mainwindow's own _preview_start_meas/_pick_marker mechanism directly
(already used by
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
                   then Distance. Angular: Angle + Define Axis (2
                   points), no Direction control at all.
    Bottom:        one '\u2705 Done' button only -- no Reverse/Back,
                   no Keep WP/Keep Prof (Doug: shortcuts, not needed
                   yet)
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QComboBox, QLineEdit,
                               QPushButton, QRadioButton, QButtonGroup,
                               QStackedWidget, QWidget, QGridLayout)

import math

from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.gp import gp_Ax1, gp_Dir, gp_Vec, gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

import docmodel
import dialog_style
import safe_boolean
# dm is created in mainwindow (module-global there); importing it at
# module level here would be circular-adjacent -- fetch lazily, same
# precedent as the old, now-removed mill_pull_dialog.py.
from mainwindow import dm


class PullDialog(QDialog):
    """Minimalist layout (Session 179, the Creo E/D Pull dialog as the
    model; Doug: 'the workplane and profile are always kept, so no Keep
    WP / Keep Prof boxes', and the dialog closes after Done):

        check / cross / ?
        Part         (the active part, read-only)
        Workplane    (the active workplane, read-only)
        Operation    Add Material / Remove Material
        (o) Linear  ( ) Angular
        Linear:   Direction, Distance (yellow until a valid number)
        Angular:  Axis (yellow until both points are picked) + Pick,
                  Angle (yellow until a number)

    The long explanations (right-hand rule, why Angular has no
    Direction, the full part path) live in the '?' info window."""

    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.setWindowTitle("Pull")
        self.setModal(False)
        self._info = dialog_style.InfoWindow(main_win, "Pull details")

        lay = QVBoxLayout(self)
        bar, self.ok_btn, self.cancel_btn, self.help_btn = \
            dialog_style.icon_bar(self._on_done, self.close,
                                  self._toggle_info)
        lay.addLayout(bar)

        rows = QGridLayout()
        rows.addWidget(dialog_style.row_label("Part"), 0, 0)
        self.part_edit = QLineEdit()
        self.part_edit.setReadOnly(True)
        rows.addWidget(self.part_edit, 0, 1)
        rows.addWidget(dialog_style.row_label("Workplane"), 1, 0)
        self.wp_edit = QLineEdit()
        self.wp_edit.setReadOnly(True)
        rows.addWidget(self.wp_edit, 1, 1)
        rows.addWidget(dialog_style.row_label("Operation"), 2, 0)
        self.op_combo = QComboBox()
        self.op_combo.addItems(["Add Material", "Remove Material"])
        rows.addWidget(self.op_combo, 2, 1)
        rows.setColumnStretch(1, 1)
        lay.addLayout(rows)

        # Direction lives on the Linear page only. Once the axis has an
        # explicit, user-picked direction (tail -> head) the right-hand
        # rule fully determines which way a positive angle rotates;
        # there is no second +W/-W choice for Angular (Doug's live
        # test: a 180-degree pull swept into the -W half-plane with
        # Direction still +W proved it inert). Matches Creo's own
        # Angular layout, which shows no Direction row.
        self.dir_combo = QComboBox()
        self.dir_combo.addItems(["+W", "-W", "Both"])
        self._dir_touched = False
        self.dir_combo.activated.connect(self._mark_dir_touched)
        self.op_combo.currentIndexChanged.connect(self._op_changed)
        self.op_combo.currentIndexChanged.connect(self._refresh_info)
        self.dir_combo.currentIndexChanged.connect(self._refresh_info)

        row_mode = QHBoxLayout()
        self.linear_radio = QRadioButton("Linear")
        self.angular_radio = QRadioButton("Angular")
        self.linear_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.linear_radio)
        self.mode_group.addButton(self.angular_radio)
        self.linear_radio.toggled.connect(self._mode_changed)
        row_mode.addWidget(self.linear_radio)
        row_mode.addWidget(self.angular_radio)
        row_mode.addStretch(1)
        lay.addLayout(row_mode)

        # --- the part below swaps with the mode ---
        self.mode_stack = QStackedWidget()

        linear_page = QWidget()
        lg = QGridLayout(linear_page)
        lg.setContentsMargins(0, 0, 0, 0)
        lg.addWidget(dialog_style.row_label("Direction"), 0, 0)
        lg.addWidget(self.dir_combo, 0, 1)
        lg.addWidget(dialog_style.row_label("Distance"), 1, 0)
        self.dist_edit = QLineEdit()
        self.dist_edit.setPlaceholderText("e.g. 12.0")
        self.dist_edit.textChanged.connect(self._dist_changed)
        self.dist_edit.returnPressed.connect(self._on_done)
        dialog_style.accept_calc_value(main_win, self.dist_edit)
        lg.addWidget(self.dist_edit, 1, 1)
        lg.setColumnStretch(1, 1)
        self.mode_stack.addWidget(linear_page)

        angular_page = QWidget()
        ag = QGridLayout(angular_page)
        ag.setContentsMargins(0, 0, 0, 0)
        ag.addWidget(dialog_style.row_label("Axis"), 0, 0)
        axis_row = QHBoxLayout()
        self.axis_edit = QLineEdit()
        self.axis_edit.setReadOnly(True)
        axis_row.addWidget(self.axis_edit, 1)
        self.select_axis_btn = QPushButton("Pick")
        self.select_axis_btn.setAutoDefault(False)
        self.select_axis_btn.setToolTip(
            "Click two points: the axis's tail, then its head")
        self.select_axis_btn.clicked.connect(self._start_axis_pick)
        axis_row.addWidget(self.select_axis_btn)
        ag.addLayout(axis_row, 0, 1)
        ag.addWidget(dialog_style.row_label("Angle"), 1, 0)
        self.angle_edit = QLineEdit()
        self.angle_edit.setPlaceholderText("degrees, e.g. 90")
        self.angle_edit.textChanged.connect(self._angle_changed)
        self.angle_edit.returnPressed.connect(self._on_done)
        dialog_style.accept_calc_value(main_win, self.angle_edit)
        ag.addWidget(self.angle_edit, 1, 1)
        ag.setColumnStretch(1, 1)
        self.mode_stack.addWidget(angular_page)

        lay.addWidget(self.mode_stack)

        self.msg_label = QLabel("")
        self.msg_label.setObjectName("KcStatus")
        self.msg_label.setWordWrap(True)
        lay.addWidget(self.msg_label)

        dialog_style.apply_minimal(self)
        self.setMinimumWidth(250)

        self._picked_axis = None  # gp_Ax1, set once both points picked
        self._axis_pt1 = None  # gp_Pnt, set after the first pick
        self._refresh_labels()
        self._update_awaiting()
        self.dist_edit.setFocus()

    def _toggle_info(self):
        self._refresh_info()
        self._info.toggle(self.main_win)

    def _refresh_info(self, *_):
        adding = self.op_combo.currentText() == "Add Material"
        part = self.part_edit.toolTip() or "(none)"
        h = ["<h3>Pull</h3>",
             "<p>Sweeps the active workplane's profile(s) into a solid "
             "and %s the active part. The workplane and profile are "
             "always kept; delete them separately if you no longer "
             "need them.</p>" % ("adds it to" if adding
                                 else "removes it from"),
             "<p><b>Part</b> (the active part):<br>%s</p>" % part,
             "<p><b>Workplane</b>: %s</p>" % (
                 self.wp_edit.text() or "(none)")]
        if self.angular_radio.isChecked():
            h.append("<p><b>Angular</b>: the profile is revolved about "
                     "an axis in the workplane. Click <b>Pick</b>, then "
                     "the axis's <b>tail</b> and its <b>head</b> (a "
                     "workplane catch or a part vertex; they need not be "
                     "on the part). A positive angle turns by the "
                     "right-hand rule about tail &rarr; head; for the "
                     "opposite rotation pick the points in the other "
                     "order. There is no Direction choice, since the "
                     "axis direction already fixes it.</p>")
        else:
            h.append("<p><b>Linear</b>: the profile is extruded along "
                     "the workplane normal (W). <b>+W</b> / <b>-W</b> "
                     "choose the side; <b>Both</b> splits the distance "
                     "equally about the workplane. Direction follows the "
                     "Operation (+W to add, -W to remove) until you "
                     "choose one yourself.</p>")
        h.append("<p>An open profile is reported with red markers at its "
                 "unconnected ends. Done is one undo step (Ctrl+Z).</p>")
        self._info.set_html("".join(h))

    def _update_awaiting(self):
        """Yellow = still needs a value (Creo's cue)."""
        def valid_pos(txt):
            try:
                return float(txt) > 0.0
            except ValueError:
                return False
        dialog_style.set_awaiting(self.dist_edit,
                                  not valid_pos(self.dist_edit.text()))
        dialog_style.set_awaiting(self.angle_edit,
                                  not valid_pos(self.angle_edit.text()))
        dialog_style.set_awaiting(self.axis_edit,
                                  self._picked_axis is None)

    def _angle_changed(self, text):
        self._update_awaiting()

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
                "Enter an angle, then click Pick to define the axis "
                "(2 points).", 5000)
        self._refresh_info()

    def _dist_changed(self, text):
        # Spec: "acknowledge value entered, prompt user to click
        # Done" -- brief status-bar note once a valid, positive
        # number is present, nothing louder than that.
        self._update_awaiting()
        try:
            v = float(text)
            if v > 0.0:
                self.main_win.statusBar().showMessage(
                    f"Distance set -- click Done.", 4000)
        except ValueError:
            pass

    def _refresh_labels(self):
        win = self.main_win
        uid = win.activePartUID
        if uid:
            try:
                path = dm.get_full_path_name(uid)
            except Exception:
                path = str(dm.label_dict.get(uid, {}).get('name') or uid)
            leaf = dm.label_dict.get(uid, {}).get('name') or path
            self.part_edit.setText(str(leaf))
            self.part_edit.setToolTip(path)
        else:
            self.part_edit.setText("")
            self.part_edit.setToolTip("")
        dialog_style.set_awaiting(self.part_edit, not uid)
        wp_uid = getattr(win, "activeWpUID", 0)
        # Workplanes aren't XDE-backed like parts -- the uid ('wp1') or
        # the name the user gave it (Session 179) is what is shown.
        self.wp_edit.setText(win._wp_display_name(wp_uid) if wp_uid
                             else "")
        self.wp_edit.setToolTip(str(wp_uid) if wp_uid else "")
        dialog_style.set_awaiting(self.wp_edit, not wp_uid)
        if not uid:
            self.msg_label.setText("Set an Active Part first (RMB in "
                                   "the tree).")
        elif not wp_uid:
            self.msg_label.setText("Create and activate a workplane "
                                   "first.")
        self._refresh_info()

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
        self._picked_axis = None
        self.axis_edit.setText("pick point 1")
        self._update_awaiting()
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
                    hidden = win.activeWpUID in win.hide_list
                    snap = find_snap(wp, uv, tol, current_snap_mode(),
                                     hidden=hidden)
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
            self.axis_edit.setText("pick point 2")
            self._say("Point 1 picked. Pick point 2 (the axis's "
                      "head).")
        else:
            self._picked_axis = gp_Ax1(
                self._axis_pt1, gp_Dir(gp_Vec(self._axis_pt1, pt)))
            win.clearCallback()
            win._preview_stop_meas()
            self.axis_edit.setText("defined")
            self._update_awaiting()
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
            hidden = (self.main_win.activeWpUID
                     in self.main_win.hide_list)
            snap = find_snap(wp, uv, tol, current_snap_mode(),
                             hidden=hidden)
        except Exception:
            return None
        if snap is None:
            return None
        mk = self.main_win._pick_marker(wp, snap[1])
        return (mk, "geom") if mk is not None else None

    # ------------------------------------------------------------------

    def done(self, r):
        # Session 179: remove any open-profile markers, stop an axis
        # pick left half-finished, and close the info window.
        win = self.main_win
        try:
            win.clear_open_ends()
        except Exception:
            pass
        try:
            if win.registeredCallback == self._axis_pick_callback:
                win.clearCallback()
                win._preview_stop_meas()
        except Exception:
            pass
        try:
            self._info.hide()
            self._info.deleteLater()
        except Exception:
            pass
        super().done(r)

    def _on_done(self):
        win = self.main_win
        self._refresh_labels()
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

        self.main_win.clear_open_ends()
        faces, err = wp.make_faces()
        if err is not None:
            self._say(f"Profile problem: {err}")
            self.main_win.show_open_ends(wp)
            return

        if angular:
            if self._picked_axis is None:
                self._say("Define the axis first (click Pick, then the "
                          "axis's two points).")
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
            direction = self.dir_combo.currentText()
            both = (direction == "Both")
            sign = -1.0 if direction == "-W" else 1.0
            try:
                dist = float(self.dist_edit.text())
            except ValueError:
                self._say("Enter a numeric distance.")
                return
            if dist <= 0.0:
                self._say("Distance must be positive (choose -W for "
                          "the other direction, or Both for symmetric).")
                return
            vec = wp.wVec * (sign * dist * win.unitscale)
            # Both: Total Distance split equally -- start half the
            # distance on the -W side, sweep the full distance +W.
            if both:
                back = gp_Trsf()
                back.SetTranslation(
                    wp.wVec * (-0.5 * dist * win.unitscale))
            summary = (f"{dist:g} {getattr(win, 'units', 'mm')} "
                      f"{self.dir_combo.currentText()}")

        try:
            tool = None
            for f in faces:
                if angular:
                    piece = BRepPrimAPI_MakeRevol(
                        f, self._picked_axis, angle_rad).Shape()
                else:
                    start = f
                    if both:
                        start = BRepBuilderAPI_Transform(
                            f, back, True).Shape()
                    piece = BRepPrimAPI_MakePrism(start, vec).Shape()
                if tool is None:
                    tool = piece
                else:
                    tool, msg = safe_boolean.run_boolean(
                        "fuse", tool, piece, parent=win,
                        label="Combining the profiles...")
                    if tool is None:
                        self._say(msg)
                        return

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
                newPart, msg = safe_boolean.run_boolean(
                    "fuse", part, tool, parent=win,
                    label="Adding material...")
                if newPart is None:
                    self._say(msg)
                    return
            else:
                newPart, msg = safe_boolean.run_boolean(
                    "cut", part, tool, parent=win,
                    label="Removing material...")
                if newPart is None:
                    self._say(msg)
                    return
        except Exception as be:
            self._say(f"Boolean failed: {be}")
            return

        # Each Done = ONE undo transaction (a complete operation)
        # Capture the stable prototype entry + old uids BEFORE the
        # replace so every shared instance gets redrawn (Session 136).
        ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
        old_uids = set(dm.part_dict.keys())
        win.erase_shape(uid)
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        win.redraw_after_shape_replace(ref_entry, old_uids)
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
        self.axis_edit.setText("")
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
    dialog_style.place_top_left(dlg, main_win)
