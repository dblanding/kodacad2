"""
smoke_test_dedicated_root.py -- does the zero-NAUO failure happen
because a label was made to be BOTH a leaf shape (with its own raw
geometry) AND an assembly (holding components) at once -- something
every test this session has done, but which Kodacad's real document
structure never does?

Checked docmodel.py directly: the real root is a DEDICATED, EMPTY
compound (labeled '/'), created once via AddShape(empty_compound,
True). Real parts are added to it via the SHAPE-based AddComponent
overload (AddComponent(root_label, shape, True)) -- never by giving
the root its own separate raw geometry. Every test this session
instead made 'base' a literal box (BRepPrimAPI_MakeBox) that ALSO had
a component added to it -- mixing "has its own geometry" with "holds
components" on the same label, something Kodacad's real code never
does anywhere.

Also confirmed directly: set_component_location() (the reposition
code, long confirmed working for native content) deliberately uses
the LABEL-based AddComponent overload, not the shape-based one --
documented in its own code as a fix for the shape-based overload
losing names (auto-numbered '22', '25' in a real historical test).
So this test uses the label-based overload for the reposition step,
matching that confirmed-correct usage -- the one change under test
here is giving 'base' a dedicated, empty-compound structure instead
of raw box geometry, matching Kodacad's actual '/' root exactly.

Run: uv run smoke_test_dedicated_root.py
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
    print("Building with a DEDICATED EMPTY-COMPOUND root, matching")
    print("Kodacad's real '/' structure exactly -- 'base' never has")
    print("its own raw geometry, only components")
    print("=" * 70)

    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    # Dedicated root -- an EMPTY compound, exactly matching docmodel.py's
    # real '/' creation (AddShape(empty_compound, True)).
    root_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(root_shape)
    root_label = shape_tool.AddShape(root_shape, True)
    set_name(root_label, "/")

    # Real part, added via the SHAPE-based overload -- matching
    # docmodel.py's real native-part-add code exactly
    # (AddComponent(root_label, shape, True)).
    leaf_box = BRepPrimAPI_MakeBox(3.0, 3.0, 3.0).Shape()
    leaf_comp = shape_tool.AddComponent(root_label, leaf_box, True)
    set_name(leaf_comp, "leaf_instance")
    leaf_ref = TDF_Label()
    shape_tool.GetReferredShape_s(leaf_comp, leaf_ref)
    set_name(leaf_ref, "leaf_part")
    shape_tool.UpdateAssemblies()

    print("\nBefore reposition:")
    dump(shape_tool, root_label)

    print()
    print("=" * 70)
    print("Repositioning via the LABEL-based AddComponent overload --")
    print("matching set_component_location()'s own confirmed-correct")
    print("usage exactly")
    print("=" * 70)
    ref_label = TDF_Label()
    shape_tool.GetReferredShape_s(leaf_comp, ref_label)
    shape_tool.RemoveComponent(leaf_comp)

    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    new_comp = shape_tool.AddComponent(root_label, ref_label, TopLoc_Location(t))
    set_name(new_comp, "leaf_moved")
    shape_tool.UpdateAssemblies()

    print("\nAfter reposition, BEFORE any STEP write (in-memory, correct):")
    dump(shape_tool, root_label)

    fname = "dedicated_root_test.stp"
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

    print("\nExpected: '/' with child 'leaf_moved' at (50,0,0). If this")
    print("now works, the culprit was mixing raw geometry with")
    print("components on the same label -- something Kodacad's real")
    print("code never does, meaning REAL sessions may not be at risk")
    print("of this at all, and this whole line of investigation was")
    print("specific to how the test scripts (not the real app) were")
    print("built.")


if __name__ == "__main__":
    main()
