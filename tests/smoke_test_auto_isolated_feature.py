"""
smoke_test_auto_isolated_feature.py -- headless validation of
isolated_features.find_isolated_feature_faces() against synthetic
geometry, BEFORE wiring it into kodacad.py's UI.

Run: uv run python smoke_test_auto_isolated_feature.py

Five cases, each built with BRepPrimAPI + BRepAlgoAPI (not sketch +
prism, to keep this self-contained), matching the kind of parts the
real menu items are meant to handle.

FIRST RUN OF THIS SCRIPT (Doug, 2026-09-30) found a real thing, not
a bug in the harness: CASE 3 (boss, single seed) worked exactly as
predicted -- proof the whole OCP call chain (TopExp.MapShapes_s,
BRepTools.OuterWire_s, TopTools_IndexedMapOfShape, all of it) is
correct on this system. CASE 1 (through-hole, single seed) came back
empty, and rightly so: a through-hole's wall is ALSO adjacent to its
second, unpicked opening, which stays connected to the rest of the
part -- so picking only one capping face never isolates it as its
own graph island. find_isolated_feature_faces() now takes a LIST of
seed faces for exactly this reason (see isolated_features.py's own
docstring). CASE 2's original failure was a separate, genuine bug in
THIS test file, not the algorithm: the cylinder axis was placed so
the "blind hole" actually opened out the BOTTOM of the block and
never reached the top face being picked -- fixed below.

  CASE 1: through-hole, TWO seeds (top face + bottom face). Expect
  the detector to find the hole's own cylindrical wall face (just
  one -- the bottom cap doesn't need finding or removing,
  BRepAlgoAPI_Defeaturing heals it once the wall is gone, exactly as
  removeHoleC's own docstring already documented for the manual
  tool).

  CASE 1b: the SAME through-hole part, but only the top face as
  seed -- kept deliberately, as a standing demonstration of why one
  capping face isn't enough for a through-feature. Expect [].

  CASE 2: blind hole, ONE seed (top face only). Cylinder now cut
  downward FROM ABOVE the top face, stopping well short of the
  bottom, so the hole genuinely opens at the top and is blind at the
  bottom. Expect the detector to find BOTH the cylindrical wall AND
  the hole's own bottom cap face (two faces, not one) -- the case
  removeHole()'s own multi-patch/cap-adjacency logic had to
  special-case by hand; this algorithm finds both without any
  hole-shape-specific logic at all.

  CASE 3: boss, ONE seed. A block with a smaller cylinder FUSED on
  top. Pick the block's TOP face (which now has a circular inner
  wire where the boss meets it, since the flat face's own domain
  excludes the boss's footprint). Expect the detector to find the
  boss's cylindrical wall AND its own top cap (two faces).

For each (non-negative) case: run the detector, print what it found,
then actually run BRepAlgoAPI_Defeaturing on the result (removing
exactly what was found) and print before/after face counts plus
IsDone(), matching the same validity check kodacad.py's
removeHoleC/removeIsolatedFeatureC already use -- IsDone()=True
alone isn't trusted on its own (Session 103's own finding), so
before/after face count is checked too.

Also runs a NEGATIVE case: pick a face with no inner wire at all (a
plain side face) and confirm the detector returns [] rather than
guessing.
"""

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, \
    BRepAlgoAPI_Defeaturing
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane

import isolated_features as isof


def count_faces(shape):
    n = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        n += 1
        exp.Next()
    return n


def top_face(shape, z_expected):
    """Return the planar face whose plane sits at z == z_expected
    (within tolerance) -- picks out 'the top face' without relying on
    face ordering."""
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        f = TopoDS.Face_s(exp.Current())
        surf = BRepAdaptor_Surface(f)
        if surf.GetType() == GeomAbs_Plane:
            pln = surf.Plane()
            origin = pln.Location()
            normal = pln.Axis().Direction()
            if abs(abs(normal.Z()) - 1.0) < 1e-6 and \
                    abs(origin.Z() - z_expected) < 1e-4:
                return f
        exp.Next()
    return None


def any_side_face(shape):
    """Return a planar, VERTICAL face (a plain side wall -- no inner
    wire expected) for the negative test."""
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        f = TopoDS.Face_s(exp.Current())
        surf = BRepAdaptor_Surface(f)
        if surf.GetType() == GeomAbs_Plane:
            pln = surf.Plane()
            normal = pln.Axis().Direction()
            if abs(normal.Z()) < 1e-6:
                return f
        exp.Next()
    return None


def run_case(name, shape, seed_faces, expect_n_faces):
    print("=" * 70)
    print(name)
    print("=" * 70)
    seeds = seed_faces if isinstance(seed_faces, list) else [seed_faces]
    if not seeds or any(s is None for s in seeds):
        print("  COULD NOT FIND SEED FACE -- test setup itself is broken.")
        return
    found = isof.find_isolated_feature_faces(shape, seeds)
    print(f"  faces found: {len(found)} (expected {expect_n_faces})")
    if not found:
        print("  (nothing to defeature -- stopping here for this case)")
        return

    dfr = BRepAlgoAPI_Defeaturing()
    dfr.SetShape(shape)
    for f in found:
        dfr.AddFaceToRemove(f)
    dfr.Build()
    n_before = count_faces(shape)
    print(f"  IsDone={dfr.IsDone()}")
    if not dfr.IsDone():
        print("  DEFEATURING FAILED.")
        return
    new_shape = dfr.Shape()
    n_after = count_faces(new_shape)
    print(f"  faces before={n_before}, after={n_after}")


def main():
    # ---- CASE 1: through-hole, both capping faces as seeds ----
    block = BRepPrimAPI_MakeBox(40.0, 40.0, 20.0).Shape()
    hole_ax = gp_Ax2(gp_Pnt(20.0, 20.0, -1.0), gp_Dir(0, 0, 1))
    through_cyl = BRepPrimAPI_MakeCylinder(hole_ax, 5.0, 22.0).Shape()
    through_part = BRepAlgoAPI_Cut(block, through_cyl).Shape()
    seed1_top = top_face(through_part, 20.0)
    seed1_bot = top_face(through_part, 0.0)
    run_case("CASE 1: through-hole, pick BOTH top and bottom faces",
             through_part, [seed1_top, seed1_bot], expect_n_faces=1)

    # ---- CASE 1b: same part, only ONE capping face -- expect [] ----
    run_case("CASE 1b: same through-hole, only top face (expect "
             "nothing -- demonstrates why through-features need both "
             "capping faces)", through_part, seed1_top,
             expect_n_faces=0)

    # ---- CASE 2: blind hole, cut downward from above the top face,
    # stopping well short of the bottom (genuinely blind at the
    # bottom, open at the top) ----
    block2 = BRepPrimAPI_MakeBox(40.0, 40.0, 20.0).Shape()
    blind_ax = gp_Ax2(gp_Pnt(20.0, 20.0, 21.0), gp_Dir(0, 0, -1))
    blind_cyl = BRepPrimAPI_MakeCylinder(blind_ax, 5.0, 12.0).Shape()
    blind_part = BRepAlgoAPI_Cut(block2, blind_cyl).Shape()
    seed2 = top_face(blind_part, 20.0)
    run_case("CASE 2: blind hole, pick top face", blind_part, seed2,
             expect_n_faces=2)

    # ---- CASE 3: boss ----
    block3 = BRepPrimAPI_MakeBox(40.0, 40.0, 20.0).Shape()
    boss_ax = gp_Ax2(gp_Pnt(20.0, 20.0, 20.0), gp_Dir(0, 0, 1))
    boss_cyl = BRepPrimAPI_MakeCylinder(boss_ax, 5.0, 10.0).Shape()
    boss_part = BRepAlgoAPI_Fuse(block3, boss_cyl).Shape()
    seed3 = top_face(boss_part, 20.0)
    run_case("CASE 3: boss, pick surrounding top face", boss_part, seed3,
             expect_n_faces=2)

    # ---- NEGATIVE CASE: plain face, no inner wire ----
    print("=" * 70)
    print("CASE 4 (negative): plain side face, expect []")
    print("=" * 70)
    block4 = BRepPrimAPI_MakeBox(40.0, 40.0, 20.0).Shape()
    seed4 = any_side_face(block4)
    if seed4 is None:
        print("  COULD NOT FIND SEED FACE -- test setup itself is broken.")
    else:
        found4 = isof.find_isolated_feature_faces(block4, seed4)
        print(f"  faces found: {len(found4)} (expected 0)")


if __name__ == "__main__":
    main()
