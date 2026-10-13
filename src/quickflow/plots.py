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


def _o(key, label, section, kind, default, scope="both", shown=True, **kw):
    return dict(key=key, label=label, section=section, kind=kind, default=default,
                scope=scope, shown=shown, **kw)


# every figure option: section, widget, default; scope "fig" = the figure's only, "both" =
# a panel may override it; shown = in the option list unless hidden in Options ▸ Figure
OPTIONS = [
    _o("bw", "black & white", "Style", "check", False,
       tip="black lines with dashes, the control filled grey: for print"),
    _o("layout", "histograms", "Style", "choice", "overlay",
       choices=[("overlaid", "overlay"), ("offset (one above the other)", "offset")]),
    _o("y", "y axis", "Style", "choice", "mode",
       choices=[("% of max (normalised to mode)", "mode"), ("count", "count")],
       tip="% of max: each histogram scaled to its own peak - the usual overlay when the "
           "samples' event numbers differ (the table gives the counts)"),
    _o("smooth", "smoothed", "Style", "check", True),
    _o("fill", "filled", "Style", "check", True),
    _o("fill_alpha", "fill opacity", "Style", "float", 0.30, lo=0, hi=1, step=0.05,
       shown=False),
    _o("lw", "line width", "Style", "float", 1.1, lo=0.2, hi=6, step=0.1, suffix=" pt"),
    _o("gates", "range gates", "Style", "check", True),
    _o("gate_lines", "range limits as dotted lines", "Style", "check", True, shown=False),
    _o("values", "value of each sample", "Style", "check", True,
       tip="bars: the value written above each bar"),
    _o("title_pt", "titles", "Text", "float", 9.0, lo=4, hi=40, step=0.5, suffix=" pt"),
    _o("label_pt", "axis labels", "Text", "float", 8.0, lo=4, hi=40, step=0.5, suffix=" pt"),
    _o("tick_pt", "tick labels", "Text", "float", 7.0, lo=4, hi=40, step=0.5, suffix=" pt"),
    _o("gate_pt", "range labels", "Text", "float", 7.0, lo=4, hi=40, step=0.5, suffix=" pt",
       shown=False),
    _o("legend_pt", "legend", "Text", "float", 7.5, lo=4, hi=40, step=0.5, suffix=" pt",
       scope="fig"),
    _o("neg_suffix", "after the negative control's name", "Text", "text", "", scope="fig",
       shown=False, tip='e.g. " (neg. ctrl)" - or give the label an alias (▤)'),
    _o("x_lo", "x from 10^", "Axes", "int", 0, lo=0, hi=9, shown=False),
    _o("x_hi", "x up to 10^ (0: the scale's top)", "Axes", "int", 0, lo=0, hi=9, shown=False),
    _o("panel_w", "panel width", "Layout", "float", 60.0, lo=20, hi=400, step=5, suffix=" mm",
       scope="fig"),
    _o("panel_h", "panel height", "Layout", "float", 50.0, lo=20, hi=400, step=5,
       suffix=" mm", scope="fig"),
    _o("max_w", "figure width at most", "Layout", "float", 180.0, lo=40, hi=800, step=5,
       suffix=" mm", scope="fig",
       tip="panels go on as many columns as fit, then a new row"),
    _o("cols", "columns (0: as many as fit)", "Layout", "int", 0, lo=0, hi=12, scope="fig",
       shown=False),
    _o("legend", "legend", "Layout", "choice", "bottom", scope="fig",
       choices=[("below the figure", "bottom"), ("above the figure", "top"),
                ("right of the figure", "right"), ("in the grid, at its place", "grid"),
                ("in each panel", "panel"), ("none", "none")]),
    _o("legend_cols", "legend columns (0: as many as fit)", "Layout", "int", 0, lo=0, hi=12,
       scope="fig", shown=False),
    _o("background", "background", "Layout", "choice", "white", scope="fig",
       choices=[("white", "white"), ("transparent", "none")]),
]
SPEC = {o["key"]: o for o in OPTIONS}
DEFAULTS = {o["key"]: o["default"] for o in OPTIONS}
LEGEND_KEYS = ["legend", "legend_pt", "legend_cols"]
PRESETS = {
    "colour": dict(bw=False, layout="overlay", fill=True, fill_alpha=0.30, lw=1.1,
                   title_pt=9.0, label_pt=8.0, tick_pt=7.0, gate_pt=7.0, legend_pt=7.5,
                   panel_w=60.0, panel_h=50.0, max_w=180.0),
    "black & white": dict(bw=True, layout="overlay", fill=True, lw=1.0, title_pt=9.0,
                          label_pt=8.0, tick_pt=7.0, gate_pt=7.0, legend_pt=7.5,
                          panel_w=60.0, panel_h=50.0, max_w=180.0),
    "black & white, offset": dict(bw=True, layout="offset", fill=True, lw=1.0,
                                  panel_w=60.0, panel_h=60.0, max_w=180.0),
    "one column (85 mm)": dict(title_pt=7.5, label_pt=7.0, tick_pt=6.0, gate_pt=6.0,
                               legend_pt=6.5, lw=0.9, panel_w=42.0, panel_h=36.0,
                               max_w=85.0),
    "large (slides)": dict(title_pt=16.0, label_pt=14.0, tick_pt=12.0, gate_pt=12.0,
                           legend_pt=13.0, lw=2.0, panel_w=110.0, panel_h=85.0, max_w=330.0),
}


# --- settings ---------------------------------------------------------------------------

def options(exp) -> dict:
    """The figure's options, defaults filled in."""
    fig = migrate(exp.figure)
    return {**DEFAULTS, **{k: v for k, v in fig.get("options", {}).items() if k in DEFAULTS}}


def merged(o: dict, panel: dict) -> dict:
    return {**o, **{k: v for k, v in panel.get("opts", {}).items()
                    if k in SPEC and SPEC[k]["scope"] == "both"}}


def migrate(fig: dict) -> dict:
    """A figure saved by the first version (one flat dict of settings): as options +
    panels. Changes *fig* in place."""
    if "style" not in fig and "width_mm" not in fig:
        return fig
    old = {k: fig.pop(k) for k in list(fig) if k not in ("options", "panels", "series")}
    o = fig.setdefault("options", {})
    o.update(bw=old.get("style") == "bw", layout=old.get("layout", "overlay"),
             y=old.get("y", "mode"), smooth=old.get("smooth", True),
             fill=old.get("fill", True), gates=old.get("gates", True),
             legend={"shared": "bottom", "panel": "panel"}.get(old.get("legend"), "none"))
    if old.get("font_pt"):
        o.update(label_pt=old["font_pt"], tick_pt=old["font_pt"] - 1,
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


def series_style(exp, o: dict) -> dict[str, dict]:
    """label -> {edge, fill, dash, ctrl}: the negative control grey, the others by slot,
    then what the figure's series settings change."""
    bw = o["bw"]
    custom = migrate(exp.figure).get("series", {})
    out, k = {}, 0
    names = list(DASHES)
    for lab in exp.labels():
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


def hist_axes(ax, exp, panel: dict, o: dict, styles: dict, only=None) -> None:
    """Histograms of the panel's group (its samples, or *only*) on the panel's channel
    (the marker), its population (the main one); the range gates below it drawn."""
    group = panel.get("group", "")
    ch = panel.get("x") or exp.marker
    pop = panel.get("population") or exp.main_population(group)
    curves, top = [], 0.0
    for s in (only if only is not None else panel_samples(exp, panel)):
        if ch not in s.fcs.data:
            continue
        m = exp.masks(s).get(pop)
        if m is None:
            continue
        top = max(top, s.fcs.range(ch) or s.fcs.data[ch].max())
        x, h = model.histogram(s.fcs.data[ch][m], top or 1e7, smooth=o["smooth"])
        if o["y"] == "mode" and h.max():
            h = 100 * h / h.max()
        curves.append((s, x, h))
    title = panel.get("title") or exp.name("group", group)
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
                    fontsize=o["tick_pt"], color=INK, va="bottom", ha="left", zorder=20)
    x0 = 10 ** o["x_lo"] if o["x_lo"] else 1
    x1 = 10 ** o["x_hi"] if o["x_hi"] else (top or 1e7)
    ax.set_xscale("log")
    ax.set_xlim(x0, x1)
    data_top = (len(order) - 1) * step + peak * 1.04
    ranges = model_ranges(exp, group, pop, ch,
                          only[0] if only is not None and len(only) == 1 else None)
    ymax = data_top
    if o["gates"] and ranges:
        ymax = _ranges(ax, exp, ranges, o, data_top, x0, x1)
    ax.set_ylim(0, ymax)
    ax.xaxis.set_major_locator(LogLocator(base=10, numticks=12))
    ax.xaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10), numticks=12))
    ax.xaxis.set_minor_formatter(NullFormatter())
    if o["y"] == "mode" and not step:
        ax.set_yticks([0, 25, 50, 75, 100])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_bounds(0, data_top if step else min(ymax, peak * 1.04))
    if step:
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
    ax.tick_params(labelsize=o["tick_pt"])
    ax.set_xlabel(exp.name("channel", ch), fontsize=o["label_pt"])
    ax.set_ylabel(("% of max" if o["y"] == "mode" else "Count") + (" (offset)" if step else ""),
                  fontsize=o["label_pt"])
    ax.set_title(title, fontsize=o["title_pt"], color=INK, pad=3)
    if o["legend"] == "panel":
        ax.legend(frameon=False, loc="upper left", fontsize=o["legend_pt"],
                  handlelength=2.2, borderaxespad=0.2)


def model_ranges(exp, group, pop, ch, sample=None) -> list:
    """The range gates on *ch* below *pop* (a sample's own versions if *sample*)."""
    below = set(exp.below(group, pop))
    tree = exp.tree(sample) if sample is not None else exp.gates.get(group, [])
    return [g for g in tree if g.kind == "range" and g.x == ch and g.name in below]


def _ranges(ax, exp, gates, o, data_top, x0, x1) -> float:
    """Each range as a bracket above the curves, its name over it; ranges that overlap
    take the next row up. Returns the axes' new top."""
    rows, placed = [], []
    for g in sorted(gates, key=lambda g: g.lo or 0):
        lo, hi = max(g.lo or x0, x0), min(g.hi or x1, x1)
        if hi <= lo:
            continue
        r = next((k for k, end in enumerate(rows) if lo >= end * 0.999), len(rows))
        if r < len(rows):
            rows[r] = hi
        else:
            rows.append(hi)
        placed.append((g, lo, hi, r))
    if not placed:
        return data_top
    fig = ax.figure
    ax_h_pt = max(ax.get_position().height * fig.get_figheight() * 72, 30)
    frac = (o["gate_pt"] * 1.35 + 5) / ax_h_pt          # one row, as a fraction of the axes
    top = data_top / max(0.35, 1 - frac * len(rows))
    band = frac * top
    for g, lo, hi, r in placed:
        y = data_top + band * (r + 0.3)
        tick = band * 0.18
        ax.plot([lo, hi], [y, y], color=INK, lw=0.8, solid_capstyle="butt", zorder=30,
                clip_on=False)
        ax.plot([lo, lo], [y - tick, y + tick], color=INK, lw=0.8, zorder=30, clip_on=False)
        ax.plot([hi, hi], [y - tick, y + tick], color=INK, lw=0.8, zorder=30, clip_on=False)
        ax.text(math.sqrt(lo * hi), y + tick * 0.6, exp.name("population", g.name),
                ha="center", va="bottom",
                fontsize=o["gate_pt"], color=INK, zorder=30)
        if o["gate_lines"]:
            for v in (lo, hi):
                if x0 < v < x1:
                    ax.plot([v, v], [0, y - tick], color=MUTED, lw=0.5, ls=(0, (1.5, 1.5)),
                            zorder=1)
    return top


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
    ax.tick_params(labelsize=o["tick_pt"])
    if title:
        ax.set_title(title, fontsize=o["title_pt"], color=INK, pad=3)
    n = len(X)
    for g in gates or []:
        if g.kind != "polygon" or len(g.vertices) < 3:
            continue
        v = np.asarray(g.vertices + g.vertices[:1], float)
        if g.name != edit:
            ax.plot(v[:, 0], v[:, 1], color=INK, lw=0.9, clip_on=False, zorder=5)
        inside = sum(int((ms[g.name] & base).sum()) for s, ms, base in keep if g.name in ms)
        pct = 100 * inside / n if n else 0
        ty = v[:, 1].max()
        hi_edge = ty > 0.85 * ry
        ax.text(v[:, 0].mean(), ty if not hi_edge else ty - 0.02 * ry,
                f"{exp.name('population', g.name)}\n{pct:.1f} %", ha="center",
                va="top" if hi_edge else "bottom", fontsize=o["gate_pt"], color=INK, zorder=6)


def bars_axes(ax, exp, panel: dict, o: dict, styles: dict) -> None:
    """The statistic of each of the panel's samples (the marker, the main population) as
    bars on a log axis, the control first."""
    group = panel.get("group", "")
    ch = panel.get("x") or exp.marker
    pop = panel.get("population") or exp.main_population(group)
    key = model.STATS.get(exp.stat, "gmean")
    ss = sorted(panel_samples(exp, panel), key=lambda s: not styles.get(s.label, {}).get("ctrl"))
    vals = []
    for s in ss:
        m = exp.masks(s).get(pop)
        v = model.stats(s.fcs.data[ch][m])[key] if m is not None and ch in s.fcs.data else None
        vals.append(v)
    title = panel.get("title") or exp.name("group", group)
    if not any(vals):
        ax.set_axis_off()
        ax.text(0.5, 0.5, f"{title}\nnothing to plot", ha="center", va="center",
                transform=ax.transAxes, color=MUTED, fontsize=o["label_pt"])
        return
    bw = o["bw"]
    for i, (s, v) in enumerate(zip(ss, vals)):
        if not v:
            continue
        sty = styles.get(s.label) or {"edge": INK, "fill": None, "dash": "-", "ctrl": False}
        face = sty["fill"] if sty["fill"] else ("white" if bw else sty["edge"])
        ax.bar(i, v, width=0.7, color=to_rgba(face, 1.0 if bw or sty["ctrl"] else 0.85),
               edgecolor=sty["edge"], lw=0.7, ls=sty["dash"], zorder=3)
        if o["values"]:
            ax.text(i, v * 1.12, model_num(v), ha="center", va="bottom", fontsize=o["gate_pt"],
                    color=INK, zorder=4)
    ax.set_yscale("log")
    good = [v for v in vals if v]
    ax.set_ylim(min(good) / 3, max(good) * (6 if o["values"] else 2))
    ax.set_xticks(range(len(ss)))
    ax.set_xticklabels([exp.name("label", s.label) for s in ss], rotation=35, ha="right",
                       rotation_mode="anchor")
    ax.set_xlim(-0.6, len(ss) - 0.4)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=o["tick_pt"])
    ax.set_ylabel(f"{exp.stat}, {exp.name('channel', ch)}", fontsize=o["label_pt"])
    ax.set_title(title, fontsize=o["title_pt"], color=INK, pad=3)


def model_num(v) -> str:
    return f"{v:,.0f}".replace(",", " ") if v >= 100 else f"{v:.3g}"


# --- the figure -------------------------------------------------------------------------

def _margins(o: dict, kind: str) -> tuple[float, float, float, float]:
    """(left, bottom, right, top) mm around a panel's axes, from its fonts."""
    noy = kind == "histogram" and o["layout"] == "offset"
    left = (o["label_pt"] * 1.3 + 5 if noy else o["tick_pt"] * 2.4 + o["label_pt"] * 1.3 + 7)
    bottom = o["tick_pt"] * 1.4 + o["label_pt"] * 1.3 + 6
    if kind == "bars":
        bottom += o["tick_pt"] * 2.2
    top = o["title_pt"] * 1.45 + 3
    right = o["tick_pt"] * 1.3 + 2
    return left * PT, bottom * PT, right * PT, top * PT


def _legend_entries(exp, items, styles, o):
    shown = set()
    for p in items:
        if p.get("kind") in ("histogram", "bars"):
            shown |= {s.label for s in panel_samples(exp, p)}
    labs = [lab for lab in styles if lab in shown]
    return [_handle(styles[lab], o) for lab in labs], [legend_name(exp, lab, o) for lab in labs]


def _legend_size(names, o, width_mm: float | None):
    """(columns, width mm, height mm) of a legend of *names*."""
    em = o["legend_pt"] * PT
    entry = (2.6 + 1.6) * em + max((len(n) for n in names), default=0) * 0.55 * em
    if width_mm is None:
        return 1, entry + 2, len(names) * o["legend_pt"] * 1.5 * PT + 2
    cols = o["legend_cols"] or max(1, int(width_mm // entry))
    cols = max(1, min(cols, len(names)))
    rows = math.ceil(len(names) / cols)
    return cols, cols * entry, rows * o["legend_pt"] * 1.5 * PT + 3


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
    leg_w = _legend_size(names, o, None)[1] if place == "right" and names else 0.0
    fit = max(1, int((o["max_w"] - leg_w + 0.01) // pw))
    cols = max(1, min(o["cols"] or fit, fit, len(grid) or 1))
    rows = max(1, math.ceil(len(grid) / cols))
    W = cols * pw + leg_w
    lcols, _, leg_h = _legend_size(names, o, W) if place in ("top", "bottom") and names \
        else (1, 0, 0.0)
    H = rows * ph + leg_h
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
        if not grid and not names:
            fig.text(0.5, 0.5, "Nothing to plot yet: add FCS files (or a panel with +)",
                     ha="center", va="center", color=MUTED, fontsize=8)
            return fig
        y_top = H - (leg_h if place == "top" else 0)
        for k, (i, p) in enumerate(grid):
            r, c = divmod(k, cols)
            x0, y1 = c * pw, y_top - r * ph
            fig.quickflow_cells.append((i, (x0 / W, (y1 - ph) / H, (x0 + pw) / W, y1 / H)))
            if p.get("kind") == "legend":
                ax = fig.add_axes([x0 / W, (y1 - ph) / H, pw / W, ph / H])
                ax.set_axis_off()
                if handles:
                    ax.legend(handles, names, loc="center", frameon=False,
                              fontsize=o["legend_pt"], handlelength=2.6)
                continue
            po = merged(o, p)
            ml, mb, mr, mt = _margins(po, p.get("kind", "histogram"))
            ax = fig.add_axes([(x0 + ml) / W, (y1 - ph + mb) / H, (pw - ml - mr) / W,
                               (ph - mb - mt) / H])
            if clear:
                ax.patch.set_alpha(0)
            kind = p.get("kind", "histogram")
            if kind == "dot":
                ss = panel_samples(exp, p) or exp.in_group(p.get("group", ""))
                x, y = p.get("x") or "FSC-A", p.get("y") or "SSC-A"
                parent = p.get("population", "")
                kids = [g for g in exp.children(p.get("group", ""), parent or model.ALL)
                        if g.kind == "polygon" and (g.x, g.y) == (x, y)]
                dot_axes(ax, exp, ss, x, y, parent, kids, po,
                         p.get("title") or exp.name("group", p.get("group", "")))
            elif kind == "bars":
                bars_axes(ax, exp, p, po, styles)
            else:
                hist_axes(ax, exp, p, po, styles)
        if names and place in ("top", "bottom", "right"):
            li = next(i for i, p in enumerate(items) if p.get("kind") == "legend")
            if place == "right":
                rect = ((W - leg_w) / W, 0, 1, 1)
                fig.legend(handles, names, loc="center left", bbox_to_anchor=(rect[0], 0.5),
                           frameon=False, fontsize=o["legend_pt"], handlelength=2.6,
                           borderaxespad=0)
            else:
                y0 = 0 if place == "bottom" else (H - leg_h) / H
                rect = (0, y0, 1, y0 + leg_h / H)
                fig.legend(handles, names, loc="center", bbox_to_anchor=(0.5, y0 + leg_h / H / 2),
                           ncol=lcols, frameon=False, fontsize=o["legend_pt"],
                           handlelength=2.6, columnspacing=1.6, borderaxespad=0)
            fig.quickflow_cells.append((li, rect))
    return fig


def _handle(sty, o):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    if sty["fill"] and o["fill"]:
        return Patch(facecolor=sty["fill"] if o["bw"] else to_rgba(sty["fill"], 0.45),
                     edgecolor=sty["edge"], linestyle=sty["dash"], lw=1.0)
    return Line2D([], [], color=sty["edge"], ls=sty["dash"], lw=max(1.0, o["lw"]))
