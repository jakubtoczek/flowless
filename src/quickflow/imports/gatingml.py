"""Gating-ML 2.0 (ISAC's standard file for gates, read by most flow cytometry software): the
experiment's gates written out. Polygons and ranges (a one-dimension rectangle), nested by
parent_id, on the files' own scale (no transformation), uncompensated. Each gate's group and
name are in its custom_info (ids must be XML names). A sample's own version of a gate is not
written: the group's is.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .flowjo import DATATYPES, GATING

G, D = GATING.strip("{}"), DATATYPES.strip("{}")


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
            ET.SubElement(info, "quickflow", group=group, name=g.name)
            for i, ch in enumerate([g.x, g.y] if g.kind == "polygon" else [g.x]):
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
