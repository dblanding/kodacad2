"""Standalone Shell test, completely independent of KodaCAD's own
code -- run with `uv run python test_shell_standalone.py` from the
kodacad2 directory.

Purpose: isolate whether 'BRep_API: command not done' is a genuine
OCCT/system-level issue (this script fails too, with zero KodaCAD
code involved at all) or something specific to how KodaCAD builds or
hands off its own shapes (this script succeeds, meaning the problem
is somewhere in kodacad.py's own shell()/shellC(), not underneath it).

This mirrors kodacad.py's own shell() call signature exactly:
mkShell.MakeThickSolidByJoin(workPart, faces, -shellT, 1.0e-3)
"""
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopTools import TopTools_ListOfShape

print("Building a simple 20x20x20 box...")
box = BRepPrimAPI_MakeBox(20.0, 20.0, 20.0).Shape()

print("Picking its first face as the one to remove...")
faces = TopTools_ListOfShape()
exp = TopExp_Explorer(box, TopAbs_FACE)
first_face = exp.Current()
faces.Append(first_face)

print("Attempting Shell (1mm wall thickness)...")
try:
    mkShell = BRepOffsetAPI_MakeThickSolid()
    mkShell.MakeThickSolidByJoin(box, faces, -1.0, 1.0e-3)
    result = mkShell.Shape()
    print(f"SUCCESS -- Shell completed. Result ShapeType={result.ShapeType()}")
except Exception as e:
    print(f"FAILED -- {type(e).__name__}: {e}")
