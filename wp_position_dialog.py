"""
wp_position_dialog.py

THE WORKPLANE POSITION DIALOG -- per Doug's own proposal
(wp-position.md): a separate dialog from PositionDialog
(position_dialog.py), for repositioning an EXISTING workplane rather
than a part/assembly. Deliberately started with just one of the five
proposed methods -- On Face -- Doug's own, explicit choice to "pave
the way with something basic" before adding the other four (2 Points,
Dynamic, By Point & Direction, 3 Points).

WHY On Face FIRST: unlike 2 Points or Dynamic, which the proposal
describes as working "just like it does for parts/assemblies," On
Face needed no new positioning math at all. workplane.py's own
WorkPlane class already has a face=/faceU= construction path (origin
at the first face's own center of mass, W along its normal, U along a
second face's normal) -- proven, existing code, already used today by
wpOnFace()/wpOnFaceC() in kodacad.py whenever a NEW workplane gets
created this way. Parts/assemblies, by contrast, are OCAF labels;
PositionDialog's own _apply_world_move() is built entirely around
that (dm.label_dict, dm.set_component_location(), ...) and doesn't
apply to a workplane at all, which isn't an OCAF label -- it's a
plain Python object living in win.wp_dict.

REPOSITIONING MODEL: in-place mutation of the existing WorkPlane
object's own positional attributes -- NOT build-a-new-object-and-
replace-it, which an earlier version of this file did, and which
Doug found loses all of the workplane's own sketch geometry (a
rectangle, a circle, an arc) on the first real test. Root cause: a
brand new WorkPlane's own __init__ always regenerates its own default
H&V construction lines from scratch -- they only LOOKED like they'd
survived the reposition; nothing actually had.

The fix follows Doug's own paper analogy directly: a 2D picture in
indelible ink, moved from a table to a wall. Everything stays exactly
where it is relative to the paper's own edges, origin, and U/V axes;
only the paper's position in the room changes. Two different kinds of
"ink" here, needing two different treatments:

  - construction geometry (clines/ccircs/carcs/csegs) is stored as
    plane-relative (u,v) coefficients, never baked into world space
    at all -- left completely untouched. Automatically correct under
    the new plane, no work needed.
  - profile geometry (edgeList) is the opposite: each TopoDS_Edge was
    built by transforming a local (u,v) point through self.Trsf AT
    CREATION TIME (see line()/rect()/circle()/arcc2p()/arc3p()) --
    the (u,v) itself is never stored afterward, only the resulting
    world-space edge, so it can't be read back directly. Recovered by
    composing a single delta transform (new_trsf applied after
    old_trsf's own inverse) and applying it directly to each existing
    edge -- mathematically the same as recovering (u,v) and
    re-applying the new transform, without needing (u,v) as an
    explicit intermediate value.

A workplane's own tree identity (its name, which lives on the tree
item's own text, not on the WorkPlane object itself) was never at
risk either way, mutation or replacement -- this dialog never touches
the tree at all.

NO UNDO INTEGRATION: workplanes aren't part of dm's OCAF-based undo
system today -- wpOnFace() itself doesn't open a transaction either.
Repositioning matches that same, existing behavior rather than
introducing undo support inconsistently for just this one workplane
operation.
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QButtonGroup,
    QRadioButton,
    QGroupBox,
)
from PySide6.QtGui import QFont

from OCP.TopoDS import TopoDS
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

import workplane


class WpPositionDialog(QDialog):
    def __init__(self, main_win, uid, name):
        super().__init__(main_win)
        self.main_win = main_win
        self.uid = uid
        self.name = name

        self._picking_for = None    # 'on_face' while that method is active
        self._face1 = None          # first picked face (defines the plane)

        self.setWindowTitle("Position Workplane")
        self._build_ui()

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # TOP: workplane name, bold -- per Doug's own proposal.
        name_label = QLabel(self.name)
        bold = QFont()
        bold.setBold(True)
        name_label.setFont(bold)
        self._name_label = name_label
        layout.addWidget(QLabel("Moving workplane:"))
        layout.addWidget(name_label)

        # METHODS -- just On Face for now; the other four (2 Points,
        # Dynamic, By Point & Direction, 3 Points) join this same
        # QButtonGroup later, each with its own _start_X_picking().
        methods_box = QGroupBox("Methods")
        methods_layout = QVBoxLayout(methods_box)
        self._method_group = QButtonGroup(self)
        self._on_face_btn = QRadioButton("On Face")
        self._on_face_btn.setToolTip(
            "Pick a face -- the workplane's origin lands on its "
            "geometric center, with W along its normal. Then pick a "
            "second face whose normal sets the U direction.")
        self._method_group.addButton(self._on_face_btn, 0)
        methods_layout.addWidget(self._on_face_btn)
        layout.addWidget(methods_box)

        # BOTTOM: Done only for now (per Doug's own proposal, a Back
        # button matters once there's a gizmo/preview to step back
        # from -- On Face applies immediately on the second face pick,
        # with nothing in progress to reverse).
        self._done_btn = QPushButton("\u2705 Done")
        layout.addWidget(self._done_btn)

        # clicked, not toggled (position_dialog.py's own established
        # reason): toggled only fires on an actual state change, so
        # re-clicking On Face while it's already selected -- to
        # restart the pick sequence after a mistaken first pick --
        # would silently do nothing with toggled.
        self._on_face_btn.clicked.connect(self._start_on_face_picking)
        self._done_btn.clicked.connect(self._on_done)

    # -----------------------------------------------------------------
    # On Face
    # -----------------------------------------------------------------

    def _start_on_face_picking(self):
        self._picking_for = "on_face"
        self._face1 = None
        self.main_win.registerCallback(self._on_face_pick_callback)
        self.main_win.canvas._display.SetSelectionModeFace()
        self.main_win.statusBar().showMessage(
            f"Select a face for '{self.name}'s own plane.")

    def _on_face_pick_callback(self, shapeList, *args):
        for shape in shapeList:
            try:
                face = TopoDS.Face_s(shape)
            except Exception:
                continue
            if self._face1 is None:
                self._face1 = face
                self.main_win.statusBar().showMessage(
                    f"Select a face for '{self.name}'s U direction.")
            else:
                self._apply_on_face(self._face1, face)
                return

    def _apply_on_face(self, faceW, faceU):
        self.main_win.clearCallback()
        if self.uid not in self.main_win.wp_dict:
            self.main_win.statusBar().showMessage(
                f"'{self.name}' is no longer available.", 5000)
            return
        old_wp = self.main_win.wp_dict[self.uid]
        old_trsf = old_wp.Trsf  # local (u,v) -> world, BEFORE reposition

        # A throwaway WorkPlane, built purely to compute the new
        # gpPlane/Trsf/origin/uDir/vDir/wDir via the SAME, proven
        # constructor math wpOnFace() already uses -- never displayed
        # or kept itself, just a source of correctly-computed
        # positional attributes to copy onto the EXISTING object.
        try:
            scratch = workplane.WorkPlane(
                old_wp.size, face=faceW, faceU=faceU)
        except Exception as e:
            self.main_win.statusBar().showMessage(
                f"Could not build a workplane from those faces: {e}",
                5000)
            return

        # Doug's own report: an earlier version replaced the
        # WorkPlane object entirely, discarding all its own sketch
        # geometry (his rectangle, circle, arc) -- the H&V
        # construction lines only LOOKED like they survived, since
        # __init__ regenerates those fresh for every new WorkPlane
        # regardless. Fixed by mutating the EXISTING object's own
        # positional attributes in place instead of replacing it --
        # Doug's own paper analogy: a 2D picture in indelible ink,
        # moved from table to wall. Everything stays exactly where it
        # was relative to the paper's own edges/origin/U/V; only the
        # paper's position in the room changes.
        #
        #   - construction geometry (clines/ccircs/carcs/csegs) is
        #     stored as plane-relative (u,v) coefficients, never
        #     baked into world space -- left completely untouched,
        #     automatically correct under the new plane (the "ink"
        #     never needed to move relative to the "paper" at all).
        #   - profile geometry (edgeList) is the opposite: each
        #     TopoDS_Edge was built by transforming a local (u,v)
        #     point through self.Trsf AT CREATION TIME -- the (u,v)
        #     itself isn't stored anywhere afterward, only the
        #     resulting world-space edge. Recovering it means undoing
        #     the OLD transform (world -> old local (u,v)) and then
        #     re-applying the NEW one ((u,v) -> new world) -- a single
        #     composed delta, new_trsf after old_trsf-inverse, applied
        #     directly to the existing edge without ever extracting
        #     (u,v) as an intermediate value.
        old_wp.gpPlane = scratch.gpPlane
        old_wp.plane = scratch.plane
        old_wp.Trsf = scratch.Trsf
        old_wp.origin = scratch.origin
        old_wp.uDir = scratch.uDir
        old_wp.vDir = scratch.vDir
        old_wp.wDir = scratch.wDir
        old_wp.wVec = scratch.wVec
        old_wp.face = scratch.face

        delta = old_wp.Trsf.Multiplied(old_trsf.Inverted())
        new_edges = []
        for edge in old_wp.edgeList:
            try:
                moved = BRepBuilderAPI_Transform(
                    edge, delta, True).Shape()
                new_edges.append(TopoDS.Edge_s(moved))
            except Exception as e:
                print(f"[WpPositionDialog] failed to re-transform "
                     f"an edge: {e}")
                new_edges.append(edge)  # keep it rather than lose it
        old_wp.edgeList = new_edges

        # Creo behavior (Session 63's own precedent, wpOnFace()):
        # pane sized to the picked face + margins, floored there.
        try:
            old_wp.seed_min_bounds_from_face(faceW)
        except Exception as e:
            print(f"[WpPositionDialog] seed_min_bounds_from_face "
                 f"failed: {e}")

        # win.activeWp is a SEPARATE, cached reference to the actual
        # WorkPlane object -- not an issue here (old_wp IS still the
        # object win.activeWp would already be pointing at, since
        # nothing got replaced), but kept explicit for clarity.
        if self.uid == self.main_win.activeWpUID:
            self.main_win.activeWp = old_wp
        self.main_win.draw_wp(self.uid)  # already erase-before-redraw
        self.main_win.statusBar().showMessage(
            f"'{self.name}' repositioned.", 5000)

    # -----------------------------------------------------------------
    # Done / close
    # -----------------------------------------------------------------

    def _on_done(self):
        self.main_win.clearCallback()
        self.close()

    def closeEvent(self, event):
        self.main_win.clearCallback()
        event.accept()
