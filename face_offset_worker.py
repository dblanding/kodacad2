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


def try_offsets(shape, faces, idx, value, tol0):
    """Offset attempts in order of increasing desperation; returns
    (result_or_None, done, label). Session 161: the wheel's top face
    returned a NULL result on a plain attempt, so retry with looser/
    tighter tolerances and on a ShapeFix_Shape-healed copy."""
    tries = [("tol", tol0), ("tol", 1.0e-3), ("tol", 1.0e-5),
             ("healed", tol0), ("healed", 1.0e-3)]
    healed = None
    any_done = False
    for kind, tol in tries:
        s, fs = shape, faces
        if kind == "healed":
            try:
                if healed is None:
                    from OCP.ShapeFix import ShapeFix_Shape
                    fx = ShapeFix_Shape(shape)
                    fx.Perform()
                    healed = (fx.Shape(), fx.Context())
                hs, ctx = healed
                s = hs
                fs = {i: TopoDS.Face_s(ctx.Apply(faces[i])) for i in idx}
            except Exception as e:
                print(f"[offset] heal attempt skipped: {e}",
                      file=sys.stderr, flush=True)
                continue
        mk = BRepOffset_MakeOffset()
        mk.Initialize(s, 0.0, tol, BRepOffset_Skin, False, False,
                      GeomAbs_Intersection, False, False)
        for i in idx:
            mk.SetOffsetOnFace(fs[i] if kind == "healed" else faces[i],
                               value)
        mk.MakeOffsetShape()
        done = bool(mk.IsDone())
        any_done = any_done or done
        res = mk.Shape() if done else None
        ok = res is not None and not res.IsNull()
        print(f"[offset] attempt {kind} tol={tol:g}: done={done} "
              f"result={'yes' if ok else 'NULL/none'}",
              file=sys.stderr, flush=True)
        if ok:
            return res, True, f"{kind} tol={tol:g}"
    return None, any_done, ""


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

    res, done, label = try_offsets(shape, faces, idx, value, tol)
    null = res is None
    if not null:
        BRepTools.Write_s(res, out_path)
        print(f"[offset worker] succeeded with {label}", file=sys.stderr,
              flush=True)
    print(json.dumps({"done": done, "null": null, "n_faces": len(faces),
                      "areas": areas}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3],
         float(sys.argv[4]), float(sys.argv[5]))
