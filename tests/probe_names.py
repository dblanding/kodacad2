"""
probe_names.py -- which name fields does a STEP file actually carry,
and where?

Built for the Session 57 'button' investigation: a natively-created
Kodacad part displayed namelessly in CAD Assistant and FreeCAD but
fine in Kodacad, even after a round trip. Diagnosis from code
reading: add_component gave the occurrence and the product IDENTICAL
names, which triggers the Session 17 writer rule -- identical
occurrence/product names make STEPCAFControl_Writer write the NAUO's
descriptive-name field BLANK. External viewers display the NAUO name
(blank); Kodacad displays the occurrence label, which the READER
back-fills from the product name when the NAUO is blank -- hence the
asymmetry. This probe verifies that diagnosis against the real file.

Prints, for a given STEP file:
1. Every PRODUCT entity line from the raw text (product names).
2. Every NEXT_ASSEMBLY_USAGE_OCCURRENCE line (occurrence names --
   what CAD Assistant/FreeCAD display; a blank second field here is
   the smoking gun).
3. The reader's reconstructed tree with occurrence AND referred names
   at every level (what Kodacad displays).

Run: uv run probe_names.py <file.step>
"""

import sys

from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence, TDF_Tool
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.IFSelect import IFSelect_RetDone


def create_doc():
    doc_format = "BinXCAF"
    doc = TDocStd_Document(TCollection_ExtendedString(doc_format))
    app = XCAFApp_Application.GetApplication_s()
    app.NewDocument(TCollection_ExtendedString(doc_format), doc)
    BinXCAFDrivers.DefineFormat_s(app)
    return doc, app


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


def dump_names(shape_tool, label, depth=0):
    """Occurrence name AND referred/product name at every level."""
    ref = TDF_Label()
    if shape_tool.GetReferredShape_s(label, ref):
        print(f"{'  '*depth}occurrence={get_name(label)!r}  ->  "
              f"product={get_name(ref)!r}  (entry {get_entry(ref)})")
        kids = TDF_LabelSequence()
        shape_tool.GetComponents_s(ref, kids, False)
        for i in range(1, kids.Length() + 1):
            dump_names(shape_tool, kids.Value(i), depth + 1)
    else:
        print(f"{'  '*depth}free shape / product: {get_name(label)!r} "
              f"(entry {get_entry(label)})")
        kids = TDF_LabelSequence()
        shape_tool.GetComponents_s(label, kids, False)
        for i in range(1, kids.Length() + 1):
            dump_names(shape_tool, kids.Value(i), depth + 1)


def main():
    if len(sys.argv) != 2:
        print("Usage: uv run probe_names.py <file.step>")
        sys.exit(1)
    fname = sys.argv[1]

    with open(fname, errors="replace") as f:
        raw = f.read()

    print("=" * 70)
    print("1. PRODUCT entities (product names)")
    print("=" * 70)
    # STEP lines can wrap; join then split on ';' for whole entities
    entities = raw.replace("\n", "").split(";")
    n = 0
    for ent in entities:
        s = ent.strip()
        if "= PRODUCT(" in s or "=PRODUCT(" in s:
            print(f"  {s[:120]}")
            n += 1
    if n == 0:
        print("  (none found)")

    print()
    print("=" * 70)
    print("2. NEXT_ASSEMBLY_USAGE_OCCURRENCE entities (occurrence names --")
    print("   what CAD Assistant/FreeCAD display; blank 2nd field = the")
    print("   Session 17 identical-names blanking)")
    print("=" * 70)
    n = 0
    for ent in entities:
        s = ent.strip()
        if "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in s:
            print(f"  {s[:150]}")
            n += 1
    if n == 0:
        print("  (none found)")

    print()
    print("=" * 70)
    print("3. Reader's reconstructed tree (what Kodacad displays)")
    print("=" * 70)
    doc, app = create_doc()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    status = reader.ReadFile(fname)
    if status != IFSelect_RetDone:
        print(f"ERROR: could not read {fname}")
        sys.exit(1)
    reader.Transfer(doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free_labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_labels)
    for i in range(1, free_labels.Length() + 1):
        dump_names(shape_tool, free_labels.Value(i))


if __name__ == "__main__":
    main()
