## A good tool should be a *Pleasure To Use*.

* This file is a collection of suggestions aimed at making Kodacad a *Pleasure To Use*, mostly by improving workflow on *typical* projects.
* Tracks outstanding issues and future development ideas.
* Both developer and user contributions are welcome.

---

## To Do (by priority):

* RMB on part in tree to set/edit part color (color picker?)

* Box-select edges for filleting (eg.: OCC bottle)
    * Claude: box-select for fillet edges is real and feasible — OCCT has rubber-band selection machinery — moderate effort, worth banking near the top of Misc, because picking twelve bottle edges one at a time is exactly the kind of friction this project exists to remove.

* Multi-item select (from tree) for delete (using ctrl or shift key?)

* Booleans (fuse, subtract, intersect)

* Heal scars in solids that have been built progressively
    * Claude: OCCT has `ShapeUpgrade_UnifySameDomain`, which exists precisely to merge same-domain faces and erase those lines. A one-afternoon smoke test could tell us whether healing is nearly free.

* Implement abilty to create and save a 1x scale drawing view in printable format (for checking feature alignment w/ real parts)
    * Workaround: Export the part in Step format and create the dwg in another app.

## Deferred (Not easily implemented)

* View Cube is unresponsive when 2D drawing tools are in use
    * Claude: Annoying but cosmetic, and it touches the selection-mode plumbing that has historically been the riskiest code in the app to poke.
    * Workaround: Just middle click to exit 2D tool and use the view cube

* Native save / load format
    * Claude:  Blocked, not hard: native `.xbf` save. Session 49 confirmed the OCP binding bug (CadQuery/OCP#182: `Open` returns an empty document while reporting success). No amount of effort on our side fixes that; the move is to re-run our existing smoke test whenever OCP ships a new version.
    * Workaround: Just save session (gets saved in .STEP format) and reload as next session. Workplanes are not saved.
