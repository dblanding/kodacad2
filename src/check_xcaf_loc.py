"""Check how to correctly get location from a component label in OCP."""
import sys, os

# Run from kodacad2/ directory or find step file
step_file = None
for candidate in [
    'step/as1-oc-214.stp',
    '../step/as1-oc-214.stp',
    os.path.expanduser('~/Desktop/kodacad2/step/as1-oc-214.stp'),
]:
    if os.path.exists(candidate):
        step_file = os.path.abspath(candidate)
        break

if not step_file:
    print("Could not find as1-oc-214.stp -- run from kodacad2/ directory")
    sys.exit(1)

print(f"Using: {step_file}")

# Add kodacad2/ to path for docmodel import
kodacad2_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, kodacad2_dir)

from docmodel import create_doc, get_label_name
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_Location
from OCP.TDF import TDF_LabelSequence

doc, app = create_doc()
reader = STEPCAFControl_Reader()
reader.SetNameMode(True)
reader.SetColorMode(True)
status = reader.ReadFile(step_file)
if status != IFSelect_RetDone:
    print(f"ReadFile failed: {status}")
    sys.exit(1)
reader.Transfer(doc)
print("File loaded OK")

shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
labels = TDF_LabelSequence()
shape_tool.GetShapes(labels)
root_label = labels.Value(1)

comps = TDF_LabelSequence()
shape_tool.GetComponents_s(root_label, comps, False)
c_label = comps.Value(1)
print(f"Component: {get_label_name(c_label)}")

# Approach 1: FindAttribute
loc_attr = XCAFDoc_Location()
found = c_label.FindAttribute(XCAFDoc_Location.GetID_s(), loc_attr)
print(f"Approach 1 - FindAttribute found: {found}")
if found:
    loc = loc_attr.Get()
    t = loc.Transformation()
    print(f"  IsIdentity: {loc.IsIdentity()}")
    print(f"  Translation: {t.TranslationPart().X():.2f}, {t.TranslationPart().Y():.2f}, {t.TranslationPart().Z():.2f}")

# Approach 2: GetLoc_s
try:
    loc2 = XCAFDoc_Location.GetLoc_s(c_label)
    t2 = loc2.Transformation()
    print(f"Approach 2 - GetLoc_s IsIdentity: {loc2.IsIdentity()}")
    print(f"  Translation: {t2.TranslationPart().X():.2f}, {t2.TranslationPart().Y():.2f}, {t2.TranslationPart().Z():.2f}")
except Exception as e:
    print(f"Approach 2 - GetLoc_s failed: {e}")

# Approach 3: shape.Location()
shape = shape_tool.GetShape_s(c_label)
loc3 = shape.Location()
t3 = loc3.Transformation()
print(f"Approach 3 - shape.Location() IsIdentity: {loc3.IsIdentity()}")
print(f"  Translation: {t3.TranslationPart().X():.2f}, {t3.TranslationPart().Y():.2f}, {t3.TranslationPart().Z():.2f}")
