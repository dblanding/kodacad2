"""probe_slot_offset2.py -- is it the SLOT, or the whole PART?

Session 180, follow-up to probe_slot_offset.py. Its output showed the slot
itself is fine (10 mm wide, perfectly G1 round ends, valid part, tiny
tolerances) yet the offset fails at EVERY distance, +/-0.01 .. 1 mm, also on
a UnifySameDomain copy. Suspect: the part's 8 BSpline faces (hole walls
exported as rational splines) -- OCCT's offset analyses the whole part.

This tries a +0.1 and a -0.1 mm offset of EVERY face, one at a time, and
classifies every edge by the types of the two faces it joins:

    uv run python probe_slot_offset2.py                # the saved brep
    uv run python probe_slot_offset2.py other.brep

Reading the result:
  * every face fails      -> a whole-part problem (not the slot): look at
                             the spline edges / faces in part 2
  * only some fail        -> the failing ones share something (the table
                             shows their types)
  * the flat outer faces work but the slot does not -> the slot itself
Takes about a minute (each attempt is ~1 s; a hung one is stopped after
30 s). Nothing is written (the diagnose() brep dump is switched off).
"""
import contextlib
import io
import os
import sys
import time

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape

import face_offset
import probe_slot_offset as p1

face_offset.WORKER_TIMEOUT = 30
face_offset.diagnose = lambda *a, **k: None        # no brep dump


def quiet_offset(shape, face, dist):
    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        try:
            res, msg = face_offset.offset_faces(shape, [face], dist)
        except Exception as e:
            res, msg = None, f"{type(e).__name__}: {e}"
    dt = time.time() - t0
    if res is None:
        short = "TIMEOUT" if "too long" in msg else "FAIL"
        return short, dt
    dv = face_offset.volume(res) - face_offset.volume(shape)
    return f"ok dV{dv:+.2f}", dt


def spline_info(face):
    s = BRepAdaptor_Surface(face)
    try:
        b = s.BSpline()
        return (f"deg {b.UDegree()}x{b.VDegree()}, poles "
                f"{b.NbUPoles()}x{b.NbVPoles()}, rational "
                f"{b.IsURational() or b.IsVRational()}, "
                f"Uperiodic {b.IsUPeriodic()}, Vperiodic {b.IsVPeriodic()}")
    except Exception as e:
        return f"({type(e).__name__})"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.expanduser("~"), "kodacad_offset_input.brep")
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, path, BRep_Builder()):
        print(f"could not read {path}")
        return
    faces = [TopoDS.Face_s(f) for f in p1.explore(shape, TopAbs_FACE)]
    print(f"reading {path}: {len(faces)} faces\n")

    print("== 1. every face, +0.1 and -0.1 mm ==")
    works = 0
    for i, f in enumerate(faces):
        a, _c = p1.area(f)
        plus, t1 = quiet_offset(shape, f, 0.1)
        minus, t2 = quiet_offset(shape, f, -0.1)
        works += plus.startswith("ok") + minus.startswith("ok")
        print(f"  face {i:2d} {p1.surf_desc(f)[:44]:44s} area {a:9.2f}   "
              f"+0.1: {plus:14s} -0.1: {minus:14s} ({t1 + t2:.1f}s)",
              flush=True)
    print(f"\n{works} of {2 * len(faces)} attempts worked")

    print("\n== 2. the BSpline faces ==")
    for i, f in enumerate(faces):
        if BRepAdaptor_Surface(f).GetType().name == "GeomAbs_BSplineSurface":
            a, c = p1.area(f)
            print(f"  face {i:2d} area {a:.3f} centre ({c.X():.1f}, "
                  f"{c.Y():.1f}, {c.Z():.1f}): {spline_info(f)}")

    print("\n== 3. edges by the types of the two faces they join ==")
    emap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, emap)

    def idx(face):
        return next((k for k, g in enumerate(faces) if g.IsSame(face)), -1)
    groups = {}
    spline_edges = []
    for ei in range(1, emap.Extent() + 1):
        e = TopoDS.Edge_s(emap.FindKey(ei))
        pair = [TopoDS.Face_s(x) for x in emap.FindFromIndex(ei)]
        if len(pair) != 2:
            groups[("(not 2 faces: %d)" % len(pair),)] = \
                groups.get(("(not 2 faces: %d)" % len(pair),), 0) + 1
            continue
        if pair[0].IsSame(pair[1]):
            groups[("seam",)] = groups.get(("seam",), 0) + 1
            continue
        ta = BRepAdaptor_Surface(pair[0]).GetType().name[8:]
        tb = BRepAdaptor_Surface(pair[1]).GetType().name[8:]
        try:
            cont = BRep_Tool.Continuity_s(e, pair[0], pair[1]).name[8:]
        except Exception:
            cont = "?"
        ang = p1.max_normal_angle(e, pair[0], pair[1])
        angs = "n/a" if ang is None else (
            "0" if ang < 0.01 else "90" if abs(ang - 90) < 0.5
            else f"{ang:.1f}")
        key = tuple(sorted((ta, tb))) + (f"stored {cont}", f"angle {angs}")
        groups[key] = groups.get(key, 0) + 1
        if "BSplineSurface" in (ta, tb):
            spline_edges.append((idx(pair[0]), idx(pair[1]), key))
    for k, n in sorted(groups.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d} x {' | '.join(k)}")
    print("\n  edges that touch a BSpline face (faces, kind):")
    for a, b, key in spline_edges:
        print(f"    faces {a:2d} / {b:2d}: {' | '.join(key)}")
    print("\ndone")


if __name__ == "__main__":
    main()
