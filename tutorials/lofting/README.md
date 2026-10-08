# Tutorial: Lofting a Hollow Part Through a Workplane Set (`loft-demo.stp`)

In a typical workflow, a profile on a workplane is **pulled** so that it
sweeps through 3D space, adding material to a part or removing it. In
**lofting**, a stationary **Workplane Set** -- several workplanes, each
holding a profile -- defines a smooth surface that passes through all of
the profiles, like the hull of a boat or the skin of an airplane
fuselage. Other typical uses are an airplane wing or a turbine blade.

This tutorial builds a simple lofted vase and then works it over: a
hollow wall made by subtracting one lofted part from another, a
transverse hole, fillets, and finally Defeaturing to take the fillets
back off. It doubles as a regression test for the Workplane Set, Loft and
Boolean tools.

## What you'll need

A fresh (empty) KodaCAD session. `loft-demo.stp`, in this folder, is the
finished part (fillets included) for comparison, or for trying the
Defeaturing and Other Tests steps without rebuilding the part first.

## What this exercises

Workplane creation, construction circles, **Workplane -> Set...**,
drawing profiles on the individual workplanes of a set, Create Empty
Part, **Loft**, **Boolean** (Subtract, with seam merging), Save Session
and the Undo/Redo caveat that goes with it, **Workplane -> By 3 points**,
**Pull** (Remove Material, Linear), Fillet, **Defeaturing** (including
what happens to the surface seam), and afterwards Create Shared Instance
and Copy Part on a lofted part.

---

## Step 1 -- Create the reference workplane

We start with a *Reference workplane*, which *anchors* the new workplane
set. It is not itself a member of the set -- it only defines where the
set goes.

**Workplane -> At Origin, XY Plane**

![wp1, the Reference workplane that anchors the new workplane set](imgs/wp1.png)

Once wp1 exists, draw a construction circle on it with its center at the
origin and radius = 30. We don't need it yet, but we will use it in Step
8 to place another workplane.

*Exercises: workplane creation; construction circle.*

## Step 2 -- Create the Workplane Set

**Workplane -> Set...**

![Workplane -> Set... menu item](imgs/set.png)

The dialog asks for:

1. **Number of workplanes (N)** -- how many parallel workplanes the set
   will contain.
2. **Spacing along +W** -- the uniform spacing between workplanes,
   starting with the space between the Reference workplane and the
   first workplane of the set.

For this tutorial use **N = 5** and **Spacing = 20** mm.

![Create Workplane Set dialog](imgs/set-dialog.png)

Click **Done**. This creates `s1`, the set containing `wp2` through
`wp6`. They appear both in the viewport and in the tree. The last one
created is **active**, shown with green highlighting in the tree. Only
the active workplane can be drawn on, so keep an eye on this in the next
step.

![Workplane set s1, before any profiles](imgs/s1start.png)

*Exercises: Workplane Set creation; the active workplane.*

## Step 3 -- Draw the inner profiles

Draw one circular profile on each workplane of `s1`. To draw on a
workplane, first make it active (RMB the workplane in the tree, then
**Set Active**). Each circle is centered on the workplane's origin (where
the horizontal and vertical construction lines cross). The radii are:

| Workplane | wp2 | wp3 | wp4 | wp5 | wp6 |
|-----------|-----|-----|-----|-----|-----|
| Radius (mm) | 15 | 20 | 25 | 20 | 15 |

![The five inner profiles on s1](imgs/s1-profiles.png)

*Exercises: switching the active workplane; circle profiles.*

## Step 4 -- Loft the inner part

Lofting needs an empty part to receive the result. RMB the **'/'** in
the tree and choose **Create Empty Part**. Name it `inner-loft`. (The
tree shows it as `inner-loft_1`, as usual for a part's occurrence name.)
It is highlighted in yellow, which means it is the **active part**.

![Create Empty Part](imgs/create-empty-inner-loft.png)

With an active part, and with a workplane of the set active, click
**Create/Modify -> Loft**. The loft passes a smooth surface through all
five profiles.

![The inner part, lofted](imgs/inner-lofted.png)

This part is a **subtractive tool**: its outer surface becomes the
*inner* surface of the finished shape. The reason for doing it this way
instead of using Shell is explained in Step 6.

*Exercises: Create Empty Part; Loft (workplane set identified by its
active workplane).*

## Step 5 -- Loft the outer part

Repeat the process for the outer surface. First make **wp1** the active
workplane again -- it is the Reference workplane for the next set -- and
create a second set, `s2`, with **Workplane -> Set...** using the same N
= 5 and Spacing = 20. Then draw circles whose radii are 5 mm larger than
the inner ones:

| Workplane | wp7 | wp8 | wp9 | wp10 | wp11 |
|-----------|-----|-----|-----|------|------|
| Radius (mm) | 20 | 25 | 30 | 25 | 20 |

![The five outer profiles on s2](imgs/s2-profiles.png)

Then, as before:

1. Create an empty part and name it `outer-loft`. It must be active.
2. Make sure one of the workplanes of `s2` is active.
3. **Create/Modify -> Loft**

We now have two lofted parts, superimposed.

*Exercises: a second Workplane Set; Loft again with a different set.*

## Step 6 -- Subtract the inner part from the outer part

The next operation subtracts the inner part from the outer part,
leaving a 5 mm wall whose outer and inner surfaces were both created by
lofting.

*Why not simply Shell the outer part with a thickness of 5 mm?* Because
later we will want to remove or modify features such as fillets using
**Defeaturing**. In our testing, fillets and chamfers adjacent to a
*shelled* surface cannot be removed by Defeaturing -- the operation
reports success but leaves the feature in place -- whereas the same
fillets next to a *lofted* inner surface can. We don't know exactly why
Shell causes this, but lofting the inner surface avoids it.

With the outer part active, click **Create/Modify -> Boolean...**, which
opens the Boolean dialog.

1. **Operation:** Subtract.
2. **Tool part:** `inner-loft_1`.
3. Leave **Merge seam faces** checked. This heals "scar lines" that can
   appear where the edges of the original parts land on what should be
   one smooth, continuous face of the result.

![Boolean dialog, Subtract](imgs/subtract-dialog.png)

Click **Done**. The tool part is consumed by the operation, so only the
hollow `outer-loft_1` remains.

![The lofted part after subtraction](imgs/subtract-done.png)

*Exercises: Boolean Subtract with a part as the tool; seam merging; the
tool part being removed from the tree.*

## Step 7 -- Save the session

Two things worth doing right now:

1. **File -> Save Session.** A STEP file stores 3D geometry and the
   assembly hierarchy very well, but it does not store workplanes.
2. If you want to look back, this is also the time to check that the
   Undo steps that built the part are available. Undo/Redo history is
   **not** saved in the file, so it is gone after a reload.

**Warning:** if you click Undo all the way back to the very first
operation, this session is toast -- you will be back to an empty
session. Save first (step 1) before experimenting with that particular
stick of dynamite.

The good news is that every remaining step can be done just as well
starting from the reloaded session file.

*Exercises: Save Session; the Undo/Redo limits across a save/reload.*

## Step 8 -- Punch a transverse hole

Back in Step 1 we drew a construction circle on wp1 and said we would use
it. Now is the time. Make wp1 active, then click **Workplane -> By 3
points** and pick, in order:

1. the **center** of the construction circle -- the origin of the new
   workplane;
2. the **lower intersection** of the circle with the vertical
   construction line -- this sets the **+W** direction;
3. the **right-hand intersection** of the circle with the horizontal
   construction line -- this sets the **+U** direction.

On the new workplane, draw a circle profile of **radius 10 mm** at the
center of the lofted part. To find the center, project the top and bottom
faces of the part onto the workplane and construct the bisector between
them.

![The new workplane with its pull profile](imgs/pull-profile.png)

Now, with the new workplane and the lofted part both active, click
**Create/Modify -> Pull** and choose:

* **Operation:** Remove Material
* **Mode:** Linear
* **Direction:** +W
* **Total Distance:** 35

![The Pull dialog](imgs/pull-dialog.png)

Click **Done**. The hole goes through the front wall of the part, as the
section view below shows.

![The lofted part in section view](imgs/section-view.png)

*Tip:* choose **Direction: Both** to cut through both walls at once. The
Total Distance is split equally between +W and -W, so a Total Distance
above 70 clears both walls.

*Exercises: Workplane -> By 3 points; projecting faces onto a workplane;
Pull, Remove Material, Linear, +W (and Both).*

## Step 9 -- Apply fillets

Apply fillets (or chamfers) to all the sharp edges of the part: the top,
the bottom, and both rims of the transverse hole. The wall is only 5 mm
thick, so choose a radius comfortably under that (1.5 mm, say).

![The lofted part, complete](imgs/fillets.png)

*Exercises: Fillet, including edges next to lofted (B-spline) surfaces.*

## Step 10 -- Test Defeaturing

Now check that the fillets can be taken back off. Open
**Create/Modify -> Defeaturing...**, choose **Manual (pick every face)**,
click the faces of one fillet, then Apply. Repeat for the others.

Two things to notice:

* All of the fillets should be removable, including those next to the
  *inner* lofted surface -- which is exactly why Step 6 went to the
  trouble of lofting it.
* If you remove several fillets together as one group, "scar lines" can
  be left on the lofted face along the circle where each fillet met it.
  Removing the fillets one at a time does not leave them. If a seam does
  remain, pick the smaller of the two faces with the **Manual** method
  and Apply, and the seam is gone.

*Exercises: Defeaturing (Manual); fillets next to a lofted surface; seam
cleanup.*

## Step 11 -- Other tests

Repeat any of these on the finished lofted part:

* **Save Session**, then **Load Session**: names and color should
  survive.
* **Create Shared Instance** (RMB the part), move the instance, then
  modify the original (for example, cut the hole with Pull): both
  instances should update.
* **Copy Part** (RMB), move the copy with **Position**, then remove a
  fillet from the copy only: the original and its shared siblings should
  stay unchanged.

*Exercises: STEP round trip of lofted geometry; shared-instance redraw;
independent copies.*

---

## Notes for whoever runs this next

- If any menu label, dialog control name, or message has drifted from
  what is written here, fix it in this document directly -- catching
  that drift is exactly what this tutorial is for.
- Fillet and chamfer radii in Step 9 are a suggestion, not a requirement;
  anything that fits within the 5 mm wall works.
- See the [OCC Bottle tutorial](../occ-bottle/README.md) for the Shell
  operation, which is the road not taken in Step 6.
- See the [Jack-o'-Lantern tutorial](../jack/README.md) for more of
  Pull and the 2D sketch toolbar.
