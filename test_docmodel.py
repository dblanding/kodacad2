"""Quick smoke test: verify docmodel.py OCP port works."""
import sys
sys.path.insert(0, '.')

from docmodel import create_doc, DocModel, load_stp_undr_top
from OCP.XCAFDoc import XCAFDoc_DocumentTool

doc, app = create_doc()
print("create_doc(): OK")

dm = DocModel()
print("DocModel(): OK")

# Verify shape tool works
from OCP.TDF import TDF_LabelSequence
shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(dm.doc.Main())
labels = TDF_LabelSequence()
shape_tool.GetShapes(labels)
print(f"Empty doc has {labels.Length()} shapes: OK")

print("\nAll docmodel smoke tests passed.")
