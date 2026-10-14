"""Other programs' files, read into an experiment. The experiment's own formats are the FCS
files and its .json; these are best-effort readers kept apart, each in its module:

gatingml Gating-ML 2.0 (.xml), the standard for gates: read, and written (the only export)
flowjo   a FlowJo workspace (.wsp): its gates (read, not named in the window)
sheet    a procedure sheet (.xlsx, free-form as written at the bench): steps, reagents,
         each tube's condition
"""

from __future__ import annotations

from pathlib import Path


def kind(p: Path) -> str:
    """What a dropped / opened path is: fcs, experiment, gatingml, gates (a workspace),
    sheet, or ''."""
    ext = p.suffix.lower()
    if p.is_dir() or ext == ".fcs":
        return "fcs"
    if ext == ".xml":
        from . import gatingml
        return "gatingml" if gatingml.is_gatingml(p) else ""
    return {".json": "experiment", ".wsp": "gates", ".xlsx": "sheet", ".xlsm": "sheet"}.get(ext, "")


FILTER = ("Everything QuickFlow reads (*.fcs *.json *.xml *.wsp *.xlsx *.xlsm);;FCS (*.fcs);;"
          "QuickFlow experiment (*.json);;Gates, Gating-ML 2.0 (*.xml)")
