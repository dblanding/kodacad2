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
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.gp import gp_Ax1, gp_Ax3, gp_Dir, gp_Lin, gp_Pnt, gp_Trsf, gp_Vec
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Face, TopoDS_Vertex
from OCP.TopTools import TopTools_ListOfShape
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QTreeWidgetItemIterator

from m2d import M2D
import stepanalyzer
import docmodel
from mainwindow import MainWindow, dm
from OCCUtils import Topology
import workplane
from workplane import face_normal

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
    """Direction from pt1 to pt2 sets wDir, pt2 is wpOrigin.
    Direction from pt2 to pt3 sets uDir."""

    prev_uid = win.activeWpUID  # uid of currently active workplane
    if win.ptStack:
        # Finish
        p3 = win.ptStack.pop()
        p2 = win.ptStack.pop()
        p1 = win.ptStack.pop()
        wVec = gp_Vec(p1, p2)
        wDir = gp_Dir(wVec)
        origin = p2
        uVec = gp_Vec(p2, p3)
        uDir = gp_Dir(uVec)
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
        statusText = "Pick 3 points. Dir from pt1-pt2 sets wDir, pt2 is origin."
        win.statusBar().showMessage(statusText)
        return


def wpBy3PtsC(shapeList, *args):
    """Callbask (collector) for wpBy3Pts"""

    for shape in shapeList:
        vrtx = TopoDS.Vertex_s(shape)
        gpPt = BRep_Tool.Pnt_s(vrtx)  # convert vertex to gp_Pnt
        win.ptStack.append(gpPt)
    if len(win.ptStack) == 1:
        statusText = "Now select point 2 (wp origin)."
        win.statusBar().showMessage(statusText)
    elif len(win.ptStack) == 2:
        statusText = "Now select point 3 to set uDir."
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
    win.build_tree()
    if ref_entry:
        force = {u for u, info in dm.label_dict.items()
                if info.get('ref_entry') == ref_entry and u in dm.part_dict}
    else:
        force = set()
    win._incremental_reconcile(old_uids, force_redraw_uids=force)


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


def removeHole(event=None):
    """Remove a simple cylindrical hole (blind or through) from the
    active part, healing the surrounding geometry, via OCP's
    BRepAlgoAPI_Defeaturing.

    Deliberately scoped narrow for now (Doug's own step-at-a-time
    preference): one simple cylindrical hole per operation. Confirmed
    working via the Utility menu smoke tests that preceded this --
    both on synthetic geometry and on a real, imported goBILDA part --
    including the discovery that a hole's cylindrical surface can be
    split into multiple face patches (picking captures only one; the
    algorithm needs the complete set), and that a blind hole's own
    bottom cap is healed automatically once the cylindrical wall is
    removed, with no separate cap handling needed.
    """
    if not require_active_part("Remove Hole"):
        return
    win.registerCallback(removeHoleC)
    display.SetSelectionModeFace()
    win.statusBar().showMessage(
        "Select a cylindrical face (a hole) to remove.")


def removeHoleC(shapeList, *args):
    """Callback (collector) for removeHole."""
    if not shapeList:
        return
    try:
        picked_face = TopoDS.Face_s(shapeList[0])
    except Exception:
        win.statusBar().showMessage(
            "Pick a face (not an edge or vertex).")
        return

    # Ownership check -- same pattern fillet()/shell() already use:
    # compare against the part's own DISPLAYED reference shape (which
    # may be NurbsConverted), not win.activePart directly.
    uid = win.activePartUID
    cached = win._display_prep_cache.get(uid)
    ref_shape = cached[1] if cached is not None else win.activePart
    ref_faces = list(Topology.Topo(ref_shape).faces()) \
        if ref_shape is not None else []
    if not any(picked_face.IsSame(f) for f in ref_faces):
        win.statusBar().showMessage(
            "Selected face must be in Active Part.")
        return

    surf = BRepAdaptor_Surface(picked_face)
    if surf.GetType() != GeomAbs_Cylinder:
        win.statusBar().showMessage(
            "Pick a cylindrical face (a hole) -- other feature "
            "types aren't supported yet.")
        return
    win.clearCallback()

    # Same analytic-mapping pattern as fillet()/shell() (Session 91):
    # a picked face may come from a NurbsConverted display surrogate
    # rather than the part's own real geometry.
    face_prep = win._face_prep_map.get(uid)
    if face_prep is not None:
        analytic_shape, face_pairs, _edge_pairs = face_prep
        matched = _match_analytic_subshape(
            picked_face, analytic_shape, face_pairs, TopAbs_FACE)
        workPart = analytic_shape
        work_face = matched if matched is not None else picked_face
    else:
        workPart = ref_shape
        work_face = picked_face

    # Multi-patch collection: find every face sharing the SAME
    # underlying cylinder (same axis, same radius) as the picked one,
    # rather than pass only the single patch that was clicked.
    picked_surf = BRepAdaptor_Surface(work_face)
    matching_faces = [work_face]
    try:
        cyl1 = picked_surf.Cylinder()
        ax1 = cyl1.Axis()
        r1 = cyl1.Radius()
        line1 = gp_Lin(ax1)
        exp = TopExp_Explorer(workPart, TopAbs_FACE)
        while exp.More():
            f = TopoDS.Face_s(exp.Current())
            if not f.IsSame(work_face):
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
        print(f"[removeHole] multi-patch detection failed ({e}) -- "
             f"falling back to the single picked face")
        matching_faces = [work_face]

    print(f"[removeHole] {len(matching_faces)} cylindrical face(s) "
         f"share the picked face's own surface")

    # Doug's own finding (re-watching the source video): a blind hole
    # built this way (sketch + prism + cut, not a native cylinder
    # primitive) needs its BOTTOM CAP explicitly added too, not just
    # the cylindrical wall -- confirmed directly by a synthetic test
    # mirroring the real construction path, which failed identically
    # to Doug's own part until the cap was included. Found by
    # adjacency: any face sharing an edge with a collected cylindrical
    # face. Restricted to faces bounded by exactly one edge (a simple,
    # fully-closed cap) to avoid also picking up the block's own top
    # face, which is ALSO adjacent to the cylinder's top edge but is
    # part of the surrounding geometry, not the feature -- adding
    # that one would be a genuine mistake, not just a missed one.
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
            print(f"[removeHole] {len(cap_faces)} cap face(s) found "
                 f"adjacent to the cylindrical wall -- adding them "
                 f"too")
            matching_faces.extend(cap_faces)
    except Exception as e:
        print(f"[removeHole] cap-face detection failed ({e}) -- "
             f"proceeding with cylindrical face(s) only")

    dfr = BRepAlgoAPI_Defeaturing()
    dfr.SetShape(workPart)
    for f in matching_faces:
        dfr.AddFaceToRemove(f)
    dfr.Build()
    print(f"[removeHole] IsDone={dfr.IsDone()}")
    if not dfr.IsDone():
        win.statusBar().showMessage(
            "Unable to remove this hole -- the surrounding geometry "
            "couldn't be healed.")
        return
    newPart = dfr.Shape()

    # Doug's own report: IsDone=True on both the through hole AND the
    # blind hole, but only the through hole was actually removed --
    # a claimed success that doesn't match what's on screen. Checking
    # the actual result shape directly, before it's ever written back
    # to the document, rather than trust IsDone=True at face value a
    # second time: does the face count genuinely reflect a removal,
    # or is IsDone=True trivially true without one?
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
    print(f"[removeHole] faces before={n_before}, after={n_after}")

    try:
        win.erase_shape(uid)
        ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
        old_uids = set(dm.part_dict.keys())
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        _redraw_after_shape_replace(ref_entry, old_uids)
        win.statusBar().showMessage("Hole removed.")
    except Exception as e:
        print(f"Unable to replace/draw shape. {e}")
        win.redraw()
    win.setActivePart(uid)


def removeIsolatedFeature(event=None):
    """Remove an arbitrary, isolated feature (a slot, pocket, or any
    shape bounded by a specific set of faces) from the active part,
    healing the surrounding geometry, via OCP's
    BRepAlgoAPI_Defeaturing -- confirmed general-purpose via a
    synthetic through-slot smoke test (4 flat wall faces, no
    cylindrical geometry at all: 10 faces before, 6 after, valid),
    per Quaoar's own description of the algorithm's real capability.

    Deliberately kept SEPARATE from Remove Hole (Doug's own explicit
    choice), rather than merged into it or replacing it -- Remove
    Hole's own single-click convenience and automatic cylindrical
    multi-patch/cap detection stay exactly as they are, untouched and
    still proven. This tool instead asks the user to pick every face
    bounding the feature manually (no automatic surface-matching at
    all), then press Enter to execute -- Quaoar's own terminology,
    "Remove Isolated Feature", used directly, per Doug's own request.
    """
    if not require_active_part("Remove Isolated Feature"):
        return
    win.registerCallback(removeIsolatedFeatureC)
    display.SetSelectionModeFace()
    win.statusBar().showMessage(
        "Select all faces bounding the feature to remove, then "
        "press Enter.")


def removeIsolatedFeatureC(shapeList, *args):
    """Callback (collector) for removeIsolatedFeature. Accumulates
    picked faces into win.faceStack (shared with shell(), never
    simultaneously active, same convention chamfer() already uses
    with win.edgeStack). An empty shapeList means Enter was pressed:
    mainwindow.py's own appendToStack() (the Enter handler) appends
    whatever's in the line edit -- even an empty string -- and calls
    the registered callback with cb([]) regardless, so no numeric
    value is needed here at all, unlike Fillet or Chamfer.

    win.lineEdit.setFocus() (Doug's own report: Enter needed a
    manual click into the line edit first, before it would register
    at all) -- missing from the very first version. filletC() has
    exactly this call as its own first line, for exactly this reason:
    without it, Enter routes wherever focus already is (the
    viewport), not to the line edit that's actually listening for it.
    """

    win.lineEdit.setFocus()
    uid = win.activePartUID

    if shapeList:
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
        win.statusBar().showMessage(
            f"Face {count} selected. Add more faces or press Enter "
            f"to remove the feature.")
        return

    # shapeList is empty -- Enter was pressed
    if not win.faceStack:
        win.statusBar().showMessage(
            "Pick at least one face before pressing Enter.")
        return
    picked_faces = list(win.faceStack)
    win.faceStack = []
    win.clearCallback()

    # Same analytic-mapping pattern as fillet()/chamfer()/removeHole
    # (Session 91): a picked face may come from a NurbsConverted
    # display surrogate rather than the part's own real geometry.
    cached = win._display_prep_cache.get(uid)
    ref_shape = cached[1] if cached is not None else win.activePart
    face_prep = win._face_prep_map.get(uid)
    if face_prep is not None:
        analytic_shape, face_pairs, _edge_pairs = face_prep
        workPart = analytic_shape
        mapped_faces = []
        for picked_face in picked_faces:
            matched = _match_analytic_subshape(
                picked_face, analytic_shape, face_pairs, TopAbs_FACE)
            if matched is not None:
                mapped_faces.append(TopoDS.Face_s(matched))
            else:
                print(f"[removeIsolatedFeature] picked face has no "
                     f"analytic counterpart at all -- skipping it "
                     f"rather than risk a mismatch")
        picked_faces = mapped_faces
    else:
        workPart = ref_shape

    if not picked_faces:
        win.statusBar().showMessage("No usable faces to remove.")
        return

    dfr = BRepAlgoAPI_Defeaturing()
    dfr.SetShape(workPart)
    for f in picked_faces:
        dfr.AddFaceToRemove(f)
    dfr.Build()
    print(f"[removeIsolatedFeature] IsDone={dfr.IsDone()}")
    if not dfr.IsDone():
        win.statusBar().showMessage(
            "Unable to remove this feature -- the surrounding "
            "geometry couldn't be healed.")
        return
    newPart = dfr.Shape()

    # Same before/after face-count safety check as removeHoleC
    # (Session 103): IsDone=True alone turned out NOT to be
    # trustworthy on its own for this algorithm.
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
    print(f"[removeIsolatedFeature] faces before={n_before}, "
         f"after={n_after}")

    try:
        win.erase_shape(uid)
        ref_entry = dm.label_dict.get(uid, {}).get('ref_entry')
        old_uids = set(dm.part_dict.keys())
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        _redraw_after_shape_replace(ref_entry, old_uids)
        win.statusBar().showMessage("Feature removed.")
    except Exception as e:
        print(f"Unable to replace/draw shape. {e}")
        win.redraw()
    win.setActivePart(uid)


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


def _get_plane_geom(mode, axis):
    """The gp_Pln to use when (re)building a given (mode, axis)
    plane. Session 120 (Doug's own request: toggling back and forth
    to Normal View, or between modes, shouldn't reset a plane's own,
    already-adjusted position): checks win._section_plane_state
    first, restoring exactly where that specific plane was last left
    (position AND normal both) if it's been built before. Only when
    nothing's been remembered yet -- the very first time this
    particular (mode, axis) plane is ever activated -- does it fall
    back to a fresh build, centered on the scene's own current
    bounding box (Session 112), with the base normal from
    _AXIS_NORMALS reversed first if this (mode, axis) row's own
    Reverse checkbox is currently checked (win._section_reversed)."""
    from OCP.gp import gp_Pln, gp_Pnt
    stored = getattr(win, "_section_plane_state", {}).get(
        mode, {}).get(axis)
    if stored is not None:
        return stored
    cx, cy, cz = _scene_bbox_center()
    normal = _AXIS_NORMALS[axis]
    reversed_state = getattr(win, "_section_reversed", {}).get(
        mode, {}).get(axis, False)
    if reversed_state:
        normal = normal.Reversed()
    return gp_Pln(gp_Pnt(cx, cy, cz), normal)


def _store_plane_geom(mode, axis, pln):
    """Remember a (mode, axis) plane's own current position and
    normal (a full gp_Pln, capturing both at once), so a future
    rebuild -- switching modes and back, or toggling Normal/Section
    View -- restores it via _get_plane_geom() instead of resetting to
    the scene's own bounding-box center. Called after every completed
    drag (_clip_plane_drag_done) and every Reverse toggle
    (_on_reverse_checkbox_toggled), the only two things that ever
    change a plane's own geometry after it's first built."""
    win._section_plane_state = getattr(win, "_section_plane_state", {})
    win._section_plane_state.setdefault(mode, {})[axis] = pln


def set_section_view_mode(mode):
    """Apply a section-view configuration -- Doug's own confirmation,
    reading the CAD Assistant screenshot's tooltip list: the first
    six options (Off, DX, DY, DZ, 2 planes, 3 planes) are mutually
    exclusive, "what we used to call radio buttons" -- not six
    independent toggles. Removes whatever's currently active first,
    then builds the new configuration, if any -- only one mode is
    ever live at a time.

    'off', 'x', 'y', 'z', and 'xy' (2 planes, chained via
    SetChainNextPlane -- a logical AND, a point must satisfy both to
    remain visible) are built so far -- 'xyz' (3 planes) is the next
    step.

    _update_clip_visibility() now handles every mode uniformly,
    single-axis and xy alike (Session 116) -- it targets whichever
    plane _get_clip_target_plane() returns, which is
    win._section_clip_planes[0] for single-axis modes (unchanged) or
    whichever axis the toolbar's own Edit X/Edit Y switch currently
    has selected for xy mode. Replaced an earlier, abandoned design
    where xy mode built real, visible, independently-clickable plane
    faces and a persistent 3D click handler -- CAD Assistant's own
    interaction model, matching how the operator actually clicks a
    plane there directly. Dropped after live testing surfaced three
    distinct problems in a row (a parameter mismatch, a stale-
    reference bug after dragging, and what testing indicated was very
    likely OCCT's own depth-based picking overriding
    SelectionPriority rather than respecting it) -- Doug's own call,
    given the mounting friction: a toolbar switch reusing the
    existing, already-proven single-manipulator machinery entirely
    unchanged, rather than detecting which of several 3D faces got
    clicked.

    Session 119: called with "off" whenever the toolbar's own top-
    level switch reads Normal View, to tear the actual clip planes
    down -- but this no longer overwrites win._section_clip_mode when
    that happens, so the lower X/Y/Z/X&Y group's own last selection
    survives the round trip and is restored correctly whenever
    Section View gets re-enabled, rather than being lost to "off",
    which isn't even a valid value in that group anymore.

    Session 120: plane geometry now comes from _get_plane_geom()
    rather than always being built fresh here -- restoring each
    plane's own, last-remembered position and normal (see that
    function's own docstring) rather than resetting it on every mode
    switch or Normal/Section View toggle. Capping is now unconditional
    (Doug's own call, having lived with it a while: not a preference,
    just how a section view should always look) -- no separate
    persistent flag to preserve across mode changes anymore.

    Reversed normal (Doug's own reading of the CAD Assistant
    screenshot) is now built too (Session 120), per-plane rather than
    a single, global toggle -- see _get_plane_geom() and
    _on_reverse_checkbox_toggled()."""
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.Graphic3d import Graphic3d_ClipPlane

    existing = getattr(win, "_section_clip_planes", [])
    for plane in existing:
        try:
            win.canvas.view.RemoveClipPlane(plane)
        except Exception as e:
            print(f"[section-view] remove failed: {e}")
    win._section_clip_planes = []

    if mode in _AXIS_NORMALS:
        try:
            plane_geom = _get_plane_geom(mode, mode)
            clip_plane = Graphic3d_ClipPlane(plane_geom)
            clip_plane.SetOn(True)
            win.canvas.view.AddClipPlane(clip_plane)
            win._section_clip_planes = [clip_plane]
        except Exception as e:
            print(f"[section-view] {mode.upper()} clip plane failed: {e}")
    elif mode == "xy":
        # Session 114: proved the chained, combined cut works on its
        # own first (SetChainNextPlane -- a logical AND: a point must
        # satisfy BOTH planes to remain visible; only the first plane
        # in the chain is added to the view, the chained one is
        # implicit) before building anything visual or interactive on
        # top of it. Visibility/dragging wired in Session 116, via
        # the toolbar Edit X/Edit Y switch -- see
        # _get_clip_target_plane().
        try:
            plane_x_geom = _get_plane_geom("xy", "x")
            plane_y_geom = _get_plane_geom("xy", "y")
            plane_x = Graphic3d_ClipPlane(plane_x_geom)
            plane_y = Graphic3d_ClipPlane(plane_y_geom)
            plane_x.SetOn(True)
            plane_y.SetOn(True)
            plane_x.SetChainNextPlane(plane_y)
            win.canvas.view.AddClipPlane(plane_x)
            win._section_clip_planes = [plane_x, plane_y]
            win._section_clip_planes_by_axis = {"x": plane_x, "y": plane_y}
        except Exception as e:
            print(f"[section-view] XY clip plane failed: {e}")
    elif mode != "off":
        print(f"[section-view] mode {mode!r} not yet built")

    if mode != "off":
        win._section_clip_mode = mode
    win.canvas.view.Redraw()
    _apply_section_capping()
    _update_clip_visibility()


def _get_clip_target_plane():
    """The single clip plane the manipulator should currently target,
    or None if nothing should currently be draggable at all.

    Session 119 (Doug's own toolbar redesign): a full, two-level
    model now. Returns None outright unless the toolbar's own
    Normal/Section View switch is on "section" -- previously "off"
    was just another entry in the same exclusive mode group as x/y/z/
    xy; now it's a separate, higher-level switch, and the lower
    section (mode + edit controls) is Qt-disabled (grayed out)
    whenever it reads "normal", so this can never even be reached
    from a click in that state, but the check stays here too as the
    authoritative, function-level source of truth.

    win._section_clip_active_axis (None by default) is the single,
    shared "which row's own Enable-edit control is checked" state,
    covering x/y/z's own single checkbox each AND xy's own, separate
    Enable-X/Enable-Y pair uniformly -- deliberately never touched by
    switching win._section_clip_mode itself (x/y/z/xy), only ever set
    or cleared by the Enable-edit controls themselves. That's what
    gives per-row persistence across mode switches for free, with no
    separate, per-mode dictionary needed at all: switch from X to Y,
    active_axis stays "x" the whole time (simply not matching mode
    "y", so nothing shows); switch back to X, it matches again
    automatically, and X's own manipulator reappears exactly as it
    was left.

    For a single-axis mode (x/y/z), the active axis must equal the
    mode itself (only one possible "on" value each). For xy, either
    "x" or "y" directly selects that specific plane, via
    win._section_clip_planes_by_axis -- unchanged from Session 116/
    117's own design there."""
    if getattr(win, "_section_top_level", "normal") != "section":
        return None
    axis = getattr(win, "_section_clip_active_axis", None)
    if axis is None:
        return None
    mode = getattr(win, "_section_clip_mode", "x")
    if mode == "xy":
        by_axis = getattr(win, "_section_clip_planes_by_axis", {})
        return by_axis.get(axis)
    if axis != mode:
        return None
    planes = getattr(win, "_section_clip_planes", [])
    return planes[0] if planes else None


def _update_clip_visibility():
    """Keep the clip plane's own drag gizmo in sync with whether
    visibility is toggled on AND whether a plane is currently active.
    Called both when the visibility button itself is toggled, and
    whenever the mode changes (set_section_view_mode) -- so switching
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
    _store_plane_geom(), keyed by the current (mode, axis) -- the
    actual position-memory wiring behind Doug's own request that
    toggling Normal/Section View, or switching between modes, not
    reset a plane's own, already-adjusted position."""
    _clip_plane_drag_update(delta_trsf)
    target_plane = _get_clip_target_plane()
    if target_plane is not None:
        win._section_clip_drag_orig_pln = target_plane.ToPlane()
        mode = getattr(win, "_section_clip_mode", "x")
        axis = getattr(win, "_section_clip_active_axis", None)
        if axis is not None:
            _store_plane_geom(mode, axis, target_plane.ToPlane())


def _apply_section_capping():
    """Apply capping to every currently active clip plane. Called by
    set_section_view_mode whenever a new plane is built.
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


def set_section_top_level(level):
    """Handler for the toolbar's own top-level Normal View/Section
    View switch (Session 119, Doug's own redesign). "normal" tears
    the actual clip planes down entirely, via set_section_view_mode
    ("off") -- guarded there (see its own docstring) so that call
    doesn't overwrite the lower group's own remembered mode.
    "section" restores whatever the lower group was last set to.
    Either way, the lower section's own container widget is enabled/
    disabled here too, relying on Qt's own standard behavior: a
    disabled parent grays out and disables every child inside it
    automatically, regardless of each child's own, individual
    setEnabled() state -- no manual per-widget graying needed on top
    of this one call."""
    win._section_top_level = level
    lower = getattr(win, "_section_lower_widget", None)
    if lower is not None:
        lower.setEnabled(level == "section")
    if level == "normal":
        set_section_view_mode("off")
    else:
        set_section_view_mode(getattr(win, "_section_clip_mode", "x"))
    _refresh_section_lower_controls()


def _on_section_mode_clicked(mode):
    """Handler for the lower X/Y/Z/X&Y group -- applies the mode,
    then refreshes which row's own Enable-edit control(s) are
    enabled and which are checked, to match the new mode."""
    set_section_view_mode(mode)
    _refresh_section_lower_controls()


def _on_reverse_checkbox_toggled(checked, mode, axis):
    """Handler for every Reverse control -- one per row, same
    X/Y/Z/X&Y-X/X&Y-Y shape as the Enable-edit controls. Only ever
    enabled (clickable) when its own row's mode is the current one
    (see _refresh_section_lower_controls()), so the live plane for
    this exact (mode, axis) is guaranteed to exist and be the one
    win._section_clip_planes (or, for xy, win._section_clip_planes_
    by_axis) currently holds.

    Flips the plane's own live normal directly (SetEquation with the
    same location, reversed direction) rather than rebuilding the
    plane from scratch -- preserves whatever position it's currently
    at, including one that's already been dragged away from center.
    Stores the result via _store_plane_geom() (Session 120's own
    position-memory mechanism, shared with drag completion) so the
    reversed state survives a later mode switch or Normal/Section
    View toggle too, not just this immediate change. Refreshes the
    manipulator afterward in case it's currently attached to this
    same plane, so its own orientation follows the new normal rather
    than staying stale."""
    win._section_reversed = getattr(win, "_section_reversed", {})
    win._section_reversed.setdefault(mode, {})[axis] = checked

    if mode == "xy":
        by_axis = getattr(win, "_section_clip_planes_by_axis", {})
        plane = by_axis.get(axis)
    else:
        planes = getattr(win, "_section_clip_planes", [])
        plane = planes[0] if planes else None

    if plane is not None:
        from OCP.gp import gp_Pln
        pln = plane.ToPlane()
        loc = pln.Position().Location()
        normal = pln.Position().Direction().Reversed()
        new_pln = gp_Pln(loc, normal)
        plane.SetEquation(new_pln)
        _store_plane_geom(mode, axis, new_pln)
        win.canvas.view.Redraw()
        _update_clip_visibility()


def _on_edit_checkbox_toggled(checked, axis, partner_btn=None):
    """Handler for every Enable-edit control alike -- X/Y/Z's own
    single checkbox each, and X&Y's own Enable-X/Enable-Y pair.
    win._section_clip_active_axis is the one, shared state behind all
    of them (see _get_clip_target_plane()'s own docstring for why a
    single, shared value gives correct per-row persistence across
    mode switches for free, with no separate per-mode dictionary
    needed).

    For X&Y's own pair specifically (Doug's own, explicit
    confirmation): mutually exclusive AND both-can-be-unchecked at
    once, the default -- not a standard Qt exclusive group at all,
    since QButtonGroup's own setExclusive(True) forces exactly one
    button always checked, with no way back to zero by clicking the
    checked one again. Wired by hand instead: checking one unchecks
    its partner directly (only ever passed for this X&Y pair; X/Y/Z's
    own single checkboxes pass none), via blockSignals so the
    partner's own handler doesn't also fire and race to set
    active_axis to something else right afterward."""
    if checked and partner_btn is not None:
        partner_btn.blockSignals(True)
        partner_btn.setChecked(False)
        partner_btn.blockSignals(False)
    win._section_clip_active_axis = axis if checked else None
    _update_clip_visibility()


def _refresh_section_lower_controls():
    """Sync every Enable-edit AND Reverse control's own enabled/
    disabled state, plus checked/unchecked display state, to match
    the current mode (and, for Edit specifically,
    win._section_clip_active_axis). Needed because switching modes
    never touches active_axis itself (deliberately -- see
    _get_clip_target_plane()), so each row's own control(s) must be
    re-derived explicitly whenever the mode changes. Also called once
    at toolbar-build time, so a freshly-built toolbar starts in a
    correct, consistent state rather than whatever Qt's own widget
    defaults happen to be.

    Session 120: renamed from _refresh_section_edit_controls and
    extended to cover Reverse too, alongside the original Edit
    controls -- both follow the identical "only the current mode's
    own row(s) are enabled" rule, so it made sense to sync them
    together in one pass rather than duplicate the same mode-matching
    logic in two separate functions. Their CHECKED state comes from
    two different places, though: Edit's own is derived fresh each
    time from active_axis (a single, shared "which row" value);
    Reverse's own is read directly from win._section_reversed, an
    independent, per-(mode, axis) flag that isn't tied to whether
    Edit happens to be on for that same row at all."""
    current_mode = getattr(win, "_section_clip_mode", "x")
    active_axis = getattr(win, "_section_clip_active_axis", None)
    reversed_state = getattr(win, "_section_reversed", {})

    edit_by_mode = getattr(win, "_section_edit_buttons_by_mode", {})
    for mode, axis_to_btn in edit_by_mode.items():
        is_current = (mode == current_mode)
        for axis, btn in axis_to_btn.items():
            btn.setEnabled(is_current)
            btn.blockSignals(True)
            btn.setChecked(is_current and active_axis == axis)
            btn.blockSignals(False)

    reverse_by_mode = getattr(win, "_section_reverse_buttons_by_mode", {})
    for mode, axis_to_btn in reverse_by_mode.items():
        is_current = (mode == current_mode)
        for axis, btn in axis_to_btn.items():
            btn.setEnabled(is_current)
            btn.blockSignals(True)
            btn.setChecked(reversed_state.get(mode, {}).get(axis, False))
            btn.blockSignals(False)


def build_section_view_toolbar():
    """Populate the Section View toolbar (mainwindow.py's own
    sectionViewToolBar, docked Qt.RightToolBarArea, stacked below
    wcToolBar/wgToolBar). Called once at startup.

    Session 119: rebuilt around Doug's own, two-level design. A top-
    level Normal View/Section View pair (QButtonGroup, exclusive,
    Normal default) replaces "Off" as a plain member of the old,
    single five-way mode group. Below it, in a separate container
    widget whose own setEnabled() state Qt propagates automatically
    to every child -- graying the whole section out at once whenever
    Normal View is selected, with no manual per-widget work needed.

    Session 120: the lower section rebuilt again, as a compact,
    3-column table (Doug's own layout, to keep the toolbar from
    getting too wide once Reverse needed its own control per row,
    same as Edit): a Dir column (the X/Y/Z/X&Y mode-selector buttons,
    unchanged QToolButtons with icons), an Edit column, and a Rev
    column -- the latter two now plain QCheckBox widgets, no icon or
    label needed once the column header itself says what they are.
    X&Y's own Dir cell is a mode-selector button like the others, but
    has no Edit/Rev of its own (blank cells) -- it isn't a single
    plane. Its own X and Y sub-planes get their own rows right below
    it instead, each with real Edit/Rev checkboxes but a plain,
    non-clickable QLabel in the Dir column instead of a button, since
    they aren't independently selectable modes, just the two
    components of the X&Y mode itself.

    Only the row(s) matching the current mode have their own Edit/Rev
    control(s) enabled at all; the rest are grayed out, tracked via
    win._section_edit_buttons_by_mode / win._section_reverse_buttons_
    by_mode and kept in sync by _refresh_section_lower_controls().
    Edit's own mutually-exclusive-but-both-can-be-off X&Y pair is
    wired by hand (_on_edit_checkbox_toggled's own docstring); Rev's
    own X&Y pair is fully independent of each other instead -- wanting
    only one plane reversed and not the other is a real, named use
    case Doug specifically raised, so no such wiring exists for Rev
    at all.

    Capping is no longer a toggle here at all (Session 120, Doug's
    own call: always capped, not a preference). Reversed normal is
    now built."""
    from PySide6.QtWidgets import (QWidget, QGridLayout, QToolButton,
                                   QButtonGroup, QFrame, QCheckBox,
                                   QLabel)
    from PySide6.QtCore import QSize

    _panel = QWidget()
    _grid = QGridLayout(_panel)
    _grid.setContentsMargins(2, 2, 2, 2)
    _grid.setSpacing(2)

    # --- Top level: Normal View / Section View ---
    win._section_top_level_group = QButtonGroup(win)
    win._section_top_level_group.setExclusive(True)
    _TOP_LEVELS = [("normal", "Normal View"), ("section", "Section View")]
    for _trow, (_level, _label) in enumerate(_TOP_LEVELS):
        _tbtn = QToolButton()
        _tbtn.setCheckable(True)
        _tbtn.setText(_label)
        _tbtn.clicked.connect(
            lambda checked, lv=_level: set_section_top_level(lv))
        win._section_top_level_group.addButton(_tbtn)
        _grid.addWidget(_tbtn, _trow, 0, 1, 3)
        if _level == "normal":
            _tbtn.setChecked(True)  # matches the real initial state

    _sep1 = QFrame()
    _sep1.setFrameShape(QFrame.HLine)
    _grid.addWidget(_sep1, len(_TOP_LEVELS), 0, 1, 3)

    # --- Lower section: Dir | Edit | Rev table, entirely disabled
    # while Normal View is selected.
    _lower = QWidget()
    _lower_grid = QGridLayout(_lower)
    _lower_grid.setContentsMargins(0, 0, 0, 0)
    _lower_grid.setSpacing(2)
    win._section_lower_widget = _lower
    _lower.setEnabled(False)  # Normal View is the default

    _lower_grid.addWidget(QLabel("Dir"), 0, 0)
    _lower_grid.addWidget(QLabel("Edit"), 0, 1)
    _lower_grid.addWidget(QLabel("Rev"), 0, 2)

    win._section_view_group = QButtonGroup(win)
    win._section_view_group.setExclusive(True)
    win._section_edit_buttons_by_mode = {}
    win._section_reverse_buttons_by_mode = {}

    def _make_edit_checkbox(mode, axis, partner_btn=None):
        cb = QCheckBox()
        cb.setToolTip(f"Enable dragging the {axis.upper()} plane")
        cb.toggled.connect(
            lambda checked, a=axis, p=partner_btn:
                _on_edit_checkbox_toggled(checked, a, p))
        win._section_edit_buttons_by_mode.setdefault(mode, {})[axis] = cb
        return cb

    def _make_reverse_checkbox(mode, axis):
        cb = QCheckBox()
        cb.setToolTip(f"Reverse the {axis.upper()} plane's own normal")
        cb.toggled.connect(
            lambda checked, m=mode, a=axis:
                _on_reverse_checkbox_toggled(checked, m, a))
        win._section_reverse_buttons_by_mode.setdefault(mode, {})[axis] = cb
        return cb

    _MODES = [
        ("x", "clip_x.gif", "DX normal"),
        ("y", "clip_y.gif", "DY normal"),
        ("z", "clip_z.gif", "DZ normal"),
        ("xy", "clip_xy.gif", "2 planes (X and Y)"),
    ]
    _lrow = 1
    for _mode, _iconfile, _tip in _MODES:
        _btn = QToolButton()
        _btn.setCheckable(True)
        _pix = QPixmap(f"icons/{_iconfile}")
        if not _pix.isNull():
            _btn.setIcon(QIcon(_pix))
            _btn.setIconSize(QSize(24, 24))
        else:
            _btn.setText(_mode.upper())
        _btn.setToolTip(_tip)
        _btn.clicked.connect(
            lambda checked, m=_mode: _on_section_mode_clicked(m))
        win._section_view_group.addButton(_btn)
        _lower_grid.addWidget(_btn, _lrow, 0)
        if _mode == "x":
            _btn.setChecked(True)  # default lower-group selection

        if _mode == "xy":
            # X&Y itself: Dir only, no Edit/Rev of its own -- it isn't
            # a single plane. Its own X/Y sub-planes get real rows
            # right below, each with a plain label instead of a
            # mode-selector button in the Dir column.
            #
            # Edit's own two checkboxes are built plain here (no
            # signal connected yet) rather than via the shared
            # _make_edit_checkbox helper, since each one's own partner
            # is the OTHER one -- and that partner doesn't exist yet
            # at the point the first one would need to be built.
            # Registered and displayed the same way regardless; both
            # signals connected together right after, once both boxes
            # genuinely exist.
            _lrow += 1
            _ex_cb = QCheckBox()
            _ex_cb.setToolTip("Enable dragging the X plane")
            win._section_edit_buttons_by_mode.setdefault(
                "xy", {})["x"] = _ex_cb
            _ey_cb = QCheckBox()
            _ey_cb.setToolTip("Enable dragging the Y plane")
            win._section_edit_buttons_by_mode.setdefault(
                "xy", {})["y"] = _ey_cb
            _ex_cb.toggled.connect(
                lambda checked, a="x", p=_ey_cb:
                    _on_edit_checkbox_toggled(checked, a, p))
            _ey_cb.toggled.connect(
                lambda checked, a="y", p=_ex_cb:
                    _on_edit_checkbox_toggled(checked, a, p))

            _lower_grid.addWidget(QLabel("X"), _lrow, 0)
            _lower_grid.addWidget(_ex_cb, _lrow, 1)
            _lower_grid.addWidget(_make_reverse_checkbox("xy", "x"),
                                  _lrow, 2)
            _lrow += 1
            _lower_grid.addWidget(QLabel("Y"), _lrow, 0)
            _lower_grid.addWidget(_ey_cb, _lrow, 1)
            _lower_grid.addWidget(_make_reverse_checkbox("xy", "y"),
                                  _lrow, 2)
        else:
            _lower_grid.addWidget(
                _make_edit_checkbox(_mode, _mode), _lrow, 1)
            _lower_grid.addWidget(
                _make_reverse_checkbox(_mode, _mode), _lrow, 2)
        _lrow += 1

    _grid.addWidget(_lower, len(_TOP_LEVELS) + 1, 0, 1, 3)

    win.sectionViewToolBar.addWidget(_panel)
    win._section_clip_mode = "x"  # matches the lower group's own default
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
    win.add_function_to_menu("Create/Modify", "Remove Hole", removeHole)
    win.add_function_to_menu(
        "Create/Modify", "Remove Isolated Feature",
        removeIsolatedFeature)
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
                                   QFrame)
    from PySide6.QtCore import QSize

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
    _row = 0
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
