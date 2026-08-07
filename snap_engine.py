"""
snap_engine.py -- the sketch engine (Sessions 62+; design in
docs/SKETCH_ENGINE_DESIGN.md).

screen_to_uv: THE bridge (cursor ray -> gp_Pln -> UV).
find_snap: app-side candidate search in workplane UV space, calling
workplane.py's Pyurcad-lineage math. Candidates now include GEOMETRY
LINES (Doug's request): linear-edge endpoints and intersections
(geom x geom, geom x cline) alongside the construction categories.
SnapHover: the catch indicator -- a small SQUARE outline drawn on
the workplane at the catch point (the Pyurcad glyph), deliberately
unlike the legacy pre-built '+' markers it supersedes. Non-selectable,
never steals picks.

Input philosophy (binding, see design doc): NO CATCH -> NO POINT for
coordinate input; free clicks exist only as GESTURES (side/direction
choices). The square is the permission indicator.
"""

from OCP.gp import gp_Pnt
from OCP.AIS import AIS_Shape
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.ElSLib import ElSLib

import workplane as wpm  # the Pyurcad-lineage 2D math lives here

PRIORITY = {"isect": 4, "endpoint": 4, "center": 4, "midpoint": 4,
            "origin": 2, "on": 1}

SNAP_PIXELS = 12       # catch radius on screen, constant at any zoom
MARKER_PIXELS = 5      # half-side of the catch square, in pixels


def _elslib(name_base):
    fn = getattr(ElSLib, name_base + "_s", None)
    if fn is None:
        fn = getattr(ElSLib, name_base)
    return fn


def screen_to_uv(view, x, y, gp_pln):
    """Cursor pixel -> (u, v) on the plane, or None if the view ray
    is parallel to the plane. THE bridge."""
    try:
        px, py, pz, vx, vy, vz = view.ConvertWithProj(int(x), int(y))
    except Exception:
        return None
    ax = gp_pln.Axis()
    o = ax.Location()
    n = ax.Direction()
    denom = n.X() * vx + n.Y() * vy + n.Z() * vz
    if abs(denom) < 1.0e-12:
        return None
    t = (n.X() * (o.X() - px) + n.Y() * (o.Y() - py)
         + n.Z() * (o.Z() - pz)) / denom
    hit = gp_Pnt(px + vx * t, py + vy * t, pz + vz * t)
    try:
        u, v = _elslib("Parameters")(gp_pln, hit)
    except Exception:
        return None
    return (u, v)


def uv_to_world(gp_pln, u, v):
    """(u, v) on the plane -> world gp_Pnt."""
    return _elslib("Value")(u, v, gp_pln)


def _dist(p, q):
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _geom_segments_uv(wp):
    """Extract the workplane's LINEAR geometry edges as UV segments
    ((u1,v1),(u2,v2)) -- geometry participates in catching (Doug:
    'intersections of either construction or geometry lines').
    Non-linear edges (arcs) are deferred; noted in the log."""
    segs = []
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_CurveType
        for edge in getattr(wp, "edgeList", ()) or ():
            try:
                crv = BRepAdaptor_Curve(edge)
                if crv.GetType() != GeomAbs_CurveType.GeomAbs_Line:
                    continue
                p1 = crv.Value(crv.FirstParameter())
                p2 = crv.Value(crv.LastParameter())
                u1, v1 = _elslib("Parameters")(wp.gpPlane, p1)
                u2, v2 = _elslib("Parameters")(wp.gpPlane, p2)
                segs.append(((u1, v1), (u2, v2)))
            except Exception:
                continue
    except Exception:
        pass
    return segs


def current_snap_mode():
    """'center' while Ctrl+Shift are held (the CoCreate modifier:
    temporarily catch ONLY centers of circles/arcs and midpoints of
    straight edges), else 'normal'. Session 62, Doug's TODO item."""
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        mods = QApplication.keyboardModifiers()
        if (mods & Qt.KeyboardModifier.ControlModifier
                and mods & Qt.KeyboardModifier.ShiftModifier):
            return "center"
    except Exception:
        pass
    return "normal"


def _geom_circles_uv(wp):
    """The workplane's circular geometry edges as (center_uv, radius)
    -- their CENTERS participate in Ctrl+Shift catching."""
    circs = []
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_CurveType
        for edge in getattr(wp, "edgeList", ()) or ():
            try:
                crv = BRepAdaptor_Curve(edge)
                if crv.GetType() != GeomAbs_CurveType.GeomAbs_Circle:
                    continue
                c = crv.Circle()
                loc = c.Location()
                u, v = _elslib("Parameters")(wp.gpPlane, loc)
                circs.append(((u, v), c.Radius()))
            except Exception:
                continue
    except Exception:
        pass
    return circs


def _on_segment(p, a, b, eps=1.0e-6):
    """Is point p (on the infinite line ab) within the segment ab?"""
    du, dv = b[0] - a[0], b[1] - a[1]
    L2 = du * du + dv * dv
    if L2 < eps * eps:
        return False
    t = ((p[0] - a[0]) * du + (p[1] - a[1]) * dv) / L2
    return -eps <= t <= 1.0 + eps


def find_snap(wp, uv, tol, mode="normal"):
    """Best snap candidate near cursor uv within tol. Returns
    (kind, (u, v)) or None. Guarded per pair -- one degenerate
    entity can't kill the sweep.

    MODES (Session 62, Doug's catch policy):
    - 'normal': INTERSECTIONS (+ endpoints, origin). On-curve and
      centers are NOT offered -- a drafter draws dark lines between
      intersections of the layout, not 'somewhere along' a line.
    - 'center' (Ctrl+Shift held, the CoCreate override): centers of
      circles/arcs (construction AND geometry) and MIDPOINTS of
      straight geometry edges, EXCLUSIVELY."""
    cands = []
    clines = list(getattr(wp, "clines", ()) or ())
    ccircs = list(getattr(wp, "ccircs", ()) or ())
    segs = _geom_segments_uv(wp)

    if mode == "center":
        # ENTITY-ANCHORED (Session 62 refinement -- Doug verified
        # against Creo E/D and Pyurcad): the cursor points at the
        # ENTITY, anywhere along it; the glyph appears at ITS
        # center/midpoint, which may be FAR from the cursor. (The
        # center of a circle has no visible feature at it -- making
        # the user aim at empty space was backwards. Point at what
        # you can see.) Ranking is by distance to the CURVE, not to
        # the anchor point. Click takes the glyph's location.
        best = None
        best_d = None
        for cc in ccircs:  # construction circles: distance to rim
            try:
                pc, r = cc[0], cc[1]
                d = abs(_dist(uv, (pc[0], pc[1])) - r)
                if d <= tol and (best_d is None or d < best_d):
                    best_d = d
                    best = ("center", (pc[0], pc[1]))
            except Exception:
                pass
        for pc, r in _geom_circles_uv(wp):  # geometry circles/arcs
            d = abs(_dist(uv, (pc[0], pc[1])) - r)
            if d <= tol and (best_d is None or d < best_d):
                best_d = d
                best = ("center", (pc[0], pc[1]))
        for a, b in segs:  # geometry segments: distance to segment
            try:
                coef = wpm.cnvrt_2pts_to_coef(a, b)
                p = wpm.proj_pt_on_line(coef, uv)
                if _on_segment(p, a, b):
                    d = _dist(uv, p)
                else:
                    d = min(_dist(uv, a), _dist(uv, b))
                if d <= tol and (best_d is None or d < best_d):
                    best_d = d
                    best = ("midpoint", ((a[0] + b[0]) / 2.0,
                                         (a[1] + b[1]) / 2.0))
            except Exception:
                pass
        return best

    # --- construction x construction ---
    for i in range(len(clines)):
        for j in range(i + 1, len(clines)):
            try:
                p = wpm.intersection(clines[i], clines[j])
                if p is not None:
                    cands.append(("isect", (p[0], p[1])))
            except Exception:
                pass
    for cl in clines:
        for cc in ccircs:
            try:
                pts = wpm.line_circ_inters(cl, cc)
                for p in (pts or ()):
                    cands.append(("isect", (p[0], p[1])))
            except Exception:
                pass
    for i in range(len(ccircs)):
        for j in range(i + 1, len(ccircs)):
            try:
                pts = wpm.circ_circ_inters(ccircs[i], ccircs[j])
                for p in (pts or ()):
                    cands.append(("isect", (p[0], p[1])))
            except Exception:
                pass

    # --- geometry lines (Session 62, Doug's request) ---
    seg_coefs = []
    for a, b in segs:
        try:
            seg_coefs.append((wpm.cnvrt_2pts_to_coef(a, b), a, b))
        except Exception:
            seg_coefs.append((None, a, b))
        cands.append(("endpoint", a))
        cands.append(("endpoint", b))
    # geom x geom
    for i in range(len(seg_coefs)):
        for j in range(i + 1, len(seg_coefs)):
            ci, ai, bi = seg_coefs[i]
            cj, aj, bj = seg_coefs[j]
            if ci is None or cj is None:
                continue
            try:
                p = wpm.intersection(ci, cj)
                if (p is not None and _on_segment(p, ai, bi)
                        and _on_segment(p, aj, bj)):
                    cands.append(("isect", (p[0], p[1])))
            except Exception:
                pass
    # geom x cline
    for ci, ai, bi in seg_coefs:
        if ci is None:
            continue
        for cl in clines:
            try:
                p = wpm.intersection(ci, cl)
                if p is not None and _on_segment(p, ai, bi):
                    cands.append(("isect", (p[0], p[1])))
            except Exception:
                pass

    # --- origin (normal mode; centers/on-curve deliberately absent:
    # centers live behind Ctrl+Shift, on-curve is not a drafter's
    # catch -- Session 62 policy) ---
    cands.append(("origin", (0.0, 0.0)))

    best = None
    best_key = None
    for kind, p in cands:
        d = _dist(uv, p)
        if d > tol:
            continue
        key = (-PRIORITY.get(kind, 0), d)
        if best_key is None or key < best_key:
            best_key = key
            best = (kind, p)
    return best


class SnapHover:
    """The catch indicator: a small SQUARE outline drawn ON the
    workplane at the catch point (Pyurcad's glyph -- Doug's request,
    deliberately unlike the legacy pre-built '+' markers). Rebuilt
    only when the snap result changes; sized in pixels via
    view.Convert so it stays constant on screen. Non-selectable --
    it can never steal a pick."""

    COLOR = (1.0, 0.45, 0.0)        # normal mode: orange
    COLOR_CENTER = (0.0, 0.85, 0.9)  # Ctrl+Shift center mode: cyan
    # -- the flyby colour tells you which catch set is live

    def __init__(self, win):
        self.win = win
        self._marker = None
        self._last = None

    def _context(self):
        display = getattr(self.win.canvas, "_display", None)
        return None if display is None else display.Context

    def _square_edge(self, wp, u, v):
        """A square wire in the workplane at (u, v), half-side sized
        MARKER_PIXELS on screen."""
        try:
            s = abs(self.win.canvas.view.Convert(MARKER_PIXELS))
        except Exception:
            s = 0.5
        corners = ((u - s, v - s), (u + s, v - s),
                   (u + s, v + s), (u - s, v + s))
        poly = BRepBuilderAPI_MakePolygon()
        for cu, cv in corners:
            poly.Add(gp_Pnt(cu, cv, 0).Transformed(wp.Trsf))
        poly.Close()
        return poly.Wire()

    def _show(self, wp, snap, mode):
        context = self._context()
        if context is None:
            return
        wire = self._square_edge(wp, snap[1][0], snap[1][1])
        rgb = self.COLOR_CENTER if mode == "center" else self.COLOR
        if self._marker is None:
            self._marker = AIS_Shape(wire)
            context.Display(self._marker, False)
        else:
            self._marker.SetShape(wire)
            context.Redisplay(self._marker, False)
        try:
            context.SetColor(
                self._marker,
                Quantity_Color(*rgb,
                               Quantity_TypeOfColor.Quantity_TOC_RGB),
                False)
            context.Deactivate(self._marker)  # never pickable
        except Exception:
            pass
        context.UpdateCurrentViewer()

    def _hide(self):
        if self._marker is not None:
            context = self._context()
            if context is not None:
                try:
                    context.Erase(self._marker, True)
                except Exception:
                    pass
            self._marker = None

    def on_move(self, x, y):
        """Mouse-move callback from the viewport (hover only)."""
        try:
            wp = getattr(self.win, "activeWp", None)
            if wp is None:
                if self._last is not None:
                    self._hide()
                    self._last = None
                return
            view = self.win.canvas.view
            uv = screen_to_uv(view, x, y, wp.gpPlane)
            if uv is None:
                if self._last is not None:
                    self._hide()
                    self._last = None
                return
            try:
                tol = abs(view.Convert(SNAP_PIXELS))
            except Exception:
                tol = 1.0
            mode = current_snap_mode()
            snap = find_snap(wp, uv, tol, mode)
            if snap is None:
                if self._last is not None:
                    self._hide()
                    self._last = None
                return
            if (mode, snap) == self._last:
                return
            self._show(wp, snap, mode)
            self._last = (mode, snap)
        except Exception as e:
            if not getattr(self, "_warned", False):
                print(f"[snap_hover] disabled after error: {e}")
                self._warned = True
