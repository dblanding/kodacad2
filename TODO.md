# KodaCAD TODO

### A good tool should be a *Pleasure To Use*.

* This file is a collection of suggestions aimed at making Kodacad a *Pleasure To Use*, mostly by improving workflow on *typical* projects.
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

#### View Cube is inoperable when 2D drawing tools are in use (corners, edges, faces of cube no longer highlight)

#### Sometimes RMB -> 'Set Active' doesn't work on the 1st try. (re-click)

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

### 3D

#### Clicked part in tree highlights in viewport, and vice versa (like Cad Asst)

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

#### Remove test items in "Modify Active Part" menu
* "Rotate Active Part"
* "Reverse Rotate Active Part"

#### In the header of step files, there is a FILE_NAME field:
```
FILE_NAME(
/* name */ '3209-0004-0001.step',
/* time_stamp */ '2025-02-26T09:28:08-06:00',
/* author */ (''),
/* organization */ (''),
/* preprocessor_version */ 'ST-DEVELOPER v20',
/* originating_system */ 'Autodesk Translation Framework v13.20.0.188',
/* authorisation */ '');
```
Different step files have vastly different formats. The example above is one.
Can we "personalize" this?

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


