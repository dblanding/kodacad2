"""
smoke_test_wp_set_and_loft.py -- headless validation of:

  1. The make_faces() refactor (Session 128): it was split into
     _chain_profile_loops / _loops_to_wires_and_polys /
     _classify_loop_depth so the new outer_profile_wire() could reuse
     the same logic instead of duplicating it. CASES 1-3 below are a
     regression check -- make_faces() must still do exactly what it
     did before the refactor.

  2. outer_profile_wire() itself (new, for the Loft command): returns
     the single top-level profile wire on a workplane, or a clear
     error. CASES 1, 3 and 4 exercise it directly.

  3. The actual Loft code path kodacad.py's loftWpSet() runs: build N
     WorkPlanes the same way wp_set_dialog.py does (gp_Ax3 translated
     along +W), sketch a circle on each via wp.circle() (the same
     method the 2D UI itself calls), pull outer_profile_wire() from
     each, and feed the wires into BRepOffsetAPI_ThruSections exactly
     as loftWpSet() does -- isSolid=True, ruled=False,
     CheckCompatibility(True). CASE 5 validates the result against a
     known analytic answer (a loft between equal circles is a
     cylinder), the same ground-truth check
     smoke_test_loft_thru_sections.py's own CASE 1 used for the raw
     OCCT call -- this time through the real, wired-up code path
     instead of hand-built wires.

Run: uv run python smoke_test_wp_set_and_loft.py
"""

import math

from OCP.gp import gp_Ax3, gp_Vec
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

import workplane


def volume_of(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def main():
    # ---- CASE 1: single circle -- make_faces() and
    # outer_profile_wire() should both succeed, agreeing there's
    # exactly one profile ----
    print("=" * 70)
    print("CASE 1: single circle on a workplane")
    print("=" * 70)
    wp1 = workplane.WorkPlane(50)
    wp1.circle((0.0, 0.0), 10.0)
    faces, err = wp1.make_faces()
    print(f"  make_faces(): {len(faces)} face(s), err={err}")
    wire, werr = wp1.outer_profile_wire()
    print(f"  outer_profile_wire(): wire={'ok' if wire is not None else None}, "
         f"err={werr}")

    # ---- CASE 2: square with a circular hole -- make_faces() must
    # still build 1 face with 1 hole (regression); outer_profile_wire()
    # is defined to ignore holes and still succeed, returning just the
    # square ----
    print("=" * 70)
    print("CASE 2: square with a circular hole (regression + "
         "outer_profile_wire ignores holes)")
    print("=" * 70)
    wp2 = workplane.WorkPlane(50)
    wp2.line((-20, -20), (20, -20))
    wp2.line((20, -20), (20, 20))
    wp2.line((20, 20), (-20, 20))
    wp2.line((-20, 20), (-20, -20))
    wp2.circle((0.0, 0.0), 5.0)
    faces2, err2 = wp2.make_faces()
    print(f"  make_faces(): {len(faces2)} face(s), err={err2} "
         f"(expected 1 face, 1 hole)")
    wire2, werr2 = wp2.outer_profile_wire()
    print(f"  outer_profile_wire(): wire={'ok' if wire2 is not None else None}, "
         f"err={werr2} (expected ok -- hole ignored)")

    # ---- CASE 3: two disjoint circles on one workplane --
    # make_faces() should still build 2 separate faces (regression);
    # outer_profile_wire() should now REFUSE (ambiguous -- which one
    # is "the" profile for a loft section?) ----
    print("=" * 70)
    print("CASE 3: two disjoint circles (regression + "
         "outer_profile_wire refuses ambiguity)")
    print("=" * 70)
    wp3 = workplane.WorkPlane(50)
    wp3.circle((-15.0, 0.0), 5.0)
    wp3.circle((15.0, 0.0), 5.0)
    faces3, err3 = wp3.make_faces()
    print(f"  make_faces(): {len(faces3)} face(s), err={err3} "
         f"(expected 2 faces)")
    wire3, werr3 = wp3.outer_profile_wire()
    print(f"  outer_profile_wire(): wire={'ok' if wire3 is not None else None}, "
         f"err={werr3} (expected None, an error naming 2 profiles)")

    # ---- CASE 4: empty workplane -- outer_profile_wire() should
    # report "no profile", not crash ----
    print("=" * 70)
    print("CASE 4: empty workplane (no profile sketched)")
    print("=" * 70)
    wp4 = workplane.WorkPlane(50)
    wire4, werr4 = wp4.outer_profile_wire()
    print(f"  outer_profile_wire(): wire={'ok' if wire4 is not None else None}, "
         f"err={werr4} (expected None, 'no profile...')")

    # ---- CASE 5: the real Loft path -- 4 workplanes built the same
    # way wp_set_dialog.py builds a Workplane Set (translated along
    # +W from a reference wp's own origin/wDir/uDir), each with an
    # equal-radius circle sketched via wp.circle() (the same call the
    # 2D UI itself uses), lofted exactly as loftWpSet() does. Ground
    # truth: a loft between equal circles is a cylinder. ----
    print("=" * 70)
    print("CASE 5: end-to-end Loft path -- 4 equal-radius circles, "
         "spaced 10mm apart -- should loft into a cylinder")
    print("=" * 70)
    r = 8.0
    d = 10.0
    n = 4
    ref_wp = workplane.WorkPlane(50)  # default wp: origin (0,0,0), W=+Z
    origin = ref_wp.origin
    wDir = ref_wp.wDir
    uDir = ref_wp.uDir
    wVec = gp_Vec(wDir)

    section_wps = []
    for i in range(n):
        new_origin = origin.Translated(wVec * (d * i))
        axis3 = gp_Ax3(new_origin, wDir, uDir)
        wp = workplane.WorkPlane(50, ax3=axis3)
        wp.circle((0.0, 0.0), r)
        section_wps.append(wp)

    wires = []
    ok = True
    for i, wp in enumerate(section_wps):
        wire, err = wp.outer_profile_wire()
        if err is not None:
            print(f"  station {i}: outer_profile_wire() FAILED: {err}")
            ok = False
            continue
        wires.append(wire)
    print(f"  collected {len(wires)}/{n} section wires")

    if ok and len(wires) == n:
        ts = BRepOffsetAPI_ThruSections(True, False)  # isSolid, ruled
        ts.CheckCompatibility(True)
        for w in wires:
            ts.AddWire(w)
        ts.Build()
        print(f"  IsDone={ts.IsDone()}")
        if ts.IsDone():
            shape = ts.Shape()
            valid = BRepCheck_Analyzer(shape).IsValid()
            vol = volume_of(shape)
            h = d * (n - 1)
            expected = math.pi * r * r * h
            print(f"  BRepCheck_Analyzer.IsValid()={valid}")
            print(f"  volume={vol:.3f}  expected(pi*r^2*h)={expected:.3f}"
                 f"  diff={abs(vol - expected):.6f}")


if __name__ == "__main__":
    main()
