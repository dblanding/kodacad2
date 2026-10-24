"""scott_russell.py -- the pin-jointed four-bar in scott-russell.stp,
for Utility -> Animate Mechanism...

Parts (as named in the tree): base_1 (fixed), A-link_1 (the driven
crank), B-link_1 (the rocker) and C-link_1 (the coupler). The input is
the A-link's angle, counter-clockwise about +Z, 0 = as modelled. The
far hole of the C-link traces a nearly straight path.

Nothing is typed in by hand: the pin positions are read from the pin
holes (cylindrical faces of radius PIN_R) of the parts as they are
modelled, so the file works wherever the assembly is placed, as long
as the model is in the pose it was built in:
    base_1   two holes: the lower-x one is B's ground pivot, the other
             is A's ground pivot
    C-link_1 three holes in order of x: B joint, A joint, tracing hole

KodaCAD reads these names (see geneva4.py for the simple, fixed-shaft
form):

    NAME, START, PARTS, setup(ctx)
    RANGE      (low, high) slider range in degrees. The A-link cannot
               go below about -45: there the B-link and the coupler
               line up (a dead point) and the linkage is stretched out.
    LOOP       "pingpong": Play runs back and forth between the ends
    poses(theta)   {role: (angle_deg, (tx, ty, tz))}: rotate the role's
               parts about its axis point by angle, then translate
    TRACE      {label: (role, (x, y, z))}: points whose path Trace draws
"""
import math

NAME = "Four-bar linkage (scott-russell.stp)"
START = 0.0
RANGE = (-44.9, 100.0)
LOOP = "pingpong"
TRACE_STEP = 0.5                  # degrees between traced points
PIN_R = 1.5875                    # radius of the pin holes (1/16 in), mm

PARTS = {
    "A-link_1": "Alink",
    "B-link_1": "Blink",
    "C-link_1": "coupler",
}
TRACE = {}

_OB = _OA = _P1 = _P2 = None
_a = _b = _cd = 0.0
_side = 1.0


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def setup(ctx):
    global _OB, _OA, _P1, _P2, _a, _b, _cd, _side
    base = sorted(ctx.holes("base_1", PIN_R), key=lambda p: p[0])
    coup = sorted(ctx.holes("C-link_1", PIN_R), key=lambda p: p[0])
    if len(base) != 2 or len(coup) != 3:
        raise ValueError(f"expected 2 pin holes in base_1 and 3 in "
                         f"C-link_1, found {len(base)} and {len(coup)}")
    _OB, _OA = base[0], base[1]
    _P1, _P2, tip = coup
    _a = math.dist(_OA[:2], _P2[:2])
    _b = math.dist(_OB[:2], _P1[:2])
    _cd = math.dist(_P1[:2], _P2[:2])
    # which of the two circle intersections the model is in
    _side = math.copysign(1.0, _cross(_P1[0] - _OB[0], _P1[1] - _OB[1],
                                      _P2[0] - _P1[0], _P2[1] - _P1[1]))
    TRACE.clear()
    TRACE["C-link far hole"] = ("coupler", tuple(tip))
    up = (0.0, 0.0, 1.0)
    return {"Alink": (_OA, up), "Blink": (_OB, up), "coupler": (_P1, up)}


def _solve_p1(p2):
    """B-link end P1: |P1-OB| = b and |P1-P2| = coupler length, on the
    same side as in the model."""
    dx, dy = p2[0] - _OB[0], p2[1] - _OB[1]
    d = math.hypot(dx, dy)
    if d > _b + _cd or d < abs(_b - _cd):
        raise ValueError("linkage cannot reach this angle")
    x = (_b * _b - _cd * _cd + d * d) / (2.0 * d)
    h = math.sqrt(max(_b * _b - x * x, 0.0))
    ux, uy = dx / d, dy / d
    for s in (1.0, -1.0):
        px = _OB[0] + x * ux - s * h * uy
        py = _OB[1] + x * uy + s * h * ux
        if math.copysign(1.0, _cross(px - _OB[0], py - _OB[1],
                                     p2[0] - px, p2[1] - py)) == _side:
            return (px, py)
    return (px, py)


def poses(theta):
    al = math.radians(theta)
    base = math.atan2(_P2[1] - _OA[1], _P2[0] - _OA[0])
    p2 = (_OA[0] + _a * math.cos(base + al),
          _OA[1] + _a * math.sin(base + al))
    p1 = _solve_p1(p2)
    beta = (math.atan2(p1[1] - _OB[1], p1[0] - _OB[0])
            - math.atan2(_P1[1] - _OB[1], _P1[0] - _OB[0]))
    gamma = (math.atan2(p2[1] - p1[1], p2[0] - p1[0])
             - math.atan2(_P2[1] - _P1[1], _P2[0] - _P1[0]))
    return {
        "Alink": (theta, (0.0, 0.0, 0.0)),
        "Blink": (math.degrees(beta), (0.0, 0.0, 0.0)),
        "coupler": (math.degrees(gamma),
                    (p1[0] - _P1[0], p1[1] - _P1[1], 0.0)),
    }
