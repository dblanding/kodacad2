"""
smoke_test_removecomponent_timing.py -- does RemoveComponent() itself
silently invalidate the referred label we're about to reuse?

smoke_test_pure_native_assembly.py's result was worse than the
original bug: not a blank name/identity location, but the component
COMPLETELY ABSENT after the round trip. That's different enough to
chase specifically rather than assume it's just a variant of the same
symptom.

New hypothesis: what if RemoveComponent() doesn't just drop the
component reference, but also silently prunes the now-unreferenced
underlying shape automatically -- the same cleanup Session 47 had to
add EXPLICITLY for delete_component() (GetUsers_s + RemoveShape)? If
OCAF does something like this internally for RemoveComponent too, the
ref_label captured immediately beforehand (matching the exact pattern
this project has used throughout for repositioning) could already be
pointing at something gone by the time it's handed to the next
AddComponent() call -- and OCAF might silently accept a component
built on a dangling reference rather than raising an error, matching
the pattern of silent no-ops this whole project has run into
repeatedly (guessed-wrong enum names, stale Qt references, etc.).

This test checks the document's ACTUAL state at the precise moment
between RemoveComponent() and the next AddComponent() -- does
GetFreeShapes() still show the referred assembly as a free/orphaned
shape at that exact point, or has it already vanished?

Run: uv run smoke_test_removecomponent_timing.py
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


def is_still_valid(label):
    """A label whose underlying TDF node has been deleted raises when
    you try to use it, the same class of check this project has used
    for stale Qt references -- try touching it and see."""
    try:
        get_entry(label)
        return True
    except Exception as e:
        return f"INVALID: {e}"


def main():
    print("=" * 70)
    print("Building the same pure-native assembly as before")
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

    print(f"\nassy_label entry (before anything): {get_entry(assy_label)}")

    print()
    print("=" * 70)
    print("Capturing ref_label via GetReferredShape_s...")
    print("=" * 70)
    ref_label = TDF_Label()
    shape_tool.GetReferredShape_s(comp, ref_label)
    print(f"ref_label entry: {get_entry(ref_label)}")
    print(f"ref_label == assy_label (same entry)? "
         f"{get_entry(ref_label) == get_entry(assy_label)}")

    print()
    print("=" * 70)
    print("Calling RemoveComponent(comp)...")
    print("=" * 70)
    shape_tool.RemoveComponent(comp)

    print(f"\nref_label still valid immediately after RemoveComponent? "
         f"{is_still_valid(ref_label)}")

    free_labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_labels)
    print(f"\nGetFreeShapes() right now shows {free_labels.Length()} "
         f"free shape(s):")
    found_orphan = False
    for i in range(1, free_labels.Length() + 1):
        entry = get_entry(free_labels.Value(i))
        name = get_name(free_labels.Value(i))
        print(f"  entry={entry} name={name!r}")
        if entry == get_entry(ref_label):
            found_orphan = True
    print(f"\nIs the (former) assembly (native_assembly, ref_label's "
         f"entry) present as a free/orphaned shape right now? {found_orphan}")

    print()
    print("=" * 70)
    print("Calling AddComponent(base_label, ref_label, new_location)...")
    print("=" * 70)
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    try:
        new_comp = shape_tool.AddComponent(base_label, ref_label, TopLoc_Location(t))
        set_name(new_comp, "native_assembly_moved")
        print(f"AddComponent succeeded, new_comp entry: {get_entry(new_comp)}")
        new_ref = TDF_Label()
        has_ref = shape_tool.GetReferredShape_s(new_comp, new_ref)
        print(f"new_comp's own referred shape: has_ref={has_ref}, "
             f"entry={get_entry(new_ref) if has_ref else 'N/A'}")
        if has_ref:
            kids = TDF_LabelSequence()
            shape_tool.GetComponents_s(new_ref, kids, False)
            print(f"That referred shape's own children: {kids.Length()} "
                 f"(expect 1 -- sub_box_1_1)")
            for i in range(1, kids.Length() + 1):
                print(f"  {get_name(kids.Value(i))!r}")
    except Exception as e:
        print(f"AddComponent RAISED an exception: {e}")


if __name__ == "__main__":
    main()
