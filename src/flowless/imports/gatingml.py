"""Gating-ML 2.0 (ISAC's standard file for gates, read and written by most flow cytometry
software): the experiment's gates read in and written out. Polygons and ranges (a
one-dimension rectangle; a two-dimension one becomes a polygon), nested by parent_id, on the
files' own scale. Each gate's group and name go in its custom_info (ids must be XML names).
A sample's own version of a gate is not written: the group's is.

Not read: ellipses, quadrants, Boolean gates, and gates on a transformed scale or on
compensated / ratio dimensions - their numbers mean something else here; each is named in
the log.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

GATING = "{http://www.isac-net.org/std/Gating-ML/v2.0/gating}"
DATATYPES = "{http://www.isac-net.org/std/Gating-ML/v2.0/datatypes}"
G, D = GATING.strip("{}"), DATATYPES.strip("{}")


def _tag(e) -> str:
    return e.tag.rsplit("}", 1)[-1]


def shape(e) -> dict | None:
    """A gate element (PolygonGate, RectangleGate) as {kind, x, y, vertices | lo, hi}; None
    for a kind not read."""
    dims = [d.get(f"{DATATYPES}name") for d in e.iter() if _tag(d) == "fcs-dimension"]
    kind = _tag(e)
    if kind == "PolygonGate" and len(dims) == 2:
        verts = [[float(c.get(f"{DATATYPES}value")) for c in v if _tag(c) == "coordinate"]
                 for v in e if _tag(v) == "vertex"]
        return {"kind": "polygon", "x": dims[0], "y": dims[1], "vertices": verts}
    if kind == "RectangleGate":
        lims = []
        for d in e:
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


def _plain(e) -> bool:
    """The gate's dimensions on the raw scale, uncompensated (or FCS-compensated): what a
    gate here is drawn on."""
    for d in e:
        if _tag(d) != "dimension":
            continue
        if d.get(f"{GATING}transformation-ref") or \
                d.get(f"{GATING}compensation-ref", "uncompensated") not in ("uncompensated", "FCS"):
            return False
        if not any(_tag(x) == "fcs-dimension" for x in d):
            return False
    return True


def is_gatingml(path) -> bool:
    try:
        for _, el in ET.iterparse(path, events=("start",)):
            return _tag(el) == "Gating-ML"
    except (ET.ParseError, OSError):
        return False
    return False


def read(path) -> tuple[list[dict], list[str]]:
    """([{name, parent, group, kind, x, y, vertices | lo, hi}], [what was not read]).
    group: the one written in custom_info ('' from another program); parent "" for all
    events."""
    root = ET.parse(path).getroot()
    if _tag(root) != "Gating-ML":
        raise ValueError("not a Gating-ML file")
    gates, skipped, names = [], [], {}
    for e in root:
        gid = e.get(f"{GATING}id")
        if not gid:
            continue
        info = next((x for x in e.iter() if _tag(x) in ("flowless", "quickflow")), None)
        name = info.get("name") if info is not None else gid
        names[gid] = name
        g = shape(e) if _plain(e) else None
        if g is None:
            skipped.append(f"{name} ({_tag(e)}{'' if _plain(e) else ', on a transformed or '
                                                 'compensated scale'})")
            continue
        gates.append({"id": gid, "name": name, "parent_id": e.get(f"{GATING}parent_id", ""),
                      "group": info.get("group", "") if info is not None else "", **g})
    while True:                           # a parent not read: its children can't be either
        ok = {g["id"] for g in gates}
        lost = [g for g in gates if g["parent_id"] and g["parent_id"] not in ok]
        if not lost:
            break
        skipped += [f"{g['name']} (its parent was not read)" for g in lost]
        gates = [g for g in gates if g not in lost]
    for g in gates:
        p = g.pop("parent_id")
        g.pop("id")
        g["parent"] = names[p] if p else ""
    return gates, skipped


def apply(exp, path) -> list[str]:
    """The file's gates into the experiment: a gate written for a group (by Flowless) to
    that group; gates without one (another program's) to every group. Each group read
    gets these gates in place of its own (the samples' own versions dropped). The log."""
    from ..model import Gate

    gates, skipped = read(path)
    if not gates:
        return ["✗ no gate read"] + [f"  not read: {x}" for x in skipped]
    groups = exp.groups()
    by = {}
    for g in gates:
        for grp in ([g["group"]] if g["group"] else groups):
            if grp in groups:
                by.setdefault(grp, []).append(g)
    log = []
    for grp, gs in by.items():
        exp.gates[grp] = [Gate(**{k: g[k] for k in Gate.__dataclass_fields__ if k in g})
                          for g in gs]
        for s in exp.in_group(grp):
            s.gates = {}
        log.append(f"✓ {grp}: {', '.join(g['name'] for g in gs)}")
    missing = sorted({g["group"] for g in gates if g["group"] and g["group"] not in groups})
    if missing:
        log.append(f"⚠ groups not in this experiment, their gates not used: {', '.join(missing)}")
    log += [f"⚠ not read: {x}" for x in skipped]
    return log


def write(exp, path) -> int:
    """Write *exp*'s gates to *path*; returns how many."""
    ET.register_namespace("gating", G)
    ET.register_namespace("data-type", D)
    root = ET.Element(f"{{{G}}}Gating-ML")
    n = 0
    for k, (group, gates) in enumerate(exp.gates.items(), 1):
        ids = {g.name: f"g{k}_{j}_{re.sub(r'[^A-Za-z0-9]+', '_', g.name).strip('_')}"
               for j, g in enumerate(gates, 1)}
        for g in gates:
            if g.kind not in ("polygon", "range"):
                continue
            e = ET.SubElement(root, f"{{{G}}}{'PolygonGate' if g.kind == 'polygon' else 'RectangleGate'}",
                              {f"{{{G}}}id": ids[g.name]})
            if g.parent in ids:
                e.set(f"{{{G}}}parent_id", ids[g.parent])
            info = ET.SubElement(e, f"{{{D}}}custom_info")
            ET.SubElement(info, "flowless", group=group, name=g.name)
            for ch in [g.x, g.y] if g.kind == "polygon" else [g.x]:
                d = ET.SubElement(e, f"{{{G}}}dimension", {f"{{{G}}}compensation-ref": "uncompensated"})
                if g.kind == "range":
                    if g.lo is not None:
                        d.set(f"{{{G}}}min", repr(float(g.lo)))
                    if g.hi is not None:
                        d.set(f"{{{G}}}max", repr(float(g.hi)))
                ET.SubElement(d, f"{{{D}}}fcs-dimension", {f"{{{D}}}name": ch})
            for v in g.vertices if g.kind == "polygon" else []:
                vx = ET.SubElement(e, f"{{{G}}}vertex")
                for c in v:
                    ET.SubElement(vx, f"{{{G}}}coordinate", {f"{{{D}}}value": repr(float(c))})
            n += 1
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    return n


if __name__ == "__main__":
    import sys

    gs, sk = read(sys.argv[1])
    for g in gs:
        print(g["group"] or "(every group)", g["name"], "<", g["parent"] or "all", g["kind"],
              g["x"], g.get("y", ""))
    for x in sk:
        print("not read:", x)
