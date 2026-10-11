# Defeaturing a part -- Removal of holes and faces 


Kodacad is built on the OCCT kibrary and kernel, which has a built-in, official algorithm for removing selected faces — BRepAlgoAPI_Defeaturing.
Here’s how it actually works, per OCCT’s own documentation: you give it a solid, and you tell it which face (or faces) represent the unwanted feature — say, the cylindrical face of a hole, or a fillet’s rounded face. The algorithm removes those faces and extends the surrounding, adjacent faces to heal the gap, as if the feature had never existed at all — not just deleting geometry and leaving a hole in the shape, but also surface extension and re-stitching, which are the harder technical problem.

In this tutorial, we will show show some examples of how this is done in KodaCAD.
We will use the file ANC101.stp to demonstrate.

### Circular Hole Removal

We will remove the yellow highlighted hole in the view below. Notice that this hole is a "through hole" between the front face and the blue highlighted hole.

* Import the file ANC101.stp into KodaCAD.
* RMB click on demo-part in the tree and choose **Set Active**.
* **Create/Modify -> Defeaturing...**
    * In the Dialog, choose Method: Remove Hole
    * Pick the yellow highlighted hole and click Apply
    * Now click on the blue hole and click Apply.

Notice the second hole is a "blind hole",  **not** a "through hole". But the algorithm still removes it.

*Claude: It would be good to summarize the way the algorithm works to detect all circular cylindrical patches sharing the same axis and the way the cap is detected on a blind hole.*

* Click Undo twice then Redo twice.

![Holes](imgs/holes.png)

### Individual Face Removal

* Rotate the part around to the view shown below.
* RMB click on demo-part in the tree and choose **Set Active**.

We will remove each of the 2 yellow highlighted features, one at a time. They are both individual blends. Once removed, the adjacent faces will revert to their prior configuration.

* **Create/Modify -> Defeaturing...**
    * In the Dialog, choose Method: Manual (pick every face)
    * Pick one of the 2 highlighted faces then click Apply
    * Pick the other highlighted face then click Apply
    * Click Done
    * Undo twice

Go through this again, but this time select both faces before clicking Apply.

![Individual Faces](imgs/individual-faces.png)

### Multiple Faces

* Rotate the part around to the view shown below.
* RMB click on demo-part in the tree and choose **Set Active**.

Now we're going to ust the "Manual method" but this time we will pick each face in the 2 yellow highlighted features shown in the screenshot below. It can be a little tedious (and unforgiving if you accidentally skip one of the faces of the feature).

* **Create/Modify -> Defeaturing...**
    * In the Dialog, choose Method: Manual (pick every face)
    * Pick each and every face in one of the 2 features highlighted in yellow, then click apply.
    * Do the same for the other feature.
    * Click Done
    * Click Undo twice
    * Click Redo twice

![Multiple Faces](imgs/multi-faces.png)

### Automatic Detection of Isolated Features

Now we will do it the easy way. In this [article](https://analysissitus.org/features/features_isolate-features.html), Sergey Slyadneva describes an algorithm for detecting "Isolated Features" in a part. Instead of manually selecting all the faces of a feature, it is often possible to use a feature detection algorithm to see if a face contains any "Isolated Features". We're doing somthing similar.

Here's how the agorithm works: 
1. Build the whole part’s face-adjacency graph (faces sharing an edge are adjacent). 
2. Delete the picked face from that graph. What’s left splits into separate connected islands. 
3. One island is just “the rest of the part,” reached through the picked face’s own outer boundary — discard it. 
4. Any other island that touches every edge of one of the picked face’s own inner wires is the feature itself.

* Rotate the part around to the view shown below.
* RMB click on demo-part in the tree and choose **Set Active**.
* **Create/Modify -> Defeaturing...**
    * In the Dialog, choose Method: Auto (pick capping face(s))
    * Click on the blue face that caps the 2 pocket features and click Apply
    * Click on the purple face that caps the 9 blind holes arranged in a circle and click Apply.
    * Click Done
    * Click Undo twice
    * Click Redo twice

![Capping Faces](imgs/capping-faces.png)

### Automatic Detection between 2 Capping Faces

This final demo will be to remove the hole (with multiple conterbores) that is capped between the top purple face and the bottom face (also purple).

* RMB click on demo-part in the tree and choose **Set Active**.
* **Create/Modify -> Defeaturing...**
    * In the Dialog, choose Method: Auto (pick capping face(s))
    * Click on the purple top face then click on the bottom purple
    * Click Apply.
    * Click Done
    * Click Undo
    * Click Redo

![Bottom Cap](imgs/bottom-cap.png)
