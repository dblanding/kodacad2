# KodaCAD 2

A from-scratch 3D CAD application
* Based on the original [KodaCAD](https://github.com/dblanding/kodacad)
* Built on OCP (Python bindings for OpenCascade's
    [OCCT](https://www.opencascade.com/)) -- see below for how this
    differs from other Python CAD libraries
* Patterned after HP's dynamic modeling lineage (ME-30 → SolidDesigner)
* Part creation workflow: workplane → sketch → **Pull** (add or remove
  material, straight or around an axis) → modify
* Intended to meet the basic requirements in a typical CAD workflow:
    * Start a new session or load a previous one (saved as a `.kcad`
      file: the STEP model plus your workplanes)
    * Import components in STEP format
    * Position them within an assembly structure
    * Create simple mounting plates & brackets
    * Loft a solid -- or a hollow section -- through a set of
      workplanes, combine parts with **Boolean** (Fuse / Subtract), and
      make linear or angular **arrays** of parts and assemblies
    * Modify parts directly, even ones you didn't build: remove
      features (**Defeaturing**) and push or pull faces (**Move Face**)
      with a live preview
    * Select, recolor, move and delete whole groups of parts with a box
    * Animate a mechanism (Geneva drive, four-bar linkage, a crane lift)
      with a slider, trace the path of a point, and export the motion as
      an mp4 video
    * Save session as `.kcad`, export the 3D model as plain STEP, or save
      any one assembly or part as its own STEP file, placed at the origin

Designed for users who want to assemble, modify, and create
3D mechanical parts and assemblies using a scriptable, open-source
toolchain -- with no commercial dependencies and no Conda environment.

![KodaCAD UI](imgs/kodacad-ui.png)

## Dynamic modeling: change the part, not the history

A STEP file arrives with no feature tree. KodaCAD lets you edit it
directly, the way the HP/CoCreate lineage did:

* **Move Face** -- pick a face (or a box of faces), type a distance, and
  watch a live ghost of the result before you commit. A positive
  distance adds material (thickens a wall, narrows a slot); a negative
  one removes it (opens a hole up for a clearance fit). Faces that must
  move with the one you picked show in yellow, and heavy green or
  magenta lines mark exactly what changes.
* **Defeaturing** -- remove a hole, a pocket, a blend or a whole
  isolated feature, and the surrounding faces heal over the gap.
* **They work together.** When OpenCascade cannot build an offset, Move
  Face marks the faces that stand in its way in red and tells you what
  to remove first; Defeaturing takes them out, and the move goes
  through.

Try it on a real bracket in the
[Moving Faces tutorial](tutorials/move-face/README.md), and see
[Defeaturing a Part](tutorials/defeaturing/README.md) for the other half.

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


* [Install uv](https://docs.astral.sh/uv/getting-started/installation) if you don't have it

* Clone this repo
```
git clone https://github.com/dblanding/kodacad2
cd kodacad2
```

* Run directly -- uv handles all dependencies automatically
`uv run kodacad.py`


Dependencies (managed automatically by uv):
- `ocp` -- OCCT Python bindings (replaces PythonOCC)
- `pyside6` -- Qt6 Python bindings (replaces PyQt5)
- `build123d` -- geometry helpers used by the viewport and the Position
  dialog

Optional: **`ffmpeg`** on your PATH, needed only by *Export video...* in
Animate Mechanism (on Ubuntu: `sudo apt install ffmpeg`). Everything
else works without it.

---

## How to use it

### Loading a STEP file

Two menu items bring a STEP file in: **File → Load Session** *replaces*
the whole 3D document with the file, and **File → Import STEP** *adds*
the file as a new component alongside whatever is open. Both are
described under [Saving and loading](#saving-and-loading).

### Navigating the view

| Gesture | What it does |
|---|---|
| **MMB drag** | orbit |
| **Ctrl + MMB drag** | pan |
| **Shift + MMB drag** | zoom |
| **MMB drag near the edge** of the viewport (the outer ring) | spin the view about the line of sight, like turning a map |
| **LMB click** / **LMB drag** | select / box-select |
| **RMB click** | fit everything in the window |
| **Utility → Level View (Z up)** | roll the view so the model's Z axis points up the screen again |

A middle *click* (no drag) ends the current operation, wherever it lands.

### Saving and loading

KodaCAD's native session file is a **`.kcad`** file: a zip holding the 3D
model (as a standard STEP file) and your workplanes.

| Menu item | What it does |
|---|---|
| **File → Save Session** | Writes a `.kcad` file: the model *and* your workplanes. |
| **File → Load Session** | Opens a `.kcad` (or plain STEP) file, *replacing* the whole 3D document. |
| **File → Import STEP** | *Adds* a STEP file as a new component under the current `/`. |
| **File → Export STEP** | Writes the 3D model alone, as plain STEP, for other CAD programs. |
| **Save as STEP (at origin)...** (tree right-click) | Writes one assembly or part to its own STEP file, with its frame at the origin. |

The details -- what is and is not saved, what happens to workplanes on
load, and why `/` stays clean through repeated cycles -- are in
[Sessions and files](docs/concepts/sessions-and-files.md).

#### Undo and Redo apply to the 3D model only

Undo (Ctrl+Z) and Redo (Ctrl+Y) step through changes to the **3D
model** -- pulls, fillets, shells, Booleans, lofts, arrays, face moves,
positioning, renaming and so on. **Workplanes and their sketch geometry are not part of that
history.** Drawing a line, deleting an element, or repositioning a
workplane cannot be undone with Ctrl+Z, and undoing a 3D operation
will not rewind your sketches. Workplanes are your construction
scaffolding rather than the model itself, and they live outside the
document that Undo/Redo manages.

In practice this means: Undo is safe to use freely on the model without
disturbing your sketches, but a workplane edit is final until you make
the opposite edit yourself. Since a workplane's state is only stored
when you save, **Save Session before experimenting** with sketch work
you might want back -- the `.kcad` file is your safety net for
workplanes.

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
- **Left-click** — select item (Ctrl+click / Shift+click select several)
- **Right-click** — context menu: Item Info, Set Active, Rename,
  Create New Assembly, Create Empty Part, Create Shared Instance,
  Copy Part, Create Array..., Make Workplane Set, Save as STEP (at
  origin)..., Set Transparent, Set Opaque, Set Color..., Take Color as
  Pen, Paint with Pen Color, Color Faces (display only)..., Delete.
  Set Color, Paint with Pen Color and Delete act on **every selected
  part** when you right-click one of several selected rows.

### Combining and shaping parts

* **Create/Modify → Pull** -- pull a sketched profile out of its
  workplane. *Add Material* builds, *Remove Material* cuts; the mode is
  *Linear* (a distance along +W, −W or both) or *Angular* (around an
  axis you pick).
* **Create/Modify → Boolean...** -- Fuse or Subtract one part from
  another (*Keep Tool* leaves the second part in place, *Merge Seams*
  heals the scar lines a Boolean can leave).
* **Create/Modify → Loft** -- loft through a **Workplane Set** (made with
  *Workplane → Set...* or, from workplanes you already have, *Make
  Workplane Set* in the tree). Draw an outer profile and any number of
  inner profiles on each workplane and the loft comes out hollow.
* **Create Array...** (right-click a part or assembly) -- linear or
  angular arrays of instances.
* **Fillet, Chamfer, Shell..., Defeaturing..., Move Face...** -- modify
  the active part.

**Booleans can't freeze KodaCAD.** Every Boolean that Pull, Boolean and
Loft perform runs in a separate helper process. If one takes longer than
half a second a *Working* box appears with a **Cancel** button; a
Boolean that runs too long or uses too much memory is stopped, and
nothing changes. (Operations that OpenCascade cannot finish -- for
example two round bars of exactly equal diameter crossing at right
angles -- are better avoided by changing one diameter slightly.)

### Working on groups of parts

The tree and the viewport select together, in both directions.

1. With no operation active, **drag a box** in the viewport (top to
   bottom is *window* mode: parts entirely inside the box; bottom to
   top is *crossing*: parts the box touches). Every part picked is
   highlighted in the tree, and the assemblies that hold them open up.
   Selecting several rows in the tree (Ctrl/Shift+click) likewise
   highlights all of them in the viewport.
2. **Move them:** drag any one of the selected rows onto an assembly
   (create one first with *Create New Assembly*). All of them move, and
   keep their place in space. The target must be an assembly; dropping
   onto a plain part is refused. A new sub-assembly is also the way to
   hide or show a group with one checkbox.
3. **Color them:** right-click one of the selected rows ->
   *Set Color...*.
4. **Delete them:** right-click one of the selected rows -> *Delete*.
   One confirmation, one undo (Ctrl+Z brings the whole group back).
   Only the *instances* are removed. A part's underlying prototype is
   removed too only when nothing else still uses it, so deleting one
   instance of a shared pair never damages the other. Workplanes and
   the top-level root in a selection are left alone.

### The pen: copy a color from one part to another

Matching an existing color by eye in the color picker is slow. Instead,
right-click a part -> **Take Color as Pen**. The status bar (lower
right) shows a swatch of the color and its hex value. Then right-click
any other part (or one of a group of selected parts) -> **Paint with
Pen Color**. The color is written into the document like *Set Color*,
so it is saved and survives a reload. The pen itself is not saved: it
is empty at the start of each session.

### Units

**Utility -> set Units** switches between inches, millimeters, feet and
meters (the status bar shows the current choice). Everything is held in
millimeters internally; typed distances, measurements and the Move Face
distance are converted. Pick feet or meters for large models; the
workplane label stays a sensible size at any scale.

### Animate Mechanism

**Utility -> Animate Mechanism...** moves the parts of an assembly with
a slider so you can see how a mechanism works, stop it in any pose
(then project faces onto a workplane to get a snapshot) and **Trace**
the path of a point. The motion is defined by a short Python file you
choose and can edit; `mechanisms/` has a 4-slot Geneva drive, a
pin-jointed four-bar and a crane lift (`crane_lift.py`). It is display
only: the model, tree and undo history are untouched, and *Done* puts
every part back. **Export video...** records the motion as an mp4 (it
needs `ffmpeg`, see *Installation*). How to write a mechanism file:
[docs/MECHANISMS.md](docs/MECHANISMS.md).

### If KodaCAD crashes

A crash closes the terminal along with the program, so KodaCAD also
writes crash information to **`kodacad-crash.log`** next to
`kodacad.py` (a start-up line each run; the last block before the next
start-up line is the crash). If you report a crash, send that file.
It is ignored by git and can be deleted at any time.

---

## Tutorials

Full, step-by-step walkthroughs live under [`tutorials/`](tutorials/) --
each one doubles as a regression test, with every step annotated with
what it exercises in KodaCAD's own code.

- **[The OCC Bottle](tutorials/occ-bottle/README.md)** -- builds the
  classic OpenCascade tutorial bottle entirely from scratch: sketching,
  Pull (adding material), Fillet, Shell, and Undo/Redo, all on a single
  part.
- **[Assembly Structure with `as1-oc-214.stp`](tutorials/as1-oc-214/README.md)** --
  loading a pre-built, multi-part assembly two different ways, the XDE
  hierarchy viewer, and fillet propagation across a pre-existing
  shared instance.
- **[Build Assembly `as1` from a Kit of Parts](tutorials/build-as1-oc-214/README.md)** --
  the reverse of the tutorial above: starting from `as1-oc-214`'s five
  loose, un-positioned prototype parts and rebuilding the real
  assembly from scratch, exercising nearly every Position dialog
  method along the way.
- **[Building Quaoar's Chassis](tutorials/chassis/README.md)** --
  building a wheel-and-axle-in-a-chassis assembly from nothing:
  sibling-assembly creation, reparenting, shared instances (both a
  part and an assembly), the Position dialog's full surface, and
  Undo/Redo across a long, mixed operation history.
- **[Organizing an Assembly](tutorials/lathe/README.md)** --
  organizing a flat file in which all parts are a direct child of
  the root (often with cryptic names), into a hierarchical structure
  of functional subassemblies, making it easier to navigate. 
- **[Sketching a Jack-o'-Lantern](tutorials/jack/README.md)** --
  a full workout of the 2D sketch toolbar building a jack-o'-lantern
  face, then reusing the OCC Bottle's pull-then-heavily-fillet
  technique to carve that same face into a pumpkin with a real,
  multi-profile Pull operation.
- **[Defeaturing a Part](tutorials/defeaturing/README.md)** --
  demonstrating the ability to remove holes and faces and to extend
  adjacent faces to heal the gap.
- **[Lofting a Hollow Part Through a Workplane Set](tutorials/lofting/README.md)** -- building a simple hollow lofted part (outer and inner profiles on each
  workplane) then working it over: a transverse hole, fillets, and
  finally defeaturing to take the fillets back off; plus building a
  Workplane Set from existing workplanes and lofting onto an existing part.
- **[Moving Faces](tutorials/move-face/README.md)** --
  pushing and pulling the faces of an imported L-bracket (`L-brkt.stp`)
  with a live preview: thickening a wall, opening up a slot, widening
  holes (box select and Ctrl+click to unpick), and what to do when
  OpenCascade cannot build an offset -- the red "suspect" faces, and
  Defeaturing to fix them.
  

**Looking for how something works?** The [documentation index](docs/INDEX.md)
lists the tutorials, the one-page explanations of key ideas, and the
reference notes.

## Tested workflows

### Load / Modify / Save
1. Load `as1-oc-214.stp`
2. Set `l-bracket_1` as active part
3. Apply fillet -- both L-brackets update simultaneously
4. Rename a bolt -- all shared instances update
5. Save session
6. Reload -- modifications preserved

### Create and place a new part
1. Load `as1-oc-214.stp`
2. Place workplane on top face of right L-bracket
3. Create a new part
    * RMB click on '/' in tree; select "Create Empty Part"; name "button"
    * Draw 5mm circle on workplane
    * **Create/Modify -> Pull**; Distance: 3mm
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
  wp_io.py            .kcad session container + workplane save/restore
  m2d.py              2D sketch toolbar
  koda_viewport.py    OCP 3D viewport (AIS_ViewController)
  stepanalyzer.py     STEP structure analysis utility
  face_offset.py      Move Face geometry (per-face offset, no GUI)
  face_offset_server.py  persistent worker that computes the live preview
  face_offset_worker.py  one-shot worker used by Apply
  offset_preview.py   Qt client for the preview worker
  mechanism_dialog.py Animate Mechanism dialog (slider, Trace, video)
  video_export.py     frame list + ffmpeg command for Export video...
  trace_math.py       straight-section finder for Trace (plain Python)
  mechanisms/         mechanism files (Geneva drive, four-bar, crane lift)
                      + STEP models
  dialog_style.py     the minimal dialog theme shared by the dialogs below
  frame_chooser.py    the shared Frame row (World | Workplane | Pick)
  pull_dialog.py      Create/Modify -> Pull
  boolean_dialog.py   Create/Modify -> Boolean...
  safe_boolean.py     Fuse / Cut / Common with guard rails (busy box,
                      Cancel, time and memory limits)
  boolean_worker.py   the helper process safe_boolean runs one Boolean in
  position_dialog.py  Position -> Part/Asy (Dynamic, Mate Align, 2 Points)
  position_math.py    the arithmetic behind it (plain Python)
  wp_position_dialog.py  Position -> Workplane
  wp_set_dialog.py    Workplane -> Set... (create a Workplane Set)
  wp_sets.py          group existing workplanes into a set (tree menu)
  array_dialog.py     Create Array... (linear and angular)
  array_math.py       the arithmetic behind it (plain Python)
  face_color_dialog.py  Color Faces (display only)
  isolated_features.py  finds isolated features for Defeaturing's Auto mode
  xde_tree_dialog.py  Utility -> XDE Label Hierarchy viewer
  snap_engine.py      the 2D sketch engine
  rpnCalculator.py    RPN calculator widget
  version.py          version string and changelog
  OCCUtils/           OCC geometry utilities (ported from PythonOCC)
  icons/              toolbar icons
  imgs/               images used by this README
  tests/              smoke tests and the STEP files they use
  test_all.py, test_docmodel.py, probe_*.py, minimal_repro.py
                      small diagnostic scripts (not needed to run KodaCAD)
  src/                small label / location checking scripts
  TODO.md             broken items + future ideas
  tools/
    check_docs.py       checks the Markdown docs (links, layering, stale phrases)
  docs/
    INDEX.md            where to find everything
    concepts/           one page per idea (how it works)
    WRITING_DOCS.md     rules for keeping the docs tidy
    DEVELOPMENT_LOG.md  development history, newest entries last
    MECHANISMS.md       how Animate Mechanism works; writing a mechanism file
    PICKING_ARCHITECTURE.md  the two picking pipelines
    SKETCH_ENGINE_DESIGN.md  design of the 2D sketch engine
    TESTING_CHECKLIST.md     manual regression checklist
    UNDO-REDO.md        what Undo/Redo covers and how
  tutorials/
    occ-bottle/         build the OCC bottle from scratch
    as1-oc-214/         load and explore a pre-built assembly
    build-as1-oc-214/   rebuild that same assembly from loose parts
    chassis/            build an assembly from scratch (Quaoar's chassis)
    lathe/              organizing and navigating a large assembly
    jack/               sketch a jack-o'-lantern face, then carve a pumpkin
    defeaturing/        remove holes and features, heal the gap
    lofting/            loft through a workplane set, then work it over
    move-face/          push/pull faces of an L-bracket, with live preview
    extract-roots/      script that splits as1-oc-214 into its loose parts
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
