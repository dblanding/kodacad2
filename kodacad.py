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
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.gp import gp_Ax1, gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Face, TopoDS_Vertex
from OCP.TopTools import TopTools_ListOfShape

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QTreeWidgetItemIterator

from m2d import M2D
import stepanalyzer
import docmodel
from mainwindow import MainWindow, dm
from OCCUtils import Topology
import workplane

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


def position_selected():
    """Open the Position dialog on the currently selected part/assembly.

    Pre-select an item in the tree first (same convention as the rest
    of the tree-item action methods), then choose Position -> Position
    Selected. See position_dialog.py for the dialog itself; this is
    just the tree-selection -> dialog-launch glue, matching the
    pattern the design PDF described (pre-select, then a single
    dropdown menu item opens the dialog).
    """
    item = win.itemClicked or win.treeView.currentItem()
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


#############################################
#
# 3D Geometry creation functions
#
#############################################


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


def extrude():
    """Extrude profile on active WP to create a new part.
    Add new part to active assembly, if any, else to Top"""

    tag = get_tag_of_active_asy()
    loc = get_inv_loc_of_active_asy()
    wp = win.activeWp
    if len(win.lineEditStack) == 2:
        name = win.lineEditStack.pop()
        length = float(win.lineEditStack.pop()) * win.unitscale
        # MULTI-PROFILE (Session 63, Doug: 'use multiple wires to
        # create a new part'): same wp.make_faces() the Mill/Pull
        # dialog uses -- outer loops with contained loops as holes;
        # disjoint outers prism separately and fuse into one part.
        faces, err = wp.make_faces()
        if err is not None:
            win.statusBar().showMessage(f"Profile problem: {err}",
                                        6000)
            print(f"[extrude] profile problem: {err}")
            return
        aPrismVec = wp.wVec * length
        new_part = None
        for f in faces:
            prism = BRepPrimAPI_MakePrism(f, aPrismVec).Shape()
            new_part = prism if new_part is None else \
                BRepAlgoAPI_Fuse(new_part, prism).Shape()
        loc_new_part = BRepBuilderAPI_Transform(
            new_part, loc.Transformation()).Shape()
        with docmodel.undo_transaction(dm):
            uid = dm.add_component(loc_new_part, name, DEFAULT_COLOR)
        win.build_tree()
        win.redraw()
        win.syncUncheckedToHideList()
        win.statusBar().showMessage("New part created.")
        win.clearCallback()
    else:
        win.registerCallback(extrudeC)
        win.lineEdit.setFocus()
        statusText = "Enter extrusion length, then enter part name."
        win.statusBar().showMessage(statusText)


def extrudeC(shapeList, *args):
    """Callback (collector) for extrude"""

    win.lineEdit.setFocus()
    if len(win.lineEditStack) == 1:
        win.statusBar().showMessage("Length received. Enter part name.")
    elif len(win.lineEditStack) == 2:
        extrude()


def revolve():
    """Revolve profile on active WP to create a new part.
    Add new part to active assembly, if any, else to Top"""

    wp = win.activeWp
    if win.lineEditStack and len(win.ptStack) == 2:
        p2 = win.ptStack.pop()
        p1 = win.ptStack.pop()
        name = win.lineEditStack.pop()
        win.clearAllStacks()
        wireOK = wp.makeWire()
        if not wireOK:
            print("Unable to make wire.")
            return
        face = BRepBuilderAPI_MakeFace(wp.wire).Shape()
        revolve_axis = gp_Ax1(p1, gp_Dir(gp_Vec(p1, p2)))
        new_part = BRepPrimAPI_MakeRevol(face, revolve_axis).Shape()
        loc_new_part = BRepBuilderAPI_Transform(
            new_part, loc.Transformation()).Shape()
        with docmodel.undo_transaction(dm):
            uid = dm.add_component(loc_new_part, name, DEFAULT_COLOR)
        win.build_tree()
        win.redraw()
        win.syncUncheckedToHideList()
        win.statusBar().showMessage("New part created.")
        win.clearCallback()
    else:
        win.registerCallback(revolveC)
        display.SetSelectionModeVertex()
        win.lineEdit.setFocus()
        statusText = "Pick two points on revolve axis."
        win.statusBar().showMessage(statusText)


def revolveC(shapeList, *args):
    """Callback (collector) for revolve.

    Session 63 sweep: same retired-paradigm consumer as the
    calculator's distPtPt was -- it expected wp intersection-point
    VERTEX picks for the axis, which no longer exist. ENGINE INPUT
    FIRST (a catch on the active wp becomes a world point -- the
    natural way to define an axis in the sketch), 3D vertex pick as
    fallback, polite decline otherwise. Fixed BEFORE it bit, per the
    every-consumer-sweep lesson."""
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
                snap = find_snap(wp, uv, tol, current_snap_mode())
                if snap is not None:
                    pt = uv_to_world(wp.gpPlane, snap[1][0], snap[1][1])
    except Exception as se:
        print(f"[revolve] engine path failed: {se}")
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
            "a part vertex for the axis.", 3000)
        return
    win.ptStack.append(pt)
    if len(win.ptStack) == 1:
        statusText = "Select 2nd point on revolve axis."
        win.statusBar().showMessage(statusText)
    elif len(win.ptStack) == 2 and not win.lineEditStack:
        statusText = "Enter part name."
        win.statusBar().showMessage(statusText)
    win.lineEdit.setFocus()
    if win.lineEditStack and len(win.ptStack) == 2:
        revolve()


#############################################
#
# 3D Geometry positioning functons
#
#############################################


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


def mill():
    """Mill profile on active WP into active part."""

    wp = win.activeWp
    if win.lineEditStack:
        depth = float(win.lineEditStack.pop()) * win.unitscale
        wireOK = wp.makeWire()
        if not wireOK:
            print("Unable to make wire.")
            return
        wire = wp.wire
        workPart = win.activePart
        uid = win.activePartUID
        punchProfile = BRepBuilderAPI_MakeFace(wire)
        aPrismVec = wp.wVec * -depth
        tool = BRepPrimAPI_MakePrism(punchProfile.Shape(), aPrismVec).Shape()
        newPart = BRepAlgoAPI_Cut(workPart, tool).Shape()
        win.erase_shape(uid)
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        win.draw_shape(uid)
        win.setActivePart(uid)
        win.statusBar().showMessage("Mill operation complete")
        win.clearCallback()
    elif not require_active_part("Mill"):
        return
    else:
        win.registerCallback(millC)
        win.lineEdit.setFocus()
        statusText = "Enter milling depth (pos in -w direction)"
        win.statusBar().showMessage(statusText)


def millC(shapeList, *args):
    """Callback (collector) for mill"""

    win.lineEdit.setFocus()
    if win.lineEditStack:
        mill()


def pull():
    """Pull profile on active WP onto active part."""

    wp = win.activeWp
    if win.lineEditStack:
        length = float(win.lineEditStack.pop()) * win.unitscale
        wireOK = wp.makeWire()
        if not wireOK:
            print("Unable to make wire.")
            return
        wire = wp.wire
        workPart = win.activePart
        uid = win.activePartUID
        pullProfile = BRepBuilderAPI_MakeFace(wire)
        aPrismVec = wp.wVec * length
        tool = BRepPrimAPI_MakePrism(pullProfile.Shape(), aPrismVec).Shape()
        newPart = BRepAlgoAPI_Fuse(workPart, tool).Shape()
        win.erase_shape(uid)
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        win.draw_shape(uid)
        win.setActivePart(uid)
        win.statusBar().showMessage("Pull operation complete")
        win.clearCallback()
    elif not require_active_part("Pull"):
        return
    else:
        win.registerCallback(pullC)
        win.lineEdit.setFocus()
        statusText = "Enter pull distance (pos in +w direction)"
        win.statusBar().showMessage(statusText)


def pullC(shapeList, *args):
    """Callback (collector) for pull"""

    win.lineEdit.setFocus()
    if win.lineEditStack:
        pull()


def fillet(event=None):
    """Fillet (blend) edges of active part"""

    if win.lineEditStack and win.edgeStack:
        topo = Topology.Topo(win.activePart)
        text = win.lineEditStack.pop()
        try:
            fillet_r = float(text) * win.unitscale
        except ValueError:
            print(f"Expected a number. You entered '{text}'")
            win.clearCallback()
            return
        edges = []
        # Test if edge(s) selected are in active part
        # Use IsSame() instead of Python 'in' -- TopoDS shapes may be
        # different Python objects but the same underlying geometry
        for edge in win.edgeStack:
            part_edges = list(topo.edges())
            found = any(edge.IsSame(e) for e in part_edges)
            if found:
                edges.append(edge)
            else:
                print("Selected edge(s) must be in Active Part.")
                win.clearCallback()
                return
        win.edgeStack = []
        workPart = win.activePart
        uid = win.activePartUID
        mkFillet = BRepFilletAPI_MakeFillet(workPart)
        for edge in edges:
            mkFillet.Add(fillet_r, edge)
        try:
            newPart = mkFillet.Shape()
        except RuntimeError as e:
            print(f"Unable to make Fillet shape. {e}")
            win.clearCallback()
            return
        try:
            win.erase_shape(uid)
            with docmodel.undo_transaction(dm):
                dm.replace_shape(uid, newPart)
            win.draw_shape(uid)
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
    for shape in shapeList:
        try:
            edge = TopoDS.Edge_s(shape)
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


def fuse():
    """Fuse an adjacent or overlapping solid shape to active part."""

    if win.shapeStack:
        shape = win.shapeStack.pop()
        workpart = win.activePart
        uid = win.activePartUID
        newPart = BRepAlgoAPI_Fuse(workpart, shape).Shape()
        win.erase_shape(uid)
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        win.draw_shape(uid)
        win.setActivePart(uid)
        win.statusBar().showMessage("Fuse operation complete")
        win.clearCallback()
    else:
        win.registerCallback(fuseC)
        statusText = "Select shape to fuse to active part."
        win.statusBar().showMessage(statusText)


def fuseC(shapeList, *args):
    """Callback (collector) for fuse"""

    for shape in shapeList:
        win.shapeStack.append(shape)
    if win.shapeStack:
        fuse()


def shell(event=None):
    """Shell active part"""

    if win.lineEditStack and win.faceStack:
        text = win.lineEditStack.pop()
        faces = TopTools_ListOfShape()
        for face in win.faceStack:
            faces.Append(face)
        win.faceStack = []
        workPart = win.activePart
        uid = win.activePartUID
        shellT = float(text) * win.unitscale
        mkShell = BRepOffsetAPI_MakeThickSolid()
        mkShell.MakeThickSolidByJoin(workPart, faces, -shellT, 1.0e-3)
        newPart = mkShell.Shape()
        win.erase_shape(uid)
        with docmodel.undo_transaction(dm):
            dm.replace_shape(uid, newPart)
        win.draw_shape(uid)
        win.setActivePart(uid)
        win.statusBar().showMessage("Shell operation complete")
        win.clearCallback()
    elif not require_active_part("Shell"):
        return
    else:
        win.registerCallback(shellC)
        display.SetSelectionModeFace()
        statusText = "Select face(s) to remove then specify shell thickness."
        win.statusBar().showMessage(statusText)


def shellC(shapeList, *args):
    """Callback (collector) for shell"""

    win.lineEdit.setFocus()
    for shape in shapeList:
        try:
            face = TopoDS.Face_s(shape)
            win.faceStack.append(face)
            count = len(win.faceStack)
            win.statusBar().showMessage(
                f"Face {count} selected. Add more faces or enter thickness + Enter.")
        except Exception as e:
            print(f"[shellC] not a face: {e}")
    if win.faceStack and win.lineEditStack:
        shell()


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
    docmodel.load_stp_at_top(dm)
    win.build_tree()
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
    win.add_menu("Create 3D")
    win.add_function_to_menu("Create 3D", "Extrude", extrude)
    win.add_function_to_menu("Create 3D", "Revolve", revolve)
    win.add_menu("Modify Active Part")
    # Session 63: Mill & Pull COMBINED into one lean dialog (the
    # banked Creo Pull spec: Operation / Direction / Distance) with
    # multi-profile support. Legacy mill()/pull() remain in code.
    from mill_pull_dialog import show_mill_pull_dialog
    win.add_function_to_menu(
        "Modify Active Part", "Mill / Pull...",
        lambda: show_mill_pull_dialog(win))
    win.add_function_to_menu("Modify Active Part", "Fillet", fillet)
    win.add_function_to_menu("Modify Active Part", "Shell", shell)
    win.add_function_to_menu("Modify Active Part", "Fuse", fuse)
    win.add_menu("Position")
    win.add_function_to_menu("Position", "Position Selected", position_selected)
    win.add_menu("Utility")
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

    win.treeView.popMenu.addAction("Item Info", win.showClickedInfo)
    win.treeView.popMenu.addAction("Set Active", win.setClickedActive)
    win.treeView.popMenu.addAction("Delete Item", win.deleteItem)
    win.treeView.popMenu.addAction("Make Transparent", win.setTransparent)
    win.treeView.popMenu.addAction("Make Opaque", win.setOpaque)
    win.treeView.popMenu.addAction("Edit Name", win.editName)

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
        ("refangcl.gif", "Reference-Angle Constr Line", None),
        ("abcl.gif", "Angular Bisector", None),
        ("lbcl.gif", "Linear Bisector", a2d.clineLinBisec),
        ("parcl.gif", "Parallel Construction Line", None),
        ("perpcl.gif", "Perpendicular Constr Line", None),
        ("cltan1.gif", "Tangent to Circle", None),
        ("cltan2.gif", "Tangent to 2 Circles", None),
        ("ccirc.gif", "Construction Circle", a2d.ccirc),
        ("cc3p.gif", "Constr Circle by 3 Points", a2d.cc3p),
        ("cccirc.gif", "Concentric Constr Circle", None),
        ("proj_edge.gif", "Project Edge", a2d.projectEdge),
        ("proj_face.gif", "Project Face Edges", a2d.projectFaceEdges),
        "SEP",
        ("line.gif", "Line", a2d.line),
        ("poly.gif", "Polyline", a2d.poly),
        ("rect.gif", "Rectangle", a2d.rect),
        ("circ.gif", "Circle", a2d.circle),
        ("arcc2p.gif", "Arc: Center + 2 Points", a2d.arcc2p),
        ("arc3p.gif", "Arc by 3 Points", a2d.arc3p),
        ("slot.gif", "Slot", None),
        ("fillet.gif", "2D Fillet", None),
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

    win.raise_()  # bring the app to the top
    app.exec()
