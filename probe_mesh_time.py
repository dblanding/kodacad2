"""probe_mesh_time.py -- why does draw_shape spend 17 s meshing 10 faces?

Session 181. draw_shape pre-meshes every displayed part with
BRepMesh_IncrementalMesh(shape, 0.1, False, 0.5, True) (0.1 mm absolute
deviation, 0.5 rad angular, parallel). On the fused 'anchor-top_1' (four
8 in bars up to 15 ft long, 10 faces after NurbsConvert) that one call took
17.4 s of a 20 s draw. This times the same call at several deviations, on
the analytic shape and on its NurbsConvert'ed twin, and counts triangles.

    uv run python probe_mesh_time.py FILE.stp [FILE2 ...]

FILE: a STEP file holding the slow part -- File -> Export the fused
anchor-top_1 (a .brep also works). Every solid in it is tried. Read-only;
nothing is written. A run that takes over 60 s is not stopped, so for the
0.1 mm case on a slow part expect about 20 s per line.
"""
import sys
import time

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy, BRepBuilderAPI_NurbsConvert
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape

DEVIATIONS = (0.1, 0.3, 1.0, 3.0)      # mm, absolute (relative=False)


def load(path):
    if path.lower().endswith((".brep", ".brp")):
        s = TopoDS_Shape()
        BRepTools.Read_s(s, path, BRep_Builder())
        return s
    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_RetDone:
        raise RuntimeError(f"cannot read {path}")
    r.TransferRoots()
    return r.OneShape()


def solids(shape):
    ex, out = TopExp_Explorer(shape, TopAbs_SOLID), []
    while ex.More():
        out.append(TopoDS.Solid_s(ex.Current()))
        ex.Next()
    return out or [shape]


def faces(shape):
    ex, out = TopExp_Explorer(shape, TopAbs_FACE), []
    while ex.More():
        out.append(TopoDS.Face_s(ex.Current()))
        ex.Next()
    return out


def triangles(shape):
    n = 0
    for f in faces(shape):
        t = BRep_Tool.Triangulation_s(f, TopLoc_Location())
        if t is not None:
            n += t.NbTriangles()
    return n


def timed_mesh(shape, deflection, parallel=True):
    s = BRepBuilderAPI_Copy(shape, True, True).Shape()
    t0 = time.monotonic()
    BRepMesh_IncrementalMesh(s, deflection, False, 0.5, parallel)
    return time.monotonic() - t0, triangles(s)


def main(paths):
    for path in paths:
        print(f"\n== {path}")
        for i, sol in enumerate(solids(load(path))):
            box = Bnd_Box()
            BRepBndLib.Add_s(sol, box)
            lo, hi = box.CornerMin(), box.CornerMax()
            diag = ((hi.X() - lo.X()) ** 2 + (hi.Y() - lo.Y()) ** 2
                    + (hi.Z() - lo.Z()) ** 2) ** 0.5
            print(f"-- solid {i}: {len(faces(sol))} faces, bbox diagonal "
                  f"{diag:.0f} mm")
            t0 = time.monotonic()
            nurbs = BRepBuilderAPI_NurbsConvert(
                BRepBuilderAPI_Copy(sol, True, True).Shape(), True).Shape()
            print(f"   NurbsConvert {time.monotonic() - t0:.2f} s -> "
                  f"{len(faces(nurbs))} faces")
            for label, shp in (("analytic", sol), ("nurbs   ", nurbs)):
                for d in DEVIATIONS:
                    try:
                        dt, tri = timed_mesh(shp, d)
                        print(f"   {label} deviation {d:>4} mm: {dt:6.2f} s, "
                              f"{tri:>9} triangles", flush=True)
                    except Exception as e:
                        print(f"   {label} deviation {d:>4} mm: "
                              f"{type(e).__name__}: {e}")
    print("\ndone")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
    else:
        main(sys.argv[1:])
