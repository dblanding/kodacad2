#!/usr/bin/env python
#
# Copyright 2022 Doug Blanding (dblanding@gmail.com)
#
# This file is part of kodacad2.
# Licensed under the GNU General Public License v3 -- see LICENSE.
#


import logging
import math
import pprint
import sys

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.BRepAlgoAPI import (BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse,
                             BRepAlgoAPI_Defeaturing)
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform
from OCP.BRepFilletAPI import (BRepFilletAPI_MakeFillet,
                               BRepFilletAPI_MakeChamfer)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepOffsetAPI import (BRepOffsetAPI_MakeThickSolid,
                               BRepOffsetAPI_ThruSections)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.gp import gp_Ax1, gp_Ax3, gp_Dir, gp_Lin, gp_Pnt, gp_Trsf, gp_Vec
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Face, TopoDS_Vertex
from OCP.TopTools import TopTools_ListOfShape
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE

from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QPushButton,
                               QTreeWidgetItemIterator, QVBoxLayout)

from m2d import M2D
import stepanalyzer
import docmodel
from mainwindow import MainWindow, dm
from OCCUtils import Topology
import workplane
from workplane import face_normal
import isolated_features

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # set to DEBUG | INFO | ERROR

TOL = 1e-7  # Linear Tolerance
ATOL = TOL  # Angular Tolerance
print("TOLERANCE = ", TOL)
# DEFAULT_COLOR = Quantity_ColorRGBA(0.6, 0.6, 0.4, 1.0)
DEFAULT_COLOR = Quantity_Color(0.6, 0.6, 0.4, Quantity_TypeOfColor.Quantity_TOC_RGB)


#############################################
#
# Workplane creation functions
#
#############################################


def wpBy3Pts(*args):
    """3 points define the new workplane (Session 129, Doug's own
    request -- Workplane Sets/Loft surfaced a real need to build
    precise workplane "scaffolding" off a non-block-shaped part, and
    this method was the natural one to improve for it):

        point 1 -> origin of the new workplane
        point 2 -> sets the +W direction (origin -> pt2)
        point 3 -> sets the +U direction (origin -> pt3)

    (Previously: pt1->pt2 set wDir, pt2 was the origin, pt2->pt3 set
    uDir -- changed to this origin-first ordering per Doug's explicit
    request, a cleaner match for how the 3 picks are actually used.)

    Each of the 3 points may be EITHER a genuine 3D vertex on a part
    OR a catch (endpoint, intersection, Ctrl+Shift center/midpoint) on
    the ACTIVE workplane's own 2D sketch -- see wpBy3PtsC, which tries
    the workplane-catch path first and falls back to a 3D vertex pick,
    the same established pattern wpByPtDirC and position_dialog.py's
    own _point_pick_callback already use, now extended here to all 3
    picks (previously vertex-only) so a new workplane can be built
    from scaffolding sketched on the current workplane, points on the
    3D part, or a mix of both."""

    prev_uid = win.activeWpUID  # uid of currently active workplane
    if win.ptStack:
        # Finish
        p3 = win.ptStack.pop()
        p2 = win.ptStack.pop()
        p1 = win.ptStack.pop()
        origin = p1
        wDir = gp_Dir(gp_Vec(p1, p2))
        uDir = gp_Dir(gp_Vec(p1, p3))
        axis3 = gp_Ax3(origin, wDir, uDir)
        wp = workplane.WorkPlane(100, ax3=axis3)
        new_uid = win.get_wp_uid(wp)
        display_new_active_wp(prev_uid, new_uid)
        win.clearCallback()
    else:
        # Initial setup
        win.registerCallback(wpBy3PtsC)
        display.selected_shape = None
        display.SetSelectionModeVertex()
        statusText = ("Pick point 1 (new workplane's origin) -- a "
                     "part vertex or a catch on the active workplane.")
        win.statusBar().showMessage(statusText)
        return


def wpBy3PtsC(shapeList, *args):
    """Callback (collector) for wpBy3Pts. Each pick tries the active
    workplane's own 2D sketch FIRST -- a snap-engine catch (endpoint,
    intersection, Ctrl+Shift center/midpoint) turned into a world
    point via uv_to_world -- falling back to a genuine 3D vertex pick
    if there's no catch there. Same engine-path-first/vertex-fallback
    order as wpByPtDirC / position_dialog.py's own
    _point_pick_callback (Session 129: previously this callback only
    ever accepted a 3D vertex, for all 3 picks)."""

    pt = None
    # 1. Engine path: catch on the active workplane
    try:
        click_xy = args[1] if len(args) > 1 else None
        wp = win.activeWp
        if (click_xy is not None and click_xy[0] is not None
                and wp is not None):
            from snap_engine import (screen_to_uv, find_snap,
                                     uv_to_world, SNAP_PIXELS,
                                     current_snap_mode)
            uv = screen_to_uv(win.canvas.view, click_xy[0],
                              click_xy[1], wp.gpPlane)
            if uv is not None:
                try:
                    tol = abs(win.canvas.view.Convert(SNAP_PIXELS))
                except Exception:
                    tol = 1.0
                hidden = win.activeWpUID in win.hide_list
                snap = find_snap(wp, uv, tol, current_snap_mode(),
                                 hidden=hidden)
                if snap is not None:
                    pt = uv_to_world(wp.gpPlane, snap[1][0],
                                     snap[1][1])
    except Exception as e:
        print(f"[wpBy3PtsC] engine path failed: {e}")
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
        win.statusBar().showMessage(
            "No catch or vertex there -- click a workplane catch or "
            "a part vertex.", 3000)
        return

    win.ptStack.append(pt)
    if len(win.ptStack) == 1:
        statusText = "Now pick point 2 to set the +W direction."
        win.statusBar().showMessage(statusText)
    elif len(win.ptStack) == 2:
        statusText = "Now pick point 3 to set the +U direction."
        win.statusBar().showMessage(statusText)
    elif len(win.ptStack) == 3:
        wpBy3Pts()


def wpByPtDir(*args):
    """Point & Direction workplane (Session 63, Doug's 4th mode):
    1. Click a point -> origin. 2. Click a face -> +W direction.
    3. Click another face -> +U direction. Reuses the same ax3=
    constructor path as wpBy3Pts -- only the inputs differ (a
    picked point instead of derived-from-3-points, face normals
    instead of point-to-point vectors)."""

    prev_uid = win.activeWpUID
    if win.faceStack and len(win.faceStack) >= 2 and win.ptStack:
        # Finish
        origin = win.ptStack.pop()
        faceU = win.faceStack.pop()
        faceW = win.faceStack.pop()
        wDir = face_normal(faceW)
        uDir = face_normal(faceU)
        axis3 = gp_Ax3(origin, wDir, uDir)
        wp = workplane.WorkPlane(100, ax3=axis3)
        new_uid = win.get_wp_uid(wp)
        display_new_active_wp(prev_uid, new_uid)
        win.clearCallback()
    else:
        # Initial setup -- starts on a VERTEX pick; the callback
        # itself switches to face-selection mode after step 1
        win.registerCallback(wpByPtDirC)
        display.selected_shape = None
        display.SetSelectionModeVertex()
        win.statusBar().showMessage(
            "Click a point to specify the origin.")
        return


def wpByPtDirC(shapeList, *args):
    """Callback (collector) for wpByPtDir -- mixed vertex/face pick,
    switching selection mode itself between steps.

    Step 1 (Doug's own report, Session 110): only ever accepted a
    genuine 3D vertex, never a workplane catch (an intersection,
    endpoint, etc.) -- unlike position_dialog.py's own
    _point_pick_callback / pull_dialog.py's _axis_pick_callback,
    which both try the engine path (a workplane catch) FIRST and
    only fall back to a 3D vertex. This function predates that
    established pattern (Session 63) and was simply never brought up
    to match it -- not a regression, a pre-existing gap. Fixed to use
    the same, now-standard order, including the hidden-workplane
    check (Session 109)."""

    if not win.ptStack:
        # step 1: engine path (a workplane catch) first, genuine 3D
        # vertex as fallback -- same order as position_dialog.py /
        # pull_dialog.py.
        pt = None
        try:
            click_xy = args[1] if len(args) > 1 else None
            wp = win.activeWp
            if (click_xy is not None and click_xy[0] is not None
                    and wp is not None):
                from snap_engine import (screen_to_uv, find_snap,
                                         uv_to_world, SNAP_PIXELS,
                                         current_snap_mode)
                uv = screen_to_uv(win.canvas.view, click_xy[0],
                                  click_xy[1], wp.gpPlane)
                if uv is not None:
                    try:
                        tol = abs(win.canvas.view.Convert(SNAP_PIXELS))
                    except Exception:
                        tol = 1.0
                    hidden = win.activeWpUID in win.hide_list
                    snap = find_snap(wp, uv, tol, current_snap_mode(),
                                     hidden=hidden)
                    if snap is not None:
                        pt = uv_to_world(wp.gpPlane, snap[1][0],
                                         snap[1][1])
        except Exception as e:
            print(f"[wpByPtDirC] engine path failed: {e}")
        if pt is None and shapeList:
            try:
                vrtx = TopoDS.Vertex_s(shapeList[0])
                pt = BRep_Tool.Pnt_s(vrtx)
            except Exception:
                pass
        if pt is None:
            win.statusBar().showMessage(
                "No catch or vertex there -- click a workplane catch "
                "or a part vertex.", 3000)
            return
        win.ptStack.append(pt)
        display.SetSelectionModeFace()
        win.statusBar().showMessage(
            "Click a face to set the +W direction.")
        return
    # steps 2 and 3: faces
    if not shapeList:
        return
    try:
        face = TopoDS.Face_s(shapeList[0])
    except Exception:
        return
    win.faceStack.append(face)
    if len(win.faceStack) == 1:
        win.statusBar().showMessage(
            "Click another face to set the +U direction.")
    elif len(win.faceStack) == 2:
        wpByPtDir()


def position_selected():
    """Open the Position dialog on the currently selected part/assembly.

    Pre-select an item in the tree first (same convention as the rest
    of the tree-item action methods), then choose Position -> Part/Asy
    (formerly named "Position Selected" -- renamed, not moved, when
    Workplane joined it as the Position menu's new first item). See
    position_dialog.py for the dialog itself; this is just the
    tree-selection -> dialog-launch glue, matching the pattern the
    design PDF described (pre-select, then a single dropdown menu
    item opens the dialog).
    """
    item = win.treeView.currentItem() or win.itemClicked
    if not item:
        win.statusBar().showMessage(
            "Select a part or assembly in the tree, then choose Position.", 5000)
        return
    uid = item.text(1)
    name = item.text(0)
    if uid not in dm.label_dict:
        win.statusBar().showMessage(f"'{name}' cannot be positioned.", 5000)
        return

    from position_dialog import PositionDialog
    dlg = PositionDialog(win, dm, uid, name)
    dlg.show()
    win._position_dialog = dlg  # keep a reference so it isn't garbage collected


def position_selected_wp():
    """Open the Workplane Position dialog on the currently selected
    workplane -- Position -> Workplane, the new first item, per
    Doug's own wp-position.md proposal. Same tree-selection -> dialog-
    launch pattern as position_selected() (Part/Asy), adapted for
    workplanes: validated against win.wp_dict, a plain {uid: WorkPlane
    object} dict, rather than dm.label_dict, since a workplane isn't
    an OCAF label at all.
    """
    # currentItem() checked FIRST (Doug's own report, confirmed
    # directly): win.itemClicked gets unconditionally overwritten by
    # ANY tree click, including an unrelated item's visibility
    # checkbox -- selecting the workplane, then toggling a part's
    # show/hide, left itemClicked on the part while currentItem()
    # correctly stayed on the workplane. Same fix applied to
    # position_selected() (Part/Asy) below, same latent bug there too.
    item = win.treeView.currentItem() or win.itemClicked
    if not item:
        win.statusBar().showMessage(
            "Select a workplane in the tree, then choose Position.", 5000)
        return
    uid = item.text(1)
    name = item.text(0)
    if uid not in win.wp_dict:
        win.statusBar().showMessage(f"'{name}' cannot be positioned.", 5000)
        return

    from wp_position_dialog import WpPositionDialog
    dlg = WpPositionDialog(win, uid, name)
    dlg.show()
    win._wp_position_dialog = dlg  # keep a reference so it isn't garbage collected


def wpOnFace(*args):
    """ First face defines plane of wp. Second face defines uDir."""

    prev_uid = win.activeWpUID  # uid of currently active workplane
    if not win.faceStack:
        win.registerCallback(wpOnFaceC)
        display.selected_shape = None
        display.SetSelectionModeFace()
        statusText = "Select face for workplane."
        win.statusBar().showMessage(statusText)
        return
    faceU = win.faceStack.pop()
    faceW = win.faceStack.pop()
    wp = workplane.WorkPlane(100, face=faceW, faceU=faceU)
    # Creo behavior (Session 63): pane sized to the picked face +
    # margins from the start, and floored there
    wp.seed_min_bounds_from_face(faceW)
    new_uid = win.get_wp_uid(wp)
    display_new_active_wp(prev_uid, new_uid)
    win.clearCallback()


def wpOnFaceC(shapeList, *args):
    """Callback (collector) for wpOnFace"""

    if not shapeList:
        shapeList = []
    for shape in shapeList:
        try:
            face = TopoDS.Face_s(shape)
            win.faceStack.append(face)
        except Exception as e:
            print(f"[wpOnFaceC] TopoDS.Face_s failed: {e}")
    if len(win.faceStack) == 1:
        statusText = "Select face for workplane U direction."
        win.statusBar().showMessage(statusText)
    elif len(win.faceStack) == 2:
        wpOnFace()


def makeWP():
    """Default workplane located in X-Y plane at 0,0,0"""

    prev_uid = win.activeWpUID  # uid of currently active workplane
    wp = workplane.WorkPlane(100)
    new_uid = win.get_wp_uid(wp)
    display_new_active_wp(prev_uid, new_uid)


def display_new_active_wp(prev_uid, new_uid):
    """Display new active wp & redraw previous active wp if it is displayed."""

    # If currently active wp is displayed, redraw to show its new border color
    if prev_uid and prev_uid not in win.hide_list:
        win.redraw_workplanes()
    else:
        win.draw_wp(new_uid)




def get_tag_of_active_asy():
    """Get tag of active assy, if any, else top assembly"""

    # New parts always go to root level (tag=1 = as1).
    # User then drags to target assembly (Creo workflow).
    # The active assembly concept is not used for part creation.
    return 1


def get_inv_loc_of_active_asy():
    """Get inverse location vector, if any, of active assembly"""

    # New parts always created at root -- no inverse transform needed.
    return TopLoc_Location()


#############################################
#
# 3D Geometry modification functions
#
#############################################

def require_active_part(op_name):
    """Check that an Active Part is set before a Modify Active Part
    operation starts picking geometry. Returns True if OK to proceed.

    Session 20 caught fillet crashing outright when no Active Part was
    set (wrong exception type caught). Fixing just the crash wasn't
    enough on its own, though -- the check only fired AFTER the user
    had already picked every edge and typed a radius, so a real-world
    12-edge fillet failed only at the very last step. This checks
    upfront, before any picking starts, and uses a modal dialog (not
    just a status-bar/console message) so it can't be missed and the
    user isn't left to discover the problem after doing all the work.
    """
    if win.activePart is not None:
        return True
    QMessageBox.warning(
        win, "No Active Part",
        f"You must set an Active Part before using {op_name}.\n\n"
        f"Select a part in the tree, then RMB \u2192 Set Active.")
    return False


def require_active_wp(op_name):
    """Check that an Active Workplane is set before an operation that
    needs one as a reference starts. Same purpose and shape as
    require_active_part() above, for the workplane side of the app
    (Session 127, added for "Create Workplane Set", which needs an
    active workplane to offset from)."""
    if win.activeWp is not None:
        return True
    QMessageBox.warning(
        win, "No Active Workplane",
        f"You must set an Active Workplane before using {op_name}.\n\n"
        f"Select a workplane in the tree, then RMB → Set Active, "
        f"or create one first.")
    return False


def makeWpSet():
    """Launch the Create Workplane Set dialog (Session 127) -- guarded
    the same way Pull/Defeaturing guard on an active part."""
    if not require_active_wp("Workplane Set"):
        return
    from wp_set_dialog import show_wp_set_dialog
    show_wp_set_dialog(win)


def loftWpSet():
    """Loft through the profiles sketched on every workplane in a
    Workplane Set, in the set's own spacing order, producing one
    solid (Session 128 -- realizes Doug's own description of the
    end-to-end workflow: "an empty part is created, followed by a
    loft operation on a workplane set, et Voila! we get a lofted
    shape.").

    The set is taken from the tree selection if that is a Workplane
    Set node ('s1') or one of its workplanes, else from the ACTIVE
    workplane's set (Session 133); then choose Create/Modify -> Loft. Each member
    workplane must have exactly one closed profile sketched on it
    (WorkPlane.outer_profile_wire() -- holes/multiple profiles per
    plane aren't supported yet, same "simple and lean first" call
    Doug made for Workplane Sets themselves).

    Uses BRepOffsetAPI_ThruSections(isSolid=True, ruled=False) with
    CheckCompatibility(True) -- OCCT's own automatic point
    correspondence/twist-avoidance (confirmed by
    smoke_test_loft_thru_sections.py) -- rather than requiring Doug to
    hand-align a "match line" the way CoCreate did. Always ADDS to the
    active part: an empty part becomes the loft directly (Doug's
    described workflow); a non-empty one gets the loft fused in --
    same empty-part convention pull_dialog.py already established, no
    separate Add/Remove choice exposed (lean first)."""

    if not require_active_part("Loft"):
        return

    # Which set? (Session 133, Doug: "finicky" -- it demanded a FRESH
    # tree selection of the set or a member, rejected an active
    # workplane, and complained about whatever else happened to be
    # selected, e.g. the active part.) Now:
    #   1. If the tree's current/clicked item happens to be a
    #      Workplane Set node or a member workplane, that explicit
    #      choice wins.
    #   2. Otherwise the ACTIVE workplane's set is used.
    # Anything else in the tree (a part, an assembly, the root nodes)
    # is simply not considered -- never an error in itself.
    set_uid = None
    for item in (win.treeView.currentItem(), win.itemClicked):
        if not item:
            continue
        try:
            item_uid = item.text(1)
        except RuntimeError:  # stale wrapper after a tree rebuild
            continue
        if item_uid in win.wp_set_dict:
            set_uid = item_uid
        elif item_uid in win.wp_parent_set:
            set_uid = win.wp_parent_set[item_uid]
        if set_uid is not None:
            break
    if set_uid is None and win.activeWpUID in win.wp_parent_set:
        set_uid = win.wp_parent_set[win.activeWpUID]
    if set_uid is None:
        win.statusBar().showMessage(
            "Loft needs a Workplane Set: make one of its workplanes "
            "active (or select the set in the tree), then choose "
            "Loft.", 5000)
        return

    wp_uids = win.wp_set_dict.get(set_uid, [])
    if len(wp_uids) < 2:
        win.statusBar().showMessage(
            f"Workplane set '{set_uid}' needs at least 2 workplanes "
            f"to loft.", 5000)
        return

    wires = []
    for wp_uid in wp_uids:
        wp = win.wp_dict.get(wp_uid)
        if wp is None:
            win.statusBar().showMessage(
                f"'{wp_uid}' is missing from the set -- aborting "
                f"Loft.", 5000)
            return
        wire, err = wp.outer_profile_wire()
        if err is not None:
            win.statusBar().showMessage(
                f"Loft aborted -- {wp_uid}: {err}", 8000)
            return
        wires.append(wire)

    ts = BRepOffsetAPI_ThruSections(True, False)  # isSolid, ruled=False
    ts.CheckCompatibility(True)
    for w in wires:
        ts.AddWire(w)
    try:
        ts.Build()
    except Exception as e:
        win.statusBar().showMessage(f"Loft failed: {e}", 8000)
        return
    if not ts.IsDone():
        win.statusBar().showMessage(
            "Loft failed -- BRepOffsetAPI_ThruSections did not "
            "complete.", 8000)
        return
    tool = ts.Shape()
    if not BRepCheck_Analyzer(tool).IsValid():
        # Session 103's own standing finding, still honored: IsDone()
        # == True alone isn't trustworthy -- check the actual shape.
        win.statusBar().showMessage(
            "Loft failed -- result shape is not valid.", 8000)
        return

    uid = win.activePartUID
    part = win.activePart
    n_faces = 0
    exp = TopExp_Explorer(part, TopAbs_FACE)
    while exp.More():
        n_faces += 1
        exp.Next()
    part_is_empty = (n_faces == 0)

    try:
        newPart = (tool if part_is_empty
                  else BRepAlgoAPI_Fuse(part, tool).Shape())
    except Exception as e:
        win.statusBar().showMessage(f"Loft fuse failed: {e}", 8000)
        return

    ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
    old_uids = set(dm.part_dict.keys())
    win.erase_shape(uid)
    with docmodel.undo_transaction(dm):
        dm.replace_shape(uid, newPart)
    _redraw_after_shape_replace(ref_entry, old_uids)
    win.setActivePart(uid)
    win.statusBar().showMessage(
        f"Loft complete through {len(wires)} profiles in '{set_uid}' "
        f"(Ctrl+Z undoes).", 6000)


def _redraw_after_shape_replace(ref_entry, old_uids):
    """After dm.replace_shape() has run (it calls parse_doc()
    internally), redraw the modified part AND every OTHER instance
    sharing the same prototype -- Session 78, Doug: filleted one of
    two shared L-brackets, only that one instance's DISPLAY updated.
    replace_shape's own docstring/code correctly targets the SHARED
    prototype label (confirmed by reading it directly) -- the
    document data is genuinely correct for every sharing instance
    after the call. But fillet()/shell() only ever redrew the ONE
    uid that was picked; nothing was redrawing the others' AIS
    objects, even though their underlying shape data was already
    right. A latent bug, not introduced this session -- newly
    exposed because this is apparently the first test of filleting a
    genuinely shared part.

    ref_entry/old_uids MUST be captured by the caller BEFORE calling
    replace_shape -- the picked uid itself can become stale/invalid
    after replace_shape's internal parse_doc() re-parse (uids are
    entry+serial, and serial is a per-parse counter -- see Session
    72's reparenting investigation), so this takes the STABLE entry
    string, resolved fresh against the just-updated label_dict."""
    win.redraw_after_shape_replace(ref_entry, old_uids)


def _match_analytic_subshape(picked, analytic_shape, pairs, shape_type):
    """Match a picked (surrogate) face or edge back to its analytic
    counterpart -- the mapping fillet()/shell() both need to operate
    on genuinely analytic geometry rather than the NurbsConvert
    surrogate (Session 91).

    Tries the Modified()-based pairs first (built in mainwindow's own
    draw_shape, covering every sub-shape NurbsConvert actually
    changed). Falls back to a direct IsSame() check against
    analytic_shape's own sub-shapes for the case Session 91's own fix
    missed: BRepBuilderAPI_MakeShape's own Modified() only reports
    sub-shapes that were actually altered -- a straight edge or
    planar face NurbsConvert leaves completely untouched is never
    reported at all, so it has no entry in `pairs`, even though it
    persists as the SAME object in the surrogate and can be matched
    directly. Confirmed as the real cause of Doug's own report: every
    one of 12 picked edges on the pumpkin's base block failed to
    match anything in edge_pairs, consistent with all 12 being
    straight edges NurbsConvert never touched, on a part that
    qualified for the workaround because of curved geometry
    elsewhere.
    """
    for analytic_sub, surrogate_sub in pairs:
        if picked.IsSame(surrogate_sub):
            return analytic_sub
    exp = TopExp_Explorer(analytic_shape, shape_type)
    while exp.More():
        candidate = exp.Current()
        if picked.IsSame(candidate):
            return candidate
        exp.Next()
    return None


def fillet(event=None):
    """Fillet (blend) edges of active part"""

    if win.lineEditStack and win.edgeStack:
        text = win.lineEditStack.pop()
        try:
            fillet_r = float(text) * win.unitscale
        except ValueError:
            print(f"Expected a number. You entered '{text}'")
            win.clearCallback()
            return
        # Ownership is verified at PICK TIME now (filletC, via the
        # AIS owner tag) -- Session 66, Doug's regression report.
        # The IsSame()-against-win.activePart.edges() check this
        # used to do here broke for any part whose DISPLAYED shape
        # legitimately differs from win.activePart itself (the
        # Session 60/61 cylindrical-pick NurbsConvert workaround does
        # exactly this for qualifying parts) -- picked edges then
        # never matched by identity even though the pick was
        # genuinely on the active part.
        edges = list(win.edgeStack)
        win.edgeStack = []
        uid = win.activePartUID
        # Session 91 (Doug's own undo-twice discovery): fillet()'s
        # result becomes the document's own stored shape, which
        # becomes the input to every operation after it -- if this
        # keeps building from cached[1] (the surrogate), a filleted
        # part is permanently surrogate-derived from this point
        # forward, regardless of any fix downstream (confirmed
        # directly: undoing back to before the fillet let shell()
        # succeed on the exact same part that failed after fillet+
        # shell). Same fix as shell() -- map picked edges back to
        # their analytic counterparts via the face-prep map's own
        # edge_pairs, operate on the analytic shape instead.
        face_prep = win._face_prep_map.get(uid)
        if face_prep is not None:
            analytic_shape, _face_pairs, edge_pairs = face_prep
            workPart = analytic_shape
            mapped_edges = []
            for picked_edge in edges:
                matched = _match_analytic_subshape(
                    picked_edge, analytic_shape, edge_pairs, TopAbs_EDGE)
                if matched is not None:
                    mapped_edges.append(TopoDS.Edge_s(matched))
                else:
                    print(f"[fillet] picked edge has no analytic "
                         f"counterpart at all -- skipping it rather "
                         f"than risk a mismatch")
            edges = mapped_edges
        else:
            # No face-prep map -- this part never needed the Session
            # 60 workaround. Unchanged from before Session 91.
            cached = win._display_prep_cache.get(uid)
            workPart = cached[1] if cached is not None else win.activePart
        mkFillet = BRepFilletAPI_MakeFillet(workPart)
        for edge in edges:
            mkFillet.Add(fillet_r, edge)
        try:
            newPart = mkFillet.Shape()
        except Exception as e:
            # Session 79: RuntimeError alone did NOT catch a real
            # OCP.StdFail.StdFail_NotDone -- confirmed directly from
            # Doug's own traceback (the raw exception still printed
            # despite this exact guard shape). Broadened to Exception
            # -- unverified before, now corrected against real
            # evidence rather than an assumption carried over from
            # this same pattern's first use.
            print(f"Unable to make Fillet shape. {e}")
            win.clearCallback()
            return
        try:
            win.erase_shape(uid)
            ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
            old_uids = set(dm.part_dict.keys())
            with docmodel.undo_transaction(dm):
                dm.replace_shape(uid, newPart)
            _redraw_after_shape_replace(ref_entry, old_uids)
            win.statusBar().showMessage("Fillet operation complete")
        except Exception as e:
            print(f"Unable to replace/draw shape. {e}")
            # Try to redraw to recover
            win.redraw()
        win.setActivePart(uid)
        win.clearCallback()
    elif not require_active_part("Fillet"):
        return
    else:
        win.registerCallback(filletC)
        display.SetSelectionModeEdge()
        statusText = "Select edge(s) to fillet then specify fillet radius."
        win.statusBar().showMessage(statusText)


def filletC(shapeList, *args):
    """Callback (collector) for fillet"""

    win.lineEdit.setFocus()
    # OWNERSHIP CHECK, take 3 (Session 69). Doug's diagnostic gave a
    # definitive answer: BOTH SelectedInteractive() AND
    # SelectedOwner().Selectable() return None for edge-mode picks in
    # this environment -- ais_obj is simply not available here, so
    # further chasing the AIS-tag path is the wrong use of time.
    # SelectedShape() DOES reliably work (it's how `shape` always
    # arrives) -- so check ownership by comparing the picked edge
    # against the SAME reference shape fillet() itself now builds
    # from: the DISPLAYED shape (which may be NurbsConverted --
    # Session 60/61's cylindrical-pick fix), not win.activePart. This
    # is the original bug's actual fix: shape-identity matching was
    # never wrong in principle, only the REFERENCE it compared
    # against was wrong.
    uid = win.activePartUID
    cached = win._display_prep_cache.get(uid)
    ref_shape = cached[1] if cached is not None else win.activePart
    ref_edges = list(Topology.Topo(ref_shape).edges()) \
        if ref_shape is not None else []
    for shape in shapeList:
        try:
            edge = TopoDS.Edge_s(shape)
        except Exception:
            win.statusBar().showMessage(
                "Pick an edge (not a face or vertex).")
            return
        if not any(edge.IsSame(e) for e in ref_edges):
            win.statusBar().showMessage(
                "Selected edge(s) must be in Active Part.")
            return
        try:
            win.edgeStack.append(edge)
        except Exception:
            win.statusBar().showMessage("Pick an edge (not a face or vertex).")
            return
    count = len(win.edgeStack)
    if count:
        win.statusBar().showMessage(
            f"Edge {count} selected. Add more edges or enter radius + Enter.")
    if win.edgeStack and win.lineEditStack:
        fillet()


def chamfer(event=None):
    """Chamfer edges of active part -- same UI/workflow as Fillet
    (Doug's own explicit request). Confirmed directly (not assumed
    from the C++ reference docs, which turned out not to match this
    specific OCP binding): a symmetric chamfer's own Add(distance,
    edge) needs no reference face at all, matching Fillet's own
    Add(radius, edge) exactly -- so this mirrors fillet()/filletC()
    closely, reusing win.edgeStack since only one of the two is ever
    armed at a time."""

    if win.lineEditStack and win.edgeStack:
        text = win.lineEditStack.pop()
        try:
            chamfer_d = float(text) * win.unitscale
        except ValueError:
            print(f"Expected a number. You entered '{text}'")
            win.clearCallback()
            return
        edges = list(win.edgeStack)
        win.edgeStack = []
        uid = win.activePartUID
        # Same analytic-mapping pattern as fillet() (Session 91): a
        # picked edge may come from a NurbsConverted display
        # surrogate rather than the part's own real geometry.
        face_prep = win._face_prep_map.get(uid)
        if face_prep is not None:
            analytic_shape, _face_pairs, edge_pairs = face_prep
            workPart = analytic_shape
            mapped_edges = []
            for picked_edge in edges:
                matched = _match_analytic_subshape(
                    picked_edge, analytic_shape, edge_pairs, TopAbs_EDGE)
                if matched is not None:
                    mapped_edges.append(TopoDS.Edge_s(matched))
                else:
                    print(f"[chamfer] picked edge has no analytic "
                         f"counterpart at all -- skipping it rather "
                         f"than risk a mismatch")
            edges = mapped_edges
        else:
            cached = win._display_prep_cache.get(uid)
            workPart = cached[1] if cached is not None else win.activePart
        mkChamfer = BRepFilletAPI_MakeChamfer(workPart)
        for edge in edges:
            mkChamfer.Add(chamfer_d, edge)
        try:
            newPart = mkChamfer.Shape()
        except Exception as e:
            print(f"Unable to make Chamfer shape. {e}")
            win.clearCallback()
            return
        try:
            win.erase_shape(uid)
            ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
            old_uids = set(dm.part_dict.keys())
            with docmodel.undo_transaction(dm):
                dm.replace_shape(uid, newPart)
            _redraw_after_shape_replace(ref_entry, old_uids)
            win.statusBar().showMessage("Chamfer operation complete")
        except Exception as e:
            print(f"Unable to replace/draw shape. {e}")
            win.redraw()
        win.setActivePart(uid)
        win.clearCallback()
    elif not require_active_part("Chamfer"):
        return
    else:
        win.registerCallback(chamferC)
        display.SetSelectionModeEdge()
        statusText = "Select edge(s) to chamfer then specify chamfer distance."
        win.statusBar().showMessage(statusText)


def chamferC(shapeList, *args):
    """Callback (collector) for chamfer -- same ownership-check
    pattern as filletC()."""

    win.lineEdit.setFocus()
    uid = win.activePartUID
    cached = win._display_prep_cache.get(uid)
    ref_shape = cached[1] if cached is not None else win.activePart
    ref_edges = list(Topology.Topo(ref_shape).edges()) \
        if ref_shape is not None else []
    for shape in shapeList:
        try:
            edge = TopoDS.Edge_s(shape)
        except Exception:
            win.statusBar().showMessage(
                "Pick an edge (not a face or vertex).")
            return
        if not any(edge.IsSame(e) for e in ref_edges):
            win.statusBar().showMessage(
                "Selected edge(s) must be in Active Part.")
            return
        try:
            win.edgeStack.append(edge)
        except Exception:
            win.statusBar().showMessage("Pick an edge (not a face or vertex).")
            return
    count = len(win.edgeStack)
    if count:
        win.statusBar().showMessage(
            f"Edge {count} selected. Add more edges or enter distance + Enter.")
    if win.edgeStack and win.lineEditStack:
        chamfer()


def shell(event=None):
    """Shell active part"""

    if win.lineEditStack and win.faceStack:
        text = win.lineEditStack.pop()
        # Session 91 (Doug's own session-60 connection): shell() was
        # operating on the NurbsConvert surrogate (cached[1]) -- the
        # SAME multi-patch geometry that made picking cylindrical
        # faces reliable in the first place, but MakeThickSolidByJoin
        # chokes offsetting across the seams between converted
        # patches on any face that's still part of the result (not
        # necessarily the one being removed). Fixed by mapping each
        # picked (surrogate) face back to the original, analytic face
        # it came from, via the map draw_shape now builds, and
        # operating on the analytic shape instead of the surrogate.
        face_prep = win._face_prep_map.get(win.activePartUID)
        faces = TopTools_ListOfShape()
        if face_prep is not None:
            analytic_shape, face_pairs, _edge_pairs = face_prep
            workPart = analytic_shape
            for picked_face in win.faceStack:
                matched = _match_analytic_subshape(
                    picked_face, analytic_shape, face_pairs, TopAbs_FACE)
                if matched is not None:
                    faces.Append(matched)
                else:
                    # Genuinely unexpected (every analytic face should
                    # match, whether via face_pairs or the fallback
                    # direct check) -- loud rather than silently
                    # appending a face that doesn't belong to
                    # workPart's own topology, which would just
                    # recreate the original Session 79 bug.
                    print(f"[shell] picked face has no analytic "
                         f"counterpart at all -- skipping it rather "
                         f"than risk a mismatch")
        else:
            # No face-prep map -- this part never needed the Session
            # 60 workaround (never NurbsConverted). A prior investigation
            # (Doug's STEP-import report) traced an apparent map-miss
            # here to a corrupt test file, not a real gap in this
            # branch -- confirmed and resolved.
            cached = win._display_prep_cache.get(win.activePartUID)
            workPart = cached[1] if cached is not None else win.activePart
            for face in win.faceStack:
                faces.Append(face)
        win.faceStack = []
        uid = win.activePartUID
        shellT = float(text) * win.unitscale
        mkShell = BRepOffsetAPI_MakeThickSolid()
        mkShell.MakeThickSolidByJoin(workPart, faces, -shellT, 1.0e-3)
        try:
            newPart = mkShell.Shape()
            print(f"[shell] SUCCESS -- result ShapeType="
                 f"{newPart.ShapeType()} (analytic mapping "
                 f"{'used' if face_prep is not None else 'not needed'})")
        except Exception as e:
            # Session 79: same fix as fillet's identical guard above
            # -- RuntimeError did not catch the real
            # OCP.StdFail.StdFail_NotDone Doug's traceback showed.
            print(f"Unable to make Shell shape. {e}")
            win.clearCallback()
            return
        try:
            win.erase_shape(uid)
            ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
            old_uids = set(dm.part_dict.keys())
            with docmodel.undo_transaction(dm):
                dm.replace_shape(uid, newPart)
            _redraw_after_shape_replace(ref_entry, old_uids)
            shell_ok = True
        except Exception as e:
            # Session 79, Doug: the part vanished from the viewport
            # but stayed in the tree after a replace_shape failure --
            # erase_shape(uid) had already run, but nothing recovered
            # the display when the operation failed partway through.
            # Same protective structure fillet() already has.
            print(f"Unable to replace/draw shape. {e}")
            win.redraw()
            shell_ok = False
        win.setActivePart(uid)
        win.clearCallback()
        # FIX (Doug: "the terminal says it's there, but it is most
        # definitely not there"): clearCallback() itself calls
        # statusBar().showMessage("") -- it was silently wiping this
        # message the moment it was set, before any repaint could
        # ever show it. The message now has to be set AFTER
        # clearCallback runs, not before, so nothing overwrites it.
        if shell_ok:
            win.statusBar().showMessage("Shell operation complete")
    elif not require_active_part("Shell"):
        return
    else:
        win.registerCallback(shellC)
        display.SetSelectionModeFace()
        statusText = "Select face(s) to remove then specify shell thickness."
        win.statusBar().showMessage(statusText)


def shellC(shapeList, *args):
    """Callback (collector) for shell -- same ownership-check pattern
    as filletC()/chamferC(), previously missing here (flagged during
    the UI Interaction Policy review as a live example of exactly the
    copy-paste drift that document's "promote helper functions" goal
    was meant to prevent)."""

    win.lineEdit.setFocus()
    uid = win.activePartUID
    cached = win._display_prep_cache.get(uid)
    ref_shape = cached[1] if cached is not None else win.activePart
    ref_faces = list(Topology.Topo(ref_shape).faces()) \
        if ref_shape is not None else []
    for shape in shapeList:
        try:
            face = TopoDS.Face_s(shape)
        except Exception:
            win.statusBar().showMessage(
                "Pick a face (not an edge or vertex).")
            return
        if not any(face.IsSame(f) for f in ref_faces):
            win.statusBar().showMessage(
                "Selected face(s) must be in Active Part.")
            return
        win.faceStack.append(face)
    count = len(win.faceStack)
    if count:
        win.statusBar().showMessage(
            f"Face {count} selected. Add more faces or enter thickness + Enter.")
    if win.faceStack and win.lineEditStack:
        shell()


def _defeaturing_workpart(uid):
    """Return (workPart, ref_shape, face_pairs) for the active part --
    same analytic-mapping lookup fillet()/shell() and the old
    removeHole()/removeIsolatedFeature()/autoIsolatedFeature() all
    already used (Session 91): a picked face may come from a
    NurbsConverted display surrogate rather than the part's own real
    geometry. face_pairs is None when there's no analytic surrogate
    in play at all (workPart == ref_shape, no mapping needed)."""
    cached = win._display_prep_cache.get(uid)
    ref_shape = cached[1] if cached is not None else win.activePart
    face_prep = win._face_prep_map.get(uid)
    if face_prep is not None:
        analytic_shape, face_pairs, _edge_pairs = face_prep
        return analytic_shape, ref_shape, face_pairs
    return ref_shape, ref_shape, None


def _defeaturing_map_picked_faces(picked_faces, workPart, face_pairs):
    """Map picked (possibly NurbsConverted-surrogate) faces onto
    workPart's own analytic geometry -- same pattern used throughout
    this file. A face with no analytic counterpart is skipped rather
    than risk a mismatch."""
    if face_pairs is None:
        return list(picked_faces)
    mapped = []
    for picked_face in picked_faces:
        matched = _match_analytic_subshape(
            picked_face, workPart, face_pairs, TopAbs_FACE)
        if matched is not None:
            mapped.append(TopoDS.Face_s(matched))
        else:
            print("[Defeaturing] picked face has no analytic "
                 "counterpart at all -- skipping it rather than "
                 "risk a mismatch")
    return mapped


def _defeaturing_hole_faces(workPart, seed_face):
    """Given ONE picked face for Remove Hole mode, verify it's
    cylindrical and return every face sharing its surface (a hole's
    cylindrical wall can be split into multiple patches -- picking
    captures only one) plus any adjacent single-edge cap face (a
    blind hole's own bottom, healed automatically once the wall is
    removed -- no separate handling needed beyond finding it).
    Unchanged logic from the original standalone removeHoleC.
    Returns (faces, None) or (None, error_message)."""
    surf = BRepAdaptor_Surface(seed_face)
    if surf.GetType() != GeomAbs_Cylinder:
        return None, ("Pick a cylindrical face (a hole) for Remove "
                      "Hole -- other feature types aren't supported "
                      "by this mode.")

    matching_faces = [seed_face]
    try:
        cyl1 = surf.Cylinder()
        ax1 = cyl1.Axis()
        r1 = cyl1.Radius()
        line1 = gp_Lin(ax1)
        exp = TopExp_Explorer(workPart, TopAbs_FACE)
        while exp.More():
            f = TopoDS.Face_s(exp.Current())
            if not f.IsSame(seed_face):
                surf2 = BRepAdaptor_Surface(f)
                if surf2.GetType() == GeomAbs_Cylinder:
                    cyl2 = surf2.Cylinder()
                    same_radius = abs(cyl2.Radius() - r1) < 1e-4
                    ax2 = cyl2.Axis()
                    same_axis = (
                        ax1.IsParallel(ax2, 1e-4)
                        and line1.Distance(ax2.Location()) < 1e-4)
                    if same_radius and same_axis:
                        matching_faces.append(f)
            exp.Next()
    except Exception as e:
        print(f"[Defeaturing:Hole] multi-patch detection failed "
             f"({e}) -- falling back to the single picked face")
        matching_faces = [seed_face]

    print(f"[Defeaturing:Hole] {len(matching_faces)} cylindrical "
         f"face(s) share the picked face's own surface")

    try:
        cap_faces = []
        for cyl_f in list(matching_faces):
            cyl_edges = []
            eexp = TopExp_Explorer(cyl_f, TopAbs_EDGE)
            while eexp.More():
                cyl_edges.append(TopoDS.Edge_s(eexp.Current()))
                eexp.Next()
            exp3 = TopExp_Explorer(workPart, TopAbs_FACE)
            while exp3.More():
                f = TopoDS.Face_s(exp3.Current())
                already = (any(f.IsSame(m) for m in matching_faces)
                          or any(f.IsSame(c) for c in cap_faces))
                if not already:
                    f_edges = []
                    fe = TopExp_Explorer(f, TopAbs_EDGE)
                    while fe.More():
                        f_edges.append(TopoDS.Edge_s(fe.Current()))
                        fe.Next()
                    adjacent = any(
                        ce.IsSame(fe2)
                        for ce in cyl_edges for fe2 in f_edges)
                    if adjacent and len(f_edges) == 1:
                        cap_faces.append(f)
                exp3.Next()
        if cap_faces:
            print(f"[Defeaturing:Hole] {len(cap_faces)} cap face(s) "
                 f"found adjacent to the cylindrical wall -- adding "
                 f"them too")
            matching_faces.extend(cap_faces)
    except Exception as e:
        print(f"[Defeaturing:Hole] cap-face detection failed ({e}) "
             f"-- proceeding with cylindrical face(s) only")

    return matching_faces, None


def _defeaturing_execute(uid, workPart, faces_to_remove, label=""):
    """Run BRepAlgoAPI_Defeaturing on workPart, removing
    faces_to_remove, and write the result back to the active part as
    ONE undo step. Shared tail logic for all three Defeaturing dialog
    modes -- previously duplicated three times across the standalone
    removeHoleC/removeIsolatedFeatureC/autoIsolatedFeatureC. Returns
    (True, status_message) or (False, status_message)."""
    dfr = BRepAlgoAPI_Defeaturing()
    dfr.SetShape(workPart)
    for f in faces_to_remove:
        dfr.AddFaceToRemove(f)
    dfr.Build()
    print(f"[Defeaturing:{label}] IsDone={dfr.IsDone()}")
    if not dfr.IsDone():
        return False, ("Unable to remove this feature -- the "
                       "surrounding geometry couldn't be healed.")
    newPart = dfr.Shape()

    # Same before/after face-count safety check every defeaturing
    # path in this file has always used (Session 103): IsDone=True
    # alone isn't trustworthy on its own for this algorithm.
    n_before = 0
    exp_before = TopExp_Explorer(workPart, TopAbs_FACE)
    while exp_before.More():
        n_before += 1
        exp_before.Next()
    n_after = 0
    exp_after = TopExp_Explorer(newPart, TopAbs_FACE)
    while exp_after.More():
        n_after += 1
        exp_after.Next()
    print(f"[Defeaturing:{label}] faces before={n_before}, "
         f"after={n_after}")

    try:
        win.erase_shape(uid)
        ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
        old_uids = set(dm.part_dict.keys())
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        _redraw_after_shape_replace(ref_entry, old_uids)
        win.setActivePart(uid)
        return True, "Feature removed."
    except Exception as e:
        print(f"Unable to replace/draw shape. {e}")
        win.redraw()
        return False, f"Unable to replace/draw shape: {e}"


class DefeaturingDialog(QDialog):
    """Unified Defeaturing dialog (Session 125) -- replaces the three
    formerly-separate menu items (Remove Hole / Remove Isolated
    Feature / Auto Isolated Feature) with one dialog offering all
    three as named "Method" choices.

    Doug's own design call, after using all three separately on a
    real part (ANC101.stp, Quaoar's own demo part): the three tools
    are related in PURPOSE but different in INTERACTION -- Remove
    Hole fired instantly on one click, Remove Isolated Feature needed
    every face picked by hand then Enter, and Auto Isolated Feature
    (once generalized to handle through-features -- see
    isolated_features.py's own docstring) ALSO needed Enter, except
    Doug's live app was still running the pre-Enter build when he
    first tried it, which is what made it look like a single click
    was enough even for multi-pocket cases. Renaming alone couldn't
    fix that inconsistency; a shared '✅ Apply' button can, by
    making every mode work the same way: pick face(s), press Apply.
    Apply had been deliberately avoided everywhere else in this
    project (mill_pull_dialog.py's own docstring: "Apply exists
    nowhere else") -- used here specifically because giving the three
    modes a homogeneous feel was the actual point, not a convenience.

    '⏹ Done' is a SEPARATE button, ending the whole defeaturing
    SESSION rather than a single operation -- the dialog stays open
    across repeated Apply presses so a part can be defeatured one
    feature at a time without reopening the tool each time (confirmed
    directly: Doug took ANC101.stp down to a bare slab, Apply by
    Apply, then undid all the way back -- each Apply is its own undo
    step already, via _defeaturing_execute's own undo_transaction).

    Modeled on mill_pull_dialog.py's own conventions (non-modal
    QDialog, bold full-path breadcrumb header) with one genuine
    first for this project: live 3D face picking (win.registerCallback)
    while a dialog stays open, rather than working off a workplane's
    own 2D profiles the way Mill/Pull does. Using a clicked Apply
    button rather than Enter-in-a-lineEdit sidesteps the one real
    risk that raised on paper (Enter-key/lineEdit-focus competing
    with the dialog for keyboard focus) -- Apply is an ordinary
    button click, no different from any other dialog control, and
    doesn't depend on win.lineEdit having focus at all.
    """

    MODES = [
        ("Remove Hole",
         "Click the hole's cylindrical face, then Apply."),
        ("Manual (pick every face)",
         "Click every face of the feature, then Apply."),
        ("Auto (pick capping face(s))",
         "Click the face capping the feature. For a feature open at "
         "BOTH ends (a through-hole), also click its other capping "
         "face. Then Apply."),
    ]

    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.setWindowTitle("Defeaturing")
        self.setModal(False)
        self.face_stack = []

        lay = QVBoxLayout(self)

        # Header matches Mill/Pull's own convention exactly (Session
        # 63, Doug: side-by-side dialogs should share one look):
        # caption line + BOLD full-path breadcrumb.
        lay.addWidget(QLabel("Modifying part:"))
        self.part_label = QLabel()
        _bold = QFont()
        _bold.setBold(True)
        self.part_label.setFont(_bold)
        self.part_label.setWordWrap(True)
        lay.addWidget(self.part_label)

        row = QHBoxLayout()
        row.addWidget(QLabel("Method:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([m[0] for m in self.MODES])
        self.mode_combo.currentIndexChanged.connect(
            self._on_mode_changed)
        row.addWidget(self.mode_combo)
        lay.addLayout(row)

        self.instructions_label = QLabel()
        self.instructions_label.setWordWrap(True)
        lay.addWidget(self.instructions_label)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("✅ Apply")
        self.apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self.apply_btn)
        self.done_btn = QPushButton("⏹ Done")
        self.done_btn.clicked.connect(self._on_done)
        btn_row.addWidget(self.done_btn)
        lay.addLayout(btn_row)

        self._refresh_header()
        self._on_mode_changed()
        self._start_picking()

    def _refresh_header(self):
        uid = win.activePartUID
        name = ""
        if uid is not None and hasattr(dm, "get_full_path_name"):
            try:
                name = dm.get_full_path_name(uid)
            except Exception:
                name = str(uid)
        self.part_label.setText(name)

    def _on_mode_changed(self):
        idx = self.mode_combo.currentIndex()
        self.instructions_label.setText(self.MODES[idx][1])
        self.face_stack = []
        self._update_status()

    def _update_status(self, extra=""):
        n = len(self.face_stack)
        base = f"{n} face(s) selected."
        self.status_label.setText(f"{extra}  {base}" if extra else base)

    def _start_picking(self):
        win.registerCallback(self._on_pick)
        display.SetSelectionModeFace()

    def _on_pick(self, shapeList, *args):
        # Apply drives execution now, not Enter -- an empty
        # shapeList (what used to mean "Enter was pressed" for the
        # old Manual/Auto tools) is simply ignored here.
        if not shapeList:
            return
        uid = win.activePartUID
        cached = win._display_prep_cache.get(uid)
        ref_shape = cached[1] if cached is not None else win.activePart
        ref_faces = list(Topology.Topo(ref_shape).faces()) \
            if ref_shape is not None else []
        for shape in shapeList:
            try:
                face = TopoDS.Face_s(shape)
            except Exception:
                self._update_status("Pick a face (not an edge or "
                                    "vertex).")
                return
            if not any(face.IsSame(f) for f in ref_faces):
                self._update_status("Selected face must be in "
                                    "Active Part.")
                return
            self.face_stack.append(face)
        self._update_status()

    def _on_apply(self):
        if not require_active_part("Defeaturing"):
            return
        uid = win.activePartUID
        if not self.face_stack:
            self._update_status("Pick at least one face before "
                                "Apply.")
            return
        picked_faces = list(self.face_stack)
        self.face_stack = []

        workPart, _ref_shape, face_pairs = _defeaturing_workpart(uid)
        seed_faces = _defeaturing_map_picked_faces(
            picked_faces, workPart, face_pairs)
        if not seed_faces:
            self._update_status("No usable faces to apply.")
            return

        idx = self.mode_combo.currentIndex()
        mode_name = self.MODES[idx][0]

        if idx == 0:  # Remove Hole
            if len(seed_faces) > 1:
                self._update_status("Remove Hole takes one pick at "
                                    "a time -- pick just the hole's "
                                    "cylindrical face.")
                return
            faces_to_remove, err = _defeaturing_hole_faces(
                workPart, seed_faces[0])
            if err:
                self._update_status(err)
                return
        elif idx == 1:  # Manual
            faces_to_remove = seed_faces
        else:  # Auto
            try:
                faces_to_remove = \
                    isolated_features.find_isolated_feature_faces(
                        workPart, seed_faces)
            except Exception as e:
                print(f"[Defeaturing:Auto] detection failed: {e}")
                self._update_status("Could not analyze -- see "
                                    "console for details.")
                return
            if not faces_to_remove:
                self._update_status("No isolated feature found -- "
                                    "for a through-feature, pick "
                                    "BOTH capping faces.")
                return

        ok, msg = _defeaturing_execute(
            uid, workPart, faces_to_remove, label=mode_name)
        self._update_status(msg)
        self._refresh_header()
        # Session stays open -- ready for the next pick/Apply.
        self._start_picking()

    def _on_done(self):
        win.clearCallback()
        self.close()

    def closeEvent(self, event):
        win.clearCallback()
        super().closeEvent(event)


def show_defeaturing_dialog(main_win):
    if not require_active_part("Defeaturing"):
        return
    dlg = getattr(main_win, "_defeaturing_dialog", None)
    if dlg is None or not dlg.isVisible():
        dlg = DefeaturingDialog(main_win)
        main_win._defeaturing_dialog = dlg
        dlg.show()
    else:
        dlg.raise_()
        dlg.activateWindow()

#############################################
#
#  Save / Open / Load functions
#
#############################################


def open_doc():
    dm.open_doc()
    win.build_tree()


def save_doc():
    dm.save_doc()


def load_session():
    """Load a previously saved session from STEP file.

    Replaces the entire document with the loaded file.
    The '/' root is preserved -- if the loaded file has its own root
    assembly it appears under '/'. Repeated save/load cycles do not
    accumulate extra '/' levels (same fix as Basicad item 30).
    """
    win.setActivePart(0)
    win.setActiveAsy(0)
    # Session 81, cont'd: clear the viewport's own AIS objects BEFORE
    # replacing dm.doc, not after. The previous order left every
    # displayed AIS object -- built from the OLD document's shapes --
    # alive and referenced by win.ais_shape_dict throughout the ENTIRE
    # load (repair_unnamed_products, parse_doc, etc.), with nothing
    # clearing them until win.redraw() ran at the very end. If Python
    # decides to release the old document's underlying C++ object
    # the moment dm.doc's reference is replaced (inside
    # load_stp_at_top), those still-alive AIS objects would be
    # holding dangling references to shape data that's being torn
    # down out from under them -- a very plausible mechanism for a
    # crash that only shows up when there's an existing document to
    # replace, never on a fresh process with nothing loaded yet,
    # matching Doug's own reproducible pattern exactly. The earlier
    # attempt (explicitly closing the old document via
    # TDocStd_Application.Close()) was confirmed ineffective by
    # Doug's own diagnostic output -- that call fails unconditionally
    # on a NewDocument()-created document, which is the only kind
    # this codebase ever creates -- removed rather than left in as
    # permanent, misleading noise.
    win.ais_shape_dict.clear()
    try:
        win.canvas._display.Context.RemoveAll(False)
    except Exception as ce:
        print(f"[load_session] could not clear the viewport before "
             f"loading ({ce}) -- continuing regardless")
    docmodel.load_stp_at_top(dm)
    win.build_tree()
    # DIAGNOSTIC (Doug's empty-part-then-Pull test: correct geometry
    # confirmed present after reload -- IsNull=False, faces=6 -- but
    # nothing draws). load_session() never clears self.hide_list,
    # which is a session-level Python set, not something persisted
    # in the STEP file itself. Doug tested hide/show on this exact
    # part earlier in the same session -- if a stale entry survived
    # that, and the reloaded part happens to land on the same uid
    # string (plausible, since parse ordering is deterministic),
    # redraw()'s own "if uid not in self.hide_list" check would
    # silently skip it. This checks that directly instead of guessing.
    print(f"[load_session] hide_list contents: {win.hide_list}")
    print(f"[load_session] part_dict keys: {list(dm.part_dict.keys())}")
    for _u in dm.part_dict:
        if _u in win.hide_list:
            print(f"[load_session] part {_u!r} IS in hide_list -- "
                 f"redraw() will skip drawing it")
    win.redraw()
    win.fitAll()


def import_step():
    """Import a STEP file as a new component under '/'.

    The imported assembly appears at root level, ready to be
    positioned and dragged into a sub-assembly.
    """
    with docmodel.undo_transaction(dm):
        docmodel.load_stp_cmpnt(dm)
    win.build_tree()
    win.redraw()
    win.fitAll()


#############################################
#
#  Info & Utility functions
#
#############################################


def show_undo_redo_count():
    """Utility menu item (Doug: the count flashes in the status bar
    at the end of each undo/redo and vanishes before he can read it)
    -- same GetAvailableUndos/Redos win.editUndo/editRedo already
    use, just shown on demand instead of only for a moment."""
    n_undo = dm.doc.GetAvailableUndos()
    n_redo = dm.doc.GetAvailableRedos()
    win.statusBar().showMessage(
        f"Undo steps available: {n_undo}   |   "
        f"Redo steps available: {n_redo}")


def print_uid_dict():
    pprint.pprint(dm.label_dict)


def print_part_dict():
    pprint.pprint(dm.part_dict)


def dumpDoc():
    sa = stepanalyzer.StepAnalyzer(document=dm.doc)
    dumpdata = sa.dump()
    print(dumpdata)


def topoDumpAP():
    if win.activePart:
        Topology.dumpTopology(win.activePart)


def printActiveAsyInfo():
    uid = win.activeAsyUID
    if uid:
        name = dm.label_dict[uid]["name"]
        print(f"Active Assembly (uid) Name: ({uid}) {name}")
    else:
        print("No assembly active")


def printActiveWpInfo():
    uid = win.activeWpUID
    if uid:
        name = win.activeWp
        print(f"Active WP (uid) Name: ({uid}) {name}")
    else:
        print("No workplane active")


def printActivePartInfo():
    uid = win.activePartUID
    if uid:
        name = dm.label_dict[uid]["name"]
        print(f"Active Part (uid) Name: ({uid}) {name}")
    else:
        print("No part active")


def printActPart():
    uid = win.activePartUID
    if uid:
        name = win.label_dict[uid]["name"]
        print(f"Active Part: {name} [{uid}]")
    else:
        print(None)


def printTreeView():
    """Print 'uid'; 'name'; 'parent' for all items in treeView."""

    iterator = QTreeWidgetItemIterator(win.treeView)
    while iterator.value():
        item = iterator.value()
        name = item.text(0)
        uid = item.text(1)
        pname = None
        parent = item.parent()
        if parent:
            puid = parent.text(1)
            pname = parent.text(0)
        print(f"UID: {uid}; Name: {name}; Parent: {pname}")
        iterator += 1


def printDrawList():
    print("Draw List:", win.drawList)


def printInSync():
    print(win.inSync())


def setUnits_in():
    win.setUnits("in")


def setUnits_mm():
    win.setUnits("mm")


def _scene_bbox_center():
    """World-space (x, y, z) center of every currently displayed
    part's own bounding box, or (0, 0, 0) if nothing's displayed.
    Confirmed live (Doug's own test, as1-oc-214.stp): extents matched
    the model's own known proportions exactly (X, the rod's own
    length direction, clearly the largest). Same logic as the
    now-removed Scene BBox Inspect smoke test, made permanent."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bbox = Bnd_Box()
    for uid, ais in win.ais_shape_dict.items():
        try:
            BRepBndLib.Add_s(ais.Shape(), bbox)
        except Exception as e:
            print(f"[section-view] bbox: uid={uid} failed: {e}")
    if bbox.IsVoid():
        return (0.0, 0.0, 0.0)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return ((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2)


_AXIS_NORMALS = {
    # X and Z reversed from the "obvious" +axis normal (Doug's own
    # live observation, Session 111): with KodaCAD2's default
    # Top-Front-Right isometric startup view, the geometric +X/+Z
    # normal clips away the FAR side, leaving the NEAR side blocking
    # the view of the cut -- backwards from what a section view is
    # for. Y already clipped the near side correctly as-is and was
    # left alone. This is the base direction BEFORE any per-plane
    # Reverse toggle (Session 120) is taken into account -- see
    # _get_plane_geom().
    "x": gp_Dir(-1, 0, 0),
    "y": gp_Dir(0, 1, 0),
    "z": gp_Dir(0, 0, -1),
}

_SECTION_AXES = ("x", "y", "z")  # fixed chain order, also row order


def _get_plane_geom(axis):
    """The gp_Pln to use when (re)building a given axis's clip plane.
    Session 129 (FreeCAD-style redesign, Doug's own call -- see
    _rebuild_section_clip_planes()'s docstring): simplified from the
    old (mode, axis)-keyed lookup to a flat, axis-only one. There's no
    more "mode" dimension to key by -- a given axis's plane is the
    same plane regardless of which OTHER axes happen to be checked
    alongside it, so remembering its position/normal per-mode was
    never actually needed, just inherited from the old design.

    Checks win._section_plane_state first, restoring exactly where
    this axis's plane was last left (position AND normal both) if
    it's been built before (Session 120's own memory mechanism,
    unchanged in spirit). Only when nothing's been remembered yet --
    the very first time this axis is ever checked -- does it fall
    back to a fresh build, centered on the scene's own current
    bounding box (Session 112), with the base normal from
    _AXIS_NORMALS reversed first if this axis's own Reverse checkbox
    is currently checked (win._section_reversed)."""
    from OCP.gp import gp_Pln, gp_Pnt
    stored = getattr(win, "_section_plane_state", {}).get(axis)
    if stored is not None:
        return stored
    cx, cy, cz = _scene_bbox_center()
    normal = _AXIS_NORMALS[axis]
    reversed_state = getattr(win, "_section_reversed", {}).get(axis, False)
    if reversed_state:
        normal = normal.Reversed()
    return gp_Pln(gp_Pnt(cx, cy, cz), normal)


def _store_plane_geom(axis, pln):
    """Remember an axis's own current plane position and normal (a
    full gp_Pln, capturing both at once), so a future rebuild --
    unchecking and rechecking it, or checking a DIFFERENT axis
    alongside it -- restores it via _get_plane_geom() instead of
    resetting to the scene's own bounding-box center. Called after
    every completed drag (_clip_plane_drag_done) and every Reverse
    toggle (_on_reverse_checkbox_toggled), the only two things that
    ever change a plane's own geometry after it's first built.
    Session 129: flat, axis-only dict now -- see _get_plane_geom()'s
    own docstring for why the old mode dimension was dropped."""
    win._section_plane_state = getattr(win, "_section_plane_state", {})
    win._section_plane_state[axis] = pln


def _rebuild_section_clip_planes():
    """Apply the current section-view configuration from scratch --
    whichever of X/Y/Z are currently checked (win._section_checked),
    zero to three of them, independently. Session 129: replaces the
    old set_section_view_mode(mode) -- FreeCAD's own section-view UI
    (Doug's own reference) uses 3 independent checkboxes rather than a
    5-way exclusive mode selector (off/x/y/z/xy): none checked is
    Normal View, any combination of 1-3 gives that combination's own
    section view, including the 3-plane case that was never actually
    built under the old design ("'xyz' (3 planes) is the next step" --
    Session 116's own docstring, now obsolete). Doug's own reasoning:
    a user should be able to turn any subset of the 3 principal planes
    on or off independently, the same way FreeCAD lets them -- not
    pick from a fixed menu of named combinations.

    Removes whatever clip planes currently exist, then rebuilds from
    win._section_checked: each checked axis gets a Graphic3d_ClipPlane
    from _get_plane_geom(axis) (restoring its own remembered position/
    normal if it's been built before), chained together in a fixed
    x->y->z order via SetChainNextPlane (a logical AND -- a point must
    satisfy EVERY checked plane to remain visible; only the first
    plane in the chain is ever added to the view -- Session 114 proved
    this mechanism for the old, always-2-plane xy mode; generalized
    here to 1, 2, or 3 planes uniformly instead of special-casing a
    fixed pair). Capping stays unconditional (Session 120's own call,
    unchanged)."""
    from OCP.Graphic3d import Graphic3d_ClipPlane

    existing = getattr(win, "_section_clip_planes", [])
    for plane in existing:
        try:
            win.canvas.view.RemoveClipPlane(plane)
        except Exception as e:
            print(f"[section-view] remove failed: {e}")
    win._section_clip_planes = []
    win._section_clip_planes_by_axis = {}

    checked = getattr(win, "_section_checked", {})
    active_axes = [a for a in _SECTION_AXES if checked.get(a)]

    try:
        planes = []
        for axis in active_axes:
            plane_geom = _get_plane_geom(axis)
            plane = Graphic3d_ClipPlane(plane_geom)
            plane.SetOn(True)
            planes.append(plane)
            win._section_clip_planes_by_axis[axis] = plane
        for i in range(len(planes) - 1):
            planes[i].SetChainNextPlane(planes[i + 1])
        if planes:
            win.canvas.view.AddClipPlane(planes[0])
        win._section_clip_planes = planes
    except Exception as e:
        print(f"[section-view] clip plane build failed: {e}")

    win.canvas.view.Redraw()
    _apply_section_capping()
    _update_clip_visibility()


def _get_clip_target_plane():
    """The single clip plane the manipulator should currently target,
    or None if nothing should currently be draggable at all.

    Session 129: simplified along with the rest of the mode-based
    machinery it replaces -- no more top-level Normal/Section switch
    to check (none of X/Y/Z checked already means no planes exist at
    all, so there's nothing to target either way), and no more mode-
    dependent lookup (the old xy-only by-axis dict is now simply how
    every configuration works, 1, 2 or 3 planes alike, not a special
    case for exactly 2).

    win._section_clip_active_axis (None by default) is still the one,
    shared "which row's own Edit control is checked" state -- now
    covering X/Y/Z uniformly instead of X/Y/Z/XY-X/XY-Y. Returns the
    live plane for that axis if it's currently built in
    win._section_clip_planes_by_axis -- unchecking an axis's own Dir
    box while it's also the active Edit axis clears active_axis
    directly (_on_dir_checkbox_toggled), so this should never actually
    be asked for a stale axis, but checks the dict anyway rather than
    assuming that invariant always holds."""
    axis = getattr(win, "_section_clip_active_axis", None)
    if axis is None:
        return None
    by_axis = getattr(win, "_section_clip_planes_by_axis", {})
    return by_axis.get(axis)


def _update_clip_visibility():
    """Keep the clip plane's own drag gizmo in sync with whether
    visibility is toggled on AND whether a plane is currently active.
    Called both when the visibility button itself is toggled, and
    whenever the configuration changes (_rebuild_section_clip_planes)
    -- so switching
    from Z to X while visibility is on rebuilds the gizmo to match X
    rather than leaving it stale on Z, and switching to Off removes
    it entirely, since there's nothing to drag with no plane active.

    Session 112 (Doug's own idea, after the underlying clip mechanism
    checked out clean via direct diagnostic -- construction was
    identical and correct for X/Y/Z alike, the "planes weren't there"
    report turned out to be a viewing-angle issue, not a bug):
    dropped the translucent, filled-face visual entirely. The
    manipulator only ever needed SOME AIS_Shape to attach to for
    tracking position -- not a visible square representing "the
    plane" -- and CAD Assistant itself has no separate plane visual
    at all, just the draggable gizmo. Attaches to a minimal vertex
    marker at the plane's own center instead.

    Drag-sync logic (move/done callbacks, translate_only_axis=2, the
    live Graphic3d_ClipPlane update) is unchanged -- proven correct
    independently of what the manipulator's own leaf shape looks
    like.

    Session 116: now targets _get_clip_target_plane() instead of
    always win._section_clip_planes[0] -- for single-axis modes this
    is the exact same plane either way (no behavior change at all);
    for xy mode it's whichever plane the toolbar's own Edit X/Edit Y
    switch currently has selected, letting this same, unmodified
    mechanism serve both cases.

    Session 119: the separate win._section_clip_move_enabled flag is
    gone -- _get_clip_target_plane() itself now folds in every reason
    nothing should be draggable (Normal View selected, no row's own
    Enable-edit checked, or an enabled axis that doesn't match the
    current mode after a mode switch), so a plain None check here
    covers all of it uniformly."""
    # Always start clean.
    win.canvas.detach_manipulator()
    visual = getattr(win, "_section_clip_visual", None)
    if visual is not None:
        try:
            win.canvas.context.Erase(visual, True)
        except Exception as e:
            print(f"[section-view] visual erase failed: {e}")
        win._section_clip_visual = None

    target_plane = _get_clip_target_plane()
    if target_plane is None:
        return

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.AIS import AIS_Shape

    try:
        gp_pln = target_plane.ToPlane()
        center = gp_pln.Position().Location()
        marker_shape = BRepBuilderAPI_MakeVertex(center).Vertex()
        ais_shape = AIS_Shape(marker_shape)
        win.canvas.context.Display(ais_shape, False)  # redraw deferred
        # to attach_manipulator's own UpdateCurrentViewer() call, same
        # pattern it already uses for the gizmo itself
        win._section_clip_visual = ais_shape
    except Exception as e:
        print(f"[section-view] marker build failed: {e}")
        return

    win._section_clip_drag_orig_pln = target_plane.ToPlane()
    attached = win.canvas.attach_manipulator(
        [win._section_clip_visual],
        move_callback=_clip_plane_drag_update,
        done_callback=_clip_plane_drag_done,
        translate_only_axis=2)
    if attached:
        ax3 = gp_pln.Position()
        origin = ax3.Location()
        w_dir = ax3.Direction()
        u_dir = ax3.XDirection()
        win.canvas.reposition_manipulator(
            (origin.X(), origin.Y(), origin.Z()),
            (w_dir.X(), w_dir.Y(), w_dir.Z()),
            (u_dir.X(), u_dir.Y(), u_dir.Z()))


def _clip_plane_drag_update(delta_trsf):
    """Shared by move and done callbacks: reposition the ACTUAL
    Graphic3d_ClipPlane (not just the visual face) by the delta
    accumulated since the drag started, keeping the same normal.
    delta_trsf is the WORLD-space total delta so far (not
    incremental), per attach_manipulator's own documented contract --
    always computed fresh from the captured drag-start plane, so
    repeated calls during one drag can't drift.

    Session 116: targets _get_clip_target_plane() -- the same lookup
    _update_clip_visibility() used when it attached the manipulator
    in the first place, so this always stays consistent with
    whichever plane is actually being dragged."""
    target_plane = _get_clip_target_plane()
    orig_pln = getattr(win, "_section_clip_drag_orig_pln", None)
    if target_plane is None or orig_pln is None:
        return
    from OCP.gp import gp_Pln, gp_Pnt
    tp = delta_trsf.TranslationPart()
    orig_loc = orig_pln.Position().Location()
    normal = orig_pln.Position().Direction()
    new_loc = gp_Pnt(orig_loc.X() + tp.X(), orig_loc.Y() + tp.Y(),
                     orig_loc.Z() + tp.Z())
    new_pln = gp_Pln(new_loc, normal)
    target_plane.SetEquation(new_pln)
    win.canvas.view.Redraw()


def _clip_plane_drag_done(delta_trsf):
    """Done-callback wrapper -- Session 117 fix, confirmed via Doug's
    own terminal output (a stack trace directly from mouseReleaseEvent
    -> _manip_done_callback, not a guess): win._section_clip_drag_
    orig_pln was only ever captured ONCE, when the manipulator was
    first attached inside _update_clip_visibility(). The manipulator
    stays attached and draggable indefinitely afterward, with no
    re-attachment between separate drags -- so a SECOND drag of the
    same, already-attached manipulator incorrectly recomputed its new
    position as the ORIGINAL, attach-time baseline plus the new
    delta, rather than wherever the first drag had actually left it.
    Doug's own report matched this exactly: a real drag to a bolt,
    then a tiny, likely-accidental micro-drag just from re-grabbing
    the manipulator, snapped the real plane back to its starting
    point while the manipulator's own visual (unaffected by this
    calculation at all) stayed exactly where the first drag left it.

    Applies the final update via _clip_plane_drag_update() as before,
    then re-captures the target plane's own, now-current position as
    the new baseline -- so the NEXT drag, whenever it starts, begins
    from the right place. Deliberately only on done, not on every
    move event too -- attach_manipulator's own documented contract
    requires orig_pln to stay FIXED for the full duration of a single,
    continuous drag (delta_trsf is the total accumulated-so-far
    delta, not incremental); re-capturing on every move would break
    that and reintroduce drift within one drag.

    Session 120: also stores the plane's own new position via
    _store_plane_geom(), keyed by axis -- the actual position-memory
    wiring behind Doug's own request that toggling a plane off and
    back on not reset its own, already-adjusted position. Session 129:
    _store_plane_geom() is now flat/axis-only (no more mode dimension
    -- see its own docstring)."""
    _clip_plane_drag_update(delta_trsf)
    target_plane = _get_clip_target_plane()
    if target_plane is not None:
        win._section_clip_drag_orig_pln = target_plane.ToPlane()
        axis = getattr(win, "_section_clip_active_axis", None)
        if axis is not None:
            _store_plane_geom(axis, target_plane.ToPlane())


def _apply_section_capping():
    """Apply capping to every currently active clip plane. Called by
    _rebuild_section_clip_planes() whenever a new plane is built.
    SetCapping/SetCappingColor, confirmed via the original research
    as real Graphic3d_ClipPlane methods -- same class as SetOn/
    SetEquation/ToPlane, all already proven working live, unlike
    AIS_Plane (a different, presentation-layer class) which needed
    real diagnosis.

    SetUseObjectMaterial(True) added (Session 113, Doug's own
    observation against the CAD Assistant screenshot: color and
    hatching both convey real information a flat gray cap conceals --
    which part's material is at this cross-section, not just that a
    cut happened). Confirmed via official OCCT reference docs
    (consistent across 7.1 through 8.0): a real, documented flag,
    default FALSE, controlling whether capping material is taken from
    the object being cut instead of the plane's own fixed
    CappingColor/CappingMaterial. CONFIRMED live by Doug: works
    automatically for every object our single, global clip plane
    cuts -- no per-object association needed.

    Hatching was also tried, same session -- confirmed live to have
    no visible effect, then confirmed via two independent sources
    (an official OCCT forum reply, and a separate, unrelated project
    hitting the identical issue) as a genuine, acknowledged OCCT
    limitation: native hatch rendering depends on obsolete OpenGL
    functionality unavailable in modern Core Profile contexts, not
    fixable via a different call or style value. Removed by Doug's
    own call, rather than pursue the sanctioned workaround
    (SetCappingTexture, an actual image applied as a texture map) --
    treated as a nice-to-have, given color-from-object already
    delivers the main informational value on its own.

    Session 117 (Doug's own alternative, once hatching and texturing
    both looked like real steps up in scope): white edge lines along
    each part's own cut-surface boundary, matching how real part
    edges are already shown in black elsewhere. Confirmed via
    official OCCT reference docs plus a working, real-world code
    example: Graphic3d_AspectFillArea3d::SetEdgeOn()/SetEdgeColor()
    are real, and white is that class's own DEFAULT edge color
    already. Applied to the capping aspect Graphic3d_ClipPlane
    already exposes via CappingAspect() -- genuinely lower risk than
    texturing, no new image asset or object kind this project hasn't
    already used.

    First attempt also called SetCappingAspect(cap_aspect) explicitly
    after modifying it, on the assumption CappingAspect() might
    return a copy needing to be set back. Doug's own live test showed
    the whole cap rendering white instead of edges over the existing
    color-from-object fill -- consistent with that explicit re-set
    replacing the plane's entire capping aspect wholesale, discarding
    whatever UseObjectMaterial was doing internally, rather than
    modifying it in place as intended. Removed; CappingAspect()
    modified directly, with no re-set call at all, testing whether it
    already returns a live, mutable reference. Confirmed by Doug:
    still rendered solid white regardless -- edges genuinely don't
    combine with per-object color in this API. Removed entirely
    (Session 118): Doug's own call, given plain color-from-object is
    what he actually wants as the accepted result now, not color plus
    a broken white override.

    SetCappingColor also removed (Session 118), as a direct test of
    Doug's own observation: the isolated capping-texture test planes
    (never calling SetCappingColor at all, only SetUseObjectMaterial)
    looked distinctly cleaner and crisper than this function's own,
    real output. The docs describe CappingColor as simply unused
    once UseObjectMaterial is on, but that's a claim about the final
    color, not necessarily about every aspect of how the surface
    renders -- worth trusting Doug's own, direct side-by-side
    observation over an incomplete reading of the docs.

    Session 120 (Doug's own call, having lived with it a while):
    capping isn't optional preference at all, it's simply how a
    section view should always look -- toggle_section_capping and
    its own toolbar button removed entirely; this function no longer
    takes a persistent on/off flag into account, it just always
    applies."""
    planes = getattr(win, "_section_clip_planes", [])
    for plane in planes:
        try:
            plane.SetCapping(True)
            plane.SetUseObjectMaterial(True)
        except Exception as e:
            print(f"[section-view] capping failed: {e}")
    win.canvas.view.Redraw()


def _on_dir_checkbox_toggled(checked, axis):
    """Handler for every Dir checkbox (X/Y/Z) -- Session 129's
    FreeCAD-style redesign: independently toggleable, any combination
    of 0-3 checked at once, replacing the old 2-level Normal View/
    Section View switch plus 5-way exclusive mode selector entirely.
    None checked IS Normal View now -- there's no separate top-level
    switch to keep in sync with this anymore.

    Unchecking an axis that's currently the active Edit target clears
    active_axis too (rather than leaving it pointing at a plane that's
    about to stop existing) -- _get_clip_target_plane() would also
    catch this via the by_axis dict no longer having that key after
    rebuild, but clearing it explicitly here keeps
    win._section_clip_active_axis itself honest rather than relying on
    a downstream dict-miss to paper over a stale value.

    Session 130 (Doug's own report: unchecking Dir left Edit cleared
    correctly, but Rev stayed checked -- grayed out, and un-clickable,
    until Dir was checked again): unchecking also resets Rev for this
    axis, not just Edit. win._section_reversed[axis] is cleared, and
    if a plane position was already remembered for this axis
    (win._section_plane_state, Session 120's own memory mechanism),
    its stored normal is flipped back to match -- so a later recheck
    of this axis starts from a normal (non-reversed) state rather than
    silently coming back reversed the instant Rev shows unchecked.
    Position memory itself is left untouched either way -- Doug only
    asked about Rev, not the remembered drag position, and Session
    120's own position-preservation behavior still applies."""
    win._section_checked = getattr(win, "_section_checked", {})
    win._section_checked[axis] = checked
    if not checked:
        if getattr(win, "_section_clip_active_axis", None) == axis:
            win._section_clip_active_axis = None
        win._section_reversed = getattr(win, "_section_reversed", {})
        if win._section_reversed.get(axis):
            win._section_reversed[axis] = False
            stored = getattr(win, "_section_plane_state", {}).get(axis)
            if stored is not None:
                from OCP.gp import gp_Pln
                loc = stored.Position().Location()
                normal = stored.Position().Direction().Reversed()
                _store_plane_geom(axis, gp_Pln(loc, normal))
    _rebuild_section_clip_planes()
    _refresh_section_lower_controls()


def _on_reverse_checkbox_toggled(checked, axis):
    """Handler for every Reverse control -- one per axis (X/Y/Z),
    only ever enabled (clickable) while that axis's own Dir checkbox
    is checked (see _refresh_section_lower_controls()), so the live
    plane for this axis is guaranteed to exist in
    win._section_clip_planes_by_axis when this fires.

    Flips the plane's own live normal directly (SetEquation with the
    same location, reversed direction) rather than rebuilding the
    plane from scratch -- preserves whatever position it's currently
    at, including one that's already been dragged away from center.
    Stores the result via _store_plane_geom() (Session 120's own
    position-memory mechanism, shared with drag completion; Session
    129: flat, axis-only now) so the reversed state survives
    unchecking/rechecking this axis, or checking a different axis
    alongside it, too -- not just this immediate change. Refreshes the
    manipulator afterward in case it's currently attached to this same
    plane, so its own orientation follows the new normal rather than
    staying stale."""
    win._section_reversed = getattr(win, "_section_reversed", {})
    win._section_reversed[axis] = checked

    by_axis = getattr(win, "_section_clip_planes_by_axis", {})
    plane = by_axis.get(axis)

    if plane is not None:
        from OCP.gp import gp_Pln
        pln = plane.ToPlane()
        loc = pln.Position().Location()
        normal = pln.Position().Direction().Reversed()
        new_pln = gp_Pln(loc, normal)
        plane.SetEquation(new_pln)
        _store_plane_geom(axis, new_pln)
        win.canvas.view.Redraw()
        _update_clip_visibility()


def _on_edit_checkbox_toggled(checked, axis, other_btns=()):
    """Handler for every Edit control -- one per axis (X/Y/Z).
    win._section_clip_active_axis is the one, shared state behind all
    three (see _get_clip_target_plane()'s own docstring) -- only one
    plane can ever be the manipulator's own drag target at a time
    (translate_only_axis=2 manipulator mechanism), so Edit picks which
    one of the currently-checked (Dir) planes that is.

    Mutually exclusive AND all-can-be-unchecked at once, the default
    (Doug's own explicit confirmation, originally for the old X&Y
    mode's own Enable-X/Enable-Y pair, Session 129: generalized from 2
    rows to 3) -- not a standard Qt exclusive group, since
    QButtonGroup's own setExclusive(True) forces exactly one button
    always checked, with no way back to zero. Wired by hand instead:
    checking one unchecks every OTHER currently-checked Edit box
    directly, via blockSignals so their own handlers don't also fire
    and race to overwrite active_axis right afterward."""
    if checked:
        for btn in other_btns:
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
    win._section_clip_active_axis = axis if checked else None
    _update_clip_visibility()


def _refresh_section_lower_controls():
    """Sync every Edit and Reverse control's own enabled/disabled
    state, plus Edit's own checked/unchecked display state, to match
    which axes are currently checked. Session 129: replaces the old
    mode-matching version -- there's no more "current mode" to match
    against, just "is this row's own Dir box checked." Also called
    once at toolbar-build time, so a freshly-built toolbar starts in a
    correct, consistent state rather than whatever Qt's own widget
    defaults happen to be.

    Edit's own CHECKED state is derived fresh each time from
    win._section_clip_active_axis (a single, shared "which row" value,
    unchanged from before); Reverse's own CHECKED state is read
    directly from win._section_reversed, an independent, per-axis flag
    that isn't tied to whether Edit happens to be on for that same row
    at all."""
    checked_axes = getattr(win, "_section_checked", {})
    active_axis = getattr(win, "_section_clip_active_axis", None)
    reversed_state = getattr(win, "_section_reversed", {})

    edit_buttons = getattr(win, "_section_edit_buttons", {})
    for axis, btn in edit_buttons.items():
        is_on = checked_axes.get(axis, False)
        btn.setEnabled(is_on)
        btn.blockSignals(True)
        btn.setChecked(is_on and active_axis == axis)
        btn.blockSignals(False)

    reverse_buttons = getattr(win, "_section_reverse_buttons", {})
    for axis, btn in reverse_buttons.items():
        is_on = checked_axes.get(axis, False)
        btn.setEnabled(is_on)
        btn.blockSignals(True)
        btn.setChecked(reversed_state.get(axis, False))
        btn.blockSignals(False)


def build_section_view_toolbar():
    """Populate the Section View toolbar (mainwindow.py's own
    sectionViewToolBar, docked Qt.RightToolBarArea, stacked below
    wcToolBar/wgToolBar). Called once at startup.

    Session 129: rebuilt around Doug's own FreeCAD-style redesign --
    "I had a look at the way FreeCAD implements the section view UI
    and I decided I like their way better." The old 2-level design
    (Session 119: a top-level Normal View/Section View switch, then a
    lower, 5-way-exclusive X/Y/Z/XY mode selector) is gone entirely.
    Now just one, flat Dir/Edit/Rev table, one row per principal axis
    (X, Y, Z), each with its own independently-toggleable Dir
    checkbox -- zero checked is Normal View, any combination of 1-3
    gives that combination's own section view (including the 3-plane
    case the old design never actually built). No more special-cased
    "XY" row with label-only sub-rows either -- every row is now
    structurally identical, since there's no longer a single
    multi-plane "mode" that owns 2 particular axes together.

    Still the same 3 functional columns Doug asked to keep -- Dir,
    Edit, Rev -- with a 4th, unlabeled column on the left for each
    row's own X/Y/Z identity (previously carried by the Dir button's
    own icon/text; now that Dir is a plain checkbox like Edit and Rev,
    the row needs its own label instead). Only Edit/Rev are still
    conditionally enabled (per-row, via _refresh_section_lower_
    controls -- grayed out until that row's own Dir box is checked);
    Dir itself is always enabled, there's no higher-level switch left
    to gray it out at all.

    Capping is still not a toggle here at all (Session 120, Doug's own
    call: always capped, not a preference).

    Session 131 (cosmetic pass, once the checkbox redesign had
    decluttered this section enough to be worth polishing): a bold
    "Clipping" title row added above the Dir/Pos/Rev header, matching
    the "2D Tools" title Doug asked added to the toolbar stacked right
    above this one in the same right-dock area -- subtle visual
    separation between the two, no structural change. Also "Edit" ->
    "Pos" in the header (Doug's own call, to keep the toolbar narrow)
    -- display text only; the checkbox's own tooltip and every
    internal name (_section_edit_buttons, _on_edit_checkbox_toggled)
    are unchanged."""
    from PySide6.QtWidgets import QWidget, QGridLayout, QCheckBox, QLabel
    from PySide6.QtGui import QFont
    from PySide6.QtCore import Qt

    _panel = QWidget()
    _grid = QGridLayout(_panel)
    _grid.setContentsMargins(2, 2, 2, 2)
    _grid.setSpacing(2)

    # Session 131 (Doug's own cosmetic pass, once the checkbox
    # redesign had decluttered this section enough to be worth
    # polishing): a bold section title, matching the one added to the
    # 2D tool panel right above it in the same toolbar stack -- subtle
    # visual separation between the two stacked sections, with no
    # structural change underneath.
    # Session 131 addendum: Doug's live-test screenshot showed the
    # title sitting flush against the left edge instead of centered
    # over the (narrower) table below it -- QLabel defaults to
    # left-aligned text. Explicitly centered now.
    _title = QLabel("Clipping")
    _title_font = QFont()
    _title_font.setBold(True)
    _title.setFont(_title_font)
    _title.setAlignment(Qt.AlignCenter)
    _grid.addWidget(_title, 0, 0, 1, 4)

    _grid.addWidget(QLabel(""), 1, 0)
    _grid.addWidget(QLabel("Dir"), 1, 1)
    # Session 131: "Edit" -> "Pos" (Doug's own call, to keep the
    # overall toolbar narrow -- 3 letters instead of 4). Only the
    # displayed header text changes; the checkbox's own tooltip
    # ("Enable dragging the ... plane") and every internal name
    # (_section_edit_buttons, _on_edit_checkbox_toggled, etc.) are
    # unchanged -- this is a label change, not a renamed concept.
    _grid.addWidget(QLabel("Pos"), 1, 2)
    _grid.addWidget(QLabel("Rev"), 1, 3)

    win._section_checked = {}
    win._section_edit_buttons = {}
    win._section_reverse_buttons = {}
    _edit_btns_by_axis = {}

    for _row, _axis in enumerate(_SECTION_AXES, start=2):
        _grid.addWidget(QLabel(_axis.upper()), _row, 0)

        _dir_cb = QCheckBox()
        _dir_cb.setToolTip(f"Show the {_axis.upper()} section plane")
        _dir_cb.toggled.connect(
            lambda checked, a=_axis: _on_dir_checkbox_toggled(checked, a))
        _grid.addWidget(_dir_cb, _row, 1)

        _edit_cb = QCheckBox()
        _edit_cb.setToolTip(f"Enable dragging the {_axis.upper()} plane")
        win._section_edit_buttons[_axis] = _edit_cb
        _edit_btns_by_axis[_axis] = _edit_cb
        _grid.addWidget(_edit_cb, _row, 2)

        _rev_cb = QCheckBox()
        _rev_cb.setToolTip(f"Reverse the {_axis.upper()} plane's own normal")
        _rev_cb.toggled.connect(
            lambda checked, a=_axis: _on_reverse_checkbox_toggled(checked, a))
        win._section_reverse_buttons[_axis] = _rev_cb
        _grid.addWidget(_rev_cb, _row, 3)

    # Edit's own mutually-exclusive-but-all-can-be-off wiring needs
    # every row's checkbox to exist first (each one's "other" list is
    # the other two), so connected in a second pass.
    for _axis, _cb in _edit_btns_by_axis.items():
        _others = [b for a, b in _edit_btns_by_axis.items() if a != _axis]
        _cb.toggled.connect(
            lambda checked, a=_axis, o=_others:
                _on_edit_checkbox_toggled(checked, a, o))

    win.sectionViewToolBar.addWidget(_panel)
    _refresh_section_lower_controls()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    menu = win.menuBar()
    file_menu = win.add_menu("File")
    win.add_function_to_menu("File", "Load Session", load_session)
    win.add_function_to_menu("File", "Save Session", dm.save_step_doc)
    file_menu.addSeparator()
    win.add_function_to_menu("File", "Import STEP", import_step)
    edit_menu = win.add_menu("Edit")
    win.add_function_to_menu("Edit", "Undo    (Ctrl+Z)", win.editUndo)
    win.add_function_to_menu("Edit", "Redo    (Ctrl+Y)", win.editRedo)

    win.add_menu("Workplane")
    win.add_function_to_menu("Workplane", "At Origin, XY Plane", makeWP)
    win.add_function_to_menu("Workplane", "On face", wpOnFace)
    win.add_function_to_menu("Workplane", "By 3 points", wpBy3Pts)
    win.add_function_to_menu(
        "Workplane", "Point && Direction", wpByPtDir)
    win.add_function_to_menu("Workplane", "Set...", makeWpSet)
    # Session 96: the "crystal ball" end state from Doug's own
    # Pull_Dialog_Specification.pdf, now realized -- Create 3D and
    # Modify Active Part are gone, folded into one Create/Modify menu
    # (Doug: dropped the "3D" to match the rest of the bar's own
    # one-word rhythm -- File, Edit, Workplane, Position, Utility).
    # Deferred deliberately back in Session 93 until Pull was
    # genuinely feature-complete (Linear, then Angular, both tested
    # against real geometry) -- that's now true, so the swap and the
    # accompanying dead-code removal (extrude/revolve/mill/pull and
    # mill_pull_dialog.py, all superseded) happen together, this
    # session, matching Doug's own "rip it out by the roots" call
    # rather than leave any of it as orphaned, unreferenced code.
    win.add_menu("Create/Modify")
    from pull_dialog import show_pull_dialog
    win.add_function_to_menu(
        "Create/Modify", "Pull", lambda: show_pull_dialog(win))
    win.add_function_to_menu("Create/Modify", "Fillet", fillet)
    win.add_function_to_menu("Create/Modify", "Chamfer", chamfer)
    win.add_function_to_menu("Create/Modify", "Shell", shell)
    win.add_function_to_menu("Create/Modify", "Loft", loftWpSet)
    win.add_function_to_menu(
        "Create/Modify", "Defeaturing...",
        lambda: show_defeaturing_dialog(win))
    win.add_menu("Position")
    win.add_function_to_menu("Position", "Workplane", position_selected_wp)
    win.add_function_to_menu("Position", "Part/Asy", position_selected)
    win.add_menu("Utility")
    win.add_function_to_menu(
        "Utility", "Undo/Redo count", show_undo_redo_count)
    from xde_tree_dialog import show_xde_tree_dialog
    win.add_function_to_menu(
        "Utility", "XDE Label Hierarchy...",
        lambda: show_xde_tree_dialog(win))
    win.add_function_to_menu("Utility", "print label_dict", print_uid_dict)
    win.add_function_to_menu("Utility", "print part_dict", print_part_dict)
    win.add_function_to_menu("Utility", "dump doc", dumpDoc)
    win.add_function_to_menu("Utility", "Topology of Act Prt", topoDumpAP)
    win.add_function_to_menu(
        "Utility", "print(Active Wp Info)", printActiveWpInfo)
    win.add_function_to_menu(
        "Utility", "print(Active Asy Info)", printActiveAsyInfo)
    win.add_function_to_menu(
        "Utility", "print(Active Prt Info)", printActivePartInfo)
    win.add_function_to_menu(
        "Utility", "Clear Line Edit Stack", win.clearLEStack)
    win.add_function_to_menu("Utility", "Calculator", win.launchCalc)
    win.add_function_to_menu("Utility", "set Units ->in", setUnits_in)
    win.add_function_to_menu("Utility", "set Units ->mm", setUnits_mm)

    drawSubMenu = QMenu("Draw")
    win.popMenu.addMenu(drawSubMenu)
    drawSubMenu.addAction("Fit", win.fitAll)

    win.show()
    win.canvas.InitDriver()
    win.canvas.update()
    display = win.canvas._display
    win.install_highlight_sync()  # bidirectional tree<->viewport
    # Snap engine step 1 (Session 62): hover-only snap marker --
    # shows what the engine would catch; changes no tool behavior.
    from snap_engine import SnapHover
    win.snap_hover = SnapHover(win)
    win.canvas.register_move_callback(win.snap_hover.on_move)
    # Middle-click = End Operation (CoCreate/Pyurcad muscle memory)
    win.canvas.on_middle_click = win.clearCallback
    a2d = M2D(win, display)

    selectSubMenu = QMenu("Select Mode")
    win.popMenu.addMenu(selectSubMenu)
    selectSubMenu.addAction("Vertex", display.SetSelectionModeVertex)
    selectSubMenu.addAction("Edge", display.SetSelectionModeEdge)
    selectSubMenu.addAction("Face", display.SetSelectionModeFace)
    selectSubMenu.addAction("Shape", display.SetSelectionModeShape)
    selectSubMenu.addAction("Neutral", display.SetSelectionModeNeutral)
    win.popMenu.addAction("Clear Callback", win.clearCallback)
    # ==== 2-COLUMN 2D TOOL PANEL (Session 63, Doug's layout PDF:
    # Pyurcad's tool set, two columns on the right edge, deletes
    # quarantined at the bottom behind a separator). Disabled
    # buttons = tools not yet implemented; they enable as each
    # lands. noop.gif lives in the Pyurcad icons folder -- copy it
    # over (text fallback until then). ====
    from PySide6.QtWidgets import (QWidget, QGridLayout, QToolButton,
                                   QFrame, QLabel)
    from PySide6.QtGui import QFont
    from PySide6.QtCore import QSize, Qt

    _TOOL_LAYOUT = [
        ("noop.gif", "End Operation", win.clearCallback),
        ("hvcl.gif", "H + V Construction Lines", a2d.clineHV),
        ("hcl.gif", "Horizontal Construction Line", a2d.clineH),
        ("vcl.gif", "Vertical Construction Line", a2d.clineV),
        ("tpcl.gif", "Construction Line by 2 Points", a2d.cline2Pts),
        ("acl.gif", "Angled Construction Line", a2d.clineAng),
        ("refangcl.gif", "Reference-Angle Constr Line",
         a2d.clineRefAng),
        ("abcl.gif", "Angular Bisector", a2d.clineAngBisec),
        ("lbcl.gif", "Linear Bisector", a2d.clineLinBisec),
        ("parcl.gif", "Parallel Construction Line", a2d.clinePara),
        ("perpcl.gif", "Perpendicular Constr Line", a2d.clinePerp),
        ("cltan1.gif", "Tangent to Circle", a2d.clineTan1),
        ("cltan2.gif", "Tangent to 2 Circles", a2d.clineTan2),
        ("ccirc.gif", "Construction Circle", a2d.ccirc),
        ("cc3p.gif", "Constr Circle by 3 Points", a2d.cc3p),
        ("cccirc.gif", "Concentric Constr Circle", a2d.cccirc),
        ("proj_edge.gif", "Project Edge", a2d.projectEdge),
        ("proj_face.gif", "Project Face Edges", a2d.projectFaceEdges),
        "SEP",
        ("line.gif", "Line", a2d.line),
        ("poly.gif", "Polyline", a2d.poly),
        ("rect.gif", "Rectangle", a2d.rect),
        ("circ.gif", "Circle", a2d.circle),
        ("arcc2p.gif", "Arc: Center + 2 Points", a2d.arcc2p),
        ("arc3p.gif", "Arc by 3 Points", a2d.arc3p),
        ("slot.gif", "Slot", a2d.slot),
        ("fillet.gif", "2D Fillet", a2d.fillet2d),
        "SEP",
        ("del_cel.gif", "Delete Construction Element", a2d.delCl),
        ("del_constr.gif", "Delete ALL Construction",
         a2d.delAllConstr),
        ("del_el.gif", "Delete Geometry Element", a2d.delEl),
        ("del_geom.gif", "Delete ALL Geometry", a2d.delAllGeom),
    ]
    _panel = QWidget()
    _grid = QGridLayout(_panel)
    _grid.setContentsMargins(2, 2, 2, 2)
    _grid.setSpacing(2)

    # Session 131 (Doug's own cosmetic pass): a bold section title,
    # matching the "Clipping" title added to the Section View toolbar
    # stacked right below this one in the same right-dock area --
    # subtle visual separation between the two, no structural change.
    _title = QLabel("2D Tools")
    _title_font = QFont()
    _title_font.setBold(True)
    _title.setFont(_title_font)
    _title.setAlignment(Qt.AlignCenter)
    _grid.addWidget(_title, 0, 0, 1, 2)

    _row = 1
    _col = 0
    for _item in _TOOL_LAYOUT:
        if _item == "SEP":
            if _col == 1:
                _row += 1
                _col = 0
            _sep = QFrame()
            _sep.setFrameShape(QFrame.HLine)
            _sep.setFrameShadow(QFrame.Sunken)
            _grid.addWidget(_sep, _row, 0, 1, 2)
            _row += 1
            continue
        _iconfile, _tip, _handler = _item
        _btn = QToolButton()
        _pix = QPixmap(f"icons/{_iconfile}")
        if not _pix.isNull():
            _btn.setIcon(QIcon(_pix))
            _btn.setIconSize(QSize(24, 24))
        else:
            _btn.setText(_tip.split()[0][:5])
        if _handler is not None:
            _btn.setToolTip(_tip)
            _btn.clicked.connect(_handler)
        else:
            _btn.setToolTip(_tip + "  (not yet implemented)")
            _btn.setEnabled(False)
        _grid.addWidget(_btn, _row, _col)
        _col += 1
        if _col == 2:
            _col = 0
            _row += 1
    win.wcToolBar.clear()
    win.wcToolBar.addWidget(_panel)
    win.wgToolBar.setVisible(False)

    build_section_view_toolbar()

    win.raise_()  # bring the app to the top
    app.exec()
