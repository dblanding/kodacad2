# Lofting Tutorial

In a typical workflow, a profile on a workplane is **pulled** so that it sweeps through 3D space. As it sweeps through space, it will add or remove material to/from a 3-Dimensional shape. By contrast, in lofting, a stationary **Set** of multiple workplanes, each containing a profile, is used to define a smooth surface such as the hull of a boat or the skin of an airplane fuselage. The process of using such a **workplane set** to define the shape of a part is referred to as **lofting**. Other uses of lofting are an airplane wing or a turbine blade.

In this tutorial, it will be shown how to build a simple lofted part using a workplane set.

We start with a workplane which will be used to "anchor" the new workplane set. The anchor is not actually going to be part of the set. It just defines the location of the set. 

For our example, we will use **Workplane -> At Origin, XY Plane**

![WP1 will "anchor" the new workplane set](imgs/wp1.png)

Once wp1 is created, we will draw a construction circle with its center at the origin and radius = 30. We won't need that construction circle until much later in the tutorial.

Next, click **Workplane -> Set...**

![](imgs/set.png)

This launches a dialog which will allow us to specfy:
1. The total number of parallel workplanes that will be contianed in the set
2. The uniform spacing between the workpanes, starting with the space between wp1 and the first of the workplanes in the set.

![](imgs/set-dialog.png)

Clicking the "Done" button creates "s1", the set containing workplanes numbered wp2 through wp6. They are shown both in the viewport and in the tree. The last one created is currently shown "active", indicated by the green highlighting in the tree. Only the **Active workplane** can be drawn on. You are going to need to pay attention to this when you create the circular profiles in the next step.

![](imgs/s1start.png)

In this step, a circular profile is drawn on each of the workplanes. The centers are all located at the wp origin (where the horizontal and vertical construction lines intersect). The circle radii start at 15 mm (on wp2 & wp6) then go to 20 mm (on wp3 & wp5), and 25 mm on wp4.

![](imgs/s1-profiles.png)

After all the profiles are drawn, we need to create an empty part. RMB click on the **'/'** symbol in the tree, then choose **Create Empty Part**. Name it "inner-loft". It will be show highlighted in yellow, indicating that it is the active part.


![](imgs/create-empty-inner-loft.png)

Once we have an active part and have a set containing an active workplane, go to the menubar and click **Create/Modify**. Then, click on **Loft** to generate the resulting lofted part.


This part will actually be used as a **subtractive** tool in the construction of the final result. It's outer surface will end up being the inner surface of the final resulting shape. We'll talk more later about why it's being done this way.

![](imgs/inner-lofted.png)

Next we are going to repeat the steps that went into creating the inner-loft and we will create the outer-lofted part. In the screenshot below, you can see that we have created a 2nd set, s2, with circular profiles that have radii 5 mm larger than the profiles used to create the inner-loft. The new radii go from 20 mm at the ends to 30 mm in the center.

![](imgs/s2-profiles.png)

Again, once the profiles are drawn, the steps to create the loft are the same.
1. Create an empty part, and give it a name. It must be active.
2. Make sure there is an active workplane in the set that will be used.
3. **Create/Modify -> Loft**

At this point, we have created 2 lofted parts superimposed. We will do a boolean subtraction operation to *subtract* the inner one from the outer one, resulting in a 5 mm thick shell whose outer face and inner face were both created by lofting. Why go to the trouble of lofting the inner face? Why not just use the shell operation and set the thickness to 5 mm? The reason, as it turns out, is that when we subsequently add more features (operations), we may still want to be able to remove those features using **Defeaturing** functionality. For some reason, fillets and chamfers adjacent to a shelled face do not cooperate with the defeaturing operation.

### The Boolean Subtraction

With the outer part active, click **Create/Modify -> Boolean...**

This will launch the Boolean Dialog.
1. Choose Operation: Subtract
2. Choose Tool part: inner-loft_1
3. Make sure "Merge seam faces" is checked. This heals any "scar lines" that might occur where part edges of one part land on an otherwise smooth, continuous face of the finished part.

![](imgs/subtract-dialog.png)

And here is the result of the subtraction.
1. Now would be an excellent time to save the session. Saving the session creates a step file, which does a really nice job of saving 3D geometry and assembly hierarchy, but workplanes are not saved.
2. It would also be a good time to make sure the Undo steps that went into creating this lofted part are all available. Undo/Redo steps won't be avialble when re-loading a saved session file.

The good news is that all the following steps in the tutorial can be easily performed by starting with the re-loaded session file.

![](imgs/subtract-done.png)

### Punching a transverse hole in the lofted part

At the beginning of the tutorial, when we created wp1, we made a construction circle, noting that we would use it later. Well, it's time. After making wp1 active, click **Workplane -> By 3 points**. Click first on the center of the construction circle on wp1 to specify the origin, then on the intersection of the circle and the vertical consruction line to specify the +W direction of the new workplane. Third, specify the +U direction by clicking on the intersection of the circle with the horizontal consruction line.

After creating the new workplane, we want to draw a 10 mm radius circle profile on it, located at the center of the lofted part, as shown in the screenshot below. To aid in finding the center of the part, you can project the top and bottom faces of the part, then construct a bisector between them.

![](imgs/pull-profile.png)

Now, with the new workplane active and with the lofted part active, click **Create/Modify -> Pull**. This will display the Pull Dialog. Complete the option selections as shown in the screenshot below.

![](imgs/pull-dialog.png)

Click Done to create the transverse hole in the front face of the lofted part, as shown in the section view below.

![](imgs/section-view.png)

### Apply Fillets

It's now time to apply fillets (or chamfers) to all the sharp edges of the part, including the top, the bottom, and also around the perimeter of the trasnverse hole.

![](imgs/fillets.png)

### Test Defeaturing

Once these fillets are applied, test that they can be removed using the defeaturing tools available by clicking **Create/Modify -> Defeature...**.

### Other Tests
Other tests include:
* Save/Load session
* Create shared Instance
* Create copy
