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
