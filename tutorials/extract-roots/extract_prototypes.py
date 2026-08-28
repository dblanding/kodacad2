"""Extract the leaf-level prototype shapes from as1-oc-214.stp into a
fresh, un-positioned 'kit of parts' session, for a tutorial that
rebuilds the assembly using the Position dialog's various methods.

Doug: run this with `uv run python extract_prototypes.py` from your
kodacad2 directory (needs OCP, which this sandbox doesn't have -- I
can't run or verify this myself, only reason through it against the
same docmodel.py functions used throughout the app).

What this does:
  1. Loads as1-oc-214.stp the same way KodaCAD's own load_stp_at_top
     does (via docmodel._load_step's own reader setup).
  2. Walks every shape label in the document via shape_tool.GetShapes,
     and keeps only the ones that are BOTH:
       - not a reference (shape_tool.IsReference_s is False) -- a
         genuine prototype, not a component/occurrence
       - not an assembly (shape_tool.IsAssembly_s is False) -- a
         leaf-level solid, not a compound of its own components
     This is a structural test, not a name-based guess. Doug confirmed
     it correctly finds exactly 5: rod, nut, bolt, l-bracket, plate.
  3. Creates a brand-new, empty document (matching create_doc()'s own
     pattern) and adds each selected shape as a component under its
     own '/' root, via add_component -- preserving each shape's own,
     native transform (identity/origin) rather than whatever world
     position it ends up at inside the full as1-oc-214 assembly.
  4. Transfers each part's real color from the source document, via
     docmodel's OWN, already-proven _transfer_color function -- see
     the note below on why this went through two failed attempts
     before landing here.
  5. Saves the result as as1-oc-214-kit-of-parts.stp.

Color history, for whoever reads this next: the first two attempts at
color transfer (this script re-implementing its own, simpler GetColor
call) both failed -- first from a wrong enum-vs-int argument, then
from passing the wrong color type (only tried XCAFDoc_ColorGen, never
XCAFDoc_ColorSurf) and possibly the wrong label/shape keying. Rather
than keep guessing at OCP's own overload behavior piece by piece,
this version calls docmodel._transfer_color directly -- the real,
already-proven function parse_doc()'s own color reading is built on,
which already handles three separate real-world color-storage
patterns (shape-keyed, label-keyed, and sub-shape-level colors) that
this script's own simpler attempts never accounted for.
"""


from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_LabelSequence
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
import sys
sys.path.insert(0, '../..')  # path to where docmodel.py is
import docmodel



SOURCE_FILE = "as1-oc-214.stp"
OUTPUT_FILE = "as1-oc-214-kit-of-parts.stp"


def load_source(path):
    """Read the source STEP file into a fresh XDE document, matching
    docmodel._load_step's own reader setup exactly (including calls
    this task doesn't strictly need, like SetLayerMode/SetMatMode --
    mirroring the proven pattern in full rather than guessing which
    parts are safe to drop)."""
    doc, app = docmodel.create_doc()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    reader.SetNameMode(True)
    reader.SetMatMode(True)
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Could not read {path} (status={status})")
    # _load_step doesn't check Transfer()'s own return value -- matching
    # that rather than inventing an unverified assumption about what it
    # reliably signals.
    reader.Transfer(doc)
    return doc


def find_leaf_prototypes(doc):
    """Every shape label that is neither a reference nor an assembly
    -- the structural definition of a leaf-level prototype part.
    Returns (name, shape, src_label) -- src_label is kept so color
    can be transferred later via docmodel._transfer_color, which
    needs the actual label, not just the extracted shape."""
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    all_labels = TDF_LabelSequence()
    shape_tool.GetShapes(all_labels)

    leaves = []
    for i in range(1, all_labels.Length() + 1):
        label = all_labels.Value(i)
        if shape_tool.IsReference_s(label):
            continue
        if shape_tool.IsAssembly_s(label):
            continue
        name = docmodel.get_label_name(label)
        shape = shape_tool.GetShape_s(label)
        leaves.append((name, shape, label))
    return leaves


def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else SOURCE_FILE
    out_path = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_FILE

    print(f"Loading {src_path}...")
    src_doc = load_source(src_path)

    leaves = find_leaf_prototypes(src_doc)
    print(f"Found {len(leaves)} leaf-level prototype shape(s):")
    for name, shape, src_label in leaves:
        print(f"  - {name!r}")

    print(f"\nBuilding a fresh 'kit of parts' document...")
    from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
    placeholder_color = Quantity_Color(
        0.8, 0.8, 0.8, Quantity_TypeOfColor.Quantity_TOC_RGB)
    dm = docmodel.DocModel()
    dm_shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(dm.doc.Main())
    dm_color_tool = XCAFDoc_DocumentTool.ColorTool_s(dm.doc.Main())
    for name, shape, src_label in leaves:
        new_uid = dm.add_component(shape, name, placeholder_color)
        entry = new_uid.split('.')[0]
        dst_label = dm._find_label_by_entry(entry)
        if dst_label is None:
            print(f"  [color] could not find the new label for "
                 f"{name!r} (entry {entry}) -- keeping placeholder gray")
            continue
        docmodel._transfer_color(
            src_label, dst_label, dm_shape_tool, dm_color_tool)

    print(f"Saving to {out_path}...")
    # Matches docmodel.save_step_doc's own, proven writer setup
    # exactly (minus the file dialog, since this script already has
    # out_path) -- including the PCURVE-suppression fix from earlier
    # work, which keeps the output file leaner.
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.XSControl import XSControl_WorkSession
    try:
        from OCP.Interface import Interface_Static
        Interface_Static.SetIVal_s("write.surfacecurve.mode", 0)
    except Exception as pe:
        print(f"  (could not disable PCURVE writing: {pe} -- "
             f"file will still be correct, just larger)")
    WS = XSControl_WorkSession()
    step_writer = STEPCAFControl_Writer(WS, False)
    step_writer.Transfer(dm.doc, STEPControl_AsIs)
    status = step_writer.Write(out_path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Write failed (status={status})")

    print(f"\nDone. {out_path} contains {len(leaves)} un-positioned "
         f"part(s), each a direct component under its own '/' root, "
         f"ready to drag, mate, and nudge into place.")


if __name__ == "__main__":
    main()
