"""
face_offset.py -- geometry for Create/Modify -> Move Face (Session 157).

No GUI and no document access here: just OCCT calls, so the logic can be
read, probed and tested on its own (see probe_offset_faces.py, whose
runs 1 and 2 established everything below).

What the probe showed (OCP 7.9, BRepOffset_MakeOffset):
  * Per-face offsets work: SetOffsetOnFace(face, value) then
    MakeOffsetShape(), with join = GeomAbs_Intersection (Arc fails every
    time) and the default offset 0.
  * The offset runs along the solid's OUTWARD face normal. So + ADDS
    material (grows a boss, narrows a slot or hole) and - REMOVES it
    (widens a slot or hole). Volumes matched hand calculation exactly
    for flat faces, a hole wall, a slot (walls + round end) and a
    chamfered neighbour (the tilted neighbour is extended correctly).
  * The offset spreads across faces joined TANGENTLY to the picked one
    (a slot's round end follows its walls; filleted edges follow the
    face they are tangent to -- and so do the whole chain of tangent
    faces around the part). tangent_chain() reports that set so the
    user can see what will move before it moves.
  * The result can come back as a SHELL, even from a valid solid
    (always when the input was a compound): as_solid() rebuilds it.
"""
import json
import os
import subprocess
import sys
import tempfile

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepTools import BRepTools
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Intersection, GeomAbs_G1
from OCP.ShapeFix import ShapeFix_Solid
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape

OFFSET_TOL = 1.0e-4     # same value the probe used successfully


def _explore(shape, kind):
    out = []
    ex = TopExp_Explorer(shape, kind)
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def count_solids(shape):
    return len(_explore(shape, TopAbs_SOLID))


def volume(shape):
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, p)
    return p.Mass()


def tangent_chain(shape, seed_faces):
    """Every face of `shape` reachable from the seed faces across edges
    where the two faces meet tangentially (G1 or better). The seeds are
    included. This is OUR estimate of what OCCT's offset will carry
    along; it is shown to the user, never used to build the result.
    Returns a list of TopoDS_Face (members of `shape`)."""
    emap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, emap)

    faces = [TopoDS.Face_s(f) for f in _explore(shape, TopAbs_FACE)]

    def index_of(face):
        for i, f in enumerate(faces):
            if f.IsSame(face):
                return i
        return -1

    # adjacency over tangent edges only
    nbrs = {i: set() for i in range(len(faces))}
    for ei in range(1, emap.Extent() + 1):
        edge = TopoDS.Edge_s(emap.FindKey(ei))
        pair = [TopoDS.Face_s(f) for f in emap.FindFromIndex(ei)]
        if len(pair) != 2 or pair[0].IsSame(pair[1]):
            continue
        try:
            cont = BRep_Tool.Continuity_s(edge, pair[0], pair[1])
        except Exception:
            continue
        if cont.value >= GeomAbs_G1.value:
            a, b = index_of(pair[0]), index_of(pair[1])
            if a >= 0 and b >= 0:
                nbrs[a].add(b)
                nbrs[b].add(a)

    start = [i for i in (index_of(f) for f in seed_faces) if i >= 0]
    seen = set(start)
    stack = list(start)
    while stack:
        i = stack.pop()
        for j in nbrs[i]:
            if j not in seen:
                seen.add(j)
                stack.append(j)
    return [faces[i] for i in sorted(seen)]


def as_solid(shape):
    """Return a solid for `shape`: the shape itself if it already holds
    one, else a solid rebuilt from its (first) shell. None on failure."""
    if count_solids(shape) >= 1:
        return shape
    shells = _explore(shape, TopAbs_SHELL)
    if not shells:
        return None
    try:
        return ShapeFix_Solid().SolidFromShell(TopoDS.Shell_s(shells[0]))
    except Exception as e:
        print(f"[face_offset] SolidFromShell failed: {e}")
        return None


WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "face_offset_worker.py")
WORKER_TIMEOUT = 120      # seconds

NO_RESULT = ("OpenCascade could not build an offset for these faces at "
             "this distance (it returned no shape). This can happen when "
             "the picked face is tangent to fillets that run into other "
             "features. Nothing was changed; try a different face or "
             "distance, or remove the fillets first (Defeaturing).")



def _raw_offset_inprocess(shape, faces, value):
    """The offset call in THIS process. A native crash here takes the
    application down -- used only as a fallback (see _raw_offset)."""
    mk = BRepOffset_MakeOffset()
    mk.Initialize(shape, 0.0, OFFSET_TOL, BRepOffset_Skin, False, False,
                  GeomAbs_Intersection, False, False)
    for f in faces:
        mk.SetOffsetOnFace(f, value)
    mk.MakeOffsetShape()
    if not mk.IsDone():
        return None, ("OpenCascade could not offset these faces by that "
                      "distance (the feature may collapse, or a "
                      "neighbouring face can't be extended).")
    res = mk.Shape()
    if res.IsNull():
        return None, NO_RESULT
    return res, ""


def _raw_offset_isolated(shape, faces, value):
    """The offset call in a short-lived WORKER PROCESS (Session 158):
    OCCT's offset can crash the whole process with no Python exception;
    here that only kills the worker. Returns (result, message); result
    None with a message on any failure, a crash included. Raises
    OSError only if the worker cannot be started at all."""
    all_faces = [TopoDS.Face_s(f) for f in _explore(shape, TopAbs_FACE)]
    idx = []
    for f in faces:
        hit = [i for i, g in enumerate(all_faces) if g.IsSame(f)]
        if not hit:
            return None, "A picked face is not part of this solid."
        idx.append(hit[0])
    areas_here = []
    for i in idx:
        p = GProp_GProps()
        BRepGProp.SurfaceProperties_s(all_faces[i], p)
        areas_here.append(p.Mass())

    with tempfile.TemporaryDirectory(prefix="kodacad_offset_") as td:
        in_path = os.path.join(td, "in.brep")
        out_path = os.path.join(td, "out.brep")
        print("[face_offset] writing shape for the worker", flush=True)
        BRepTools.Write_s(shape, in_path)
        print("[face_offset] starting worker", flush=True)
        cmd = [sys.executable, "-I", WORKER, in_path, out_path,
               json.dumps(idx), repr(float(value)), repr(OFFSET_TOL)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=WORKER_TIMEOUT)
        except subprocess.TimeoutExpired:
            print(f"[face_offset] worker timed out after "
                  f"{WORKER_TIMEOUT}s")
            return None, ("OpenCascade took too long on this offset and "
                          "was stopped. The part was not changed.")
        print(f"[face_offset] worker finished, exit code "
              f"{proc.returncode}", flush=True)
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-12:]
            print(f"[face_offset] worker died: exit code "
                  f"{proc.returncode}; stderr tail: {tail}")
            return None, ("OpenCascade crashed on this offset (the "
                          "application is fine and the part was not "
                          "changed). Try a smaller distance or "
                          "different faces.")
        try:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception:
            print(f"[face_offset] worker gave no usable answer: "
                  f"{proc.stdout!r} {proc.stderr!r}")
            return None, "The offset worker gave no answer."
        # The worker re-read the shape from a file: make sure it saw the
        # SAME faces we picked (same count, same areas).
        if info["n_faces"] != len(all_faces) or any(
                abs(a - b) > 1.0e-6 * max(1.0, abs(b))
                for a, b in zip(info["areas"], areas_here)):
            print(f"[face_offset] worker face mismatch: "
                  f"{info['n_faces']} vs {len(all_faces)}, "
                  f"areas {info['areas']} vs {areas_here}")
            return None, ("Internal error: the offset worker saw "
                          "different faces than the ones picked.")
        if not info["done"]:
            return None, ("OpenCascade could not offset these faces by "
                          "that distance (the feature may collapse, or "
                          "a neighbouring face can't be extended).")
        if info.get("null"):
            print("[face_offset] worker: IsDone() but the result shape "
                  "is NULL")
            return None, NO_RESULT
        result = TopoDS_Shape()
        read_ok = BRepTools.Read_s(result, out_path, BRep_Builder())
        if not read_ok or result.IsNull():
            print(f"[face_offset] could not read the worker's result "
                  f"(Read_s={read_ok})")
            return None, NO_RESULT
        return result, ""


def _raw_offset(shape, faces, value):
    try:
        return _raw_offset_isolated(shape, faces, value)
    except OSError as e:
        print(f"[face_offset] could not start worker ({e}); running the "
              f"offset in-process (a native crash would end the app)")
        return _raw_offset_inprocess(shape, faces, value)


def offset_faces(shape, faces, value):
    """Offset each of `faces` (members of `shape`) by `value` mm along
    its outward normal (+ adds material, - removes it).

    The OCCT call runs in a worker process so that a native crash in
    the offset algorithm cannot take the application down.

    Returns (new_shape, message). new_shape is None on failure and
    message says why, in words fit for the status bar. On success the
    shape is a valid SOLID (not yet healed beyond that) and `message`
    is an empty string."""
    n_solids = count_solids(shape)
    if n_solids != 1:
        return None, (f"Move Face needs a part with exactly one solid "
                      f"(this one has {n_solids}).")
    if not faces:
        return None, "No faces to move."
    if abs(value) < 1.0e-9:
        return None, "Distance is zero -- nothing to do."
    try:
        result, msg = _raw_offset(shape, faces, value)
    except Exception as e:
        print(f"[face_offset] offset failed: {type(e).__name__}: {e}")
        return None, ("OpenCascade could not offset these faces by that "
                      "distance -- try a smaller distance.")
    if result is None or result.IsNull():
        # (ShapeType() on a NULL shape is a native crash -- Session 159)
        return None, msg or NO_RESULT
    print(f"[face_offset] offset {value:+.4f} mm on {len(faces)} "
          f"picked face(s): result {result.ShapeType().name} with "
          f"{len(_explore(result, TopAbs_SOLID))} solid(s), "
          f"{len(_explore(result, TopAbs_SHELL))} shell(s), "
          f"{len(_explore(result, TopAbs_FACE))} face(s)")
    solid = as_solid(result)
    if solid is None:
        return None, ("The offset result did not close into a solid. "
                      "That usually means the distance is too large for "
                      "the faces that move with the picked one (a slot, "
                      "a concave curve or a fillet would collapse) -- "
                      "try a smaller distance.")
    if not BRepCheck_Analyzer(solid).IsValid():
        return solid, "invalid"        # caller may try to heal it
    return solid, ""


def sane(old_shape, new_shape):
    """Cheap plausibility check on a finished result: positive volume
    and at least one face. Returns (ok, old_volume, new_volume)."""
    v0, v1 = volume(old_shape), volume(new_shape)
    n_faces = len(_explore(new_shape, TopAbs_FACE))
    return (v1 > 0.0 and n_faces > 0), v0, v1
