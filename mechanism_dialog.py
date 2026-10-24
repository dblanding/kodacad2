#!/usr/bin/env python
#
# Copyright 2026 Doug Blanding (dblanding@gmail.com)
#
# This file is part of kodacad2.
# Licensed under the GNU General Public License v3 -- see LICENSE.
#
"""mechanism_dialog.py -- Utility -> Animate Mechanism... (Session 171).

A QSlider drives an editable Python "mechanism file" (see
mechanisms/geneva4.py) that says how far each moving part has turned.
Nothing in the document changes: each moving part's on-screen
AIS_Shape is rotated with AIS_InteractiveContext.SetLocation (a
gp_Trsf rotation about the shaft's gp_Ax1), which is display-only,
fast, and leaves the XDE document and the undo history alone. Closing
the dialog puts every part back where it was.

(Why not Position's set_component_location? It removes and re-adds the
component, hands out a new uid, reparses the document and rebuilds the
tree -- far too heavy to run on every slider tick.)

The mechanism file is Python that the USER picks and edits, so it is
loaded with importlib and run in-process. It is deliberately NOT part
of a .kcad session: a session file never executes anything on load.
"""
import importlib.util
import math
import os

from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QFileDialog,
                               QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout)

import trace_math
from mainwindow import dm

DEFAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "mechanisms", "geneva4.py")


class _Ctx:
    """What a mechanism file may ask of the model."""

    def __init__(self, dlg):
        self._dlg = dlg

    def center(self, part_name):
        """Centre (x, y, z) in mm of the bounding box of the displayed
        part called part_name."""
        uids = self._dlg._uids_named(part_name)
        if not uids:
            raise KeyError(f"no part named '{part_name}'")
        ais = self._dlg.win.ais_shape_dict.get(uids[0])
        if ais is None:
            raise KeyError(f"part '{part_name}' is not displayed")
        box = Bnd_Box()
        BRepBndLib.Add_s(ais.Shape(), box)
        lo, hi = box.CornerMin(), box.CornerMax()
        return ((lo.X() + hi.X()) / 2.0, (lo.Y() + hi.Y()) / 2.0,
                (lo.Z() + hi.Z()) / 2.0)


    def holes(self, part_name, radius=None, tol=1.0e-3):
        """Axis points (x, y, z) of the cylindrical faces of the
        displayed part called part_name -- hole centres, and rounded
        ends too, unless `radius` selects one size. Duplicates (a wall
        split into two faces) are merged."""
        uids = self._dlg._uids_named(part_name)
        if not uids:
            raise KeyError(f"no part named '{part_name}'")
        ais = self._dlg.win.ais_shape_dict.get(uids[0])
        if ais is None:
            raise KeyError(f"part '{part_name}' is not displayed")
        out = []
        ex = TopExp_Explorer(ais.Shape(), TopAbs_FACE)
        while ex.More():
            surf = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current()))
            if surf.GetType() == GeomAbs_Cylinder:
                cyl = surf.Cylinder()
                if radius is None or abs(cyl.Radius() - radius) < tol:
                    loc = cyl.Axis().Location()
                    pt = (loc.X(), loc.Y(), loc.Z())
                    if not any(math.dist(pt[:2], q[:2]) < 1.0e-3
                               for q in out):
                        out.append(pt)
            ex.Next()
        return out


class MechanismDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.win = main_win
        self.setWindowTitle("Animate Mechanism")
        self.setModal(False)
        self._mod = None
        self._path = DEFAULT_FILE
        self._axes = {}
        self._moved = set()           # uids currently displaced
        self._playing = False
        self._dir = 1                 # +1/-1 for ping-pong Play
        self._trace_ais = []          # display-only path curves
        self._range = (0.0, 360.0)

        lay = QVBoxLayout(self)
        self.file_label = QLabel()
        self.file_label.setWordWrap(True)
        lay.addWidget(self.file_label)
        row = QHBoxLayout()
        self.load_btn = QPushButton("Choose file...")
        self.load_btn.clicked.connect(self._choose_file)
        row.addWidget(self.load_btn)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setToolTip("Re-read the mechanism file after "
                                   "editing it")
        self.reload_btn.clicked.connect(self._load)
        row.addWidget(self.reload_btn)
        lay.addLayout(row)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 3600)         # tenths of a degree
        self.slider.valueChanged.connect(self._on_slider)
        lay.addWidget(self.slider)
        self.angle_label = QLabel()
        lay.addWidget(self.angle_label)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        self.trace_row = QHBoxLayout()
        self.trace_btn = QPushButton("Trace path")
        self.trace_btn.setToolTip(
            "Sweep the whole slider range and draw the path of the "
            "mechanism file's TRACE point(s), then find the straightest "
            "stretch of it")
        self.trace_btn.clicked.connect(self._trace)
        self.trace_row.addWidget(self.trace_btn)
        self.trace_row.addWidget(QLabel("straight within"))
        self.tol_box = QDoubleSpinBox()
        self.tol_box.setDecimals(3)
        self.tol_box.setRange(0.001, 100.0)
        self.tol_box.setValue(0.5)
        self.tol_box.setSuffix(" mm")
        self.trace_row.addWidget(self.tol_box)
        self.clear_trace_btn = QPushButton("Clear trace")
        self.clear_trace_btn.clicked.connect(self._clear_trace)
        self.trace_row.addWidget(self.clear_trace_btn)
        lay.addLayout(self.trace_row)
        self.trace_label = QLabel()
        self.trace_label.setWordWrap(True)
        lay.addWidget(self.trace_label)
        self._show_trace_row(False)

        btns = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self._toggle_play)
        btns.addWidget(self.play_btn)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset)
        btns.addWidget(self.reset_btn)
        self.done_btn = QPushButton("⏹ Done")
        self.done_btn.clicked.connect(self.close)
        btns.addWidget(self.done_btn)
        for b in (self.load_btn, self.reload_btn, self.play_btn,
                  self.reset_btn, self.done_btn, self.trace_btn,
                  self.clear_trace_btn):
            b.setAutoDefault(False)
            b.setDefault(False)
        lay.addLayout(btns)

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

        self._load()

    # ---- mechanism file -------------------------------------------
    def _choose_file(self):
        start = os.path.dirname(self._path)
        path, _ = QFileDialog.getOpenFileName(
            self, "Mechanism file", start, "Python files (*.py)")
        if path:
            self._path = path
            self._load()

    def _load(self):
        self._stop_play()
        self._clear_trace()
        self._restore()
        self._mod = None
        self.file_label.setText(f"Mechanism file: {self._path}")
        try:
            spec = importlib.util.spec_from_file_location(
                "kodacad_mechanism", self._path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._axes = mod.setup(_Ctx(self))
            self._mod = mod
        except Exception as e:
            self.status_label.setText(f"Could not load: "
                                      f"{type(e).__name__}: {e}")
            print(f"[mechanism] load failed: {type(e).__name__}: {e}")
            return
        self.setWindowTitle(f"Animate Mechanism - "
                            f"{getattr(mod, 'NAME', 'mechanism')}")
        missing = [n for n in mod.PARTS if not self._uids_named(n)]
        if missing:
            names = sorted({dm.part_dict[u].get("name", "?")
                            for u in dm.part_dict})
            self.status_label.setText(
                f"Parts not found: {', '.join(missing)}. Names in this "
                f"model: {', '.join(names)}")
            return
        self.status_label.setText("Drag the slider (angle of the "
                                  "driving crank).")
        lo, hi = getattr(mod, "RANGE", (0.0, 360.0))
        self._range = (float(lo), float(hi))
        self._dir = 1
        self.slider.blockSignals(True)
        self.slider.setRange(int(round(lo * 10)), int(round(hi * 10)))
        self.slider.setValue(self._slider_pos(getattr(mod, "START", 0.0)))
        self.slider.blockSignals(False)
        self._show_trace_row(bool(getattr(mod, "TRACE", None)))
        self.trace_label.setText("")
        self._apply(self.slider.value() / 10.0)

    def _slider_pos(self, angle):
        """Slider position for an angle: wrapped into the range when
        the range is a full turn, else clamped to it."""
        lo, hi = self._range
        if hi - lo >= 360.0:
            angle = lo + (angle - lo) % 360.0
        angle = min(max(angle, lo), hi)
        return int(round(angle * 10))

    def _show_trace_row(self, on):
        for i in range(self.trace_row.count()):
            w = self.trace_row.itemAt(i).widget()
            if w is not None:
                w.setVisible(on)
        self.trace_label.setVisible(on)

    def _uids_named(self, part_name):
        return [u for u, d in dm.part_dict.items()
                if d.get("name") == part_name]

    # ---- moving parts ---------------------------------------------
    def _roles_at(self, theta):
        """{role: (angle_deg, (tx, ty, tz))} for crank angle theta, from
        poses() if the file has it, else from angles() (pure rotation
        about a fixed shaft)."""
        if hasattr(self._mod, "poses"):
            return self._mod.poses(theta)
        return {r: (a, (0.0, 0.0, 0.0))
                for r, a in self._mod.angles(theta).items()}

    def _trsf_for(self, role, pose):
        """gp_Trsf: rotate about the role's axis by the angle, then
        translate."""
        angle, (tx, ty, tz) = pose
        (px, py, pz), (dx, dy, dz) = self._axes[role]
        rot = gp_Trsf()
        rot.SetRotation(gp_Ax1(gp_Pnt(px, py, pz), gp_Dir(dx, dy, dz)),
                        math.radians(angle))
        if tx or ty or tz:
            move = gp_Trsf()
            move.SetTranslation(gp_Vec(tx, ty, tz))
            return move.Multiplied(rot)
        return rot

    def _apply(self, theta):
        if self._mod is None:
            return
        try:
            poses = self._roles_at(theta)
        except Exception as e:
            self.status_label.setText(f"{type(e).__name__}: {e}")
            return
        ctx = self.win.canvas._display.Context
        for part_name, role in self._mod.PARTS.items():
            if role not in self._axes or role not in poses:
                continue
            loc = TopLoc_Location(self._trsf_for(role, poses[role]))
            for uid in self._uids_named(part_name):
                ais = self.win.ais_shape_dict.get(uid)
                if ais is None:
                    continue          # hidden or not drawn
                ctx.SetLocation(ais, loc)
                self._moved.add(uid)
        ctx.UpdateCurrentViewer()
        parts = ", ".join(f"{r} {p[0]:+.1f}\u00b0"
                          for r, p in poses.items())
        self.angle_label.setText(f"Angle {theta:.1f}\u00b0   ({parts})")
        self.status_label.setText("")

    # ---- trace -----------------------------------------------------
    def _clear_trace(self):
        ctx = self.win.canvas._display.Context
        for ais in self._trace_ais:
            try:
                self.win.canvas._display.remove_never_pick(ais)
                ctx.Remove(ais, False)
            except Exception as e:
                print(f"[mechanism] trace erase failed: {e}")
        self._trace_ais = []
        try:
            ctx.UpdateCurrentViewer()
        except Exception:
            pass
        self.trace_label.setText("")

    def _show_polyline(self, points, rgb, width):
        poly = BRepBuilderAPI_MakePolygon()
        for (x, y, z) in points:
            poly.Add(gp_Pnt(x, y, z))
        if not poly.IsDone():
            return
        from OCP.AIS import AIS_Shape
        ctx = self.win.canvas._display.Context
        ais = AIS_Shape(poly.Wire())
        ctx.Display(ais, False)
        self.win.canvas._display.add_never_pick(ais)
        ctx.SetColor(ais, Quantity_Color(
            *rgb, Quantity_TypeOfColor.Quantity_TOC_RGB), False)
        ctx.SetWidth(ais, width, False)
        self._trace_ais.append(ais)

    def _trace(self):
        if self._mod is None or not getattr(self._mod, "TRACE", None):
            return
        self._clear_trace()
        lo, hi = self._range
        step = float(getattr(self._mod, "TRACE_STEP", 0.5))
        n = int(round((hi - lo) / step))
        angles = [lo + i * step for i in range(n + 1)]
        text = []
        for label, (role, pt) in self._mod.TRACE.items():
            path, used = [], []
            for th in angles:
                try:
                    pose = self._roles_at(th)[role]
                except Exception:
                    continue          # outside what the linkage reaches
                q = gp_Pnt(*pt).Transformed(self._trsf_for(role, pose))
                path.append((q.X(), q.Y(), q.Z()))
                used.append(th)
            if len(path) < 2:
                text.append(f"{label}: no path")
                continue
            self._show_polyline(path, (1.0, 0.55, 0.0), 1.0)
            tol = self.tol_box.value()
            i, j, length, dev = trace_math.longest_straight_section(
                path, tol)
            if length > 0:
                self._show_polyline(path[i:j + 1], (0.1, 0.8, 0.2), 4.0)
                text.append(
                    f"{label}: straightest stretch within {tol:g} mm of "
                    f"a line: slider {used[i]:.1f}\u00b0 to {used[j]:.1f}"
                    f"\u00b0, {length:.1f} mm long (max deviation "
                    f"{dev:.3f} mm), from ({path[i][0]:.2f}, "
                    f"{path[i][1]:.2f}, {path[i][2]:.2f}) to "
                    f"({path[j][0]:.2f}, {path[j][1]:.2f}, "
                    f"{path[j][2]:.2f}).")
            print(f"[mechanism] trace '{label}': {len(path)} points, "
                  f"slider {used[0]:.1f} to {used[-1]:.1f}")
        self.trace_label.setText("  ".join(text))
        self.win.canvas._display.Context.UpdateCurrentViewer()

    def _restore(self):
        """Put every displaced part back where the document has it."""
        ctx = self.win.canvas._display.Context
        for uid in list(self._moved):
            ais = self.win.ais_shape_dict.get(uid)
            if ais is not None:
                try:
                    ctx.SetLocation(ais, TopLoc_Location())
                except Exception as e:
                    print(f"[mechanism] restore failed for {uid}: {e}")
        self._moved.clear()
        try:
            ctx.UpdateCurrentViewer()
        except Exception:
            pass

    # ---- slider / buttons -----------------------------------------
    def _on_slider(self, value):
        self._apply(value / 10.0)

    def _reset(self):
        self._stop_play()
        start = getattr(self._mod, "START", 0.0) if self._mod else 0.0
        self.slider.setValue(self._slider_pos(start))

    def _toggle_play(self):
        if self._playing:
            self._stop_play()
        elif self._mod is not None:
            self._playing = True
            self.play_btn.setText("⏸ Pause")
            self._timer.start()

    def _stop_play(self):
        self._playing = False
        self._timer.stop()
        self.play_btn.setText("▶ Play")

    def _tick(self):
        v = self.slider.value() + 10 * self._dir     # 1 degree per frame
        if getattr(self._mod, "LOOP", "wrap") == "pingpong":
            if v > self.slider.maximum():
                v, self._dir = self.slider.maximum(), -1
            elif v < self.slider.minimum():
                v, self._dir = self.slider.minimum(), 1
        elif v > self.slider.maximum():
            v = self.slider.minimum()
        self.slider.setValue(v)

    def closeEvent(self, event):
        self._stop_play()
        self._clear_trace()
        self._restore()
        event.accept()


def show_mechanism_dialog(main_win):
    """Launcher -- one dialog instance, raised if already open."""
    dlg = getattr(main_win, "_mechanism_dlg", None)
    if dlg is not None and dlg.isVisible():
        dlg.raise_()
        dlg.activateWindow()
        return
    dlg = MechanismDialog(main_win)
    main_win._mechanism_dlg = dlg
    dlg.show()
