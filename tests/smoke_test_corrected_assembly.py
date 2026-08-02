"""
smoke_test_corrected_assembly.py -- THE critical test: does the
corrected structure (matching Kodacad's real document layout exactly)
fix the ORIGINAL bug for an assembly-with-children, not just a leaf
part?

smoke_test_dedicated_root.py succeeded -- but only for a leaf part,
matching what occt_bug_repro.py's Case 2 already confirmed works. It
did NOT yet test the actual thing this entire investigation (and the
OCCT discussion thread) has been about: an assembly WITH ITS OWN
CHILDREN, repositioned, losing name/location on STEP round trip.

This test uses the corrected structure throughout -- a dedicated,
empty-compound '/' root (never given its own raw geometry), the
SHAPE-based AddComponent overload for the initial add (matching
add_component()), the LABEL-based overload for reposition (matching
set_component_location()) -- but builds a genuine two-level assembly
this time: '/' contains 'sub_assembly', which itself contains
'sub_box_1_1'. This is the structure that actually matters.

Run: uv run smoke_test_corrected_assembly.py
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


def main():
    print("=" * 70)
    print("Building a TWO-LEVEL assembly with the corrected structure:")
    print("'/' (dedicated empty compound) -> 'sub_assembly' -> 'sub_box_1_1'")
    print("=" * 70)

    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    # Dedicated root -- empty compound, matching '/' exactly.
    root_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(root_shape)
    root_label = shape_tool.AddShape(root_shape, True)
    set_name(root_label, "/")

    # The sub-assembly's own children, built the normal way (these are
    # leaf parts, not roots, so the label-based construction used
    # throughout this project for building UP an assembly's internal
    # structure applies here -- this part was never in question).
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

    # Add the sub-assembly under '/' using the SHAPE-based overload --
    # matching add_component()'s real, confirmed-working pattern for
    # adding new content under the root. Note: add_component() passes
    # a raw TopoDS_Shape, not a label -- here that means passing the
    # sub-assembly's OWN shape (shape_tool.GetShape_s(assy_label)),
    # since that's what a caller building a new assembly natively
    # would actually have on hand.
    #
    # REAL RISK WORTH WATCHING FOR IN THE OUTPUT BELOW:
    # set_component_location()'s own documented history (Session 16)
    # warns that passing RAW geometry (not a label) through the
    # shape-based AddComponent(..., expand=True) tells OCCT to
    # decompose it into a fresh structure with no name information to
    # work from, falling back to auto-numbering. shape_tool.GetShape_s
    # returns bare geometry with no XCAF name/structure attached --
    # exactly the trap that comment describes. If 'sub_box_1_1's name
    # is lost in the dump below (even before any reposition or STEP
    # write), that confirms this specific step -- not reposition, not
    # STEP writing -- is where the problem actually is.
    assy_raw_shape = shape_tool.GetShape_s(assy_label)
    comp = shape_tool.AddComponent(root_label, assy_raw_shape, True)
    set_name(comp, "sub_assembly_instance")
    shape_tool.UpdateAssemblies()

    print("\nBefore reposition:")
    dump(shape_tool, root_label)

    print()
    print("=" * 70)
    print("Repositioning via the LABEL-based AddComponent overload --")
    print("matching set_component_location()'s confirmed-correct usage")
    print("=" * 70)
    ref_label = TDF_Label()
    shape_tool.GetReferredShape_s(comp, ref_label)
    shape_tool.RemoveComponent(comp)

    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    new_comp = shape_tool.AddComponent(root_label, ref_label, TopLoc_Location(t))
    set_name(new_comp, "sub_assembly_moved")
    shape_tool.UpdateAssemblies()

    print("\nAfter reposition, BEFORE any STEP write (in-memory, correct):")
    dump(shape_tool, root_label)

    fname = "corrected_assembly_test.stp"
    write_step(doc, fname)

    print()
    print("=" * 70)
    print(f"RAW FILE TEXT INSPECTION of {fname}")
    print("=" * 70)
    with open(fname) as f:
        raw_text = f.read()
    nauo_lines = [line for line in raw_text.splitlines()
                 if "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in line]
    print(f"\nNEXT_ASSEMBLY_USAGE_OCCURRENCE lines: {len(nauo_lines)}")
    for line in nauo_lines:
        print(f"  {line.strip()}")

    print()
    print("=" * 70)
    print("Reading back fresh")
    print("=" * 70)
    fresh_doc = read_step(fname)
    fresh_tool = XCAFDoc_DocumentTool.ShapeTool_s(fresh_doc.Main())
    free_labels = TDF_LabelSequence()
    fresh_tool.GetFreeShapes(free_labels)
    print(f"\n{free_labels.Length()} free shape(s) after fresh read:")
    for i in range(1, free_labels.Length() + 1):
        dump(fresh_tool, free_labels.Value(i))

    print("\nExpected: '/' with child 'sub_assembly_moved' at (50,0,0),")
    print("which itself has child 'sub_box_1_1' -- name AND location")
    print("both surviving, for a genuine assembly-with-children this")
    print("time, not just a leaf part. THIS is the actual question this")
    print("whole investigation has been about.")


if __name__ == "__main__":
    main()
