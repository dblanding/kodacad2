"""
face_offset_server.py -- PERSISTENT offset worker for the Move Face live
preview (Session 161).

Like face_offset_worker.py (one offset per process, used by Apply) but it
keeps running, so the ~1 s cost of importing OCP is paid once instead of
on every preview. Talks to offset_preview.py over stdin/stdout, one JSON
object per line:

    {"op":"load","path":"in.brep"}                    -> {"op":"load","ok":true}
    {"op":"offset","id":7,"idx":[3,4],"value":0.5,
     "tol":1e-4,"out":"out.brep"}                      -> {"op":"offset","id":7,
                                         "done":b,"null":b,"n_faces":n,
                                         "areas":[..],"secs":t}
    {"op":"quit"}

Replies are written to a private copy of the ORIGINAL stdout; C-level
stdout (where OCCT sometimes prints) is redirected to stderr, so
diagnostics can never corrupt the protocol. If OCCT crashes natively this
process dies and the application just starts a new one.
Run with -I; self-contained (does not import KodaCAD modules).
"""
import faulthandler
import json
import os
import sys
import time

_out = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
faulthandler.enable()

from OCP.BRep import BRep_Builder
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Intersection
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape


def reply(d):
    _out.write(json.dumps(d) + "\n")
    _out.flush()


path = None


def read_shape():
    shape = TopoDS_Shape()
    ok = BRepTools.Read_s(shape, path, BRep_Builder())
    faces = []
    if ok and not shape.IsNull():
        ex = TopExp_Explorer(shape, TopAbs_FACE)
        while ex.More():
            faces.append(TopoDS.Face_s(ex.Current()))
            ex.Next()
    return shape, faces


def _flatten(shape):  # FLATTEN-S182
    """STEP round trip: bakes every sub-shape location into the geometry."""
    import shutil
    import tempfile
    from OCP.STEPControl import (STEPControl_AsIs, STEPControl_Reader,
                                 STEPControl_Writer)
    td = tempfile.mkdtemp(prefix="kodacad_flat_")
    try:
        fp = os.path.join(td, "flat.stp")
        w = STEPControl_Writer()
        w.Transfer(shape, STEPControl_AsIs)
        w.Write(fp)
        r = STEPControl_Reader()
        r.ReadFile(fp)
        r.TransferRoots()
        return r.OneShape()
    finally:
        shutil.rmtree(td, ignore_errors=True)


def _same_face_in(shape, face):  # FLATTEN-S182
    """The face of `shape` with the same area and centre as `face`, or
    None if there is none or more than one."""
    def key(f):
        p = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, p)
        c = p.CentreOfMass()
        return p.Mass(), c.X(), c.Y(), c.Z()
    a, x, y, z = key(face)
    best = None
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        m, fx, fy, fz = key(f)
        if (abs(m - a) <= 1e-6 * max(a, 1.0) + 1e-6
                and abs(fx - x) < 1e-4 and abs(fy - y) < 1e-4
                and abs(fz - z) < 1e-4):
            if best is not None:
                return None
            best = f
        ex.Next()
    return best


def try_offsets(shape, faces, idx, value, tol0):
    """Offset attempts in order of increasing desperation; returns
    (result_or_None, done, label). Session 161: the wheel's top face
    returned a NULL result on a plain attempt, so retry with looser/
    tighter tolerances and on a ShapeFix_Shape-healed copy."""
    tries = [("tol", tol0), ("flat", tol0), ("tol", 1.0e-3),
             ("tol", 1.0e-5), ("healed", tol0), ("healed", 1.0e-3)]
    healed = None
    flat = None
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
        elif kind == "flat":  # FLATTEN-S182
            try:
                if flat is None:
                    fshape = _flatten(shape)
                    flat = (fshape, {i: _same_face_in(fshape, faces[i])
                                     for i in idx})
                s, fs = flat
                if any(f is None for f in fs.values()):
                    print("[offset] flat attempt skipped: picked face not "
                          "found after the round trip",
                          file=sys.stderr, flush=True)
                    continue
            except Exception as e:
                print(f"[offset] flat attempt skipped: {e}",
                      file=sys.stderr, flush=True)
                continue
        mk = BRepOffset_MakeOffset()
        mk.Initialize(s, 0.0, tol, BRepOffset_Skin, False, False,
                      GeomAbs_Intersection, False, False)
        for i in idx:
            mk.SetOffsetOnFace(fs[i] if kind != "tol" else faces[i],
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



def do_load(msg):
    """Remember the file. The shape is RE-READ for every offset: OCCT's
    offset algorithm can modify its input (tolerances, pcurves), and a
    shape reused across calls made later offsets fail (Session 161)."""
    global path
    path = msg["path"]
    shape, faces = read_shape()
    reply({"op": "load", "ok": bool(faces)})


def do_offset(msg):
    t0 = time.time()
    shape, faces = read_shape()
    idx = msg["idx"]
    areas = []
    for i in idx:
        p = GProp_GProps()
        BRepGProp.SurfaceProperties_s(faces[i], p)
        areas.append(p.Mass())
    # Session 166: for a planar face whose neighbours are all parallel
    # to the move, extrude/cut is exact, fast and does not depend on
    # OCCT's whole-part offset analysis (which fails on tiny clipped
    # features elsewhere on the part) -- so it goes FIRST. Anything it
    # declines goes to OCCT's offset as before.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import face_offset
    res, label = face_offset.extrude_fallback(
        shape, [faces[i] for i in idx], msg["value"])
    done = res is not None
    print(f"[offset] extrusion: "
          f"{'ok' if done else 'no (' + label + ')'}",
          file=sys.stderr, flush=True)
    if res is None:
        res, done, label = try_offsets(shape, faces, idx, msg["value"],
                                       msg.get("tol", 1.0e-4))
    null = res is None
    if not null:
        BRepTools.Write_s(res, msg["out"])
    print(f"[offset server] id {msg['id']}: {len(idx)} face(s), "
          f"value {msg['value']:+.4f}, done={done}, null={null} ({label}), "
          f"{time.time() - t0:.2f}s", file=sys.stderr, flush=True)
    reply({"op": "offset", "id": msg["id"], "done": done, "null": null,
           "n_faces": len(faces), "areas": areas,
           "secs": time.time() - t0})


def main():
    for line in iter(sys.stdin.readline, ""):
        msg = None
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            op = msg.get("op")
            if op == "quit":
                break
            elif op == "load":
                do_load(msg)
            elif op == "offset":
                do_offset(msg)
        except Exception as e:
            reply({"op": "error", "id": (msg or {}).get("id")
                   if isinstance(msg, dict) else None,
                   "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
