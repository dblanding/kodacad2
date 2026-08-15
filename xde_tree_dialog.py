"""
xde_tree_dialog.py -- XDE label-hierarchy viewer (Session 66).

Doug's motivation: the Diffy assembly taught him he's "blind to the
extent to which shared instances are used" in an imported STEP file
-- names alone (e.g. 'Bearing Block' / 'Bearing Block (1)') don't
reveal whether two parts are a genuine OCAF shared-instance pair
(multiple components referencing one prototype label) or merely two
independent parts with a naming collision. This dialog answers that
directly from dm.label_dict, the same data build_tree() uses, so it
is always in sync with the live document -- no separate document walk.

Format follows the README's own XDE hierarchy example:
    0:1:1:1     as1 (assembly)
    0:1:1:2     rod-assembly
    0:1:1:1:1   rod-assembly_1  => 0:1:1:2   [SHARED x3]
Prototypes referenced by MORE than one component are tagged
[SHARED xN] -- the direct, at-a-glance answer to Doug's question.
"""

from collections import Counter

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# dm is created in mainwindow (module-global there), not docmodel
# (docmodel.py only defines the DocModel class) -- same import bug
# already caught once in mill_pull_dialog.py; fixed here before it
# ever shipped.
from mainwindow import dm


def _entry_sort_key(entry):
    """Natural sort for XDE entries ('0:1:1:10' after '0:1:1:2', not
    before it -- a plain string sort gets this wrong)."""
    try:
        return [int(p) for p in entry.split(":")]
    except (ValueError, AttributeError):
        return [entry]


class XdeTreeDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.setWindowTitle("XDE Label Hierarchy")
        self.resize(720, 560)
        self.setModal(False)

        lay = QVBoxLayout(self)

        self.summary_label = QLabel()
        lay.addWidget(self.summary_label)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        mono = QFont("Courier New")
        mono.setStyleHint(QFont.Monospace)
        self.text.setFont(mono)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(self.text)

        btns = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        btns.addWidget(self.refresh_btn)
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.clicked.connect(self._copy)
        btns.addWidget(self.copy_btn)
        btns.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btns.addWidget(self.close_btn)
        lay.addLayout(btns)

        self.refresh()

    def _copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.main_win.statusBar().showMessage(
            "XDE hierarchy copied to clipboard.", 3000)

    def refresh(self):
        lines = []
        label_dict = dm.label_dict

        # Which prototype entries are referenced by MORE than one
        # component -- the direct answer to 'is this really shared'.
        ref_counts = Counter(
            dic["ref_entry"] for dic in label_dict.values()
            if dic.get("ref_entry"))

        # parent_uid -> [child uids], children sorted by entry so the
        # tree reads in a stable, natural order every time.
        children = {}
        roots = []
        for uid, dic in label_dict.items():
            parent = dic.get("parent_uid")
            if parent is None:
                roots.append(uid)
            else:
                children.setdefault(parent, []).append(uid)
        roots.sort(key=lambda u: _entry_sort_key(
            label_dict[u].get("entry", "")))
        for kids in children.values():
            kids.sort(key=lambda u: _entry_sort_key(
                label_dict[u].get("entry", "")))

        def emit(uid, depth):
            dic = label_dict[uid]
            entry = dic.get("entry", "?")
            name = dic.get("name", "?")
            ref = dic.get("ref_entry")
            tags = []
            if ref:
                tags.append(f"=> {ref}")
            if entry in ref_counts and ref_counts[entry] > 1:
                tags.append(f"[SHARED x{ref_counts[entry]}]")
            tag_str = ("  " + "  ".join(tags)) if tags else ""
            lines.append(f"{'  ' * depth}{entry:<16} {name}{tag_str}")
            for child in children.get(uid, []):
                emit(child, depth + 1)

        for root in roots:
            emit(root, 0)

        n_parts = len(label_dict)
        n_shared_prototypes = sum(
            1 for c in ref_counts.values() if c > 1)
        n_shared_instances = sum(
            c for c in ref_counts.values() if c > 1)
        self.summary_label.setText(
            f"{n_parts} label(s) total  |  "
            f"{n_shared_prototypes} shared prototype(s), referenced "
            f"by {n_shared_instances} component(s) total")
        self.text.setPlainText("\n".join(lines))


def show_xde_tree_dialog(main_win):
    """Launcher -- one dialog instance, raised (and refreshed) if
    already open."""
    dlg = getattr(main_win, "_xde_tree_dlg", None)
    if dlg is not None:
        try:
            dlg.refresh()
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        except RuntimeError:
            pass  # underlying C++ object was deleted; fall through
    dlg = XdeTreeDialog(main_win)
    main_win._xde_tree_dlg = dlg
    dlg.show()
