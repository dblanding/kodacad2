"""
smoke_test_undo_redo.py -- does OCAF's built-in transaction-based
undo/redo (NewCommand/Undo/Redo) correctly track the SPECIFIC XCAF
operations Kodacad's docmodel.py actually performs?

Why test against real operations rather than a trivial attribute
change: OCAF's undo/redo is documented and known to work for simple
attribute changes (see the OCCT forum threads on this). What's NOT
already confirmed is whether it correctly tracks XCAF-level structural
operations specifically -- AddComponent (creating a new component
under an assembly) and the RemoveComponent+AddComponent pattern
docmodel.py's set_component_location() uses for repositioning (see
Session 22 onward). If OCAF's transaction system doesn't cleanly
capture these, undo/redo would need custom handling in Kodacad rather
than being usable out of the box -- worth knowing before assuming
either way.

Undo/redo history itself does NOT persist across save/load (confirmed
directly: a real OCCT forum thread on exactly this question -- "There
is no possibility to store the undo/redo information in the OCCT
TDocStd_Document"). That's a session-only feature by design, matching
how undo/redo works in most CAD tools anyway -- not a limitation
specific to this approach.

Run: uv run smoke_test_undo_redo.py
"""

from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.TCollection import TCollection_ExtendedString
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_LabelSequence, TDF_Label
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location


def create_doc():
    """Exactly matches docmodel.py's own create_doc()."""
    doc_format = "BinXCAF"
    doc = TDocStd_Document(TCollection_ExtendedString(doc_format))
    app = XCAFApp_Application.GetApplication_s()
    app.NewDocument(TCollection_ExtendedString(doc_format), doc)
    BinXCAFDrivers.DefineFormat_s(app)
    return doc, app


def set_name(label, name):
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))


def get_name(label):
    """Matches docmodel.py's own get_label_name() exactly."""
    try:
        name = TDataStd_Name.Get_s(label)
        if name is not None:
            return str(name.ToExtString())
    except Exception:
        pass
    try:
        name_attr = TDataStd_Name()
        found = label.FindAttribute(TDataStd_Name.GetID_s(), name_attr)
        if found:
            return str(name_attr.Get().ToExtString())
    except Exception:
        pass
    return ""


def dump(shape_tool, label, depth=0):
    loc = shape_tool.GetShape_s(label).Location()
    t = loc.Transformation().TranslationPart()
    print(f"{'  '*depth}name={get_name(label)!r} "
          f"loc=({t.X():.3f}, {t.Y():.3f}, {t.Z():.3f})")
    kids = TDF_LabelSequence()
    shape_tool.GetComponents_s(label, kids, False)
    for i in range(1, kids.Length() + 1):
        dump(shape_tool, kids.Value(i), depth + 1)


def dump_assembly(shape_tool, assy_label, header):
    print(f"\n{header}")
    dump(shape_tool, assy_label)


def get_last_component(shape_tool, assembly_label):
    comps = TDF_LabelSequence()
    shape_tool.GetComponents_s(assembly_label, comps, False)
    return comps.Value(comps.Length())


def main():
    print("=" * 70)
    print("SMOKE TEST 2: OCAF undo/redo on real XCAF operations")
    print("=" * 70)

    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    # Undo is disabled by default -- must be explicitly enabled, and
    # takes effect starting with the NEXT NewCommand() call.
    doc.SetUndoLimit(10)

    box_shape = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    box_label = shape_tool.AddShape(box_shape, False)
    set_name(box_label, "box_part")

    assy_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy_shape)
    assy_label = shape_tool.AddShape(assy_shape, True)
    set_name(assy_label, "top_assembly")
    shape_tool.UpdateAssemblies()

    doc.NewCommand()  # opens the FIRST trackable transaction
    dump_assembly(shape_tool, assy_label, "Initial state (empty assembly):")

    # --- Transaction 1: AddComponent (docmodel.py's add_component_
    # from_label / normal part-add path) ---
    t1 = gp_Trsf()
    t1.SetTranslation(gp_Vec(0.0, 0.0, 0.0))
    comp1 = shape_tool.AddComponent(assy_label, box_label, TopLoc_Location(t1))
    set_name(comp1, "box_instance")
    shape_tool.UpdateAssemblies()
    doc.NewCommand()  # commits transaction 1, opens transaction 2
    dump_assembly(shape_tool, assy_label, "After AddComponent (transaction 1 committed):")

    # --- Transaction 2: RemoveComponent + AddComponent (docmodel.py's
    # set_component_location() reposition pattern, Session 22 onward)
    # ---
    comp_to_move = get_last_component(shape_tool, assy_label)
    ref_label = TDF_Label()
    shape_tool.GetReferredShape_s(comp_to_move, ref_label)
    shape_tool.RemoveComponent(comp_to_move)
    t2 = gp_Trsf()
    t2.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    new_comp = shape_tool.AddComponent(assy_label, ref_label, TopLoc_Location(t2))
    set_name(new_comp, "box_instance_moved")
    shape_tool.UpdateAssemblies()
    doc.NewCommand()  # commits transaction 2
    dump_assembly(shape_tool, assy_label, "After reposition (transaction 2 committed):")

    print(f"\nGetAvailableUndos(): {doc.GetAvailableUndos()} "
         f"(expect 2 -- one per committed transaction)")

    # --- Undo the reposition ---
    print("\nCalling Undo() once (should revert the reposition)...")
    undo_ok = doc.Undo()
    print(f"Undo() returned: {undo_ok}")
    dump_assembly(shape_tool, assy_label, "State after 1 undo (expect box_instance at origin):")

    # --- Undo the AddComponent ---
    print("\nCalling Undo() again (should revert the AddComponent, "
         "back to empty assembly)...")
    undo_ok2 = doc.Undo()
    print(f"Undo() returned: {undo_ok2}")
    dump_assembly(shape_tool, assy_label, "State after 2 undos (expect EMPTY assembly):")

    # --- Redo both ---
    print("\nCalling Redo() twice (should replay both transactions)...")
    redo_ok1 = doc.Redo()
    print(f"Redo() #1 returned: {redo_ok1}")
    redo_ok2 = doc.Redo()
    print(f"Redo() #2 returned: {redo_ok2}")
    dump_assembly(shape_tool, assy_label,
                 "State after 2 redos (expect box_instance_moved at (50,0,0), "
                 "matching the 'After reposition' dump above exactly):")


if __name__ == "__main__":
    main()
