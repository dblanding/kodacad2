"""
probe_step_files.py -- inspect REAL KodaCAD session files (Session 136).

Usage (from the kodacad2 project folder):
    uv run python probe_step_files.py s1.stp s2.stp s3.stp

Give it files in the order they were saved: e.g. save a session that
contains a lofted part as s1.stp, load it, save as s2.stp, load that,
save as s3.stp. For every file it prints:

  * size, and a histogram of STEP entity types
  * what CHANGED in that histogram versus the previous file (this is
    what shows exactly what grows from one save/load cycle to the next)
  * after reading the file back the way the app does: every part that
    contains a solid -- its name, where its color lives (if anywhere),
    and its face/edge geometry types, B-spline pole counts, tolerances
    and volume

Run it on a lofted-part session and (as a control) an analytic-part
session to compare.
"""
import os
import re
import sys

import docmodel
import probe_loft_roundtrip as P
from OCP.TDF import TDF_LabelSequence
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool


def entity_histogram(path):
    with open(path, "r", errors="replace") as f:
        text = f.read()
    data = text.split("DATA;", 1)[-1].split("ENDSEC;", 1)[0]
    hist = {}
    for stmt in data.split(";"):
        m = re.match(r"\s*#\d+\s*=\s*(.*)", stmt, re.S)
        if not m:
            continue
        body = m.group(1).strip()
        if body.startswith("("):
            names = sorted(set(re.findall(r"([A-Z][A-Z0-9_]{3,})\s*\(", body)))
            key = "COMPLEX(" + "+".join(names[:4]) + ")"
        else:
            key = re.match(r"([A-Z0-9_]+)", body).group(1)
        hist[key] = hist.get(key, 0) + 1
    return hist


def parts_with_solids(doc):
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    out = []
    for i in range(1, labels.Length() + 1):
        lab = labels.Value(i)
        shp = XCAFDoc_ShapeTool.GetShape_s(lab)
        if shp.IsNull() or not XCAFDoc_ShapeTool.IsSimpleShape_s(lab):
            continue
        if TopExp_Explorer(shp, TopAbs_SOLID).More():
            out.append((docmodel.get_label_name(lab), lab, shp))
    return out


def main(paths):
    prev = None
    for path in paths:
        print("=" * 72)
        print(f"{path}: {os.path.getsize(path)} bytes")
        print("=" * 72)
        hist = entity_histogram(path)
        top = sorted(hist.items(), key=lambda kv: -kv[1])[:20]
        print("  top entity types:", dict(top))
        if prev is not None:
            changed = {k: (prev.get(k, 0), hist.get(k, 0))
                       for k in set(prev) | set(hist)
                       if prev.get(k, 0) != hist.get(k, 0)}
            print("  CHANGED vs previous file (entity: before -> after):")
            if not changed:
                print("    (no entity-count changes at all)")
            for k in sorted(changed):
                print(f"    {k}: {changed[k][0]} -> {changed[k][1]}")
        prev = hist
        try:
            doc = P.read_step(path)
        except Exception as e:
            print(f"  READ FAILED: {e}")
            continue
        for name, lab, shp in parts_with_solids(doc):
            print(f"  PART {name!r}")
            print(f"    COLOR  {P.color_report(doc, lab, shp)}")
            print(f"    GEOM   {P.geometry_report(doc, lab, shp)}")
    print("=" * 72)
    print("Done. Please paste this whole output back.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
