"""
position_math.py

POSITIONING MATH -- geometry for the Mate/Align workflow (Position
dialog). Ported from Doug's Basicad project (src/pose.py), which
solved this same problem already -- but Basicad is built on build123d,
and Kodacad deliberately does NOT take a build123d dependency (it
would risk the STEP round-trip fidelity that's been the throughline of
this whole project -- see docs/DEVELOPMENT_LOG.md). Basicad's own
compute_*_move() functions turned out to already be almost entirely
raw OCP calls (gp_Trsf, gp_Ax1, gp_Dir, gp_Pnt) with build123d's
Vector/Location used only as thin point/direction bookkeeping -- so
this port replaces that thin layer with Vec3 (below) and returns
TopLoc_Location (Kodacad's native placement type) instead of
build123d's Location. The actual geometry math is unchanged.

Only Step 1 (Mate/Align) is ported and wired up so far -- Step 2,
Step 3, and Align Axis come next once Step 1 is proven working
end-to-end (pick -> compute -> dm.set_component_location -> persisted
-> survives save/reload).

One simplification vs. the original: compute_step1_move() had a
branch ("if result is not None: ... else: ...") that's provably
unreachable in the original too (by the point that code runs,
`result` has already been confirmed not-None earlier in the same
function) -- removed here as dead code, not a behavior change.

FUNCTIONS:

  resolve_face_pick(face)
    Resolve a picked planar TopoDS_Face into (Vec3 point, Vec3
    direction) = face centroid + outward normal. Kodacad's displayed
    part shapes are already world-located (confirmed in Session 13),
    so no extra transform is needed here.

  find_intersection_line(P1, N1, P2, N2)
    Return (point, direction) of the intersection line of two planes,
    or None if the planes are parallel.

  compute_step1_move(pick1, pick2, mate)
    Step 1: rotate about the intersection line of the two face planes
    until they're flush. mate=True: normals become opposed (Mate).
    mate=False: normals become parallel (Align). Falls back to a pure
    translation when the planes are already parallel (the rotation
    axis is "at infinity").
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Vec3 -- minimal dependency-free 3D vector.
#
# Deliberately NOT build123d.Vector and NOT a wrapper around
# OCP.gp.gp_Vec -- just three plain floats. This is the whole reason
# the port avoids a build123d dependency: Basicad's ported functions
# only ever use a handful of Vector operations (X/Y/Z, +, -, unary -,
# scalar *, dot, cross, normalized, length), all of which are trivial
# to replicate here with zero framework dependency and zero impact on
# Kodacad's XCAF/STEP handling (this module never touches document
# I/O -- it only turns picked points/directions into a TopLoc_Location).
# ---------------------------------------------------------------------------

class Vec3:
    __slots__ = ("X", "Y", "Z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.X = x
        self.Y = y
        self.Z = z

    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.X + other.X, self.Y + other.Y, self.Z + other.Z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.X - other.X, self.Y - other.Y, self.Z - other.Z)

    def __neg__(self) -> "Vec3":
        return Vec3(-self.X, -self.Y, -self.Z)

    def __mul__(self, scalar: float) -> "Vec3":
        return Vec3(self.X * scalar, self.Y * scalar, self.Z * scalar)

    __rmul__ = __mul__

    def dot(self, other: "Vec3") -> float:
        return self.X * other.X + self.Y * other.Y + self.Z * other.Z

    def cross(self, other: "Vec3") -> "Vec3":
        return Vec3(
            self.Y * other.Z - self.Z * other.Y,
            self.Z * other.X - self.X * other.Z,
            self.X * other.Y - self.Y * other.X,
        )

    @property
    def length(self) -> float:
        return (self.X ** 2 + self.Y ** 2 + self.Z ** 2) ** 0.5

    def normalized(self) -> "Vec3":
        L = self.length
        if L < 1e-12:
            # Same guard Basicad's circle-fit needed for a real,
            # confirmed failure mode (collinear points -> zero-length
            # normal -> OCCT's own uncatchable-by-ValueError error) --
            # cheap insurance here for the analogous case (parallel/
            # degenerate directions).
            raise ValueError("Cannot normalize a zero-length Vec3")
        return Vec3(self.X / L, self.Y / L, self.Z / L)

    @classmethod
    def from_gp(cls, p) -> "Vec3":
        """Build from a gp_Pnt, gp_Vec, or gp_Dir (all expose X()/Y()/Z())."""
        return cls(p.X(), p.Y(), p.Z())

    def to_gp_pnt(self):
        from OCP.gp import gp_Pnt
        return gp_Pnt(self.X, self.Y, self.Z)

    def to_gp_dir(self):
        from OCP.gp import gp_Dir
        return gp_Dir(self.X, self.Y, self.Z)

    def to_gp_vec(self):
        from OCP.gp import gp_Vec
        return gp_Vec(self.X, self.Y, self.Z)

    def __repr__(self):
        return f"Vec3({self.X:.3f}, {self.Y:.3f}, {self.Z:.3f})"


@dataclass
class PickResult:
    """Resolved geometry from a single viewport pick."""
    point: Vec3
    direction: Optional[Vec3]
    label: str = ""


def resolve_face_pick(face) -> PickResult:
    """Resolve a picked planar TopoDS_Face into a PickResult (centroid
    + outward normal). Reuses the exact face_normal() helper already
    proven in workplane.py (handles face orientation correctly via
    TopAbs_REVERSED) rather than re-deriving face-normal logic here.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from workplane import face_normal

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    center = Vec3.from_gp(props.CentreOfMass())

    normal = face_normal(face)  # gp_Dir, already orientation-corrected
    direction = Vec3.from_gp(normal)

    return PickResult(point=center, direction=direction, label="face normal")


def find_intersection_line(P1: Vec3, N1: Vec3, P2: Vec3, N2: Vec3):
    """
    Find the intersection line of two infinite planes.

    Plane 1: N1 . (X - P1) = 0
    Plane 2: N2 . (X - P2) = 0

    Returns (point_on_line, direction) where:
      - direction = N1 x N2 (normalized)
      - point_on_line = the point on L closest to the midpoint of
        P1, P2 (a well-defined unique point even though L is infinite)

    Returns None if the planes are parallel (|N1 x N2| < tol), in
    which case the caller should fall back to pure translation.
    """
    D = N1.cross(N2)
    d_len_sq = D.dot(D)

    TOL = 1e-8
    if d_len_sq < TOL:
        return None  # planes are parallel

    D_norm = D * (1.0 / d_len_sq ** 0.5)

    d1 = N1.dot(P1)
    d2 = N2.dot(P2)

    # Point on L closest to origin
    P_origin = (N2 * d1 - N1 * d2).cross(D) * (1.0 / d_len_sq)

    # Project midpoint of P1,P2 onto L for a more central reference point
    M = (P1 + P2) * 0.5
    P_near = P_origin + D_norm * (M - P_origin).dot(D_norm)

    return P_near, D_norm


def compute_two_points_move(p1: Vec3, p2: Vec3):
    """2 Points method: pure translation from p1 to p2, no rotation.
    Same math as the original standalone 2-Points command (kodacad.py,
    Session 13), just expressed as a Vec3-based function here so the
    Position dialog can go through position_math.py for every method
    rather than duplicating gp_Trsf construction inline.
    """
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location
    delta = p2 - p1
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(delta.X, delta.Y, delta.Z))
    return TopLoc_Location(t)


def compute_step1_move(pick1: PickResult, pick2: PickResult,
                       mate: bool = True):
    """
    Step 1 of the 3-2-1 workflow: rotate the moving part about the
    intersection line of the two face planes until the faces are
    flush.

    mate=True:  normals become OPPOSED  (N1_new = -N2)
    mate=False: normals become PARALLEL (N1_new = +N2)

    If the planes are already parallel (degenerate intersection
    line), falls back to a pure translation along the target normal
    to close the gap between the faces -- the axis is "at infinity"
    so rotation degenerates to translation.

    Returns a TopLoc_Location (world-space delta) to be applied via
    dm.set_component_location() (after converting world -> local),
    or None if the picks aren't usable (e.g. not directed picks).
    """
    from OCP.gp import gp_Ax1, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    P1, N1 = pick1.point, pick1.direction
    P2, N2 = pick2.point, pick2.direction

    if N1 is None or N2 is None:
        print("[position_math] Step 1 requires directed picks (faces).")
        return None

    target_N1 = -N2 if mate else N2

    result = find_intersection_line(P1, N1, P2, N2)

    if result is None:
        # Planes are parallel (N1 || N2).
        gap = (P2 - P1).dot(N2)
        tv = N2 * gap
        trans_trsf = gp_Trsf()
        trans_trsf.SetTranslation(gp_Vec(tv.X, tv.Y, tv.Z))
        trans_loc = TopLoc_Location(trans_trsf)

        needs_rotation = (mate and N1.dot(N2) > 0) or \
                         (not mate and N1.dot(N2) < 0)
        if not needs_rotation:
            return trans_loc

        # 180-degree rotation about an axis perpendicular to N1, through P1
        arbitrary = Vec3(1, 0, 0) if abs(N1.dot(Vec3(1, 0, 0))) < 0.9 \
            else Vec3(0, 1, 0)
        rot_axis = N1.cross(arbitrary).normalized()
        ax = gp_Ax1(P1.to_gp_pnt(), rot_axis.to_gp_dir())
        rot_trsf = gp_Trsf()
        rot_trsf.SetRotation(ax, math.pi)
        rot_loc = TopLoc_Location(rot_trsf)
        return trans_loc.Multiplied(rot_loc)

    L_point, L_dir = result

    cross = N1.cross(target_N1)
    sin_a = cross.length
    cos_a = N1.dot(target_N1)
    angle = math.atan2(sin_a, cos_a)

    if abs(angle) < 1e-6:
        # N1 already equals target_N1 -- just close the gap with translation
        gap = (P2 - P1).dot(target_N1)
        tv = target_N1 * gap
        t = gp_Trsf()
        t.SetTranslation(gp_Vec(tv.X, tv.Y, tv.Z))
        return TopLoc_Location(t)

    if sin_a < 1e-8:
        # N1 ~= -target_N1: 180-degree rotation needed.
        ax = gp_Ax1(L_point.to_gp_pnt(), L_dir.to_gp_dir())
        t = gp_Trsf()
        t.SetRotation(ax, math.pi)
        return TopLoc_Location(t)

    # Rotation axis: L_dir, sign-aligned to N1 x target_N1 so the
    # rotation goes the right way.
    if cross.dot(L_dir) < 0:
        L_dir = -L_dir

    ax = gp_Ax1(L_point.to_gp_pnt(), L_dir.to_gp_dir())
    t = gp_Trsf()
    t.SetRotation(ax, angle)
    return TopLoc_Location(t)
