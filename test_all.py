"""Smoke test all ported modules (no GUI)."""
import sys
sys.path.insert(0, '.')

print("Testing docmodel...")
from docmodel import create_doc, DocModel
doc, app = create_doc()
dm = DocModel()
print("  docmodel: OK")

print("Testing workplane...")
from workplane import WorkPlane
wp = WorkPlane(100)
print("  workplane: OK")

print("Testing m2d...")
import m2d
print("  m2d: OK")

print("\nAll non-GUI modules passed.")
