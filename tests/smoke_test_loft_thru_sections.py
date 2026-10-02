"""
smoke_test_loft_thru_sections.py -- headless validation of OCP's
BRepOffsetAPI_ThruSections, BEFORE any "Workplane Set" / loft UI gets
built on top of it.

Run: uv run python smoke_test_loft_thru_sections.py

CONFIDENCE NOTE: like smoke_test_auto_isolated_feature.py before it,
this has NOT been run against a live OCP in this sandbox -- no
network access here to install cadquery-ocp-novtk. Every class/method
name below is confirmed against the OCCT reference docs and against
CadQuery's own GitHub issue tracker (CadQuery/cadquery#652 and
CadQuery/OCP#87, both of which call BRepOffsetAPI_ThruSections
directly through OCP -- real, working usage, not just documentation),
but none of it has actually executed yet. Run this and share the
full output before anything gets wired into the UI.

FOUR CASES, each validated numerically (never just IsDone()==True on
its own -- Session 103's own finding, from the Remove Hole work,
still holds here: a defeaturing/lofting call can report success
without having done the right thing):

  CASE 1: ruled loft between two same-size circles, 20mm apart.
  Sanity check against a KNOWN ANALYTIC ANSWER -- a loft between two
  identical circles is a cylinder, so its volume should match
  pi*r^2*h within a tight tolerance. This validates the whole
  ThruSections call path against ground truth, not just "did it
  build something."

  CASE 2: the actual point of this whole exploration -- does vertex
  CORRESPONDENCE across sections control twist, the way Doug recalls
  CoCreate's "match line" working? Two identical squares, 20mm apart.
  2a builds both squares with their 4 corners in the SAME starting
  corner/order (the "match line" aligned) and expects a straight
  prism -- every one of its 4 side faces should be VERTICAL (face
  normal has zero Z-component). 2b builds the same two squares but
  starts the top square's corner list one position further around
  (deliberately misaligned correspondence) and expects a visibly
  TWISTED ruled surface -- side faces whose normal is NOT purely
  horizontal. Both use CheckCompatibility(False) (manual
  correspondence, OCCT's own automatic twist-avoidance turned off)
  so the only variable between 2a and 2b is vertex order itself.

  CASE 3: a simplified hull -- four closed, lens-shaped cross-section
  profiles (Doug's own ship-hull example), all built with the SAME
  number of segments and the same starting-corner convention (the
  actual match-line discipline CoCreate required), tapering to a
  single point at bow and stern via AddVertex(). Smooth (non-ruled)
  solid loft. Validated with BRepCheck_Analyzer (a real shape
  validity check, not just Build().IsDone()) and a positive, sane
  volume via GProp.

  CASE 4 (negative): two profiles with a DIFFERENT number of
  segments, CheckCompatibility(False) (manual mode, no automatic
  edge-splitting to equalize them). Expects Build() to fail or raise
  -- confirming Doug's own CoCreate recollection ("each profile had
  to contain the same number of segments") as a real, enforced
  constraint of manual-correspondence mode in OCCT too, not just a
  CoCreate-specific rule of thumb.
"""

import math

from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge,
                                 BRepBuilderAPI_MakeWire,
                                 BRepBuilderAPI_MakePolygon)
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Pnt, gp_Circ, gp_Ax2, gp_Dir
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane


def circle_wire(radius, z):
    circ = gp_Circ(gp_Ax2(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), radius)
    edge = BRepBuilderAPI_MakeEdge(circ).Edge()
    return BRepBuilderAPI_MakeWire(edge).Wire()


def square_wire(half, z, start_offset=0):
    """Closed 4-corner square wire, corners listed starting from
    corner index `start_offset` (0..3) around the square -- the
    knob that controls match-line ALIGNMENT between this wire and
    whatever it's lofted against."""
    corners = [
        gp_Pnt(half, half, z),
        gp_Pnt(-half, half, z),
        gp_Pnt(-half, -half, z),
        gp_Pnt(half, -half, z),
    ]
    ordered = corners[start_offset:] + corners[:start_offset]
    mp = BRepBuilderAPI_MakePolygon()
    for p in ordered:
        mp.Add(p)
    mp.Close()
    return mp.Wire()


def hull_station_wire(x, half_width, half_height, n=6):
    """Closed, lens-shaped cross-section at station x -- n points
    around a simple ellipse-ish outline, ALWAYS the same n and the
    same starting-point convention (angle 0) across every station,
    per the match-line discipline this whole test is about."""
    mp = BRepBuilderAPI_MakePolygon()
    pts = []
    for i in range(n):
        ang = 2 * math.pi * i / n
        y = half_width * math.cos(ang)
        z = half_height * math.sin(ang)
        pts.append(gp_Pnt(x, y, z))
    for p in pts:
        mp.Add(p)
    mp.Close()
    return mp.Wire()


def volume_of(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def count_vertical_side_faces(shape, tol=1e-6):
    """Count planar faces whose normal is purely horizontal (Z
    component ~0) -- i.e. VERTICAL side faces, the signature of an
    untwisted ruled loft along Z."""
    n = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        f = TopoDS.Face_s(exp.Current())
        surf = BRepAdaptor_Surface(f)
        if surf.GetType() == GeomAbs_Plane:
            normal = surf.Plane().Axis().Direction()
            if abs(normal.Z()) < tol:
                n += 1
        exp.Next()
    return n


def run_loft(wires, vertices_first_last=(None, None), ruled=False,
            is_solid=False, check_compat=True, label=""):
    """vertices_first_last: (vertex_or_None, vertex_or_None) added
    before/after the wire sequence via AddVertex()."""
    ts = BRepOffsetAPI_ThruSections(is_solid, ruled)
    ts.CheckCompatibility(check_compat)
    v0, v1 = vertices_first_last
    if v0 is not None:
        ts.AddVertex(v0)
    for w in wires:
        ts.AddWire(w)
    if v1 is not None:
        ts.AddVertex(v1)
    try:
        ts.Build()
    except Exception as e:
        print(f"[{label}] Build() raised: {e}")
        return None, False
    done = ts.IsDone()
    print(f"[{label}] IsDone={done}")
    if not done:
        return None, False
    return ts.Shape(), True


def main():
    # ---- CASE 1: ruled loft between two circles == a cylinder ----
    print("=" * 70)
    print("CASE 1: circle -> circle, ruled, isSolid -- should be a "
         "cylinder")
    print("=" * 70)
    r, h = 10.0, 20.0
    w1 = circle_wire(r, 0.0)
    w2 = circle_wire(r, h)
    shape1, ok1 = run_loft([w1, w2], ruled=True, is_solid=True,
                           check_compat=True, label="CASE 1")
    if ok1:
        vol = volume_of(shape1)
        expected = math.pi * r * r * h
        print(f"  volume={vol:.3f}  expected(pi*r^2*h)={expected:.3f}"
             f"  diff={abs(vol - expected):.6f}")

    # ---- CASE 2a: aligned squares -> straight prism ----
    print("=" * 70)
    print("CASE 2a: square -> square, SAME corner order (match line "
         "aligned) -- expect a straight prism, 4 vertical side "
         "faces")
    print("=" * 70)
    sq_bot = square_wire(10.0, 0.0, start_offset=0)
    sq_top_aligned = square_wire(10.0, h, start_offset=0)
    shape2a, ok2a = run_loft(
        [sq_bot, sq_top_aligned], ruled=True, is_solid=True,
        check_compat=False, label="CASE 2a")
    if ok2a:
        n_vert = count_vertical_side_faces(shape2a)
        print(f"  vertical side faces: {n_vert} (expected 4)")

    # ---- CASE 2b: misaligned squares -> twisted loft ----
    print("=" * 70)
    print("CASE 2b: square -> square, corner list rotated by ONE "
         "position (match line MISALIGNED) -- expect a twisted "
         "result, fewer (likely 0) vertical side faces")
    print("=" * 70)
    sq_top_twisted = square_wire(10.0, h, start_offset=1)
    shape2b, ok2b = run_loft(
        [sq_bot, sq_top_twisted], ruled=True, is_solid=True,
        check_compat=False, label="CASE 2b")
    if ok2b:
        n_vert = count_vertical_side_faces(shape2b)
        print(f"  vertical side faces: {n_vert} (expected < 4, "
             f"likely 0 -- this IS the twist)")

    # ---- CASE 3: simplified hull, tapering to a point at both ends
    print("=" * 70)
    print("CASE 3: 4-station lens-shaped hull, same segment count "
         "and starting-point convention at every station, tapering "
         "to a point at bow and stern via AddVertex()")
    print("=" * 70)
    n_pts = 6
    bow_pt = gp_Pnt(0.0, 0.0, 0.0)
    stations = [
        (20.0, 2.0, 1.0),
        (40.0, 8.0, 4.0),
        (60.0, 8.0, 4.0),
        (80.0, 3.0, 1.5),
    ]
    stern_pt = gp_Pnt(100.0, 0.0, 0.0)
    station_wires = [hull_station_wire(x, hw, hh, n=n_pts)
                     for x, hw, hh in stations]
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    bow_v = BRepBuilderAPI_MakeVertex(bow_pt).Vertex()
    stern_v = BRepBuilderAPI_MakeVertex(stern_pt).Vertex()
    shape3, ok3 = run_loft(
        station_wires, vertices_first_last=(bow_v, stern_v),
        ruled=False, is_solid=True, check_compat=False,
        label="CASE 3")
    if ok3:
        analyzer = BRepCheck_Analyzer(shape3)
        print(f"  BRepCheck_Analyzer.IsValid()={analyzer.IsValid()}")
        vol = volume_of(shape3)
        print(f"  volume={vol:.3f} (expect positive, roughly "
             f"order-of-magnitude sane for an 8x4x100-ish taper)")

    # ---- CASE 4 (negative): mismatched segment counts ----
    print("=" * 70)
    print("CASE 4 (negative): mismatched segment counts (4 vs 6), "
         "CheckCompatibility(False) -- expect failure, confirming "
         "the equal-segment-count requirement is real and enforced")
    print("=" * 70)
    w_sq = square_wire(10.0, 0.0)
    w_hex = hull_station_wire(h, 10.0, 10.0, n=6)
    _shape4, ok4 = run_loft(
        [w_sq, w_hex], ruled=True, is_solid=False,
        check_compat=False, label="CASE 4")
    print(f"  succeeded despite mismatched counts: {ok4} "
         f"(expected False)")


if __name__ == "__main__":
    main()
