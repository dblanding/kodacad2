"""
smoke_test_freecad_single_shot.py -- THE pivotal test, per Doug's
FreeCAD observation: in FreeCAD, manual-lathe was moved while still a
FREE item, then added to the Assembly exactly ONCE, already at its
final position. The "add as component, then reposition via
RemoveComponent+AddComponent" two-step -- which every failing test in
this entire investigation has done -- never happens in FreeCAD's
workflow at all.

Three cases, one variable each:

CASE A -- label-based AddComponent, ONCE, at the final location.
    Same corrected structure as smoke_test_corrected_assembly.py
    (dedicated '/' root, two-level assembly), but the component is
    created a single time with its final (50,0,0) location -- no
    prior add-at-identity, no RemoveComponent, ever. If this works
    where corrected_assembly's reposition failed, the NAUO placement
    mechanism itself is fine and the fragility is specifically in
    the remove/re-add cycle.

CASE B -- shape-based AddComponent of a PRE-LOCATED shape.
    The shape-based overload takes no location parameter -- but a
    TopoDS_Shape can carry its own location (shape.Moved(loc)), and
    XCAF splits a located shape into prototype-at-identity plus
    instance-carrying-the-location. That is exactly how
    STEPCAFControl_Reader itself constructs components when reading
    a file -- i.e. the construction pattern underlying
    l-bracket-assembly, whose repositioning has been confirmed
    reliable throughout this project -- and very likely what
    FreeCAD's export effectively produces too (each object added
    once, already carrying its final placement).

CASE C -- the known-failing remove+re-add cycle, but with
    UpdateAssemblies() called BETWEEN the RemoveComponent and the
    AddComponent. A cheap probe of the "RemoveComponent leaves stale
    internal state that poisons the next AddComponent on the same
    referred shape" theory. If A works and C still fails, the stale
    state isn't flushed by UpdateAssemblies and the practical fix
    for Kodacad is to make repositioning look like Case A/B instead.

Run: uv run smoke_test_freecad_single_shot.py
"""

from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.TCollection import TCollection_ExtendedString
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
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


def dump(shape_tool, label, depth=0):
    loc = shape_tool.GetShape_s(label).Location()
    t = loc.Transformation().TranslationPart()
    print(f"{'  '*depth}name={get_name(label)!r} "
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


def make_root(shape_tool):
    """Dedicated empty-compound '/' root, matching docmodel.py."""
    root_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(root_shape)
    root_label = shape_tool.AddShape(root_shape, True)
    set_name(root_label, "/")
    return root_label


def make_sub_assembly(shape_tool):
    """Two-level content: sub_assembly containing sub_box_1_1."""
    box1 = BRepPrimAPI_MakeBox(3.0, 3.0, 3.0).Shape()
    box1_label = shape_tool.AddShape(box1, False)
    set_name(box1_label, "sub_box_1")

    assy_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy_shape)
    assy_label = shape_tool.AddShape(assy_shape, True)
    set_name(assy_label, "sub_assembly")
    c1 = shape_tool.AddComponent(assy_label, box1_label, TopLoc_Location())
    set_name(c1, "sub_box_1_1")
    shape_tool.UpdateAssemblies()
    return assy_label


def target_location():
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    return TopLoc_Location(t)


def finish(doc, shape_tool, root_label, fname, case_name):
    """Shared: dump in-memory, write, grep raw NAUO lines, read back,
    dump reloaded."""
    print(f"\nIn-memory state before write:")
    dump(shape_tool, root_label)

    write_step(doc, fname)

    with open(fname) as f:
        raw_text = f.read()
    nauo_lines = [line.strip() for line in raw_text.splitlines()
                  if "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in line]
    print(f"\nRAW FILE -- NEXT_ASSEMBLY_USAGE_OCCURRENCE lines "
          f"({len(nauo_lines)}):")
    for line in nauo_lines:
        print(f"  {line}")

    fresh_doc = read_step(fname)
    fresh_tool = XCAFDoc_DocumentTool.ShapeTool_s(fresh_doc.Main())
    free_labels = TDF_LabelSequence()
    fresh_tool.GetFreeShapes(free_labels)
    print(f"\nAfter fresh read ({free_labels.Length()} free shape(s)):")
    for i in range(1, free_labels.Length() + 1):
        dump(fresh_tool, free_labels.Value(i))

    print(f"\n[{case_name}] PASS criteria: 'sub_assembly_moved' present "
          f"at (50.000, 0.000, 0.000) with child 'sub_box_1_1'.")


def case_a():
    print("=" * 70)
    print("CASE A: label-based AddComponent, ONCE, at final location")
    print("(never repositioned -- no prior add, no RemoveComponent, ever)")
    print("=" * 70)
    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    root_label = make_root(shape_tool)
    assy_label = make_sub_assembly(shape_tool)

    comp = shape_tool.AddComponent(root_label, assy_label, target_location())
    set_name(comp, "sub_assembly_moved")
    shape_tool.UpdateAssemblies()

    finish(doc, shape_tool, root_label, "single_shot_A.stp", "CASE A")


def case_b():
    print()
    print("=" * 70)
    print("CASE B: shape-based AddComponent of a PRE-LOCATED shape")
    print("(shape.Moved(loc) -- mimicking how the STEP reader itself,")
    print("and FreeCAD's export, construct components)")
    print("=" * 70)
    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    root_label = make_root(shape_tool)
    assy_label = make_sub_assembly(shape_tool)

    # The assembly's own shape, carrying the final location itself.
    assy_shape = shape_tool.GetShape_s(assy_label)
    located_shape = assy_shape.Moved(target_location())
    comp = shape_tool.AddComponent(root_label, located_shape, True)
    set_name(comp, "sub_assembly_moved")
    shape_tool.UpdateAssemblies()

    finish(doc, shape_tool, root_label, "single_shot_B.stp", "CASE B")


def case_c():
    print()
    print("=" * 70)
    print("CASE C: add at identity, RemoveComponent, UpdateAssemblies(),")
    print("THEN AddComponent at final location (probing whether an")
    print("UpdateAssemblies between remove and re-add flushes whatever")
    print("poisons the known-failing reposition cycle)")
    print("=" * 70)
    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    root_label = make_root(shape_tool)
    assy_label = make_sub_assembly(shape_tool)

    comp = shape_tool.AddComponent(root_label, assy_label, TopLoc_Location())
    set_name(comp, "sub_assembly_instance")
    shape_tool.UpdateAssemblies()

    ref_label = TDF_Label()
    shape_tool.GetReferredShape_s(comp, ref_label)
    shape_tool.RemoveComponent(comp)
    shape_tool.UpdateAssemblies()   # <-- the one new variable vs. the
                                    #     known-failing pattern
    new_comp = shape_tool.AddComponent(root_label, ref_label, target_location())
    set_name(new_comp, "sub_assembly_moved")
    shape_tool.UpdateAssemblies()

    finish(doc, shape_tool, root_label, "single_shot_C.stp", "CASE C")


if __name__ == "__main__":
    case_a()
    case_b()
    case_c()
