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

    def add_snap_pt_to_xyPtStack(self, args):
        """ENGINE INPUT (Session 62, sketch engine step 3): convert
        the click's pixel coords (rides callbacks as the 3rd arg) to
        workplane UV via screen_to_uv, snap through find_snap with
        the same tolerance the hover marker uses -- so the click
        lands EXACTLY where the marker showed -- and push the point.
        NO CATCH -> NO POINT: a click lands only where the engine
        catches (the hover marker is the permission indicator); a
        free-space click is rejected with a status hint. Returns True
        when the engine had jurisdiction (point pushed OR click
        deliberately rejected); False only when the engine could not
        operate (no coords / no wp / bridge failure), letting the
        caller fall back to the legacy vertex path.
        """
        click_xy = args[1] if len(args) > 1 else None
        if click_xy is None or click_xy[0] is None:
            return False
        wp = self.win.activeWp
        if wp is None:
            return False
        try:
            from snap_engine import (screen_to_uv, find_snap,
                                     SNAP_PIXELS)
            view = self.win.canvas.view
            uv = screen_to_uv(view, click_xy[0], click_xy[1], wp.gpPlane)
            if uv is None:
                return False
            try:
                tol = abs(view.Convert(SNAP_PIXELS))
            except Exception:
                tol = 1.0
            from snap_engine import current_snap_mode
            snap = find_snap(wp, uv, tol, current_snap_mode())
            if snap is None:
                # NO CATCH -> NO POINT (Session 62, Doug's design
                # principle -- the drafter's #6-pencil layout method:
                # construction lines ARE the input space; a free-space
                # click near-missing an intersection would silently
                # place a slightly-wrong point, the exact imprecision
                # the layout method exists to prevent). The hover
                # marker is the permission indicator: no marker, no
                # input.
                self.win.statusBar().showMessage(
                    "No catch -- intersections/endpoints catch "
                    "(hold Ctrl+Shift for centers & midpoints).", 3000)
                return True  # handled: engine had jurisdiction,
                # deliberately added no point (no legacy fallback)
            pt = snap[1]
            self.win.xyPtStack.append((pt[0], pt[1]))
            return True
        except Exception as e:
            if not getattr(self, "_snap_input_warned", False):
                print(f"[snap input] fell back to vertex picks: {e}")
                self._snap_input_warned = True
            return False

    def delAllConstr(self):
        """Delete ALL construction geometry on the active workplane
        (clines, ccircs, carcs, csegs). Session 63 -- also lets the
        auto-fit border's SHRINK behavior be exercised."""
        wp = self.win.activeWp
        if wp is None:
            self.win.statusBar().showMessage(
                "No active workplane.", 3000)
            return
        n = (len(wp.clines) + len(wp.ccircs) + len(wp.carcs)
             + len(wp.csegs))
        wp.clines.clear()
        wp.ccircs.clear()
        wp.carcs.clear()
        wp.csegs.clear()
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            f"{n} construction element(s) deleted.", 4000)

    def delAllGeom(self):
        """Delete ALL profile geometry on the active workplane."""
        wp = self.win.activeWp
        if wp is None:
            self.win.statusBar().showMessage(
                "No active workplane.", 3000)
            return
        n = len(wp.edgeList)
        wp.edgeList.clear()
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            f"{n} geometry element(s) deleted.", 4000)

    # --- PROJECT EDGES (Session 63, Doug's post-2.0 priority #1:
    # 'I need that to show where the mounting holes in my plate will
    # go'). Two tools: project ALL edges of a picked FACE, or project
    # a single picked EDGE. Linear edges -> finite csegs; circular
    # edges whose axis is parallel to the wp normal (holes seen
    # square-on) -> construction CIRCLES at the projected center.
    # Oblique circles (ellipses) and other curve types are skipped
    # with a count in the status bar -- honest v1 scope. Both tools
    # chain (pick face after face); middle-click ends. ---

    def _project_edge_onto_wp(self, wp, edge):
        """Project one TopoDS edge onto the active wp. Returns
        'cseg', 'ccirc', or None (skipped)."""
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_CurveType
        from snap_engine import _elslib
        from workplane import cr_from_3p as wpm_cr3p
        import math as _m
        try:
            crv = BRepAdaptor_Curve(edge)
            ctype = crv.GetType()
            if ctype == GeomAbs_CurveType.GeomAbs_Line:
                p1 = crv.Value(crv.FirstParameter())
                p2 = crv.Value(crv.LastParameter())
                u1, v1 = _elslib("Parameters")(wp.gpPlane, p1)
                u2, v2 = _elslib("Parameters")(wp.gpPlane, p2)
                if abs(u2 - u1) < 1.0e-9 and abs(v2 - v1) < 1.0e-9:
                    return None  # edge perpendicular to wp: projects
                    # to a point
                wp.cseg((u1, v1), (u2, v2))
                return 'cseg'
            if ctype == GeomAbs_CurveType.GeomAbs_Circle:
                c = crv.Circle()
                cdir = c.Axis().Direction()
                ndir = wp.gpPlane.Axis().Direction()
                dot = (cdir.X() * ndir.X() + cdir.Y() * ndir.Y()
                       + cdir.Z() * ndir.Z())
                if abs(dot) < 0.9999:
                    print(f"[proj]   skipped circle: oblique "
                          f"(|dot|={abs(dot):.4f})")
                    return None
                u, v = _elslib("Parameters")(wp.gpPlane, c.Location())
                span = abs(crv.LastParameter() - crv.FirstParameter())
                if span >= 2.0 * _m.pi - 1.0e-3:
                    wp.circle((u, v), c.Radius(), constr=True)
                    return 'ccirc'
                # PARTIAL arc (Session 63, Doug: a full c-circle from
                # a projected fillet could be obscenely large) ->
                # construction ARC, angles measured in UV about the
                # projected center from sampled points.
                a0, a1 = self._arc_angles_from_samples(wp, crv, (u, v))
                wp.carc((u, v), c.Radius(), a0, a1)
                return 'carc'
            # Fall-through (Session 63, Doug's plate): hole arcs can
            # arrive as BSPLINES -- some authoring systems encode arcs
            # that way -- so type-checking for Circle was too literal.
            # SAMPLE-AND-RECOGNIZE: project sample points and let the
            # geometry declare itself -- circle fit (Doug's own
            # cr_from_3p) -> c-circle; straight fit -> cseg; neither
            # -> honest skip with reason.
            f0, f1 = crv.FirstParameter(), crv.LastParameter()
            n_s = 9
            uvs = []
            for i in range(n_s):
                p = crv.Value(f0 + (f1 - f0) * i / (n_s - 1))
                uvs.append(_elslib("Parameters")(wp.gpPlane, p))
            span = max(abs(uvs[-1][0] - uvs[0][0]),
                       abs(uvs[-1][1] - uvs[0][1]),
                       1.0e-9)
            # straight? max deviation of samples from the end-chord
            import math as _m
            x1, y1 = uvs[0]
            x2, y2 = uvs[-1]
            chord = _m.hypot(x2 - x1, y2 - y1)
            if chord > 1.0e-6:
                devmax = 0.0
                for (u, v) in uvs[1:-1]:
                    devmax = max(devmax, abs((x2 - x1) * (y1 - v)
                                             - (x1 - u) * (y2 - y1))
                                 / chord)
                if devmax < max(1.0e-6, chord * 1.0e-4):
                    wp.cseg(uvs[0], uvs[-1])
                    return 'cseg'
            # circular? fit through 3 spread samples, verify all
            try:
                ctr, rad = wpm_cr3p(uvs[0], uvs[n_s // 3],
                                    uvs[(2 * n_s) // 3])
                ok = all(abs(_m.hypot(u - ctr[0], v - ctr[1]) - rad)
                         < max(1.0e-6, rad * 1.0e-4)
                         for (u, v) in uvs)
                if ok and rad > 1.0e-6:
                    a0, a1, span = self._uv_arc_span(uvs, ctr)
                    if span >= 2.0 * _m.pi - 5.0e-2:
                        # full circle -- dedupe (0.1um apart is the
                        # same hole)
                        for (pc, r) in list(wp.ccircs):
                            if (abs(pc[0] - ctr[0]) < 1.0e-4
                                    and abs(pc[1] - ctr[1]) < 1.0e-4
                                    and abs(r - rad) < 1.0e-4):
                                return 'ccirc'
                        wp.circle((round(ctr[0], 9), round(ctr[1], 9)),
                                  round(rad, 9), constr=True)
                        return 'ccirc'
                    wp.carc((round(ctr[0], 9), round(ctr[1], 9)),
                            round(rad, 9), a0, a1)
                    return 'carc'
            except Exception:
                pass
            print(f"[proj]   skipped edge: unrecognized curve "
                  f"(type {ctype})")
        except Exception as pe:
            print(f"[proj]   edge projection raised: {pe}")
        return None

    def _uv_arc_span(self, uvs, ctr):
        """Angles (a0, a1 stored CCW) and span of an arc from its
        sampled UV points about center ctr. Samples run monotonically
        along the edge, so unwrapped angles are monotone."""
        import math as _m
        thetas = []
        prev = None
        for (u, v) in uvs:
            t = _m.atan2(v - ctr[1], u - ctr[0])
            if prev is not None:
                while t - prev > _m.pi:
                    t -= 2.0 * _m.pi
                while prev - t > _m.pi:
                    t += 2.0 * _m.pi
            thetas.append(t)
            prev = t
        t0, t1 = thetas[0], thetas[-1]
        span = abs(t1 - t0)
        if t1 < t0:
            t0, t1 = t1, t0  # store CCW
        two_pi = 2.0 * _m.pi
        t0n = t0 % two_pi
        return t0n, t0n + (t1 - t0), span

    def _arc_angles_from_samples(self, wp, crv, ctr):
        """Angles for a native circular edge: sample it, project to
        UV, measure about the projected center."""
        from snap_engine import _elslib
        f0, f1 = crv.FirstParameter(), crv.LastParameter()
        uvs = []
        for i in range(9):
            p = crv.Value(f0 + (f1 - f0) * i / 8.0)
            uvs.append(_elslib("Parameters")(wp.gpPlane, p))
        a0, a1, _span = self._uv_arc_span(uvs, ctr)
        return a0, a1

    def _coalesce_carcs(self, wp):
        """After projecting a face: carcs sharing center+radius whose
        spans sum to a full circle (a hole arriving as two seam arcs)
        merge into ONE clean c-circle."""
        import math as _m
        groups = {}
        for arc in wp.carcs:
            key = (round(arc[0][0], 4), round(arc[0][1], 4),
                   round(arc[1], 4))
            groups.setdefault(key, []).append(arc)
        for key, arcs in groups.items():
            total = sum(a[3] - a[2] for a in arcs)
            if total >= 2.0 * _m.pi - 5.0e-2:
                for a in arcs:
                    wp.carcs.remove(a)
                wp.circle((key[0], key[1]), key[2], constr=True)

    def _project_shape_edges(self, wp, shape):
        """Project every edge of shape (a face). Returns
        (n_projected, n_skipped)."""
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_ShapeEnum
        n_proj = 0
        n_skip = 0
        seen = []
        from OCP.TopoDS import TopoDS
        exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_EDGE)
        while exp.More():
            # Current() returns generic TopoDS_Shape; BRepAdaptor_Curve
            # demands a downcast TopoDS_Edge (Doug's diagnostic run
            # caught the exact pybind error). Same idiom as Face_s
            # elsewhere in the codebase.
            edge = TopoDS.Edge_s(exp.Current())
            if not any(edge.IsSame(e) for e in seen):
                seen.append(edge)
                if self._project_edge_onto_wp(wp, edge) is not None:
                    n_proj += 1
                else:
                    n_skip += 1
            exp.Next()
        return n_proj, n_skip

    def projectFaceEdges(self):
        """Project all edges of a picked face onto the active wp."""
        if self.win.activeWp is None:
            self.win.statusBar().showMessage(
                "No active workplane -- activate one first.", 4000)
            return
        self.win.registerCallback(self.projectFaceEdgesC)
        self.display.SetSelectionModeFace()
        self.win.statusBar().showMessage(
            "Pick a face to project its edges onto the active "
            "workplane (middle-click to end).")

    def projectFaceEdgesC(self, shapeList, *args):
        wp = self.win.activeWp
        if wp is None:
            return
        for shape in shapeList:
            if shape is None:
                continue
            n_proj, n_skip = self._project_shape_edges(wp, shape)
            self._coalesce_carcs(wp)
            print(f"[proj] {n_proj} projected, {n_skip} skipped; "
                  f"wp: {len(wp.csegs)} cseg(s), "
                  f"{len(wp.ccircs)} ccirc(s), "
                  f"{len(wp.carcs)} carc(s)")
            msg = (f"{n_proj} edge(s) projected"
                   + (f", {n_skip} skipped (oblique/unsupported)"
                      if n_skip else "")
                   + ". Pick another face (middle-click to end).")
            self.win.statusBar().showMessage(msg)
        self.win.draw_wp(self.win.activeWpUID)

    def projectEdge(self):
        """Project a single picked edge onto the active wp."""
        if self.win.activeWp is None:
            self.win.statusBar().showMessage(
                "No active workplane -- activate one first.", 4000)
            return
        self.win.registerCallback(self.projectEdgeC)
        self.display.SetSelectionModeEdge()
        self.win.statusBar().showMessage(
            "Pick an edge to project onto the active workplane "
            "(middle-click to end).")

    def projectEdgeC(self, shapeList, *args):
        wp = self.win.activeWp
        if wp is None:
            return
        for shape in shapeList:
            if shape is None:
                continue
            try:
                from OCP.TopoDS import TopoDS
                edge = TopoDS.Edge_s(shape)
            except Exception:
                self.win.statusBar().showMessage(
                    "That pick wasn't an edge -- try again.", 3000)
                continue
            kind = self._project_edge_onto_wp(wp, edge)
            if kind is not None:
                self.win.statusBar().showMessage(
                    f"Edge projected ({kind}). Pick another edge "
                    "(middle-click to end).")
            else:
                self.win.statusBar().showMessage(
                    "Edge skipped (oblique circle or unsupported "
                    "type). Pick another edge.", 4000)
        self.win.draw_wp(self.win.activeWpUID)

    def gesture_uv_from_args(self, args):
        """GESTURE INPUT (Session 62, the second input class): return
        the click's RAW workplane UV, deliberately WITHOUT snapping
        and without rejection -- for clicks that CHOOSE among
        discrete alternatives rather than define coordinates: which
        SIDE for a parallel cline (Doug's canonical example), which
        direction, which of two intersections. The click means 'this
        half-plane', not 'this exact spot' -- precision is irrelevant
        by construction, so catch-only does not apply. Returns
        (u, v) or None when unavailable (no coords / no wp / bridge
        failure). Tools consuming gestures use this; tools consuming
        POINTS use add_snap_pt_to_xyPtStack.
        """
        click_xy = args[1] if len(args) > 1 else None
        if click_xy is None or click_xy[0] is None:
            return None
        wp = self.win.activeWp
        if wp is None:
            return None
        try:
            from snap_engine import screen_to_uv
            return screen_to_uv(self.win.canvas.view,
                                click_xy[0], click_xy[1], wp.gpPlane)
        except Exception:
            return None

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
        if not self.add_snap_pt_to_xyPtStack(args):
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
        if not self.add_snap_pt_to_xyPtStack(args):
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
        if not self.add_snap_pt_to_xyPtStack(args):
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
        if not self.add_snap_pt_to_xyPtStack(args):
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
        if not self.add_snap_pt_to_xyPtStack(args):
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
        if not self.add_snap_pt_to_xyPtStack(args):
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
        if not self.add_snap_pt_to_xyPtStack(args):
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

    def cc3p(self):
        """Construction circle through 3 picked points (Session 63,
        toolbar layout). Doug's own cr_from_3p does the math; the
        preview shows the circle through the first two picks and the
        live cursor."""
        self.win.registerCallback(self.cc3pC)
        self.display.SetSelectionModeVertex()
        self.win.xyPtStack = []
        self._preview_start(self.cc3pC, self._cc3p_preview_builder)
        self.win.statusBar().showMessage(
            "Pick 3 points on the construction circle.")

    def cc3pC(self, shapeList, *args):
        n_before = len(self.win.xyPtStack)
        if not self.add_snap_pt_to_xyPtStack(args):
            self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        n = len(self.win.xyPtStack)
        if n == n_before:
            return
        if n < 3:
            self.win.statusBar().showMessage(
                f"Point {n} set. Pick point {n + 1}.")
            return
        p3 = self.win.xyPtStack.pop()
        p2 = self.win.xyPtStack.pop()
        p1 = self.win.xyPtStack.pop()
        try:
            from workplane import cr_from_3p
            ctr, rad = cr_from_3p(p1, p2, p3)
        except Exception:
            self.win.statusBar().showMessage(
                "Those 3 points are collinear -- no circle. "
                "Start again.", 4000)
            self.win.xyPtStack = []
            return
        wp = self.win.activeWp
        wp.circle((ctr[0], ctr[1]), rad, constr=True)
        self.win.xyPtStack = []
        self._preview_stop()
        self._preview_start(self.cc3pC, self._cc3p_preview_builder)
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Circle created. Pick 3 points for the next "
            "(middle-click to end).")

    def _cc3p_preview_builder(self, wp, uv):
        if len(self.win.xyPtStack) != 2:
            return None
        try:
            from workplane import cr_from_3p
            p1, p2 = self.win.xyPtStack[0], self.win.xyPtStack[1]
            ctr, rad = cr_from_3p(p1, p2, uv)
            if rad < 1.0e-6:
                return None
            from OCP.gp import gp_Circ, gp_Ax2
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
            center = self._uvpnt(wp, ctr[0], ctr[1])
            return BRepBuilderAPI_MakeEdge(
                gp_Circ(gp_Ax2(center, wp.wDir), rad)).Edge()
        except Exception:
            return None

    def poly(self):
        """POLYLINE (Session 63, toolbar layout): chained line
        segments -- each pick continues from the previous point;
        middle-click ends the chain."""
        self.win.registerCallback(self.polyC)
        self.display.SetSelectionModeVertex()
        self.win.xyPtStack = []
        self._poly_prev = None
        self._preview_start(self.polyC, self._poly_preview_builder)
        self.win.statusBar().showMessage(
            "Pick the start point of the polyline.")

    def polyC(self, shapeList, *args):
        n_before = len(self.win.xyPtStack)
        if not self.add_snap_pt_to_xyPtStack(args):
            self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if len(self.win.xyPtStack) == n_before:
            return
        pt = self.win.xyPtStack.pop()
        self.win.xyPtStack = []
        wp = self.win.activeWp
        if self._poly_prev is None:
            self._poly_prev = pt
            self.win.statusBar().showMessage(
                "Start set. Pick the next point "
                "(middle-click to end).")
            return
        wp.line(self._poly_prev, pt)
        self._poly_prev = pt
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Segment added. Pick the next point "
            "(middle-click to end).")

    def _poly_preview_builder(self, wp, uv):
        prev = getattr(self, "_poly_prev", None)
        if prev is None:
            return None
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        g1 = self._uvpnt(wp, prev[0], prev[1])
        g2 = self._uvpnt(wp, uv[0], uv[1])
        if g1.Distance(g2) < 1.0e-6:
            return None
        return BRepBuilderAPI_MakeEdge(g1, g2).Edge()

    def line(self):
        """Create a profile geometry line between two end points."""
        if len(self.win.xyPtStack) == 2:
            wp = self.win.activeWp
            pnt2 = self.win.xyPtStack.pop()
            pnt1 = self.win.xyPtStack.pop()
            wp.line(pnt1, pnt2)
            self.win.xyPtStack = []
            self._preview_stop()
            self._preview_start(self.lineC, self._line_preview_builder)
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.lineC)
            self._preview_start(self.lineC, self._line_preview_builder)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.lineEdit.setFocus()
            statusText = "Select 2 end points for line."
            self.win.statusBar().showMessage(statusText)

    def lineC(self, shapeList, *args):
        """callback (collector) for line"""
        if not self.add_snap_pt_to_xyPtStack(args):
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
            self._preview_stop()
            self._preview_start(self.rectC, self._rect_preview_builder)
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.rectC)
            self._preview_start(self.rectC, self._rect_preview_builder)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.lineEdit.setFocus()
            statusText = "Select 2 points for Rectangle."
            self.win.statusBar().showMessage(statusText)

    def rectC(self, shapeList, *args):
        """callback (collector) for rect"""
        if not self.add_snap_pt_to_xyPtStack(args):
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
            self._preview_stop()
            self._preview_start(self.circleC, self._circle_preview_builder)
            self.win.draw_wp(self.win.activeWpUID)
        elif self.win.xyPtStack and self.win.floatStack:
            pnt = self.win.xyPtStack.pop()
            rad = self.win.floatStack.pop() * self.win.unitscale
            wp.circle(pnt, rad, constr=False)
            self.win.xyPtStack = []
            self.win.floatStack = []
            self._preview_stop()
            self._preview_start(self.circleC, self._circle_preview_builder)
            self.win.draw_wp(self.win.activeWpUID)
        else:
            self.win.registerCallback(self.circleC)
            self._preview_start(self.circleC, self._circle_preview_builder)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self.win.floatStack = []
            self.win.lineEditStack = []
            self.win.lineEdit.setFocus()
            statusText = "Pick center and enter radius or pick center & 2nd point."
            self.win.statusBar().showMessage(statusText)

    def circleC(self, shapeList, *args):
        """callback (collector) for circle"""
        if not self.add_snap_pt_to_xyPtStack(args):
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
        if not self.add_snap_pt_to_xyPtStack(args):
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
            self._preview_stop()
            self._preview_start(self.arc3pC,
                                self._arc_preview_builder)
            self.win.draw_wp(self.win.activeWpUID)
            self.win.statusBar().showMessage(
                "Arc created. Pick 2 end points for the next arc "
                "(or End Operation).")
        else:
            self.win.registerCallback(self.arc3pC)
            self.display.SetSelectionModeVertex()
            self.win.xyPtStack = []
            self._preview_start(self.arc3pC,
                                self._arc_preview_builder)
            statusText = "Pick 2 end points, then a point on the arc."
            self.win.statusBar().showMessage(statusText)

    def arc3pC(self, shapeList, *args):
        """Callback (collector) for arc3p -- first tool on ENGINE
        INPUT (step 3): the click lands where the hover marker
        showed, snapped or free, pre-built vertices not required."""
        n_before = len(self.win.xyPtStack)
        if not self.add_snap_pt_to_xyPtStack(args):
            self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        if self.win.lineEditStack:
            self.processLineEdit()
        # Per-pick acknowledgement -- only when a point was actually
        # ADDED this click (a rejected no-catch click keeps its own
        # hint on the status bar instead of being overwritten)
        n = len(self.win.xyPtStack)
        if n == n_before:
            return
        if n == 1:
            self.win.statusBar().showMessage(
                "End point 1 set. Pick the second end point.")
        elif n == 2:
            self.win.statusBar().showMessage(
                "End point 2 set. Pick a point on the arc.")
        if n == 3:
            self.arc3p()

    # --- GENERIC live preview (Session 62): one mechanism, any tool ---
    # A tool starts a preview with _preview_start(owner_cb, builder);
    # builder(wp, uv) returns the preview TopoDS shape for the current
    # cursor (or None to keep the last one). Self-cleaning: if the
    # owner is no longer the registered callback, the first stray move
    # erases and unregisters. Grown from the arc's dedicated preview,
    # generalized when Doug asked for rectangle rubber lines -- now
    # arc, line, rect, and circle all ride the same few lines.

    def _preview_start(self, owner_cb, builder):
        self._prev_owner = owner_cb
        self._prev_builder = builder
        self._prev_ais = None
        try:
            self.win.canvas.register_move_callback(self._preview_move)
        except Exception:
            pass

    def _preview_stop(self):
        try:
            self.win.canvas.unregister_move_callback(self._preview_move)
        except Exception:
            pass
        ais = getattr(self, "_prev_ais", None)
        if ais is not None:
            try:
                self.display.Context.Erase(ais, True)
            except Exception:
                pass
            try:
                self.win.canvas._display.remove_never_pick(ais)
            except Exception:
                pass
        self._prev_ais = None
        self._prev_owner = None
        self._prev_builder = None

    def _preview_move(self, x, y):
        try:
            if self.win.registeredCallback != getattr(self, "_prev_owner",
                                                      None):
                self._preview_stop()
                return
            wp = self.win.activeWp
            if wp is None:
                return
            from snap_engine import screen_to_uv
            uv = screen_to_uv(self.win.canvas.view, x, y, wp.gpPlane)
            if uv is None:
                return
            shape = self._prev_builder(wp, uv)
            if shape is None:
                return
            context = self.display.Context
            if self._prev_ais is None:
                from OCP.AIS import AIS_Shape
                from OCP.Quantity import (Quantity_Color,
                                          Quantity_TypeOfColor)
                self._prev_ais = AIS_Shape(shape)
                context.Display(self._prev_ais, False)
                try:
                    self.win.canvas._display.add_never_pick(
                        self._prev_ais)
                except Exception:
                    pass
                try:
                    context.SetColor(
                        self._prev_ais,
                        Quantity_Color(1.0, 0.55, 0.0,
                                       Quantity_TypeOfColor.Quantity_TOC_RGB),
                        False)
                    context.Deactivate(self._prev_ais)  # never pickable
                except Exception:
                    pass
            else:
                self._prev_ais.SetShape(shape)
                context.Redisplay(self._prev_ais, False)
            context.UpdateCurrentViewer()
        except Exception as e:
            if not getattr(self, "_prev_warned", False):
                print(f"[preview] disabled after error: {e}")
                self._prev_warned = True
            self._preview_stop()

    # --- per-tool preview builders ---

    def _uvpnt(self, wp, u, v):
        from OCP.gp import gp_Pnt
        return gp_Pnt(u, v, 0).Transformed(wp.Trsf)

    def _arc_preview_builder(self, wp, uv):
        n = len(self.win.xyPtStack)
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        if n == 1:
            p1 = self.win.xyPtStack[0]
            g1 = self._uvpnt(wp, p1[0], p1[1])
            g2 = self._uvpnt(wp, uv[0], uv[1])
            if g1.Distance(g2) < 1.0e-6:
                return None
            return BRepBuilderAPI_MakeEdge(g1, g2).Edge()
        if n == 2:
            from OCP.GC import GC_MakeArcOfCircle
            e1, e2 = self.win.xyPtStack[0], self.win.xyPtStack[1]
            g1 = self._uvpnt(wp, e1[0], e1[1])
            g3 = self._uvpnt(wp, e2[0], e2[1])
            g2 = self._uvpnt(wp, uv[0], uv[1])
            maker = GC_MakeArcOfCircle(g1, g2, g3)
            if not maker.IsDone():
                return None
            return BRepBuilderAPI_MakeEdge(maker.Value()).Edge()
        return None

    def _line_preview_builder(self, wp, uv):
        if len(self.win.xyPtStack) != 1:
            return None
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        p1 = self.win.xyPtStack[0]
        g1 = self._uvpnt(wp, p1[0], p1[1])
        g2 = self._uvpnt(wp, uv[0], uv[1])
        if g1.Distance(g2) < 1.0e-6:
            return None
        return BRepBuilderAPI_MakeEdge(g1, g2).Edge()

    def _rect_preview_builder(self, wp, uv):
        if len(self.win.xyPtStack) != 1:
            return None
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
        p1 = self.win.xyPtStack[0]
        u1, v1 = p1[0], p1[1]
        u2, v2 = uv[0], uv[1]
        if abs(u2 - u1) < 1.0e-6 or abs(v2 - v1) < 1.0e-6:
            return None  # degenerate rectangle -- keep last preview
        poly = BRepBuilderAPI_MakePolygon()
        for cu, cv in ((u1, v1), (u2, v1), (u2, v2), (u1, v2)):
            poly.Add(self._uvpnt(wp, cu, cv))
        poly.Close()
        return poly.Wire()

    def _circle_preview_builder(self, wp, uv):
        if len(self.win.xyPtStack) != 1:
            return None
        from OCP.gp import gp_Circ, gp_Ax2
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        pc = self.win.xyPtStack[0]
        r = ((uv[0] - pc[0]) ** 2 + (uv[1] - pc[1]) ** 2) ** 0.5
        if r < 1.0e-6:
            return None
        center = self._uvpnt(wp, pc[0], pc[1])
        circ = gp_Circ(gp_Ax2(center, wp.wDir), r)
        return BRepBuilderAPI_MakeEdge(circ).Edge()

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
