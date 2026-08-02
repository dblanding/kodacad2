"""
smoke_test_freecad_strategy.py -- does FreeCAD's confirmed import/
export strategy fix Kodacad's assembly-import-reposition-persistence
bug?

FreeCAD's real source code (ExportOCAF::saveShape, confirmed directly
by reading it) never uses XCAFDoc_Editor::Extract_s or any other
cross-document label copying. On import, it reads shape + name +
location out of the source document as plain DATA into its own
native object model, discarding the original document entirely. On
export, it rebuilds a completely fresh XCAF document from scratch,
using ordinary same-document AddShape/AddComponent calls. Every shape
FreeCAD ever writes is, from that document's own perspective, freshly
and natively created -- exactly matching the case this project has
already confirmed is fully reliable in Kodacad (content built up
natively in a session, never imported via Extract_s, has never shown
this bug).

CRITICAL CAUTION this test is specifically designed to check: Session
29 already tried something in this spirit (a native-rebuild-with-
recursion approach) and it regressed internal sharing within imported
files -- rebuilding naively duplicated shared geometry instead of
preserving the sharing. This test's rebuild function uses a memo dict
keyed by source entry, so a shape referenced by MULTIPLE components
(a genuinely shared part) is rebuilt ONCE in the destination and
referenced twice, not duplicated. This is the specific thing worth
confirming works BEFORE touching docmodel.py.

What this tests, end to end, matching Kodacad's real workflow:
1. Build a SOURCE document (standing in for "an imported STEP file")
   with an assembly containing a genuinely SHARED leaf part (same
   part instanced twice, at different locations).
2. Rebuild that structure NATIVELY into a DESTINATION document
   (standing in for "the current Kodacad session") -- reading as
   data, never calling Extract_s.
3. Add the rebuilt assembly as a component of the destination's own
   existing content (matching add_component_from_label's real role).
4. REPOSITION it via RemoveComponent + AddComponent with a new
   location -- the exact pattern that has always been the failure
   point in every prior attempt (Sessions 14-30+).
5. Write to STEP, re-read fresh, and check: does the repositioned
   component's name/location survive? Does the shared-instance
   structure survive (both instances still referencing the SAME
   underlying part, not duplicated)?

Run: uv run smoke_test_freecad_strategy.py
"""

from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence, TDF_Tool
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location
from OCP.STEPCAFControl import STEPCAFControl_Writer, STEPCAFControl_Reader
from OCP.STEPControl import STEPControl_AsIs
from OCP.XSControl import XSControl_WorkSession
from OCP.IFSelect import IFSelect_RetDone


def create_doc():
    doc_format = "BinXCAF"
    doc = TDocStd_Document(TCollection_ExtendedString(doc_format))
    app = XCAFApp_Application.GetApplication_s()
    app.NewDocument(TCollection_ExtendedString(doc_format), doc)
    BinXCAFDrivers.DefineFormat_s(app)
    return doc, app


def set_name(label, name):
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))


def get_name(label):
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


def get_entry(label):
    entry = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, entry)
    return entry.ToCString()


def dump(shape_tool, label, depth=0):
    loc = shape_tool.GetShape_s(label).Location()
    t = loc.Transformation().TranslationPart()
    print(f"{'  '*depth}name={get_name(label)!r} entry={get_entry(label)} "
          f"loc=({t.X():.3f}, {t.Y():.3f}, {t.Z():.3f})")
    kids = TDF_LabelSequence()
    shape_tool.GetComponents_s(label, kids, False)
    for i in range(1, kids.Length() + 1):
        dump(shape_tool, kids.Value(i), depth + 1)


def write_step(doc, fname):
    ws = XSControl_WorkSession()
    writer = STEPCAFControl_Writer(ws, False)
    writer.Transfer(doc, STEPControl_AsIs)
    status = writer.Write(fname)
    assert status == IFSelect_RetDone


def read_step(fname):
    doc, app = create_doc()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    reader.SetNameMode(True)
    reader.SetMatMode(True)
    status = reader.ReadFile(fname)
    assert status == IFSelect_RetDone
    reader.Transfer(doc)
    return doc


def build_source_assembly():
    """A leaf part shared TWICE inside an assembly -- standing in for
    'an imported STEP file' that itself has internal sharing."""
    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    leaf = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    leaf_label = shape_tool.AddShape(leaf, False)
    set_name(leaf_label, "leaf_part")

    assy_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy_shape)
    assy_label = shape_tool.AddShape(assy_shape, True)
    set_name(assy_label, "source_assembly")

    t1 = gp_Trsf()
    t1.SetTranslation(gp_Vec(0.0, 0.0, 0.0))
    c1 = shape_tool.AddComponent(assy_label, leaf_label, TopLoc_Location(t1))
    set_name(c1, "leaf_instance_1")

    t2 = gp_Trsf()
    t2.SetTranslation(gp_Vec(5.0, 0.0, 0.0))
    c2 = shape_tool.AddComponent(assy_label, leaf_label, TopLoc_Location(t2))
    set_name(c2, "leaf_instance_2")

    shape_tool.UpdateAssemblies()
    return doc, app, shape_tool, assy_label


def rebuild_natively(src_shape_tool, src_label, dst_shape_tool, memo):
    """
    Recursively read src_label's structure as DATA and rebuild it
    NATIVELY in the destination document via AddShape/AddComponent --
    FreeCAD's confirmed strategy, instead of XCAFDoc_Editor::Extract_s
    cross-document label copying.

    memo: dict mapping source entry -> destination label. A shape
    referenced by MULTIPLE components (a genuinely shared part) is
    rebuilt ONCE and referenced twice in the destination, not
    duplicated -- the specific thing Session 29's attempt got wrong.

    Returns the destination label for src_label's own underlying
    shape (not a component -- the caller adds it as a component with
    whatever location applies at that level).
    """
    entry = get_entry(src_label)
    if entry in memo:
        return memo[entry]

    if src_shape_tool.IsAssembly_s(src_label):
        empty = TopoDS_Compound()
        BRep_Builder().MakeCompound(empty)
        dst_label = dst_shape_tool.AddShape(empty, True)
        set_name(dst_label, get_name(src_label))
        memo[entry] = dst_label

        children = TDF_LabelSequence()
        src_shape_tool.GetComponents_s(src_label, children, False)
        for i in range(1, children.Length() + 1):
            child_comp = children.Value(i)
            child_ref = TDF_Label()
            src_shape_tool.GetReferredShape_s(child_comp, child_ref)
            child_dst_label = rebuild_natively(src_shape_tool, child_ref,
                                               dst_shape_tool, memo)
            child_loc = src_shape_tool.GetShape_s(child_comp).Location()
            new_comp = dst_shape_tool.AddComponent(dst_label, child_dst_label,
                                                    child_loc)
            set_name(new_comp, get_name(child_comp))
    else:
        shape = src_shape_tool.GetShape_s(src_label)
        dst_label = dst_shape_tool.AddShape(shape, False)
        set_name(dst_label, get_name(src_label))
        memo[entry] = dst_label

    return dst_label


def main():
    print("=" * 70)
    print("Building SOURCE assembly (standing in for an imported STEP file)")
    print("=" * 70)
    src_doc, src_app, src_shape_tool, src_assy_label = build_source_assembly()
    dump(src_shape_tool, src_assy_label)

    print()
    print("=" * 70)
    print("Rebuilding NATIVELY into a DESTINATION document (FreeCAD's")
    print("strategy: read as data, AddShape/AddComponent -- no Extract_s)")
    print("=" * 70)
    dst_doc, dst_app = create_doc()
    dst_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(dst_doc.Main())
    base = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    base_label = dst_shape_tool.AddShape(base, False)
    set_name(base_label, "base")

    memo = {}
    rebuilt_assy_label = rebuild_natively(src_shape_tool, src_assy_label,
                                          dst_shape_tool, memo)
    imported_comp = dst_shape_tool.AddComponent(base_label, rebuilt_assy_label,
                                                TopLoc_Location())
    set_name(imported_comp, "assembly_imported")
    dst_shape_tool.UpdateAssemblies()

    print("\nAfter native rebuild + import, before reposition:")
    dump(dst_shape_tool, base_label)

    print()
    print("=" * 70)
    print("Repositioning (RemoveComponent + AddComponent) -- the exact")
    print("pattern that has always been the failure point before")
    print("=" * 70)
    ref_label = TDF_Label()
    dst_shape_tool.GetReferredShape_s(imported_comp, ref_label)
    dst_shape_tool.RemoveComponent(imported_comp)

    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    new_loc = TopLoc_Location(t)
    new_comp = dst_shape_tool.AddComponent(base_label, ref_label, new_loc)
    set_name(new_comp, "assembly_moved")
    dst_shape_tool.UpdateAssemblies()

    print("\nAfter reposition, BEFORE any STEP write (in-memory, correct):")
    dump(dst_shape_tool, base_label)

    write_step(dst_doc, "freecad_strategy_test.stp")
    fresh_doc = read_step("freecad_strategy_test.stp")
    fresh_tool = XCAFDoc_DocumentTool.ShapeTool_s(fresh_doc.Main())
    free_labels = TDF_LabelSequence()
    fresh_tool.GetFreeShapes(free_labels)

    print()
    print("=" * 70)
    print("After STEP write + fresh read:")
    print("=" * 70)
    for i in range(1, free_labels.Length() + 1):
        dump(fresh_tool, free_labels.Value(i))

    print("\nExpected: 'assembly_moved' at (50.000, 0.000, 0.000), with")
    print("children 'leaf_instance_1' at (0,0,0) and 'leaf_instance_2' at")
    print("(5,0,0) -- name AND location surviving this time.")

    print()
    print("=" * 70)
    print("Explicit sharing check (dump() alone can't show this --")
    print("checking whether the two instances reference the SAME")
    print("underlying shape, or got silently duplicated -- Session 29's")
    print("regression, which would defeat the point of this approach)")
    print("=" * 70)
    moved = None
    for i in range(1, free_labels.Length() + 1):
        if get_name(free_labels.Value(i)) == "assembly_moved":
            moved = free_labels.Value(i)
    if moved is None:
        print("Could not find 'assembly_moved' in the reloaded file -- "
              "see the dump above; name may not have survived at all.")
    else:
        kids = TDF_LabelSequence()
        fresh_tool.GetComponents_s(moved, kids, False)
        ref_entries = []
        for i in range(1, kids.Length() + 1):
            child_comp = kids.Value(i)
            child_ref = TDF_Label()
            fresh_tool.GetReferredShape_s(child_comp, child_ref)
            ref_entries.append((get_name(child_comp), get_entry(child_ref)))
        for name, ref_entry in ref_entries:
            print(f"  {name}: refers to entry {ref_entry}")
        if len(ref_entries) == 2 and ref_entries[0][1] == ref_entries[1][1]:
            print("\n  SHARING PRESERVED -- both instances reference the "
                 "same underlying part.")
        elif len(ref_entries) == 2:
            print("\n  SHARING LOST -- the two instances reference DIFFERENT "
                 "entries, meaning the geometry got duplicated during the "
                 "native rebuild (the Session 29 regression).")
        else:
            print(f"\n  Expected 2 children, found {len(ref_entries)} -- "
                 "structure did not survive as expected.")


if __name__ == "__main__":
    main()
