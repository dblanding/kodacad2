"""trace_math.py -- plain-Python helpers for Animate Mechanism's Trace.

No OCP and no Qt in here, so it can be tested on its own.
Points are (x, y, z) tuples in mm, in the order the mechanism was driven.
"""
import math


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross_len(a, u):
    """|a x u| for a unit vector u: distance of vector a from the line
    through the origin along u."""
    cx = a[1] * u[2] - a[2] * u[1]
    cy = a[2] * u[0] - a[0] * u[2]
    cz = a[0] * u[1] - a[1] * u[0]
    return math.sqrt(cx * cx + cy * cy + cz * cz)


def longest_straight_section(points, tol):
    """The longest stretch of the path that stays within `tol` of the
    straight chord joining its two ends.

    Returns (i, j, length, max_deviation): points[i]..points[j] is the
    stretch. (0, 0, 0.0, 0.0) if the path has fewer than 2 points."""
    n = len(points)
    best = (0, 0, 0.0, 0.0)
    for i in range(n - 1):
        for j in range(i + 1, n):
            chord = _sub(points[j], points[i])
            length = math.sqrt(chord[0] ** 2 + chord[1] ** 2
                               + chord[2] ** 2)
            if length < 1e-12:
                continue
            u = (chord[0] / length, chord[1] / length, chord[2] / length)
            dev = 0.0
            for k in range(i + 1, j):
                dev = max(dev, _cross_len(_sub(points[k], points[i]), u))
                if dev > tol:
                    break
            if dev > tol:
                break                 # longer stretches from i only worse
            if length > best[2]:
                best = (i, j, length, dev)
    return best


def path_stats(points):
    """(x_min, x_max, y_min, y_max, z_min, z_max) of the path."""
    xs, ys, zs = zip(*points)
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
