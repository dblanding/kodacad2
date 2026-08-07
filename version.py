"""Single source of truth for the KodaCAD application version.

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

APP_VERSION = "2.0.0"
