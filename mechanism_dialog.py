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
from OCP.BRepBndLib import BRepBndLib
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf
from OCP.TopLoc import TopLoc_Location

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QVBoxLayout)

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
                  self.reset_btn, self.done_btn):
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
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((getattr(mod, "START", 0.0) % 360.0)
                                       * 10)))
        self.slider.blockSignals(False)
        self._apply(self.slider.value() / 10.0)

    def _uids_named(self, part_name):
        return [u for u, d in dm.part_dict.items()
                if d.get("name") == part_name]

    # ---- moving parts ---------------------------------------------
    def _apply(self, theta):
        if self._mod is None:
            return
        try:
            angs = self._mod.angles(theta)
        except Exception as e:
            self.status_label.setText(f"angles() failed: "
                                      f"{type(e).__name__}: {e}")
            return
        ctx = self.win.canvas._display.Context
        for part_name, role in self._mod.PARTS.items():
            axis = self._axes.get(role)
            if axis is None:
                continue
            (px, py, pz), (dx, dy, dz) = axis
            trsf = gp_Trsf()
            trsf.SetRotation(gp_Ax1(gp_Pnt(px, py, pz), gp_Dir(dx, dy, dz)),
                             math.radians(angs.get(role, 0.0)))
            loc = TopLoc_Location(trsf)
            for uid in self._uids_named(part_name):
                ais = self.win.ais_shape_dict.get(uid)
                if ais is None:
                    continue          # hidden or not drawn
                ctx.SetLocation(ais, loc)
                self._moved.add(uid)
        ctx.UpdateCurrentViewer()
        parts = ", ".join(f"{r} {a:+.1f}°" for r, a in angs.items())
        self.angle_label.setText(f"Crank angle {theta:.1f}°   ({parts})")

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
        self.slider.setValue(int(round((start % 360.0) * 10)))

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
        v = self.slider.value() + 10          # 1 degree per frame
        if v > self.slider.maximum():
            v = 0
        self.slider.setValue(v)

    def closeEvent(self, event):
        self._stop_play()
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
