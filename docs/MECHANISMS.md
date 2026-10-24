# Animate Mechanism -- how it works and how to write a mechanism file

**Utility -> Animate Mechanism...** moves the parts of an assembly on
screen with a slider, so you can see how a mechanism works, park it in
any pose, and trace the path of a point. It was built in Sessions
171-172 and proved on two examples:

| File | Mechanism | Shows |
|------|-----------|-------|
| `mechanisms/geneva4.py` (+ `geneva4.stp`) | 4-slot Geneva drive | rotation of each part about a fixed shaft |
| `mechanisms/scott_russell.py` (+ the STEP) | pin-jointed four-bar | a floating coupler, a slider range, Trace |

## What it does (and does not do)

* **Display only.** Each moving part's `AIS_Shape` is moved with
  `AIS_InteractiveContext.SetLocation` (a `gp_Trsf` rotation about a
  `gp_Ax1`, plus an optional translation). The XDE document, the tree
  and the undo history are never touched, and **Done** puts every part
  back. Position's `set_component_location` was rejected on purpose: it
  removes and re-adds the component, hands out a new uid, reparses the
  document and rebuilds the tree -- far too heavy for every slider tick.
* **No constraint solver.** OCCT has no kinematics, and KodaCAD does not
  solve joints. A mechanism file supplies the equations (a few lines of
  Python per mechanism).
* **Face projection follows the slider.** Doug confirmed that
  projecting faces onto a workplane while the slider is parked in a pose
  uses the displayed (moved) positions, not the stored ones. That is the
  "snapshot" technique: set the slider, then project.
* A mechanism file is **Python the user picks and edits**, loaded with
  `importlib` and run in-process. It is deliberately **not** stored in a
  `.kcad` session, whose loader never executes anything.

## The mechanism file

A plain `.py` file. KodaCAD reads these names (all but `PARTS` and
`setup` have defaults):

| Name | Meaning |
|------|---------|
| `NAME` | Title shown in the dialog. |
| `PARTS` | `{part name as shown in the tree: role}`. Every part with a role is moved; the others stay put. Several parts may share a role. |
| `setup(ctx)` | Called once on load; returns `{role: (point, direction)}`, each role's axis in world mm. Raise an error here if the model isn't what the file expects. |
| `angles(theta)` | Simple form: `{role: degrees}`, rotation about the role's axis **relative to the modelled pose**. |
| `poses(theta)` | General form (used if present, instead of `angles`): `{role: (degrees, (tx, ty, tz))}` -- rotate about the role's axis point, **then** translate. Needed for a coupler that moves bodily. |
| `START` | Slider angle at which the parts sit exactly as modelled. Default 0. |
| `RANGE` | `(low, high)` slider range in degrees. Default `(0, 360)`. |
| `LOOP` | `"pingpong"`: Play runs back and forth. Default wraps. |
| `TRACE` | `{label: (role, (x, y, z))}`: points whose path **Trace path** draws. Assign it inside `setup()` if the point comes from the model. |
| `TRACE_STEP` | Degrees between traced points. Default 0.5. |

The slider angle is whatever the file says it is (the crank angle).
Because every angle is **relative to the modelled pose**, the file
doesn't need to know what angle the model happened to be drawn at --
only `START` has to say which slider value matches it. Flip a `*_DIR`
constant if a part turns the wrong way.

### What `ctx` offers

* `ctx.center(part_name)` -- centre of the part's bounding box, a good
  shaft position for a symmetric part (the Geneva wheel).
* `ctx.holes(part_name, radius=None)` -- the axis point `(x, y, z)` of
  each cylindrical face (optionally only one radius), duplicates
  merged. This lets a file read pin positions **off the model** instead
  of typing coordinates in. `scott_russell.py` does this, so it works
  wherever the assembly is placed -- provided the model is in the pose
  it was built in.

### Rules of thumb

* **Everything is millimetres, world coordinates, positive angles
  counter-clockwise about the axis direction.**
* **Pick the right circle-intersection branch deterministically.** A
  four-bar has two assembly modes. `scott_russell.py` remembers which
  side of the line the model was on (the sign of a cross product at
  setup) and always picks that one, so jumping the slider never flips
  the linkage.
* **A linkage that cannot reach an angle should raise.** The dialog
  shows the message, and Trace skips such angles. Put the reachable
  interval in `RANGE`.
* **Check the mathematics outside KodaCAD first.** The kinematics and
  `trace_math.py` are plain Python; both examples were verified without
  OCP before ever being run in the app (joint distances to 3e-14 mm).

## Trace

If the file has a `TRACE`, the dialog shows **Trace path**. It sweeps
`RANGE` in `TRACE_STEP` steps, moves each traced point with the same
`gp_Trsf` as its part, and draws the path (orange, display only). It
then finds the **longest stretch that stays within a tolerance of the
straight chord joining its ends** (`trace_math.longest_straight_section`)
and draws it in bold green, reporting the slider angles at both ends,
the length, the largest deviation and the end points.

For the four-bar in `scott-russell.stp` the far hole of the C-link
gives, for the A-link angle:

| Tolerance | Slider range | Length |
|-----------|--------------|--------|
| 0.25 mm | 0.5 deg to 38 deg | 44 mm |
| 0.5 mm | -7 deg to 42 deg | 57 mm |
| 1 mm | -18 deg to 46.5 deg | 75 mm |
| 2 mm | -30.5 deg to 52.5 deg | 94 mm |

(The linkage is a pin-jointed four-bar, so the line is approximate. At
-45 deg the B-link and the coupler line up -- a dead point -- so the
slider stops at -44.9.)

## Lessons from building it (OCP/OCCT)

* `_explore()` (and `TopExp_Explorer.Current()`) return a generic
  `TopoDS_Shape`. Adaptors (`BRepAdaptor_Curve`) need a real edge:
  cast with `TopoDS.Edge_s`. An uncaught cast problem inside a
  swallowed `except` made the whole edge test silently do nothing for a
  session.
* Booleans of a shape against its own offset result (they share almost
  every face) returned nonsense in OCP 7.9. For the Move Face change
  outline we compare edges instead (`_new_edges_ais`).
* A part's shape can carry a non-identity `TopLoc_Location`. Bake it
  into the geometry (`BRepBuilderAPI_Transform` of the un-located
  shape) before comparing two shapes.
* An AIS object's `SetLocation` **replaces** its transformation (it does
  not compose), so setting an identity location restores the part.
* The displayed shapes are already in world coordinates, so a rotation
  about a world axis is all that is needed.
* Word-wrapped labels don't make a QDialog grow; a long message is
  clipped unless the dialog is grown to fit (`_fit_height`).

## Ideas, not done

* **Save the trace to the active workplane** as real sketch geometry
  (so it can be dimensioned or projected onto). Needs a look at how a
  workplane stores its geometry.
* A table of straight-section length against tolerance in the dialog.
* A **clearance check** at the current angle (OCCT already has
  `BRepAlgoAPI_Common` for overlap volume and `BRepExtrema_DistShapeShape`
  for the minimum gap), and a sweep listing the angles at which parts
  touch. Doug: not a priority.
* "Keep this pose": commit the displayed pose to the document through
  the Position path.
* A mechanism file for other linkages (a slider-crank, a Chebyshev or
  Hoeken straight-line linkage, a cam) -- each is a few lines of
  kinematics plus a `PARTS` map.
