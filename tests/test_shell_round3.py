"""Standalone Shell test round 3 -- refining round 2's cylinder
result. TopExp_Explorer's traversal order isn't something explicitly
controlled, so round 2 doesn't actually confirm WHICH face of the
cylinder got picked -- possibly the curved, lateral side face, not
one of the flat, circular caps the Bottle tutorial's own real
workflow opens ("select the top face of the neck"). Those could be
genuinely different operations with different results. This
identifies each face by its actual surface type (GeomAbs_Plane vs
GeomAbs_Cylinder) and tests each explicitly, rather than guessing
from traversal order.

Run with `uv run python test_shell_round3.py` from the kodacad2
directory.
"""
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopTools import TopTools_ListOfShape
from OCP.TopoDS import TopoDS


def try_shell(shape, face, label, thickness=1.0):
    faces = TopTools_ListOfShape()
    faces.Append(face)
    print(f"--- {label} ---")
    try:
        mkShell = BRepOffsetAPI_MakeThickSolid()
        mkShell.MakeThickSolidByJoin(shape, faces, -thickness, 1.0e-3)
        result = mkShell.Shape()
        print(f"SUCCESS -- ShapeType={result.ShapeType()}")
    except Exception as e:
        print(f"FAILED -- {type(e).__name__}: {e}")
    print()


print("Building a cylinder, radius 10, height 20...")
cyl = BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape()

flat_face = None
curved_face = None
exp = TopExp_Explorer(cyl, TopAbs_FACE)
while exp.More():
    face = TopoDS.Face_s(exp.Current())
    surf = BRepAdaptor_Surface(face)
    st = surf.GetType()
    if st == GeomAbs_Plane and flat_face is None:
        flat_face = face
    elif st == GeomAbs_Cylinder and curved_face is None:
        curved_face = face
    exp.Next()

print(f"Found flat face: {flat_face is not None}, "
     f"curved face: {curved_face is not None}\n")

if flat_face is not None:
    try_shell(cyl, flat_face,
             "Cylinder, opening a FLAT circular cap (matches the "
             "Bottle tutorial's own real workflow)")
if curved_face is not None:
    try_shell(cyl, curved_face,
             "Cylinder, opening the CURVED lateral side face")
