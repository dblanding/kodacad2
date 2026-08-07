# Sketch Engine Design: Pyurcad-style Sketching on Kodacad Workplanes

*Session 61 design note. Foundational to all Tier-3 TODO items.*

## The core realization

Kodacad's current sketch input asks the 3D engine (OCCT selection) to
understand sketch-level snap semantics -- hence pre-constructed
intersection points as AIS objects at every place the user might want
to pick. Pyurcad (github.com/dblanding/pyurcad) proves the opposite
architecture is the effortless one: **the snap engine should be ours
and the 3D engine should just be a projector.** Pyurcad's tkinter
canvas supplies continuous cursor position in sketch coordinates, and
everything else -- candidate search, catch/snap ranking, rubber-band
feedback -- is app-side 2D logic against an app-side 2D data model.
The Kodacad viewport can supply exactly the same thing. The missing
bridge is one function.

## The bridge: screen_to_uv(x, y)

On every mouse MOVE (not just clicks):

1. `V3d_View.ConvertWithProj(x, y)` -> a 3D point + projection
   direction (the pick ray through the cursor).
2. Intersect the ray with the active workplane's `gp_Pln` -- one line
   of algebra (or `IntAna_IntConicQuad`).
3. `ElSLib.Parameters(pln, pnt)` -> (u, v) in the plane's own frame.

With that, the viewport IS a tkinter canvas as far as sketching is
concerned: continuous cursor UV, with the 3D model still visible
behind it -- which is CoCreate's soul: sketching ON the part, in
context, not in a separate 2D editor.

## The snap engine (app-side, UV space)

Sketch entities (clines, ccircles, geometry: lines/arcs/circles) live
in Python structures -- which Kodacad largely already has. On each
mouse move, search them for snap candidates near the cursor UV:

- endpoints, midpoints of geometry
- centers of circles/arcs/ccircles
- intersections of any two entities -- computed ON THE FLY near the
  cursor (2D line/line, line/circle, circle/circle intersection is
  trivial closed-form math). The pre-built intersection-point AIS
  objects become obsolete: intersections stop being objects that must
  be anticipated and created, and become just one candidate CATEGORY.
- on-curve (nearest point on a cline/ccircle/geometry item)
- grid, axis, origin as desired

Candidate ranking: distance in PIXELS, converted to model units via
`view.Convert(n_pixels)` so the catch radius stays constant on screen
at every zoom -- exactly the tkinter behavior.

CATCH POLICY (final, Session 62 -- Doug): the DEFAULT catch set is
INTERSECTIONS (+ geometry endpoints, origin). On-curve and centers
are deliberately NOT in the default -- a drafter draws dark lines
between intersections of the layout, not 'somewhere along' a line.
Holding CTRL+SHIFT switches EXCLUSIVELY to centers of circles/arcs
(construction and geometry) and midpoints of straight geometry edges
-- the CoCreate override, ENTITY-ANCHORED (verified by Doug against
Creo E/D and Pyurcad): the cursor points at the ENTITY, anywhere
along it, and the glyph appears at ITS center/midpoint -- possibly
far from the cursor -- because the center of a circle has no visible
feature to aim at. Click takes the glyph's location. Ranking is by
distance to the curve. (Pyurcad uses plain Shift; Kodacad uses the
CoCreate chord, Ctrl+Shift, by Doug's decision.)
The catch square changes colour (orange -> cyan) so the flyby
feedback tells you which catch set is live. On-curve remains
available in the engine for tools that explicitly want it (e.g. a
future trim), but no default input path offers it.

Every input tool (line, arc, circle, dimension, trim...) consumes the
same engine: tool declares which candidate categories it accepts;
engine returns the best candidate + its UV; tool proceeds. Uniform
snap behavior across all tools falls out for free.

## What this dissolves from the Tier-3 list (side effects, not tasks)

- **Arc-over-ccircle deletion**: the picker filters by entity class
  per operation -- "delete geometry" simply never considers
  construction entities. No OCCT selection filtering involved.
- **Ctrl+Shift center snap**: modifier check re-ranking candidates.
- **Full snap points on all tools**: the engine serves every tool.
- **Parallel clines / offset input**: tools read cursor UV + snaps
  directly; no special pickable helpers needed.
- Robustness: after the Session 60 analytic-selection saga, the most
  interaction-intensive feature of the app deliberately does NOT
  depend on deep OCCT selection subtleties. OCCT selection remains
  for 3D part/face picking only, where it belongs.

## Dynamic feedback

A snap MARKER (small glyph at the current best candidate, styled by
category: endpoint square, midpoint triangle, center cross,
intersection X) and a RUBBER-BAND (line/arc preview from the anchor
to the cursor) are small AIS objects whose geometry is updated on
each mouse move -- the same proven pattern as the live manipulator
drag. OCCT's AIS_RubberBand exists for the screen-space case;
plane-space AIS_Line/AIS_Circle updates work for the in-plane case.

## Rejected alternatives

- **Embedded QGraphicsScene sketch editor**: a real 2D canvas, but it
  breaks in-context sketching on the model -- the defining CoCreate
  quality. Rejected.
- **Deeper OCCT-native selection (custom sensitive entities,
  per-entity activation)**: fighting the framework exactly where
  Session 60 proved surprises live. Rejected.
- **Status quo (pre-built intersection AIS points)**: works, but
  scales poorly (N^2 intersection objects), requires anticipating
  picks, and leaves every Tier-3 snap item as a separate fight.

## Incremental adoption path (each step useful on its own)

1. **Bridge + hover marker**: implement screen_to_uv and a
   hover-only snap marker. No behavioral change -- just a glyph
   showing what WOULD be caught. Validates the bridge, lets the
   responsiveness be felt, zero risk.
2. **One tool**: route a single input operation (line endpoint input)
   through the engine.
3. **Migrate remaining tools**; retire pre-built intersection points.
4. **Then** the rest of Tier 3 (booleans, two-wire extrude,
   project-edges-to-workplane -- projected edges simply become more
   snap-candidate entities in the engine) builds on it.

Pyurcad's catch logic should transplant with little surgery -- it was
always the right architecture; it was waiting for the coordinate
bridge.

## Input philosophy (Session 62, Doug): NO CATCH -> NO POINT

The drafter's layout method, stated by Doug as the governing metaphor:
a drafter lays out with a #6 (hard-lead) pencil -- very light
construction lines -- then draws the dark final lines at the
INTERSECTIONS of that layout. The construction geometry IS the input
space. Consequences, binding on every tool migrated to engine input:

- A click lands ONLY where the engine catches. No catch -> the click
  is rejected with a status hint; no point is created.
- Free-space input does not exist. (A near-miss click silently
  placing a slightly-wrong point is the exact imprecision the layout
  method prevents; rejecting it makes precision STRUCTURAL.)
- The hover marker is therefore the PERMISSION INDICATOR: no marker
  visible, no input possible.
- Numeric entry (lineEdit) remains the other first-class input path
  (that is how the first construction lines bootstrap, along with
  snaps to origin/axes).
- REFINEMENT (same session, Doug's parallel-cline example): there
  are TWO CLASSES of clicks, and the principle governs only the
  first.
  * POINT INPUT -- the click DEFINES COORDINATES that become
    geometry. Catch-only. No catch -> no point. (Helper:
    add_snap_pt_to_xyPtStack.)
  * GESTURE INPUT -- the click CHOOSES among discrete alternatives:
    which SIDE for a parallel cline, which direction, which of two
    intersections. The click means 'this half-plane', not 'this
    exact spot'; precision is irrelevant by construction, so a free
    raw-UV click is the NATURAL interface, not an exception.
    (Helper: gesture_uv_from_args -- raw UV, no snap, no rejection.)
  Every tool in the flush-out pass declares which class each of its
  clicks belongs to; there is no third class.

## Construction SEGMENTS (csegs) -- required by project-edges (Doug, pre-2.0 pause)

Projecting part edges onto a workplane requires a NEW construction
entity: the c-line SEGMENT -- finite, ((u1,v1),(u2,v2)) -- as opposed
to the infinite c-line. Rationale (why not just infinite clines
through each projected edge): every projected edge extended to
infinity would flood the layout with clutter and combinatorial FALSE
catches far from the part; segments keep the layout local to the
geometry that cast it. This is how CoCreate projects.

Data-model and engine implications, recorded ahead of implementation:
- wp gains a csegs collection alongside clines/ccircs.
- Display: dashed construction style (magenta), finite extent.
- Snap engine: cseg endpoints are catches (a projected face's CORNERS
  are exactly the mounting-hole landmarks Doug needs); cseg x cseg,
  cseg x cline, cseg x ccirc, cseg x geometry intersections with
  on-segment bounds checks (the machinery already exists for geometry
  segments -- csegs reuse it); Ctrl+Shift midpoints of csegs.
- Delete-all-construction (future tool) includes csegs.
- Projected circular edges (holes) will analogously need c-ARCS or
  c-circles at projected positions -- decide during project-edges
  implementation.
