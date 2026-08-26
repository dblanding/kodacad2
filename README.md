# KodaCAD 2.0

A 3D CAD application for Python, built on
[OCCT](https://www.opencascade.com/) via the
[OCP](https://github.com/CadQuery/OCP) Python bindings.

KodaCAD is designed for users who want to assemble, modify, and create
3D mechanical parts and assemblies using a scriptable, open-source
toolchain -- with no commercial dependencies and no Conda environment.

---

## What makes KodaCAD different

Most Python CAD libraries (build123d, CadQuery) represent assemblies as
**copies** of shapes organized in a Python object tree. This means
modifying one instance of a repeated part only affects that copy.

KodaCAD uses OCCT's **XDE document model** directly. In XDE, repeated
parts are stored once as a *prototype shape* and placed multiple times
as *instances* (references with location transforms). Modifying the
prototype automatically updates all placements -- exactly the behavior
you expect from professional CAD software like Creo or CoCreate.

**Example:** the `as1-oc-214.stp` test assembly has two L-bracket
assemblies, each containing the same L-bracket part. Applying a fillet
to one L-bracket updates both simultaneously, because they share the
same XDE root label.

---

## Who is it for

- Python programmers who want to work with real STEP assemblies
- Users coming from CoCreate / Creo who want familiar assembly workflow
- Developers who want to understand OCCT's XDE document architecture
- Anyone who needs to load, modify, and save STEP files with full
  assembly structure preserved

---

## Installation

KodaCAD uses [uv](https://github.com/astral-sh/uv) for dependency
management. No Conda required.

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repo
git clone https://github.com/dblanding/kodacad2
cd kodacad2

# Run directly -- uv handles all dependencies automatically
uv run kodacad.py
```

Dependencies (managed automatically by uv):
- `ocp` -- OCCT Python bindings (replaces PythonOCC)
- `pyside6` -- Qt6 Python bindings (replaces PyQt5)
- `build123d` -- used for geometry utilities

---

## How to use it

### Loading a STEP file

**File → Load Session**
Loads a previously saved KodaCAD session or any STEP file with assembly
structure. *Replaces the entire current document* -- whatever was open
before is gone. The loaded file's own content becomes the session, with
no wrapping or nesting involved.

**File → Import STEP**
*Adds* a STEP file as a new component under the current `/`, alongside
whatever's already open, ready to be positioned and dragged into an
assembly. This is the one operation that nests a file's content under
an existing root, so it's the one that needs to guard against a saved
session's own `/` wrapper getting nested under the current one --
which it does automatically (see below).

**File → Save Session**
Saves the current state to a STEP file. This is KodaCAD's native save
format -- STEP files can be reloaded exactly as saved, and opened in
any other CAD application.

**Why repeated save/load/import cycles stay clean:** Save strips any
redundant `/` wrapper before writing, so a saved file never contains
one to begin with. Load Session replaces the whole document rather
than nesting anything, so there's nothing for a wrapper to accumulate
into. Import STEP is the one path that adds content under an existing
root, so it explicitly unwraps any `/`-named root in the file being
imported before adding its children -- composing locations through any
already-nested legacy wrapper levels in one pass, so even an older
file saved before this existed unwraps completely on import.

**Note on the tree's own `/` label:** the tree view always shows a `/`
under the `3D` header, whether or not anything is loaded -- that's
just the tree's own organizing scaffolding, not part of any document.
The document's actual root assembly label is *also* named `/` by
convention (visible in the tree as its child), which is why a
freshly-built, never-saved session can show what looks like `/` nested
under `/` -- two different things that happen to share a name, not an
accumulation bug.

### Assembly tree

The tree on the left shows the assembly hierarchy:
```
WP              ← workplanes (2D construction geometry)
  wp1
3D
  /             ← root of 3D assembly
    as1         ← loaded assembly
      rod-assembly_1
      l-bracket-assembly_1
        ...
    button      ← newly created part (ready to drag)
```

- **Checkbox** — show/hide part or assembly. Parent checkbox
  propagates to all children.
- **Left-click** — select item
- **Right-click** — context menu: Item Info, Set Active, Rename,
  Create New Assembly, Create Shared Instance, Set Transparent,
  Set Opaque, Delete

### Creating a new part (Creo-style workflow)

1. **Workplane → On Face** — click a face in the viewport to place a
   workplane, then click a second face for the U direction
2. Draw a profile using the toolbar (H/V clines, circle, rectangle,
   line, arc)
3. **Create 3D → Extrude** — enter extrusion length and part name
4. The new part appears under `/` in the tree
5. **Drag** the new part onto the target assembly in the tree
6. Because KodaCAD uses shared instances, the part appears in ALL
   instances of the target assembly simultaneously

### Modifying parts

**Modify Active Part → Fillet**
1. Right-click part in tree → Set Active
2. Modify Active Part → Fillet
3. Click edges in the viewport
4. Enter radius, press Enter

Because KodaCAD modifies the XDE prototype shape, all instances of the
modified part update simultaneously.

**Modify Active Part → Shell, Mill, Pull, Fuse**
Same workflow -- Set Active, choose operation, select geometry, enter
parameters.

---

## Tutorials

Full, step-by-step walkthroughs live under [`tutorials/`](tutorials/) --
each one doubles as a regression test, with every step annotated with
what it exercises in KodaCAD's own code.

- **[The OCC Bottle](tutorials/occ-bottle/README.md)** -- builds the
  classic OpenCascade tutorial bottle entirely from scratch: sketching,
  Extrude, Fillet, Mill/Pull, Shell, and Undo/Redo, all on a single
  part.
- **[Assembly Structure with `as1-oc-214.stp`](tutorials/as1-oc-214/README.md)** --
  loading a pre-built, multi-part assembly two different ways, the XDE
  hierarchy viewer, and fillet propagation across a pre-existing
  shared instance.
- **[Building Quaoar's Chassis](tutorials/chassis/README.md)** --
  building a wheel-and-axle-in-a-chassis assembly from nothing:
  sibling-assembly creation, reparenting, shared instances (both a
  part and an assembly), the Position dialog's full surface, and
  Undo/Redo across a long, mixed operation history.

## Tested workflows

### Load / Modify / Save
See `docs/DEVELOPMENT_LOG.md` for a detailed walkthrough matching
the steps in `docs/Load_Modify_Save_Demo.pdf`:
1. Load `as1-oc-214.stp`
2. Set `l-bracket_1` as active part
3. Apply fillet -- both L-brackets update simultaneously
4. Rename a bolt -- all shared instances update
5. Save session
6. Reload -- modifications preserved

### Create and place a new part
1. Load `as1-oc-214.stp`
2. Place workplane on top face of right L-bracket
3. Draw 5mm circle, extrude 3mm, name "button"
4. Button appears under `/` alongside `as1`
5. Drag button to `l-bracket-assembly_2`
6. Button appears in BOTH L-bracket assemblies (shared instance)
7. Save and verify in CAD Assistant -- color and name preserved

---

## File structure

```
kodacad2/
  kodacad.py          main entry point
  mainwindow.py       MainWindow, TreeView
  docmodel.py         XDE document model (core -- read this first)
  workplane.py        2D workplane geometry
  m2d.py              2D sketch toolbar
  koda_viewport.py    OCP 3D viewport (AIS_ViewController)
  stepanalyzer.py     STEP structure analysis utility
  rpnCalculator.py    RPN calculator widget
  version.py          version string
  OCCUtils/           OCC geometry utilities (ported from PythonOCC)
  icons/              toolbar icons
  step/               sample STEP files
  docs/
    DEVELOPMENT_LOG.md  session-by-session development history
    TODO.md             broken items + future ideas
  tutorials/
    occ-bottle/         build the OCC bottle from scratch
    as1-oc-214/         load and explore a pre-built assembly
    chassis/            build an assembly from scratch (Quaoar's chassis)
  pyproject.toml      uv project file
```

---

## Key concepts for developers

**docmodel.py is the heart of KodaCAD.** It wraps OCCT's XDE
(`XCAFDoc_DocumentTool`, `XCAFDoc_ShapeTool`, `XCAFDoc_ColorTool`) and
provides `parse_doc()` which builds `part_dict` and `label_dict` from
the live document. Everything else in the application reads from these
two dicts.

**The XDE label hierarchy:**
```
0:1:1:1   as1 (assembly)       <- GetFreeShapes returns this
0:1:1:2   rod-assembly          <- prototype shapes at root
0:1:1:3   nut
...
0:1:1:1:1  rod-assembly_1  => 0:1:1:2   <- component (instance)
0:1:1:1:2  l-bracket-assembly_1 => 0:1:1:5
```

**OCP vs PythonOCC:** Static methods get `_s` suffix in OCP.
`GetApplication()` → `GetApplication_s()`. See `docs/DEVELOPMENT_LOG.md`
for the complete list of API changes.

**Mouse picking has two separate pipelines** -- native OCCT 3D
selection and the 2D sketch engine's own pixel-to-workplane math --
that converge on one callback dispatcher. See
[`docs/PICKING_ARCHITECTURE.md`](docs/PICKING_ARCHITECTURE.md) for
the full picture, including a trap worth knowing about before editing
selection-mode code.
