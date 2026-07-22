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

        # AIS_Manipulator ("Dynamic" Position method) state -- None
        # when not in dynamic-move mode. Ported from Basicad's
        # main_app.py (proven working there, including the mouse-
        # gesture-ownership handling below), adapted for Kodacad's
        # uid/ais_shape_dict model instead of Basicad's build123d node
        # tree. See docs/DEVELOPMENT_LOG.md, Session 23.
        self._manipulator = None
        self._view_cube = None  # AIS_ViewCube, set in _add_view_cube()
        self._manip_dragging = False
        self._manip_leaf_shapes = []       # every AIS_Shape that must move together
        self._manip_start_trsfs = {}       # id(ais) -> gp_Trsf at drag start
        self._manip_move_callback = None   # called every move: (delta_trsf) -> None
        self._manip_done_callback = None   # called on release: (delta_trsf) -> None

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

        self._add_view_cube()

        view.MustBeResized()
        self.update()

    def _add_view_cube(self):
        """AIS_ViewCube in the corner, with RGB-colored XYZ axes
        (matching CAD Assistant's viewport). Clickable faces (6),
        edges (12), and corners (8) animate the camera to the
        corresponding standard view.

        Ported from Basicad's gui/assembly_viewer.py -- already
        proven working there, including a real gotcha already solved:
        Quantity_Color needs an explicit RGB or named-color
        construction, not a bare float triple (confirmed against the
        actual OCP error message when this was first built). The
        corner-pinning via Graphic3d_TransformPers is copied as-is.

        The RGB axis coloring is new -- Basicad's own version doesn't
        have it. Confirmed via a real OCCT forum thread (a user asked
        exactly this -- "how to change the color of the coordinate
        system near the viewcube" -- and the documented, working
        answer is Prs3d_DatumAspect's per-axis ShadingAspect):
        https://dev.opencascade.org/content/how-change-color-coordinate-system-near-viewcube-or-even-erase-coordinate-system
        """
        self._view_cube = None
        try:
            from OCP.AIS import AIS_ViewCube
            from OCP.Prs3d import Prs3d_DatumAspect, Prs3d_DP_XAxis, Prs3d_DP_YAxis, Prs3d_DP_ZAxis
            from OCP.Graphic3d import (
                Graphic3d_TransformPers,
                Graphic3d_TransModeFlags,
                Graphic3d_Vec2i,
            )
            from OCP.Aspect import Aspect_TypeOfTriedronPosition

            vc = AIS_ViewCube()
            vc.SetSize(80)
            vc.SetBoxFacetExtension(8)
            vc.SetAxesPadding(5)
            vc.SetFontHeight(12)
            vc.SetDrawAxes(True)

            # RGB axes: X=red, Y=green, Z=blue, matching CAD Assistant.
            # DatumAspect() returns null on a freshly-constructed
            # AIS_ViewCube -- confirmed directly (real testing hit this
            # exact "'NoneType' object has no attribute 'ShadingAspect'"
            # error) -- it needs an explicit Prs3d_DatumAspect assigned
            # first via SetDatumAspect(), matching a real, confirmed-
            # working example found on the OCCT forum.
            drawer = vc.Attributes()
            drawer.SetDatumAspect(Prs3d_DatumAspect())
            datum = drawer.DatumAspect()
            # Explicit RGB construction (not a bare Quantity_NOC_* enum
            # passed directly) -- matches the already-proven-working
            # pattern this codebase already uses for the background
            # color, avoiding the enum-vs-object construction ambiguity
            # Basicad's own comment flagged when this was first built.
            red = Quantity_Color(1.0, 0.0, 0.0, Quantity_TypeOfColor.Quantity_TOC_RGB)
            green = Quantity_Color(0.0, 1.0, 0.0, Quantity_TypeOfColor.Quantity_TOC_RGB)
            blue = Quantity_Color(0.0, 0.0, 1.0, Quantity_TypeOfColor.Quantity_TOC_RGB)
            datum.ShadingAspect(Prs3d_DP_XAxis).SetColor(red)
            datum.ShadingAspect(Prs3d_DP_YAxis).SetColor(green)
            datum.ShadingAspect(Prs3d_DP_ZAxis).SetColor(blue)

            # Transform persistence keeps it fixed in the corner
            # regardless of camera orientation/zoom.
            trsf_pers = Graphic3d_TransformPers(
                Graphic3d_TransModeFlags.Graphic3d_TMF_TriedronPers,
                Aspect_TypeOfTriedronPosition.Aspect_TOTP_RIGHT_LOWER,
                Graphic3d_Vec2i(100, 100)
            )
            vc.SetTransformPersistence(trsf_pers)
            self.context.Display(vc, False)
            self.context.UpdateCurrentViewer()
            self._view_cube = vc
            print("AIS_ViewCube added to corner (RGB axes).")
        except Exception as e:
            print(f"(AIS_ViewCube not available: {e} -- falling back to trihedron)")
            self.view.TriedronDisplay()

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

    # ── AIS_Manipulator ("Dynamic" Position method) ─────────────────────

    def attach_manipulator(self, leaf_shapes, move_callback=None, done_callback=None):
        """Attach an AIS_Manipulator gizmo to the first of leaf_shapes
        (the rest move in lockstep during drag -- see mouseMoveEvent).

        move_callback(delta_trsf): called on every mouse-move while
        dragging, with the WORLD-space gp_Trsf delta accumulated so
        far. Used for live status-bar feedback.

        done_callback(delta_trsf): called once when the drag ends
        (mouse release), with the final delta. Used to actually apply
        the move via dm.set_component_location(), same as every other
        Position method.
        """
        self.detach_manipulator()  # clean up any existing one first

        if not leaf_shapes:
            print("[manipulator] No shapes to attach to")
            return False

        try:
            from OCP.AIS import AIS_Manipulator
        except ImportError:
            print("[manipulator] AIS_Manipulator not available in this OCP build")
            return False

        self._manip_leaf_shapes = list(leaf_shapes)
        self._manip_move_callback = move_callback
        self._manip_done_callback = done_callback

        try:
            manip = AIS_Manipulator()
            manip.SetModeActivationOnDetection(True)

            # Disable scaling handles -- translate + rotate only.
            # CONFIRMED (previously guessed and wrong): AIS_MM_Scaling
            # is a top-level member of the separate AIS_ManipulatorMode
            # enum, not an attribute of the AIS_Manipulator class --
            # every name in the old try/except guess-loop
            # ("Scaling"/"Scale"/"AIS_MM_Scaling" as attributes of
            # AIS_Manipulator itself) failed silently, so scaling was
            # never actually disabled. This is very likely why the
            # Dynamic gizmo has been seen inducing scaling as well as
            # rotation -- see docs/DEVELOPMENT_LOG.md, Session 39.
            from OCP.AIS import AIS_MM_Scaling
            for axis in range(3):
                manip.SetPart(axis, AIS_MM_Scaling, False)

            manip.Attach(self._manip_leaf_shapes[0])
            self.context.Display(manip, False)
            self.context.UpdateCurrentViewer()
            self.update()
            self._manipulator = manip
            return True
        except Exception as e:
            print(f"[manipulator] attach failed: {e}")
            return False

    def detach_manipulator(self):
        """Remove the manipulator gizmo from the viewport."""
        if self._manipulator is None:
            return
        try:
            self.context.Erase(self._manipulator, False)
            self._manipulator.Detach()
            self.context.UpdateCurrentViewer()
            self.update()
        except Exception as e:
            print(f"[manipulator] detach failed: {e}")
        self._manipulator = None
        self._manip_dragging = False
        self._manip_leaf_shapes = []
        self._manip_start_trsfs = {}
        self._manip_move_callback = None
        self._manip_done_callback = None

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

        # Manipulator gets first refusal on LMB -- same "who owns this
        # gesture" pattern as Session 12's RMB fix, this time deciding
        # between the gizmo and AIS_ViewController's rotate instead of
        # between our own click-to-fit and OCCT's built-in zoom.
        #
        # RELIABILITY NOTE (Session 39): a real OCCT forum thread shows
        # HasActiveMode() alone can be unreliable in exactly this kind
        # of manual context.MoveTo()+check pattern (confirmed: Doug
        # reproduced spurious captured drags in BOTH Kodacad and
        # Basicad, ruling out a Kodacad-specific porting error --
        # this is a real limitation of the pattern itself, not
        # something introduced in this port). Added DetectedInteractive()
        # as a second, more specific gate: confirms the object
        # context.MoveTo() actually found under the cursor IS
        # specifically our manipulator, not just trusting HasActiveMode()
        # in isolation. A genuine architectural fix (letting
        # AIS_ViewController drive the manipulator directly, which a
        # forum reply confirms removes the need for manual StartTransform/
        # Transform/StopTransform calls entirely) may still be needed if
        # this isn't sufficient -- not attempted here without a confirmed
        # concrete example of how that wiring actually works internally.
        if event.button() == Qt.MouseButton.LeftButton and self._manipulator is not None:
            x, y = int(event.position().x()), int(event.position().y())
            try:
                self.context.MoveTo(x, y, self.view, True)
                is_manip = (self._manipulator.HasActiveMode()
                           and self.context.DetectedInteractive() == self._manipulator)
            except Exception:
                is_manip = False
            if is_manip:
                try:
                    self._manipulator.StartTransform(x, y, self.view)
                    self._manip_dragging = True
                    self._manip_start_trsfs = {
                        id(ais): ais.LocalTransformation()
                        for ais in self._manip_leaf_shapes
                    }
                    return  # do NOT forward to _vc -- gizmo owns this drag
                except Exception as e:
                    print(f"[manipulator] StartTransform failed: {e}")
            self._manip_dragging = False

        pt = self._vec2i(event.position())
        self._vc.UpdateMouseButtons(pt, self._qt_buttons_to_occt(event.buttons()), 0, False)
        self._flush()

    def mouseMoveEvent(self, event):
        if self._press_pos is not None:
            dx = event.position().x() - self._press_pos.x()
            dy = event.position().y() - self._press_pos.y()
            self._drag_distance = (dx**2 + dy**2) ** 0.5

        if self._manip_dragging and self._manipulator is not None:
            x, y = int(event.position().x()), int(event.position().y())
            try:
                self._manipulator.Transform(x, y, self.view)

                # The gizmo only moves the ONE shape it's Attach()-ed
                # to. Work out how far that shape moved since drag
                # start and apply the SAME delta to every other leaf
                # shape in the sub-assembly, so the whole thing moves
                # live instead of just one part of it.
                target_obj = self._manipulator.Object()
                delta_trsf = None
                if target_obj is not None and self._manip_start_trsfs:
                    start_target = self._manip_start_trsfs.get(id(target_obj))
                    if start_target is not None:
                        new_target = target_obj.LocalTransformation()
                        delta_trsf = new_target.Multiplied(start_target.Inverted())
                        for ais in self._manip_leaf_shapes:
                            if ais is target_obj:
                                continue
                            start = self._manip_start_trsfs.get(id(ais))
                            if start is None:
                                continue
                            ais.SetLocalTransformation(delta_trsf.Multiplied(start))
                            self.context.Redisplay(ais, False)

                if delta_trsf is not None and self._manip_move_callback:
                    try:
                        self._manip_move_callback(delta_trsf)
                    except Exception as e:
                        print(f"[manipulator] move_callback failed: {e}")

                self.context.UpdateCurrentViewer()
                self.update()
                return  # suppress orbit/pan while dragging the gizmo
            except Exception as e:
                print(f"[manipulator] Transform failed: {e}")
                self._manip_dragging = False

        pt = self._vec2i(event.position())
        self._vc.UpdateMousePosition(pt, self._qt_buttons_to_occt(event.buttons()), 0, False)
        self._flush()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._manip_dragging and self._manipulator is not None):
            final_delta = None
            try:
                target_obj = self._manipulator.Object()
                if target_obj is not None:
                    start_target = self._manip_start_trsfs.get(id(target_obj))
                    if start_target is not None:
                        final_delta = target_obj.LocalTransformation().Multiplied(
                            start_target.Inverted())
                self._manipulator.StopTransform()
                # CRITICAL (per Basicad's own comment, confirmed the
                # same concern applies here): deactivate the current
                # mode so HasActiveMode() returns False once the cursor
                # moves away -- without this, HasActiveMode() stays
                # True and every subsequent LMB click gets intercepted
                # as a manipulator drag, locking out rotation entirely.
                self._manipulator.DeactivateCurrentMode()
            except Exception as e:
                print(f"[manipulator] StopTransform/Deactivate failed: {e}")
            self._manip_dragging = False
            if final_delta is not None and self._manip_done_callback:
                try:
                    self._manip_done_callback(final_delta)
                except Exception as e:
                    print(f"[manipulator] done_callback failed: {e}")
            self._press_pos = None
            self._drag_distance = 0.0
            self.update()
            return  # suppress the normal LMB click/selection handling

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
