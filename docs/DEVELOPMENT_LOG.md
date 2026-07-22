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

## Session 20: regression pass -- fillet crash, status bar terseness,
testing checklist

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

## Session 25: Session 24's fix crashed -- the real problem was one
level deeper

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

## Session 27: round-trip theory confirmed dead; testing cross-document
vs. same-document Extract_s instead

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

## Session 28 (cont'd): nesting confirmed as the trigger; re-clone
experiment removed

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

## Session 29: root cause fixed -- build assembly structure natively,
Extract_s only for leaves

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

## Session 30: wrap-up decision -- revert the native-rebuild dead end,
close out Position work for now

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

## Session 31: propagation restored -- Sessions 24/25 were fixing a
misdiagnosis, not a real bug

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

## Session 32: the actual gizmo-jump fix -- uid recovery preferred
whichever parent the tree walk visits first

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

## Session 36: standalone Align Axis -- Basicad's actual architecture,
for the case the PDF used it that way too

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

## Session 37: cylindrical surface misclassification -- the same bug
class as circular edges, one level up

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
