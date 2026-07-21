# Kodacad2 Manual Regression Checklist

Purpose: a quick pass through this after any change touching
`docmodel.py`, `mainwindow.py`, or `kodacad.py`, to catch regressions
before they slip in unnoticed. Each item traces back to a real bug we
hit and fixed at least once -- see `DEVELOPMENT_LOG.md` for the story
behind each one if the "why" isn't obvious.

Check off what you tested; note the date and result for anything that
fails. When a NEW bug gets fixed, add a line here for it so it can't
silently come back.

## STEP Import

- [ ] Import a STEP file containing a multi-part sub-assembly. Every
      part's real name shows in the tree (not blank / not auto-numbered).
      (Session 9)
- [ ] Import the SAME file twice into one session. Both copies show
      correct names; editing a shared part inside one copy shows the
      edit in the other too (see Shared Instances below).

## Session Save / Reload (do this after ANY document-mutating feature)

- [ ] Save a freshly-imported (untouched) component, reload, name and
      position both correct. (Confirms import path alone is sound.)
- [ ] Position a part or assembly that was part of the ORIGINAL loaded
      session file (never separately imported), save, reload -- name
      and position both correct. (Session 19: this case has always
      worked.)
- [ ] Position a part or assembly that came in via "Import STEP" in
      THIS session, save, reload -- name and position both correct.
      (Session 19: `manual-lathe` passes as of Session 19; a hub
      assembly with unusual internal structure -- NAUO1/NAUO2 generic
      names in its own file -- still does NOT pass. Known open issue,
      narrower than the general regression that preceded it.)
- [ ] Move MULTIPLE different parts/assemblies in one session (mix of
      2 Points and Mate/Align), save, reload -- ALL moves survived,
      not just the first.
- [ ] After any of the above, re-check colors survived too (color-
      setting logic changed alongside the naming fixes in Session 16 --
      never independently regression-tested since).

## Tree View / RMB Context Menu

- [ ] RMB on a tree item shows the menu immediately (no prior left
      click required). (Session 11)
- [ ] Set Active, Rename, Set Transparent, Set Opaque, Delete all work
      from RMB, including clicking an action again right after using
      it (not just the first time). (Session 11 for the menu itself;
      Session 16 for the "clicking an already-selected option does
      nothing" class of Qt bug -- same root cause hit again in the
      Position dialog's radio buttons.)
- [ ] Delete a leaf part, an assembly with children, one instance of a
      SHARED part (confirm the other instance survives untouched), and
      a workplane.

## Shared Instances

- [ ] Two components in the tree that reference the same underlying
      part/assembly DEFINITION (e.g. `l-bracket-assembly_1` and `_2`
      in `as1-oc-214.stp`, which share an inner `l-bracket` part):
      editing/moving the SHARED PART shows up in both places (this is
      correct, expected behavior -- not a bug). Moving one COMPONENT
      INSTANCE's own top-level placement should NOT move the sibling
      instance's placement. (Session 13)
- [ ] Delete one shared instance -- the other instance and the
      underlying shared definition survive intact. (Session 11)
- [ ] Position (2 Points or Mate/Align) a shared instance, save,
      reload -- name and position both survive now (Session 22:
      previously any shared instance -- confirmed with
      `l-bracket-assembly_1`/`_2` -- reverted position and lost its
      name on export, a documented `STEPCAFControl_Writer` limitation
      with "partner shapes" at different locations). Confirm the
      REPOSITIONED instance is now independent -- editing it should NOT
      affect its sibling anymore (deliberate behavior change: a
      repositioned instance intentionally stops sharing geometry with
      any sibling that stays linked to the original, matching "make
      unique" in mainstream CAD tools). Confirm the UNTOUCHED sibling
      still round-trips correctly and is still linked to whatever else
      references the original shared definition.

## Viewport

- [ ] RMB click (not drag) on the viewport does a clean Fit All, no
      residual zoom drift on subsequent mouse movement. (Session 12)
- [ ] LMB rotate and MMB pan still feel normal (these were never
      broken, but worth a sanity check after any `koda_viewport.py`
      change).

## Position Dialog

- [ ] Pre-select a part/assembly in the tree, open Position -- the
      full breadcrumb path (not just a bare name) shows at the top.
      (Session 16 -- disambiguates shared instances.)
- [ ] 2 Points: neither picked point needs to be on the moving part --
      only the distance between them matters. Try picking both points
      on an unrelated part purely as a reference distance (confirmed
      real workflow, Session 16).
- [ ] Mate/Align Step 1: pick two faces, Mate rotates them to opposed
      normals, Align to parallel. Click Mate (or Align) a SECOND time
      in the same dialog session without switching away first -- it
      must start a new pick sequence, not silently do nothing.
      (Session 16 -- Qt `toggled` vs `clicked` bug.)
- [ ] Reverse re-applies the last Mate/Align move with the opposite
      mode using the SAME picks, without re-prompting.
- [ ] Back undoes the last applied step and restores the exact prior
      position.
- [ ] Status bar messages are short enough to read in full, not
      truncated by the window width. (Session 20)
- [ ] Save + reload after using Position -- see the Session Save /
      Reload section above; this is the step most likely to reveal a
      regression that looked fine in the live session.

## Modify Active Part (fillet, shell, extrude, revolve, etc.)

- [ ] Try fillet, shell, mill, pull, rotateAP, and rev_rotateAP with NO
      Active Part set -- each must show a MODAL warning immediately
      (before any edge/face picking starts), not a console-only
      message, and not a crash. (Session 20: crash from catching the
      wrong exception type. Session 21: catching it correctly wasn't
      enough on its own -- the check fired only after a full 12-edge
      fillet's worth of picking was already done; moved to fire at the
      moment the menu item is clicked instead, and made modal so it
      can't be missed.)
- [ ] Set an Active Part, fillet a batch of edges (the OCCT "Bottle"
      tutorial's 12-edge fillet is a good stress case), shell, extrude,
      revolve -- all still produce correct geometry and update the
      tree/display correctly.

## Known Open Issues (not yet fixed -- don't re-report, do check they
haven't gotten WORSE)

- Positioning an imported hub assembly with unusual internal STEP
  structure (generic `NAUO1`/`NAUO2` names in its own file) does not
  survive save/reload. UPDATE (Session 22): the general mechanism
  turned out to be shared instances ("partner shapes" at different
  locations, a documented OCCT writer limitation) -- now fixed via
  automatic unsharing before reposition. The hub's own internal
  NAUO1/NAUO2 naming was an early clue pointing at some kind of
  internal duplication/sharing in that specific file, so this fix may
  well have resolved the hub case too as a side effect -- worth
  retesting before assuming it's still broken.
- Mate/Align only implements Step 1 of the 3-2-1 workflow -- applying
  Mate twice in a row does NOT preserve the first mate's constraint
  (no DOF-tracking yet; Step 2/3 not built). Expected limitation, not
  a bug -- see Session 16.
- "Dynamic" (AIS_Manipulator) method is disabled -- not ported yet.
- "Align Axis" constraint is disabled -- Step 2/3 territory, not built
  yet.
