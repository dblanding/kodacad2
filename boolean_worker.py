"""
boolean_worker.py -- runs ONE Boolean (fuse / cut / common) in its own
process (Session 181).

Why: OCCT's Boolean engine can run away on degenerate geometry (Doug's
frame of 8 in round bars of EQUAL diameter whose axes cross made it eat
all the memory until the laptop froze). In this separate process the
application can watch it, stop it on request, and kill it when it uses
too much memory or time -- the application and the document stay intact.

Usage (called by safe_boolean.py, not by hand):
    python -I boolean_worker.py OP A.brep B.brep OUT.brep
OP is fuse | cut | common (A fuse B, A cut B, A common B).

Self-contained on purpose (run with -I, imports no KodaCAD module).
Prints ONE JSON line: {"done": bool, "errors": bool, "null": bool}
and writes the result to OUT.brep when there is one.
"""
import faulthandler
import json
import sys

faulthandler.enable()

from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import (BRepAlgoAPI_Common, BRepAlgoAPI_Cut,
                             BRepAlgoAPI_Fuse)
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape

OPS = {"fuse": BRepAlgoAPI_Fuse, "cut": BRepAlgoAPI_Cut,
       "common": BRepAlgoAPI_Common}


def main(op_name, a_path, b_path, out_path):
    # Test hook: KODACAD_BOOLEAN_TEST_SLEEP=<seconds> makes every Boolean
    # wait first, to try the busy box / Cancel / time limit without
    # needing a genuinely slow Boolean.
    import os
    import time
    delay = os.environ.get("KODACAD_BOOLEAN_TEST_SLEEP")
    if delay:
        time.sleep(float(delay))
    a, b = TopoDS_Shape(), TopoDS_Shape()
    if not BRepTools.Read_s(a, a_path, BRep_Builder()) or \
            not BRepTools.Read_s(b, b_path, BRep_Builder()):
        print(json.dumps({"done": False, "errors": True, "null": True,
                          "read_failed": True}))
        return
    op = OPS[op_name](a, b)
    done = bool(op.IsDone())
    # HasErrors() is not exposed on every OCP build's Boolean classes
    # (Doug's: AttributeError) -- IsDone() plus a valid, non-null result
    # is what the caller relies on; the flag is informational only.
    try:
        errors = bool(op.HasErrors())
    except Exception:
        errors = False
    res = op.Shape() if done else None
    null = res is None or res.IsNull()
    if not null:
        BRepTools.Write_s(res, out_path)
    print(json.dumps({"done": done, "errors": errors, "null": null}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
