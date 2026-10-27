"""The experiment: samples, gates, statistics. No Qt.

An experiment is a list of samples (FCS files), each in a *group* (a panel on the figure,
a block of the table: the cell line, a treatment) with a *label* (a series: the stain).
Each group has a gate tree: populations, each a gate on its parent ("" = all events) -
a polygon on two channels or a range on one. A sample can have its own version of a gate
(same name, same place in the tree): the group's gate is the default. Every population gets
the same statistics on the *marker* channel. The single-marker analysis (overlay histograms
+ one value per population) is built on that; more markers, quadrants or titrations would
add a gate kind or a statistic, not a new model.

    python -m flowless.model --self-check [DATA]   counts and values against FlowJo
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from . import __version__, fcs, jsonfile, record, scale

FORMAT, FORMAT_VERSION = "flowless-experiment", 2   # FORMATS.md; 1: "flowless": <version>

ROLES = ["sample", "negative control", "secondary only", "unstained"]
SCATTER = ("FSC", "SSC", "TIME", "WIDTH")       # linear on a dot plot
VIABILITY = re.compile(r"viab|live|dead|zombie|7-?aad|draq ?7|sytox|\bPI\b|dapi", re.I)
CONTROL_ORDER = ["negative control", "secondary only", "unstained"]   # the "÷ control" one
STATS = {"geometric mean": "gmean", "median": "median", "mean": "mean"}
ALL = "All events"
ALIAS_KINDS = ["group", "label", "sample", "channel", "population"]


# --- data -------------------------------------------------------------------------------

_cache: dict[str, fcs.FCS] = {}


def load(path) -> fcs.FCS:
    """The file's events, read once. Looked up by the path as given first: resolving it
    asks the disk (Sample.fcs runs this hundreds of times a figure)."""
    given = str(path)
    f = _cache.get(given)
    if f is None:
        key = str(Path(path).resolve())
        f = _cache.get(key) or fcs.read(key)
        _cache[key] = _cache[given] = f
    return f


@dataclass
class Gate:
    name: str
    parent: str = ""                     # "" = all events
    kind: str = "polygon"                # polygon (x, y, vertices) | range (x, lo, hi)
    x: str = ""
    y: str = ""
    vertices: list = field(default_factory=list)
    lo: float | None = None
    hi: float | None = None
    xs: str = ""                         # a polygon's sides are straight on these scales:
    ys: str = ""                         # "" linear, "log", "logicle 0.65" (its plot's)

    def mask(self, f: fcs.FCS, base: np.ndarray) -> np.ndarray:
        if self.x not in f.data or (self.kind == "polygon" and self.y not in f.data):
            return np.zeros(f.n, bool)
        x = f.data[self.x]
        if self.kind == "range":
            m = base.copy()
            if self.lo is not None:
                m &= x >= self.lo
            if self.hi is not None:
                m &= x < self.hi
            return m
        if len(self.vertices) < 3:
            return np.zeros(f.n, bool)
        from matplotlib.path import Path as Poly

        v = np.asarray(self.vertices, float)
        cols = []
        for k, (ch, sc) in enumerate(((self.x, self.xs), (self.y, self.ys))):
            top = f.range(ch)
            a = _piled(f.data[ch][base], top, v[:, k])
            cols.append(scale.events(sc, a, top) if sc else a)
            if sc:
                v[:, k] = scale.forward(sc, v[:, k], top)
        out = np.zeros(f.n, bool)                # only the parent's events are tested
        out[base] = Poly(v).contains_points(np.column_stack(cols))
        return out

    def key(self) -> tuple:
        return (self.name, self.parent, self.kind, self.x, self.y,
                tuple(map(tuple, self.vertices)), self.lo, self.hi, self.xs, self.ys)


def _piled(a: np.ndarray, top: float, verts: np.ndarray) -> np.ndarray:
    """Events off the top of the scale sit on the plot's edge: a gate drawn to that edge
    takes them, as FlowJo does (an Accuri's FSC-A saturates for big cells: 20 % of the
    events of a sample here). Measured: without this, -15 % against FlowJo's counts.
    The bottom edge needs nothing: a vertex put there sits just below 0."""
    if not top or verts.max() < 0.99 * top:
        return a
    return np.where(a >= top - 1, verts.max() - 1, a)


@dataclass
class Sample:
    path: str
    name: str = ""
    group: str = ""
    label: str = ""
    role: str = "sample"
    plot: bool = True
    fields: dict = field(default_factory=dict)   # condition, primary, secondary… (the record)
    ident: str = ""                              # $DATE $BTIM $TOT: is it still that file?
    gates: dict = field(default_factory=dict)    # its own version of a group's gate, by name

    @property
    def fcs(self) -> fcs.FCS:
        return load(self.path)


_masks: dict[tuple, dict] = {}


@dataclass
class Experiment:
    samples: list[Sample] = field(default_factory=list)
    gates: dict[str, list[Gate]] = field(default_factory=dict)   # group -> its gate tree
    marker: str = ""                                              # channel, "FL2-A"
    stat: str = "geometric mean"
    record: dict = field(default_factory=dict)
    figure: dict = field(default_factory=dict)
    aliases: dict = field(default_factory=dict)                  # kind -> {name: shown as}
    channels: list = field(default_factory=list)                 # shown; [] = auto
    path: str = ""                                                # where it was saved
    gates_file: dict = field(default_factory=dict)    # {path, how, key}: the gates' file
    label_order: list = field(default_factory=list)   # the series as the user ordered them
    id: str = ""                                       # given at the first save, kept

    # -- groups and samples
    def groups(self) -> list[str]:
        return list(dict.fromkeys(s.group for s in self.samples))

    def in_group(self, g: str) -> list[Sample]:
        return [s for s in self.samples if s.group == g]

    def labels(self) -> list[str]:
        """Series in order: as the user set them (label_order), the others after them in
        table order, controls first. Fixes the legend's order and each label's colour."""
        order = {r: i for i, r in enumerate(["negative control", "sample", "secondary only",
                                             "unstained"])}
        seen = list(dict.fromkeys(s.label for s in self.samples))
        role = {s.label: s.role for s in self.samples}
        rest = sorted((l for l in seen if l not in self.label_order),
                      key=lambda l: (order.get(role[l], 9), seen.index(l)))
        return [l for l in self.label_order if l in role] + rest

    def rank(self) -> dict[str, int]:
        """label -> its place in labels()."""
        return {lab: i for i, lab in enumerate(self.labels())}

    def add(self, paths, negatives=()) -> tuple[list[Sample], list[str]]:
        """Load FCS files (folders: every .fcs inside); *negatives*: labels known to be
        negative controls. Returns (added, problems)."""
        have = {str(Path(s.path).resolve()) for s in self.samples}
        files, bad = [], []
        for p in map(Path, paths):
            files += (sorted(p.rglob("*.fcs"), key=lambda q: (str(q.parent).lower(), _natural(q)))
                      if p.is_dir() else [p])
        added = []
        for p in files:
            if str(p.resolve()) in have:
                continue
            try:
                f = load(p)
            except Exception as e:                # a broken file must not stop the others
                bad.append(f"{p.name}: {e}")
                continue
            have.add(str(p.resolve()))
            s = Sample(str(p.resolve()), p.stem, ident=_ident(f))
            added.append(s)
        guess(added, negatives)
        self.samples += added
        if not self.marker and self.samples:
            self.marker = self.default_marker()
        return added, bad

    # -- names: what the figure, the tables and the report show
    def name(self, kind: str, key: str) -> str:
        shown = self.aliases.get(kind, {}).get(key, "")
        if shown:
            return shown
        if kind == "channel" and self.samples:
            return self.samples[0].fcs.label(key)
        return key

    def pool(self, g: str) -> list[str]:
        """The groups shown under *g*'s name, *g* among them: replicates (runs) of one
        condition."""
        n = self.name("group", g)
        return [x for x in self.groups() if self.name("group", x) == n]

    def run_of(self, g: str) -> str:
        """The day the group's files were acquired ('2026-05-27'), else its own name."""
        days = sorted({fcs.when(s.fcs.meta)[:10] for s in self.in_group(g)} - {""})
        return days[0] if days else g

    def title(self, g: str) -> str:
        """The group's name as shown; its run's day after it when replicates share it."""
        n = self.name("group", g)
        if len(self.pool(g)) < 2:
            return n
        runs = [self.run_of(x) for x in self.pool(g)]
        return f"{n} · {self.run_of(g) if runs.count(self.run_of(g)) == 1 else g}"

    def same_named(self) -> dict[str, str]:
        """Groups whose names differ only by case, spaces or punctuation from an earlier
        group's ('MDA-MB-157-parental cells' / 'MDA-MB-157 parental cells': two runs'
        folders), neither renamed: {group: the earlier one's name}."""
        out, seen = {}, {}
        named = self.aliases.get("group", {})
        for g in self.groups():
            k = re.sub(r"[^0-9a-z]+", "", g.lower())
            if k in seen and g not in named and seen[k] not in named:
                out[g] = seen[k]
            seen.setdefault(k, g)
        return out

    # -- channels
    def all_channels(self) -> list[str]:
        return list(self.samples[0].fcs.channels) if self.samples else []

    def fluorescence(self) -> list[str]:
        """The fluorescence channels the reagents' fluorochromes are read on (areas); all
        fluorescence areas when no fluorochrome is recorded."""
        if not self.samples:
            return []
        f = self.samples[0].fcs
        fl = [c for c, lab in zip(f.channels, f.labels) if _is_fluo(c, lab) and c.endswith("-A")]
        want = record.fluorochromes(record.clean(self.record))
        hit = [c for c in fl if fcs.fluor_of(f.labels[f.channels.index(c)] or c) in want]
        return hit or fl

    def shown_channels(self) -> list[str]:
        """What the channel lists offer: FSC-A, SSC-A and the fluorescence areas in use
        (heights, other detectors and Time hidden), or the ones chosen; channels a gate is
        on always."""
        allc = self.all_channels()
        if self.channels:
            keep = set(self.channels)
        else:
            keep = {c for c in ("FSC-A", "SSC-A") if c in allc} | set(self.fluorescence())
        for gs in self.gates.values():
            for g in gs:
                keep |= {g.x, g.y}
        keep.add(self.marker)
        return [c for c in allc if c in keep]

    def default_marker(self) -> str:
        dye = self.viability_channel()
        return next((c for c in self.fluorescence() + self.all_channels() if c != dye), "")

    def scale(self, ch: str, dot: bool = False) -> str:
        """The axis of *ch*: log ('' for linear: a dot plot's scatter channels), logicle
        where a file holds values below 0 (compensated data), its width from the most
        negative ones ('logicle 0.65')."""
        if dot and ch.upper().startswith(SCATTER):
            return ""
        neg = [s.fcs.negative[ch] for s in self.samples if ch in s.fcs.negative]
        if not neg:
            return "log"
        top = next(s.fcs.range(ch) for s in self.samples if ch in s.fcs.data) or 262144.0
        return scale.logicle(top, min(neg))

    def viability_channel(self) -> str:
        """The channel a viability dye is read on: a recorded one's (a reagent of kind
        'viability dye'), else a channel named for one ($PnS 'DRAQ7-A', 'Live/Dead'…);
        '' without: nothing about viability is shown then."""
        if not self.samples:
            return ""
        f = self.samples[0].fcs
        dyes = {fcs.fluor_of(r.get("fluorochrome") or fcs.find_fluor(r.get("name", "")))
                for r in self.record.get("reagents", []) if r.get("kind") == "viability dye"}
        for c, lab in zip(f.channels, f.labels):
            if c.endswith("-A") and _is_fluo(c, lab) and (
                    fcs.fluor_of(lab or c) in dyes - {""} or VIABILITY.search(lab)):
                return c
        return ""

    # -- gating
    def tree(self, s: Sample) -> list[Gate]:
        """The sample's gate tree: the group's, with the sample's own versions in place."""
        out = []
        for g in self.gates.get(s.group, []):
            own = s.gates.get(g.name)
            out.append(replace(own, name=g.name, parent=g.parent) if own else g)
        return out

    def masks(self, s: Sample) -> dict[str, np.ndarray]:
        """Each population of the sample's group: its events (ALL first). Cached on the
        file and the gates."""
        tree = self.tree(s)
        key = (s.path, tuple(g.key() for g in tree))
        hit = _masks.get(key)
        if hit is None:
            f = s.fcs
            hit = {ALL: np.ones(f.n, bool)}
            for g in tree:
                base = hit.get(g.parent or ALL)
                if base is not None:
                    hit[g.name] = g.mask(f, base)
            if len(_masks) > 500:   # ponytail: whole-cache reset, an LRU if it ever matters
                _masks.clear()
            _masks[key] = hit
        return hit

    def children(self, group: str, pop: str) -> list[Gate]:
        return [g for g in self.gates.get(group, []) if (g.parent or ALL) == pop]

    def main_population(self, group: str) -> str:
        """The population a group's figure and values use: its first gate when that's a
        polygon (the cells), the first polygon below that one if it's first, and so on
        (cells › singlets). All events when the group has no gate."""
        pop = ALL
        while True:
            kids = self.children(group, pop)
            if not kids or kids[0].kind != "polygon":
                return pop
            pop = kids[0].name

    def below(self, group: str, pop: str) -> list[str]:
        """Every population under *pop*, in tree order."""
        out = []
        for g in self.children(group, pop):
            out += [g.name] + self.below(group, g.name)
        return out

    def stray_ranges(self, group: str, pop: str = "") -> dict[str, list[str]]:
        """The ranges not below *pop* (default: the main population) - what a figure of it
        leaves out -, by the top gate they hang from ("" : on all events)."""
        used = set(self.below(group, pop or self.main_population(group)))
        by = {g.name: g for g in self.gates.get(group, [])}
        out = {}
        for g in by.values():
            if g.kind == "range" and g.name not in used:
                top = g
                while top.parent in by:
                    top = by[top.parent]
                out.setdefault("" if top is g else top.name, []).append(g.name)
        return out

    def control(self, group: str) -> Sample | None:
        for role in CONTROL_ORDER:
            for s in self.in_group(group):
                if s.role == role:
                    return s
        return None

    # -- results
    def results(self) -> list[dict]:
        """A row per sample and population: count, % of parent, the statistics on the
        marker, and the chosen one over the group's control's (main population)."""
        rows, key = [], STATS.get(self.stat, "gmean")
        ctrl_val = {}
        for g in self.groups():
            c = self.control(g)
            if c is not None:
                m = self.masks(c).get(self.main_population(g))
                if m is not None:
                    ctrl_val[g] = stats(c.fcs.data.get(self.marker, np.empty(0))[m])[key]
        for s in self.samples:
            ms = self.masks(s)
            vals = s.fcs.data.get(self.marker, np.zeros(s.fcs.n))
            parents = {ALL: None, **{g.name: g.parent or ALL for g in self.gates.get(s.group, [])}}
            gated = self.main_population(s.group) != ALL
            for pop, m in ms.items():
                st = stats(vals[m])
                par = parents.get(pop)
                n_par = int(ms[par].sum()) if par in ms else None
                # all events (debris too) over the control's cells means nothing: no ratio
                c = None if gated and pop == ALL else ctrl_val.get(s.group)
                rows.append({"group": s.group, "label": s.label, "role": s.role,
                             "sample": s.name, "population": pop, "parent": par or "",
                             "count": st["count"],
                             "% parent": 100 * st["count"] / n_par if n_par else None,
                             **{k: st[v] for k, v in STATS.items()}, "CV %": st["cv"],
                             "÷ control": st[key] / c if c and st[key] is not None else None,
                             "own gate": pop in s.gates})
        gi, rk = {g: i for i, g in enumerate(self.groups())}, self.rank()
        return sorted(rows, key=lambda r: (gi[r["group"]], rk[r["label"]]))   # stable

    def gates_key(self) -> str:
        """A fingerprint of every gate (the groups' and the samples' own)."""
        import hashlib
        d = [{g: [asdict(x) for x in gs] for g, gs in self.gates.items()},
             [(s.name, {k: asdict(v) for k, v in s.gates.items()}) for s in self.samples]]
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def gates_from(self) -> dict:
        """The file the gates came from or went to, while they are still as there."""
        f = self.gates_file
        ok = f.get("key") == self.gates_key() and Path(f.get("path", "")).is_file()
        return f if ok else {}

    # -- file
    def to_dict(self) -> dict:
        base = Path(self.path).parent if self.path else None
        samples = []
        for s in self.samples:
            d = asdict(s)
            if base:
                try:          # the folder moved with its data opens the same
                    d["rel"] = Path(os.path.relpath(s.path, base)).as_posix()
                except ValueError:                        # another drive
                    d["rel"] = ""
            samples.append(d)
        return {"id": self.id, "marker": self.marker, "stat": self.stat,
                "samples": samples,
                "gates": {g: [asdict(x) for x in gs] for g, gs in self.gates.items()},
                "record": self.record, "figure": self.figure, "aliases": self.aliases,
                "channels": self.channels, "gates_file": self.gates_file,
                "label_order": self.label_order}

    def save(self, path) -> None:
        self.path = str(Path(path).resolve())
        self.id = self.id or jsonfile.new_id()
        jsonfile.write(path, self.to_dict(), FORMAT, FORMAT_VERSION, f"Flowless {__version__}",
                       self.id)                   # whole or not at all

    @classmethod
    def from_dict(cls, d: dict, path: str = "") -> tuple["Experiment", list[str]]:
        """The experiment, and what didn't come back (a file not found, one changed)."""
        e = cls(marker=d.get("marker", ""), stat=d.get("stat", "geometric mean"),
                record=d.get("record", {}), figure=d.get("figure", {}),
                aliases=d.get("aliases", {}), channels=d.get("channels", []), path=path,
                gates_file=d.get("gates_file", {}), label_order=d.get("label_order", []),
                id=d.get("id", ""))
        base = Path(path).parent if path else None
        problems = []
        for sd in d.get("samples", []):
            sd = dict(sd)
            rel = sd.pop("rel", "")
            cands = ([base / rel] if base and rel else []) + [Path(sd["path"])]
            if base:
                cands.append(base / Path(sd["path"]).name)
            p = next((c for c in cands if c.is_file()), None)
            known = {k: sd[k] for k in Sample.__dataclass_fields__ if k in sd}
            known["fields"] = {OLD_FIELDS.get(k, k): v for k, v in known.get("fields", {}).items()}
            known["gates"] = {k: _gate(v) for k, v in known.get("gates", {}).items()}
            if p is None:
                problems.append(f"{Path(sd['path']).name}: not found (left out)")
                continue
            s = Sample(**{**known, "path": str(p.resolve())})
            try:
                now = _ident(s.fcs)
            except Exception as ex:
                problems.append(f"{p.name}: {ex}")
                continue
            if s.ident and now != s.ident:
                problems.append(f"{p.name}: not the file it was ({s.ident} → {now})")
            e.samples.append(s)
        e.gates = {g: [_gate(x) for x in gs] for g, gs in d.get("gates", {}).items()}
        return e, problems

    @classmethod
    def open(cls, path) -> tuple["Experiment", list[str]]:
        d = jsonfile.read(path)
        try:                                 # quickflow: its first name
            jsonfile.version_of(d, FORMAT, FORMAT_VERSION,
                                lambda d: 1 if "flowless" in d or "quickflow" in d else None)
        except jsonfile.FormatError as e:
            raise ValueError(f"{Path(path).name}: "
                             + (str(e) if "newer" in str(e) else "not a Flowless experiment"))
        return cls.from_dict(d, str(Path(path).resolve()))


OLD_FIELDS = {"VHH, µL": "primary µL", "Anti-VHH, µL": "secondary µL", "VHH": "primary",
              "Anti-VHH": "secondary"}       # the first version's names, from the sheets


def _gate(d) -> Gate:
    return d if isinstance(d, Gate) else Gate(**{k: d[k] for k in Gate.__dataclass_fields__
                                                  if k in d})


def _is_fluo(ch: str, label: str) -> bool:
    return not ch.upper().startswith(SCATTER) and not label.upper().startswith(("FSC", "SSC"))


AUTO = "cells (auto)"


def add_cells_gate(exp: Experiment, group: str, x: str, y: str, verts) -> str:
    """A 'cells (auto)' polygon on all events, after the gates already there (beside
    them, not around them: the main population stays the one it was)."""
    gs = exp.gates.setdefault(group, [])
    names = {g.name for g in gs}
    name = next(n for n in [AUTO] + [f"{AUTO} {i}" for i in range(2, 99)] if n not in names)
    gs.append(Gate(name, "", "polygon", x, y, verts))
    return name


# --- statistics -------------------------------------------------------------------------

def stats(v: np.ndarray) -> dict:
    """count, geometric mean (of the positive values, as FlowJo), median, mean, CV %."""
    n = int(v.size)
    if not n:
        return {"count": 0, "gmean": None, "median": None, "mean": None, "cv": None}
    pos = v[v > 0]
    mean = float(v.mean())
    return {"count": n,
            "gmean": float(np.exp(np.log(pos).mean())) if pos.size else None,
            "median": float(np.median(v)), "mean": mean,
            "cv": float(100 * v.std(ddof=1) / mean) if n > 1 and mean else None}


def histogram(v: np.ndarray, top: float, bins: int = 256, smooth: bool = True,
              kind: str = "log"):
    """Counts per channel on a log scale from 1 to *top* (256 channels, as FlowJo's
    'Count' axis), or a logicle one (*kind*: values below 0 too). Returns (bin centres,
    counts)."""
    if kind.startswith("logicle"):
        h, e = np.histogram(scale.forward(kind, v, top), bins=bins, range=(0, scale.M))
    else:
        hi = math.log10(top) if top > 1 else 7.0
        h, e = np.histogram(np.log10(v[v > 0]) if v.size else np.empty(0), bins=bins,
                            range=(0, hi))
    h = h.astype(float)
    if smooth and h.sum():
        k = np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2)
        h = np.convolve(h, k / k.sum(), mode="same")
    return scale.inverse(kind, (e[:-1] + e[1:]) / 2, top), h


def saturated(s: Sample) -> dict[str, float]:
    """% of the sample's events at the top of each channel's scale (off scale), where > 1 %."""
    f = s.fcs
    out = {}
    for c in f.channels:
        top = f.range(c)
        if top and c in f.data and f.n:
            p = 100 * float((f.data[c] >= top - 1).mean())
            if p > 1:
                out[c] = p
    return out


def auto_gate(samples: list[Sample], x: str, y: str, level: float = 0.15) -> list:
    """A polygon around the main cluster of the samples' events on x/y (pooled): the
    density contour at *level* × its peak that holds the peak, raised as far as the dip
    to a second cluster when one lies inside it (≥ 2 % of the events, its own peak
    ≥ 10 % of the main one above the dip) - the gate stops between two populations
    instead of cutting through one. Debris and the off-scale pile fall outside. A
    starting point: drag its corners to adjust."""
    import contourpy
    from matplotlib.path import Path as Poly

    xs, ys, top = [], [], [0.0, 0.0]
    for s in samples:
        f = s.fcs
        if x in f.data and y in f.data:
            rx, ry = f.range(x) or f.data[x].max(), f.range(y) or f.data[y].max()
            top = [max(top[0], rx), max(top[1], ry)]
            ok = (f.data[x] < rx - 1) & (f.data[y] < ry - 1)
            xs.append(f.data[x][ok])
            ys.append(f.data[y][ok])
    if not xs:
        return []
    X, Y = np.concatenate(xs), np.concatenate(ys)
    n = 128
    h, ex, ey = np.histogram2d(X, Y, bins=n, range=[[0, top[0]], [0, top[1]]])
    k = np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2)
    k /= k.sum()
    h = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 0, h)
    h = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, h)
    xc, yc = (ex[:-1] + ex[1:]) / 2, (ey[:-1] + ey[1:]) / 2
    # debris is denser than the cells but small: the peak is taken weighted by size (x),
    # and everything left of the dip between the debris and that peak is cut off
    i, j = np.unravel_index(np.argmax(h * xc[:, None]), h.shape)
    mx = h.sum(axis=1)
    a = int(np.argmax(mx[: max(1, i // 2)]))
    h[: a + int(np.argmin(mx[a:i])) if i > a else 0, :] = 0
    while True:                                  # up the slope to the cluster's own peak
        r0, c0 = max(i - 1, 0), max(j - 1, 0)
        sub = h[r0:i + 2, c0:j + 2]
        a, b = np.unravel_index(np.argmax(sub), sub.shape)
        if sub[a, b] <= h[i, j]:
            break
        i, j = r0 + a, c0 + b
    cx, cy = xc[i], yc[j]
    pk = h[i, j]
    t = max(level * pk, min(_split_level(h, i * n + j, level * pk), 0.5 * pk))
    lines = contourpy.contour_generator(xc, yc, h.T).lines(t)
    for line in sorted(lines, key=len):
        if len(line) > 3 and Poly(line).contains_point((cx, cy)):
            step = max(1, len(line) // 24)
            return [[float(a), float(b)] for a, b in line[::step]]
    return []


SINGLETS = "singlets (auto)"


def singlets_gate(samples: list[Sample], masks: list, x: str = "FSC-A",
                  y: str = "FSC-H") -> tuple[list, float]:
    """A polygon on area (x) × height (y) around the singlets - a doublet has about twice
    the area for the same height. The singlets' ridge is a line A = c0 + c1·H through the
    densest area in each height slice (the area / height ratio grows with the cells' size,
    so no single ratio fits); the band around it is measured on its left side (singlets
    only; the doublets are the right tail): 3 σ above the line, 4 σ below, σ relative to
    the line. *masks*: each sample's parent population. Returns (vertices, % of the
    events in); ([], 0) with too few events."""
    A, H, top = [], [], 0.0
    for s, m in zip(samples, masks):
        f = s.fcs
        if x in f.data and y in f.data:
            A.append(f.data[x][m])
            H.append(f.data[y][m])
            top = max(top, f.range(x) or 0)
    if not A:
        return [], 0.0
    A, H = np.concatenate(A), np.concatenate(H)
    top = top or float(A.max())
    ok = (H > 0) & (A > 0) & (A < top - 1)            # the off-scale pile has no ratio
    if ok.sum() < 200:
        return [], 0.0
    a, h = A[ok], H[ok]
    ridge = []                                        # the densest area per height slice
    for lo, hi in zip(*(np.percentile(h, q) for q in (np.arange(2, 98, 8),
                                                       np.arange(10, 106, 8).clip(max=98)))):
        sel = a[(h >= lo) & (h < hi)]
        if sel.size < 50:
            continue
        cnt, e = np.histogram(sel, bins=60, range=tuple(np.percentile(sel, [1, 99])))
        cnt = np.convolve(cnt, np.ones(3) / 3, mode="same")
        ridge.append(((lo + hi) / 2, (e[cnt.argmax()] + e[cnt.argmax() + 1]) / 2, sel.size))
    if len(ridge) < 3:
        return [], 0.0
    rh, ra, w = (np.array(v, float) for v in zip(*ridge))
    c1, c0 = np.polyfit(rh, ra, 1, w=np.sqrt(w))
    line = c0 + c1 * h
    rel = (a - line) / np.maximum(line, 1.0)
    left = rel[rel < 0]
    sd = -float(np.percentile(left, 31.7)) if left.size > 50 else 0.1
    lo_f, hi_f = 1 - 4 * sd, 1 + 3 * sd
    h0, h1 = float(np.percentile(h, 0.2)) * 0.9, float(np.percentile(h, 99.8)) * 1.05
    L = lambda hh: c0 + c1 * hh                         # noqa: E731
    v = [[max(lo_f * L(h0), 0.0), h0], [hi_f * L(h0), h0]]
    if hi_f * L(h1) > top and c1 > 0:                   # past the scale's top: its edge
        hx = (top / hi_f - c0) / c1
        v += [[top, hx], [top, h1]]
    else:
        v += [[hi_f * L(h1), h1]]
    v += [[min(lo_f * L(h1), top), h1]]
    from matplotlib.path import Path as Poly
    pts = np.column_stack([np.minimum(A, top - 1), H])
    pct = 100 * float(Poly(np.asarray(v)).contains_points(pts).mean())
    return [[float(p), float(q)] for p, q in v], pct


LIVE = "live (auto)"


def live_gate(samples: list[Sample], masks: list, x: str, kind: str,
              y: str = "SSC-A") -> tuple[list, float]:
    """A rectangle on the viability dye (*x*, on its *kind* of axis) × *y* around the live
    cells: the dye's dim events, up to the dip before the bright (dead) ones - the lowest
    point of the smoothed histogram between its main peak and a second peak (≥ 3 % of it);
    with no second peak (all alive) 2.5 half-widths above the main peak. *masks*: each
    sample's parent population. Returns (vertices, % of the events in); ([], 0) without
    events."""
    v, ry, top = [], 0.0, 0.0
    for s, m in zip(samples, masks):
        f = s.fcs
        if x in f.data and y in f.data:
            v.append(f.data[x][m])
            ry, top = max(ry, f.range(y) or float(f.data[y].max())), max(top, f.range(x))
    v = np.concatenate(v) if v else np.empty(0)
    if v.size < 50:
        return [], 0.0
    top = top or float(v.max())
    d = scale.events(kind, v, top)
    span = scale.span(kind, top)
    h, e = np.histogram(d[d > 0], bins=256, range=(0, span))   # not the pile on the edge
    k = np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2)
    h = np.convolve(h.astype(float), k / k.sum(), mode="same")
    p = int(np.argmax(h))
    half = p + int(np.argmax(h[p:] < 0.5 * h[p]))
    q = half + int(np.argmax(h[half:])) if half < len(h) else half
    if q > half + 3 and h[q] >= 0.03 * h[p] and h[half:q].min() < 0.7 * h[q]:
        cut = half + int(np.argmin(h[half:q + 1]))
    else:
        cut = min(len(h) - 1, int(p + 2.5 * max(half - p, 2)))
    t = float(e[cut])
    xs = float(scale.inverse(kind, -0.02 * span, top)), float(scale.inverse(kind, t, top))
    y0 = -0.005 * ry
    pct = 100 * float((d < t).mean())
    return [[xs[0], y0], [xs[1], y0], [xs[1], ry], [xs[0], ry]], pct


def _split_level(h: np.ndarray, main: int, floor: float) -> float:
    """The density at which the main peak's region would take in another cluster (its
    own peak ≥ 10 % of the main one above that level, ≥ 2 % of the events): flood the
    density from the top down (union-find over the cells), stop at the first such merge.
    *floor* if none. ponytail: 8-neighbour union-find in Python, ~50 ms on 128²."""
    n = h.shape[1]
    flat = h.ravel()
    total = flat.sum() or 1.0
    parent = np.full(flat.size, -1)
    peak, mass = {}, {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for idx in np.argsort(-flat):
        v = flat[idx]
        if v < floor:
            break
        parent[idx] = idx
        peak[idx], mass[idx] = idx, v
        r, c = divmod(int(idx), n)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, cc = r + dr, c + dc
                if (dr or dc) and 0 <= rr < h.shape[0] and 0 <= cc < n and \
                        parent[rr * n + cc] != -1:
                    ra, rb = find(idx), find(rr * n + cc)
                    if ra == rb:
                        continue
                    mr = find(main) if parent[main] != -1 else -2
                    if mr in (ra, rb):
                        other = rb if mr == ra else ra
                        if flat[peak[other]] - v >= 0.1 * flat[main] and \
                                mass[other] >= 0.02 * total:
                            return float(v) * 1.02
                    if flat[peak[ra]] < flat[peak[rb]]:
                        ra, rb = rb, ra
                    parent[rb] = ra
                    mass[ra] += mass.pop(rb)
                    peak.pop(rb)
    return floor


# --- guesses from file names ------------------------------------------------------------

_RUN = re.compile(r"^\d{8}_\d{6}$")              # an Accuri run folder: 20260629_145214
_WELL = re.compile(r"^[A-H]\d{2}\b[ _-]*")


def _natural(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def _ident(f: fcs.FCS) -> str:
    m = f.meta
    return " ".join(x for x in (fcs.pick(m, ("$DATE",)), fcs.pick(m, ("$BTIM",)), str(f.n)) if x)


def guess(samples: list[Sample], negatives=()) -> None:
    """Group, label and role from where the files sit and what they're called:
    `MDA-MB-157 parental cells/24E8_PC.fcs` → group the folder, label 24E8 (the suffix the
    whole folder shares dropped); `PC3-29A1.fcs` in a run folder → PC3 / 29A1;
    `A02 24E8.fcs` → 24E8 (the well dropped). 'unstained', '… only' set the role; a label
    recorded as a negative control before is one again. A file named only by its well (an
    empty or wash well) isn't plotted."""
    negs = {n.lower() for n in negatives}
    by_dir: dict[Path, list[Sample]] = {}
    for s in samples:
        by_dir.setdefault(Path(s.path).parent, []).append(s)
    for d, ss in by_dir.items():
        stems = [_WELL.sub("", Path(s.path).stem) or Path(s.path).stem for s in ss]
        folder = None if _RUN.match(d.name) else d.name
        if folder:
            cut = _shared_suffix(stems)
            for s, st in zip(ss, stems):
                s.group, s.label = folder, (re.sub(r"[_-][^_-]+$", "", st) if cut else st) or st
        else:                                     # run folder: "PC3-29A1", "OVCAR_29A1"
            for s, st in zip(ss, stems):
                m = re.match(r"^(.+?)[_-](.+)$", st)
                if m and sum(1 for t in stems if t.startswith(m.group(1))) > 1:
                    s.group, s.label = m.group(1), m.group(2)
                else:
                    s.group, s.label = d.name, st
        for s in ss:
            low = s.label.lower()
            s.role = ("unstained" if "unstained" in low else
                      "secondary only" if low.endswith("only") or " only" in low else
                      "negative control" if low in negs else "sample")
            s.plot = s.role in ("sample", "negative control")
            if re.fullmatch(r"[A-H]\d{2}", Path(s.path).stem):
                s.plot = False


def _shared_suffix(stems: list[str]) -> bool:
    """True for ['24E8_PC', '0006_PC', …] or ['29A1-Doxo', 'R3B23_doxo']: all end alike
    after a _ or -, so that ending names the folder, not the stain."""
    tails = [re.search(r"[_-]([^_-]+)$", s) for s in stems]
    return len(stems) > 1 and all(tails) and len({t.group(1).lower() for t in tails}) == 1


# --- self-check -------------------------------------------------------------------------

# geometric means FlowJo gave for these (data/Figures.pptx), and the channel
REFERENCE = [("TheraSen_260611.wsp", "FL2-A", {
                  "0006_m.fcs": {"": 2776}, "29A1_m.fcs": {"": 4358}, "29E7_m.fcs": {"": 2362},
                  "24A10_m.fcs": {"medium": 12211, "high": 6.33e5},
                  "24E8_m.fcs": {"medium": 9538},
                  "0006_PC.fcs": {"": 1293}, "29A1_PC.fcs": {"": 1273},
                  "24A10_PC.fcs": {"": 1260}, "24E8_PC.fcs": {"": 1369}}),
             ("20260629_145214/29-Jun-2026.wsp", "FL2-A", {
                  "PC3-R3B23.fcs": {"": 3854}, "PC3-29A1.fcs": {"": 70543}}),
             ("06-Aug-2026.wsp", "FL2-H", {
                  "A04 R23B23.fcs": {"": 863}, "A02 24E8.fcs": {"": 6893},
                  "A03 24A10.fcs": {"": 7338}})]


def self_check(data: Path) -> int:
    from .imports import flowjo

    worst_n, worst_v, ok = 0.0, 0.0, True
    for wsp, marker, want in REFERENCE:
        e = Experiment()
        e.add([(data / wsp).parent])
        e.marker = marker
        for s in e.samples:                        # FlowJo gated per file: one group each
            s.group = s.name
        for line in flowjo.apply(e, data / wsp):
            m = re.search(r"\(the workspace: \d+, ([+-][\d.]+) %\)", line)
            if m:
                worst_n = max(worst_n, abs(float(m.group(1))))
        rows = e.results()
        for fname, pops in want.items():
            for pop, ref in pops.items():
                s = next(s for s in e.samples if Path(s.path).name == fname)
                name = pop or e.main_population(s.group)
                r = next(r for r in rows if r["sample"] == s.name and r["population"] == name)
                err = 100 * abs(r["geometric mean"] - ref) / ref
                worst_v = max(worst_v, err)
                if err > 0.5:
                    ok = False
                    print(f"✗ {fname} {name}: {r['geometric mean']:.0f}, FlowJo {ref:.0f}")
    print(f"counts within {worst_n:.1f} % of FlowJo's, geometric means within "
          f"{worst_v:.2f} %")
    if worst_n > 1.5:
        ok = False
    # one group, a sample's own gate: FlowJo's per-file medium / high gates come back
    e = Experiment()
    e.add([data / "20260611_152206" / "MDA-MB-157-mCDCP1"])
    e.marker = "FL2-A"
    flowjo.apply(e, data / "TheraSen_260611.wsp")
    s = next(s for s in e.samples if s.label == "24E8")
    r = next(r for r in e.results() if r["sample"] == s.name and r["population"] == "medium")
    assert "medium" in s.gates and abs(r["geometric mean"] - 9538) / 9538 < 0.005, r
    assert e.main_population(s.group) == e.gates[s.group][0].name
    # file-name guesses
    t = [Sample(f"C:/x/MDA-MB-157 parental cells/{n}.fcs") for n in ("24E8_PC", "AcII only_PC",
                                                                      "unstained_PC")]
    guess(t, ["0006"])
    assert [(s.group, s.label, s.role) for s in t] == [
        ("MDA-MB-157 parental cells", "24E8", "sample"),
        ("MDA-MB-157 parental cells", "AcII only", "secondary only"),
        ("MDA-MB-157 parental cells", "unstained", "unstained")], t
    t = [Sample(f"C:/x/20260629_145214/{n}.fcs") for n in ("PC3-29A1", "PC3_unstained", "OVCAR_29A1",
                                                          "OVCAR_R3B23")]
    guess(t, ["R3B23"])
    assert [(s.group, s.label, s.role) for s in t] == [
        ("PC3", "29A1", "sample"), ("PC3", "unstained", "unstained"),
        ("OVCAR", "29A1", "sample"), ("OVCAR", "R3B23", "negative control")], t
    # the main population: first gate if a polygon, then its first polygon child
    e = Experiment(gates={"g": [Gate("cells"), Gate("high", "cells", "range"),
                                Gate("singlets", "cells")]})
    assert e.main_population("g") == "cells"
    e.gates["g"].insert(1, e.gates["g"].pop(2))
    assert e.main_population("g") == "singlets" and e.below("g", "cells") == ["singlets", "high"]
    e2 = Experiment(gates={"g": [Gate("cells"), Gate("gate 1"), Gate("high", "gate 1", "range")]})
    assert e2.stray_ranges("g") == {"gate 1": ["high"]}, e2.stray_ranges("g")
    assert e2.stray_ranges("g", "gate 1") == {}
    # two clusters: the gate holds the big one, not half of the small one
    rng = np.random.default_rng(1)
    big = rng.normal([1.0e7, 2.0e6], [1.6e6, 5e5], (20000, 2))
    small = rng.normal([5.0e6, 3.6e6], [6e5, 3e5], (3000, 2))
    xy = np.clip(np.vstack([big, small]), 1, 1.6e7)
    f = fcs.FCS(Path("t.fcs"), {"$P1R": "16777216", "$P2R": "16777216"}, ["FSC-A", "SSC-A"],
                ["", ""], {"FSC-A": xy[:, 0], "SSC-A": xy[:, 1]})
    _cache[str(Path("t.fcs").resolve())] = f
    v = auto_gate([Sample("t.fcs")], "FSC-A", "SSC-A")
    from matplotlib.path import Path as Poly
    inside = Poly(np.array(v)).contains_points(xy)
    assert inside[:20000].mean() > 0.8 and inside[20000:].mean() < 0.1, \
        (inside[:20000].mean(), inside[20000:].mean())
    # singlets: a band of area / height around 1.8, doublets at about twice the area
    hs = rng.uniform(2e6, 6e6, 12000)
    a1 = hs * rng.normal(1.8, 0.08, 12000)
    hd = rng.uniform(2e6, 6e6, 1500)
    a2 = hd * 1.05 * rng.normal(3.4, 0.2, 1500)
    A, H = np.concatenate([a1, a2]), np.concatenate([hs, hd * 1.05])
    f = fcs.FCS(Path("s.fcs"), {"$P1R": "16777216", "$P2R": "16777216"}, ["FSC-A", "FSC-H"],
                ["", ""], {"FSC-A": A, "FSC-H": H})
    _cache[str(Path("s.fcs").resolve())] = f
    v, pct = singlets_gate([Sample("s.fcs")], [np.ones(A.size, bool)])
    inside = Poly(np.array(v)).contains_points(np.column_stack([A, H]))
    assert inside[:12000].mean() > 0.97 and inside[12000:].mean() < 0.05, \
        (inside[:12000].mean(), inside[12000:].mean())
    # viability: compensated data (values below 0: logicle), the dye's dim live cells in,
    # the bright dead ones out; nothing about it without a dye
    live = rng.normal(150, 120, 9000)
    dead = 10 ** rng.normal(4.3, 0.25, 1500)
    dye = np.concatenate([live, dead]).astype(np.float32)
    ssc = rng.uniform(1e4, 2e5, dye.size).astype(np.float32)
    f = fcs.FCS(Path("v.fcs"), {"$P1R": "262144", "$P2R": "262144"}, ["FL4-A", "SSC-A"],
                ["DRAQ7-A", "SSC-A"], {"FL4-A": dye, "SSC-A": ssc})
    _cache[str(Path("v.fcs").resolve())] = f
    e4 = Experiment(samples=[Sample("v.fcs")])
    assert e4.viability_channel() == "FL4-A" and e4.scale("FL4-A").startswith("logicle")
    assert e4.scale("SSC-A", dot=True) == "" and e4.default_marker() == "SSC-A"
    lc = e4.scale("FL4-A")
    v, pct = live_gate(e4.samples, [np.ones(dye.size, bool)], "FL4-A", lc)
    m = Gate(LIVE, "", "polygon", "FL4-A", "SSC-A", v, xs=lc).mask(f, np.ones(dye.size, bool))
    assert m[:9000].mean() > 0.97 and m[9000:].mean() < 0.03, (m[:9000].mean(), m[9000:].mean())
    assert 80 < pct < 90, pct
    tri = [[1e2, 1e4], [1e5, 1e4], [1e5, 1.9e5]]          # straight on logicle, not in values
    g_lin, g_lc = Gate("t", "", "polygon", "FL4-A", "SSC-A", tri), \
        Gate("t", "", "polygon", "FL4-A", "SSC-A", tri, xs="logicle")
    one = np.ones(dye.size, bool)
    assert g_lin.mask(f, one).sum() != g_lc.mask(f, one).sum()
    assert not Experiment().viability_channel()
    # two runs of one cell line: their folders' names differ by a space or a dash
    e3 = Experiment(samples=[Sample("a.fcs", group="MDA-MB-157 parental cells"),
                             Sample("b.fcs", group="MDA-MB-157-parental cells"),
                             Sample("c.fcs", group="MDA-MB-157-mCDCP1")])
    assert e3.same_named() == {"MDA-MB-157-parental cells": "MDA-MB-157 parental cells"}
    e3.aliases = {"group": {"MDA-MB-157-parental cells": "MDA-MB-157 parental cells"}}
    assert e3.pool("MDA-MB-157 parental cells") == ["MDA-MB-157 parental cells",
                                                    "MDA-MB-157-parental cells"]
    # the file (FORMATS.md): its header first, written whole; its id kept by every save; a
    # version-1 file opens; a newer one, or another app's, is refused
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "e.json"
        Experiment(marker="FL2-A").save(p)
        d = jsonfile.read(p)
        assert list(d)[:3] == ["format", "format_version", "id"] and "flowless" not in d, list(d)
        e5, _ = Experiment.open(p)
        e5.save(p)
        assert jsonfile.read(p)["id"] == d["id"] and e5.marker == "FL2-A"
        assert not Path(tmp, "e.json.part").exists()
        p.write_text(json.dumps({"flowless": "2026.10.16", "marker": "FL1-A"}), encoding="utf-8")
        assert Experiment.open(p)[0].marker == "FL1-A", "version 1"
        for bad, why in (({**d, "format_version": 3}, "newer"), ({"x": 1}, "not a Flowless")):
            p.write_text(json.dumps(bad), encoding="utf-8")
            try:
                Experiment.open(p)
                raise AssertionError(bad)
            except ValueError as ex:
                assert why in str(ex), ex
    print("model self-check", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        rest = [a for a in sys.argv[1:] if not a.startswith("--")]
        raise SystemExit(self_check(Path(rest[0]) if rest else
                                    Path(__file__).resolve().parents[3] / "data" / "data"))
