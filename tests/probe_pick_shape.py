"""
probe_pick_shape.py -- what is structurally different about shapes
after a Kodacad session save/reload?

Doug's minimal repro (Session 60, the 2-can experiment): a freshly
created part hover-picks everywhere; after SAVE + RELOAD it picks
only via rays through its flat bottom face -- reproducible with
clean-history parts, so the damage happens in the save/reload cycle
itself. Flat faces always pick (outline sensitivity); curved faces
die. And the pre-mesh at AIS-build time did NOT cure it, so the
missing-mesh mechanism is not (or not the whole) story.

Prime remaining suspect: FACE ORIENTATION. An inverted face
(normal pointing INTO the solid) renders fine (two-sided shading)
but can defeat selection. This probe reads the session file the
same way Kodacad does and reports, per leaf part, per face:

- face orientation flag (FORWARD/REVERSED)
- surface type
- triangulation state as-read, then after forced meshing
- face tolerance
- whether the face normal (accounting for the orientation flag)
  points OUTWARD from the solid at the face's midpoint -- computed
  by nudging a point off the face along the oriented normal and
  asking the solid classifier whether it landed OUTSIDE (correct)
  or INSIDE (inverted).

Also reports each solid's own orientation and closedness.

Run: uv run probe_pick_shape.py <2can_session.step>
"""

import sys

from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.TCollection import TCollection_ExtendedString
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_Orientation, TopAbs_State
from OCP.TopoDS import TopoDS
from OCP.TopLoc import TopLoc_Location
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt, gp_Vec, gp_Ax2, gp_Dir
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.ShapeFix import ShapeFix_Shape


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
    return ""


def orient_str(o):
    try:
        return str(o).split(".")[-1]
    except Exception:
        return str(o)


def probe_solid(name, solid_shape):
    print(f"\n--- part {name!r} ---")
    print(f"  shape type={orient_str(solid_shape.ShapeType())} "
          f"orientation={orient_str(solid_shape.Orientation())} "
          f"closed={solid_shape.Closed()}")
    # SHELL-level flags -- one level deeper than faces. A mis-flagged
    # shell flips selection winding globally while rendering fine.
    sh_exp = TopExp_Explorer(solid_shape, TopAbs_ShapeEnum.TopAbs_SHELL)
    si = 0
    while sh_exp.More():
        si += 1
        sh = sh_exp.Current()
        nf = 0
        f_exp = TopExp_Explorer(sh, TopAbs_ShapeEnum.TopAbs_FACE)
        while f_exp.More():
            nf += 1
            f_exp.Next()
        print(f"  shell{si}: orientation={orient_str(sh.Orientation())} "
              f"closed={sh.Closed()} orientable={sh.Orientable()} "
              f"faces={nf}")
        sh_exp.Next()
    t = solid_shape.Location().Transformation().TranslationPart()
    print(f"  location translation=({t.X():.2f},{t.Y():.2f},{t.Z():.2f})")

    classifier = BRepClass3d_SolidClassifier(solid_shape)

    exp = TopExp_Explorer(solid_shape, TopAbs_ShapeEnum.TopAbs_FACE)
    i = 0
    while exp.More():
        i += 1
        face = TopoDS.Face_s(exp.Current())
        floc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, floc)
        n_before = tri.NbTriangles() if tri is not None else 0
        try:
            tol = BRep_Tool.Tolerance_s(face)
        except Exception:
            tol = -1.0
        surf = BRepAdaptor_Surface(face)
        stype = orient_str(surf.GetType())
        fo = orient_str(face.Orientation())

        # Normal direction check: point at mid-params, oriented
        # normal, nudge outward, classify.
        verdict = "?"
        try:
            u = (surf.FirstUParameter() + surf.LastUParameter()) / 2.0
            v = (surf.FirstVParameter() + surf.LastVParameter()) / 2.0
            geom_surf = BRep_Tool.Surface_s(face)
            props = GeomLProp_SLProps(geom_surf, u, v, 1, 1e-6)
            if props.IsNormalDefined():
                pnt = props.Value()
                nrm = props.Normal()
                # account for face orientation flag
                if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
                    nrm.Reverse()
                # account for the face's location (surface is in
                # local coords when the face carries a location)
                fl = face.Location()
                if not fl.IsIdentity():
                    trsf = fl.Transformation()
                    pnt = pnt.Transformed(trsf)
                    vn = gp_Vec(nrm.X(), nrm.Y(), nrm.Z())
                    vn.Transform(trsf)
                    nrm.SetCoord(vn.X(), vn.Y(), vn.Z())
                nudge = max(tol, 1e-4) * 10.0 + 0.05
                test = gp_Pnt(pnt.X() + nrm.X() * nudge,
                              pnt.Y() + nrm.Y() * nudge,
                              pnt.Z() + nrm.Z() * nudge)
                classifier.Perform(test, 1e-7)
                state = classifier.State()
                if state == TopAbs_State.TopAbs_OUT:
                    verdict = "OUTWARD (correct)"
                elif state == TopAbs_State.TopAbs_IN:
                    verdict = "INWARD (INVERTED!)"
                else:
                    verdict = f"state={orient_str(state)}"
        except Exception as ne:
            verdict = f"normal-check failed: {ne}"

        print(f"  face{i}: {stype} orient={fo} tol={tol:.2e} "
              f"tri_before={n_before} normal->{verdict}")
        exp.Next()

    # Now force-mesh and re-report triangle counts
    try:
        BRepMesh_IncrementalMesh(solid_shape, 0.1, False, 0.5, True)
        exp = TopExp_Explorer(solid_shape, TopAbs_ShapeEnum.TopAbs_FACE)
        i = 0
        counts = []
        while exp.More():
            i += 1
            face = TopoDS.Face_s(exp.Current())
            floc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(face, floc)
            counts.append(tri.NbTriangles() if tri is not None else 0)
            exp.Next()
        print(f"  after forced mesh: triangles per face = {counts}")
    except Exception as me:
        print(f"  forced mesh failed: {me}")


def main():
    if len(sys.argv) != 2:
        print("Usage: uv run probe_pick_shape.py <session.step>")
        sys.exit(1)
    fname = sys.argv[1]

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

    # Walk to leaf parts exactly the way parse_doc does: free shapes,
    # then components, resolving references.
    def walk(label, depth=0):
        ref = TDF_Label()
        if shape_tool.GetReferredShape_s(label, ref):
            target = ref
            name = get_name(label)
        else:
            target = label
            name = get_name(label)
        if shape_tool.IsAssembly_s(target):
            kids = TDF_LabelSequence()
            shape_tool.GetComponents_s(target, kids, False)
            for k in range(1, kids.Length() + 1):
                walk(kids.Value(k), depth + 1)
        else:
            shape = shape_tool.GetShape_s(label)
            probe_solid(name, shape)

    free_labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_labels)
    for i in range(1, free_labels.Length() + 1):
        walk(free_labels.Value(i))

    print("\n" + "=" * 60)
    print("BASELINE: fresh BRepPrimAPI_MakeCylinder (never saved)")
    print("=" * 60)
    fresh = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 5.0, 15.0).Shape()
    probe_solid("FRESH-BASELINE", fresh)

    print("\n" + "=" * 60)
    print("CURE TRIAL: reloaded parts after ShapeFix_Shape")
    print("=" * 60)

    def walk_fixed(label):
        ref = TDF_Label()
        if shape_tool.GetReferredShape_s(label, ref):
            target = ref
            name = get_name(label)
        else:
            target = label
            name = get_name(label)
        if shape_tool.IsAssembly_s(target):
            kids = TDF_LabelSequence()
            shape_tool.GetComponents_s(target, kids, False)
            for k in range(1, kids.Length() + 1):
                walk_fixed(kids.Value(k))
        else:
            shape = shape_tool.GetShape_s(label)
            try:
                sf = ShapeFix_Shape(shape)
                sf.Perform()
                probe_solid(f"{name} (healed)", sf.Shape())
            except Exception as fe:
                print(f"  ShapeFix failed for {name!r}: {fe}")

    for i in range(1, free_labels.Length() + 1):
        walk_fixed(free_labels.Value(i))


if __name__ == "__main__":
    main()
