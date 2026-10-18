"""
face_offset_worker.py -- runs ONE BRepOffset_MakeOffset call in its own
process (Session 158).

Why: OCCT's offset algorithm can crash the whole Python process with a
native fault (no Python exception, nothing in the terminal) on some
geometry -- Doug's filleted geneva wheel did exactly that at 0.5 mm. A
native crash cannot be caught in-process. Running the call here means a
crash only kills this short-lived worker; face_offset.py sees the exit
code and reports "OpenCascade crashed on this offset" while the
application and the document stay untouched.

Usage (called by face_offset.py, not by hand):
    python -I face_offset_worker.py IN.brep OUT.brep "[face indices]" VALUE TOL

Self-contained on purpose: run with -I (isolated), so it cannot import
KodaCAD's own modules. Prints ONE JSON line to stdout:
    {"done": bool, "n_faces": int, "areas": [..picked face areas..]}
and writes the raw offset result to OUT.brep when done.
"""
import faulthandler
import json
import sys

faulthandler.enable()   # a native fault prints the Python stack to stderr

from OCP.BRep import BRep_Builder
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Intersection
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape


def main(in_path, out_path, idx_json, value, tol):
    shape = TopoDS_Shape()
    BRepTools.Read_s(shape, in_path, BRep_Builder())
    faces = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        faces.append(TopoDS.Face_s(ex.Current()))
        ex.Next()
    idx = json.loads(idx_json)
    areas = []
    for i in idx:
        p = GProp_GProps()
        BRepGProp.SurfaceProperties_s(faces[i], p)
        areas.append(p.Mass())

    mk = BRepOffset_MakeOffset()
    mk.Initialize(shape, 0.0, tol, BRepOffset_Skin, False, False,
                  GeomAbs_Intersection, False, False)
    for i in idx:
        mk.SetOffsetOnFace(faces[i], value)
    mk.MakeOffsetShape()
    done = bool(mk.IsDone())
    null = True
    if done:
        res = mk.Shape()
        # IsDone() can be True while the shape is NULL (seen on a
        # filleted wheel); a null shape must never be written/used.
        null = res.IsNull()
        if not null:
            BRepTools.Write_s(res, out_path)
    print(json.dumps({"done": done, "null": null, "n_faces": len(faces),
                      "areas": areas}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3],
         float(sys.argv[4]), float(sys.argv[5]))
