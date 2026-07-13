# KodaCAD TODO

This file tracks outstanding issues and future development ideas.
Both developer and user contributions welcome.

---

## 1. Broken (should work but doesn't)

### RMB FitAll not working in viewport
Right-click in the viewport should call `view.FitAll()`. The
`AIS_ViewController` consumes RMB events entirely for its own pan
gesture -- `mouseReleaseEvent` is never called for RMB clicks.
**Fix:** use Qt `eventFilter` to intercept RMB before
`AIS_ViewController` processes it, or detect the click duration.

### Color and name loss on STEP export/reload (pre-existing)
Modified parts (after fillet, shell, etc.) lose their color when
saved to STEP and reloaded. Part names inside assemblies show as
the OCCT translator string instead of the user-assigned name.
This was a known issue in the original KodaCAD 0.2.x.

### Part selection sometimes requires left-click before RMB
The context menu (Set Active, Item Info, etc.) only works if the
item was first left-clicked to select it. RMB on an unselected
item shows "No item selected." This is mildly annoying.

### Dynamic move (AIS Manipulator) moves only active part
When using Dynamic move on a sub-assembly, only the active part
moves visually during the drag. Clicking Done applies the move
correctly to the whole assembly, but the preview is misleading.

### Mate/Align fails after Dynamic move
After using Dynamic move to mis-align a part, picking faces for
Mate/Align is not registered, leaving the dialog waiting
indefinitely.

### Shelling L-brkt in as1-oc-214.stp fails

---

## 2. Known limitations (by design, not bugs)

### Modifying a shared instance in Basicad breaks sharing
This is specific to Basicad (the companion project using build123d).
`import_step()` collapses XDE references into independent Python
objects, so modifying one instance makes it a copy. KodaCAD does
NOT have this limitation -- it modifies the XDE prototype directly.

### New part position may be wrong if created in wrong context
When creating a part via workplane → extrude, the part's world
position depends on which face the workplane was placed on. If the
workplane was placed on a face that is deep inside a positioned
sub-assembly, the extruded shape appears in the correct world
position but the user must drag it to the correct assembly.
This is the correct Creo-style behavior.

---

## 3. Future development ideas

### ViewCube in viewport corner
Add `AIS_ViewCube` for click-to-orient (Top/Front/Right/Isometric).
In Basicad this was implemented using `AIS_ViewCube` with
`AIS_ViewCubeOwner` for face click detection. See
`docs/DEVELOPMENT_LOG.md` (Session 5) for implementation notes.

### Workplane label in viewport
Display "wp1", "wp2" etc. in the lower-left corner of each
workplane boundary rectangle so the active workplane is always
identifiable. Possible approach: `AIS_TextLabel` at workplane origin.

### Align Axis -- missing DOF steps
The Align Axis section in the positioning dialog only aligns the
axis direction (4 DOF). It needs two more steps:
- Axial position (slide along the axis)
- Radial/angular position (spin around the axis)

### Copy part/assembly
Add "Duplicate" to the RMB context menu. Should create an
independent copy at the same world position, ready to reposition.

### More workplane creation modes
Currently only "On Face" (two face picks) is supported. Add:
- At origin (global XY/XZ/YZ planes)
- Offset from existing face
- Through three points

### Project part edges onto workplane as construction lines
Pick an edge on a part and project it onto the active workplane
as a construction line. Essential for referencing existing geometry
when sketching.

### Clickable snap points on all sketch tools
Full 2D CAD snap behavior: snap to endpoints, midpoints,
intersections, centers. Currently only cline/ccirc intersection
snap is supported. See PyurCAD for reference implementation.

### Undo/Redo
OCCT's `TDocStd_Document` has built-in undo/redo support via
`TDocStd_Document::NewCommand()` and `Undo()`/`Redo()`. This would
be a significant quality-of-life improvement.

### Native save format
Currently uses STEP as a save/load surrogate. OCCT's native
`.xbf` (BinXCAF) format preserves more data and is faster. The
infrastructure is in `docmodel.py` (`save_doc`, `open_doc`) but
is not exposed in the UI. Color and name preservation on round-trip
would also be better with native format.

### Version string from OCP
Re-add the OCP/OCCT version string to the title bar:
```python
from OCP.Standard import Standard_Version
title += f"(Using: OCP {Standard_Version.OCC_VERSION_COMPLETE} with PySide6)"
```
