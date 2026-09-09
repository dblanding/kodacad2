"""Standalone Shell test round 2 -- Doug's own observation: Shell has
been failing specifically on shapes with round/cylindrical faces
(cup, can, bottle neck), but a plain box worked, both in the earlier
standalone test and directly in KodaCAD. This tests a cylinder
alongside a box, side by side, in the same run -- completely
independent of any KodaCAD code -- to confirm or rule out
"round/cylindrical geometry specifically" as the actual pattern.

Run with `uv run python test_shell_round2.py` from the kodacad2
directory.
"""
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopTools import TopTools_ListOfShape


def try_shell(shape, label, thickness=1.0):
    faces = TopTools_ListOfShape()
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    first_face = exp.Current()
    faces.Append(first_face)
    print(f"--- {label} ---")
    try:
        mkShell = BRepOffsetAPI_MakeThickSolid()
        mkShell.MakeThickSolidByJoin(shape, faces, -thickness, 1.0e-3)
        result = mkShell.Shape()
        print(f"SUCCESS -- ShapeType={result.ShapeType()}")
    except Exception as e:
        print(f"FAILED -- {type(e).__name__}: {e}")
    print()


print("Building a 20x20x20 box...")
box = BRepPrimAPI_MakeBox(20.0, 20.0, 20.0).Shape()
try_shell(box, "Box (flat faces only)")

print("Building a cylinder, radius 10, height 20...")
cyl = BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape()
try_shell(cyl, "Cylinder (one round side face, two flat circular caps)")
