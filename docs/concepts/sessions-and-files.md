# Sessions and files: .kcad, STEP, Load, Import

How KodaCAD saves your work and brings files in. This is the single place
this is explained; other documents link here.

## The session file: `.kcad`

KodaCAD's native session file is a **`.kcad`** file. It is an ordinary
zip archive holding two things side by side, in the spirit of NumPy's
`.npz`:

```
mypart.kcad
  mypart.stp        the 3D model -- a standard STEP file
  workplanes.json   the workplanes, plain text
```

The STEP half carries everything a STEP file can: the assembly
structure, part names, colors, shared instances. The JSON half carries
what STEP has no place for: each workplane's position in 3D, its
sketched profile geometry (lines, circles, arcs), its construction
geometry, which workplanes are hidden, and which one was active. The
file is plain data -- nothing in it is executed when it loads -- and
because it is a zip, you can always open it with any archive tool and
pull out the `.stp` by hand.

## The menu items

**File → Save Session**
Writes a `.kcad` file holding the model *and* your workplanes. The file
is written to a temporary name and swapped into place only when
complete, so a failed save never damages an existing file.

**File → Load Session**
Opens a `.kcad` file -- or any plain `.stp` / `.step` file with
assembly structure. *Replaces the entire 3D document* -- whatever was
open before is gone. The loaded file's own content becomes the session,
with no wrapping or nesting involved.

What happens to workplanes depends on the file. A `.kcad` file brings
its own workplanes and replaces the ones on screen. A plain STEP file
has no workplanes to bring, so it **leaves your current workplanes
alone** -- handy for loading a part or assembly and sketching on it
with the workplanes you already have set up.

**File → Import STEP**
*Adds* a STEP file as a new component under the current `/`, alongside
whatever is already open, ready to be positioned and dragged into an
assembly. Use Load Session to pick up where a previous session left off;
use Import STEP to bring a file's content into a session you are
actively building.

**File → Export STEP**
Writes the 3D model alone, as a plain STEP file, for opening in other
CAD applications or sharing with people who don't use KodaCAD. No
workplanes are included.

**Save as STEP (at origin)...** (right-click an assembly or part in the
tree)
Writes just that assembly or part -- with everything beneath it -- as its
own STEP file. It is saved with its own frame at the **origin**, however
far from the origin it sits in your model, so it loads cleanly into
another session. Shared parts inside it stay shared. The model itself is
not changed.

## What a session does *not* save

- **Undo/Redo history.** Loading starts you with a clean history.
- **Display-only face colors** (Color Faces...), which are an
  illustration aid, not part of the model.
- **A workplane's link to the face it was placed on.** The workplane
  keeps its position in space; it just no longer remembers which face
  it came from.

Because workplane edits are not part of Undo/Redo (see the README's
section on Undo and Redo), **save the session before experimenting** with
sketch work you might want back: the `.kcad` file is your safety net for
workplanes.

## Why `/` stays clean through repeated save, load and import

KodaCAD holds one guarantee: once a document exists, `/` is always the
top assembly, through any number of save/reload cycles.

Save strips any redundant `/` wrapper before writing, so a saved file
never contains one. Load Session replaces the whole document rather than
nesting anything, so there is nothing for a wrapper to accumulate into.
Import STEP is the one path that adds content under an existing root, so
it unwraps any `/`-named root in the incoming file first -- composing
locations through any already-nested legacy wrapper levels in one pass,
so even an older file saved before this existed unwraps completely.

**The tree's own `/` label.** The tree always shows a `/` under the `3D`
header, whether or not anything is loaded -- that is the tree's own
scaffolding, not part of any document. The document's real root assembly
is *also* named `/` by convention (visible as its child), which is why a
freshly built session can show what looks like `/` inside `/`: two
different things that share a name, not an accumulation bug.

## Related

- [Writing and organizing the docs](../WRITING_DOCS.md) -- where this page
  sits and why.
