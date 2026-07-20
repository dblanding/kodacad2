"""
position_dialog.py

THE POSITION DIALOG -- layout follows Doug's design PDF
("Position function for Kodacad2"):

  TOP section:     full breadcrumb path (root down to the item) in
                    bold, read-only -- a bare name doesn't disambiguate
                    which instance is meant when the same part/
                    assembly appears more than once in the tree
                    (shared instances) -- see Session 16.
  METHODS section: Dynamic (disabled -- AIS_Manipulator not ported
                    yet), Mate Align, 2 Points.
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
        self._dynamic_btn.setEnabled(False)  # AIS_Manipulator not ported yet
        self._dynamic_btn.setToolTip("Not available yet -- coming with the AIS_Manipulator port")
        self._mate_align_btn = QRadioButton("Mate Align")
        self._two_points_btn = QRadioButton("2 Points")
        for i, btn in enumerate([self._dynamic_btn, self._mate_align_btn, self._two_points_btn]):
            self._method_group.addButton(btn, i)
            methods_layout.addWidget(btn)
        layout.addWidget(methods_box)

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
        self._picking_for = "mate_align"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._face_pick_callback)
        self.main_win.canvas._display.SetSelectionModeFace()
        self.main_win.statusBar().showMessage(
            f"Positioning '{self.name}': pick a face ON the part to move.")

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
                self.main_win.statusBar().showMessage(
                    f"Positioning '{self.name}': now pick the FIXED (target) face.")
            else:
                self._pick2 = pick
                self._apply_mate_align()
                return

    def _apply_mate_align(self):
        self.main_win.clearCallback()
        mate = (self._last_mode == "mate")
        move = position_math.compute_step1_move(self._pick1, self._pick2, mate=mate)
        if move is None:
            self.main_win.statusBar().showMessage(
                "Could not compute move from these picks. Try again.", 5000)
            return
        self._last_picks = (self._pick1, self._pick2)
        ok = self._apply_world_move(move)
        if ok:
            label = "Mate" if mate else "Align"
            self.main_win.statusBar().showMessage(
                f"{label} applied. Reverse to flip Mate/Align, or Done to finish.", 8000)
        self._update_ui_state()

    # -----------------------------------------------------------------
    # Picking -- 2 Points
    # -----------------------------------------------------------------

    def _start_two_points_picking(self):
        self._picking_for = "two_points"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._point_pick_callback)
        self.main_win.canvas._display.SetSelectionModeVertex()
        self.main_win.statusBar().showMessage(
            f"Positioning '{self.name}': pick a reference point (point 1). "
            f"It doesn't need to be on '{self.name}' itself -- only the "
            f"distance from point 1 to point 2 matters.")

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
                self.main_win.statusBar().showMessage(
                    f"Positioning '{self.name}': now pick point 2 -- "
                    f"'{self.name}' will move by the distance from point 1 to point 2.")
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
        prev_local = self._history.pop()
        new_uid = self.dm.set_component_location(self.uid, prev_local)
        if new_uid is not None:
            self.uid = new_uid
            self._refresh_display()
            self.main_win.statusBar().showMessage("Step undone.", 5000)
        self._last_picks = None
        self._update_ui_state()

    def _on_done(self):
        self.main_win.clearCallback()
        self.main_win.statusBar().showMessage("Position complete.", 5000)
        self.close()

    def closeEvent(self, event):
        self.main_win.clearCallback()
        super().closeEvent(event)
