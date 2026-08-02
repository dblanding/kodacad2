"""
smoke_test_pure_native_assembly.py -- isolating a new variable after
smoke_test_freecad_strategy.py's surprising negative result.

That test's native rebuild (AddShape/AddComponent only, no Extract_s
anywhere) STILL failed identically to the original Extract_s-based
bug. That rules out cross-document copying as the sole cause -- but
it conflicts with something already well-established in this project:
repositioning an ASSEMBLY-with-children (l-bracket-assembly, which
itself contains nut-bolt-assembly children) via this exact
RemoveComponent+AddComponent pattern has worked reliably, confirmed
surviving save/reload many times over many sessions.

One real difference stands out: l-bracket-assembly's structure was
read WHOLESALE by STEPCAFControl_Reader from an existing STEP file --
not constructed via explicit AddShape/AddComponent Python calls
within the current session the way smoke_test_freecad_strategy.py's
rebuild did (and the way add_component_from_label's real usage
inherently also does, since it's building NEW label structure via
Extract_s within the current session).

This test isolates that variable as cleanly as possible: build an
assembly via AddShape/AddComponent from the very start, in ONE
document, no cross-document anything, no "rebuild from data read out
of another document" -- as pure a native case as this project has
ever tested for an ASSEMBLY (as opposed to a leaf part, which
occt_bug_repro.py's Case 2 already confirmed works). Reposition it
the same way, save, reload.

If this ALSO fails: the bug has nothing to do with import/Extract_s/
rebuilding at all -- it's specifically about repositioning an
assembly-typed component via RemoveComponent+AddComponent, full stop,
and l-bracket-assembly's success must depend on something about being
reader-constructed rather than being native. That would be a genuinely
new, important pivot in understanding this whole limitation.

If this SUCCEEDS: the difference is specifically "was this assembly's
structure built via explicit Python-level AddShape/AddComponent calls
in the current session, vs. read wholesale by STEPCAFControl_Reader" --
also a real, actionable finding, just a different one.

Run: uv run smoke_test_pure_native_assembly.py
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
    print("Building a PURE NATIVE assembly -- ONE document from the")
    print("start, AddShape/AddComponent only, no cross-document")
    print("anything, no rebuild-from-elsewhere")
    print("=" * 70)

    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    box1 = BRepPrimAPI_MakeBox(3.0, 3.0, 3.0).Shape()
    box1_label = shape_tool.AddShape(box1, False)
    set_name(box1_label, "sub_box_1")

    box2 = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    box2_label = shape_tool.AddShape(box2, False)
    set_name(box2_label, "sub_box_2")

    assy_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy_shape)
    assy_label = shape_tool.AddShape(assy_shape, True)
    set_name(assy_label, "native_assembly")
    c1 = shape_tool.AddComponent(assy_label, box1_label, TopLoc_Location())
    set_name(c1, "sub_box_1_1")
    c2 = shape_tool.AddComponent(assy_label, box2_label, TopLoc_Location())
    set_name(c2, "sub_box_2_1")
    shape_tool.UpdateAssemblies()

    base = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    base_label = shape_tool.AddShape(base, False)
    set_name(base_label, "base")

    comp = shape_tool.AddComponent(base_label, assy_label, TopLoc_Location())
    set_name(comp, "native_assembly_instance")
    shape_tool.UpdateAssemblies()

    print("\nBefore reposition:")
    dump(shape_tool, base_label)

    print()
    print("=" * 70)
    print("Repositioning (RemoveComponent + AddComponent)")
    print("=" * 70)
    ref_label = TDF_Label()
    shape_tool.GetReferredShape_s(comp, ref_label)
    shape_tool.RemoveComponent(comp)

    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    new_comp = shape_tool.AddComponent(base_label, ref_label, TopLoc_Location(t))
    set_name(new_comp, "native_assembly_moved")
    shape_tool.UpdateAssemblies()

    print("\nAfter reposition, BEFORE any STEP write (in-memory, correct):")
    dump(shape_tool, base_label)

    write_step(doc, "pure_native_assembly_test.stp")
    fresh_doc = read_step("pure_native_assembly_test.stp")
    fresh_tool = XCAFDoc_DocumentTool.ShapeTool_s(fresh_doc.Main())
    free_labels = TDF_LabelSequence()
    fresh_tool.GetFreeShapes(free_labels)

    print()
    print("=" * 70)
    print("After STEP write + fresh read:")
    print("=" * 70)
    for i in range(1, free_labels.Length() + 1):
        dump(fresh_tool, free_labels.Value(i))

    print("\nExpected: 'native_assembly_moved' at (50.000, 0.000, 0.000).")
    print("If this fails the same way -- the bug is NOT about import/")
    print("Extract_s/rebuild at all. If this succeeds -- the difference")
    print("really is 'built via Python calls this session' vs 'read")
    print("wholesale by STEPCAFControl_Reader'.")


if __name__ == "__main__":
    main()
