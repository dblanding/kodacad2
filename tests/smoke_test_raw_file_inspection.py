"""
smoke_test_raw_file_inspection.py -- what does the RAW .stp file
actually contain, for the exact case smoke_test_removecomponent_
timing.py just confirmed is 100% correct in memory?

That test proved the in-memory state right after reposition is
correct -- ref_label stays valid, GetFreeShapes() shows it correctly,
AddComponent succeeds cleanly, the new component's referred shape and
its own child are all exactly right. So the bug isn't in the
reposition logic. It has to be in the STEP write or read.

Every prior raw-STEP-file inspection in this project (going back to
minimal_repro.py) was done on the CROSS-DOCUMENT Extract_s case. This
is the first time this exact scenario -- pure single-document,
natively-built assembly, repositioned, then written -- has actually
been inspected at the raw file level rather than just through the
reader's reinterpretation of it.

This test does the same build+reposition as smoke_test_
removecomponent_timing.py (already confirmed correct in memory),
then writes to STEP and greps the RAW FILE TEXT directly for
NEXT_ASSEMBLY_USAGE_OCCURRENCE and CARTESIAN_POINT entities -- the
same two diagnostic markers this project has used from the very
start -- before ever involving a fresh STEPCAFControl_Reader pass at
all. This separates two genuinely different possible failures:
        (a) the WRITER never puts correct data in the file to begin
            with, or
        (b) the file is written correctly and the READER is somehow
            failing to reconstruct it.

Run: uv run smoke_test_raw_file_inspection.py
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
    print("Building + repositioning (identical to smoke_test_")
    print("removecomponent_timing.py, already confirmed correct")
    print("in memory)")
    print("=" * 70)

    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    box1 = BRepPrimAPI_MakeBox(3.0, 3.0, 3.0).Shape()
    box1_label = shape_tool.AddShape(box1, False)
    set_name(box1_label, "sub_box_1")

    assy_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy_shape)
    assy_label = shape_tool.AddShape(assy_shape, True)
    set_name(assy_label, "native_assembly")
    c1 = shape_tool.AddComponent(assy_label, box1_label, TopLoc_Location())
    set_name(c1, "sub_box_1_1")
    shape_tool.UpdateAssemblies()

    base = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    base_label = shape_tool.AddShape(base, False)
    set_name(base_label, "base")

    comp = shape_tool.AddComponent(base_label, assy_label, TopLoc_Location())
    set_name(comp, "native_assembly_instance")
    shape_tool.UpdateAssemblies()

    ref_label = TDF_Label()
    shape_tool.GetReferredShape_s(comp, ref_label)
    shape_tool.RemoveComponent(comp)
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    new_comp = shape_tool.AddComponent(base_label, ref_label, TopLoc_Location(t))
    set_name(new_comp, "native_assembly_moved")
    shape_tool.UpdateAssemblies()

    print("\nIn-memory state right before write (already confirmed correct):")
    dump(shape_tool, base_label)

    fname = "raw_file_inspection_test.stp"
    write_step(doc, fname)

    print()
    print("=" * 70)
    print(f"RAW FILE TEXT INSPECTION of {fname}")
    print("(before involving a fresh reader at all)")
    print("=" * 70)
    with open(fname) as f:
        raw_text = f.read()

    print("\nAll NEXT_ASSEMBLY_USAGE_OCCURRENCE lines:")
    nauo_lines = [line for line in raw_text.splitlines()
                 if "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in line]
    for line in nauo_lines:
        print(f"  {line.strip()}")
    if not nauo_lines:
        print("  (none found -- no assembly usage occurrences in the "
             "file at all)")

    print("\nAll CARTESIAN_POINT lines with a non-zero value (skipping "
         "the (0.,0.,0.) origin ones for brevity):")
    cart_lines = [line for line in raw_text.splitlines()
                 if "CARTESIAN_POINT" in line and "(0.,0.,0.)" not in line]
    for line in cart_lines[:20]:
        print(f"  {line.strip()}")
    if not cart_lines:
        print("  (none found -- every CARTESIAN_POINT in the file is at "
             "the origin, meaning the (50,0,0) translation is not "
             "present ANYWHERE in the written file)")

    print()
    print("=" * 70)
    print("Now reading it back fresh, for comparison")
    print("=" * 70)
    fresh_doc = read_step(fname)
    fresh_tool = XCAFDoc_DocumentTool.ShapeTool_s(fresh_doc.Main())
    free_labels = TDF_LabelSequence()
    fresh_tool.GetFreeShapes(free_labels)
    print(f"\n{free_labels.Length()} free shape(s) after fresh read:")
    for i in range(1, free_labels.Length() + 1):
        dump(fresh_tool, free_labels.Value(i))


if __name__ == "__main__":
    main()
