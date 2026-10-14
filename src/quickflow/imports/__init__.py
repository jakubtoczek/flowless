"""Other programs' files, read into an experiment. The experiment's own formats are the FCS
files and its .json; these are best-effort readers kept apart, each in its module:

flowjo   a FlowJo workspace (.wsp): its gates
sheet    a procedure sheet (.xlsx, free-form as written at the bench): steps, reagents,
         each tube's condition
gatingml the gates written as Gating-ML 2.0 (export only)
"""

from __future__ import annotations

from pathlib import Path


def kind(p: Path) -> str:
    """What a dropped / opened path is: fcs, experiment, gates, sheet, or ''."""
    ext = p.suffix.lower()
    if p.is_dir() or ext == ".fcs":
        return "fcs"
    return {".json": "experiment", ".wsp": "gates", ".xlsx": "sheet", ".xlsm": "sheet"}.get(ext, "")


FILTER = ("Everything QuickFlow reads (*.fcs *.json *.wsp *.xlsx *.xlsm);;FCS (*.fcs);;"
          "QuickFlow experiment (*.json);;FlowJo workspace, its gates (*.wsp);;"
          "Procedure sheet (*.xlsx *.xlsm)")
