"""geneva4.py -- a 4-slot Geneva drive, for Utility -> Animate Mechanism...

This file is plain Python that YOU edit. KodaCAD reads these names:

    NAME      title shown in the dialog
    START     slider angle (degrees) at which the parts sit exactly as
              modelled. Slider values are the pin-wheel (crank) angle
              THETA, measured from the line of centres: THETA = 0 when
              the pin is on the line between the two shafts, pointing
              at the geneva wheel.
    PARTS     {part name as shown in the tree: role}. Every part with a
              role is rotated about that role's shaft.
    setup(ctx)  called once when the file is loaded; returns
              {role: (point, direction)} -- each shaft's axis in world
              coordinates (mm). ctx.center(name) gives the centre of a
              part's bounding box, which is the shaft position for a
              symmetric part such as the geneva wheel or the disc.
    angles(theta)  returns {role: degrees}, the rotation of each role
              relative to the modelled pose, for crank angle theta.

If the parts turn the wrong way, flip CRANK_DIR / WHEEL_DIR. If the
modelled pose does not match the slider, change START (the crank angle
of the model as drawn; -45 means the pin is just entering a slot).
"""
import math

NAME = "Geneva drive (4 slots)"
N = 4                       # number of slots
START = 315.0               # == -45: pin just entering a slot (CHECK THIS)
CRANK_DIR = +1              # +1 = counter-clockwise about the axis
WHEEL_DIR = -1              # an external Geneva turns opposite to its driver

PARTS = {
    "driver_1": "crank",
    "pin_1": "crank",
    "geneva-wheel_1": "wheel",
}

_A = 1.0                    # crank radius (set by setup)
_C = 1.0                    # shaft distance (set by setup)


def setup(ctx):
    global _A, _C
    cx, cy, cz = ctx.center("driver_1")
    wx, wy, wz = ctx.center("geneva-wheel_1")
    _C = math.dist((cx, cy), (wx, wy))
    _A = _C * math.sin(math.pi / N)       # right triangle at engagement
    up = (0.0, 0.0, 1.0)
    return {"crank": ((cx, cy, cz), up), "wheel": ((wx, wy, wz), up)}


def wheel_angle(theta):
    """Absolute geneva-wheel angle (degrees) for crank angle theta.

    While the pin is in a slot (|t| <= 90 - 180/N) the wheel turns by
    atan2(a sin t, C - a cos t); in between it is held at +-180/N.
    Each crank revolution advances the wheel by 360/N."""
    half = 180.0 / N
    window = 90.0 - half
    n = math.floor((theta + 180.0) / 360.0)
    t = theta - 360.0 * n                  # -180 <= t < 180
    if abs(t) <= window:
        r = math.radians(t)
        phi = math.degrees(math.atan2(_A * math.sin(r),
                                      _C - _A * math.cos(r)))
    else:
        phi = math.copysign(half, t)
    return (360.0 / N) * n + phi


def angles(theta):
    return {
        "crank": CRANK_DIR * (theta - START),
        "wheel": WHEEL_DIR * (wheel_angle(theta) - wheel_angle(START)),
    }
