"""array_math.py -- the arithmetic of the 3D arrays (Session 180).

Pure Python (no OCP / Qt), so it can be checked offline. Distances are
in internal units (mm); angles in degrees.

Number = the TOTAL number of items INCLUDING the original (Doug): 6
angular items 60 degrees apart = Number 6, Angle 60. The original is
item 0 and stays where it is, so only items 1 .. n-1 are created.
"""
import math


def _unit(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if n < 1e-12:
        raise ValueError("The direction has no length.")
    return (v[0] / n, v[1] / n, v[2] / n)


def linear_offsets(n, distance, direction):
    """World-space offsets (x, y, z) of the new items k = 1 .. n-1 of a
    linear array: k * distance along `direction` (any length; it is
    normalized). A negative distance runs the other way."""
    if n < 2:
        raise ValueError("An array needs Number >= 2 (the original "
                         "counts as one).")
    d = _unit(direction)
    return [(k * distance * d[0], k * distance * d[1], k * distance * d[2])
            for k in range(1, n)]
