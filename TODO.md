# KodaCAD TODO

> A good tool should be a **Pleasure** to use.

* This file is a collection of suggestions for improving workflow.
* Tracks outstanding issues and future development ideas.
* Both developer and user contributions are welcome.

---

## 1. Broken: (should work but doesn't or doesn't always work)

#### Version string from OCP
* Re-add the OCP/OCCT version string to the title bar:
```python
from OCP.Standard import Standard_Version
title += f"(Using: OCP {Standard_Version.OCC_VERSION_COMPLETE} with PySide6)"
```

#### Component part names in goBILDA step files don't show in tree (but they do show up in Basicad)

#### View Cube is inoperable when wp is shown (corners, edges, faces of cube no longer highlight)

#### Sometimes RMB -> 'Set Active' doesn't work on the 1st try. (re-click)

#### Deleting geom arc overlaying c-circle is tricky (Because both are selectable)

#### Name of top assembly (of session) can be edited, but new name doesn't survive save/load rnd trip

---

## 2. UI improvement ideas

### 2D

#### Add More workplane creation modes
* Point & Direction
    1. Click point (sets origin)
    2. Click face (sets +W direction)
    3. Click face (sets +U direction)

#### Label Workplanes in viewport
* Display "w1", "w2" etc. in the lower-left corner of each wp
    * Makes wp identifiable
    * identifies U, V directions clearly
    * Possible approach: `AIS_TextLabel`

#### Control workplane size automatically

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

#### Access center point of circles and arcs using ctrl+shift keys
* In HP SolidDesigner (later CoCreate Modeling / Creo Elements/Direct Modeling), holding down Ctrl + Shift while moving the mouse temporarily forces the catch/snap mode to the center of circles and arcs. 
* Using the Center Snap Modifier
    * Key combination: Hold Ctrl + Shift simultaneously while an active command expects a point input.
    * Behavior: It overrides current settings to temporarily catch center points of circles/arcs (and midpoints of straight edges).
    * Visual cue: The flyby highlighting changes dynamically on the element as you hover over it.

### 3D

#### Create a new assembly

#### Copy part/assembly (both shared or copied)
* Add "Duplicate" to the RMB context menu. Should create an
independent copy at the same world position, ready to reposition.

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

#### Auto append of '_n' to part names. Why is that?

#### Remove test items in "Modify Active Part" menu
* "Rotate Active Part"
* "Reverse Rotate Active Part"

---

## 3. Future development ideas (Big jobs - Not likely any time soon)

#### Undo/Redo
OCCT's `TDocStd_Document` has built-in undo/redo support via
`TDocStd_Document::NewCommand()` and `Undo()`/`Redo()`. This would
be a significant quality-of-life improvement.

#### Native save format
Currently uses STEP as a save/load surrogate. OCCT's native
`.xbf` (BinXCAF) format preserves more data and is faster. The
infrastructure is in `docmodel.py` (`save_doc`, `open_doc`) but
is not exposed in the UI. Color and name preservation on round-trip
would also be better with native format.


