"""FlowJo workspace (.wsp, v10) -> the gates of each sample, so an analysis done in FlowJo
opens here with the same populations.

Read: polygon and rectangle / range gates (Gating-ML 2.0, what FlowJo writes), nested.
Not read: ellipses, quadrants, Boolean gates, FlowJo's own statistics (it recomputes them).
"""

from __future__ import annotations

import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

GATING = "{http://www.isac-net.org/std/Gating-ML/v2.0/gating}"
DATATYPES = "{http://www.isac-net.org/std/Gating-ML/v2.0/datatypes}"


def _tag(e) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _gate(pop) -> dict | None:
    g = pop.find("Gate")
    if g is None or not len(g):
        return None
    shape = g[0]
    dims = [d.get(f"{DATATYPES}name") for d in shape.iter() if _tag(d) == "fcs-dimension"]
    kind = _tag(shape)
    if kind == "PolygonGate" and len(dims) == 2:
        verts = [[float(c.get(f"{DATATYPES}value")) for c in v if _tag(c) == "coordinate"]
                 for v in shape if _tag(v) == "vertex"]
        return {"kind": "polygon", "x": dims[0], "y": dims[1], "vertices": verts}
    if kind == "RectangleGate":
        lims = []
        for d in shape:
            if _tag(d) != "dimension":
                continue
            lo, hi = d.get(f"{GATING}min"), d.get(f"{GATING}max")
            lims.append((float(lo) if lo else None, float(hi) if hi else None))
        if len(dims) == 1:
            return {"kind": "range", "x": dims[0], "lo": lims[0][0], "hi": lims[0][1]}
        if len(dims) == 2:                               # a rectangle is a 4-vertex polygon
            (x0, x1), (y0, y1) = lims
            big = 1e12
            x0, y0 = (x0 if x0 is not None else -big), (y0 if y0 is not None else -big)
            x1, y1 = (x1 if x1 is not None else big), (y1 if y1 is not None else big)
            return {"kind": "polygon", "x": dims[0], "y": dims[1],
                    "vertices": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}
    return None


def _walk(node, parent: str, out: list, skipped: list) -> None:
    subs = node.find("Subpopulations")
    if subs is None:
        return
    for pop in subs.findall("Population"):
        name = pop.get("name", "?")
        g = _gate(pop)
        if g is None:
            skipped.append(name)
            continue
        out.append({"name": name, "parent": parent, **g,
                    "flowjo_count": int(pop.get("count", -1))})
        _walk(pop, name, out, skipped)


def read(path) -> list[dict]:
    """[{"file": name, "uri": the path FlowJo had, "count": events, "gates": [population…],
    "skipped": [names of gates of a kind not read]}…]. A population's parent is "" for the
    root (all events). The same file name can come twice (two folders): match on the uri."""
    root = ET.parse(path).getroot()
    out = []
    for s in root.iter("Sample"):
        ds, node = s.find("DataSet"), s.find("SampleNode")
        if ds is None or node is None:
            continue
        uri = urllib.parse.unquote(ds.get("uri", ""))
        gates, skipped = [], []
        _walk(node, "", gates, skipped)
        out.append({"file": uri.rsplit("/", 1)[-1] or node.get("name", ""), "uri": uri,
                    "count": int(node.get("count", -1)), "gates": gates, "skipped": skipped})
    return out


def match(uri: str, paths) -> Path | None:
    """The loaded file FlowJo's *uri* means: the one sharing the most trailing path parts
    (file name at least), None when no file has its name."""
    want = [p.lower() for p in uri.replace("\\", "/").split("/") if p][::-1]
    best, score = None, 0
    for p in paths:
        have = [x.lower() for x in Path(p).parts][::-1]
        n = 0
        while n < min(len(want), len(have)) and want[n] == have[n]:
            n += 1
        if n > score:
            best, score = Path(p), n
    return best


def apply(exp, wsp) -> list[str]:
    """The gates of a workspace, for the groups whose samples it holds. FlowJo gates each
    file; here a group shares one tree: every population any of its files has, the first
    file's version of it; a later file whose version differs keeps it as its own gate.
    Returns the log."""
    from dataclasses import asdict

    from ..model import Gate

    log, done = [], {}
    samples = {str(Path(s.path).resolve()): s for s in exp.samples}
    for ws in read(wsp):
        p = match(ws["uri"], samples)
        s = samples.get(str(p)) if p else None
        if s is None or not ws["gates"]:
            continue
        if ws["count"] >= 0 and ws["count"] != s.fcs.n:
            log.append(f"⚠ {s.name}: the workspace had {ws['count']} events, the file "
                       f"{s.fcs.n} - another file of that name; skipped")
            continue
        if s.group not in done:
            done[s.group] = {}
            exp.gates[s.group] = []
        tree = done[s.group]
        s.gates = {}
        for g in ws["gates"]:
            new = Gate(**{k: g[k] for k in Gate.__dataclass_fields__ if k in g})
            if g["name"] not in tree:
                tree[g["name"]] = s.name
                exp.gates[s.group].append(new)
                continue
            mine = next(x for x in exp.gates[s.group] if x.name == g["name"])
            if asdict(new) != asdict(mine):
                s.gates[g["name"]] = new
                log.append(f"✓ {s.group} › {g['name']}: {s.name} keeps its own gate "
                           f"(differs from {tree[g['name']]}'s, the group's)")
        if ws["skipped"]:
            log.append(f"⚠ {s.group}: gates not read: {', '.join(ws['skipped'])}")
        ms = exp.masks(s)
        for g in ws["gates"]:
            if g["name"] in ms and g["flowjo_count"] > 0 and \
                    (tree[g["name"]] == s.name or g["name"] in s.gates):
                n, fj = int(ms[g["name"]].sum()), g["flowjo_count"]
                log.append(f"✓ {s.group} › {g['name']}: {n} events in {s.name} "
                           f"(the workspace: {fj}, {100 * (n - fj) / fj:+.1f} %)")
    if not done:
        log.append("✗ no sample of this workspace is loaded")
    return log


if __name__ == "__main__":
    for s in read(sys.argv[1]):
        print(s["uri"], s["count"])
        for g in s["gates"]:
            print("   ", g["name"], "<", g["parent"] or "all", g["kind"], g["x"], g.get("y", ""),
                  g["flowjo_count"])
