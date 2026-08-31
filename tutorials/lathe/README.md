# Tutorial: Assembly Structure with `manual-lathe.step`

This tutorial addresses some of the issues that are encountered when dealing with a model that consists of several imported parts and assemblies that are integrated into a larger overall assembly.

The file `manual-lathe.step` was built by importing several parts and assemblies found online at the goBILDA website, and then arranging them into an apparatus whose function is similar to the headstock of a lathe, driven by hand using a crank.

Many of the topics in this tutorial will show how to make the model easier to navigate:

1. Tree checkbox bottom-up derivation + expand/collapse persistence
2. Renaming parts and assemblies with names that are functionally descriptive
3. Creating sibling assemblies
4. Reparent an assembly that already has a parent to a different parent
Then Reposition it using dynamic / Align Gizmo to Active Workplane / Nudge
6. Workplane → By Point & Direction
 

## What this exercises

*TBD by claude*

---

## Step 1 -- Load the file:

* **File -> Load Session**

If you use your imagination, hopefully you can notice some functional similarity with a lathe headstock, a spindle (hex shaft) supported on 2 bearings, with a face_plate on the right, and a crank (arm) on the left.
Looking at the tree, you can see that the names of the parts and assemblies are not very descriptive.

![Manual Lathe Assembly](imgs/lathe0.png)

## Step 2 -- Assign more descriptive names:

Assign functionally descriptive names to the children of the top assembly. This will make it easier to navigate the model.

![Named Components](imgs/names.png)

## Step 3 -- Create 2 subassemblies under top assembly

When an assembly grows in size (number of components), redrawing the viewport can take longer if everything is being displayed. By clumping things into functional subassemblies, and by only displaying the ones being currently worked on, the application will be able to execute operations more quickly.

1. Collapse the child components of manual-lathe assembly in the tree. This collapsed tree configuration should persist throughout this session.
2. RMB click on manual lathe and select Create New Assembly. Name the new assembly "stator-asy"
    * Notice how long it took to complete this operation.
    * Now click to hide manual-lathe then proceed to the next step.
3. RMB click on manual-lathe and select Create New Assembly. Name the new assembly "rotor-asy".
    * Did you notice that this operation completed "instantly" this time?
    * It takes time to redraw the viewport so it makes sense to hide all but the things you are working on at the moment.

* The two new assemblies should appear in the tree as siblings under manual-lathe.
* The draw/hide configuration set previously should persist.
* The expand/collapse configuration should also persist.
* The tree should now show rotor-asy as the only checked child.
    * This causes the parent assembly to also be checked.

![Two Sibling Assemblies Added](imgs/siblings.png)

## Step 4 -- Drag and drop components into rotor-asy or stator-asy

* Drag and drop each of the original child components of manual-lathe into either rotor-asy or stator-asy.
* Try it with everything hidden

*Claude: I noticed that when I dragged and dropped an assembly, everything stayed unchecked (hidden), but when I dragged & dropped a part (base, spindle, faceplate), the part and one or both of rotor-asy, stator-asy would become checked.* 

![Rotor & Stator Populated](imgs/populated.png)

* As a final part of this step, RMB click on one of the bearing-block-asy instances and choose **Create Shared Instance**. Name it "bearing-block-asy_3" and drag it (in the tree) from the stator-asy into the rotor-asy

## Step 5 -- Reposition the new "bearing-block-asy_3"

* We will reposition "bearing-block-asy_3" by rotating it 180 degrees aroung the spindle axis and moving it to the center of the manual-lathe assembly
* First we will need to create workplane:
    * **Workplane -> Point & Direction**, ctrl+shift click on a circular arc on the end of the spindle, then click on the end face of the base for the W direction, then a side face of the base for the +U direction.
    * This creates a workplane with its W axis colinear with the spindle axis.
* Select bearing-block-asy_3, then **Position -> Position Selected**
* Choose method **Dynamic**.
    * Click **Align Gizmo to Active Workplane**.
    * Enter `180` in the **rZ** field, then **Apply Nudge** to preview
    the move.
    * If it looks wrong, **Back** and try again; if it looks right, proceed

![Dynamic  Nudge](imgs/nudge.png)

* While still in dynamic mode:
    * After the 180 degree nudge, the manipulator moves back to its default position.
    * Use a handle to move it in the Y direction to the center.
    * Commit the move by clicking **Done**.



![Move complete](imgs/bb3-moved.png)



