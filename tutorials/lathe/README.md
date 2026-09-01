# Tutorial: Assembly Structure with `manual-lathe.step`

This tutorial addresses some issues that are encountered when working with a model that consists of several imported parts and assemblies that are integrated into a larger overall assembly.

The file `manual-lathe.step` was built by importing several parts and assemblies found online at the goBILDA website, and then arranging them into an apparatus whose function is similar to the headstock of a lathe, driven by hand using a crank.

Several of the topics in this tutorial will show how to make the model easier to navigate:

* Tree checkbox bottom-up derivation + expand/collapse persistence
* Renaming parts and assemblies using functionally descriptive names
* Creating sibling assemblies
* Reparent an assembly that already has a parent to a different parent
* Reposition it using Dynamic / Align Gizmo to Active Workplane / Nudge
* Workplane → By Point & Direction

## What this exercises

*TBD by claude*

---

## Step 1 -- Load the file:

* **File -> Load Session**

If you use your imagination, hopefully you can notice some functional similarity with a lathe headstock, a spindle (hex shaft) supported on 2 bearings, with a face_plate on the right, and a crank (arm) on the left.

But looking at the tree, you can see that the names of the parts and assemblies are not very descriptive.

![Manual Lathe Assembly](imgs/lathe0.png)

## Step 2 -- Assign more descriptive names:

Assign functionally descriptive names to the children of the top assembly. This will make it easier to navigate the model.

![Named Components](imgs/names.png)

## Step 3 -- Create 2 subassemblies under top assembly

When working with an assembly, doing certain operations causes the viewport to be redrawn, so in the interest of speed, it helps to limit the number of items being displayed. To do this, it can help to clump things into functional subassemblies, and then only display the ones being currently worked on. In this step we will create 2 sibling assemblies under the manual-lathe assembly.

1. Collapse the child components of manual-lathe assembly in the tree. This collapsed tree configuration should persist throughout the session.
2. RMB click on manual lathe and select Create New Assembly. Name the new assembly "stator-asy"
    * Notice how long it took to complete this operation.
    * Now click to hide manual-lathe then proceed to the next step.
3. RMB click on manual-lathe and select Create New Assembly. Name the new assembly "rotor-asy".
    * Did you notice that this operation completed "instantly" this time?
    * It takes time to redraw the viewport so it makes sense to hide all but the things you are working on at the moment.

* The two new assemblies will appear in the tree as siblings under manual-lathe.
* The draw/hide configuration set previously should persist.
* The expand/collapse configuration should also persist.
* The tree should now show rotor-asy as the only checked child. The creation of a new assembly is checked (by default).
    * This causes its parent assembly to also be checked.

*Claude: I noticed that stator-asy also became checked.*

![Two Sibling Assemblies Added](imgs/siblings.png)

## Step 4 -- Drag and drop components into rotor-asy or stator-asy

Uncheck manual-lathe assembly to hide everything.

* Drag and drop each of the original child components of manual-lathe into either rotor-asy or stator-asy, as appropriate.
* Try it with everything hidden. Everything should stay hidden.

*Claude: I started by dragging items into rotor-asy and noticed that as each was dropped, the empty stator-asy would become checked. I also noticed that when I dropped a part (spindle or faceplate), it would get displayed. When an assembly got dropped, it remained hiddedn but got expanded. Next, after unchecking stator-asy, I brought components into it, starting with the base. This got displayed. Finally, the bearing-block-asy instances, which remained hidden, also got expanded.* 

![Rotor & Stator Populated](imgs/populated.png)

* Now, to set up step 5, RMB click on bearing-block-asy_1 and choose **Create Shared Instance**. Name it "bearing-block-asy_3" and drag it (in the tree) from the stator-asy into the rotor-asy.

![Bearing Block 3 added](imgs/bb3.png)

## Step 5 -- Reposition the new "bearing-block-asy_3"

* We will reposition "bearing-block-asy_3" by rotating it 180 degrees aroung the spindle axis and moving it to the center of the manual-lathe assembly
* In order to rotate it around the spindle axis, we will first need to create a workplane with its origin on the spindle axis:
    * **Workplane -> Point & Direction**, ctrl+shift click on a circular arc on the end of the spindle, then click on the top face of the base for the W direction, then a side face of the base for the +U direction.
    * This creates a workplane with its W axis colinear with the spindle axis.
* Select bearing-block-asy_3, then **Position -> Position Selected**
* Choose method **Dynamic**.
    * Click **Align Gizmo to Active Workplane**.
    * Enter `180` in the **rZ** field, then **Apply Nudge** to preview
    the move.
    * If it looks wrong, **Back** and try again; if it looks right, proceed

![Dynamic Nudge](imgs/nudge.png)

* While still in dynamic mode:
    * After the 180 degree nudge, the manipulator moves back to its default position.
    * Use a handle to move it in the Y direction to the center.
    * Commit the move by clicking **Done**.

*Claude: The new user will undoubtedly meet with some frustration when using the AIS manipulator (as I did). If the cursor just happens to fly over the manipulator, it will respond to the next drag event that occurs, regardless of where it occurs in the viewport. To transfer the receiver of drag events back to the orbit controls, a click somewhere in the background is needed. Then the orbit controls will receive the drag events.*

![Move complete](imgs/bb3-moved.png)



