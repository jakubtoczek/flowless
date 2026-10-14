"""The Gating tab: a group's populations (drag them to order or nest them), the dot plot
and the histogram, each its own plot, and the gate editors on them. Widgets only.
"""

from __future__ import annotations

import copy
import html
import math
from pathlib import Path

import numpy as np
from matplotlib.path import Path as Poly
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QLabel, QListWidget, QMenu,
                               QPushButton, QSplitter, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import model, plots
from .canvas import PlotCanvas

EDIT = "#eb6834"
PICK = 8                        # px: how near a corner or a side a click must be


class PolyEditor:
    """A polygon on *ax*, edited with the mouse: drag a corner to move it, click a side to
    add a corner there, click a corner to select it (Del deletes it), drag inside to move
    the whole gate, click elsewhere to select nothing. Drawing (*drawing*): click the
    corners, then the first one again (or double-click, or Enter); Esc cancels.
    A click outside the plot area lands on its edge: the gate then takes the events piled
    there (off scale). *on_change(vertices)* after each edit; *on_delete()* when a delete
    would leave fewer than 3 corners."""

    def __init__(self, canvas, ax, verts, lims, on_change, on_delete=None, drawing=False,
                 sel=None):
        self.c, self.ax = canvas, ax
        self.v = [list(map(float, p)) for p in verts]
        self.lims = lims
        self.on_change, self.on_delete = on_change, on_delete
        self.drawing = drawing
        self.sel = sel if sel is not None and sel < len(self.v) else None
        self.drag = None
        self.cursor = None
        # in_layout=False: an empty marker sits at pixel (0, 0); in the tight layout it
        # pushed the axes a little further in at every redraw (a splitter dragged: 4.png)
        kw = dict(animated=True, clip_on=False, zorder=50, in_layout=False)
        self.line, = ax.plot([], [], color=EDIT, lw=1.5, **kw)
        self.pts, = ax.plot([], [], "o", ms=5, mfc=EDIT, mec="white", mew=0.8, **kw)
        self.hi, = ax.plot([], [], "o", ms=9, mfc="white", mec=EDIT, mew=1.8, **kw)
        self.bg = None
        self.cids = [canvas.mpl_connect(ev, fn) for ev, fn in (
            ("draw_event", self._on_draw), ("button_press_event", self._press),
            ("motion_notify_event", self._move), ("button_release_event", self._release))]

    def disconnect(self):
        for cid in self.cids:
            self.c.mpl_disconnect(cid)
        for a in (self.line, self.pts, self.hi):
            a.remove()

    # -- drawing on screen
    def _on_draw(self, _):
        self.bg = self.c.copy_from_bbox(self.c.figure.bbox)
        self._blit()

    def _blit(self):
        if self.bg is None:
            return
        v = list(self.v)
        if self.drawing and self.cursor is not None and v:
            v = v + [self.cursor]
        elif not self.drawing and len(v) > 2:
            v = v + v[:1]
        a = np.asarray(v, float).reshape(-1, 2)
        self.line.set_data(a[:, 0], a[:, 1])
        p = np.asarray(self.v, float).reshape(-1, 2)
        self.pts.set_data(p[:, 0], p[:, 1])
        s = self.v[self.sel] if self.sel is not None else None
        self.hi.set_data([s[0]] if s else [], [s[1]] if s else [])
        self.c.restore_region(self.bg)
        for art in (self.line, self.pts, self.hi):
            self.ax.draw_artist(art)
        self.c.blit(self.c.figure.bbox)

    # -- geometry
    def _data(self, e):
        x, y = self.ax.transData.inverted().transform((e.x, e.y))
        x0, x1, y0, y1 = self.lims
        return [min(max(x, x0), x1), min(max(y, y0), y1)]

    def _px(self, p):
        return self.ax.transData.transform(p)

    def _hit(self, e):
        """('corner', i) | ('side', i) after corner i | ('inside',) | None."""
        if not self.v:
            return None
        here = np.array([e.x, e.y])
        px = np.array([self._px(p) for p in self.v])
        d = np.hypot(*(px - here).T)
        if d.min() <= PICK:
            return ("corner", int(d.argmin()))
        if len(self.v) > 2:
            for i in range(len(self.v)):
                a, b = px[i], px[(i + 1) % len(self.v)]
                ab = b - a
                t = np.clip(np.dot(here - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
                if np.hypot(*(a + t * ab - here)) <= PICK:
                    return ("side", i)
            if Poly(px).contains_point(here):
                return ("inside",)
        return None

    # -- mouse
    def _press(self, e):
        if e.button != 1:
            return
        self.c.setFocus()
        p = self._data(e)
        if self.drawing:
            if e.dblclick or (len(self.v) >= 3 and self._hit(e) == ("corner", 0)):
                self.finish()
                return
            self.v.append(p)
            self._blit()
            return
        hit = self._hit(e)
        if hit is None:
            self.sel = None
        elif hit[0] == "corner":
            self.sel = hit[1]
            self.drag = ("corner", hit[1], list(self.v[hit[1]]))
        elif hit[0] == "side":
            self.v.insert(hit[1] + 1, p)
            self.sel = hit[1] + 1
            self.drag = ("corner", self.sel, None)            # a new corner: a change
        else:
            self.sel = None
            self.drag = ("move", p, copy.deepcopy(self.v))
        self._blit()

    def _move(self, e):
        p = self._data(e)
        if self.drawing:
            self.cursor = p
            self._blit()
            return
        if self.drag is None:
            return
        if self.drag[0] == "corner":
            self.v[self.drag[1]] = p
        else:
            dx, dy = p[0] - self.drag[1][0], p[1] - self.drag[1][1]
            self.v = [[a + dx, b + dy] for a, b in self.drag[2]]
        self._blit()

    def _release(self, e):
        d, self.drag = self.drag, None
        if d is None:
            return
        moved = d[0] == "corner" and d[2] != self.v[d[1]] or \
            d[0] == "move" and d[2] != self.v
        if moved:
            self.on_change(self.v)

    # -- keys (from the canvas)
    def key(self, e) -> bool:
        """Del / Backspace, Esc, Enter. True when used."""
        k = e.key()
        if self.drawing:
            if k == Qt.Key_Escape:
                self.on_change(None)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.finish()
                return True
            if k in (Qt.Key_Delete, Qt.Key_Backspace) and self.v:
                self.v.pop()
                self._blit()
                return True
            return False
        if k in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel is not None:
            del self.v[self.sel]
            self.sel = None
            if len(self.v) < 3:
                if self.on_delete:
                    self.on_delete()
            else:
                self.on_change(self.v)
            return True
        if k == Qt.Key_Escape and self.sel is not None:
            self.sel = None
            self._blit()
            return True
        return False

    def finish(self):
        if len(self.v) >= 3:
            self.drawing = False
            self.on_change(self.v)


class RangeEditor:
    """A range on a histogram (log x): drag either limit, or between them to move both.
    A click beyond the plot's right edge opens it to the top of the scale, beyond the left
    one to the bottom."""

    def __init__(self, canvas, ax, lo, hi, lims, on_change):
        self.c, self.ax = canvas, ax
        self.lo, self.hi = lo, hi
        self.lims = lims                  # (x0, x1): the axis' ends
        self.on_change = on_change
        self.drag = None
        kw = dict(animated=True, zorder=40, in_layout=False)
        self.span = ax.axvspan(1, 2, color=EDIT, alpha=0.15, lw=0, **kw)
        self.l1 = ax.axvline(1, color=EDIT, lw=1.6, **kw)
        self.l2 = ax.axvline(1, color=EDIT, lw=1.6, **kw)
        self.bg = None
        self.cids = [canvas.mpl_connect(ev, fn) for ev, fn in (
            ("draw_event", self._on_draw), ("button_press_event", self._press),
            ("motion_notify_event", self._move), ("button_release_event", self._release))]

    def disconnect(self):
        for cid in self.cids:
            self.c.mpl_disconnect(cid)
        for a in (self.span, self.l1, self.l2):
            a.remove()

    def _ends(self):
        x0, x1 = self.lims
        return max(self.lo or x0, x0), min(self.hi or x1, x1)

    def _on_draw(self, _):
        self.bg = self.c.copy_from_bbox(self.c.figure.bbox)
        self._blit()

    def _blit(self):
        if self.bg is None:
            return
        a, b = self._ends()
        self.span.set_x(a)
        self.span.set_width(b - a)
        self.l1.set_xdata([a, a])
        self.l2.set_xdata([b, b])
        self.c.restore_region(self.bg)
        for art in (self.span, self.l1, self.l2):
            self.ax.draw_artist(art)
        self.c.blit(self.c.figure.bbox)

    def _press(self, e):
        if e.button != 1:
            return
        self.c.setFocus()
        a, b = self._ends()
        pa, pb = self.ax.transData.transform((a, 0))[0], self.ax.transData.transform((b, 0))[0]
        left, right = self.ax.bbox.x0, self.ax.bbox.x1
        if e.x > right + 2:
            self.hi = None
            self.on_change(self.lo, self.hi)
            return
        if e.x < left - 2:
            self.lo = None
            self.on_change(self.lo, self.hi)
            return
        if abs(e.x - pa) <= PICK:
            self.drag = ("lo", None)
        elif abs(e.x - pb) <= PICK:
            self.drag = ("hi", None)
        elif pa < e.x < pb:
            self.drag = ("move", (e.x, a, b))

    def _move(self, e):
        if self.drag is None:
            return
        x0, x1 = self.lims
        inv = self.ax.transData.inverted()
        x = min(max(inv.transform((e.x, e.y))[0], x0), x1)
        if self.drag[0] == "lo":
            self.lo = None if x <= x0 * 1.001 else min(x, self._ends()[1] * 0.999)
        elif self.drag[0] == "hi":
            self.hi = None if x >= x1 * 0.999 else max(x, self._ends()[0] * 1.001)
        else:
            px, a, b = self.drag[1]
            f = 10 ** (math.log10(x) - math.log10(inv.transform((px, 0))[0]))
            if a * f >= x0 and b * f <= x1:
                self.lo, self.hi = a * f, b * f
        self._blit()

    def _release(self, e):
        if self.drag is not None:
            self.drag = None
            self.on_change(self.lo, self.hi)


class PopTree(QTreeWidget):
    """The population tree; a drop (to reorder or nest) says so."""
    moved = Signal()

    def dropEvent(self, e):
        super().dropEvent(e)
        self.moved.emit()


class GroupList(QListWidget):
    moved = Signal()

    def dropEvent(self, e):
        super().dropEvent(e)
        self.moved.emit()


class GatingTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.group = ""
        self.pop = model.ALL
        self.editor = None
        self.groups = GroupList(toolTip="Drag to reorder the groups (the figure's and the "
                                        "tables' order)")
        self.groups.setDragDropMode(QAbstractItemView.InternalMove)
        self.groups.currentTextChanged.connect(self._group_changed)
        self.groups.moved.connect(self._groups_moved)
        self.tree = PopTree()
        self.tree.setHeaderLabels(["population", "% parent", "events"])
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.itemSelectionChanged.connect(self._pop_changed)
        self.tree.itemChanged.connect(self._renamed)
        self.tree.moved.connect(self._tree_moved)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.setToolTip(
            "Each population is a gate on the one above it. Drag to reorder or nest them: "
            "the figure and the values use the population in bold — the first gate, and "
            "the first polygon below it (right-click: show another one). F2 or "
            "double-click renames, Del deletes, Ctrl+C copies the table. ◆: some samples "
            "have their own version of the gate.")
        for key, fn in ((QKeySequence.Delete, self.delete), (QKeySequence.Copy, self.copy_tree)):
            self.tree.addAction(QAction(self.tree, shortcut=key, triggered=fn,
                                        shortcutContext=Qt.WidgetShortcut))
        self.view = QComboBox(toolTip="whose events the plots and the counts show")
        self.view.currentIndexChanged.connect(lambda _: self._view_changed())
        self.own = QCheckBox("this sample's own gate",
                             toolTip="ticked: the selected gate is this sample's own "
                                     "version (edits change it only); unticked: the group's "
                                     "gate (edits change every sample without its own)")
        self.own.toggled.connect(self._own_toggled)
        self.cx, self.cy, self.ch = QComboBox(), QComboBox(), QComboBox()
        self.ny = QComboBox(toolTip="count: events per channel; % of max: each histogram to "
                                    "its peak; % of events: each histogram's area is 100 %")
        for label, v in (("count", "count"), ("% of max", "mode"), ("% of events", "area")):
            self.ny.addItem(label, v)
        self.ny.setCurrentIndex(max(0, self.ny.findData(win.opts.get("gating_y", "count"))))
        self.ny.currentIndexChanged.connect(
            lambda _: win.opts.__setitem__("gating_y", self.ny.currentData()))
        for c in (self.cx, self.cy, self.ch, self.ny):
            c.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            c.currentIndexChanged.connect(lambda _: self.draw())
        self.dot = PlotCanvas(on_copy=lambda: win.log("✓ dot plot copied"))
        self.hist = PlotCanvas(on_copy=lambda: win.log("✓ histogram copied"))
        self.ax1 = self.dot.figure.add_subplot()
        self.ax2 = self.hist.figure.add_subplot()
        self.dot.keyPressed.connect(self._dot_key)
        self.hist.keyPressed.connect(self._hist_key)
        self.help = QLabel(wordWrap=True)
        self.help.setStyleSheet("color: #8d8d8d")
        self.warn = QLabel(wordWrap=True, textFormat=Qt.RichText)
        self.warn.setStyleSheet("color: #e0a040")
        self.warn.linkActivated.connect(self._use)
        self.warn.hide()

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Groups"))
        lv.addWidget(self.groups, 1)
        lv.addWidget(QLabel("Populations"))
        lv.addWidget(self.tree, 2)
        lv.addWidget(self.warn)
        h = QHBoxLayout()
        for text, tip, fn in [("Auto gate", "the selected polygon redrawn around the main "
                                            "cluster of the group's events; with all events "
                                            "selected, a new 'cells (auto)' gate beside the "
                                            "others", self.auto),
                              ("+ Polygon", "below the selected population: click its corners "
                                            "on the dot plot, then the first again", self.new_polygon),
                              ("+ Range", "on the histogram's channel, below the selected "
                                          "population (starts above 99 % of the control)",
                               self.new_range)]:
            b = QPushButton(text, toolTip=tip)
            b.clicked.connect(fn)
            h.addWidget(b)
        lv.addLayout(h)
        h = QHBoxLayout()
        b = QPushButton("Delete", toolTip="this population and those below it (Del)")
        b.clicked.connect(self.delete)
        h.addWidget(b)
        cp = QToolButton(text="Copy gates to ▾", popupMode=QToolButton.InstantPopup)
        self.copy_menu = QMenu(cp)
        self.copy_menu.aboutToShow.connect(self._fill_copy_menu)
        cp.setMenu(self.copy_menu)
        h.addWidget(cp)
        b = QPushButton("Export…", toolTip="every group's gates as a Gating-ML 2.0 file (the "
                                           "standard most flow cytometry software reads)")
        b.clicked.connect(self.export)
        h.addWidget(b)
        lv.addLayout(h)
        lv.addWidget(QLabel("events of"))
        lv.addWidget(self.view)
        lv.addWidget(self.own)

        def pane(canvas, combos):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            bar = QHBoxLayout()
            for lab, c in combos:
                bar.addWidget(QLabel(lab))
                bar.addWidget(c)
            bar.addStretch()
            v.addLayout(bar)
            v.addWidget(canvas, 1)
            return w

        plots_split = QSplitter()
        plots_split.addWidget(pane(self.dot, [("x", self.cx), ("y", self.cy)]))
        plots_split.addWidget(pane(self.hist, [("channel", self.ch), ("y", self.ny)]))
        plots_split.setChildrenCollapsible(False)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(plots_split, 1)
        rv.addWidget(self.help)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([280, 1000])
        QVBoxLayout(self).addWidget(split)

    # -- state
    def gates(self) -> list[model.Gate]:
        return self.win.exp.gates.setdefault(self.group, []) if self.group else []

    def gate(self) -> model.Gate | None:
        return next((g for g in self.gates() if g.name == self.pop), None)

    def one(self) -> model.Sample | None:
        """The sample shown alone, if one is."""
        ss = self.win.exp.in_group(self.group)
        i = self.view.currentIndex() - 1
        return ss[i] if 0 <= i < len(ss) else None

    def samples(self) -> list[model.Sample]:
        s = self.one()
        return [s] if s else self.win.exp.in_group(self.group)

    def shown(self, g: model.Gate | None) -> model.Gate | None:
        """The version of *g* the plots show and the edits change."""
        s = self.one()
        if g is not None and s is not None and g.name in s.gates:
            return s.gates[g.name]
        return g

    def refresh(self):
        exp = self.win.exp
        cur = self.group if self.group in exp.groups() else (exp.groups() or [""])[0]
        self.groups.blockSignals(True)
        self.groups.clear()
        self.groups.addItems([g for g in exp.groups()])
        for i, g in enumerate(exp.groups()):
            self.groups.item(i).setToolTip(exp.name("group", g))
        items = self.groups.findItems(cur, Qt.MatchExactly)
        if items:
            self.groups.setCurrentItem(items[0])
        self.groups.blockSignals(False)
        chans = exp.shown_channels()
        for c, want in ((self.cx, "FSC-A"), (self.cy, "SSC-A"), (self.ch, exp.marker)):
            keep = c.currentData()
            c.blockSignals(True)
            c.clear()
            for ch in chans:
                c.addItem(exp.name("channel", ch), ch)
            i = c.findData(keep if keep in chans else want)
            c.setCurrentIndex(max(0, i))
            c.blockSignals(False)
        self._set_group(cur)

    def _group_changed(self, g):
        if g:
            self._set_group(g)

    def _set_group(self, g):
        self.group = g
        self.view.blockSignals(True)
        keep = self.view.currentText()
        self.view.clear()
        self.view.addItem("all samples of the group")
        self.view.addItems([f"{self.win.exp.name('label', s.label)} — {Path(s.path).name}"
                            for s in self.win.exp.in_group(g)])
        self.view.setCurrentIndex(max(0, self.view.findText(keep)))
        self.view.blockSignals(False)
        if self.gate() is None:                    # a new group: its main gate, editable
            self.pop = self.win.exp.main_population(g)
            self._axes_to(self.gate())
        self.fill_tree()
        self.draw()

    def _view_changed(self):
        self.fill_tree()
        self.draw()

    def fill_tree(self):
        exp = self.win.exp
        self.tree.blockSignals(True)
        self.tree.clear()
        counts = {}
        for s in self.samples():
            for k, m in exp.masks(s).items():
                counts[k] = counts.get(k, 0) + int(m.sum())
        root = QTreeWidgetItem([model.ALL, "", str(counts.get(model.ALL, 0))])
        root.setFlags(root.flags() & ~Qt.ItemIsDragEnabled)
        self.tree.addTopLevelItem(root)
        nodes = {model.ALL: root}
        main = plots.measured(exp, self.group)
        chain = set()
        p = main
        while p and p != model.ALL:
            chain.add(p)
            p = next((g.parent for g in self.gates() if g.name == p), "") or ""
        own = {g.name: [s.name for s in exp.in_group(self.group) if g.name in s.gates]
               for g in self.gates()}
        for g in self.gates():
            par = nodes.get(g.parent or model.ALL, root)
            n, np_ = counts.get(g.name, 0), counts.get(g.parent or model.ALL, 0)
            it = QTreeWidgetItem([g.name + (" ◆" if own[g.name] else ""),
                                  f"{100 * n / np_:.1f}" if np_ else "", str(n)])
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            it.setData(0, Qt.UserRole, g.name)
            tip = f"{g.kind} on {g.x}{' × ' + g.y if g.kind == 'polygon' else ''}"
            if g.name in chain:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
                tip += " — the population the figure and the values use" \
                    if g.name == main else " — above the one the figure uses"
            if own[g.name]:
                tip += f"\nown version in: {', '.join(own[g.name])}"
            it.setToolTip(0, tip)
            par.addChild(it)
            nodes[g.name] = it
        self.tree.expandAll()
        for c in range(3):
            self.tree.resizeColumnToContents(c)
        self.tree.setCurrentItem(nodes.get(self.pop, root))
        self.tree.blockSignals(False)
        self._sync_own()
        warn = []
        for top, names in exp.stray_ranges(self.group, main).items():
            them = ", ".join(names)
            warn.append(f"⚠ {html.escape(them)}: under {html.escape(top or model.ALL)}, not "
                        f"under {html.escape(main)} (bold) — the figure and the summary leave "
                        f"{'it' if len(names) == 1 else 'them'} out.")
            if top and top not in chain:
                i = [g.name for g in self.gates()].index(top)
                warn[-1] += (f' <a href="{i}" style="color:#4a9782">Show '
                             f"{html.escape(top)}</a> in the figure instead.")
        self.warn.setText("<br>".join(warn))
        self.warn.setVisible(bool(warn))

    def _use(self, i):
        """Gate *i* (a link's text, or the tree's menu) shown by the group's histogram and
        bars panels: the figure, and the summary that measures what it shows."""
        name = self.gates()[int(i)].name
        exp = self.win.exp
        self.win.snap()
        own = plots.panels(exp)
        exp.figure["panels"] = own
        for p in own:
            if p.get("group") == self.group and p.get("kind") in ("histogram", "bars"):
                p["population"] = name
        self.win.changed()
        self.win.log(f"✓ {self.group}: the figure and the summary show {name} now")

    def _tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        name = it.data(0, Qt.UserRole) if it else None
        if not name:
            return
        m = QMenu(self)
        i = [g.name for g in self.gates()].index(name)
        a = m.addAction(f"Show {name} in the figure (the summary measures it)")
        a.setEnabled(name != plots.measured(self.win.exp, self.group))
        a.triggered.connect(lambda: self._use(i))
        m.addAction("Rename (F2)").triggered.connect(lambda: self.tree.editItem(it, 0))
        m.addAction("Delete (Del)").triggered.connect(self.delete)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _sync_own(self):
        s, g = self.one(), self.gate()
        self.own.blockSignals(True)
        self.own.setEnabled(s is not None and g is not None)
        self.own.setChecked(bool(s is not None and g is not None and g.name in s.gates))
        self.own.blockSignals(False)

    def _pop_changed(self):
        it = self.tree.currentItem()
        self.pop = (it.data(0, Qt.UserRole) or model.ALL) if it else model.ALL
        self._axes_to(self.gate())
        self._sync_own()
        self.draw()

    def _axes_to(self, g):
        """The plots on the selected gate's channels (all events: the first polygon's)."""
        if g is None:
            g = next((x for x in self.gates() if x.kind == "polygon"), None)
        if g is None:
            return
        pairs = ((self.cx, g.x), (self.cy, g.y)) if g.kind == "polygon" else ((self.ch, g.x),)
        for c, ch in pairs:
            i = c.findData(ch)
            if i >= 0:
                c.blockSignals(True)
                c.setCurrentIndex(i)
                c.blockSignals(False)

    def _renamed(self, it, col):
        old = it.data(0, Qt.UserRole)
        new = it.text(0).replace(" ◆", "").strip()
        if not old or not new or new == old or new == model.ALL or \
                any(g.name == new for g in self.gates()):
            self.fill_tree()
            return
        self.win.snap()
        for g in self.gates():
            if g.name == old:
                g.name = new
            if g.parent == old:
                g.parent = new
        for s in self.win.exp.in_group(self.group):
            if old in s.gates:
                s.gates[new] = s.gates.pop(old)
                s.gates[new].name = new
        self.pop = new
        self.win.changed()

    def _tree_moved(self):
        """The tree as the drop left it: each gate's parent, and their order."""
        order, parents = [], {}

        def walk(item, parent):
            for i in range(item.childCount()):
                ch = item.child(i)
                name = ch.data(0, Qt.UserRole)
                if name:
                    order.append(name)
                    parents[name] = parent
                    walk(ch, name)

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            name = top.data(0, Qt.UserRole)
            if name:                                  # dropped beside "All events"
                order.append(name)
                parents[name] = ""
                walk(top, name)
            else:
                walk(top, "")
        by = {g.name: g for g in self.gates()}
        if set(order) != set(by):
            self.fill_tree()
            return
        self.win.snap()
        for n in order:
            by[n].parent = parents[n]
            for s in self.win.exp.in_group(self.group):
                if n in s.gates:
                    s.gates[n].parent = parents[n]
        self.win.exp.gates[self.group] = [by[n] for n in order]
        self.win.changed()

    def _groups_moved(self):
        order = [self.groups.item(i).text() for i in range(self.groups.count())]
        if order == self.win.exp.groups():
            return
        self.win.snap()
        self.win.exp.samples.sort(key=lambda s: order.index(s.group))
        self.win.changed()

    def _own_toggled(self, on):
        s, g = self.one(), self.gate()
        if s is None or g is None:
            return
        self.win.snap()
        if on:
            s.gates[g.name] = copy.deepcopy(g)
            self.win.log(f"✓ {s.name} has its own '{g.name}' gate now: edits change it only")
        else:
            s.gates.pop(g.name, None)
            self.win.log(f"✓ {s.name} uses the group's '{g.name}' gate again")
        self.win.changed()

    def copy_tree(self):
        rows = ["\t".join(["population", "parent", "% parent", "events"])]

        def walk(item, parent):
            for i in range(item.childCount()):
                ch = item.child(i)
                rows.append("\t".join([ch.text(0), parent, ch.text(1), ch.text(2)]))
                walk(ch, ch.text(0))

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            rows.append("\t".join([top.text(0), "", top.text(1), top.text(2)]))
            walk(top, top.text(0))
        QApplication.clipboard().setText("\n".join(rows))
        self.win.log(f"✓ {len(rows) - 1} populations copied")

    # -- drawing
    def _lims(self, x, y):
        ss = self.samples()
        rx = max((s.fcs.range(x) for s in ss if x in s.fcs.data), default=0) or 1e7
        ry = max((s.fcs.range(y) for s in ss if y in s.fcs.data), default=0) or 1e7
        return -0.005 * rx, rx, -0.005 * ry, ry

    def draw(self, sel=None):
        exp = self.win.exp
        if self.editor is not None:
            self.editor.disconnect()
            self.editor = None
        self.ax1.clear()
        self.ax2.clear()
        if not self.group or not exp.samples:
            self.dot.draw_idle()
            self.hist.draw_idle()
            return
        g = self.gate()
        shown = self.shown(g)
        ss = self.samples()
        one = self.one()
        x, y = self.cx.currentData(), self.cy.currentData()
        o = {**plots.options(exp), "legend": "panel", "layout": "overlay", "title_pt": 9,
             "label_pt": 8.5, "tick_pt": 7.5, "legend_pt": 7.5, "gate_pt": 7.5, "fill": False,
             "y": self.ny.currentData() or "count"}
        # the dot plot: the selected polygon's parent on its axes, else the selected
        # population's events with its polygons below
        editing = g is not None and g.kind == "polygon" and (g.x, g.y) == (x, y)
        parent = (g.parent or model.ALL) if editing else \
            ((g.parent or model.ALL) if g is not None and g.kind == "range" else self.pop)
        tree = exp.tree(one) if one else self.gates()
        drawn = [t for t in tree if t.kind == "polygon" and (t.parent or model.ALL) == parent
                 and (t.x, t.y) == (x, y)]
        plots.dot_axes(self.ax1, exp, ss, x, y, "" if parent == model.ALL else parent, drawn,
                       o, edit=g.name if editing else "")
        if editing:
            self.editor = PolyEditor(self.dot, self.ax1, shown.vertices, self._lims(x, y),
                                     self._poly_done, self.delete, sel=sel)
            who = f"{one.name}'s own" if one and g.name in one.gates else "the group's"
            self.help.setText(
                f"{g.name} ({who} gate): drag a corner; click a side to add a corner; click a "
                "corner then Del to delete it; drag inside to move the gate. A click outside "
                "the plot puts the corner on its edge (the off-scale events piled there are "
                "then in).")
        elif g is not None and g.kind == "polygon":
            self.help.setText(f"{g.name} is on {g.x} × {g.y}: set those axes to edit it.")
        else:
            self.help.setText("Select a population to edit its gate; + Polygon draws one below "
                              "the selected population on the dot plot's axes.")
        # the histogram: the selected population (a range: its parent, the range editable)
        ch = self.ch.currentData() or exp.marker
        hp = (g.parent or model.ALL) if g is not None and g.kind == "range" else self.pop
        panel = {"group": self.group, "x": ch, "population": hp}
        styles = plots.series_style(exp, o)
        plots.hist_axes(self.ax2, exp, panel, {**o, "gates": True}, styles, only=ss)
        self.ax2.set_title(f"{exp.name('group', self.group)} › {hp}", fontsize=9)
        if g is not None and g.kind == "range" and g.x == ch:
            top = max((s.fcs.range(ch) for s in ss if ch in s.fcs.data), default=0) or 1e7
            self.editor = RangeEditor(self.hist, self.ax2, shown.lo, shown.hi, (1.0, top),
                                      self._span_done)
            self.help.setText(f"{g.name}: drag its limits, or between them to move both; a "
                              "click beyond the plot's right edge opens it to the top.")
        self.dot.draw_idle()
        self.hist.draw_idle()

    def _target(self) -> model.Gate | None:
        return self.shown(self.gate())

    def _poly_done(self, verts):
        t = self._target()
        if t is None or verts is None or len(verts) < 3:
            return
        v = [list(map(float, p)) for p in verts]
        if v == t.vertices:
            return
        sel = self.editor.sel if self.editor else None
        self.win.snap()
        t.vertices = v
        self.win.changed(redraw_gating=False)
        self.fill_tree()
        self.draw(sel=sel)

    def _span_done(self, lo, hi):
        t = self._target()
        if t is None or (lo is not None and hi is not None and hi <= lo):
            return
        if (t.lo, t.hi) == (lo, hi):
            return
        self.win.snap()
        t.lo, t.hi = (float(lo) if lo is not None else None), (float(hi) if hi is not None
                                                               else None)
        self.win.changed(redraw_gating=False)
        self.fill_tree()
        self.draw()

    def _dot_key(self, e):
        if self.editor is not None and isinstance(self.editor, PolyEditor) and self.editor.key(e):
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.gate() is not None:
            self.delete()

    def _hist_key(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.gate() is not None and \
                self.gate().kind == "range":
            self.delete()

    # -- actions
    def auto(self):
        if not self.group:
            return
        g = self.gate()
        x, y = (g.x, g.y) if g is not None and g.kind == "polygon" else \
            (self.cx.currentData(), self.cy.currentData())
        v = model.auto_gate(self.win.exp.in_group(self.group), x, y)
        if not v:
            self.win.log("✗ auto gate: no cluster found on these axes")
            return
        self.win.snap()
        t = self._target()
        if g is not None and g.kind == "polygon":
            t.vertices = v
        else:
            self.pop = model.add_cells_gate(self.win.exp, self.group, x, y, v)
        self.win.changed()

    def new_polygon(self):
        if not self.group:
            return
        parent = "" if self.pop == model.ALL else self.pop
        names = {x.name for x in self.gates()}
        name = "cells" if not self.gates() else next(f"gate {i}" for i in range(1, 99)
                                                    if f"gate {i}" not in names)
        x, y = self.cx.currentData(), self.cy.currentData()
        if self.editor is not None:
            self.editor.disconnect()
        exp = self.win.exp
        o = {**plots.options(exp), "label_pt": 8.5, "tick_pt": 7.5}
        plots.dot_axes(self.ax1, exp, self.samples(), x, y, parent, [], o)
        self.help.setText(f"Drawing '{name}' below {parent or model.ALL}: click its corners "
                          "(outside the plot: on its edge), then the first one again, a "
                          "double-click or Enter. Esc cancels; Del removes the last corner.")

        def done(verts):
            if verts is None:
                self.draw()
                return
            self.win.snap()
            self.gates().append(model.Gate(name, parent, "polygon", x, y,
                                           [list(map(float, v)) for v in verts]))
            self.pop = name
            self.win.changed()

        self.editor = PolyEditor(self.dot, self.ax1, [], self._lims(x, y), done, drawing=True)
        self.dot.setFocus()
        self.dot.draw_idle()

    def new_range(self):
        exp = self.win.exp
        ch = self.ch.currentData() or exp.marker
        if not self.group or not ch:
            return
        parent = self.pop if self.pop != model.ALL else exp.main_population(self.group)
        parent = "" if parent == model.ALL else parent
        names = {x.name for x in self.gates()}
        name = next(n for n in ["positive"] + [f"range {i}" for i in range(1, 99)]
                    if n not in names)
        lo = 1.0
        c = exp.control(self.group)
        if c is not None and ch in c.fcs.data:
            m = exp.masks(c).get(parent or model.ALL)
            v = c.fcs.data[ch][m] if m is not None else np.empty(0)
            if v.size:
                lo = float(np.percentile(v, 99))
        self.win.snap()
        self.gates().append(model.Gate(name, parent, "range", ch, lo=lo, hi=None))
        self.pop = name
        self.win.changed()
        self.win.log(f"✓ {self.group} › {name}: from {lo:.0f} (99 % of "
                     f"{c.label if c else 'the events'} below it) — drag to adjust")

    def delete(self):
        g = self.gate()
        if g is None:
            return
        self.win.snap()
        gone, todo = set(), [g.name]
        while todo:
            n = todo.pop()
            gone.add(n)
            todo += [x.name for x in self.gates() if x.parent == n]
        self.win.exp.gates[self.group] = [x for x in self.gates() if x.name not in gone]
        for s in self.win.exp.in_group(self.group):
            s.gates = {k: v for k, v in s.gates.items() if k not in gone}
        self.pop = g.parent or model.ALL
        self.win.changed()
        self.win.log(f"✓ deleted {', '.join(sorted(gone))} (Ctrl+Z brings it back)")

    def export(self):
        from .imports import gatingml

        exp = self.win.exp
        if not any(exp.gates.values()):
            self.win.log("✗ no gate to export")
            return
        p, _ = QFileDialog.getSaveFileName(
            self, "Export the gates", str(Path(self.win.opts.get("last_dir") or Path.home())
                                          / (self.win.stem() + "_gates.xml")),
            "Gating-ML 2.0 (*.xml)")
        if not p:
            return
        n = gatingml.write(exp, p)
        exp.gates_file = {"path": str(Path(p).resolve()), "how": "exported",
                          "key": exp.gates_key()}
        self.win.set_dirty()
        own = sum(len(s.gates) for s in exp.samples)
        self.win.log(f"✓ {n} gates exported: {p}" + (f" (not the {own} samples' own versions)"
                                                    if own else ""))

    def _fill_copy_menu(self):
        m = self.copy_menu
        m.clear()
        others = [g for g in self.win.exp.groups() if g != self.group]
        m.addAction("every other group").triggered.connect(lambda: self._copy_to(others))
        m.addSeparator()
        for g in others:
            m.addAction(g).triggered.connect(lambda _=False, g=g: self._copy_to([g]))

    def _copy_to(self, groups):
        if not groups:
            return
        self.win.snap()
        for g in groups:
            self.win.exp.gates[g] = copy.deepcopy(self.gates())
            for s in self.win.exp.in_group(g):
                s.gates = {}
        self.win.changed()
        self.win.log(f"✓ gates of {self.group} copied to {', '.join(groups)}")

