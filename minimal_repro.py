"""
minimal_repro.py -- headless, minimal reproduction of the "Extract_s-
imported component doesn't survive save/reload" bug (Sessions 14-27).

Run directly: uv run minimal_repro.py  (or python3 minimal_repro.py)
No GUI, no Qt event loop -- just docmodel.py's real DocModel methods
driven against a two-box toy model instead of the full lathe assembly.
Same code paths Kodacad actually uses (add_component_from_label,
set_component_location), so this is a genuine reproduction, not a
reimplementation that could hide or introduce a different bug.

WHAT IT DOES:
  1. Builds a minimal "session" doc: a top-level box named 'base'.
  2. Builds a SEPARATE document with one small box -- mirrors what
     _load_step() hands back for an imported STEP file, but skips the
     file dialog / actual STEP read (going straight to an in-memory
     doc), which is fine since add_component_from_label() only cares
     that the source label is in a DIFFERENT TDocStd_Document.
  3. Imports it via dm.add_component_from_label() -- the exact method
     manual-lathe goes through.
  4. Moves it via dm.set_component_location() -- the exact method
     every Position move goes through.
  5. Dumps every attribute on the resulting label (not just name/
     location -- literally every TDF_Attribute present) before AND
     after a real STEP write+read round-trip, to see what's actually
     different at the raw OCAF level, not just what our own name/
     location readback helpers report.

Please run this and share the FULL output -- especially the "ATTRIBUTE
DUMP" sections, which show something our diagnostics so far never
have: literally everything attached to the label, by GUID.
"""

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_LabelSequence
from OCP.gp import gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.STEPCAFControl import STEPCAFControl_Writer, STEPCAFControl_Reader
from OCP.STEPControl import STEPControl_AsIs
from OCP.XSControl import XSControl_WorkSession
from OCP.IFSelect import IFSelect_RetDone

import docmodel


def dump_attributes(label, indent="    "):
    """List EVERY TDF_Attribute on a label, by GUID -- not just the
    ones our own get_label_name()/get_label_location() helpers know
    to look for. This is the one thing none of our prior diagnostics
    have actually shown us."""
    from OCP.TDF import TDF_AttributeIterator
    it = TDF_AttributeIterator(label)
    count = 0
    while it.More():
        attr = it.Value()
        guid = attr.ID()
        print(f"{indent}attribute: {attr.DynamicType().Name()}  GUID={guid}")
        count += 1
        it.Next()
    if count == 0:
        print(f"{indent}(no attributes)")


def dump_label_full(label, depth=0):
    indent = "  " * depth
    name = docmodel.get_label_name(label)
    entry = docmodel.get_label_entry(label)
    print(f"{indent}LABEL entry={entry} name={name!r}")
    dump_attributes(label, indent=indent + "    ")


def write_step(doc, fname):
    ws = XSControl_WorkSession()
    writer = STEPCAFControl_Writer(ws, False)
    writer.Transfer(doc, STEPControl_AsIs)
    status = writer.Write(fname)
    print(f"  write status: {status}")
    return status


def read_step(fname):
    doc, app = docmodel.create_doc()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    reader.SetNameMode(True)
    reader.SetMatMode(True)
    status = reader.ReadFile(fname)
    print(f"  read status: {status}")
    if status == IFSelect_RetDone:
        reader.Transfer(doc)
    return doc, app


def build_nested_import_doc():
    """Build a SEPARATE document with a NESTED assembly -- a wrapper
    assembly containing two sub-boxes -- instead of a flat leaf shape.
    manual-lathe has this kind of structure (e.g. '1925-4008-0048
    assembly' as one of its own children); the flat single-box test
    above did not, and it did NOT reproduce the bug. Testing whether
    nesting depth is the missing variable."""
    import_dm = docmodel.DocModel()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(import_dm.doc.Main())

    # Two sub-boxes
    sub1_shape = BRepPrimAPI_MakeBox(3.0, 3.0, 3.0).Shape()
    sub1_label = shape_tool.AddShape(sub1_shape, False)
    docmodel.set_label_name(sub1_label, "sub_box_1")

    sub2_shape = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    sub2_label = shape_tool.AddShape(sub2_shape, False)
    docmodel.set_label_name(sub2_label, "sub_box_2")

    # Wrapper assembly containing both sub-boxes as components
    wrapper_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(wrapper_shape)
    wrapper_label = shape_tool.AddShape(wrapper_shape, True)
    docmodel.set_label_name(wrapper_label, "nested_assembly")
    comp1 = shape_tool.AddComponent(wrapper_label, sub1_label, TopLoc_Location())
    docmodel.set_label_name(comp1, "sub_box_1_1")
    comp2 = shape_tool.AddComponent(wrapper_label, sub2_label, TopLoc_Location())
    docmodel.set_label_name(comp2, "sub_box_2_1")
    shape_tool.UpdateAssemblies()

    return import_dm, wrapper_label


def main():
    print("#" * 70)
    print("# SCENARIO A: flat leaf shape (already run once -- confirmed")
    print("# working). Skipping re-run; see prior output.")
    print("#" * 70)
    print()
    print("#" * 70)
    print("# SCENARIO B: NESTED assembly (wrapper containing 2 sub-boxes)")
    print("# -- does bug reproduce when the imported item has its own")
    print("# children, like manual-lathe does?")
    print("#" * 70)

    print()
    print("=" * 70)
    print("STEP 1: build minimal session doc (one box, 'base')")
    print("=" * 70)
    dm = docmodel.DocModel()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(dm.doc.Main())
    base_shape = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    base_label = shape_tool.AddShape(base_shape, False)
    docmodel.set_label_name(base_label, "base")
    dm.parse_doc()
    print("label_dict after building base:", list(dm.label_dict.keys()))

    print()
    print("=" * 70)
    print("STEP 2: build a SEPARATE document with a NESTED assembly")
    print("=" * 70)
    import_dm, wrapper_label = build_nested_import_doc()
    print("Source label (wrapper) before import:")
    dump_label_full(wrapper_label)

    print()
    print("=" * 70)
    print("STEP 3: import it via dm.add_component_from_label()")
    print("(Session 30: reverted to the simple, single-Extract_s form --")
    print("the Session 29 native-rebuild attempt did not fix this bug")
    print("and introduced its own regression (lost internal import")
    print("sharing). Set aside as a known limitation -- see")
    print("docs/DEVELOPMENT_LOG.md, Session 30.)")
    print("=" * 70)
    uid = dm.add_component_from_label(wrapper_label, "nested_assembly")
    print(f"uid after import: {uid}")
    if uid is None:
        print("IMPORT FAILED -- stopping here.")
        return
    comp_label = dm._find_label_by_entry(dm.label_dict[uid]['entry'])
    print("Label after import:")
    dump_label_full(comp_label)
    print("Its children:")
    children = TDF_LabelSequence()
    shape_tool_after = XCAFDoc_DocumentTool.ShapeTool_s(dm.doc.Main())
    shape_tool_after.GetComponents_s(comp_label, children, False)
    for i in range(1, children.Length() + 1):
        dump_label_full(children.Value(i), depth=1)

    print()
    print("=" * 70)
    print("STEP 4: move it via dm.set_component_location()")
    print("=" * 70)
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    new_uid = dm.set_component_location(uid, TopLoc_Location(t))
    print(f"uid after move: {new_uid}")
    if new_uid is None:
        print("MOVE FAILED -- stopping here.")
        return
    moved_label = dm._find_label_by_entry(dm.label_dict[new_uid]['entry'])
    print("Label after move (BEFORE any STEP write):")
    dump_label_full(moved_label)
    print("Its children after move:")
    children2 = TDF_LabelSequence()
    shape_tool_after2 = XCAFDoc_DocumentTool.ShapeTool_s(dm.doc.Main())
    shape_tool_after2.GetComponents_s(moved_label, children2, False)
    for i in range(1, children2.Length() + 1):
        dump_label_full(children2.Value(i), depth=1)

    print()
    print("=" * 70)
    print("STEP 5: write to STEP")
    print("=" * 70)
    out_path = "/tmp/minimal_repro_nested.stp"
    write_step(dm.doc, out_path)
    print(f"\nWritten to: {out_path}")
    print("Please also run these two greps on it and share the output:")
    print(f'  grep -n "NEXT_ASSEMBLY_USAGE_OCCURRENCE" {out_path}')
    print(f'  grep -n "CARTESIAN_POINT" {out_path}')

    print()
    print("=" * 70)
    print("STEP 6: read it back fresh, dump the FULL tree")
    print("=" * 70)
    fresh_doc, fresh_app = read_step(out_path)
    fresh_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(fresh_doc.Main())
    free_labels = TDF_LabelSequence()
    fresh_shape_tool.GetFreeShapes(free_labels)
    print(f"Free shapes after reload: {free_labels.Length()}")

    def dump_recursive(label, depth):
        dump_label_full(label, depth=depth)
        kids = TDF_LabelSequence()
        fresh_shape_tool.GetComponents_s(label, kids, False)
        for k in range(1, kids.Length() + 1):
            dump_recursive(kids.Value(k), depth + 1)

    for i in range(1, free_labels.Length() + 1):
        print()
        dump_recursive(free_labels.Value(i), 0)


if __name__ == "__main__":
    main()
