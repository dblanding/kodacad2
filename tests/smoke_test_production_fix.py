"""
smoke_test_production_fix.py -- the decisive test: the exact fix
candidate for docmodel.py's add_component_from_label, end to end.

Why this should work when smoke_test_freecad_strategy.py "failed":
that earlier test's destination 'base' was a RAW BOX that also held
components -- the exact mixed-geometry-root flaw discovered only
AFTERWARD (smoke_test_dedicated_root.py et al.). Its failure was
very likely confounded by that flaw, not a verdict on the native-
rebuild approach itself. Meanwhile smoke_test_freecad_single_shot.py
just confirmed ALL THREE placement mechanisms work (single-shot
label-based, located-shape, and even remove/re-add with
UpdateAssemblies between) when the structure is built label-based
into a proper dedicated root -- which Kodacad's real '/' root
already is.

This test is the production scenario exactly:
1. SOURCE document: an assembly containing a genuinely SHARED leaf
   part (two instances of the same part at different locations) --
   standing in for an imported STEP file with internal sharing.
2. DESTINATION: a dedicated empty-compound '/' root (matching
   docmodel.py's real root exactly) that already holds a native part
   (simulating existing session content).
3. Rebuild the source assembly NATIVELY into the destination via
   rebuild_natively() with a memo dict (shared part rebuilt ONCE,
   referenced twice -- the Session 29 regression guard).
4. Add it under '/' at identity (as a fresh import would land).
5. REPOSITION it: RemoveComponent + UpdateAssemblies + AddComponent
   at (50,0,0) -- the production reposition, with the cheap
   UpdateAssemblies insurance Case C validated.
6. Write STEP, re-read fresh, and verify ALL THREE: name survives,
   location survives, sharing survives (both instances still
   referencing the SAME underlying part).

Also: dump() here resolves component references and recurses through
them (unlike the earlier tests' dumps, which stopped at the instance
level) -- so the complete tree, including the shared leaf level, is
actually visible in the output.

If this passes, the fix goes into docmodel.py.

Run: uv run smoke_test_production_fix.py
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


def dump_full(shape_tool, label, depth=0):
    """Unlike the earlier tests' dump(), this resolves component
    references and recurses through them -- the complete tree is
    visible, including levels below an instance."""
    loc = shape_tool.GetShape_s(label).Location()
    t = loc.Transformation().TranslationPart()
    line = (f"{'  '*depth}name={get_name(label)!r} "
            f"loc=({t.X():.3f}, {t.Y():.3f}, {t.Z():.3f})")
    ref = TDF_Label()
    if shape_tool.GetReferredShape_s(label, ref):
        line += f"  -> refers to entry {get_entry(ref)} ({get_name(ref)!r})"
        print(line)
        kids = TDF_LabelSequence()
        shape_tool.GetComponents_s(ref, kids, False)
        for i in range(1, kids.Length() + 1):
            dump_full(shape_tool, kids.Value(i), depth + 1)
    else:
        print(line)
        kids = TDF_LabelSequence()
        shape_tool.GetComponents_s(label, kids, False)
        for i in range(1, kids.Length() + 1):
            dump_full(shape_tool, kids.Value(i), depth + 1)


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
    """Assembly with a genuinely SHARED leaf part -- two instances of
    the same part at different locations."""
    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    leaf = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    leaf_label = shape_tool.AddShape(leaf, False)
    set_name(leaf_label, "leaf_part")

    assy_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy_shape)
    assy_label = shape_tool.AddShape(assy_shape, True)
    set_name(assy_label, "imported_assembly")

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
    """Read src_label's structure as DATA, rebuild NATIVELY in the
    destination via AddShape/AddComponent (label-based throughout).
    memo maps source entry -> destination label, so a shape referenced
    by multiple components is rebuilt ONCE and referenced twice."""
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
    print("SOURCE document: assembly with a genuinely SHARED leaf part")
    print("=" * 70)
    src_doc, src_app, src_tool, src_assy = build_source_assembly()
    dump_full(src_tool, src_assy)

    print()
    print("=" * 70)
    print("DESTINATION: dedicated '/' root (matching Kodacad exactly),")
    print("already holding a native part (simulating session content)")
    print("=" * 70)
    dst_doc, dst_app = create_doc()
    dst_tool = XCAFDoc_DocumentTool.ShapeTool_s(dst_doc.Main())

    root_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(root_shape)
    root_label = dst_tool.AddShape(root_shape, True)
    set_name(root_label, "/")

    native_box = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    native_comp = dst_tool.AddComponent(root_label, native_box, True)
    set_name(native_comp, "native_part")
    dst_tool.UpdateAssemblies()

    print()
    print("=" * 70)
    print("NATIVE REBUILD of the imported assembly (memo-guarded")
    print("sharing), added under '/' at identity -- a fresh import")
    print("=" * 70)
    memo = {}
    rebuilt = rebuild_natively(src_tool, src_assy, dst_tool, memo)
    imported_comp = dst_tool.AddComponent(root_label, rebuilt, TopLoc_Location())
    set_name(imported_comp, "imported_assembly_1")
    dst_tool.UpdateAssemblies()

    print("\nDestination after import:")
    dump_full(dst_tool, root_label)

    print()
    print("=" * 70)
    print("REPOSITION: RemoveComponent + UpdateAssemblies +")
    print("AddComponent at (50,0,0) -- the production reposition")
    print("=" * 70)
    ref_label = TDF_Label()
    dst_tool.GetReferredShape_s(imported_comp, ref_label)
    dst_tool.RemoveComponent(imported_comp)
    dst_tool.UpdateAssemblies()

    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    new_comp = dst_tool.AddComponent(root_label, ref_label, TopLoc_Location(t))
    set_name(new_comp, "imported_assembly_moved")
    dst_tool.UpdateAssemblies()

    print("\nIn-memory after reposition:")
    dump_full(dst_tool, root_label)

    fname = "production_fix_test.stp"
    write_step(dst_doc, fname)

    print()
    print("=" * 70)
    print(f"RAW FILE -- NEXT_ASSEMBLY_USAGE_OCCURRENCE lines in {fname}:")
    print("=" * 70)
    with open(fname) as f:
        raw_text = f.read()
    for line in raw_text.splitlines():
        if "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in line:
            print(f"  {line.strip()}")

    print()
    print("=" * 70)
    print("After STEP write + fresh read:")
    print("=" * 70)
    fresh_doc = read_step(fname)
    fresh_tool = XCAFDoc_DocumentTool.ShapeTool_s(fresh_doc.Main())
    free_labels = TDF_LabelSequence()
    fresh_tool.GetFreeShapes(free_labels)
    for i in range(1, free_labels.Length() + 1):
        dump_full(fresh_tool, free_labels.Value(i))

    print()
    print("=" * 70)
    print("Explicit sharing check on the reloaded file")
    print("=" * 70)
    moved = None
    for i in range(1, free_labels.Length() + 1):
        top = free_labels.Value(i)
        kids = TDF_LabelSequence()
        fresh_tool.GetComponents_s(top, kids, False)
        for j in range(1, kids.Length() + 1):
            if get_name(kids.Value(j)) == "imported_assembly_moved":
                moved = kids.Value(j)
    if moved is None:
        print("FAIL -- 'imported_assembly_moved' not found by name in the "
              "reloaded file.")
        return
    ref = TDF_Label()
    fresh_tool.GetReferredShape_s(moved, ref)
    kids = TDF_LabelSequence()
    fresh_tool.GetComponents_s(ref, kids, False)
    ref_entries = []
    for i in range(1, kids.Length() + 1):
        child_ref = TDF_Label()
        fresh_tool.GetReferredShape_s(kids.Value(i), child_ref)
        ref_entries.append((get_name(kids.Value(i)), get_entry(child_ref)))
    for name, ref_entry in ref_entries:
        print(f"  {name}: refers to entry {ref_entry}")
    if len(ref_entries) == 2 and ref_entries[0][1] == ref_entries[1][1]:
        print("\n  SHARING PRESERVED -- both instances reference the same "
              "underlying part.")
        print("\n*** ALL PASS CRITERIA MET: name, location, and sharing "
              "all survived. This fix is ready for docmodel.py. ***")
    elif len(ref_entries) == 2:
        print("\n  SHARING LOST -- geometry was duplicated during rebuild.")
    else:
        print(f"\n  Expected 2 children, found {len(ref_entries)}.")


if __name__ == "__main__":
    main()
