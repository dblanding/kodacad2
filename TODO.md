# KodaCAD TODO

This file tracks outstanding issues and future development ideas.
Both developer and user contributions welcome.

---

## 1. Broken (should work but doesn't)


---

## 2. Known limitations (by design, not bugs)


---

## 3. Future development ideas

### Workplane label in viewport
Display "w1", "w2" etc. in the lower-left corner of each
workplane boundary rectangle so the active workplane is always
identifiable. Possible approach: `AIS_TextLabel`

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
