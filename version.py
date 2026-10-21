"""Single source of truth for the KodaCAD application version.

2.3.0 -- 2026-10-21 (Sessions 154-169)
* Create/Modify -> Move Face: push or pull one or more faces by a typed
  distance (+ adds material, - removes it) using OCCT's per-face
  offset. Live preview: a translucent ghost of the result, the picked
  faces in orange, faces that move with them (tangent) in yellow, and
  heavy lines (green: material added, magenta: removed) showing only
  the stretch each edge changes by. Planar faces with parallel
  neighbours are moved by an exact extrude/cut instead, and the
  offset runs in a separate worker process so a slow or failed
  offset never freezes the GUI.
* When OpenCascade cannot build an offset, Move Face marks the
  "suspect" faces red (very narrow faces, or faces touching a very
  short edge: a leftover chamfer, a sliver, a countersink that just
  clips a slot) with advice to remove them first (Defeaturing).
* Ctrl+click unpicks a face in Defeaturing and Move Face; box select
  adds (drag top to bottom = window, bottom to top = crossing).
* Enter no longer completes the operation in Defeaturing or Move Face;
  only Apply does.
* Rad measurement ignores circles on hidden workplanes.
* Move status is shown in the user's units; a zero-radius circle no
  longer breaks drawing.
* New tutorial: Moving Faces (tutorials/move-face).

2.2.0 -- 2026-10-12 (Sessions 149-152)
* Native session format: File -> Save Session now writes a .kcad file
  (a zip holding the STEP model plus workplanes.json), so workplanes,
  their sketch geometry and construction geometry survive a save and
  reload. Plain .stp/.step files still load; File -> Export STEP writes
  a plain STEP for other CAD programs.
* Workplane profile geometry is stored as plain data (lines, circles,
  arcs) with edges derived from it -- lean to save, and ready for
  curves (NURBS) that can't be recovered from their edges.
* Display-only face coloring (for tutorial illustrations).
* Undo/Redo now keeps the active part, and the face-pick dialogs keep
  working across it.
* Shell repairs an invalid MakeThickSolid result instead of showing a
  ghost of the unshelled part.

2.1.2 -- 2026-10-08 (Session 143)
* Bi-directional Pull
* Boolean (Fuse + Subtract)

2.1.1 -- 2026-10-04 (Session 131)
* Polished toolbar visually, especially clipping section.

2.1.0 -- 2026-10-03 (Session 129) including:
* Pull (Linear/Angular, Add/Remove material, +/- Direction)
* Chamfer
* Loft from Workplane Set
* Defeaturing (Remove hole, remove Isolated Feature (manual/auto))
* Position (Parts/Assemblies, Workplanes)
* Section Views
* Set Part Color

2.0.0 -- THE SKETCH ENGINE ERA (Session 62). In Doug's words: 'a
foundation that, quite honestly, I didn't think was achievable.'
Pyurcad/CoCreate-style sketching on Kodacad workplanes: the
screen_to_uv bridge, app-side snap engine with the drafter's catch
policy (intersections by default; Ctrl+Shift entity-anchored
centers/midpoints), engine input on every 2D tool (no catch -> no
point; gesture clicks as their own class), rubber-band previews on
all point-sequence tools, the catch square, bold-black geometry over
dashed construction, middle-click end-operation, and the retirement
of the pre-built intersection-point paradigm. First part created
end-to-end with the new sketcher: 2026-08-06.

1.2.0: undo/redo (Edit menu, Ctrl+Z/Y, OCAF transactions, Position
dialog as one transaction per session). 1.1.x: highlight sync, the
save/reload analytic-selection pick fix, naming round-trips, STEP
header customization.
"""

APP_VERSION = "2.3.0"
