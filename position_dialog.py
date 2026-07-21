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
  CONSTRAINTS section: Mate, Align, Align Axis (disabled -- Step 2/3
                    not ported yet).
  BOTTOM section:   Reverse / Back side by side, Done below. Status
                    messages go to the main window's status bar (not
                    printed in the dialog), per Doug's explicit note
                    that Basicad's dialog "often has to be resized...
                    let's put it on a diet."

THIS ROUND: only Step 1 of Mate/Align (rotate about the intersection
line of two picked face planes until flush) and 2 Points (pure
translation) are wired up. No DOF/constraint-accounting engine yet --
that's Step 2/3 territory, built once this is proven working
end-to-end including save/reload (see docs/DEVELOPMENT_LOG.md,
Session 14 -- persistence bugs here are easy to miss without a real
save+reload test, not just a redraw check).

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
        self._last_mode = "mate"    # 'mate' or 'align' -- for Reverse
        self._last_picks = None     # (pick1, pick2) from the most recent Mate/Align apply

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
        self._align_axis_btn.setEnabled(False)  # Step 2/3 not ported yet
        self._align_axis_btn.setToolTip("Not available yet -- coming after Step 1 is proven")
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
        self._reverse_btn.clicked.connect(self._on_reverse)
        self._back_btn.clicked.connect(self._on_back)
        self._done_btn.clicked.connect(self._on_done)

        self._update_ui_state()

    def _update_ui_state(self):
        self._back_btn.setEnabled(len(self._history) > 0)
        self._reverse_btn.setEnabled(self._last_pick_pair_available())

    def _last_pick_pair_available(self):
        return bool(self._history) and self._picking_for == "mate_align" \
            and self._last_picks is not None

    # -----------------------------------------------------------------
    # Constraint selection (starts picking)
    # -----------------------------------------------------------------

    def _on_constraint_chosen(self, mode):
        """Mate or Align radio chosen -- start picking (moving face,
        then fixed face), per Doug's design: 'Having chosen to apply a
        Mate or Align constraint, the user will be prompted to click
        on a moving face and a fixed face.'"""
        if not self._mate_align_btn.isChecked():
            self._mate_align_btn.setChecked(True)
        self._last_mode = mode
        self._start_face_picking()

    # -----------------------------------------------------------------
    # Picking -- Mate/Align (faces)
    # -----------------------------------------------------------------

    def _start_face_picking(self):
        self.main_win.canvas.detach_manipulator()
        self._nudge_box.setVisible(False)
        self._picking_for = "mate_align"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._face_pick_callback)
        self.main_win.canvas._display.SetSelectionModeFace()
        self.main_win.statusBar().showMessage("Pick face 1 (moving part).")

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
        self.main_win.clearCallback()
        mate = (self._last_mode == "mate")
        move = position_math.compute_step1_move(self._pick1, self._pick2, mate=mate)
        if move is None:
            self.main_win.statusBar().showMessage("Couldn't compute move -- try again.", 5000)
            return
        self._last_picks = (self._pick1, self._pick2)
        ok = self._apply_world_move(move)
        if ok:
            label = "Mate" if mate else "Align"
            self.main_win.statusBar().showMessage(f"{label} applied.", 5000)
        self._update_ui_state()

    # -----------------------------------------------------------------
    # Picking -- 2 Points
    # -----------------------------------------------------------------

    def _start_two_points_picking(self):
        self.main_win.canvas.detach_manipulator()
        self._nudge_box.setVisible(False)
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
        re-prompting for new picks."""
        if not self._last_picks or not self._history:
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
        self._refresh_display()

        self._last_mode = "align" if self._last_mode == "mate" else "mate"
        pick1, pick2 = self._last_picks
        mate = (self._last_mode == "mate")
        move = position_math.compute_step1_move(pick1, pick2, mate=mate)
        if move is None:
            self.main_win.statusBar().showMessage(
                "Reverse failed: could not recompute move.", 5000)
            self._update_ui_state()
            return
        self._apply_world_move(move)
        label = "Mate" if mate else "Align"
        self.main_win.statusBar().showMessage(f"Reversed to {label}.", 5000)
        self._update_ui_state()

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
        self._last_picks = None
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
