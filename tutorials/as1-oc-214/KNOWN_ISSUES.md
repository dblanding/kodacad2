# `as1-oc-214.stp`: what it is, and where it misleads as a benchmark

KodaCAD has used `as1-oc-214.stp` throughout development as a ready-made
assembly with shared instances. It is good for that: assembly structure,
shared prototypes, STEP round trips, undo/redo across a mixed chain. It is
**not** a reliable test of *solid-modelling* operations on curved faces
(Defeaturing, Move Face, Shell, fillets). This page records why, so a
failure on this file is not taken for a KodaCAD bug (or the reverse) without
checking. Written Nov 19, 2026 (Session 180) after Move Face failed on the
big L-bracket. Facts below are marked **measured** (looked at in the file or
seen in KodaCAD) or **suspected** (not proven).

## What the file is (measured)

- Header: `FILE_NAME('Open CASCADE Shape Model','2008-07-24T15:00:20', ... 'Datakit Converter' ... 'Open CASCADE 6.1')`,
  schema AUTOMOTIVE_DESIGN (AP214). A 2008 export through a third-party
  converter, not something modern OCCT wrote.
- 53 faces in the whole file: **25 planes and 28 rational B-spline
  surfaces** (all degree 1 x 3). There is **no** cylindrical, conical,
  spherical or toroidal surface anywhere: every round hole, bolt shank, nut
  and rod is built from B-spline patches, normally in two halves
  ("semi-holes").
- 5 solids (`MANIFOLD_SOLID_BREP`): l-bracket, bolt, nut, rod, plate.

## What that does in KodaCAD (measured, Doug's tests, Nov 19)

On the original, unmodified `l-bracket`:

| Operation | Result |
|---|---|
| Move Face +1 mm on the outer vertical face | works |
| Defeaturing, Remove Hole, click a hole (rod hole in the vertical leg) | only the lower semi-hole face is picked; fails |
| Remove Hole with both semi-holes picked | fails; the hole stays highlighted afterwards |
| Remove Hole on the holes in the horizontal leg | fails the same way |
| Defeaturing, Manual (pick every face of the hole) | works; all 4 holes removed |
| Then cut a slot in the vertical face and use Move Face | works normally |

Remove Hole needs a CYLINDRICAL face. A hole made of two spline halves
is not one, so the mode's rule ('pick a cylindrical face') cannot be met.
That is a limit of the *file's* geometry, not of Defeaturing.

## The Move Face failure (measured), and its cause (suspected)

- `slot-foo.kcad` is the L-bracket with a slot (made in KodaCAD) and the
  original spline holes still in place. There **every** Move Face fails:
  the slot walls and also the outer vertical face, at +1, +0.5, +0.1,
  +0.01, -0.1, -0.5 and -1 mm, also on a UnifySameDomain copy
  (`probe_slot_offset.py`). OCCT returns no shape at all.
- The part itself checks out: valid, one solid, tolerance <= 2.6e-5, the
  slot is 10 mm wide with r = 5 round ends whose edges are exactly G1.
  So it is not the slot's geometry, width, tangency, validity or tolerance.
- The same bracket with the holes removed (Manual) and a slot added moves
  faces normally; the unmodified bracket (holes, no slot) moves its outer
  face. So the failure appeared only with the **spline holes and an added
  feature together**. *Suspected:* OCCT's offset analyses every face of the
  part, and the 8 spline hole faces are what it chokes on once the part is
  edited. Not proven. Not yet tested: a fresh session of the original plus
  a slot with the holes kept, to be sure `slot-foo.kcad` was not changed in
  some other way.
- Counts that do not obviously agree (open): the file text gives the
  l-bracket 18 faces (6 planes, 12 splines); `slot-foo`'s part has 20
  (10 planes, 2 cylinders, 8 splines) including the slot's 4. Something
  differs between the file and the loaded part; not explained.

## What this means for testing

- Keep using it for structure, sharing, save/reload and undo/redo.
- For Defeaturing, Move Face, Shell, fillets: also test on a part KodaCAD
  built itself (analytic planes / cylinders) or on the Move Face tutorial
  bracket. A failure on `as1-oc-214.stp` alone is not enough to call a bug.
- A failure here may be worth fixing anyway (parts from other CAD systems
  often have spline holes), but it is a separate item, listed below.

## Possible follow-ups (none started)

1. Remove Hole: accept a hole whose wall is several tangent faces (pick
   one half, take its tangent neighbours), and stop leaving the hole
   highlighted after a failed attempt (that second part looks like a plain
   bug).
2. Find out which feature of the part makes the offset return nothing
   (try removing holes one at a time on `slot-foo.kcad`).
3. Recognise spline faces that are really cylinders and rebuild them as
   true cylinders on import (a bigger job).
4. `probe_slot_offset.py` / `probe_slot_offset2.py` are in the repo root
   for the next time.
