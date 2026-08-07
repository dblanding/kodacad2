# KodaCAD TODO

### A good tool should be a *Pleasure To Use*.

* This file is a collection of suggestions aimed at making Kodacad a *Pleasure To Use*, mostly by improving workflow on *typical* projects.
* Tracks outstanding issues and future development ideas.
* Both developer and user contributions are welcome.

---

## 1. Broken: (should work but doesn't or doesn't always work)

#### View Cube is inoperable when 2D drawing tools are in use (corners, edges, faces of cube no longer highlight)

#### Deleting geom arc overlaying c-circle is tricky (Because both are selectable).
If operation is to delete geom lines, then perhaps c-lines and c-circles should not be selectable.

---

## 2. UI improvement ideas

#### Access center point of circles and arcs using ctrl+shift keys
* In HP SolidDesigner (later CoCreate Modeling / Creo Elements/Direct Modeling), holding down Ctrl + Shift while moving the mouse temporarily forces the catch/snap mode to the center of circles and arcs. 
* Using the Center Snap Modifier
    * Key combination: Hold Ctrl + Shift simultaneously while an active command expects a point input.
    * Behavior: It overrides current settings to temporarily catch center points of circles/arcs (and midpoints of straight edges).
    * Visual cue: The flyby highlighting changes dynamically on the element as you hover over it.

### 2D

#### Add More workplane creation modes
* Point & Direction
    1. Click point (sets origin)
    2. Click face (sets +W direction)
    3. Click face (sets +U direction) -- In Creo, this is optional. A default direction is shown.

#### Label Workplanes in viewport
* Display "w1", "w2" etc. in the lower-left corner of each wp
    * Makes wp identifiable
    * identifies U, V directions clearly
    * Possible approach: `AIS_TextLabel`

#### Adjust workplane size automatically

#### More 2D sketching tools (see Pyurcad)
* Parallel c-lines (c-lines highlight so they should be selectable.)
* Delete all Construction
* Delete all Geometry (profile)

#### Project part edges onto workplane as construction lines
Essential for referencing existing geometry when sketching.
* Pick an edge on a part and project c-line onto the active workplane.
* Pick a face and project all edges.

#### Clickable snap points on all sketch tools
* Full 2D CAD snap behavior: snap to endpoints, midpoints,
intersections, centers. Currently only cline/ccirc intersection
snap is supported. See PyurCAD for reference implementation.

### 3D

#### It would be nice if multiple items in the tree could be chosen for delete all at once.
* In a large assembly, it takes a long time to refresh after deleting each item, one at a  time.
* Also, the tree does an expand all items with each deletion. that's annoying.

#### Extrude/Mill:
* Ability to choose on the fly to add or remove mat'l
    * Choose direction on the fly: +W, -W, Both (symetric)
    * Entering a negative value doesn't work
* Can't handle 2 profiles (inner & outer wires)
* Possible to have undo here?

#### Move Face (on simple "boxy" shapes)

#### 'Scars' (Adding mat'l to an existing face leaves a line at the old edge.)
* Possible to heal these parts?

#### Booleans: (fuse, subtract, etc)

#### Ability to set, edit part color

---

## 3. Future development ideas (Big jobs - Not likely any time soon)

#### Native save format
Currently uses STEP as a save/load surrogate. OCCT's native
`.xbf` (BinXCAF) format preserves more data and is faster. The
infrastructure is in `docmodel.py` (`save_doc`, `open_doc`) but
is not exposed in the UI. Color and name preservation on round-trip
would also be better with native format.


