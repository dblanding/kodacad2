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
at every zoom -- exactly the tkinter behavior. Modifier keys re-rank:
Ctrl+Shift = centers-only (the CoCreate center-snap override) is a
one-line filter on the candidate list.

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
