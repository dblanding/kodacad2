"""crane_lift.py -- the S-20 derrick moving segment 65, for
Utility -> Animate Mechanism...

ONE slider runs four moves in a row (PHASES below), starting from the pose
as modelled (segment 65 in place, ready to join segment 64):

    LIFT    0 - 100   the load (everything in Rigging-lower_1: hook block,
                      hook, the copied load lines, the lifting frame and
                      segment 65) rises LIFT mm straight up. The copied
                      lower load lines end up on top of the upper set.
    SWING 100 - 300   the whole rotor (rotor-asy_1, load included) turns
                      SWING_DEG degrees about the mast axis, slowly.
    SPIN  300 - 350   only what hangs BELOW the hook block -- the Hook,
                      the lifting frame, its four cables and segment 65 --
                      turns SPIN_DEG degrees about the hook axis (so the
                      load lines do not wind up).
    LOWER 350 - 450   the load comes down LOWER mm (half the lift).

Run it backwards and it is the erection. Display only, like every
mechanism: nothing in the model changes.

WHAT YOU MAY HAVE TO ADJUST (mm / degrees):
    SWING_DEG   + is counter-clockwise seen from above (+Z). The rotor
                starts 55 deg CW of nominal and ends 45 deg CCW: 100.
    SPIN_DEG    - is clockwise; -15 matches the truck.
    LIFT        None = measured: the height of the copied lower load lines
                (Rigging-lower_1/rope-pair_1). Type a number to override.
    LOWER       None = LOWER_FRACTION of the lift (the truck is higher
                than where the segment started).
    MAST_XY     None = centre of wheel-asy_1 (the round rotor base). Type
                (x, y) in mm if the console line '[crane_lift] mast axis'
                shows it is off.
    PHASES      (name, start, end) slider ranges; RANGE must cover them.
    PARTS       'rotor-asy_1' moves everything beneath it; deeper keys
                override it: 'Rigging-lower_1' (the load), then 'Hook'
                and 'load-asy_1' (what spins).

setup() prints what it measured to the console.
"""
import math

NAME = "Erection of segment 65"
START = 0.0
RANGE = (0.0, 450.0)
LOOP = "pingpong"

PHASES = (("Lift", 0.0, 100.0), ("Swing", 100.0, 300.0),
          ("Spin", 300.0, 350.0), ("Lower", 350.0, 450.0))

SWING_DEG = 100.0
SPIN_DEG = -15.0
LIFT = None
LOWER = None
LOWER_FRACTION = 0.5
MAST_XY = None

PARTS = {
    "rotor-asy_1": "rotor",
    "Rigging-lower_1": "load",
    "Hook": "spun",
    "load-asy_1": "spun",
}

_G = {}          # measured values, filled by setup()


def smooth(t):
    """0..1 with gentle starts and stops (3t^2 - 2t^3)."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def progress(theta):
    """(lift, swing, spin, lower), each 0..1, for slider value theta."""
    return tuple(smooth((theta - a) / (b - a)) for _n, a, b in PHASES)


def rot2(deg, x, y):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (c * x - s * y, s * x + c * y)


def load_pose(theta, mast, hook, lift, lower, spins=True):
    """(angle_deg, (tx, ty, tz)) for the load (spins=False: for the part
    of it that does not spin), as 'rotate about the mast axis, then
    translate'. Derivation: the true motion is lift (z),
    swing about the mast M, spin about the hook axis AFTER the swing
    (H' = M + R(sw)(H - M)), lower (z). With h = H - M:
        p'' = M + R(sw + sp)(p - M) + [R(sw) h - R(sw + sp) h]."""
    lp, sp_, np_, dp = progress(theta)
    sw = SWING_DEG * sp_
    sn = SPIN_DEG * np_ if spins else 0.0
    hx, hy = hook[0] - mast[0], hook[1] - mast[1]
    ax, ay = rot2(sw, hx, hy)
    bx, by = rot2(sw + sn, hx, hy)
    return (sw + sn, (ax - bx, ay - by, lift * lp - lower * dp))


def setup(ctx):
    global _G
    if MAST_XY is not None:
        mast = (float(MAST_XY[0]), float(MAST_XY[1]))
    else:
        c = ctx.center("wheel-asy_1")
        mast = (c[0], c[1])
    hc = ctx.center("Hook")
    hook = (hc[0], hc[1])
    if LIFT is not None:
        lift = float(LIFT)
    else:
        b = ctx.bbox("Rigging-lower_1/rope-pair_1")
        lift = b[5] - b[2]
    lower = lift * LOWER_FRACTION if LOWER is None else float(LOWER)
    _G = {"mast": mast, "hook": hook, "lift": lift, "lower": lower}
    print(f"[crane_lift] mast axis ({mast[0]:.1f}, {mast[1]:.1f}) mm; "
          f"hook axis ({hook[0]:.1f}, {hook[1]:.1f}) mm; lift "
          f"{lift:.1f} mm, lower {lower:.1f} mm")
    axis = ((mast[0], mast[1], 0.0), (0.0, 0.0, 1.0))
    return {"rotor": axis, "load": axis, "spun": axis}


def poses(theta):
    lp, sp_, np_, dp = progress(theta)
    g = _G
    return {
        "rotor": (SWING_DEG * sp_, (0.0, 0.0, 0.0)),
        "load": load_pose(theta, g["mast"], g["hook"], g["lift"],
                          g["lower"], spins=False),
        "spun": load_pose(theta, g["mast"], g["hook"], g["lift"],
                          g["lower"]),
    }


def describe(theta):
    lp, sp_, np_, dp = progress(theta)
    vals = (lp, sp_, np_, dp)
    k = 0
    for n, (_name, a, b) in enumerate(PHASES):
        if theta >= a:
            k = n
    return (f"{theta:.0f} / {RANGE[1]:.0f}   {PHASES[k][0]} "
            f"{vals[k] * 100:.0f}%   (lifted {lp * 100:.0f}%, swung "
            f"{sp_ * SWING_DEG:+.1f} deg, spun {np_ * SPIN_DEG:+.1f} "
            f"deg, lowered {dp * 100:.0f}%)")
