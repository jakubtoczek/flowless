"""The Figure tab: the figure's items on the left (panels and the legend: + to add one)
over the options of the figure - or of the selected panel, which then override the
figure's -; in the middle the layout as boxes (click to select, drag to arrange); on the
right the figure itself, as it is exported. Widgets only: the figure is plots.figure().
"""

from __future__ import annotations

import copy
import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
                               QToolButton, QVBoxLayout, QWidget)

from . import plots
from .app import guard_wheel
from .canvas import FOCUS, FigureView, copy_figure
from .gating import GroupList

FIGURE = "▣  The figure — every panel"
ACCENT = "#4a9782"


class Schematic(QWidget):
    """The figure's layout as boxes, in its proportions: click one to select it (outside
    them: the whole figure), drag a panel onto another's place, the legend above, below or
    right of the figure or into the grid. Del removes the selected panel."""

    picked = Signal(int)                 # an index in panels(); -1: the figure
    moved = Signal(int, int)             # item, onto item's place
    legend = Signal(str, int)            # place, item whose place it takes (grid) or -1
    M = 30                               # px around the figure: the legend's drop zones

    def __init__(self):
        super().__init__()
        self.cells, self.texts, self.size_mm = [], {}, (1.0, 1.0)
        self.legend_i, self.place, self.sel = None, "bottom", -1
        self.press = self.drag = None
        self.setMinimumSize(180, 160)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_layout(self, cells, texts, size_mm, legend_i, place, sel):
        self.cells, self.texts, self.size_mm = list(cells), texts, size_mm
        self.legend_i, self.place, self.sel = legend_i, place, sel
        self.update()

    def _frame(self) -> QRectF:
        m, (W, H) = self.M, self.size_mm
        a = QRectF(self.rect()).adjusted(m, m, -m, -m - 26)       # 26: the legend chip
        k = min(a.width() / max(W, 1), a.height() / max(H, 1))
        return QRectF(a.center().x() - W * k / 2, a.center().y() - H * k / 2, W * k, H * k)

    def _boxes(self) -> list[tuple[int, QRectF]]:
        f = self._frame()
        out = [(i, QRectF(f.left() + x0 * f.width(), f.top() + (1 - y1) * f.height(),
                          (x1 - x0) * f.width(), (y1 - y0) * f.height()).adjusted(2, 2, -2, -2))
               for i, (x0, y0, x1, y1) in self.cells]
        for _, r in out:                     # a legend band above / below: readable
            if r.height() < 18:
                if r.center().y() < f.center().y():
                    r.setTop(r.bottom() - 18)
                else:
                    r.setBottom(r.top() + 18)
        if self.legend_i is not None and all(i != self.legend_i for i, _ in out):
            out.append((self.legend_i, QRectF(f.center().x() - 90, self.height() - 26, 180, 22)))
        return out

    def _zones(self) -> dict[str, QRectF]:
        f, m = self._frame(), self.M
        return {"top": QRectF(f.left(), f.top() - m, f.width(), m - 2),
                "bottom": QRectF(f.left(), f.bottom() + 2, f.width(), m - 2),
                "right": QRectF(f.right() + 2, f.top(), m - 2, f.height())}

    def _at(self, pos) -> int | None:
        return next((i for i, r in self._boxes() if r.contains(pos)), None)

    def _target(self, pos):
        """Where the dragged item would go: ("legend", place, item) | ("move", item)."""
        i = self.drag[0]
        if i == self.legend_i:
            for place, r in self._zones().items():
                if r.contains(pos):
                    return ("legend", place, -1)
        grid = {j for j, _ in self.cells if j != self.legend_i or self.place == "grid"}
        j = next((j for j, r in self._boxes() if r.contains(pos) and j in grid and j != i), None)
        if j is None:
            return None
        return ("legend", "grid", j) if i == self.legend_i else ("move", j)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = self._frame()
        p.fillRect(self.rect(), QColor("#262626"))
        p.fillRect(f, QColor("#323232"))
        if not self.cells and self.legend_i is None:
            p.setPen(QColor("#8d8d8d"))
            p.drawText(self.rect(), Qt.AlignCenter, "nothing yet")
            return
        drag_to = self._target(self.drag[1]) if self.drag else None
        if self.drag and self.drag[0] == self.legend_i:
            p.setPen(QPen(QColor("#8d8d8d"), 1, Qt.DashLine))
            for place, r in self._zones().items():
                p.drawRect(r)
                p.drawText(r, Qt.AlignCenter, {"top": "above", "bottom": "below",
                                               "right": "right"}[place])
        font = p.font()
        font.setPointSizeF(8)
        p.setFont(font)
        for i, r in self._boxes():
            leg, on = i == self.legend_i, i == self.sel
            p.setBrush(QColor("#2f3d38" if leg else "#3d3d3d"))
            p.setPen(QPen(FOCUS if on else QColor(ACCENT if leg else "#6a6a6a"), 2 if on else 1))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("#e0e0e0"))
            p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignCenter | Qt.TextWordWrap,
                       self.texts.get(i, ""))
        if drag_to:
            r = self._zones()[drag_to[1]] if drag_to[0] == "legend" and drag_to[2] < 0 else                 dict(self._boxes())[drag_to[-1]]
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(FOCUS, 2, Qt.DashLine))
            p.drawRect(r)
        if self.drag:
            src = dict(self._boxes())[self.drag[0]]
            p.setOpacity(0.5)
            p.setBrush(FOCUS)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(src).translated(self.drag[1] - self.press[1]), 4, 4)

    def mousePressEvent(self, e):
        self.setFocus()
        i = self._at(e.position())
        self.press = (i, e.position()) if i is not None else None
        if i is None:
            self.picked.emit(-1)

    def mouseMoveEvent(self, e):
        if self.press and (self.drag or (e.position() - self.press[1]).manhattanLength() > 6):
            self.drag = (self.press[0], e.position())
            self.update()

    def mouseReleaseEvent(self, e):
        press, drag, self.press = self.press, self.drag, None
        to = self._target(e.position()) if drag else None
        self.drag = None
        self.update()
        if to and to[0] == "move":
            self.moved.emit(drag[0], to[1])
        elif to:
            self.legend.emit(to[1], to[2])
        elif press and not drag:
            self.picked.emit(press[0])


class FigureTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.sel = -1                              # -1: the figure; else an index in panels()
        self._snap_key = (None, 0.0)
        self.fig = None
        self.timer = QTimer(singleShot=True, interval=120, timeout=self.render)

        self.preset = QComboBox(toolTip="a set of options for the whole figure (sizes, fonts, "
                                        "black & white); panels keep their own")
        self.preset.addItems(list(plots.PRESETS))
        apply = QPushButton("Apply", toolTip="apply this style to the figure")
        apply.clicked.connect(self._apply_preset)
        self.items = GroupList(toolTip="The figure's items in order: drag to move one; the "
                                       "legend's place counts when it is 'in the grid'. "
                                       "Select one for its options; the first line: the "
                                       "whole figure's.")
        self.items.setDragDropMode(QAbstractItemView.InternalMove)
        self.items.setMaximumHeight(118)
        self.items.currentRowChanged.connect(self._selected)
        self.items.moved.connect(self._moved)
        self.items.addAction(QAction(self.items, shortcut=QKeySequence.Delete,
                                     triggered=self.remove, shortcutContext=Qt.WidgetShortcut))
        bar = QHBoxLayout()
        for text, tip, fn in [("+", "add a panel (a copy of the selected one)", self.add),
                              ("−", "remove the selected panel (Del)", self.remove),
                              ("↺", "the selected panel back to the figure's options",
                               self.reset_panel)]:
            b = QPushButton(text, toolTip=tip)
            b.setFixedWidth(36)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.opt_box = QWidget()
        self.opt_layout = QVBoxLayout(self.opt_box)
        self.opt_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.opt_box)
        self.dpi = QSpinBox(suffix=" dpi", singleStep=100, toolTip="PNG / TIFF resolution")
        self.dpi.setRange(72, 1200)
        self.dpi.setValue(win.opts.get("dpi", 300))
        self.dpi.valueChanged.connect(lambda v: win.opts.__setitem__("dpi", v))
        exp_row = QHBoxLayout()
        exp_row.addWidget(self.dpi)
        for text, tip, fn in [("Save…", "PNG, TIFF, SVG or PDF (SVG / PDF: text stays text)",
                               self.save),
                              ("Colour + B&&W…", "both versions in one go", self.save_both),
                              ("Copy", "Ctrl+C on the figure: paste into PowerPoint, Word…",
                               self.copy)]:
            b = QPushButton(text, toolTip=tip)
            b.clicked.connect(fn)
            exp_row.addWidget(b)
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        h = QHBoxLayout()
        h.addWidget(QLabel("style"))
        h.addWidget(self.preset, 1)
        h.addWidget(apply)
        sv.addLayout(h)
        sv.addWidget(self.items)
        sv.addLayout(bar)
        sv.addWidget(scroll, 1)
        sv.addLayout(exp_row)

        self.view = FigureView()
        self.view.clicked.connect(self._clicked)
        self.view.zoomed.connect(lambda _: self.zoom.setText(f"{self.view.zoom_percent():.0f} %"))
        self.view.addAction(QAction(self.view, shortcut=QKeySequence.Copy, triggered=self.copy,
                                    shortcutContext=Qt.WidgetShortcut))
        self.view.setToolTip("Wheel: zoom; drag: move; double-click: fit; click a panel for "
                             "its options; Ctrl+C copies the figure")
        self.zoom = QLabel("")
        self.zoom.setMinimumWidth(46)
        self.checker = QCheckBox("checker", toolTip="a checker behind the figure: shows where "
                                                    "it is transparent")
        self.checker.setChecked(True)
        self.checker.toggled.connect(self._checker)
        self.size = QLabel("")
        self.size.setStyleSheet("color: #8d8d8d")
        self.res = QSlider(Qt.Horizontal, minimum=10, maximum=50, value=10,
                           toolTip="resolution: the panels this many times larger, the text "
                                   "as set — more room for the data")
        self.res.setFixedWidth(90)
        self.res_label = QLabel("1.0×")
        self.res.valueChanged.connect(self._res)
        self.res_export = QCheckBox("export", toolTip="the exports and the copy at this "
                                                      "resolution too")
        top = QHBoxLayout()
        for text, fn in (("Fit", self.view.fit), ("100 %", self.view.actual_size)):
            b = QToolButton(text=text)
            b.clicked.connect(fn)
            top.addWidget(b)
        top.addWidget(self.zoom)
        top.addWidget(self.checker)
        top.addSpacing(12)
        top.addWidget(QLabel("res"))
        top.addWidget(self.res)
        top.addWidget(self.res_label)
        top.addWidget(self.res_export)
        top.addStretch()
        top.addWidget(self.size)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(top)
        rv.addWidget(self.view, 1)
        self.schema = Schematic()
        self.schema.picked.connect(lambda i: self.items.setCurrentRow(i + 1))
        self.schema.moved.connect(self._move_to)
        self.schema.legend.connect(self._legend_to)
        self.schema.addAction(QAction(self.schema, shortcut=QKeySequence.Delete,
                                      triggered=self.remove, shortcutContext=Qt.WidgetShortcut))
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        cap = QLabel("Layout — click to select; drag a panel onto another's place, the legend "
                     "to a side or into the grid", wordWrap=True)
        cap.setStyleSheet("color: #8d8d8d")
        mv.addWidget(cap)
        mv.addWidget(self.schema, 1)
        split = QSplitter()
        for w in (side, mid, right):
            split.addWidget(w)
        split.setSizes([340, 330, 760])
        QVBoxLayout(self).addWidget(split)

    # -- the figure's settings
    def fig_dict(self) -> dict:
        return plots.migrate(self.win.exp.figure)

    def panels(self) -> list[dict]:
        return plots.panels(self.win.exp)

    def _own_panels(self) -> list[dict]:
        """The panels as the figure's own list (the automatic one becomes it)."""
        f = self.fig_dict()
        f["panels"] = self.panels()
        return f["panels"]

    def _snap(self, key):
        """Undo point, one per run of edits of the same option."""
        k, t = self._snap_key
        if k != key or time.monotonic() - t > 2:
            self.win.snap()
        self._snap_key = (key, time.monotonic())

    def _changed(self):
        self.win.set_dirty()
        self.timer.start()

    # -- refresh
    def refresh(self):
        items = self.panels()
        self.sel = min(self.sel, len(items) - 1)
        self.items.blockSignals(True)
        self.items.clear()
        first = QListWidgetItem(FIGURE)
        first.setFlags(first.flags() & ~Qt.ItemIsDragEnabled)
        self.items.addItem(first)
        for p in items:
            self.items.addItem(QListWidgetItem(self._describe(p)))
        self.items.setCurrentRow(self.sel + 1)
        self.items.blockSignals(False)
        self.build_options()
        self.render()

    def _describe(self, p) -> str:
        exp = self.win.exp
        if p.get("kind") == "legend":
            return f"▤  Legend — {dict((v, k) for k, v in plots.SPEC['legend']['choices'])[plots.options(exp)['legend']]}"
        kind = dict(plots.KINDS).get(p.get("kind"), p.get("kind"))
        ch = p.get("x") or (exp.marker if p.get("kind") != "dot" else "FSC-A")
        what = exp.name("channel", ch) + (f" × {exp.name('channel', p.get('y') or 'SSC-A')}"
                                          if p.get("kind") == "dot" else "")
        mark = " •" if p.get("opts") else ""
        return f"{kind} · {exp.name('group', p.get('group', ''))} · {what}{mark}"

    def _selected(self, row):
        self.sel = row - 1
        self.build_options()
        self._frame()
        self.schema.sel = self.sel
        self.schema.update()

    def _move_to(self, i, j):
        """Item *i* to item *j*'s place (j and those after it shift by one)."""
        own = self._own_panels()
        self._snap("order")
        own.insert(j, own.pop(i))
        self.sel = j
        self._changed()
        self.refresh()

    def _legend_to(self, place, j):
        self._snap("legend")
        self.fig_dict().setdefault("options", {})["legend"] = place
        own = self._own_panels()
        li = next(k for k, p in enumerate(own) if p.get("kind") == "legend")
        if j >= 0:
            own.insert(j, own.pop(li))
            li = j
        self.sel = li
        self._changed()
        self.refresh()

    def _box_text(self, p) -> str:
        exp = self.win.exp
        if p.get("kind") == "legend":
            return "Legend"
        ch = p.get("x") or (exp.marker if p.get("kind") != "dot" else "FSC-A")
        what = exp.name("channel", ch) + (f" × {exp.name('channel', p.get('y') or 'SSC-A')}"
                                          if p.get("kind") == "dot" else "")
        return (f"{dict(plots.KINDS).get(p.get('kind'), p.get('kind'))}\n"
                f"{p.get('title') or exp.name('group', p.get('group', ''))}\n{what}")

    def _res(self, v):
        self.res_label.setText(f"{v / 10:.1f}×")
        self.timer.start()

    def _scaled(self, export=False) -> dict:
        """The sizes times the resolution (on screen; exports when ticked)."""
        k = self.res.value() / 10
        if k == 1 or (export and not self.res_export.isChecked()):
            return {}
        o = plots.options(self.win.exp)
        return {key: o[key] * k for key in ("panel_w", "panel_h", "max_w")}

    def _moved(self):
        """The list as the drag left it: the figure's line first, the items in order."""
        old = self.panels()
        texts = [self.items.item(i).text() for i in range(self.items.count())]
        if texts and texts[0] != FIGURE:
            self.refresh()
            return
        desc = [self._describe(p) for p in old]
        order, used = [], set()
        for t in texts[1:]:
            i = next((k for k, d in enumerate(desc) if d == t and k not in used), None)
            if i is None:
                self.refresh()
                return
            used.add(i)
            order.append(old[i])
        self._snap("order")
        self.fig_dict()["panels"] = order
        self.sel = self.items.currentRow() - 1
        self._changed()
        self.refresh()

    def _clicked(self, fx, fy):
        for i, (x0, y0, x1, y1) in getattr(self.fig, "quickflow_cells", []):
            if x0 <= fx <= x1 and y0 <= fy <= y1:
                self.items.setCurrentRow(i + 1)
                return
        self.items.setCurrentRow(0)

    def _frame(self):
        cells = dict(getattr(self.fig, "quickflow_cells", []))
        self.view.select(cells.get(self.sel))

    # -- the options
    def build_options(self):
        lay = self.opt_layout
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)                  # off screen now, not at the next loop
                w.deleteLater()
        exp = self.win.exp
        items = self.panels()
        p = items[self.sel] if 0 <= self.sel < len(items) else None
        visible = set(self.win.opts.get("figure_options") or
                      [o["key"] for o in plots.OPTIONS if o["shown"]])
        if p is not None and p.get("kind") == "legend":
            box = QGroupBox("Legend")
            f = QFormLayout(box)
            for key in plots.LEGEND_KEYS:
                f.addRow(plots.SPEC[key]["label"], self._widget(key, None))
            lay.addWidget(box)
            lay.addStretch()
            guard_wheel(self.opt_box)
            return
        if p is not None:
            lay.addWidget(self._panel_box(p))
        sections = {}
        for spec in plots.OPTIONS:
            if spec["key"] not in visible or (p is not None and spec["scope"] != "both"):
                continue
            if spec["section"] not in sections:
                box = QGroupBox(spec["section"] + ("" if p is None else " — this panel"))
                sections[spec["section"]] = QFormLayout(box)
                lay.addWidget(box)
            label = QLabel(spec["label"])
            if p is not None and spec["key"] in p.get("opts", {}):
                label.setText(f"<b>{spec['label']}</b>")
                label.setToolTip("this panel's own: ↺ for the figure's")
            sections[spec["section"]].addRow(label, self._widget(spec["key"], p))
        if p is None:
            lay.addWidget(self._series_box())
        lay.addStretch()
        guard_wheel(self.opt_box)

    def _value(self, key, p):
        o = plots.options(self.win.exp)
        if p is not None and key in p.get("opts", {}):
            return p["opts"][key]
        return o[key]

    def _widget(self, key, p):
        spec = plots.SPEC[key]
        val = self._value(key, p)
        kind = spec["kind"]
        if kind == "check":
            w = QCheckBox()
            w.setChecked(bool(val))
            w.toggled.connect(lambda v: self._set(key, v, p))
        elif kind == "choice":
            w = QComboBox()
            for label, v in spec["choices"]:
                w.addItem(label, v)
            w.setCurrentIndex(max(0, w.findData(val)))
            w.currentIndexChanged.connect(lambda _: self._set(key, w.currentData(), p))
        elif kind == "float":
            w = QDoubleSpinBox(decimals=2 if spec.get("step", 1) < 0.1 else 1,
                               singleStep=spec.get("step", 1), suffix=spec.get("suffix", ""))
            w.setRange(spec["lo"], spec["hi"])
            w.setValue(float(val))
            w.valueChanged.connect(lambda v: self._set(key, float(v), p))
        elif kind == "int":
            w = QSpinBox(suffix=spec.get("suffix", ""))
            w.setRange(spec["lo"], spec["hi"])
            w.setValue(int(val))
            w.valueChanged.connect(lambda v: self._set(key, int(v), p))
        else:
            w = QLineEdit(str(val))
            w.editingFinished.connect(lambda: self._set(key, w.text(), p))
        if spec.get("tip"):
            w.setToolTip(spec["tip"])
        return w

    def _set(self, key, val, p):
        self._snap(key)
        if p is None or plots.SPEC[key]["scope"] == "fig":
            self.fig_dict().setdefault("options", {})[key] = val
            if key == "legend":
                self.refresh()
                return
        else:
            own = self._own_panels()
            i = self.sel
            own[i].setdefault("opts", {})[key] = val
            it = self.items.item(i + 1)
            if it is not None:
                it.setText(self._describe(own[i]))
        self._changed()

    def _panel_box(self, p) -> QGroupBox:
        exp = self.win.exp
        box = QGroupBox("Panel")
        f = QFormLayout(box)
        kind = QComboBox()
        for v, label in plots.KINDS:
            kind.addItem(label, v)
        kind.setCurrentIndex(max(0, kind.findData(p.get("kind", "histogram"))))
        kind.currentIndexChanged.connect(lambda _: self._panel_set("kind", kind.currentData()))
        f.addRow("shows", kind)
        grp = QComboBox()
        for g in exp.groups():
            grp.addItem(exp.name("group", g), g)
        grp.setCurrentIndex(max(0, grp.findData(p.get("group"))))
        grp.currentIndexChanged.connect(lambda _: self._panel_set("group", grp.currentData()))
        f.addRow("group", grp)
        chans = exp.shown_channels()

        def chan(key, default):
            c = QComboBox()
            for ch in chans:
                c.addItem(exp.name("channel", ch), ch)
            c.setCurrentIndex(max(0, c.findData(p.get(key) or default)))
            c.currentIndexChanged.connect(lambda _: self._panel_set(key, c.currentData()))
            return c

        dot = p.get("kind") == "dot"
        f.addRow("x" if dot else "channel", chan("x", "FSC-A" if dot else exp.marker))
        if dot:
            f.addRow("y", chan("y", "SSC-A"))
        pop = QComboBox(toolTip="dot plot: whose events; histograms, values: the population "
                                "measured")
        pop.addItem("events of: all events" if dot else
                    f"the main one ({exp.main_population(p.get('group', ''))})", "")
        for g in exp.gates.get(p.get("group", ""), []):
            pop.addItem(exp.name("population", g.name), g.name)
        pop.setCurrentIndex(max(0, pop.findData(p.get("population", ""))))
        pop.currentIndexChanged.connect(lambda _: self._panel_set("population", pop.currentData()))
        f.addRow("population", pop)
        ss = QListWidget(toolTip="the samples shown; none ticked: the group's plotted ones")
        want = set(p.get("samples") or [])
        for s in exp.in_group(p.get("group", "")):
            it = QListWidgetItem(f"{exp.name('label', s.label)} — {exp.name('sample', s.name)}")
            it.setData(Qt.UserRole, s.name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (s.name in want if want else s.plot) else Qt.Unchecked)
            ss.addItem(it)
        ss.setMaximumHeight(min(160, 22 * max(1, ss.count()) + 6))

        def picked(_):
            names = [ss.item(i).data(Qt.UserRole) for i in range(ss.count())
                     if ss.item(i).checkState() == Qt.Checked]
            plotted = [s.name for s in exp.in_group(p.get("group", "")) if s.plot]
            self._panel_set("samples", [] if names == plotted else names, rebuild=False)

        ss.itemChanged.connect(picked)
        f.addRow("samples", ss)
        title = QLineEdit(p.get("title", ""), placeholderText=exp.name("group", p.get("group", "")))
        title.editingFinished.connect(lambda: self._panel_set("title", title.text(), rebuild=False))
        f.addRow("title", title)
        return box

    def _panel_set(self, key, val, rebuild=True):
        own = self._own_panels()
        p = own[self.sel]
        if p.get(key) == val:
            return
        self._snap(f"panel {key}")
        p[key] = val
        if key in ("kind", "group"):
            p["x"] = p["y"] = p["population"] = ""
            p["samples"] = []
        it = self.items.item(self.sel + 1)
        if it is not None:
            it.setText(self._describe(p))
        if rebuild:
            self.build_options()
        self._changed()

    def _series_box(self) -> QGroupBox:
        exp = self.win.exp
        box = QGroupBox("Series — each label, in every panel")
        f = QFormLayout(box)
        o = plots.options(exp)
        styles = plots.series_style(exp, o)
        custom = self.fig_dict().setdefault("series", {})
        for lab in exp.labels():
            if not any(s.label == lab and s.plot for s in exp.samples):
                continue
            st = styles[lab]
            row = QHBoxLayout()
            col = QToolButton(toolTip="colour (in colour figures)")
            colour = custom.get(lab, {}).get("color") or (st["fill"] or st["edge"])
            col.setStyleSheet(f"background: {colour}; min-width: 28px")
            col.clicked.connect(lambda _=False, lab=lab, c=colour: self._pick_colour(lab, c))
            dash = QComboBox(toolTip="line (dashes)")
            dash.addItem("(automatic)", "")
            for name in plots.DASHES:
                dash.addItem(name, name)
            dash.setCurrentIndex(max(0, dash.findData(custom.get(lab, {}).get("dash", ""))))
            dash.currentIndexChanged.connect(
                lambda _, lab=lab, d=dash: self._series_set(lab, "dash", d.currentData() or None))
            fill = QCheckBox("fill")
            fill.setChecked(custom.get(lab, {}).get("fill", True) is not False)
            fill.toggled.connect(lambda v, lab=lab: self._series_set(lab, "fill", None if v else False))
            row.addWidget(col)
            row.addWidget(dash, 1)
            row.addWidget(fill)
            w = QWidget()
            w.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            f.addRow(exp.name("label", lab) + (" (control)" if st["ctrl"] else ""), w)
        return box

    def _pick_colour(self, lab, current):
        c = QColorDialog.getColor(QColor(current), self, f"Colour of {lab}")
        if c.isValid():
            self._series_set(lab, "color", c.name())
            self.build_options()

    def _series_set(self, lab, key, val):
        self._snap(f"series {lab} {key}")
        d = self.fig_dict().setdefault("series", {}).setdefault(lab, {})
        if val is None:
            d.pop(key, None)
        else:
            d[key] = val
        self._changed()

    def _apply_preset(self):
        self._snap("preset")
        self.fig_dict().setdefault("options", {}).update(plots.PRESETS[self.preset.currentText()])
        self._changed()
        self.refresh()

    # -- panels
    def add(self):
        exp = self.win.exp
        if not exp.groups():
            return
        own = self._own_panels()
        cur = own[self.sel] if 0 <= self.sel < len(own) else None
        if cur is not None and cur.get("kind") != "legend":
            new = copy.deepcopy(cur)
        else:
            shown = {p.get("group") for p in own}
            g = next((g for g in exp.groups() if g not in shown), exp.groups()[0])
            new = plots.new_panel(g)
        self._snap("add")
        at = self.sel + 1 if self.sel >= 0 else len(own)
        own.insert(at, new)
        self.sel = at
        self._changed()
        self.refresh()

    def remove(self):
        own = self._own_panels()
        if not (0 <= self.sel < len(own)) or own[self.sel].get("kind") == "legend":
            return
        self._snap("remove")
        del own[self.sel]
        self.sel = min(self.sel, len(own) - 1)
        self._changed()
        self.refresh()

    def reset_panel(self):
        own = self._own_panels()
        if 0 <= self.sel < len(own) and own[self.sel].get("opts"):
            self._snap("reset")
            own[self.sel]["opts"] = {}
            self._changed()
            self.refresh()

    # -- the picture
    def render(self):
        scaled = self._scaled()
        self.fig = plots.figure(self.win.exp, self.fig, style=scaled)
        self.view.set_figure(self.fig)
        self._frame()
        w, h = plots.figure(self.win.exp, draw=False, style=scaled)
        items = self.panels()
        li = next((k for k, p in enumerate(items) if p.get("kind") == "legend"), None)
        self.schema.set_layout(self.fig.quickflow_cells,
                               {k: self._box_text(p) for k, p in enumerate(items)}, (w, h), li,
                               plots.options(self.win.exp)["legend"], self.sel)
        self.size.setText(f"{w:.0f} × {h:.0f} mm")
        self.zoom.setText(f"{self.view.zoom_percent():.0f} %")

    def _checker(self, on):
        self.view.checker = on
        self.view.viewport().update()

    def _write(self, path, style=None):
        fig = plots.figure(self.win.exp, style={**self._scaled(True), **(style or {})})
        clear = plots.options(self.win.exp)["background"] == "none"
        fig.savefig(path, dpi=self.dpi.value(), transparent=clear,
                    facecolor="none" if clear else "white",
                    **({"pil_kwargs": {"compression": "tiff_lzw"}}
                       if str(path).lower().endswith((".tif", ".tiff")) else {}))

    def _ask(self, title, name):
        p, _ = QFileDialog.getSaveFileName(
            self, title, str(Path(self.win.opts.get("last_dir") or Path.home()) / name),
            "PNG (*.png);;TIFF (*.tif);;SVG (*.svg);;PDF (*.pdf)")
        if p:
            self.win.opts["last_dir"] = str(Path(p).parent)
        return p

    def save(self):
        p = self._ask("Save the figure", self.win.stem() + ".png")
        if p:
            self._write(p)
            self.win.log(f"✓ figure saved: {p}")

    def save_both(self):
        p = self._ask("Save colour and black & white", self.win.stem() + ".png")
        if not p:
            return
        q = Path(p)
        for style, tag in (({"bw": False}, "colour"), ({"bw": True}, "bw")):
            out = q.with_name(f"{q.stem}_{tag}{q.suffix or '.png'}")
            self._write(out, style)
            self.win.log(f"✓ figure saved: {out}")

    def copy(self):
        clear = plots.options(self.win.exp)["background"] == "none"
        copy_figure(plots.figure(self.win.exp, style=self._scaled(True)), self.dpi.value(),
                    clear)
        self.win.log("✓ figure copied (paste it into PowerPoint, Word…)")
