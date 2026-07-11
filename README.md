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
