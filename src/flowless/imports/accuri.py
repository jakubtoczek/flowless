"""BD Accuri C6 workspace (.ci, a zip): its samples - the FCS files inside, named as in the
instrument's software ($SMNO) - and its polygon gates, with a well's own version where one
was adjusted. Read only, best effort, as FlowJo's .wsp.

The wells with events are written once as FCS files beside the workspace,
<workspace>/<run's start, 20260527_160343>/<name>.fcs, so the samples are files like any
other (an Accuri export's run folder: the names' prefix is the group, PC-1 → PC / 1).
Read: the plots' polygons (CollectPlots.xml), a well's adjusted polygon
(BatchAnalysis.xml). Not read: other region kinds (named in the log), Accuri's statistics.

    python -m flowless.imports.accuri FILE.ci      what it holds
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .. import fcs


def _well(w: str) -> str:
    """'A1' → 'A01' (the plate's name of a well in the FCS files)."""
    m = re.fullmatch(r"([A-H])(\d{1,2})", w.strip())
    return f"{m.group(1)}{int(m.group(2)):02d}" if m else w.strip()


def _points(e) -> list:
    return [[float(p.findtext("x")), float(p.findtext("y"))] for p in e.iter("point")]


def gates(z: zipfile.ZipFile) -> tuple[list[dict], dict, list[str]]:
    """([{name, x, y, xs, ys, vertices}], {well: {gate name: vertices}}, [not read])."""
    out, skipped = [], []
    root = ET.fromstring(z.read("CollectPlots.xml"))
    for plot in root.iter("plotDefinition"):
        x = plot.findtext("xParameterType/parameterName", "")
        y = plot.findtext("yParameterType/parameterName", "")
        sc = {"Log": "log"}
        for b in plot.iter("subsetBundles"):
            for region in b:
                name = region.findtext("customName") or region.findtext("subsetId") or "?"
                if region.tag == "polygon" and y != "Count":
                    out.append({"name": name, "x": x, "y": y, "vertices": _points(region),
                                "xs": sc.get(plot.findtext("xAxisType"), ""),
                                "ys": sc.get(plot.findtext("yAxisType"), "")})
                else:
                    skipped.append(f"{name} ({region.tag} on {x})")
    own = {}
    if "BatchAnalysis.xml" in z.namelist():
        for row in ET.fromstring(z.read("BatchAnalysis.xml")).iter("SampleRow"):
            for tool in row.iter("BatchDefinitionTool"):
                pts = _points(tool)
                if pts:
                    own.setdefault(_well(row.findtext("ID", "")), {})[tool.findtext("ID")] = pts
    return out, own, skipped


def extract(path) -> list[Path]:
    """The workspace's wells with events as FCS files beside it (written once: a file
    already there is kept); in plate order."""
    path = Path(path)
    out = []
    with zipfile.ZipFile(path) as z:
        wells = []
        for info in z.infolist():
            if not info.filename.lower().endswith(".fcs") or info.file_size < 100:
                continue
            raw = z.read(info)
            meta = fcs.text_of(raw)
            if int(meta.get("$TOT", "0") or 0) <= 0:
                continue
            wells.append((_well(meta.get("$WELLID", "")), meta, raw))
        if not wells:
            return []
        m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d)",
                         min(fcs.when(w[1]) for w in wells))
        run = f"{m[1]}{m[2]}{m[3]}_{m[4]}{m[5]}00" if m else path.stem   # the run's start
        folder = path.with_suffix("") / run
        folder.mkdir(parents=True, exist_ok=True)
        for well, meta, raw in sorted(wells, key=lambda w: (w[0][:1], w[0][1:])):
            name = re.sub(r'[<>:"/\\|?*]', "_", meta.get("$SMNO", "").strip() or well)
            p = folder / f"{name}.fcs"
            if p.exists() and fcs.text_of(p.read_bytes()[:65536]).get("$WELLID") != well:
                p = folder / f"{well} {name}.fcs"          # two wells named alike
            if not p.exists():
                p.write_bytes(raw)
            out.append(p)
    return out


def apply(exp, path, added) -> list[str]:
    """The workspace's polygons as the gates of the groups its samples (*added*) are in, a
    well's adjusted version as that sample's own; the log."""
    from dataclasses import asdict

    from ..model import Gate

    with zipfile.ZipFile(path) as z:
        found, own, skipped = gates(z)
    if not found:
        return ["✗ no polygon gate in it"] + [f"  not read: {x}" for x in skipped]
    log = []
    for g in dict.fromkeys(s.group for s in added):
        exp.gates[g] = [Gate(d["name"], "", "polygon", d["x"], d["y"], d["vertices"],
                             xs=d["xs"], ys=d["ys"]) for d in found]
        log.append(f"✓ {g}: {', '.join(d['name'] for d in found)} (on all events)")
        for s in exp.in_group(g):
            s.gates = {}
            mine = own.get(fcs.pick(s.fcs.meta, ("$WELLID",)), {})
            for gate in exp.gates[g]:
                v = mine.get(gate.name)
                if v and v != gate.vertices:
                    s.gates[gate.name] = Gate(**{**asdict(gate), "vertices": v})
                    log.append(f"✓ {g} › {gate.name}: {s.name} keeps its own (adjusted in "
                               "the workspace)")
    log += [f"⚠ not read: {x}" for x in skipped]
    return log


if __name__ == "__main__":
    with zipfile.ZipFile(sys.argv[1]) as z:
        gs, own, sk = gates(z)
    for g in gs:
        print(g["name"], g["x"], "×", g["y"], len(g["vertices"]), "vertices")
    print("own versions:", {w: list(v) for w, v in own.items()})
    print("not read:", sk)
