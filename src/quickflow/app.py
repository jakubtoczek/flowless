"""The window. Widgets only: the experiment, gates and numbers are model.py's, the figures
plots.py's, the report report.py's; the Gating and Figure tabs are gating.py's and
figtab.py's, built the first time they're opened (matplotlib loads meanwhile).

Tabs, in the order of the work: Samples → Gating → Figure → Results → Experiment.
Drop anything anywhere: FCS files or folders, a saved experiment (.json); imports/ reads
the rest it can.
"""

from __future__ import annotations

import copy
import html
import json
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QEventLoop, QLocale, QMarginsF, QMimeData, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QBrush, QColor, QIcon, QImage, QKeySequence, QPageLayout,
                           QPageSize, QPainter, QPdfWriter, QPixmap, QShortcut, QTextDocument)
from PySide6.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox,
                               QApplication, QCheckBox, QComboBox, QCompleter, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                               QStackedWidget, QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QToolButton,
                               QVBoxLayout, QWidget)

from . import __version__, fcs, imports, model, record

APP_NAME = "QuickFlow"
_PKG = Path(__file__).resolve().parent
OPTIONS = _PKG.parents[1] / "quickflow_options.json"     # beside QuickFlow.bat
SAMPLE_COLUMNS = ["⤢", "plot", "group", "label", "role", "condition", "file", "well",
                  "acquired", "events", "µL", "primary", "primary µL", "secondary",
                  "secondary µL", "cells", "note"]
SHOWN_COLUMNS = ["⤢", "plot", "group", "label", "role", "condition", "file"]
DEFAULT_OPTIONS = {"negatives": ["0006", "R3B23"], "procedures": {}, "lists": {},
                   "last_dir": "", "aliases": {}, "sample_columns": SHOWN_COLUMNS,
                   "figure_options": None, "dpi": 300}
HINT = "Drop FCS files or folders anywhere on this window, or a saved experiment (.json)."
MAX_COL = 280                                             # px: no column wider at first
ACCENT = "#4a9782"                                        # ⤢ ▤: what opens more, the suite's


def glyph_icon(text: str, colour: str = ACCENT) -> QIcon:
    """A character as an icon (▤ on a toolbar button, the text beside it)."""
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    f = p.font()
    f.setPixelSize(52)                     # the glyph is about half its em: 26 px of 32
    p.setFont(f)
    p.setPen(QColor(colour))
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    return QIcon(pm)


class WheelGuard(QObject):
    """The wheel scrolls the page, never a value: a list or a number under the pointer
    while scrolling stays as set (the wheel goes to the scroll area around it). On those
    boxes only (guard_wheel): a filter on the whole application costs every event a call
    into Python."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QAbstractSpinBox)):
            w = obj.parentWidget()
            while w is not None and not isinstance(w, QAbstractScrollArea):
                w = w.parentWidget()
            if w is not None:
                QApplication.sendEvent(w.verticalScrollBar(), e)
            return True
        return False


_guard = None


def guard_wheel(root: QWidget) -> None:
    """The lists and number boxes under *root*: the wheel passes them by."""
    global _guard
    _guard = _guard or WheelGuard()
    for w in root.findChildren(QComboBox) + root.findChildren(QAbstractSpinBox):
        w.installEventFilter(_guard)


def app_icon():
    p = _PKG / "assets" / "quickflow.ico"
    return QIcon(str(p)) if p.exists() else None


def load_options() -> dict:
    try:
        d = json.loads(OPTIONS.read_text(encoding="utf-8"))
        d = d if isinstance(d, dict) else {}
        if "tick_pt" in (d.get("figure_options") or []):     # one tick size before x / y
            d["figure_options"] += ["xtick_pt", "ytick_pt"]
        return {**copy.deepcopy(DEFAULT_OPTIONS), **d}
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULT_OPTIONS)


def _warm():
    """matplotlib's first import and first log axis (its math-text parser, the fonts) take
    ~2 s: done in the background once the window is up, so the first plot doesn't wait."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        from . import plots
        fig = Figure(figsize=(2, 2))
        ax = fig.add_subplot()
        ax.set_xscale("log")
        ax.set_xlim(1, 1e7)
        ax.set_title("x", fontfamily=["Arial", "DejaVu Sans"])
        FigureCanvasAgg(fig).draw()
        _ = plots.DEFAULTS
    except Exception:                       # only a head start: never in the way
        pass


def _item(text, editable=True) -> QTableWidgetItem:
    it = QTableWidgetItem("" if text is None else str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    return it


def fit_columns(t: QTableWidget, cap: int = MAX_COL, stretch: bool = True) -> None:
    """Columns as wide as their contents and a little air, none wider than *cap* at
    first; the user can still drag them. *stretch*: the last one takes the rest (a text
    column; not numbers, which would end up far right)."""
    t.resizeColumnsToContents()
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.Interactive)
    for c in range(t.columnCount()):
        t.setColumnWidth(c, min(cap, t.columnWidth(c) + 14))
    h.setStretchLastSection(stretch)


def _expand_item() -> QTableWidgetItem:
    it = _item("⤢", False)
    it.setTextAlignment(Qt.AlignCenter)
    it.setForeground(QBrush(QColor(ACCENT)))
    it.setToolTip("everything about this row")
    return it


class _Combo(QStyledItemDelegate):
    """A cell edited by picking from *items*."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items

    def createEditor(self, parent, option, index):
        c = QComboBox(parent)
        c.addItems(self.items)
        return c

    def setEditorData(self, ed, index):
        ed.setCurrentText(index.data() or "")

    def setModelData(self, ed, model_, index):
        model_.setData(index, ed.currentText())


class InfoDialog(QDialog):
    """Everything about one row: its fields (editable) over what the files say (read
    only, filterable)."""

    def __init__(self, parent, title, fields, info):
        """fields: [(name, value, choices or None)]; info: [(key, value)]."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 680)
        self.edits = {}
        form = QFormLayout()
        for name, val, choices in fields:
            if choices == "check":
                w = QCheckBox()
                w.setChecked(bool(val))
            elif choices:
                w = QComboBox(editable=False)
                w.addItems(choices)
                w.setCurrentText(str(val))
            else:
                w = QLineEdit(str(val or ""))
            self.edits[name] = w
            form.addRow(name, w)
        v = QVBoxLayout(self)
        v.addLayout(form)
        if info:
            find = QLineEdit(placeholderText="filter…")
            t = QTableWidget(len(info), 2, editTriggers=QAbstractItemView.NoEditTriggers)
            t.setHorizontalHeaderLabels(["", ""])
            t.verticalHeader().hide()
            for r, (k, val) in enumerate(info):
                t.setItem(r, 0, _item(k, False))
                t.setItem(r, 1, _item(val, False))
            fit_columns(t, 320)

            def filt(s):
                for r in range(t.rowCount()):
                    t.setRowHidden(r, bool(s) and s.lower() not in
                                   (t.item(r, 0).text() + t.item(r, 1).text()).lower())

            find.textChanged.connect(filt)
            v.addWidget(find)
            v.addWidget(t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        guard_wheel(self)

    def values(self) -> dict:
        out = {}
        for k, w in self.edits.items():
            out[k] = w.isChecked() if isinstance(w, QCheckBox) else \
                w.currentText() if isinstance(w, QComboBox) else w.text().strip()
        return out


# --- Samples ----------------------------------------------------------------------------

class SamplesTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cols = list(SAMPLE_COLUMNS)
        self.sort_col, self.sort_desc = None, False
        self.table = QTableWidget(0, 0)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._quick)
        self.table.cellClicked.connect(self._clicked)
        self._roles = _Combo(model.ROLES, self.table)
        self._plain = QStyledItemDelegate(self.table)
        self.table.setToolTip("Edit a cell with several rows selected: they all take the "
                              "value. ⤢: everything about a sample. Click a column's title to "
                              "sort by it; right-click it for the columns shown. Del removes "
                              "the selected files.")
        h = self.table.horizontalHeader()
        h.setSectionsClickable(True)
        h.sectionClicked.connect(self._sort)
        h.setContextMenuPolicy(Qt.CustomContextMenu)
        h.customContextMenuRequested.connect(
            lambda pos: self.columns_menu(QMenu(self)).exec(h.mapToGlobal(pos)))
        self.hint = QLabel(HINT, wordWrap=True, alignment=Qt.AlignCenter)
        self.hint.setStyleSheet("color: #8d8d8d; font-size: 12pt; padding: 30px")
        self.quick_box = QWidget()
        self.quick_layout = QVBoxLayout(self.quick_box)
        self.quick_layout.setContentsMargins(0, 0, 0, 0)
        self.quick_title = QLabel("Select a sample: its events and its histogram show here",
                                  wordWrap=True)
        self.quick_title.setStyleSheet("color: #8d8d8d")
        self.quick_layout.addWidget(self.quick_title)
        self.canvases = None
        split = QSplitter()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.hint)
        lv.addWidget(self.table)
        bar = QHBoxLayout()
        for text, tip, fn in [("Import…", "FCS files, an experiment, a sheet… (Ctrl+I)",
                               win.import_dialog),
                              ("Remove", "Del", self.remove),
                              ("▲", "move up (legend and table order)", lambda: self.move(-1)),
                              ("▼", "move down", lambda: self.move(1))]:
            b = QPushButton(text, toolTip=tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        lv.addLayout(bar)
        split.addWidget(left)
        split.addWidget(self.quick_box)
        split.setSizes([950, 420])
        QVBoxLayout(self).addWidget(split)
        self.table.addAction(QAction(self.table, shortcut=QKeySequence.Delete,
                                     triggered=self.remove, shortcutContext=Qt.WidgetShortcut))

    def shown(self) -> list[str]:
        want = set(self.win.opts.get("sample_columns") or SHOWN_COLUMNS)
        return [c for c in self.cols if c in want]

    def columns_menu(self, m: QMenu) -> QMenu:
        want = list(self.win.opts.get("sample_columns") or SHOWN_COLUMNS)
        for c in self.cols:
            if c == "⤢":
                continue
            a = m.addAction(c)
            a.setCheckable(True)
            a.setChecked(c in want)
            a.toggled.connect(lambda on, c=c: self._toggle_column(c, on))
        m.addSeparator()
        m.addAction("the usual ones").triggered.connect(lambda: self._set_columns(SHOWN_COLUMNS))
        return m

    def _toggle_column(self, c, on):
        want = [x for x in (self.win.opts.get("sample_columns") or SHOWN_COLUMNS) if x != c]
        self._set_columns(want + ([c] if on else []))

    def _set_columns(self, cols):
        self.win.opts["sample_columns"] = list(dict.fromkeys(["⤢"] + list(cols)))
        self.win.save_options()
        self.refresh()

    def _value(self, s: model.Sample, col: str):
        f = s.fcs
        own = {"group": s.group, "label": s.label, "role": s.role, "file": Path(s.path).name,
               "well": fcs.pick(f.meta, ("$WELLID",)), "acquired": fcs.when(f.meta),
               "events": f.n, "µL": _fmt(fcs.volume_ul(f.meta), 1)}
        return own[col] if col in own else s.fields.get(col, "")

    def refresh(self):
        exp = self.win.exp
        self.hint.setVisible(not exp.samples)
        self.table.setVisible(bool(exp.samples))
        extra = [k for s in exp.samples for k in s.fields if k not in SAMPLE_COLUMNS]
        self.cols = SAMPLE_COLUMNS + list(dict.fromkeys(extra))
        cols = self.shown()
        t = self.table
        t.blockSignals(True)
        t.clear()
        t.setColumnCount(len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.setRowCount(len(exp.samples))
        for c, col in enumerate(cols):
            t.setItemDelegateForColumn(c, self._roles if col == "role" else self._plain)
        fixed = {"⤢", "file", "well", "acquired", "events", "µL"}
        for r, s in enumerate(exp.samples):
            for c, col in enumerate(cols):
                if col == "⤢":
                    it = _expand_item()
                elif col == "plot":
                    it = _item("", False)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked if s.plot else Qt.Unchecked)
                else:
                    it = _item(self._value(s, col), col not in fixed)
                    if col == "file":
                        it.setToolTip(s.path)
                    if col in ("events", "µL"):
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, it)
        if self.sort_col in cols:
            t.horizontalHeader().setSortIndicatorShown(True)
            t.horizontalHeader().setSortIndicator(
                cols.index(self.sort_col), Qt.DescendingOrder if self.sort_desc else Qt.AscendingOrder)
        else:
            t.horizontalHeader().setSortIndicatorShown(False)
        fit_columns(t)
        if "⤢" in cols:
            t.setColumnWidth(cols.index("⤢"), 26)
        if "plot" in cols:
            t.setColumnWidth(cols.index("plot"), 36)
        t.blockSignals(False)
        self._quick()

    def _edited(self, it: QTableWidgetItem):
        exp, col = self.win.exp, self.shown()[it.column()]
        sel = {i.row() for i in self.table.selectedIndexes()}
        rows = sel if it.row() in sel else {it.row()}
        self.win.snap()
        val = it.text().strip()
        for r in rows:
            s = exp.samples[r]
            if col == "plot":
                s.plot = it.checkState() == Qt.Checked
            elif col == "group":
                old = s.group
                s.group = val
                if val not in exp.gates and old in exp.gates:     # a new group: same gates
                    exp.gates[val] = copy.deepcopy(exp.gates[old])
            elif col == "label":
                s.label = val
            elif col == "role":
                s.role = val if val in model.ROLES else "sample"
                if s.role == "negative control" and s.label not in self.win.opts["negatives"]:
                    self.win.opts["negatives"].append(s.label)
                    self.win.save_options()
            else:
                s.fields[col] = val
        if col == "group":
            used = set(exp.groups())
            exp.gates = {g: v for g, v in exp.gates.items() if g in used}
        self.win.changed()

    def _clicked(self, row, col):
        cols = self.shown()
        if col < len(cols) and cols[col] == "⤢":
            self.details(row)

    def details(self, row):
        exp = self.win.exp
        s = exp.samples[row]
        f = s.fcs
        fields = [("group", s.group, None), ("label", s.label, None),
                  ("role", s.role, model.ROLES), ("plot", s.plot, "check")]
        fields += [(k, s.fields.get(k, ""), None) for k in
                   list(dict.fromkeys(record.SAMPLE_FIELDS + list(s.fields)))]
        fields.append(("shown as (alias)", exp.aliases.get("sample", {}).get(s.name, ""), None))
        sat = model.saturated(s)
        info = [("file", s.path), ("events", f"{f.n:,}".replace(",", " ")),
                ("acquired", fcs.when(f.meta)), ("end", fcs.pick(f.meta, ("$ETIM",))),
                ("volume", f"{_fmt(fcs.volume_ul(f.meta), 1)} µL"),
                ("acquisition", f"{_fmt(fcs.acquired_s(f.meta), 0)} s"),
                ("off scale", ", ".join(f"{c} {p:.1f} %" for c, p in sat.items()) or "none"),
                ("own gates", ", ".join(s.gates) or "none — the group's")]
        info += [(k, v) for k, keys in fcs.ACQUISITION for v in [fcs.pick(f.meta, keys)] if v]
        info += record.instrument(f)
        info += [(f"channel {c}", f"{f.label(c)}, scale to {f.range(c):.0f}") for c in f.channels]
        info += [(k, v) for k, v in f.meta.items() if not k.startswith(("$P", "#P"))]
        d = InfoDialog(self, f"{s.name} — {Path(s.path).name}", fields, info)
        if not d.exec():
            return
        v = d.values()
        self.win.snap()
        old = s.group
        s.group, s.label = v.pop("group") or s.group, v.pop("label") or s.label
        if s.group != old and s.group not in exp.gates and old in exp.gates:
            exp.gates[s.group] = copy.deepcopy(exp.gates[old])
        s.role, s.plot = v.pop("role"), v.pop("plot")
        alias = v.pop("shown as (alias)")
        self.win.set_alias("sample", s.name, alias)
        s.fields = {k: x for k, x in v.items() if x}
        self.win.changed()

    def _sort(self, col):
        cols = self.shown()
        name = cols[col]
        if name in ("⤢",):
            return
        self.sort_desc = not self.sort_desc if self.sort_col == name else False
        self.sort_col = name
        exp = self.win.exp
        self.win.snap()

        def key(s):
            v = s.plot if name == "plot" else self._value(s, name)
            if isinstance(v, (int, float)):
                return (0, v, "")
            return (1, 0, model._natural(Path(str(v))))

        exp.samples.sort(key=key, reverse=self.sort_desc)
        self.win.changed()

    def selected(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def remove(self):
        rows = self.selected()
        if not rows:
            return
        self.win.snap()
        exp = self.win.exp
        exp.samples = [s for i, s in enumerate(exp.samples) if i not in rows]
        used = set(exp.groups())
        exp.gates = {g: v for g, v in exp.gates.items() if g in used}
        self.win.changed()

    def move(self, d):
        rows = self.selected()
        exp = self.win.exp
        if not rows or rows[0] + d < 0 or rows[-1] + d >= len(exp.samples):
            return
        self.win.snap()
        ss = exp.samples
        for r in (rows if d < 0 else rows[::-1]):
            ss[r], ss[r + d] = ss[r + d], ss[r]
        self.sort_col = None
        self.win.changed()
        self.table.clearSelection()
        for r in rows:
            self.table.selectRow(r + d)

    def _quick(self):
        """The selected sample at a glance: its events on its first gate's axes (FSC-A ×
        SSC-A) with that gate, and its marker histogram on the main population."""
        rows = self.selected()
        exp = self.win.exp
        if not rows or rows[0] >= len(exp.samples):
            return
        s = exp.samples[rows[0]]
        from . import plots
        from .canvas import PlotCanvas

        if self.canvases is None:
            self.canvases = (PlotCanvas(on_copy=lambda: self.win.log("✓ dot plot copied")),
                             PlotCanvas(on_copy=lambda: self.win.log("✓ histogram copied")))
            sp = QSplitter(Qt.Vertical)
            for c in self.canvases:
                c.figure.add_subplot()
                sp.addWidget(c)
            self.quick_layout.addWidget(sp, 1)
        tree = exp.tree(s)
        first = next((g for g in tree if not g.parent and g.kind == "polygon"), None)
        x, y = (first.x, first.y) if first else ("FSC-A", "SSC-A")
        o = {**plots.options(exp), "title_pt": 8.5, "label_pt": 8, "xtick_pt": 7, "ytick_pt": 7,
             "gate_pt": 7, "legend": "none"}
        dot, hist = self.canvases
        a1, a2 = dot.figure.axes[0], hist.figure.axes[0]
        drawn = [g for g in tree if not g.parent and g.kind == "polygon" and (g.x, g.y) == (x, y)]
        plots.dot_axes(a1, exp, [s], x, y, "", drawn, o)
        a2.clear()
        plots.hist_axes(a2, exp, {"group": s.group, "title": f"{exp.name('label', s.label)} › "
                                  f"{exp.main_population(s.group)}"},
                        o, plots.series_style(exp, o), only=[s])
        self.quick_title.setText(f"{exp.name('group', s.group)} · {exp.name('label', s.label)}"
                                 f" — {Path(s.path).name}")
        for c in self.canvases:
            c.draw_idle()


def _fmt(v, nd=0) -> str:
    if v is None or v == "":
        return ""
    return f"{v:.{nd}f}" if nd else f"{v:,.0f}".replace(",", " ")


# --- Results ----------------------------------------------------------------------------

class ResultsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.mode = QComboBox()
        self.mode.addItems(["summary (the figure's table)", "every sample and population",
                            "replicates: runs pooled (groups shown under one name)"])
        self.mode.currentIndexChanged.connect(lambda _: self.refresh())
        self.stat = QComboBox(toolTip="the value of the summary, the bars and ÷ control")
        self.stat.addItems(list(model.STATS))
        self.stat.currentTextChanged.connect(self._stat)
        self.chan = QComboBox(toolTip="the channel measured: the marker")
        self.chan.currentIndexChanged.connect(self._marker)
        self.table = QTableWidget(editTriggers=QAbstractItemView.NoEditTriggers)
        self.note = QLabel(wordWrap=True)
        self.note.setStyleSheet("color: #8d8d8d")
        top = QHBoxLayout()
        top.addWidget(self.mode)
        top.addWidget(QLabel("value"))
        top.addWidget(self.stat)
        top.addWidget(QLabel("of"))
        top.addWidget(self.chan)
        top.addStretch()
        for text, tip, fn in [("⧉", "Copy the table (Ctrl+C: the selected rows, else all): "
                                    "paste into Excel, Word or PowerPoint as a table",
                               self.copy),
                              ("Export…", "Excel (every sheet) or CSV (this table)", self.export),
                              ("Report…", "PDF, HTML, PowerPoint or Excel (Ctrl+P)", win.report)]:
            b = QPushButton(text, toolTip=tip)
            if text == "⧉":
                b.setStyleSheet(f"font-size: 15px; color: {ACCENT}; padding: 0 10px")
            b.clicked.connect(fn)
            top.addWidget(b)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.table, 1)
        v.addWidget(self.note)
        self.addAction(QAction(self, shortcut=QKeySequence.Copy, triggered=self.copy,
                               shortcutContext=Qt.WidgetWithChildrenShortcut))

    def _stat(self, s):
        if s and s != self.win.exp.stat:
            self.win.snap()
            self.win.exp.stat = s
            self.win.changed()

    def _marker(self, _):
        c = self.chan.currentData()
        if c and c != self.win.exp.marker:
            self.win.snap()
            self.win.exp.marker = c
            self.win.changed()

    def rows(self) -> tuple[list[str], list[list]]:
        from . import report

        exp = self.win.exp
        if self.mode.currentIndex() == 0:
            heads = ["group", "label", "sub-population", "events", "% parent", exp.stat,
                     "÷ control"]
            return heads, [[exp.title(r["group"]), exp.name("label", r["label"]),
                            exp.name("population", r["sub-population"]) or "—", r["count"],
                            r["% parent"], r["value"], r["÷ control"]]
                           for r in report.summary_rows(exp)]
        if self.mode.currentIndex() == 2:
            heads = ["group", "label", "sub-population", "runs", f"{exp.stat} mean", "SD",
                     "÷ control mean", "SD ", "each run"]
            return heads, [[r["group"], r["label"], r["sub-population"] or "—", r["n"],
                            r["mean"], r["sd"], r["ratio mean"], r["ratio sd"], r["runs"]]
                           for r in report.replicate_rows(exp)]
        heads = ["group", "label", "role", "sample", "population", "count", "% parent",
                 "geometric mean", "median", "mean", "CV %", "÷ control"]
        named = {"label", "sample", "population"}
        return heads, [[exp.title(r[h]) if h == "group" else exp.name(h, r[h]) if h in named
                        else r[h] for h in heads] for r in exp.results()]

    def refresh(self):
        from . import report

        exp = self.win.exp
        self.stat.blockSignals(True)
        self.stat.setCurrentText(exp.stat)
        self.stat.blockSignals(False)
        self.chan.blockSignals(True)
        self.chan.clear()
        for c in exp.fluorescence() + [c for c in exp.shown_channels()
                                       if c not in exp.fluorescence()]:
            self.chan.addItem(exp.name("channel", c), c)
        self.chan.setCurrentIndex(max(0, self.chan.findData(exp.marker)))
        self.chan.blockSignals(False)
        heads, rows = self.rows()
        t = self.table
        t.clear()
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                txt = report.num(v, 2 if heads[c] in ("÷ control", "÷ control mean", "SD ") else
                                 1 if heads[c] in ("% parent", "CV %") else 0) \
                    if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v or "")
                it = _item(txt, False)
                if isinstance(v, (int, float)):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, it)
        fit_columns(t, stretch=False)
        self.note.setText(report.stat_note(exp))

    def copy(self):
        from . import report

        heads, rows = self.rows()
        sel = sorted({i.row() for i in self.table.selectedIndexes()}) or range(len(rows))
        rows = [rows[i] for i in sel]
        fmt = [[("" if v is None else f"{v:.6g}" if isinstance(v, float) else str(v))
                for v in r] for r in rows]
        tsv = "\n".join("\t".join(r) for r in [heads] + fmt)
        md = QMimeData()
        md.setText(tsv)
        md.setHtml(report.table(heads, [[report.num(v, 2) if isinstance(v, float) and v < 100
                                         else report.num(v) if isinstance(v, (int, float))
                                         else (v or "") for v in r] for r in rows]))
        QApplication.clipboard().setMimeData(md)
        self.win.log(f"✓ {len(rows)} rows copied")

    def export(self):
        from . import report

        p, _ = QFileDialog.getSaveFileName(
            self, "Export the values",
            str(Path(self.win.opts.get("last_dir") or Path.home()) / (self.win.stem() + ".xlsx")),
            "Excel (*.xlsx);;CSV (*.csv)")
        if not p:
            return
        if p.lower().endswith(".csv"):
            import csv
            heads, rows = self.rows()
            with open(p, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(heads)
                w.writerows(rows)
        else:
            report.save_xlsx(self.win.exp, p)
        self.win.log(f"✓ values saved: {p}")


# --- Experiment record ------------------------------------------------------------------

class RecordTab(QScrollArea):
    def __init__(self, win):
        super().__init__(widgetResizable=True)
        self.win = win
        body = QWidget()
        v = QVBoxLayout(body)
        gen = QGroupBox("Experiment")
        f = QFormLayout(gen)
        self.fields = {}
        for k in record.GENERAL:
            e = QLineEdit(placeholderText=record.HINT.get(k, ""))
            e.editingFinished.connect(lambda k=k, e=e: self._general(k, e.text()))
            self.fields[k] = e
            f.addRow(k, e)
        v.addWidget(gen)
        grp = QGroupBox("Groups (cells)")
        gv = QVBoxLayout(grp)
        self.groups = QTableWidget(0, 1 + len(record.GROUP_FIELDS))
        self.groups.setHorizontalHeaderLabels(["⤢"] + record.GROUP_FIELDS)
        self.groups.itemChanged.connect(self._group_edit)
        self.groups.cellClicked.connect(lambda r, c: self._group_details(r) if c == 0 else None)
        self.groups.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        gv.addWidget(self.groups)
        v.addWidget(grp)
        rg = QGroupBox("Reagents")
        rv = QVBoxLayout(rg)
        self.reagents = QTableWidget(0, 2 + len(record.REAGENT_FIELDS))
        self.reagents.setHorizontalHeaderLabels(["⤢"] + record.REAGENT_FIELDS + ["reads as"])
        self.reagents.setItemDelegateForColumn(2, _Combo(record.REAGENT_KINDS, self.reagents))
        self.reagents.itemChanged.connect(self._reagent_edit)
        self.reagents.cellClicked.connect(lambda r, c: self._reagent_details(r) if c == 0 else None)
        self.reagents.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        rv.addWidget(self.reagents)
        h = QHBoxLayout()
        for text, fn in (("+ reagent", self._add_reagent), ("− remove", self._del_reagent)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        rv.addLayout(h)
        v.addWidget(rg)
        pg = QGroupBox("Procedure — one step per line")
        pv = QVBoxLayout(pg)
        self.proc = QPlainTextEdit()
        self.proc.setMinimumHeight(220)
        self.proc.textChanged.connect(lambda: self._ptimer.start())
        self._ptimer = QTimer(singleShot=True, interval=600, timeout=self._proc_edit)
        pv.addWidget(self.proc)
        h = QHBoxLayout()
        rec = QToolButton(text="Recorded procedures ▾", popupMode=QToolButton.InstantPopup)
        self.rec_menu = QMenu(rec)
        self.rec_menu.aboutToShow.connect(self._fill_recorded)
        rec.setMenu(self.rec_menu)
        h.addWidget(rec)
        h.addStretch()
        pv.addLayout(h)
        v.addWidget(pg)
        ag = QGroupBox("Acquisition — from the files")
        self.acq = QLabel(wordWrap=True, textInteractionFlags=Qt.TextSelectableByMouse)
        QVBoxLayout(ag).addWidget(self.acq)
        v.addWidget(ag)
        ig = QGroupBox("Instrument — from the files")
        self.instr = QLabel(wordWrap=True, textInteractionFlags=Qt.TextSelectableByMouse)
        QVBoxLayout(ig).addWidget(self.instr)
        v.addWidget(ig)
        cg = QGroupBox("MIFlowCyt — what a report of this experiment holds")
        self.check = QLabel(wordWrap=True)
        QVBoxLayout(cg).addWidget(self.check)
        v.addWidget(cg)
        v.addStretch()
        self.setWidget(body)

    def rec(self) -> dict:
        self.win.exp.record = record.clean(self.win.exp.record)
        return self.win.exp.record

    def refresh(self):
        rec = self.rec()
        exp = self.win.exp
        lists = self.win.opts.get("lists", {})
        acq = dict(record.acquisition(exp.samples))
        for k, e in self.fields.items():
            e.setText(rec["general"].get(k, ""))
            if lists.get(k):
                e.setCompleter(QCompleter(lists[k], e))
        self.fields["date"].setPlaceholderText(acq.get("date") or record.HINT["date"])
        t = self.groups
        t.blockSignals(True)
        t.setRowCount(len(exp.groups()))
        t.setVerticalHeaderLabels([exp.name("group", g) for g in exp.groups()])
        for r, g in enumerate(exp.groups()):
            t.setItem(r, 0, _expand_item())
            for c, f in enumerate(record.GROUP_FIELDS, 1):
                t.setItem(r, c, _item(rec["groups"].get(g, {}).get(f, "")))
        fit_columns(t)
        t.setColumnWidth(0, 26)
        t.blockSignals(False)
        t = self.reagents
        t.blockSignals(True)
        t.setRowCount(len(rec["reagents"]))
        for r, rg in enumerate(rec["reagents"]):
            t.setItem(r, 0, _expand_item())
            for c, f in enumerate(record.REAGENT_FIELDS, 1):
                t.setItem(r, c, _item(rg.get(f, "")))
            t.setItem(r, len(record.REAGENT_FIELDS) + 1, _item(record.describe(rg), False))
        fit_columns(t)
        t.setColumnWidth(0, 26)
        t.blockSignals(False)
        self.proc.blockSignals(True)
        self.proc.setPlainText("\n".join(rec["procedure"]))
        self.proc.blockSignals(False)
        first = exp.samples[0].fcs if exp.samples else None
        self.acq.setText("<br>".join(f"<b>{k}</b>: {v}" for k, v in acq.items()) or "(no file yet)")
        self.instr.setText("<br>".join(f"<b>{k}</b>: {v}" for k, v in record.instrument(first))
                           or "(no file yet)")
        self._checklist()

    def _checklist(self):
        exp = self.win.exp
        items = record.miflowcyt(self.rec(), exp.samples, exp.gates)
        self.check.setText("<br>".join(f"{'✓' if ok else '<span style=\"color:#e66767\">✗</span>'}"
                                       f" {i} <span style='color:#8d8d8d'>— {w}</span>"
                                       for i, ok, w in items))

    def _general(self, k, val):
        rec = self.rec()
        if rec["general"].get(k, "") == val:
            return
        rec["general"][k] = val
        if val:
            lst = self.win.opts.setdefault("lists", {}).setdefault(k, [])
            if val not in lst:
                lst.insert(0, val)
                del lst[30:]
        self.win.set_dirty()
        self._checklist()

    def _group_edit(self, it):
        if it.column() == 0:
            return
        g = self.win.exp.groups()[it.row()]
        self.rec()["groups"].setdefault(g, {})[record.GROUP_FIELDS[it.column() - 1]] = \
            it.text().strip()
        self.win.set_dirty()
        self._checklist()

    def _group_details(self, r):
        exp = self.win.exp
        g = exp.groups()[r]
        d = self.rec()["groups"].get(g, {})
        fields = [(f, d.get(f, ""), None) for f in record.GROUP_FIELDS]
        fields.append(("shown as (alias)", exp.aliases.get("group", {}).get(g, ""), None))
        info = [(exp.name("label", s.label), f"{s.role} — {Path(s.path).name}")
                for s in exp.in_group(g)]
        info += [("gates", ", ".join(x.name for x in exp.gates.get(g, [])) or "none")]
        dlg = InfoDialog(self, g, fields, info)
        if dlg.exec():
            v = dlg.values()
            self.win.set_alias("group", g, v.pop("shown as (alias)"))
            self.rec()["groups"][g] = {k: x for k, x in v.items() if x}
            self.win.changed()

    def _reagent_edit(self, it):
        if not 0 < it.column() <= len(record.REAGENT_FIELDS):
            return
        self.rec()["reagents"][it.row()][record.REAGENT_FIELDS[it.column() - 1]] = it.text().strip()
        self.win.set_dirty()
        self._checklist()
        d = self.reagents.item(it.row(), len(record.REAGENT_FIELDS) + 1)
        if d is not None:
            self.reagents.blockSignals(True)
            d.setText(record.describe(self.rec()["reagents"][it.row()]))
            self.reagents.blockSignals(False)

    def _reagent_details(self, r):
        rg = self.rec()["reagents"][r]
        fields = [(f, rg.get(f, ""), record.REAGENT_KINDS if f == "kind" else None)
                  for f in record.REAGENT_FIELDS]
        dlg = InfoDialog(self, rg.get("name") or "reagent", fields,
                         [("reads as", record.describe(rg) or "(say more: kind, target, "
                                                              "fluorochrome)")])
        if dlg.exec():
            self.rec()["reagents"][r] = record.complete(dlg.values())
            self.win.changed()

    def _add_reagent(self):
        self.rec()["reagents"].append({k: "" for k in record.REAGENT_FIELDS})
        self.win.set_dirty()
        self.refresh()

    def _del_reagent(self):
        rows = sorted({i.row() for i in self.reagents.selectedIndexes()}, reverse=True)
        for r in rows:
            del self.rec()["reagents"][r]
        if rows:
            self.win.changed()

    def _proc_edit(self):
        steps = [x.strip() for x in self.proc.toPlainText().splitlines() if x.strip()]
        if steps != self.rec()["procedure"]:
            self.rec()["procedure"] = steps
            self.win.set_dirty()
            self._checklist()

    def _fill_recorded(self):
        m = self.rec_menu
        m.clear()
        procs = self.win.opts.setdefault("procedures", {})
        for name in sorted(procs):
            m.addAction(f"use: {name}").triggered.connect(
                lambda _=False, n=name: self._use(n))
        if procs:
            m.addSeparator()
        m.addAction("Record this procedure as…").triggered.connect(self._record)

    def _use(self, name):
        self._proc_edit()
        self.rec()["procedure"] = list(self.win.opts["procedures"][name])
        self.win.set_dirty()
        self.refresh()

    def _record(self):
        self._proc_edit()
        steps = self.rec()["procedure"]
        if not steps:
            return
        name, ok = QInputDialog.getText(self, "Record the procedure", "name:",
                                        text=self.rec()["general"].get("title", ""))
        if ok and name.strip():
            self.win.opts.setdefault("procedures", {})[name.strip()] = list(steps)
            self.win.save_options()
            self.win.log(f"✓ procedure recorded as '{name.strip()}'")


# --- Aliases ----------------------------------------------------------------------------

class AliasDialog(QDialog):
    """What the figure, the tables and the report call things: a name per group, label,
    sample, channel or population (empty: its own)."""

    KIND_NAMES = {"group": "group", "label": "label (series)", "sample": "sample",
                  "channel": "channel", "population": "population"}

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        exp = win.exp
        self.setWindowTitle("▤ Aliases — what things are called on the figure, the tables, "
                            "the report")
        self.resize(720, 640)
        rows = []
        names = {"group": exp.groups(), "label": exp.labels(),
                 "sample": [s.name for s in exp.samples], "channel": exp.shown_channels(),
                 "population": list(dict.fromkeys(g.name for gs in exp.gates.values() for g in gs))}
        for kind in model.ALIAS_KINDS:
            for n in names[kind]:
                own = exp.samples[0].fcs.label(n) if kind == "channel" and exp.samples else n
                rows.append((kind, n, own, exp.aliases.get(kind, {}).get(n, "")))
        self.rows = rows
        self.kind = QComboBox()
        self.kind.addItem("everything", "")
        for k in model.ALIAS_KINDS:
            self.kind.addItem(self.KIND_NAMES[k], k)
        self.kind.currentIndexChanged.connect(lambda _: self._filter())
        t = self.table = QTableWidget(len(rows), 3)
        t.setHorizontalHeaderLabels(["", "name", "shown as"])
        t.verticalHeader().hide()
        for r, (kind, n, own, alias) in enumerate(rows):
            t.setItem(r, 0, _item(self.KIND_NAMES[kind], False))
            t.setItem(r, 1, _item(own, False))
            a = _item(alias)
            a.setToolTip("empty: the name itself")
            t.setItem(r, 2, a)
        fit_columns(t, 300)
        QShortcut(QKeySequence.Copy, t, self._copy, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence.Paste, t, self._paste, context=Qt.WidgetShortcut)
        self.remember = QCheckBox("remember them for the next experiments (same names)")
        self.remember.setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Double-click a 'shown as' cell to type the name to show — e.g. "
                           "FL2-A :: PE-A → anti-His PE, or a cell line's full name. Ctrl+C "
                           "copies a name, Ctrl+V pastes it as the selected rows' 'shown as'. "
                           "Labels shown under one name are one series in the figure."))
        v.addWidget(self.kind)
        v.addWidget(t, 1)
        v.addWidget(self.remember)
        v.addWidget(bb)

    def _copy(self):
        it = self.table.currentItem()
        if it is not None:
            QApplication.clipboard().setText(it.text())

    def _paste(self):
        text = QApplication.clipboard().text().strip()
        for r in {i.row() for i in self.table.selectedIndexes()} or {self.table.currentRow()}:
            if r >= 0 and not self.table.isRowHidden(r):
                self.table.item(r, 2).setText(text)

    def _filter(self):
        k = self.kind.currentData()
        for r, row in enumerate(self.rows):
            self.table.setRowHidden(r, bool(k) and row[0] != k)

    def apply(self):
        self.win.snap()
        for r, (kind, n, _, _) in enumerate(self.rows):
            self.win.set_alias(kind, n, self.table.item(r, 2).text().strip(),
                               self.remember.isChecked())
        self.win.changed()


# --- Options ----------------------------------------------------------------------------

class OptionsDialog(QDialog):
    """The options, a topic per page (list on the left); each applies as it is ticked and
    is remembered."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Options")
        self.resize(860, 600)
        self.topics = QListWidget()
        self.topics.setFixedWidth(190)
        self.pages = QStackedWidget()
        self.topics.currentRowChanged.connect(self.pages.setCurrentIndex)
        for name, page in (("Samples table", self._columns()), ("Channels", self._channels()),
                           ("Figure options", self._figure())):
            self.topics.addItem(name)
            sc = QScrollArea(widgetResizable=True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setWidget(page)
            self.pages.addWidget(sc)
        self.topics.setCurrentRow(0)
        where = QLabel(f"remembered as they change, in {OPTIONS}")
        where.setStyleSheet("color: #8d8d8d")
        h = QHBoxLayout()
        h.addWidget(self.topics)
        h.addWidget(self.pages, 1)
        v = QVBoxLayout(self)
        v.addLayout(h, 1)
        v.addWidget(where)

    @staticmethod
    def _page(title, text):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 4, 8, 4)
        t = QLabel(f"<b>{title}</b>")
        t.setStyleSheet("font-size: 14px")
        v.addWidget(t)
        d = QLabel(text, wordWrap=True)
        d.setStyleSheet("color: #8d8d8d")
        v.addWidget(d)
        return w, v

    def _columns(self):
        w, v = self._page("Samples table", "The columns of the Samples tab (also: right-click "
                                            "a column's title). ⤢ always shows everything.")
        st = self.win.samples_tab
        boxes = {}

        def sync():
            want = set(self.win.opts.get("sample_columns") or SHOWN_COLUMNS)
            for c, b in boxes.items():
                b.blockSignals(True)
                b.setChecked(c in want)
                b.blockSignals(False)

        for c in st.cols:
            if c != "⤢":
                boxes[c] = b = QCheckBox(c)
                b.toggled.connect(lambda on, c=c: st._toggle_column(c, on))
                v.addWidget(b)
        sync()
        usual = QPushButton("The usual ones")
        usual.clicked.connect(lambda: (st._set_columns(SHOWN_COLUMNS), sync()))
        h = QHBoxLayout()
        h.addWidget(usual)
        h.addStretch()
        v.addLayout(h)
        v.addStretch()
        return w

    def _channels(self):
        win = self.win
        exp = win.exp
        w, v = self._page("Channels", "The channels offered in the lists (gates, histograms, "
                                      "figure, values). Any channel a gate uses is always "
                                      "offered.")
        if not exp.samples:
            v.addWidget(QLabel("(no file yet: the channels are the files')"))
            v.addStretch()
            return w
        auto = QCheckBox("automatic: FSC-A, SSC-A and the fluorochromes' areas ("
                         + ", ".join(exp.name("channel", c) for c in exp.fluorescence()) + ")")
        v.addWidget(auto)
        boxes = {}

        def sync():
            shown = set(win.exp.shown_channels())
            for b in [auto, *boxes.values()]:
                b.blockSignals(True)
            auto.setChecked(not win.exp.channels)
            for c, b in boxes.items():
                b.setChecked(c in shown)
            for b in [auto, *boxes.values()]:
                b.blockSignals(False)

        def picked():
            win._set_channels([c for c, b in boxes.items() if b.isChecked()])
            sync()

        auto.toggled.connect(lambda on: (win._set_channels([] if on else
                                                           win.exp.shown_channels()), sync()))
        for c in exp.all_channels():
            boxes[c] = b = QCheckBox(exp.name("channel", c))
            b.toggled.connect(picked)
            v.addWidget(b)
        sync()
        v.addStretch()
        return w

    def _figure(self):
        from . import plots

        w, v = self._page("Figure options", "The options listed in the Figure tab; the others "
                                            "keep their value (or the style's).")
        vis = set(self.win.opts.get("figure_options") or
                  [o["key"] for o in plots.OPTIONS if o["shown"]])
        boxes = {}
        for o in plots.OPTIONS:
            if o["bar"] or o["key"] in plots.LEGEND_KEYS[2:]:   # always there: the layout's
                continue                                        # bar, the legend's box
            if o["section"] not in boxes:
                boxes[o["section"]] = QVBoxLayout(box := QGroupBox(o["section"]))
                v.addWidget(box)
            b = QCheckBox(o["label"].replace("&", "&&"), toolTip=o.get("tip", ""))
            b.setChecked(o["key"] in vis)
            b.toggled.connect(lambda on, k=o["key"]: self.win._figure_option(k, on))
            boxes[o["section"]].addWidget(b)
        v.addStretch()
        return w


# --- Report -----------------------------------------------------------------------------

class ReportDialog(QDialog):
    """The format, the sections on the left (tick, drag in order: each format keeps its
    own), the report as it will read on the right, one Save."""

    FORMATS = [(".pdf", "PDF"), (".html", "Web page (.html)"),
               (".pptx", "PowerPoint slide (figure + tables; the rest in its notes)"),
               (".xlsx", "Excel workbook (a sheet per section)")]
    OFF = {".pdf": [], ".html": [], ".pptx": ["samples", "checklist"],
           ".xlsx": ["figure", "checklist"]}          # unticked at first, per format

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Report")
        self.resize(1200, 820)
        self.timer = QTimer(singleShot=True, interval=250, timeout=self.refresh)
        self.fmt = QComboBox()
        for ext, label in self.FORMATS:
            self.fmt.addItem(label, ext)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(win.opts.get("report_format"))))
        self.fmt.currentIndexChanged.connect(self._format)
        self.ext = self.fmt.currentData()
        self.list = QListWidget(toolTip="tick the sections; drag them in order — each format "
                                        "remembers its own")
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.itemChanged.connect(lambda _: self.timer.start())
        self.list.model().rowsMoved.connect(lambda *_: self.timer.start())
        self.full = QCheckBox("every sample and population in the results, too")
        self.full.toggled.connect(lambda _: self.timer.start())
        save = QPushButton("Save report…", toolTip="Ctrl+S")
        save.clicked.connect(self.save)
        QShortcut(QKeySequence.Save, self, self.save)
        side = QWidget()
        side.setFixedWidth(330)
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("<b>Format</b>"))
        v.addWidget(self.fmt)
        v.addSpacing(8)
        v.addWidget(QLabel("<b>Sections</b>"))
        v.addWidget(self.list, 1)
        v.addWidget(self.full)
        v.addSpacing(8)
        v.addWidget(save)
        self.view = QTextBrowser()
        self.view.setStyleSheet("QTextBrowser { background: white; color: black }")
        h = QHBoxLayout(self)
        h.addWidget(side)
        h.addWidget(self.view, 1)
        self._fill()
        self.refresh()

    def _state(self, ext) -> tuple[list[str], set[str]]:
        """(order, unticked) for *ext*: as left, else the format's defaults."""
        from . import report

        keys = [k for k, _ in report.SECTIONS]
        st = self.win.opts.get("report_sections", {}).get(ext)
        if st is None and ext in (".pdf", ".html") and "report" in self.win.opts:
            st = {"order": self.win.opts["report"], "off": self.win.opts.get("report_off", [])}
        st = st or {"order": keys, "off": self.OFF.get(ext, [])}
        order = [k for k in st["order"] if k in keys]
        return order + [k for k in keys if k not in order], set(st["off"])

    def _fill(self):
        from . import report

        names = dict(report.SECTIONS)
        order, off = self._state(self.ext)
        self.list.blockSignals(True)
        self.list.clear()
        for k in order:
            place = report.where(self.ext, k)
            it = QListWidgetItem(names[k] + (f"  — {place}" if place else ""))
            it.setData(Qt.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if k in off else Qt.Checked)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.full.setEnabled(self.ext in (".pdf", ".html"))

    def _format(self, _):
        self._remember()
        self.ext = self.fmt.currentData()
        self._fill()
        self.refresh()

    def sections(self):
        items = [self.list.item(i) for i in range(self.list.count())]
        return [i.data(Qt.UserRole) for i in items if i.checkState() == Qt.Checked]

    def _remember(self):
        items = [self.list.item(i) for i in range(self.list.count())]
        self.win.opts.setdefault("report_sections", {})[self.ext] = {
            "order": [i.data(Qt.UserRole) for i in items],
            "off": [i.data(Qt.UserRole) for i in items if i.checkState() != Qt.Checked]}
        self.win.opts["report_format"] = self.fmt.currentData()
        self.win.save_options()

    def refresh(self):
        from . import report

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            exp, secs = self.win.exp, self.sections()
            if self.ext == ".pptx":
                text, images, notes = report.pptx_parts(exp, secs)
                text = text.replace("</body>", "<h2>Notes (below the slide)</h2><pre "
                                    "style='white-space: pre-wrap; font-size: 8.5pt'>"
                                    f"{html.escape(notes)}</pre></body>")
            else:
                text, images = report.build(exp, secs, self.full.isChecked() and
                                            self.ext in (".pdf", ".html"))
            y = self.view.verticalScrollBar().value()
            self.view.setDocument(html_document(text, images, self.view))
            self.view.verticalScrollBar().setValue(y)
        finally:
            QApplication.restoreOverrideCursor()
        self._remember()

    def write(self, p):
        from . import report

        exp, ext, secs = self.win.exp, self.ext, self.sections()
        if ext == ".xlsx":
            report.save_xlsx(exp, p, secs)
        elif ext == ".pptx":
            report.save_pptx(exp, p, secs)
        else:
            text, images = report.build(exp, secs, self.full.isChecked())
            if ext == ".html":
                report.save_html(text, images, p)
            else:
                to_pdf(text, images, p)

    def save(self):
        win, ext = self.win, self.ext
        p, _ = QFileDialog.getSaveFileName(
            self, "Save the report",
            str(Path(win.opts.get("last_dir") or Path.home()) / (win.stem() + "_report" + ext)),
            f"{self.fmt.currentText()} (*{ext})")
        if not p:
            return
        self._remember()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.write(p)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Could not write the report:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        win.log(f"✓ report saved: {p}")


def html_document(text: str, images: dict, parent=None) -> QTextDocument:
    """The report's HTML with its images, as Qt lays it out (the preview, the PDF)."""
    doc = QTextDocument(parent)
    for name, png in images.items():
        doc.addResource(QTextDocument.ImageResource, QUrl(name), QImage.fromData(png))
    doc.setHtml(text)
    return doc


def to_pdf(text: str, images: dict, path) -> None:
    doc = html_document(text, images)
    w = QPdfWriter(str(path))
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)   # print_ adds 2 cm
    w.setTitle(Path(path).stem)
    w.setCreator(f"QuickFlow {__version__}")
    doc.print_(w)


# --- Window -----------------------------------------------------------------------------

TABS = ["1  Samples", "2  Gating", "3  Figure", "4  Results", "5  Experiment"]


class MainWindow(QMainWindow):
    def __init__(self):
        QLocale.setDefault(QLocale.c())     # 1.5, not the system's 1,5: as published; before
        super().__init__()                  # the window, or it and its children keep the old
        self.opts = load_options()
        self.exp = model.Experiment(record=record.empty())
        self.undo, self.redo = [], []
        self.dirty = False
        self.resize(1400, 860)
        self.setAcceptDrops(True)

        self.tabs = QTabWidget()
        self.samples_tab = SamplesTab(self)
        self.results_tab = ResultsTab(self)
        self._pages = [self.samples_tab, None, None, self.results_tab, None]
        self._holders = {}
        for i, name in enumerate(TABS):
            w = self._pages[i]
            if w is None:                         # built when first opened
                w = QWidget()
                QVBoxLayout(w).setContentsMargins(0, 0, 0, 0)
                self._holders[i] = w
            self.tabs.addTab(w, name)
        self.tabs.currentChanged.connect(lambda _: self._refresh_current())
        self.stale = set()
        self.logbox = QPlainTextEdit(readOnly=True, maximumHeight=110)
        self.logbox.setPlaceholderText("What happened, and what looks wrong (✗ ⚠)")

        bar = self.addToolBar("main")
        bar.setMovable(False)
        for text, key, tip, fn in [
                ("Open…", QKeySequence.Open, "an experiment (.json) or FCS files", self.open_dialog),
                ("Save", QKeySequence.Save, "the experiment as one .json", self.save),
                ("Save as…", QKeySequence.SaveAs, "", self.save_as),
                (None, None, None, None),
                ("Import…", "Ctrl+I", "FCS files or a folder of them, an experiment, gates "
                                      "(Gating-ML) — the kind is told by the file",
             self.import_dialog),
                (None, None, None, None),
                ("Report…", "Ctrl+P", "PDF, HTML, PowerPoint or Excel", self.report)]:
            if text is None:
                bar.addSeparator()
                continue
            a = QAction(text, self, toolTip=f"{tip} ({QKeySequence(key).toString()})"
                        if key else tip, triggered=fn)
            a.setShortcut(QKeySequence(key))
            bar.addAction(a)
        for key, fn in ((QKeySequence.Undo, self.do_undo), (QKeySequence.Redo, self.do_redo),
                        (QKeySequence("Ctrl+Shift+Z"), self.do_redo)):
            self.addAction(QAction(self, shortcut=key, triggered=fn))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.addAction(QAction(glyph_icon("▤"), "Aliases…", self, triggered=self.aliases_dialog,
                              toolTip="what the figure, the tables and the report call the "
                                      "groups, labels, samples, channels, populations"))
        bar.addAction(QAction("Options…", self, triggered=self.options_dialog,
                              toolTip="what is shown: the samples' columns, the channels, the "
                                      "figure's options"))

        central = QWidget()
        v = QVBoxLayout(central)
        v.addWidget(self.tabs, 1)
        v.addWidget(self.logbox)
        self.setCentralWidget(central)
        guard_wheel(self)
        self.refresh_all()
        self._title()
        self._warmer = threading.Thread(target=_warm, daemon=True)
        self._warmer.start()

    def ready(self):
        """Wait for the warm-up before anything that plots: two threads importing
        matplotlib at once can each get the other's half-loaded module. The window keeps
        painting meanwhile: on a cold start (antivirus, disk) that import takes seconds,
        and a window that stops answering for 5 s is 'not responding' to Windows."""
        t = getattr(self, "_warmer", None)
        if t is None or not t.is_alive():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            while t.is_alive():
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents, 50)
                t.join(0.03)
        finally:
            QApplication.restoreOverrideCursor()

    # -- the tabs built when first opened
    def page(self, i):
        if self._pages[i] is None:
            self.ready()
            if i == 1:
                from .gating import GatingTab
                w = GatingTab(self)
            elif i == 2:
                from .figtab import FigureTab
                w = FigureTab(self)
            else:
                w = RecordTab(self)
            self._holders[i].layout().addWidget(w)
            guard_wheel(w)
            self._pages[i] = w
            self.stale.add(i)
        return self._pages[i]

    @property
    def gating_tab(self):
        return self.page(1)

    @property
    def figure_tab(self):
        return self.page(2)

    @property
    def record_tab(self):
        return self.page(4)

    def _record_edits(self):
        """The procedure being typed, in the record (it's taken in after a pause)."""
        if self._pages[4] is not None:
            self._pages[4]._proc_edit()

    # -- bookkeeping
    def log(self, *lines):
        for line in lines:
            self.logbox.appendPlainText(line)

    def save_options(self):
        try:
            OPTIONS.write_text(json.dumps(self.opts, indent=1, ensure_ascii=False),
                               encoding="utf-8")
        except OSError as e:
            self.log(f"⚠ options not saved: {e}")

    def stem(self) -> str:
        if self.exp.path:
            return Path(self.exp.path).stem
        g = record.clean(self.exp.record)["general"]
        return g.get("title") or "quickflow"

    def _title(self):
        name = Path(self.exp.path).name if self.exp.path else "new experiment"
        self.setWindowTitle(f"{APP_NAME} {__version__} — {name}{' •' if self.dirty else ''}")

    def set_dirty(self, v=True):
        self.dirty = v
        self._title()

    def snap(self):
        """Before a change: what Ctrl+Z goes back to."""
        self.undo.append(json.dumps(self.exp.to_dict()))
        del self.undo[:-100]
        self.redo.clear()

    def _restore(self, text):
        exp, _ = model.Experiment.from_dict(json.loads(text), self.exp.path)
        self.exp = exp
        self.changed()

    def do_undo(self):
        if self.undo:
            self.redo.append(json.dumps(self.exp.to_dict()))
            self._restore(self.undo.pop())

    def do_redo(self):
        if self.redo:
            self.undo.append(json.dumps(self.exp.to_dict()))
            self._restore(self.redo.pop())

    def changed(self, redraw_gating=True):
        self.set_dirty()
        self.stale = set(range(len(TABS)))
        if not redraw_gating:
            self.stale.discard(1)
        self._refresh_current()

    def refresh_all(self):
        self.stale = set(range(len(TABS)))
        self._refresh_current()

    def _refresh_current(self):
        if self.stale:
            self.ready()
        i = self.tabs.currentIndex()
        w = self.page(i)
        if i in self.stale:
            self.stale.discard(i)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                w.refresh()
            finally:
                QApplication.restoreOverrideCursor()

    # -- names
    def set_alias(self, kind, name, alias, remember=True):
        d = self.exp.aliases.setdefault(kind, {})
        if alias and alias != name:
            d[name] = alias
        else:
            d.pop(name, None)
        if remember:
            r = self.opts.setdefault("aliases", {}).setdefault(kind, {})
            if alias and alias != name:
                r[name] = alias
            else:
                r.pop(name, None)
            self.save_options()

    def _known_aliases(self):
        """Names given before, for the names this experiment has (and hasn't named)."""
        exp, known = self.exp, self.opts.get("aliases", {})
        have = {"group": exp.groups(), "label": exp.labels(),
                "sample": [s.name for s in exp.samples], "channel": exp.all_channels(),
                "population": [g.name for gs in exp.gates.values() for g in gs]}
        for kind, names in have.items():
            for n in names:
                if n in known.get(kind, {}) and n not in exp.aliases.get(kind, {}):
                    exp.aliases.setdefault(kind, {})[n] = known[kind][n]

    def _pool_same_named(self, new):
        """Two runs' folders named alike (a space for a dash): one name for the groups just
        added (*new*), so they are replicates of one condition (▤ Aliases keeps them apart
        again: not redone afterwards)."""
        for g, first in self.exp.same_named().items():
            if g not in new:
                continue
            self.set_alias("group", g, first, remember=False)
            self.log(f"✓ '{g}' shown as '{first}' (the same name but for spaces and dashes): "
                     "another run of it — pooled as replicates in Results; ▤ Aliases to "
                     "keep them apart")
            self.dirty = True

    def aliases_dialog(self):
        if not self.exp.samples:
            self.log("✗ no sample yet")
            return
        d = AliasDialog(self)
        if d.exec():
            d.apply()

    # -- options
    def options_dialog(self):
        self.ready()
        OptionsDialog(self).exec()

    def _set_channels(self, chans):
        self.snap()
        self.exp.channels = list(chans)
        self.changed()

    def _figure_option(self, key, on):
        self.ready()
        from . import plots

        vis = list(self.opts.get("figure_options") or
                   [o["key"] for o in plots.OPTIONS if o["shown"]])
        vis = [k for k in vis if k != key] + ([key] if on else [])
        self.opts["figure_options"] = vis
        self.save_options()
        if self._pages[2] is not None:
            self._pages[2].build_options()

    # -- files
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.open_paths([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])

    def open_paths(self, paths):
        self.ready()
        kinds = [(p, imports.kind(p)) for p in paths]
        for p, k in kinds:
            if k == "experiment":
                self.open_experiment(p)
        fcs_like = [p for p, k in kinds if k == "fcs"]
        if fcs_like:
            self.add_files(fcs_like)
        for p, k in kinds:
            if k in ("gates", "gatingml"):
                self.import_gates(p, k)
            elif k == "sheet":
                self.import_procedure(p)
            elif not k:
                self.log(f"✗ {p.name}: not a file QuickFlow reads")

    def add_files(self, paths):
        self.snap()
        before = set(self.exp.groups())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            added, bad = self.exp.add(paths, self.opts.get("negatives", []))
            new_groups = [g for g in self.exp.groups() if g not in before]
            for g in new_groups:
                if self.exp.gates.get(g):
                    continue
                f = self.exp.in_group(g)[0].fcs
                x, y = next(((a, b) for a, b in (("FSC-A", "SSC-A"), ("FSC-H", "SSC-H"))
                             if a in f.data and b in f.data), (None, None))
                v = model.auto_gate(self.exp.in_group(g), x, y) if x else []
                if v:
                    model.add_cells_gate(self.exp, g, x, y, v)
            fig = self.exp.figure
            if fig.get("panels") is not None:          # a figure of its own: new groups added
                from . import plots
                fig["panels"] += [plots.new_panel(g) for g in new_groups]
            self._known_aliases()
            self._pool_same_named(new_groups)
        finally:
            QApplication.restoreOverrideCursor()
        if not added and not bad:
            self.undo.pop()
            self.log("(nothing new: those files are already in)")
            return
        if added:
            self.opts["last_dir"] = str(Path(added[-1].path).parent)
            groups = list(dict.fromkeys(s.group for s in added))
            self.log(f"✓ {len(added)} files in {len(groups)} groups: " + ", ".join(groups),
                     "  groups, labels and roles are guessed from the folders and names — "
                     "check them in Samples; new groups got a 'cells (auto)' gate on "
                     "FSC × SSC — check it in Gating")
            for g in groups:
                worst = {}
                for s in self.exp.in_group(g):
                    for c, p in model.saturated(s).items():
                        worst[c] = max(worst.get(c, 0), p)
                if worst:
                    self.log(f"⚠ {g}: off scale (piled at the top) in up to "
                             + ", ".join(f"{p:.0f} % of events on {c}" for c, p in worst.items())
                             + " — a gate drawn to the plot's edge takes them")
        self.log(*[f"✗ {b}" for b in bad])
        self.changed()

    def import_gates(self, p, kind="gatingml"):
        from .imports import flowjo, gatingml

        if not self.exp.samples:
            self.log(f"✗ {p.name}: add the FCS files first, then the gates")
            return
        self.snap()
        try:
            self.log(f"Gates of {p.name}:",
                     *(gatingml if kind == "gatingml" else flowjo).apply(self.exp, p))
        except Exception as e:
            self.undo.pop()
            self.log(f"✗ {p.name}: {e}")
            return
        self.exp.gates_file = {"path": str(Path(p).resolve()), "how": "imported",
                               "key": self.exp.gates_key()}
        self.changed()

    def import_procedure(self, p):
        from .imports import sheet

        try:
            got = sheet.read(p)
        except Exception as e:
            self.log(f"✗ {p.name}: {e}")
            return
        self.snap()
        rec = record.clean(self.exp.record)
        self.exp.record = rec
        lines = sheet.apply(rec, got, self.exp.samples, self.exp.groups())
        if not rec["general"].get("title"):
            rec["general"]["title"] = p.stem
        self.log(f"Procedure sheet {p.name} (read as well as its layout allows — check "
                 "Experiment):", *lines)
        if not lines:
            self.log("  (nothing found in it)")
        if not self.exp.channels and self.exp.marker not in self.exp.fluorescence() and \
                self.exp.fluorescence():
            self.exp.marker = self.exp.fluorescence()[0]
        self.changed()

    def open_experiment(self, p):
        if not self._discard_ok():
            return
        try:
            exp, problems = model.Experiment.open(p)
        except Exception as e:
            self.log(f"✗ {p.name}: {e}")
            return
        exp.record = record.clean(exp.record, exp.labels())
        self.exp = exp
        self.dirty = False
        self.log(f"✓ opened {p}", *[f"⚠ {x}" for x in problems])
        self._known_aliases()
        self.undo.clear()
        self.redo.clear()
        self.refresh_all()
        self.set_dirty(self.dirty)

    def _dir(self):
        return self.opts.get("last_dir") or str(Path.home())

    def open_dialog(self):
        ps, _ = QFileDialog.getOpenFileNames(self, "Open", self._dir(),
                                             "Experiment or FCS (*.json *.fcs);;All (*.*)")
        if ps:
            self.open_paths([Path(p) for p in ps])

    def import_dialog(self):
        ps, _ = QFileDialog.getOpenFileNames(self, "Import", self._dir(), imports.FILTER)
        if ps:
            self.open_paths([Path(p) for p in ps])

    def save(self):
        if not self.exp.path:
            return self.save_as()
        self._record_edits()
        self.exp.save(self.exp.path)
        self.set_dirty(False)
        self.save_options()
        self.log(f"✓ saved {self.exp.path}")
        return True

    def save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save the experiment",
                                           str(Path(self._dir()) / (self.stem() + ".json")),
                                           "QuickFlow experiment (*.json)")
        if not p:
            return False
        self.exp.path = str(Path(p).resolve())
        return self.save()

    def report(self):
        if not self.exp.samples:
            self.log("✗ no sample yet")
            return
        self._record_edits()
        ReportDialog(self).exec()

    def _discard_ok(self) -> bool:
        if not self.dirty or not self.exp.samples:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save the changes to this experiment?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return bool(self.save())
        return r == QMessageBox.Discard

    def closeEvent(self, e):
        if self._discard_ok():
            self.save_options()
            e.accept()
        else:
            e.ignore()
