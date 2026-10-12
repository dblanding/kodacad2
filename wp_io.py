#!/usr/bin/env python
#
# Copyright 2026 Doug Blanding (dblanding@gmail.com)
#
# This file is part of kodacad2.
# Licensed under the GNU General Public License v3 -- see LICENSE.
#
"""wp_io.py -- saving and loading workplanes, and the .kcad container.

A KodaCAD session file (.kcad) is an ordinary ZIP archive (like NumPy's
.npz) holding two members:

    <name>.stp        the 3D model, exactly what "Export STEP" writes
    workplanes.json   the workplanes, as plain data

Anyone can unzip a .kcad and use the STEP file on its own.

workplanes.json holds ONLY plain data (numbers, strings, lists) -- never
OCP objects and never pickles (loading a pickle runs code). Per
workplane: its placement (origin, U direction, W direction), size, auto-
fit floor (min_bounds), the construction geometry (clines / ccircs /
carcs / csegs, all already plane-relative (u,v) numbers) and the
profile geometry as a list of "prims" (see WorkPlane.add_prim -- what
the user entered, with the TopoDS edges DERIVED from it on load). Also
the workplane-set grouping, uid counters, active workplane and which
workplanes are hidden.

Not saved: a workplane's `face` reference (a workplane made on a face
keeps its placement but not the link), anything keyed by PART uids
(those are reassigned every time a STEP file is read), undo history and
display-only face colors.

Format versioning: "format" is an integer. A file with a HIGHER number
than this code knows is refused with a clear message instead of being
misread. An unknown profile prim type raises (WorkPlane._edge_from_prim).
"""

import json
import os
import zipfile

FORMAT = 1
JSON_NAME = "workplanes.json"


class KcadError(Exception):
    """A .kcad file that cannot be read (message is user-presentable)."""


# ----------------------------------------------------------------------
# One workplane <-> plain dict
# ----------------------------------------------------------------------

def _xyz(obj):
    return [float(obj.X()), float(obj.Y()), float(obj.Z())]


def wp_to_dict(wp):
    """Plain-data description of one WorkPlane (JSON-ready)."""
    return {
        "origin": _xyz(wp.origin),
        "u_dir": _xyz(wp.uDir),
        "w_dir": _xyz(wp.wDir),
        "size": float(wp.size),
        "min_bounds": [float(x) for x in wp.min_bounds],
        # sorted so identical workplanes always write identical files
        "clines": sorted([float(a), float(b), float(c)]
                         for (a, b, c) in wp.clines),
        "ccircs": sorted([[float(pc[0]), float(pc[1])], float(r)]
                         for (pc, r) in wp.ccircs),
        "carcs": [[[float(pc[0]), float(pc[1])], float(r),
                   float(a0), float(a1)]
                  for (pc, r, a0, a1) in wp.carcs],
        "csegs": [[[float(p1[0]), float(p1[1])],
                   [float(p2[0]), float(p2[1])]]
                  for (p1, p2) in wp.csegs],
        "profile": wp.profile_prims(),
    }


def wp_from_dict(d):
    """Build a WorkPlane from wp_to_dict() output."""
    from OCP.gp import gp_Ax3, gp_Pnt, gp_Dir
    import workplane
    o, u, w = d["origin"], d["u_dir"], d["w_dir"]
    ax3 = gp_Ax3(gp_Pnt(o[0], o[1], o[2]),
                 gp_Dir(w[0], w[1], w[2]),
                 gp_Dir(u[0], u[1], u[2]))
    wp = workplane.WorkPlane(d["size"], ax3=ax3)
    wp.min_bounds = tuple(d["min_bounds"])
    # JSON turns tuples into lists; these sets/lists need TUPLES back
    # (hashable, and compared by equality throughout the sketch code).
    wp.clines = {(a, b, c) for (a, b, c) in d["clines"]}
    wp.ccircs = {((pc[0], pc[1]), r) for (pc, r) in d["ccircs"]}
    wp.carcs = [((pc[0], pc[1]), r, a0, a1)
                for (pc, r, a0, a1) in d["carcs"]]
    wp.csegs = [((p1[0], p1[1]), (p2[0], p2[1]))
                for (p1, p2) in d["csegs"]]
    for prim in d["profile"]:
        wp.add_prim(prim)
    try:
        wp.update_border()
    except Exception as e:
        print(f"[wp_io] update_border failed: {e}")
    return wp


# ----------------------------------------------------------------------
# All workplanes of a MainWindow <-> plain dict
# ----------------------------------------------------------------------

def collect_wp_state(win):
    """Everything about the session's workplanes, as plain data."""
    return {
        "workplanes": [dict(uid=uid, **wp_to_dict(wp))
                       for uid, wp in win.wp_dict.items()],
        "sets": {s: list(m) for s, m in win.wp_set_dict.items()},
        "wp_counter": int(win._wpNmbr),
        "set_counter": int(win._wpSetNmbr),
        "active_wp": win.activeWpUID or None,
        "hidden_wps": [u for u in win.hide_list if u in win.wp_dict],
    }


def restore_wp_state(win, state):
    """Replace the session's workplanes with those in `state`.

    Updates the data structures only. The caller then calls
    win.build_tree() (which creates the tree items from them), then
    activate_saved_wp(), then win.redraw().
    """
    # Build everything first so a bad file leaves the session untouched.
    new_wps = {}
    for entry in state["workplanes"]:
        new_wps[entry["uid"]] = wp_from_dict(entry)

    for uid in list(win.wp_dict):
        win._erase_wp(uid)
    win._wp_ais_reg = {}
    win.activeWp = None
    win.activeWpUID = 0
    # A new document: every old part/workplane uid in hide_list is stale.
    win.hide_list = []

    win.wp_dict = new_wps
    win.wp_set_dict = {s: list(m) for s, m in state["sets"].items()}
    win.wp_parent_set = {uid: s for s, members in win.wp_set_dict.items()
                         for uid in members}
    win._wpNmbr = int(state["wp_counter"])
    win._wpSetNmbr = int(state["set_counter"])
    win.hide_list.extend(u for u in state["hidden_wps"] if u in new_wps)


def activate_saved_wp(win, state):
    """After build_tree(): make the saved active workplane active."""
    uid = state.get("active_wp")
    if uid and uid in win.wp_dict:
        win.setActiveWp(uid)


# ----------------------------------------------------------------------
# The .kcad container
# ----------------------------------------------------------------------

def write_kcad(path, stp_path, state):
    """Write `path` (.kcad) holding the STEP file at stp_path plus the
    workplane `state`. Written to a temporary name and renamed, so a
    failure can never leave a half-written file in place of a good one."""
    stp_name = os.path.basename(stp_path)
    doc = {"format": FORMAT, "step_file": stp_name}
    doc.update(state)
    tmp = path + ".tmp"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(stp_path, arcname=stp_name)
            z.writestr(JSON_NAME, json.dumps(doc, indent=1))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_kcad(path, dest_dir):
    """Extract the STEP file of a .kcad into dest_dir and return
    (stp_path, state). Raises KcadError with a user-presentable message
    for anything unreadable. Members are read by name and written under
    their base name only (never trust paths inside an archive)."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if JSON_NAME not in names:
                raise KcadError(f"Not a KodaCAD session file: no "
                                f"{JSON_NAME} inside.")
            doc = json.loads(z.read(JSON_NAME).decode("utf-8"))
            fmt = doc.get("format")
            if not isinstance(fmt, int) or fmt < 1:
                raise KcadError("Unreadable session file (bad format "
                                "number).")
            if fmt > FORMAT:
                raise KcadError(
                    f"This session file is format {fmt}; this KodaCAD "
                    f"reads up to format {FORMAT}. Update KodaCAD to "
                    f"open it.")
            stp_name = os.path.basename(doc.get("step_file", ""))
            if not stp_name or stp_name not in names:
                stps = [n for n in names
                        if n.lower().endswith((".stp", ".step"))]
                if len(stps) != 1:
                    raise KcadError("Session file has no (or more than "
                                    "one) STEP model inside.")
                stp_name = os.path.basename(stps[0])
                member = stps[0]
            else:
                member = stp_name
            stp_path = os.path.join(dest_dir, stp_name)
            with open(stp_path, "wb") as fh:
                fh.write(z.read(member))
    except zipfile.BadZipFile:
        raise KcadError("Not a valid session file (not a zip archive).")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise KcadError(f"Session file's {JSON_NAME} is damaged.")
    return stp_path, doc
