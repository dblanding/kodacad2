"""
smoke_test_undo_redo_full.py -- the undo/redo GAUGE (Session 61).

Session 49 already confirmed OCAF's native transaction system
(NewCommand/CommitCommand/Undo/Redo) works on real document
operations. This test answers the remaining question that decides
whether undo/redo integration will be EASY: does it work across
KODACAD'S ACTUAL FULL OPERATION VOCABULARY, driving the real
DocModel methods -- including the heavyweight ones (rebuild-import,
delete with recursive orphan cleanup, reposition via
Remove+UpdateAssemblies+Add, shared instances)?

Protocol per operation:
  snapshot A -> NewCommand -> op -> CommitCommand -> snapshot B
  -> Undo -> verify structure == A -> Redo -> verify structure == B

Snapshots are canonical structure strings: every free shape walked
recursively through component references, recording name + referred
entry + location translation at each node. Equality of snapshots is
the pass criterion.

If all cases PASS: the remaining integration work is mechanical --
wrap the ops in transactions in the app, wire Ctrl+Z/Ctrl+Y, refresh
(parse_doc + build_tree + redraw) after Undo/Redo, plus the one
deferred design decision (reconciling with the Position dialog's
Back button). Any FAIL names exactly which operation needs special
handling.

Run: uv run smoke_test_undo_redo_full.py
(Headless -- imports docmodel but never instantiates any GUI.)
"""

import docmodel
from docmodel import (DocModel, create_doc, set_label_name,
                      get_label_name)

from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Trsf, gp_Vec, gp_Pnt, gp_Dir, gp_Ax2
from OCP.TopLoc import TopLoc_Location
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor

COLOR = Quantity_Color(0.6, 0.6, 0.4, Quantity_TypeOfColor.Quantity_TOC_RGB)


def snapshot(dm):
    """Canonical structure string for the whole document."""
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(dm.doc.Main())
    lines = []

    def walk(label, depth):
        loc = shape_tool.GetShape_s(label).Location()
        t = loc.Transformation().TranslationPart()
        ref = TDF_Label()
        has_ref = shape_tool.GetReferredShape_s(label, ref)
        refpart = ""
        target = label
        if has_ref:
            from OCP.TCollection import TCollection_AsciiString
            from OCP.TDF import TDF_Tool
            e = TCollection_AsciiString()
            TDF_Tool.Entry_s(ref, e)
            refpart = f" ->{e.ToCString()}"
            target = ref
        lines.append(f"{'  ' * depth}{get_label_name(label)!r}{refpart} "
                     f"({t.X():.3f},{t.Y():.3f},{t.Z():.3f})")
        kids = TDF_LabelSequence()
        shape_tool.GetComponents_s(target, kids, False)
        for i in range(1, kids.Length() + 1):
            walk(kids.Value(i), depth + 1)

    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    for i in range(1, free.Length() + 1):
        walk(free.Value(i), 0)
    return "\n".join(lines)


def run_case(dm, case_name, op):
    """snapshot A -> transaction(op) -> snapshot B -> Undo -> ==A ->
    Redo -> ==B. Returns True on full pass."""
    before = snapshot(dm)
    dm.doc.NewCommand()
    try:
        op()
    except Exception as e:
        dm.doc.AbortCommand()
        print(f"[{case_name}] OP RAISED: {e} -- FAIL")
        return False
    dm.doc.CommitCommand()
    after = snapshot(dm)

    ok = True
    if not dm.doc.Undo():
        print(f"[{case_name}] Undo() returned False -- FAIL")
        ok = False
    else:
        dm.parse_doc()
        undone = snapshot(dm)
        if undone != before:
            print(f"[{case_name}] UNDO MISMATCH -- FAIL")
            print("  expected (before-op):")
            for ln in before.splitlines():
                print(f"    {ln}")
            print("  got (after undo):")
            for ln in undone.splitlines():
                print(f"    {ln}")
            ok = False

    if ok:
        if not dm.doc.Redo():
            print(f"[{case_name}] Redo() returned False -- FAIL")
            ok = False
        else:
            dm.parse_doc()
            redone = snapshot(dm)
            if redone != after:
                print(f"[{case_name}] REDO MISMATCH -- FAIL")
                print("  expected (after-op):")
                for ln in after.splitlines():
                    print(f"    {ln}")
                print("  got (after redo):")
                for ln in redone.splitlines():
                    print(f"    {ln}")
                ok = False

    print(f"[{case_name}] {'PASS' if ok else 'FAIL'}")
    return ok


def build_source_doc():
    """A small external assembly with a shared leaf, standing in for
    an imported STEP file (drives add_component_from_label's rebuild
    path, memo and all)."""
    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    leaf = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    leaf_label = shape_tool.AddShape(leaf, False)
    set_label_name(leaf_label, "src_leaf")
    assy = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy)
    assy_label = shape_tool.AddShape(assy, True)
    set_label_name(assy_label, "src_assembly")
    c1 = shape_tool.AddComponent(assy_label, leaf_label, TopLoc_Location())
    set_label_name(c1, "src_leaf_1")
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(5.0, 0.0, 0.0))
    c2 = shape_tool.AddComponent(assy_label, leaf_label, TopLoc_Location(t))
    set_label_name(c2, "src_leaf_2")
    shape_tool.UpdateAssemblies()
    return doc, app, assy_label


def main():
    dm = DocModel()
    # Undo history must be enabled BEFORE any transaction
    dm.doc.SetUndoLimit(50)

    # SETUP (outside any transaction -- not recorded in undo history):
    # seed the '/' root and a baseline part, so every case's Undo
    # returns to a stable non-empty baseline. (Undoing back to a
    # completely EMPTY document is itself a legitimate state the app
    # must handle -- parse_doc gained that guard from this test's
    # first run -- but the gauge measures per-operation semantics
    # against a realistic session, not the empty-doc edge.)
    seed = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(50.0, 50.0, 0.0), gp_Dir(0.0, 0.0, 1.0)),
        4.0, 12.0).Shape()
    dm.add_component(seed, "seed", COLOR)
    dm.parse_doc()

    results = []

    # --- CASE 1: add a native part ---
    box = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    holder = {}

    def op_add():
        holder['uid_box'] = dm.add_component(box, "box", COLOR)
    results.append(run_case(dm, "1 add_component", op_add))

    # Re-add outside test bookkeeping? No -- the Redo left it in
    # place, so the part exists for subsequent cases. Find its uid
    # fresh (uids may differ after undo/redo cycles).
    dm.parse_doc()
    box_uid = next((u for u, d in dm.part_dict.items()
                    if d.get('name', '').startswith('box')), None)
    print(f"    (box uid now {box_uid})")

    # --- CASE 2: rename it ---
    results.append(run_case(dm, "2 change_label_name",
                            lambda: dm.change_label_name(box_uid,
                                                         "renamed-box")))

    # --- CASE 3: create a new (empty) assembly under root ---
    dm.parse_doc()
    root_uid = next((u for u in dm.label_dict
                     if not dm.label_dict[u].get('parent_uid')), None)
    results.append(run_case(dm, "3 create_new_assembly",
                            lambda: dm.create_new_assembly(root_uid,
                                                           "sub-asy")))

    # --- CASE 4: shared instance of the box ---
    dm.parse_doc()
    box_uid = next((u for u, d in dm.part_dict.items()
                    if 'box' in d.get('name', '')), None)
    results.append(run_case(dm, "4 create_shared_instance",
                            lambda: dm.create_shared_instance(box_uid)))

    # --- CASE 5: reposition (the Remove+UpdateAssemblies+Add cycle) ---
    dm.parse_doc()
    box_uid = next((u for u, d in dm.part_dict.items()
                    if 'box' in d.get('name', '')), None)
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(25.0, 0.0, 0.0))
    results.append(run_case(dm, "5 set_component_location",
                            lambda: dm.set_component_location(
                                box_uid, TopLoc_Location(t))))

    # --- CASE 6: rebuild-IMPORT of an external assembly (memo path) ---
    src_doc, src_app, src_assy = build_source_doc()
    results.append(run_case(dm, "6 add_component_from_label",
                            lambda: dm.add_component_from_label(
                                src_assy, "imported")))

    # --- CASE 7: delete with orphan cleanup (delete the import) ---
    dm.parse_doc()
    imp_uid = next((u for u in dm.label_dict
                    if 'imported' in dm.label_dict[u].get('name', '')
                    or 'src_assembly' in dm.label_dict[u].get('name', '')),
                   None)
    if imp_uid is None:
        print("[7 delete_component] could not find imported item -- SKIP")
        results.append(False)
    else:
        results.append(run_case(dm, "7 delete_component",
                                lambda: dm.delete_component(imp_uid)))

    print()
    print("=" * 60)
    npass = sum(1 for r in results if r)
    print(f"RESULT: {npass}/{len(results)} cases pass")
    if npass == len(results):
        print("ALL PASS -- OCAF undo/redo handles Kodacad's full")
        print("operation vocabulary. Integration is mechanical:")
        print("transaction-wrap the ops, wire Ctrl+Z/Ctrl+Y, refresh")
        print("after Undo/Redo, and settle the Position-dialog")
        print("Back-button design question.")
    else:
        print("Failures above name exactly which operations need")
        print("special handling before integration.")

    # Clean shutdown: exit-time garbage collection destroys the OCAF
    # documents in an order OCCT dislikes (Standard_NullObject ->
    # terminate, AFTER all results printed -- cosmetic, but a smoke
    # test should exit clean). Close documents explicitly, then exit
    # without running Python's teardown.
    import os
    try:
        dm.app.Close(dm.doc)
    except Exception:
        pass
    try:
        src_app.Close(src_doc)
    except Exception:
        pass
    os._exit(0 if npass == len(results) else 1)


if __name__ == "__main__":
    main()
