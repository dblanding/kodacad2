#!/usr/bin/env python
#
# Copyright 2026 Doug Blanding (dblanding@gmail.com)
#
# This file is part of kodacad2.
# Licensed under the GNU General Public License v3 -- see LICENSE.
#
"""wp_set_dialog.py -- "Create Workplane Set" dialog, under the
Workplane menu (Session 127).

Origin: Doug raised CoCreate's "Workplane Set" concept as a future
loft workflow -- parallel workplanes from stem to stern of a ship's
hull, say, each with a cross-section profile, lofted together. The
loft side of this was already confirmed and smoke-tested
(smoke_test_loft_thru_sections.py, BRepOffsetAPI_ThruSections) --
this dialog is the other half: actually creating the set of
workplanes to draw the profiles on.

Doug looked at how Creo E/D does it (his own research PDF, from a
Creo training video) and found a 3-step flow: (1) a dialog creates N
parallel workplanes, offset by a fixed spacing D, (2) a SEPARATE
dialog creates an empty, named Workplane Set, (3) the new workplanes
are manually selected as a group in the tree and dragged into the
set. Doug's own call, verbatim: "I think we could do something pretty
similar to what Creo is doing but we could take a shortcut... We
could make N workplanes parallel to the active one, spaced apart by
distance D and have them all be children of the new wp Set 's1'...
I would lean toward keeping this simple and lean. Let's make it work,
then make it more deluxe later." So this dialog does all three of
Creo's steps in one Done press, and deliberately leaves out anything
Creo's workflow has that Doug didn't ask for:

  - no per-plane spacing list, no alternating/zigzag direction -- one
    uniform D, always offset along +W from the reference (active) wp.
  - no spin-angle option (Creo's own dialog has one; Doug's research
    PDF notes it goes unused in the demo).
  - no match-line UI -- Doug's own prior question ("does OCCT have a
    way to figure out the correct way to match up the profiles
    without the match line") was already answered yes
    (BRepOffsetAPI_ThruSections.CheckCompatibility, confirmed by
    smoke test) -- the loft step, not this one, is where that
    matters, and it isn't wired up yet either (separate, future step).
  - the reference (active) workplane itself is NOT added to the new
    set -- only the N new ones are, matching Creo's own distinction
    between "the plane you start from" and "the planes you create."
  - each new workplane starts as a bare, empty WorkPlane (the same
    starting state every other wp-creation command in kodacad.py
    leaves -- makeWP, wpOnFace, wpBy3Pts, wpByPtDir) -- Doug profiles
    each one by hand afterward, matching his own stated CoCreate-style
    workflow ("creating the first one then... making any needed
    modifications to the profile").

Non-modal QDialog, bold-label convention (pull_dialog.py /
mill_pull_dialog.py's own precedent), single "✅ Done" button --
this is a one-shot creation command, not a multi-operation session
like the Defeaturing dialog, so Apply/Done doesn't apply here.
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton)
from PySide6.QtGui import QFont

from OCP.gp import gp_Ax3, gp_Vec

import workplane


def _bold_label(text=""):
    lbl = QLabel(text)
    f = QFont()
    f.setBold(True)
    lbl.setFont(f)
    lbl.setWordWrap(True)
    return lbl


class WpSetDialog(QDialog):
    """Create N workplanes parallel to the active workplane, spaced by
    distance D along its own +W direction, grouped as children of a
    brand-new Workplane Set tree node -- all in one Done press."""

    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.setWindowTitle("Create Workplane Set")
        self.setModal(False)

        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("Reference Workplane (active):"))
        self.wp_label = _bold_label(str(main_win.activeWpUID) or "(none)")
        lay.addWidget(self.wp_label)

        row_n = QHBoxLayout()
        row_n.addWidget(QLabel("Number of workplanes (N):"))
        self.n_edit = QLineEdit("5")
        row_n.addWidget(self.n_edit)
        lay.addLayout(row_n)

        row_d = QHBoxLayout()
        units = getattr(main_win, "units", "mm")
        row_d.addWidget(QLabel(f"Spacing along +W ({units}):"))
        self.d_edit = QLineEdit()
        self.d_edit.setPlaceholderText("e.g. 20.0")
        row_d.addWidget(self.d_edit)
        lay.addLayout(row_d)

        self.msg_label = QLabel("")
        self.msg_label.setWordWrap(True)
        lay.addWidget(self.msg_label)

        self.done_btn = QPushButton("✅ Done")
        self.done_btn.clicked.connect(self._on_done)
        lay.addWidget(self.done_btn)

        self.d_edit.setFocus()

    def _on_done(self):
        main_win = self.main_win
        active_uid = main_win.activeWpUID
        active_wp = main_win.activeWp
        if not active_uid or active_wp is None:
            self.msg_label.setText(
                "No active workplane -- create or select one first.")
            return

        try:
            n = int(self.n_edit.text())
        except ValueError:
            self.msg_label.setText("N must be a whole number.")
            return
        if n < 1:
            self.msg_label.setText("N must be at least 1.")
            return

        try:
            d = float(self.d_edit.text())
        except ValueError:
            self.msg_label.setText("Spacing D must be a number.")
            return
        if d == 0:
            self.msg_label.setText("Spacing D must be nonzero.")
            return

        origin = active_wp.origin
        wDir = active_wp.wDir
        uDir = active_wp.uDir
        wVec = gp_Vec(wDir)

        new_wps = []
        for i in range(1, n + 1):
            new_origin = origin.Translated(wVec * (d * i))
            axis3 = gp_Ax3(new_origin, wDir, uDir)
            new_wps.append(workplane.WorkPlane(active_wp.size, ax3=axis3))

        set_uid, wp_uids = main_win.create_wp_set(new_wps)
        main_win.build_tree()
        main_win.redraw_workplanes()
        print(f"Workplane set {set_uid} created with {len(wp_uids)} "
             f"workplane(s), spaced {d} apart along +W from {active_uid}.")
        self.close()


def show_wp_set_dialog(main_win):
    """Launcher -- one dialog instance, raised if already open."""
    dlg = getattr(main_win, "_wp_set_dlg", None)
    if dlg is not None and dlg.isVisible():
        dlg.raise_()
        dlg.activateWindow()
        return
    dlg = WpSetDialog(main_win)
    main_win._wp_set_dlg = dlg
    dlg.show()
