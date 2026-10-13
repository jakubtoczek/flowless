"""The experiment: samples, gates, statistics. No Qt.

An experiment is a list of samples (FCS files), each in a *group* (a panel on the figure,
a block of the table: the cell line, a treatment) with a *label* (a series: the stain).
Each group has a gate tree: populations, each a gate on its parent ("" = all events) -
a polygon on two channels or a range on one. A sample can have its own version of a gate
(same name, same place in the tree): the group's gate is the default. Every population gets
the same statistics on the *marker* channel. The single-marker analysis (overlay histograms
+ one value per population) is built on that; more markers, quadrants or titrations would
add a gate kind or a statistic, not a new model.

    python -m quickflow.model --self-check [DATA]   counts and values against FlowJo
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

from . import __version__, fcs, record

ROLES = ["sample", "negative control", "secondary only", "unstained"]
CONTROL_ORDER = ["negative control", "secondary only", "unstained"]   # the "÷ control" one
STATS = {"geometric mean": "gmean", "median": "median", "mean": "mean"}
ALL = "All events"
ALIAS_KINDS = ["group", "label", "sample", "channel", "population"]


# --- data -------------------------------------------------------------------------------

_cache: dict[str, fcs.FCS] = {}


def load(path) -> fcs.FCS:
    key = str(Path(path).resolve())
    if key not in _cache:
        _cache[key] = fcs.read(key)
    return _cache[key]


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
        pts = np.column_stack([_piled(x, f.range(self.x), v[:, 0]),
                               _piled(f.data[self.y], f.range(self.y), v[:, 1])])
        return base & Poly(v).contains_points(pts)

    def key(self) -> tuple:
        return (self.name, self.parent, self.kind, self.x, self.y,
                tuple(map(tuple, self.vertices)), self.lo, self.hi)


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

    # -- groups and samples
    def groups(self) -> list[str]:
        return list(dict.fromkeys(s.group for s in self.samples))

    def in_group(self, g: str) -> list[Sample]:
        return [s for s in self.samples if s.group == g]

    def labels(self) -> list[str]:
        """Series in table order, controls first: what fixes each label's colour."""
        order = {r: i for i, r in enumerate(["negative control", "sample", "secondary only",
                                             "unstained"])}
        seen = list(dict.fromkeys(s.label for s in self.samples))
        role = {s.label: s.role for s in self.samples}
        return sorted(seen, key=lambda l: (order.get(role[l], 9), seen.index(l)))

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
        fl = self.fluorescence()
        return fl[0] if fl else (self.all_channels() or [""])[0]

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
        return rows

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
        return {"quickflow": __version__, "marker": self.marker, "stat": self.stat,
                "samples": samples,
                "gates": {g: [asdict(x) for x in gs] for g, gs in self.gates.items()},
                "record": self.record, "figure": self.figure, "aliases": self.aliases,
                "channels": self.channels}

    def save(self, path) -> None:
        self.path = str(Path(path).resolve())
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False),
                              encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict, path: str = "") -> tuple["Experiment", list[str]]:
        """The experiment, and what didn't come back (a file not found, one changed)."""
        e = cls(marker=d.get("marker", ""), stat=d.get("stat", "geometric mean"),
                record=d.get("record", {}), figure=d.get("figure", {}),
                aliases=d.get("aliases", {}), channels=d.get("channels", []), path=path)
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
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if "quickflow" not in d:
            raise ValueError(f"{Path(path).name}: not a QuickFlow experiment")
        return cls.from_dict(d, str(Path(path).resolve()))


def _gate(d) -> Gate:
    return d if isinstance(d, Gate) else Gate(**{k: d[k] for k in Gate.__dataclass_fields__
                                                  if k in d})


def _is_fluo(ch: str, label: str) -> bool:
    return not ch.upper().startswith(("FSC", "SSC", "TIME", "WIDTH")) and \
        not label.upper().startswith(("FSC", "SSC"))


def add_cells_gate(exp: Experiment, group: str, x: str, y: str, verts) -> str:
    """A 'cells' polygon first in the group's tree; gates that were on all events go
    under it."""
    gs = exp.gates.setdefault(group, [])
    name = "cells" if all(g.name != "cells" for g in gs) else "cells 2"
    for g in gs:
        if not g.parent:
            g.parent = name
    gs.insert(0, Gate(name, "", "polygon", x, y, verts))
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


def histogram(v: np.ndarray, top: float, bins: int = 256, smooth: bool = True):
    """Counts per channel on a log scale from 1 to *top* (256 channels, as FlowJo's
    'Count' axis). Returns (bin centres, counts)."""
    hi = math.log10(top) if top > 1 else 7.0
    lv = np.log10(v[v > 0]) if v.size else np.empty(0)
    h, e = np.histogram(lv, bins=bins, range=(0, hi))
    h = h.astype(float)
    if smooth and h.sum():
        k = np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2)
        h = np.convolve(h, k / k.sum(), mode="same")
    return 10 ** ((e[:-1] + e[1:]) / 2), h


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
    print("model self-check", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        rest = [a for a in sys.argv[1:] if not a.startswith("--")]
        raise SystemExit(self_check(Path(rest[0]) if rest else
                                    Path(__file__).resolve().parents[3] / "data" / "data"))
