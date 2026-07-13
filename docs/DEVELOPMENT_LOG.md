# KodaCAD Development Log

This document is a chronological record of the development sessions for
KodaCAD 3.0. It documents the hard-won knowledge acquired during each
session: what broke, what was discovered, what was fixed, and why.

It is written primarily for developers (and for "future Claude") who need
to understand the history of decisions made during the port from PythonOCC
+ PyQt5 + Conda to OCP + PySide6 + uv.

For user-facing documentation see `README.md`.
For outstanding issues and future ideas see `TODO.md`.

---

# KodaCAD 2

A port of [KodaCAD 0.2.2](https://github.com/dblanding/kodacad) from
PythonOCC + PyQt5 + Conda to **OCP + PySide6 + uv**.

## What is KodaCAD?

KodaCAD is a 3D CAD application built on OCCT (Open CASCADE Technology)
via Python bindings. It uses the XDE (Extended Data Framework) document
model to maintain full assembly structure, including shared part instances.
This means modifying one instance of a shared part updates ALL instances
-- the architecturally correct CAD behavior.

## Why this port?

- **No more Conda** -- `uv` handles all dependencies
- **PySide6** instead of PyQt5 (Qt6, actively maintained)
- **OCP** instead of PythonOCC (modern OCCT Python bindings used by
  build123d and CadQuery)
- Uses a proven crash-safe viewport (same AIS_ViewController pattern
  as the companion Basicad project)

## Status (initial commit)

**Working:**
- App starts with `uv run kodacad.py`
- File -> Load STEP At Top loads and displays assembly
- Assembly tree fully populated with correct part names and hierarchy
- All 18 leaf solids displayed in 3D viewport
- 3D viewport: orbit (LMB drag), pan (MMB drag), zoom (scroll)
- Checkboxes for show/hide parts

**Not yet tested / known issues:**
- Workplane creation
- Create 3D (extrude, revolve)
- Modify Active Part (fillet, shell, mill, pull, fuse)
- The goal feature: shared instance modification updating ALL instances
- Reverse-transform problem when adding new components to a positioned assembly

## Running

```bash
cd ~/Desktop/kodacad2
uv run kodacad.py
```

## Key OCC -> OCP API changes made during port

### Import paths
```python
from OCC.Core.X import Y   ->  from OCP.X import Y
from PyQt5.X import Y      ->  from PySide6.X import Y
pyqtSignal                 ->  Signal
```

### Static methods (get _s suffix in OCP)
```python
XCAFApp_Application_GetApplication()   ->  XCAFApp_Application.GetApplication_s()
binxcafdrivers_DefineFormat(app)       ->  BinXCAFDrivers.DefineFormat_s(app)
XCAFDoc_DocumentTool_ShapeTool(label)  ->  XCAFDoc_DocumentTool.ShapeTool_s(label)
XCAFDoc_DocumentTool_ColorTool(label)  ->  XCAFDoc_DocumentTool.ColorTool_s(label)
TDataStd_Name.Set(label, str)          ->  TDataStd_Name.Set_s(label, str)
topods_Edge/Face/Vertex(shape)         ->  TopoDS.Edge_s/Face_s/Vertex_s(shape)
topexp_MapShapesAndAncestors(...)      ->  TopExp.MapShapesAndAncestors_s(...)
brepbndlib_Add(...)                    ->  BRepBndLib.Add_s(...)
brepgprop_SurfaceProperties(...)       ->  BRepGProp.SurfaceProperties_s(...)
CPnts_AbscissaPoint_Length(...)        ->  CPnts_AbscissaPoint.Length_s(...)
shape_tool.GetShape(label)             ->  shape_tool.GetShape_s(label)
shape_tool.GetReferredShape(c, ref)    ->  shape_tool.GetReferredShape_s(c, ref)
shape_tool.IsSimpleShape(label)        ->  shape_tool.IsSimpleShape_s(label)
shape_tool.IsAssembly(label)           ->  shape_tool.IsAssembly_s(label)
shape_tool.GetComponents(label, ...)   ->  shape_tool.GetComponents_s(label, ...)
shape_tool.AddComponent(...)           ->  shape_tool.AddComponent_s(...)
shape_tool.AddShape(...)               ->  shape_tool.AddShape_s(...)
shape_tool.SetShape(...)               ->  shape_tool.SetShape_s(...)
```

### Instance methods (stay as-is, no _s suffix)
```python
shape_tool.GetShapes(labels)
shape_tool.GetFreeShapes(labels)
shape_tool.UpdateAssemblies()
color_tool.GetColor(...)
color_tool.SetColor(...)
```

### PythonOCC extension methods replaced with helpers in docmodel.py
PythonOCC added convenience methods to TDF_Label that don't exist in OCP.
These are replaced with module-level helper functions:

```python
label.GetLabelName()        ->  get_label_name(label)
                                Uses TDataStd_Name.Get_s(label)

label.EntryDumpToString()   ->  get_label_entry(label)
                                Uses TDF_Tool.Entry_s(label, AsciiString)

shape_tool.GetLocation(lbl) ->  get_label_location(label)
                                Uses XCAFDoc_Location.GetLoc_s(label)
```

**Critical bug found during port:** In `parse_components`, the original
PythonOCC code `c_name = c_label.GetLabelName()` was mangled by the
mechanical port to `c_name = c_label` (storing the TDF_Label object
itself as the name). Fixed to `c_name = get_label_name(c_label)`.

### Qt5 -> Qt6 changes
```python
QDesktopWidget            ->  QApplication.primaryScreen().availableGeometry()
QAction                   ->  moved from QtWidgets to QtGui
Qt.Checked                ->  Qt.CheckState.Checked
Qt.Unchecked              ->  Qt.CheckState.Unchecked
Qt.ItemIsTristate         ->  Qt.ItemFlag.ItemIsUserTristate
Qt.ItemIsSelectable       ->  Qt.ItemFlag.ItemIsSelectable
Qt.Horizontal             ->  Qt.Orientation.Horizontal
self.ExtendedSelection    ->  self.SelectionMode.ExtendedSelection
self.InternalMove         ->  self.DragDropMode.InternalMove
app.exec_()               ->  app.exec()
VERSION string removed    ->  title hardcoded as "Using: OCP with PySide6"
```

### Viewport
`myDisplay/qtDisplay.py` (PythonOCC QGLWidget-based) replaced entirely
by `koda_viewport.py`:
- `KodaViewport` -- QWidget with WA_NativeWindow + WA_PaintOnScreen
  (same proven pattern as Basicad; QOpenGLWidget conflicts with OCCT's
  own OpenGL context management)
- `DisplayShim` -- provides `canvas._display` interface for mainwindow.py
- AIS_ViewController for crash-safe mouse handling (no direct MoveTo/Select)

### OCCUtils
All files in `OCCUtils/` ported with the same OCC->OCP substitutions.
Additional fixes:
- `brepbndlib_Add` -> `BRepBndLib.Add_s`
- `topods` -> `TopoDS` (types_lut.py)
- `topexp` -> `TopExp` (edge.py, face.py, Topology.py)
- `TopTools_ListIteratorOfListOfShape` removed -- replaced with direct
  iteration over `TopTools_ListOfShape`
- `geomlib` -> `GeomLib` (edge.py)
- `face_normal` from OCCUtils.Construct reimplemented inline in workplane.py
  using OCP's `GeomLProp_SLProps`
- `BRepTools.UVBounds_s` in Construct.py and face.py
- `brepfill_Face` -> `BRepFill.Face_s` (Construct.py)

## File structure

```
kodacad2/
  kodacad.py        -- main entry point, menu setup, operation callbacks
  mainwindow.py     -- MainWindow, TreeView, UI layout
  docmodel.py       -- XDE document model (key file for shared instances)
  workplane.py      -- 2D workplane geometry
  m2d.py            -- 2D drawing toolbar callbacks
  koda_viewport.py  -- OCP viewport (replaces myDisplay/)
  stepanalyzer.py   -- STEP file structure analysis utility
  rpnCalculator.py  -- RPN calculator widget
  version.py        -- version string
  OCCUtils/         -- OCC utility functions (ported from PythonOCC)
  icons/            -- toolbar icons (copied from original kodacad)
  step/             -- sample STEP files
  pyproject.toml    -- uv project file
```

## Next steps

1. Test workplane creation on a face
2. Test fillet operation -- the key goal: verify shared instance
   modification updates BOTH l-brackets simultaneously
3. Fix the reverse-transform problem when adding new components to
   a positioned assembly (see original kodacad docs/assembly_structure/)
4. Get the OCC version string back into the title bar:
   `from OCP.Standard import Standard_Version`

---

## Session 2 fixes (after initial commit)

### Assembly location fix

**Problem:** All parts displayed at origin (prototype shapes) instead
of their assembled positions. All locations returned IsIdentity=True.

**Root cause:** `get_label_location()` used `XCAFDoc_Location.GetLoc_s()`
which doesn't exist in OCP, silently returning identity.

**Investigation:** Three approaches tested via `src/check_xcaf_loc.py`:
1. `FindAttribute(XCAFDoc_Location.GetID_s(), loc_attr)` -- WORKS on
   component labels, returns correct non-identity location. BUT segfaults
   on the root label which has no location attribute.
2. `XCAFDoc_Location.GetLoc_s(label)` -- doesn't exist in OCP.
3. `shape_tool.GetShape_s(label).Location()` -- WORKS, returns correct
   location.

**Fix:** Use `label.IsAttribute(XCAFDoc_Location.GetID_s())` to safely
check if a location attribute exists BEFORE calling FindAttribute.
`IsAttribute()` is safe on all label types including root. Only call
FindAttribute if it returns True.

```python
def get_label_location(label):
    from OCP.XCAFDoc import XCAFDoc_Location
    from OCP.TopLoc import TopLoc_Location
    try:
        if label.IsAttribute(XCAFDoc_Location.GetID_s()):
            loc_attr = XCAFDoc_Location()
            if label.FindAttribute(XCAFDoc_Location.GetID_s(), loc_attr):
                return loc_attr.Get()
    except Exception:
        pass
    return TopLoc_Location()
```

**Also fixed:** `c_name = c_label` in `parse_components` -- the mechanical
port mangled `c_name = c_label.GetLabelName()` into `c_name = c_label`,
storing TDF_Label objects as names instead of strings. Fixed to
`c_name = get_label_name(c_label)`.

### Status after session 2

**Working:**
- Full assembly displayed in correct assembled positions
- Tree shows complete hierarchy with correct part names
- All 18 leaf solids at correct world positions
- Orbit/pan/zoom navigation

**Next to fix:**
- Workplane placement: `'TopoDS_Shape' object is not iterable` error
  when clicking a face. The select callback receives a TopoDS_Shape
  but tries to iterate it (probably expecting a list).
- Test fillet on L-bracket to verify shared instance update

---

## Session 3 fixes

### Workplane on face working

**Problem 1:** `'TopoDS_Shape' object is not iterable` in select callback.
PythonOCC callbacks received `(shapeList, *args)` where shapeList is a
list. OCP's `call_select_callbacks` was passing the shape directly.
**Fix:** Wrap shape in a list: `shape_list = [shape] if shape else []`
then call `cb(shape_list, *args)`.

**Problem 2:** `Prs3d_LineAspect` constructor failing -- bare int `2`
passed for `Aspect_TypeOfLine` argument.
**Fix:** Import and use the enum:
`Aspect_TypeOfLine.Aspect_TOL_DASH` instead of `2`.

**Problem 3:** `gp_Dir::CrossCross() - zero norm` when picking two
parallel faces. This is valid user error (faces must be non-parallel).
No fix needed -- user must pick a face and a non-parallel face for U dir.

**Result:** Workplane displays correctly with:
- Cyan boundary rectangle
- Magenta H/V construction lines
- `wp1` entry in tree under WP node
- Circle drawing working (tested 10mm radius at 0,0)

**Known issue:** Intersection snap point not clickable at cline
intersection. The clickable point marker is not appearing. To fix next.

### Files changed this session
- `koda_viewport.py` -- call_select_callbacks passes shapeList not shape
- `mainwindow.py` -- Prs3d_LineAspect uses Aspect_TypeOfLine enum
- `kodacad.py` -- wpOnFaceC debug prints removed

---

## Session 4 fixes

### Fillet working with shared instance update (KEY MILESTONE)

**Problem 1:** `TopTools_ListOfShape` has no `.More()` method in OCP.
`_loop_topo` in `OCCUtils/Topology.py` used the old PythonOCC
iterator pattern. **Fix:** Replace `while occ_iterator.More():` with
`for item in occ_seq:` -- `TopTools_ListOfShape` is directly iterable
in OCP.

**Problem 2:** `edge in topo.edges()` always returned False. Python's
`in` operator uses `__eq__` which doesn't work correctly for
`TopoDS_Edge` objects that are geometrically identical but different
Python objects. **Fix:** Use `any(edge.IsSame(e) for e in part_edges)`.

**Problem 3:** `shape_tool.SetShape_s()` doesn't exist -- it's an
instance method, not static. **Fix:** `shape_tool.SetShape()`.

**Result:** Fillet operation works end-to-end. Both L-brackets update
simultaneously because `replace_shape()` modifies the root XDE label
that both instances reference. This confirms the shared-instance
architecture is working correctly -- the primary goal of KodaCAD2.

**Edge pick feedback:** `filletC` now shows "Edge N selected. Add more
edges or enter radius + Enter." in the status bar after each successful
edge pick.

### Checkbox parent/child propagation

**Problem:** Qt6 removed automatic tristate checkbox propagation.
`ItemIsUserTristate` caused checkboxes to cycle through 3 states
instead of propagating to children.

**Fix:**
- Removed `Qt.ItemFlag.ItemIsUserTristate` from item flags
- Added `_set_children_check_state(item, state)` which recursively
  sets all children to the same checked/unchecked state when a parent
  is clicked.

### Black face boundary edges

Added `SetFaceBoundaryDraw(True)` to `draw_shape()` in `mainwindow.py`.
Key details for OCP:
- Use explicit `Quantity_Color(0.0, 0.0, 0.0, Quantity_TOC_RGB)`
  not `Quantity_Color(Quantity_NOC_BLACK)` (wrong constructor)
- Use `Aspect_TypeOfLine.Aspect_TOL_SOLID` not bare int
- Must call `context.Redisplay(aisShape, False)` after setting drawer
  attributes -- OCCT does not apply drawer changes until recomputed

### Known issue: RMB FitAll not working

`AIS_ViewController` consumes RMB events entirely for its own pan
gesture -- `mouseReleaseEvent` is never called for RMB. Need to either
override `FlushViewEvents` or use Qt `eventFilter` to intercept before
`AIS_ViewController`. Deferred to future session.

---

## Session 5 fixes

### Extrude / Create 3D part working

**Problem:** `shape_tool.AddComponent_s()` and `shape_tool.AddShape_s()`
don't exist -- these are instance methods, not static.
**Fix:** Remove `_s` suffix: `shape_tool.AddComponent()`, `shape_tool.AddShape()`.

**Result:** Full Create 3D workflow works end-to-end:
  1. Place workplane on a face (two face picks)
  2. Draw profile (circle, rectangle, etc.)
  3. Extrude to create new part
  4. New part appears in tree under active assembly
  5. Shared instances: part appears in ALL instances of the active assembly

### Load / Modify / Save Demo: COMPLETE

All steps from `Load_Modify_Save_Demo.pdf` pass successfully:
  - Load STEP at top
  - Set active part, apply fillet (both L-brackets update simultaneously)
  - Rename part (all shared instances update)
  - Save to STEP
  - Reload saved STEP -- modifications preserved

**Known issues (pre-existing in original KodaCAD, not regressions):**

1. **Color loss on STEP export:** Modified parts lose their color when
   saved and reloaded. The STEP translator string changes from
   "Open CASCADE STEP translator 7.41.2.4" (old KodaCAD/PythonOCC)
   to "Open CASCADE STEP translator 7.91.2.4" (KodaCAD2/OCP) --
   reflects newer OCCT version, not a bug.

2. **New part position wrong (pre-existing KodaCAD issue):**
   When a new part is created on a workplane inside a positioned assembly,
   the part is placed in world coordinates but then gets transformed by
   the containing assembly's location, moving it to the wrong position.
   The fix (documented in `kodacad_assembly_structure.pdf`) is to apply
   the INVERSE transform of the containing assembly before storing:
   `modshape.Move(containing_assy_loc.Inverted())`
   This was the unsolved problem when KodaCAD development paused, and
   is the next major item for KodaCAD2 development.

---

## Future enhancements (to-do)

### RMB FitAll (attempted, blocked)
RMB click in viewport should call `view.FitAll()`. Attempted via
`mouseReleaseEvent` but `AIS_ViewController` consumes RMB events
entirely for its own pan gesture -- `mouseReleaseEvent` is never
called for RMB. Need Qt `eventFilter` or `FlushViewEvents` override.

### Workplane label in viewport
Display "wp1", "wp2" etc. in the lower-left corner of each workplane
rectangle so the user knows which workplane is active at a glance.
Possible approach: `AIS_Text2d` or `AIS_TextLabel` displayed at the
workplane origin, or a corner of the boundary rectangle.

### AIS ViewCube
Re-add the orientation ViewCube to the viewport corner (same as
Basicad). In Basicad this was done with `AIS_ViewCube`:
```python
from OCP.AIS import AIS_ViewCube
vc = AIS_ViewCube()
vc.SetSize(55)
vc.SetBoxColor(Quantity_Color(...))
context.Display(vc, False)
context.Deactivate(vc)
```
The ViewCube allows click-to-orient (top/front/right/isometric).
In Basicad, clicking the ViewCube face triggers `view.SetProj()`
via `AIS_ViewCubeOwner`. With `AIS_ViewController` this is handled
automatically via `FlushViewEvents`.

### Intersection snap point (workplane)
When H and V construction lines are drawn, a clickable snap point
should appear at their intersection. Currently the point marker
is not displayed. In original KodaCAD this used
`display.DisplayShape(gp_Pnt(...))` -- in KodaCAD2 this needs
`BRepBuilderAPI_MakeVertex(pnt).Shape()` to convert the point
to a `TopoDS_Vertex` before passing to `AIS_Shape`.

### Inverse transform for new parts (PRIORITY)
Fix the new-part placement so parts appear where the user drew them
regardless of the containing assembly's world position. See
`kodacad_assembly_structure.pdf` for the documented fix approach.

---

## Session 6: Drag-and-drop reparent with shared instance propagation (MILESTONE)

### The Creo workflow implemented

Creo's approach to placing new parts in assemblies:
1. Create new part at ROOT level in world position (no active assembly needed)
2. Drag part in tree to target sub-assembly
3. Creo computes inverse transform so part stays in world position
4. Because both L-bracket assemblies share the same XDE root label,
   BOTH instances automatically get the new part

KodaCAD2 now implements this same workflow.

### Implementation: reparent_component() in docmodel.py

When a tree item is dragged to a new parent:
1. Get part's world location from `part_dict[uid]['loc']`
2. Get target assembly's world location from `label_dict[uid]['world_loc']`
   (stored during `parse_components` by composing the assy_loc_stack)
3. Compute: `new_local = parent_world.Inverted() x part_world`
4. Find target assembly's REFERRED label (ref_entry) -- the shared root
   label that both instances point to
5. `shape_tool.AddComponent(target_label, ref_shape.Located(new_local))`
6. `shape_tool.RemoveComponent(comp_label)` -- remove from old location
7. `shape_tool.UpdateAssemblies()` then `parse_doc()`

Key insight: adding to the REFERRED label (e.g. `0:1:1:5` for
l-bracket-assembly) rather than the component label means ALL shared
instances automatically get the new component.

### world_loc stored in label_dict during parse_components

Assembly nodes now store `world_loc` in label_dict:
```python
world_loc = compose(assy_loc_stack) x a_loc
label_dict[c_uid]['world_loc'] = world_loc
```
This avoids the previous brittle approach of inferring world location
from children.

### _find_label_by_entry searches component labels recursively

Component labels (depth 5+) are not returned by `shape_tool.GetShapes()`.
Added `_search_children(label, entry)` which walks `TDF_ChildIterator`
recursively to find labels at any depth.

### Display refresh after reparent

`moveSelection` in TreeView walks up the Qt parent chain to find
MainWindow (direct `self.parent()` returns an intermediate container):
```python
main_win = self.parent()
while main_win is not None and not hasattr(main_win, 'ais_shape_dict'):
    main_win = main_win.parent()
```
Then clears AIS context and redraws from scratch:
```python
main_win.canvas._display.Context.RemoveAll(False)
main_win.ais_shape_dict.clear()
main_win.build_tree()
main_win.redraw()
```

### doc_linter removed from reparent_component

`doc_linter` (STEP save/reload cycle) was causing label entries to change
and losing components. Removed entirely from reparent -- direct XDE
manipulation + `parse_doc()` is sufficient.

### Result

Create button on right L-bracket top face → extrude → button appears
at root under as1. Drag button to l-bracket-assembly_2 in tree →
button appears under BOTH l-bracket-assembly_1 AND l-bracket-assembly_2
in tree and viewport. Show/hide works correctly.

---

## Session 7: Full Creo-style workflow + UI cleanup (MILESTONE)

### Tree structure now matches CoCreate/Creo
```
WP
  wp1
3D
  /
    as1
      rod-assembly_1
      ...
    button   <- new parts appear here, ready to drag
```
The `'3D'` intermediate node contains `'/'` which is the root of the
3D assembly hierarchy. New parts and imported STEP files appear as
direct children of `'/'`, not nested under `as1`.

### New part creation workflow (Creo-style)
1. Place workplane on target face
2. Draw profile, extrude → new part appears under `'/'`
3. Drag new part to target assembly in tree
4. Both shared instances of target assembly receive the part

### Key fixes

**`add_component` uses `AddShape` not `AddComponent`:**
New parts are added as free root-level shapes (siblings of `as1`),
not as components under `as1`. This places them correctly under `'/'`.

**`parse_doc` includes free root shapes:**
After the main assembly parse, `GetFreeShapes()` is called to find
standalone shapes at root level. Only non-assembly free shapes are
included (prototype shapes like nut/bolt are referenced by components
so they don't appear as free shapes).

**`reparent_component` handles free root shapes:**
Free shapes (depth 4) use `RemoveShape()` after drag.
Component labels (depth 5) use `RemoveComponent()`.
Previously both used `RemoveComponent` which silently failed for
free shapes, leaving the ghost button at root level.

**Name preserved on drag:**
After `AddComponent`, the referred shape label is also named
so instances show the correct name (not 'SOLID') in all viewers
including CAD Assistant.

**File menu simplified:**
- `Load Session` — replaces entire doc (save/load surrogate)
- `Save Session` — saves to STEP
- `Import STEP` — adds component under `'/'`
Removed: "Load STEP Under Top", "Load STEP Component",
"Open File", "Save File" (native .xbf format -- unused).

**`doc_linter` removed from `add_component` and `add_component_to_asy`:**
The STEP save/reload cycle was scrambling label entries and causing
stale UIDs. Direct XDE manipulation + `parse_doc()` is sufficient.

### Round-trip STEP verified in CAD Assistant
- Button color preserved ✓
- Button name 'button' shown correctly in both shared instances ✓
- Assembly structure preserved ✓
