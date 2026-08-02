"""
smoke_test_save_load.py -- does OCAF's NATIVE document persistence
(SaveAs/Open, distinct from STEP export/import) work correctly in
Kodacad's OCP environment?

Why this matters: Kodacad already creates its documents in "BinXCAF"
format (see docmodel.py's create_doc()) -- which is ALSO OCAF's own
native binary persistence format. If TDocStd_Application::SaveAs/Open
round-trip a document with full fidelity, that's a completely
different persistence path from STEP export -- one that doesn't go
through STEP's translation layer AT ALL, and so would sidestep every
STEP-round-trip fidelity issue this project has spent many sessions
on (the assembly-import-persistence limitation from Sessions 17-30,
for instance).

Why this needs testing rather than assuming: a real, confirmed
GitHub issue (CadQuery/OCP#182, CadQuery/cadquery#1599) reports
TDocStd_Application::Open returning an EMPTY document specifically in
OCP's wrapping, as recently as last year. Other real code (CadQuery/
OCP#55) shows SaveAs working correctly (PCDM_SS_OK). The signal is
genuinely mixed -- this test finds out empirically for THIS specific
OCP version, rather than assuming either way.

What this tests, beyond a bare round trip: builds an assembly with
BOTH a simple leaf part AND a genuinely SHARED instance (the same
part referenced twice, at different locations) -- since preserving
sharing correctly (not silently duplicating or collapsing it) is
exactly the kind of thing that's gone wrong with STEP round-trips in
this project before, and is worth checking here too rather than
assuming native persistence handles it correctly just because it's
"native."

Run: uv run smoke_test_save_load.py
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
from OCP.gp import gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location
from OCP.PCDM import PCDM_ReaderStatus, PCDM_StoreStatus
from OCP.Message import Message_ProgressRange


def create_doc():
    """Exactly matches docmodel.py's own create_doc()."""
    doc_format = "BinXCAF"
    doc = TDocStd_Document(TCollection_ExtendedString(doc_format))
    app = XCAFApp_Application.GetApplication_s()
    app.NewDocument(TCollection_ExtendedString(doc_format), doc)
    BinXCAFDrivers.DefineFormat_s(app)
    return doc, app


def set_name(label, name):
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))


def get_name(label):
    """Matches docmodel.py's own get_label_name() exactly."""
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


def build_test_assembly():
    """Leaf part + a genuinely SHARED instance (same part, two
    locations) -- the case most worth checking, not just a bare
    round trip."""
    doc, app = create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    leaf = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    leaf_label = shape_tool.AddShape(leaf, False)
    set_name(leaf_label, "leaf_part")

    assy_shape = TopoDS_Compound()
    BRep_Builder().MakeCompound(assy_shape)
    assy_label = shape_tool.AddShape(assy_shape, True)
    set_name(assy_label, "top_assembly")

    t1 = gp_Trsf()
    t1.SetTranslation(gp_Vec(0.0, 0.0, 0.0))
    c1 = shape_tool.AddComponent(assy_label, leaf_label, TopLoc_Location(t1))
    set_name(c1, "leaf_instance_1")

    t2 = gp_Trsf()
    t2.SetTranslation(gp_Vec(10.0, 0.0, 0.0))
    c2 = shape_tool.AddComponent(assy_label, leaf_label, TopLoc_Location(t2))
    set_name(c2, "leaf_instance_2")

    shape_tool.UpdateAssemblies()
    return doc, app, shape_tool, assy_label


def main():
    print("=" * 70)
    print("SMOKE TEST 1: OCAF native SaveAs/Open round trip")
    print("=" * 70)

    doc, app, shape_tool, assy_label = build_test_assembly()

    print("\nBEFORE save (in-memory, known correct):")
    dump(shape_tool, assy_label)

    path = "smoke_test_save_load.xbf"
    print(f"\nSaving via TDocStd_Application::SaveAs to {path} ...")
    store_status = app.SaveAs(doc, TCollection_ExtendedString(path),
                              Message_ProgressRange())
    print(f"Store status: {store_status}")
    if store_status != PCDM_StoreStatus.PCDM_SS_OK:
        print("FAILED -- SaveAs did not return PCDM_SS_OK. Stopping here.")
        return

    print(f"\nOpening a FRESH document from {path} via "
         f"TDocStd_Application::Open ...")
    doc2, app2 = create_doc()
    open_status = app2.Open(TCollection_ExtendedString(path), doc2,
                            Message_ProgressRange())
    print(f"Open status: {open_status}")
    if open_status != PCDM_ReaderStatus.PCDM_RS_OK:
        print("FAILED -- Open did not return PCDM_RS_OK. Stopping here.")
        return

    shape_tool2 = XCAFDoc_DocumentTool.ShapeTool_s(doc2.Main())
    free_labels = TDF_LabelSequence()
    shape_tool2.GetFreeShapes(free_labels)

    print(f"\nAFTER round trip -- {free_labels.Length()} free shape(s) "
         f"in the reopened document:")
    for i in range(1, free_labels.Length() + 1):
        dump(shape_tool2, free_labels.Value(i))

    print("\nExpected: 'top_assembly' with TWO children, "
         "'leaf_instance_1' at (0,0,0) and 'leaf_instance_2' at "
         "(10,0,0), both sharing the same underlying leaf_part -- "
         "exactly matching the BEFORE dump above, byte-for-byte in "
         "structure (names, locations, and sharing all preserved).")


if __name__ == "__main__":
    main()
