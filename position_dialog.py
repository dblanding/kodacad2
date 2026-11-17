"""
position_dialog.py

THE POSITION DIALOG -- layout follows Doug's design PDF
("Position function for Kodacad2"):

  Object row:      full breadcrumb path, read-only -- a bare name doesn't
                    disambiguate which instance is meant when the same
                    part/assembly appears more than once (shared
                    instances -- see Session 16).
  METHODS:         Dynamic, Mate Align, 2 Points (radios); below them a
                    stacked page per method (Session 179, minimal style):
                    Dynamic = Frame + Nudge fields + Apply/Re-Apply (see
                    Session 23 for the numeric Nudge); Mate Align =
                    Mate / Align / Align Axis + Reverse; 2 Points = hint.
  ALWAYS:          check / cross / ? bar on top, Back at the bottom.
                    Status messages go to the main window's status bar,
                    per Doug's note that Basicad's dialog "often has to
                    be resized... let's put it on a diet."

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
    QLineEdit,
    QGridLayout,
    QStackedWidget,
    QWidget,
    QSizePolicy,
)
from PySide6.QtGui import QFont

from OCP.TopoDS import TopoDS

import position_math
import dialog_style


class PositionDialog(QDialog):
    def __init__(self, main_win, dm, uid, name):
        super().__init__(main_win)
        self.main_win = main_win
        self.dm = dm
        self.uid = uid
        self.name = name

        # UNDO INTEGRATION, option (b) chosen by Doug (Session 61):
        # the WHOLE positioning session is ONE OCAF transaction,
        # opened here and committed at Done (or on close) -- so the
        # app-level undo history reads one-entry-per-completed-
        # placement and Ctrl+Z undoes a placement as a unit, while
        # the Back button keeps its fine-grained internal _history
        # stepping WITHIN the open transaction. Internal moves call
        # dm.set_component_location through undo_transaction, which
        # JOINS this open command rather than nesting.
        self._txn_open = False
        try:
            if not dm.doc.HasOpenCommand():
                dm.doc.NewCommand()
                self._txn_open = True
        except Exception as e:
            print(f"[position] could not open undo transaction: {e}")

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
        # constrained). Two different things can happen at Step 1, and
        # two different things at Step 2/3 -- _step1_kind and
        # _step3_kind are the explicit discriminators that tell later
        # steps which math to use, rather than inferring it from which
        # other variable happens to be non-None:
        #
        #   _step1_kind == "face": normal face Mate/Align (3 DOF).
        #     _mated_normal / _step1_point record what it established.
        #   _step1_kind == "axis": standalone Align Axis (Basicad's
        #     "bolt in a hole" case -- 4 DOF at once). Same two
        #     variables record the resulting shared axis instead.
        #
        #   _step3_kind == "wall": Step 2 was a normal face-align.
        #     _step2_wall_normal is Step 3's free-direction input.
        #   _step3_kind == "spin": Step 2 was EITHER Align Axis's pin
        #     move (Doug's PDF "2nd option", chained after a face
        #     mate) OR the axial-translate step after standalone Align
        #     Axis -- both leave pure rotation as the only remaining
        #     DOF. _align_axis_pivot is Step 3's spin-pivot input.
        #
        # Reset to a "Clean Slate" whenever the user switches to a
        # different Method -- constraint accounting only makes sense
        # as one continuous Mate/Align session.
        self._mate_align_step = 0
        self._step1_kind = None
        self._mated_normal = None
        self._step1_point = None
        self._step3_kind = None
        self._step2_wall_normal = None
        self._align_axis_pivot = None

        # Sticky gizmo frame (Session 179, Doug: after each nudge the
        # gizmo jumped back to its default place, losing 'Align Gizmo
        # to Active Workplane'). When set, it is
        # (origin_xyz, w_dir_xyz, u_dir_xyz), a SNAPSHOT of the
        # workplane's frame taken when the user aligned; every
        # re-attach of the manipulator re-applies it, so repeated
        # rotations about the same workplane axis need no re-aligning.
        # Cleared when Dynamic is (re)started: that returns the gizmo
        # to its default placement.
        self._frame = None
        self._frame_name = ""    # display name of the workplane it came from

        # Stage C (minimal layout) state: the stacked method pages, the
        # '?' window, the Re-Apply button and the last nudge's values.
        self._stack = None
        self._info = None
        self._reapply_btn = None
        self._last_nudge = None   # six field texts of the last good nudge

        self.setWindowTitle("Position")
        self._build_ui()

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------

    # -- stage C: minimal layout ---------------------------------------
    # One fixed-size dialog. The three Methods are radios; the section
    # below them is a QStackedWidget holding ONE page per method, so
    # only the chosen method's controls are ever visible (the old
    # dialog showed Constraints under Dynamic and 2 Points too, and
    # its show/hide calls were scattered through the pick starters).
    # A stack is as tall as its tallest page, so the dialog does not
    # change size when the method changes (Creo does the same).
    # All the positioning LOGIC below is unchanged.

    _PAGE_DYNAMIC, _PAGE_MATE, _PAGE_TWO_POINTS, _PAGE_NONE = 0, 1, 2, 3

    def _build_ui(self):
        lay = QVBoxLayout(self)
        self._info = dialog_style.InfoWindow(self.main_win,
                                             "Position details")

        bar, self._ok_btn, self._cancel_btn, self._help_btn = \
            dialog_style.icon_bar(self._on_done, self.close,
                                  self._toggle_info)
        # Doug: the red cross does what the window's X does (closeEvent
        # commits the moves already made).
        self._cancel_btn.setToolTip(
            "Close (same as the window's X) - moves already made stay")
        self._ok_btn.setToolTip("Done")
        self._done_btn = self._ok_btn
        lay.addLayout(bar)

        # Object: the full breadcrumb path (shared instances are told
        # apart by it - Session 16). Read-only; always filled.
        obj = QGridLayout()
        obj.addWidget(dialog_style.row_label("Object"), 0, 0)
        full = self.dm.get_full_path_name(self.uid)
        self._name_label = QLineEdit(full)
        self._name_label.setReadOnly(True)
        self._name_label.setCursorPosition(0)
        self._name_label.setToolTip(full)
        obj.addWidget(self._name_label, 0, 1)
        obj.setColumnStretch(1, 1)
        lay.addLayout(obj)

        # Methods
        mrow = QHBoxLayout()
        self._method_group = QButtonGroup(self)
        self._dynamic_btn = QRadioButton("Dynamic")
        self._dynamic_btn.setToolTip(
            "Drag the gizmo's arrows to translate or rings to rotate; "
            "refine with the typed Nudge below.")
        self._mate_align_btn = QRadioButton("Mate Align")
        self._two_points_btn = QRadioButton("2 Points")
        for i, btn in enumerate((self._dynamic_btn, self._mate_align_btn,
                                 self._two_points_btn)):
            self._method_group.addButton(btn, i)
            mrow.addWidget(btn)
        mrow.addStretch(1)
        lay.addLayout(mrow)

        # One page per method (+ an empty 'choose a method' page)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_dynamic_page())
        self._stack.addWidget(self._build_mate_page())
        self._stack.addWidget(self._build_two_points_page())
        self._stack.addWidget(self._hint_page("Choose a method above."))
        self._stack.setCurrentIndex(self._PAGE_NONE)
        lay.addWidget(self._stack)

        # Always visible: Back
        self._back_btn = QPushButton("Back")
        self._back_btn.setAutoDefault(False)
        self._back_btn.setToolTip("Undo the last step of this session")
        lay.addWidget(self._back_btn)

        # Wiring. clicked, not toggled (see the old builder's note).
        self._dynamic_btn.clicked.connect(self._start_dynamic_mode)
        self._mate_align_btn.clicked.connect(self._on_mate_align_method)
        self._two_points_btn.clicked.connect(self._start_two_points_picking)
        self._nudge_apply_btn.clicked.connect(self._apply_nudge)
        self._reapply_btn.clicked.connect(self._on_reapply_nudge)
        self._mate_btn.clicked.connect(
            lambda: self._on_constraint_chosen("mate"))
        self._align_btn.clicked.connect(
            lambda: self._on_constraint_chosen("align"))
        self._align_axis_btn.clicked.connect(
            lambda: self._on_constraint_chosen("axis"))
        self._reverse_btn.clicked.connect(self._on_reverse)
        self._back_btn.clicked.connect(self._on_back)

        dialog_style.apply_minimal(self)
        self.setMinimumWidth(300)
        self._update_ui_state()

    def _hint_page(self, text):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text)
        # single line that never widens the dialog
        lab.setSizePolicy(QSizePolicy.Policy.Ignored,
                          QSizePolicy.Policy.Preferred)
        pl.addWidget(lab)
        pl.addStretch(1)
        return page

    def _nudge_field(self):
        f = QLineEdit("0")
        f.setMaximumWidth(64)
        dialog_style.accept_calc_value(self.main_win, f)
        return f

    def _build_dynamic_page(self):
        page = QWidget()
        g = QGridLayout(page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(4)
        g.setVerticalSpacing(4)

        # Frame (Session 179): World = gizmo at its default place with
        # world X/Y/Z; Active Workplane = gizmo on the workplane's
        # origin and U/V/W, where it STAYS after each move (_frame).
        # Radios, not a combo (a combo drew blank until focus loss).
        fr = QHBoxLayout()
        fr.addWidget(dialog_style.row_label("Frame"))
        self._frame_world_rb = QRadioButton("World")
        self._frame_wp_rb = QRadioButton("Active Workplane")
        self._frame_world_rb.setChecked(True)
        self._frame_group = QButtonGroup(self)
        self._frame_group.addButton(self._frame_world_rb)
        self._frame_group.addButton(self._frame_wp_rb)
        self._frame_world_rb.setToolTip(
            "The gizmo's default place, axes X/Y/Z.")
        self._frame_wp_rb.setToolTip(
            "The gizmo sits on the active workplane's origin with its "
            "own U/V/W as the axes, so a Nudge rotation turns about the "
            "workplane's axis and typed distances run along U/V/W. It "
            "stays there after each move.\n"
            "Click it again to pick up a different active workplane.")
        # clicked: re-clicking the checked button must re-read the
        # CURRENT active workplane
        self._frame_world_rb.clicked.connect(self._on_frame_chosen)
        self._frame_wp_rb.clicked.connect(self._on_frame_chosen)
        fr.addWidget(self._frame_world_rb)
        fr.addWidget(self._frame_wp_rb)
        fr.addStretch(1)
        g.addLayout(fr, 0, 0, 1, 6)

        self._frame_wp_label = QLabel("")
        bold = QFont()
        bold.setBold(True)
        self._frame_wp_label.setFont(bold)
        self._frame_wp_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                           QSizePolicy.Policy.Preferred)
        g.addWidget(self._frame_wp_label, 1, 0, 1, 6)

        self._nudge_dx = self._nudge_field()
        self._nudge_dy = self._nudge_field()
        self._nudge_dz = self._nudge_field()
        self._nudge_rx = self._nudge_field()
        self._nudge_ry = self._nudge_field()
        self._nudge_rz = self._nudge_field()
        self._trans_labels = []
        self._rot_labels = []
        for row, labels, fields, store in (
                (2, ("dX", "dY", "dZ"),
                 (self._nudge_dx, self._nudge_dy, self._nudge_dz),
                 self._trans_labels),
                (3, ("rX\u00b0", "rY\u00b0", "rZ\u00b0"),
                 (self._nudge_rx, self._nudge_ry, self._nudge_rz),
                 self._rot_labels)):
            for i, (txt, fld) in enumerate(zip(labels, fields)):
                lab = dialog_style.row_label(txt)
                store.append(lab)
                g.addWidget(lab, row, 2 * i)
                g.addWidget(fld, row, 2 * i + 1)

        brow = QHBoxLayout()
        self._nudge_apply_btn = QPushButton("Apply Nudge")
        self._nudge_apply_btn.setAutoDefault(False)
        self._reapply_btn = QPushButton("Re-Apply")
        self._reapply_btn.setAutoDefault(False)
        self._reapply_btn.setEnabled(False)
        self._reapply_btn.setToolTip("Repeat the last nudge")
        brow.addWidget(self._nudge_apply_btn)
        brow.addWidget(self._reapply_btn)
        brow.addStretch(1)
        g.addLayout(brow, 4, 0, 1, 6)
        return page

    def _build_mate_page(self):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self._constraint_group = QButtonGroup(self)
        self._mate_btn = QRadioButton("Mate")
        self._align_btn = QRadioButton("Align")
        self._align_axis_btn = QRadioButton("Align Axis")
        self._align_axis_btn.setToolTip(
            "Used as Step 2, after mating/aligning a face first: pick "
            "a hole on the moving part, then a hole on the fixed part. "
            "Pins the two hole/face intersection points together, "
            "leaving only rotation for a final Align.")
        for i, btn in enumerate((self._mate_btn, self._align_btn,
                                 self._align_axis_btn)):
            self._constraint_group.addButton(btn, i)
            row.addWidget(btn)
        row.addStretch(1)
        pl.addLayout(row)
        self._reverse_btn = QPushButton("Reverse")
        self._reverse_btn.setAutoDefault(False)
        self._reverse_btn.setToolTip(
            "Flip the last Mate/Align to the other side of the face")
        rrow = QHBoxLayout()
        rrow.addWidget(self._reverse_btn)
        rrow.addStretch(1)
        pl.addLayout(rrow)
        pl.addStretch(1)
        return page

    def _build_two_points_page(self):
        return self._hint_page("Pick point 1, then point 2.")

    def _show_page(self, idx):
        """Select the method page (and keep the Methods radios in step)."""
        self._stack.setCurrentIndex(idx)
        if idx < 3:
            btn = (self._dynamic_btn, self._mate_align_btn,
                   self._two_points_btn)[idx]
            if not btn.isChecked():
                btn.setChecked(True)

    def _on_mate_align_method(self):
        """The 'Mate Align' method radio itself (the constraint radios
        start the picking). Entering from another method is a clean
        slate: drop the gizmo, any pick callback and the DOF count."""
        if self._stack.currentIndex() == self._PAGE_MATE:
            return
        self.main_win.clearCallback()
        self.main_win.canvas.detach_manipulator()
        self._reset_mate_align_dof()
        self._picking_for = None
        self._show_page(self._PAGE_MATE)
        self.main_win.statusBar().showMessage(
            "Choose Mate, Align or Align Axis, then pick the faces.")

    def _nudge_fields(self):
        return (self._nudge_dx, self._nudge_dy, self._nudge_dz,
                self._nudge_rx, self._nudge_ry, self._nudge_rz)

    def _on_reapply_nudge(self):
        """Put the last nudge's values back in the fields and apply
        them again (Doug: repeating the same nudge without retyping)."""
        if self._last_nudge is None:
            return
        for fld, txt in zip(self._nudge_fields(), self._last_nudge):
            fld.setText(txt)
        self._apply_nudge()

    def _update_reapply(self):
        if self._reapply_btn is None or self._last_nudge is None:
            return
        parts = []
        labels = [l.text() for l in self._trans_labels + self._rot_labels]
        for name, txt in zip(labels, self._last_nudge):
            try:
                if float(txt) != 0:
                    parts.append(f"{name} {txt}")
            except ValueError:
                pass
        self._reapply_btn.setEnabled(True)
        self._reapply_btn.setToolTip(
            "Repeat the last nudge: " + (", ".join(parts) or "-"))

    def _toggle_info(self):
        self._info.set_html(self._info_html())
        self._info.toggle(self.main_win)

    def _info_html(self):
        import html
        full = html.escape(self.dm.get_full_path_name(self.uid))
        return (
            f"<p><b>Object</b><br>{full}</p>"
            "<p><b>Dynamic</b><br>Drag the gizmo's arrows to move or its "
            "rings to rotate. For exact values type them in the Nudge "
            "fields and press Apply Nudge; Re-Apply repeats the last "
            "nudge. Click in a field first, then use the calculator, to "
            "send it a value.</p>"
            "<p><b>Frame</b><br><i>World</i>: the gizmo at its default "
            "place, X/Y/Z. <i>Active Workplane</i>: the gizmo sits on the "
            "workplane's origin with its U/V/W, and stays there after "
            "each move, so repeated rotations about the same workplane "
            "axis need no re-aligning. Click it again to pick up a "
            "different active workplane.</p>"
            "<p><b>Mate Align</b><br><i>Mate</i>: bring two faces "
            "together, facing each other. <i>Align</i>: make two faces "
            "face the same way. <i>Align Axis</i>: line up two hole or "
            "cylinder axes (or pin two holes after a face mate). Up to "
            "three steps fix all six degrees of freedom; Reverse flips "
            "the last Mate/Align.</p>"
            "<p><b>2 Points</b><br>Moves the object by the vector from "
            "point 1 to point 2 (no rotation). The points may be "
            "workplane catches or part vertices.</p>"
            "<p><b>Back</b> undoes the last step of this session. "
            "<b>✔</b> finishes; <b>✖</b> closes (like the window's X) "
            "and keeps the moves already made; Ctrl+Z afterwards undoes "
            "the whole placement.</p>")

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
        self._step1_kind = None
        self._mated_normal = None
        self._step1_point = None
        self._step3_kind = None
        self._step2_wall_normal = None
        self._align_axis_pivot = None

    # -----------------------------------------------------------------
    # Constraint selection (starts picking)
    # -----------------------------------------------------------------

    def _on_constraint_chosen(self, mode):
        """Mate/Align/Align Axis radio chosen -- start the appropriate
        picking flow. Mate/Align: 'Having chosen to apply a Mate or
        Align constraint, the user will be prompted to click on a
        moving face and a fixed face.' Align Axis has two distinct
        roles, per Doug's original design:

        - At Step 1 (mate_align_step == 0): standalone -- align two
          cylindrical FACES directly ("a bolt in a hole"), 4 DOF at
          once. Matches Basicad's own architecture for this specific
          case.
        - At Step 2 (mate_align_step == 1): chained after a face mate
          -- pin two hole/circular-EDGE intersection points together,
          2 DOF. The PDF's "2nd option," distinct from Basicad's.

        Both leave exactly 2 more constraint-applications to reach
        fully-constrained (3 total either way -- see _record_step_
        success/_apply_align_axis_pin/_apply_align_axis_full for the
        DOF accounting)."""
        if not self._mate_align_btn.isChecked():
            self._mate_align_btn.setChecked(True)
        self._show_page(self._PAGE_MATE)

        if mode == "axis":
            if self._mate_align_step == 0:
                self._start_axis_face_picking()
                return
            elif self._mate_align_step == 1:
                self._start_axis_pin_picking()
                return
            else:
                self.main_win.statusBar().showMessage(
                    "Align Axis is only used as Step 1 (aligning two "
                    "cylindrical faces) or Step 2 (pinning holes after "
                    "mating a face).", 6000)
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
        use. Step 2 branches on _step1_kind (was Step 1 a normal face
        mate, or standalone Align Axis?); Step 3 branches on
        _step3_kind (was Step 2 a normal face-align, or a spin-leaving
        step -- either kind of Align Axis?)."""
        self.main_win.clearCallback()
        mate = (self._last_mode == "mate")
        step = self._mate_align_step

        if step == 0:
            move = position_math.compute_step1_move(self._pick1, self._pick2, mate=mate)
        elif step == 1:
            if self._step1_kind == "axis":
                move = position_math.compute_axis_step2_move(
                    self._pick1, self._pick2, self._step1_point,
                    self._mated_normal, mate=mate)
            else:
                move = position_math.compute_step2_move(
                    self._pick1, self._pick2, self._mated_normal, mate=mate)
        elif step == 2:
            if self._step3_kind == "spin":
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
    # Picking -- Align Axis, chained pin (circular edges / holes),
    # only valid as Step 2 -- Doug's original PDF design.
    # -----------------------------------------------------------------

    def _start_axis_pin_picking(self):
        self.main_win.canvas.detach_manipulator()
        self._picking_for = "mate_align"
        self._picking_kind = "circle"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._axis_pin_pick_callback)
        self.main_win.canvas._display.SetSelectionModeEdge()
        self.main_win.statusBar().showMessage(
            "Step 2 of 3 (Align Axis): pick a hole on the moving part.")

    def _axis_pin_pick_callback(self, shapeList, *args):
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
            self._pick1, self._pick2, self._mated_normal, self._step1_point)
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
                self._step1_point, N)
            self._step3_kind = "spin"
            self._mate_align_step = 2
            self.main_win.statusBar().showMessage(
                "Align Axis applied (step 2 of 3, 1 DOF left). "
                "Pick Mate or Align again for the final rotation.", 8000)
        self._update_ui_state()

    # -----------------------------------------------------------------
    # Picking -- Align Axis, standalone (cylindrical faces), only
    # valid as Step 1 -- Basicad's own architecture, matching the
    # PDF's "bolt in a hole" example.
    # -----------------------------------------------------------------

    def _start_axis_face_picking(self):
        self.main_win.canvas.detach_manipulator()
        self._picking_for = "mate_align"
        self._picking_kind = "cylinder"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._axis_face_pick_callback)
        self.main_win.canvas._display.SetSelectionModeFace()
        self.main_win.statusBar().showMessage(
            "Step 1 of 3 (Align Axis): pick a cylindrical face on the "
            "moving part (e.g. a bolt shaft).")

    def _axis_face_pick_callback(self, shapeList, *args):
        for shape in shapeList:
            try:
                face = TopoDS.Face_s(shape)
                pick = position_math.resolve_cylinder_pick(face)
            except Exception as e:
                print(f"[PositionDialog] pick was not a cylindrical face: {e}")
                self.main_win.statusBar().showMessage(
                    "Pick a cylindrical face, not that.", 4000)
                continue
            if self._pick1 is None:
                self._pick1 = pick
                self.main_win.statusBar().showMessage(
                    "Cylindrical face 1 picked. Pick face 2 (fixed, e.g. a hole).")
            else:
                self._pick2 = pick
                self._apply_align_axis_full()
                return

    def _apply_align_axis_full(self):
        """Align Axis as a standalone Step 1 (Basicad's own
        architecture for this specific case, matching Doug's "bolt in
        a hole" example): aligns 2 cylindrical faces directly,
        consuming 4 DOF (2 rotational + 2 translational) in one step.
        The remaining 2 DOF -- axial translation and spin -- are left
        for 2 more Align constraints (compute_axis_step2_move, then
        compute_step3_move's spin case -- the same spin case Align
        Axis's OTHER role, the chained pin, also leaves for Step 3)."""
        self.main_win.clearCallback()
        move = position_math.compute_align_axis_move(self._pick1, self._pick2)
        if move is None:
            self.main_win.statusBar().showMessage("Couldn't compute move -- try again.", 5000)
            return

        self._last_picks = (self._pick1, self._pick2)
        self._last_step_applied = 0
        self._last_step_kind = "axis"  # Reverse doesn't apply -- no mate/align choice here
        ok = self._apply_world_move(move)
        if ok:
            self._mated_normal = self._pick2.direction
            self._step1_point = self._pick2.point
            self._step1_kind = "axis"
            self._mate_align_step = 1
            self.main_win.statusBar().showMessage(
                "Align Axis applied (step 1 of 3, 2 DOF left). "
                "Pick Mate or Align to constrain the axial position.", 8000)
        self._update_ui_state()

    # -----------------------------------------------------------------
    # Picking -- 2 Points
    # -----------------------------------------------------------------

    def _start_two_points_picking(self):
        self.main_win.canvas.detach_manipulator()
        self._show_page(self._PAGE_TWO_POINTS)
        self._reset_mate_align_dof()
        self._picking_for = "two_points"
        self._pick1 = None
        self._pick2 = None
        self.main_win.registerCallback(self._point_pick_callback)
        self.main_win.canvas._display.SetSelectionModeVertex()
        self.main_win.statusBar().showMessage("Pick point 1 (need not be on the part).")

    def _point_pick_callback(self, shapeList, *args):
        """Session 75, Doug's report: workplane points highlighted
        (the snap-engine catch glyph) but were never acknowledged --
        this callback only ever handled a genuine 3D TopoDS_Vertex
        from OCCT's own selection. A workplane catch point
        (intersection, endpoint, Ctrl+Shift center/midpoint) is a
        snap-engine construct, not necessarily backed by any real
        TopoDS_Vertex at all -- the downcast below would silently
        fail (or shapeList would be empty) and nothing ever advanced
        the tool, even though the glyph correctly showed a valid
        catch. Same bug class as distPtPtC's own original gap
        (Session 63), fixed the identical way: ENGINE PATH FIRST --
        a workplane catch becomes a world point via uv_to_world; the
        3D vertex pick remains as fallback, so a workplane catch and
        a part vertex can be used as the two points interchangeably,
        matching distPtPtC's own established precedent exactly."""
        from OCP.BRep import BRep_Tool
        pt = None
        # 1. Engine path: catch on the active workplane
        try:
            click_xy = args[1] if len(args) > 1 else None
            wp = self.main_win.activeWp
            if (click_xy is not None and click_xy[0] is not None
                    and wp is not None):
                from snap_engine import (screen_to_uv, find_snap,
                                         uv_to_world, SNAP_PIXELS,
                                         current_snap_mode)
                uv = screen_to_uv(self.main_win.canvas.view,
                                  click_xy[0], click_xy[1], wp.gpPlane)
                if uv is not None:
                    try:
                        tol = abs(self.main_win.canvas.view.Convert(
                            SNAP_PIXELS))
                    except Exception:
                        tol = 1.0
                    hidden = (self.main_win.activeWpUID
                             in self.main_win.hide_list)
                    snap = find_snap(wp, uv, tol, current_snap_mode(),
                                     hidden=hidden)
                    if snap is not None:
                        pt = uv_to_world(wp.gpPlane, snap[1][0],
                                         snap[1][1])
        except Exception as se:
            print(f"[PositionDialog] engine path failed: {se}")
        # 2. Fallback: a genuine 3D vertex pick
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
            self.main_win.statusBar().showMessage(
                "No catch or vertex there -- click a workplane catch "
                "or a part vertex.", 3000)
            return
        if self._pick1 is None:
            self._pick1 = position_math.Vec3.from_gp(pt)
            self.main_win.statusBar().showMessage(
                "Point 1 picked. Pick point 2.")
        else:
            self._pick2 = position_math.Vec3.from_gp(pt)
            self._apply_two_points()

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
        self._show_page(self._PAGE_DYNAMIC)
        self._reset_mate_align_dof()
        self._picking_for = "dynamic"
        # (re)starting Dynamic applies the Frame row's choice: World =
        # default gizmo; Active Workplane = a fresh snapshot of the
        # CURRENT active workplane (re-attached below).
        self._frame = None
        if self._frame_wp_rb.isChecked():
            self._frame = self._read_active_wp_frame()
            if self._frame is None:
                self._frame_world_rb.setChecked(True)
        self._set_nudge_labels()
        if self._reattach_manipulator():
            self.main_win.statusBar().showMessage(
                "Drag an arrow to translate or a ring to rotate.")
        else:
            self.main_win.statusBar().showMessage(
                "Could not attach manipulator -- see console.", 5000)

    def _read_active_wp_frame(self):
        """(origin_xyz, w_xyz, u_xyz) of the active workplane, or None
        (with a status-bar message) if there is none / it can't be
        read."""
        wp = self.main_win.activeWp
        if wp is None:
            self.main_win.statusBar().showMessage(
                "No active workplane -- select or create one first.",
                5000)
            return None
        try:
            uid = getattr(self.main_win, "activeWpUID", 0)
            self._frame_name = (self.main_win._wp_display_name(uid)
                                if uid else "")
        except Exception:
            self._frame_name = ""
        try:
            ax3 = wp.gpPlane.Position()
            loc = ax3.Location()
            w_dir = ax3.Direction()
            u_dir = ax3.XDirection()
            return ((loc.X(), loc.Y(), loc.Z()),
                    (w_dir.X(), w_dir.Y(), w_dir.Z()),
                    (u_dir.X(), u_dir.Y(), u_dir.Z()))
        except Exception as e:
            self.main_win.statusBar().showMessage(
                f"Could not read the workplane's frame ({e}).", 5000)
            return None

    def _on_frame_chosen(self, _index=0):
        """The user clicked an entry in the Frame row (Session 76's
        'Align Gizmo to Active Workplane' button, promoted)."""
        if self.main_win.canvas.manipulator_position() is None:
            self.main_win.statusBar().showMessage(
                "No manipulator attached -- select Dynamic first.", 5000)
            return
        if self._frame_wp_rb.isChecked():
            fr = self._read_active_wp_frame()
            if fr is None:
                self._frame_world_rb.setChecked(True)
                self._frame = None
                self._set_nudge_labels()
                return
            if self.main_win.canvas.reposition_manipulator(*fr):
                self._frame = fr               # sticky snapshot
                self._set_nudge_labels()
                self.main_win.statusBar().showMessage(
                    "Gizmo placed on the active workplane and it stays "
                    "there -- rW (the 3rd rotation) turns about the "
                    "workplane's own normal. Choose World to release "
                    "it.", 6000)
            else:
                self.main_win.statusBar().showMessage(
                    "Could not align the gizmo -- see console.", 5000)
        else:
            self._frame = None
            self._reattach_manipulator()       # default place again
            self._set_nudge_labels()
            self.main_win.statusBar().showMessage(
                "Gizmo back at its default place (World axes).", 5000)

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
        ok = self.main_win.canvas.attach_manipulator(
            leaf_shapes, move_callback=self._on_manip_move,
            done_callback=self._on_manip_done)
        if ok and self._frame is not None:
            # sticky frame: put the gizmo back on the workplane
            if not self.main_win.canvas.reposition_manipulator(*self._frame):
                print("[position] could not re-apply the sticky frame")
        return ok

    def _set_nudge_labels(self):
        """Nudge fields are in world X/Y/Z, or in the sticky frame's
        U/V/W once the gizmo has been aligned to a workplane."""
        if self._frame is not None:
            t, r = ("dU", "dV", "dW"), ("rU\u00b0", "rV\u00b0", "rW\u00b0")
        else:
            t, r = ("dX", "dY", "dZ"), ("rX\u00b0", "rY\u00b0", "rZ\u00b0")
        for lab, txt in zip(self._trans_labels, t):
            lab.setText(txt)
        for lab, txt in zip(self._rot_labels, r):
            lab.setText(txt)
        if self._frame is not None:
            # the name of the workplane the frame was TAKEN from (the
            # active workplane may have changed since)
            self._frame_wp_label.setText(self._frame_name)
        else:
            self._frame_wp_label.setText("")

    def _on_manip_move(self, delta_trsf):
        """Live status update during a drag. Translation distance only
        (not rotation angle) -- keeps this to APIs already proven
        elsewhere in this codebase (TranslationPart().X/Y/Z()) rather
        than guessing at gp_Trsf's rotation-extraction signature."""
        tp = delta_trsf.TranslationPart()
        dist = (tp.X() ** 2 + tp.Y() ** 2 + tp.Z() ** 2) ** 0.5
        if dist > 1e-6:
            # Session 155: report in the user's units (internal is mm)
            mw = self.main_win
            scale = getattr(mw, "unitscale", 1.0) or 1.0
            units = getattr(mw, "units", "mm")
            places = {"mm": 2, "in": 3, "ft": 4}.get(units, 3)
            mw.statusBar().showMessage(
                f"Dragging: {dist / scale:.{places}f} {units} from start.")
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
        nudge_texts = tuple(f.text() for f in self._nudge_fields())

        # Convert translation from the user's displayed units into mm
        # (Kodacad's internal storage unit) -- the same convention
        # every other numeric entry point in the app already follows
        # (extrude, mill, pull, fillet, shell, all 2D sketch entry):
        # "(user input values) * unitscale = value in mm" (see
        # mainwindow.py). CONFIRMED MISSING here directly: Doug
        # switched to inches, typed 0.75 (meaning 3/4"), and the part
        # moved 0.75 MM instead. Rotation values are in degrees and
        # unit-independent -- correctly left alone.
        unitscale = self.main_win.unitscale
        dx *= unitscale
        dy *= unitscale
        dz *= unitscale

        import math
        from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir
        from OCP.TopLoc import TopLoc_Location

        # Rotations pivot about the MANIPULATOR's current position --
        # the white dot at the gizmo's center, which is where the user
        # visually expects the part to spin (Session 55: Doug nudged
        # RX 90 and the part orbited away in the Y-Z plane instead of
        # spinning in place). The gizmo sits at the attached object's
        # geometric center; the part's LOCAL ORIGIN -- the previous
        # pivot -- can be arbitrarily far from the geometry on
        # vendor-authored parts, turning an intended in-place spin
        # into an orbit about a distant point.
        # Fallback: the part's world location (better than the global
        # origin, still correct for parts whose origin is at/near
        # their geometry). Captured BEFORE detach_manipulator() below.
        current_world = self.dm.get_world_loc(self.uid)
        manip_pnt = self.main_win.canvas.manipulator_position()
        if manip_pnt is not None:
            pivot_pnt = gp_Pnt(manip_pnt.X(), manip_pnt.Y(), manip_pnt.Z())
            pivot_src = "manipulator"
        else:
            pivot = current_world.Transformation().TranslationPart()
            pivot_pnt = gp_Pnt(pivot.X(), pivot.Y(), pivot.Z())
            pivot_src = "part world loc (no manipulator attached)"

        # Rotation AXES: the manipulator's OWN current X/Y/Z when one
        # is attached (Session 76, Doug: reposition the gizmo to a
        # workplane's origin/U/V/W via the new 'Align to Workplane'
        # button, then Nudge should genuinely rotate about THOSE
        # axes -- not always world X/Y/Z, which is all the pivot-only
        # fix above ever gave: correct PIVOT LOCATION, but rZ would
        # still spin about world Z regardless of the gizmo's actual
        # orientation, silently wrong for any tilted workplane).
        # Falls back to world X/Y/Z when no manipulator is attached,
        # matching this function's own prior, unchanged behavior for
        # that case.
        axes = self.main_win.canvas.manipulator_axes()
        if axes is not None:
            _origin, x_xyz, y_xyz, z_xyz = axes
            axis_x, axis_y, axis_z = (gp_Dir(*x_xyz), gp_Dir(*y_xyz),
                                      gp_Dir(*z_xyz))
        else:
            axis_x, axis_y, axis_z = (gp_Dir(1, 0, 0), gp_Dir(0, 1, 0),
                                      gp_Dir(0, 0, 1))

        # Compose in a fixed order: rotate about X, then Y, then Z
        # (all at the pivot), then translate. Simultaneous multi-axis
        # rotation is inherently order-dependent (there's no single
        # "correct" order) -- fine for a nudge, which is typically one
        # axis at a time, but worth knowing if two angles are entered
        # together and the result isn't what was expected.
        combined = gp_Trsf()
        if rx or ry or rz:
            print(f"[nudge] rotation pivot: ({pivot_pnt.X():.3f}, "
                  f"{pivot_pnt.Y():.3f}, {pivot_pnt.Z():.3f}) via {pivot_src}")
        for axis_dir, angle_deg in ((axis_x, rx),
                                    (axis_y, ry),
                                    (axis_z, rz)):
            if angle_deg == 0:
                continue
            t = gp_Trsf()
            t.SetRotation(gp_Ax1(pivot_pnt, axis_dir), math.radians(angle_deg))
            combined = t.Multiplied(combined)
        if dx or dy or dz:
            t = gp_Trsf()
            if self._frame is not None and axes is not None:
                # sticky frame: dU/dV/dW run along the gizmo's own axes
                vec = gp_Vec(
                    dx * x_xyz[0] + dy * y_xyz[0] + dz * z_xyz[0],
                    dx * x_xyz[1] + dy * y_xyz[1] + dz * z_xyz[1],
                    dx * x_xyz[2] + dy * y_xyz[2] + dz * z_xyz[2])
            else:
                vec = gp_Vec(dx, dy, dz)    # world axes, as before
            t.SetTranslation(vec)
            combined = t.Multiplied(combined)

        move = TopLoc_Location(combined)
        self.main_win.canvas.detach_manipulator()
        ok = self._apply_world_move(move)
        if ok:
            for field in (self._nudge_dx, self._nudge_dy, self._nudge_dz,
                         self._nudge_rx, self._nudge_ry, self._nudge_rz):
                field.setText("0")
            self._last_nudge = nudge_texts
            self._update_reapply()
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

        old_uids = set(self.dm.part_dict.keys())
        new_uid = self.dm.set_component_location(self.uid, new_local)
        if new_uid is None:
            self.main_win.statusBar().showMessage(
                "Position failed -- see console.", 5000)
            return False

        self._history.append(current_local)
        self.uid = new_uid
        self._refresh_display(old_uids)
        return True

    def _refresh_display(self, old_uids=None):
        """Session 77, Doug: full redraws (RemoveAll + redraw every
        part in the document) were tedious on a large assembly, and
        every Nudge/manipulator-release/Mate/Align went through this
        exact path -- Doug specifically noticed 'Done' does NOT
        redraw, which was the tell that each of these calls its own
        refresh separately rather than something the dialog forces
        generally.

        set_component_location() (called by every path that reaches
        here) always assigns the MOVED component a fresh uid on every
        call -- confirmed via its own docstring -- so the moved item
        itself is always genuinely new to _incremental_reconcile's
        own old/new uid diff. BUT: if self.uid is an ASSEMBLY (Doug's
        own stated use case last session -- 'I have an assembly which
        I want to rotate'), only the assembly's OWN component label
        gets replaced; its CHILDREN keep their original uids, since
        their own labels were never touched -- only their ANCESTOR's
        location changed. Their computed world position genuinely
        changes (parse_doc() correctly recomputes it), but under the
        default fast path a surviving uid is skipped, not redrawn --
        every child of a moved assembly would go stale on screen.
        Caught and fixed before shipping, not discovered as a bug
        report: redraw_all_survivors=True is required whenever the
        moved item is an assembly; the plain-leaf-part case (provably
        safe per set_component_location's own docstring -- other
        instances of a shared part are untouched) keeps the fast,
        default path.

        old_uids must be snapshotted by the CALLER, immediately
        before its own set_component_location() call -- by the time
        this method runs, dm.part_dict already reflects the NEW state
        (set_component_location calls parse_doc() internally), so
        snapshotting here would already be too late."""
        if old_uids is not None:
            self.main_win.build_tree()
            # Session 77 (real regression, caught by Doug's own
            # timing data, not guessed): redraw_all_survivors=True
            # was the WRONG tool here -- it redraws the ENTIRE
            # document (95 parts, 15-20+ seconds measured), not just
            # the moved assembly's own descendants (4 parts). Only
            # those descendants actually need it: their world
            # position changed via their ancestor, but their own uid
            # never did, so they're survivors the default rule would
            # otherwise (correctly, for everything else) skip.
            # get_descendant_part_uids is the same method
            # _reattach_manipulator already uses to find exactly this
            # set.
            force = set(self.dm.get_descendant_part_uids(self.uid))
            # Session 87, Doug: moving a component nested inside a
            # SHARED parent (e.g. nut-bolt-assembly_1 within l-bracket-
            # assembly, itself shared by l-bracket-assembly_1/_2)
            # correctly propagates in the document data -- confirmed,
            # deliberate behavior since Session 31 -- but the OTHER
            # occurrence never visibly moved, because this default
            # path's own comment assumed (citing set_component_
            # location's docstring, now stale for this exact case)
            # that other shared instances are always untouched.
            # dm._shared_parent_moves records the shared parent's own
            # entry whenever set_component_location's parent-
            # resolution logic actually took the shared-propagation
            # branch (mirrors dm._shape_replaced_entries, the proven
            # signal for the identical shape of bug in fillet/shell
            # propagation). Resolve each recorded entry to every
            # CURRENT sibling sharing that same parent, force-redraw
            # each one, and its own descendants too in case that
            # sibling is itself an assembly.
            shared_parent_moves = getattr(
                self.dm, '_shared_parent_moves', [])
            for parent_entry in shared_parent_moves:
                for u, info in self.dm.label_dict.items():
                    p_uid = info.get('parent_uid')
                    p_info = self.dm.label_dict.get(p_uid, {})
                    p_entry = p_info.get('ref_entry') or p_info.get('entry')
                    if p_entry == parent_entry:
                        force.add(u)
                        force |= set(
                            self.dm.get_descendant_part_uids(u))
            self.dm._shared_parent_moves = []
            self.main_win._incremental_reconcile(
                old_uids, force_redraw_uids=force)
        else:
            # Defensive fallback for any caller that doesn't (yet)
            # pass a snapshot -- correct, just not the fast path.
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
        old_uids = set(self.dm.part_dict.keys())
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
            self._step1_point = None
            self._step1_kind = None
        elif step == 1:
            self._step2_wall_normal = None
        self._refresh_display(old_uids)

        self._last_mode = "align" if self._last_mode == "mate" else "mate"
        pick1, pick2 = self._last_picks
        mate = (self._last_mode == "mate")
        if step == 0:
            move = position_math.compute_step1_move(pick1, pick2, mate=mate)
        elif step == 1:
            if self._step1_kind == "axis":
                move = position_math.compute_axis_step2_move(
                    pick1, pick2, self._step1_point, self._mated_normal, mate=mate)
            else:
                move = position_math.compute_step2_move(
                    pick1, pick2, self._mated_normal, mate=mate)
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
        """After successfully applying Mate/Align step 0/1 via the
        FACE-picking path (step 0: normal face mate; step 1: normal
        face-align OR the axial-translate step after standalone Align
        Axis -- both go through _apply_mate_align/_face_pick_callback).
        Align Axis's OWN two entry points (_apply_align_axis_pin,
        _apply_align_axis_full) record their own bookkeeping directly,
        since it differs enough not to fit this shared shape. Shared
        by _apply_mate_align and _on_reverse so the bookkeeping can't
        drift between the two."""
        if step == 0:
            self._mated_normal = (-self._last_picks[1].direction if mate
                                  else self._last_picks[1].direction)
            self._step1_point = self._last_picks[0].point
            self._step1_kind = "face"
        elif step == 1:
            if self._step1_kind == "axis":
                # Step 1 was standalone Align Axis -- this step just
                # closed the axial gap, leaving only spin for Step 3.
                self._step3_kind = "spin"
                self._align_axis_pivot = self._step1_point
            else:
                self._step3_kind = "wall"
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
        old_uids = set(self.dm.part_dict.keys())
        new_uid = self.dm.set_component_location(self.uid, prev_local)
        if new_uid is not None:
            self.uid = new_uid
            self._refresh_display(old_uids)
            self.main_win.statusBar().showMessage("Step undone.", 5000)
            # Step the DOF tracker backward too, clearing whatever
            # that step had established for the NEXT step to use --
            # covers all paths (only the relevant variables for
            # whichever path was actually taken would ever be set,
            # safe to clear all of them regardless).
            if self._mate_align_step > 0:
                self._mate_align_step -= 1
                if self._mate_align_step == 1:
                    self._step3_kind = None
                    self._step2_wall_normal = None
                    self._align_axis_pivot = None
                elif self._mate_align_step == 0:
                    self._step1_kind = None
                    self._mated_normal = None
                    self._step1_point = None
        self._last_picks = None
        self._last_step_applied = None
        self._last_step_kind = None
        if was_dynamic:
            self._reattach_manipulator()
        self._update_ui_state()

    def _commit_position_txn(self):
        """Commit the session-wide transaction (option (b)). Called
        from Done AND from closeEvent (closing via X keeps what the
        user sees on screen -- committing preserves it; an empty
        command commits to nothing). Idempotent via _txn_open."""
        if getattr(self, "_txn_open", False):
            try:
                self.dm.doc.CommitCommand()
            except Exception as e:
                print(f"[position] commit failed: {e}")
            self._txn_open = False

    def _on_done(self):
        self._commit_position_txn()
        self.main_win.clearCallback()
        self.main_win.canvas.detach_manipulator()
        self.main_win.statusBar().showMessage("Position complete.", 5000)
        self.close()

    def closeEvent(self, event):
        if self._info is not None:
            try:
                self._info.hide()
                self._info.deleteLater()
            except Exception:
                pass
            self._info = None
        self._commit_position_txn()
        self.main_win.clearCallback()
        self.main_win.canvas.detach_manipulator()
        super().closeEvent(event)
