"""
probe_offset_faces.py -- can OCCT move individual faces of a solid and
let the neighbours follow? (Session 156)

Doug's question: instead of automating workarounds (copy + move + fuse),
is there OCCT functionality that offsets chosen faces by different
amounts -- the kernel call behind a CoCreate-style "move face"? An OCCT
forum thread points at BRepOffset_MakeOffset.SetOffsetOnFace(face, value),
the class BRepOffsetAPI_MakeOffsetShape (and our Shell command's
MakeThickSolid) wrap. The thread leaves open which settings work, which
SIGN means "into the material", and what happens to faces that are not
moved. This probe finds out, case by case, against volumes we can
compute by hand.

What it does
------------
0. API check: is SetOffsetOnFace exposed in this OCP build, and which
   Initialize(...) argument list does it accept.
1. Synthetic cases (each tried with offset +d AND -d, join =
   Intersection and Arc, intersection flag False and True):
     A  box, move the TOP face                 expected vol = +/- top area * d
     B  box, move the +X SIDE face             expected vol = +/- side area * d
     C  plate with a slot open at one edge: move BOTH slot walls and the
        round end together (this is the geneva-slot widening)
     C2 same plate, move only the two WALLS (the end left alone) -- to see
        what the kernel does to the end
     D  box with a chamfered top edge, move the TOP face (the neighbour is
        tilted, so a plain extrusion would leave a step) -- info only
   Each line prints validity, solid/face counts, volume, and the volume
   we expected. MATCH = within 0.1 %.
2. Optional, on your own part:
     uv run probe_offset_faces.py --step wheel.stp --list
         lists every face: index, kind, area, center / normal / radius
     uv run probe_offset_faces.py --step wheel.stp --faces 12,13,14 --offset -0.5
         moves those faces by that offset (mm) and reports validity and
         the volume change. (Same sign convention as the synthetic runs;
         read them first.)

Nothing here touches KodaCAD's code or documents. It only prints.

Run: uv run probe_offset_faces.py            (synthetic cases)
"""

import argparse
import math
import sys

from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffset import BRepOffset_Skin
from OCP.BRepOffset import BRepOffset_MakeOffset
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Cylinder, GeomAbs_Intersection
from OCP.GeomAbs import GeomAbs_Plane
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL
from OCP.ShapeFix import ShapeFix_Solid
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

TOL = 1.0e-4          # offset tolerance handed to OCCT
MATCH_REL = 1.0e-3    # volume match: 0.1 %


# ----------------------------------------------------------------- helpers
def volume(shape):
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, p)
    return p.Mass()


def count(shape, kind):
    n = 0
    ex = TopExp_Explorer(shape, kind)
    while ex.More():
        n += 1
        ex.Next()
    return n


def faces_of(shape):
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        out.append(TopoDS.Face_s(ex.Current()))
        ex.Next()
    return out


def edges_of(shape):
    out = []
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        out.append(TopoDS.Edge_s(ex.Current()))
        ex.Next()
    return out


def face_info(face):
    """(kind, normal-or-radius, centre (x,y,z), area). Plane normals are
    the OUTWARD normal of the solid (orientation applied)."""
    surf = BRepAdaptor_Surface(face)
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    c = props.CentreOfMass()
    area = props.Mass()
    t = surf.GetType()
    if t == GeomAbs_Plane:
        d = surf.Plane().Axis().Direction()
        n = (d.X(), d.Y(), d.Z())
        if face.Orientation() == TopAbs_REVERSED:
            n = (-n[0], -n[1], -n[2])
        return "plane", n, (c.X(), c.Y(), c.Z()), area
    if t == GeomAbs_Cylinder:
        return "cyl", surf.Cylinder().Radius(), (c.X(), c.Y(), c.Z()), area
    return "other", None, (c.X(), c.Y(), c.Z()), area


def find_plane(shape, normal, near=None, tol=1e-6):
    """The planar face with outward normal `normal` (closest centre to
    `near` if several)."""
    best, bd = None, 1e300
    for f in faces_of(shape):
        kind, n, c, _a = face_info(f)
        if kind != "plane":
            continue
        if max(abs(n[i] - normal[i]) for i in range(3)) > tol:
            continue
        d = 0.0 if near is None else sum((c[i] - near[i]) ** 2
                                         for i in range(3))
        if d < bd:
            best, bd = f, d
    return best


def find_cyl(shape, radius, near):
    best, bd = None, 1e300
    for f in faces_of(shape):
        kind, r, c, _a = face_info(f)
        if kind != "cyl" or abs(r - radius) > 1e-6:
            continue
        d = sum((c[i] - near[i]) ** 2 for i in range(3))
        if d < bd:
            best, bd = f, d
    return best


def as_solid(res):
    """Run 1: with a compound / cut result, MakeOffsetShape returned a
    shell (solids=0) though volume and validity were right. Rebuild a
    solid from the shell. Returns (solid_or_None, note)."""
    if count(res, TopAbs_SOLID) >= 1:
        return res, "already has a solid"
    ex = TopExp_Explorer(res, TopAbs_SHELL)
    if not ex.More():
        return None, "no shell found"
    try:
        sol = ShapeFix_Solid().SolidFromShell(TopoDS.Shell_s(ex.Current()))
        return sol, "solid built from shell"
    except Exception as e:
        return None, f"SolidFromShell failed: {e}"


def radii(shape):
    return sorted(round(face_info(f)[1], 4) for f in faces_of(shape)
                  if face_info(f)[0] == "cyl")


def wrap_compound(shape):
    """The same shape inside a COMPOUND, the way KodaCAD often holds it."""
    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    b.Add(comp, shape)
    return comp


# ----------------------------------------------------- the offset call
_INIT_FORMS = None   # which Initialize(...) argument list worked


def make_builder(shape, default_off, join, intersection):
    """Create + initialise BRepOffset_MakeOffset, trying the argument
    lists OCP builds are known to expose, longest first. Returns the
    builder; raises if none accept."""
    global _INIT_FORMS
    forms = [
        ("S,Offset,Tol,Mode,Intersection,SelfInter,Join,Thickening,RemoveIntEdges",
         (shape, default_off, TOL, BRepOffset_Skin, intersection, False,
          join, False, False)),
        ("S,Offset,Tol,Mode,Intersection,SelfInter,Join,Thickening",
         (shape, default_off, TOL, BRepOffset_Skin, intersection, False,
          join, False)),
        ("S,Offset,Tol,Mode,Intersection,SelfInter,Join",
         (shape, default_off, TOL, BRepOffset_Skin, intersection, False,
          join)),
    ]
    last = None
    for name, args in forms:
        b = BRepOffset_MakeOffset()
        try:
            b.Initialize(*args)
        except TypeError as e:
            last = e
            continue
        if _INIT_FORMS is None:
            _INIT_FORMS = name
        return b
    raise TypeError(f"no Initialize() form accepted: {last}")


def offset_faces(shape, moves, join, intersection, default_off=0.0):
    """moves: list of (face, offset). Returns (result_or_None, note)."""
    try:
        b = make_builder(shape, default_off, join, intersection)
        for face, val in moves:
            b.SetOffsetOnFace(face, val)
        b.MakeOffsetShape()
        done = b.IsDone()
        if not done:
            err = ""
            if hasattr(b, "Error"):
                try:
                    err = f" Error()={b.Error()}"
                except Exception:
                    pass
            return None, f"IsDone()=False{err}"
        return b.Shape(), ""
    except Exception as e:  # OCCT raises for many invalid configurations
        return None, f"{type(e).__name__}: {e}"


# Run 1 (Session 156): join=Arc failed in EVERY case ("command not done")
# and intersection=True changed nothing. Keep only what worked.
JOINS = [("Intersection", GeomAbs_Intersection)]
INTERS = [False]
SIGNS = [+1, -1]
SUMMARY = []   # (label, sign, join, inter, verdict)


def trial(label, shape, moves_fn, expected_fn, d, extra=None):
    """Run one case over the settings grid. moves_fn(sign*d) -> moves list
    built from faces of `shape`; expected_fn(sign*d) -> expected volume or
    None (info only)."""
    v0 = volume(shape)
    print(f"\n=== {label}  (start volume {v0:.3f}) ===")
    for sign in SIGNS:
        off = sign * d
        exp = expected_fn(off) if expected_fn else None
        for jn, join in JOINS:
            for inter in INTERS:
                res, note = offset_faces(shape, moves_fn(off), join, inter)
                head = (f"  off={off:+7.3f} join={jn:<12} "
                        f"inter={str(inter):<5}")
                if res is None:
                    print(f"{head} FAILED  {note}")
                    SUMMARY.append((label, off, jn, inter, "FAILED"))
                    continue
                ok = BRepCheck_Analyzer(res).IsValid()
                v = volume(res)
                tail = (f"valid={ok!s:<5} type={res.ShapeType().name.split('_')[-1]:<8}"
                        f" solids={count(res, TopAbs_SOLID)} "
                        f"faces={count(res, TopAbs_FACE):<3} vol={v:.3f} "
                        f"dV={v - v0:+.3f}")
                if exp is not None:
                    err = abs(v - exp) / max(abs(exp), 1e-12)
                    hit = ok and err < MATCH_REL
                    tail += f"  expected={exp:.3f}  " + (
                        "MATCH" if hit else f"no match (rel err {err:.2e})")
                    verdict = "MATCH" if hit else (
                        "valid, wrong vol" if ok else "INVALID")
                else:
                    verdict = "valid (info)" if ok else "INVALID"
                print(f"{head} {tail}")
                if count(res, TopAbs_SOLID) == 0:
                    sol, wn = as_solid(res)
                    if sol is not None:
                        print(f"      wrap: {wn}; valid="
                              f"{BRepCheck_Analyzer(sol).IsValid()} "
                              f"vol={volume(sol):.3f}")
                    else:
                        print(f"      wrap: {wn}")
                if extra is not None:
                    print(f"      {extra(res)}")
                SUMMARY.append((label, off, jn, inter, verdict))


# ---------------------------------------------------------------- cases
def case_box_face(which, d=5.0):
    L, W, H = 100.0, 60.0, 20.0
    box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), L, W, H).Shape()
    if which == "top":
        face = find_plane(box, (0, 0, 1))
        area = L * W
        label = "A  box: move TOP face"
    else:
        face = find_plane(box, (1, 0, 0))
        area = W * H
        label = "B  box: move +X side face"
    trial(label, box, lambda off: [(face, off)],
          lambda off: L * W * H + area * off, d)


def make_slot_plate():
    """100 x 60 x 20 plate, slot open at the +X edge: width 10 (walls at
    y=25 and y=35), round end of radius 5 centred at x=40. Through Z."""
    L, W, H = 100.0, 60.0, 20.0
    plate = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), L, W, H).Shape()
    rect = BRepPrimAPI_MakeBox(gp_Pnt(40, 25, -1), 80, 10, H + 2).Shape()
    cyl = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(40, 30, -1), gp_Dir(0, 0, 1)), 5.0, H + 2).Shape()
    cutter = BRepAlgoAPI_Fuse(rect, cyl).Shape()
    return BRepAlgoAPI_Cut(plate, cutter).Shape(), (L, W, H)


def slot_volume(L, W, H, r):
    """Plate volume with a slot of half-width r (round end at x=40,
    open to x=L)."""
    slot_area = (L - 40.0) * 2.0 * r + math.pi * r * r / 2.0
    return L * W * H - H * slot_area


def case_slot(with_end, d=1.0):
    plate, (L, W, H) = make_slot_plate()
    wall_lo = find_plane(plate, (0, 1, 0), near=(70, 35, 10))   # y=35 wall
    wall_hi = find_plane(plate, (0, -1, 0), near=(70, 25, 10))  # y=25 wall
    end = find_cyl(plate, 5.0, near=(40, 30, 10))
    missing = [n for n, f in (("wall y=35", wall_lo), ("wall y=25", wall_hi),
                              ("round end", end)) if f is None]
    if missing:
        print(f"\n(slot case skipped: could not find {missing})")
        return
    if with_end:
        label = "C  slot plate: move both WALLS + ROUND END (widen slot)"
        moves = lambda off: [(wall_lo, off), (wall_hi, off), (end, off)]
    else:
        label = "C2 slot plate: move only the two WALLS (end left alone)"
        moves = lambda off: [(wall_lo, off), (wall_hi, off)]
    # A face's offset is along its OUTWARD solid normal. The slot walls'
    # outward normals point into the (empty) slot, so a POSITIVE offset
    # moves the wall into the slot (slot narrows) and a NEGATIVE one
    # widens it. Expected volume uses slot half-width r = 5 - off.
    trial(label, plate, moves,
          (lambda off: slot_volume(L, W, H, 5.0 - off)) if with_end
          else None, d,
          extra=lambda r: f"cylinder radii in result: {radii(r)} "
                          f"(was [5.0])")


def case_chamfer(d=3.0):
    L, W, H = 100.0, 60.0, 20.0
    box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), L, W, H).Shape()
    target = None
    for e in edges_of(box):
        p = GProp_GProps()
        BRepGProp.LinearProperties_s(e, p)
        c = p.CentreOfMass()
        if abs(c.X() - L) < 1e-6 and abs(c.Z() - H) < 1e-6:
            target = e
            break
    if target is None:
        print("\n(chamfer case skipped: edge not found)")
        return
    mk = BRepFilletAPI_MakeChamfer(box)
    mk.Add(10.0, target)
    mk.Build()
    shape = mk.Shape()
    top = find_plane(shape, (0, 0, 1))
    trial("D  chamfered box: move TOP face (tilted neighbour) -- info only",
          shape, lambda off: [(top, off)], None, d)


def case_hole(d=2.0):
    """Plate with a through hole r=10. The hole wall's outward normal
    points into the hole, so +off SHRINKS the hole: r' = 10 - off."""
    L, W, H = 100.0, 60.0, 20.0
    plate = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), L, W, H).Shape()
    cyl = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(50, 30, -1), gp_Dir(0, 0, 1)), 10.0, H + 2).Shape()
    part = BRepAlgoAPI_Cut(plate, cyl).Shape()
    wall = find_cyl(part, 10.0, near=(50, 30, 10))
    if wall is None:
        print("\n(hole case skipped: wall not found)")
        return
    trial("E  plate with hole r=10: move the hole wall (resize hole)",
          part, lambda off: [(wall, off)],
          lambda off: L * W * H - math.pi * (10.0 - off) ** 2 * H, d,
          extra=lambda r: f"cylinder radii in result: {radii(r)}")


def case_two_faces(d=2.0):
    """Two different offsets at once on a box corner: top +d, +X side
    +2.5d. Independent faces, so expected = (100+2.5d)*60*(20+d)."""
    L, W, H = 100.0, 60.0, 20.0
    box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), L, W, H).Shape()
    top = find_plane(box, (0, 0, 1))
    side = find_plane(box, (1, 0, 0))
    trial("F  box: top +d AND +X side +2.5d in the same call",
          box, lambda off: [(top, off), (side, 2.5 * off)],
          lambda off: (L + 2.5 * off) * W * (H + off), d)


def case_compound_input(d=5.0):
    """KodaCAD often holds a shape as a COMPOUND around the solid."""
    L, W, H = 100.0, 60.0, 20.0
    box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), L, W, H).Shape()
    comp = wrap_compound(box)
    top = find_plane(comp, (0, 0, 1))
    trial("G  same box inside a COMPOUND: move TOP face",
          comp, lambda off: [(top, off)],
          lambda off: L * W * H + L * W * off, d)


def case_fillet_neighbours(d=4.0):
    """Box with its 4 vertical edges filleted r=8; move the +X face.
    The fillets are tangent to that face. Info only: do they follow?"""
    L, W, H = 100.0, 60.0, 20.0
    box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), L, W, H).Shape()
    mk = BRepFilletAPI_MakeFillet(box)
    for e in edges_of(box):
        p = GProp_GProps()
        BRepGProp.LinearProperties_s(e, p)
        c = p.CentreOfMass()
        # vertical edges: centre z = H/2, and x,y at the box corners
        if abs(c.Z() - H / 2) < 1e-6 and (
                min(abs(c.X()), abs(c.X() - L)) < 1e-6) and (
                min(abs(c.Y()), abs(c.Y() - W)) < 1e-6):
            mk.Add(8.0, e)
    mk.Build()
    part = mk.Shape()
    side = find_plane(part, (1, 0, 0))
    trial("H  box with filleted vertical edges: move +X face (info)",
          part, lambda off: [(side, off)], None, d,
          extra=lambda r: f"cylinder radii in result: {radii(r)} "
                          f"(fillets were 8.0)")


# ------------------------------------------------------------ own part
def load_first_solid(path):
    r = STEPControl_Reader()
    if r.ReadFile(path) != 1:   # IFSelect_RetDone
        raise SystemExit(f"could not read {path}")
    r.TransferRoots()
    shape = r.OneShape()
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    if ex.More():
        return TopoDS.Solid_s(ex.Current())
    return shape


def own_part(path, list_only, face_idx, off):
    shape = load_first_solid(path)
    faces = faces_of(shape)
    if list_only:
        print(f"{path}: {len(faces)} faces, volume {volume(shape):.3f}")
        for i, f in enumerate(faces):
            kind, v, c, a = face_info(f)
            if kind == "plane":
                desc = f"normal=({v[0]:+.2f},{v[1]:+.2f},{v[2]:+.2f})"
            elif kind == "cyl":
                desc = f"radius={v:.4f}"
            else:
                desc = ""
            print(f"  [{i:3d}] {kind:<5} area={a:10.3f} "
                  f"centre=({c[0]:8.2f},{c[1]:8.2f},{c[2]:8.2f}) {desc}")
        return
    sel = [faces[i] for i in face_idx]
    v0 = volume(shape)
    print(f"{path}: moving faces {face_idx} by {off:+.4f} mm "
          f"(start volume {v0:.3f})")
    for jn, join in JOINS:
        for inter in INTERS:
            res, note = offset_faces(shape, [(f, off) for f in sel],
                                     join, inter)
            head = f"  join={jn:<12} inter={str(inter):<5}"
            if res is None:
                print(f"{head} FAILED  {note}")
                continue
            ok = BRepCheck_Analyzer(res).IsValid()
            v = volume(res)
            print(f"{head} valid={ok!s:<5} solids={count(res, TopAbs_SOLID)} "
                  f"faces={count(res, TopAbs_FACE):<3} vol={v:.3f} "
                  f"dV={v - v0:+.3f}")


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--step", help="STEP file of your own part")
    ap.add_argument("--list", action="store_true",
                    help="with --step: list faces and exit")
    ap.add_argument("--faces", help="with --step: comma-separated indices")
    ap.add_argument("--offset", type=float, default=0.5,
                    help="with --step --faces: offset in mm (default 0.5)")
    args = ap.parse_args()

    print("[0] API check")
    print("    SetOffsetOnFace exposed:",
          hasattr(BRepOffset_MakeOffset, "SetOffsetOnFace"))
    if not hasattr(BRepOffset_MakeOffset, "SetOffsetOnFace"):
        print("    -> not available in this OCP build; nothing to probe.")
        sys.exit(1)

    if args.step:
        idx = ([int(s) for s in args.faces.split(",")]
               if args.faces else [])
        if not args.list and not idx:
            raise SystemExit("give --list, or --faces i,j,k")
        own_part(args.step, args.list, idx, args.offset)
        return

    case_box_face("top")
    case_box_face("side")
    case_slot(with_end=True)
    case_slot(with_end=False)
    case_chamfer()
    case_hole()
    case_two_faces()
    case_compound_input()
    case_fillet_neighbours()

    print(f"\nInitialize() argument form that worked: {_INIT_FORMS}")
    print("\n=== SUMMARY (verdict per case / sign / join / intersection) ===")
    last = None
    for label, off, jn, inter, verdict in SUMMARY:
        if label != last:
            print(label)
            last = label
        print(f"    off={off:+7.3f} {jn:<12} inter={str(inter):<5} {verdict}")
    print("\nPlease paste this whole output back.")


if __name__ == "__main__":
    main()
