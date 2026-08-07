"""
snap_engine.py -- Step 1 of the sketch engine (Session 62; design in
docs/SKETCH_ENGINE_DESIGN.md).

The bridge and the hover-only snap marker. Zero behavioral change to
any existing tool: this module only OBSERVES mouse motion and shows a
glyph at the point the engine would catch. Later steps route tool
input through find_snap().

Architecture (the Pyurcad inversion): the snap engine is OURS, in
workplane UV space; OCCT is just a projector. screen_to_uv() converts
every cursor position to workplane coordinates; candidates come from
the workplane's own construction data using workplane.py's
Pyurcad-lineage math (intersection, line_circ_inters,
circ_circ_inters, proj_pt_on_line -- already in this codebase);
ranking is by PIXEL distance (view.Convert for a zoom-constant catch
radius).

Candidate categories (step 1 -- construction geometry, matching the
current sketching paradigm; profile endpoints/midpoints arrive with
step 2):
    isect   cline x cline, cline x ccirc, ccirc x ccirc  (on the fly)
    center  ccirc centers
    origin  workplane origin
    on      nearest point ON a cline / ccirc  (lower priority)
"""

from OCP.gp import gp_Pnt
from OCP.Geom import Geom_CartesianPoint
from OCP.AIS import AIS_Point
from OCP.Prs3d import Prs3d_PointAspect
from OCP.Aspect import Aspect_TypeOfMarker
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.ElSLib import ElSLib

import workplane as wpm  # the Pyurcad-lineage 2D math lives here

# Higher = wins ties; candidates within tolerance rank by
# (priority desc, pixel distance asc)
PRIORITY = {"isect": 3, "center": 3, "origin": 2, "on": 1}

SNAP_PIXELS = 12  # catch radius on screen, constant at any zoom


def _elslib(name_base):
    fn = getattr(ElSLib, name_base + "_s", None)
    if fn is None:
        fn = getattr(ElSLib, name_base)
    return fn


def screen_to_uv(view, x, y, gp_pln):
    """Cursor pixel -> (u, v) on the plane, or None if the view ray
    is parallel to the plane. THE bridge (design doc, 'The bridge')."""
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


def find_snap(wp, uv, tol):
    """Best snap candidate near cursor uv within tol (model units on
    the plane -- the plane is an isometric embedding, so world tol ==
    UV tol). Returns (kind, (u, v)) or None. All candidate math is
    workplane.py's own; every pair is guarded so one degenerate
    entity can't kill the sweep."""
    cands = []
    clines = list(getattr(wp, "clines", ()) or ())
    ccircs = list(getattr(wp, "ccircs", ()) or ())

    # intersections, computed on the fly near the cursor
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

    # centers and origin
    for cc in ccircs:
        try:
            pc = cc[0]
            cands.append(("center", (pc[0], pc[1])))
        except Exception:
            pass
    cands.append(("origin", (0.0, 0.0)))

    # on-curve (lower priority; only offered when nothing sharper is
    # within reach)
    for cl in clines:
        try:
            p = wpm.proj_pt_on_line(cl, uv)
            cands.append(("on", (p[0], p[1])))
        except Exception:
            pass
    for cc in ccircs:
        try:
            pc, r = cc[0], cc[1]
            d = _dist(uv, (pc[0], pc[1]))
            if d > 1.0e-9:
                f = r / d
                cands.append(("on", (pc[0] + (uv[0] - pc[0]) * f,
                                     pc[1] + (uv[1] - pc[1]) * f)))
        except Exception:
            pass

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
    """Hover-only marker (step 1). Observes mouse motion; shows a
    non-selectable glyph at the current best snap. Never participates
    in selection (Deactivate after Display) and never intercepts
    input -- pure visualization until later steps consume
    find_snap()."""

    def __init__(self, win):
        self.win = win
        self._marker = None
        self._last = None  # last shown (kind, (u,v)) or None

    def _context(self):
        display = getattr(self.win.canvas, "_display", None)
        return None if display is None else display.Context

    def _ensure_marker(self, pnt):
        context = self._context()
        if context is None:
            return None
        if self._marker is None:
            self._marker = AIS_Point(Geom_CartesianPoint(pnt))
            color = Quantity_Color(1.0, 0.85, 0.0,
                                   Quantity_TypeOfColor.Quantity_TOC_RGB)
            try:
                aspect = Prs3d_PointAspect(
                    Aspect_TypeOfMarker.Aspect_TOM_PLUS, color, 4.0)
                self._marker.Attributes().SetPointAspect(aspect)
            except Exception:
                pass
            context.Display(self._marker, False)
            try:
                context.Deactivate(self._marker)  # never pickable
            except Exception:
                pass
        else:
            self._marker.SetComponent(Geom_CartesianPoint(pnt))
            context.Redisplay(self._marker, False)
        return context

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
        """Mouse-move callback from the viewport (hover only -- the
        viewport does not call this during drags)."""
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
            snap = find_snap(wp, uv, tol)
            if snap is None:
                if self._last is not None:
                    self._hide()
                    self._last = None
                return
            if snap == self._last:
                return  # unchanged -- no redisplay churn
            pnt = uv_to_world(wp.gpPlane, snap[1][0], snap[1][1])
            context = self._ensure_marker(pnt)
            if context is not None:
                context.UpdateCurrentViewer()
            self._last = snap
        except Exception as e:
            # hover must never break the viewport -- report once
            if not getattr(self, "_warned", False):
                print(f"[snap_hover] disabled after error: {e}")
                self._warned = True
