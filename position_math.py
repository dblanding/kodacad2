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


@dataclass
class CircleFit:
    """Result of resolving a picked edge as a circle: center, axis
    (unit normal to the circle's plane), radius, and max_residual (how
    far the worst sampled point's distance-to-center deviates from the
    fitted radius -- 0.0 for a genuine CIRCLE-typed edge, used to
    decide whether a fitted result should be trusted)."""
    center: Vec3
    axis: Vec3
    radius: float
    max_residual: float


# Tolerance for accepting a circle-fit on a non-circle-typed edge.
# Compared against max_residual relative to the fitted radius (so it
# scales sensibly for both small holes and large shafts) rather than
# an absolute distance. Matches Basicad's own CIRCLE_FIT_RELATIVE_TOLERANCE.
CIRCLE_FIT_RELATIVE_TOLERANCE = 0.01  # 1% of fitted radius


def _fit_circle_to_edge(edge, num_samples: int = 12) -> CircleFit:
    """
    Sample points along ANY edge and fit a circle to them via least
    squares, regardless of the edge's actual curve type. Ported from
    Basicad's src/pose.py _fit_circle_to_edge -- same Kasa least-
    squares algebraic method, same collinear-points guard (a REAL,
    confirmed failure mode there: sampling a STRAIGHT edge makes every
    cross product in the normal-estimation step zero, and normalizing
    a zero vector raises an uncatchable-by-ValueError OCCT error that
    silently escaped every handler built around the original function
    -- detected explicitly here, before ever attempting that normalize).

    Samples by evenly-spaced PARAMETER value (not exact arc length,
    unlike Basicad's build123d-based position_at() which normalizes by
    arc length) -- a reasonable simplification for a first port; fine
    for anything close to circular, which is the only case this
    function's result gets trusted for anyway (see CIRCLE_FIT_RELATIVE_
    TOLERANCE below).
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    curve = BRepAdaptor_Curve(edge)
    u0, u1 = curve.FirstParameter(), curve.LastParameter()
    points = []
    for i in range(num_samples):
        u = u0 + (u1 - u0) * (i / num_samples)
        gp_pt = curve.Value(u)
        points.append(Vec3.from_gp(gp_pt))

    centroid = Vec3(0, 0, 0)
    for p in points:
        centroid = centroid + p
    centroid = centroid * (1.0 / len(points))

    normal_accum = Vec3(0, 0, 0)
    for i in range(len(points)):
        a = points[i] - centroid
        b = points[(i + 1) % len(points)] - centroid
        normal_accum = normal_accum + a.cross(b)

    if normal_accum.length < 1e-9:
        raise ValueError(
            "Cannot fit a circle: sampled points are collinear (or "
            "otherwise produce a degenerate/zero normal) -- this edge "
            "is not circular, even approximately.")
    normal = normal_accum.normalized()

    arbitrary = Vec3(0, 0, 1) if abs(normal.dot(Vec3(0, 0, 1))) < 0.9 else Vec3(0, 1, 0)
    u_ax = (arbitrary - normal * arbitrary.dot(normal)).normalized()
    v_ax = normal.cross(u_ax)

    xy = []
    for p in points:
        rel = p - centroid
        xy.append((rel.dot(u_ax), rel.dot(v_ax)))

    n = len(xy)
    sum_x = sum(p[0] for p in xy)
    sum_y = sum(p[1] for p in xy)
    sum_xx = sum(p[0] ** 2 for p in xy)
    sum_yy = sum(p[1] ** 2 for p in xy)
    sum_xy = sum(p[0] * p[1] for p in xy)
    sum_xxx = sum(p[0] ** 3 for p in xy)
    sum_yyy = sum(p[1] ** 3 for p in xy)
    sum_xyy = sum(p[0] * p[1] ** 2 for p in xy)
    sum_xxy = sum(p[0] ** 2 * p[1] for p in xy)

    A1 = sum_xx - sum_x * sum_x / n
    B1 = sum_xy - sum_x * sum_y / n
    C1 = sum_yy - sum_y * sum_y / n
    D1 = 0.5 * (sum_xyy - sum_x * sum_yy / n + sum_xxx - sum_x * sum_xx / n)
    E1 = 0.5 * (sum_xxy - sum_y * sum_xx / n + sum_yyy - sum_y * sum_yy / n)

    denom = A1 * C1 - B1 * B1
    if abs(denom) < 1e-12:
        return CircleFit(center=centroid, axis=normal, radius=0.0, max_residual=float("inf"))

    cx = (D1 * C1 - B1 * E1) / denom
    cy = (A1 * E1 - B1 * D1) / denom
    center_2d = (cx + sum_x / n, cy + sum_y / n)
    radius = (sum(((p[0] - cx) ** 2 + (p[1] - cy) ** 2) for p in xy) / n) ** 0.5

    center_3d = centroid + u_ax * center_2d[0] + v_ax * center_2d[1]
    max_residual = max(abs((p - center_3d).length - radius) for p in points)

    return CircleFit(center=center_3d, axis=normal, radius=radius, max_residual=max_residual)


def resolve_circle_pick(edge) -> PickResult:
    """
    Resolve a picked TopoDS_Edge into a PickResult (circle center +
    axis direction) for Align Axis. Ported from Basicad's
    _resolve_circle: use OCCT's own circle data directly when the
    edge's curve type is genuinely GeomAbs_Circle (fast, exact path),
    otherwise fall back to _fit_circle_to_edge() and only accept the
    fit if its residual is small relative to the fitted radius -- so a
    truly non-circular edge still gets correctly rejected rather than
    this fallback silently accepting anything vaguely curved.

    Raises ValueError if the edge does not appear to be circular, even
    approximately -- callers should catch this the same way
    _face_pick_callback already catches a wrong-shape-type pick.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle

    curve = BRepAdaptor_Curve(edge)
    if curve.GetType() == GeomAbs_Circle:
        circ = curve.Circle()
        center = Vec3.from_gp(circ.Location())
        axis = Vec3.from_gp(circ.Axis().Direction())
        return PickResult(point=center, direction=axis, label="circle axis")

    fit = _fit_circle_to_edge(edge)
    if fit.radius <= 0 or fit.max_residual > CIRCLE_FIT_RELATIVE_TOLERANCE * fit.radius:
        raise ValueError(
            f"Edge is not circular (fit residual={fit.max_residual:.6g}, "
            f"fitted radius={fit.radius:.6g}) -- pick a hole or circular edge.")
    return PickResult(point=fit.center, direction=fit.axis, label="circle axis (fitted)")


def line_plane_intersection(line_point: Vec3, line_dir: Vec3,
                            plane_point: Vec3, plane_normal: Vec3):
    """Where the line (line_point + t*line_dir) crosses the plane
    (points X such that (X - plane_point).dot(plane_normal) == 0).
    Returns the intersection Vec3, or None if the line is parallel to
    the plane (line_dir perpendicular to plane_normal, no
    intersection or infinitely many)."""
    denom = line_dir.dot(plane_normal)
    if abs(denom) < 1e-9:
        return None
    t = (plane_point - line_point).dot(plane_normal) / denom
    return line_point + line_dir * t


def resolve_cylinder_pick(face) -> PickResult:
    """
    Resolve a picked TopoDS_Face into a PickResult (a point on its
    axis + axis direction), for Align Axis's standalone "bolt in a
    hole" first step (aligning two cylindrical FACES directly, not
    circular edges -- see resolve_circle_pick for that, used by Align
    Axis's OTHER role, pinning holes after a face mate).

    Unlike circular edges (which sometimes get misclassified as
    BSPLINE, needing _fit_circle_to_edge's fallback), cylindrical
    SURFACES are reliably typed as GeomAbs_Cylinder in OCCT -- no
    fallback needed here, just a clear rejection if the picked face
    genuinely isn't cylindrical.

    Raises ValueError if the face is not a cylindrical surface.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    surf = BRepAdaptor_Surface(face)
    if surf.GetType() != GeomAbs_Cylinder:
        raise ValueError(
            f"Face is not a cylindrical surface (type={surf.GetType()}) -- "
            f"pick a cylindrical face (a hole's inner wall or a shaft's "
            f"outer surface).")
    cyl = surf.Cylinder()
    point_on_axis = Vec3.from_gp(cyl.Location())
    axis_dir = Vec3.from_gp(cyl.Axis().Direction())
    return PickResult(point=point_on_axis, direction=axis_dir, label="cylinder axis")


def _any_perpendicular(v: Vec3) -> Vec3:
    """Return an arbitrary unit vector perpendicular to v (assumed
    already unit length). Ported from Basicad's pose.py -- used as the
    "flip" rotation axis in compute_axis_step2_move and the 180-degree
    case in compute_align_axis_move: any direction perpendicular to
    the main cylinder axis works equally well for a 180-degree flip,
    since what's being (anti-)aligned is a direction along the axis,
    not any particular in-plane direction."""
    fallback = Vec3(0, 0, 1) if abs(v.dot(Vec3(0, 0, 1))) < 0.9 else Vec3(0, 1, 0)
    return (fallback - v * fallback.dot(v)).normalized()


def compute_align_axis_move(pick1: PickResult, pick2: PickResult):
    """
    Align Axis used as a STANDALONE Step 1 ("bolt in a hole" -- see
    Doug's design PDF's other Align Axis use, distinct from
    compute_align_axis_pin_move's chained-after-a-face-mate role):
    two cylindrical axes become fully coincident -- both direction (2
    rotational DOF) and position perpendicular to the axis (2
    translational DOF). Ported from Basicad's compute_align_axis_move,
    which built this via a general from-plane/to-plane transform
    (build123d Planes); reimplemented directly here as "rotate pick1's
    axis direction onto pick2's, then translate pick1's point onto
    pick2's" -- equivalent result, no build123d dependency needed.

    The rotation's spin (about the now-shared axis) is intentionally
    arbitrary -- whatever falls out of the axis-to-axis rotation is
    fine, because it gets completely superseded by the next two
    constraints (compute_axis_step2_move for axial position, then
    compute_step3_move's spin case for rotation) regardless of what it
    was. The 2 DOF this step does NOT constrain -- translation along
    the now-shared axis, and spin about it -- are left for those two
    steps.

    Returns a TopLoc_Location (world-space delta), or None if either
    pick lacks a direction (i.e. isn't actually a resolved
    cylindrical face).
    """
    from OCP.gp import gp_Ax1, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    if pick1.direction is None or pick2.direction is None:
        print("[position_math] Align Axis requires directed picks (cylindrical faces).")
        return None

    D1 = pick1.direction.normalized()
    D2 = pick2.direction.normalized()

    dot = max(-1.0, min(1.0, D1.dot(D2)))
    cross = D1.cross(D2)

    rot_trsf = gp_Trsf()
    if cross.length < 1e-9:
        if dot < 0:
            # Anti-parallel: 180-degree rotation about any axis
            # perpendicular to D1 -- the specific choice of axis
            # doesn't matter, since the resulting spin is arbitrary
            # and gets superseded by the next 2 constraints anyway.
            perp = _any_perpendicular(D1)
            ax = gp_Ax1(pick1.point.to_gp_pnt(), perp.to_gp_dir())
            rot_trsf.SetRotation(ax, math.pi)
        # else: already parallel -- no rotation needed.
    else:
        angle = math.acos(dot)
        ax = gp_Ax1(pick1.point.to_gp_pnt(), cross.normalized().to_gp_dir())
        rot_trsf.SetRotation(ax, angle)

    # Translate pick1's (now-rotated) point onto pick2's.
    rotated_pt = pick1.point.to_gp_pnt()
    rotated_pt.Transform(rot_trsf)
    rotated_pick1_pt = Vec3.from_gp(rotated_pt)

    delta = pick2.point - rotated_pick1_pt
    trans_trsf = gp_Trsf()
    if delta.length > 1e-9:
        trans_trsf.SetTranslation(gp_Vec(delta.X, delta.Y, delta.Z))

    return TopLoc_Location(trans_trsf).Multiplied(TopLoc_Location(rot_trsf))


def compute_axis_step2_move(pick1: PickResult, pick2: PickResult,
                            axis_point: Vec3, axis_dir: Vec3, mate: bool = True):
    """
    Align Axis (standalone path) -- Step 2: constrain the remaining
    translational DOF along the axis Step 1 established, by making a
    face on the moving part coplanar with a parallel face on the fixed
    part. Ported from Basicad's compute_axis_step2_move.

    mate=True: faces end up with OPPOSED normals (e.g. a shoulder
    seating flush against a mounting face). mate=False: faces end up
    with SAME-direction normals (e.g. a shaft end flush with a
    housing's outer face).

    Step 1 already fixed every rotational DOF except spin about the
    axis (Step 3's job) -- so we can't rotate to satisfy mate vs.
    align here the way compute_step1_move does. Instead: if the moving
    part's CURRENT face relationship doesn't already match the
    requested mate/align state, first flip the part 180 degrees about
    an axis PERPENDICULAR to the main axis (through axis_point) -- the
    standard CAD "mate alignment / anti-alignment flip" -- which
    reverses the face's effective direction along the axis without
    disturbing Step 1's axis coincidence (a 180-degree rotation about
    any line through axis_point perpendicular to axis_dir maps the
    axis line onto itself). Then translate along the axis to close the
    remaining gap.

    Returns a TopLoc_Location (world-space delta).
    """
    from OCP.gp import gp_Ax1, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    A = axis_dir.normalized()
    D1, D2 = pick1.direction, pick2.direction

    flip_trsf = gp_Trsf()
    needs_flip = False
    if D1 is not None and D2 is not None:
        currently_opposed = D1.dot(D2) < 0
        needs_flip = (mate and not currently_opposed) or ((not mate) and currently_opposed)
        if needs_flip:
            perp = _any_perpendicular(A)
            ax = gp_Ax1(axis_point.to_gp_pnt(), perp.to_gp_dir())
            flip_trsf.SetRotation(ax, math.pi)

    if needs_flip:
        moving_pt = pick1.point.to_gp_pnt()
        moving_pt.Transform(flip_trsf)
        moving_point = Vec3.from_gp(moving_pt)
    else:
        moving_point = pick1.point

    gap = (pick2.point - moving_point).dot(A)
    translation_vec = A * gap
    trans_trsf = gp_Trsf()
    if translation_vec.length > 1e-9:
        trans_trsf.SetTranslation(gp_Vec(translation_vec.X, translation_vec.Y,
                                         translation_vec.Z))

    return TopLoc_Location(trans_trsf).Multiplied(TopLoc_Location(flip_trsf))


def compute_align_axis_pin_move(hole1: PickResult, hole2: PickResult,
                                mated_normal: Vec3, plane_point: Vec3):
    """
    Align Axis, used as Step 2 within the 3-2-1 Mate/Align sequence
    (per Doug's original design -- see docs/PositionForKodacad2.pdf,
    the "2nd option": pin 2 points together rather than a full 4-DOF
    axis alignment).

    Each hole's own axis is intersected with the plane Step 1 already
    established (defined by plane_point + mated_normal) -- "those
    points are defined as the intersection of the cylindrical hole and
    the constrained (mated or aligned) face." The moving part is then
    translated WITHIN that plane so its hole's intersection point
    coincides with the fixed hole's -- consuming x and y of the 2D DOF
    remaining after Step 1, leaving only theta_z for a final Align
    (Step 3's "spin" case -- see compute_step3_move).

    Returns a TopLoc_Location (world-space in-plane translation), or
    None if either hole's axis is parallel to the mated plane (no
    well-defined intersection point).
    """
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    N = mated_normal.normalized()
    p1 = line_plane_intersection(hole1.point, hole1.direction.normalized(),
                                 plane_point, N)
    p2 = line_plane_intersection(hole2.point, hole2.direction.normalized(),
                                 plane_point, N)
    if p1 is None or p2 is None:
        print("[position_math] Align Axis: a hole's axis is parallel to "
              "the mated plane -- no well-defined intersection point.")
        return None

    delta = p2 - p1
    delta_in_plane = delta - N * delta.dot(N)  # already ~in-plane, but be safe

    t = gp_Trsf()
    if delta_in_plane.length > 1e-9:
        t.SetTranslation(gp_Vec(delta_in_plane.X, delta_in_plane.Y, delta_in_plane.Z))
    return TopLoc_Location(t)


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


def compute_step2_move(pick1: PickResult, pick2: PickResult,
                       mated_normal: Vec3, mate: bool = False):
    """
    Step 2 of the 3-2-1 workflow: rotate WITHIN the plane Step 1
    already established (about mated_normal itself, NOT a new
    intersection line), then translate within that plane to close the
    gap. Consumes 2 of the 3 DOF remaining after Step 1; leaves 1
    (translation along whatever line Step 3 will resolve).

    mate=True: the two picked faces' in-plane directions become
    opposed. mate=False (default): they become parallel -- "shove
    against a wall" semantics, matching Basicad's original design.
    Basicad hardcoded Align only for this step; generalized here the
    same way Step 1 already is, so applying Mate a second time doesn't
    require Reverse to fix a wrong guess (see docs/DEVELOPMENT_LOG.md,
    the hex-on-hex-shaft discussion that first flagged this).

    Returns a TopLoc_Location (world-space delta), or None if the
    picks aren't usable.
    """
    from OCP.gp import gp_Ax1, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    P1, D1 = pick1.point, pick1.direction
    P2, D2 = pick2.point, pick2.direction
    N = mated_normal.normalized()

    if D1 is None or D2 is None:
        print("[position_math] Step 2 requires directed picks (faces).")
        return None

    d1_proj = D1 - N * D1.dot(N)
    d2_proj = D2 - N * D2.dot(N)

    if d1_proj.length < 1e-6 or d2_proj.length < 1e-6:
        # Picked faces are perpendicular to the mated plane -- no
        # well-defined in-plane direction to align. Fall back to a
        # pure in-plane translation (matches Basicad's own fallback).
        delta = P2 - P1
        delta_in_plane = delta - N * delta.dot(N)
        t = gp_Trsf()
        t.SetTranslation(gp_Vec(delta_in_plane.X, delta_in_plane.Y, delta_in_plane.Z))
        return TopLoc_Location(t)

    d1_proj = d1_proj.normalized()
    d2_proj = d2_proj.normalized()
    target = -d2_proj if mate else d2_proj

    dot = max(-1.0, min(1.0, d1_proj.dot(target)))
    angle = math.acos(dot)
    cross = d1_proj.cross(target)
    sign = 1.0 if cross.dot(N) > 0 else -1.0

    rot_trsf = gp_Trsf()
    if abs(angle) > 1e-6:
        ax = gp_Ax1(P1.to_gp_pnt(), (N * sign).to_gp_dir())
        rot_trsf.SetRotation(ax, angle)
    rot_loc = TopLoc_Location(rot_trsf)

    # Translate along D2's in-plane direction to close the remaining gap.
    delta = P2 - P1
    delta_in_plane = delta - N * delta.dot(N)
    d2_in_plane = D2 - N * D2.dot(N)
    if d2_in_plane.length > 1e-6:
        d2_in_plane = d2_in_plane.normalized()
        delta_perp = d2_in_plane * delta_in_plane.dot(d2_in_plane)
    else:
        delta_perp = delta_in_plane

    trans_trsf = gp_Trsf()
    if delta_perp.length > 1e-6:
        trans_trsf.SetTranslation(gp_Vec(delta_perp.X, delta_perp.Y, delta_perp.Z))
    trans_loc = TopLoc_Location(trans_trsf)

    return trans_loc.Multiplied(rot_loc)


def compute_step3_move(pick1: PickResult, pick2: PickResult,
                       mated_normal: Vec3, wall_normal: Optional[Vec3] = None,
                       spin_pivot: Optional[Vec3] = None):
    """
    Step 3 of the 3-2-1 workflow: removes the LAST remaining DOF after
    Steps 1+2. Exactly one of wall_normal/spin_pivot should be given,
    matching which kind of Step 2 preceded this:

    wall_normal given ("wall" case -- Step 2 was a normal face-align):
    the only motion left is translation along the single line where
    the mated plane (Step 1) and the wall plane (Step 2) intersect:
        free_dir = mated_normal x wall_normal
    Projects the delta between the two picks onto free_dir and
    translates by that amount only.

    spin_pivot given ("axis"/spin case -- Step 2 was Align Axis's pin
    move): the only motion left is ROTATION about mated_normal,
    through spin_pivot (the point Align Axis's Step 2 pinned -- using
    either pick's own point instead would translate the part as a side
    effect of the rotation, undoing Step 2's constraint). Rotates until
    the two picked faces' in-plane directions are parallel, choosing
    whichever of the direct or flipped target gives the smaller angle
    (no mate/align choice here -- either resulting alignment is
    equally valid for pure spin, so the smaller rotation wins).

    Returns a TopLoc_Location (world-space delta), or None if the
    picks/inputs aren't usable.
    """
    from OCP.gp import gp_Ax1, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    N = mated_normal.normalized()

    if spin_pivot is not None:
        D1, D2 = pick1.direction, pick2.direction
        if D1 is None or D2 is None:
            print("[position_math] Step 3 (spin) requires directed picks (faces).")
            return None
        d1 = D1 - N * D1.dot(N)
        d2 = D2 - N * D2.dot(N)
        if d1.length < 1e-6 or d2.length < 1e-6:
            print("[position_math] Step 3 (spin): picked faces are "
                  "perpendicular to the mated plane.")
            return None
        d1 = d1.normalized()
        d2 = d2.normalized()

        dot_pos = max(-1.0, min(1.0, d1.dot(d2)))
        dot_neg = max(-1.0, min(1.0, d1.dot(-d2)))
        if abs(dot_pos) >= abs(dot_neg):
            target, dot = d2, dot_pos
        else:
            target, dot = -d2, dot_neg

        angle = math.acos(dot)
        cross = d1.cross(target)
        sign = 1.0 if cross.dot(N) > 0 else -1.0

        t = gp_Trsf()
        if abs(angle) > 1e-6:
            ax = gp_Ax1(spin_pivot.to_gp_pnt(), (N * sign).to_gp_dir())
            t.SetRotation(ax, angle)
        return TopLoc_Location(t)

    if wall_normal is None:
        print("[position_math] Step 3: need either wall_normal or spin_pivot.")
        return None

    P1, P2 = pick1.point, pick2.point
    W = wall_normal.normalized()

    free_dir = N.cross(W)
    if free_dir.length < 1e-6:
        print("[position_math] Step 3: mated_normal and wall_normal are "
              "parallel -- no well-defined free direction.")
        return None
    free_dir = free_dir.normalized()

    delta = P2 - P1
    translation = free_dir * delta.dot(free_dir)

    t = gp_Trsf()
    if translation.length > 1e-6:
        t.SetTranslation(gp_Vec(translation.X, translation.Y, translation.Z))
    return TopLoc_Location(t)
