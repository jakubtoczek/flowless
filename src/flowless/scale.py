"""A channel's axis: linear (the scatter channels), log (fluorescence), or logicle when the
files hold negative values (compensated data, where a log axis would drop them). No Qt, no
matplotlib.

Display units: the value itself (lin), decades (log), logicle decades (Parks et al. 2006,
Cytometry A 69:541: linear around 0, log above). A logicle scale is named with its width
W, 'logicle 0.65' (decades of its linear part; from the data: logicle()), so a gate drawn
on it keeps its sides straight there whatever is added later: its mask is taken in these
units (model.Gate.mask).

    python -m flowless.scale      self-check
"""

from __future__ import annotations

import functools
import math

import numpy as np

W, M = 0.5, 4.5                  # FlowJo's defaults: width (a bare 'logicle'), decades
LN10 = math.log(10)


def logicle(top: float, r: float) -> str:
    """The logicle scale for data whose negatives reach *r* (their 5th percentile): W =
    (M - log10(T / |r|)) / 2 (Parks 2006, eq. 13), in 0.05 steps, 0 to 2 decades."""
    w = (M - math.log10(top / abs(r))) / 2 if r < 0 and top > 0 else 0.0
    return f"logicle {min(max(round(w * 20) / 20, 0.0), 2.0):g}"


def _w(kind: str) -> float:
    return float(kind.split()[1]) if " " in kind else W


@functools.lru_cache(maxsize=32)
def _logicle(top: float, width: float) -> tuple[np.ndarray, np.ndarray]:
    """(values, display) on a dense grid: the logicle function is display -> value; the
    other way is read off the grid by interpolation (monotone, 1e-6 relative)."""
    w, m = max(width, 1e-6) * LN10, M * LN10
    lo, hi = 1.0, 10.0                         # p: w = 2 p ln p / (p + 1)
    for _ in range(60):
        p = (lo + hi) / 2
        lo, hi = (p, hi) if 2 * p * math.log(p) / (p + 1) < w else (lo, p)

    def s(y):
        return top * math.exp(-(m - w)) * (np.exp(y - w) - p * p * np.exp(-(y - w) / p)
                                           + p * p - 1)

    y = np.linspace(-0.05 * m, m, 8193)        # a little below the axis: the editor's edge
    return np.where(y >= w, s(y), -s(2 * w - y)), y / LN10


def forward(kind: str, v, top: float):
    """Values to display units (vertices: unclipped)."""
    v = np.asarray(v, float)
    if kind == "log":
        return np.log10(np.maximum(v, 1e-6))
    if kind.startswith("logicle"):
        x, d = _logicle(top, _w(kind))
        return np.interp(v, x, d)
    return v


def events(kind: str, v, top: float):
    """Events to display units, the ones below the axis on its bottom edge: a corner put
    outside the plot takes them (the top edge: model._piled)."""
    d = forward(kind, v, top)
    return np.maximum(d, 0.0) if kind else d


def inverse(kind: str, d, top: float):
    d = np.asarray(d, float)
    if kind == "log":
        return 10.0 ** d
    if kind.startswith("logicle"):
        x, dd = _logicle(top, _w(kind))
        return np.interp(d, dd, x)
    return d


def span(kind: str, top: float) -> float:
    """The axis' length in display units (log: decades from 1)."""
    if kind.startswith("logicle"):
        return M
    return math.log10(top) if kind == "log" and top > 1 else top


def ticks(kind: str, top: float) -> tuple[list, list, list]:
    """(major values, their labels, minor values) for a logicle axis: 0 and the decades
    either side; labelled from 0 outwards where a label doesn't crowd another (0.35
    decade apart)."""
    lo = float(inverse(kind, 0.0, top))
    major = sorted([0.0] + [s * 10.0 ** k for k in range(1, 10) for s in (1, -1)
                            if lo <= s * 10.0 ** k <= top])
    d = {v: float(forward(kind, v, top)) for v in major}
    kept = []
    for v in sorted(major, key=abs):
        if all(abs(d[v] - d[k]) >= 0.35 for k in kept):
            kept.append(v)
    labels = [("0" if v == 0 else
               rf"$\mathdefault{{{'-' if v < 0 else ''}10^{{{round(math.log10(abs(v)))}}}}}$")
              if v in kept else "" for v in major]
    minor = [s * k * 10.0 ** e for e in range(1, 9) for s in (1, -1)
             if abs(float(forward(kind, s * 10.0 ** (e + 1), top) -
                          forward(kind, s * 10.0 ** e, top))) >= 0.6     # a log-like decade
             for k in range(2, 10) if lo <= s * k * 10.0 ** e <= top]
    return major, labels, minor


if __name__ == "__main__":
    T = 262144.0
    v = np.array([-100.0, -10, 0, 10, 100, 1e3, 1e4, 1e5, T])
    back = inverse("logicle", forward("logicle", v, T), T)
    assert np.allclose(back, v, rtol=1e-4, atol=1e-3), back
    d = forward("logicle", v, T)
    assert np.all(np.diff(d) > 0) and abs(d[-1] - M) < 0.01, d       # monotone, T at the top
    assert -150 < inverse("logicle", 0.0, T) < -50                    # FlowJo's W 0.5: ~ -111
    assert logicle(T, -181.0) == "logicle 0.65" and logicle(T, -1.0) == "logicle 0"
    k = logicle(T, -1000.0)
    assert inverse(k, 0.0, T) < -1000, inverse(k, 0.0, T)          # r is on the axis
    assert np.allclose(inverse(k, forward(k, v, T), T), v, rtol=1e-4, atol=1e-3)
    assert abs(forward("log", 1e4, T) - 4) < 1e-12 and events("log", [-5.0], T)[0] == 0
    mj, lab, mn = ticks("logicle", T)
    assert 0.0 in mj and 1e5 in mj and lab[mj.index(1e5)] and mn
    print("scale self-check OK")
