"""
koda_viewport.py

Viewport for kodacad2 -- OCP + PySide6 replacement for PythonOCC's qtDisplay.

Uses the same proven initialization pattern as Basicad's assembly_viewer.py
with WA_NativeWindow + WA_PaintOnScreen attributes.

Provides:
  self._display  -- DisplayShim for mainwindow.py compatibility
  self.context   -- AIS_InteractiveContext
  self.view      -- V3d_View
"""

from OCP.AIS import AIS_Shape, AIS_InteractiveContext, AIS_ViewController
from OCP.TopAbs import TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE, TopAbs_SHAPE
from OCP.Aspect import Aspect_ScrollDelta
from OCP.Graphic3d import Graphic3d_Vec2i
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


class DisplayShim:
    """
    Compatibility shim exposing the PythonOCC display interface
    that mainwindow.py expects from canvas._display.
    """

    def __init__(self, context, view, viewport):
        self.Context = context
        self._view = view
        self._viewport = viewport
        self.selected_shape = None
        self._select_callbacks = []

    def FitAll(self):
        self._view.FitAll()
        self._viewport.update()

    def Repaint(self):
        self.Context.UpdateCurrentViewer()
        self._viewport.update()

    def DisplayShape(self, shape, color=None, transparency=None, update=False):
        try:
            # Convert gp_Pnt to TopoDS_Vertex if needed
            from OCP.gp import gp_Pnt
            if isinstance(shape, gp_Pnt):
                from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
                shape = BRepBuilderAPI_MakeVertex(shape).Vertex()
            ais = AIS_Shape(shape)
            self.Context.Display(ais, False)
            if color:
                if isinstance(color, str):
                    color = self._named_color(color)
                self.Context.SetColor(ais, color, False)
            if transparency is not None:
                self.Context.SetTransparency(ais, transparency, False)
            if update:
                self.Context.UpdateCurrentViewer()
                self._viewport.update()
            return ais
        except Exception as e:
            print(f"DisplayShape failed: {e}")

    def _named_color(self, name):
        color_map = {
            'WHITE': Quantity_Color(1, 1, 1, Quantity_TypeOfColor.Quantity_TOC_RGB),
            'RED':   Quantity_Color(1, 0, 0, Quantity_TypeOfColor.Quantity_TOC_RGB),
            'GREEN': Quantity_Color(0, 1, 0, Quantity_TypeOfColor.Quantity_TOC_RGB),
            'BLUE':  Quantity_Color(0, 0, 1, Quantity_TypeOfColor.Quantity_TOC_RGB),
        }
        return color_map.get(name.upper(),
            Quantity_Color(1, 1, 1, Quantity_TypeOfColor.Quantity_TOC_RGB))

    def _set_selection_mode(self, shape_type):
        if shape_type is None:
            self.Context.SetAutoActivateSelection(True)
            try: self.Context.Activate(0)
            except Exception: pass
            return
        mode = AIS_Shape.SelectionMode_s(shape_type)
        try: self.Context.Deactivate(0)
        except Exception: pass
        self.Context.Activate(mode)

    def SetSelectionModeVertex(self):   self._set_selection_mode(TopAbs_VERTEX)
    def SetSelectionModeEdge(self):     self._set_selection_mode(TopAbs_EDGE)
    def SetSelectionModeFace(self):     self._set_selection_mode(TopAbs_FACE)
    def SetSelectionModeShape(self):    self._set_selection_mode(TopAbs_SHAPE)
    def SetSelectionModeNeutral(self):  self._set_selection_mode(None)

    def register_select_callback(self, callback):
        self._select_callbacks.append(callback)

    def unregister_callback(self, callback):
        if callback in self._select_callbacks:
            self._select_callbacks.remove(callback)

    def call_select_callbacks(self, shape, *args):
        self.selected_shape = shape
        # PythonOCC callbacks expected (shapeList, *args) where shapeList
        # is a list of selected shapes. Wrap single shape in a list.
        shape_list = [shape] if shape is not None else []
        for cb in self._select_callbacks:
            try:
                cb(shape_list, *args)
            except Exception:
                # str(e) alone can be empty for some exception types
                # (confirmed: this is exactly why "Select callback
                # error: " was printing with nothing after it) -- print
                # a full traceback so the actual failure is visible.
                import traceback
                print("Select callback error:")
                traceback.print_exc()


class KodaViewport(QWidget):
    """
    3D viewport for kodacad2. Uses WA_NativeWindow + WA_PaintOnScreen
    (same as Basicad's assembly_viewer.py) for reliable OCCT rendering.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Same attributes as Basicad's proven viewport
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._occt_window = None
        self.context = None
        self.view = None
        self._display = None
        self._vc = AIS_ViewController()
        self._press_pos = None
        self._drag_distance = 0.0
        self._drag_threshold = 4.0
        self._rmb_press_pos = None

    def paintEngine(self):
        return None  # Required for WA_PaintOnScreen

    def InitDriver(self):
        """Initialize the OCCT viewer. Called after show()."""
        from OCP.Aspect import Aspect_DisplayConnection, Aspect_NeutralWindow
        from OCP.OpenGl import OpenGl_GraphicDriver
        from OCP.V3d import V3d_Viewer

        display_connection = Aspect_DisplayConnection()
        graphic_driver = OpenGl_GraphicDriver(display_connection, False)
        viewer = V3d_Viewer(graphic_driver)
        viewer.SetDefaultLights()
        viewer.SetLightOn()
        viewer.SetDefaultViewSize(1000.0)

        view = viewer.CreateView()
        view.SetBackgroundColor(
            Quantity_Color(0.5, 0.5, 0.5, Quantity_TypeOfColor.Quantity_TOC_RGB))

        win_handle = int(self.winId())
        occ_win = Aspect_NeutralWindow()
        occ_win.SetSize(max(self.width(), 1), max(self.height(), 1))
        occ_win.SetNativeHandle(win_handle)
        view.SetWindow(occ_win)
        if not occ_win.IsMapped():
            occ_win.Map()

        self._occt_window = occ_win
        self.view = view

        context = AIS_InteractiveContext(viewer)
        context.SetDisplayMode(1, False)
        self.context = context
        self._display = DisplayShim(context, view, self)

        view.MustBeResized()
        self.update()

    def paintEvent(self, event):
        if self.view is not None:
            try:
                self.view.Redraw()
            except Exception as e:
                print(f"paintEvent Redraw error: {e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._occt_window is not None and self.view is not None:
            try:
                self._occt_window.SetSize(self.width(), self.height())
                self.view.MustBeResized()
                self.update()
            except Exception as e:
                print(f"resizeEvent error: {e}")

    # ── Mouse (AIS_ViewController -- crash safe) ────────────────────────

    def _qt_buttons_to_occt(self, qt_buttons):
        """Convert Qt mouse buttons to OCCT flags -- LMB/MMB only.

        RMB is deliberately NOT forwarded here. AIS_ViewController's
        default gesture map binds the right button to
        AIS_MouseGesture_Zoom (drag right button = zoom, driven by
        horizontal cursor movement). We use RMB exclusively for our
        own click-to-FitAll gesture (see mouseReleaseEvent), handled
        entirely outside the ViewController. If RMB press/move events
        are fed to _vc, every RMB click also starts OCCT's built-in
        zoom-drag gesture -- even a few pixels of jitter between press
        and release is enough to trigger it -- and then our own
        view.FitAll() call changes the camera scale out from under
        that gesture's cached start-state, leaving the view zooming
        wildly with cursor position afterward. Excluding RMB here
        means it never reaches the ViewController's gesture state
        machine at all.
        """
        result = 0
        if qt_buttons & Qt.MouseButton.LeftButton:   result |= 8192
        if qt_buttons & Qt.MouseButton.MiddleButton: result |= 16384
        return result

    def _vec2i(self, pos):
        return Graphic3d_Vec2i(int(pos.x()), int(pos.y()))

    def _flush(self):
        if self._occt_window is None or self.view is None:
            return
        try:
            self._vc.FlushViewEvents(self.context, self.view, True)
        except Exception:
            pass
        self.update()

    def mousePressEvent(self, event):
        self._press_pos = event.position()
        self._drag_distance = 0.0
        if event.button() == Qt.MouseButton.RightButton:
            self._rmb_press_pos = event.position()
        pt = self._vec2i(event.position())
        self._vc.UpdateMouseButtons(pt, self._qt_buttons_to_occt(event.buttons()), 0, False)
        self._flush()

    def mouseMoveEvent(self, event):
        if self._press_pos is not None:
            dx = event.position().x() - self._press_pos.x()
            dy = event.position().y() - self._press_pos.y()
            self._drag_distance = (dx**2 + dy**2) ** 0.5
        pt = self._vec2i(event.position())
        self._vc.UpdateMousePosition(pt, self._qt_buttons_to_occt(event.buttons()), 0, False)
        self._flush()

    def mouseReleaseEvent(self, event):
        pt = self._vec2i(event.position())
        self._vc.UpdateMouseButtons(pt, self._qt_buttons_to_occt(event.buttons()), 0, False)
        self._flush()
        if event.button() == Qt.MouseButton.LeftButton:
            if (self._press_pos is not None and
                    self._drag_distance < self._drag_threshold):
                self._on_click()
        elif event.button() == Qt.MouseButton.RightButton:
            if self._rmb_press_pos is not None:
                dx = event.position().x() - self._rmb_press_pos.x()
                dy = event.position().y() - self._rmb_press_pos.y()
                rmb_dist = (dx**2 + dy**2) ** 0.5
                if rmb_dist < self._drag_threshold:
                    if self.view is not None:
                        self.view.FitAll()
                        self.view.ZFitAll()
                        self.update()
            self._rmb_press_pos = None
        self._press_pos = None
        self._drag_distance = 0.0

    def wheelEvent(self, event):
        pt = self._vec2i(event.position())
        delta = Aspect_ScrollDelta(pt, event.angleDelta().y() / 120.0)
        self._vc.UpdateMouseScroll(delta)
        self._flush()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def _on_click(self):
        if self.context is None or self._display is None:
            return
        self.context.InitSelected()
        if self.context.MoreSelected():
            shape = self.context.SelectedShape()
            self._display.call_select_callbacks(shape)
        else:
            self._display.call_select_callbacks(None)
