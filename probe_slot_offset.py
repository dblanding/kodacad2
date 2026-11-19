"""probe_slot_offset.py -- why does Move Face fail on the slot of l-bracket_1?

Session 180 (Doug, Nov 16: +1 mm on the slot wall of l-bracket_1 in
as1-oc-214.stp gives 'OpenCascade cannot build this offset'). The failing
input was saved by face_offset.diagnose() as ~/kodacad_offset_input.brep.

Run it from the KodaCAD2 folder:

    uv run python probe_slot_offset.py                 # the saved brep
    uv run python probe_slot_offset.py other.brep      # another file

Read-only: nothing is written except a few temporary files the offset
worker needs. It prints, in order:

  1. the part: solids / faces, validity, tolerances, faces by type
  2. every CANDIDATE slot wall (a plane with one wire and four edges that
     has a curved neighbour), with its neighbours: type, radius, how well
     the edge is G1 (largest normal angle along it), and the distance to
     the opposite parallel wall (is the slot narrower than 2 x offset?)
  3. for each candidate: the offset at +1, +0.5, +0.1, +0.01, -0.1, -0.5
     and -1 mm on the ORIGINAL shape, then on a UnifySameDomain copy and
     on a ShapeFix copy -- volume change and result, or 'FAILED'

Paste the whole output back.
"""
import math
import os
import sys

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
from OCP.ShapeFix import ShapeFix_Shape
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import (TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED,
                        TopAbs_SOLID, TopAbs_WIRE)
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.BRepAdaptor import BRepAdaptor_Curve

import face_offset

DISTANCES = (1.0, 0.5, 0.1, 0.01, -0.1, -0.5, -1.0)


def explore(shape, kind):
    return face_offset._explore(shape, kind)


def area(face):
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, p)
    return p.Mass(), p.CentreOfMass()


def outward_normal_at(face, pt):
    surf = BRep_Tool.Surface_s(face)
    proj = GeomAPI_ProjectPointOnSurf(pt, surf)
    if proj.NbPoints() < 1:
        return None
    u, v = proj.LowerDistanceParameters()
    props = GeomLProp_SLProps(surf, u, v, 1, 1.0e-6)
    if not props.IsNormalDefined():
        return None
    n = props.Normal()
    if face.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    return n


def max_normal_angle(edge, f1, f2):
    """Largest angle (degrees) between the two faces' outward normals at
    5 points along `edge`: 0 = perfectly G1."""
    crv = BRepAdaptor_Curve(edge)
    t0, t1 = crv.FirstParameter(), crv.LastParameter()
    worst = 0.0
    for k in range(5):
        pt = crv.Value(t0 + (k + 0.5) / 5.0 * (t1 - t0))
        n1, n2 = outward_normal_at(f1, pt), outward_normal_at(f2, pt)
        if n1 is None or n2 is None:
            return None
        d = max(-1.0, min(1.0, n1.Dot(n2)))
        worst = max(worst, math.degrees(math.acos(d)))
    return worst


def surf_desc(face):
    s = BRepAdaptor_Surface(face)
    t = s.GetType()
    if t == GeomAbs_Cylinder:
        c = s.Cylinder()
        a = c.Axis().Direction()
        return (f"Cylinder r={c.Radius():.4f} axis=({a.X():+.3f},"
                f"{a.Y():+.3f},{a.Z():+.3f})")
    if t == GeomAbs_Plane:
        d = s.Plane().Axis().Direction()
        if face.Orientation() == TopAbs_REVERSED:
            d = d.Reversed()
        return f"Plane n=({d.X():+.3f},{d.Y():+.3f},{d.Z():+.3f})"
    return t.name


def report_part(shape):
    print("== 1. the part ==")
    faces = [TopoDS.Face_s(f) for f in explore(shape, TopAbs_FACE)]
    print(f"solids {len(explore(shape, TopAbs_SOLID))}, faces {len(faces)}, "
          f"valid {BRepCheck_Analyzer(shape).IsValid()}, volume "
          f"{face_offset.volume(shape):.4f}")
    st = ShapeAnalysis_ShapeTolerance()
    print(f"tolerance: max {st.Tolerance(shape, 1):.3g}, "
          f"avg {st.Tolerance(shape, 0):.3g}, min {st.Tolerance(shape, -1):.3g}")
    kinds = {}
    for f in faces:
        k = BRepAdaptor_Surface(f).GetType().name
        kinds[k] = kinds.get(k, 0) + 1
    print("faces by type:", dict(sorted(kinds.items())))
    for i, f in enumerate(faces):
        a, _c = area(f)
        print(f"  face {i:2d}: {surf_desc(f):55s} area {a:9.3f}")
    return faces


def candidates(shape, faces):
    emap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, emap)
    out = []
    for i, f in enumerate(faces):
        if BRepAdaptor_Surface(f).GetType() != GeomAbs_Plane:
            continue
        if len(explore(f, TopAbs_WIRE)) != 1 or \
                len(explore(f, TopAbs_EDGE)) != 4:
            continue
        curved = False
        for e in explore(f, TopAbs_EDGE):
            e = TopoDS.Edge_s(e)
            for g in emap.FindFromKey(e):
                g = TopoDS.Face_s(g)
                if not g.IsSame(f) and BRepAdaptor_Surface(g).GetType() \
                        != GeomAbs_Plane:
                    curved = True
        if curved:
            out.append(i)
    return out, emap


def describe_candidate(i, faces, emap):
    f = faces[i]
    a, c = area(f)
    print(f"\n-- candidate face {i}: {surf_desc(f)}, area {a:.3f}, "
          f"centre ({c.X():.2f}, {c.Y():.2f}, {c.Z():.2f})")
    d0 = BRepAdaptor_Surface(f).Plane().Axis().Direction()
    if f.Orientation() == TopAbs_REVERSED:
        d0 = d0.Reversed()
    for e in explore(f, TopAbs_EDGE):
        e = TopoDS.Edge_s(e)
        for g in emap.FindFromKey(e):
            g = TopoDS.Face_s(g)
            if g.IsSame(f):
                continue
            try:
                cont = BRep_Tool.Continuity_s(e, f, g).name
            except Exception:
                cont = "?"
            ang = max_normal_angle(e, f, g)
            angs = "n/a" if ang is None else f"{ang:.5f} deg"
            print(f"   neighbour {surf_desc(g):55s} stored {cont:3s}, "
                  f"largest normal angle {angs}")
    # the opposite parallel wall (anti-parallel normal): the slot width
    best = None
    for j, g in enumerate(faces):
        if j == i or BRepAdaptor_Surface(g).GetType() != GeomAbs_Plane:
            continue
        dg = BRepAdaptor_Surface(g).Plane().Axis().Direction()
        if g.Orientation() == TopAbs_REVERSED:
            dg = dg.Reversed()
        if dg.Dot(d0) < -0.9999:
            _a, cg = area(g)
            dist = abs((cg.X() - c.X()) * d0.X() + (cg.Y() - c.Y()) * d0.Y()
                       + (cg.Z() - c.Z()) * d0.Z())
            if best is None or dist < best[0]:
                best = (dist, j)
    if best:
        print(f"   nearest facing parallel plane: face {best[1]}, "
              f"{best[0]:.4f} mm away (a +offset on BOTH walls closes "
              f"the slot at {best[0] / 2.0:.4f} mm)")


def find_like(shape, area0, centre0):
    """The face of `shape` with the same area and centre as the original
    candidate (faces are rebuilt by the healing variants)."""
    for f in explore(shape, TopAbs_FACE):
        f = TopoDS.Face_s(f)
        a, c = area(f)
        if abs(a - area0) < 1.0e-3 * max(1.0, area0) and \
                c.Distance(centre0) < 1.0e-3:
            return f
    return None


def try_offsets(label, shape, face):
    v0 = face_offset.volume(shape)
    for dist in DISTANCES:
        chain = len(face_offset.tangent_chain(shape, [face]))
        try:
            res, msg = face_offset.offset_faces(shape, [face], dist)
        except Exception as e:
            res, msg = None, f"{type(e).__name__}: {e}"
        if res is None:
            print(f"   {label:9s} {dist:+6.2f} mm  chain {chain}: "
                  f"FAILED  ({msg[:70]})")
        else:
            dv = face_offset.volume(res) - v0
            print(f"   {label:9s} {dist:+6.2f} mm  chain {chain}: ok, "
                  f"volume change {dv:+.4f}"
                  f"{'  [' + msg + ']' if msg else ''}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.expanduser("~"), "kodacad_offset_input.brep")
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, path, BRep_Builder()):
        print(f"could not read {path}")
        return
    print(f"reading {path}")
    faces = report_part(shape)
    cand, emap = candidates(shape, faces)
    print(f"\n== 2. candidate slot walls: {cand} ==")
    for i in cand:
        describe_candidate(i, faces, emap)
    print("\n== 3. offsets ==")
    for i in cand:
        a, c = area(faces[i])
        print(f"\n-- candidate face {i}")
        try_offsets("original", shape, faces[i])
        try:
            us = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
            us.Build()
            f2 = find_like(us.Shape(), a, c)
            if f2 is None:
                print("   unified   (the face was merged / rebuilt: skipped)")
            else:
                try_offsets("unified", us.Shape(), f2)
        except Exception as e:
            print(f"   unified   error: {type(e).__name__}: {e}")
        try:
            fx = ShapeFix_Shape(shape)
            fx.Perform()
            f3 = find_like(fx.Shape(), a, c)
            if f3 is None:
                print("   fixed     (the face was rebuilt: skipped)")
            else:
                try_offsets("fixed", fx.Shape(), f3)
        except Exception as e:
            print(f"   fixed     error: {type(e).__name__}: {e}")
    print("\ndone")


if __name__ == "__main__":
    main()
