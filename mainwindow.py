#!/usr/bin/env python
#
# Copyright 2022 Doug Blanding (dblanding@gmail.com)
#
# This file is part of kodacad2.
# Licensed under the GNU General Public License v3 -- see LICENSE.
#

from collections import defaultdict
import logging
from PySide6.QtCore import Qt, QPersistentModelIndex, QModelIndex, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QMainWindow,
    QTreeWidget,
    QMenu,
    QDockWidget,
    QToolButton,
    QTreeWidgetItem,
    QFrame,
    QToolBar,
    QAbstractItemView,
    QInputDialog,
    QTreeWidgetItemIterator,
    QMessageBox,
)
from OCP.AIS import AIS_Shape, AIS_Line, AIS_Circle
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.CPnts import CPnts_AbscissaPoint
from OCP.gp import gp_Vec, gp_Pnt
from OCP.Prs3d import Prs3d_LineAspect
from OCP.Aspect import Aspect_TypeOfLine
from OCP.Quantity import (Quantity_NOC_BLACK,
                          
    Quantity_Color,
    Quantity_NOC_GRAY,
    Quantity_NOC_DARKGREEN,
    Quantity_NOC_MAGENTA1,
)
from OCP.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Vertex

# from koda_viewport import KodaViewport
# import local version instead (allows changing rotate/pan/zoom controls)
# import myDisplay.qtDisplay as qtDisplay  # For pythonocc-7.4
from koda_viewport import KodaViewport  # For pythonocc-7.5
import rpnCalculator
from docmodel import DocModel, undo_transaction
from version import APP_VERSION


logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # set to DEBUG | INFO | ERROR

dm = DocModel()


class TreeView(QTreeWidget):
    """Part & Assembly structure display

    The Part/Assy treeView display is kept in sync with the XCAF data model
    by calling the function build_tree() whenever changes in the data model
    cause the treeView display to become out of date. By first clicking on a
    treeView item, then right clicking, a drop down list of options appears,
    allowing some modifications to be made to the model. Although the treeView
    display currently permits the user to make 'drag & drop' modifications,
    those changes are currently not propagated to the data model.
    """

    def __init__(self, parent=None):
        QTreeWidget.__init__(self, parent)
        self.header().setHidden(True)
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)
        self.setDragDropMode(self.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.contextMenu)
        self.popMenu = QMenu(self)

    def contextMenu(self, point):
        # Right-clicking should target whatever item is under the
        # cursor, regardless of whether it was left-clicked first.
        item = self.itemAt(point)
        if item is not None:
            self.setCurrentItem(item)
        # Also overwrite the main window's itemClicked (Session 59):
        # a stale-but-VALID itemClicked from an earlier left-click on
        # a DIFFERENT item passes the shiboken validity check and
        # shadows the currentItem fallback -- so the RMB action
        # silently targeted the old item ("Set Active doesn't work on
        # the 1st try"; the re-click 'fixed' it only because the
        # left-click refreshed itemClicked). The item under the RMB
        # cursor is always the user's intent.
        win = self.window()
        if hasattr(win, "itemClicked"):
            win.itemClicked = item
        self.popMenu.exec_(self.mapToGlobal(point))

    def dropEvent(self, event):
        if event.source() == self:
            QAbstractItemView.dropEvent(self, event)

    def dropMimeData(self, parent, row, data, action):
        if action == Qt.DropAction.MoveAction:
            return self.moveSelection(parent, row)
        return False

    def moveSelection(self, parent, position):
        # Get uid info BEFORE the visual move changes the tree
        selection = [QPersistentModelIndex(i) for i in self.selectedIndexes()]
        parent_index = self.indexFromItem(parent)
        if parent_index in selection:
            return False
        # Capture uid and new parent uid for XDE reparenting after visual move
        # Use both selectedIndexes() and currentItem() to catch the dragged item
        drag_items = []
        new_parent_uid = parent.text(1) if parent else None
        # First try selectedIndexes
        for index in selection:
            item = self.itemFromIndex(QModelIndex(index))
            if item is not None:
                drag_items.append((item.text(1), new_parent_uid))
        # Also try currentItem as fallback
        if not drag_items:
            current = self.currentItem()
            if current is not None:
                drag_items.append((current.text(1), new_parent_uid))
        # save the drop location in case it gets moved
        target = self.model().index(position, 0, parent_index).row()
        if target < 0:
            target = position
        # remove the selected items
        taken = []
        for index in reversed(selection):
            item = self.itemFromIndex(QModelIndex(index))
            if item is None or item.parent() is None:
                taken.append(self.takeTopLevelItem(index.row()))
            else:
                taken.append(item.parent().takeChild(index.row()))
        # insert the selected items at their new positions
        while taken:
            if position == -1:
                # append the items if position not specified
                if parent_index.isValid():
                    parent.insertChild(parent.childCount(), taken.pop(0))
                else:
                    self.insertTopLevelItem(
                        self.topLevelItemCount(), taken.pop(0))
            else:
                # insert the items at the specified position
                if parent_index.isValid():
                    parent.insertChild(
                        min(target, parent.childCount()), taken.pop(0))
                else:
                    self.insertTopLevelItem(
                        min(target, self.topLevelItemCount()), taken.pop(0)
                    )
        # After visual tree update, perform XDE reparent with inverse transform
        for drag_uid, new_parent_uid in drag_items:
            if drag_uid and new_parent_uid and drag_uid in dm.label_dict:
                if new_parent_uid in dm.label_dict:
                    try:
                        with undo_transaction(dm):
                            dm.reparent_component(drag_uid, new_parent_uid)
                        # Full reset: clear all AIS shapes and redraw from scratch
                        # Walk up parent chain to find MainWindow
                        main_win = self.parent()
                        while main_win is not None and not hasattr(main_win, "ais_shape_dict"):
                            main_win = main_win.parent()
                        if main_win is not None and hasattr(main_win, "ais_shape_dict"):
                            main_win.canvas._display.Context.RemoveAll(False)
                            main_win.ais_shape_dict.clear()
                            main_win.build_tree()
                            main_win.redraw()

                    except Exception as e:
                        import traceback
                        print(f"[reparent] failed: {e}")
                        traceback.print_exc()
        return True


def _occt_version_string():
    """Best-effort OCP/OCCT version for the title bar. Primary source
    (Session 58 cont'd): the installed cadquery-ocp PACKAGE version
    via importlib.metadata -- pure Python packaging, no binding
    uncertainty, and it encodes the OCCT version and build (e.g.
    '7.9.3.1.1'). The Standard_Version binding candidates remain as
    fallback; on Doug's build none of them resolved ('graceful
    absence'), which is exactly why the metadata route is primary."""
    try:
        from importlib.metadata import version, distributions
        # Collect ALL ocp-ish candidates, then prefer one whose
        # version looks like an actual OCCT release (major >= 7).
        # Round 4 (Session 59): the name 'ocp' in Doug's pyproject is
        # a thin wrapper package versioned 0.1.4 -- matching it first
        # put a WRONG number in the title bar, which is worse than an
        # absent one. The real binding (cadquery-ocp, 7.9.x) is a
        # dependency underneath it and gets preferred by version
        # shape; if only wrapper-like versions exist, show nothing.
        candidates = []
        for dist_name in ("cadquery-ocp", "cadquery-ocp-novtk", "ocp"):
            try:
                v = version(dist_name)
                if v:
                    candidates.append(v)
            except Exception:
                continue
        try:
            for dist in distributions():
                dname = (dist.metadata["Name"] or "").lower()
                if "ocp" in dname and dist.version:
                    candidates.append(dist.version)
        except Exception:
            pass
        for v in candidates:
            try:
                if int(v.split(".")[0]) >= 7:
                    return v
            except Exception:
                continue
    except Exception:
        pass
    try:
        from OCP.Standard import Standard_Version
    except Exception:
        return ""
    for attr in ("OCC_VERSION_COMPLETE", "Complete_s", "Version_s",
                 "Complete", "Version"):
        try:
            val = getattr(Standard_Version, attr)
            if callable(val):
                val = val()
            s = str(val)
            if s and any(ch.isdigit() for ch in s):
                return s
        except Exception:
            continue
    return ""


# Stick font for the in-plane workplane label (Session 63: the
# AIS_TextLabel was screen-aligned and screen-sized; Doug wants the
# label lying ON the plane, aligned with U, zooming with the model
# -- so it is drawn as stroke GEOMETRY, which cannot do otherwise).
# Each glyph: list of polylines in a 1.0-height em box; advance 0.75.
_WP_LABEL_GLYPHS = {
    "/": [[(0.1, 0.0), (0.5, 1.0)]],
    "w": [[(0.0, 0.6), (0.15, 0.0), (0.3, 0.45), (0.45, 0.0),
           (0.6, 0.6)]],
    "p": [[(0.0, -0.35), (0.0, 0.6)],
          [(0.0, 0.6), (0.4, 0.6), (0.5, 0.5), (0.5, 0.25),
           (0.4, 0.15), (0.0, 0.15)]],
    "0": [[(0.1, 0.0), (0.4, 0.0), (0.5, 0.12), (0.5, 0.88),
           (0.4, 1.0), (0.1, 1.0), (0.0, 0.88), (0.0, 0.12),
           (0.1, 0.0)]],
    "1": [[(0.1, 0.8), (0.3, 1.0), (0.3, 0.0)],
          [(0.1, 0.0), (0.5, 0.0)]],
    "2": [[(0.0, 0.85), (0.1, 1.0), (0.4, 1.0), (0.5, 0.85),
           (0.5, 0.6), (0.0, 0.0)], [(0.0, 0.0), (0.5, 0.0)]],
    "3": [[(0.0, 1.0), (0.5, 1.0), (0.25, 0.55), (0.45, 0.45),
           (0.5, 0.2), (0.4, 0.0), (0.1, 0.0), (0.0, 0.1)]],
    "4": [[(0.35, 0.0), (0.35, 1.0), (0.0, 0.35), (0.5, 0.35)]],
    "5": [[(0.5, 1.0), (0.0, 1.0), (0.0, 0.55), (0.35, 0.55),
           (0.5, 0.4), (0.5, 0.15), (0.35, 0.0), (0.05, 0.0)]],
    "6": [[(0.45, 1.0), (0.1, 0.6), (0.0, 0.35), (0.0, 0.15),
           (0.1, 0.0), (0.4, 0.0), (0.5, 0.15), (0.5, 0.35),
           (0.4, 0.5), (0.05, 0.5)]],
    "7": [[(0.0, 1.0), (0.5, 1.0), (0.15, 0.0)]],
    "8": [[(0.25, 0.55), (0.08, 0.65), (0.05, 0.85), (0.15, 1.0),
           (0.35, 1.0), (0.45, 0.85), (0.42, 0.65), (0.25, 0.55),
           (0.08, 0.42), (0.0, 0.2), (0.1, 0.0), (0.4, 0.0),
           (0.5, 0.2), (0.42, 0.42), (0.25, 0.55)]],
    "9": [[(0.05, 0.0), (0.4, 0.4), (0.5, 0.65), (0.5, 0.85),
           (0.4, 1.0), (0.1, 1.0), (0.0, 0.85), (0.0, 0.65),
           (0.1, 0.5), (0.45, 0.5)]],
}


def _wp_label_shape(text, origin_uv, height, trsf):
    """Build '/wN' as a TopoDS compound of stroke edges lying in the
    workplane (UV coords transformed by trsf). Returns None if
    nothing drawable."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    n_edges = 0
    pen_u = origin_uv[0]
    base_v = origin_uv[1]
    for ch in text:
        glyph = _WP_LABEL_GLYPHS.get(ch)
        if glyph is not None:
            for stroke in glyph:
                for i in range(len(stroke) - 1):
                    x1, y1 = stroke[i]
                    x2, y2 = stroke[i + 1]
                    g1 = gp_Pnt(pen_u + x1 * height,
                                base_v + y1 * height,
                                0).Transformed(trsf)
                    g2 = gp_Pnt(pen_u + x2 * height,
                                base_v + y2 * height,
                                0).Transformed(trsf)
                    if g1.Distance(g2) < 1.0e-9:
                        continue
                    try:
                        builder.Add(comp,
                                    BRepBuilderAPI_MakeEdge(g1, g2)
                                    .Edge())
                        n_edges += 1
                    except Exception:
                        pass
        pen_u += 0.75 * height
    return comp if n_edges else None


def _clip_line_to_rect(cline, bounds):
    """Clip infinite line ax+by+c=0 to rectangle (u1,v1,u2,v2).
    Returns ((ua,va),(ub,vb)) or None if the line misses it."""
    a, b, c = cline
    u1, v1, u2, v2 = bounds
    pts = []
    eps = 1.0e-9
    if abs(b) > eps:  # crossings with vertical border edges
        for u in (u1, u2):
            v = -(a * u + c) / b
            if v1 - eps <= v <= v2 + eps:
                pts.append((u, v))
    if abs(a) > eps:  # crossings with horizontal border edges
        for v in (v1, v2):
            u = -(b * v + c) / a
            if u1 - eps <= u <= u2 + eps:
                pts.append((u, v))
    # dedupe corner double-hits
    uniq = []
    for p in pts:
        if not any(abs(p[0] - q[0]) < 1.0e-7 and
                   abs(p[1] - q[1]) < 1.0e-7 for q in uniq):
            uniq.append(p)
    if len(uniq) < 2:
        return None
    # take the two most distant
    best = (uniq[0], uniq[1])
    best_d = -1.0
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            d = ((uniq[i][0] - uniq[j][0]) ** 2
                 + (uniq[i][1] - uniq[j][1]) ** 2)
            if d > best_d:
                best_d = d
                best = (uniq[i], uniq[j])
    return best


def _needs_analytic_workaround(shape):
    """True when the Session 60 pick pathology MATTERS for this part:
    pathological curved faces (cylinder/cone with negative V-range --
    the STEP reader's reversed-axis signature that OCCT's analytic
    Select3D_SensitiveCylinder mishandles) make up a significant
    FRACTION of the part's total surface area.

    Session 61 refinement (Doug: initial lathe load still slow --
    every vendor part has holes, and holes carry the same reader
    signature, so 'any pathological face' converted the whole lathe):
    a hole's pickability is irrelevant -- nobody picks a part by its
    holes; the planes carry the picking. The pathology only matters
    when pathological faces DOMINATE the pickable surface: a can's
    wall (~75% of area -> convert), a rod's shaft (~90% -> convert,
    correctly -- its edge-on picking has the same latent defect),
    a plate's holes (~5-15% -> exempt, fast, clean wireframes).

    Threshold 0.30. Tradeoff, documented: a mostly-planar part could
    in principle still have a degraded pathological cylinder that a
    user tries to pick from a hostile angle -- if that ever bites,
    lower the threshold (or return True on any pathological face, the
    pre-refinement behavior). Area via BRepGProp is far cheaper than
    the NurbsConvert+remesh it gates."""
    try:
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_ShapeEnum
        from OCP.TopoDS import TopoDS
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_SurfaceType
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        total_area = 0.0
        patho_area = 0.0
        exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
        while exp.More():
            face = TopoDS.Face_s(exp.Current())
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            area = props.Mass()
            total_area += area
            surf = BRepAdaptor_Surface(face)
            if surf.GetType() in (GeomAbs_SurfaceType.GeomAbs_Cylinder,
                                  GeomAbs_SurfaceType.GeomAbs_Cone):
                if surf.FirstVParameter() < -1.0e-7:
                    patho_area += area
            exp.Next()
        if total_area <= 0.0:
            return True  # degenerate -- convert (safe side)
        return (patho_area / total_area) > 0.30
    except Exception:
        return True  # cannot inspect -> convert (safe side)


class MainWindow(QMainWindow):
    """Main GUI window containing an assy tree view and a 3D display view

    The User controls whether parts displayed in the 3D display view are drawn
    or hidden through the use of check boxes on the tree view display. The list
    of the uid's of all the items currently hidden is held in self.hide_list.
    When tree view items are checked or unchecked, a list of unchecked items is
    compared to self.hide_list. That comparison results in two new lists:
    a list of items to be erased and a list of items to be drawn. The items to
    be erased are erased and the items to be drawn are drawn, and the hide_list
    is then updated.

    When a part is newly created or loaded (step), the doc model (dm) is changed and
    this results in the regeneration of the tree view. As the new tree view
    items are generated, they are shown checked except for the ones that are
    contained in the hide_list. """

    def __init__(self, *args):
        super().__init__()
        self.canvas = KodaViewport(self)
        # Renaming self.canvas._display (like below) doesn't work.
        # self.display = self.canvas._display
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.contextMenu)
        self.popMenu = QMenu(self)
        title = f"KodaCAD {APP_VERSION} "
        occt_ver = _occt_version_string()
        if occt_ver:
            title += f"(Using: OCP {occt_ver} with PySide6)"
        else:
            title += "(Using: OCP with PySide6)"
        self.setWindowTitle(title)
        self.resize(960, 720)
        self.setCentralWidget(self.canvas)
        self.createDockWidget()
        self.wcToolBar = QToolBar("2D")  # Construction toolbar
        self.addToolBar(Qt.RightToolBarArea, self.wcToolBar)
        self.wcToolBar.setMovable(True)
        self.wgToolBar = QToolBar("2D")  # Geom Profile toolbar
        self.addToolBar(Qt.RightToolBarArea, self.wgToolBar)
        self.wgToolBar.setMovable(True)
        self.menu_bar = self.menuBar()
        self._menus = {}
        self._menu_methods = {}
        self.centerOnScreen()

        self.calculator = None

        self.assy_root, self.wp_root = self.create_root_items()
        self.itemClicked = None  # TreeView item that has been mouse clicked
        # Undo/Redo shortcuts (Session 61); menu items added in kodacad.py
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence.StandardKey.Undo, self, self.editUndo)
        # StandardKey.Redo is Ctrl+Shift+Z on Linux -- bind it AND the
        # Ctrl+Y the Edit menu advertises (Session 61, Doug's report)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.editRedo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.editRedo)

        # Internally, everything is always in mm
        # scale user input and output values
        # (user input values) * unitscale = value in mm
        # (output values) / unitscale = value in user's units
        self._unitDict = {"mm": 1.0, "in": 25.4, "ft": 304.8}
        self.units = "mm"
        self.unitscale = self._unitDict[self.units]
        self.unitsLabel = QLabel()
        self.unitsLabel.setText("Units: %s " % self.units)
        self.unitsLabel.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)

        self.endOpButton = QToolButton()
        self.endOpButton.setText("End Operation")
        self.endOpButton.clicked.connect(self.clearCallback)
        self.currOpLabel = QLabel()
        self.registeredCallback = None
        self.currOpLabel.setText("Current Operation: %s " %
                                 self.registeredCallback)

        self.lineEdit = QLineEdit()
        self.lineEdit.returnPressed.connect(self.appendToStack)

        status = self.statusBar()
        status.setSizeGripEnabled(False)
        status.addPermanentWidget(self.lineEdit)
        status.addPermanentWidget(self.currOpLabel)
        status.addPermanentWidget(self.endOpButton)
        status.addPermanentWidget(self.unitsLabel)
        status.showMessage("Ready", 5000)

        self.hide_list = []  # list of part uid's to be hidden (not displayed)
        self.floatStack = []  # storage stack for floating point values
        self.xyPtStack = []  # storage stack for 2d points (x, y)
        self.ptStack = []  # storage stack for gp_Pnts
        self.edgeStack = []  # storage stack for edge picks
        self.faceStack = []  # storage stack for face picks
        self.shapeStack = []  # storage stack for shape picks
        self.lineEditStack = []  # list of user inputs

        self.activePart = None  # <TopoDS_Shape> object
        self.activePartUID = 0
        self.transparency_dict = {}  # {uid: part display transparency}
        # {uid: [list of ancestor shapes]}
        self.ancestor_dict = defaultdict(list)
        self.ais_shape_dict = {}  # {uid: <AIS_Shape> object}
        self._display_prep_cache = {}  # {uid: (src_shape,
        # prepared_shape)} -- Session 61 draw-prep cache
        self._syncing_highlight = False  # re-entrancy guard for
        # bidirectional tree<->viewport highlight sync (Session 60):
        # each side's highlight setter fires the other side's
        # selection signal; without this guard they ping-pong forever.
        self._highlighted_uid = None

        self.activeWp = None  # WorkPlane object
        self.activeWpUID = 0
        self.wp_dict = {}  # k = uid, v = wpObject
        self._wpNmbr = 1

        self.activeAsyUID = 0
        self.assy_list = []  # list of assy uid's
        self.showItemActive(0)
        self.setActiveAsy(self.activeAsyUID)

        # Used to show 'Top' assembly in initial tree view but removed
        # it here in order to allow creating it in 'load_step_under_top'
        # dm.parse_doc()
        # self.build_tree()

    def createDockWidget(self):
        self.treeDockWidget = QDockWidget("Assy/Part Structure", self)
        self.treeDockWidget.setObjectName("treeDockWidget")
        self.treeDockWidget.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.treeView = TreeView()  # Assy/Part structure (display)
        self.treeView.itemClicked.connect(self.treeViewItemClicked)
        # Highlight sync: currentItemChanged fires on mouse AND
        # keyboard navigation (itemClicked is mouse-only), so the
        # viewport tracks arrow-key tree navigation too (Session 60).
        self.treeView.currentItemChanged.connect(self.onTreeCurrentChanged)
        self.populate_tree_context_menu()
        self.treeDockWidget.setWidget(self.treeView)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.treeDockWidget)

    def centerOnScreen(self):
        """Centers the window on the screen."""
        resolution = QApplication.primaryScreen().availableGeometry()
        self.move(
            int(resolution.width() / 2) - int(self.frameSize().width() / 2),
            int(resolution.height() / 2) - int(self.frameSize().height() / 2),
        )

    def contextMenu(self, point):
        self.menu = QMenu()
        self.popMenu.exec_(self.mapToGlobal(point))

    def add_menu(self, menu_name):
        _menu = self.menu_bar.addMenu("&" + menu_name)
        self._menus[menu_name] = _menu
        return _menu

    def add_function_to_menu(self, menu_name, text, _callable):
        assert callable(_callable), "the function supplied is not callable"
        try:
            _action = QAction(text, self)
            # if not, the "exit" action is now shown...
            # Qt is trying so hard to be native cocoa'ish that its a nuisance
            _action.setMenuRole(QAction.NoRole)
            _action.triggered.connect(_callable)
            self._menus[menu_name].addAction(_action)
        except KeyError:
            raise ValueError("the menu item %s does not exist" % (menu_name))

    def closeEvent(self, event):  # things that need to happen on exit
        try:
            self.calculator.close()
        except AttributeError:
            pass
        event.accept()

    #############################################
    #
    # treeView (QTreeWidget) building methods:
    #
    #############################################

    def build_tree(self):
        """Build new tree view from dm.label_dict.

        This method is called whenever dm.doc is modified in a way that would
        result in a change in the tree view. The tree view represents the
        hierarchical structure of the top assembly and its components."""
        import time as _time
        _t0 = _time.monotonic()
        # Capture expand/collapse state BEFORE clearTree() wipes the
        # widget (Session 71, Doug: every refresh returned the whole
        # tree to fully expanded, discarding the user's own collapse
        # choices -- tedious on a large assembly). Keyed by uid (the
        # QTreeWidgetItems themselves don't survive the rebuild, but
        # uid does), restored below; brand-new uids default to
        # expanded, matching the prior always-expanded behavior for
        # content the user has never had a chance to collapse yet.
        expand_state = {}

        def _capture_expand(item):
            uid = item.text(1)
            if uid:
                expand_state[uid] = item.isExpanded()
            for i in range(item.childCount()):
                _capture_expand(item.child(i))
        for _root in (self.assy_root, self.wp_root):
            if _root is not None:
                _capture_expand(_root)
        # Standard Qt practice for rebuilding a QTreeWidget from
        # scratch: disable repaint/layout churn while many items are
        # added one at a time, re-enable once. Without this, each
        # QTreeWidgetItem construction and expandItem() call can
        # trigger its own layout pass -- visible on large models.
        self.treeView.setUpdatesEnabled(False)
        self.clearTree()
        self.assy_list = []
        parent_item_dict = {}  # {uid: tree view item}
        for uid, dic in dm.label_dict.items():
            # dic: {keys: 'entry', 'name', 'parent_uid', 'ref_entry'}
            entry = dic["entry"]
            name = dic["name"]
            parent_uid = dic["parent_uid"]
            if parent_uid not in parent_item_dict:
                parent_item = self.assy_root
            else:
                parent_item = parent_item_dict[parent_uid]

            # create node in tree view
            item_name = [str(name) if name else "", str(uid)]
            item = QTreeWidgetItem(parent_item, item_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if uid in self.hide_list:
                item.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                item.setCheckState(0, Qt.CheckState.Checked)
            item.setExpanded(expand_state.get(uid, True))
            parent_item_dict[uid] = item
            # build assy_list
            if dic["is_assy"]:
                self.assy_list.append(uid)
        # Assembly checkbox state, DERIVED bottom-up (Session 71,
        # Doug: an assembly sometimes showed CHECKED while every one
        # of its children was unchecked, requiring an extra click to
        # actually show anything). assy_list was appended in the same
        # parent-before-child order dm.label_dict guarantees, so
        # walking it IN REVERSE processes every assembly only after
        # all of its descendants already have their final state --
        # a valid post-order traversal without a second tree walk.
        # An assembly with no children at all keeps its own
        # hide_list-derived state; nothing to derive FROM otherwise.
        for _auid in reversed(self.assy_list):
            _aitem = parent_item_dict[_auid]
            if _aitem.childCount() == 0:
                continue
            _any_checked = any(
                _aitem.child(_i).checkState(0) == Qt.CheckState.Checked
                for _i in range(_aitem.childCount()))
            if not _any_checked:
                # Display-only correction -- hide_list elsewhere in
                # this codebase is reserved for actual drawable items
                # (parts/workplanes; see uncheckedToList()), and this
                # state is re-derived fresh from children every call
                # anyway, so nothing is lost by not persisting an
                # assembly uid into it (and doing so would make it a
                # target for _incremental_reconcile's OWN hide_list
                # pruning, which only considers part/wp uids valid).
                _aitem.setCheckState(0, Qt.CheckState.Unchecked)
        self.treeView.setUpdatesEnabled(True)
        self.sync_treeview_to_active()
        _dt = _time.monotonic() - _t0
        if _dt > 0.5:
            print(f"[build_tree] {len(dm.label_dict)} items in "
                 f"{_dt:.2f}s")
        # self.syncCheckedToDrawList()

    def clearTree(self):
        """Remove all tree view widget items and replace root item"""
        self.treeView.clear()
        self.assy_root, self.wp_root = self.create_root_items()
        self.repopulate_2D_tree_view()

    def create_root_items(self):
        """Create root items in treeView.

        Tree structure mirrors CoCreate:
            WP          <- workplanes (outside 3D hierarchy)
              wp1
            3D          <- 3D container
              /         <- root of 3D assembly hierarchy
                as1     <- top assembly
                  ...
        """
        wp_root = QTreeWidgetItem(self.treeView, ["WP", "wp0"])
        self.treeView.expandItem(wp_root)
        node_3d = QTreeWidgetItem(self.treeView, ["3D", "3d0"])
        self.treeView.expandItem(node_3d)
        slash_root = QTreeWidgetItem(node_3d, ["/", "0"])
        self.treeView.expandItem(slash_root)
        # Assemblies go under slash_root
        return (slash_root, wp_root)

    def repopulate_2D_tree_view(self):
        """Add all workplanes to 2D section of tree view."""

        # add items to treeView
        for uid in self.wp_dict:
            itemName = [uid, uid]
            item = QTreeWidgetItem(self.wp_root, itemName)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)

    #############################################
    #
    # treeView item action methods:
    #
    #############################################

    def populate_tree_context_menu(self):
        """Add actions to the treeView's RMB popup menu.

        The menu was created (TreeView.__init__) but never populated,
        so right-clicking a tree item previously showed an empty menu
        and did nothing -- including Delete.
        """
        menu = self.treeView.popMenu
        menu.addAction("Set Active", self.setClickedActive)
        menu.addAction("Rename", self.editName)
        menu.addAction("Create New Assembly", self.createNewAssembly)
        menu.addAction("Create Shared Instance", self.createSharedInstance)
        menu.addAction("Set Transparent", self.setTransparent)
        menu.addAction("Set Opaque", self.setOpaque)
        menu.addSeparator()
        menu.addAction("Delete", self.deleteItem)

    def treeViewItemClicked(self, item):
        """Called when treeView item is clicked.

        When a parent item is checked/unchecked, propagate the state
        to all children (Qt6 removed automatic tristate propagation).
        """
        self.itemClicked = item  # store item
        # Propagate checkbox state to all children
        state = item.checkState(0)
        if state in (Qt.CheckState.Checked, Qt.CheckState.Unchecked):
            self._set_children_check_state(item, state)
        # Correct ancestor checkboxes to match their children (Session
        # 71, Doug: an assembly could stay CHECKED after its last
        # child was unchecked, forcing a two-click workaround to show
        # anything). Walks up from whichever item was just touched --
        # cheap (ancestor chain only, not the whole tree) and applies
        # in BOTH directions for consistency: an assembly with zero
        # checked children becomes unchecked; one with at least one
        # checked child (e.g. after re-checking one) becomes checked
        # again. Only build_tree()'s own bottom-up pass needs to walk
        # the FULL tree; live clicks only ever change one lineage.
        self._correct_ancestor_checkboxes(item)
        if not self.inSync():  # click may have been on checkmark.
            self.adjust_draw_hide()

    def _set_children_check_state(self, item, state):
        """Recursively set all children to the same check state."""
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._set_children_check_state(child, state)

    def _correct_ancestor_checkboxes(self, item):
        """Walk up from item's parent, deriving each ancestor's
        checkbox from whether ANY of its own children are checked."""
        parent = item.parent()
        while parent is not None:
            if not (parent.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                break
            any_checked = any(
                parent.child(i).checkState(0) == Qt.CheckState.Checked
                for i in range(parent.childCount()))
            parent.setCheckState(
                0, Qt.CheckState.Checked if any_checked
                else Qt.CheckState.Unchecked)
            parent = parent.parent()

    def inSync(self):
        """Return True if unchecked items are in sync with hide_list."""
        return set(self.uncheckedToList()) == set(self.hide_list)

    def uncheckedToList(self):
        """Return list of uid's of unchecked (part & wp) items in treeView."""
        dl = []
        for item in self.treeView.findItems("", Qt.MatchFlag.MatchContains | Qt.MatchRecursive):
            if item.checkState(0) == Qt.CheckState.Unchecked:
                uid = item.text(1)
                if (uid in dm.part_dict) or (uid in self.wp_dict):
                    dl.append(uid)
        return dl

    def adjust_draw_hide(self):
        """Erase from 3D display any item that gets unchecked, draw when checked.

        An item is a treeView widget item. It may be a part, assy or workplane.
        For our purpose here, we only care if it is a part or wp because those
        are the only types that are displayed in the 3D view window. For parts,
        the display is adjusted incrementally. A newly checked part is drawn and
        a newly unchecked part is erased. However, because workplanes have a
        great many ais_shapes, ais lines, ais_circles and topoDS_shapes (edges &
        border) as well, it isn't practical to keep track of them all just so
        they can be removed incrementally. Also, when a new workplane is created,
        it is set active, so the old active workplane needs to be redrawn with a
        duller border color. Therefore, if there is a change in the hide_list
        involving a workplane, it is best to just clear the display and redraw
        all the workplanes that are not in the hide_list.
        """

        unchecked = self.uncheckedToList()
        unchecked_set = set(unchecked)
        hide_list = list(self.hide_list)
        hide_set = set(hide_list)
        newly_unchecked = unchecked_set - hide_set
        newly_checked = hide_set - unchecked_set
        for uid in newly_unchecked:
            # If a workplane is newly unchecked, redraw is needed
            if uid in self.wp_dict:
                self.hide_list.append(uid)
                self.redraw()
            # Otherwise, we can do an incremental change in the display
            elif uid in dm.part_dict:
                self.erase_shape(uid)  # Erase the shape
        for uid in newly_checked:
            if uid in dm.part_dict:
                self.draw_shape(uid)  # Draw the shape
            elif uid in self.wp_dict:
                self.draw_wp(uid)  # Draw the workplane
        self.hide_list = unchecked

    def syncUncheckedToHideList(self):
        """Use this method after building a new treeView to make sure items
        that were previously hidden are still unchecked in new treeView."""
        for item in self.treeView.findItems("", Qt.MatchFlag.MatchContains | Qt.MatchRecursive):
            uid = item.text(1)
            if (uid in dm.part_dict) or (uid in self.wp_dict):
                if uid in self.hide_list:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                else:
                    item.setCheckState(0, Qt.CheckState.Checked)

    def sortViewItems(self):
        """Return dicts of tree view items sorted by type: (prt, ay, wp)"""
        # Traverse all treeView widget items
        iterator = QTreeWidgetItemIterator(self.treeView)
        pdict = {}  # part-types    {uid: item}
        adict = {}  # asy-types     {uid: item}
        wdict = {}  # wp-types      {uid: item}
        while iterator.value():
            item = iterator.value()
            name = item.text(0)
            uid = item.text(1)
            if uid in dm.part_dict:
                pdict[uid] = item
            elif uid in self.assy_list:
                adict[uid] = item
            elif uid in self.wp_dict:
                wdict[uid] = item
            iterator += 1
        return (pdict, adict, wdict)

    def showClickedInfo(self):
        """Show info for item clicked in treeView."""
        item = self.itemClicked
        if item:
            self.showItemInfo(item)
        else:
            print("No item selected. Try first left clicking item then right clicking.")

    def showItemInfo(self, item):
        """Show info for item clicked in treeView."""
        if item:
            name = item.text(0)
            uid = item.text(1)
            if name in ["/", "WP", "3D"]:
                print(f"Root ({name}) tree view item")
            elif uid.startswith("wp"):
                print(f"Workplane: uid: {uid}; name: {name}")
            else:
                entry = dm.label_dict[uid]["entry"]
                ref_ent = dm.label_dict[uid]["ref_entry"]
                is_assy = dm.label_dict[uid]["is_assy"]
                if is_assy:
                    print(
                        f"Assembly: uid: {uid}; name: {name}; entry: {entry}; ref_entry: {ref_ent}"
                    )
                else:
                    print(
                        f"Part: uid: {uid}; name: {name}; entry: {entry}; ref_entry: {ref_ent}"
                    )

    def _get_clicked_or_current_item(self):
        """Returns self.itemClicked if it's still valid, else falls
        back to self.treeView.currentItem() -- the correct version of
        the "self.itemClicked or self.treeView.currentItem()" pattern
        every RMB handler used to use directly.

        self.itemClicked can go stale: if the tree gets rebuilt (e.g.
        extrude() -> build_tree()) after an item was clicked but
        before an RMB action is taken on it, the underlying C++
        QTreeWidgetItem is destroyed even though the Python reference
        in self.itemClicked is untouched. A dead shiboken wrapper is
        still Python-truthy (`or` doesn't fall through to
        currentItem() the way the old code assumed), so calling
        anything on it -- even .text(0) -- raised "Internal C++
        object already deleted." Confirmed directly (Doug hit this
        immediately after creating a part, which rebuilds the tree,
        then tried to RMB-delete it).
        """
        from shiboken6 import Shiboken
        item = self.itemClicked
        if item is not None and not Shiboken.isValid(item):
            item = None
        return item or self.treeView.currentItem()

    def setClickedActive(self):
        """Set item clicked in treeView Active.
        Falls back to currentItem() so RMB works without prior left-click.
        """
        item = self._get_clicked_or_current_item()
        if item:
            self.setItemActive(item)
            self.treeView.clearSelection()
            self.itemClicked = None
        else:
            print("No item selected.")

    def setItemActive(self, item):
        """Set (part, wp or assy) represented by treeView item to be active."""
        if item:
            name = item.text(0)
            uid = item.text(1)
            print(f"Part selected: {name}, UID: {uid}")
            pd, ad, wd = self.sortViewItems()
            if uid in pd:
                self.setActivePart(uid)
                sbText = f"{name} [uid={uid}] is now the active part"
            elif uid in wd:
                self.setActiveWp(uid)
                sbText = f"{name} [uid={uid}] is now the active workplane"
                self.redraw()  # update color of new active wp
            elif uid in ad:
                self.setActiveAsy(uid)
                sbText = f"{name} [uid={uid}] is now the active assembly"
            else:
                sbText = f"{name} [uid={uid}] Unable to set active."
            self.statusBar().showMessage(sbText, 5000)

    def showItemActive(self, uid):
        """Update tree view to show active status of (uid)."""
        pd, ad, wd = self.sortViewItems()
        if uid in pd:
            # Clear BG color of all part items
            for itm in pd.values():
                itm.setBackground(0, QBrush(QColor(255, 255, 255, 0)))
            # Set BG color of new active part
            pd[uid].setBackground(0, QBrush(QColor("gold")))
        elif uid in wd:
            # Clear BG color of all wp items
            for itm in wd.values():
                itm.setBackground(0, QBrush(QColor(255, 255, 255, 0)))
            # Set BG color of new active wp
            wd[uid].setBackground(0, QBrush(QColor("lightgreen")))
        elif uid in ad:
            # Clear BG color of all asy items
            for itm in ad.values():
                itm.setBackground(0, QBrush(QColor(255, 255, 255, 0)))
            # Set BG color of new active asy
            ad[uid].setBackground(0, QBrush(QColor("lightblue")))

    def sync_treeview_to_active(self):
        for uid in (self.activePartUID, self.activeAsyUID, self.activeWpUID):
            if uid:
                self.showItemActive(uid)

    def deleteItem(self):
        """Delete the (workplane, part, or assembly) item clicked."""
        item = self._get_clicked_or_current_item()
        if not item:
            print("No item selected. Try first left clicking item then right clicking.")
            return
        name = item.text(0)
        uid = item.text(1)
        if uid in self.wp_dict:
            del self.wp_dict[uid]
            if uid in self.hide_list:
                self.hide_list.remove(uid)
            # Incremental: the AIS objects for THIS workplane are
            # already tracked per-uid in _wp_ais_reg -- remove
            # exactly those, nothing else in the viewer is touched.
            context = self.canvas._display.Context
            for ais in self._wp_ais_reg.pop(uid, []):
                try:
                    context.Remove(ais, False)
                except Exception:
                    pass
            context.UpdateCurrentViewer()
            self.canvas.update()
            self.build_tree()
            print(f"Workplane {name} deleted.")
            if uid == self.activeWpUID:
                self.activeWp = None
                self.activeWpUID = 0
        elif uid in dm.label_dict:
            reply = QMessageBox.question(
                self,
                "Delete",
                f"Delete '{name}' from the assembly?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                # delete_component can cascade (orphaned nested-
                # assembly children removed too) and calls
                # parse_doc() internally -- snapshot the uid set now,
                # reconcile the diff after.
                old_uids = set(dm.part_dict.keys())
                with undo_transaction(dm):
                    deleted = dm.delete_component(uid)
                if deleted:
                    if uid == self.activePartUID:
                        self.activePartUID = 0
                        self.activePart = None
                    if uid == self.activeAsyUID:
                        self.activeAsyUID = 0
                    self.build_tree()
                    self._incremental_reconcile(old_uids)
                    print(f"{name} deleted.")
                else:
                    print(f"Failed to delete {name}.")
        else:
            print(f"'{name}' cannot be deleted.")
        self.itemClicked = None

    def setTransparent(self):
        """Set treeView item clicked transparent"""
        item = self._get_clicked_or_current_item()
        if item:
            uid = item.text(1)
            if uid in dm.part_dict:
                self.transparency_dict[uid] = 0.6
                self.erase_shape(uid)
                self.draw_shape(uid)
            self.itemClicked = None
        else:
            print("No item selected. Try first left clicking item then right clicking.")

    def setOpaque(self):
        """Set treeView item clicked opaque"""
        item = self._get_clicked_or_current_item()
        if item:
            uid = item.text(1)
            if uid in dm.part_dict:
                self.transparency_dict.pop(uid)
                self.erase_shape(uid)
                self.draw_shape(uid)
            self.itemClicked = None
        else:
            print("No item selected. Try first left clicking item then right clicking.")

    def createNewAssembly(self):
        """RMB: create a new, empty assembly under the clicked item
        (which must be an assembly). Session 54."""
        item = self._get_clicked_or_current_item()
        if not item:
            print("No item selected. Try first left clicking item then right clicking.")
            return
        uid = item.text(1)
        if uid not in dm.label_dict:
            print(f"'{item.text(0)}' cannot hold a new assembly.")
            self.itemClicked = None
            return
        name, OK = QInputDialog.getText(
            self, "Create New Assembly",
            "Enter a name for the new assembly:", text="assembly")
        if OK and name:
            with undo_transaction(dm):
                created = dm.create_new_assembly(uid, name)
            if created:
                # Full refresh -- not just build_tree(). Matching
                # createSharedInstance (Session 60 fix): a structure
                # change leaves stale AIS objects in the context that
                # are displayed but NOT re-activated for selection, so
                # affected parts (Doug's 'button') stopped hover-
                # highlighting and couldn't be picked, while tree->
                # viewport SetSelected still worked on them. redraw()
                # re-displays with SetAutoActivateSelection(True).
                self.ais_shape_dict.clear()
                self.build_tree()
                self.redraw()
        self.treeView.clearSelection()
        self.itemClicked = None

    def createSharedInstance(self):
        """RMB: create a shared instance of the clicked part or
        assembly, superimposed on the original -- move it via the
        Position dialog. Session 54."""
        item = self._get_clicked_or_current_item()
        if not item:
            print("No item selected. Try first left clicking item then right clicking.")
            return
        uid = item.text(1)
        if uid not in dm.label_dict:
            print(f"'{item.text(0)}' cannot be instanced.")
            self.itemClicked = None
            return
        with undo_transaction(dm):
            instanced = dm.create_shared_instance(uid)
        if instanced:
            self.ais_shape_dict.clear()
            self.build_tree()
            self.redraw()
        self.treeView.clearSelection()
        self.itemClicked = None

    def editName(self):
        """Edit name of treeView item clicked"""
        item = self._get_clicked_or_current_item()
        if item:
            name = item.text(0)
            uid = item.text(1)
            prompt = "Enter new name for part %s" % name
            newName, OK = QInputDialog.getText(
                self, "Input Dialog", prompt, text=name)
            if OK:
                item.setText(0, newName)
                print(f"UID= {uid}, name = {newName}")
                self.treeView.clearSelection()
                self.itemClicked = None
                with undo_transaction(dm):
                    dm.change_label_name(uid, newName)
                self.build_tree()
        else:
            print("No item selected. Try first left clicking item then right clicking.")

    #############################################
    #
    # Administrative and data management methods:
    #
    #############################################

    def get_wp_uid(self, wp_objct):
        """ Assign (and return) a new uid to a new workplane.
            Add item to treeview (2D)
            Make wp active
            Add to self.wp_dict.
        """
        uid = "wp%i" % self._wpNmbr
        self._wpNmbr += 1
        self.wp_dict[uid] = wp_objct
        # Add treeView item
        itemName = [uid, uid]
        item = QTreeWidgetItem(self.wp_root, itemName)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        # Make new workplane active
        self.setActiveWp(uid)
        return uid

    def appendToStack(self):
        """Called when <ret> is pressed on line edit"""
        self.lineEditStack.append(self.lineEdit.text())
        self.lineEdit.clear()
        cb = self.registeredCallback
        if cb:
            cb([])  # call self.registeredCallback with arg=empty_list
        else:
            self.lineEditStack.pop()

    def setActivePart(self, uid):
        """Change active part status in a coordinated manner."""
        self.activePartUID = uid
        if uid and uid in dm.part_dict:
            self.activePart = dm.part_dict[uid]["shape"]
            self.showItemActive(uid)
        else:
            if uid and uid not in dm.part_dict:
                print(f"[setActivePart] uid {uid} not in part_dict")
            self.activePart = None

    def setActiveWp(self, uid):
        """Change active workplane status in coordinated manner."""
        # modify status in self
        self.activeWpUID = uid
        self.activeWp = self.wp_dict[uid]
        # show as active in treeView
        self.showItemActive(uid)

    def setActiveAsy(self, uid):
        """Change active assembly status in coordinated manner."""
        # modify status in self
        self.activeAsyUID = uid
        if uid:
            # show as active in treeView
            self.showItemActive(uid)

    def valueFromCalc(self, value):
        """Receive value from calculator."""
        cb = self.registeredCallback
        if cb:
            self.lineEditStack.append(str(value))
            cb([])  # call self.registeredCallback with arg=empty_list
        else:
            print(value)

    def clearLEStack(self):
        """Clear lineEditStack"""
        self.lineEditStack = []

    def clearAllStacks(self):
        self.lineEditStack = []
        self.floatStack = []
        self.xyPtStack = []
        self.edgeStack = []
        self.faceStack = []
        self.ptStack = []

    def install_highlight_sync(self):
        """Register the always-on viewport->tree highlight callback.
        Called once after the display exists (Session 60). Kept
        SEPARATE from registerCallback's operation-callback slot:
        operations (mate, extrude, ...) temporarily own selection and
        must not be disturbed, so onViewportSelect no-ops whenever an
        operation callback is active."""
        try:
            self.canvas._display.register_select_callback(
                self.onViewportSelect)
        except Exception as e:
            print(f"[highlight_sync] could not register: {e}")

    def onTreeCurrentChanged(self, current, previous):
        """Tree -> viewport highlight. Guarded against the
        ping-pong: setting viewport selection fires onViewportSelect,
        which would set the tree, which fires this again."""
        if self._syncing_highlight:
            return
        uid = current.text(1) if current is not None else None
        self._syncing_highlight = True
        try:
            self._highlight_viewport(uid)
        finally:
            self._syncing_highlight = False

    def onViewportSelect(self, shape_list, *args):
        """Viewport -> tree highlight. Real callback signature is
        (shape_list, ais_obj) -- the first fix was mis-declared as
        (shape) and received the LIST, matching nothing (Session 60).
        No-op while an operation callback owns selection."""
        if self.registeredCallback is not None:
            return
        if self._syncing_highlight:
            return
        ais_obj = args[0] if args else None
        uid = self._uid_for_ais(ais_obj)
        if uid is None and shape_list:
            # Fallback: match by shape geometry if no AIS object
            uid = self._uid_for_selected_shape(shape_list[0])
        self._syncing_highlight = True
        try:
            if uid is not None:
                item = self._tree_item_for_uid(uid)
                if item is not None:
                    self.treeView.setCurrentItem(item)
                    self.treeView.scrollToItem(item)
            else:
                self.treeView.setCurrentItem(None)
            self._highlighted_uid = uid
        finally:
            self._syncing_highlight = False

    def _uid_for_ais(self, ais_obj):
        """Reverse-map a selected AIS InteractiveObject to its uid.
        PRIMARY: reads the owner tag SetOwner() attached at display
        time (draw_shape) -- O(1), and correct even when two
        occurrences share an underlying TopoDS_Shape (shared-instance
        assemblies: the AIS OBJECT is unique per occurrence even when
        the geometry isn't). FALLBACK: the original shape-identity
        scan, kept for two reasons -- (1) if the OCP binding's
        SetOwner doesn't accept a plain str the way hoped (unverified
        -- OCP isn't installed in the dev sandbox), draw_shape's own
        guard already degrades gracefully and prints once, and this
        fallback keeps the app FUNCTIONAL (if ambiguous for shared
        parts) rather than breaking selection entirely; (2) parts
        drawn before this fix shipped (a long-running session that
        hasn't reloaded) won't have the tag yet.

        The old scan's own docstring assumption -- 'each part's
        AIS_Shape wraps a distinct base shape' -- is exactly what
        broke on Doug's large model: shared-instance assemblies
        (mirrored/duplicated parts) violate it constantly, and the
        fingerprint was one-way tree<->viewport highlighting (tree-
        to-viewport uses an unrelated code path and kept working;
        viewport-to-tree, this function, silently matched whichever
        uid happened to iterate first)."""
        if ais_obj is None:
            return None
        try:
            owner = ais_obj.GetOwner()
            if owner is not None:
                candidate = None
                try:
                    # Case 1: pybind11 auto-downcast the Transient
                    # handle to its real runtime subtype already.
                    candidate = owner.ToCString()
                except AttributeError:
                    try:
                        # Case 2: it didn't -- explicit downcast,
                        # same pattern as this project's TopoDS._s
                        # downcasts elsewhere.
                        from OCP.TCollection import (
                            TCollection_HAsciiString)
                        candidate = TCollection_HAsciiString.DownCast_s(
                            owner).ToCString()
                    except Exception:
                        candidate = None
                if candidate in self.ais_shape_dict:
                    return candidate
        except Exception:
            pass
        try:
            target = ais_obj.Shape()
        except Exception:
            return None
        for uid, ais in self.ais_shape_dict.items():
            try:
                if ais.Shape().IsSame(target):
                    return uid
            except Exception:
                continue
        return None

    def _highlight_viewport(self, uid):
        """Highlight exactly the AIS shape for uid (clear others).
        Uses the AIS context's own hilight so it coexists with normal
        selection colours."""
        display = getattr(self.canvas, "_display", None)
        if display is None:
            return
        context = display.Context
        try:
            context.ClearSelected(False)
            ais = self.ais_shape_dict.get(uid) if uid else None
            if ais is not None:
                context.SetSelected(ais, False)
            context.UpdateCurrentViewer()
            self.canvas.update()
            self._highlighted_uid = uid
        except Exception as e:
            print(f"[highlight_sync] viewport highlight failed: {e}")

    def _uid_for_selected_shape(self, shape):
        """Reverse-map a picked TopoDS_Shape to its uid via
        ais_shape_dict. The picked shape is a sub-shape (face/edge) or
        the whole shape; match by identifying which AIS_Shape's shape
        contains/equals it."""
        if shape is None:
            return None
        from OCP.TopoDS import TopoDS_Shape
        for uid, ais in self.ais_shape_dict.items():
            try:
                if ais.Shape().IsEqual(shape):
                    return uid
            except Exception:
                continue
        # Sub-shape pick: match by ancestry (the picked face/edge
        # belongs to one part's shape)
        for uid, ais in self.ais_shape_dict.items():
            try:
                from OCP.TopExp import TopExp_Explorer
                from OCP.TopAbs import TopAbs_ShapeEnum
                exp = TopExp_Explorer(ais.Shape(), shape.ShapeType())
                while exp.More():
                    if exp.Current().IsSame(shape):
                        return uid
                    exp.Next()
            except Exception:
                continue
        return None

    def _tree_item_for_uid(self, uid):
        """Find the tree item whose column-1 text is uid."""
        for item in self.treeView.findItems(
                "", Qt.MatchFlag.MatchContains | Qt.MatchRecursive):
            if item.text(1) == uid:
                return item
        return None

    def editUndo(self):
        """Undo the last committed transaction (Session 61)."""
        if dm.doc.GetAvailableUndos() < 1:
            self.statusBar().showMessage("Nothing to undo", 3000)
            return
        dm.doc.Undo()
        self._refresh_after_history("Undo")

    def editRedo(self):
        """Redo the last undone transaction (Session 61)."""
        if dm.doc.GetAvailableRedos() < 1:
            self.statusBar().showMessage("Nothing to redo", 3000)
            return
        dm.doc.Redo()
        self._refresh_after_history("Redo")

    def _refresh_after_history(self, verb):
        """Full state refresh after Undo/Redo. Cached uids can dangle
        (labels may be re-created under new entries), so active-part
        state is cleared; the draw-prep cache self-invalidates by
        shape identity and needs no clearing. NOTE (scope, logged):
        workplanes and 2D sketch state live OUTSIDE the OCAF document
        and are not affected by Undo/Redo."""
        self.activePartUID = 0
        self.activePart = None
        self.activeAsyUID = 0
        self.itemClicked = None
        # Snapshot BEFORE parse_doc() re-reads the document -- OCAF's
        # undo can restructure the label tree, so before/after uid
        # diffing is the only reliable signal for what changed.
        old_uids = set(dm.part_dict.keys())
        dm.parse_doc()
        self.build_tree()
        # redraw_all_survivors=True (Session 70, Doug's fillet/undo
        # report): an operation being undone/redone can replace a
        # SURVIVING uid's shape in place (fillet/shell's
        # dm.replace_shape does exactly this) -- that uid exists in
        # both old_uids and new_uids, so the default fast-path
        # (delete's provably-safe 'survivor = untouched' rule) would
        # skip it and leave stale geometry on screen. Undo/redo
        # cannot assume survivors are unchanged the way delete can.
        self._incremental_reconcile(old_uids, redraw_all_survivors=True)
        n_undo = dm.doc.GetAvailableUndos()
        n_redo = dm.doc.GetAvailableRedos()
        self.statusBar().showMessage(
            f"{verb} complete ({n_undo} undo / {n_redo} redo available)",
            4000)

    def registerCallback(self, callback):
        currCallback = self.registeredCallback
        if currCallback:  # Make sure a callback isn't already registered
            self.clearCallback()
        self.canvas._display.register_select_callback(callback)
        self.registeredCallback = callback
        self.currOpLabel.setText("Current Operation: %s " %
                                 callback.__name__[:-1])

    def clearCallback(self):
        if self.registeredCallback:
            self.canvas._display.unregister_callback(self.registeredCallback)
            self.registeredCallback = None
            self.clearAllStacks()
            self.currOpLabel.setText("Current Operation: None ")
            self.statusBar().showMessage("")
            self.canvas._display.SetSelectionModeNeutral()

    #############################################
    #
    # 3D Display Draw/Hide methods:
    #
    #############################################

    def fitAll(self):
        """Fit all displayed parts and wp's to the screen"""
        self.canvas._display.FitAll()

    def _incremental_reconcile(self, old_uids, redraw_all_survivors=False):
        """Reconciles the viewer against dm.part_dict AFTER an
        operation that already called dm.parse_doc() (delete and
        undo/redo both do) -- diffing old_uids (captured by the
        caller BEFORE the operation) against the current part_dict
        keys. Neither delete nor undo/redo gives a clean 'only this
        uid changed' signal on its own: delete can cascade through
        orphaned nested assemblies, and OCAF undo can restructure
        the label tree -- so before/after diffing is the reliable
        technique. Only genuinely removed/new/changed parts touch
        the viewer; everything else keeps its existing AIS object
        untouched, avoiding the RemoveAll()+rebuild-everything cost
        a full redraw() pays regardless of what actually changed.

        SURVIVOR RULE (confirmed by Doug's own diagnostic data, not
        guessed): a uid present in BOTH old_uids and new_uids is
        assumed UNCHANGED and never touches the viewer. An earlier
        version tried to verify this via cached[0].IsSame(current
        shape) -- OCCT's XCAF/TNaming layer is documented to keep
        shape identity stable for untouched labels, which is what
        makes IsSame()-based caching sound in principle, but Doug's
        measurement showed it failing 100% of the time in this
        codebase's actual usage (55 redrawn, 0 skipped, on a delete
        that only removed ONE part) -- so it was providing zero
        signal while costing the FULL redraw cost anyway. Removed.

        This rule is PROVABLY CORRECT for delete: delete_component
        can only remove entries, never modify a surviving sibling's
        geometry. It carries ONE KNOWN, ACCEPTED RISK for undo/redo:
        if an operation replaces a part's shape IN PLACE while
        keeping its uid (Mill/Pull's dm.replace_shape does exactly
        this), undoing/redoing it will leave that part's OLD geometry
        displayed until something else forces a redraw, because its
        uid survives in both old_uids and new_uids and this rule
        skips it. Accepted deliberately rather than silently: if this
        bites in practice, the fix is a small, targeted one (Mill/
        Pull-family operations could report their OWN touched uid
        explicitly), not a reason to keep paying the full-model cost
        for every ordinary delete.

        (Session 70: the accepted risk above was CONFIRMED, not
        hypothetical -- Doug's own GetAvailableUndos() measurement
        showed OCAF genuinely recording a delta for fillet's
        replace_shape (1 -> 2), yet the bottle's geometry stayed
        stale after Undo, because its uid survived in both sets and
        the rule (correctly, by its own logic) skipped it. Rather
        than try to detect 'did this survivor's shape actually
        change' -- IsSame() is confirmed UNRELIABLE for this in this
        codebase's own usage, so there is no cheap, trustworthy
        per-uid signal available without deeper OCAF delta
        introspection (a bigger, separate task, left for later if
        undo/redo speed on large models becomes its own problem) --
        redraw_all_survivors gives callers that know their operation
        can replace a SURVIVING uid's shape in place (undo/redo, via
        _refresh_after_history) an explicit way to say so. Delete
        continues to use the fast, provably-safe default.)

        (Session 65 postscript: this same uid space is also where
        self.hide_list needs reconciling -- it held stale uids
        across undo/redo with nothing ever pruning it, causing tree/
        viewport checkbox desync. Folded in here since it's the same
        underlying problem: state keyed by uid, unrefreshed when the
        uid space changes.)"""
        import time as _time
        _t0 = _time.monotonic()
        context = self.canvas._display.Context
        if not self.registeredCallback:
            self.canvas._display.SetSelectionModeNeutral()
            context.SetAutoActivateSelection(True)
        new_uids = set(dm.part_dict.keys())
        valid_uids = new_uids | set(self.wp_dict.keys())
        stale = [u for u in self.hide_list if u not in valid_uids]
        for u in stale:
            self.hide_list.remove(u)
        _t_removed0 = _time.monotonic()
        removed = old_uids - new_uids
        for uid in removed:
            ais = self.ais_shape_dict.pop(uid, None)
            if ais is not None:
                try:
                    context.Remove(ais, False)
                except Exception as re:
                    print(f"[reconcile] Context.Remove failed for "
                         f"{uid}: {re}")
            self._display_prep_cache.pop(uid, None)
        _dt_removed = _time.monotonic() - _t_removed0
        _t_survivors0 = _time.monotonic()
        _n_skipped = 0
        _n_redrawn = 0
        _redrawn_uids = []
        genuinely_new = new_uids - old_uids
        to_redraw = new_uids if redraw_all_survivors else genuinely_new
        for uid in to_redraw:
            if uid in self.hide_list:
                continue
            self.draw_shape(uid)
            _n_redrawn += 1
            _redrawn_uids.append(uid)
        _n_skipped = len(new_uids) - len(to_redraw)
        _dt_survivors = _time.monotonic() - _t_survivors0
        _t1 = _time.monotonic()
        context.UpdateCurrentViewer()
        self.canvas.update()
        _dt_total = _time.monotonic() - _t0
        _dt_repaint = _time.monotonic() - _t1
        if removed or stale:
            print(f"[reconcile] {len(removed)} removed, "
                 f"{len(stale)} stale hide_list entr"
                 f"{'y' if len(stale) == 1 else 'ies'} pruned")
        if _dt_total > 0.5:
            print(f"[reconcile] TIMING: total {_dt_total:.2f}s -- "
                 f"removed-loop {_dt_removed:.2f}s, "
                 f"survivor-loop {_dt_survivors:.2f}s "
                 f"({_n_redrawn} redrawn, {_n_skipped} skipped as "
                 f"unchanged), repaint {_dt_repaint:.2f}s")
            if _n_redrawn > 1:
                print(f"[reconcile]   redrawn (not just the deleted "
                     f"uid's siblings -- these should have been "
                     f"SKIPPED if truly unchanged): {_redrawn_uids}")

    def redraw(self):
        """Erase & redraw all parts & workplanes except those in hide_list."""
        context = self.canvas._display.Context
        if not self.registeredCallback:
            self.canvas._display.SetSelectionModeNeutral()
            context.SetAutoActivateSelection(True)
        context.RemoveAll(False)
        # Redraw all parts except those hidden
        for uid in dm.part_dict:
            if uid not in self.hide_list:
                self.draw_shape(uid)
        # Redraw workplanes except those hidden
        self.redraw_workplanes()
        # RemoveAll() above wipes EVERYTHING in the context, not just
        # part/workplane geometry -- the AIS_ViewCube (Session 38)
        # lives in the same context and was only ever added once, at
        # startup, with nothing restoring it after any of the many
        # places that call redraw() (session load, Position moves,
        # RMB delete, etc. -- not just session load, which is just
        # where this was first noticed). Re-add it every time.
        self.canvas._add_view_cube()
        # Prune draw-prep cache entries for parts that no longer exist
        for stale in [u for u in self._display_prep_cache
                      if u not in dm.part_dict]:
            del self._display_prep_cache[stale]
        context.UpdateCurrentViewer()
        self.canvas.update()

    
    def redraw_workplanes(self):
        """Redraw all workplanes except those in self.hide_list"""

        for uid in self.wp_dict:
            if uid not in self.hide_list:
                self.draw_wp(uid)

    def draw_wp(self, uid):
        """Draw the workplane with uid."""
        context = self.canvas._display.Context
        if uid:
            wp = self.wp_dict[uid]
            # ERASE-BEFORE-REDRAW (Session 63, Doug's double-border
            # report): draw_wp used to only ADD -- identical objects
            # stacked invisibly until the auto-fit border changed
            # size between redraws and exposed the accumulation as a
            # 'second workplane'. Every AIS this method displays is
            # registered per-uid and removed at the next redraw.
            if not hasattr(self, "_wp_ais_reg"):
                self._wp_ais_reg = {}
            for old_ais in self._wp_ais_reg.get(uid, []):
                try:
                    context.Remove(old_ais, False)
                except Exception:
                    pass
                self.canvas._display.remove_never_pick(old_ais)
            _reg = self._wp_ais_reg[uid] = []
            try:
                wp.update_border()  # auto-fit (Session 63)
            except Exception as ube:
                print(f"[draw_wp] border auto-fit failed: {ube}")
            border = wp.border
            if uid == self.activeWpUID:
                borderColor = Quantity_Color(Quantity_NOC_DARKGREEN)
            else:
                borderColor = Quantity_Color(Quantity_NOC_GRAY)
            aisBorder = AIS_Shape(border)
            _reg.append(aisBorder)
            context.Display(aisBorder, True)
            # NON-PICKABLE (Session 63, Doug's 'pick barrier' report):
            # the translucent pane was a selectable face, competing
            # with part faces behind it in face-selection mode --
            # highlight flicker, and sometimes the pane's rectangular
            # highlight winning outright. The pane is scenery, not an
            # entity; it never participates in selection.
            self.canvas._display.add_never_pick(aisBorder)
            context.SetColor(aisBorder, borderColor, True)
            # 0.92: barely-there interior, CoCreate-like (Session 63)
            transp = 0.92  # 0.0 <= transparency <= 1.0
            context.SetTransparency(aisBorder, transp, True)
            drawer = aisBorder.DynamicHilightAttributes()
            context.HilightWithColor(aisBorder, drawer, True)
            # Explicit BORDER OUTLINE (Session 63, Doug: the CoCreate
            # pane has a visible boundary line; ours never did -- the
            # translucent fill was the only cue, invisible against
            # some backgrounds). Thin dark rectangle at the pane
            # edge, non-pickable.
            try:
                bo = getattr(wp, 'border_bounds', None)
                if bo is not None:
                    owire = wp.makeRectProfile(bo[0], bo[1],
                                               bo[2], bo[3])
                    ais_outline = AIS_Shape(owire)
                    _reg.append(ais_outline)
                    context.Display(ais_outline, False)
                    try:
                        from OCP.Quantity import Quantity_NOC_TEAL
                        _oc = Quantity_Color(Quantity_NOC_TEAL)
                    except Exception:
                        _oc = Quantity_Color(Quantity_NOC_DARKGREEN)
                    context.SetColor(ais_outline, _oc, False)
                    context.SetWidth(ais_outline, 2.0, False)
                    self.canvas._display.add_never_pick(ais_outline)
            except Exception as oe:
                if not getattr(self, "_wpoutline_warned", False):
                    print(f"[draw_wp] border outline failed: {oe}")
                    self._wpoutline_warned = True
            # '/w#' label at the border's lower-left corner --
            # drawn as STROKE GEOMETRY lying in the plane (Session
            # 63: AIS_TextLabel was screen-aligned and screen-sized;
            # Doug wants it square with the wp and zooming with the
            # model, which model-space geometry cannot fail to do).
            try:
                bbnds = getattr(wp, 'border_bounds', None)
                if bbnds is not None:
                    pane_min = min(bbnds[2] - bbnds[0],
                                   bbnds[3] - bbnds[1])
                    lh = max(2.5, min(0.05 * pane_min, 12.0))
                    lorig = (bbnds[0] + 0.6 * lh, bbnds[1] + 0.6 * lh)
                    lshape = _wp_label_shape(f"/{uid}", lorig, lh,
                                             wp.Trsf)
                    if lshape is not None:
                        ais_label = AIS_Shape(lshape)
                        _reg.append(ais_label)
                        context.Display(ais_label, False)
                        context.SetColor(
                            ais_label,
                            Quantity_Color(Quantity_NOC_BLACK), False)
                        context.SetWidth(ais_label, 1.5, False)
                        self.canvas._display.add_never_pick(ais_label)
            except Exception as le:
                if not getattr(self, "_wplabel_warned", False):
                    print(f"[draw_wp] wp label failed: {le}")
                    self._wplabel_warned = True
            clClr = Quantity_Color(Quantity_NOC_MAGENTA1)
            # Clines CLIPPED to the border (Session 63, Doug: Creo
            # doesn't display clines beyond the pane edge; ours ran
            # to infinity -- they always had, via AIS_Line of an
            # infinite Geom_Line). Each cline is drawn as a finite
            # dashed edge spanning the border rectangle. The line
            # remains mathematically infinite in the engine; only
            # the DISPLAY is clipped. A cline that misses the border
            # entirely (possible for angled clines, which don't
            # constrain the auto-fit) simply isn't drawn.
            bb = getattr(wp, 'border_bounds', None)
            for cline in wp.clines:
                seg = _clip_line_to_rect(cline, bb) if bb else None
                if seg is None:
                    continue
                try:
                    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge
                                                    as _MkCL)
                    g1 = gp_Pnt(seg[0][0], seg[0][1],
                                0).Transformed(wp.Trsf)
                    g2 = gp_Pnt(seg[1][0], seg[1][1],
                                0).Transformed(wp.Trsf)
                    if g1.Distance(g2) < 1.0e-9:
                        continue
                    aisline = AIS_Shape(_MkCL(g1, g2).Edge())
                    drawer = aisline.Attributes()
                    asp = Prs3d_LineAspect(
                        clClr, Aspect_TypeOfLine.Aspect_TOL_DASH, 1.0)
                    drawer.SetLineAspect(asp)
                    drawer.SetWireAspect(asp)
                    aisline.SetAttributes(drawer)
                    _reg.append(aisline)
                    context.Display(aisline, False)
                    context.SetColor(aisline, clClr, False)
                    self.canvas._display.add_never_pick(aisline)
                except Exception as cle:
                    print(f"[draw_wp] cline display failed: {cle}")
            # Construction ARCS (Session 63): finite, dashed
            # magenta -- csegs' logic applied to circles
            for ca in getattr(wp, 'carcs', ()):
                try:
                    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge
                                                    as _MkAE)
                    geomCirc = wp.convert_circ_to_geomCirc(
                        (ca[0], ca[1]))
                    ais_ca = AIS_Shape(
                        _MkAE(geomCirc, ca[2], ca[3]).Edge())
                    cadrawer = ais_ca.Attributes()
                    caasp = Prs3d_LineAspect(
                        clClr, Aspect_TypeOfLine.Aspect_TOL_DASH, 1.0)
                    cadrawer.SetLineAspect(caasp)
                    cadrawer.SetWireAspect(caasp)
                    ais_ca.SetAttributes(cadrawer)
                    _reg.append(ais_ca)
                    context.Display(ais_ca, False)
                    context.SetColor(ais_ca, clClr, False)
                    self.canvas._display.add_never_pick(ais_ca)
                except Exception as cae:
                    print(f"[draw_wp] carc display failed: {cae}")
            # Construction SEGMENTS (Session 63): finite, dashed
            # magenta like clines -- the projected-edge entity
            for cs in getattr(wp, 'csegs', ()):
                try:
                    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge
                                                    as _MkE)
                    # (gp_Pnt now module-level -- a function-local
                    # import here made gp_Pnt local to ALL of
                    # draw_wp, unbinding it for the label and cline
                    # blocks that run earlier. Doug's terminal
                    # diagnosed it verbatim.)
                    g1 = gp_Pnt(cs[0][0], cs[0][1], 0).Transformed(wp.Trsf)
                    g2 = gp_Pnt(cs[1][0], cs[1][1], 0).Transformed(wp.Trsf)
                    if g1.Distance(g2) < 1.0e-9:
                        continue
                    ais_cs = AIS_Shape(_MkE(g1, g2).Edge())
                    csdrawer = ais_cs.Attributes()
                    csasp = Prs3d_LineAspect(
                        clClr, Aspect_TypeOfLine.Aspect_TOL_DASH, 1.0)
                    csdrawer.SetLineAspect(csasp)
                    csdrawer.SetWireAspect(csasp)
                    ais_cs.SetAttributes(csdrawer)
                    _reg.append(ais_cs)
                    context.Display(ais_cs, False)
                    context.SetColor(ais_cs, clClr, False)
                    self.canvas._display.add_never_pick(ais_cs)
                except Exception as cse:
                    print(f"[draw_wp] cseg display failed: {cse}")
            # RETIRED (Session 62, sketch engine step 4): the
            # pre-built intersection-point markers (wp.intersectPts()
            # displayed as vertex-selectable '+' glyphs) are gone --
            # the snap engine computes intersections ON THE FLY and
            # the orange catch square carries the feedback role. All
            # 2D collectors now take engine input; the legacy vertex
            # path survives only as a fallback that these markers no
            # longer feed. wp.intersectPts() itself remains available
            # in workplane.py.
            for ccirc in wp.ccircs:
                aiscirc = AIS_Circle(wp.convert_circ_to_geomCirc(ccirc))
                # (was aisline.Attributes() -- the LAST cline's
                # drawer, a NameError on any wp with circles but no
                # clines; latent forever because creation always made
                # clines, exposed the moment they were retired)
                drawer = aiscirc.Attributes()
                # asp parameters: (color, type, width)
                asp = Prs3d_LineAspect(clClr, Aspect_TypeOfLine.Aspect_TOL_DASH, 1.0)
                drawer.SetLineAspect(asp)
                aiscirc.SetAttributes(drawer)
                _reg.append(aiscirc)
                context.Display(aiscirc, False)  # (see comment below)
                self.canvas._display.add_never_pick(aiscirc)
                # 'False' above enables 'context' mode display & selection
            for edge in wp.edgeList:
                # BOLD BLACK geometry (Session 62, Doug: Creo E/D
                # draws geometry in bold black and it reads far
                # better than white -- Pyurcad's white-on-black
                # doesn't translate to this canvas)
                ais_geom = self.canvas._display.DisplayShape(edge)
                if ais_geom is not None:
                    _reg.append(ais_geom)
                    # (local Quantity import removed -- it shadowed
                    # module-level Quantity_NOC_BLACK function-wide,
                    # unbinding it for the label block that runs
                    # earlier; same scoping bug as gp_Pnt)
                    try:
                        context.SetColor(ais_geom,
                                         Quantity_Color(
                                             Quantity_NOC_BLACK), False)
                        context.SetWidth(ais_geom, 3.0, False)
                    except Exception:
                        pass
            self.canvas._display.Repaint()

    def draw_shape(self, uid):
        """Draw the part (shape) with uid."""
        context = self.canvas._display.Context
        if uid:
            # ERASE-BEFORE-REDISPLAY (Session 70, Doug's fillet/undo
            # scars report). draw_shape has ALWAYS only ever ADDED --
            # it creates a fresh AIS_Shape and overwrites
            # ais_shape_dict[uid] without first removing whatever
            # was PREVIOUSLY displayed for this uid. Masked for the
            # project's entire history because every prior call site
            # either used a full redraw() (context.RemoveAll() first,
            # wiping the slate before this ever mattered) or genuinely
            # displayed a uid for the first time. Session 70's
            # redraw_all_survivors fix is the first code path to call
            # draw_shape() repeatedly for the SAME uid with no
            # RemoveAll() in between (undo then redo, back to back) --
            # exposing this for real: each call left the PRIOR AIS
            # object orphaned and still displayed, invisible to
            # ais_shape_dict and therefore to erase_shape/hide-show
            # too. Overlapping near-identical surfaces (filleted vs.
            # not) is exactly what produces 'scars at the tangencies'.
            # Identical fix already proven for draw_wp earlier this
            # session -- same disease, same cure, different function.
            _prior_ais = self.ais_shape_dict.pop(uid, None)
            if _prior_ais is not None:
                try:
                    context.Remove(_prior_ais, False)
                except Exception:
                    pass
            if uid in self.transparency_dict:
                transp = self.transparency_dict[uid]
            else:
                transp = 0.0
            part_data = dm.part_dict[uid]
            shape = part_data["shape"]
            color = part_data["color"]
            try:
                # THE SAVE/RELOAD PICK FIX (Session 60; perf pass
                # Session 61). Root cause: OCCT 7.7+ analytic
                # selection for cylindrical faces
                # (Select3D_SensitiveCylinder from surface placement +
                # V-range, ignoring triangulation) mishandles the
                # STEP reader's reversed-axis/NEGATIVE-V-range
                # cylinder parametrization -- the pickable wall gets
                # built displaced one height below the visible face.
                # Fix: display-only NurbsConvert makes such faces
                # ineligible for the analytic path; selection falls
                # back to triangulation.
                #
                # Session 61 performance pass (Doug: visibly slower
                # lathe display): (1) SELECTIVE -- convert only when
                # the measured pathology is present (cylinder/cone
                # face with negative V-range, the reader's signature);
                # fresh/canonical parts skip conversion entirely, and
                # get their clean highlight wireframes back (no patch
                # seams). If a pick regression ever reappears on a
                # part this trigger skipped, broaden
                # _needs_analytic_workaround. (2) CACHED -- the
                # prepared (converted+meshed) shape is kept per uid,
                # keyed by source-shape identity (IsSame), so redraws
                # reuse it; a changed/moved part self-invalidates and
                # re-prepares alone.
                cached = self._display_prep_cache.get(uid)
                if cached is not None and cached[0].IsSame(shape):
                    shape = cached[1]
                else:
                    # COPY BEFORE ANY DISPLAY-PREP MUTATION (the
                    # actual fix for Doug's 2.6x STEP-save point
                    # bloat). shape here is part_data["shape"] --
                    # the SAME object backing this label inside
                    # dm.doc. BRepMesh_IncrementalMesh below does
                    # NOT return a new shape; it attaches
                    # triangulation directly to whatever shape it's
                    # given, IN PLACE. For the common case (no
                    # NurbsConvert -- 'fresh/canonical parts skip
                    # conversion entirely' per the comment below),
                    # shape was never reassigned, so meshing ran
                    # directly on the document's own stored geometry
                    # -- every part ever displayed before a save
                    # picked up a permanent mesh, written out as
                    # extra CARTESIAN_POINT entities identical
                    # topology, 2.6x the points, confirmed by Doug's
                    # entity-count diagnostic (solid/face/surface
                    # counts exactly unchanged; point count alone
                    # exploded). An explicit, independent copy here
                    # -- unconditional, before EITHER branch below --
                    # guarantees display prep can never mutate dm.doc
                    # again, regardless of which branch runs or
                    # whether some future OCCT algorithm shares
                    # sub-shape identity with its input.
                    # src_shape MUST stay the ORIGINAL part_data["shape"]
                    # reference -- it's the cache-identity key compared
                    # (via IsSame()) against a FRESH part_data["shape"]
                    # read on every future call (line ~1931 above). If
                    # this captured the COPY instead, no future read of
                    # part_data["shape"] would ever IsSame()-match it
                    # (a copy is never IsSame its source) -- the cache
                    # would miss on every single redraw, silently
                    # undoing Session 61's whole caching mechanism.
                    src_shape = shape
                    try:
                        from OCP.BRepBuilderAPI import \
                            BRepBuilderAPI_Copy
                        shape = BRepBuilderAPI_Copy(shape, True, True).Shape()
                    except Exception as cpe:
                        if not getattr(self, "_copy_warned", False):
                            print(f"[draw_shape] display-prep copy "
                                 f"failed ({cpe}) -- display-prep "
                                 f"mutations may leak into the saved "
                                 f"document")
                            self._copy_warned = True
                    if _needs_analytic_workaround(shape):
                        try:
                            from OCP.BRepBuilderAPI import \
                                BRepBuilderAPI_NurbsConvert
                            shape = BRepBuilderAPI_NurbsConvert(
                                shape, True).Shape()
                        except Exception as ce:
                            if not getattr(self, "_nurbs_warned", False):
                                print(f"[draw_shape] nurbs convert "
                                      f"failed (analytic-selection bug "
                                      f"may reappear on reloaded curved "
                                      f"faces): {ce}")
                                self._nurbs_warned = True
                    try:
                        from OCP.BRepMesh import BRepMesh_IncrementalMesh
                        BRepMesh_IncrementalMesh(shape, 0.1, False, 0.5,
                                                 True)
                    except Exception as me:
                        if not getattr(self, "_mesh_warned", False):
                            print(f"[draw_shape] pre-mesh failed: {me}")
                            self._mesh_warned = True
                    self._display_prep_cache[uid] = (src_shape, shape)
                aisShape = AIS_Shape(shape)
                # Tag the AIS object with its OWN uid directly
                # (selection-sync fix). Reverse-lookup used to match
                # by SHAPE IDENTITY (ais.Shape().IsSame(...)) -- an
                # assumption that breaks the instant two parts share
                # an underlying TopoDS_Shape, which shared-instance
                # assemblies do routinely (Doug's large Diffy model:
                # many mirrored/duplicated parts). A direct owner tag
                # is unambiguous per AIS OBJECT (unique per
                # occurrence, even when the geometry isn't).
                # DEFENSIVE: SetOwner's C++ signature expects a
                # Handle(Standard_Transient); whether the OCP binding
                # accepts a plain Python str could not be verified in
                # this sandbox (OCP isn't installed here). Guarded so
                # a binding mismatch degrades to the OLD shape-scan
                # lookup (still correct for non-shared parts) instead
                # of crashing draw_shape for every part -- and prints
                # once so a failure is immediately visible rather
                # than silently falling back forever.
                try:
                    # Doug's terminal gave the exact answer: OCP's
                    # SetOwner wants a Standard_Transient handle, not
                    # a bare str. TCollection_HAsciiString is a real
                    # Transient subclass built for exactly this.
                    from OCP.TCollection import TCollection_HAsciiString
                    aisShape.SetOwner(TCollection_HAsciiString(uid))
                except Exception as oe:
                    if not getattr(self, "_setowner_warned", False):
                        print(f"[draw_shape] SetOwner(uid) failed "
                             f"({oe}) -- selection-sync falls back "
                             f"to the shape-identity scan, which is "
                             f"ambiguous for shared-instance parts")
                        self._setowner_warned = True
                self.ais_shape_dict[uid] = aisShape
                context.Display(aisShape, False)
                if color:
                    context.SetColor(aisShape, color, False)
                if transp > 0:
                    context.SetTransparency(aisShape, transp, False)
                # Black face boundary edges
                from OCP.Aspect import Aspect_TypeOfLine
                from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
                drawer = aisShape.Attributes()
                drawer.SetFaceBoundaryDraw(True)
                black = Quantity_Color(0.0, 0.0, 0.0,
                    Quantity_TypeOfColor.Quantity_TOC_RGB)
                drawer.FaceBoundaryAspect().SetColor(black)
                drawer.FaceBoundaryAspect().SetWidth(1.0)
                drawer.FaceBoundaryAspect().SetTypeOfLine(
                    Aspect_TypeOfLine.Aspect_TOL_SOLID)
                context.Redisplay(aisShape, False)
            except Exception as e:
                print(f"draw_shape error for {uid}: {e}")
        context.UpdateCurrentViewer()
        self.canvas.update()

    def erase_shape(self, uid):
        """Erase the part (shape) with uid."""
        if uid in self.ais_shape_dict:
            context = self.canvas._display.Context
            aisShape = self.ais_shape_dict[uid]
            # This did the job prior to PyOCC 7.6
            context.Remove(aisShape, True)
            # Added to get 'hide' working in PyOCC 7.6
            context.Erase(aisShape, True)

    #############################################
    #
    # 3D Measure functions...
    #
    #############################################

    def launchCalc(self):
        """Launch Calculator"""
        if not self.calculator:
            self.calculator = rpnCalculator.Calculator(self)
            self.calculator.show()

    def setUnits(self, units):
        """Set units of linear distance (Default is 'mm')"""
        if units in self._unitDict.keys():
            self.units = units
            self.unitscale = self._unitDict[self.units]
            self.unitsLabel.setText("Units: %s " % self.units)

    def distPtPt(self):
        """Measure distance between 2 selectable points on model or workplane"""
        if len(self.ptStack) == 2:
            p2 = self.ptStack.pop()
            p1 = self.ptStack.pop()
            vec = gp_Vec(p1, p2)
            dist = vec.Magnitude()
            dist = dist / self.unitscale
            self.calculator.putx(dist)
            self.distPtPt()
        else:
            self.registerCallback(self.distPtPtC)
            # How to enable selecting intersection points on WP?
            self.canvas._display.SetSelectionModeVertex()
            statusText = "Select 2 points to measure distance."
            self.statusBar().showMessage(statusText)

    def distPtPtC(self, shapeList, *args):
        """Callback (collector) for distPtPt.

        Session 63 (answering the old comment in distPtPt itself --
        'How to enable selecting intersection points on WP?'):
        ENGINE INPUT FIRST -- a catch on the active workplane
        (intersection/endpoint, or Ctrl+Shift center/midpoint)
        becomes a measurable world point via uv_to_world; the 3D
        VERTEX pick remains as fallback for measuring between part
        vertices. Both yield world gp_Pnts, so a wp catch and a 3D
        vertex can be measured AGAINST EACH OTHER. No catch and no
        vertex -> the click is declined with a hint, never a
        traceback."""
        pt = None
        # 1. Engine path: catch on the active workplane
        try:
            click_xy = args[1] if len(args) > 1 else None
            wp = self.activeWp
            if (click_xy is not None and click_xy[0] is not None
                    and wp is not None):
                from snap_engine import (screen_to_uv, find_snap,
                                         uv_to_world, SNAP_PIXELS,
                                         current_snap_mode)
                uv = screen_to_uv(self.canvas.view, click_xy[0],
                                  click_xy[1], wp.gpPlane)
                if uv is not None:
                    try:
                        tol = abs(self.canvas.view.Convert(SNAP_PIXELS))
                    except Exception:
                        tol = 1.0
                    snap = find_snap(wp, uv, tol, current_snap_mode())
                    if snap is not None:
                        pt = uv_to_world(wp.gpPlane, snap[1][0],
                                         snap[1][1])
        except Exception as se:
            print(f"[distPtPt] engine path failed: {se}")
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
            self.statusBar().showMessage(
                "No catch or vertex there -- click a workplane catch "
                "or a part vertex.", 3000)
            return
        self.ptStack.append(pt)
        if len(self.ptStack) == 1:
            self.statusBar().showMessage(
                "Point 1 set. Select the second point.")
        if len(self.ptStack) == 2:
            self.distPtPt()

    def edgeLen(self):
        """Measure length of a part edge or geometry profile line"""
        if self.edgeStack:
            edge = self.edgeStack.pop()
            edgelen = CPnts_AbscissaPoint.Length_s(BRepAdaptor_Curve(edge))
            edgelen = edgelen / self.unitscale
            self.calculator.putx(edgelen)
            self.edgeLen()
        else:
            self.registerCallback(self.edgeLenC)
            self.canvas._display.SetSelectionModeEdge()
            statusText = "Pick an edge to measure."
            self.statusBar().showMessage(statusText)

    def edgeLenC(self, shapeList, *args):
        """Callback (collector) for edgeLen"""
        logger.debug("Edges selected: %s", shapeList)
        logger.debug("args: %s", args)  # args = x, y mouse coords
        for shape in shapeList:
            edge = TopoDS.Edge_s(shape)
            self.edgeStack.append(edge)
        if self.edgeStack:
            self.edgeLen()
