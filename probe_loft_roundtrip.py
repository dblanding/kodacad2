"""
probe_loft_roundtrip.py -- headless diagnosis of two observed
differences between LOFTED and ANALYTIC parts across the session
save/load cycle (Session 136):

  1. a lofted part loses its default beige color after save/load;
     analytic parts keep theirs.
  2. a lofted part's STEP file grows a little with every save/load
     cycle; analytic parts stay the same size.

This script builds the same document structure the app does
('/' assembly -> empty part component -> replace_shape-style
SetShape + shape-keyed SetColor), then runs N write->read cycles with
the app's own writer/reader configuration, and prints for every cycle:

  COLOR     where (if anywhere) the color survived: on the part's
            shape (Surf/Gen), on its label, or on a sub-shape
  GEOMETRY  face/edge geometry type counts, B-spline pole totals,
            max edge tolerance, volume
  FILE      bytes, and counts of the STEP entities that matter
            (B-spline surfaces/curves, cartesian points, styled
            items, colour entries, PCURVEs)

Cases (all through the same cycles):
  loft-A    loft solid, color set EXACTLY as replace_shape() does today
            (shape-keyed ColorSurf + ColorGen on the new shape)
  loft-C    loft solid, color set on the part's LABEL (ColorSurf + Gen)
            -- a candidate fix
  loft-F    loft solid, color set on every FACE (shape-keyed) --
            another candidate fix
  cyl-A     analytic cylinder, same as loft-A -- the CONTROL

Run from the kodacad2 project folder:
    uv run python probe_loft_roundtrip.py
Output files are kept (path printed) so they can be inspected.
"""

import math
import os
import re
import tempfile

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Solid
from OCP.XCAFDoc import (XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorTool,
                         XCAFDoc_DocumentTool, XCAFDoc_ShapeTool)
from OCP.XSControl import XSControl_WorkSession
from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

import docmodel  # the app's own create_doc / repair_unnamed_products

N_CYCLES = 4
# kodacad.DEFAULT_COLOR, the color every new part is created with
BEIGE = Quantity_Color(0.6, 0.6, 0.4, Quantity_TypeOfColor.Quantity_TOC_RGB)


def rgb_str(c):
    return f"({c.Red():.3f}, {c.Green():.3f}, {c.Blue():.3f})"


# ------------------------------------------------------------------
# shapes
# ------------------------------------------------------------------
def make_loft():
    """Vase-like loft through 5 circles, built exactly the way the
    app's loftWpSet() does (isSolid=True, ruled=False,
    CheckCompatibility(True))."""
    radii = [8.0, 12.0, 14.0, 12.0, 8.0]
    ts = BRepOffsetAPI_ThruSections(True, False)
    ts.CheckCompatibility(True)
    for i, r in enumerate(radii):
        ax = gp_Ax2(gp_Pnt(0, 0, 10.0 * i), gp_Dir(0, 0, 1))
        edge = BRepBuilderAPI_MakeEdge(gp_Circ(ax, r)).Edge()
        wire = BRepBuilderAPI_MakeWire(edge).Wire()
        ts.AddWire(wire)
    ts.Build()
    assert ts.IsDone(), "loft failed"
    return ts.Shape()


def make_cylinder():
    return BRepPrimAPI_MakeCylinder(10.0, 40.0).Shape()


# ------------------------------------------------------------------
# document construction -- mirrors add_component() + replace_shape()
# ------------------------------------------------------------------
def build_doc(solid, color_mode):
    doc, app = docmodel.create_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    builder = BRep_Builder()
    root_shape = TopoDS_Compound()
    builder.MakeCompound(root_shape)
    root_label = shape_tool.AddShape(root_shape, True)  # '/'
    docmodel.set_label_name(root_label, "/")

    # createEmptyPart(): an empty TopoDS_Solid (NOT a compound -- an
    # empty compound passed to AddComponent(..., True) becomes an
    # ASSEMBLY label, and a later SetShape never makes it a part)
    empty_part = TopoDS_Solid()
    builder.MakeSolid(empty_part)
    comp_label = shape_tool.AddComponent(root_label, empty_part, True)
    ref_label = TDF_Label()
    shape_tool.GetReferredShape_s(comp_label, ref_label)
    docmodel.set_label_name(ref_label, "part_1")
    docmodel.set_label_name(comp_label, "part_1")
    # add_component(): label-keyed ColorGen on the referred label
    color_tool.SetColor(ref_label, BEIGE, XCAFDoc_ColorGen)

    # replace_shape(): SetShape on the label, then color
    shape_tool.SetShape(ref_label, solid)
    if color_mode == "A":
        color_tool.SetColor(solid, BEIGE, XCAFDoc_ColorSurf)
        color_tool.SetColor(solid, BEIGE, XCAFDoc_ColorGen)
    elif color_mode == "C":
        color_tool.SetColor(ref_label, BEIGE, XCAFDoc_ColorSurf)
        color_tool.SetColor(ref_label, BEIGE, XCAFDoc_ColorGen)
    elif color_mode == "F":
        exp = TopExp_Explorer(solid, TopAbs_FACE)
        while exp.More():
            face = TopoDS.Face_s(exp.Current())
            color_tool.SetColor(face, BEIGE, XCAFDoc_ColorSurf)
            exp.Next()
    shape_tool.UpdateAssemblies()
    return doc


# ------------------------------------------------------------------
# write / read -- same configuration as docmodel.save_step_doc / _load_step
# ------------------------------------------------------------------
def write_step(doc, path):
    docmodel.repair_unnamed_products(doc, context=" probe")
    try:
        Interface_Static.SetIVal_s("write.surfacecurve.mode", 0)
    except Exception as e:
        print(f"  (could not set write.surfacecurve.mode: {e})")
    ws = XSControl_WorkSession()
    writer = STEPCAFControl_Writer(ws, False)
    writer.Transfer(doc, STEPControl_AsIs)
    status = writer.Write(path)
    return status


def read_step(path):
    doc, app = docmodel.create_doc()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    reader.SetNameMode(True)
    reader.SetMatMode(True)
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"ReadFile status {status}")
    reader.Transfer(doc)
    return doc


# ------------------------------------------------------------------
# reports
# ------------------------------------------------------------------
def find_part_label(doc):
    """The label (simple shape) that holds the solid."""
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    for i in range(1, labels.Length() + 1):
        lab = labels.Value(i)
        shp = XCAFDoc_ShapeTool.GetShape_s(lab)
        if shp.IsNull():
            continue
        if TopExp_Explorer(shp, TopAbs_SOLID).More():
            if XCAFDoc_ShapeTool.IsSimpleShape_s(lab):
                return lab, shp
    return None, None


def color_report(doc, lab=None, shp=None):
    if lab is None:
        lab, shp = find_part_label(doc)
    if lab is None:
        return "NO PART WITH A SOLID FOUND"
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    found = []
    c = Quantity_Color()
    if color_tool.GetColor(shp, XCAFDoc_ColorSurf, c):
        found.append(f"shape-Surf{rgb_str(c)}")
    if color_tool.GetColor(shp, XCAFDoc_ColorGen, c):
        found.append(f"shape-Gen{rgb_str(c)}")
    if XCAFDoc_ColorTool.GetColor_s(lab, XCAFDoc_ColorSurf, c):
        found.append(f"label-Surf{rgb_str(c)}")
    if XCAFDoc_ColorTool.GetColor_s(lab, XCAFDoc_ColorGen, c):
        found.append(f"label-Gen{rgb_str(c)}")
    # sub-shapes (labels), the way get_part_display_color scans them
    n_sub = 0
    n_sub_colored = 0
    try:
        subs = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetSubShapes_s(lab, subs)
        n_sub = subs.Length()
        for i in range(1, n_sub + 1):
            sl = subs.Value(i)
            if (XCAFDoc_ColorTool.GetColor_s(sl, XCAFDoc_ColorSurf, c)
                    or XCAFDoc_ColorTool.GetColor_s(sl, XCAFDoc_ColorGen, c)):
                n_sub_colored += 1
    except Exception as e:
        found.append(f"(subshape scan failed: {e})")
    found.append(f"subshape-labels={n_sub}, colored={n_sub_colored}")
    # what the app's own display-color chain would conclude
    try:
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        disp = docmodel.get_part_display_color(color_tool, shape_tool,
                                               lab, shp)
        found.append(f"APP-DISPLAY-COLOR={rgb_str(disp)}")
    except Exception as e:
        found.append(f"(display-color chain failed: {e})")
    return "; ".join(found)


def geometry_report(doc, lab=None, shp=None):
    if lab is None:
        lab, shp = find_part_label(doc)
    if lab is None:
        return "no part"
    out = []
    out.append(f"shape-type={shp.ShapeType()}")
    surf_types = {}
    bs_poles = 0
    nfaces = 0
    max_ftol = 0.0
    exp = TopExp_Explorer(shp, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        nfaces += 1
        try:
            ad = BRepAdaptor_Surface(face)
            t = str(ad.GetType()).split(".")[-1]
            surf_types[t] = surf_types.get(t, 0) + 1
            if "BSpline" in t:
                bs = ad.BSpline()
                bs_poles += bs.NbUPoles() * bs.NbVPoles()
            max_ftol = max(max_ftol, BRep_Tool.Tolerance_s(face))
        except Exception as e:
            surf_types[f"err:{e}"] = surf_types.get(f"err:{e}", 0) + 1
        exp.Next()
    out.append(f"faces={nfaces} {surf_types} bspline-surface-poles={bs_poles}")
    curve_types = {}
    bc_poles = 0
    max_etol = 0.0
    exp = TopExp_Explorer(shp, TopAbs_EDGE)
    seen = []
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        exp.Next()
        if any(edge.IsSame(e) for e in seen):
            continue
        seen.append(edge)
        try:
            ad = BRepAdaptor_Curve(edge)
            t = str(ad.GetType()).split(".")[-1]
            curve_types[t] = curve_types.get(t, 0) + 1
            if "BSpline" in t:
                bc_poles += ad.BSpline().NbPoles()
            max_etol = max(max_etol, BRep_Tool.Tolerance_s(edge))
        except Exception as e:
            curve_types[f"err:{e}"] = curve_types.get(f"err:{e}", 0) + 1
    out.append(f"edges={len(seen)} {curve_types} bspline-curve-poles={bc_poles}")
    out.append(f"max-tol face={max_ftol:.3e} edge={max_etol:.3e}")
    try:
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shp, props)
        out.append(f"volume={props.Mass():.6f}")
    except Exception as e:
        out.append(f"(volume failed: {e})")
    return "\n        ".join(out)


ENTITIES = ["B_SPLINE_SURFACE_WITH_KNOTS", "B_SPLINE_CURVE_WITH_KNOTS",
            "RATIONAL_B_SPLINE", "CARTESIAN_POINT", "STYLED_ITEM",
            "COLOUR_RGB", "PCURVE", "ADVANCED_FACE", "EDGE_CURVE"]


def file_report(path):
    size = os.path.getsize(path)
    with open(path, "r", errors="replace") as f:
        text = f.read()
    counts = {k: len(re.findall(r"=\s*" + k + r"\b", text)) for k in ENTITIES}
    # B-spline entities can be complex (multi-part) entities: also count
    # plain substring hits for the surface/curve names
    counts["B_SPLINE_SURFACE (substr)"] = text.count("B_SPLINE_SURFACE")
    counts["B_SPLINE_CURVE (substr)"] = text.count("B_SPLINE_CURVE")
    counts["lines"] = text.count("\n")
    return size, counts


# ------------------------------------------------------------------
def run_case(label, solid, color_mode, outdir):
    print("=" * 72)
    print(f"CASE {label}")
    print("=" * 72)
    doc = build_doc(solid, color_mode)
    print(f"  before any save: COLOR  {color_report(doc)}")
    print(f"                   GEOM   {geometry_report(doc)}")
    sizes = []
    for cycle in range(1, N_CYCLES + 1):
        path = os.path.join(outdir, f"{label}_cycle{cycle}.stp")
        status = write_step(doc, path)
        size, counts = file_report(path)
        sizes.append(size)
        doc = read_step(path)
        print(f"  --- cycle {cycle}: wrote {os.path.basename(path)}  "
              f"{size} bytes (write status {status})")
        print(f"      FILE    {counts}")
        print(f"      COLOR   {color_report(doc)}")
        print(f"      GEOM    {geometry_report(doc)}")
    deltas = [sizes[i + 1] - sizes[i] for i in range(len(sizes) - 1)]
    print(f"  SIZES per cycle: {sizes}   growth between cycles: {deltas}")


def main():
    outdir = tempfile.mkdtemp(prefix="kodacad_probe_")
    print(f"Output files kept in: {outdir}")
    loft = make_loft()
    run_case("loft-A", loft, "A", outdir)
    run_case("loft-C", make_loft(), "C", outdir)
    run_case("loft-F", make_loft(), "F", outdir)
    run_case("cyl-A", make_cylinder(), "A", outdir)
    print("=" * 72)
    print("Done. Please paste this whole output back.")


if __name__ == "__main__":
    main()
