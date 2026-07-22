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
- [ ] Mate/Align Steps 2 and 3 (Session 33, UNTESTED as of this
      writing): apply Mate or Align a SECOND time on the same item
      (not switching Method in between) -- confirm it rotates WITHIN
      the plane Step 1 already established (about the same axis),
      not a fresh independent flush-rotation that could undo Step 1's
      constraint. Status bar should read "step 2 of 3, 1 DOF left."
      Apply a THIRD time -- should be pure translation along the one
      remaining free direction, status bar reading "fully constrained
      (3 of 3)." Try a 4th Mate/Align attempt at that point -- should
      refuse with a clear message, not silently do something. Test
      Back after 2-3 steps -- confirm it correctly steps back through
      Step 3->2->1->0, not just undoing position while leaving the
      step counter wrong. Test Reverse after Step 2 specifically
      (previously only worked correctly for Step 1). Switch to 2
      Points or Dynamic mid-sequence (after Step 1 or 2), then back to
      Mate Align -- confirm it starts over at Step 1 (Clean Slate),
      not continuing where it left off.
- [ ] Align Axis (Session 35, UNTESTED as of this writing -- per
      Doug's original PDF design, NOT Basicad's standalone version):
      Mate/Align a face first (Step 1), then choose Align Axis
      instead of Mate/Align again -- pick a hole on the moving part,
      then a hole on the fixed part. Confirm it pins the two holes'
      axis-vs-mated-plane intersection points together (translation
      only, no rotation) and status bar reads "step 2 of 3, 1 DOF
      left." Try Align Axis BEFORE Step 1 (fresh Position, no Mate/
      Align yet) -- should refuse with a clear message, not start
      picking. Complete with a final Align (face pick) -- should be
      pure rotation (spin) about the mated axis, pivoting at the
      pinned hole point, not translating the part as a side effect.
      Confirm Reverse is disabled (greyed out) immediately after
      Align Axis's own pin step, since there's no mate/align choice
      to flip there. Confirm Back correctly unwinds Step 3 -> Align
      Axis pin -> Step 1 -> start. Also worth trying: pick a non-
      circular edge (e.g. a straight edge) when Align Axis is
      expecting a hole -- should show a friendly rejection message,
      not crash.
- [ ] Standalone Align Axis (Session 36, UNTESTED as of this writing
      -- "bolt in a hole"): as the FIRST thing in a Position session
      (no prior Mate/Align), choose Align Axis -- should pick
      CYLINDRICAL FACES this time (not circular edges), e.g. a bolt
      shaft's outer surface and a hole's inner wall. Confirm both
      axes become coincident (position AND orientation), status bar
      reading "step 1 of 3, 2 DOF left." Pick a non-cylindrical face
      -- should reject cleanly. Continue with Mate or Align (face
      picks) -- should translate along the now-shared axis only,
      with a 180-degree flip if the current face relationship doesn't
      match Mate vs Align (e.g. clicking Mate when the faces are
      currently same-direction should visibly flip the part, not
      just translate it wrong-way). Reverse should work here (this
      step DOES have a real mate/align choice, unlike the axis
      alignment itself). Finish with a final Align -- pure spin about
      the shared axis. Confirm Back correctly unwinds all 3 steps.
      Also confirm choosing Align Axis mid-sequence (after a normal
      Mate/Align Step 1, i.e. mate_align_step==1) still correctly
      goes to the OTHER Align Axis role (circular-edge pin, Session
      35) rather than this one -- same button, different picking mode
      depending on which step you're on.
- [ ] Back undoes the last applied step and restores the exact prior
      position.
- [ ] Status bar messages are short enough to read in full, not
      truncated by the window width. (Session 20)
- [ ] Save + reload after using Position -- see the Session Save /
      Reload section above; this is the step most likely to reveal a
      regression that looked fine in the live session.
- [ ] Dynamic (Session 23; translate-drag + Nudge CONFIRMED working --
      Doug used this to precisely mate the lathe assembly to the
      plate, centered, using Nudge values computed from the
      calculator's edge-length key. Gizmo-jump-to-sibling and a crash,
      both traced to set_component_location()'s parent-resolution
      logic, fixed in Session 25.): drag a translate arrow, drag a
      rotate ring, both move the part live and show status-bar
      feedback during the drag. Position an ASSEMBLY with multiple
      parts -- confirm the WHOLE thing moves together during the drag,
      not just one part of it. After releasing, use Nudge (dX/dY/dZ +
      rX/rY/rZ + Apply) to add an exact correction on top of the rough
      drag -- rotation nudge specifically has NOT yet been cleanly
      tested (every attempt so far happened to hit the shared-parent
      limitation first; try it on something whose parent is NOT
      shared). Click Back while Dynamic is active -- confirm no stale/
      orphaned gizmo is left on screen and the manipulator still works
      afterward if you drag again. Switch from Dynamic to 2 Points or
      Mate/Align mid-session -- confirm the gizmo disappears cleanly.
      Click Done, or close the dialog, while a gizmo is attached --
      confirm it's removed.

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

- **Imported top-level assemblies don't survive save/reload.** An item
  brought in via "Import STEP" survives correctly if it's a LEAF/
  simple part, but NOT if it is itself an assembly with its own
  children (confirmed: manual-lathe, a hub assembly, and a purpose-
  built minimal test all fail the same way -- blank NAUO name,
  identity location -- despite the in-memory document being confirmed
  correct right up to the STEP write). Seven fix attempts across
  Sessions 14-29 all failed identically on a fully isolated, headless
  re-test (`minimal_repro.py`); the most invasive one (Session 29, a
  full native-rebuild-with-recursion) additionally regressed internal
  sharing within imported files and was reverted (Session 30). Set
  aside as a known, well-understood (if unresolved) limitation rather
  than chased further for now. Items NATIVE to the session file
  (never imported) are unaffected, including shared instances --
  see the Session Save/Reload section above.
- Repositioning a child within a shared parent assembly (e.g. moving
  `l-bracket` inside `l-bracket-assembly_2`) PROPAGATES to every
  instance of that parent (`l-bracket-assembly_1` too) -- this is
  intended behavior, not a bug, matching how shape edits already
  propagate to shared instances (confirmed with Doug, Session 31,
  after Sessions 24/25 briefly and incorrectly treated this as
  something to refuse). Test: move a shared child via 2 Points, confirm
  BOTH parent instances show the correction, and it survives save/
  reload.
- The AIS_Manipulator gizmo jumping to a sibling occurrence after
  releasing a drag on a SHARED child (Session 23/24 report) -- FIXED
  (Session 32): `set_component_location`'s uid-recovery took the
  first matching label unconditionally, which for a shared child was
  always whichever parent `parse_doc()`'s tree walk visits first in
  document order (assy_1 before assy_2), regardless of which sibling
  was actually selected. Now prefers the occurrence reached through
  the SAME parent the operation started from. Test: select the L-
  bracket via assy_2 specifically, Dynamic-drag it, confirm the
  dialog's breadcrumb and the gizmo both stay anchored to assy_2
  after releasing, not jump to assy_1. Known remaining limitation:
  only resolves one level of sharing ambiguity -- a shared child
  under a shared grandparent (nested two levels deep) could still hit
  a similar issue, not currently tested.
- Positioning an imported hub assembly (`clamping-hub-assembly.step`)
  does not survive save/reload. DEFERRED (Session 22): confirmed its
  `NAUO1`/`NAUO2` blank names are present in the file's own original
  source, before any Kodacad involvement -- a pre-existing data-
  quality issue in that file, not necessarily the same bug as the
  shared-instance fix above. Whether it's the same root cause (true
  sharing between NAUO1/NAUO2) was never confirmed. Set aside after
  diminishing returns; revisit the open question above before
  assuming it's fixed OR assuming it's a new bug.
- Mate/Align's full 3-2-1 workflow (Steps 1/2/3, with real DOF
  tracking) was built in Session 33 -- UNTESTED as of this writing.
  Until confirmed working, treat the old Session 16 limitation
  ("applying Mate twice in a row does NOT preserve the first mate's
  constraint") as possibly still present.
- "Align Axis" constraint is disabled -- needs its own hole/cylinder
  axis-picking machinery, separate from Mate/Align's face-picking,
  not built yet.
