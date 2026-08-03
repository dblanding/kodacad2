"""
probe_colors.py -- one-shot diagnostic: where (or whether) does a
STEP file actually store its colors?

Session 53's instrumented import reported "top-level none, sub-shape
colors transferred: 0" for real vendor part files -- neither the part
labels nor their registered sub-shapes carry colors where the
transfer code looks. Two very different explanations remain:
(a) these files genuinely contain no color data at all, or
(b) colors exist but are stored somewhere the scan doesn't reach.

This script settles it with data instead of another guess:

1. RAW FILE scan: counts COLOUR_RGB / DRAUGHTING_PRE_DEFINED_COLOUR /
   STYLED_ITEM / OVER_RIDING_STYLED_ITEM entities in the file text.
   Zero COLOUR_RGB and zero styled items = the file has no colors,
   full stop, and the investigation ends there.
2. Reads the file via STEPCAFControl_Reader (color mode on) and dumps
   the color tool's ENTIRE color table (GetColors) -- every color the
   reader registered, regardless of what it's attached to.
3. Walks EVERY shape label in the document (GetShapes_s), reporting
   for each: entry, name, kind (assembly/simple/reference), sub-shape
   label count, and its color status via every read variant (shape-
   keyed instance Surf/Gen/Curv, label-keyed static Surf/Gen/Curv) --
   plus the same for every sub-shape label.

Run: uv run probe_colors.py <some_vendor_part.step>
"""

import sys

from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.XCAFDoc import (
    XCAFDoc_DocumentTool,
    XCAFDoc_ColorTool,
    XCAFDoc_ShapeTool,
    XCAFDoc_ColorGen,
    XCAFDoc_ColorSurf,
    XCAFDoc_ColorCurv,
)
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_LabelSequence, TDF_Tool
from OCP.Quantity import Quantity_Color
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


def color_status(color_tool, shape_tool, label):
    """Report every read variant's result for one label, as a compact
    string like 'shapeSurf shapeGen labelSurf' (only the hits)."""
    hits = []
    color = Quantity_Color()
    try:
        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        for ctype, tag in ((XCAFDoc_ColorSurf, "shapeSurf"),
                           (XCAFDoc_ColorGen, "shapeGen"),
                           (XCAFDoc_ColorCurv, "shapeCurv")):
            try:
                if color_tool.GetColor(shape, ctype, color):
                    hits.append(f"{tag}=({color.Red():.2f},"
                                f"{color.Green():.2f},{color.Blue():.2f})")
            except Exception:
                pass
    except Exception:
        pass
    for ctype, tag in ((XCAFDoc_ColorSurf, "labelSurf"),
                       (XCAFDoc_ColorGen, "labelGen"),
                       (XCAFDoc_ColorCurv, "labelCurv")):
        try:
            if XCAFDoc_ColorTool.GetColor_s(label, ctype, color):
                hits.append(f"{tag}=({color.Red():.2f},"
                            f"{color.Green():.2f},{color.Blue():.2f})")
        except Exception:
            pass
    return " ".join(hits) if hits else "NO COLOR (any variant)"


def main():
    if len(sys.argv) != 2:
        print("Usage: uv run probe_colors.py <file.step>")
        sys.exit(1)
    fname = sys.argv[1]

    print("=" * 70)
    print(f"1. RAW FILE TEXT SCAN of {fname}")
    print("=" * 70)
    with open(fname, errors="replace") as f:
        raw = f.read()
    for entity in ("COLOUR_RGB", "DRAUGHTING_PRE_DEFINED_COLOUR",
                   "STYLED_ITEM", "OVER_RIDING_STYLED_ITEM",
                   "PRESENTATION_STYLE_ASSIGNMENT"):
        count = raw.count(entity)
        print(f"  {entity}: {count}")
    print("\n  (zero COLOUR_RGB / DRAUGHTING_PRE_DEFINED_COLOUR and zero")
    print("  styled items = the file simply contains no color data,")
    print("  and yellow-in-Kodacad is just the no-color default.)")

    print()
    print("=" * 70)
    print("2. Reading via STEPCAFControl_Reader (color mode ON)")
    print("=" * 70)
    doc, app = create_doc()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    reader.SetNameMode(True)
    reader.SetMatMode(True)
    status = reader.ReadFile(fname)
    if status != IFSelect_RetDone:
        print(f"ERROR: could not read {fname}")
        sys.exit(1)
    reader.Transfer(doc)

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    color_labels = TDF_LabelSequence()
    color_tool.GetColors(color_labels)
    print(f"\nColor table: {color_labels.Length()} registered color(s)")
    for i in range(1, color_labels.Length() + 1):
        cl = color_labels.Value(i)
        color = Quantity_Color()
        decoded = ""
        try:
            if XCAFDoc_ColorTool.GetColor_s(cl, color):
                decoded = (f" rgb=({color.Red():.2f},{color.Green():.2f},"
                           f"{color.Blue():.2f})")
        except Exception:
            pass
        print(f"  entry={get_entry(cl)} name={get_name(cl)!r}{decoded}")

    print()
    print("=" * 70)
    print("3. Every shape label and its color status")
    print("=" * 70)
    all_labels = TDF_LabelSequence()
    shape_tool.GetShapes(all_labels)
    for i in range(1, all_labels.Length() + 1):
        label = all_labels.Value(i)
        if shape_tool.IsAssembly_s(label):
            kind = "assembly"
        elif shape_tool.IsReference_s(label):
            kind = "reference"
        else:
            kind = "simple"
        subs = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetSubShapes_s(label, subs)
        print(f"\nentry={get_entry(label)} name={get_name(label)!r} "
              f"({kind}, {subs.Length()} sub-shape label(s))")
        print(f"  {color_status(color_tool, shape_tool, label)}")
        for j in range(1, subs.Length() + 1):
            sub = subs.Value(j)
            print(f"  sub entry={get_entry(sub)} name={get_name(sub)!r}: "
                  f"{color_status(color_tool, shape_tool, sub)}")


if __name__ == "__main__":
    main()
