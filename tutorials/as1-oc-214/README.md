# Tutorial: Assembly Structure with `as1-oc-214.stp`

Where the OCC Bottle tutorial builds a single part from nothing, this
one is about KodaCAD's handling of an assembly that already exists.
`as1-oc-214.stp` is a genuine multi-part assembly (a top assembly
`as1`, with a pair of shared L-bracket assemblies among its
components) -- the natural file for exercising how KodaCAD loads,
displays, and modifies structure it didn't just build itself.

This tutorial covers only the material specific to *this* file. Sibling-
assembly creation, reparenting, creating and positioning a shared
instance from scratch, and undo/redo across a mixed chain of
operations are covered instead by the [Quaoar Chassis
tutorial](../chassis/README.md), which builds that structure directly
rather than exploring a pre-built one -- a more concrete way to
exercise the same mechanisms.

## What this exercises

Both STEP loading paths and why each is safe against `/` accumulation;
the XDE hierarchy viewer; recognizing a shared prototype from its
referring components; fillet propagation across two *pre-existing*
shared instances (as opposed to the Chassis tutorial's freshly-created
one); toggling transparency from the tree's own RMB menu; deleting one
of two shared instances and confirming the other survives intact; and
Mill (material removal, as opposed to Pull's material addition)
through the Mill/Pull dialog's own operation-linked direction default.

---

## Step 1 -- Load the file two ways, and see why each is safe

1. **File -> Load Session**, choose `as1-oc-214.stp`. The assembly
   appears under `/` -- this *replaces* whatever was open.
2. Restart, then **File -> Import STEP**,
   choose the same file. This time it's *added* as a new component
   under the current `/`, alongside anything else already open.

Load file `as1-oc-214.stp` as session | Import file `as1-oc-214.stp` into empty session
-------------|--------------
![as1-oc-214 Session](imgs/session.png) | ![as1-oc-214 Import](imgs/import.png)

*Exercises: the two loading mechanisms documented in the README's
"Loading a STEP file" section -- Load Session replaces the whole
document (structurally immune to `/` accumulation), Import STEP adds
under the existing root (the one path that explicitly unwraps a
saved-session's own `/` wrapper before nesting its children).*

## Step 2 -- Explore the structure

**Utility -> XDE Label Hierarchy...** Walk the tree that opens.

Note which labels are components (occurrences, referring to a
prototype) versus the prototypes themselves.

Format: component  name-of-component => prototype

Load file `as1-oc-214.stp` as session | Import file `as1-oc-214.stp` into empty session
-------------|--------------
![Session Tree](imgs/session-tree.png) | ![Import Tree](imgs/import-tree.png)

*Exercises: XDE hierarchy viewer; recognizing a shared prototype from
its referring components.*

## Step 3 -- Fillet a shared part

Set one of the shared L-bracket instances active, **Modify Active
Part -> Fillet** on one of its corners. Confirm *both* L-brackets
(every instance sharing that prototype) show the fillet, not just the
one you picked.

![Fillet one L-Bracket](imgs/fillet-bracket.png)

*Exercises: fillet's propagation to every instance sharing a
prototype -- a prior bug left sibling instances' displays stale even
though the underlying shared geometry was already correct. Doing this
on `as1-oc-214.stp` specifically (rather than a freshly-created shared
instance, as in the Chassis tutorial) confirms the fix also holds for
sharing relationships that came in from an imported file rather than
being built in the current session.*

## Step 4 -- See through the plate

RMB click `plate` in the tree and select **Set Transparent**. Confirm
the plate becomes see-through in the viewport, revealing the bolt
heads and L-bracket geometry that would otherwise be hidden beneath
it. RMB click `plate` again and select **Set Opaque** to restore it.

*Exercises: Set Transparent / Set Opaque from the tree's own RMB
menu -- neither has appeared in any tutorial before this one.*

## Step 5 -- Delete one of the shared L-bracket assemblies

RMB click `l-bracket-assembly_2` (or whichever of the two shared
instances you didn't fillet in Step 3) and select **Delete**. Confirm:

* The deleted instance disappears from both the tree and the
  viewport.
* The *other* L-bracket assembly is completely unaffected -- still
  present, still filleted, still correctly showing every nut, bolt,
  and bracket it had before.

*Exercises: deleting one occurrence of a shared prototype while the
other survives -- the underlying prototype must not be torn down
just because one of its two occurrences was removed, since the
remaining occurrence still refers to it. `Delete` hasn't been
exercised on a part or assembly in any tutorial before this one
(only once before, briefly, on a workplane).*

## Step 6 -- Mill a hole into the plate

* **Workplane -> On Face**, click the plate's top face, then a side
  face for the +U direction.
* Sketch a circle somewhere on the plate that doesn't intersect any
  existing hole.
* Set the plate active, then **Modify Active Part -> Mill / Pull**.
* In the dialog:
  * Operation: **Remove material (Mill)** -- Direction defaults to
    **-W** automatically once Mill is selected (cutting straight down
    into the part), unless you touch the Direction field yourself.
  * Distance (mm): enter something less than the plate's own
    thickness.
  * Click **✅ Done**.
* Confirm the hole appears in the viewport, cut straight down into
  the plate.

*Exercises: Mill -- Pull has been used repeatedly across other
tutorials (the Bottle's neck, elsewhere), but Mill (material
*removal* through the same dialog) has never been demonstrated
anywhere until this step. Also exercises the dialog's own
operation-linked direction default.*

---

## Notes for whoever runs this next

- If any menu label, dialog control name, or button text has drifted
  from what's written here, that's worth fixing in this document
  directly -- catching that drift is exactly what this tutorial is
  for.
- See the [Quaoar Chassis tutorial](../chassis/README.md) for the
  broader assembly-construction workflow: creating sibling assemblies,
  reparenting, creating and positioning a shared instance, and
  undo/redo across a mixed chain of position- and shape-changing
  operations.
- See [Build Assembly `as1` from a Kit of Parts](../build-as1-oc-214/README.md)
  for the reverse of this tutorial: starting from `as1-oc-214`'s five
  loose prototype parts and rebuilding the real assembly from scratch,
  exercising nearly every Position dialog method along the way.
- See the [Lathe tutorial](../lathe/README.md) for organizing and
  navigating a large, messily-imported assembly -- renaming, sibling
  assemblies, and reparenting an assembly that already has a parent
  to a different one.
