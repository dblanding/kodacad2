"""
smoke_test_shared_reposition.py -- is Session 22's unshare-on-
reposition still necessary, post-Session-52?

Doug's new workflow (Session 54): RMB "Create Shared Instance" makes
a second component referencing the SAME underlying shape, superimposed
on the original, to then be moved via the Position dialog. But
set_component_location currently UNSHARES first whenever the moved
instance's underlying shape has multiple users (the Session 22 fix:
back then, repositioning one of N shared instances corrupted the STEP
export). If that unshare still fires, the moved instance silently
becomes an independent copy -- defeating the point of a shared
instance.

Reasons to suspect the unshare is no longer needed: Session 51/52
established that healthy, label-based structures survive
RemoveComponent+AddComponent reposition cycles cleanly (validated all
the way through smoke_test_production_fix.py) -- and as1-oc-214.stp's
own two l-bracket-assembly instances are living proof that
shared-at-different-locations round-trips correctly. Session 22's
corruption evidence predates every structural discovery of Session 51
and may have been confounded the same way smoke_test_freecad_strategy
was.

This test settles it: two shared instances (same ref, one at
identity, one superimposed then MOVED to (50,0,0) via
RemoveComponent + UpdateAssemblies + AddComponent -- NO unshare),
STEP round trip, then verify: both instances present, names correct,
locations correct (one at origin, one at 50), and BOTH still
referencing the SAME underlying shape.

Tested for BOTH cases: a shared leaf part, and a shared
assembly-with-children (Doug's real 1602 case).

If both PASS: set_component_location's unshare step gets removed, and
the create-instance-then-move workflow keeps genuine persistent
sharing end to end.
If either FAILS: the unshare stays for that case, and the new feature
needs a documented caveat instead.

Run: uv run smoke_test_shared_reposition.py
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


def make_root(shape_tool):
    root_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(root_shape)
    root_label = shape_tool.AddShape(root_shape, True)
    set_name(root_label, "/")
    return root_label


def target_location():
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(50.0, 0.0, 0.0))
    return TopLoc_Location(t)


def run_case(case_name, make_ref_label):
    """Shared scenario: instance_1 at identity, instance_2 created
    superimposed (create_shared_instance's exact mechanism), then
    instance_2 MOVED to (50,0,0) with NO unshare."""
    print("=" * 70)
    print(f"CASE: {case_name}")
    print("=" * 70)
    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    root_label = make_root(shape_tool)
    ref_label = make_ref_label(shape_tool)
    ref_name = get_name(ref_label)

    c1 = shape_tool.AddComponent(root_label, ref_label, TopLoc_Location())
    set_name(c1, f"{ref_name}_1")
    # create_shared_instance's mechanism: same parent, same ref, same loc
    c2 = shape_tool.AddComponent(root_label, ref_label, TopLoc_Location())
    set_name(c2, f"{ref_name}_2")
    shape_tool.UpdateAssemblies()

    # Reposition instance 2 -- NO unshare
    ref2 = TDF_Label()
    shape_tool.GetReferredShape_s(c2, ref2)
    shape_tool.RemoveComponent(c2)
    shape_tool.UpdateAssemblies()
    new_c2 = shape_tool.AddComponent(root_label, ref2, target_location())
    set_name(new_c2, f"{ref_name}_2")
    shape_tool.UpdateAssemblies()

    print("\nIn-memory after moving instance 2 (no unshare):")
    dump_full(shape_tool, root_label)

    fname = f"shared_reposition_{case_name}.stp"
    write_step(doc, fname)

    with open(fname) as f:
        raw = f.read()
    nauo_lines = [line.strip() for line in raw.splitlines()
                  if "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in line]
    print(f"\nRAW FILE -- NAUO lines ({len(nauo_lines)}):")
    for line in nauo_lines:
        print(f"  {line}")

    fresh = read_step(fname)
    fresh_tool = XCAFDoc_DocumentTool.ShapeTool_s(fresh.Main())
    free_labels = TDF_LabelSequence()
    fresh_tool.GetFreeShapes(free_labels)
    print(f"\nAfter round trip:")
    for i in range(1, free_labels.Length() + 1):
        dump_full(fresh_tool, free_labels.Value(i))

    # Explicit checks
    top = free_labels.Value(1)
    kids = TDF_LabelSequence()
    fresh_tool.GetComponents_s(top, kids, False)
    entries = []
    for i in range(1, kids.Length() + 1):
        r = TDF_Label()
        fresh_tool.GetReferredShape_s(kids.Value(i), r)
        loc = fresh_tool.GetShape_s(kids.Value(i)).Location()
        t = loc.Transformation().TranslationPart()
        entries.append((get_name(kids.Value(i)), get_entry(r),
                        (t.X(), t.Y(), t.Z())))
    print(f"\n[{case_name}] verdict:")
    for name, ref_entry, xyz in entries:
        print(f"  {name}: ref={ref_entry} loc=({xyz[0]:.1f},"
              f"{xyz[1]:.1f},{xyz[2]:.1f})")
    ok = (len(entries) == 2
          and entries[0][1] == entries[1][1]
          and any(abs(e[2][0] - 50.0) < 1e-6 for e in entries)
          and any(abs(e[2][0]) < 1e-6 for e in entries))
    verdict = ("PASS: two instances, sharing preserved, one at origin "
               "and one at 50" if ok else "FAIL -- see above")
    print(f"  -> {verdict}")
    print()
    return ok


def make_leaf(shape_tool):
    leaf = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    leaf_label = shape_tool.AddShape(leaf, False)
    set_name(leaf_label, "shared_part")
    return leaf_label


def make_assembly(shape_tool):
    box = BRepPrimAPI_MakeBox(3.0, 3.0, 3.0).Shape()
    box_label = shape_tool.AddShape(box, False)
    set_name(box_label, "sub_box")
    assy_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy_shape)
    assy_label = shape_tool.AddShape(assy_shape, True)
    set_name(assy_label, "shared_assembly")
    c = shape_tool.AddComponent(assy_label, box_label, TopLoc_Location())
    set_name(c, "sub_box_1")
    shape_tool.UpdateAssemblies()
    return assy_label


if __name__ == "__main__":
    ok1 = run_case("leaf_part", make_leaf)
    ok2 = run_case("assembly", make_assembly)
    print("=" * 70)
    if ok1 and ok2:
        print("BOTH CASES PASS -- the Session 22 unshare-on-reposition is")
        print("no longer necessary; set_component_location's unshare step")
        print("can be removed, and Create Shared Instance -> Position")
        print("gives genuine persistent sharing end to end.")
    else:
        print("At least one case FAILED -- the unshare stays for the")
        print("failing case(s); see the dumps above.")
