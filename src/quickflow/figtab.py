"""The Figure tab: the figure's items on the left (panels and the legend: + to add one,
drag to order them), the options of the figure - or of the selected panel, which then
override the figure's - and the figure itself on the right, as it is exported. Widgets
only: the figure is plots.figure().
"""

from __future__ import annotations

import copy
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSpinBox, QSplitter, QToolButton,
                               QVBoxLayout, QWidget)

from . import plots
from .canvas import FigureView, copy_figure
from .gating import GroupList

FIGURE = "▣  The figure — every panel"


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
        sv.addWidget(self.items, 1)
        sv.addLayout(bar)
        sv.addWidget(scroll, 2)
        sv.addLayout(exp_row)

        self.view = FigureView()
        self.view.clicked.connect(self._clicked)
        self.view.zoomed.connect(lambda _: self.zoom.setText(f"{self.view.zoom_percent():.0f} %"))
        self.view.addAction(QAction(self.view, shortcut=QKeySequence.Copy, triggered=self.copy,
                                    shortcutContext=Qt.WidgetShortcut))
        self.view.setToolTip("Wheel: zoom; drag: move; double-click: fit; click a panel for "
                             "its options; Ctrl+C copies the figure")
        self.zoom = QLabel("")
        self.checker = QCheckBox("checker", toolTip="a checker behind the figure: shows where "
                                                    "it is transparent")
        self.checker.setChecked(True)
        self.checker.toggled.connect(self._checker)
        self.size = QLabel("")
        self.size.setStyleSheet("color: #8d8d8d")
        top = QHBoxLayout()
        for text, fn in (("Fit", self.view.fit), ("100 %", self.view.actual_size)):
            b = QToolButton(text=text)
            b.clicked.connect(fn)
            top.addWidget(b)
        top.addWidget(self.zoom)
        top.addWidget(self.checker)
        top.addStretch()
        top.addWidget(self.size)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(top)
        rv.addWidget(self.view, 1)
        split = QSplitter()
        split.addWidget(side)
        split.addWidget(right)
        split.setSizes([360, 1000])
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
        self.fig = plots.figure(self.win.exp, self.fig)
        self.view.set_figure(self.fig)
        self._frame()
        w, h = plots.figure(self.win.exp, draw=False)
        self.size.setText(f"{w:.0f} × {h:.0f} mm")
        self.zoom.setText(f"{self.view.zoom_percent():.0f} %")

    def _checker(self, on):
        self.view.checker = on
        self.view.viewport().update()

    def _write(self, path, style=None):
        fig = plots.figure(self.win.exp, style=style)
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
        copy_figure(plots.figure(self.win.exp), self.dpi.value(), clear)
        self.win.log("✓ figure copied (paste it into PowerPoint, Word…)")
