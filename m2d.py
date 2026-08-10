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
        self.win.lineEdit.setFocus()
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
        self.win.lineEdit.setFocus()
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

    # Kodacad's rendering of Pyurcad's shift_key_advice -- appended
    # exactly where Pyurcad appended its version
    _ADVICE = " (Use Ctrl+Shift to select center of element)"

    # ---- H / V / H+V construction lines (pyurcad hcl/vcl/hvcl) ----

    def clineH(self):
        self.win.registerCallback(self.clineHC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._preview_start(self.clineHC, self._hcl_preview_builder,
                            style="constr")
        self.win.statusBar().showMessage(
            "Pick a pt or enter a value" + self._ADVICE)

    def _hcl_preview_builder(self, wp, uv):
        import workplane as wpm
        return self._cline_edge(wp, wpm.angled_cline(uv, 0))

    def clineHC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        p = self._take_pt(args)
        if p is None and self.win.floatStack:
            y = self.win.floatStack.pop() * self.win.unitscale
            p = (0.0, y)
        if p is None:
            return
        wp.cline_gen(wpm.angled_cline(p, 0))
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Pick a pt or enter a value" + self._ADVICE)

    def clineV(self):
        self.win.registerCallback(self.clineVC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._preview_start(self.clineVC, self._vcl_preview_builder,
                            style="constr")
        self.win.statusBar().showMessage(
            "Pick a pt or enter a value" + self._ADVICE)

    def _vcl_preview_builder(self, wp, uv):
        import workplane as wpm
        return self._cline_edge(wp, wpm.angled_cline(uv, 90))

    def clineVC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        p = self._take_pt(args)
        if p is None and self.win.floatStack:
            x = self.win.floatStack.pop() * self.win.unitscale
            p = (x, 0.0)
        if p is None:
            return
        wp.cline_gen(wpm.angled_cline(p, 90))
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Pick a pt or enter a value" + self._ADVICE)

    def clineHV(self):
        self.win.registerCallback(self.clineHVC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self.win.statusBar().showMessage(
            "Pick a pt or enter coords x,y" + self._ADVICE)

    def clineHVC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        # typed 'x,y' arrives as a point via _take_pt (Doug's
        # report: the coords went to xyPtStack and were ignored)
        p = self._take_pt(args)
        if p is None:
            return
        wp.cline_gen(wpm.angled_cline(p, 0))
        wp.cline_gen(wpm.angled_cline(p, 90))
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Pick a pt or enter coords x,y" + self._ADVICE)

    # ---- Construction line by 2 points (pyurcad cl2p) ----

    def cline2Pts(self):
        self.win.registerCallback(self.cline2PtsC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._preview_start(self.cline2PtsC,
                            self._cl2p_preview_builder, style="constr")
        self.win.statusBar().showMessage(
            "Pick 1st point or enter coords" + self._ADVICE)

    def _cl2p_preview_builder(self, wp, uv):
        if len(self.win.xyPtStack) != 1:
            return None
        import workplane as wpm
        p0 = self.win.xyPtStack[0]
        try:
            return self._cline_edge(
                wp, wpm.angled_cline(p0, wpm.p2p_angle(p0, uv)))
        except Exception:
            return None

    def cline2PtsC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        p = self._take_pt(args)
        if p is None:
            return
        self.win.xyPtStack.append(p)
        if len(self.win.xyPtStack) == 1:
            self.win.statusBar().showMessage(
                "Pick 2nd point or enter coords" + self._ADVICE)
            return
        p1 = self.win.xyPtStack.pop()
        p0 = self.win.xyPtStack.pop()
        wp.cline_gen(wpm.cnvrt_2pts_to_coef(p0, p1))
        self._preview_stop()
        self._preview_start(self.cline2PtsC,
                            self._cl2p_preview_builder, style="constr")
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Pick 1st point or enter coords" + self._ADVICE)

    # ---- Angled construction line (pyurcad acl) ----

    def clineAng(self):
        self.win.registerCallback(self.clineAngC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._preview_start(self.clineAngC,
                            self._cl2p_preview_builder, style="constr")
        self.win.statusBar().showMessage(
            "Pick a pt for angled construction line or enter coords"
            + self._ADVICE)

    def clineAngC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        p = self._take_pt(args)
        if p is not None:
            self.win.xyPtStack.append(p)
            if len(self.win.xyPtStack) == 1:
                self.win.statusBar().showMessage(
                    "Specify 2nd point or enter angle in degrees"
                    + self._ADVICE)
                return
            p1 = self.win.xyPtStack.pop()
            p0 = self.win.xyPtStack.pop()
            wp.cline_gen(wpm.cnvrt_2pts_to_coef(p0, p1))
            self._preview_stop()
            self._preview_start(self.clineAngC,
                                self._cl2p_preview_builder,
                                style="constr")
            self.win.draw_wp(self.win.activeWpUID)
            self.win.statusBar().showMessage(
                "Pick a pt for angled construction line or enter "
                "coords" + self._ADVICE)
            return
        if self.win.xyPtStack and self.win.floatStack:
            p0 = self.win.xyPtStack.pop()
            self.win.xyPtStack = []
            ang = self.win.floatStack.pop()
            wp.cline_gen(wpm.angled_cline(p0, ang))
            self._preview_stop()
            self._preview_start(self.clineAngC,
                                self._cl2p_preview_builder,
                                style="constr")
            self.win.draw_wp(self.win.activeWpUID)
            self.win.statusBar().showMessage(
                "Pick a pt for angled construction line or enter "
                "coords" + self._ADVICE)
            return

    # ---- Construction line by REF ANGLE (pyurcad clrefang --
    #      previously believed absent; Doug pointed the way) ----

    def clineRefAng(self):
        self.win.registerCallback(self.clineRefAngC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self.win.statusBar().showMessage(
            "Specify a pt for new construction line" + self._ADVICE)

    def clineRefAngC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        if self.win.lineEditStack:
            self.processLineEdit()
            if (self.win.floatStack
                    and len(self.win.xyPtStack) == 1):
                self.win.statusBar().showMessage(
                    "Pick first point on reference line"
                    + self._ADVICE)
                return
        n = len(self.win.xyPtStack)
        if n == 0:
            p = self._catch_pt(args)
            if p is None:
                return
            self.win.xyPtStack.append(p)
            self.win.statusBar().showMessage(
                "Enter offset angle in degrees")
            return
        if not self.win.floatStack:
            self.win.statusBar().showMessage(
                "Enter offset angle in degrees")
            return
        # reference-line points are DIRECTION picks
        p = self._direction_pt(args, wp)
        if p is None:
            return
        self.win.xyPtStack.append(p)
        n = len(self.win.xyPtStack)
        if n == 2:
            self.win.statusBar().showMessage(
                "Pick second point on reference line" + self._ADVICE)
            return
        p3 = self.win.xyPtStack.pop()
        p2 = self.win.xyPtStack.pop()
        p1 = self.win.xyPtStack.pop()
        baseangle = wpm.p2p_angle(p2, p3)
        angoffset = self.win.floatStack.pop()
        wp.cline_gen(wpm.angled_cline(p1, baseangle + angoffset))
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Specify a pt for new construction line" + self._ADVICE)

    # ---- Linear bisector (pyurcad lbcl) -- factor + rubber ----

    def clineLinBisec(self):
        self.win.registerCallback(self.clineLinBisecC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._preview_start(self.clineLinBisecC,
                            self._lbcl_preview_builder, style="constr")
        self.win.statusBar().showMessage(
            "Enter bisector factor (Default=.5) or specify first "
            "point" + self._ADVICE)

    def _lbcl_preview_builder(self, wp, uv):
        if len(self.win.xyPtStack) != 1:
            return None
        import workplane as wpm
        try:
            f = (self.win.floatStack[-1]
                 if self.win.floatStack else 0.5)
            p1 = self.win.xyPtStack[0]
            p0 = wpm.midpoint(p1, uv, f)
            baseline = wpm.cnvrt_2pts_to_coef(p1, uv)
            return self._cline_edge(wp, wpm.perp_line(baseline, p0))
        except Exception:
            return None

    def clineLinBisecC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        p = self._take_pt(args)
        if p is None and self.win.floatStack \
                and not self.win.xyPtStack:
            self.win.statusBar().showMessage(
                "Specify first point" + self._ADVICE)
            return
        if p is None:
            return
        self.win.xyPtStack.append(p)
        if len(self.win.xyPtStack) == 1:
            self.win.statusBar().showMessage(
                "Specify second point" + self._ADVICE)
            return
        f = self.win.floatStack[-1] if self.win.floatStack else 0.5
        p2 = self.win.xyPtStack.pop()
        p1 = self.win.xyPtStack.pop()
        p0 = wpm.midpoint(p1, p2, f)
        baseline = wpm.cnvrt_2pts_to_coef(p1, p2)
        wp.cline_gen(wpm.perp_line(baseline, p0))
        self._preview_stop()
        self._preview_start(self.clineLinBisecC,
                            self._lbcl_preview_builder, style="constr")
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Enter bisector factor (Default=.5) or specify first "
            "point" + self._ADVICE)

    # ================= PHASE-2 TOOLS (Session 63) =================
    # Ported from pyurcad.py with VERBATIM status messages (Doug's
    # requirement). Input classes per the design doc: entity picks
    # and side picks are GESTURES (raw uv resolves the entity/side);
    # points that define geometry are CATCHES (no catch, no point).
    # clineRefAng is RETIRED: no such tool exists in Pyurcad either
    # (icon only) -- pending Doug's verdict.

    def _nearest_straight(self, wp, uv, tol):
        """Nearest STRAIGHT element (cline, cseg, or geometry line)
        as (a, b, c) coefficients, or None."""
        import math as _m
        import workplane as wpm
        best = [None, None]

        def consider(coef, d):
            if d <= tol and (best[1] is None or d < best[1]):
                best[0] = coef
                best[1] = d

        for cl in wp.clines:
            a, b, c = cl
            den = _m.hypot(a, b)
            if den > 1.0e-12:
                consider(cl, abs(a * uv[0] + b * uv[1] + c) / den)
        segs = [(s[0], s[1]) for s in wp.csegs]
        try:
            from snap_engine import _geom_segments_uv
            segs += _geom_segments_uv(wp)
        except Exception:
            pass
        for (p1, p2) in segs:
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            l2 = dx * dx + dy * dy
            if l2 < 1.0e-18:
                continue
            t = ((uv[0] - p1[0]) * dx + (uv[1] - p1[1]) * dy) / l2
            t = max(0.0, min(1.0, t))
            d = _m.hypot(uv[0] - (p1[0] + t * dx),
                         uv[1] - (p1[1] + t * dy))
            try:
                consider(wpm.cnvrt_2pts_to_coef(p1, p2), d)
            except Exception:
                pass
        return best[0]

    def _nearest_circle_ent(self, wp, uv, tol):
        """Nearest CIRCLE element (ccirc, carc, geometry circle) as
        ((pc, r)), or None. Rim distance; carcs range-checked."""
        import math as _m
        best = [None, None]

        def consider(circ, d):
            if d <= tol and (best[1] is None or d < best[1]):
                best[0] = circ
                best[1] = d

        for (pc, r) in wp.ccircs:
            consider((pc, r),
                     abs(_m.hypot(uv[0] - pc[0], uv[1] - pc[1]) - r))
        try:
            from snap_engine import _on_arc
            for (pc, r, a0, a1) in wp.carcs:
                dc = _m.hypot(uv[0] - pc[0], uv[1] - pc[1])
                if dc < 1.0e-9:
                    continue
                onp = (pc[0] + (uv[0] - pc[0]) * r / dc,
                       pc[1] + (uv[1] - pc[1]) * r / dc)
                if _on_arc(onp, pc, a0, a1):
                    consider((pc, r), abs(dc - r))
        except Exception:
            pass
        try:
            from snap_engine import _geom_circles_uv
            for (pc, r) in _geom_circles_uv(wp):
                consider((pc, r),
                         abs(_m.hypot(uv[0] - pc[0],
                                      uv[1] - pc[1]) - r))
        except Exception:
            pass
        return best[0]

    def _take_pt(self, args):
        """Uniform point intake (Session 63, Doug's H+V report):
        typed 'x,y' coords land in xyPtStack via processLineEdit and
        are the SAME as a clicked catch. Also fills floatStack for
        single typed values -- callers check it when this returns
        None."""
        n0 = len(self.win.xyPtStack)
        if self.win.lineEditStack:
            self.processLineEdit()
        if len(self.win.xyPtStack) > n0:
            return self.win.xyPtStack.pop()
        return self._catch_pt(args)

    def _catch_pt(self, args):
        """A CATCH-class point from a click, or None (the no-catch
        hint is shown by the shared engine path)."""
        n0 = len(self.win.xyPtStack)
        self.add_snap_pt_to_xyPtStack(args)
        if len(self.win.xyPtStack) > n0:
            return self.win.xyPtStack.pop()
        return None

    def _direction_pt(self, args, wp):
        """A DIRECTION pick (Session 63, Doug's abcl walkthrough:
        'click on the base line'): raw gesture uv PROJECTED onto the
        nearest straight element -- clicking anywhere along a line
        yields an exact on-line point. No element nearby -> the raw
        uv (Pyurcad's free-direction behavior)."""
        import workplane as wpm
        uv = self.gesture_uv_from_args(args)
        if uv is None:
            return None
        hit = self._nearest_straight(wp, uv, self._snap_tol())
        if hit is not None:
            try:
                return wpm.proj_pt_on_line(hit, uv)
            except Exception:
                pass
        return uv

    def _cline_edge(self, wp, cline):
        """A displayable edge for a PROPOSED cline: clipped to the
        border like every real cline."""
        try:
            from mainwindow import _clip_line_to_rect
            bounds = getattr(wp, 'border_bounds', None)
            if bounds is None:
                return None
            seg = _clip_line_to_rect(cline, bounds)
            if seg is None:
                return None
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
            g1 = self._uvpnt(wp, seg[0][0], seg[0][1])
            g2 = self._uvpnt(wp, seg[1][0], seg[1][1])
            if g1.Distance(g2) < 1.0e-9:
                return None
            return BRepBuilderAPI_MakeEdge(g1, g2).Edge()
        except Exception:
            return None

    def _snap_tol(self):
        try:
            from snap_engine import SNAP_PIXELS
            return abs(self.win.canvas.view.Convert(SNAP_PIXELS))
        except Exception:
            return 1.0

    # ---- Parallel construction line (pyurcad parcl) ----

    def clinePara(self):
        self.win.registerCallback(self.clineParaC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._parcl_baseline = None
        self._preview_start(self.clineParaC,
                            self._parcl_preview_builder,
                            style="constr")
        self.win.statusBar().showMessage(
            "Pick a straight element or enter an offset distance")

    def _parcl_preview_builder(self, wp, uv):
        if self._parcl_baseline is None or self.win.floatStack:
            return None  # rubber only in through-point mode
        import workplane as wpm
        try:
            return self._cline_edge(
                wp, wpm.para_line(self._parcl_baseline, uv))
        except Exception:
            return None

    def clineParaC(self, shapeList, *args):
        import workplane as wpm
        if self.win.lineEditStack:
            self.processLineEdit()
        wp = self.win.activeWp
        if wp is None:
            return
        if self._parcl_baseline is None:
            uv = self.gesture_uv_from_args(args)
            if uv is not None:
                hit = self._nearest_straight(wp, uv, self._snap_tol())
                if hit is not None:
                    self._parcl_baseline = hit
                    if self.win.floatStack:
                        self.win.statusBar().showMessage(
                            "Pick on (+) side of line")
                    else:
                        self.win.statusBar().showMessage(
                            "Select point for new parallel line")
                    return
            if self.win.floatStack:
                self.win.statusBar().showMessage(
                    "Pick a straight element to be parallel to")
            return
        baseline = self._parcl_baseline
        if self.win.floatStack:  # mode 1: offset + SIDE GESTURE
            uv = self.gesture_uv_from_args(args)
            if uv is None:
                return
            d = self.win.floatStack[-1] * self.win.unitscale
            c1, c2 = wpm.para_lines(baseline, d)
            p1 = wpm.proj_pt_on_line(c1, uv)
            p2 = wpm.proj_pt_on_line(c2, uv)
            chosen = c1 if wpm.p2p_dist(p1, uv) < wpm.p2p_dist(p2, uv) \
                else c2
            wp.cline_gen(chosen)
            self._parcl_baseline = None
            self._preview_stop()
            self._preview_start(self.clineParaC,
                                self._parcl_preview_builder,
                                style="constr")
            self.win.draw_wp(self.win.activeWpUID)
            self.win.statusBar().showMessage(
                "Parallel cline created. Pick a straight element "
                "(same offset) or enter a new offset distance")
        else:  # mode 2: through a CATCH point
            p = self._catch_pt(args)
            if p is None:
                return
            wp.cline_gen(wpm.para_line(baseline, p))
            self._parcl_baseline = None
            self._preview_stop()
            self._preview_start(self.clineParaC,
                                self._parcl_preview_builder,
                                style="constr")
            self.win.draw_wp(self.win.activeWpUID)
            self.win.statusBar().showMessage(
                "Pick a straight element or enter an offset distance")

    # ---- Perpendicular construction line (pyurcad perpcl) ----

    def clinePerp(self):
        self.win.registerCallback(self.clinePerpC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._perp_baseline = None
        self._preview_start(self.clinePerpC,
                            self._perp_preview_builder,
                            style="constr")
        self.win.statusBar().showMessage(
            "Pick line to be perpendicular to")

    def _perp_preview_builder(self, wp, uv):
        if self._perp_baseline is None:
            return None
        import workplane as wpm
        try:
            return self._cline_edge(
                wp, wpm.perp_line(self._perp_baseline, uv))
        except Exception:
            return None

    def clinePerpC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        if self._perp_baseline is None:
            uv = self.gesture_uv_from_args(args)
            if uv is None:
                return
            hit = self._nearest_straight(wp, uv, self._snap_tol())
            if hit is not None:
                self._perp_baseline = hit
                self.win.statusBar().showMessage(
                    "Select point for perpendicular construction")
            return
        p = self._catch_pt(args)
        if p is None:
            return
        wp.cline_gen(wpm.perp_line(self._perp_baseline, p))
        self._perp_baseline = None
        self._preview_stop()
        self._preview_start(self.clinePerpC,
                            self._perp_preview_builder,
                            style="constr")
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Pick line to be perpendicular to")

    # ---- Angular bisector (pyurcad abcl) ----

    def clineAngBisec(self):
        self.win.registerCallback(self.clineAngBisecC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._preview_start(self.clineAngBisecC,
                            self._abcl_preview_builder, style="constr")
        self.win.statusBar().showMessage(
            "Enter bisector factor (Default=.5) or specify vertex")

    def _abcl_preview_builder(self, wp, uv):
        if len(self.win.xyPtStack) != 2:
            return None
        import workplane as wpm
        try:
            f = (self.win.floatStack[-1]
                 if self.win.floatStack else 0.5)
            p0, p1 = self.win.xyPtStack[0], self.win.xyPtStack[1]
            return self._cline_edge(
                wp, wpm.ang_bisector(p0, p1, uv, f))
        except Exception:
            return None

    def clineAngBisecC(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        n = len(self.win.xyPtStack)
        if n == 0:
            # the VERTEX is a precision point -> CATCH (typed
            # coords accepted too)
            p = self._take_pt(args)
            if p is None:
                if (self.win.floatStack
                        and not self.win.xyPtStack):
                    self.win.statusBar().showMessage(
                        "Specify vertex point" + self._ADVICE)
                return
            self.win.xyPtStack.append(p)
            self.win.statusBar().showMessage(
                "Specify point on base line")
            return
        # base line and second line are DIRECTION picks (Doug's
        # walkthrough: 'click on the base line') -- projected onto
        # the nearest straight element
        p = self._direction_pt(args, wp)
        if p is None:
            return
        self.win.xyPtStack.append(p)
        if len(self.win.xyPtStack) == 2:
            self.win.statusBar().showMessage("Specify second point")
            return
        f = self.win.floatStack[-1] if self.win.floatStack else 0.5
        p2 = self.win.xyPtStack.pop()
        p1 = self.win.xyPtStack.pop()
        p0 = self.win.xyPtStack.pop()
        wp.cline_gen(wpm.ang_bisector(p0, p1, p2, f))
        self._preview_stop()
        self._preview_start(self.clineAngBisecC,
                            self._abcl_preview_builder, style="constr")
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Enter bisector factor (Default=.5) or specify vertex")

    # ---- Tangent to circle (pyurcad cltan1) ----

    def clineTan1(self):
        self.win.registerCallback(self.clineTan1C)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._tan1_circ = None
        self.win.statusBar().showMessage("Pick circle")

    def clineTan1C(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        if self._tan1_circ is None:
            uv = self.gesture_uv_from_args(args)
            if uv is None:
                return
            circ = self._nearest_circle_ent(wp, uv, self._snap_tol())
            if circ is not None:
                self._tan1_circ = circ
                self.win.statusBar().showMessage("specify point")
            return
        p = self._catch_pt(args)
        if p is None:
            return
        try:
            p1, p2 = wpm.line_tan_to_circ(self._tan1_circ, p)
            wp.cline_gen(wpm.cnvrt_2pts_to_coef(p1, p))
            wp.cline_gen(wpm.cnvrt_2pts_to_coef(p2, p))
        except Exception:
            self.win.statusBar().showMessage(
                "Point is inside the circle -- pick outside.", 4000)
            return
        self._tan1_circ = None
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage("Pick circle")

    # ---- Tangent to 2 circles (pyurcad cltan2) ----

    def clineTan2(self):
        self.win.registerCallback(self.clineTan2C)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._tan2_circs = []
        self.win.statusBar().showMessage("Pick first circle")

    def clineTan2C(self, shapeList, *args):
        import workplane as wpm
        wp = self.win.activeWp
        if wp is None:
            return
        uv = self.gesture_uv_from_args(args)
        if uv is None:
            return
        circ = self._nearest_circle_ent(wp, uv, self._snap_tol())
        if circ is None:
            return
        self._tan2_circs.append(circ)
        if len(self._tan2_circs) == 1:
            self.win.statusBar().showMessage("Pick 2nd circle")
            return
        c2 = self._tan2_circs.pop()
        c1 = self._tan2_circs.pop()
        try:
            p1, p2 = wpm.line_tan_to_2circs(c1, c2)
            wp.cline_gen(wpm.cnvrt_2pts_to_coef(p1, p2))
        except Exception:
            self.win.statusBar().showMessage(
                "Tangent construction failed for those circles.",
                4000)
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage("Pick first circle")

    # ---- Concentric construction circle (pyurcad cccirc) ----

    def cccirc(self):
        self.win.registerCallback(self.cccircC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self._ccc_circ = None
        self._preview_start(self.cccircC,
                            self._ccc_preview_builder,
                            style="constr")
        self.win.statusBar().showMessage("Select existing circle")

    def _ccc_preview_builder(self, wp, uv):
        if self._ccc_circ is None:
            return None
        import workplane as wpm
        pc, _r0 = self._ccc_circ
        r = wpm.p2p_dist(pc, uv)
        if r < 1.0e-6:
            return None
        from OCP.gp import gp_Circ, gp_Ax2
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        center = self._uvpnt(wp, pc[0], pc[1])
        return BRepBuilderAPI_MakeEdge(
            gp_Circ(gp_Ax2(center, wp.wDir), r)).Edge()

    def cccircC(self, shapeList, *args):
        import workplane as wpm
        if self.win.lineEditStack:
            self.processLineEdit()
        wp = self.win.activeWp
        if wp is None:
            return
        if self._ccc_circ is None:
            uv = self.gesture_uv_from_args(args)
            if uv is not None:
                circ = self._nearest_circle_ent(wp, uv,
                                                self._snap_tol())
                if circ is not None:
                    self._ccc_circ = circ
                    self.win.statusBar().showMessage(
                        "Enter relative radius or specify point on "
                        "new circle")
            return
        pc, r0 = self._ccc_circ
        r = None
        if self.win.floatStack:
            r = r0 + self.win.floatStack.pop() * self.win.unitscale
        else:
            p = self._catch_pt(args)
            if p is not None:
                r = wpm.p2p_dist(pc, p)
        if r is None:
            return
        if r <= 1.0e-6:
            self.win.statusBar().showMessage(
                "Resulting radius is not positive.", 4000)
            return
        wp.circle((pc[0], pc[1]), r, constr=True)
        self._ccc_circ = None
        self._preview_stop()
        self._preview_start(self.cccircC,
                            self._ccc_preview_builder,
                            style="constr")
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage("Select existing circle")

    # ---- Slot (pyurcad slot) ----

    def slot(self):
        self.win.registerCallback(self.slotC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self.win.statusBar().showMessage(
            "Specify first point for slot")

    def slotC(self, shapeList, *args):
        import workplane as wpm
        if self.win.lineEditStack:
            self.processLineEdit()
        wp = self.win.activeWp
        if wp is None:
            return
        if len(self.win.xyPtStack) < 2:
            p = self._catch_pt(args)
            if p is None:
                return
            self.win.xyPtStack.append(p)
            if len(self.win.xyPtStack) == 1:
                self.win.statusBar().showMessage(
                    "Specify second point for slot")
            else:
                self.win.statusBar().showMessage("Enter slot width")
            return
        if not self.win.floatStack:
            self.win.statusBar().showMessage("Enter slot width")
            return
        p2 = self.win.xyPtStack.pop()
        p1 = self.win.xyPtStack.pop()
        w = self.win.floatStack.pop() * self.win.unitscale
        baseline = wpm.cnvrt_2pts_to_coef(p1, p2)
        crossline1 = wpm.perp_line(baseline, p1)
        crossline2 = wpm.perp_line(baseline, p2)
        paraline1, paraline2 = wpm.para_lines(baseline, w / 2.0)
        p1a = wpm.intersection(paraline1, crossline1)
        p1b = wpm.intersection(paraline2, crossline1)
        p1e = wpm.extendline(p2, p1, w / 2.0)
        p2a = wpm.intersection(paraline1, crossline2)
        p2b = wpm.intersection(paraline2, crossline2)
        p2e = wpm.extendline(p1, p2, w / 2.0)
        wp.arc3p(p1a, p1e, p1b)
        wp.arc3p(p2a, p2e, p2b)
        wp.line(p1a, p2a)
        wp.line(p1b, p2b)
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Specify first point for slot")

    # ---- 2D Fillet (pyurcad fillet) ----

    def fillet2d(self):
        self.win.registerCallback(self.fillet2dC)
        self.win.lineEdit.setFocus()
        self.win.xyPtStack = []
        self.win.statusBar().showMessage("Enter radius for fillet")

    def fillet2dC(self, shapeList, *args):
        import math as _m
        import workplane as wpm
        if self.win.lineEditStack:
            self.processLineEdit()
            if self.win.floatStack:
                self.win.statusBar().showMessage(
                    "Pick corner to apply fillet")
            return
        if not self.win.floatStack:
            self.win.statusBar().showMessage(
                "Enter radius for fillet")
            return
        wp = self.win.activeWp
        if wp is None:
            return
        # The corner is a CATCH on the shared endpoint of 2 lines
        p = self._catch_pt(args)
        if p is None:
            return
        # find the two geometry LINE edges meeting at that point
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_CurveType
        from snap_engine import _elslib
        hits = []
        for edge in list(wp.edgeList):
            try:
                crv = BRepAdaptor_Curve(edge)
                if crv.GetType() != GeomAbs_CurveType.GeomAbs_Line:
                    continue
                q1 = _elslib("Parameters")(
                    wp.gpPlane, crv.Value(crv.FirstParameter()))
                q2 = _elslib("Parameters")(
                    wp.gpPlane, crv.Value(crv.LastParameter()))
                for qa, qb in ((q1, q2), (q2, q1)):
                    if (abs(qa[0] - p[0]) < 1.0e-4
                            and abs(qa[1] - p[1]) < 1.0e-4):
                        hits.append((edge, qb))
                        break
            except Exception:
                continue
        if len(hits) != 2:
            self.win.statusBar().showMessage(
                "Pick the corner point where exactly 2 lines meet.",
                4000)
            return
        rw = self.win.floatStack[-1] * self.win.unitscale
        cp = p
        ep1 = hits[0][1]
        ep2 = hits[1][1]
        try:
            ctr, tp1, tp2 = wpm.find_fillet_pts(rw, cp, ep1, ep2)
        except Exception:
            self.win.statusBar().showMessage(
                "Fillet radius too large for that corner.", 4000)
            return
        for edge, _q in hits:
            matching = next(
                (e for e in wp.edgeList if e.IsSame(edge)), None)
            if matching is not None:
                wp.edgeList.remove(matching)
        wp.line(ep1, tp1)
        wp.line(ep2, tp2)
        a1 = _m.atan2(tp1[1] - ctr[1], tp1[0] - ctr[0])
        a2 = _m.atan2(tp2[1] - ctr[1], tp2[0] - ctr[0])
        if (a2 - a1) > _m.pi or -_m.pi < (a2 - a1) < 0:
            tp1, tp2 = tp2, tp1
            a1, a2 = a2, a1
        amid = a1 + ((a2 - a1) % (2.0 * _m.pi)) / 2.0
        rad = wpm.p2p_dist(ctr, tp1)
        pm = (ctr[0] + rad * _m.cos(amid), ctr[1] + rad * _m.sin(amid))
        wp.arc3p(tp1, pm, tp2)
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            "Fillet applied. Pick another corner (same radius) or "
            "End Operation.")

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
        self.win.lineEdit.setFocus()
        self.display.SetSelectionModeVertex()
        self.win.xyPtStack = []
        self._preview_start(self.cc3pC, self._cc3p_preview_builder)
        self.win.statusBar().showMessage(
            "Pick first point on circle")

    def cc3pC(self, shapeList, *args):
        n_before = len(self.win.xyPtStack)
        if not self.add_snap_pt_to_xyPtStack(args):
            self.add_vertex_to_xyPtStack(shapeList)
        self.win.lineEdit.setFocus()
        n = len(self.win.xyPtStack)
        if n == n_before:
            return
        if n == 1:
            self.win.statusBar().showMessage(
                "Pick second point on circle")
            return
        if n == 2:
            self.win.statusBar().showMessage(
                "Pick third point on circle")
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
        self.win.lineEdit.setFocus()
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

    def _preview_start(self, owner_cb, builder, style="geom"):
        self._preview_stop()  # single registration, always (Session
        # 63: starting tool B while tool A's preview awaited its lazy
        # cleanup left DUPLICATE move callbacks -- the root of the
        # 'NoneType is not callable' crash)
        # style 'geom': BRIGHT YELLOW solid (geometry rubber).
        # style 'constr': DASHED MAGENTA, indistinguishable from a
        # final cline (Session 63, Doug: construction rubber
        # previews exactly what will exist -- yellow is for
        # geometry rubber ONLY).
        self._prev_owner = owner_cb
        self._prev_builder = builder
        self._prev_style = style
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
            if (getattr(self, "_prev_builder", None) is None
                    or self.win.registeredCallback is None):
                self._preview_stop()
                return
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
                                          Quantity_TypeOfColor,
                                          Quantity_NOC_MAGENTA1)
                self._prev_ais = AIS_Shape(shape)
                if getattr(self, "_prev_style", "geom") == "constr":
                    try:
                        from OCP.Prs3d import Prs3d_LineAspect
                        from OCP.Aspect import Aspect_TypeOfLine
                        drw = self._prev_ais.Attributes()
                        asp = Prs3d_LineAspect(
                            Quantity_Color(Quantity_NOC_MAGENTA1),
                            Aspect_TypeOfLine.Aspect_TOL_DASH, 1.0)
                        drw.SetLineAspect(asp)
                        drw.SetWireAspect(asp)
                        self._prev_ais.SetAttributes(drw)
                    except Exception:
                        pass
                context.Display(self._prev_ais, False)
                try:
                    self.win.canvas._display.add_never_pick(
                        self._prev_ais)
                except Exception:
                    pass
                try:
                    if getattr(self, "_prev_style", "geom") == "constr":
                        context.SetColor(
                            self._prev_ais,
                            Quantity_Color(Quantity_NOC_MAGENTA1),
                            False)
                    else:
                        # BRIGHT YELLOW geometry rubber
                        context.SetColor(
                            self._prev_ais,
                            Quantity_Color(
                                1.0, 1.0, 0.0,
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
        """Delete a 2D CONSTRUCTION element -- engine ENTITY PICK
        (Session 63). The click resolves to the nearest construction
        entity by CURVE distance (the same ranking Ctrl+Shift center
        mode uses); no OCCT selection is involved, so this tool
        structurally CANNOT delete geometry -- and delEl structurally
        cannot delete construction -- which closes both c/g filter
        items from the to-do list. (Historical note: this tool was a
        known TODO since the original port -- AIS_Line identification
        never worked; the engine dissolved the problem rather than
        solving it.)"""
        self.win.registerCallback(self.delClC)
        self.win.lineEdit.setFocus()
        self.win.statusBar().showMessage(
            "Pick a construction element to delete "
            "(middle-click to end).")

    def delClC(self, shapeList, *args):
        """Callback (collector) for delCl -- entity pick by click."""
        uv = self.gesture_uv_from_args(args)
        wp = self.win.activeWp
        if uv is None or wp is None:
            return
        try:
            from snap_engine import SNAP_PIXELS
            tol = abs(self.win.canvas.view.Convert(SNAP_PIXELS))
        except Exception:
            tol = 1.0
        hit = self._nearest_constr_entity(wp, uv, tol)
        if hit is None:
            self.win.statusBar().showMessage(
                "No construction element there -- pick closer "
                "(middle-click to end).", 3000)
            return
        kind, key = hit
        try:
            if kind == "cline":
                wp.clines.discard(key)
            elif kind == "ccirc":
                wp.ccircs.discard(key)
            elif kind == "carc":
                wp.carcs.remove(key)
            elif kind == "cseg":
                wp.csegs.remove(key)
        except (KeyError, ValueError):
            pass
        self.win.draw_wp(self.win.activeWpUID)
        self.win.statusBar().showMessage(
            f"Construction {kind} deleted. Pick another "
            "(middle-click to end).")

    def _nearest_constr_entity(self, wp, uv, tol):
        """Nearest construction entity to uv by curve distance.
        Returns (kind, key) or None."""
        import math as _m
        best = [None, None]

        def consider(kind, key, d):
            if d <= tol and (best[1] is None or d < best[1]):
                best[0] = (kind, key)
                best[1] = d

        for cl in wp.clines:
            a, b, c = cl
            den = _m.hypot(a, b)
            if den < 1.0e-12:
                continue
            consider("cline", cl,
                     abs(a * uv[0] + b * uv[1] + c) / den)
        for cs in wp.csegs:
            (x1, y1), (x2, y2) = cs
            dx, dy = x2 - x1, y2 - y1
            l2 = dx * dx + dy * dy
            if l2 < 1.0e-18:
                continue
            t = ((uv[0] - x1) * dx + (uv[1] - y1) * dy) / l2
            t = max(0.0, min(1.0, t))
            consider("cseg", cs,
                     _m.hypot(uv[0] - (x1 + t * dx),
                              uv[1] - (y1 + t * dy)))
        for cc in wp.ccircs:
            pc, r = cc
            consider("ccirc", cc,
                     abs(_m.hypot(uv[0] - pc[0], uv[1] - pc[1]) - r))
        try:
            from snap_engine import _on_arc
        except Exception:
            _on_arc = None
        for ca in wp.carcs:
            pc, r, a0, a1 = ca
            dc = _m.hypot(uv[0] - pc[0], uv[1] - pc[1])
            if dc < 1.0e-9:
                continue
            onp = (pc[0] + (uv[0] - pc[0]) * r / dc,
                   pc[1] + (uv[1] - pc[1]) * r / dc)
            if _on_arc is None or _on_arc(onp, pc, a0, a1):
                consider("carc", ca, abs(dc - r))
        return best[0]

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
