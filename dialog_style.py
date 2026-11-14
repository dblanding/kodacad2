"""Minimalist dialog theme (Session 179, Doug: take the Creo E/D
dialog as the model -- small, landing in the upper-left corner of the
viewport so the geometry of interest stays visible).

Three shared pieces, so every dialog can be converted the same way:

  * apply_minimal(dlg)       -- compact stylesheet + a small tool-window
                                frame (no taskbar entry, stays above
                                the main window).
  * place_top_left(dlg, win) -- park the dialog in the viewport's
                                upper-left corner.
  * icon_bar(...)            -- the green check / red cross / ? row
                                (accept, cancel, help).
  * InfoWindow               -- an auxiliary floating window for the
                                detail text that used to crowd the
                                dialog itself (the '?' button toggles
                                it). It sits OUTSIDE the main window
                                when the screen has room (Doug works on
                                an external monitor), otherwise over
                                the lower-right of the viewport.
  * set_awaiting(widget, on) -- the Creo 'yellow field = pick something
                                now' cue.

Pure Qt layout and styling; no CAD logic lives here.
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout,
                               QToolButton, QTextBrowser, QLabel)

MINIMAL_QSS = """
QDialog, QWidget#KcInfo { background: #f0f0f0; font-size: 9pt; }
QLabel { color: #202020; }
QLabel[kc="rowlabel"] { background: #e2e2e2; padding: 2px 6px; }
QLineEdit { background: white; border: 1px solid #9a9a9a;
            padding: 1px 4px; }
QLineEdit[awaiting="true"] { background: #fff59d;
                             border: 1px solid #3b8eea; }
QComboBox { padding: 0px 4px; min-height: 18px; }
QCheckBox { spacing: 4px; }
QToolButton { border: 1px solid transparent; border-radius: 3px;
              font-size: 14pt; font-weight: bold; padding: 0px 14px; }
QToolButton:hover { border: 1px solid #9a9a9a; background: #fafafa; }
QToolButton:disabled { color: #b0b0b0; }
QToolButton#KcOk { color: #2e9d3a; }
QToolButton#KcCancel { color: #d03030; }
QToolButton#KcHelp { color: #555555; }
QLabel#KcStatus { color: #7a2a00; }
"""


def apply_minimal(dlg):
    """Compact look + small tool-window frame. Call once, after the
    dialog's widgets are built."""
    dlg.setWindowFlag(Qt.WindowType.Tool, True)
    dlg.setStyleSheet(MINIMAL_QSS)
    lay = dlg.layout()
    if lay is not None:
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)


def place_top_left(dlg, main_win, margin=8):
    """Move dlg to the upper-left corner of the 3D viewport."""
    try:
        view = main_win.canvas
        dlg.move(view.mapToGlobal(QPoint(margin, margin)))
    except Exception as e:
        print(f"[dialog_style] place_top_left failed: {e}")


def icon_bar(on_ok, on_cancel, on_help=None):
    """Returns (layout, ok_button, cancel_button, help_button)."""
    row = QHBoxLayout()
    ok = QToolButton()
    ok.setObjectName("KcOk")
    ok.setText("✔")
    ok.setToolTip("Done")
    ok.clicked.connect(on_ok)
    cancel = QToolButton()
    cancel.setObjectName("KcCancel")
    cancel.setText("✖")
    cancel.setToolTip("Cancel")
    cancel.clicked.connect(on_cancel)
    row.addWidget(ok)
    row.addWidget(cancel)
    help_btn = None
    if on_help is not None:
        help_btn = QToolButton()
        help_btn.setObjectName("KcHelp")
        help_btn.setText("?")
        help_btn.setToolTip("Show / hide details")
        help_btn.clicked.connect(on_help)
        row.addWidget(help_btn)
    return row, ok, cancel, help_btn


def row_label(text):
    lab = QLabel(text)
    lab.setProperty("kc", "rowlabel")
    return lab


def set_awaiting(widget, on):
    """Yellow 'waiting for a pick' state (re-polish so QSS re-reads
    the dynamic property)."""
    widget.setProperty("awaiting", "true" if on else "false")
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)


class InfoWindow(QWidget):
    """Floating details window. Owner calls set_html(); the '?' button
    calls toggle(main_win)."""

    def __init__(self, main_win, title="Details"):
        super().__init__(main_win, Qt.WindowType.Tool)
        self.setObjectName("KcInfo")
        self.setWindowTitle(title)
        self.setStyleSheet(MINIMAL_QSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        lay.addWidget(self.browser)
        self.resize(360, 320)
        self._placed = False

    def set_html(self, html):
        self.browser.setHtml(html)

    def _place(self, main_win):
        """Prefer the space beside the main window; fall back to the
        lower-right corner of the viewport."""
        try:
            avail = main_win.screen().availableGeometry()
            fr = main_win.frameGeometry()
            w, h = self.width(), self.height()
            if avail.right() - fr.right() >= w + 8:
                self.move(fr.right() + 8, fr.top())
            elif fr.left() - avail.left() >= w + 8:
                self.move(fr.left() - w - 8, fr.top())
            else:
                view = main_win.canvas
                br = view.mapToGlobal(QPoint(view.width(), view.height()))
                self.move(br.x() - w - 8, br.y() - h - 8)
        except Exception as e:
            print(f"[dialog_style] info window placement failed: {e}")

    def toggle(self, main_win):
        if self.isVisible():
            self.hide()
            return
        if not self._placed:
            self._place(main_win)
            self._placed = True  # after that the user may drag it
        self.show()
