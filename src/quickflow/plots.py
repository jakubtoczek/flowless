"""The figures, in matplotlib only (no Qt): what the window shows is what is exported.

figure()    the experiment's figure: its panels in a grid (a group's histograms, a dot plot,
            the values as bars) and the legend, an item like the panels, sizes in mm.
hist_axes() histograms of one group on an Axes; dot_axes() events as a density with the
            gates; bars_axes() the values.

Options: one set for the figure (OPTIONS, PRESETS); a panel can override the 'both' ones.
Each label keeps one style (colour, dashes) in every panel: series_style().
"""

from __future__ import annotations

import math

import numpy as np
from matplotlib.colors import LinearSegmentedColormap, LogNorm, to_rgba
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

from . import model

# categorical slots, in order (validated palette: adjacent pairs clear CVD ΔE 8 in light
# mode); a label keeps its slot in every panel. The negative control is the grey reference.
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6",
         "#e34948"]
CONTROL = "#8a8984"
DASHES = {"solid": "-", "dashed": (0, (4, 1.6)), "dotted": (0, (1, 1.3)),
          "dash-dot": (0, (6, 1.5, 1, 1.5)), "long dashes": (0, (9, 2.5)),
          "short dashes": (0, (2.5, 2.5)), "dash-dot-dot": (0, (6, 1.5, 1, 1.5, 1, 1.5)),
          "sparse dots": (0, (1, 3))}
DENSITY = LinearSegmentedColormap.from_list(
    "density", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#104281"])
GREYS = LinearSegmentedColormap.from_list("greys", ["#d9d9d9", "#8c8c8c", "#3a3a3a", "#000000"])
INK, MUTED = "#0b0b0b", "#52514e"
PT = 25.4 / 72                                   # mm per point
KINDS = [("histogram", "Histograms"), ("dot", "Dot plot"), ("bars", "Values (bars)")]
Y_LABEL = {"mode": "% of max", "count": "Count", "area": "% of events / channel"}


def _o(key, label, section, kind, default, scope="both", shown=True, bar=False, **kw):
    return dict(key=key, label=label, section=section, kind=kind, default=default,
                scope=scope, shown=shown, bar=bar, **kw)


# every figure option: section, widget, default; scope "fig" = the figure's only, "both" =
# a panel may override it; shown = in the option list unless hidden in Options ▸ Figure;
# bar = set on the layout's bar (over the boxes), not in the list
OPTIONS = [
    _o("bw", "black & white", "Style", "check", False,
       tip="black lines with dashes, the control filled grey: for print"),
    _o("layout", "histograms", "Style", "choice", "overlay",
       choices=[("overlaid", "overlay"), ("offset (one above the other)", "offset")]),
    _o("y", "y axis", "Style", "choice", "mode",
       choices=[("% of max (normalised to mode)", "mode"), ("count", "count"),
                ("% of events (each area 100 %)", "area")],
       tip="% of max: each histogram scaled to its own peak - the usual overlay when the "
           "samples' event numbers differ (the table gives the counts). % of events: each "
           "histogram's area is its population, 100 % - fair when the peaks' widths differ"),
    _o("smooth", "smoothed", "Style", "check", True),
    _o("fill", "filled", "Style", "check", True),
    _o("fill_alpha", "fill opacity", "Style", "float", 0.30, lo=0, hi=1, step=0.05,
       shown=False),
    _o("lw", "line width (data)", "Style", "float", 1.1, lo=0.2, hi=6, step=0.1, suffix=" pt"),
    _o("axis_lw", "line width (axes)", "Style", "float", 0.6, lo=0.1, hi=4, step=0.1,
       suffix=" pt", tip="the axes, their ticks and the range brackets"),
    _o("gates", "range gates", "Style", "check", True),
    _o("gate_lines", "range limits as dotted lines", "Style", "check", True, shown=False),
    _o("values", "value of each sample", "Style", "check", True,
       tip="bars: the value written above each bar"),
    _o("title_pt", "titles", "Text", "float", 9.0, lo=4, hi=40, step=0.5, suffix=" pt"),
    _o("label_pt", "axis labels", "Text", "float", 8.0, lo=4, hi=40, step=0.5, suffix=" pt"),
    _o("xtick_pt", "x tick labels", "Text", "float", 7.0, lo=4, hi=40, step=0.5, suffix=" pt"),
    _o("ytick_pt", "y tick labels", "Text", "float", 7.0, lo=4, hi=40, step=0.5, suffix=" pt"),
    _o("gate_pt", "range labels", "Text", "float", 7.0, lo=4, hi=40, step=0.5, suffix=" pt"),
    _o("legend_pt", "legend", "Text", "float", 7.5, lo=4, hi=40, step=0.5, suffix=" pt",
       scope="fig"),
    _o("neg_suffix", "after the negative control's name", "Text", "text", "", scope="fig",
       shown=False, tip='e.g. " (neg. ctrl)" - or give the label an alias (▤)'),
    _o("x_lo", "x from 10^", "Axes", "int", 0, lo=0, hi=9, shown=False),
    _o("x_hi", "x up to 10^ (0: the scale's top)", "Axes", "int", 0, lo=0, hi=9, shown=False),
    _o("size_of", "the size is the", "Layout", "choice", "panel", scope="fig", bar=True,
       choices=[("panel", "panel"), ("plot", "plot")],
       tip="panel: its place in the grid, the title, ranges and axis labels inside it; "
           "plot: the axes alone, the margins added around. Every plot the same size "
           "either way"),
    _o("panel_w", "panel width", "Layout", "float", 60.0, lo=20, hi=400, step=5, suffix=" mm",
       scope="fig", bar=True),
    _o("panel_h", "panel height", "Layout", "float", 50.0, lo=20, hi=400, step=5,
       suffix=" mm", scope="fig", bar=True),
    _o("max_w", "figure width at most", "Layout", "float", 180.0, lo=40, hi=800, step=5,
       suffix=" mm", scope="fig", bar=True,
       tip="panels go on as many columns as fit, then a new row"),
    _o("cols", "columns (0: as many as fit)", "Layout", "int", 0, lo=0, hi=12, scope="fig",
       bar=True, tip="a row holds at most this many panels"),
    _o("legend", "legend", "Layout", "choice", "bottom", scope="fig", bar=True,
       choices=[("below the figure", "bottom"), ("above the figure", "top"),
                ("right of the figure", "right"), ("in the grid, at its place", "grid"),
                ("in each panel", "panel"), ("none", "none")]),
    _o("legend_join", "in the grid, with", "Legend", "choice", "", scope="fig",
       choices=[("its own place", ""), ("the panel above", "above"),
                ("the panel below", "below"), ("the panel on the left", "left"),
                ("the panel on the right", "right")],
       tip="the legend and that panel share their two places: the plot keeps its size, "
           "centred in the room the legend leaves on its side"),
    _o("legend_cols", "columns (0: as many as fit)", "Legend", "int", 0, lo=0, hi=12,
       scope="fig"),
    _o("legend_rows", "lines (0: as the columns give)", "Legend", "int", 0, lo=0, hi=12,
       scope="fig", tip="the entries on this many lines: sets the columns"),
    _o("legend_h", "across", "Legend", "choice", "left", scope="fig",
       choices=[("left", "left"), ("centred", "center"), ("right", "right")],
       tip="in its place: a grid cell, the band above / below, the column on the right"),
    _o("legend_v", "up / down", "Legend", "choice", "center", scope="fig",
       choices=[("top", "top"), ("centred", "center"), ("bottom", "bottom")]),
    _o("legend_dx", "margin across", "Legend", "float", 5.0, lo=0, hi=100, step=0.5,
       suffix=" mm", scope="fig",
       tip="from the side it is aligned to (left or right); centred: none"),
    _o("legend_dy", "offset down", "Legend", "float", 2.0, lo=-100, hi=100, step=0.5,
       suffix=" mm", scope="fig",
       tip="centred: moved down this much; top / bottom: the margin from that side"),
    _o("legend_space", "line spacing", "Legend", "float", 0.8, lo=0, hi=3, step=0.1,
       scope="fig", tip="between the entries, in font heights (0.5: tight)"),
    _o("background", "background", "Layout", "choice", "white", scope="fig",
       choices=[("white", "white"), ("transparent", "none")]),
]
SPEC = {o["key"]: o for o in OPTIONS}
DEFAULTS = {o["key"]: o["default"] for o in OPTIONS}
LEGEND_KEYS = ["legend", "legend_pt", "legend_join", "legend_cols", "legend_rows", "legend_h",
               "legend_v", "legend_dx", "legend_dy", "legend_space"]
PRESETS = {
    "colour": dict(bw=False, layout="overlay", fill=True, fill_alpha=0.30, lw=1.1, axis_lw=0.6,
                   title_pt=9.0, label_pt=8.0, xtick_pt=7.0, ytick_pt=7.0, gate_pt=7.0,
                   legend_pt=7.5, panel_w=60.0, panel_h=50.0, max_w=180.0),
    "black & white": dict(bw=True, layout="overlay", fill=True, lw=1.0, axis_lw=0.6,
                          title_pt=9.0, label_pt=8.0, xtick_pt=7.0, ytick_pt=7.0, gate_pt=7.0,
                          legend_pt=7.5, panel_w=60.0, panel_h=50.0, max_w=180.0),
    "black & white, offset": dict(bw=True, layout="offset", fill=True, lw=1.0,
                                  panel_w=60.0, panel_h=60.0, max_w=180.0),
    "one column (85 mm)": dict(title_pt=7.5, label_pt=7.0, xtick_pt=6.0, ytick_pt=6.0,
                               gate_pt=6.0, legend_pt=6.5, lw=0.9, axis_lw=0.5, panel_w=42.0,
                               panel_h=36.0, max_w=85.0),
    "large (slides)": dict(title_pt=16.0, label_pt=14.0, xtick_pt=12.0, ytick_pt=12.0,
                           gate_pt=12.0, legend_pt=13.0, lw=2.0, axis_lw=1.2, panel_w=110.0,
                           panel_h=85.0, max_w=330.0),
}


# --- settings ---------------------------------------------------------------------------

def options(exp) -> dict:
    """The figure's options, defaults filled in."""
    fig = migrate(exp.figure)
    return {**DEFAULTS, **{k: v for k, v in fig.get("options", {}).items() if k in DEFAULTS}}


def merged(o: dict, panel: dict) -> dict:
    return {**o, **{k: v for k, v in panel.get("opts", {}).items()
                    if k in SPEC and SPEC[k]["scope"] == "both"}}


def split_ticks(d: dict) -> dict:
    """One tick size (before x and y had their own): both. Changes *d* in place."""
    if "tick_pt" in d:
        v = d.pop("tick_pt")
        d.setdefault("xtick_pt", v)
        d.setdefault("ytick_pt", v)
    return d


def migrate(fig: dict) -> dict:
    """A figure saved by an earlier version: the first's one flat dict of settings as
    options + panels, one tick size as x and y. Changes *fig* in place."""
    split_ticks(fig.get("options", {}))
    for p in fig.get("panels") or []:
        split_ticks(p.get("opts", {}))
    if "style" not in fig and "width_mm" not in fig:
        return fig
    old = {k: fig.pop(k) for k in list(fig) if k not in ("options", "panels", "series")}
    o = fig.setdefault("options", {})
    o.update(bw=old.get("style") == "bw", layout=old.get("layout", "overlay"),
             y=old.get("y", "mode"), smooth=old.get("smooth", True),
             fill=old.get("fill", True), gates=old.get("gates", True),
             legend={"shared": "bottom", "panel": "panel"}.get(old.get("legend"), "none"),
             cols=int(old.get("cols") or 0))
    if old.get("font_pt"):
        o.update(label_pt=old["font_pt"], xtick_pt=old["font_pt"] - 1,
                 ytick_pt=old["font_pt"] - 1,
                 title_pt=old["font_pt"] + 1, legend_pt=old["font_pt"] - 0.5)
    if old.get("groups"):
        fig["panels"] = [new_panel(g) for g in old["groups"]] + [{"kind": "legend"}]
    return fig


def new_panel(group: str, kind: str = "histogram") -> dict:
    return {"kind": kind, "group": group, "x": "", "y": "", "population": "", "samples": [],
            "title": "", "opts": {}}


def panels(exp) -> list[dict]:
    """The figure's items in order: the panels as set, or one histogram panel per group
    with a sample to plot; the legend always among them, once."""
    fig = migrate(exp.figure)
    if fig.get("panels") is not None:
        out = [p for p in fig["panels"] if p.get("kind") == "legend" or
               p.get("group") in exp.groups()]
    else:
        out = [new_panel(g) for g in exp.groups() if any(s.plot for s in exp.in_group(g))]
    legends = [p for p in out if p.get("kind") == "legend"]
    if not legends:
        out.append({"kind": "legend"})
    elif len(legends) > 1:
        out = [p for p in out if p.get("kind") != "legend" or p is legends[0]]
    return out


def measured(exp, group: str) -> str:
    """The population the figure shows for *group* (its first histogram or bars panel's),
    else the group's main one: what the summary table measures."""
    for p in panels(exp):
        if p.get("group") == group and p.get("kind") in ("histogram", "bars"):
            return p.get("population") or exp.main_population(group)
    return exp.main_population(group)


def grid_places(items: list[dict], per_row: int) -> list[tuple[int, int]]:
    """(row, column) of each grid item: left to right, a new row when the row is full or
    the item starts one ("newrow", set by dragging it there)."""
    out, r, c = [], 0, 0
    for p in items:
        if c and (c >= per_row or p.get("newrow")):
            r, c = r + 1, 0
        out.append((r, c))
        c += 1
    return out


def series_style(exp, o: dict) -> dict[str, dict]:
    """label -> {edge, fill, dash, ctrl}: the negative control grey, the others by slot,
    then what the figure's series settings change. Labels shown under one name (▤) are one
    series: the first one's style (and settings) for all."""
    bw = o["bw"]
    custom = migrate(exp.figure).get("series", {})
    out, k, first = {}, 0, {}
    names = list(DASHES)
    for lab in exp.labels():
        n = exp.name("label", lab)
        if n in first:
            out[lab] = out[first[n]]
            continue
        first[n] = lab
        roles = {s.role for s in exp.samples if s.label == lab}
        c = custom.get(lab, {})
        if "negative control" in roles:
            st = {"edge": "#000000" if bw else "#5f5e5a",
                  "fill": "#d4d4d4" if bw else CONTROL, "dash": "-", "ctrl": True}
        else:
            colour = c.get("color") or SLOTS[k % len(SLOTS)]
            st = {"edge": "#000000" if bw else colour, "fill": None if bw else colour,
                  "dash": DASHES[names[k % len(names)]] if bw else "-", "ctrl": False}
            k += 1
        if c.get("dash") in DASHES:
            st["dash"] = DASHES[c["dash"]]
        if c.get("fill") is False:
            st["fill"] = None
        out[lab] = st
    return out


def legend_name(exp, lab: str, o: dict) -> str:
    ctrl = any(s.label == lab and s.role == "negative control" for s in exp.samples)
    return exp.name("label", lab) + (o.get("neg_suffix", "") if ctrl else "")


def _rc():
    return {"axes.linewidth": 0.6, "font.family": ["Arial", "DejaVu Sans"],
            "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.minor.width": 0.4,
            "xtick.major.size": 3, "xtick.minor.size": 1.6, "ytick.major.size": 3,
            "svg.fonttype": "none", "pdf.fonttype": 42}


# --- one panel --------------------------------------------------------------------------

def panel_samples(exp, panel: dict) -> list:
    want = panel.get("samples") or []
    return [s for s in exp.in_group(panel.get("group", ""))
            if (s.name in want if want else s.plot)]


def panel_title(exp, p: dict) -> str:
    """A panel's title: its own, else its group's name, its run's day only when another
    run of it (a group shown under the same name) has a panel too; a bars panel of runs
    pooled: '… · n runs'."""
    if p.get("title"):
        return p["title"]
    g = p.get("group", "")
    pool = exp.pool(g)
    if p.get("kind") == "bars" and len(pool) > 1:
        return f"{exp.name('group', g)} · {len(pool)} runs"
    if len(pool) > 1 and {q.get("group") for q in panels(exp)} & (set(pool) - {g}):
        return exp.title(g)
    return exp.name("group", g)


def hist_axes(ax, exp, panel: dict, o: dict, styles: dict, only=None) -> None:
    """Histograms of the panel's group (its samples, or *only*) on the panel's channel
    (the marker), its population (the main one); the range gates below it drawn above the
    axes (the figure leaves room: range_space)."""
    group = panel.get("group", "")
    ch = panel.get("x") or exp.marker
    pop = panel.get("population") or exp.main_population(group)
    curves, top = [], 0.0
    ss = only if only is not None else panel_samples(exp, panel)
    for s in ss:
        if ch not in s.fcs.data:
            continue
        m = exp.masks(s).get(pop)
        if m is None:
            continue
        top = max(top, s.fcs.range(ch) or s.fcs.data[ch].max())
        x, h = model.histogram(s.fcs.data[ch][m], top or 1e7, smooth=o["smooth"])
        if o["y"] == "mode" and h.max():
            h = 100 * h / h.max()
        elif o["y"] == "area" and h.sum():
            h = 100 * h / h.sum()
        curves.append((s, x, h))
    title = panel_title(exp, panel)
    if not curves:
        ax.set_axis_off()
        ax.text(0.5, 0.5, f"{title}\nnothing to plot", ha="center", va="center",
                transform=ax.transAxes, color=MUTED, fontsize=o["label_pt"])
        return
    bw = o["bw"]
    peak = max(h.max() for _, _, h in curves) or 1
    step = 1.02 * peak if o["layout"] == "offset" else 0.0   # no trace crosses the next
    # draw order: controls at the back, then table order; offset: first at the bottom
    order = sorted(curves, key=lambda c: not styles.get(c[0].label, {}).get("ctrl"))
    for i, (s, x, h) in enumerate(order):
        sty = styles.get(s.label) or {"edge": INK, "fill": None, "dash": "-", "ctrl": False}
        base = i * step
        if o["fill"] and sty["fill"]:
            ax.fill_between(x, base, base + h, color=sty["fill"],
                            alpha=1.0 if bw else o["fill_alpha"], lw=0, zorder=2 + i)
        ax.plot(x, base + h, color=sty["edge"], ls=sty["dash"], lw=o["lw"], zorder=3 + i,
                solid_capstyle="round", label=legend_name(exp, s.label, o))
        if step:
            ax.text(10 ** (o["x_lo"] + 0.15), base + 0.08 * peak, exp.name("label", s.label),
                    fontsize=o["ytick_pt"], color=INK, va="bottom", ha="left", zorder=20)
    x0, x1 = _span(exp, ch, ss, o)
    ax.set_xscale("log")
    ax.set_xlim(x0, x1)
    ax.set_ylim(0, (len(order) - 1) * step + peak * 1.04)
    above = 0.0
    if o["gates"]:
        above = _ranges(ax, exp, model_ranges(
            exp, group, pop, ch, only[0] if only is not None and len(only) == 1 else None),
            o, x0, x1)
    w_pt = ax.get_position().width * ax.figure.get_figwidth() * 72
    ax.xaxis.set_major_locator(LogLocator(base=10, numticks=max(3, min(12, int(
        w_pt / (o["xtick_pt"] * 2.3)) + 1))))         # '10⁶' takes about 2 em
    ax.xaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10), numticks=12))
    ax.xaxis.set_minor_formatter(NullFormatter())
    if o["y"] == "mode" and not step:
        ax.set_yticks([0, 25, 50, 75, 100])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if step:
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
    _tick_sizes(ax, o)
    ax.set_xlabel(exp.name("channel", ch), fontsize=o["label_pt"])
    ax.set_ylabel(Y_LABEL.get(o["y"], "Count") + (" (offset)" if step else ""),
                  fontsize=o["label_pt"])
    _title(ax, title, o, above)
    _axis_lines(ax, o)
    if o["legend"] == "panel":
        ax.legend(frameon=False, loc="upper left", fontsize=o["legend_pt"],
                  handlelength=2.2, borderaxespad=0.2, labelspacing=o["legend_space"])


def _span(exp, ch, ss, o) -> tuple[float, float]:
    """A histogram's x range: 10^x_lo (else 1) to 10^x_hi (else the files' top)."""
    top = max((s.fcs.range(ch) or s.fcs.data[ch].max() for s in ss if ch in s.fcs.data),
              default=0)
    return (10 ** o["x_lo"] if o["x_lo"] else 1), (10 ** o["x_hi"] if o["x_hi"] else top or 1e7)


def _tick_sizes(ax, o: dict) -> None:
    ax.tick_params(axis="x", labelsize=o["xtick_pt"])
    ax.tick_params(axis="y", labelsize=o["ytick_pt"])


def _axis_lines(ax, o: dict) -> None:
    w = o["axis_lw"]
    for sp in ax.spines.values():
        sp.set_linewidth(w)
    ax.tick_params(which="major", width=w)
    ax.tick_params(which="minor", width=w * 0.67)


def wrap(title: str, width_pt: float, pt: float) -> str:
    """*title* in lines no wider than *width_pt* at *pt* (Arial, about 0.55 em a
    character): first at ' · ' (a name · its run), then at spaces."""
    import textwrap

    per = max(6, int(width_pt / (pt * 0.55)))
    out = []
    for part in title.split(" · ") if len(title) > per else [title]:
        if out and len(out[-1]) + 3 + len(part) <= per:
            out[-1] += " · " + part
        else:
            out += textwrap.wrap(part, per, break_on_hyphens=False) or [""]
    return "\n".join(out)


def _room(ax, o: dict) -> float:
    """pt a title may take: the axes' width and a little of the margins."""
    return ax.get_position().width * ax.figure.get_figwidth() * 72 + o["ytick_pt"] * 2


def _title(ax, title: str, o: dict, above: float = 0.0) -> None:
    """The panel's title at its size, on more lines when wider than the panel (the
    figure leaves room for them: _margins), over *above* pt of range labels or the
    figure's "_above" (every title of a figure at one height)."""
    ax.set_title(wrap(title, _room(ax, o), o["title_pt"]), fontsize=o["title_pt"], color=INK,
                 pad=3 + max(above, o.get("_above", 0.0)), linespacing=1.1)


def model_ranges(exp, group, pop, ch, sample=None) -> list:
    """The range gates on *ch* below *pop* (a sample's own versions if *sample*)."""
    below = set(exp.below(group, pop))
    tree = exp.tree(sample) if sample is not None else exp.gates.get(group, [])
    return [g for g in tree if g.kind == "range" and g.x == ch and g.name in below]


def _band(o: dict) -> float:
    """pt a row of range brackets and labels takes."""
    return o["gate_pt"] * 1.35 + 5


def range_space(exp, p: dict, o: dict, w_pt: float) -> float:
    """pt the histogram panel *p*'s range gates take above its axes, *w_pt* wide."""
    if p.get("kind", "histogram") != "histogram" or not o["gates"]:
        return 0.0
    g = p.get("group", "")
    ch = p.get("x") or exp.marker
    ranges = model_ranges(exp, g, p.get("population") or exp.main_population(g), ch)
    if not ranges:
        return 0.0
    return _place(exp, ranges, o, *_span(exp, ch, panel_samples(exp, p), o), w_pt)[1] * _band(o)


def _ranges(ax, exp, gates, o, x0, x1) -> float:
    """Each range as a bracket above the axes, its name over it; ranges that overlap take
    the next row up. Returns the pt they take."""
    fig = ax.figure
    placed, n = _place(exp, gates, o, x0, x1, ax.get_position().width * fig.get_figwidth() * 72)
    if not placed:
        return 0.0
    h_pt = max(ax.get_position().height * fig.get_figheight() * 72, 30)
    tr = ax.get_xaxis_transform()                 # x: data, y: in axes heights
    t = (0.2 * o["gate_pt"] + 1) / h_pt           # a bracket's end, half
    kw = dict(color=INK, lw=o["axis_lw"] * 1.3, zorder=30, clip_on=False, transform=tr)
    for g, lo, hi, r, cx, name in placed:
        y = 1 + (2 + r * _band(o)) / h_pt + t     # row 0: its ends 2 pt over the axes
        ax.plot([lo, hi], [y, y], solid_capstyle="butt", **kw)
        ax.plot([lo, lo], [y - t, y + t], **kw)
        ax.plot([hi, hi], [y - t, y + t], **kw)
        ax.text(cx, y + t * 0.6, name, ha="center", va="bottom", fontsize=o["gate_pt"],
                color=INK, zorder=30, transform=tr)
        if o["gate_lines"]:
            for v in (lo, hi):
                if x0 < v < x1:
                    ax.plot([v, v], [0, y - t], color=MUTED, lw=0.5, ls=(0, (1.5, 1.5)),
                            zorder=1, clip_on=False, transform=tr)
    return n * _band(o)


def _place(exp, gates, o, x0, x1, w_pt) -> tuple[list, int]:
    """([(gate, lo, hi, row, label's centre, name)], rows): a range whose bracket or label
    would overlap another's takes the next row up."""
    L0, L1 = math.log10(x0), math.log10(x1)
    dec_per_pt = (L1 - L0) / max(w_pt, 30)
    rows, placed = [], []          # rows: [(bracket, label)] taken, each (from, to) log10 x
    for g in sorted(gates, key=lambda g: g.lo or 0):
        lo, hi = max(g.lo or x0, x0), min(g.hi or x1, x1)
        if hi <= lo:
            continue
        name = exp.name("population", g.name)
        half = len(name) * o["gate_pt"] * 0.55 / 2 * dec_per_pt
        c = (math.log10(lo) + math.log10(hi)) / 2
        c = min(max(c, L0 + half), L1 - half)                 # the label inside the axes
        gap = o["gate_pt"] * 0.6 * dec_per_pt
        br, lab = (math.log10(lo), math.log10(hi)), (c - half, c + half)
        tol = 1e-3

        def free(taken):           # brackets may touch (medium | high), labels keep a gap
            return all((br[0] >= b[1] - tol or br[1] <= b[0] + tol) and
                       (lab[0] >= t[1] + gap or lab[1] <= t[0] - gap) for b, t in taken)

        r = next((k for k, taken in enumerate(rows) if free(taken)), len(rows))
        if r == len(rows):
            rows.append([])
        rows[r].append((br, lab))
        placed.append((g, lo, hi, r, 10 ** c, name))
    return placed, len(rows)


_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _linear_ticks(axis, top: float) -> str:
    """Ticks in units of 10ⁿ ('1.5' for 1.5e6), and the axis label's '(×10⁶)'."""
    e = max(0, int(math.floor(math.log10(top))) - 1) if top > 0 else 0
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 10 ** e:g}"))
    return f" (×10{str(e).translate(_SUP)})" if e else ""


def dot_axes(ax, exp, samples: list, x: str, y: str, parent: str = "", gates=None,
             o: dict | None = None, title: str = "", edit: str = "") -> None:
    """Events of *samples* (their *parent* population, pooled) on x/y as a density; each
    of *gates* (polygons on x/y) drawn with its % of those events (*edit*: that one's %
    only, an editor draws it)."""
    o = {**DEFAULTS, **(o or {})}
    X, Y, rx, ry, keep = [], [], 0.0, 0.0, []
    for s in samples:
        f = s.fcs
        if x not in f.data or y not in f.data:
            continue
        ms = exp.masks(s)
        base = ms.get(parent or model.ALL, ms[model.ALL])
        X.append(f.data[x][base])
        Y.append(f.data[y][base])
        keep.append((s, ms, base))
        rx, ry = max(rx, f.range(x) or f.data[x].max()), max(ry, f.range(y) or f.data[y].max())
    ax.clear()
    if not X:
        ax.text(0.5, 0.5, "no events", ha="center", va="center", transform=ax.transAxes,
                color=MUTED)
        return
    X, Y = np.concatenate(X), np.concatenate(Y)
    X, Y = np.minimum(X, rx - 1), np.minimum(Y, ry - 1)    # off-scale: on the edge
    h, _, _ = np.histogram2d(X, Y, bins=200, range=[[0, rx], [0, ry]])
    ax.imshow(np.ma.masked_less(h.T, 1), origin="lower", extent=(0, rx, 0, ry),
              aspect="auto", cmap=GREYS if o["bw"] else DENSITY,
              norm=LogNorm(vmin=1, vmax=max(2, h.max())),
              interpolation="nearest", rasterized=True)
    ax.set_xlim(0, rx)
    ax.set_ylim(0, ry)
    sx, sy = _linear_ticks(ax.xaxis, rx), _linear_ticks(ax.yaxis, ry)
    ax.set_xlabel(exp.name("channel", x) + sx, fontsize=o["label_pt"])
    ax.set_ylabel(exp.name("channel", y) + sy, fontsize=o["label_pt"])
    _tick_sizes(ax, o)
    _axis_lines(ax, o)
    if title:
        _title(ax, title, o)
    n = len(X)
    w_pt = max(ax.get_position().width * ax.figure.get_figwidth() * 72, 30)
    h_pt = max(ax.get_position().height * ax.figure.get_figheight() * 72, 30)
    lab_h = 2.9 * o["gate_pt"] / h_pt * ry          # two lines and a gap, in data units
    taken = []                                     # (x0, x1, y0, y1) of the labels so far
    for g in gates or []:
        if g.kind != "polygon" or len(g.vertices) < 3:
            continue
        v = np.asarray(g.vertices + g.vertices[:1], float)
        if g.name != edit:
            ax.plot(v[:, 0], v[:, 1], color=INK, lw=0.9, clip_on=False, zorder=5)
        inside = sum(int((ms[g.name] & base).sum()) for s, ms, base in keep if g.name in ms)
        pct = 100 * inside / n if n else 0
        name = exp.name("population", g.name)
        half = max(len(name), 7) * o["gate_pt"] * 0.55 / 2 / w_pt * rx
        cx = min(max(v[:, 0].mean(), half), rx - half)
        y0 = v[:, 1].max()                         # above the gate, else inside its top
        if y0 + lab_h > ry:
            y0 = v[:, 1].max() - 0.02 * ry - lab_h
        while any(cx - half < b and cx + half > a and y0 < d and y0 + lab_h > c
                  for a, b, c, d in taken):        # over another label: below it
            y0 = min(c for a, b, c, d in taken if cx - half < b and cx + half > a
                     and y0 < d and y0 + lab_h > c) - lab_h
        taken.append((cx - half, cx + half, y0, y0 + lab_h))
        ax.text(cx, y0, f"{name}\n{pct:.1f} %", ha="center", va="bottom",
                fontsize=o["gate_pt"], color=INK, zorder=6)


def bars_axes(ax, exp, panel: dict, o: dict, styles: dict) -> None:
    """The statistic of each of the panel's samples (the marker, the main population) as
    bars on a log axis, the control first. A group with replicates (other groups shown
    under its name: other runs): each label's mean over the runs, ± SD, each run a dot."""
    group = panel.get("group", "")
    ch = panel.get("x") or exp.marker
    pop = panel.get("population") or exp.main_population(group)
    key = model.STATS.get(exp.stat, "gmean")
    ss = sorted(panel_samples(exp, panel), key=lambda s: not styles.get(s.label, {}).get("ctrl"))
    def value(s, p):
        m = exp.masks(s).get(p)
        return model.stats(s.fcs.data[ch][m])[key] if m is not None and ch in s.fcs.data \
            else None

    pool = exp.pool(group)
    runs = [[value(s, pop)] for s in ss]
    if len(pool) > 1:
        for k, s in enumerate(ss):
            for g in pool:
                t = next((x for x in exp.in_group(g) if x.plot and
                          exp.name("label", x.label) == exp.name("label", s.label)), None)
                if g != group and t is not None:
                    runs[k].append(value(t, measured(exp, g)))
    runs = [[v for v in r if v] for r in runs]
    vals = [float(np.mean(r)) if r else None for r in runs]
    title = panel_title(exp, panel)
    if not any(vals):
        ax.set_axis_off()
        ax.text(0.5, 0.5, f"{title}\nnothing to plot", ha="center", va="center",
                transform=ax.transAxes, color=MUTED, fontsize=o["label_pt"])
        return
    bw = o["bw"]
    floor = min([v for v in vals if v] + [x for r in runs for x in r]) / 3
    for i, (s, v) in enumerate(zip(ss, vals)):
        if not v:
            continue
        sty = styles.get(s.label) or {"edge": INK, "fill": None, "dash": "-", "ctrl": False}
        face = sty["fill"] if sty["fill"] else ("white" if bw else sty["edge"])
        ax.bar(i, v - floor, bottom=floor, width=0.7,       # from the axis' floor: log
               color=to_rgba(face, 1.0 if bw or sty["ctrl"] else 0.85),
               edgecolor=sty["edge"], lw=0.7, ls=sty["dash"], zorder=3)
        if len(runs[i]) > 1:                       # replicates: ± SD, each run a dot
            sd = float(np.std(runs[i], ddof=1))
            ax.errorbar(i, v, yerr=[[min(sd, v * 0.95)], [sd]], color=INK, lw=0.8,
                        capsize=2.5, zorder=5)
            ax.plot(i + np.linspace(-0.15, 0.15, len(runs[i])), runs[i], "o", ms=2.6,
                    mfc="white", mec=INK, mew=0.6, zorder=6)
        if o["values"]:
            top = max([v + (float(np.std(runs[i], ddof=1)) if len(runs[i]) > 1 else 0)]
                      + runs[i])
            ax.text(i, top * 1.12, model_num(v), ha="center", va="bottom",
                    fontsize=o["gate_pt"], color=INK, zorder=4)
    ax.set_yscale("log")
    good = [v for v in vals if v] + [x for r in runs for x in r]
    ax.set_ylim(floor, max(good) * (6 if o["values"] else 2))
    ax.set_xticks(range(len(ss)))
    ax.set_xticklabels([exp.name("label", s.label) for s in ss], rotation=35, ha="right",
                       rotation_mode="anchor")
    ax.set_xlim(-0.6, len(ss) - 0.4)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    _tick_sizes(ax, o)
    ax.set_ylabel(f"{exp.stat}, {exp.name('channel', ch)}", fontsize=o["label_pt"])
    _title(ax, title, o)
    _axis_lines(ax, o)


def model_num(v) -> str:
    return f"{v:,.0f}".replace(",", " ") if v >= 100 else f"{v:.3g}"


# --- the figure -------------------------------------------------------------------------

def _margins(o: dict, kind: str, lines: int = 1) -> tuple[float, float, float, float]:
    """(left, bottom, right, top) mm around a panel's axes, from its fonts; *lines*: of its
    title."""
    noy = kind == "histogram" and o["layout"] == "offset"
    left = (o["label_pt"] * 1.3 + 5 if noy else o["ytick_pt"] * 2.4 + o["label_pt"] * 1.3 + 7)
    bottom = o["xtick_pt"] * 1.4 + o["label_pt"] * 1.3 + 6
    if kind == "bars":
        bottom += o["xtick_pt"] * 2.2
    top = o["title_pt"] * (1.45 + 1.1 * (lines - 1)) + 3
    right = o["xtick_pt"] * 1.3 + 2
    return left * PT, bottom * PT, right * PT, top * PT


def margins(exp, o: dict) -> tuple[float, float, float, float, float]:
    """(left, bottom, right, top) mm around every plot, the widest any panel needs (titles,
    range labels, tick labels): every plot the same size; and the pt the range labels take
    over the plots. The size set (*o*: size_of) is the panel's (margins inside) or the
    plot's (margins around)."""
    # ponytail: one set for the whole figure, per row if the spare margin ever matters
    gp = [(p, merged(o, p)) for p in panels(exp) if p.get("kind") != "legend"]
    m = [_margins(po, p.get("kind", "histogram")) for p, po in gp] or [_margins(o, "")]
    L, B, R = (max(x[k] for x in m) for k in (0, 1, 2))
    aw = o["panel_w"] if o["size_of"] == "plot" else max(o["panel_w"] - L - R, 5.0)
    lines = max([wrap(panel_title(exp, p), aw / PT + po["ytick_pt"] * 2,
                      po["title_pt"]).count("\n") + 1 for p, po in gp] or [1])
    above = max([range_space(exp, p, po, aw / PT) for p, po in gp] or [0.0])
    T = max([_margins(po, p.get("kind", "histogram"), lines)[3] for p, po in gp] or [0.0])
    return L, B, R, T + above * PT, above


def _legend_entries(exp, items, styles, o):
    """(handles, names): one entry per name shown (labels under one name: one series)."""
    shown = set()
    for p in items:
        if p.get("kind") in ("histogram", "bars"):
            shown |= {s.label for s in panel_samples(exp, p)}
    out = {}
    for lab in styles:
        if lab in shown:
            out.setdefault(legend_name(exp, lab, o), styles[lab])
    return [_handle(st, o) for st in out.values()], list(out)


def _legend_size(names, o, width_mm: float | None):
    """(columns, width mm, height mm) of a legend of *names*: on the lines set, else in the
    columns set, else as many as fit in *width_mm* (None: one)."""
    em = o["legend_pt"] * PT
    entry = (2.6 + 1.6) * em + max((len(n) for n in names), default=0) * 0.55 * em
    line = o["legend_pt"] * (1.0 + o["legend_space"]) * PT
    dx = o["legend_dx"] if o["legend_h"] != "center" else 0.0
    dy = abs(o["legend_dy"])
    n = max(len(names), 1)
    cols = (math.ceil(n / o["legend_rows"]) if o["legend_rows"] else o["legend_cols"] or
            (max(1, int((width_mm - dx) // entry)) if width_mm else 1))
    cols = max(1, min(cols, n))
    return cols, cols * entry + 2 + dx, math.ceil(n / cols) * line + 3 + dy


def _put_legend(fig, handles, names, rect, o, W, H, ncol=1):
    """The legend in *rect* (x0, y0, x1, y1 mm from the figure's bottom left): across left /
    centred / right (a margin from that side), up / down top / centred / bottom (the offset
    down, or a margin from that side)."""
    x0, y0, x1, y1 = rect
    h, v, dx, dy = o["legend_h"], o["legend_v"], o["legend_dx"], o["legend_dy"]
    x = {"left": x0 + dx, "center": (x0 + x1) / 2, "right": x1 - dx}[h]
    y = {"top": y1 - dy, "center": (y0 + y1) / 2 - dy, "bottom": y0 + dy}[v]
    vv = {"top": "upper", "center": "center", "bottom": "lower"}[v]
    loc = "center" if (h, v) == ("center", "center") else f"{vv} {h}"
    fig.legend(handles, names, loc=loc, bbox_to_anchor=(x / W, y / H), ncol=ncol,
               frameon=False, fontsize=o["legend_pt"], handlelength=2.6, columnspacing=1.6,
               labelspacing=o["legend_space"], borderaxespad=0, borderpad=0)


def figure(exp, fig: Figure | None = None, draw: bool = True, style: dict | None = None):
    """The figure. Each item's place is kept on it (`fig.quickflow_cells`: [(index in
    panels(), (x0, y0, x1, y1) as fractions of the figure)]). draw=False: (width, height)
    in mm only. *style*: options to use over the figure's (a colour / B&W export)."""
    import matplotlib as mpl

    o = {**options(exp), **(style or {})}
    items = panels(exp)
    styles = series_style(exp, o)
    place = o["legend"]
    grid = [(i, p) for i, p in enumerate(items) if p.get("kind") != "legend" or place == "grid"]
    handles, names = _legend_entries(exp, items, styles, o)
    pw, ph = o["panel_w"], o["panel_h"]
    L, B, R, T, above = margins(exp, o)
    plot = o["size_of"] == "plot"
    cw, aw = (pw + L + R, pw) if plot else (pw, max(pw - L - R, 5.0))
    ch, ah = (ph + T + B, ph) if plot else (ph, max(ph - T - B, 5.0))
    gcols, leg_w, _ = _legend_size(names, o, None)
    leg_w = leg_w if place == "right" and names else 0.0
    fit = max(1, int((o["max_w"] - leg_w + 0.05) // cw))     # a switch's rounding: same fit
    per_row = min(o["cols"] or fit, fit)
    places = grid_places([p for _, p in grid], per_row)
    cols = max([c + 1 for _, c in places] or [1])
    rows = max([r + 1 for r, _ in places] or [1])
    W = cols * cw + leg_w
    lcols, _, leg_h = _legend_size(names, o, W) if place in ("top", "bottom") and names \
        else (1, 0, 0.0)
    H = rows * ch + leg_h
    if not draw:
        return W, H
    with mpl.rc_context(_rc()):
        if fig is None:
            fig = Figure(figsize=(W / 25.4, H / 25.4), dpi=100)
        else:
            fig.clear()
            fig.set_size_inches(W / 25.4, H / 25.4)
        clear = o["background"] == "none"
        fig.patch.set_facecolor("none" if clear else "white")
        fig.quickflow_cells = []
        fig.quickflow_grid = {"places": {i: rc for (i, _), rc in zip(grid, places)},
                              "rows": rows, "cols": cols, "per_row": per_row,
                              "cell": (cw, ch),
                              "origin": (0.0, leg_h if place == "top" else 0.0)}
        if not grid and not names:
            fig.text(0.5, 0.5, "Nothing to plot yet: add FCS files (or a panel with +)",
                     ha="center", va="center", color=MUTED, fontsize=8)
            return fig
        y_top = H - (leg_h if place == "top" else 0)
        cell = {i: (c * cw, y_top - (r + 1) * ch, (c + 1) * cw, y_top - r * ch)
                for (i, _), (r, c) in zip(grid, places)}   # mm: x0, y0, x1, y1 (bottom up)
        gcols = _join(cell, grid, places, names, o) or gcols
        for i, p in grid:
            x0, y0, x1, y1 = cell[i]
            fig.quickflow_cells.append((i, (x0 / W, y0 / H, x1 / W, y1 / H)))
            if p.get("kind") == "legend":
                if handles:
                    _put_legend(fig, handles, names, cell[i], o, W, H, gcols)
                continue
            po = {**merged(o, p), "_above": above}          # every title at one height
            ax = fig.add_axes([(x0 + L) / W, (y0 + B) / H, aw / W, ah / H])
            if clear:
                ax.patch.set_alpha(0)
            kind = p.get("kind", "histogram")
            if kind == "dot":
                ss = panel_samples(exp, p) or exp.in_group(p.get("group", ""))
                x, y = p.get("x") or "FSC-A", p.get("y") or "SSC-A"
                parent = p.get("population", "")
                kids = [g for g in exp.children(p.get("group", ""), parent or model.ALL)
                        if g.kind == "polygon" and (g.x, g.y) == (x, y)]
                dot_axes(ax, exp, ss, x, y, parent, kids, po, panel_title(exp, p))
            elif kind == "bars":
                bars_axes(ax, exp, p, po, styles)
            else:
                hist_axes(ax, exp, p, po, styles)
        if names and place in ("top", "bottom", "right"):
            li = next(i for i, p in enumerate(items) if p.get("kind") == "legend")
            if place == "right":
                mm = (W - leg_w, 0, W, H)
                _put_legend(fig, handles, names, mm, o, W, H, gcols)
            else:
                b = 0 if place == "bottom" else H - leg_h
                mm = (0, b, W, b + leg_h)
                _put_legend(fig, handles, names, mm, o, W, H, lcols)
            fig.quickflow_cells.append((li, (mm[0] / W, mm[1] / H, mm[2] / W, mm[3] / H)))
    return fig


def _join(cell, grid, places, names, o) -> int:
    """The legend in the grid sharing a neighbour panel's place (legend_join): the two
    cells one area, the legend on its side of it at its size, the panel's cell centred in
    the rest (the plot keeps its size). Changes *cell* in place; returns the legend's
    columns (above / below a panel: as many as fit), 0 if not joined."""
    d = {"above": (-1, 0), "below": (1, 0), "left": (0, -1), "right": (0, 1)}.get(
        o["legend_join"])
    at = {rc: i for (i, _), rc in zip(grid, places)}
    li = next((i for i, p in grid if p.get("kind") == "legend"), None)
    if d is None or li is None:
        return 0
    r, c = next(rc for (i, _), rc in zip(grid, places) if i == li)
    pi = at.get((r + d[0], c + d[1]))
    if pi is None:
        return 0
    (lx0, ly0, lx1, ly1), (px0, py0, px1, py1) = cell[li], cell[pi]
    x0, y0, x1, y1 = min(lx0, px0), min(ly0, py0), max(lx1, px1), max(ly1, py1)
    cols, lw, lh = _legend_size(names, o, px1 - px0 if d[0] else None)
    if d[0]:                                       # one above the other
        lh = min(lh, (y1 - y0) - (py1 - py0))      # the plot keeps its size
        top = ly1 > py1                            # the legend's side: where it was
        cell[li] = (x0, y1 - lh, x1, y1) if top else (x0, y0, x1, y0 + lh)
        b = (y0 + (y1 - lh - y0 - (py1 - py0)) / 2) if top else \
            (y0 + lh + (y1 - y0 - lh - (py1 - py0)) / 2)
        cell[pi] = (px0, b, px1, b + py1 - py0)
    else:                                          # side by side
        lw = min(lw, (x1 - x0) - (px1 - px0))
        left = lx0 < px0
        cell[li] = (x0, y0, x0 + lw, y1) if left else (x1 - lw, y0, x1, y1)
        a = (x0 + lw + (x1 - x0 - lw - (px1 - px0)) / 2) if left else \
            (x0 + (x1 - lw - x0 - (px1 - px0)) / 2)
        cell[pi] = (a, py0, a + px1 - px0, py1)
    return cols


def _handle(sty, o):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    if sty["fill"] and o["fill"]:
        return Patch(facecolor=sty["fill"] if o["bw"] else to_rgba(sty["fill"], 0.45),
                     edgecolor=sty["edge"], linestyle=sty["dash"], lw=1.0)
    return Line2D([], [], color=sty["edge"], ls=sty["dash"], lw=max(1.0, o["lw"]))
