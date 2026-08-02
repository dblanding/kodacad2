"""
smoke_test_native_no_reposition.py -- does a purely native, multi-
level assembly fail to write ANY structure even WITHOUT ever being
repositioned?

smoke_test_raw_file_inspection.py's result was severe: ZERO
NEXT_ASSEMBLY_USAGE_OCCURRENCE entities anywhere in the file, for a
structure that was reposition-then-written. That's different from
every prior test in this project, including occt_bug_repro.py's Case
1 -- which DID show 'base' with a child present in the file (wrong
name/location, but present) -- and Case 1 went THROUGH
XCAFDoc_Editor::Extract_s before the component was added, while this
session's native tests never touched Extract_s at all.

That raises an uncomfortable possibility worth testing directly
before drawing any conclusion: maybe Extract_s isn't purely the
villain this whole investigation has assumed -- maybe it performs
some necessary setup a purely manual AddComponent call is missing,
and without it the writer can't recognize the assembly relationship
AT ALL, rather than writing it with wrong details.

This test isolates REPOSITION as a variable. It builds the exact same
'base' containing 'native_assembly' containing 'sub_box_1_1'
structure as smoke_test_raw_file_inspection.py -- but does NOT
reposition it. Adds the component once, at the origin, and leaves it
there. Writes, reads, checks for NAUO entities in the raw file.

If this ALSO shows zero NAUO entities: reposition isn't the trigger
at all -- ANY purely native (Extract_s-free), multi-level assembly
fails to write its structure, which would be a much bigger and more
fundamental finding than "imported assemblies lose position on
reposition" -- it would mean natively building an assembly-of-
assemblies in Kodacad, without ever importing or repositioning
anything, could ALSO be at risk.

If this succeeds (NAUO entities present, structure correct): the
trigger really is specifically REPOSITION (RemoveComponent+
AddComponent) applied to a purely-native assembly -- a narrower,
different finding than either the import-based hypothesis or the
Extract_s-necessity hypothesis.

Run: uv run smoke_test_native_no_reposition.py
"""

from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.TCollection import TCollection_ExtendedString
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_LabelSequence
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
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
    print("Building 'base' containing 'native_assembly' containing")
    print("'sub_box_1_1' -- NEVER repositioned, added once and left")
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

    print("\nIn-memory state (never touched again -- no reposition):")
    dump(shape_tool, base_label)

    fname = "native_no_reposition_test.stp"
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
    if not nauo_lines:
        print("  (none found)")

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

    print("\nExpected: 'base' with child 'native_assembly_instance' at")
    print("(0,0,0), which itself has child 'sub_box_1_1'. If children")
    print("are missing here too, reposition is NOT the trigger -- this")
    print("is a more fundamental issue with native multi-level")
    print("assemblies in general.")


if __name__ == "__main__":
    main()
