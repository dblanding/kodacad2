# KodaCAD Development Log

This document is a chronological record of the development sessions for
kodacad2. It documents the hard-won knowledge acquired during each
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

---

## Session 8: Free root shapes vs. component labels -- the key architectural lesson

### The problem that consumed most of this session

After implementing the Creo-style workflow (create part at root, drag to
assembly), new parts were created as **free root shapes** via
`shape_tool.AddShape()`. This placed them correctly under `/` in the tree
visually, but broke fillet, shell, and all modify operations.

The symptom: `win.activePart` was always `None` after setting a newly
created part active, even though `setActivePart` appeared to be called
correctly.

### Root cause: two fundamentally different label types in XDE

XDE has two distinct kinds of shape labels:

**1. Free root shapes (depth 4):**
```
0:1:1:1   as1          <- added via AddShape, free shape
0:1:1:2   rod-assembly  <- prototype, also free shape
0:1:1:10  button        <- newly created part via AddShape
```
- Returned by `shape_tool.GetFreeShapes()`
- Have no `ref_entry` (`ref_entry = None` in `label_dict`)
- Are NOT components of any assembly
- `replace_shape()` crashed because it did `ref_entry.split(':')` on None

**2. Component labels (depth 5):**
```
0:1:1:1:1  rod-assembly_1  => 0:1:1:2   <- component of as1
0:1:1:1:2  l-bracket-assembly_1 => 0:1:1:5
```
- Returned by `shape_tool.GetComponents_s(root, comps)`
- Have `ref_entry` pointing to their prototype shape
- `replace_shape()` modifies the prototype → all instances update
- All modify operations (fillet, shell, mill) work correctly

### Why free root shapes broke modify operations

`replace_shape()` used `ref_entry.split(':')[-1]` to find the label
index. For free root shapes, `ref_entry` is `None` → crash.

`win.activePart` was being set to `None` because `setActivePart` had
no guard: if `uid not in dm.part_dict`, it silently set `activePart=None`.
Free root shapes WERE in `part_dict` (added by the free shapes scan), but
after `parse_doc()` ran during the modify operation, label entries changed
and the uid became stale.

### The fix: '/' is a REAL XDE assembly, not just visual

The correct solution: **new parts must be added as components, not free
shapes.** This means `/` must be a real XDE assembly label that contains
new parts as components.

`add_component()` was changed from `AddShape` to `AddComponent`:

```python
# WRONG: creates free root shape (depth 4, ref_entry=None)
new_label = shape_tool.AddShape(shape, True)

# CORRECT: creates component under '/' root (depth 5, has ref_entry)
root_label = free_labels.Value(1)  # '/' is first free shape
component_label = shape_tool.AddComponent(root_label, shape, True)
```

When the document is empty (no `/` root yet), `add_component` creates one:
```python
if free_labels.Length() == 0:
    root_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(root_shape)
    root_label = shape_tool.AddShape(root_shape, True)
    set_label_name(root_label, "/")
```

### What this means for the document structure

When a user creates a new part from scratch:
```
/ (0:1:1:1)              <- created automatically if needed
  can (0:1:1:1:1)        <- component, ref_entry='0:1:1:2'
  bottle (0:1:1:1:2)     <- component, ref_entry='0:1:1:3'
```

When a user loads a STEP file (e.g. as1-oc-214.stp):
```
as1 (0:1:1:1)            <- the STEP file's own root assembly
  rod-assembly_1 ...
```
In this case, `as1` IS the root free shape. New parts added via
`add_component` find `as1` as `free_labels.Value(1)` and become
components of it -- which is correct.

### The drag-and-drop reparent also benefits

`reparent_component` already used `RemoveComponent` for components and
`RemoveShape` for free root shapes. Now that all new parts are components,
`RemoveComponent` is always used -- simpler and more reliable.

### Other fixes in this session

**`replace_shape` for free root shapes:**
Added fallback: use `label_dict[uid]['entry']` when `ref_entry` is None.
```python
target_entry = ref_entry if ref_entry else self.label_dict[uid]['entry']
```

**`setActivePart` guard:**
```python
if uid and uid in dm.part_dict:
    self.activePart = dm.part_dict[uid]["shape"]
else:
    self.activePart = None  # was crashing silently before
```

**`setClickedActive` RMB fix:**
```python
item = self.itemClicked or self.treeView.currentItem()
```
RMB now works without requiring a prior left-click.

**`BRepOffsetAPI_MakeThickSolid` OCP API change:**
```python
# PythonOCC:
newPart = BRepOffsetAPI_MakeThickSolid(workPart, faces, -shellT, 1e-3).Shape()

# OCP (builder pattern):
mkShell = BRepOffsetAPI_MakeThickSolid()
mkShell.MakeThickSolidByJoin(workPart, faces, -shellT, 1e-3)
newPart = mkShell.Shape()
```

### Lesson for future development

**Any shape that needs to be modified (fillet, shell, cut, pull, fuse)
must be a component label (depth 5) with a valid `ref_entry`, NOT a
free root shape (depth 4).** Always add new shapes via `AddComponent`
under an assembly, never via `AddShape` directly at document root.


## Session 9: STEP import losing sub-component names

**Symptom:** `File -> Import STEP` (adding a component under the current
session, as opposed to `Load STEP At Top`) worked, and the imported
assembly showed up under `/` -- but every part *inside* that assembly
showed no name (or a blank/generic label) in the tree, even though the
same STEP file's names displayed correctly via `Load STEP At Top`.

### Root cause

`load_stp_cmpnt()` pulled the imported free shape out of the temporary
STEP document with:
```python
shape = step_shape_tool.GetShape_s(label)   # <- returns bare TopoDS_Shape
```
`GetShape_s` returns pure geometry. It has no idea it was ever an
assembly with named children -- names in XCAF live on **labels**
(`TDataStd_Name` attributes), not on `TopoDS_Shape` objects. Once the
sub-assembly was flattened to a `TopoDS_Shape`, every child's name was
gone. `dm.add_component(shape, name, color)` could then only apply
ONE name (the top-level import name) to the whole flattened blob.

This is the same "geometry vs. label" distinction that bit us in
Session 8, just showing up on the import path instead of the
new-part-creation path.

### The fix: copy the label subtree, not the geometry

Added `DocModel.add_component_from_label()`, which deep-copies the
**entire OCAF label subtree** (shape + name + color + every nested
child label) from the source STEP document into the session, using
the same `TDocStd_XLinkTool`-based `copy_label()` helper that
`load_stp_undr_top()` already used (that function existed in the
codebase but wasn't wired into the "Import STEP" menu item).

Pattern used -- register a placeholder shape, add it as a component
by identity (so XCAF creates a *reference*, not a duplicate), then
overwrite the placeholder label's content via `copy_label`:
```python
placeholder_shape = TopoDS_Compound()
BRep_Builder().MakeCompound(placeholder_shape)
ref_label = shape_tool.AddShape(placeholder_shape, True)
component_label = shape_tool.AddComponent(
    root_label, placeholder_shape, True)  # same object -> reused as reference

copy_label(source_label, ref_label)   # populates ref_label's full subtree

set_label_name(component_label, name)  # only the top instance is renamed
shape_tool.UpdateAssemblies()
self.doc = doc_linter(self.doc)       # STEP round-trip to normalize
self.parse_doc()
```

`load_stp_cmpnt()` now calls `add_component_from_label()` instead of
`add_component()`. `add_component()` itself was left untouched --
it's still correct for parts created at runtime (extrude, etc.) that
have no pre-existing label structure to preserve.

**Note:** the original version of this fix used a placeholder-shape +
`copy_label()` + `doc_linter()` STEP round-trip. That was replaced in
Session 10 (below) with a single `XCAFDoc_Editor.Extract_s()` call,
once the round-trip turned out to be compensating for a specific,
documented gap in `TDocStd_XLinkTool.Copy` rather than being required
in general.

### Lesson for future development

**Any time content crosses from one XCAF document into another
(imported STEP, pasted assembly, etc.), copy the label subtree rather
than calling `GetShape_s()` + re-add-as-new-shape.** `GetShape_s()` is
fine for geometry you're about to modify (fillet/shell/boolean) within
a document you already control, but it silently discards names,
colors and structure the moment it crosses a document boundary. (See
Session 10 for the specific tool to use for the cross-document copy
itself.)


## Session 10: doc_linter -- what it was actually fixing, and removing it

**Background:** `doc_linter()` did a full STEP export/import round-trip
on the document (write to a temp `.step` file, read it back into a
fresh doc). It was called after every cross-document label copy
(`copy_label()`, i.e. `TDocStd_XLinkTool.Copy`) as a "just in case"
cleanup step, going all the way back to the initial port. It was
already removed from `add_component`, `add_component_to_asy` and
`reparent_component` in Sessions 6-7 ("direct XDE + parse_doc
sufficient") -- those are single-document operations. It survived only
in `load_stp_undr_top` and (as of Session 9) `add_component_from_label`
-- the two operations that copy a label subtree **between two XCAF
documents**.

### Was it fixing something real?

Yes. `copy_label()` used `TDocStd_XLinkTool::Copy`, and OCCT's own
class reference for that method carries an explicit warning easy to
miss:

> "If the document manages shapes use the next way: `xlinktool.Copy
> (L,XL); TopTools_DataMapOfShapeShape M; TNaming::ChangeShapes
> (target,M);`"

i.e. plain `XLinkTool::Copy` is documented as **insufficient for
XCAF/XDE documents** (documents that manage shapes) -- it needs an
extra bookkeeping step that `copy_label()` never performed. This is
independently confirmed on the OCCT forum: a user hit the identical
symptom (`Copy`/`CopyWithLink` "not working" on an XCAF document) and
an OCCT team member's answer was: *"OCAF does not know anything about
XCAF. It is better to use a special tool to copy"* -- pointing at
`XCAFDoc_Editor`, a class OCCT added (~7.6) specifically for correct
cross-document XCAF copies.

So `doc_linter`'s STEP round-trip wasn't superstition: it was a real
(if expensive) fix. Serializing to STEP and reading it back forces
OCCT's STEP importer -- which *is* XCAF-aware and does the bookkeeping
correctly -- to rebuild the whole document from scratch, papering
over whatever `XLinkTool::Copy` left inconsistent.

### The fix at the source

Replaced the `copy_label()` + `doc_linter()` combination with
`XCAFDoc_Editor.Extract_s(source_label, dest_assembly_label)`, which
clones a label's full structure (shape, name, color, children)
*directly as a new component of the destination assembly*, correctly,
in one in-memory call:

```python
# OLD: placeholder shape + copy_label + doc_linter round-trip
placeholder_shape = TopoDS_Compound()
BRep_Builder().MakeCompound(placeholder_shape)
ref_label = shape_tool.AddShape(placeholder_shape, True)
component_label = shape_tool.AddComponent(root_label, placeholder_shape, True)
copy_label(source_label, ref_label)
set_label_name(component_label, name)
shape_tool.UpdateAssemblies()
self.doc = doc_linter(self.doc)   # full STEP write+read, replaces self.doc
self.parse_doc()

# NEW: one call, no round-trip
component_label = XCAFDoc_Editor.Extract_s(source_label, root_label)
set_label_name(component_label, name)
shape_tool.UpdateAssemblies()
self.parse_doc()
```

Applied to both `add_component_from_label()` (Session 9) and
`load_stp_undr_top()`. The latter also lost its `Prototype`
placeholder-shape dance entirely -- `Extract_s` makes the whole
"register an empty compound, then overwrite it" trick unnecessary.

`doc_linter()` itself has been deleted (nothing calls it anymore).
`copy_label()`/`copy_label_within_doc()` were left in place as
general-purpose OCAF utilities, though nothing currently calls them
either.

**Caveat:** `XCAFDoc_Editor` requires a reasonably recent OCCT
(~7.6+); `uv.lock` currently pins `cadquery-ocp` 7.9.3.1.1, so this
should be fine, but I could not run OCCT in the environment I made
this change in to verify `Extract_s` behaves exactly as documented --
test the Import STEP menu item (including a STEP file with a nested
multi-part assembly) and the fillet/shell/reparent operations on an
imported part before trusting this in production.

### Lesson for future development

**A slow workaround that "seems to fix something" is a signal to ask
*why*, not a reason to leave it alone.** `doc_linter` earned its
keep for years because nobody had traced *which specific API call*
it was compensating for. Once traced (cross-document `XLinkTool.Copy`
on XCAF documents), OCCT's own docs and forum pointed straight at the
purpose-built replacement. When a defensive round-trip/retry/re-parse
step is added and nobody's sure why, write down what it's *actually*
covering for as soon as you find out -- even if you don't fix it
immediately -- so it doesn't outlive its reason five sessions later.

### Correction (same session, found on first real run)

`XCAFDoc_Editor::Extract` returns `Standard_Boolean` (success/failure),
**not** the new component's `TDF_Label` -- unlike `AddComponent`,
which does return the label it creates. First pass at this fix wrongly
did `component_label = XCAFDoc_Editor.Extract_s(...)`, which crashed
downstream (`TDF_Tool.Entry_s` called with a bool where a label was
expected) the moment it hit a real STEP import.

Fix: call `Extract_s` for its side effect (it adds the copied content
as the newest component of the destination assembly label), then
retrieve that new label separately:

```python
ok = XCAFDoc_Editor.Extract_s(source_label, root_label)
if not ok:
    ...  # handle failure
component_label = get_last_component(shape_tool, root_label)
```

`get_last_component()` (new helper, next to `get_label_entry`) just
takes `shape_tool.GetComponents_s(assembly_label, comps, False)` and
returns `comps.Value(comps.Length())` -- OCAF assigns child tags in
increasing order and `GetComponents_s` returns them in that order, so
the most recently added component is reliably last in the sequence.

**Lesson:** when a header comment says "Clones the label... @return
True if successfully extracted", read `@return` literally -- don't
pattern-match to a sibling API (`AddComponent`) that happens to return
the thing you want. Two OCCT calls that do almost the same job can
still differ in exactly this way.

### Follow-up observation: exported session files got smaller

After the Session 10 fix, a real-world session (start with a part
under an assembly, import several more STEP models, export the
session) produced a noticeably *smaller* STEP file than the same
workflow did with `doc_linter` in place. Visible content (parts,
names, colors, shared-instance edits) looked correct.

**Working hypothesis (not yet confirmed):** `doc_linter`'s STEP
write/read round-trip ran on `self.doc` -- the *whole session
document* -- on every single import, not just the newly-imported
content. Each BREP -> STEP-text -> BREP cycle risks a shared/referenced
shape no longer being recognized as identical (`TShape` identity is
not guaranteed to survive a text round-trip), which would make the
*next* STEP export write that geometry out again per-instance instead
of once as a shared reference. Across a session with several imports,
that's a compounding effect. `XCAFDoc_Editor.Extract_s` never leaves
memory, so shared-instance structure should stay exactly what OCAF's
label graph says it is -- smaller file = less duplicated geometry,
not lost geometry.

**How to actually verify this (not yet done):** export the same test
session from a pre-Session-10 build and the current build, then diff
STEP entity counts:
```bash
grep -c "MANIFOLD_SOLID_BREP" old.step new.step
grep -c "ADVANCED_FACE"       old.step new.step
grep -c "COLOUR_RGB"          old.step new.step
```
If `new.step` has meaningfully fewer solid/face entities but the same
part count and colors, that confirms deduplication rather than data
loss. If a part or color is actually missing, this comparison would
catch that too. Worth doing before relying on this in earnest,
especially on a session with heavy use of shared/dragged instances.

## Session 11: RMB delete on tree items didn't work (menu was never populated)

**Symptom:** Right-clicking a part/assembly/workplane in the tree view
and choosing Delete did nothing.

### Root cause (two separate bugs stacked)

1. `TreeView.popMenu` (a `QMenu` created in `TreeView.__init__`) was
   never populated with any `QAction`s, anywhere in the codebase.
   `TreeView.contextMenu()` just called `self.popMenu.exec_(...)` on
   that permanently-empty menu -- so RMB always showed an empty popup,
   regardless of what was clicked. (`MainWindow.contextMenu()`, used
   for right-clicking the main window itself rather than the tree,
   has the identical dead-empty-menu pattern -- not touched here since
   it's a separate, unrelated right-click target, but worth knowing
   it's the same bug if that one ever gets reported too.)
2. Even with the menu wired up, `deleteItem()` only ever handled
   workplane items (`if uid in self.wp_dict: ... else: print("Only
   workplane deletion is implemented at this time")`) -- part/assembly
   deletion from the XCAF document was never implemented.

### The fix

- Added `populate_tree_context_menu()` (called once, right after
  `self.treeView` is created) that adds real actions -- Set Active,
  Rename, Set Transparent, Set Opaque, Delete -- to `self.treeView.
  popMenu`, wired to the handler methods that already existed
  (`setClickedActive`, `editName`, `setTransparent`, `setOpaque`,
  `deleteItem`) but were previously unreachable from the UI.
- `TreeView.contextMenu()` now resolves `self.itemAt(point)` and
  calls `self.setCurrentItem(item)` before showing the menu, so RMB
  always targets whatever is under the cursor. Previously the class
  docstring said you had to left-click an item *then* right-click to
  act on it (`self.itemClicked`, set only by the `itemClicked` signal)
  -- easy to trip over and easy to mistake for "the feature doesn't
  work" when it's really "the feature requires an undocumented
  two-step click." `setClickedActive()` already had `item =
  self.itemClicked or self.treeView.currentItem()` as a partial fix;
  extended that same fallback to `deleteItem()`, `setTransparent()`,
  `setOpaque()`, `editName()` for consistency, and it's now backed by
  `contextMenu()` actually setting `currentItem()`, so it's reliable
  rather than coincidental.
- `deleteItem()` now handles parts/assemblies via a new
  `DocModel.delete_component(uid)`, which mirrors the removal step
  already proven in `reparent_component()`: `RemoveComponent` for a
  component under an assembly (drops just that reference -- other
  shared instances of the same part/assembly are untouched),
  `RemoveShape` for a free root shape. A confirmation dialog
  (`QMessageBox`) guards the actual delete since it's destructive;
  workplane deletion (already working) was left without a dialog to
  match its prior behavior.

### Lesson for future development

**A UI element that "exists but does nothing" (menu created, signal
connected, handler methods present) is a different bug from a UI
element that's simply missing -- and easy to misdiagnose as the
latter.** Every piece looked present here: `popMenu`, `contextMenu`,
`deleteItem`, even docstrings describing the intended click-then-RMB
workflow. The actual gap was one `addAction()` call that never
happened. When "the feature doesn't work" and the code for it clearly
exists, check whether the pieces are actually wired to each other
before assuming logic is broken -- half-finished wiring reads a lot
like working code at a glance.

## Session 12: RMB->Fit zoomed wildly by cursor horizontal position

**Symptom:** RMB (click, not drag) on the viewport is supposed to Fit
All. It did fit the view initially, but then zoomed wildly, tracking
the cursor's horizontal position, until the next click.

**User-supplied notes going in (unverified):** *"AIS_ViewController
consumes RMB events entirely for its own pan gesture -- mouseRelease
Event is never called for RMB clicks. Fix: use Qt eventFilter to
intercept RMB before AIS_ViewController processes it, or detect the
click duration."* Worth checking claims like this against the actual
code before acting on them -- the general instinct (AIS_ViewController
is consuming RMB for its own gesture) was right, but the specifics
were off: `mouseReleaseEvent` *was* being called for RMB (there were
even debug prints confirming it, left over from an earlier look at
this), and a click-to-FitAll handler already existed and worked --
`view.FitAll()` really was firing. The gesture AIS_ViewController
was running underneath it was Zoom, not Pan.

### Root cause

`KodaViewport._qt_buttons_to_occt()` forwarded LMB, MMB, *and* RMB
button state into `AIS_ViewController` (`self._vc`) on every mouse
event. Confirmed via an OCCT forum thread showing the actual default
gesture map: `AIS_MouseGestureMap` binds `Aspect_VKeyMouse_RightButton`
to `AIS_MouseGesture_Zoom` by default -- drag-right-button-to-zoom,
with horizontal cursor movement driving the zoom factor. That's an
exact match for the reported symptom.

So every RMB press/move/release sequence was doing two unrelated
things at once:
1. The app's own custom logic: track press position, and on release,
   if the distance moved was under the drag threshold, call
   `view.FitAll()`.
2. AIS_ViewController's own built-in Zoom gesture, silently running
   in parallel because RMB button state was also being fed to `_vc`
   via `UpdateMouseButtons`/`UpdateMousePosition`.

Even a "stationary" click has a few pixels of real mouse jitter
between press and release -- enough to nudge the Zoom gesture's
internal state. Then the app's own `view.FitAll()` call changes the
camera scale directly, bypassing the ViewController entirely. That
leaves the ViewController's cached zoom-gesture start-state (distance/
scale at button-down) stale relative to the camera's new, post-FitAll
scale. Any further cursor movement gets interpreted against that
stale baseline, producing the "zooms wildly by horizontal cursor
position" behavior.

### The fix

Stop forwarding RMB to the ViewController at all -- it's used
exclusively for the app's own click-to-Fit gesture, never for OCCT's
navigation. `_qt_buttons_to_occt()` now only sets the LMB/MMB bits;
RMB state simply never reaches `_vc`, so its Zoom gesture never starts
in the first place. `mouseReleaseEvent`'s existing click-to-FitAll
logic (already correct) is untouched. Also removed the `[RMB] ...`
debug prints left over from the earlier (inconclusive) investigation,
now that the actual cause is understood and fixed.

### Lesson for future development

**When mixing a custom app-level gesture with a framework's own
built-in gesture system on the *same* input (here: RMB), decide which
one owns that input and stop forwarding it to the other.** Feeding
the same raw button/position events to both `AIS_ViewController` and
your own click-detection logic doesn't just risk visible conflict --
it risks exactly this kind of latent state desync, where the
symptom (wild zoom) shows up nowhere near the code that causes it
(`_qt_buttons_to_occt`, not `mouseReleaseEvent`, was the actual fix
site). Also: take "unverified notes from an earlier look at this" as
a lead worth checking, not a diagnosis worth trusting outright --
the instinct here (ViewController eating RMB for a gesture) pointed
in the right direction even though the specific claim (mouseRelease
never fires; it's Pan) didn't hold up against the code.

## Session 13: Position function -- foundation + first working method

**Goal:** Port Doug's Basicad Position/Mate-Align design (see the PDF
he shared) to Kodacad, WITHOUT taking a build123d dependency -- explicit
hard requirement, to protect Kodacad's raw XCAF/XDE STEP fidelity
(Basicad, being built on build123d, has known STEP round-trip issues
Doug specifically wants to avoid re-inheriting here).

### What we found in Basicad worth porting

`src/pose.py`'s six `compute_*_move()` functions (Step 1/2/3 of
Mate/Align, plus the three Align Axis steps) turned out to be almost
entirely raw OCP calls already (`gp_Trsf`, `gp_Ax1`, `gp_Dir`,
`gp_Pnt`) -- build123d's `Vector`/`Location` are only used as thin
point/direction bookkeeping. That makes this the most portable part of
the whole design: swap the thin wrapper for a small dependency-free
equivalent (or raw `gp_Vec` arithmetic) and the actual geometry math
carries over close to verbatim.

`gui/position_dialog.py`'s state machine (`PositionState`,
`ConstraintType`, per-step pick handling, `_move_history` for
Back/Reverse) matches the PDF design closely and ports as logic, not
code -- Kodacad's `registerCallback()`/`SetSelectionModeFace()`/status
bar already do the job Basicad's own pick-collection plumbing does.

Also found (unexpectedly): `main_app.py` has a REAL, working
`AIS_Manipulator` integration for the "Dynamic" method -- not a stub.
It already solves the exact "who owns this mouse gesture" problem we
spent Session 12 on for RMB (`context.MoveTo()` +
`manipulator.HasActiveMode()` gates whether LMB goes to the gizmo or
to rotation). Originally scoped as a stretch goal; turns out to be
closer to done than Mate/Align.

### The real gap, confirmed against Kodacad's own code

Basicad's `node.move(local_move)` mutates a build123d Node's location
directly -- in build123d, that mutation *is* the model; export walks
the same live object tree. Kodacad has no equivalent: `dm.doc` (the
XCAF document) is the sole source of truth; `dm.part_dict`/
`label_dict` are caches rebuilt by `parse_doc()`. This is the exact
trap already visible in Kodacad's own `rotateAP()` (kodacad.py) --
marked `"""Experimental..."""`, mutates `win.activePart` and redraws,
never touches `dm.doc`, so the rotation is display-only and
disappears on save or the next `parse_doc()`.

### set_component_location() -- the new foundational method

Verified against the OCCT 8.0 refman (not assumed) before writing
anything, per the `Extract_s` lesson from Session 10:
`XCAFDoc_ShapeTool::SetLocation(theShapeLabel, theLoc, theRefLabel)`
-- "Sets location to the shape label. If label is reference, changes
location attribute." Exactly the purpose-built primitive: reposition
one component instance in place (same identity, same parent, same
entry), as opposed to `RemoveComponent`+`AddComponent` (would change
identity) or a display-only mutation (would not persist).

```python
def set_component_location(self, uid, new_local_loc):
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())
    comp_label = self._find_label_by_entry(self.label_dict[uid]['entry'])
    ref_label = TDF_Label()
    ok = shape_tool.SetLocation(comp_label, new_local_loc, ref_label)
    shape_tool.UpdateAssemblies()
    self.parse_doc()
    return ok
```

Deliberately operates on the component's own (instance) label, not
its referred/root label -- so moving a shared part only moves the ONE
instance being positioned, matching ordinary CAD behavior. (Contrast
with `reparent_component()`, which deliberately targets the referred
label so ALL shared instances move together -- a different, and here
intentionally different, choice.)

### First working method: 2 Points (menu: Position -> Position
Selected)

Pure translation, no DOF accounting -- the simplest possible exercise
of the full pipeline (tree pre-select -> pick 2 points via the
existing `registerCallback`/vertex-selection-mode pattern -> compute
world delta -> convert to local via the SAME parent-world-inverse
math already proven in `reparent_component()` -> `set_component_
location()` -> `parse_doc()` -> redraw), deliberately built before
Mate/Align so the new persistence primitive gets proven end-to-end
against something with no other moving parts to blame if it breaks.

Handles both parts (world loc from `part_dict[uid]['loc']`) and
assemblies (world loc from `label_dict[uid]['world_loc']`) -- these
live in different dicts because `parse_components()` only adds simple
shapes to `part_dict`, a distinction that would have been an easy bug
to miss (first draft of this code checked `uid in dm.part_dict` for
validity, which silently rejects every assembly).

### Not yet done (next up)

Mate/Align (the actual design priority, per Doug: "there is no way we
are going to skip mate/Align") and Dynamic (AIS_Manipulator, now
believed lower-risk than expected). `set_component_location()` is the
piece both depend on, now in place.

### Lesson for future development

**When a proven implementation already exists in a sibling project,
the highest-value read isn't "does the code work" but "where does its
foundation stop matching mine."** Basicad's Mate/Align math and state
machine were directly reusable; the one place it *couldn't* be reused
verbatim -- how a computed move actually gets applied and persisted --
was exactly the piece Kodacad needed built fresh, and exactly the
piece where reusing Basicad's approach uncritically would have
reintroduced the same STEP-fidelity risk Doug explicitly ruled out.

## Session 14: Position moves didn't survive save/reload -- SetLocation vs. AddComponent for STEP export

**Symptom (from Doug's real test):** loaded `as1-oc-214.stp` as the
session, imported a separate "manual lathe" STEP file, moved it in Z
using the new 2-Points Position command, saved the session, reloaded
it -- the lathe was back at its original position. Everything else in
the assembly was fine.

### Diagnostic trail

Added temporary instrumentation rather than guessing:

1. **In `set_component_location()`, right after `SetLocation()`
   succeeded:** printed the translation, then read it back two ways --
   `get_label_location()` and `shape_tool.GetShape_s(comp_label)
   .Location()`. Both agreed: `(0.0, 0.0, 60.0)`, correctly applied,
   in memory.
2. **In `save_step_doc()`, right before `Write()`:** dumped every
   component under `/` with the same two readbacks. All five
   components -- including manual-lathe -- showed the correct location
   in the live document at the moment of export.
3. **In the actual saved `.stp` file** (Doug ran `grep -n
   "CARTESIAN_POINT"` and pasted the first block): the five
   component placements appeared as `#12=(0,0,0)` (root), `#16=
   (-10,75,60)` rod-assembly, `#20=(5,125,20)` l-bracket_1, `#24=
   (0,0,0)` plate, `#28=(175,25,20)` l-bracket_2, `#32=(0,0,0)`
   manual-lathe. **Every component matched its expected location
   except manual-lathe, which was written as identity** -- even though
   step 2 confirmed the document held `(0,0,60)` for it right up until
   `Write()` was called.

Conclusion: the bug is specifically in what `STEPCAFControl_Writer`
serializes for a location that was set via `XCAFDoc_ShapeTool::
SetLocation()`, at least for a component that itself was added via
`XCAFDoc_Editor.Extract_s()` (Session 9's import path). The four
components that round-tripped correctly were all built the normal
way -- via `AddComponent()` with a located shape, either by the STEP
reader itself or (for a moved part) by `reparent_component()`, which
already uses that pattern successfully.

No documented OCCT explanation for *why* `SetLocation`'s result
doesn't survive export was found despite searching -- this may be
genuinely under-tested territory (XCAF's own docs describe `AddComponent`-
with-location as the primary/canonical mechanism for assembly
placement; `SetLocation` gets far less use in examples and forum
threads by comparison).

### The fix

Rather than chase the "why", `set_component_location()` now uses
`RemoveComponent` + `AddComponent(parent_label, ref_shape.Located(new_loc),
True)` -- the exact pattern already proven correct by
`reparent_component()`, and the same mechanism that produced the four
components that round-tripped correctly in Doug's test. Trade-off:
the component gets a new label/entry/uid each time it's repositioned
(`AddComponent` creates a new label rather than mutating the existing
one) -- harmless here since `parse_doc()` runs immediately after and
every uid gets re-derived fresh anyway.

### Lesson for future development

**"Correct in memory" and "correct after STEP export" are two
different claims, and only real save+reload (not just a redraw)
proves the second one.** The in-session redraw looked completely
correct after the move -- which is exactly why this class of bug is
dangerous: it doesn't announce itself until someone actually closes
the loop with a save and a fresh load, by which point it's easy to
mistake for "I must have mis-clicked" rather than a persistence bug.
When adding any new document-mutating operation, a save+reload check
belongs in the test pass alongside the in-session visual check -- the
Position 2-Points smoke test in Session 13's writeup only asked for
the former; this session is the reason the request now explicitly
asks for both.

**When two different low-level APIs claim to do the same thing
(`SetLocation` vs. `RemoveComponent`+`AddComponent`, both "set a
component's location"), and one of them already has a proven track
record in this codebase, prefer the proven one -- even without a full
explanation for why the alternative fails.** Understanding the root
cause is worth pursuing when it's cheap, but shipping a fix that's
demonstrably correct (matches 4/4 known-good examples) shouldn't wait
on fully reverse-engineering an OCCT internals question search
couldn't answer.

## Session 15: Position dialog + Mate/Align Step 1

Built the real Position dialog from Doug's design PDF (Methods /
Constraints / Reverse-Back-Done layout), replacing the standalone
"2 Points" menu command from Session 13 with one dialog that will
grow to hold every method. Wired up Step 1 of Mate/Align (rotate
about the intersection line of two picked face planes until flush)
and folded 2 Points in as a sibling method, both going through a new
`position_math.py`.

### position_math.py -- ported from Basicad, no build123d

Doug was explicit: no build123d dependency, even a thin one -- he'd
already learned the hard way (before Kodacad existed) that it risks
STEP round-trip fidelity, which has been the throughline of this
whole project. Turned out not to cost much: Basicad's `compute_*_move()`
functions in `src/pose.py` are already almost entirely raw OCP calls
(`gp_Trsf`, `gp_Ax1`, `gp_Dir`, `gp_Pnt`); build123d's `Vector`/
`Location` were only ever used as thin point/direction bookkeeping.
Replaced that layer with `Vec3` -- a ~60-line dependency-free class
(X/Y/Z, +, -, unary -, scalar *, dot, cross, normalized, length) --
and swapped `Location` for `TopLoc_Location` throughout. Only Step 1
(`compute_step1_move`, `find_intersection_line`) is ported so far;
Step 2/3 and Align Axis come once Step 1 is proven.

**Caught two of my own mistakes before shipping, by re-diffing against
the original line-by-line instead of trusting my first transcription:**
1. Added an extra translation step after the Step 1 rotation that
   ISN'T in the original -- the original returns just the rotation,
   because rotating about the true plane-intersection line already
   makes the faces coplanar by construction. Improvising on top of an
   already-correct, already-tested algorithm is exactly the mistake
   to avoid; caught it by re-viewing the source instead of assuming my
   memory of it was right.
2. Simplified away a genuinely dead `if result is not None: ... else:
   ...` branch (the original has it too, but `result` is provably
   non-None by that point in the function in both versions) -- this
   one was a safe, behavior-preserving simplification, not a bug, but
   worth noting as the kind of thing to flag explicitly rather than
   silently "clean up" during a port.

`resolve_face_pick()` reuses `workplane.face_normal()` verbatim rather
than re-deriving face-normal/orientation logic -- that function
already correctly handles `TopAbs_REVERSED` faces and has been in
production since Session 3.

### UID tracking through a multi-step dialog

Session 14's `set_component_location()` fix (RemoveComponent +
AddComponent instead of SetLocation) means the component's uid
changes on EVERY call -- fine for a one-shot command, but the Position
dialog applies several moves in sequence (Step 1, Reverse, Back) to
the same item. Changed `set_component_location()` to return the new
uid (`None` on failure) instead of a bare bool, and made every caller
in the dialog thread that uid through (`self.uid = new_uid`) rather
than reusing the one captured at dialog-open time.

Caught a real bug in my own first draft while implementing this:
`get_uid_from_entry()` looked like the obvious way to recover a uid
from an entry string after `parse_doc()` rebuilds `label_dict` --
except it's not a lookup, it's a *generator* (increments a counter in
`self._share_dict` on every call, used internally by `parse_doc()`'s
own walk). Calling it again after the fact would mint a fresh,
never-actually-assigned uid rather than recover the real one. Fixed
by searching the freshly-rebuilt `label_dict` for the matching entry
instead.

Caught a second instance of the same class of bug in `_on_reverse()`:
it calls `set_component_location()` twice (once to undo the previous
move, once to re-apply with the flipped mode) but the first draft
only captured the uid from the second call -- leaving `self.uid` stale
for that intermediate step. Same fix: capture and use the return
value from every call, not just the last one.

### Undo model differs from Basicad's, deliberately

Basicad's `Back`/`Reverse` call `node.move(last_move.inverse())` --
correct there because build123d's `.move()` composes onto the current
location. Kodacad's `set_component_location()` sets an ABSOLUTE local
location (a consequence of the Session 14 fix), so composing an
inverse delta isn't the right primitive here. Instead, the dialog
snapshots the item's current local location onto a history stack
*before* every move, and Back/Reverse restore that exact snapshot
directly -- simpler, and immune to compounding numerical drift from
repeated delta inversions (irrelevant for one move, but would matter
across a longer Mate/Align/Align-Axis sequence later).

`Reverse` specifically: undo the last move FIRST (restoring the part
to the exact state the original two picks were taken from), THEN
recompute with the flipped Mate/Align mode from those same picks. This
order isn't just style -- it's required for correctness, since the
picks' stored world-space point/direction are only valid relative to
where the part was *when they were taken*, not wherever it ended up
after the move being reversed.

### Also added: DocModel.get_world_loc() / get_parent_world_loc() /
world_to_local()

Small helpers extracted from logic that was about to be duplicated a
third time (once in the original 2-Points command, now again in the
dialog) -- the world-location bookkeeping already proven in
`reparent_component()`, now available as `dm` methods instead of
copy-pasted inline.

### Not yet done

Step 2, Step 3, and Align Axis of Mate/Align; Dynamic (AIS_Manipulator
port); face-owner validation (trusting click order for moving/fixed,
per Session 13's note, still deferred).

### Lesson for future development

**When porting a proven algorithm, verify by re-diffing against the
source line-by-line, not by trusting a first transcription from
memory -- even within the same sitting.** Both mistakes caught this
session (the invented extra translation, the generator-vs-lookup
confusion) were things a careful second look caught immediately but a
first pass missed. The fix isn't "be more careful" in the abstract --
it's "actually re-open the source and compare," the same discipline
this log has already recorded paying off for `Extract_s` (Session 10)
and `SetLocation` (Session 14).

## Session 16: Position dialog testing -- a real regression, a real UI bug, and two feature requests

Doug's first real test of the Position dialog (Session 15) surfaced
five things. In priority order:

### 1. REGRESSION: positions AND names reverted after save/reload

Serious -- this is the exact class of bug Session 14 was supposed to
have closed. Root cause: `set_component_location()` fetched the
referred shape via `shape_tool.GetShape_s(ref_label)` -- which returns
bare geometry with **no XCAF name/structure attached**. That's the
exact trap Session 9 fixed once already, for STEP imports (`GetShape_s`
losing names when flattening a sub-assembly to raw geometry). It got
reintroduced here in Session 14 while solving a *different* problem
(getting the location to survive STEP export) -- fixing one thing
without rechecking whether the fix reopened an already-closed one.

Compounding it: `AddComponent(parent_label, located_shape, True)` --
the `True` (`expand`) tells OCCT to decompose a Compound into a FRESH
assembly structure. For a raw, name-less `TopoDS_Shape` (which is what
`GetShape_s` returns), that decomposition has nothing to name the new
sub-labels with, so it falls back to auto-numbering. Confirmed exactly:
"manual-lathe" and the hub assembly came back named `22` and `25`
after a Position move + save/reload.

**Fix:** `XCAFDoc_ShapeTool::AddComponent` has TWO overloads (both
already confirmed against the OCCT refman in Session 14, just used the
wrong one):
```
AddComponent(assembly, comp: TDF_Label, Loc: TopLoc_Location)
AddComponent(assembly, comp: TopoDS_Shape, expand: bool = false)
```
Switched to the LABEL-based overload -- reference `ref_label` directly
(never converting to raw geometry at all), passing the location
straight through at creation time. This should fix both problems at
once: names/substructure preserved (no geometry extraction), and
location survives export (still going through `AddComponent`, the
mechanism Session 14 already proved correct, not `SetLocation`).

**Also fixed `reparent_component()` proactively** -- identical
`GetShape_s` + `AddComponent(...,True)` pattern, never specifically
reported broken, but that's very plausibly because it's only ever been
tested with leaf parts (no children to lose names for) or hasn't been
tested with save/reload after reparenting an *assembly* specifically.
Switched to the same label-based `AddComponent`, and its color-setting
call (`color_tool.SetColor(ref_shape, ...)`) to the label-based
`SetColor(ref_label, ...)` overload (confirmed to exist) since
`ref_shape` is no longer fetched.

**Not yet re-verified by real testing** -- please re-run Doug's exact
repro (move an assembly, save, reload, check both position AND name)
before trusting this.

### 2. UI bug: clicking an already-selected radio button does nothing

Real, structural Qt bug, very likely the actual cause of the "reverse
to make align into a mate" workaround Doug reached for during the
hex-shaft test. `QRadioButton.toggled` only fires on an actual state
CHANGE -- clicking "Mate" again while Mate is already the selected
constraint is a no-op as far as `toggled` is concerned, so the second
pick sequence never started. Fixed by switching the Mate/Align/2-Points
buttons from `toggled` to `clicked` (fires on every user click,
regardless of prior state) for anything that should start a new pick
sequence.

### 3. Hex-on-hex-shaft ("mate, then mate again") -- not a bug, a
missing feature

With #2 fixed, clicking Mate twice in a row now DOES start two
separate pick sequences and apply two separate moves. But it still
won't do what Doug wants for the hex-collar-on-hex-shaft case: our
current `compute_step1_move()` recomputes a full flush-rotation from
only the two NEWLY picked faces' current normals every time -- it has
no concept of "rotate only within the plane already fixed by the
previous mate." Applying it twice can partially UN-mate the first
pair unless the two rotation axes happen to coincide by luck. This is
exactly what Step 2 of the 3-2-1 workflow is *for* (rotate within the
plane Step 1 already fixed, preserving that constraint) -- deliberately
not built yet. Doug's hex-shaft example is a good concrete
justification for building Step 2 next, not a bug in what exists now.

### 4. 2-Points prompt text was misleading

"pick a point ON the part to move" implied an ownership constraint
that doesn't actually exist for this method -- confirmed by Doug's own
use of it (picked both points on an L-bracket, unrelated to the lathe
being moved, purely to capture a known reference distance). Only the
DELTA between the two points matters for 2 Points; neither point needs
to belong to the moving item. (Mate/Align's face-picking prompt is
correctly left alone -- pick 1 genuinely must be a face on the moving
part there, since the math uses that face's own orientation.)

### 5. Added: full breadcrumb path in the dialog's top section

Doug: "we want to avoid any ambiguity about which instance we are
moving." A bare name doesn't disambiguate when the same part/assembly
appears more than once in the tree (shared instances -- see Session
13). Added `DocModel.get_full_path_name(uid)`, walking the
`parent_uid` chain up to `/` and joining names, e.g. `/ / as1 /
manual-lathe`. Displayed in the dialog's top label, refreshed after
every move (since `self.uid` changes each time).

### Lesson for future development

**Fixing bug A by changing how something is built doesn't
automatically mean bug B (already fixed once, in a DIFFERENT function,
for a DIFFERENT reason) can't come back through the new code path.**
Session 14 fixed a STEP-export problem by switching from `SetLocation`
to `AddComponent`. That fix was correct AS FAR AS IT WENT -- but
picking the shape-based overload of `AddComponent` (instead of the
label-based one that was sitting right there in the same refman page)
reopened the exact `GetShape_s`-loses-names problem Session 9 had
already closed, just via a new code path. When a fix touches a
primitive that a DIFFERENT past bug also touched, it's worth
explicitly checking whether the new code still respects the earlier
fix's constraints -- not just whether it solves the problem in front
of you.

## Session 19: the actual root cause -- Extract_s labels, not set_component_location

**The breakthrough test:** after four sessions (14, 16, 17, 18) of
fixes to `set_component_location()` that all failed identically, tried
repositioning a component that was NEVER imported via "Import STEP" --
`l-bracket_1`, part of the original `as1-oc-214.stp` session file,
built entirely by `STEPCAFControl_Reader`. It worked. Name and
position both survived save/reload perfectly, on the first try, with
code that had already failed on `manual-lathe` and the hub assembly
in every prior test.

**This means every fix attempted in Sessions 14-18 was aimed at the
wrong function.** `set_component_location()` was never broken. The
actual defect is in `add_component_from_label()` (Session 9's
`XCAFDoc_Editor.Extract_s`-based STEP import) -- or more precisely, in
what `Extract_s` produces: a component that is perfectly correct in
every check we ran (displays fine, name reads back fine, survives its
OWN independent save/reload untouched -- confirmed by Doug's control
test in an earlier session), but corrupts the moment it's later
referenced by a *second* `AddComponent` call, e.g. via Position. A
component built entirely by `STEPCAFControl_Reader` never shows this
problem, no matter what `set_component_location` does to it.

### The fix: normalize at import time, not save time

Session 18 tried round-tripping the whole document through a temp
STEP file right before the final `Write()` -- reasoning that this
would force everything through the one path (`STEPCAFControl_Reader`)
proven to produce correct results. Real testing showed this doesn't
help: the corruption is already present by the time of the *first*
write (confirmed: writing the temp file already produces the
identical broken output the second write then faithfully reproduces).
Round-tripping too late can only round-trip a bug, not fix it.

The actual fix: move the round-trip to `add_component_from_label()`,
immediately after `Extract_s`, before the freshly-imported component
is ever referenced by anything else. This normalizes the Extract_s-
built structure into Reader-native form *before* the user ever gets a
chance to reposition it -- so by the time `set_component_location`
later touches it, it's structurally identical to something the Reader
built directly, matching the one case that's always worked.

`save_step_doc()`'s round-trip (Session 18) was reverted -- confirmed
ineffective, now dead weight.

### Why this took five sessions to find

Every individual piece of evidence gathered along the way was real
and correctly interpreted -- the diagnostics showing memory was
correct up to `Write()` (Session 14, confirmed again here), the NAUO
name field genuinely blank in the file (Session 17), the "identical
name" correlation that turned out to be coincidental (also Session
17, disproven by direct test rather than left as unexamined belief).
What was missing wasn't more diagnostic data -- it was a *controlled
variable*: every test case tried so far (`manual-lathe`, the hub)
had gone through the SAME import path, so nothing distinguished
"caused by set_component_location" from "caused by something upstream
that set_component_location merely exposes." The test that finally
separated those two hypotheses -- try the same operation on a
component with different provenance -- is the kind of test worth
reaching for earlier when several specific fixes to the same function
have failed identically. Session 18's honest framing ("if this
doesn't work, the problem is deeper still") was the right instinct;
the actual next step should have been changing what's being tested,
not what's being fixed.

### Lesson for future development

**When several specific fixes to the same function all fail the same
way, stop varying the fix and start varying the input.** Sessions
14-18 tried `SetLocation`, two different `AddComponent` overloads,
distinct-name forcing, and a save-time round-trip -- four different
*fixes* to the same function, against the same two test components
(`manual-lathe`, the hub), both of which shared a variable nobody had
isolated: their import history. The question that actually mattered
wasn't "which API call is correct" -- it was "does this reproduce on
a component this function didn't create the label for." Once asked,
one test settled it.

## Session 20: regression pass -- fillet crash, status bar terseness, testing checklist

Doug ran a broader regression pass (the Session 19 fix, plus the OCCT
"Bottle" tutorial as an unrelated sanity check) and reported three
things.

### 1. Hub still fails; manual-lathe now passes

Confirms Session 19's fix is real progress, not a false fix -- but the
hub-specific case is narrower than the original bug and still open.
Likely related to unusual internal structure in the hub's OWN STEP
file (we noticed `NAUO1`/`NAUO2` generic occurrence names inside it
back during the Session 17 investigation, suggesting whatever tool
originally exported that file already had some internal referencing
quirk, independent of anything Kodacad does). Logged as a known open
issue in the new testing checklist (below) rather than chased further
right now -- lower priority than the general regression it resembled.

### 2. Fillet crash with no Active Part set

```
TypeError: Init(): incompatible function arguments... 
Invoked with: <TopExp_Explorer>, None, <TopAbs_EDGE>
```

Pre-existing bug, unrelated to Position work -- just never triggered
until this regression pass. `fillet()` already anticipated "no Active
Part set" as a real scenario (there's a friendly message for exactly
that case!) but only caught `ValueError`. `Topology.Topo(None).edges()`
raises `TypeError` in this OCP binding, not `ValueError`, so the
existing guard never fired. Fixed by checking `win.activePart is None`
explicitly before constructing `Topology.Topo` at all, rather than
guessing which exception type a `None` input produces.

### 3. Position dialog status bar messages too long

Several messages restated the item's full name and a paragraph of
explanation on every pick ("Positioning 'manual-lathe': pick a
reference point (point 1). It doesn't need to be on 'manual-lathe'
itself -- only the distance from point 1 to point 2 matters.") --
wider than the status bar, so unreadable in practice. Shortened to
match the terse, count-based style `filletC` already uses elsewhere
in this codebase ("Edge 3 selected. Add more edges or enter radius +
Enter.") -- e.g. "Pick point 1 (need not be on the part)." -> "Point 1
picked. Pick point 2." Explanatory prose that isn't essential in the
moment (like Reverse's behavior) moved out of the status bar entirely
rather than shortened further -- it doesn't need to be said every time.

### 4. New: docs/TESTING_CHECKLIST.md

Doug's suggestion, and overdue -- 19 sessions of manual regression
testing existed only as scattered log entries, easy to forget to
re-check. Added a checklist organized by feature area (STEP Import,
Save/Reload, Tree/RMB, Shared Instances, Viewport, Position Dialog,
Modify Active Part), each item traceable back to the session that
found the original bug, plus a "Known Open Issues" section so
Session 19's hub case and the deferred Step 2/3/Dynamic/Align Axis
work don't get silently re-reported as new bugs later.

### Lesson for future development

**A regression checklist earns its value the first time it catches
something a targeted test wouldn't have.** The fillet crash is exactly
that case -- nothing about Position work touches `fillet()`, but
running an unrelated tutorial as a broad sanity check caught a
real, user-facing crash that narrow feature testing never would have
surfaced. Worth treating "run something unrelated" as a real testing
strategy, not just a formality.

## Session 21: modal Active Part check, upfront not after-the-fact

Following up on Session 20's fillet crash fix. The crash was gone, but
the underlying UX problem wasn't: the check only fired AFTER the user
had already picked every edge and typed a radius (a real 12-edge
fillet in Doug's case) -- console-only message, easy to miss, and by
the time it showed up all that picking work was wasted.

Added `require_active_part(op_name)`: a shared, modal check (`QMessageBox.
warning`) used consistently across every "Modify Active Part" operation
that needs one -- `fillet`, `shell` (both pick geometry before
applying, same "tedium" risk), `mill`, `pull` (less picking work, but
same missing-Active-Part crash risk), and `rotateAP`/`rev_rotateAP`
(single-shot, would otherwise crash immediately calling `.Move()` on
`None`). Checked at the point the menu item is first clicked, before
any picking/callback registration starts, not after the user has
already done the work.

Also (unrelated): fixed `KodaViewport.call_select_callbacks()`'s error
handler, which was printing only `str(e)` -- empty for some exception
types, producing the useless "Select callback error: " Doug hit while
making the second construction circle in the Bottle tutorial. Now
prints a full traceback. The underlying circle bug didn't reproduce on
a second attempt (transient or input-sequence-dependent), but the
diagnostic stays in place for if/when it recurs -- per Doug: "let's
leave the expanded error message in place in case we encounter it
again."

### Menu order: not a regression

Doug flagged Position/Modify Active Part being "swapped" from what
Basicad does, worth a quick note: the delivered code already has
Position before Modify Active Part, matching workflow order (Workplane
-> Create 3D -> Modify as one linear sequence, Position introduced as
a separate subsequent step, not inserted into that flow) -- which is
actually the OPPOSITE of the original design PDF's own mockup, which
showed Modify Active Part before Position. That deviation was made
back in Session 13 without explicitly flagging it. No code change
needed; noted here so the reasoning is on record instead of silently
implicit in a menu ordering nobody wrote down.

### Lesson for future development

**Catching an error correctly isn't the same as catching it at the
right TIME.** Session 20's fix (catch the right exception type) and
Session 21's fix (catch it before the expensive part starts) address
two different aspects of the same bug report, and only the second one
actually addresses what the user experienced as the problem ("I did
all this picking for nothing"). When a fix resolves the crash but not
the underlying frustration, that's worth noticing as a separate,
still-open issue, not folded into "already fixed."

## Session 22: root cause found -- shared instances, not assemblies

Building on Session 21's data: Doug ran two more controlled tests.
`plate` (a leaf part, reached this time via `as1-oc-214.stp` imported
INTO a `manual-lathe.step` session) survived save/reload completely --
position, name, and color. `l-bracket-assembly` failed again, in this
SAME import path (Extract_s + Session 19's round-trip -- the exact
treatment that fixed `manual-lathe`), ruling out "generalize the
round-trip fix" as the answer: whatever's different about
`l-bracket-assembly` isn't fixed by the same treatment that fixed
`manual-lathe`.

### The actual differentiator: shared instances, not assembly-ness

Requested and got the untruncated NAUO grep. Two findings settled it:

1. `l-bracket-assembly`'s occurrence that failed to save showed up
   with a BLANK name (`#139794 = NEXT_ASSEMBLY_USAGE_OCCURRENCE('237',
   '','',#133581,#134718,$)`), which is why an earlier `grep
   "l-bracket-assembly"` search didn't find it -- nothing to match on
   a blank name field.
2. That entity's child reference (`#134718`) is the SAME entity
   `l-bracket_1`'s own NAUO uses as ITS parent reference -- confirming
   `l-bracket-assembly_1` and `_2` are true XCAF-level shared
   instances of one product definition, not just visually identical.

This matches a documented OCCT `STEPCAFControl_Writer` limitation
found back in Session 14 and set aside at the time as maybe not
applicable: mishandling export when a shape has "other partner shapes
with a different location." That's exactly this scenario --
repositioning one shared instance while its sibling stays at a
different location confuses the writer specifically for the modified
instance.

### The fix: unshare before repositioning

`set_component_location()` now checks `XCAFDoc_ShapeTool::GetUsers()`
on the referred label before repositioning. If more than one
component references it (a genuinely shared instance), it clones the
referred label into an independent copy via `XCAFDoc_Editor.Extract_s`
(the same tool already proven correct for imports) before proceeding,
falling back gracefully to the shared reference if any step of the
clone fails.

**This is a deliberate behavior change, discussed and confirmed with
Doug first, not assumed:** once an instance is repositioned this way,
it stops sharing geometry with any sibling that remains linked to the
original -- e.g. editing a hole size on the repositioned instance will
no longer propagate to its sibling, the way it did before (celebrated
as correct behavior back in Session 13). The tradeoff: a part that
silently reverts position and loses its name on every save is worse
than losing an edit-propagation convenience that only applies once
you've deliberately diverged an instance's placement from its sibling
anyway. Matches how mainstream CAD tools handle this same situation
("make unique" / "break the link").

Doug's own framing mattered here too: this fix stays inside strict
XDE/XCAF conformity rather than compromising it -- `Extract_s` is
OCCT's own sanctioned cloning tool, not a workaround bolted on
alongside the format. Worth recording plainly: his insistence on not
"zagging" toward build123d's looser approach (a 200MB file bloating to
1.1GB after deleting content, in his own recent test) is exactly what
kept this investigation pointed at a real fix instead of a shortcut.

### Lesson for future development

**A documented bug report set aside as "probably not applicable" is
worth re-checking once the evidence narrows enough to test it
directly, not just once.** The Mantis report about partner shapes at
different locations was found in Session 14, considered, and shelved
because nothing at the time distinguished it from several other
candidate explanations. Five sessions of increasingly controlled
tests (varying leaf-vs-assembly, import path, and finally shared-vs-
unique) were needed to isolate the one variable that mattered --
sharing -- at which point the shelved report turned out to be the
answer all along. The lesson isn't "should have found it sooner" (the
isolating tests were genuinely necessary); it's that a plausible
discarded lead is worth a second look once new evidence narrows the
field, rather than staying discarded by default.

## Session 22 (cont'd): hub deferred, not resolved

Confirmed the hub's `NAUO1`/`NAUO2` blank names are present in the
hub's OWN source file, loaded standalone with no import, no Position,
no save/reload involved at all -- this is a pre-existing data-quality
issue in that specific file, not something Kodacad causes. However,
blank names alone don't confirm this is the SAME shared-instance bug
Session 22 fixed -- that requires checking whether NAUO1 and NAUO2
reference the same child entity (true sharing) or two different ones
(just poorly named). That check was never completed.

**Decision: deferred, not resolved.** After 22 sessions chasing what
turned out to be (at least for every other tested case) the shared-
instance bug, diminishing returns on this one specific file. If it
resurfaces later, the open question is exactly where this note leaves
it: confirm whether NAUO1/NAUO2 share a child reference before
assuming Session 22's fix should have caught it.

## Session 23: Dynamic (AIS_Manipulator) -- drag + numeric Nudge

Ported Basicad's proven `AIS_Manipulator` integration into Kodacad's
`KodaViewport`, and wired it into the Position dialog as the "Dynamic"
method. Discussed scope with Doug first: a true Creo-style floating
numeric-input box that appears mid-drag next to the active axis/ring
isn't something `AIS_Manipulator` provides on its own -- Creo builds
that UI itself. Building the real thing would mean detecting which
handle is active, floating a `QLineEdit` over the OpenGL viewport at
the right screen position, live-updating it every mouse-move, and
juggling keyboard focus between dragging and typing -- a real, options-
open future project, not this session's scope. Agreed instead: live
status-bar feedback during the drag (reusing the pattern every other
Position method already has) plus a small "Nudge" section (dX/dY/dZ
fields + Apply) for exact refinement after a rough drag -- same
deterministic input -> transform -> apply flow as 2 Points and
Mate/Align, just seeded by a drag instead of two picks.

### What ported directly vs. what needed adapting

`attach_manipulator()`/`detach_manipulator()` and the mouse-gesture-
ownership logic (`context.MoveTo()` + `manipulator.HasActiveMode()`
deciding whether LMB goes to the gizmo or falls through to rotation)
ported close to verbatim -- this is the same category of problem
Session 12 solved for RMB vs. AIS_ViewController's built-in zoom
gesture, and Basicad had already proven the pattern.

What needed rework: Basicad walks a build123d node tree to find every
leaf AIS_Shape under the thing being moved (so a multi-part sub-
assembly moves live together, since the gizmo only ever transforms
the ONE shape it's Attach()-ed to). Kodacad has no such tree -- added
`DocModel.get_descendant_part_uids(uid)`, walking `parent_uid` chains
over `part_dict`/`label_dict` instead, then mapping to `win.
ais_shape_dict` for the actual AIS_Shape objects.

### The integration point that needed real care: redraws destroy AIS_Shapes

`_apply_world_move()` (used by every Position method to actually
persist a move) ends with a full redraw: `ais_shape_dict.clear()` +
`Context.RemoveAll(False)` + rebuild. That's fine for 2 Points/Mate-
Align, which don't hold onto AIS_Shape references across the apply --
but the manipulator DOES (it's `Attach()`-ed to specific shape
objects, and `_manip_leaf_shapes` holds direct references to the
rest). Applying a drag's result without detaching first would leave
the manipulator attached to shapes that no longer exist. Every path
that calls `_apply_world_move` while Dynamic mode might be active --
`_on_manip_done`, `_apply_nudge`, and `_on_back` (Back's enablement
doesn't check which method is current, so it can fire mid-Dynamic-
session) -- now detaches first and re-attaches after, resolving fresh
`AIS_Shape` references via `_reattach_manipulator()` rather than
reusing anything from before the redraw.

### Not yet tested

None of this has been run -- Doug is away and asked me to build ahead.
Test plan for next session: attach and drag a translate arrow, drag a
rotate ring, verify live status-bar feedback, verify a multi-part
sub-assembly moves together (not just one part of it), verify Nudge
applies an exact correction on top of a rough drag, verify Back/
Reverse/Done all correctly detach/reattach around the redraw without
leaving a stale gizmo on screen, and -- per the now-standard
discipline -- save and reload afterward to confirm Dynamic-produced
moves persist exactly like every other method's.

### Lesson for future development

**Scoping a feature honestly up front (the Creo floating-box
discussion) made the actual implementation simpler to reason about,
not just faster to agree on.** Knowing from the start that "Nudge
after the drag" was the real target, rather than "numeric input mid-
drag," meant the redraw-invalidates-AIS_Shape problem only needed
solving around a small, well-defined set of call sites (`_on_manip_
done`, `_apply_nudge`, `_on_back`) instead of a live-updating input
box that would need the SAME fix applied continuously during an
active drag, which would have been a materially harder problem.

## Session 24: gizmo-jump bug -- parent resolution used the wrong entry

Doug's terminal log from the Dynamic-mode L-bracket test showed the
concrete cause directly, no guessing needed: the same uid's reported
`parent_uid` silently changed between two consecutive
`set_component_location` calls --

```
[set_component_location #1] uid=0:1:1:5:4.1 ... parent_uid=0:1:1:1:4.0   (l-bracket-assembly_2)
[set_component_location #2] uid=0:1:1:5:5.0 ... parent_uid=0:1:1:1:2.0   (l-bracket-assembly_1)
```

-- with no reparenting ever requested. Root cause: `set_component_
location()`'s parent-label resolution used `parent_info.get('ref_entry')
or parent_info['entry']`, preferring the parent's *shared product
definition* over its own specific instance entry. `l-bracket-assembly_1`
and `_2` share one underlying definition (Session 22), so resolving
the parent through `ref_entry` added the repositioned L-bracket to the
SHARED DEFINITION rather than to the one specific assembly instance it
actually belonged to -- explaining exactly why the manipulator
appeared to jump to the sibling bracket after release.

This exact `ref_entry`-preferring pattern is correct and intentional
in `reparent_component()` (deliberately making every shared instance
of a target parent receive the reparented child), which is likely why
it got carried into `set_component_location()` without being
questioned -- same-looking code, opposite correct behavior, depending
on whether the goal is "affect every instance" (reparent) or
"reposition within one specific instance" (this function). Fixed by
always using the parent's own instance entry (`parent_info['entry']`)
here, never `ref_entry`.

### The lathe save/reload regression -- still open, but narrowed

Console diagnostics for `manual-lathe` in the same log show correct
state in memory AND in the pre-write dump right up to `Write()` --
the same "correct until the file is actually written" pattern from
every prior export-time bug this project has hit. The parent-
resolution bug above doesn't explain it (the lathe's parent stayed
stable across all 4 of its calls, unlike the L-bracket's). Doug is
retesting this in isolation (moving only the lathe, not mixed with
L-bracket work in the same session) to determine whether it's
independent of the bug just fixed or was somehow triggered by it.

### Lesson for future development

**Code that looks like a reasonable default in one function can be
exactly backwards in a structurally similar one -- copy-pasting (or
mentally reusing) a pattern without re-deriving why it was correct in
its original context is a real risk, not just a style concern.** This
is the second time in this project a `ref_entry`-vs-`entry` choice
mattered (Session 13's `parse_components`, Session 22's unsharing),
and the first time it was actually chosen wrong. Worth treating
`ref_entry` vs. own-`entry` as a decision to make explicitly and
comment, every time, rather than a detail to default from a nearby
example.

## Session 25: Session 24's fix crashed -- the real problem was one level deeper

Doug's next test crashed immediately:
```
OCP.OCP.Standard.Standard_NullObject: A null Label has no attribute.
```
inside `set_label_name`, meaning `AddComponent(parent_label, ...)`
returned a null/invalid label. Root cause: Session 24 correctly
diagnosed the SYMPTOM (a repositioned child's parent silently jumping
between `l-bracket-assembly_1` and `_2`) but reached for the wrong
fix. `AddComponent` requires its "assembly" argument to structurally
hold children -- and a component/INSTANCE label (like `l-bracket-
assembly_2`'s own occurrence) does not hold children directly; only
its REFERRED (product) label does. Passing the instance label
directly, as Session 24 did, isn't just semantically wrong -- it's
not a valid target at all, hence the null result.

### The real problem: the PARENT can be shared too, not just the child

Session 22 built unsharing for the CHILD being repositioned (if ITS
own geometry is shared). That's necessary but not sufficient:
`l-bracket-assembly_2`'s referred label is itself shared with `_1`
(that's the whole reason cross-contamination was possible). Removing
and re-adding a child under a shared PARENT structure edits the
shared product directly, affecting every sibling instance of that
parent -- a different, deeper problem than child-level sharing, and
one the current code has no answer for yet (would need to recursively
unshare the parent, and potentially ITS parent, and so on -- real
future work, not something to improvise untested).

**Fix, this session:** restored `ref_entry` preference for parent
resolution (required -- `AddComponent` needs a real assembly-
structured label), but added an explicit check: if the parent's own
referred label has more than one user, refuse cleanly with a clear
message instead of crashing or silently cross-contaminating a
sibling.

### Reconciles the earlier successful test

Doug's Session 22 write-up moved `l-bracket-assembly_2` (the whole
assembly) FIRST, which unshared it -- THEN moved the L-bracket part
within it, by which point the parent was already independent. Today's
tests moved `l-bracket_1` directly, without that first step, so the
parent was still shared. Same underlying limitation, different order
of operations exposed it. Practical workaround until parent-unsharing
is built: reposition the containing assembly first (any real move
unshares it), then reposition children within it.

### Also: Nudge input boxes too narrow for 3-digit values

Cosmetic but reported alongside the above -- `setMaximumWidth(60)` was
too tight to display "180" legibly. Widened to 80px across all six
Nudge fields (translation and the new rotation ones).

### Lesson for future development

**Diagnosing the right symptom doesn't guarantee the right fix if the
underlying structural assumption is wrong.** Session 24's diagnosis
(parent cross-contamination via `ref_entry`) was accurate. Its fix
assumed "the parent's own instance entry" was a viable alternative
target for `AddComponent` -- without confirming that instance labels
can actually hold children (they can't). Worth verifying not just
"does this fix the symptom" but "does this target the API actually
expects to receive" before shipping a structural change like this. In
this case, the crash caught it fast and safely (Doug's test-in-
isolation discipline again paying off) -- better than the quieter,
more dangerous alternative Session 24 could have produced elsewhere.

## Session 26: Session 19's "fix" removed -- it was never actually working

Doug's fully isolated test (single import, single nudge, nothing else
touched in the session) showed the exact same corruption Session 19
believed it had fixed: `manual-lathe`'s occurrence written with a
blank NAUO name and identity location, despite the document being
100% correct in memory and in the pre-write dump right up to
`Write()`. Confirmed via file inspection (same technique as every
previous round of this investigation): `PRODUCT('manual-lathe', ...)`
present and correct, but the NAUO for the moved occurrence blank-
named, and its `CARTESIAN_POINT` back to identity `(0,0,0)`.

This means Session 19's round-trip (write the freshly-Extract_s-built
document to a temp file, read it back, replace self.doc) never
actually solved anything for `manual-lathe` -- earlier tests that
looked successful must have coincided with success for some other,
unidentified reason, not because the round-trip normalized anything.

### The fix: remove the round-trip, don't add another one

Direct comparison caught what months of theorizing about "what's
different about Extract_s-built structures" missed: `set_component_
location()`'s unsharing logic (Session 22) uses the exact same
`XCAFDoc_Editor.Extract_s` clone -- and that path is CONFIRMED working
(Doug's L-bracket unshare test survived save/reload with correct name
and position). The only structural difference between the two code
paths was the round-trip Session 19 added. Removed it from
`add_component_from_label()`, restoring the simpler pre-Session-19
shape (Extract_s -> name -> UpdateAssemblies -> parse_doc -> done),
while keeping Session 15's uid-recovery fix (search `label_dict` for
the matching entry, since `get_uid_from_entry()` is a generator, not
a lookup -- almost got reintroduced by accident while reverting the
round-trip, caught before shipping).

**Not yet re-tested.** If this resolves it, the actual lesson is that
Extract_s's clone was fine all along and the "fix" for a real bug
(confirmed in Session 14, `manual-lathe` genuinely didn't survive
export back then) was actually solving nothing -- something else
Session 14 changed at the same time must have been the real fix, or
the original Session 14 bug and this one were never quite the same
bug to begin with. If it does NOT resolve it, the round-trip theory
is fully dead, and whatever's actually wrong with Extract_s-imported
top-level components remains open -- worth revisiting Session 14's
original diagnostic trail from scratch rather than assuming anything
carried forward from it still holds.

### Lesson for future development

**A fix that "worked" in early testing but was never re-verified in a
fully isolated test can quietly stop being trustworthy evidence.**
Session 19's round-trip got treated as settled for five sessions
because early tests looked successful -- but those tests always had
other things happening in the same session (multiple moves, mixed
with other bugs being chased). The moment Doug ran a genuinely
isolated single-operation test, the fix's actual (lack of) effect
became visible immediately. Isolation testing isn't just useful for
finding NEW bugs -- it's the only way to actually confirm an old fix
still holds, rather than assuming past success generalizes.

## Session 27: round-trip theory confirmed dead; testing cross-document vs. same-document Extract_s instead

Doug's re-test after Session 26 (round-trip removed) showed the exact
same corruption -- blank name (this time "34"), reverted position.
**This definitively kills the round-trip theory** -- it was never the
mechanism, in either direction (adding it in Session 19, or removing
it in Session 26 both left the bug unchanged). Genuinely useful
result, even though frustrating: four different fixes (`SetLocation`,
two `AddComponent` overloads, round-trip added, round-trip removed)
are now ruled out with real evidence, not abandoned on a hunch.

### The one remaining, confirmed structural difference

Direct comparison of the two `XCAFDoc_Editor.Extract_s` call sites:
- `set_component_location()`'s unsharing (Session 22, CONFIRMED
  working -- Doug's L-bracket test survived save/reload correctly):
  `Extract_s(ref_label, unshare_root)` -- both labels already inside
  `self.doc`. Same-document.
- `add_component_from_label()`'s import (CONFIRMED failing, every
  test so far): `Extract_s(source_label, root_label)` -- `source_
  label` comes from the separate, temporary document `_load_step()`
  creates for the imported STEP file. Genuinely cross-document.

This is the first real, structural distinction found between a
working and a failing use of the same primitive -- not a coincidence
noticed in passing, but the ONE variable that differs between the two
confirmed outcomes.

### Experiment: re-clone same-document, right after the cross-document import

Added a second Extract_s call in `add_component_from_label()`,
immediately after the cross-document import completes: re-clone the
just-imported referred label from WITHIN self.doc back into self.doc,
then discard the original cross-document-created component and use
the same-document re-clone instead. Cheap (in-memory, not a file
round-trip) and directly tests the one remaining distinguishing
factor, rather than another blind variation on where names/locations
get set. Falls back gracefully to the original import at every step
if anything about the re-clone fails, so this can't make the import
path worse than it already was even if the hypothesis is wrong.

**Not yet tested.** If this works, it's strong evidence the STEP-
import document itself (or something about a truly cross-document
Extract_s specifically) is where the corruption originates -- worth
understanding properly rather than just working around, once
confirmed. If it doesn't work, cross-document-vs-same-document is
ruled out too, and the remaining honest options are: (a) build a
minimal, standalone repro script outside the full app to test OCCT's
actual behavior in isolation (more rigorous than continued trial-and-
error inside Kodacad's full complexity), or (b) treat this as a
documented, accepted limitation and move on, the way the hub was set
aside in Session 22.

### Lesson for future development

**A failed fix is still worth full evidentiary credit -- it eliminates
a hypothesis as surely as a successful one confirms it.** Neither
Session 19 nor Session 26 "worked," but together they definitively
prove the round-trip was never the mechanism in either direction --
that's real ground covered, not wasted effort, and it's what actually
narrowed the search down to the cross-document/same-document
distinction being tested now.

## Session 28: minimal repro -- flat case works, testing nesting next

Doug ran `minimal_repro.py` (a headless script driving docmodel.py's
real `add_component_from_label`/`set_component_location` against a
two-box toy model, built after Session 27's fifth failed fix). Result:
**the bug did NOT reproduce.** Name and position both survived cleanly
-- `NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','imported_box_1',...)` correctly
named, `CARTESIAN_POINT('',(50.,0.,0.))` correctly positioned, and the
re-read document showed the same, correct, on the first try.

This is a genuinely valuable negative result, not a null one: it rules
out "the cross-document Extract_s + reposition mechanism is
fundamentally broken" as a category. Whatever's actually wrong depends
on something the flat single-box model doesn't have. The clearest
candidate: `manual-lathe` isn't a flat leaf shape -- it's a multi-level
assembly (e.g. `1925-4008-0048 assembly` is one of ITS OWN children,
itself presumably containing further parts). The minimal repro's test
box had no nesting at all.

Extended the script with a second scenario: a wrapper assembly
containing two sub-boxes (one level of nesting), built and moved the
same way, to test whether assembly depth is the missing variable.
**Not yet run.**

### Lesson for future development

**A minimal repro that DOESN'T reproduce the bug is exactly as valuable
as one that does -- it eliminates a whole category of explanation in
one clean result.** After five failed fixes all aimed at "something
about how Extract_s-imported components are built or referenced,"
this test shows that explanation was too broad: the mechanism itself
is fine in the simple case. The search space just got smaller in a
way six sessions of varying fixes inside the full app couldn't
achieve, because the full app never let us isolate "flat vs. nested"
as a variable on its own.

## Session 28 (cont'd): nesting confirmed as the trigger; re-clone experiment removed

The extended `minimal_repro.py` (Scenario B: a wrapper assembly
containing two sub-boxes, instead of a flat leaf shape) DID reproduce
the bug. `nested_assembly_1` -- whose name `set_component_location`
explicitly set and confirmed correct right up to `Write()` -- came
back after reload as bare `'3'`. **Nesting is confirmed as a real
trigger; flat is confirmed clean.** First genuinely new, actionable
fact this investigation has produced since Session 22.

The file also showed component-level names like `'=>0:1:1:3'` --
XCAF's own auto-naming placeholder for a reference that was never
explicitly named. Traced this to a gap in the TEST SCRIPT itself (the
sub-box components under the wrapper were never named, only their
referred labels were) -- an artifact of how the test was built, not
evidence about real STEP files, which come with their components
already named by whatever tool exported them. Fixed the script to
name components properly, to get a cleaner signal on a re-run.

Doug separately suggested round-tripping real-world STEP files through
CAD Assistant to clean them up before import. Good practice in
general, but worth being direct about: it would NOT have prevented
this specific bug, since the nested test model was built fresh,
in-memory, by a script, seconds before failing -- there was no messy
source file involved. The bug is inside Kodacad's own handling of
nested structures, not caused by, or fixable by cleaning, the input
file.

### Session 27's re-clone experiment removed

Confirmed it failed on the nested case too, and confirmed (by reading
its own logic again) that it leaves a genuinely orphaned duplicate
referred label behind on every run -- removing a component's
reference to a label doesn't delete the label, so the original
cross-document import's referred label was never cleaned up after the
re-clone replaced it. That orphan is very likely what produced the
"2 free shapes" Doug noticed in an earlier save. Removed the whole
experiment; `add_component_from_label()` is back to a single,
straightforward `Extract_s` call.

### Where this leaves the investigation

Six sessions (14, 16, 17, 18, 19/26, 27) of fixes aimed at "how the
component gets built or referenced" are now fully ruled out by direct
evidence. The confirmed remaining variable is nesting depth within
the imported structure itself -- something about how `Extract_s`
recursively clones a multi-level assembly (or how the rest of the
pipeline handles the result) breaks in a way the single-level case
doesn't hit. Next step: re-run the corrected (properly-named) nested
test without the removed re-clone experiment, to get a clean signal
on nesting alone.

### Lesson for future development

**A diagnostic script needs the same rigor as production code --
including catching its own construction bugs before trusting its
output.** The auto-naming placeholder in this test's output looked
alarming at first glance but turned out to be the script's own
oversight, not new evidence about the real bug. Worth explicitly
separating "what the tool is telling us" from "what I forgot to set
up correctly" before drawing conclusions from either.

## Session 29: root cause fixed -- build assembly structure natively, Extract_s only for leaves

The corrected nested test (component names fixed, confirming the
earlier `'=>0:1:1:3'` symptom was a test-script artifact, not a real
finding) completed the pattern: sub-component names now survived
correctly, but the TOP-level wrapper assembly's own name and position
still failed -- identical to every prior test. Combined with all prior
data, six independent, contradiction-free data points now show
exactly one rule: **cross-document `XCAFDoc_Editor.Extract_s` survives
save/reload reliably for leaf/simple shapes, never for anything that
is itself an assembly with children.** Same-document copies of
assemblies (Session 22's unsharing) are fine. Cross-document copies of
leaves are fine. Only cross-document + assembly-structure fails,
every time it's been tested.

### The fix

Added `extract_component_recursive()` (module-level function): copies
a component from a source document into a destination assembly label,
branching on whether it's a leaf or an assembly. Leaves still go
through cross-document `Extract_s` directly (proven reliable, six
confirmations). Assemblies are built NATIVELY in the destination
document instead -- plain `AddShape(empty_compound, True)` +
`AddComponent`, exactly how every other working assembly in Kodacad
(`/`, `as1`, etc.) is already built -- and the function recurses into
each child, so cross-document `Extract_s` is used only for leaf
content, at any depth, never for assembly-level structure.

`add_component_from_label()` now branches the same way at the top
level: a leaf import goes straight through `Extract_s` as before; an
assembly import builds its own wrapper natively and recurses via
`extract_component_recursive()` for each child. Signature changed to
accept `source_shape_tool` (needed for the recursive case to query
the source document) -- the one real caller (`load_stp_cmpnt`) and
`minimal_repro.py` both updated to match.

**A mistake caught and fixed before it did real damage:** the first
version of this edit accidentally placed the new module-level function
in the middle of the `DocModel` class body, at column 0 -- which
silently terminated the class early and turned `add_component_from_
label` and every method after it into a nested function inside the
new helper, no longer real methods of `DocModel` at all. `py_compile`
did not catch this (it's syntactically valid Python, just structurally
wrong) -- caught it by checking the actual class structure via `ast`,
not by trusting a clean compile. Worth remembering: a clean
`py_compile` only proves valid syntax, never correct structure.

**Not yet tested against the real bug.** `minimal_repro.py` (Scenario
B, now using the new code path) is the immediate next test; if that
passes, the real next step is retesting against `manual-lathe` and the
hub in the actual app.

### Lesson for future development

**Six sessions of testing "how the component gets built or
referenced" without changing "which primitive builds assembly
structure at all" could never have found this** -- every prior fix
(SetLocation, two AddComponent overloads, round-trip added/removed,
same-document re-clone) still used Extract_s to copy the ENTIRE
assembly structure across documents in one call; none of them stopped
doing that. The fix that (potentially) works isn't a better way to
call Extract_s -- it's recognizing Extract_s was never the right tool
for assembly-level structure in the first place, only for the leaf
content underneath it.

## Session 30: wrap-up decision -- revert the native-rebuild dead end, close out Position work for now

Doug's call, and the right one: after Session 29's native-rebuild
approach failed an isolated re-test identically to every prior
attempt, and was found to have a genuine additional downside (see
below), continuing to chase this specific bug had crossed into
diminishing returns. Reverted Session 29's changes; kept everything
else from Sessions 21-29 that's actually proven working.

### What got reverted

`add_component_from_label()` and the `extract_component_recursive()`
helper it introduced (Session 29's native-rebuild-with-recursion
approach) -- back to the simple, single cross-document `Extract_s`
call from before Session 29. Two reasons, not one:

1. It didn't work. A fully isolated re-test (minimal_repro.py,
   Scenario B, using the new code) showed the exact same corruption
   as every prior attempt -- blank NAUO name, identity location, on a
   purpose-built, perfectly clean test structure.
2. It made a DIFFERENT thing worse. `extract_component_recursive()`
   rebuilds every assembly-typed child from scratch via `AddShape`,
   with no de-duplication check -- so if a real imported STEP file
   internally reuses the same sub-assembly definition in two places (a
   common pattern for repeated hardware), the native-rebuild approach
   would silently create two independent copies instead of preserving
   that internal sharing. A regression nobody asked for, on top of not
   fixing the bug it was meant to fix.

`minimal_repro.py`'s one call site was updated to match the reverted
signature so the diagnostic script doesn't bit-rot into something
broken if this investigation is picked up again later.

### What was KEPT (all independently proven, none of it touches
add_component_from_label)

- **Session 21**: modal "No Active Part" check, checked upfront before
  any picking starts.
- **Session 22**: shared-instance unsharing in `set_component_
  location()` -- the actual high-water mark. Confirmed working,
  including a real multi-move test respecting shared instances
  correctly.
- **Session 23**: AIS_Manipulator ("Dynamic" method) + Nudge
  refinement. Doug used this successfully to precisely mate the lathe
  assembly to the plate, centered, using the calculator's edge-length
  key to compute exact Nudge values -- a genuinely proven, working
  feature.
- **Session 25**: the manipulator gizmo-jump crash fix, and the safe
  (non-crashing, non-corrupting) refusal when a component's PARENT is
  itself shared -- a real, distinct case from Session 22's child-level
  unsharing, still open as future work but no longer dangerous.
- **Session 26 / 28**: the Session 19 round-trip and Session 27
  same-document re-clone removed -- both confirmed to not matter
  either way, net code simplification.

### Honest final status of Position, as of this decision

- **2 Points**: fully working, including shared instances and
  multi-move sessions. Checked off.
- **Mate/Align**: Step 1 only (flush-rotate about the picked faces'
  intersection line). Step 2/3 and Align Axis not built.
- **Dynamic**: working -- drag to translate/rotate, Nudge to refine
  numerically. Proven in real use (the lathe-to-plate mating).
- **Known, accepted limitation**: an imported (via "Import STEP") item
  that is itself an assembly with children does not survive a save/
  reload round trip correctly -- confirmed narrowly and precisely (not
  a mystery-shaped gap: we know exactly which case fails and roughly
  why, just not how to fix it yet). Items native to the session file,
  and imported LEAF/simple parts, are unaffected. Tracked in
  docs/TESTING_CHECKLIST.md rather than chased further for now.

### Lesson for future development

**Knowing when to stop is as much a project-management skill as
debugging is, and reverting a well-reasoned but unsuccessful attempt
is not the same as reverting a mistake.** Session 29's approach was
principled, evidence-based, and genuinely worth trying -- it just
didn't pan out, and it happened to introduce a new problem in the
process. Recognizing "this specific path is a dead end AND has a real
cost" and closing it out cleanly, rather than leaving it half-resolved
alongside seven other closed hypotheses, is what actually protects
the project's overall integrity here -- exactly the concern Doug
raised in asking for this cleanup.

## Session 31: propagation restored -- Sessions 24/25 were fixing a misdiagnosis, not a real bug

Doug pushed back, correctly: the Session 19-era behavior he wants is
propagation -- move a shared child once (e.g. the L-bracket inside
l-bracket-assembly_1/_2), see the correction in BOTH assemblies,
survives save/reload -- the same mental model as shape edits already
propagating to every shared instance. That behavior worked at the end
of Session 19. Session 24 broke it, reading correct propagation
behavior (a component's reported parent_uid appearing to alternate
between l-bracket-assembly_1 and _2 across calls) as corruption, and
"fixed" it in a way that crashed (Session 25's null-label fix), then
added a refusal on top rather than reconsidering the original
diagnosis.

**Removed the Session 25 refusal.** Parent resolution goes back to
preferring the parent's referred (shared) label -- Session 22/pre-24
behavior -- so repositioning a child within a shared parent
propagates to every instance again, matching Session 19 and what Doug
explicitly wants.

### The gizmo-jump bug is real and separate -- now has a concrete
hypothesis

Doug asked directly whether the shared-parent "fix" and the
manipulator gizmo-jump bug had been wrongly conflated. Very likely
yes. Re-examining: `l-bracket`'s component reference lives structurally
INSIDE the one shared `l-bracket-assembly` product, not duplicated per
instance -- so it's reachable through TWO parent paths during
`parse_doc()`'s tree walk, getting a fresh uid generated at each
encounter even though it's the same underlying label. `set_component_
location`'s uid-recovery step (search label_dict for a matching entry)
takes whichever one comes first, which can differ between calls purely
based on walk order -- not corruption, but real ambiguity about WHICH
of two equally-valid occurrence-uids to report back. If `position_
dialog.py`'s `_reattach_manipulator()` ends up with "the other"
occurrence's uid, it would attach the gizmo to the sibling's AIS_Shape
-- exactly the reported symptom. Plausible, well-reasoned, but NOT yet
re-confirmed against fresh data -- next test will show whether this
holds up.

### Lesson for future development

**When two different reports get "fixed" by the same change, check
whether they're actually the same bug before assuming they are.**
Session 24 treated a confusing diagnostic reading (parent_uid
alternating) as the root cause of BOTH the "cross-contamination" worry
AND, implicitly, was in the neighborhood of the manipulator gizmo-jump
report from the same testing session. They were never actually shown
to be the same bug -- the connection was assumed because they surfaced
close together. Doug catching this by asking a direct question
("shouldn't these be separate?") rather than accepting the bundled
fix is exactly the kind of check that would have caught this sooner
if asked earlier.

## Session 32: the actual gizmo-jump fix -- uid recovery preferred whichever parent the tree walk visits first

Doug retested immediately: propagation confirmed correct (2 Points on
a shared L-bracket updated both l-bracket-assembly_1 and _2, exactly
as wanted). The Dynamic/manipulator gizmo jump reproduced identically
to before, confirming Session 31's hypothesis was on the right track
and this is a genuinely separate bug from the propagation question.

### Root cause, confirmed (not just theorized this time)

`set_component_location()`'s uid-recovery step searched `label_dict`
for the first entry matching the newly-created label's entry string.
A shared child (living inside the ONE shared `l-bracket-assembly`
product, not duplicated per parent instance) is reachable through
BOTH `l-bracket-assembly_1` and `_2`'s occurrence paths during
`parse_doc()`'s recursive walk -- generating a SEPARATE uid per path
for the same underlying label. Since the walk always visits
`l-bracket-assembly_1` before `_2` (plain document order), the "first
match" was deterministically always the assy_1 view -- regardless of
which sibling the user actually started from. Every previous test
that happened to select assy_2 would silently jump to assy_1 after
any move.

### The fix

When more than one candidate matches the entry (i.e. the moved label
is reachable through more than one parent), prefer the candidate
whose OWN parent's entry matches the parent this call actually started
from (captured in `parent_info` earlier in the same function, before
`parse_doc()` reran). This keeps the caller tracking the SAME
occurrence across repeated calls -- so `_reattach_manipulator()` in
the Position dialog, which relies entirely on `self.uid` staying
correctly anchored to "the thing the user is looking at," stops
losing track of which sibling was selected.

**Known remaining limitation:** this resolves one level of sharing
ambiguity (a shared child under a shared parent). If sharing were
nested more than one level deep (a shared grandparent whose own
parent is also shared), the same ambiguity could recur further up the
chain -- not currently in play for anything tested, but worth knowing
if a future report looks similar in a more deeply nested structure.

### Lesson for future development

**A "recover the uid" helper that just takes the first match is
implicitly assuming uniqueness it was never actually guaranteed.**
This bug existed from the moment `set_component_location()`'s uid-
recovery pattern was written (Session 15) -- it just never surfaced
until Session 22 made repositioning shared children a real, working
feature, and Session 23 built something (the manipulator) that
actually depended on uid continuity across repeated calls to notice
the consequence. Worth treating "search for a match" helpers as
needing an explicit disambiguation rule from the start whenever the
underlying data model allows more than one truthful answer, not just
when a bug report eventually reveals it.

## Session 33: Mate/Align Steps 2 and 3, with real DOF tracking

Ported `compute_step2_move` and `compute_step3_move` from Basicad's
`pose.py` into `position_math.py` (verified against the source
directly, not recalled from memory, same discipline as Step 1's
port). Step 2 rotates WITHIN the plane Step 1 already established
(about the same mated-normal axis, not a new intersection line) and
translates to close the gap -- consumes 2 of the 3 DOF remaining
after Step 1. Step 3 (wall case only -- the "hole" case needs Align
Axis's own axis-picking, not built) translates along the single
remaining free direction (`mated_normal x wall_normal`) -- consumes
the last DOF.

**The one thing worth generalizing on the way in, not after:**
Basicad's Step 2 hardcodes its target to Align (parallel) only. This
was flagged as a real limitation back when the hex-on-hex-shaft case
came up -- applying a second constraint that should be a Mate
required reaching for Reverse to fix a wrong guess. Generalized Step
2 to accept `mate: bool` directly, the same way Step 1 already does.

### The actual missing piece: DOF tracking

Every prior Mate/Align application was a standalone flush-rotation
with no memory of what a previous application had already
constrained -- a second Mate could silently undo the first one's
result instead of narrowing what's left. Added real state to
`PositionDialog`: `_mate_align_step` (0-3, how many of the 3 steps
have been applied), `_mated_normal` (Step 1's result, needed by Step
2), `_step2_wall_normal` (Step 2's result, needed by Step 3).
`_apply_mate_align` now dispatches to whichever step's math applies
based on the current count, and each successful application records
what it established for the next step via a shared
`_record_step_success` helper (factored out specifically so
`_apply_mate_align` and `_on_reverse` can't drift out of sync with
each other's bookkeeping).

**Clean Slate**, per the original design: switching to a different
Method (2 Points or Dynamic) resets the DOF tracker via
`_reset_mate_align_dof()` -- constraint accounting only makes sense
as one continuous Mate/Align session.

**Back and Reverse both had to learn about DOF, not just position:**
`_on_back` now steps `_mate_align_step` backward too, clearing
whichever step's contribution is being undone (so a stale
`_mated_normal` from an undone Step 1 doesn't leak into a
subsequent Step 2 attempt). `_on_reverse` now dispatches to whichever
step was actually last applied (previously hardcoded to always
recompute via `compute_step1_move`, which would have been silently
wrong the moment Step 2/3 existed) -- undoes, decrements, recomputes
with the flipped mode via the correct step's math, then re-advances
the counter and re-records via the same shared helper `_apply_mate_
align` uses. Reverse is disabled entirely when the last-applied step
was Step 3, since pure translation has no mate/align choice to flip.

**Not yet tested.** Doug specifically wants to run this and find
issues empirically rather than have the design over-specified first
-- shipped without further attempts to anticipate edge cases beyond
what's described above.

### Lesson for future development

**Undo/redo logic needs to be updated in lockstep with any new
state a feature introduces, not just the state that existed when
undo/redo were first built.** `_on_back` and `_on_reverse` were
written when Mate/Align had no DOF concept at all; adding one without
revisiting both would have left Back "working" (positions would
still restore correctly) while silently corrupting the DOF tracker's
count -- a bug that wouldn't surface until several steps later and
would have been confusing to trace back to its origin.

## Session 34: Mate/Align 3-2-1 confirmed working end-to-end

Doug ran the full sequence live: Mate/Align through all 3 steps
(choosing Mate or Align independently at each step -- the
generalization added in Session 33 rather than inheriting Basicad's
hardcoded-Align-on-Step-2 limitation), Back three times to unwind
back to the start, then 2 Points, then Dynamic -- all in one session,
all working correctly. First time all three Position methods have
been exercised together in sequence.

**Not yet confirmed: save/reload specifically for a multi-step
Mate/Align result.** Every method individually has been through that
check before, but Steps 2/3 (new this session) haven't yet -- asked
Doug to confirm before treating the whole 3-2-1 workflow as fully
closed out, given how many times "worked live" and "survives save/
reload" have turned out to be different claims in this project.

### Status of Position, updated

- 2 Points: done.
- Mate/Align: Steps 1/2/3 with real DOF tracking, confirmed working
  live (Session 34); save/reload confirmation pending.
- Dynamic: done (Session 23/25/32).
- Align Axis: not built -- the one remaining piece of the original
  design doc's scope.

## Session 35: Align Axis, per Doug's original PDF design (not Basicad's)

Doug's PDF describes Align Axis two ways: (1) chained after a face
Mate/Align as an alternative Step 2 -- pin a hole-on-face intersection
point, leaving only theta_z for a final Align -- and (2) a standalone,
always-fresh 4-DOF axis alignment for a "bolt in a hole" scenario.
Checked Basicad's actual, working implementation before building
anything: it only implements (2), as a fully independent 3-step/6-DOF
section, never chained onto Mate/Align. Doug confirmed explicitly:
build (1), the PDF's original, more carefully-considered design --
Basicad's version was noted as "a bit rough," useful for its
algorithms, not its architecture.

### What ported directly from Basicad (worth keeping regardless of
architecture)

`_resolve_circle`/`_fit_circle_to_edge` -- real, hard-won code,
including a documented bug fix for a genuine failure mode (sampling a
straight edge produces collinear points, whose cross products are all
zero, and normalizing a zero vector throws an OCCT error that isn't a
catchable ValueError -- explicitly guarded against, ported as-is).
Adapted from build123d's `Edge.geom_type`/`position_at()` to raw
`BRepAdaptor_Curve`/`GeomAbs_Circle` -- fast path for genuine circles,
Kasa least-squares fit fallback (with a residual-vs-radius tolerance
check) for anything else, same as the original.

### What's new: Align Axis as an alternative Step 2

The key realization that made this a clean fit rather than a bolt-on:
Align Axis-as-Step-2 is just **Step 2 with different math**, plugging
into the exact same 3-step counter built in Session 33.
`compute_align_axis_pin_move()` intersects each picked hole's own
axis with the plane Step 1 already established (a real line-plane
intersection, `line_plane_intersection()`) and translates the moving
part so the two intersection points coincide -- x/y consumed, theta_z
left. `compute_step3_move()` gained the "spin" branch it was always
going to need (ported from Basicad's `compute_step3_move`'s "hole"
case, which existed but was never ported since Align Axis wasn't
built yet) -- pure rotation about the mated normal, pivoting at the
Align Axis pin point (not either picked face's own point, which would
translate the part as an unwanted side effect of the rotation).

New dialog state tracks which KIND of Step 2 happened
(`_step2_wall_normal` for a normal face-align vs `_align_axis_pivot`
for Align Axis), since Step 3 needs to know which `compute_step3_move`
branch to call. Align Axis is validated as Step-2-only --
`_on_constraint_chosen` refuses it with a clear message unless
`_mate_align_step == 1`. Back/Reverse/Clean-Slate all extended to
cover the new state the same way they already covered Step 1/2/3 --
Reverse specifically disabled for Align Axis's own pin move (no
mate/align choice exists there to flip).

**Caught before shipping, not after:** the pivot for Step 3's spin
needs to be the FIXED hole's own (unmoved) intersection point, not a
recomputation from the moving hole's original pick -- recomputing from
the moving side would use its stale, pre-move position. Worth noting
as the kind of subtle correctness issue that's easy to get backwards
in a first draft.

**Completely untested.** New picking mode (circular edges via
`SetSelectionModeEdge`), new geometry resolution, new math, new DOF-
state branching -- genuinely more surface area than Session 33's
Step 2/3 port, which reused existing face-picking machinery
throughout.

### Lesson for future development

**Checking a reference implementation's actual behavior, not just its
existence, caught a real architecture mismatch before any code got
written.** Basicad's Align Axis "existing" wasn't enough to assume it
matched the PDF's design -- reading its actual dialog wiring
(`_active_section` as a mutually-exclusive selector) revealed it had
evolved into something structurally different from what the PDF
originally specified. Worth verifying not just "does a precedent
exist" but "does the precedent's actual behavior match what's being
asked for" before porting from it.

## Session 36: standalone Align Axis -- Basicad's actual architecture, for the case the PDF used it that way too

Doug's last piece: "bolt in a hole" -- aligning two cylindrical FACES
directly (not circular edges, which the chained-pin role from Session
35 uses) as a genuinely standalone first step, consuming 4 DOF at
once. Confirmed this specific case DOES match Basicad's own
architecture (an independent axis-coincidence move, not chained onto
anything) -- unlike Session 35's other Align Axis role, which
deliberately diverged from Basicad in favor of the PDF's original,
more carefully-considered chaining design.

### What ported from Basicad

`compute_align_axis_move` (the 4-DOF coincidence -- reimplemented
directly in Vec3/TopLoc_Location rather than via build123d's Plane
machinery, since the spin resulting from a from-plane/to-plane
transform is arbitrary and gets superseded by later steps regardless
of how it's computed) and `compute_axis_step2_move` (axial
translation along the now-shared axis, with the real "180-degree flip
if the current face relationship doesn't match the requested mate/
align state" logic Basicad's original has -- ported faithfully,
including the `_any_perpendicular` helper it depends on).
`resolve_cylinder_pick` is new (no build123d equivalent needed
porting -- cylindrical surfaces are reliably typed as GeomAbs_Cylinder
in OCCT, no BSpline-misclassification fallback needed the way circular
edges sometimes require).

### The state model, reorganized around explicit discriminators

Two different things can now happen at Step 1 (normal face mate, or
standalone Align Axis) and two different things at Step 2/3 (normal
face-align leaving a wall_normal, or either kind of Align Axis leaving
a spin pivot instead). Introduced `_step1_kind` and `_step3_kind` as
explicit fields set at the point each step succeeds, rather than
inferring "which path was this" from which of several other variables
happens to be non-None -- the kind of implicit-state inference that's
caused real, hard-to-trace bugs earlier in this project (Session 24's
misdiagnosis being a version of exactly this class of mistake:
drawing a conclusion from indirect evidence about program state
instead of tracking the state directly).

Same button ("Align Axis") now serves both roles depending on
`_mate_align_step` at the moment it's clicked -- 0 routes to the
standalone cylindrical-face flow, 1 routes to Session 35's chained
circular-edge pin flow, anything else refuses with a clear message.
Both DOF paths total exactly 3 constraint-applications either way
(3 for normal Mate/Align-Align-Align, or 4+1+1 for Align Axis-Align-
Align) -- meaning the existing "step X of 3" UI language and the
existing `_mate_align_step` counter needed zero changes to
accommodate this, once the accounting was worked through on paper
first.

**Completely untested**, same as Session 35.

### Lesson for future development

**Working out the DOF accounting on paper before writing any dialog
code avoided what would have been a much bigger rewrite.** The
initial instinct was that a 4-DOF-first path would need a different
step-counting model from the existing 3-step one. Actually tracing
through both paths' constraint counts (3 vs. 4+1+1, both totaling 3
applications) showed the existing framework already fit -- the real
work was just making Step 1 and Step 3 branch on which path was
taken, not rebuilding the counter itself.

## Session 37: cylindrical surface misclassification -- the same bug class as circular edges, one level up

Doug's first real test of standalone Align Axis (rod-assembly against
a hole in the plate, as1-oc-214.stp) hit exactly the gap flagged as a
risk but not built for: both the rod's and the hole's cylindrical
surfaces reported as `GeomAbs_BSplineSurface`, not `GeomAbs_Cylinder`.
The assumption that cylindrical surfaces are "reliably typed," stated
in Session 36's docstring, was wrong -- confirmed directly, not
theorized.

### The fix: the same fallback pattern as circular edges, one level up

Refactored `_fit_circle_to_edge`'s core Kasa least-squares fit into a
shared `_fit_circle_to_points(points)`, taking a plain list of Vec3
rather than sampling an edge itself -- so the same fitting math can
be reused for a surface's cross-section, not just an edge's curve.

`resolve_cylinder_pick` now falls back, when the surface isn't
genuinely typed as `GeomAbs_Cylinder`, to sampling a cross-section and
fitting a circle to it: for a true cylinder (even if BSpline-
approximated), one iso-parametric direction traces a circle and the
other a straight line. Which direction is which isn't a guaranteed
convention, so both a fixed-V and a fixed-U sample are tried, and
whichever fits within tolerance (reusing `CIRCLE_FIT_RELATIVE_
TOLERANCE`, the same threshold already used for circular edges) is
kept. The fitted circle's own center and axis normal directly give
the cylinder's axis -- no separate cylinder-fitting math needed.

**Not yet re-tested** against the actual failing case (rod-assembly
vs. the plate hole).

### Lesson for future development

**"Surfaces are more reliably typed than edges" was an assumption
carried over from general OCCT knowledge, not verified against this
specific codebase's actual data -- and it was wrong the first time it
got tested against a real file.** The circular-edge case had already
demonstrated this exact failure mode for curves (Basicad's own hard-
won fix); the surface case should have gotten the same fallback
treatment from the start, on the strength of that precedent, rather
than assuming a different (better) outcome without evidence. Same
lesson as Session 28's minimal-repro discipline, in miniature: a
claim about "how OCCT reliably behaves" is worth treating as
unverified until tested against real, specific data, not just
plausible in general.

## Session 38: AIS_ViewCube with RGB-colored axes, ported from Basicad plus a real forum-confirmed addition

Doug wanted CAD Assistant's corner ViewCube (Basicad already has one,
without axis coloring) with RGB X/Y/Z axis indicators added on top.

### What ported directly from Basicad

`gui/assembly_viewer.py`'s existing `AIS_ViewCube` setup -- already
real, working code with a genuine gotcha already solved (the same
`Quantity_Color` construction issue this codebase already handles for
the background color: needs an explicit RGB or named-color
construction, not a bare float triple) and the corner-pinning
`Graphic3d_TransformPers` setup. Ported into `koda_viewport.py`'s
`InitDriver()` close to verbatim.

### What's new: RGB axis coloring

Basicad's version doesn't have this. Found the documented, working
answer directly from a real OCCT forum thread where a user asked this
exact question ("how to change the color of the coordinate system
near the viewcube") and got a confirmed-working answer:
`Prs3d_DatumAspect`'s per-axis `ShadingAspect()`. Verified the enum
naming convention (`Prs3d_DP_XAxis` etc., flat top-level names, same
pattern as every other OCCT enum already used throughout this
codebase) against OCCT's own class reference before using it, rather
than assuming the forum snippet's naming translated directly to OCP.

### One thing I can't verify without running it

`AIS_ViewCube` is designed to integrate with `AIS_ViewController`'s
own built-in picking pipeline (automatic camera transform on
click/selection is documented as part of the class itself, not
something the application needs to code). Since Kodacad's mouse
handling already routes through `AIS_ViewController` for the "no
active drag" case, ViewCube clicks should reach it automatically --
but whether that interaction is clean with Kodacad's OWN additional
click handling (part selection via `_on_click()`, the manipulator
gesture-interception from Session 23) hasn't been tested. Worth
specifically checking that clicking a ViewCube face doesn't also
trigger an unwanted part-selection attempt.

### Lesson for future development

**A forum thread answering the exact question being asked is worth
more than general API documentation, but its exact syntax still needs
independent verification against the actual binding being used.** The
forum answer was C++; confirming `Prs3d_DP_XAxis` translates to a flat
top-level OCP name (not nested inside a wrapper enum class) took a
second, separate check against OCCT's own class reference -- exactly
the discipline that's caught several wrong assumptions earlier in
this project (WriteNames, GeomAbs_Cylinder's reliability). A forum
answer confirms the APPROACH is right; it doesn't excuse skipping the
binding-specific verification step.

## Session 38 (cont'd): the actual bug -- DatumAspect() returns null until explicitly assigned

Doug's terminal output pinpointed it exactly: `'NoneType' object has
no attribute 'ShadingAspect'` -- `vc.Attributes().DatumAspect()`
itself returns null on a freshly-constructed `AIS_ViewCube`, before
anything has explicitly given it a `Prs3d_DatumAspect`. The forum
snippet copied earlier skipped this step (or assumed it already
existed from some other setup) -- confirmed by finding a second,
more complete real-world example that includes the missing line:

```cpp
aDrawer->SetDatumAspect(new Prs3d_DatumAspect());   // required first
const Handle(Prs3d_DatumAspect)& aDatumAsp = aDrawer->DatumAspect();
```

Added `drawer.SetDatumAspect(Prs3d_DatumAspect())` before retrieving
it. The earlier `UpdateCurrentViewer()` addition (this session's first
fix attempt) turned out not to be the actual problem, but it's a
correct, low-risk improvement worth keeping regardless.

### Lesson for future development

**The very first forum snippet found isn't always the complete
picture -- a second search specifically for the failing symptom
turned up a MORE complete example that included a step the first one
omitted.** Worth treating an initial confirmed-working-elsewhere
example as a strong lead, not a guarantee of completeness, especially
when it's presented as a short snippet rather than a full working
file. When it fails, searching for the SPECIFIC error message
directly (rather than re-searching the general topic) found the exact
missing piece fast.

## Session 38 (cont'd again): ViewCube vanishing on redraw -- fixed at the actual source, not just the reported symptom

Doug reported the ViewCube disappearing after loading a session.
Traced to `redraw()`'s `context.RemoveAll(False)`, which wipes
EVERYTHING in the AIS context, not just part/workplane geometry --
the ViewCube was only ever added once, at `InitDriver()` time, with
nothing restoring it after any subsequent wipe.

**This is broader than just session load.** `redraw()` is called
throughout the app -- Position moves, RMB delete, drag-and-drop
reparenting -- session load is just where Doug happened to notice it
first. Checked all three `RemoveAll` call sites in the codebase (`main
window.py` x2, `position_dialog.py` x1): two are direct calls to
`redraw()` itself, and the third (drag-and-drop reparent) calls
`redraw()` immediately afterward -- so fixing `redraw()` once, at the
end right before the final `UpdateCurrentViewer()`, covers every wipe
path in the app, not just the one that was reported.

### Lesson for future development

**When a symptom is reported at one specific trigger, check whether
the underlying cause is shared by other triggers before fixing only
the one reported.** `RemoveAll()` wiping non-part objects is a general
property of that call, not something specific to session loading --
grepping for every call site before considering the fix complete
caught two other places that would have hit the identical bug later,
reported as separate-seeming issues if left unfixed.

## Session 39: manipulator spurious-capture -- confirmed shared with Basicad, one real fix kept, one attempted fix crashed and was reverted

Doug reported the Dynamic manipulator capturing LMB drags before any
handle was clicked, or after releasing a translation handle -- both
inducing unwanted rotation/scaling, requiring Back to undo. Confirmed
by Doug testing directly: this ALSO happens in Basicad, ruling out a
Kodacad-specific porting error -- it's a real characteristic of the
manual-detection pattern both codebases share, not something
introduced in this port.

### Confirmed and fixed: scaling was never actually disabled

Session 23's scaling-disable code tried three guessed attribute names
(`"Scaling"`, `"Scale"`, `"AIS_MM_Scaling"`) as attributes of the
`AIS_Manipulator` class itself, silently falling through all three on
failure. Confirmed via a real pythonocc-core stub file:
`AIS_MM_Scaling` is a top-level member of the SEPARATE
`AIS_ManipulatorMode` enum, not an `AIS_Manipulator` class attribute
-- none of the three guesses could ever have matched. This is very
likely why Doug saw scaling behavior at all; it was never disabled.
Fixed with the confirmed-correct import. This fix is unrelated to
everything below and was kept throughout.

### Attempted: DetectedInteractive() as a second gate -- crashed,
reverted

Found a real OCCT forum thread describing almost exactly Doug's
symptom, with a response noting `HasActiveMode()` alone can be
unreliable in a manually-driven `context.MoveTo()` + check pattern.
Added `context.DetectedInteractive() == self._manipulator` as an
additional, more specific check alongside `HasActiveMode()`. This DID
stop spurious capture on an empty-space drag right after entering
Dynamic mode -- but surfaced two further problems: the same drag
didn't fall through to normal camera orbit the way it should, and the
application crashed a few seconds later with NOTHING printed to the
terminal (consistent with a native-level crash in the OCCT/OpenGL
layer, not a catchable Python exception -- a materially harder class
of problem than anything fixed by reading a Python traceback so far
in this project).

Whether this specific change caused the crash, or just happened to be
the first test scenario to trigger a pre-existing native-level issue,
is genuinely unknown -- not enough evidence to attribute cause
responsibly. Reverted via `git revert HEAD` (confirmed via `git show
--stat HEAD` beforehand that the commit being undone was scoped to
exactly this change plus its own doc entries, not the unrelated
ViewCube work in the prior commit), then the scaling fix reapplied on
its own, cleanly, on top of the reverted state. `mousePressEvent`'s
manipulator gate is back to the simpler, `HasActiveMode()`-only check
from Session 23/32.

### The actual resolution: Doug's own characterization of the real
behavior

Doug's own hands-on testing found the actual mechanism, which the
attempted fix above was never quite aimed at: the manipulator captures
subsequent LMB drags whenever the cursor has HOVERED over it -- not
requiring a click on a handle first -- and releases that capture once
the cursor moves away without hovering it again. Predictable and
avoidable in practice once known. Doug's own words: "I think I can
live with that."

### Status of Dynamic, honestly stated

Hover-based capture (not click-based) is the actual behavior -- worth
knowing rather than fighting, not a bug requiring more chasing.
Scaling is now genuinely disabled. A crash risk remains, narrowly
scoped to the reverted `DetectedInteractive()` code path which is no
longer in use -- not currently believed to affect the reverted,
shipped state, though this was never independently re-confirmed after
reverting. The deeper architectural fix this session's research
pointed toward (letting `AIS_ViewController` drive the manipulator
directly, rather than manual `StartTransform`/`Transform`/
`StopTransform` calls -- a forum reply confirms this removes the need
for the manual calls entirely, but no confirmed concrete example of
the internal wiring was found) remains available as real future work
if hover-based capture ever becomes more than a "live with it" quirk.

### Lesson for future development

**Confirming a bug reproduces in the ORIGINAL codebase a port came
from is valuable evidence, not just a formality** -- it immediately
ruled out an entire category of explanation (porting error) and
redirected the investigation toward the shared underlying pattern.
**A user's own hands-on characterization of a UI quirk is sometimes
more valuable than another round of source-diving** -- "hover, not
click, and it releases when I look away" directly explained the
original symptom through simple, direct observation, after an entire
research-driven fix attempt had already crashed trying to solve the
same thing a different way. **Recognizing when a bug has crossed from
"debuggable with the tools at hand" into "needs different, heavier
tools" is itself a useful diagnosis, even without a fix** -- a crash
with zero output is qualitatively different from every other bug this
project has solved, where there's always been a stack trace, a print
statement, or a file to grep.

## Session 41: Bottle tutorial regression pass -- four issues, four separately-chunkable fixes

Doug went through the Bottle tutorial again with a careful eye,
catching several real issues in the early sketch/create steps -- the
same value of "run something unrelated as a regression check" that
caught the fillet crash back in Session 20.

### 1. `arc3p` status bar text -- wording fix

Changed to Doug's exact preferred wording: "Pick 3 points on arc, 1st
and last picks are end points". `m2d.py`.

### 2. ViewCube unresponsive during 2D sketching -- investigated,
deliberately not fixed

2D sketch operations call `SetSelectionModeVertex()` and similar --
exclusive selection modes on the whole AIS context. This very likely
suppresses the ViewCube's own hover/click detection as a side effect,
since it relies on the same context's detection pipeline. A proper
fix would need the ViewCube to hold its own persistent activation
mode independent of whatever selection mode sketching currently has
active -- real complexity, touching every place that currently just
calls `SetSelectionModeXxx()` directly. Doug explicitly said not
worth it if the fix adds complexity; documented as a known, accepted
limitation rather than touched.

### 3. `extrude` status bar not acknowledging the first value --
fixed

`extrudeC()` (the callback fired each time a value is submitted) only
acted once BOTH the length and the name were in -- nothing updated
the status bar between them, so it sat on the original "Enter
extrusion length, then enter part name" text with no acknowledgment.
Added an intermediate message when the length lands, prompting for
the name. `kodacad.py`.

### 4. RMB tree actions crashing with "Internal C++ object already
deleted" -- fixed at the root; not independently reproducible on
later attempts, kept anyway (see reasoning below)

Doug's original report included a complete, unambiguous Python
traceback -- not a vague symptom. That gave a clear mechanism to
trace: `self.itemClicked or self.treeView.currentItem()`, used
identically in FIVE handlers (`setClickedActive`, `deleteItem`,
`setTransparent`, `setOpaque`, `editName`), all equally vulnerable.
`self.itemClicked` goes stale whenever the tree is rebuilt (e.g.
`extrude()` -> `build_tree()`) after an item was clicked but before
an RMB action is taken on it -- the underlying C++ QTreeWidgetItem is
destroyed, but the dead shiboken wrapper is still Python-truthy, so
`or` never falls through to `currentItem()` the way the old code
assumed, and calling `.text(0)` on it raises the crash directly.

Fixed with `shiboken6.Shiboken.isValid()`, the documented, correct
way to check whether a wrapper's underlying C++ object is still
alive. Added one shared `_get_clicked_or_current_item()` helper and
updated all 5 call sites to use it.

**On follow-up, Doug could not reproduce the crash** with a more
careful, deliberate sequence across several attempts (at one point
deleting the workplane instead of the bottle by mistake, then
successfully deleting the bottle cleanly). Doug raised a genuinely
good question, worth answering directly rather than just deferring to
caution: given it didn't reproduce, is the fix still needed?

Yes, kept -- this is a different situation from something like the
Dynamic manipulator's silent crash (Session 39), which we genuinely
had no diagnostic handle on and rightly deferred. Here, the original
traceback gave a complete, understood mechanism (a stale Qt reference
that's Python-truthy despite being C++-dead), confirmed present
identically in five places by reading the code directly -- independent
of whether Doug's later, more careful manual attempts happened to hit
the exact triggering sequence again. This class of bug is inherently
sequence-dependent (the crash needs: click an item, THEN rebuild the
tree via some other action, THEN RMB the same stale item without
re-clicking) -- not retriggering it in careful, deliberate testing is
exactly what you'd expect from a real timing bug, not evidence it
isn't real. The fix itself is minimal, grounded in a documented API,
and can't make anything WORSE even if the original diagnosis somehow
turns out to be wrong (the fallback behavior -- using
`currentItem()` -- is unchanged for every case where `itemClicked`
was already valid).

### Lesson for future development

**A crash traceback naming one specific function is a starting point
for a grep, not necessarily the full scope of the fix** -- four other
handlers had the identical vulnerability, just hadn't been the one
exercised in this particular test session. **A confirmed mechanism
from a real traceback doesn't need repeated reproduction to justify
keeping the fix** -- that bar makes sense for vague, diagnosis-free
symptoms (where "I can't tell if this is even real" is the honest
state of things), but here the mechanism was independently verified
by reading the code, not inferred from the symptom alone. Doug's own
discipline of writing down a first occurrence and attempting to
reproduce it before treating it as a confirmed, standing issue is
exactly right in general -- worth applying per-bug rather than
uniformly, since a bug with a full traceback and a code-level
explanation is already a different category of confirmed than one
with neither.

## Session 41 (cont'd): calculator entry glitch -- narrowed to a specific, useful lead

Doug's "clineH stopped working" turned out to be unrelated to the
Session 41 m2d.py edit (confirmed: the edit only touched arc3p's
status text, nowhere near clineH; class structure verified intact).
Traced by Doug himself to the RPN calculator widget: entering 30, then
clicking x/2, produced 0.0 instead of 15 -- something after a
stumbled entry (saw "300", removed a digit) left the calculator
holding a value that displayed as 30 but wasn't actually 30.

**Follow-up narrowed the trigger further**: happens specifically when
a value is entered via the LAPTOP KEYBOARD, not the calculator
widget's own on-screen buttons. A real, specific starting point for
whenever this gets picked up -- worth comparing exactly how the two
input paths differ in how they update the calculator's internal
value vs. its displayed text. Not investigated further this
session -- Doug's call, deferred.

## Session 42: RPN calculator keyboard-entry bug -- root cause found and fixed

Doug's Session 41 lead ("laptop keyboard entry, not the calculator's
own buttons") was exactly the right clue. `rpnCalculator.py`'s
`xdisplay` (the X-register's QLineEdit) is fully editable -- nothing
stops direct keyboard typing into it -- but every button handler
(`func`, `calculate`, `pr`, `mm2in`, `in2mm`, `storex`, `trimx`,
`swapxy`, `putx`) reads and writes `self.x` directly, and nothing
connected the widget's own text back to that variable. Typing "30"
via keyboard correctly updated what's DISPLAYED; `self.x` (the actual
value every calculation and the X-register send-to-Kodacad button
use) silently stayed at whatever it was before -- confirmed exactly
matching Doug's report: displayed 30, but `x/2` computed against a
stale `self.x`, producing 0.0.

Fixed by connecting `xdisplay.editingFinished` (Qt's standard signal
for "user finished editing this field," firing once on Enter or focus
loss -- not per-keystroke, so no risk of a feedback loop with the
existing `setText()` calls scattered throughout the rest of the
class) to a small handler that parses the current display text into
`self.x`. Clicking away to another button naturally triggers a focus-
loss before that button's own handler runs, so `self.x` is correctly
synced before any subsequent calculation reads it.

Deliberately NOT made read-only -- direct keyboard entry is Doug's
normal workflow, not a misuse of the widget; the fix makes it actually
work correctly rather than blocking it.

Y/Z/T displays share the same editable-QLineEdit-with-no-sync
pattern, in principle, though Doug's report and testing were specific
to X. Not touched this session -- worth the same fix later if the
same symptom ever shows up on those registers.

### Lesson for future development

**A specific, narrowed lead from a prior session (Session 41's
"laptop keyboard, not buttons") turned what could have been another
open-ended investigation into a direct, half-hour trace to the exact
missing signal connection.** Worth treating Doug's own narrowing work
as seriously as a stack trace when deciding where to look first.

## Session 43: calculator fix generalized to all 4 registers; dev log heading formatting fixed throughout

Generalized Session 42's X-register fix to Y/Z/T as well, per Doug's
request to do all four at once rather than wait for the same bug
report three more times. One shared `_sync_register_from_display()`
handler, wired to all four displays' `editingFinished` signals via a
loop (matching the existing `lambda state, r=...: ...` default-arg
pattern already used elsewhere in this file for button wiring, to
avoid the classic Python late-binding closure bug).

Separately, Doug flagged that this log's own `## Session N: ...`
headings lose their heading styling wherever the heading text wraps
onto a second line in the raw markdown -- Markdown headings are
single-line by definition, so a literal newline partway through one
silently ends the heading and starts an ordinary paragraph. Affected
17 of this document's 51 headings (long descriptive titles wrapped for
raw-text readability, without realizing this would break rendering).
Fixed programmatically -- joined every split heading back onto one
line -- rather than by hand across 3000+ lines; verified afterward
that all 51 headings survived with none still split.

### Lesson for future development

**A markdown-formatting convention that looks fine in a text editor
can silently break at render time, and it's worth checking the
RENDERED output occasionally, not just the raw source.** Wrapping
long lines for readability while writing is a reasonable habit in
general, but headings are one of the few Markdown constructs where
that habit actively breaks something -- worth remembering for any
future long entries.

## Session 44: delEl (delete profile element) silently not deleting -- same bug class as fillet, fixed the same way

Doug found `delEl` picks a profile edge cleanly but never actually deletes it. Root cause: `if shape in wp.edgeList: wp.edgeList.remove(shape)` used Python's default equality on TopoDS shapes -- the exact same bug class already fixed once in `kodacad.py`'s `fillet()` (Session 20-era): a freshly-picked `TopoDS_Edge` can be a different Python wrapper object around the identical underlying geometry, so `in`/`remove()` silently never matches even when the edge genuinely is in the list. The pick worked; the membership check just never found it, so nothing was ever removed, and `redraw()` ran harmlessly on an unchanged list -- explaining exactly why this looked like "selection works, deletion doesn't."

Fixed with the same `IsSame()`-based matching already proven in `fillet()`. Checked the rest of the codebase for the same pattern before considering this done -- only one `.remove()` call exists anywhere in `m2d.py`/`kodacad.py`/`mainwindow.py`/`workplane.py`, and it's the one just fixed, so this isn't a multi-site bug like the RMB handlers or `RemoveAll()` wipe were.

### Lesson for future development

**A bug fixed once in one function is worth remembering as a pattern to check for elsewhere the next time something "silently doesn't work" rather than crashes** -- the symptom here (pick succeeds, action silently no-ops) was different from fillet's crash, but the underlying cause was identical. Recognizing "this smells like the TopoDS-equality issue" from the symptom alone, before even opening the file, made this a fast, confident fix rather than a fresh investigation.

## Session 45: tidying up -- boilerplate headers, version consistency, menu order

Doug caught the file headers still referencing the original pyocc-era "kodacad" repo (no "2") and asked whether to fix the URL or drop the boilerplate. Found real precedent already in the repo: `docmodel.py` had been updated at some point to a shorter form -- project name corrected, full GPL paragraph and stale URL both dropped -- rather than just patching the URL. Confirmed a `LICENSE` file (GPLv3) already exists in the repo root, and confirmed Doug wanted to follow standard GPL practice: a short per-file notice, full legal text living once in `LICENSE`, not repeated six times. Applied `docmodel.py`'s pattern to the other five files (`kodacad.py`, `m2d.py`, `mainwindow.py`, `rpnCalculator.py`, `workplane.py`), and added one small, standard addition to all six for full consistency: a one-line license reference (FSF's own recommended short-form notice includes this; `docmodel.py`'s version hadn't had it either). Worth noting for the record: the old boilerplate referenced GPLv2, while the actual `LICENSE` file is GPLv3 -- a real mismatch, moot now that the old text is gone, but good to have caught.

Also fixed real version inconsistencies beyond the one Doug had already caught (`version.py` -> `1.0.0`): `README.md` had "KodaCAD 3.0" in two places (title and body text), and `pyproject.toml` had `version = "0.1.0"`, a third, disconnected number. All three now agree.

Moved "Position" one spot right in the menubar, after "Modify Active Part" -- worth noting this reverts to the exact order the original PDF design mockup showed, which an earlier session had deliberately deviated from (reasoning Position fit better woven into the Create-3D-to-Modify flow) and Doug had validated at the time. Not clear whether this is a reconsideration or just a preference shift -- noted for the record either way, not questioned further.

### Lesson for future development

**A previously-made, undocumented style change (docmodel.py's shortened header) is worth surfacing as precedent before making a fresh decision from scratch.** Doug's question presented two options (fix the URL, or drop the boilerplate); the actual best answer was a third one already sitting in the repo, just not the file that happened to prompt the question.

## Session 46: Nudge ignoring the user's chosen units -- confirmed missing, fixed

Doug switched Kodacad to inches for a real project (2x4 lumber), typed 0.75 into Nudge meaning 3/4", and the part moved 0.75 MM instead -- Nudge was silently ignoring the units setting entirely. Confirmed directly: `position_dialog.py` never referenced `win.unitscale` anywhere, while every other numeric entry point in the app (extrude, mill, pull, fillet, shell, all 2D sketch entry) already follows the established, documented convention in `mainwindow.py`: "(user input values) * unitscale = value in mm." Nudge's translation fields were the one typed-numeric-value entry point in the whole Position dialog that never got wired into it -- everything else in that dialog (2 Points, Mate/Align, Align Axis) works from picked geometry, which is inherently already in mm, so this specific gap never showed up until someone actually typed a distance by hand in a non-mm session.

Fixed by multiplying dx/dy/dz by `self.main_win.unitscale` right after parsing, before they're used in the translation. Rotation values (rX/rY/rZ, always degrees) are correctly left alone -- angles don't have a length-unit dependency. Checked the rest of `position_dialog.py` for any other raw `float(...text())` parsing before considering this complete -- Nudge's six fields are the only typed-value entry point in the file.

### Lesson for future development

**An established, documented convention used consistently everywhere else in a codebase is worth checking explicitly for in any new numeric-input feature, not just assumed to be inherited automatically.** Nudge was built in Session 23, well after the unitscale convention was already standard practice across `kodacad.py` and `m2d.py` -- it just never got connected, because nothing about building it made the omission obvious until a real, non-mm use case exposed it directly.

## Session 47: deleted parts orphaned instead of removed -- confirmed via CAD Assistant, fixed

Doug used as1-oc-214.stp as a starting point for a real project, deleted the original components, and found them still present in the saved STEP file (viewed in CAD Assistant) as free shapes sitting alongside `as1`, even though Kodacad's own tree correctly showed them gone. Doug's own diagnosis was exactly right: `delete_component()`'s `RemoveComponent` call only drops the one component *reference* -- correctly so, since that's what has to happen for shared instances (breaking a sibling that still legitimately references the same part would be worse) -- but nothing ever checked whether that was the *last* reference, so a component with no siblings just became an orphaned, unreferenced free shape instead of being fully removed. XCAF writes every free shape to STEP regardless of whether anything points at it, which is exactly what showed up as siblings of `as1` in CAD Assistant.

Fixed by checking `GetUsers_s()` (the same method already used for shared-instance detection since Session 22) immediately after removing the component reference -- if zero users remain, the now-orphaned referred shape is removed too via `RemoveShape`. Verified against OCCT's own reference documentation before trusting this: `RemoveShape` explicitly "returns False (and does nothing) if shape is not free or is not top-level shape" -- a real safety guarantee independent of the `GetUsers_s` check, so even if that check somehow missed something, `RemoveShape` itself refuses to touch anything still genuinely in use. Two independent layers of protection, not one relying on the other being perfect.

### Lesson for future development

**A fix that's correct for the shared case can still be incomplete for the common case, and it's worth checking both rather than stopping once the harder case is handled.** `RemoveComponent` alone was the *right* choice for not breaking shared instances -- the gap was never testing what happens when there's nothing shared to protect. Doug catching this by cross-checking the saved file in a second, independent tool (CAD Assistant) rather than trusting Kodacad's own tree view is exactly the kind of verification that's caught several of this project's real bugs before.

## Session 47 (cont'd): existing orphans need a one-time external cleanup -- Kodacad's own tree can't see them

Doug asked the right follow-up question: will the orphans already baked into his saved (pre-fix) session file go away on their own, or does he need to redo the work? Checked `parse_doc()` directly to answer precisely: it uses `shape_tool.GetShapes(labels); root_label = labels.Value(1)` -- only ever looking at the FIRST free/top-level shape in the document as "the root." Any additional free shapes -- including the orphans from before Session 47's fix -- are invisible in Kodacad's own tree and unreachable through the app's normal UI, regardless of the fix now being in place for future deletions.

Built `cleanup_orphans.py`, a standalone, two-step script (matching the same safe pattern as `occt_bug_repro.py`/`minimal_repro.py`): Step 1 lists every free shape in a file (read-only); Step 2 removes everything except explicitly-named entries to keep, writing to a NEW file rather than overwriting the original. Never guesses which shape is the "real" root -- Doug confirms that himself from the Step 1 listing.

Caught and fixed one mistake before shipping it: the entry-extraction helper initially passed a plain Python string to `TDF_Tool.Entry_s` as an out-parameter, which can't work (Python strings are immutable) -- fixed to match `docmodel.py`'s own proven pattern (a mutable `TCollection_AsciiString` object) before it ever got run.

**Worth a separate design conversation, not resolved here:** should Kodacad's own tree-building show every free shape in a document (making a stray orphan visible and manageable through the normal UI, if one ever occurs again for some other reason), or is enforcing "exactly one root" a deliberate simplification worth keeping? Not changed this session -- a bigger, more invasive change than fixing the immediate problem needed, with unclear ripple effects on other code that may assume a single root.

### Lesson for future development

**A fix that prevents a problem going forward doesn't automatically clean up damage the problem already caused, and it's worth checking explicitly whether it does before telling someone the issue is resolved.** Session 47's `delete_component()` fix is complete and correct for anything deleted from now on -- but Doug's file was already saved before that fix existed, and the fix has no mechanism (and, by design, no way) to retroactively reach back into an already-written file. Worth stating this distinction plainly rather than letting "fixed" imply "and your existing file is fine now too."

## Session 47 (cont'd again): orphan cleanup needed to recurse, not just check one level -- fixed in both places

Doug's first cleanup run left new orphans behind: removing `rod-assembly` and `l-bracket-assembly` (both correctly identified as orphaned) exposed their OWN children -- `rod`, `nut-bolt-assembly`, `l-bracket` -- as newly-orphaned free shapes one level deeper, since `RemoveShape(label, True)` doesn't cascade orphan-detection through nested levels on its own. Doug's own diagnosis and proposed fix ("a -r option, or rerun until stable") was exactly right.

Fixed in both places this affects:

- `cleanup_orphans.py` now loops automatically (up to 20 passes) -- each pass re-checks `GetFreeShapes()` rather than computing the removal list once, so it keeps going until a full pass removes nothing new. No manual re-running needed.
- **The same gap almost certainly exists in the main app's `delete_component()` fix from earlier this session** -- it only checked one level of orphaning, so deleting a multi-level nested assembly (like `l-bracket-assembly`, which contains `nut-bolt-assembly`) would very likely leave the same kind of deeper orphan behind. Fixed with a new, recursive `remove_shape_and_orphaned_descendants()` helper: captures a shape's children's referred labels *before* removing it (removal destroys the component references needed to find them), then recursively checks each captured child for orphan status and cleans it up too. `delete_component()` now uses this instead of a bare `RemoveShape()` call, for both the "component under an assembly" and "free root shape" cases.

### Lesson for future development

**A fix confirmed correct for the reported case can still have the same structural gap one level deeper, and it's worth checking explicitly for recursion rather than assuming a single level was the whole problem.** The earlier delete_component() fix (checking GetUsers_s once, after one RemoveComponent) was correct as far as it went -- it just didn't go far enough for nested assemblies, and nothing about testing a single-level deletion would have revealed that. Doug's own cleanup script run, on real multi-level data, is what actually exposed it.

## Session 48: recursive orphan fix still leaving l-bracket-assembly behind -- hypothesis attempted, diagnostic added, not yet confirmed

Doug tested Session 47's recursive `delete_component()` fix directly: loaded as1-oc-214.stp, deleted BOTH shared instances of l-bracket-assembly, saved, checked in CAD Assistant. Still present as an orphan -- the fix did not resolve this case.

**Best-reasoned hypothesis attempted, not confirmed:** `UpdateAssemblies()` was only called once, at the very end of `delete_component()`, after the orphan-detection decision had already been made. Added an explicit `UpdateAssemblies()` call immediately after `RemoveComponent()`, before checking `GetUsers_s` -- on the theory that XCAF's internal bookkeeping about what's now free might need an explicit refresh right after removing a component reference, before `GetUsers_s`/`RemoveShape` can correctly see the change reflected. `RemoveShape` explicitly documents that it refuses to act on anything not genuinely free/top-level, so a stale view at exactly this point would produce precisely Doug's symptom -- appearing to silently do nothing.

**Also added a diagnostic print** reporting the actual `n_users` count `GetUsers_s` sees at the moment the removal decision is made. Not removed even if the hypothesis above turns out to be right, since it's cheap and directly answers the one question needed to confirm or rule out this line of reasoning without another round of blind guessing.

**Explicitly not confirmed working.** This is being shipped as a well-reasoned attempt with a built-in diagnostic, not a verified fix -- worth being honest about that distinction given how many prior sessions on this exact class of bug (component deletion / shared-instance orphaning) turned out to need more than one attempt.

### Lesson for future development

**When a fix doesn't work and the reason isn't obvious, pairing the next attempt with a diagnostic that directly answers the open question is better than either guessing again silently or asking for another round of raw terminal output first.** If this attempt is also wrong, the printed `n_users` value tells us immediately whether the orphan-detection logic itself is sound (and something else is the problem) or whether `GetUsers_s` genuinely isn't seeing what it should at that point -- narrowing the next attempt considerably either way.

## Session 48 (cont'd): confirmed working -- likely a stale-process false alarm on the first test

Doug retested the exact same scenario (delete both l-bracket-assembly instances one at a time via RMB, letting the tree refresh between each) and this time it worked correctly -- confirmed via the `[save_step_doc]` pre-write dump showing exactly one free shape (`as1`, with only `rod-assembly_1` and `plate_1` as children, no orphaned sibling), and confirmed again in CAD Assistant.

Doug's own theory is the most likely explanation: Kodacad wasn't restarted between receiving the Session 47/48 code and the first test, so that run was very likely still executing the pre-fix `delete_component()` regardless of what was already saved to disk -- Python doesn't hot-reload a running process's already-imported modules.

**One loose end, not chased further right now:** the terminal output from the successful run does NOT show the `[delete] orphan check: ref_label users=N` diagnostic added in Session 48's `UpdateAssemblies()`-timing attempt -- meaning this successful run may still have been on Session 47's code alone (without Session 48's addition), which would mean the recursive-removal fix by itself was already sufficient, and the `UpdateAssemblies()` timing theory was never actually tested. Worth a clean-restart confirmation to know for certain which specific change deserves credit, but not urgent -- either way, deletion + save now produces a correct result for this exact scenario.

### Lesson for future development

**"Did you restart the app after the code changed?" is worth asking early when a fix appears not to work, before investigating further** -- a stale, already-running process executing old code is a mundane, extremely common explanation that produces symptoms indistinguishable from a genuinely unfixed bug, and costs nothing to rule out first.

## Session 49: undo/redo and native save/load -- smoke tests written, not yet run

Doug's Quaoar tutorial insight: OCAF has BOTH undo/redo and native document save/load built in, and Kodacad already creates its documents in BinXCAF format -- OCAF's own native persistence format, not just a format STEP happens to use internally. Worth genuinely investigating rather than assuming either "too hard" (Doug's original impression from early in the port) or "just works" (unverified optimism) -- exactly the kind of claim this project has learned to verify empirically before building on.

Researched both APIs before writing anything. Undo/redo: `SetUndoLimit()` (disabled by default, takes effect on the next `NewCommand()`), `NewCommand()` (commits the current transaction and opens a new one), `Undo()`/`Redo()` (one step each). Confirmed directly: undo/redo history does NOT persist across save/load (a real OCCT forum thread confirms this explicitly) -- a session-only feature by design, matching how most CAD tools work anyway, not a limitation specific to this approach.

Native save/load: `TDocStd_Application::SaveAs`/`Open`, `PCDM_StoreStatus`/`PCDM_ReaderStatus`. Found a genuinely mixed signal worth being honest about rather than glossing over: a real, confirmed GitHub issue (CadQuery/OCP#182, CadQuery/cadquery#1599) reports `Open()` returning an EMPTY document specifically in OCP's wrapping, as recently as last year -- while other real code (CadQuery/OCP#55) shows `SaveAs` working correctly. This is exactly the kind of uncertain-until-tested-on-THIS-specific-setup situation Doug's smoke-test instinct is built for.

**Two smoke tests written, testing real operations rather than trivial cases:**

- `smoke_test_save_load.py` -- builds an assembly with a genuinely SHARED instance (not just a bare leaf part), saves via `SaveAs`, reopens in a completely fresh document via `Open`, and dumps the result for comparison. Sharing was specifically included because that's exactly the kind of thing that's gone wrong with STEP round-trips in this project before -- worth checking whether native persistence handles it correctly rather than assuming it does just because it's "native."
- `smoke_test_undo_redo.py` -- tests undo/redo against the SPECIFIC XCAF operations `docmodel.py` actually performs: `AddComponent` (the normal part-add path) and the `RemoveComponent`+`AddComponent` reposition pattern (`set_component_location()`, Session 22 onward) -- not a trivial attribute change, since what matters is whether OCAF's transaction system correctly tracks the actual operations Kodacad uses, not whether undo/redo works in the abstract.

**Not yet run.** Written and compiled, but the real answer -- whether either capability is usable in Kodacad's actual environment -- can only come from Doug running them and sharing the output, the same as every other empirical question in this project.

### Lesson for future development

**A "maybe this is achievable" question is worth researching thoroughly enough to find the REAL uncertainty (a confirmed, contradictory GitHub issue) before writing any test code**, rather than either taking the OCCT documentation at face value or assuming a clean answer exists. The mixed signal found here isn't a reason to avoid testing -- it's the precise reason a smoke test is the right next step, and it's also valuable context to hand back to Doug rather than silently writing tests as if the outcome were already known.

## Session 49 (cont'd): results in -- undo/redo confirmed working, native save/load confirmed blocked by a real OCP bug

Doug ran both smoke tests. Split result, both conclusive:

**Undo/redo: CONFIRMED WORKING.** Every step of the real-operations test passed exactly as expected -- 2 available undos after 2 committed transactions, `Undo()` x2 correctly reverted the reposition then the `AddComponent` back to an empty assembly, `Redo()` x2 correctly replayed both, ending in a state matching the original "after reposition" dump exactly. OCAF's transaction system correctly tracks the actual XCAF operations `docmodel.py` performs (`AddComponent`, the `RemoveComponent`+`AddComponent` reposition pattern) -- this is a real, usable foundation for an undo/redo feature, not just a documented capability that might not apply to Kodacad's specific usage.

**Native save/load: CONFIRMED BLOCKED.** `SaveAs` returns `PCDM_SS_OK`, `Open` returns `PCDM_RS_OK` -- both report success -- but the reopened document has ZERO free shapes. Completely empty despite both status codes claiming success. This matches a real, previously-found GitHub issue (CadQuery/OCP#182, "Empty document when trying to use TDocStd_Application::Open wrapped by OCP") closely enough to be confident it's the same underlying binding-layer bug, not something specific to this test or a mistake in how it was set up. This is a genuine limitation in the OCP binding itself, not something fixable from Kodacad's side without either a workaround or an upstream OCP fix.

### What this means going forward

Undo/redo is worth pursuing as a real feature -- the mechanism is confirmed sound on real operations. Integrating it into Kodacad would mean wiring `NewCommand()` calls around user-initiated operations throughout `kodacad.py`/`m2d.py`/`position_dialog.py`, plus UI wiring (Ctrl+Z/Ctrl+Y, menu items, keeping the UI in sync after an Undo/Redo changes the document without going through the normal operation handlers) -- a real integration effort, but built on a confirmed-solid foundation rather than an open question.

Native document save/load is blocked for now. STEP export remains the only viable persistence path, with its own already-documented, already-worked-around limitations (the assembly-import-persistence issue from Sessions 17-30, now also the subject of the ongoing OCCT discussion thread). Worth revisiting if OCP fixes the underlying issue upstream, or if a workaround surfaces -- not investigated further this session pending Doug's call on whether that's worth the effort.

### Lesson for future development

**Writing the smoke test before committing to integration work paid off exactly as intended -- one path confirmed genuinely viable, one path confirmed genuinely blocked, both on real evidence rather than documentation-reading or optimism.** Worth noting the asymmetry: a positive smoke-test result (undo/redo) still requires real integration effort to become a feature, while a negative result (save/load) closes the question cleanly and immediately, saving what would have been a much more expensive discovery mid-integration.

## Session 50: leaf-part import/reposition persistence confirmed via real external data (FreeCAD)

Doug tested with genuinely external, real-world STEP files for the first time on this question: imported 2 FreeCAD-authored parts (simple, no internal assembly structure) into an as1-oc-214.stp session, repositioned them from their at-origin import locations to the plate's corners, deleted everything else, saved, and reloaded. Positions survived correctly.

This confirms, via real external data through the actual application workflow, the same leaf-vs-assembly distinction the `minimal_repro.py` investigation established back in Session 28 (Scenario A: flat leaf shape import + move, WORKS; Scenario B: nested assembly import + move, FAILS) -- and further confirmed by `occt_bug_repro.py`'s Case 2 control case. What's new here isn't the underlying diagnosis, which was already well-characterized -- it's independent, real-world confirmation that the diagnosis holds for actual FreeCAD-authored content through Kodacad's real UI (import, Position dialog, delete, save/reload), not just synthetic test geometry run through a standalone script.

**Practically useful, worth stating plainly:** importing and repositioning individual parts is a fully reliable workflow today, independent of the ongoing OCCT discussion thread. The known limitation is specifically scoped to repositioning an imported assembly (something with its own internal component structure) as a unit -- not to importing external STEP content in general.

### Lesson for future development

**Confirming an existing diagnosis against real, independently-sourced data (a different CAD tool's actual export, not synthetic test geometry) is worth doing even when the underlying mechanism is already well understood** -- it turns "we believe this is scoped correctly, based on our own test cases" into "we've confirmed this holds against real external content too," which is a meaningfully stronger claim to stand behind, and a genuinely useful thing to know is true before recommending a workaround to rely on.

## Session 51: FreeCAD's actual source confirms a real alternative strategy -- smoke test built to verify it, carefully, given Session 29's history

Doug's FreeCAD experiment (Session 50-adjacent) succeeded where Kodacad has struggled -- imported two assemblies, repositioned one, exported, and both survived a full round trip with names and locations intact. Doug asked whether FreeCAD's open source could show us how. It can, and does, directly.

Read FreeCAD's actual `ExportOCAF::saveShape()` source (confirmed via GitHub, not inferred): FreeCAD never uses `XCAFDoc_Editor::Extract_s` or any cross-document label copying. On import, it reads shape/name/location out of the source document as plain data into its own separate `App::DocumentObject` model (confirmed via FreeCAD's own architecture documentation), discarding the original document entirely. On export, it rebuilds a completely fresh XCAF document from scratch using ordinary same-document `AddShape`/`AddComponent` calls. Every shape FreeCAD writes is, from that document's own perspective, natively created -- exactly matching the case already confirmed reliable in Kodacad (native session content never shows this bug; only `Extract_s`-based cross-document import does).

**Explicit caution carried into this session:** Session 29 already attempted something in this spirit (native-rebuild-with-recursion) and it regressed internal sharing within imported files -- rebuilding naively duplicated shared geometry instead of preserving it. Doug's own prior finding (the p-curve filesize discovery) increased confidence that FreeCAD's OCAF handling is generally careful and well-considered, but that's still a reason to verify rather than a substitute for it.

Built `smoke_test_freecad_strategy.py`: constructs a source assembly with a genuinely shared leaf part (two instances, different locations), rebuilds it natively into a destination document via a recursive `rebuild_natively()` function using a memo dict keyed by source entry (so a shared part is rebuilt once and referenced twice, not duplicated -- the specific thing Session 29 got wrong), adds it as a component of existing destination content, repositions it via the exact `RemoveComponent`+`AddComponent` pattern that has been the failure point in every prior attempt, writes to STEP, and reads back fresh. Added an explicit sharing-verification step (comparing the reloaded instances' referred-entry strings directly) rather than leaving sharing correctness to be inferred from a name/location dump alone.

**Not yet run.** This is the test that will tell us whether Kodacad should adopt this strategy for `add_component_from_label` -- real answer pending Doug running it.

### Lesson for future development

**A competitor/peer project's success at something we've struggled with is worth investigating at the actual source level, not just observing the outcome and guessing at the mechanism.** Reading FreeCAD's real export code turned "they must be doing something different" into a specific, checkable, three-sentence description of exactly what's different -- which is what made it possible to design a precise smoke test around the exact risk (sharing preservation) rather than a generic "does this work" test.

## Session 51 (cont'd): FreeCAD-strategy hypothesis disproven -- new, sharper question isolated

Doug ran smoke_test_freecad_strategy.py. Surprising, valuable negative result: the fully native rebuild (AddShape/AddComponent only, zero Extract_s anywhere) failed IDENTICALLY to the original bug -- blank/auto-generated name, identity location. This directly disproves the "cross-document Extract_s copying is the root cause" hypothesis this whole investigation (including the OCCT discussion thread) has been built on -- a native rebuild in the SAME document hits the exact same failure.

This conflicts with something already well-established in this project: l-bracket-assembly (itself containing nested nut-bolt-assembly children) has been repositioned via this exact RemoveComponent+AddComponent pattern reliably, confirmed surviving save/reload many times across many sessions (Sessions 33-36 and after). So "reposition an assembly" is not inherently broken -- something else differs between that confirmed-working case and this newly-failing one.

One real difference identified: l-bracket-assembly's structure was read WHOLESALE by STEPCAFControl_Reader from an existing STEP file. smoke_test_freecad_strategy.py's rebuild, and add_component_from_label's real usage, both construct NEW label structure via explicit Python-level AddShape/AddComponent calls within the current session. Built smoke_test_pure_native_assembly.py to isolate this specific variable: an assembly built via AddShape/AddComponent from the very start, in ONE document, no cross-document anything at all -- as pure a native case as this project has tested for an ASSEMBLY specifically (leaf parts already confirmed fine via occt_bug_repro.py's Case 2; this is the assembly equivalent).

If this also fails: the bug isn't about import/Extract_s/rebuilding at all -- it's specifically about repositioning any assembly-typed component via RemoveComponent+AddComponent, and l-bracket-assembly's success must depend specifically on being reader-constructed. That would be a significant pivot in understanding this entire limitation, seven-plus sessions in. If it succeeds, the dividing line is specifically "built via Python calls this session" vs. "read wholesale by the STEP reader" -- also a real, actionable finding, just a narrower one.

**Not yet run.**

### Lesson for future development

**A hypothesis that looked well-evidenced (confirmed via reading real, working competitor source code) can still be wrong, and disproving it cleanly is worth just as much as confirming one would have been.** The FreeCAD-strategy test wasn't wasted effort even though it failed -- it eliminated an entire plausible explanation with a single clean data point, and in doing so pointed at a sharper, more specific question (construction method, not document boundary) that a vaguer "why doesn't this work" investigation might not have found as directly.

## Session 51 (cont'd again): pure native assembly ALSO fails, worse than before -- new hypothesis, instrumented test built

Doug ran smoke_test_pure_native_assembly.py. Result: the component is COMPLETELY ABSENT after the round trip -- not blank-name/identity-location like every prior failure, but genuinely missing entirely. This rules out the "reader-constructed vs Python-constructed" hypothesis (since a genuinely pure, single-document, zero-import native case still fails) -- and it conflicts even more sharply with l-bracket-assembly's confirmed-reliable repositioning throughout this project.

Worse-than-before is itself a meaningful clue, not just a bigger failure. New hypothesis: RemoveComponent() may silently prune the now-unreferenced underlying shape internally -- the same cleanup Session 47 had to add EXPLICITLY for delete_component() (GetUsers_s + RemoveShape). If OCAF does something like this internally for RemoveComponent too, the ref_label captured immediately beforehand (the exact pattern this project has used throughout for every reposition) could already be dangling by the time it's reused in the following AddComponent() call -- and OCAF may silently accept a component built on a dangling reference rather than raising an error, consistent with the pattern of silent no-ops this project has hit repeatedly elsewhere (guessed-wrong enum names, stale Qt references).

Built smoke_test_removecomponent_timing.py to check this directly: captures the document's actual state (via GetFreeShapes) at the precise moment between RemoveComponent() and the next AddComponent(), rather than only checking the final round-trip result. If the referred assembly isn't present as a free/orphaned shape at that exact moment, that's a strong, direct confirmation of this hypothesis -- and would mean the fix is to re-resolve or re-validate the referred label immediately before reuse, not to change where the original content came from at all.

**Not yet run.**

### Lesson for future development

**When a new test's result is WORSE than a previously-understood failure, not just a repeat of it, that difference is itself informative and worth chasing specifically rather than folding into "yet another instance of the same bug."** A single symptom category ("name/location lost on reposition") had been treated as one bug for many sessions; "completely absent" versus "present but blank" turned out to be the detail that pointed toward a genuinely different, more specific mechanism (a stale reference from RemoveComponent's own internal behavior) rather than anything about import or construction history at all.

## Session 51 (cont'd yet again): RemoveComponent-staleness hypothesis disproven -- pivoting to raw-file inspection

Doug ran smoke_test_removecomponent_timing.py. Clean, important negative result: ref_label stays completely valid immediately after RemoveComponent(), GetFreeShapes() correctly shows it as an orphaned free shape, and the following AddComponent() succeeds perfectly -- the new component's own referred shape resolves correctly, and that shape's own child (sub_box_1_1) is exactly right. The in-memory state is 100% correct. This disproves the "RemoveComponent silently invalidates the label" hypothesis.

Combined with smoke_test_pure_native_assembly.py's failure (component completely absent after a full write/read round trip using this exact same, now-confirmed-correct in-memory state), the conclusion narrows sharply: the bug is not in the reposition logic at all -- it's specifically in the STEP write or read step, for a case (pure single-document, natively-built assembly, repositioned) that has never actually been inspected at the RAW FILE TEXT level before. Every prior raw-file inspection in this project (going back to minimal_repro.py) was done on the cross-document Extract_s case specifically.

Built smoke_test_raw_file_inspection.py: repeats the exact confirmed-correct build+reposition, writes to STEP, and greps the RAW FILE TEXT directly for NEXT_ASSEMBLY_USAGE_OCCURRENCE and CARTESIAN_POINT entities -- before ever involving a fresh reader pass. This separates two genuinely different possible failures cleanly: the WRITER never putting correct data in the file to begin with, versus the file being written correctly and the READER failing to reconstruct it.

**Not yet run.**

### Lesson for future development

**Disproving a specific, well-reasoned hypothesis with a clean instrumented test is real progress, not a wasted attempt** -- each of this session's three tests eliminated a distinct, plausible explanation (cross-document copying, construction-method history, RemoveComponent staleness) with actual evidence rather than leaving them as unexamined possibilities, narrowing what's left to investigate at every step rather than accumulating a pile of unresolved guesses.

## Session 51 (cont'd once more): zero NAUO entities at all -- a much more severe result than expected, forcing reconsideration

Doug ran smoke_test_raw_file_inspection.py. Severe result: ZERO NEXT_ASSEMBLY_USAGE_OCCURRENCE entities anywhere in the raw file text -- not malformed, not blank-named, completely absent. None of the CARTESIAN_POINT values show the (50,0,0) reposition translation anywhere either; the only points present are the two boxes' own corner coordinates. The writer isn't writing this assembly's structure incorrectly -- it isn't writing it at all.

Confirmed Kodacad's real save_step_doc() uses the identical write pattern as every test script this session (STEPCAFControl_Writer(WS, False), Transfer(doc, STEPControl_AsIs), Write()) -- ruling out a missing call in the test scripts specifically.

This forces an uncomfortable reconsideration of this whole session's working assumption. occt_bug_repro.py's Case 1 -- which DID show 'base' with a child present in the file (wrong name/location, but structurally there) -- went THROUGH XCAFDoc_Editor::Extract_s before the component was added. Every native test this session (never touching Extract_s) has shown either the same failure or worse. That raises the possibility that Extract_s isn't purely the villain this entire investigation (including the OCCT discussion thread) has assumed -- it may perform some necessary setup that purely manual AddComponent construction is missing, without which the writer can't recognize the assembly relationship at all.

Built smoke_test_native_no_reposition.py to isolate REPOSITION as a variable directly: identical structure, added as a component ONCE and left alone -- no RemoveComponent+AddComponent at all. If this ALSO shows zero NAUO entities, reposition isn't the trigger -- ANY purely native, Extract_s-free, multi-level assembly fails to write its structure, a far more fundamental finding than anything this entire multi-session investigation has been built around. If it succeeds, the trigger is specifically reposition applied to a purely-native assembly -- still a new finding, but a narrower one.

**Not yet run.**

### Lesson for future development

**A severe, unexpected result (complete structural absence, not a degraded version of a known symptom) is a strong signal that a foundational assumption needs to be questioned, not just that the same bug got worse.** This session's tests were built to test variations on "does avoiding Extract_s fix the known bug" -- the actual result is forcing a check of whether the entire premise (Extract_s as the primary suspect) was correctly scoped in the first place. Worth remembering: seven-plus sessions and an ongoing OCCT discussion thread were built on that premise, and it may need revisiting rather than just extending.

## Session 51 (yet another continuation): a real structural difference found between every test this session and Kodacad's actual document layout

Doug ran smoke_test_native_no_reposition.py -- confirmed conclusively that reposition is NOT the trigger. Even a never-touched, purely native two-level assembly writes zero NAUO entities. This ruled out reposition as a variable entirely, and forced a check of whether the test scripts themselves were structurally representative of Kodacad's real document layout at all.

Checked docmodel.py directly rather than continuing to theorize. Found two real, concrete differences between every test this session and Kodacad's actual code:

1. Kodacad's real root ('/') is a DEDICATED, EMPTY compound -- created once via AddShape(empty_compound, True) -- and never given its own separate raw geometry afterward. Every test this session instead made 'base' a literal box (BRepPrimAPI_MakeBox) that ALSO had a component added to it -- mixing "has its own raw geometry" with "holds components" on the same label, something Kodacad's real code never does anywhere in the codebase.

2. Kodacad's real native-part-add code (add_component()) uses the SHAPE-based AddComponent overload (AddComponent(root_label, raw_shape, True)) for adding a brand-new part -- not the label-based overload every test this session used throughout. Separately confirmed: set_component_location() (the reposition code, long confirmed correct for native content) deliberately uses the LABEL-based overload instead, with its own documented history explaining why (the shape-based overload was tried for repositioning and found to lose names, auto-numbering results as '22'/'25').

Built smoke_test_dedicated_root.py to test both corrections together: a genuinely empty-compound root matching '/' exactly, the shape-based overload for the initial add (matching add_component()), and the label-based overload for the reposition step (matching set_component_location()'s own confirmed-correct usage). If this succeeds, the entire severe "zero NAUO" result this session was specific to how the test scripts were built, not a property of Kodacad's real document structure -- meaning real sessions were never at risk of this at all, and the original, narrower "imported assembly loses name/location on reposition" question (the subject of the OCCT discussion thread) remains the actual, correctly-scoped problem.

**Not yet run.**

### Lesson for future development

**When a minimal reproduction produces a much more severe or surprising result than the real application ever has, the reproduction's own structural fidelity to the real code is worth checking before trusting the result** -- this project's own established discipline (verify against the actual codebase, don't assume a simplified test accurately represents it) applied to itself, several tests deep into an investigation, rather than only ever being applied to OCCT API claims. A test can be internally consistent and still not actually be testing the thing it was built to test.

## Session 51 (continued yet again): dedicated-root structure confirmed working for a leaf part -- now testing the actual question, an assembly-with-children

Doug ran smoke_test_dedicated_root.py. Success -- 'leaf_moved' at (50,0,0), name and location both correctly surviving the full round trip. This resolves the scare from the prior two tests: the severe "zero structure at all" failures were specific to how those test scripts mixed raw geometry with components on one label, not a property of Kodacad's real document layout. Real sessions were never at risk of that particular failure.

Important to be precise about scope, though: this test used a leaf part, matching what occt_bug_repro.py's Case 2 already confirmed works. It does not yet answer the actual question this entire investigation (and the OCCT discussion thread) has been about -- an assembly WITH ITS OWN CHILDREN, repositioned, losing name/location.

Built smoke_test_corrected_assembly.py: a genuine two-level assembly ('/' -> sub_assembly -> sub_box_1_1), using the corrected structure throughout (dedicated empty-compound root, shape-based AddComponent overload for the initial add matching add_component(), label-based overload for reposition matching set_component_location()). Flagged a specific, real risk directly in the test rather than assuming it away: adding the sub-assembly under root requires passing its raw shape (via GetShape_s, which returns bare geometry with no XCAF structure attached) through the shape-based overload's expand=True path -- exactly the trap set_component_location()'s own Session 16 history warns produces auto-numbered, unnamed results. The test's own output (checking whether 'sub_box_1_1' survives even before any reposition or STEP write) will show directly whether this specific step is itself a problem, separate from anything about reposition or STEP writing.

**Not yet run.** This is the test that actually answers the original question.

### Lesson for future development

**Precisely scoping what a passing test actually proved, rather than letting a success generalize further than the evidence supports, matters as much as chasing down a failure.** smoke_test_dedicated_root.py's success was real and worth the relief it provided, but it answered "does a leaf part work with the corrected structure" (already known) rather than "does an assembly-with-children work with the corrected structure" (the actual open question) -- worth stating that distinction explicitly rather than letting the good news be mistaken for more than it was.

## Session 51 (the FreeCAD pivot): Doug's workflow observation isolates the one variable never tested -- the remove/re-add cycle itself

Doug went back to FreeCAD and characterized its actual workflow precisely, with screenshots: manual-lathe was moved while still a FREE item (its Placement property set to (105, 66, 61) while sitting outside any assembly), and only THEN dragged into the newly-created Assembly -- added as a component exactly once, already at its final position. The "add as component, then reposition via RemoveComponent+AddComponent" two-step -- which every single failing test across this entire investigation has performed -- never happens in FreeCAD's workflow at all.

This isolates a variable nothing has directly tested: is the fragility specifically in the remove/re-add CYCLE, rather than in NAUO placement itself, construction method, document boundaries, or root structure (all now ruled out by this session's earlier tests)?

A mechanical detail sharpens the hypothesis further: the two AddComponent overloads differ in how location travels. The label-based overload takes a location parameter directly. The shape-based overload takes no location at all -- but a TopoDS_Shape can carry its own location (shape.Moved(loc)), and XCAF ingests a located shape by splitting it into prototype-at-identity plus instance-carrying-the-location -- which is exactly how STEPCAFControl_Reader itself constructs components when reading a file. That is the construction pattern underlying l-bracket-assembly, whose repositioning has been confirmed reliable throughout this project, and very likely what FreeCAD's export effectively produces (each object added once, already carrying its final placement).

Built smoke_test_freecad_single_shot.py -- three cases, one variable each:
- CASE A: label-based AddComponent, once, at the final location -- no prior add, no RemoveComponent, ever.
- CASE B: shape-based AddComponent of a pre-located shape (shape.Moved(loc), expand=True) -- mimicking reader/FreeCAD construction directly.
- CASE C: the known-failing remove+re-add cycle, but with UpdateAssemblies() sandwiched between the remove and the re-add -- a cheap probe of the "RemoveComponent leaves stale internal state that poisons the next AddComponent on the same referred shape" theory.

If A and/or B pass where every reposition-based attempt has failed, the practical fix for Kodacad's set_component_location() is to make repositioning look like a single fresh add (or a located-shape add) rather than a remove-then-re-add -- a genuinely actionable, bounded change. If C also passes, the fix is even smaller (one UpdateAssemblies call). API note: Moved() chosen over the in-place Move() (both standard TopoDS_Shape methods; Move() already proven in this exact binding in docmodel.py/kodacad.py) specifically to avoid mutating the shape record stored under the source label.

**Not yet run.**

### Lesson for future development

**A user's precise characterization of a DIFFERENT tool's working workflow -- including what that workflow never does -- can isolate an untested variable that no amount of API-level investigation had surfaced.** Every prior hypothesis this session came from reading code and documentation; the one still standing came from Doug watching FreeCAD's actual sequence of operations and noticing the two-step add-then-reposition pattern simply never occurs there.

## Session 51 (the breakthrough): ALL THREE single-shot cases PASS -- and the earlier freecad-strategy failure is now explained as confounded

Doug ran smoke_test_freecad_single_shot.py. ALL THREE CASES PASSED -- name and location surviving the full round trip for a genuine assembly-with-children in every one, including CASE C, the remove/re-add reposition cycle itself (with UpdateAssemblies between the remove and re-add). Raw NAUO lines confirm it: 'sub_assembly_moved' correctly named in the file in all three cases.

The coherent picture, finally: the NAUO placement mechanism is completely healthy. What matters is the HEALTH OF THE STRUCTURE being written -- label-based construction, reader-constructed content, and located-shape adds all produce healthy structures the writer handles correctly (including through reposition cycles); raw-geometry-with-expand roots and (per the original bug) Extract_s-imported content produce structures the writer cannot generate a proper NAUO for.

**Critical retroactive realization:** smoke_test_freecad_strategy.py's earlier "failure" -- which had been logged as disproving the native-rebuild approach -- used a destination 'base' built as a raw box that also held components: the exact mixed-geometry-root flaw discovered only AFTERWARD in this same session. That failure was very likely confounded by the flawed destination structure, not a verdict on the rebuild approach at all. The rebuild-natively strategy remains viable -- and Kodacad's real '/' root already IS the dedicated empty compound the approach requires.

Built smoke_test_production_fix.py -- the decisive, exact-production-scenario test: source assembly with a genuinely shared leaf part, dedicated-'/' destination already holding native content, memo-guarded native rebuild, add under '/' at identity, reposition via RemoveComponent + UpdateAssemblies + AddComponent at (50,0,0), STEP round trip, then verify all three criteria explicitly: name survives, location survives, sharing survives. Also fixed a real visibility gap while at it: every earlier test's dump() stopped at the instance level (never resolving component references), so the sub-part level was never actually shown; dump_full() here recurses through references, making the complete tree -- including the shared-leaf level -- visible in the output.

If this passes, the fix goes into docmodel.py's add_component_from_label: replace Extract_s with the native rebuild.

**Not yet run.**

### Lesson for future development

**When a later discovery invalidates the conditions under which an earlier negative result was obtained, the earlier conclusion needs explicit re-examination -- a logged "hypothesis disproven" can itself be wrong if the disproving test was confounded.** The freecad-strategy rebuild was declared a dead end hours before the mixed-geometry-root flaw was found; only holding both results side by side revealed that the "disproof" and the flaw were the same event seen from two angles.

## Session 52: THE FIX IS IN -- production test passed all three criteria, docmodel.py updated

Doug ran smoke_test_production_fix.py: ALL PASS CRITERIA MET. Name survived ('imported_assembly_moved'), location survived ((50,0,0)), and sharing survived (leaf_instance_1 and leaf_instance_2 both referencing entry 0:1:1:4 after reload). All four NAUOs in the raw file correctly named. The exact production scenario -- shared leaf part, dedicated '/' root already holding native content, memo-guarded native rebuild, import at identity, reposition via RemoveComponent + UpdateAssemblies + AddComponent, full STEP round trip -- validated end to end.

Implemented in docmodel.py:

- New module-level `rebuild_imported_structure(src_label, shape_tool, color_tool, memo)` -- the validated recursive native rebuild, reading source-document labels as data via the static (_s) accessors and recreating them via this document's own AddShape/AddComponent (label-based throughout). Memo keyed by source entry string preserves sharing within an imported file (shared part rebuilt once, referenced multiple times). Extended beyond the smoke test with best-effort COLOR transfer -- Extract_s carried colors, so the rebuild must too or imports would visibly lose them: source document's color tool resolved via XCAFDoc_DocumentTool.ColorTool_s(src_label) (same any-label mechanism as the ShapeTool_s(doc.Main()) calls throughout), shape-keyed GetColor matching parse_doc's proven read pattern (Surf first, Gen fallback), applied with the proven SetColor(label, color, XCAFDoc_ColorGen); wrapped so a color hiccup prints a warning but never breaks the import. One import bug caught pre-delivery: XCAFDoc_ShapeTool wasn't in module-level imports -- local import added in _transfer_color.
- `add_component_from_label`: Extract_s replaced with the rebuild + label-based AddComponent under '/' at identity. Docstring's KNOWN LIMITATION section now records the resolution (Session 52) with the mechanism. Session 17's same-name suffix guard applied here too (the rebuilt referred label keeps the source's name, and the requested component name is often the identical string -- e.g. 'manual-lathe' -- exactly the case the writer leaves NAUO names blank for).
- `set_component_location`: UpdateAssemblies() inserted between RemoveComponent and AddComponent, matching the validated sequence exactly (Case C insurance).
- `load_stp_undr_top` (dead code, no callers) marked with an explicit warning that it still contains the Extract_s anti-pattern and must be ported to rebuild_imported_structure before ever being wired back in -- left in place rather than deleted without Doug's say.
- Deliberately NOT changed: the Session 22 unshare path inside set_component_location still uses same-document Extract_s. That's cloning reader-constructed/native content within one document -- confirmed working for l-bracket across many sessions -- a different animal from the cross-document import case. Watch item: if unsharing a REBUILT imported component ever misbehaves, port that path to the rebuild too.

Also retroactively explained by the Session 51/52 chain: Session 29's native-rebuild attempt very likely failed its export test for the same confounded reason as smoke_test_freecad_strategy.py (test destination structure), while its sharing regression was real -- the memo now handles what that attempt actually got wrong.

Next: Doug tests the real workflow -- import manual-lathe and as1-oc-214 into a session, reposition, save, reload, verify names/locations/colors/sharing in Kodacad and CAD Assistant. Then update the OCCT discussion thread (#1395) with the root-cause finding: the issue is not reposition or import per se, but that Extract_s produces structures STEPCAFControl_Writer cannot generate proper NAUOs for -- reproducible, with the native-rebuild workaround validated.

### Lesson for future development

**The fix that finally worked was assembled almost entirely from previously-failed attempts whose failures were later understood: Session 29's rebuild (flawed only in sharing), the freecad_strategy test (confounded by its own destination), and the dedicated-root discovery (found by chasing a "worse" failure).** None of those dead ends were wasted -- each contributed a constraint the final fix had to satisfy, and the validated result is the intersection of all of them. Keeping honest records of WHY each attempt failed is what made reassembling them possible.

## Session 52 (cont'd): REAL-WORLD CONFIRMATION -- and the one glitch (yellow first-import colors) diagnosed and fixed

Doug ran the real workflow: imported manual-lathe into an as1-oc-214 session, repositioned it, saved, reloaded. Names survived, position survived, colors survived -- verified in Kodacad, CAD Assistant, AND FreeCAD. The Sessions 14-30 limitation is confirmed fixed on real data, not just the synthetic production test.

One glitch: on FIRST import (before any save/reload), every lathe part displayed YELLOW; colors became correct after the round trip. Diagnosed from the symptom itself: yellow is Quantity_Color's default-constructor color (Quantity_NOC_YELLOW) -- the classic OCCT tell that a color lookup found nothing and the caller displayed the untouched default. parse_doc's display read is GetColor(shape, XCAFDoc_ColorSurf, ...) (line ~386), with no fallback to Gen -- but _transfer_color wrote only XCAFDoc_ColorGen. So: first import -> Surf read finds nothing -> default yellow; STEP write exports the Gen color; STEP reader re-registers it as Surf on reload -> correct colors thereafter. Fixed by writing BOTH types in _transfer_color (Gen kept for export-convention consistency with add_component(); Surf added so parse_doc's read finds it immediately).

### Lesson for future development

**OCCT's default-yellow is diagnostic gold: when something displays as pure yellow, the first hypothesis should be "a Quantity_Color was default-constructed and never filled" -- i.e. a color LOOKUP miss, not a color STORAGE problem.** Here the round-trip-fixes-it behavior plus the yellow tell pinpointed the exact mismatch (write-as-Gen vs read-as-Surf) without needing any new diagnostic scripts.

## Session 53: real-world shakedown with vendor STEP files -- three bugs found and fixed, two features identified

Doug built the manual lathe assembly from individual vendor-supplied STEP component files, testing whether Kodacad has the necessary tools for a real project workflow. Good news: positioning worked correctly for every component. Three bugs found and fixed, two features identified as needed.

### Bug 1: yellow/missing colors on imported parts (not surviving save/reload either)

Two independent issues combined to make colors fail completely:

(a) _transfer_color WROTE via the label-keyed SetColor(dst_label, ...) overload, but parse_doc READS via the shape-keyed GetColor(ref_shape, ...) overload. These are genuinely different storage paths in XCAF -- a label-keyed write stores the color association somewhere the shape-keyed read can't find it. Fixed by writing via SetColor(dst_shape, ...) to match the read path.

(b) Vendor STEP files store colors inconsistently -- some on the shape, some on the label, some on sub-shapes. The source read now tries shape-keyed first (matching parse_doc's own read path), then falls back to label-keyed as a second attempt.

The Session 52 "yellow on first import, fixed after round trip" symptom was an earlier, partial manifestation of this same shape-vs-label mismatch -- the STEP reader re-registers colors in a way the shape-keyed read can find, which is why a save/reload appeared to "fix" it. The full fix addresses both the first-import and the persistence cases.

### Bug 2: assembly component names showing as "NAUO1", "NAUO2"

rebuild_imported_structure faithfully copied the component-reference names from the source STEP file's NAUO entities. Vendor files often have empty or generic NAUO descriptive-name fields, which the STEP reader assigns as literal "NAUO1", "NAUO2", etc. -- meaningless identifiers. The actual part name lives on the REFERRED shape, not the component reference. Fixed: when a component name is empty or starts with "NAUO", fall back to the referred shape's name with a "_1" suffix (matching the naming convention used throughout this app).

### Bug 3: .STEP file extension not recognized

The file dialog filter was missing uppercase ".STEP" (only had .stp, .STP, .step). One line fix -- added *.STEP to the filter on line 1374.

### Features identified as needed (not implemented this session)

4. Create new assembly -- needed for organizing imported parts into sub-assemblies. Basicad does this via a RMB click in the tree.
5. Create shared instance of an assembly or part -- needed for parts used multiple times (Doug's 1602 assembly is used twice). Could be done via RMB click on a tree item.

### Lesson for future development

**The first real-world project attempt finds things no amount of synthetic testing can** -- the NAUO naming issue in particular is a property of HOW vendor STEP files are structured (generic NAUO identifiers rather than meaningful names), not something any test built from hand-constructed labels would ever hit. The shape-vs-label color mismatch is subtler: it's a genuine API distinction (two different SetColor/GetColor overloads that store associations differently) that only matters when the read and write paths are written at different times by different people looking at different parts of the codebase. Both are exactly the kind of integration issue a real shakedown is built to find.

## Session 53 (cont'd): colors still yellow -- "after save/reload too" pinpointed the real issue: sub-shape colors

Doug retested: NAUO names fixed, but parts still yellow BOTH initially and after save/reload. The "after save/reload too" detail is the decisive diagnostic: if _transfer_color had found a color and written it anywhere at all, the STEP writer would have exported it and the reader re-registered it on reload -- still-yellow-after-round-trip means the SOURCE READ found nothing. All four lookups (shape/label x Surf/Gen) missed, so nothing ever reached the document or the file.

Most likely mechanism (now instrumented to confirm): vendor part files typically attach colors to SUB-SHAPES -- the solid or faces INSIDE the product -- with nothing on the part label itself. Both the transfer read AND parse_doc's own display read only ever looked at the top level. This also explains cleanly why the whole-lathe-assembly file worked earlier (its parts carry top-level colors) while individual vendor part files don't.

Two fixes plus instrumentation:

- _transfer_color now ALSO enumerates the source label's sub-shape labels (GetSubShapes_s), reads their colors, creates matching sub-shape labels on the destination (FindSubShape/AddSubShape), and applies the colors there. Signature gained shape_tool (needed for AddSubShape). Prints a one-line "[color] <part>: top-level FOUND/none, sub-shape colors transferred: N" diagnostic per part -- the next terminal run will show exactly what each vendor file actually contains, replacing guesswork with data.
- parse_doc's display read replaced with get_part_display_color(): full fallback chain of top-level Surf -> top-level Gen -> first colored sub-shape. Without this, even correctly-transferred sub-shape colors would still display yellow, since Kodacad shows one color per part read from the top level. (A genuinely multi-colored part now displays its first sub-shape color -- a display simplification, not data loss; the document keeps all sub-shape colors and exports them.)

**Awaiting Doug's next terminal output with the [color] lines to confirm the sub-shape hypothesis against real vendor-file data.**

### Lesson for future development

**"Broken after a round trip too" versus "broken until a round trip" split the color problem into two different bugs with two different fixes -- the persistence detail in a symptom report is load-bearing and worth asking about explicitly when it isn't volunteered.** Session 52's yellow (fixed BY reload) was a write-path mismatch; Session 53's yellow (surviving reload) was a read-path miss. Same visible symptom, opposite halves of the pipeline.

## Session 53 (cont'd again): the binding's own error message identified the exact API fix -- label-keyed GetColor is static (GetColor_s)

Doug's terminal output contained the binding's own signature listing: the instance GetColor accepts ONLY shape-keyed calls (all three listed overloads take TopoDS_Shape). The label-keyed GetColor variants are declared static in OCCT, which in this binding means GetColor_s -- the exact _s convention documented throughout this project (GetShape_s, IsAssembly_s, GetUsers_s, ...). A miss that the convention itself should have caught before shipping.

Consequence of the bug: the failed label-keyed call raised BEFORE the sub-shape scan ran, aborting the whole transfer inside one shared try block -- so the [color] diagnostic never reported what the vendor file actually contains, and the sub-shape hypothesis remains unconfirmed. Two fixes:

- All label-keyed color reads switched to XCAFDoc_ColorTool.GetColor_s(...) in both _transfer_color and get_part_display_color (the display helper had the identical bug, silently swallowed by its own try/except -- returning default yellow with no error printed).
- _transfer_color restructured into independent try blocks (top-level transfer / sub-shape scan), so a failure in one section can no longer blank out the other's diagnostic -- exactly what hid the sub-shape data on the first instrumented run.

Label-keyed SetColor remains an instance method (unchanged) -- proven working in production since add_component's color handling.

**Still awaiting the [color] diagnostic lines from a re-import to confirm what the vendor files actually contain.**

### Lesson for future development

**A pybind11 "incompatible function arguments" error is a complete, authoritative API reference for that method -- read the listed overloads as documentation, not just as a failure notice.** The error printed exactly which overloads exist on the instance, which immediately implied (via the established _s convention) where the label-keyed variants live. Also: one shared try block around a multi-stage diagnostic means the first failure silences all later stages' output -- diagnostics that exist to gather data need failure isolation between stages, or a bug in stage one costs the data from stage two.

## Session 53 (cont'd once more): diagnostic reports NO colors found anywhere -- built a full-characterization probe before guessing again

Doug's re-run with the fixed GetColor_s calls: "[color] '1107-0005-0144 rev1': top-level none, sub-shape colors transferred: 0" -- same for every part. Neither the part labels nor their registered sub-shapes carry colors where the transfer looks. Two very different explanations remain, and the next step is data, not a fourth patch:

(a) These individual vendor part files may genuinely contain NO color data. The colored lathe seen earlier came from the vendor's own ASSEMBLED manual-lathe file -- colors could have been assigned at the assembly level in the vendor's authoring tool, with the per-part exports left uncolored. If so, Kodacad's yellow is simply the no-color default doing its job, and the "fix" is at most cosmetic (a nicer default than OCCT yellow).

(b) Colors exist but are stored somewhere the scan doesn't reach (deeper sub-shape nesting, Curv type, RGBA-only storage, or reader placement not covered).

Built probe_colors.py -- a one-shot full characterization: (1) raw file text scan counting COLOUR_RGB / DRAUGHTING_PRE_DEFINED_COLOUR / STYLED_ITEM / OVER_RIDING_STYLED_ITEM / PRESENTATION_STYLE_ASSIGNMENT entities (zero color entities in the raw text = the file has no colors, investigation over); (2) the read document's ENTIRE color table via GetColors; (3) every shape label in the document with its kind, sub-shape count, and color status probed via every read variant (shape-keyed instance x Surf/Gen/Curv, label-keyed static x Surf/Gen/Curv), including all sub-shape labels. Also suggested the instant manual check: open one vendor part file directly in CAD Assistant -- gray there too means no colors in the file, full stop.

### Lesson for future development

**When two consecutive instrumented runs both report "found nothing," the next move is a full characterization of the data source, not a third targeted patch** -- each patch so far encoded a guess about where colors live; the probe instead asks the file itself, covering every storage variant at once, including the possibility that there is nothing to find. The raw-text entity count in particular can end the investigation in one line of output.

## Session 53 (resolved): probe_colors verdict -- the vendor files contain NO color data at all; yellow was the no-color default doing its job

Doug ran probe_colors.py on a real vendor file (1602-0032-4008 assembly.STEP). Definitive: ZERO color entities in the raw file text (COLOUR_RGB, DRAUGHTING_PRE_DEFINED_COLOUR, STYLED_ITEM, OVER_RIDING_STYLED_ITEM, PRESENTATION_STYLE_ASSIGNMENT all 0), zero registered colors in the read document's color table, NO COLOR on any label by any read variant. Doug independently confirmed the same in CAD Assistant on two part files (1121, 1602) -- no colors there either.

Explanation for the colored appearance elsewhere: Onshape and Creo Elements Direct display their own APP-SIDE default color schemes on colorless imported geometry (Creo ED in particular auto-assigns per-part colors). Neither was reading colors from these files. The assembled manual-lathe.step DOES carry real color entities -- which is why it imports colored -- those colors were present in that export.

Conclusion: the Session 52-53 color-transfer machinery (shape-keyed writes, GetColor_s label reads, sub-shape transfer, display fallback chain) is correct and stays -- it's what makes color-carrying files import properly. Nothing was broken for the colorless files; OCCT's default-constructor yellow was simply an ugly "no color found" indicator.

One cosmetic change: get_part_display_color now returns a neutral gray (0.72 RGB) instead of OCCT yellow when nothing is found anywhere. DISPLAY-ONLY, deliberately not SetColor'd into the document -- exported files stay honestly colorless as authored, no fake color data written.

Possible future nicety (not implemented): a "Set part color" RMB action, so Doug can assign his own colors to imported colorless parts within Kodacad -- would pair naturally with the create-assembly and shared-instance RMB features already identified in Session 53's shakedown list. Also worth Doug checking whether Onshape's STEP export settings have an include-appearances option, which would put real colors in the files at the source.

### Lesson for future development

**"Displays colored in application X" is not evidence the FILE contains colors -- CAD applications routinely paint colorless geometry with their own default schemes, and only a raw-entity scan (or a deliberately neutral viewer) distinguishes file data from app cosmetics.** Three patch rounds were spent on a transfer pipeline that had nothing to transfer; the five-line raw-text scan that settled it should have been the FIRST diagnostic, not the last -- it's the same raw-file-inspection discipline this project already learned for NAUOs in Session 51, applied to a different entity type.

## Session 54: two RMB tree features implemented -- Create New Assembly, Create Shared Instance -- plus the smoke test that decides the unshare question

Doug's two requested features from the Session 53 shakedown list, both implemented as RMB tree actions following the existing handler patterns exactly (_get_clicked_or_current_item -> uid -> dm method -> build_tree/redraw):

- **Create New Assembly** (docmodel.create_new_assembly): resolves the clicked item to its referred label if it's a reference, requires an assembly target, creates an empty compound via AddShape(compound, True) -- the exact '/'-root construction, the healthiest structure this project knows -- and adds it at identity via the label-based AddComponent. Name prompted via QInputDialog; component named with the _1 suffix (Session 17 same-name guard). Documented caveat, printed on creation: an EMPTY assembly may not survive STEP save/reload (a product with no geometry can be dropped by the writer) -- intended workflow is create-then-populate before saving.

- **Create Shared Instance** (docmodel.create_shared_instance): new component under the SAME parent (comp_label.Father()), referencing the SAME underlying shape, at the SAME location -- superimposed, ready for the Position dialog. One more NAUO pointing at one product: exactly as1's own l-bracket-assembly structure. Works for parts and assemblies alike. Named ref_name_{users+1}. Root guarded (cannot be instanced).

**The landmine flagged before building:** Doug's stated workflow (create shared instance -> move it) currently collides with set_component_location's Session 22 UNSHARE step -- moving one of multiple shared instances silently clones it into an independent copy first, defeating the sharing. Session 51/52's findings (healthy label-based structures survive reposition cycles; as1's shared-at-different-locations l-brackets round-trip fine) suggest the Session 22 corruption evidence -- which predates every structural discovery of Session 51 -- may have been confounded the same way smoke_test_freecad_strategy was. Built smoke_test_shared_reposition.py to settle it: two shared instances (create_shared_instance's exact mechanism), one moved to (50,0,0) with NO unshare, STEP round trip, verifying presence + names + locations + preserved sharing -- for BOTH a shared leaf part and a shared assembly-with-children (Doug's real 1602 case). If both pass, the unshare gets removed and the workflow yields genuine persistent sharing end to end; if either fails, the unshare stays for that case with a documented caveat.

**Features shipped; smoke test not yet run.**

### Lesson for future development

**When a new feature's intended workflow routes through an old defensive mechanism, check the collision BEFORE the user discovers it as mysterious behavior** -- the unshare step is invisible in the UI; Doug would have created a shared instance, moved it, saved, and only much later noticed his "shared" parts no longer updated together, with no error and no obvious cause. Tracing the workflow through the existing code path ahead of time turned a future debugging session into a one-smoke-test decision.

## Session 54 (cont'd): both smoke-test cases PASS, both features confirmed in the real app -- the Session 22 unshare is retired

Doug ran smoke_test_shared_reposition.py: BOTH CASES PASS. Leaf part and assembly-with-children alike: two instances after the round trip, correct names, one at origin and one at (50,0,0), both still referencing the SAME underlying shape. Raw NAUOs all correctly named. The Session 22 unshare-on-reposition is confirmed unnecessary -- its corruption evidence predated every Session 51 structural discovery and was evidently confounded by that era's Extract_s-tainted structures, exactly like smoke_test_freecad_strategy's first result.

Doug also confirmed both new RMB features working in the real app: Create Shared Instance made '1602-0032-4008 assembly_2' (2 users sharing one underlying assembly), positioned via Nudge/dynamic to the other end of the assembly; Create New Assembly created 'new_assembly' under as1 with the populate-before-saving reminder printing correctly.

Changes:
- The unshare block in set_component_location is REMOVED (history preserved in a comment at the site: what Session 22 observed, why it was defensible then, and which test retired it). This was the LAST functional Extract_s in any live code path -- remaining references are docstrings, history comments, and the dead load_stp_undr_top (already fenced off with its Session 52 warning).
- create_shared_instance's docstring updated from "under investigation" to the Session 54 resolution.

**Note passed to Doug:** the 1602 instance he moved during this test session was created BEFORE the unshare removal, so it is an independent clone, not a shared instance -- the terminal shows the unshare firing ("unsharing before repositioning -- using independent clone"). To get genuine sharing he should delete that instance and redo create-instance -> move on the updated code.

### Lesson for future development

**A defensive mechanism added on real evidence can outlive the bug it defended against -- when the underlying understanding changes fundamentally (Session 51), every defense built on the old understanding deserves re-testing, not just the primary bug.** The unshare was correct engineering in Session 22 given what was observable then; it became silently harmful (defeating a feature's entire purpose) once the real cause was structural health rather than a writer limitation. The retirement comment at the site preserves both halves: why it existed, and what evidence removed it.

## Session 55: nudge rotations orbited instead of spinning in place -- pivot moved to the manipulator's position

Doug reported: dynamic-nudge a vendor part -48mm in Y (correct), then nudge RX 90 degrees -- the part swung far away (up and to the right in the LEFT view) instead of rotating about the manipulator's white dot as expected. (Initially reported as RZ, corrected to RX -- the correction mattered: an RZ can never change a point's Z coordinate, so the part visibly gaining altitude briefly looked like an impossible result and had an instrumentation plan queued; RX rotates in exactly the Y-Z plane the part moved in, dissolving the contradiction and confirming the plain diagnosis.)

Root cause: _apply_nudge pivoted rotations about the part's LOCAL-FRAME ORIGIN's world position (get_world_loc's translation part). That was already better than the global origin (the previous hazard the old comment guarded against), but a vendor-authored part's local origin can sit arbitrarily far from its geometry -- wherever the vendor's modeler left the datum -- so an intended in-place spin becomes an orbit about a distant point. The AIS_Manipulator gizmo, meanwhile, places itself at the attached object's geometric center: exactly where the user visually expects the pivot to be.

Fix: new canvas accessor manipulator_position() (reads AIS_Manipulator.Position().Location(), returns None when detached); _apply_nudge now pivots about the manipulator's actual position when attached, falling back to the part's world location otherwise. Pivot captured before detach_manipulator(). A one-line "[nudge] rotation pivot: (x, y, z) via manipulator" diagnostic prints on rotation nudges so the retest confirms the pivot source directly.

### Lesson for future development

**When a reported result appears geometrically impossible (an RZ that changed Z), verify the reported INPUTS before hunting for an exotic mechanism** -- the queued instrumentation plan was about to chase a contradiction that one corrected detail (RX, not RZ) dissolved entirely. The underlying UX bug was real and simple; the "impossibility" was only ever in the report. Asking "exactly which field did you type into?" is cheaper than any diagnostic run.

## Session 56: the '////' accumulating-root-wrapper bug -- Basicad item 30 ported properly, two band-aids reverted

Doug spotted '/ / / / as1_1 / new-asy_1 / button_1_1' in the Position dialog path and recalled Basicad had fixed the same thing (DESIGN_BACKLOG item 30). He was right to redirect to it: the first two patches written before reading item 30 were name-level band-aids (rename '/' roots on load; temp-rename before export) that would not have removed any wrapper LEVEL -- just relabeled it -- and would have created duplicate product names in the file (Session 17 blank-NAUO territory). Both REVERTED this session, stated plainly.

**The actual mechanism, reasoned from evidence rather than patched at the symptom:** the tree screenshot shows nested '/' items in the LIVE document. Save and load are structure-preserving -- the STEP writer does not invent wrappers -- so the nesting was created by an in-app operation, and the only operation that nests an entire tree under the current root is IMPORT. The cycle is exactly Basicad item 30's: save a session (file root '/'), later IMPORT that file into a session (rather than loading it as the session) -> the file's '/' root gets wrapped as a component under the current '/' -- one extra level per save+import cycle.

**The two-sided fix, ported to Kodacad's XCAF architecture:**

- IMPORT side (load_stp_cmpnt): a free shape named '/' in the imported file (a saved-session wrapper) is not imported as a node -- its children are imported directly via add_component_from_label, each at its saved location (composed through nested wrapper levels via a worklist, so a legacy multi-wrapped file unwraps completely in one import). add_component_from_label gained an optional loc parameter for this (default identity, unchanged behavior for all existing callers).
- EXPORT side (save_step_doc): when the root is a '/'-wrapper CHAIN -- each level named '/', exactly one child, at identity location -- the writer descends to the first real assembly and exports THAT as the file root, by rebuilding it into a temporary document via rebuild_imported_structure (the validated Session 52 machinery: names, locations, sharing, colors all carry). The in-memory document is untouched. Because the descent walks the whole chain, ONE RE-SAVE fully cleans a legacy multi-wrapped session file ('/'->'/'->'/'->as1 exports as just as1). Any deviation from the safe pattern (multiple children, non-identity location, nothing but wrappers) falls through to writing the document as-is.

Together: export never produces a '/'-rooted file in the common single-assembly case; import never nests a '/' wrapper even when given one. The save+import cycle is idempotent (Basicad item 30's own success criterion), and the wrapper count is bounded at one in every remaining path.

Migration for Doug's existing nested session: just re-save it (single-chain case, handled by the export descent), or import it into a fresh session (multi-branch case, handled by the import unwrap) -- both produce a clean file.

### Lesson for future development

**"I recall we fixed this in <other project>, item N" is a reference worth reading BEFORE designing a fix, not after** -- the first two patches here were written from a partial mental model and aimed at names when the problem was structure; five minutes reading Basicad's actual item 30 writeup supplied the confirmed mechanism (import-of-saved-session nesting), the design shape (two-sided: export unwraps, import unwraps), and the success criterion (cycle idempotency). Porting a proven fix beat re-deriving one, and the honest revert of the premature patches cost far less than shipping them would have.

## Session 57: Tier 1 naming cluster -- three fixes from code reading, one probe for empirical confirmation

Doug's TODO triage put the naming cluster first, on the suspicion it might relate to recent changes. Correct suspicion. All three findings came from READING the code before touching it:

**Fix 1 -- 'button' nameless in CAD Assistant/FreeCAD but fine in Kodacad:** add_component() named the occurrence AND the product with the IDENTICAL string -- exactly the Session 17 rule (identical occurrence/product names make STEPCAFControl_Writer blank the NAUO's name field). External viewers display the NAUO name (blank); Kodacad displays the occurrence label, which the READER back-fills from the product name when the NAUO is blank -- hence the asymmetry, including after a round trip. Fixed: product gets the base name, occurrence gets name_1 -- matching create_new_assembly's convention and as1's own file. This also answers the TODO's "_n suffix -- why?" item: the suffix is the guard against this exact blanking, and add_component was the one path not applying it.

**Fix 2 -- rename of the top assembly lost on save/reload: OUR Session 56 regression, two days old.** The export unwrap descends past the top-assembly occurrence (where a user's rename lives -- change_label_name renames the occurrence label) to the referred product, and exported the PRODUCT's name -- the rename was never consulted, deterministically discarded on every save. Fixed: the descent tracks the final hop's occurrence name; if it's a user rename rather than the auto '<ref>_<digits>' pattern, the exported root carries it (set on the rebuilt temp-doc root before writing).

**Fix 3 -- latent crash branch in change_label_name:** the 4-part-entry case (renaming the root free shape itself) set k=None then called comps.Value(k) -- would raise. The whole legacy j/k tag arithmetic replaced with _find_label_by_entry, the same robust resolver delete_component and set_component_location already use for both root and component entries.

**probe_names.py** built for empirical confirmation on Doug's real manual-lathe+kc.step: raw PRODUCT entity names, raw NAUO entity names (a blank second field is the smoking gun), and the reader's reconstructed tree showing occurrence AND product names at every level. Confirms the button diagnosis against the actual file rather than resting on code reading alone, and doubles as a permanent diagnostic for any future which-viewer-shows-which-name question.

### Lesson for future development

**A user-visible naming asymmetry between viewers ("shows in app A but not app B") is a question about WHICH FIELD each viewer displays, not about whether the name was saved** -- the name was in the file all along, in the PRODUCT entity; the NAUO field was blank. Different viewers legitimately read different fields, and the Session 17 rule quietly determines which field survives. Also: the top-assembly-rename regression went undetected for two days because no checklist item covered "rename, save, reload" -- added now.

## Session 57 (cont'd): probe data corrects the button diagnosis -- unnamed PRODUCT, not NAUO blanking -- repair + tripwire shipped

Doug ran probe_names.py on manual-lathe+kc.step and made the decisive observation himself: CAD Assistant and FreeCAD display PRODUCT names (Kodacad displays occurrence names). The raw data then corrected Session 57's diagnosis, which must be retracted honestly: button's NAUO (#232892) carries 'button_1_1' just fine -- nothing blank, no Session 17 blanking involved. The actual defect is the last line of the probe's tree: button's PRODUCT is named 'Open CASCADE STEP translator 7.9 3.7.1' -- the placeholder STEPCAFControl_Writer stamps on a product label that has NO name at all. Unnamed product -> placeholder in the file -> nameless (well, translator-named) in every product-name-displaying viewer, while Kodacad shows the occurrence and looks fine. (Session 57's Fix 1 -- the suffix convention in add_component -- REMAINS correct and stays: the Session 17 rule is real from its own original evidence; it just wasn't the mechanism here.)

Which path left the product unnamed? All three current paths verify as correct by reading: add_component names the ref (did even pre-57), reparent_component names the new ref explicitly, replace_shape uses SetShape on the same label (name untouched). The leak is likely in a since-replaced code state. Rather than further archaeology, shipped a two-chokepoint fix with a self-identifying tripwire:

- repair_unnamed_products(doc): finds product labels with empty or translator-placeholder names and names them from their first occurrence's name stripped of trailing _N suffixes ('button_1_1' -> 'button').
- Wired at session LOAD (fixes Doug's existing files on next load: reload -> [repair_unnamed_products load] prints -> save -> clean file) and immediately before SAVE (covers both write branches, since the temp-doc rebuild copies names from self.doc). If the save-side one ever fires on content created in the current session, its printout identifies a live leak path by footprint -- turning any remaining unknown into a self-reporting one.

Also confirmed by Doug this session: the top-assembly rename fix works -- 'as1' -> 'lathe-asy' survived save/reload and displayed correctly in all three CAD systems.

### Lesson for future development

**When a diagnosis rests on code reading alone and a probe then contradicts it, the probe wins and the retraction goes in the log with the same prominence as the original claim** -- the Session 17-blanking story was plausible, cited real prior evidence, and was wrong; the raw file showed a healthy NAUO and an unnamed product in one glance. And when the historical culprit for a data defect can't be identified, a repair-plus-tripwire beats indefinite archaeology: existing damage gets fixed unconditionally, and any still-live cause is converted from something to hunt into something that reports itself.

## Session 57 (closed): Tier 1 confirmed complete

Doug confirmed the repair fixed the button name in all three CAD systems (Kodacad, CAD Assistant, FreeCAD). Tier 1 status: top-assembly rename round-trip FIXED and confirmed; product-name display in external viewers FIXED and confirmed; the _n suffix question answered (it's the Session 17 blanking guard, now documented); the latent 4-part rename crash fixed along the way. The repair-on-load pass means every existing session file heals itself on its next load+save cycle -- no manual migration needed.

New TODO item noted by Doug for later: a progress indicator during loading of big STEP files. One heads-up recorded for whoever picks it up: OCCT's Message_ProgressIndicator is designed to be subclassed with virtual-method overrides (Show/UserBreak) -- and Basicad item 28 established that OCP's bindings silently ignore Python overrides of C++ virtual methods (the OnSelectionChanged lesson). The clean OCCT-native approach may hit that wall; a pragmatic fallback is a Qt busy indicator driven from the app side around the reader call. Worth a small smoke test of the virtual-override question before committing to either design.

## Session 58: all four Tier 0 items implemented

Working through Doug's prioritized queue, Tier 0 complete in one pass:

1. **OCP/OCCT version in title bar** (mainwindow.py): the original break was the uncertain OCP surface for the version constant, so _occt_version_string() tries every known candidate spelling (OCC_VERSION_COMPLETE attribute, Complete_s/Version_s statics, non-suffixed variants) and returns '' on total failure -- the title then simply omits the number rather than crashing at startup. Whichever candidate works on Doug's build, works; none of them working costs nothing.

2. **Test items removed from Modify Active Part** (kodacad.py): the 'Rotate Act Part' / 'Reverse Rotate Act Part' menu entries AND their now-orphaned experimental handler functions (rotateAP/rev_rotateAP) removed -- verified no remaining references.

3. **STEP header customization** (docmodel.py save_step_doc): FILE_NAME header fields set between Transfer and Write via APIHeaderSection_MakeHeader on step_writer.ChangeWriter().Model() -- name (the output filename), originating_system 'KodaCAD', author 'Doug Blanding', organization/authorisation blank; values editable at the call site. Fully defensive: the exact OCP surface (ChangeWriter().Model(), SetOrganisationValue spelling) is the one uncertain part, so any binding mismatch prints '[save_step_doc] header customization skipped: <error>' and the file gets the default header -- never a broken save. If Doug's first save prints that line, the error text identifies exactly which call to adjust.

4. **Busy indicator during STEP load** (docmodel.py _load_step): a modal 'Loading <file> ...' dialog shown and painted (processEvents) BEFORE the blocking read+transfer, closed in a finally. Honest limitation documented in the docstring so nobody chases the 'proper' route unaware: true incremental progress needs Message_ProgressIndicator subclassing with virtual overrides, which OCP silently ignores (Basicad item 28); threading the reader would enable animation but brings OCCT/Qt cross-thread risk out of proportion to the feature. The static dialog delivers the actual point -- the user sees the app is working, not frozen.

**Awaiting Doug's test:** title bar shows a version number (or gracefully doesn't); the two test menu items are gone; a saved file's FILE_NAME header shows KodaCAD/authorship (check the raw file header or watch for the skipped-print); loading a big STEP file shows the busy dialog.

### Lesson for future development

**When a feature's only uncertainty is an API spelling, ship it wrapped so that every failure mode is informative and none is destructive** -- the version string degrades to the old title, the header customization degrades to the default header with the exact error printed, and both therefore convert 'will this binding call work?' from a pre-ship research question into a costless runtime answer on Doug's actual build.

## Session 58 (cont'd): Tier 0 test results -- one pass, three revisions with better second approaches

Doug's test: test-menu removal confirmed; version string got the 'graceful absence' (all binding candidates missed); the busy dialog appeared but BLANK (title bar only, label unpainted); the header customization silently produced OCCT's default header ('Author', 'Open CASCADE').

Revisions:
- **Version**: stopped guessing at C++ binding surface entirely -- primary source is now importlib.metadata.version('cadquery-ocp'), pure Python packaging metadata that cannot miss and encodes the OCCT version and build ('7.9.3.1.1'). Binding candidates kept as fallback. Title reads '(Using: OCP 7.9.3.1.1 with PySide6)'.
- **Busy dialog**: one processEvents() pass wasn't enough to paint the label before the blocking read. Explicit setLabelText, several event-pump passes, and a forced repaint() before the block.
- **Header**: default-header output means the values never reached the written model -- either an exception (terminal print not yet confirmed either way) or the wrong model object. Made self-diagnosing rather than re-guessed: per-field try blocks (one bad spelling can't void the rest), both Organisation/Organization and Authorisation/Authorization spellings tried via getattr, a fallback attempt against WS.Model() if ChangeWriter().Model() raises, and -- ground truth -- the written file's actual FILE_NAME block is read back and printed after every save. Whatever the failure mode, the next save's terminal output identifies the exact stage.

### Lesson for future development

**Package metadata beats binding introspection for version strings** -- importlib.metadata is pure-Python, present whenever the package is installed, and immune to the exact class of API-surface uncertainty that broke this feature twice. And when a wrapped feature fails SILENTLY despite its defensive prints (the header case), the revision should add ground-truth verification of the OUTPUT (read the written file back) rather than more guarded attempts -- output readback catches every failure mode including the ones the wrapping didn't anticipate, like writing to the wrong model successfully.

## Session 59: Tier-2 standalones -- RMB flakiness root-caused and fixed; version string round 3; extrude/mill analysis awaiting Doug's symptom

**RMB Set-Active first-try flakiness -- root cause found by reading, one level subtler than expected.** The tree's contextMenu already targeted the item under the cursor (itemAt(point) + setCurrentItem). The actual mechanism: a stale-but-VALID itemClicked from an earlier left-click on a DIFFERENT item passes _get_clicked_or_current_item's shiboken validity check and shadows the currentItem fallback -- so the RMB action silently targeted the OLD item. "Works on re-click" because the re-click's left-click refreshed itemClicked. Fix: contextMenu now overwrites the main window's itemClicked with the item under the RMB cursor (or None on empty area) -- the cursor target is always the user's intent. This applies to EVERY RMB action, not just Set Active.

**Version string, round 3:** the distribution name was the remaining uncertainty -- Doug's pyproject depends on 'ocp', not 'cadquery-ocp'. Now tries 'ocp' first, the other known names after, and finally scans ALL installed distributions for any name containing 'ocp' -- the name is out of the equation entirely.

**Extrude/mill negative-value item -- analysis complete, fix awaiting Doug's exact symptom.** Read everything: no input validators, the line-edit stack path is clean (float('-10') parses fine), and the prism math is sign-correct by construction (extrude's wVec*length flips with sign; mill's wVec*-depth means negative depth aims the tool in +W). Leading hypothesis: mill with negative depth cuts ABOVE the workplane -- where there is typically no material -- so the operation completes and visibly does nothing, reading as "doesn't work." But that's a hypothesis about a symptom not yet precisely described, and the fix differs by which op and what actually happens (terminal error vs silent no-op vs part in an unexpected place). Asked rather than guessed. The +W/-W/Both chooser and add/remove-material-on-the-fly from the same TODO cluster are a design conversation queued behind the symptom answer.

### Lesson for future development

**"Already handles that case" can be true at the layer you checked and false one layer up** -- the RMB handler correctly captured the cursor item into currentItem, and the bug lived in a DIFFERENT variable (itemClicked) shadowing it in the shared fallback helper. When a reported flake survives a fix that "should" have covered it, trace which of the multiple state sources actually wins in the failing sequence, not just whether the right value exists somewhere.

## Session 59 (closed): RMB fix accepted; version string round 4 -- a wrong version is worse than none

Doug confirmed the title bar now shows a version -- but 'OCP 0.1.4', which is WRONG: OCCT is at 7.9.x, and 0.1.4 is the thin 'ocp' wrapper package his pyproject names, not the binding itself. Round 4: collect all ocp-ish distribution versions and prefer one whose major version is >= 7 (the real cadquery-ocp binding underneath the wrapper); if only wrapper-shaped versions exist, show nothing. A misleading number in the title bar actively misinforms; graceful absence merely under-informs.

RMB Set-Active fix accepted by Doug (intermittent bug -- the stale-itemClicked mechanism found by reading is the class of cause that matches intermittency: it required a prior left-click on a different item still being alive). Extrude/mill direction semantics deliberately TABLED at Doug's call -- to be taken up globally in Tier 3's 2D/modeling pass rather than patched piecemeal now.

Next session queue: Tier-2 color (set/edit part color, color picker), then the Tier-2 tree clump (tree<->viewport highlight sync, multi-select delete with batched refresh, expand-all annoyance).

### Lesson for future development

**A fallback that can return a plausible-but-wrong value is more dangerous than one that returns nothing** -- 'OCP 0.1.4' looks authoritative in a title bar and would quietly misinform every screenshot and bug report thereafter. Fallback chains for display values should validate SHAPE (does this look like an OCCT version?) and prefer absence over confident wrongness.

## Session 59 (confirmed): version string round 4 verified -- 'OCP 7.9.3.1.1' in the title bar

Doug's screenshot confirms the title bar now reads 'KodaCAD 1.1.0 (Using: OCP 7.9.3.1.1 with PySide6)' -- the real cadquery-ocp binding version found beneath the 'ocp' wrapper package, selected by the major>=7 shape check. Tier 0 fully closed; Tier-2 standalones closed or deliberately tabled. Next session: Tier-2 color, then the tree clump.

## Session 60: bidirectional tree<->viewport highlight sync (like CAD Assistant)

Doug reprioritized (spending rate) to this over color/multi-select. Implemented both directions on top of the existing plumbing rather than new infrastructure:

- **Tree -> viewport**: treeView.currentItemChanged (fires on mouse AND keyboard nav, unlike itemClicked) -> onTreeCurrentChanged -> _highlight_viewport, which ClearSelected + SetSelected(ais) on the AIS context for the uid's shape from ais_shape_dict.
- **Viewport -> tree**: registered an ALWAYS-ON select callback (install_highlight_sync, called once after InitDriver) -> onViewportSelect -> reverse-map picked shape to uid (_uid_for_selected_shape: IsEqual on whole shapes, then TopExp ancestry match for sub-shape/face/edge picks) -> setCurrentItem + scrollToItem.

Two design constraints handled deliberately:
1. **Re-entrancy guard** (_syncing_highlight): each side's highlight setter fires the other side's selection signal -- without the flag they ping-pong forever. Both entry points check-and-set it.
2. **Separate from operation callbacks**: registerCallback's single-slot system is for operations (mate/extrude/...) that temporarily own selection. Highlight sync is a SEPARATE channel via register_select_callback directly, and onViewportSelect no-ops whenever self.registeredCallback is not None -- so highlight sync never steals a pick from a live operation. The viewport's _on_click already fires callbacks unconditionally on a genuine (non-drag) left-click in neutral mode, confirmed by tracing mouseReleaseEvent, so no viewport change was needed.

**Awaiting Doug's test**: click a part in the viewport -> its tree row highlights and scrolls into view; click/arrow-key a tree row -> the part highlights in the viewport; a live operation (e.g. mate) still gets its picks uninterrupted.

### Lesson for future development

**Bidirectional sync is two features plus one guard, and the guard is load-bearing, not defensive polish** -- the ping-pong loop is the DEFAULT behavior without it, not an edge case. And layering an always-on channel beside an existing single-slot operation-callback system (rather than overloading that slot) is what keeps the new feature from silently breaking mate/extrude selection -- the no-op-during-operations check is the seam between the two.

## Session 60 (cont'd): viewport->tree direction fixed -- callback wrapped the shape in a LIST

Doug: tree->viewport works, viewport->tree does nothing. Root cause found by reading call_select_callbacks: it wraps the picked shape in a LIST ([shape]) and calls cb(shape_list, *args) -- the established contract every operation callback expects. onViewportSelect was mis-declared as (self, shape, *args), so it received the LIST as 'shape' and reverse-mapped a list object, matching nothing. Silent because a no-match is a legitimate outcome (click on empty space).

Fixes:
- _on_click now also passes the selected AIS object (SelectedInteractive()) as an extra callback arg -- highlight sync matches on that, robustly, rather than on SelectedShape() geometry (which is the POSITIONED sub-shape while ais_shape_dict holds BASE shapes -- geometry matching would fail even with the signature right).
- onViewportSelect re-declared to the real (shape_list, *args) contract; reverse-maps via _uid_for_ais.
- _uid_for_ais compares the AIS objects' underlying Shape() via IsSame (TopoDS identity, reliable in this binding) rather than AIS handle ==/IsEqual (binding-fragile in OCP -- the same class of quirk that has bitten this project before). Falls back to shape geometry only if no AIS object came through.
- Added a [highlight_sync] viewport pick: diagnostic so a reverse-map miss is visible during test rather than silent.

**Awaiting Doug's test + terminal**: clicking a part should now highlight its tree row; the diagnostic line reports whether the AIS object arrived and what uid it mapped to, pinpointing any residual miss.

### Lesson for future development

**A callback's established signature is a contract to read before writing a new consumer of it** -- the first implementation guessed (shape) when the codebase's own contract was (shape_list) for every existing operation callback. One grep of call_select_callbacks would have shown the list-wrapping up front. And when adding a NEW consumer to a shared callback, matching on object identity passed explicitly (the AIS object) beats re-deriving identity from geometry that other layers may have transformed.

## Session 60 (closed): the one unpickable part -- createNewAssembly was missing its post-change redraw

Doug isolated it perfectly: highlight sync worked both ways for every part EXCEPT 'button', the one part he'd moved into an assembly he created via RMB. Two symptoms pinned it -- no hover highlight (OCCT's own, independent of our code) and no click-pick, yet tree->viewport SetSelected still worked on it.

Root cause: createNewAssembly did only build_tree() after the structure change, where every other structure-changing handler (createSharedInstance, drag-drop reparent in dropEvent) does the FULL refresh: ais_shape_dict.clear() + build_tree() + redraw(). redraw() re-displays parts with SetAutoActivateSelection(True) -- the step that makes an AIS object hover- and pick-able. Without it, 'button' kept a stale context object that was drawn (visible, and SetSelected-able from the tree) but never re-activated for selection -- hence no hover, no pick, but tree->viewport still fine. The bug predates the highlight feature (Session 54's createNewAssembly); the highlight work is just what made it visible, because before bidirectional sync nobody noticed a part being unpickable.

Fix: createNewAssembly now does the same full refresh as its sibling handlers. Diagnostic print removed (root-caused). Highlight sync confirmed working bidirectionally for all normally-created parts; this closes the last gap.

### Lesson for future development

**A new feature that exercises a capability more thoroughly than anything before it will surface latent bugs in unrelated older code** -- bidirectional highlight didn't BREAK button's pickability; button was never pickable since Session 54, and nothing had needed to pick it until now. When a new feature 'fails' on exactly one item, the item's HISTORY (how it was created) is the diagnostic axis, exactly as Doug reasoned. And the fix is consistency: three structure-changing handlers, only two did the full refresh -- the odd one out was the bug.

## Session 60 (the button saga, resolved pending test): missing triangulation on the curved face -- flat faces were the only pickable surfaces

The view-angle-dependent unpickable 'button' took FIVE wrong theories before the data forced the right one -- recorded honestly, in order: (1) stale AIS / missing redraw in createNewAssembly (a real inconsistency, fixed, but not this bug -- behavior unchanged); (2) occlusion by the channel plate (Doug corrected: the button is IN FRONT, unobstructed); (3) coarse selection tessellation worsening at grazing angles from above (Doug corrected: it's BEST from above, worst edge-on); (4) thin-disk silhouette (Doug corrected: 10mm dia x 15mm long); (5) selection volume displaced from display volume (killed by the context census: 13 shapes, no duplicates, no orphans, every object registered and exactly where drawn).

With structure exhausted, the census's very cleanness pinned the mechanism at the selection-entity level, and ONE mechanism fits all four observations exactly: **a face's pickable sensitivity is built from its TRIANGULATION; the button's curved lateral face has missing/degenerate mesh, so only its flat top/bottom disks were pickable.** Straight down Z: every ray crosses the top disk -> always picks. Iso: rays through the lower body exit through the bottom disk (sensitives aren't backface-culled) -> picks; through the upper body they exit the far lateral wall -> nothing. Edge-on: rays cross only the lateral surface -> unpickable from any azimuth. Vendor parts arrive pre-meshed from the STEP reader; the button came from Kodacad's own sketch->extrude->bake pipeline, which evidently left its mesh absent or degenerate.

Fix: BRepMesh_IncrementalMesh(shape, 0.1, False, 0.5, True) in draw_shape before AIS_Shape creation -- near-free for already-meshed shapes, repairs unmeshed ones. Binding-defensive with a one-time warning. Census and bbox diagnostics removed.

### Lesson for future development

**When a census of the suspected layer comes back perfectly clean, that cleanness IS the finding -- it moves the bug down a level.** Five theories died on user corrections and measurements; each death narrowed the space until only the selection-entity layer remained, and the flat-vs-curved pick asymmetry (the earliest observation, from the very first report) was the fingerprint of triangulation-driven sensitivity all along. Also: every one of Doug's corrections ('it's in front', 'best from above', '10x15mm') was load-bearing -- precise symptom geometry from the user is worth more than any amount of code reading.

## Session 60 (button saga: CLOSED UNRESOLVED, by Doug's call -- with the best clue arriving last)

Doug called it: log as a known problem, stop chewing the bone. Final state of evidence, recorded for whoever reopens this:

**The two anomalies (same part, probably same root):**
1. In Kodacad: the 'button' (10mm dia x 15mm cylinder, axis vertical) is pickable/hoverable ONLY when the pick ray passes through its bottom face -- best looking down Z, impossible edge-on. Unobstructed, in front of other parts.
2. In CAD ASSISTANT (Doug's final observation, the most diagnostic single fact of the saga): the cylindrical surface picks EASILY -- but highlights the PARENT ASSEMBLY ('new-asy') in the tree, uniquely; every other pick in the model highlights the PART. So the anomaly is IN THE DOCUMENT/FILE STRUCTURE: it survives STEP export and confuses an independent OCCT-based viewer. The geometry itself is fine (CA picks it); its structural attribution is nonstandard.

**What was established en route (all archived above in this log):** drawn geometry healthy (bbox 10x10x15 at the right place); context census clean (13 shapes, no duplicates/orphans, everything registered); ALL THREE faces had ZERO triangulation as stored (planar faces pick via outline sensitivity without mesh -- why only the flat faces ever picked); Clean+remesh produced healthy triangle counts (52/24/24) AND a fresh AIS built from the remeshed shape -- picking unchanged, so sensitive data exists and the selector still rejects it. Fixes shipped along the way that were correct but not curative for this part: createNewAssembly's missing full refresh (real inconsistency, fixed); general pre-mesh in draw_shape (real gap -- shapes from the modify pipeline carry no triangulation -- kept).

**The part's unique history (no other part traversed all of this):** created at root via shape-based add_component, dragged through MULTIPLE assemblies via reparent, chopped shorter via replace_shape (mill), exported through the Session 56 rebuild-unwrap, reloaded, product renamed by repair_unnamed_products (it was the translator-placeholder part). The structural scar is presumably from some combination of these.

**Workaround:** delete and recreate the part (~2 minutes). 

**Leads for whoever reopens:** (a) run probe_names.py / assembly_storyboard.py against the saved file and inspect the button's label structure -- specifically whether its solid is attached at new-asy's compound level rather than (only) under its own product, which would explain CAD Assistant attributing the pick to the assembly; (b) check IsSame identity between new-asy's compound content and the button solid; (c) if recreating the part ALSO eventually degrades after reparent+modify cycles, the modify/reparent pipeline is manufacturing these scars and deserves a ShapeFix/heal step; the swap-test build (fresh cylinder at same position, never run) remains the decisive shape-vs-environment discriminator.

### Lesson for future development

**Knowing when to stop is an engineering decision, and an unresolved bug with a complete evidence archive and a cheap workaround is a legitimate closed state** -- six theories died, each killed by a precise user observation or a measurement, and the surviving facts (structure-level anomaly, visible to third-party viewers, unique to the part with the gnarliest history) are worth more to a future session than a seventh guess tonight. The best clue arrived AFTER the decision to stop: checking the artifact in an independent viewer reframed the whole problem from 'our selector is broken' to 'this part's document structure is nonstandard' -- cross-checking in a second implementation is cheap and should happen EARLY in any future saga, not last.

## Session 60 (REOPENED by Doug's decisive experiment): the damage happens in SAVE/RELOAD -- the 2-can minimal repro

Doug ran the experiment that reframes everything. Fresh session: made a clean 10x15 can (no reparenting, no chop, no history) -- hover-picks EVERYWHERE. Saved + reloaded -- the pick pathology appears (bottom-face rays only). Made a second, larger can -- picks everywhere; the reloaded first can still broken. Saved + reloaded again -- BOTH broken. Structure: '/' -> can-asy -> can_1 + big-can_1.

**Conclusions forced by the repro:**
- The damage is introduced by the SAVE/RELOAD cycle, full stop. Part history (reparents, chop) was a red herring.
- The lathe session's 'healthy' parts were all FLAT-FACE-DOMINATED (plate, blocks, brackets) -- flats pick via outline sensitivity regardless. The button was the model's only pure-cylinder part; the cans are pure cylinders. Likely EVERY reloaded part is affected and curved faces are where it shows.
- The pre-mesh at AIS-build time (in the build Doug ran) did NOT cure it -- so missing triangulation is not (or not the whole) operative mechanism. Prime remaining suspect: FACE ORIENTATION -- an inverted face renders fine (two-sided shading) but can defeat selection.

Built probe_pick_shape.py: reads a session file exactly as Kodacad does and reports per part, per face -- orientation flags, surface type, tolerance, triangulation before/after forced meshing, and the key check: whether each face's oriented normal points OUTWARD from the solid (nudge-and-classify via BRepClass3d_SolidClassifier). 'INWARD (INVERTED!)' on the reloaded cans' faces would be the smoking gun and would indict the export rebuild or the reader settings.

**Awaiting: probe output on the 2-can session file, plus whether '[draw_shape] pre-mesh failed' ever appears in Doug's terminal.**

### Lesson for future development

**A user-built minimal reproduction with clean history is worth more than every diagnostic written so far** -- Doug's 2-can experiment eliminated in one stroke the entire history-based theory space (reparents, chop, RMB assembly) that multiple sessions of instrumentation had been unable to rule out, and localized the fault to one pipeline (save/reload) with a one-variable experiment. The 'unique history' correlation on the button was real but coincidental-by-visibility: the button was merely the only part whose geometry EXPOSED a universal defect.

## Session 60 (cont'd): probe exonerates faces -- the pick pattern implicates SHELL-level orientation; probe v2 + display-only heal shipped

Doug's probe run on the 2-can file: face normals all OUTWARD (orientation theory at face level: dead), tolerances healthy, faces meshable (0 -> 52/24/24), pre-mesh never errored in the app. Two findings survive:

1. Both reloaded solids report closed=False -- uninterpretable without a fresh-shape baseline, which we have never captured.
2. THE PICK PATTERN ITSELF: the picking face is the REVERSED-orientation plane (the bottom, back-facing to a from-above ray); the non-picking faces are the FORWARD ones, including the top plane facing the camera -- the easiest conceivable target. Picks succeeding on back-facing geometry and failing on front-facing is the signature of selection treating the solid as INSIDE-OUT -- pointing one level deeper than faces: SHELL orientation/closed flags mis-set by the save/reload round trip, flipping selection winding globally while rendering stays fine (two-sided shading) and the classifier stays consistent (topology-based, which is why the face-normal probe passed).

Shipped two artifacts for one round of testing:
- probe_pick_shape.py v2: adds per-SHELL flags (orientation/closed/orientable/face count), a FRESH BRepPrimAPI_MakeCylinder baseline dumped with the identical report in the same output (the missing comparison), and an in-probe CURE TRIAL: each reloaded part re-dumped after ShapeFix_Shape.
- docmodel.py: _heal_display_shape() -- ShapeFix_Shape applied to the DISPLAY shape only in parse_doc's SimpleShape branch. Document untouched; saved files stay exactly as authored. Prints '[heal] display shape normalized for <name>' per part. If shell flags are the mechanism, the app's picking is fixed by this in the same run that the probe documents the flag diff.

**Awaiting: probe v2 output (the reloaded-vs-fresh shell-flag diff and the post-ShapeFix state) and the picking verdict in the healed app.**

### Lesson for future development

**When a probe clears every property it measures and the symptom persists, mine the SYMPTOM'S OWN GEOMETRY for the next hypothesis** -- 'the back-facing plane picks, the front-facing one doesn't' was sitting in the combination of Doug's reports and the probe's orientation flags, and it points at inverted selection winding more specifically than any further property enumeration would. The probe's face-level cleanliness plus the inverted pick acceptance together imply the defect lives at the one level between them: the shell.

## Session 60 (cont'd): shape FULLY exonerated by baseline comparison -- measuring the selection layer directly

Probe v2 verdict: the reloaded cans are INDISTINGUISHABLE from a fresh BRepPrimAPI_MakeCylinder in every measured property -- solid flags (closed=False on the fresh baseline too: that flag was normal all along), shell flags (FORWARD/closed=True/orientable, both), face orientations (one REVERSED plane each -- any correct cylinder has one), tolerances, meshability. ShapeFix_Shape changed nothing (nothing to fix), and the in-app display-only heal changed nothing (reverted -- fewer variables). Doug's from-below test also killed the inside-out/backface theory: from below the bottom face is FRONT-facing and still the only pick surface.

Sharpened symptom statement (geometric note: the two disks are coaxial and equal, so ANY ray through the top disk also crosses the bottom one -- 'must go through the bottom' from both directions actually means): DISK-CROSSING RAYS PICK; WALL-ONLY RAYS DON'T. The planar faces are sensitive; the cylindrical face contributes nothing. Reloaded parts only; fresh parts fully sensitive; both kinds processed by the identical draw pipeline in the same session with different outcomes.

With the shape exonerated, the divergence must live in the SELECTION DATA the AIS layer builds -- the one thing this entire investigation has inferred about endlessly and never measured. Added _dump_selection_entities: after each Display, dump the AIS object's mode-0 sensitive entities (class, NbSubElements -- a SensitiveTriangulation reports its triangle count -- and each entity's own bounding box). Test protocol: load the 2-can session, then CREATE one fresh can in the same session (its redraw dumps its entities alongside the reloaded ones) -- one paste gives the reloaded-vs-fresh selection diff.

### Lesson for future development

**A baseline comparison can exonerate an entire suspect class in one output** -- every property theory (orientation, shell flags, closedness, tolerance, meshability) died simultaneously the moment a fresh reference was dumped with the identical report, something worth doing FIRST next time a 'what's different about this object' question arises. And measure the layer where the behavior lives: five rounds inferred what the selection data 'should' contain from what StdSelect 'should' do; dumping the sensitive entities themselves was always available and is only now being done.

## Session 60 (SOLVED): the save/reload pick bug -- OCCT's analytic cylinder selection vs the STEP reader's reversed parametrization

THE SMOKING GUN, measured: reloaded can cylinder surface: placement=(-21.5,96.0,24.0) axis=(0,0,-1) V=[-15.0,0.0] -- the STEP reader reconstructs cylinders with a REVERSED axis and NEGATIVE V-range (legal, geometrically identical: origin at the base, V=-15 maps to the top). A fresh MakePrism cylinder is canonical (axis up, V=[0,h]).

THE DISEASE: OCCT 7.7+ builds ANALYTIC selection for cylindrical faces -- Select3D_SensitiveCylinder constructed from the surface's placement + V-range, IGNORING triangulation (why every mesh-based fix bounced off). Fed the reversed convention, it builds the sensitive extending from the origin along the axis: from z=24 DOWN to z=9 -- an invisible pickable wall displaced exactly one height BELOW the visible can (z 24..39). Every observation of the saga follows: through-the-bottom rays crossed the phantom; wall rays at real height missed; DOWN rays always worked (disks are planar -- planes never take the analytic path); fresh parts immune (canonical parametrization); vendor flat-plate parts never showed it; deep-copy didn't help (copies preserve parametrization); ShapeFix found nothing wrong (nothing IS wrong -- the parametrization is legal); and the mid-saga 'selection volume displaced downward' hypothesis was LITERALLY CORRECT, killed at the time only because the census measured geometry bboxes rather than sensitive placement.

THE FIX (production, in draw_shape): display-only BRepBuilderAPI_NurbsConvert -- surfaces become BSplines, no longer RECOGNIZED as cylinders, so the analytic path is ineligible and selection falls back to triangulation (healthy all along; ensured by IncrementalMesh). Document and saved files untouched. Verified by ray census (side->HIT for reloaded cans) AND by Doug's hover test: both previously-broken cans now highlight everywhere. Cosmetic side effect, explained: highlight wireframes show patch-seam edges (circles split into quadrants, cylinder surfaces into patches) -- the conversion's fingerprint.

This also resolves the lathe 'button' (Session 60 earlier, closed-unresolved): same mechanism -- it was simply the lathe's only curved-face-dominated part. The CAD Assistant highlights-parent-assembly observation there remains a separate curiosity, unresolved and archived.

FOLLOW-UPS (parked): (1) selective conversion -- only convert faces with non-canonical cylinder/cone parametrization, sparing canonical parts the seam cosmetics; (2) THIS IS AN UPSTREAM OCCT BUG worth reporting: Select3D_SensitiveCylinder mishandles reversed-axis/negative-V cylinders as produced by OCCT's OWN STEP reader -- minimal repro is trivial (write any extruded cylinder to STEP, reload, analytic pick displaced), and Doug already has rapport on the OCCT tracker from #1395. All diagnostics removed; probe_pick_shape.py kept in tests/ as the investigation's instrument.

### Lesson for future development

**The elimination chain was the method: shape properties, mesh, shell flags, deep copy -- each negative narrowed the space until only parametrization remained, and the direct selector-ray measurement was what made the negatives trustworthy.** Two meta-lessons stand out: (1) a hypothesis 'killed' by a measurement is only as dead as the measurement is relevant -- the displaced-selection theory was right, but the census measured geometry bounding boxes when the displacement lived in the SENSITIVE entities; (2) when an optimization layer (analytic selection) silently replaces the data path you're reasoning about (triangulation), no amount of fixing the bypassed path helps -- 'why does the fix not fire' is sometimes the question that identifies the layer that actually decides.

## Session 61: project milestone recorded; Tier-3 sketch architecture designed; undo/redo gauge built

**Milestone, in Doug's words (worth a date on the record):** Kodacad is now a working 90% solution for its original purpose -- find STEP models of things to use in a project, import them, position them, and build simple plates and brackets to hold everything together. Priorities going forward are being chosen deliberately rather than chasing every shiny pebble.

**Tier-3 sketching architecture** designed and documented in docs/SKETCH_ENGINE_DESIGN.md (foundational to every Tier-3 item, per Doug). One-paragraph summary: the current approach asks OCCT selection to understand sketch snap semantics (hence pre-built intersection AIS points); the Pyurcad-proven inversion is an APP-SIDE snap engine in workplane UV space, fed by a single bridge function -- screen_to_uv on every mouse move (ConvertWithProj ray -> gp_Pln intersection -> ElSLib.Parameters). Snap candidates (endpoints, midpoints, centers, ON-THE-FLY intersections, on-curve) ranked by pixel distance (view.Convert for zoom-constant catch radius), modifier keys as re-rankers (Ctrl+Shift centers-only = one line). Dissolves as side effects: arc-over-ccircle deletion, center-snap override, uniform snaps across tools -- and removes the most interaction-intensive feature from dependence on the OCCT selection layer Session 60 just proved surprising. Incremental path starts with a zero-risk hover-only snap marker.

**Undo/redo, Doug's chosen next target -- gauge status:** Session 49's smoke test already confirmed OCAF NewCommand/CommitCommand/Undo/Redo works on real document operations; the open question deciding easy-vs-hard is coverage of KODACAD'S full operation vocabulary. Built smoke_test_undo_redo_full.py: drives the REAL DocModel methods headlessly -- add_component, change_label_name, create_new_assembly, create_shared_instance, set_component_location (the Remove+UpdateAssemblies+Add cycle), add_component_from_label (the memo rebuild-import), delete_component (recursive orphan cleanup) -- each wrapped in a transaction, Undo verified against a pre-op canonical structure snapshot and Redo against the post-op one, with per-case PASS/FAIL and diff dumps on mismatch. All-pass verdict = integration is mechanical (transaction-wrap ops in the app, Ctrl+Z/Ctrl+Y, refresh after Undo/Redo, settle the Position-dialog Back-button design question). Any failure names exactly which operation needs special handling. SetUndoLimit(50) noted as the required enablement step.

**Not yet run.**

## Session 61 (cont'd): the gauge's first finding arrived before it measured anything -- parse_doc crashed on an empty document

First run of smoke_test_undo_redo_full.py crashed inside parse_doc: case 1's transaction included creating the '/' root (the test doc started empty), Undo correctly emptied the document, and parse_doc hit labels.Value(1) on a zero-length sequence (Standard_OutOfRange). A genuine latent app bug, not a test artifact: undo integration WILL produce empty documents (undoing the first content of a fresh session), and the parse layer crashed rather than representing that state.

Fixes:
- docmodel.parse_doc: empty-document guard -- zero shapes means empty dicts ARE the correct parse; return cleanly after the dict resets.
- Gauge hygiene: the test now seeds the '/' root and a baseline part OUTSIDE any transaction (not recorded in undo history), so each case's Undo returns to a stable non-empty baseline and the gauge measures per-operation semantics against a realistic session rather than the empty-doc edge.

**Gauge still awaiting its first full run.**

### Lesson for future development

**A readiness gauge earns its keep on integration EDGES, not just the feature core** -- the very first thing it found was not an OCAF semantics problem but the app's inability to represent the state undo produces. These edge states (empty document, post-undo uid churn, refresh-after-restore) are where 'mechanical integration' hides its surprises, and driving the real methods rather than synthetic ops is what surfaces them early.

## Session 61 (gauge GREEN): 7/7 -- OCAF undo/redo handles Kodacad's full operation vocabulary

Doug ran the full gauge: ALL SEVEN CASES PASS. add_component, change_label_name, create_new_assembly, create_shared_instance, set_component_location (the Remove+UpdateAssemblies+Add cycle), add_component_from_label (the memo rebuild-import -- many labels, colors, sharing), and delete_component (recursive orphan cleanup) -- every one restored exactly on Undo (structure snapshot match) and re-applied exactly on Redo. The 'likelihood of easy success' question has a measured answer: HIGH. (The Standard_NullObject terminate at the very end was exit-time GC destroying the two OCAF documents in an order OCCT dislikes -- after all results printed; cosmetic, test-script-only; fixed with explicit doc Close + os._exit.)

**The integration plan this greenlights (mechanical items):**
1. dm.doc.SetUndoLimit(N) at startup AND after every load_stp_at_top (session load replaces the doc object; the fresh doc needs the limit re-set, and undo history naturally clearing on session load is correct semantics anyway).
2. Transaction-wrap every mutating call site (extrude/mill part creation, delete, rename, reposition, create assembly, shared instance, import, reparent, color ops): NewCommand before, CommitCommand after, AbortCommand on exception.
3. Edit menu Undo/Redo + Ctrl+Z/Ctrl+Y -> doc.Undo()/Redo() guarded by GetAvailableUndos/Redos, then the full refresh: parse_doc + ais_shape_dict.clear + build_tree + redraw.
4. Post-undo state hygiene: cached uids (activePartUID, dialog-held uids) can dangle after undo -- clear/re-resolve active-part state on every undo/redo.
5. Known scope boundary: workplanes and 2D sketch state live OUTSIDE the OCAF document -- undo will not restore them (worth a status-line note in the UI; the future sketch engine could revisit).

**The one real design decision, awaiting Doug (Position dialog Back button vs document undo):**
(a) UNIFY: each Position move commits its own transaction; Back literally calls doc.Undo(). Elegant, one mechanism -- but every nudge becomes a history entry (Ctrl+Z after positioning walks back through 15 nudges).
(b) COMMIT-AT-DONE: the whole Position session is one transaction committed when Done is pressed; Back keeps its existing internal _history stepping within the open transaction. History stays readable ('one entry = one completed positioning'), Ctrl+Z undoes the whole placement as a unit. RECOMMENDED.
(c) Hybrid variants possible later.

### Lesson for future development

**A gauge that drives the real methods converts a scary-sounding feature into a costed checklist** -- 'undo/redo' sat in Tier 4 as a grandiose item for weeks; one afternoon of headless testing reduced it to five mechanical integration steps plus one genuine design question, with the riskiest operations (rebuild-import, orphan-cascade delete) certified BEFORE any app code changes. The remaining risk now lives where it belongs: in UI state hygiene, not in OCAF semantics.

## Session 61 (cont'd): undo/redo design decision recorded; pick-fix performance regression fixed

**Undo/redo design decision (Doug):** option (b) -- the whole Position-dialog session is ONE transaction committed at Done; the Back button keeps its existing fine-grained internal _history stepping within the open transaction. Undo history reads one-entry-per-completed-placement; Ctrl+Z undoes a placement as a unit. Integration can proceed on this basis.

**Performance regression, owned and fixed:** Doug reported visibly slower lathe display after the Session 60 pick fix. Cause (in mainwindow draw_shape, not docmodel): NurbsConvert ran on EVERY part on EVERY redraw, and because the converted shape was rebuilt each redraw, its mesh was discarded and recomputed every time -- remeshing BSpline surfaces is far costlier than meshing analytic ones. Fix, two parts:
1. SELECTIVE: _needs_analytic_workaround(shape) triggers conversion only on the measured pathology (cylinder/cone face with NEGATIVE V-range -- the STEP reader's reversed-axis signature). Fresh/canonical parts skip conversion entirely -- faster, and their clean highlight wireframes return (no patch-seam quadrants). Broadening point documented if a pick regression ever reappears on a skipped part.
2. CACHED: _display_prep_cache = {uid: (src_shape, prepared_shape)}, keyed by source-shape identity (IsSame) -- redraws reuse the prepared shape; a changed/moved part self-invalidates and re-prepares alone; stale entries pruned against part_dict each redraw.

**Awaiting Doug's confirmation: lathe display speed restored, and the regression check (curved part -> save -> reload -> hover edge-on) still passes.**

### Lesson for future development

**A correctness fix applied unconditionally in a per-frame path is a performance bug wearing a hero's cape** -- the conversion was right, but running it for every part on every redraw (and discarding the mesh with each rebuilt copy) taxed exactly the sessions that need it least. Selectivity keyed to the MEASURED pathology plus an identity-keyed cache puts the cost where the disease is, and only once.

## Session 61 (cont'd): perf round 2 -- area-fraction criterion replaces any-pathological-face

Doug diagnosed the residual slowness himself, correctly: EVERY vendor lathe part has cylindrical faces (holes), and holes carry the same reader negative-V signature -- so 'any pathological face' converted the entire lathe, taxing parts whose picking was never in question. The insight formalized: a hole's pickability is irrelevant (nobody picks a part by its holes -- the planes carry the picking); the pathology only MATTERS when pathological curved faces DOMINATE the pickable surface.

New criterion in _needs_analytic_workaround: convert iff pathological-face area / total surface area > 0.30 (BRepGProp per face -- far cheaper than the conversion it gates). Expected: cans ~75% -> convert; channel plate/bearing blocks (holes ~5-15%) -> exempt, fast, clean wireframes; leadscrew/rods ~90% -> convert, CORRECTLY (a rod is exactly a can-shaped pick case whose edge-on defect simply went unnoticed). Tradeoff documented at the function: a mostly-planar part could in principle carry a degraded sub-threshold cylinder someone picks from a hostile angle -- broadening knob is the threshold (or revert to any-pathology).

**Awaiting: load-speed verdict, plus the standing regression check (curved part -> save -> reload -> hover edge-on).**

### Lesson for future development

**The user's operational knowledge is a profiling tool** -- 'picking them never posed a challenge' encoded the real criterion better than the code's first heuristic did: the defect's SEVERITY is proportional to how much of the pickable surface it owns, not to its mere presence. Gating an expensive workaround on where the disease MATTERS (area fraction) rather than where it EXISTS (any face) is the difference between a fix and a tax.

## Session 61 (cont'd): UNDO/REDO IMPLEMENTED -- Edit menu, Ctrl+Z/Y, transactions everywhere, option (b) in the Position dialog

Doug pulled the trigger (perf confirmed restored; save/reload regression check passing). Implemented per the gauge-certified plan:

- **docmodel**: UNDO_LIMIT=50; SetUndoLimit in DocModel.__init__ AND after load_stp_at_top's doc replacement (history clears on session load -- correct semantics). New undo_transaction(dm) contextmanager: opens/commits/aborts one OCAF command per user gesture, and JOINS an already-open command instead of nesting -- the mechanism that lets option (b) work.
- **kodacad**: 'Edit' menu (after File) with Undo (Ctrl+Z) / Redo (Ctrl+Y); all 8 mutating call sites wrapped (extrude x2, modify/replace_shape x5, import x1).
- **mainwindow**: QShortcuts; editUndo/editRedo guarded by GetAvailableUndos/Redos; _refresh_after_history does the full reset (clear activePartUID/activePart/activeAsyUID/itemClicked -- cached uids can dangle after undo -- then parse_doc + ais_shape_dict.clear + build_tree + redraw, status line with remaining undo/redo counts; draw-prep cache self-invalidates by shape identity, no clearing needed). Five RMB/drag handlers wrapped (reparent, delete, create assembly, shared instance, rename) -- the if-condition sites restructured to 'with txn: result = op()' / 'if result:'.
- **position_dialog (option (b), Doug's decision)**: the whole session is ONE transaction -- opened at __init__ (guarded by HasOpenCommand), committed at Done AND at closeEvent (closing via X preserves what the user sees; an empty command commits to nothing). The Back button's fine-grained _history stepping is unchanged, operating WITHIN the open transaction; the dialog's set_component_location calls pass through undo_transaction's join path harmlessly.
- Scope boundary logged + checklist: workplanes/2D state live outside the OCAF doc, not restored by undo.
- TESTING_CHECKLIST gained the full undo/redo section (per-op round trips, the one-Ctrl+Z-per-placement check, empty-doc undo, fresh-history-after-load).

**Awaiting Doug's in-app test pass.**

### Lesson for future development

**The join-instead-of-nest contextmanager is what made option (b) cheap** -- one HasOpenCommand check lets the dialog own a session-wide transaction while every inner operation stays wrapped identically to its standalone use, no special-casing at any call site. Transaction scope became a property of who opens first, not of call-site knowledge.

## Session 61 (cont'd): version 1.2.0

Doug confirmed undo/redo working in-app (deletes of parts and assemblies, a part move -- all round-tripping; fuller test pass planned). Version bumped 1.1.0 -> 1.2.0 per semver discipline: substantial new capability, no compatibility break (session files remain plain STEP). The 2.0.0 milestone number is deliberately held in reserve -- the sketch engine landing would be a worthy occasion. version.py documents the 1.1.x -> 1.2.0 span; the STEP header's originating_system now carries the version ('KodaCAD 1.2.0'), so saved files self-identify their authoring version -- useful forensics given how much this project has learned from interrogating its own output files.

## Session 61 (cont'd): two test-pass findings fixed -- Ctrl+Y binding, rename-to-product propagation

Doug's thorough undo/redo test pass surfaced two minor issues, both fixed:

1. **Ctrl+Y dead**: QKeySequence.StandardKey.Redo maps to Ctrl+Shift+Z on Linux (which worked all along) -- the Edit menu advertised Ctrl+Y. Both are now bound explicitly.

2. **Rename didn't reach CAD Assistant/FreeCAD** (renamed 'button'->'can', saved under a new name, CA/FC still showed 'button'): the Session 57 naming asymmetry from the rename direction -- change_label_name renamed only the OCCURRENCE (what Kodacad displays); the PRODUCT (what CA/FC display) kept the old name. Now a rename of a part with a referred product names BOTH per the add_component convention: product = base name (typed name stripped of trailing _N), occurrence = typed name or base_1 when they'd collide (identical names trigger the Session 17 NAUO blanking -- the suffix exists exactly for this). Typing 'can': product 'can' (CA/FC), tree 'can_1' (consistent with every other entry). Shared products: siblings keep their old occurrence names -- only the part's identity and THIS occurrence change. Bonus consistency: renaming the top assembly now names its product properly too, and the Session 57 export unwrap sees the suffixed occurrence as auto-pattern and correctly exports the base name.

### Lesson for future development

**Every naming operation must answer for BOTH name populations** -- occurrence (Kodacad's display) and product (the rest of the world's display). Session 57 fixed creation; the rename path had the same single-population blind spot and waited for a user test to reveal it. The checklist now demands the cross-viewer check for rename explicitly, and any future operation that touches names (reparent already does, import does) should be audited against the two-population rule rather than trusted.

## Session 62: SKETCH ENGINE STEP 1 -- the UV bridge and the hover-only snap marker

The design (docs/SKETCH_ENGINE_DESIGN.md) begins per its own incremental path: zero behavioral change, pure observation. New module snap_engine.py:

- **screen_to_uv(view, x, y, gp_pln)** -- THE bridge: ConvertWithProj cursor ray -> gp_Pln intersection (one line of algebra, guarded for parallel rays) -> ElSLib.Parameters -> (u, v). With this, the viewport supplies continuous cursor position in workplane coordinates, exactly as Pyurcad's tkinter canvas did -- the realization the whole design rests on.
- **find_snap(wp, uv, tol)** -- app-side candidate search calling workplane.py's OWN Pyurcad-lineage math (intersection, line_circ_inters, circ_circ_inters, proj_pt_on_line -- the recon's happy discovery: the 2D brain was already in this codebase). Step-1 categories: cline/ccirc pairwise intersections computed ON THE FLY (the pre-built intersection-point paradigm's replacement), ccirc centers, wp origin, on-curve (lower priority). Ranking: (priority, distance), tolerance = view.Convert(12 px) -> zoom-constant catch radius. Every pair guarded so one degenerate entity can't kill the sweep.
- **SnapHover** -- a non-selectable AIS_Point glyph (Deactivate after Display: it can never steal a pick) at the current best snap; redisplayed only when the snap RESULT changes (no per-move churn); hides with no active wp or no catch; any error disables it with one printed line rather than ever breaking the viewport.
- **koda_viewport**: setMouseTracking(True) (Qt only delivers buttonless moves with tracking on), register_move_callback, and a hover branch in mouseMoveEvent that fires ONLY when event.buttons() is empty -- drags, orbits, and the manipulator path are untouched.
- **kodacad**: installed right after highlight sync.

**Doug's test**: create/activate a workplane, draw a few clines and a ccircle, then just HOVER: a yellow '+' should appear when the cursor comes within ~12 px of any construction intersection, circle center, the wp origin, or (when nothing sharper is near) the nearest point ON a cline/ccircle -- at any zoom level, with the 3D model visible behind. No tool behavior has changed anywhere.

### Lesson for future development

**When a design names its foundation ('the missing bridge is one function'), build exactly that first and make it observable** -- the hover marker is scaffolding-as-feature: it validates the bridge, the candidate math, and the tolerance model in one glance-able artifact before any tool depends on them, and its cost was almost entirely reuse -- the recon found the entire Pyurcad math library already living in workplane.py, waiting for the coordinate bridge the design predicted it needed.

## Session 62 (cont'd): step 1 validated by feel; step 2 -- arc3p reordered to endpoints-first with a live rubber-band preview

Doug's verdict on the hover marker: catch radius feels reasonable -- the bridge, the candidate math, and the pixel-tolerance model are validated by the only test that matters for an input feature.

**Step 2, chosen by Doug's request: the 3-point arc.** Old order was end / ON-ARC / end (the middle pick was the through-point). New order is the Pyurcad one Doug prefers -- BOTH endpoints first, then a point on the arc between -- and his stated reason ('this lets the rubber band work well') is now honored directly, because step 1's infrastructure makes the preview nearly free: after the first pick a rubber LINE follows the cursor; after the second, the ARC ITSELF follows, with the cursor as the live third point (screen_to_uv each move -> GC_MakeArcOfCircle(e1, cursor, e2) -> preview edge). Implementation notes: preview is a non-selectable AIS_Shape (Deactivate -- can never steal a pick), orange, updated via SetShape/Redisplay; degenerate/collinear cursor positions keep the last valid preview rather than flickering; the preview SELF-CLEANS -- if the operation ends any way at all (End Operation, tool switch), the first stray move notices registeredCallback changed, erases, and unregisters. koda_viewport gained unregister_move_callback for tool-scoped callbacks. Pick precision itself still rides the existing vertex-pick mechanism until step 3 migrates input to find_snap; the preview tracks the raw cursor.

**Reference material banked**: Doug provided a Creo Elements/Direct screenshot of a CoCreate workplane -- translucent pane with 'w1' written at its lower-left corner. That is the visual spec for the Tier-2 workplane clump (viewport labels via AIS_TextLabel, translucency, corner placement) when that work begins.

### Lesson for future development

**The first tool migrated onto new infrastructure should be one the user just complained about** -- the arc reorder was wanted on its own merits, and delivering it WITH the live preview demonstrates the bridge's value on day one rather than asking anyone to take the architecture's benefits on faith. 'This lets the rubber band work well' was a design requirement stated as a preference; step 1 existing made honoring it a footnote instead of a project.

## Session 62 (cont'd): arc3p confirmed by Doug; two UX refinements from his notes

Doug confirmed the reordered arc + rubber band works exactly as intended. Two refinements he suggested in passing, both implemented immediately since they were adjacent and small: (1) per-pick acknowledgement in the status bar ('End point 1 set. Pick the second end point.' / 'End point 2 set. Pick a point on the arc.') -- reassuring for the first-time user; (2) seamless restart -- the operation was already staying registered after completion, so the missing pieces were just restarting the preview and re-prompting ('Arc created. Pick 2 end points for the next arc (or End Operation).'). Continuous arc creation now flows without re-invoking the tool; End Operation exits as before, and the preview's self-clean handles that path.

## Session 62 (cont'd): STEP 3 -- clicks migrate to engine input; the arc is the first customer

The path-forward milestone, per Doug's directive (mechanism to the goal first, tool-by-tool flush-out after). The essence in one sentence: clicks stop asking OCCT 'what vertex did I hit?' and start asking the engine 'where does this land?' -- which makes the hover marker the literal input preview: the click lands EXACTLY where the marker shows, snapped when within the catch radius, free (raw UV) otherwise, INCLUDING on empty plane space with no pre-built vertex anywhere near.

Mechanism:
- koda_viewport._on_click now carries the click's pixel coords as a THIRD callback arg (contract: shape_list, ais_obj, click_xy). 3D operation callbacks and highlight sync absorb it via *args untouched; both the picked and empty-click branches pass it (empty clicks MUST reach 2D tools now -- that's the point).
- m2d.add_snap_pt_to_xyPtStack(args): pixel coords -> screen_to_uv -> find_snap with the SAME tolerance the hover marker uses -> push snapped-or-raw UV. Returns False (no coords / no wp / bridge failure) so callers can fall back to the legacy vertex path -- migration is per-tool and reversible.
- arc3pC is the first customer: engine input primary, legacy vertex path as fallback. Typed-coordinate entry (lineEdit) unchanged.

Deliberately NOT yet done (the flush-out pass): migrating line/circle/cline collectors (same one-line pattern as arc3pC), retiring the pre-built intersection-point display (step 4 -- only after nothing depends on it), and dropping SetSelectionModeVertex from migrated tools.

**Doug's step-3 test**: start an arc; hover until the marker catches an intersection; CLICK -- the endpoint lands on the snap. Then click somewhere on EMPTY plane space -- the point lands at the raw cursor position (impossible before: clicks needed a vertex). Chain a few arcs. The marker-then-click agreement is the thing to feel.

### Lesson for future development

**Adding a data channel to an existing callback contract beats adding a parallel callback system** -- the click coords ride as one more *args element that every existing consumer already ignores by construction, so the 3D operation flow, highlight sync, and the legacy vertex path all continue byte-identical while the new input path switches on per-tool with a one-line change and a built-in fallback.

## Session 62 (cont'd): Doug's design principle -- NO CATCH, NO POINT

Doug, on testing step 3: free-space clicking works but he will NEVER use it -- construction lines are the embodiment of a drafter's layout drawing (#6 hard-lead layout, dark lines drawn at the layout's intersections). Elevated from preference to principle and encoded in both the engine and the design doc: a click lands only where the engine catches; a no-catch click is REJECTED with a status hint ('No catch -- move to a construction feature...') rather than placing a raw-cursor point -- because a near-miss silently placing a slightly-wrong point is the exact imprecision the layout method exists to prevent. The hover marker is thereby the permission indicator: no marker, no input. Return-value semantics refined (True = engine had jurisdiction, point pushed OR deliberately rejected; False = engine couldn't operate, legacy fallback). Per-pick acknowledgement now fires only when a point was actually added, so a rejected click's hint isn't overwritten. Design doc gained a binding 'Input philosophy' section for every tool in the flush-out pass; numeric lineEdit entry remains the other first-class path (how the first clines bootstrap, along with origin/axis snaps).

### Lesson for future development

**When the user explains WHY with a metaphor from their craft, they are handing over a design principle, not feedback on a feature** -- the #6-pencil layout method defines what input IS in this application, and encoding it as the engine's default (catch-only, opt-in for anything freer) means every future tool inherits the philosophy instead of re-litigating it.

## Session 62 (cont'd): the two-class click taxonomy -- point input vs gesture input

Doug's parallel-cline example (a free click choosing which SIDE the new line goes) refined the input philosophy rather than reversing it: there are TWO classes of clicks. POINT INPUT defines coordinates that become geometry -- catch-only governs, no catch no point (add_snap_pt_to_xyPtStack). GESTURE INPUT chooses among discrete alternatives (side, direction, which-of-two-intersections) -- the click means 'this half-plane', not 'this exact spot'; precision is irrelevant by construction, so a free raw-UV click is the natural interface (new helper gesture_uv_from_args: raw UV, no snap, no rejection). The design doc now requires every tool in the flush-out pass to declare which class each of its clicks belongs to; there is no third class. The parallel-cline tool, when migrated, is the first gesture customer.

### Lesson for future development

**A counterexample to a fresh principle is usually a missing DISTINCTION, not a refutation** -- 'no catch, no point' survived Doug's example intact once the taxonomy separated clicks-that-define-coordinates from clicks-that-choose-alternatives; both the principle and the exception got crisper, and the flush-out pass inherits a question to answer per click ('which class is this?') instead of a rule to bend.

## Session 62 (cont'd): the Pyurcad catch square, and geometry lines join the candidate pool

Two upgrades from Doug's request, one rewrite of snap_engine.py:

1. **The catch indicator is now Pyurcad's little SQUARE** -- a wire outline drawn ON the workplane at the catch point, half-side sized in pixels (view.Convert) so it stays constant at any zoom, orange, deliberately unlike the legacy pre-built yellow-'+'-turning-blue markers it supersedes. Same non-selectable, rebuild-only-on-change discipline as before.

2. **Geometry lines participate in catching** ('intersections of either construction or geometry lines'): the workplane's linear edges are extracted to UV segments each sweep (BRepAdaptor line check -> endpoints -> ElSLib.Parameters), contributing endpoint candidates, geom x geom and geom x cline intersections (with proper on-segment bounds checks via parametric projection), and on-segment nearest points. ARCS in geometry are deferred -- arc x line and arc x arc intersection candidates are a bounded follow-up (workplane.py already has line_circ_inters/circ_circ_inters; the missing piece is arc angular-range checks).

Note toward step 4: with the square now carrying the catch-feedback role, the legacy pre-built intersection-point markers have lost their last unique purpose for MIGRATED tools -- their retirement awaits only the remaining collectors' migration (line/circle/cline, the established one-line pattern).

### Lesson for future development

**When replacing a feedback mechanism, make the replacement visually unconfusable with what it replaces** -- the first marker was a yellow '+', near-identical to the legacy markers, which would have made it impossible for Doug to tell WHICH system was talking to him during the transition. The orange square is unambiguous: square = the engine speaks.

## Session 62 (cont'd): STEP 4 -- goodbye, little yellow '+' signs

Doug's words on the catch square: 'I LOVE it! I am ready to say Good bye to those little yellow + signs.' Granted, in full:

- **All 11 remaining 2D collectors migrated** to engine-first input (line, circle, rectangle, the cline family, arcc2p, ...) via the established pattern -- one exact-line replacement each, verified by AST that every migrated collector carries *args. (The first attempt's substring replace would have mangled arc3pC's already-migrated deeper-indented fallback; the assert caught it, line-exact processing fixed it -- the probe-first discipline applied to one's own edits.)
- **The pre-built intersection-point display RETIRED** from draw_wp: wp.intersectPts() is no longer displayed as vertex-selectable markers. The snap engine computes intersections on the fly; the orange catch square carries all feedback. wp.intersectPts() itself remains in workplane.py, undisplayed.
- The legacy vertex path survives only as each collector's fallback -- now fed by nothing, exercised only if the engine cannot operate. SetSelectionModeVertex calls remain in tool entry points, harmless (nothing vertex-selectable exists on a wp anymore); removable in a cosmetic pass.

The design doc's four-step incremental path is hereby COMPLETE: bridge -> hover marker -> engine input (both click classes) -> old paradigm retired. Every 2D tool now sketches the Pyurcad way: layout with construction, catch square as the permission indicator, clicks land only on catches, geometry participates in the layout.

**Doug's checkout pass (the flush-out he planned)**: every 2D tool -- lines, circles, rectangle, each cline flavor, both arcs -- against the catch square: draw, chain, snap to cline/geometry intersections, endpoints, centers, origin, on-curve; confirm typed lineEdit input still works everywhere; confirm no stray '+' markers appear on any wp redraw.

### Lesson for future development

**Retiring an old paradigm is safe exactly when its replacement already carries every role the old one had** -- markers had two jobs (feedback and pickable input); the square took feedback in the previous session and engine input took clicking in this one, so the retirement commit deletes a display block and changes nothing else. Migration order was the whole safety argument.

## Session 62 (cont'd): rubber bands for everyone -- the preview mechanism generalized

Doug: 'It's beautiful! ... Can we get rectangles to have rubber lines?' Rather than clone the arc's preview a third time, the mechanism was generalized: _preview_start(owner_cb, builder) / _preview_move / _preview_stop -- one self-cleaning machine, per-tool builder functions of a few lines each (builder(wp, uv) -> preview shape or None-to-hold). Wired into ALL FOUR point-sequence tools:
- arc (ported from its dedicated code -- one mechanism now, tested across all tools),
- line (rubber line from first end point),
- RECT (Doug's request -- live rectangle from first corner to cursor; degenerate zero-width/height held rather than flickered),
- circle (live circle centered on the first pick, radius to cursor; both completion routes -- second point AND typed radius -- restart the preview for seamless chaining).
All previews: orange, non-selectable, updated only when the builder yields, self-cleaning when the operation ends any way at all.

**Parking lot noted at Doug's request**: Pyurcad has additional tools not yet in Kodacad; SOME may come over SOMEDAY -- no commitment now. The migration cost per tool keeps falling as the engine matures (a new tool is: a collector on engine input + a builder + wp geometry op).

### Lesson for future development

**The second copy is the signal, the third request is the deadline** -- the arc's dedicated preview was fine as a first implementation; the moment a second tool wanted the same behavior, the mechanism belonged in one place with per-tool builders. Generalizing AT the second request cost less than the third clone would have, and every future tool's rubber band is now a ~15-line builder.

## Session 62 (cont'd): the Ctrl+Shift catch override -- and the default catch set tightened to intersections

Doug's original TODO item lands, timed exactly when the engine can express it in a few lines. His framing also tightened the DEFAULT: on-curve catching ('anywhere along the line shows it selectable') was step-1 scaffolding a drafter doesn't want -- dark lines are drawn between INTERSECTIONS.

Final catch policy (also written into the design doc):
- **Normal**: intersections (construction x construction, geometry x geometry, geometry x cline), geometry endpoints, origin. NO on-curve, NO centers.
- **Ctrl+Shift held**: EXCLUSIVELY centers of circles/arcs -- construction ccircs AND geometry circles (new _geom_circles_uv extraction) -- and MIDPOINTS of straight geometry edges. The CoCreate override verbatim from the TODO's own description.
- The catch square changes colour: orange = normal set, CYAN = center/midpoint set -- the flyby feedback tells you which catch set is live (the TODO's 'flyby highlighting changes dynamically' requirement).
- Mode read via QApplication.keyboardModifiers() at each move/click; hover marker keys its change-detection on (mode, snap) so pressing the modifier re-colours on the next move. Click input (add_snap_pt_to_xyPtStack) honors the same mode, so marker and click can never disagree. No-catch hint updated to teach the modifier.
- On-curve remains IN the engine (a future trim tool will want it) but no default input path offers it.

Known small limitation, logged: pressing/releasing Ctrl+Shift without moving the mouse updates the marker on the NEXT move (modifiers are sampled per move event); a keyboard-event refresh is a cosmetic follow-up if it ever matters in practice.

### Lesson for future development

**A feature request is also a chance to re-examine the defaults it touches** -- Doug asked for the Ctrl+Shift override and, in describing it, revealed that the default on-curve catch contradicted the drafter's model entirely. Scaffolding categories that made the engine demonstrable in step 1 are not automatically the right production policy; the user's workflow language ('only intersections') is the specification.

## Session 62 (cont'd): center mode goes ENTITY-ANCHORED; geometry goes bold black

Doug verified against both reference implementations (Creo E/D and Pyurcad) and refined three things:

1. **Center mode is ENTITY-ANCHORED, not proximity-based** -- the first implementation searched for centers/midpoints near the CURSOR, which meant aiming at the empty space where a circle's center is: backwards, since the center has no visible feature. The CoCreate way: point at the ENTITY (anywhere along it, within the catch radius of the CURVE -- rim distance for circles, segment distance for lines), and the square appears at ITS center/midpoint, possibly far from the cursor; click takes the glyph's location. find_snap's center branch rewritten accordingly (ranking by curve distance). Entity hover-highlighting itself was already in place (the 2D entities are live AIS objects) and is retained as the base feedback.
2. **The chord**: Pyurcad uses plain Shift; CoCreate uses Ctrl+Shift; Kodacad follows CoCreate, per Doug -- already implemented, now recorded as a decision.
3. **Geometry lines render BOLD BLACK** (width 3.0) instead of white -- Creo E/D style, which Doug judges will read better on Kodacad's canvas than Pyurcad's white-on-black translated. Construction stays dashed magenta; the visual hierarchy is now: faint dashed construction layout, bold black finished geometry -- literally the #6-pencil-then-dark-lines metaphor, rendered.

### Lesson for future development

**When a behavior imitates a reference application, verify against the reference before shipping the guess** -- the proximity-based center mode was a plausible reading of the TODO's description; Doug's ten minutes with Creo E/D and Pyurcad produced the correct semantics (entity-anchored) plus two bonus decisions (the chord, the line styling). For workflow features with a living reference, the reference IS the spec, and checking it is cheaper than iterating on approximations.

## Session 62 (cont'd): middle-click ends the operation -- muscle memory honored

Doug: both CoCreate and Pyurcad end an operation with a middle click, and it's in his muscle memory. Implemented: a middle CLICK (press-pos + drag-threshold test, the same discrimination the left button uses to separate click from orbit) fires an app-installed hook wired to win.clearCallback -- identical to pressing End Operation. Middle-DRAG panning via AIS_ViewController is untouched. Tool previews self-clean on the next move as designed (they watch registeredCallback), and a middle click with no operation active is a harmless status reset.

### Lesson for future development

**'It's in my muscle memory' is a requirement with a precise spec attached** -- decades of CoCreate use define exactly what the gesture must do, and honoring it costs a press-position test and one hook. Input conventions from a user's formative tool are the cheapest ergonomics wins available.

## Session 62 (MILESTONE): the first part from the new sketcher -- and the honest Tier-3 ledger

Doug's screenshot: a block extruded on the plate, sketched end-to-end with the new engine -- construction layout beneath, bold geometry, catch-driven input, rubber-banded, extruded, in the assembly. His words: 'a huge improvement in the main step in the process of creating a new part.' The design doc's destination picture, achieved.

**Honest audit in answer to 'am I missing anything?' -- the Tier-3 FOUNDATION is complete; Tier 3 itself is not:**

COMPLETE: the sketch engine (bridge, catch policy with Ctrl+Shift entity-anchored centers, engine input on all collectors, generic rubber-band previews on all four point-sequence tools, old intersection-point paradigm retired, middle-click end-op, bold-black geometry, input philosophy codified).

REMAINING in Tier 3, all cheaper now:
- Extrude cluster: two-wire (inner/outer) profiles; direction choice; negative values. Doug's Creo E/D 'Pull' screenshot BANKED AS THE SPEC: explicit Direction field (+w/-w) in the flow, Distance field, 'Operation: Automatic' (add/remove material auto-determined), Keep WP / Keep Profile options.
- Project part edges onto workplane (Doug's screenshot also shows the reference: wp-created-on-face with the face's edges projected -- doubles as reference for the workplane-creation-modes work).
- Parallel clines (gesture_uv_from_args is waiting; tool not built).
- Arc-over-ccircle DELETION -- honest correction: NOT yet dissolved. Point collectors migrated to engine input, but the DELETE tools still pick entities via OCCT selection where both remain selectable. The per-operation entity-class filter is still owed.
- Booleans; Move Face; scars/healing.

**Version question raised by Doug**: the sketch engine landing was this log's own stated criterion for 2.0.0 ('a new era'). Options presented: 2.0.0 now (the character of the app changed today -- sketching IS the new era, per the criterion), or 1.3.0 now with 2.0.0 reserved for the completed sketch-to-solid workflow (direction control + multi-wire + project-edges). Doug's call.

### Lesson for future development

**'Have we finished X?' deserves a ledger, not a cheer** -- the foundation's completion is real and version-worthy, and five features still sit in the tier it enables. Conflating the two would have cost the remaining items their visibility exactly when the re-triage Doug plans should weigh them against his 90% workflow (two-wire holes serve the plates-and-brackets use case directly; booleans may not).

## Session 62 (RELEASE): KodaCAD 2.0.0 -- the sketch engine era

Doug's call, his words as the release rationale: 'we have arrived at a foundation that, quite honestly, I didn't think was achievable. Now, a whole bunch of things can be tackled.' Version 2.0.0 per the criterion this log set when 1.2.0 shipped (the sketch engine landing = the new era). version.py carries the era summary; the STEP header and title bar carry the number automatically. A PAUSE follows, at Doug's instigation -- commit, use the tool, let priorities settle.

**Post-pause priorities, Doug's triage:**
1. **PROJECT-EDGES first** -- he needs it to place mounting holes in his plates (the 90% workflow speaking).
2. Two-wire extrude: LOW -- workaround exists (make the plate, add holes subsequently).
3. Direction choice: small, but Doug wants thinking time on dialog design and option count (the Creo Pull spec is banked).
4. Arc-over-ccircle delete filter: owed, small.

**Design requirement banked ahead of project-edges (Doug): construction SEGMENTS.** Projected edges must be finite c-SEGMENTS, not infinite c-lines -- infinite lines through every projected edge would flood the layout with clutter and combinatorial false catches far from the part; segments keep the layout local. Full data-model/engine implications recorded in SKETCH_ENGINE_DESIGN.md (csegs collection, endpoint/midpoint/intersection catches reusing the geometry-segment machinery, projected holes needing c-arcs -- decide at implementation).

### Lesson for future development

**The best design requirements arrive during pauses** -- Doug stated the cseg requirement while stepping back, BEFORE project-edges exists, which means the feature will be designed around the right data model instead of retrofitted onto the wrong one. A pause that produces one sentence like 'we will need c-line segments' has paid for itself.

## Session 63: PROJECT-EDGES -- csegs land, and mounting holes have a home

Doug's post-pause priority #1, built on the cseg design he banked before the pause. UI decision: TOOLBAR, not menubar -- projection tools are sketching INPUT operations used mid-flow, the same class as line/circle/cline (and CoCreate agrees: Project lives in its Draw group). Two buttons on the construction toolbar ('Project Face Edges', 'Project Edge'), wired to icons/proj_face.gif and icons/proj_edge.gif -- Doug supplies the icons; absent files show text-only buttons, fully functional.

The build, five files:
- **workplane.py**: csegs data model ([((u1,v1),(u2,v2))]) + wp.cseg(p1,p2), with the banked rationale in the comment (finite, or the layout floods with false catches).
- **mainwindow.py draw_wp**: csegs drawn dashed magenta like clines, finite extent.
- **snap_engine.py**: ONE structural line -- csegs join the same segment machinery as geometry lines, so endpoints (a projected face's CORNERS -- the mounting-hole landmarks), seg x seg / seg x cline intersections, and Ctrl+Shift midpoints all work for free. The reuse the design doc predicted.
- **m2d.py**: _project_edge_onto_wp (linear edge -> cseg via ElSLib.Parameters projection of endpoints; circular edge with axis parallel to the wp normal -> construction CIRCLE at the projected center -- THE mounting-hole case; perpendicular lines project to points and are skipped; oblique circles (ellipses) skipped with a count -- honest v1 scope); projectFaceEdges (face pick -> all its edges, deduplicated) and projectEdge (single edge), both chaining with per-pick status counts, middle-click ends.
- **kodacad.py**: the two toolbar actions.

**Doug's test**: activate a wp coincident with (or parallel to) a plate face, Project Face Edges, pick the plate's top face -- the outline arrives as dashed csegs and every hole as a dashed c-circle; corners and hole centers (Ctrl+Shift) catch; sketch the bracket against them. The workflow his triage named: 'show where the mounting holes in my plate will go.'

### Lesson for future development

**A data model designed one session before its feature costs one structural line at integration** -- csegs slid into the snap engine's existing segment machinery exactly as the banked design note predicted, because the note was written when the machinery was fresh in mind and the feature wasn't yet rushing anyone.

## Session 63 (cont'd): project-edges fixed -- the TopoDS_Edge downcast

Doug's instrumented run delivered a textbook diagnosis in one paste: the collector fired, the face arrived, and every edge raised BRepAdaptor_Curve's pybind signature error -- TopExp_Explorer.Current() returns generic TopoDS_Shape, and the constructor demands a downcast TopoDS_Edge. Fixed with TopoDS.Edge_s() in both paths (the face-edge explorer and the single-edge pick, where SelectedShape likewise returns TopoDS_Shape even in edge mode) -- the same idiom the codebase already uses for Face_s. Diagnostic chatter trimmed to one result line per pick; the raised-print stays as a permanent tripwire (silent unless something actually fails -- the guarded-silence lesson from this very bug).

### Lesson for future development

**A guarded except that swallows silently converts a one-paste diagnosis into a mystery** -- the original helper caught this exact error and said nothing; the instrumented build's only real change was letting the exception SPEAK, and the fix was then obvious from the error text alone. Guards should be quiet on success and loud on failure, never quiet on failure.
