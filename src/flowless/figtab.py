"""The Figure tab: the figure's items on the left (panels and the legend: + to add one)
over the options of the figure - or of the selected panel, which then override the
figure's -; in the middle the layout as boxes (click to select, drag to arrange); on the
right the figure itself, as it is exported. Widgets only: the figure is plots.figure().
"""

from __future__ import annotations

import copy
import math
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget)

from . import plots
from .app import guard_wheel
from .canvas import FOCUS, FigureView, copy_figure
from .gating import GroupList

FIGURE = "▣  The figure — every panel"
ACCENT = "#4a9782"
MARK = QColor("#6fb0ff")                   # where a dragged box goes
WARN = QColor("#e34948")                   # ... can't go (over another), too wide


class Num(QDoubleSpinBox):
    """A number to two decimals (0.75 can be typed), shown with no more than it needs
    (1.1, 60.0, 0.75); the arrows step as set."""

    def __init__(self, **kw):
        super().__init__(decimals=2, **kw)

    def textFromValue(self, v):
        t = f"{v:.2f}"
        return t[:-1] if t.endswith("0") else t


class Schematic(QWidget):
    """The figure's layout as boxes, in its proportions (from the render, so they can't
    disagree with it). Click a box to select it (elsewhere: the whole figure), right-click
    for its menu, + adds a panel. Drag a box anywhere on a grid of half panels: its outline
    shows where it lands (red: over another box, not taken); nothing else moves. The legend
    also goes above, below or right of the figure."""

    picked = Signal(int)                 # an index in panels(); -1: the figure
    placed = Signal(int, int, int, str)  # item, x, y (half cells), the legend's place ('': as
    #                                      it was; a place outside the grid: x, y unused)
    add = Signal()
    menu = Signal(int, object)           # item, global position
    M = 26                               # px around the figure: the legend's drop zones

    def __init__(self):
        super().__init__()
        self.items, self.at, self.texts = {}, {}, {}
        self.cell, self.origin, self.size_mm = (60.0, 50.0), (0, 0), (1.0, 1.0)
        self.top, self.next, self.leg_size, self.max_w = 0.0, (0, 0), (2, 2), 0.0
        self.legend_i, self.place, self.sel = None, "bottom", -1
        self.press = self.drag = None
        self.setMinimumSize(180, 160)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_layout(self, fig, texts, legend_i, place, sel, max_w):
        W, H = (v * 25.4 for v in fig.get_size_inches())
        self.size_mm = (W, H)
        self.items = {i: (x0 * W, (1 - y1) * H, (x1 - x0) * W, (y1 - y0) * H)
                      for i, (x0, y0, x1, y1) in getattr(fig, "flowless_cells", [])}
        g = getattr(fig, "flowless_grid", {})
        self.at = dict(g.get("at", {}))
        self.cell, self.origin = g.get("cell", self.cell), g.get("origin", (0, 0))
        self.top, self.next = g.get("top", 0.0), g.get("next", (0, 0))
        self.leg_size, self.max_w = g.get("legend", (2, 2)), max_w
        self.texts, self.legend_i, self.place, self.sel = texts, legend_i, place, sel
        self.update()

    # -- geometry: half cells to mm (the figure's, top-down) to px
    def _half(self, x, y, w, h) -> tuple[float, float, float, float]:
        hw, hh = self.cell[0] / 2, self.cell[1] / 2
        return (x - self.origin[0]) * hw, self.top + (y - self.origin[1]) * hh, w * hw, h * hh

    def _ghost(self) -> tuple[float, float, float, float]:
        """The '+' box: where the next panel goes."""
        return self._half(*self.next, 2, 2)

    def _area(self) -> tuple[float, float, float, float]:
        """mm shown: the figure, half a panel of room left and above, a panel right and
        below, the '+'."""
        W, H = self.size_mm
        (cw, ch), g = self.cell, self._ghost()
        return (-cw / 2, -ch / 2, max(W + cw, g[0] + g[2], self.max_w if W > self.max_w else 0),
                max(H + ch, g[1] + g[3]))

    def _scale(self):
        x0, y0, x1, y1 = self._area()
        m = self.M
        k = min((self.width() - 2 * m) / (x1 - x0), (self.height() - 2 * m - 24) / (y1 - y0))
        return (k, (self.width() - (x1 - x0) * k) / 2 - x0 * k,
                m + max(0.0, (self.height() - 2 * m - 24 - (y1 - y0) * k) / 2) - y0 * k)

    def _px(self, x, y, w, h) -> QRectF:
        k, ox, oy = self._scale()
        return QRectF(ox + x * k, oy + y * k, w * k, h * k)

    def _mm(self, pos) -> tuple[float, float]:
        k, ox, oy = self._scale()
        return (pos.x() - ox) / k, (pos.y() - oy) / k

    def _frame(self) -> QRectF:
        return self._px(0, 0, *self.size_mm)

    def _boxes(self) -> dict[int, QRectF]:
        out = {}
        for i, r in self.items.items():
            q = self._px(*r).adjusted(2, 2, -2, -2)
            if q.height() < 18:                  # a legend band above / below: readable
                if r[1] < self.size_mm[1] / 2:
                    q.setTop(q.bottom() - 18)
                else:
                    q.setBottom(q.top() + 18)
            out[i] = q
        if self.legend_i is not None and self.legend_i not in out:    # in each panel / none
            f = self._frame()
            out[self.legend_i] = QRectF(f.center().x() - 80, f.bottom() + self.M - 4, 160, 20)
        return out

    def _zones(self) -> dict[str, QRectF]:
        """Where the legend goes outside the grid: strips around the room shown, so every
        place of the grid stays a place for it."""
        x0, y0, x1, y1 = self._area()
        a, m = self._px(x0, y0, x1 - x0, y1 - y0), self.M
        return {"top": QRectF(a.left(), a.top() - m, a.width(), m - 3),
                "bottom": QRectF(a.left(), a.bottom() + 3, a.width(), m - 3),
                "right": QRectF(a.right() + 3, a.top(), m - 3, a.height())}

    def _at(self, pos):
        """The item under *pos*, 'add' on the '+', None."""
        hit = next((i for i, r in self._boxes().items() if r.contains(pos)), None)
        if hit is None and self._px(*self._ghost()).adjusted(4, 4, -4, -4).contains(pos):
            return "add"
        return hit

    # -- where a drag goes
    def _size(self, i) -> tuple[int, int]:
        return tuple(self.at[i][2:]) if i in self.at else self.leg_size

    def _target(self, pos):
        """('zone', place) | ('grid', x, y, free), for the item dragged: the half cell its
        top left would take, centred on the pointer; free: over no other box."""
        i = self.drag[0]
        if i == self.legend_i:
            for place, r in self._zones().items():
                if r.contains(pos):
                    return ("zone", place)
        w, h = self._size(i)
        x, y = self._mm(pos)
        gx = max(round(x / (self.cell[0] / 2) - w / 2), -1) + self.origin[0]
        gy = max(round((y - self.top) / (self.cell[1] / 2) - h / 2), -1) + self.origin[1]
        free = not any(plots._overlap((gx, gy, w, h), r) for j, r in self.at.items() if j != i)
        return ("grid", gx, gy, free)

    def _drop(self, to):
        i = self.drag[0]
        if to[0] == "zone":
            self.placed.emit(i, 0, 0, to[1])
        elif to[3]:
            self.placed.emit(i, to[1], to[2], "grid" if i == self.legend_i else "")

    def _mark(self, p, to):
        """The outline where the dragged item would go (red: taken)."""
        p.setBrush(Qt.NoBrush)
        if to[0] == "zone":
            p.setPen(QPen(FOCUS, 2, Qt.DashLine))
            return p.drawRect(self._zones()[to[1]])
        p.setPen(QPen(MARK if to[3] else WARN, 2, Qt.DashLine))
        p.drawRoundedRect(self._px(*self._half(to[1], to[2], *self._size(self.drag[0])))
                          .adjusted(3, 3, -3, -3), 4, 4)

    # -- drawing
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#262626"))
        p.fillRect(self._frame(), QColor("#323232"))
        boxes = self._boxes()
        to = self._target(self.drag[1]) if self.drag else None
        if self.drag and self.drag[0] == self.legend_i:
            p.setPen(QPen(QColor("#8d8d8d"), 1, Qt.DashLine))
            for place, r in self._zones().items():
                p.drawRect(r)
                if place != "right":
                    p.drawText(r, Qt.AlignCenter, "above" if place == "top" else "below")
        font = p.font()
        font.setPointSizeF(8)
        p.setFont(font)
        for i, r in boxes.items():
            leg, on = i == self.legend_i, i == self.sel
            p.setOpacity(0.35 if self.drag and self.drag[0] == i else 1.0)
            p.setBrush(QColor("#2f3d38" if leg else "#3d3d3d"))
            p.setPen(QPen(FOCUS if on else QColor(ACCENT if leg else "#6a6a6a"), 2 if on else 1))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("#e0e0e0"))
            text = self.texts.get(i, "")
            if leg and p.fontMetrics().horizontalAdvance(text) > r.width() - 8:
                text = "▤"                       # a narrow legend
            p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignCenter | Qt.TextWordWrap, text)
        p.setOpacity(1.0)
        if self.size_mm[0] > self.max_w + 0.05:     # too wide: where the width ends
            x = self._px(self.max_w, 0, 0, 0).x()
            p.setPen(QPen(WARN, 1.5, Qt.DashLine))
            f = self._frame()
            p.drawLine(QPointF(x, f.top() - 6), QPointF(x, f.bottom() + 6))
        if self.drag:                            # the grid of half panels
            x0, y0, x1, y1 = self._area()
            hw, hh = self.cell[0] / 2, self.cell[1] / 2
            p.setPen(QPen(QColor("#4a4a4a"), 1, Qt.DotLine))
            for k in range(math.ceil(x0 / hw), math.floor(x1 / hw) + 1):
                a = self._px(k * hw, y0, 0, y1 - y0)
                p.drawLine(a.topLeft(), a.bottomLeft())
            for k in range(math.ceil((y0 - self.top) / hh), math.floor((y1 - self.top) / hh) + 1):
                a = self._px(x0, self.top + k * hh, x1 - x0, 0)
                p.drawLine(a.topLeft(), a.topRight())
        else:
            g = self._px(*self._ghost()).adjusted(6, 6, -6, -6)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(ACCENT), 1, Qt.DashLine))
            p.drawRoundedRect(g, 4, 4)
            f = p.font()
            f.setPointSizeF(16)
            p.setFont(f)
            p.drawText(g, Qt.AlignCenter, "+")
        if self.drag:
            src = boxes[self.drag[0]]
            p.setOpacity(0.45)
            p.setBrush(FOCUS)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(src).translated(self.drag[1] - self.press[1]), 4, 4)
            p.setOpacity(1.0)
        if to:                                   # over the dragged box: always seen
            self._mark(p, to)

    # -- mouse
    def mousePressEvent(self, e):
        self.setFocus()
        hit = self._at(e.position())
        if e.button() == Qt.RightButton:
            if isinstance(hit, int):
                self.picked.emit(hit)
                self.menu.emit(hit, e.globalPosition().toPoint())
            return
        if hit == "add":
            return self.add.emit()
        self.press = (hit, e.position()) if hit is not None else None
        if hit is None:
            self.picked.emit(-1)

    def mouseMoveEvent(self, e):
        if self.press and (self.drag or (e.position() - self.press[1]).manhattanLength() > 6):
            self.drag = (self.press[0], e.position())
            self.update()

    def mouseReleaseEvent(self, e):
        press, self.press = self.press, None
        if self.drag:
            self.drag = (self.drag[0], e.position())
            to = self._target(e.position())
            if to:
                self._drop(to)
            self.drag = None
            self.update()
        elif press:
            self.picked.emit(press[0])

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.drag:
            self.press = self.drag = None
            self.update()
            return
        super().keyPressEvent(e)


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
        self.items = GroupList(toolTip="The figure's items: select one for its options (the "
                                       "first line: the whole figure's). Their places are "
                                       "the boxes' (drag those); the order here only says "
                                       "which panel of a group the summary follows.")
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
        self.schema.placed.connect(self._place)
        self.schema.add.connect(lambda: self.add(end=True))
        self.schema.menu.connect(self._schema_menu)
        self.schema.addAction(QAction(self.schema, shortcut=QKeySequence.Delete,
                                      triggered=self.remove, shortcutContext=Qt.WidgetShortcut))
        self.schema.setToolTip("Click a box to select it; drag it anywhere on the grid of half "
                               "panels (the outline: where it lands, red: taken; the legend "
                               "also above, below or right of the figure); + adds a panel; "
                               "right-click: its menu; Del removes the selected panel")
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        self.bar_box = QWidget()
        self.bar = QGridLayout(self.bar_box)
        self.bar.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(self.bar_box)
        self.wide = QLabel(wordWrap=True)
        self.wide.setStyleSheet(f"color: {WARN.name()}")
        self.wide.hide()
        mv.addWidget(self.wide)
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
        self.build_bar()
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
        return f"{kind} · {exp.title(p.get('group', ''))} · {what}{mark}"

    def _selected(self, row):
        self.sel = row - 1
        self.build_options()
        self._frame()
        self.schema.sel = self.sel
        self.schema.update()

    def _pin(self):
        """Every item of the grid at the place it is drawn ("at"), so that a move or a new
        order moves nothing else."""
        own = self._own_panels()
        for i, v in getattr(self.fig, "flowless_grid", {}).get("at", {}).items():
            if i < len(own) and not own[i].get("at"):
                own[i]["at"] = list(v[:2])

    def _place(self, i, x, y, place):
        """A box dropped: item *i* at (x, y) half cells, the others where they are; the
        legend out of the grid to *place*."""
        self.win.snap()                                   # each drop its own undo
        self._snap_key = (None, 0.0)
        opts = self.fig_dict().setdefault("options", {})
        if place and place != "grid":
            opts["legend"] = place
        else:
            self._pin()
            own = self._own_panels()
            own[i]["at"] = [x, y]
            if place:
                opts["legend"] = "grid"
            placed = [q["at"] for q in own if q.get("at")]
            dx, dy = min(a[0] for a in placed), min(a[1] for a in placed)
            for a in placed:                       # the grid from (0, 0)
                a[0], a[1] = a[0] - dx, a[1] - dy
        self.sel = i
        self._changed()
        self.refresh()

    def _schema_menu(self, i, at):
        own = self.panels()
        m = QMenu(self)
        if own[i].get("kind") == "legend":
            cur = plots.options(self.win.exp)["legend"]
            for label, v in plots.SPEC["legend"]["choices"]:
                a = m.addAction(label)
                a.setCheckable(True)
                a.setChecked(v == cur)
                a.triggered.connect(lambda _=False, v=v: self._set("legend", v, None))
        else:
            m.addAction("Add a copy").triggered.connect(self.add)
            m.addAction("Remove (Del)").triggered.connect(self.remove)
        m.exec(at)

    def build_bar(self):
        """The layout's options over the boxes: panel size, width, columns, legend."""
        while self.bar.count():
            w = self.bar.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for r, c, label, key in ((0, 0, "", "size_of"), (0, 1, "", "panel_w"),
                                 (0, 2, "×", "panel_h"), (0, 4, "columns", "cols"),
                                 (1, 0, "width ≤", "max_w"), (1, 2, "legend", "legend")):
            w = self._widget(key, None)
            if key == "max_w":
                self.max_w_box = w
            if label:
                self.bar.addWidget(QLabel(label), r, c, Qt.AlignRight)
                c += 1
            self.bar.addWidget(w, r, c, 1, 3 if key == "legend" else 1)
        guard_wheel(self.bar_box)

    def _box_text(self, p) -> str:
        exp = self.win.exp
        if p.get("kind") == "legend":
            return "Legend"
        ch = p.get("x") or (exp.marker if p.get("kind") != "dot" else "FSC-A")
        what = exp.name("channel", ch) + (f" × {exp.name('channel', p.get('y') or 'SSC-A')}"
                                          if p.get("kind") == "dot" else "")
        return (f"{dict(plots.KINDS).get(p.get('kind'), p.get('kind'))}\n"
                f"{p.get('title') or exp.title(p.get('group', ''))}\n{what}")

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
        self._pin()                          # the places stay: the order only names the first
        self.fig_dict()["panels"] = order
        self.sel = self.items.currentRow() - 1
        self._changed()
        self.refresh()

    def _clicked(self, fx, fy):
        for i, (x0, y0, x1, y1) in getattr(self.fig, "flowless_cells", []):
            if x0 <= fx <= x1 and y0 <= fy <= y1:
                self.items.setCurrentRow(i + 1)
                return
        self.items.setCurrentRow(0)

    def _frame(self):
        cells = dict(getattr(self.fig, "flowless_cells", []))
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
            if spec["key"] not in visible or spec["bar"] or \
                    spec["key"] in plots.LEGEND_KEYS[2:] or \
                    (p is not None and spec["scope"] != "both"):
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
            w = Num(singleStep=spec.get("step", 1), suffix=spec.get("suffix", ""))
            w.setRange(spec["lo"], spec["hi"])
            w.setValue(float(val))
            w.valueChanged.connect(lambda v: self._set(key, float(v), p))
        elif kind == "int":
            w = QSpinBox(suffix=spec.get("suffix", ""))
            w.setRange(spec["lo"], spec["hi"])
            w.setSpecialValueText(spec.get("zero", ""))
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
        o = plots.options(self.win.exp)
        if key == "size_of" and val != o["size_of"]:     # the figure stays: the sizes now
            L, B, R, T, _ = plots.margins(self.win.exp, o)  # mean the plot's (or the panel's)
            k = 1 if val == "panel" else -1
            self.fig_dict().setdefault("options", {}).update(
                panel_w=round(o["panel_w"] + k * (L + R), 2),
                panel_h=round(o["panel_h"] + k * (T + B), 2))
        if key == "cols":                                  # in rows again, as listed
            for q in self.fig_dict().get("panels") or []:
                q.pop("at", None)
        if p is None or plots.SPEC[key]["scope"] == "fig":
            self.fig_dict().setdefault("options", {})[key] = val
            if key in ("legend", "size_of"):           # size_of: the sizes shown change
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
                                "shown, with the ranges below it - the group's first such "
                                "panel is what the summary table and the report measure")
        grp_ = p.get("group", "")

        def with_ranges(name):
            rs = [x.name for x in exp.gates.get(grp_, [])
                  if x.kind == "range" and x.name in exp.below(grp_, name)]
            return exp.name("population", name) + \
                (f" — with {', '.join(rs)}" if rs and not dot else "")

        pop.addItem("events of: all events" if dot else
                    f"the main one: {with_ranges(exp.main_population(grp_))}", "")
        for g in exp.gates.get(grp_, []):
            pop.addItem(with_ranges(g.name), g.name)
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
        title = QLineEdit(p.get("title", ""), placeholderText=exp.title(p.get("group", "")))
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
        box = QGroupBox("Series — each label, in every panel (one name: one series)")
        f = QFormLayout(box)
        o = plots.options(exp)
        styles = plots.series_style(exp, o)
        custom = self.fig_dict().setdefault("series", {})
        seen = set()
        for lab in exp.labels():               # labels under one name (▤): the first's row
            n = exp.name("label", lab)
            if n in seen or not any(exp.name("label", s.label) == n and s.plot
                                    for s in exp.samples):
                continue
            seen.add(n)
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
    def add(self, end=False):
        """A panel after the selected one, a copy of it; *end* (the layout's +): last, a
        group not shown yet, else a copy of the last panel."""
        exp = self.win.exp
        if not exp.groups():
            return
        own = self._own_panels()
        cur = own[self.sel] if 0 <= self.sel < len(own) and not end else None
        shown = {p.get("group") for p in own}
        last = [p for p in own if p.get("kind") != "legend"]
        if cur is not None and cur.get("kind") != "legend":
            new = copy.deepcopy(cur)
        elif end and last and all(g in shown for g in exp.groups()):
            new = copy.deepcopy(last[-1])
        else:
            new = plots.new_panel(next((g for g in exp.groups() if g not in shown),
                                       exp.groups()[0]))
        new.pop("newrow", None)
        new.pop("at", None)
        self._snap("add")
        at = len(own) if end or self.sel < 0 else self.sel + 1
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
        o = plots.options(self.win.exp)
        self.schema.set_layout(self.fig, {k: self._box_text(p) for k, p in enumerate(items)},
                               li, o["legend"], self.sel, scaled.get("max_w", o["max_w"]))
        self.size.setText(f"{w:.0f} × {h:.0f} mm")
        self.zoom.setText(f"{self.view.zoom_percent():.0f} %")
        wide = self.too_wide()
        self.wide.setText(f"The figure is {w:.0f} mm wide, more than the {wide:.0f} mm set: it "
                          "isn't drawn. Move a panel back left of the red line, or raise the "
                          "width." if wide else "")
        self.wide.setVisible(bool(wide))
        if getattr(self, "max_w_box", None) is not None:
            self.max_w_box.setStyleSheet(f"color: {WARN.name()}" if wide else "")

    def too_wide(self) -> float:
        """The width set (at the resolution shown) when the figure is wider, else 0."""
        if not getattr(self.fig, "flowless_grid", {}).get("wide"):
            return 0.0
        return self._scaled().get("max_w", plots.options(self.win.exp)["max_w"])

    def _refuse(self) -> bool:
        if self.too_wide():
            self.win.log("✗ the figure is wider than the width set: not drawn, not exported "
                         "(Figure: move a panel back, or raise the width)")
            return True
        return False

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
        if self._refuse():
            return
        p = self._ask("Save the figure", self.win.stem() + ".png")
        if p:
            self._write(p)
            self.win.log(f"✓ figure saved: {p}")

    def save_both(self):
        if self._refuse():
            return
        p = self._ask("Save colour and black & white", self.win.stem() + ".png")
        if not p:
            return
        q = Path(p)
        for style, tag in (({"bw": False}, "colour"), ({"bw": True}, "bw")):
            out = q.with_name(f"{q.stem}_{tag}{q.suffix or '.png'}")
            self._write(out, style)
            self.win.log(f"✓ figure saved: {out}")

    def copy(self):
        if self._refuse():
            return
        clear = plots.options(self.win.exp)["background"] == "none"
        copy_figure(plots.figure(self.win.exp, style=self._scaled(True)), self.dpi.value(),
                    clear)
        self.win.log("✓ figure copied (paste it into PowerPoint, Word…)")
