"""
position_dialog.py

THE POSITION DIALOG -- layout follows Doug's design PDF
("Position function for Kodacad2"):

  TOP section:     full breadcrumb path (root down to the item) in
                    bold, read-only -- a bare name doesn't disambiguate
                    which instance is meant when the same part/
                    assembly appears more than once in the tree
                    (shared instances) -- see Session 16.
  METHODS section: Dynamic (AIS_Manipulator drag + numeric Nudge
                    refinement -- see Session 23), Mate Align, 2 Points.
  CONSTRAINTS section: Mate, Align, Align Axis (disabled -- needs its
                    own axis-picking machinery, not built yet).
  BOTTOM section:   Reverse / Back side by side, Done below. Status
                    messages go to the main window's status bar (not
                    printed in the dialog), per Doug's explicit note
                    that Basicad's dialog "often has to be resized...
                    let's put it on a diet."

THIS ROUND: the full 3-2-1 Mate/Align workflow (Step 1: rotate about
the intersection line of two picked face planes; Step 2: rotate within
the plane Step 1 established; Step 3: translate along whatever's left)
and 2 Points (pure translation) are wired up, WITH DOF tracking --
applying Mate/Align a second and third time now consumes the
remaining degrees of freedom instead of independently re-flushing
against the newest pick (the original limitation that motivated this,
via the hex-on-hex-shaft case -- see docs/DEVELOPMENT_LOG.md). Align
Axis (for aligning two hole/cylinder axes directly) is its own,
separate 3-step sequence per the original design and still needs its
own axis-picking machinery -- not built yet.

UNDO MODEL: dm.set_component_location() sets an ABSOLUTE local
location (not a relative delta -- see Session 14, it rebuilds the
component's label each call). So Back does NOT apply an inverse
delta (which is what Basicad's node.move(inverse) does, since
build123d's .move() composes). Instead, before every move this dialog
snapshots the item's CURRENT local location onto a history stack, and
Back restores that exact snapshot. Simpler and immune to compounding
rotation/translation numerical drift from repeated inversions.

UID TRACKING: dm.set_component_location() returns the component's NEW
uid (the old one no longer refers to anything after the label
rebuild). self.uid is updated after every successful move -- forgetting
this would silently break the second pick sequence in a dialog
session.
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QButtonGroup,
    QRadioButton,
    QGroupBox,
    QLineEdit,
)
from PySide6.QtGui import QFont

from OCP.TopoDS import TopoDS

import position_math


class PositionDialog(QDialog):
    def __init__(self, main_win, dm, uid, name):
        super().__init__(main_win)
        self.main_win = main_win
        self.dm = dm
        self.uid = uid
        self.name = name

        # Undo history: list of local-location snapshots taken BEFORE
        # each applied move, most recent last (see _apply_world_move).
        self._history = []

        # Picking state
        self._pick1 = None          # first picked TopoDS_Face/vertex point
        self._pick2 = None
        self._picking_for = None    # 'mate_align' or 'two_points'
        self._picking_kind = None   # 'face' or 'circle' -- which resolver to use
        self._last_mode = "mate"    # 'mate' or 'align' -- for Reverse
        self._last_picks = None     # (pick1, pick2) from the most recent Mate/Align apply
        self._last_step_applied = None  # which compute_stepN_move was last used (0/1/2)
        self._last_step_kind = None      # 'face' or 'axis' -- Reverse only applies to 'face'

        # 3-2-1 DOF tracking for Mate/Align. _mate_align_step counts how
        # many of the 3 steps have been applied (0 = none yet, 3 = fully
        # constrained). _mated_normal is Step 1's result (the axis Step
        # 2 rotates about). Step 2 can be EITHER a face-align
        # (_step2_wall_normal, needed for Step 3's free-direction
        # calculation) OR Align Axis's pin move (_align_axis_pivot, the
        # point Step 3 then spins about) -- per Doug's original design
        # (docs/PositionForKodacad2.pdf, the "2nd option": mate a face,
        # then pin a hole-on-face intersection instead of a second
        # face-align, leaving only theta_z for a final Align). Reset to
        # a "Clean Slate" whenever the user switches to a different
        # Method -- constraint accounting only makes sense as one
        # continuous Mate/Align session.
        self._mate_align_step = 0
        self._mated_normal = None
        self._step1_plane_point = None  # Step 1's own pick1.point -- needed by
                                        # Align Axis's line-plane intersection
        self._step2_wall_normal = None
        self._align_axis_pivot = None   # set only if Step 2 was Align Axis

        self.setWindowTitle("Position")
        self._build_ui()

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # TOP: full breadcrumb path of item being moved (read-only).
        # Bare name alone doesn't disambiguate WHICH instance is meant
        # when the same part/assembly appears more than once in the
        # tree (shared instances) -- see Session 16.
        name_label = QLabel(self.dm.get_full_path_name(self.uid))
        bold = QFont()
        bold.setBold(True)
        name_label.setFont(bold)
        name_label.setWordWrap(True)
        self._name_label = name_label
        layout.addWidget(QLabel("Moving part / assembly:"))
        layout.addWidget(name_label)

        # METHODS
        methods_box = QGroupBox("Methods")
        methods_layout = QVBoxLayout(methods_box)
        self._method_group = QButtonGroup(self)
        self._dynamic_btn = QRadioButton("Dynamic")
        self._dynamic_btn.setToolTip(
            "Drag the gizmo's arrows to translate or rings to rotate. "
            "After releasing, use Nudge below for an exact adjustment.")
        self._mate_align_btn = QRadioButton("Mate Align")
        self._two_points_btn = QRadioButton("2 Points")
        for i, btn in enumerate([self._dynamic_btn, self._mate_align_btn, self._two_points_btn]):
            self._method_group.addButton(btn, i)
            methods_layout.addWidget(btn)
        layout.addWidget(methods_box)

        # NUDGE -- shown only while using Dynamic. A drag with
        # AIS_Manipulator is inherently mouse-driven, not exact; this
        # gives a way to refine the result with a typed value
        # afterward, rather than needing a Creo-style floating input
        # box mid-drag (real, but a much bigger UI undertaking -- see
        # docs/DEVELOPMENT_LOG.md, Session 23).
        self._nudge_box = QGroupBox("Nudge (after a drag)")
        nudge_layout = QVBoxLayout(self._nudge_box)
        trans_row = QHBoxLayout()
        self._nudge_dx = QLineEdit("0")
        self._nudge_dy = QLineEdit("0")
        self._nudge_dz = QLineEdit("0")
        for label, field in (("dX", self._nudge_dx), ("dY", self._nudge_dy), ("dZ", self._nudge_dz)):
            trans_row.addWidget(QLabel(label))
            field.setMaximumWidth(80)
            trans_row.addWidget(field)
        nudge_layout.addLayout(trans_row)
        # Rotation nudges (degrees, about world X/Y/Z) -- pivot about
        # the part's CURRENT world position (see _apply_nudge), not
        # the global origin, so a small angle can't swing a part that's
        # far from (0,0,0) wildly across the scene.
        rot_row = QHBoxLayout()
        self._nudge_rx = QLineEdit("0")
        self._nudge_ry = QLineEdit("0")
        self._nudge_rz = QLineEdit("0")
        for label, field in (("rX\u00b0", self._nudge_rx), ("rY\u00b0", self._nudge_ry), ("rZ\u00b0", self._nudge_rz)):
            rot_row.addWidget(QLabel(label))
            field.setMaximumWidth(80)
            rot_row.addWidget(field)
        nudge_layout.addLayout(rot_row)
        self._nudge_apply_btn = QPushButton("Apply Nudge")
        nudge_layout.addWidget(self._nudge_apply_btn)
        self._nudge_box.setVisible(False)
        layout.addWidget(self._nudge_box)

        # CONSTRAINTS (only meaningful for Mate Align)
        constraints_box = QGroupBox("Constraints")
        constraints_layout = QVBoxLayout(constraints_box)
        self._constraint_group = QButtonGroup(self)
        self._mate_btn = QRadioButton("Mate")
        self._align_btn = QRadioButton("Align")
        self._align_axis_btn = QRadioButton("Align Axis")
        self._align_axis_btn.setToolTip(
            "Used as Step 2, after mating/aligning a face first: pick "
            "a hole on the moving part, then a hole on the fixed part. "
            "Pins the two hole/face intersection points together, "
            "leaving only rotation for a final Align.")
        for i, btn in enumerate([self._mate_btn, self._align_btn, self._align_axis_btn]):
            self._constraint_group.addButton(btn, i)
            constraints_layout.addWidget(btn)
        layout.addWidget(constraints_box)

        # BOTTOM: Reverse / Back, then Done
        btn_row = QHBoxLayout()
        self._reverse_btn = QPushButton("Reverse")
        self._back_btn = QPushButton("Back")
        btn_row.addWidget(self._reverse_btn)
        btn_row.addWidget(self._back_btn)
        layout.addLayout(btn_row)
        self._done_btn = QPushButton("\u2705 Done")
        layout.addWidget(self._done_btn)

        # Wiring
        # IMPORTANT: use clicked, not toggled, for anything that should
        # start a NEW pick sequence. Qt's toggled signal only fires on
        # an actual state change -- clicking an already-selected radio
        # button again is a no-op as far as toggled is concerned, which
        # silently breaks "apply a second Mate in a row" (clicking Mate
        # again while Mate is already selected would do nothing). clicked
        # fires on every user click regardless of prior state.
        self._two_points_btn.clicked.connect(self._start_two_points_picking)
        self._dynamic_btn.clicked.connect(self._start_dynamic_mode)
        self._nudge_apply_btn.clicked.connect(self._apply_nudge)
        self._mate_btn.clicked.connect(lambda: self._on_constraint_chosen("mate"))
        self._align_btn.clicked.connect(lambda: self._on_constraint_chosen("align"))
        self._align_axis_btn.clicked.connect(lambda: self._on_constraint_chosen("axis"))
        self._reverse_btn.clicked.connect(self._on_reverse)
        self._back_btn.clicked.connect(self._on_back)
        self._done_btn.clicked.connect(self._on_done)

        self._update_ui_state()

    def _update_ui_state(self):
        self._back_btn.setEnabled(len(self._history) > 0)
        self._reverse_btn.setEnabled(self._last_pick_pair_available())

    def _last_pick_pair_available(self):
        # Step 3 (index 2) is pure translation or spin -- no mate/align
        # choice to reverse. Align Axis's own pin move (kind=='axis')
        # likewise has no mate/align choice.
        return (bool(self._history) and self._picking_for == "mate_align"
                and self._last_picks is not None
                and self._last_step_applied != 2
                and self._last_step_kind != "axis")

    def _reset_mate_align_dof(self):
        """Clean Slate: called whenever the user switches to a
        different Method. Per the original design, constraint
        accounting only makes sense as one continuous Mate/Align
        session -- switching away and back starts over."""
        self._mate_align_step = 0
        self._mated_normal = None
        self._step1_plane_point = None
        self._step2_wall_normal = None
        self._align_axis_pivot = None

    # -----------------------------------------------------------------
    # Constraint selection (starts picking)
    # -----------------------------------------------------------------

    def _on_constraint_chosen(self, mode):
        """Mate/Align/Align Axis radio chosen -- start the appropriate
        picking flow. Mate/Align: 'Having chosen to apply a Mate or
        Align constraint, the user will be prompted to click on a
        moving face and a fixed face.' Align Axis: per Doug's original
        design, used specifically as Step 2 -- pin a hole-on-face
        intersection instead of a second face-align -- so it's only
        valid right after Step 1."""
        if not self._mate_align_btn.isChecked():
            self._mate_align_btn.setChecked(True)

        if mode == "axis":
            if self._mate_align_step != 1:
                self.main_win.statusBar().showMessage(
                    "Align Axis is used as Step 2 -- mate or align a "
                    "face first (Step 1).", 6000)
                return
            self._start_axis_picking()
            return

        self._last_mode = mode
        if self._mate_align_step >= 3:
            self.main_win.statusBar().showMessage(
                "Already fully constrained (3 of 3 steps applied) -- "
                "click Back to remove a step first.", 6000)
            return
        self._start_face_picking()

    # -----------------------------------------------------------------
    # Picking -- Mate/Align (faces)
    # -----------------------------------------------------------------

    def _start_face_picking(self):
        self.main_win.canvas.detach_manipulator()
        self._nudge_box.setVisible(False)
        self._picking_for = "mate_align"
        self._picking_kind = "face"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._face_pick_callback)
        self.main_win.canvas._display.SetSelectionModeFace()
        step_num = self._mate_align_step + 1
        self.main_win.statusBar().showMessage(
            f"Step {step_num} of 3: pick face 1 (moving part).")

    def _face_pick_callback(self, shapeList, *args):
        for shape in shapeList:
            try:
                face = TopoDS.Face_s(shape)
            except Exception as e:
                print(f"[PositionDialog] pick was not a face: {e}")
                continue
            pick = position_math.resolve_face_pick(face)
            if self._pick1 is None:
                self._pick1 = pick
                self.main_win.statusBar().showMessage("Face 1 picked. Pick face 2 (fixed).")
            else:
                self._pick2 = pick
                self._apply_mate_align()
                return

    def _apply_mate_align(self):
        """Dispatches to whichever of Step 1/2/3's math applies, based
        on how many steps have already been applied this session
        (self._mate_align_step). Each successful step records what it
        established via _record_step_success() for the NEXT step to
        use. Step 3 itself branches on whether Step 2 was a normal
        face-align (_step2_wall_normal set) or Align Axis
        (_align_axis_pivot set instead)."""
        self.main_win.clearCallback()
        mate = (self._last_mode == "mate")
        step = self._mate_align_step

        if step == 0:
            move = position_math.compute_step1_move(self._pick1, self._pick2, mate=mate)
        elif step == 1:
            move = position_math.compute_step2_move(
                self._pick1, self._pick2, self._mated_normal, mate=mate)
        elif step == 2:
            if self._align_axis_pivot is not None:
                move = position_math.compute_step3_move(
                    self._pick1, self._pick2, self._mated_normal,
                    spin_pivot=self._align_axis_pivot)
            else:
                move = position_math.compute_step3_move(
                    self._pick1, self._pick2, self._mated_normal,
                    wall_normal=self._step2_wall_normal)
        else:
            self.main_win.statusBar().showMessage(
                "Already fully constrained (3 of 3 steps applied) -- "
                "click Back to remove a step first.", 6000)
            return

        if move is None:
            self.main_win.statusBar().showMessage("Couldn't compute move -- try again.", 5000)
            return

        self._last_picks = (self._pick1, self._pick2)
        self._last_step_applied = step
        self._last_step_kind = "face"
        ok = self._apply_world_move(move)
        if ok:
            self._record_step_success(step, mate)
            label = "Mate" if mate else "Align"
            remaining = 3 - self._mate_align_step
            if remaining > 0:
                self.main_win.statusBar().showMessage(
                    f"{label} applied (step {self._mate_align_step} of 3, "
                    f"{remaining} DOF left). Pick Mate or Align again to continue.", 8000)
            else:
                self.main_win.statusBar().showMessage(
                    f"{label} applied -- fully constrained (3 of 3).", 6000)
        self._update_ui_state()

    # -----------------------------------------------------------------
    # Picking -- Align Axis (circular edges / holes), Step 2 only
    # -----------------------------------------------------------------

    def _start_axis_picking(self):
        self.main_win.canvas.detach_manipulator()
        self._nudge_box.setVisible(False)
        self._picking_for = "mate_align"
        self._picking_kind = "circle"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._axis_pick_callback)
        self.main_win.canvas._display.SetSelectionModeEdge()
        self.main_win.statusBar().showMessage(
            "Step 2 of 3 (Align Axis): pick a hole on the moving part.")

    def _axis_pick_callback(self, shapeList, *args):
        for shape in shapeList:
            try:
                edge = TopoDS.Edge_s(shape)
                pick = position_math.resolve_circle_pick(edge)
            except Exception as e:
                print(f"[PositionDialog] pick was not a circular edge: {e}")
                self.main_win.statusBar().showMessage(
                    "Pick a hole/circular edge, not that.", 4000)
                continue
            if self._pick1 is None:
                self._pick1 = pick
                self.main_win.statusBar().showMessage(
                    "Hole 1 picked. Pick hole 2 (fixed part).")
            else:
                self._pick2 = pick
                self._apply_align_axis_pin()
                return

    def _apply_align_axis_pin(self):
        """Align Axis as Step 2 (Doug's original design): pins the two
        picked holes' axis-vs-mated-plane intersection points
        together, consuming x/y and leaving only rotation for a final
        Align (Step 3's spin case)."""
        self.main_win.clearCallback()
        move = position_math.compute_align_axis_pin_move(
            self._pick1, self._pick2, self._mated_normal, self._step1_plane_point)
        if move is None:
            self.main_win.statusBar().showMessage("Couldn't compute move -- try again.", 5000)
            return

        self._last_picks = (self._pick1, self._pick2)
        self._last_step_applied = 1
        self._last_step_kind = "axis"  # Reverse doesn't apply -- no mate/align choice here
        ok = self._apply_world_move(move)
        if ok:
            # Pivot for Step 3's spin: the FIXED hole's own intersection
            # point (pick2, never moved) -- after a correct pin move the
            # moving hole's point now coincides with it, but recomputing
            # from pick1 would use its STALE pre-move position.
            N = self._mated_normal.normalized()
            self._align_axis_pivot = position_math.line_plane_intersection(
                self._pick2.point, self._pick2.direction.normalized(),
                self._step1_plane_point, N)
            self._mate_align_step = 2
            self.main_win.statusBar().showMessage(
                "Align Axis applied (step 2 of 3, 1 DOF left). "
                "Pick Mate or Align again for the final rotation.", 8000)
        self._update_ui_state()

    # -----------------------------------------------------------------
    # Picking -- 2 Points
    # -----------------------------------------------------------------

    def _start_two_points_picking(self):
        self.main_win.canvas.detach_manipulator()
        self._nudge_box.setVisible(False)
        self._reset_mate_align_dof()
        self._picking_for = "two_points"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._point_pick_callback)
        self.main_win.canvas._display.SetSelectionModeVertex()
        self.main_win.statusBar().showMessage("Pick point 1 (need not be on the part).")

    def _point_pick_callback(self, shapeList, *args):
        from OCP.BRep import BRep_Tool
        for shape in shapeList:
            try:
                vrtx = TopoDS.Vertex_s(shape)
            except Exception as e:
                print(f"[PositionDialog] pick was not a vertex: {e}")
                continue
            gp_pt = BRep_Tool.Pnt_s(vrtx)
            pt = position_math.Vec3.from_gp(gp_pt)
            if self._pick1 is None:
                self._pick1 = pt
                self.main_win.statusBar().showMessage("Point 1 picked. Pick point 2.")
            else:
                self._pick2 = pt
                self._apply_two_points()
                return

    def _apply_two_points(self):
        self.main_win.clearCallback()
        move = position_math.compute_two_points_move(self._pick1, self._pick2)
        ok = self._apply_world_move(move)
        if ok:
            self.main_win.statusBar().showMessage("Position applied.", 5000)
        self._update_ui_state()

    # -----------------------------------------------------------------
    # Dynamic (AIS_Manipulator drag + numeric Nudge refinement)
    # -----------------------------------------------------------------

    def _start_dynamic_mode(self):
        self.main_win.clearCallback()
        self._reset_mate_align_dof()
        self._picking_for = "dynamic"
        if self._reattach_manipulator():
            self._nudge_box.setVisible(True)
            self.main_win.statusBar().showMessage(
                "Drag an arrow to translate or a ring to rotate.")
        else:
            self.main_win.statusBar().showMessage(
                "Could not attach manipulator -- see console.", 5000)

    def _reattach_manipulator(self):
        """(Re)attach the manipulator to every leaf part under self.uid.

        Called both to start Dynamic mode and after every applied move
        (Session 15's uid-tracking rule applies here too: self.uid
        changes on every set_component_location() call, and the
        redraw it triggers destroys/rebuilds every AIS_Shape, so the
        manipulator has to be re-resolved fresh each time rather than
        reused)."""
        part_uids = self.dm.get_descendant_part_uids(self.uid)
        leaf_shapes = [self.main_win.ais_shape_dict[u] for u in part_uids
                       if u in self.main_win.ais_shape_dict]
        if not leaf_shapes:
            return False
        return self.main_win.canvas.attach_manipulator(
            leaf_shapes, move_callback=self._on_manip_move,
            done_callback=self._on_manip_done)

    def _on_manip_move(self, delta_trsf):
        """Live status update during a drag. Translation distance only
        (not rotation angle) -- keeps this to APIs already proven
        elsewhere in this codebase (TranslationPart().X/Y/Z()) rather
        than guessing at gp_Trsf's rotation-extraction signature."""
        tp = delta_trsf.TranslationPart()
        dist = (tp.X() ** 2 + tp.Y() ** 2 + tp.Z() ** 2) ** 0.5
        if dist > 1e-6:
            self.main_win.statusBar().showMessage(f"Dragging: {dist:.2f} mm from start.")
        else:
            self.main_win.statusBar().showMessage("Dragging (rotation).")

    def _on_manip_done(self, delta_trsf):
        """Drag released -- apply it the same way every other Position
        method does (dm.set_component_location via _apply_world_move),
        so Back/Reverse/history all work uniformly regardless of which
        method produced the move."""
        from OCP.TopLoc import TopLoc_Location
        # Detach BEFORE applying: _apply_world_move triggers a full
        # redraw (ais_shape_dict.clear() + rebuild), which would leave
        # the manipulator attached to now-destroyed AIS_Shape objects.
        self.main_win.canvas.detach_manipulator()
        move = TopLoc_Location(delta_trsf)
        ok = self._apply_world_move(move)
        if ok:
            self.main_win.statusBar().showMessage(
                "Move applied. Drag again, or use Nudge to refine.", 6000)
            self._reattach_manipulator()
        self._update_ui_state()

    def _apply_nudge(self):
        """Apply an exact numeric translation and/or rotation on top of
        whatever the drag already did -- the actual answer to 'I want
        a precise typed value', short of a full Creo-style floating
        input box mid-drag (see module docstring)."""
        try:
            dx = float(self._nudge_dx.text())
            dy = float(self._nudge_dy.text())
            dz = float(self._nudge_dz.text())
            rx = float(self._nudge_rx.text())
            ry = float(self._nudge_ry.text())
            rz = float(self._nudge_rz.text())
        except ValueError:
            self.main_win.statusBar().showMessage("Nudge values must be numbers.", 5000)
            return
        if dx == dy == dz == rx == ry == rz == 0:
            return

        import math
        from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir
        from OCP.TopLoc import TopLoc_Location

        # Rotations pivot about the part's CURRENT world position, not
        # the global origin -- otherwise a small angle could swing a
        # part that's far from (0,0,0) wildly across the scene, since
        # gp_Ax1's default axis point IS the origin unless told
        # otherwise.
        current_world = self.dm.get_world_loc(self.uid)
        pivot = current_world.Transformation().TranslationPart()
        pivot_pnt = gp_Pnt(pivot.X(), pivot.Y(), pivot.Z())

        # Compose in a fixed order: rotate about X, then Y, then Z
        # (all at the pivot), then translate. Simultaneous multi-axis
        # rotation is inherently order-dependent (there's no single
        # "correct" order) -- fine for a nudge, which is typically one
        # axis at a time, but worth knowing if two angles are entered
        # together and the result isn't what was expected.
        combined = gp_Trsf()
        for axis_dir, angle_deg in ((gp_Dir(1, 0, 0), rx),
                                    (gp_Dir(0, 1, 0), ry),
                                    (gp_Dir(0, 0, 1), rz)):
            if angle_deg == 0:
                continue
            t = gp_Trsf()
            t.SetRotation(gp_Ax1(pivot_pnt, axis_dir), math.radians(angle_deg))
            combined = t.Multiplied(combined)
        if dx or dy or dz:
            t = gp_Trsf()
            t.SetTranslation(gp_Vec(dx, dy, dz))
            combined = t.Multiplied(combined)

        move = TopLoc_Location(combined)
        self.main_win.canvas.detach_manipulator()
        ok = self._apply_world_move(move)
        if ok:
            for field in (self._nudge_dx, self._nudge_dy, self._nudge_dz,
                         self._nudge_rx, self._nudge_ry, self._nudge_rz):
                field.setText("0")
            self.main_win.statusBar().showMessage("Nudge applied.", 5000)
            self._reattach_manipulator()
        self._update_ui_state()

    # -----------------------------------------------------------------
    # Applying a computed world-space move
    # -----------------------------------------------------------------

    def _apply_world_move(self, world_move_loc):
        """Apply a world-space delta Location to self.uid, persisting
        via dm.set_component_location(). Snapshots the pre-move LOCAL
        location onto the undo history (not the delta -- see module
        docstring) and updates self.uid to whatever
        set_component_location() reports (the label gets rebuilt every
        call -- Session 14)."""
        if self.uid not in self.dm.label_dict:
            self.main_win.statusBar().showMessage(
                "Position failed: part no longer available.", 5000)
            return False

        current_world = self.dm.get_world_loc(self.uid)
        current_local = self.dm.world_to_local(self.uid, current_world)
        new_world = world_move_loc.Multiplied(current_world)
        new_local = self.dm.world_to_local(self.uid, new_world)

        new_uid = self.dm.set_component_location(self.uid, new_local)
        if new_uid is None:
            self.main_win.statusBar().showMessage(
                "Position failed -- see console.", 5000)
            return False

        self._history.append(current_local)
        self.uid = new_uid
        self._refresh_display()
        return True

    def _refresh_display(self):
        self.main_win.ais_shape_dict.clear()
        self.main_win.canvas._display.Context.RemoveAll(False)
        self.main_win.build_tree()
        self.main_win.redraw()
        self._name_label.setText(self.dm.get_full_path_name(self.uid))

    # -----------------------------------------------------------------
    # Reverse / Back / Done
    # -----------------------------------------------------------------

    def _on_reverse(self):
        """Re-apply the last Mate/Align move with the opposite mode,
        using the SAME two picks (per Doug's design: 'The Reverse
        button will toggle between Mate and Align'), rather than
        re-prompting for new picks. Works for whichever step (1 or 2 --
        Step 3 is pure translation, no mode to flip, and is excluded
        by _last_pick_pair_available) was last applied, not just Step 1."""
        if not self._last_picks or not self._history:
            return
        step = self._last_step_applied
        if step is None or step == 2 or self._last_step_kind == "axis":
            return

        # Undo the last move first (restore pre-move local location),
        # then re-apply with the flipped mode from the same picks.
        # IMPORTANT: capture the uid this restore call returns --
        # set_component_location() rebuilds the label every time
        # (Session 14), so self.uid must be updated here too, not
        # just after the re-apply below.
        prev_local = self._history.pop()
        restored_uid = self.dm.set_component_location(self.uid, prev_local)
        if restored_uid is None:
            self.main_win.statusBar().showMessage(
                "Reverse failed: could not restore previous position.", 5000)
            self._update_ui_state()
            return
        self.uid = restored_uid
        # Step the DOF tracker back to before this step, clearing what
        # it established -- we're about to recompute it with the
        # flipped mode, which may change what gets recorded (e.g. a
        # flipped Step 1 mated_normal points the opposite way).
        self._mate_align_step = step
        if step == 0:
            self._mated_normal = None
            self._step1_plane_point = None
        elif step == 1:
            self._step2_wall_normal = None
        self._refresh_display()

        self._last_mode = "align" if self._last_mode == "mate" else "mate"
        pick1, pick2 = self._last_picks
        mate = (self._last_mode == "mate")
        if step == 0:
            move = position_math.compute_step1_move(pick1, pick2, mate=mate)
        elif step == 1:
            move = position_math.compute_step2_move(pick1, pick2, self._mated_normal, mate=mate)
        else:
            move = None

        if move is None:
            self.main_win.statusBar().showMessage(
                "Reverse failed: could not recompute move.", 5000)
            self._update_ui_state()
            return
        ok = self._apply_world_move(move)
        if ok:
            self._record_step_success(step, mate)
        label = "Mate" if mate else "Align"
        self.main_win.statusBar().showMessage(f"Reversed to {label}.", 5000)
        self._update_ui_state()

    def _record_step_success(self, step, mate):
        """After successfully applying Mate/Align step 0/1 (face-based
        -- Align Axis's own Step-2-equivalent is recorded separately in
        _apply_align_axis_pin), record what it established for the
        NEXT step to use, and advance the DOF counter. Shared by
        _apply_mate_align and _on_reverse so the bookkeeping can't
        drift between the two."""
        if step == 0:
            self._mated_normal = (-self._last_picks[1].direction if mate
                                  else self._last_picks[1].direction)
            self._step1_plane_point = self._last_picks[0].point
        elif step == 1:
            self._step2_wall_normal = self._last_picks[1].direction
        self._mate_align_step = step + 1

    def _on_back(self):
        if not self._history:
            return
        # Back can be clicked while Dynamic mode is active (its
        # enablement doesn't check which method is current) -- detach
        # around the redraw for the same reason _on_manip_done and
        # _apply_nudge do.
        was_dynamic = self._picking_for == "dynamic"
        if was_dynamic:
            self.main_win.canvas.detach_manipulator()
        prev_local = self._history.pop()
        new_uid = self.dm.set_component_location(self.uid, prev_local)
        if new_uid is not None:
            self.uid = new_uid
            self._refresh_display()
            self.main_win.statusBar().showMessage("Step undone.", 5000)
            # Step the DOF tracker backward too, clearing whatever
            # that step had established for the NEXT step to use --
            # covers BOTH the normal face-align path and Align Axis
            # (only one of _step2_wall_normal/_align_axis_pivot would
            # ever actually be set, safe to clear both).
            if self._mate_align_step > 0:
                self._mate_align_step -= 1
                if self._mate_align_step == 1:
                    self._step2_wall_normal = None
                    self._align_axis_pivot = None
                elif self._mate_align_step == 0:
                    self._mated_normal = None
                    self._step1_plane_point = None
        self._last_picks = None
        self._last_step_applied = None
        self._last_step_kind = None
        if was_dynamic:
            self._reattach_manipulator()
        self._update_ui_state()

    def _on_done(self):
        self.main_win.clearCallback()
        self.main_win.canvas.detach_manipulator()
        self.main_win.statusBar().showMessage("Position complete.", 5000)
        self.close()

    def closeEvent(self, event):
        self.main_win.clearCallback()
        self.main_win.canvas.detach_manipulator()
        super().closeEvent(event)
