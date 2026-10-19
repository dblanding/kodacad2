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
from OCP.TopAbs import (TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL,
                        TopAbs_SOLID, TopAbs_WIRE)
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


def narrow_faces(shape, max_report=6, rel=0.01):
    """Faces of `shape` that are unusually narrow -- slivers, stubs,
    forgotten chamfers -- or that touch a very short edge (width/length
    reported is whichever triggered it). OCCT's offset analyses the WHOLE part, and one
    such face anywhere can make it return nothing for any picked face
    (Session 162: a 2.7 mm leftover chamfer on the geneva wheel).
    Width = 2 * area / perimeter; reported when below `rel` x the part's
    bounding-box diagonal. Returns [(width_mm, face)], narrowest first."""
    try:
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        bb = Bnd_Box()
        BRepBndLib.Add_s(shape, bb)
        lo, hi = bb.CornerMin(), bb.CornerMax()
        diag = ((hi.X() - lo.X()) ** 2 + (hi.Y() - lo.Y()) ** 2 +
                (hi.Z() - lo.Z()) ** 2) ** 0.5
    except Exception:
        return []
    thr = rel * diag
    out = []
    seen = []
    for f in _explore(shape, TopAbs_FACE):
        f = TopoDS.Face_s(f)
        try:
            pa, pl = GProp_GProps(), GProp_GProps()
            BRepGProp.SurfaceProperties_s(f, pa)
            BRepGProp.LinearProperties_s(f, pl)
            area, per = pa.Mass(), pl.Mass()
            if per <= 0.0:
                continue
            w = 2.0 * area / per
        except Exception:
            continue
        if w < thr:
            out.append((w, f))
            seen.append(f)
    # Very SHORT EDGES (Session 165): a countersink that breaks 0.04 mm
    # into a neighbouring slot leaves edges a fraction of a millimetre
    # long on otherwise ordinary faces -- no narrow face to find.
    try:
        emap = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE,
                                       emap)
        edge_thr = 2.0 * thr      # 2% of the diagonal
        for ei in range(1, emap.Extent() + 1):
            e = TopoDS.Edge_s(emap.FindKey(ei))
            pe = GProp_GProps()
            BRepGProp.LinearProperties_s(e, pe)
            ln = pe.Mass()
            if ln >= edge_thr or ln <= 0.0:
                continue
            for g in emap.FindFromIndex(ei):
                g = TopoDS.Face_s(g)
                if not any(g.IsSame(x) for x in seen):
                    seen.append(g)
                    out.append((ln, g))
    except Exception as e:
        print(f"[face_offset] short-edge check failed: {e}")
    out.sort(key=lambda t: t[0])
    return out[:max_report]


def diagnose(shape, faces):
    """Print what is special about `faces` of `shape` (called when the
    offset returns nothing): validity, tolerances, the picked faces'
    surface types and edge neighbours with their continuity."""
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
        print("[face_offset] DIAG shape valid:",
              BRepCheck_Analyzer(shape).IsValid())
        st = ShapeAnalysis_ShapeTolerance()
        print(f"[face_offset] DIAG max tolerance "
              f"{st.Tolerance(shape, 1):.3g}")
        emap = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE,
                                       emap)
        for f in faces:
            sf = BRepAdaptor_Surface(f)
            nwire = len(_explore(f, TopAbs_WIRE))
            nedge = len(_explore(f, TopAbs_EDGE))
            print(f"[face_offset] DIAG picked: {sf.GetType().name}, "
                  f"{nwire} wire(s), {nedge} edge(s)")
            kinds = {}
            for e in _explore(f, TopAbs_EDGE):
                e = TopoDS.Edge_s(e)
                if not emap.Contains(e):
                    continue
                for g in emap.FindFromKey(e):
                    g = TopoDS.Face_s(g)
                    if g.IsSame(f):
                        continue
                    try:
                        c = BRep_Tool.Continuity_s(e, f, g).name
                    except Exception:
                        c = "?"
                    k = (BRepAdaptor_Surface(g).GetType().name, c)
                    kinds[k] = kinds.get(k, 0) + 1
            for (t, c), n in sorted(kinds.items()):
                print(f"[face_offset] DIAG   neighbour {t} across "
                      f"{c} edge x{n}")
        try:
            BRepTools.Write_s(shape, os.path.join(
                os.path.expanduser("~"), "kodacad_offset_input.brep"))
            print("[face_offset] DIAG input saved to "
                  "~/kodacad_offset_input.brep")
        except Exception as e:
            print(f"[face_offset] DIAG could not save input: {e}")
    except Exception as e:
        print(f"[face_offset] DIAG failed: {type(e).__name__}: {e}")


def _extrusion_normal(shape, face, emap):
    """Outward unit normal (gp_Dir) of a PLANAR `face` whose every
    neighbour is "extrusion compatible" (a plane parallel to the normal
    or a cylinder whose axis is parallel to it), else None. For such a
    face, moving it is exactly the same as extruding it (fuse) or
    cutting a prism from it."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_REVERSED
    sf = BRepAdaptor_Surface(face)
    if sf.GetType() != GeomAbs_Plane:
        return None
    d = sf.Plane().Axis().Direction()
    if face.Orientation() == TopAbs_REVERSED:
        d = d.Reversed()
    for e in _explore(face, TopAbs_EDGE):
        e = TopoDS.Edge_s(e)
        if not emap.Contains(e):
            return None
        for g in emap.FindFromKey(e):
            g = TopoDS.Face_s(g)
            if g.IsSame(face):
                continue
            sg = BRepAdaptor_Surface(g)
            t = sg.GetType()
            if t == GeomAbs_Plane:
                if abs(sg.Plane().Axis().Direction().Dot(d)) > 1.0e-6:
                    return None
            elif t == GeomAbs_Cylinder:
                if abs(abs(sg.Cylinder().Axis().Direction().Dot(d)) - 1.0) \
                        > 1.0e-6:
                    return None
            else:
                return None
    return d


def _extrude_fallback_once(shape, faces, value, flip):
    """Fallback for when OCCT's offset returns nothing (seen on the
    geneva wheel). For PLANAR picked faces whose neighbours are all
    parallel to the face normal (vertical walls), moving the face by
    `value` is an extrusion: value > 0 fuses a prism on the face,
    value < 0 cuts one into the part. Volume must change by exactly
    area * value, else the situation was not that simple and we give
    up (returns (None, reason)). Returns (result_shape, label)."""
    try:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut
        from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
        from OCP.gp import gp_Vec
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf
        emap = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE,
                                       emap)
        v0 = volume(shape)
        # NO overlap margin (Session 166): a 0.001 mm overlap left
        # 0.001 mm sliver rings on every hole wall the prism crossed
        # (34 faces instead of 30), which then blocked OCCT's offset.
        margin = 0.0
        cur = shape
        expect = 0.0
        for f in faces:
            n = _extrusion_normal(shape, f, emap)
            if n is None:
                return None, "not extrusion-compatible"
            if flip:
                n = n.Reversed()
            p = GProp_GProps()
            BRepGProp.SurfaceProperties_s(f, p)
            area = p.Mass()
            # start a hair on the far side so the tool overlaps solid
            # (fuse) or void (cut) instead of sharing the face plane
            back = -margin if value > 0 else margin
            tr = gp_Trsf()
            tr.SetTranslation(gp_Vec(n.X() * back, n.Y() * back,
                                     n.Z() * back))
            base = BRepBuilderAPI_Transform(f, tr, True).Shape()
            length = value + (-back)          # signed along n
            vec = gp_Vec(n.X() * length, n.Y() * length, n.Z() * length)
            prism = BRepPrimAPI_MakePrism(base, vec).Shape()
            op = (BRepAlgoAPI_Fuse(cur, prism) if value > 0
                  else BRepAlgoAPI_Cut(cur, prism))
            if not op.IsDone():
                return None, "boolean failed"
            cur = op.Shape()
            expect += area * value
        us = ShapeUpgrade_UnifySameDomain(cur, True, True, True)
        us.Build()
        cur = us.Shape()
        sols = _explore(cur, TopAbs_SOLID)
        if len(sols) != 1:
            return None, f"result has {len(sols)} solids"
        cur = TopoDS.Solid_s(sols[0])
        v1 = volume(cur)
        err = abs((v1 - v0) - expect)
        if err > 1.0e-4 * max(abs(expect), 1.0) + 1.0e-6:
            return None, (f"volume change {v1 - v0:.6g} != expected "
                          f"{expect:.6g}")
        return cur, "extrusion fallback"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def extrude_fallback(shape, faces, value):
    """See _extrude_fallback_once. The outward direction is worked out
    from the face orientation; if that is wrong for some face the volume
    check rejects the result, so the opposite direction is tried too
    (Session 165: the first real use of the fallback did not rescue a
    plain planar leg face)."""
    res, label = _extrude_fallback_once(shape, faces, value, False)
    if res is not None or label == "not extrusion-compatible":
        return res, label
    res2, label2 = _extrude_fallback_once(shape, faces, value, True)
    if res2 is not None:
        return res2, label2 + " (flipped)"
    return None, label


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
        for ln in (proc.stderr or "").splitlines():
            if ln.startswith("[offset"):
                print(ln, flush=True)
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
            diagnose(shape, faces)
            return None, ("OpenCascade could not offset these faces by "
                          "that distance (the feature may collapse, or "
                          "a neighbouring face can't be extended).")
        if info.get("null"):
            print("[face_offset] worker: no usable result")
            diagnose(shape, faces)
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
    return finish_offset(result, msg, value, len(faces))


def finish_offset(result, msg, value, n_faces):
    """Turn a RAW offset result (from _raw_offset, or from the live
    preview's server) into the final solid. Same return contract as
    offset_faces: (solid, "") | (solid, "invalid") | (None, message)."""
    if result is None or result.IsNull():
        # (ShapeType() on a NULL shape is a native crash -- Session 159)
        return None, msg or NO_RESULT
    print(f"[face_offset] offset {value:+.4f} mm on {n_faces} "
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


def face_indices(shape, faces):
    """Indices of `faces` in shape's face order (TopExp_Explorer order,
    the same order the worker processes see after a BREP round trip).
    None if any face is not part of shape."""
    all_faces = [TopoDS.Face_s(f) for f in _explore(shape, TopAbs_FACE)]
    idx = []
    for f in faces:
        hit = [i for i, g in enumerate(all_faces) if g.IsSame(f)]
        if not hit:
            return None
        idx.append(hit[0])
    return idx


def face_areas(shape, idx):
    """(n_faces, [area of face i for i in idx]) -- the cross-check that
    a worker which re-read the shape from a file sees the same faces."""
    all_faces = [TopoDS.Face_s(f) for f in _explore(shape, TopAbs_FACE)]
    areas = []
    for i in idx:
        p = GProp_GProps()
        BRepGProp.SurfaceProperties_s(all_faces[i], p)
        areas.append(p.Mass())
    return len(all_faces), areas


def same_faces(info_n, info_areas, n, areas):
    return info_n == n and all(
        abs(a - b) <= 1.0e-6 * max(1.0, abs(b))
        for a, b in zip(info_areas, areas))


def sane(old_shape, new_shape):
    """Cheap plausibility check on a finished result: positive volume
    and at least one face. Returns (ok, old_volume, new_volume)."""
    v0, v1 = volume(old_shape), volume(new_shape)
    n_faces = len(_explore(new_shape, TopAbs_FACE))
    return (v1 > 0.0 and n_faces > 0), v0, v1
