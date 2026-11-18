"""frame_chooser.py -- the shared "Frame" row: World | Workplane | Pick.

Session 180. Extracted from position_dialog.py (where it began in
Session 179, stages A, B and D1) so the array dialogs can reuse it: any
dialog that needs an AXIS SOURCE -- the Position gizmo's frame, the
direction of a linear array, the axis of an angular one.

A frame is the tuple (origin_xyz, w_xyz, u_xyz), or None for World:

  World      -- None: origin (0, 0, 0), axes X / Y / Z
  Workplane  -- the ACTIVE workplane's origin and U / V / W (a snapshot,
                taken when the radio is clicked)
  Pick       -- a picked cylindrical face, circular or straight edge or
                flat face (position_math.resolve_frame_pick): origin on
                the axis, W along it, U any perpendicular (a snapshot)

The chooser owns the three radios and the state; the dialog supplies
hooks, because what a frame DOES differs (Position moves its gizmo onto
it, an array only reads its axes):

  on_changed()       the frame (or its name) just changed; called after
                     every click on the row and after a pick
  on_pick_started()  a face/edge pick is about to begin (Position
                     detaches the gizmo: its arrows and rings win the
                     hover and click over the geometry behind them)
  guard()            return False (after saying why) to refuse a click

Radios use `clicked`, not `toggled`: re-clicking the checked radio must
re-read the CURRENT active workplane / start a new pick.
"""

import math

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QRadioButton

import dialog_style
import position_math


def _sub_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / n, v[1] / n, v[2] / n)


def frame_triad(frame):
    """(origin, u, v, w), each an (x, y, z) tuple, for a frame tuple;
    World (None) gives origin 0 and the X / Y / Z axes. V = W x U, so
    U x V = W (right-handed, as in gp_Ax3)."""
    if frame is None:
        return ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    origin, w, u = frame
    w = _unit(w)
    u = _unit(u)
    v = _unit(_sub_cross(w, u))
    return (tuple(origin), u, v, w)


class FrameChooser(QObject):
    DEFAULT_PICK_HINT = ("Pick a cylindrical face, a circular or straight "
                         "edge, or a flat face -- its axis is used.")

    def __init__(self, main_win, parent=None, on_changed=None,
                 on_pick_started=None, guard=None, label="Frame",
                 pick_hint=None):
        super().__init__(parent)
        self.main_win = main_win
        self._on_changed = on_changed
        self._on_pick_started = on_pick_started
        self._guard = guard
        self._label = label
        self._pick_hint = pick_hint or self.DEFAULT_PICK_HINT

        self.frame = None          # (origin, w, u) xyz tuples, or None
        self.name = ""             # what the frame was taken from
        self.picking = False       # waiting for a face / edge pick

        self.world_rb = QRadioButton("World")
        self.wp_rb = QRadioButton("Workplane")
        self.pick_rb = QRadioButton("Pick")
        self.world_rb.setChecked(True)
        self._group = QButtonGroup(self)
        for rb in (self.world_rb, self.wp_rb, self.pick_rb):
            self._group.addButton(rb)
            rb.clicked.connect(self._on_clicked)
        self.world_rb.setToolTip("The world axes X / Y / Z.")
        self.wp_rb.setToolTip(
            "The active workplane's origin and its own U / V / W axes "
            "(a snapshot taken now).\n"
            "Click it again to pick up a different active workplane.")
        self.pick_rb.setToolTip(
            "Click a cylindrical face, a circular or straight edge, or "
            "a flat face: its axis becomes W (a flat face uses its "
            "normal).\n"
            "Click it again to pick a different one. The frame is a "
            "snapshot: it does not follow a part that moves.")

    # -- layout / state ------------------------------------------------
    def row_layout(self):
        row = QHBoxLayout()
        row.addWidget(dialog_style.row_label(self._label))
        row.addWidget(self.world_rb)
        row.addWidget(self.wp_rb)
        row.addWidget(self.pick_rb)
        row.addStretch(1)
        return row

    def triad(self):
        """(origin, u, v, w) of the current frame (see frame_triad)."""
        return frame_triad(self.frame)

    def restart(self):
        """Re-apply the row's CHOICE (the dialog (re)started its
        work): World = default; Workplane = a fresh snapshot of the
        CURRENT active workplane (falls back to World if there is
        none); Pick = the earlier pick is kept (it is a snapshot), or
        World if nothing was picked yet. No hook is called."""
        self.picking = False
        prev = self.frame
        self.frame = None
        if self.wp_rb.isChecked():
            self.frame = self._read_active_wp_frame()
            if self.frame is None:
                self.world_rb.setChecked(True)
        elif self.pick_rb.isChecked():
            self.frame = prev
            if self.frame is None:
                self.world_rb.setChecked(True)

    # -- the row's clicks ----------------------------------------------
    def _changed(self):
        if self._on_changed is not None:
            self._on_changed()

    def _on_clicked(self, _checked=False):
        # (while a pick is pending the dialog may have detached things
        # on purpose, so the guard only applies when no pick is pending)
        if (self._guard is not None and not self.picking
                and not self._guard()):
            return
        if self.pick_rb.isChecked():
            self._start_picking()
            return
        if self.picking:
            # World / Workplane chosen while a pick was pending: cancel it
            self.picking = False
            self.main_win.clearCallback()
        if self.wp_rb.isChecked():
            fr = self._read_active_wp_frame()
            if fr is None:
                self.world_rb.setChecked(True)
                self.frame = None
                self.name = ""
            else:
                self.frame = fr                 # snapshot
        else:
            self.frame = None
            self.name = ""
        self._changed()

    def _read_active_wp_frame(self):
        """(origin_xyz, w_xyz, u_xyz) of the active workplane, or None
        (with a status-bar message) if there is none / it can't be
        read. Sets self.name."""
        wp = self.main_win.activeWp
        if wp is None:
            self.main_win.statusBar().showMessage(
                "No active workplane -- select or create one first.",
                5000)
            return None
        try:
            uid = getattr(self.main_win, "activeWpUID", 0)
            self.name = (self.main_win._wp_display_name(uid)
                         if uid else "")
        except Exception:
            self.name = ""
        try:
            ax3 = wp.gpPlane.Position()
            loc = ax3.Location()
            w_dir = ax3.Direction()
            u_dir = ax3.XDirection()
            return ((loc.X(), loc.Y(), loc.Z()),
                    (w_dir.X(), w_dir.Y(), w_dir.Z()),
                    (u_dir.X(), u_dir.Y(), u_dir.Z()))
        except Exception as e:
            self.main_win.statusBar().showMessage(
                f"Could not read the workplane's frame ({e}).", 5000)
            return None

    # -- Pick ------------------------------------------------------------
    def _start_picking(self):
        self.picking = True
        if self._on_pick_started is not None:
            self._on_pick_started()
        # Doug: picks often needed 2+ tries. The previous pick stays
        # selected, and clicking a selected entity toggles it OFF, so
        # the selection is cleared when picking starts and after a pick
        # (the dialog's hook also gets the gizmo out of the way).
        try:
            self.main_win.canvas._display.Context.ClearSelected(True)
        except Exception:
            pass
        self.main_win.registerCallback(self._pick_callback)
        self.main_win.canvas._display.SetSelectionModeFaceOrEdge()
        self.main_win.statusBar().showMessage(self._pick_hint)

    def _pick_callback(self, shapeList, *args):
        for shape in shapeList:
            try:
                fr = position_math.resolve_frame_pick(shape)
            except Exception as e:
                print(f"[FrameChooser] pick gives no frame: {e}")
                self.main_win.statusBar().showMessage(
                    "That gives no axis -- pick a cylindrical face, a "
                    "circular or straight edge, or a flat face.", 4000)
                continue
            self.frame = ((fr.origin.X, fr.origin.Y, fr.origin.Z),
                          (fr.w.X, fr.w.Y, fr.w.Z),
                          (fr.u.X, fr.u.Y, fr.u.Z))
            self.name = fr.label
            self.picking = False
            self.main_win.clearCallback()   # also back to neutral picking
            try:
                self.main_win.canvas._display.Context.ClearSelected(True)
            except Exception:
                pass
            self._changed()
            return
