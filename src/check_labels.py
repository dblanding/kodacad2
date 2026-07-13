"""Check what GetReferredShape returns for l-bracket-assembly_2"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/Desktop/kodacad2'))

from docmodel import create_doc, get_label_name, get_label_entry
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_LabelSequence, TDF_Label

# Find the STEP file
step_file = os.path.expanduser('~/Desktop/step/as1-oc-214.stp')
if not os.path.exists(step_file):
    for candidate in [
        'step/as1-oc-214.stp',
        '../step/as1-oc-214.stp',
    ]:
        if os.path.exists(candidate):
            step_file = os.path.abspath(candidate)
            break

print(f"Using: {step_file}")

doc, app = create_doc()
reader = STEPCAFControl_Reader()
reader.SetNameMode(True)
status = reader.ReadFile(step_file)
if status != IFSelect_RetDone:
    print(f"ReadFile failed: {status}")
    sys.exit(1)
reader.Transfer(doc)

shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
labels = TDF_LabelSequence()
shape_tool.GetShapes(labels)

print("\nRoot labels:")
for i in range(1, labels.Length() + 1):
    lbl = labels.Value(i)
    print(f"  {get_label_entry(lbl)} : {get_label_name(lbl)}")

# Find as1 components
root = labels.Value(1)
comps = TDF_LabelSequence()
shape_tool.GetComponents_s(root, comps, False)
print("\nas1 components and their referred labels:")
for i in range(1, comps.Length() + 1):
    c = comps.Value(i)
    ref = TDF_Label()
    is_ref = shape_tool.GetReferredShape_s(c, ref)
    ref_entry = get_label_entry(ref) if is_ref else 'none'
    ref_name = get_label_name(ref) if is_ref else ''
    is_simple = shape_tool.IsSimpleShape_s(ref) if is_ref else False
    is_assy = shape_tool.IsAssembly_s(ref) if is_ref else False
    print(f"  {get_label_entry(c)} : {get_label_name(c)}")
    print(f"    => ref={ref_entry} ({ref_name}) simple={is_simple} assy={is_assy}")
