#!/usr/bin/env python
#
# Copyright 2020 Doug Blanding (dblanding@gmail.com)
#
# This file is part of kodacad2.
# Licensed under the GNU General Public License v3 -- see LICENSE.
#


from OCP.BRep import BRep_Tool
from OCP.TopoDS import TopoDS, TopoDS_Vertex


class M2D:
    """Methods for creating and drawing elements on 2D workplanes"""

    def __init__(self, win, display):
        self.win = win
        self.display = display

    #############################################
    #
    # Create 2d Construction Line functions
    #
    #############################################

    def add_vertex_to_xyPtStack(self, shapeList):
        """Helper function to convert vertex to gp_Pnt and put on ptStack.

        Accepts TopoDS_Vertex or any TopoDS_Shape that can be cast to a vertex
        (e.g. the snap point markers returned by context.SelectedShape()).
        """
        wp = self.win.activeWp
        for shape in shapeList:
            try:
                # Try to get a vertex -- works for both TopoDS_Vertex and
                # TopoDS_Shape wrapping a vertex (from context.SelectedShape)
                if not isinstance(shape, TopoDS_Vertex):
                    shape = TopoDS.Vertex_s(shape)
                vrtx = TopoDS.Vertex_s(shape)
                pnt = BRep_Tool.Pnt_s(vrtx)  # convert vertex to type <gp_Pnt>
                trsf = wp.Trsf.Inverted()  # New transform. Don't invert wp.Trsf
                pnt.Transform(trsf)
                pt2d = (pnt.X(), pnt.Y())  # 2d point
                self.win.xyPtStack.append(pt2d)
            except Exception as e:
                print(f"(Unwanted) shape type: {type(shape)}: {e}")

    def processLineEdit(self):
        """pop value from lineEditStack and place on floatStack or ptStack."""

        text = self.win.lineEditStack.pop()
        if "," in text:
            try:
                xstr, ystr = text.split(",")
                p = (float(xstr) * self.win.unitscale,
                     float(ystr) * self.win.unitscale)
                self.win.xyPtStack.append(p)
            except:
                print("Problem with processing line edit stack")
        else:
            try:
                self.win.floatStack.append(float(text))
            except ValueError as e:
                print(f"{e}")

    def clineH(self):
        """Horizontal construction line"""
        if self.win.xyPtStack:
            wp = self.win.activeWp
            p = self.win.xyPtStack.pop()
            self.win.xyPtStack = []
            wp.hcl(p)
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.clineHC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.clearLEStack()
            self.win.lineEdit.setFocus()
            statusText = "Select point or enter Y-value for horizontal cline."
            self.win.statusBar().showMessage(statusText)

    def clineHC(self, shapeList, *args):
        """Callback (collector) for clineH"""
        self.add_vertex_to_xyPtStack(shapeList)
        if self.win.lineEditStack:
            self.processLineEdit()
        if self.win.floatStack:
            y = self.win.floatStack.pop() * self.win.unitscale
            pnt = (0, y)
            self.win.xyPtStack.append(pnt)
        if self.win.xyPtStack:
            self.clineH()

    def clineV(self):
        """Vertical construction line"""
        if self.win.xyPtStack:
            wp = self.win.activeWp
            p = self.win.xyPtStack.pop()
            self.win.xyPtStack = []
            wp.vcl(p)
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.clineVC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.clearLEStack()
            self.win.lineEdit.setFocus()
            statusText = "Select point or enter X-value for vertcal cline."
            self.win.statusBar().showMessage(statusText)

    def clineVC(self, shapeList, *args):
        """Callback (collector) for clineV"""
        self.add_vertex_to_xyPtStack(shapeList)
        if self.win.lineEditStack:
            self.processLineEdit()
        if self.win.floatStack:
            x = self.win.floatStack.pop() * self.win.unitscale
            pnt = (x, 0)
            self.win.xyPtStack.append(pnt)
        if self.win.xyPtStack:
            self.clineV()

    def clineHV(self):
        """Horizontal + Vertical construction lines"""
        if self.win.xyPtStack:
            wp = self.win.activeWp
            p = self.win.xyPtStack.pop()
            self.win.xyPtStack = []
            wp.hvcl(p)
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.clineHVC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.clearLEStack()
            self.win.lineEdit.setFocus()
            statusText = "Select point or enter x,y coords for H+V cline."
            self.win.statusBar().showMessage(statusText)

    def clineHVC(self, shapeList, *args):
        """Callback (collector) for clineHV"""
        self.add_vertex_to_xyPtStack(shapeList)
        if self.win.lineEditStack:
            self.processLineEdit()
        if self.win.xyPtStack:
            self.clineHV()

    def cline2Pts(self):
        """Construction line through two points"""
        if len(self.win.xyPtStack) == 2:
            wp = self.win.activeWp
            p2 = self.win.xyPtStack.pop()
            p1 = self.win.xyPtStack.pop()
            wp.acl(p1, p2)
            self.win.xyPtStack = []
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.cline2PtsC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.clearLEStack()
            self.win.lineEdit.setFocus()
            statusText = "Select 2 points for Construction Line."
            self.win.statusBar().showMessage(statusText)

    def cline2PtsC(self, shapeList, *args):
        """Callback (collector) for cline2Pts"""
        self.add_vertex_to_xyPtStack(shapeList)
        if self.win.lineEditStack:
            self.processLineEdit()
        if len(self.win.xyPtStack) == 2:
            self.cline2Pts()

    def clineAng(self):
        """Construction line through a point and at an angle"""
        if self.win.xyPtStack and self.win.floatStack:
            wp = self.win.activeWp
            text = self.win.floatStack.pop()
            angle = float(text)
            pnt = self.win.xyPtStack.pop()
            wp.acl(pnt, ang=angle)
            self.win.xyPtStack = []
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.clineAngC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.lineEditStack = []
            self.win.lineEdit.setFocus()
            statusText = "Select point on WP (or enter x,y coords) then enter angle."
            self.win.statusBar().showMessage(statusText)

    def clineAngC(self, shapeList, *args):
        """Callback (collector) for clineAng"""
        self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if self.win.lineEditStack:
            self.processLineEdit()
        if self.win.xyPtStack and self.win.floatStack:
            self.clineAng()

    def clineRefAng(self):
        pass

    def clineAngBisec(self):
        pass

    def clineLinBisec(self):
        """Linear bisector between two points"""
        if len(self.win.xyPtStack) == 2:
            wp = self.win.activeWp
            pnt2 = self.win.xyPtStack.pop()
            pnt1 = self.win.xyPtStack.pop()
            wp.lbcl(pnt1, pnt2)
            self.win.xyPtStack = []
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.clineLinBisecC)
            self.display.SetSelectionModeVertex()

    def clineLinBisecC(self, shapeList, *args):
        """Callback (collector) for clineLinBisec"""
        self.add_vertex_to_xyPtStack(shapeList)
        if len(self.win.xyPtStack) == 2:
            self.clineLinBisec()

    def clinePara(self):
        pass

    def clinePerp(self):
        pass

    def clineTan1(self):
        pass

    def clineTan2(self):
        pass

    def ccirc(self):
        """Create a c-circle from center & radius or center & Pnt on circle"""
        wp = self.win.activeWp
        if len(self.win.xyPtStack) == 2:
            p2 = self.win.xyPtStack.pop()
            p1 = self.win.xyPtStack.pop()
            rad = wp.p2p_dist(p1, p2)
            wp.circle(p1, rad, constr=True)
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.draw_wp(self.win.activeWpUID)
        elif self.win.xyPtStack and self.win.floatStack:
            pnt = self.win.xyPtStack.pop()
            rad = self.win.floatStack.pop() * self.win.unitscale
            wp.circle(pnt, rad, constr=True)
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.ccircC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.lineEditStack = []
            self.win.lineEdit.setFocus()
            statusText = "Pick center of construction circle and enter radius."
            self.win.statusBar().showMessage(statusText)

    def ccircC(self, shapeList, *args):
        """callback (collector) for ccirc"""
        self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if self.win.lineEditStack:
            self.processLineEdit()
        if len(self.win.xyPtStack) == 2:
            self.ccirc()
        if self.win.xyPtStack and self.win.floatStack:
            self.ccirc()

    #############################################
    #
    # Create 2d Edge Profile functions
    #
    #############################################

    def line(self):
        """Create a profile geometry line between two end points."""
        if len(self.win.xyPtStack) == 2:
            wp = self.win.activeWp
            pnt2 = self.win.xyPtStack.pop()
            pnt1 = self.win.xyPtStack.pop()
            wp.line(pnt1, pnt2)
            self.win.xyPtStack = []
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.lineC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.lineEdit.setFocus()
            statusText = "Select 2 end points for line."
            self.win.statusBar().showMessage(statusText)

    def lineC(self, shapeList, *args):
        """callback (collector) for line"""
        self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if self.win.lineEditStack:
            self.processLineEdit()
        if len(self.win.xyPtStack) == 2:
            self.line()

    def rect(self):
        """Create a profile geometry rectangle from two diagonally opposite corners."""
        if len(self.win.xyPtStack) == 2:
            wp = self.win.activeWp
            pnt2 = self.win.xyPtStack.pop()
            pnt1 = self.win.xyPtStack.pop()
            wp.rect(pnt1, pnt2)
            self.win.xyPtStack = []
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.rectC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.lineEdit.setFocus()
            statusText = "Select 2 points for Rectangle."
            self.win.statusBar().showMessage(statusText)

    def rectC(self, shapeList, *args):
        """callback (collector) for rect"""
        self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if self.win.lineEditStack:
            self.processLineEdit()
        if len(self.win.xyPtStack) == 2:
            self.rect()

    def circle(self):
        """Create a geometry circle from cntr & rad or cntr & pnt on circle."""
        wp = self.win.activeWp
        if len(self.win.xyPtStack) == 2:
            p2 = self.win.xyPtStack.pop()
            p1 = self.win.xyPtStack.pop()
            rad = wp.p2p_dist(p1, p2)
            wp.circle(p1, rad, constr=False)
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.draw_wp(self.win.activeWpUID)
        elif self.win.xyPtStack and self.win.floatStack:
            pnt = self.win.xyPtStack.pop()
            rad = self.win.floatStack.pop() * self.win.unitscale
            wp.circle(pnt, rad, constr=False)
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.circleC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.lineEditStack = []
            self.win.lineEdit.setFocus()
            statusText = "Pick center and enter radius or pick center & 2nd point."
            self.win.statusBar().showMessage(statusText)

    def circleC(self, shapeList, *args):
        """callback (collector) for circle"""
        self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if self.win.lineEditStack:
            self.processLineEdit()
        if len(self.win.xyPtStack) == 2:
            self.circle()
        if self.win.xyPtStack and self.win.floatStack:
            self.circle()

    def arcc2p(self):
        """Create an arc from center pt, start pt and end pt."""
        wp = self.win.activeWp
        if len(self.win.xyPtStack) == 3:
            pe = self.win.xyPtStack.pop()
            ps = self.win.xyPtStack.pop()
            pc = self.win.xyPtStack.pop()
            wp.arcc2p(pc, ps, pe)
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.arcc2pC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            statusText = "Pick center of arc, then start then end point."
            self.win.statusBar().showMessage(statusText)

    def arcc2pC(self, shapeList, *args):
        """callback (collector) for arcc2p"""
        self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if self.win.lineEditStack:
            self.processLineEdit()
        if len(self.win.xyPtStack) == 3:
            self.arcc2p()

    def arc3p(self):
        """Create an arc: pick BOTH END POINTS first, then a point on
        the arc between them (Session 62, Doug's preferred Pyurcad
        order -- previously end / on-arc / end). This ordering is
        what makes the rubber band natural: after the first pick a
        rubber line follows the cursor; after the second, the ARC
        ITSELF follows, with the cursor as the live third point --
        driven by the step-1 screen_to_uv bridge."""
        wp = self.win.activeWp
        if len(self.win.xyPtStack) == 3:
            p_on = self.win.xyPtStack.pop()
            pe2 = self.win.xyPtStack.pop()
            pe1 = self.win.xyPtStack.pop()
            # GC_MakeArcOfCircle(P1, P2, P3) = arc P1 -> P3 THROUGH P2
            wp.arc3p(pe1, p_on, pe2)
            self.win.xyPtStack = []
            self.win.floatStack = []
            # Seamless restart (Session 62, Doug's suggestion): the
            # operation stays live -- reset the preview and re-prompt
            # so the next arc starts immediately. End Operation exits.
            self._arc_preview_stop()
            self._arc_preview_start()
            self.win.draw_wp(self.win.activeWpUID)
            self.win.statusBar().showMessage(
                "Arc created. Pick 2 end points for the next arc "
                "(or End Operation).")
        else:
            self.win.registerCallback(self.arc3pC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self._arc_preview_start()
            statusText = "Pick 2 end points, then a point on the arc."
            self.win.statusBar().showMessage(statusText)

    def arc3pC(self, shapeList, *args):
        """Callback (collector) for arc3p"""
        self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if self.win.lineEditStack:
            self.processLineEdit()
        # Per-pick acknowledgement (Session 62, Doug's suggestion --
        # reassuring for the first-time user)
        n = len(self.win.xyPtStack)
        if n == 1:
            self.win.statusBar().showMessage(
                "End point 1 set. Pick the second end point.")
        elif n == 2:
            self.win.statusBar().showMessage(
                "End point 2 set. Pick a point on the arc.")
        if n == 3:
            self.arc3p()

    # --- arc3p live preview (Session 62, sketch engine step 2) ---

    def _arc_preview_start(self):
        self._arc_prev_ais = None
        try:
            self.win.canvas.register_move_callback(self._arc_preview_move)
        except Exception:
            pass

    def _arc_preview_stop(self):
        try:
            self.win.canvas.unregister_move_callback(self._arc_preview_move)
        except Exception:
            pass
        ais = getattr(self, "_arc_prev_ais", None)
        if ais is not None:
            try:
                self.display.Context.Erase(ais, True)
            except Exception:
                pass
        self._arc_prev_ais = None

    def _arc_preview_move(self, x, y):
        """Rubber band for arc3p: 1 point picked -> line to cursor;
        2 points -> arc through the cursor. Self-cleaning: if the
        operation is no longer active (End Operation, tool switch),
        the first stray move erases the preview and unregisters."""
        try:
            if self.win.registeredCallback != self.arc3pC:
                self._arc_preview_stop()
                return
            wp = self.win.activeWp
            n = len(self.win.xyPtStack)
            if wp is None or n < 1 or n > 2:
                return
            from snap_engine import screen_to_uv
            uv = screen_to_uv(self.win.canvas.view, x, y, wp.gpPlane)
            if uv is None:
                return
            from OCP.gp import gp_Pnt
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
            if n == 1:
                p1 = self.win.xyPtStack[0]
                g1 = gp_Pnt(p1[0], p1[1], 0).Transformed(wp.Trsf)
                g2 = gp_Pnt(uv[0], uv[1], 0).Transformed(wp.Trsf)
                if g1.Distance(g2) < 1.0e-6:
                    return
                edge = BRepBuilderAPI_MakeEdge(g1, g2).Edge()
            else:
                from OCP.GC import GC_MakeArcOfCircle
                e1, e2 = self.win.xyPtStack[0], self.win.xyPtStack[1]
                g1 = gp_Pnt(e1[0], e1[1], 0).Transformed(wp.Trsf)
                g3 = gp_Pnt(e2[0], e2[1], 0).Transformed(wp.Trsf)
                g2 = gp_Pnt(uv[0], uv[1], 0).Transformed(wp.Trsf)
                maker = GC_MakeArcOfCircle(g1, g2, g3)
                if not maker.IsDone():
                    return  # collinear/degenerate -- keep last preview
                edge = BRepBuilderAPI_MakeEdge(maker.Value()).Edge()
            context = self.display.Context
            if self._arc_prev_ais is None:
                from OCP.AIS import AIS_Shape
                from OCP.Quantity import (Quantity_Color,
                                          Quantity_TypeOfColor)
                self._arc_prev_ais = AIS_Shape(edge)
                context.Display(self._arc_prev_ais, False)
                try:
                    context.SetColor(
                        self._arc_prev_ais,
                        Quantity_Color(1.0, 0.55, 0.0,
                                       Quantity_TypeOfColor.Quantity_TOC_RGB),
                        False)
                    context.Deactivate(self._arc_prev_ais)  # never pickable
                except Exception:
                    pass
            else:
                self._arc_prev_ais.SetShape(edge)
                context.Redisplay(self._arc_prev_ais, False)
            context.UpdateCurrentViewer()
        except Exception as e:
            if not getattr(self, "_arc_prev_warned", False):
                print(f"[arc preview] disabled after error: {e}")
                self._arc_prev_warned = True
            self._arc_preview_stop()

    def geom(self):
        pass

    #############################################
    #
    # 2D Delete functions
    #
    #############################################

    def delCl(self):
        """Delete selected 2d construction element.

        Todo: Get this working. Able to pre-select lines from the display
        as type <AIS_InteractiveObject> but haven't figured out how to get
        the type <AIS_Line> (or the cline or Geom_Line that was used to make
        it)."""
        self.win.registerCallback(self.delClC)
        statusText = "Select a construction element to delete."
        self.win.statusBar().showMessage(statusText)
        self.display = self.win.canvas._self.display.Context
        print(self.display.NbSelected())  # Use shift-select for multiple lines
        selected_line = self.display.SelectedInteractive()
        if selected_line:
            print(type(selected_line))  # <AIS_InteractiveObject>
            print(selected_line.GetOwner())  # <Standard_Transient>

    def delClC(self, shapeList, *args):
        """Callback (collector) for delCl"""
        print(shapeList)
        print(args)
        self.delCl()

    def delEl(self):
        """Delete selected geometry profile element."""
        wp = self.win.activeWp
        if self.win.shapeStack:
            while self.win.shapeStack:
                shape = self.win.shapeStack.pop()
                # Use IsSame() instead of Python 'in'/remove() -- TopoDS
                # shapes may be different Python objects but the same
                # underlying geometry (same class of bug already fixed
                # in kodacad.py's fillet()). Confirmed directly: the
                # pick worked, but 'shape in wp.edgeList' silently never
                # matched, so nothing was ever actually removed.
                matching = next((e for e in wp.edgeList if e.IsSame(shape)), None)
                if matching is not None:
                    wp.edgeList.remove(matching)
            self.win.redraw()
        else:
            self.win.registerCallback(self.delElC)
            self.display.SetSelectionModeEdge()
            self.win.xyPtStack = []
            statusText = "Select a geometry profile element to delete."
            self.win.statusBar().showMessage(statusText)

    def delElC(self, shapeList, *args):
        """Callback (collector) for delEl"""
        for shape in shapeList:
            self.win.shapeStack.append(shape)
        if self.win.shapeStack:
            self.delEl()
