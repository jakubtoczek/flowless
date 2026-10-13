"""What was done, recorded with the data: the experiment's fields, each group's cells, the
reagents, the procedure's steps, and per sample what went in its tube. No Qt.
"""

from __future__ import annotations

import re

from . import fcs

GENERAL = ["title", "date", "operator", "project", "aim", "comment"]
GROUP_FIELDS = ["cell line", "origin / transfection", "treatment", "detachment", "cells / tube",
                "note"]
SAMPLE_FIELDS = ["condition", "primary", "primary µL", "secondary", "secondary µL", "cells",
                 "note"]
REAGENT_FIELDS = ["name", "kind", "target", "fluorochrome", "supplier", "catalog #", "lot",
                  "MW (Da)", "stock (mg/mL)", "per tube", "dilution"]
REAGENT_KINDS = ["primary", "secondary", "viability dye", "isotype control", "buffer", "other"]
HINT = {"title": "what this experiment is", "date": "taken from the files when empty",
        "operator": "who did it", "project": "grant, study…",
        "aim": "the question it answers (MIFlowCyt 1.1)", "comment": "anything else",
        "cell line": "MDA-MB-157, PC3…", "origin / transfection": "parental, hCDCP1 transfected…",
        "treatment": "doxorubicin 1 µM 24 h…", "detachment": "cell dissociation buffer, trypsin…",
        "cells / tube": "250 000"}
# targets that make an antibody a secondary: a tag, or another species' antibodies
TAGS = {"his": "His-tag", "myc": "Myc-tag", "flag": "FLAG-tag", "ha": "HA-tag",
        "strep": "Strep-tag", "v5": "V5-tag", "gfp": "GFP", "mouse": "mouse IgG",
        "rabbit": "rabbit IgG", "rat": "rat IgG", "goat": "goat IgG", "human": "human IgG",
        "llama": "llama IgG", "alpaca": "alpaca IgG"}


def empty() -> dict:
    return {"general": {k: "" for k in GENERAL}, "groups": {}, "reagents": [],
            "procedure": []}


def clean(rec: dict | None) -> dict:
    """A record read back from a file: what's missing takes its default."""
    out = empty()
    rec = rec if isinstance(rec, dict) else {}
    out["general"].update({k: str(v) for k, v in rec.get("general", {}).items()})
    out["groups"] = {str(g): {k: str(v) for k, v in d.items()}
                     for g, d in rec.get("groups", {}).items() if isinstance(d, dict)}
    out["reagents"] = [{k: str(r.get(k, "")) for k in REAGENT_FIELDS}
                       for r in rec.get("reagents", []) if isinstance(r, dict)]
    out["procedure"] = [str(x) for x in rec.get("procedure", []) if str(x).strip()]
    return out


# --- reagents ---------------------------------------------------------------------------

def parse_reagent(name: str) -> dict:
    """What a reagent's name says: 'Anti his PE' → target His-tag, fluorochrome PE, a
    secondary (it binds a tag). Only what the name holds; nothing for '29A1'."""
    out = {}
    fl = fcs.find_fluor(name)
    if fl:
        out["fluorochrome"] = fl
    m = re.search(r"\banti[\s_-]*([A-Za-z0-9]+)", name, re.I)
    if m:
        t = m.group(1)
        if t.lower() in TAGS:
            out["target"], out["kind"] = TAGS[t.lower()], "secondary"
        elif fl and t.lower() != fl.lower():
            out["target"] = t
    return out


def complete(r: dict) -> dict:
    """The reagent with what its name says filled in where empty."""
    return {**r, **{k: v for k, v in parse_reagent(r.get("name", "")).items() if not r.get(k)}}


def describe(r: dict) -> str:
    """'PE-labelled anti-His-tag secondary antibody'; '' when the fields don't say enough."""
    r = complete(r)
    fl, tg, kind = r.get("fluorochrome", ""), r.get("target", ""), r.get("kind", "")
    if not (fl or tg):
        return ""
    parts = [f"{fl}-labelled" if fl else "", f"anti-{tg}" if tg else "",
             kind if kind in ("primary", "secondary") else "", "antibody" if tg else
             (kind or "reagent")]
    return " ".join(p for p in parts if p)


def fluorochromes(rec: dict) -> set[str]:
    """The channels' names of the fluorochromes in the experiment ({'PE'})."""
    out = set()
    for r in rec.get("reagents", []):
        fl = complete(r).get("fluorochrome", "")
        if fl and fcs.fluor_of(fl):
            out.add(fcs.fluor_of(fl))
    return out


# --- what the files say -----------------------------------------------------------------

def instrument(f: fcs.FCS | None) -> list[tuple[str, str]]:
    """The cytometer as its file describes it, plus the filters known for that model."""
    if f is None:
        return []
    out = [(k, fcs.pick(f.meta, keys)) for k, keys in fcs.INSTRUMENT]
    filt = fcs.FILTERS.get(fcs.pick(f.meta, ("$CYT",)), {})
    det = []
    for i, ch in enumerate(f.channels, 1):
        name = f.meta.get(f"#P{i}DetectorName", "")
        if f.meta.get(f"#P{i}IsFluorescent", "") == "true" and ch.endswith("-A"):
            lam = f.meta.get(f"$P{i}L", "")
            det.append(f"{name} {filt.get(name, '')} ({f.labels[i - 1].removesuffix('-A')}"
                       f"{', ' + lam + ' nm laser' if lam else ''})".replace("  ", " "))
    if det:
        out.append(("detectors", "; ".join(det)))
    sp = fcs.pick(f.meta, ("$SPILLOVER", "SPILL", "$SPILL"))
    if sp:
        v = sp.split(",")
        n = int(v[0]) if v[0].isdigit() else 0
        vals = [float(x) for x in v[1 + n:]] if n else []
        ident = vals and all(abs(x - (1.0 if i % (n + 1) == 0 else 0.0)) < 1e-9
                             for i, x in enumerate(vals))
        out.append(("compensation", "none (identity spillover matrix in the files)" if ident
                    else f"spillover matrix in the files ({n} channels) — not applied here"))
    return [(k, v) for k, v in out if v]


def acquisition(samples) -> list[tuple[str, str]]:
    """The runs as the files describe them: dates, first start to last end, runs, wells,
    events and volume per file, acquisition time, saturated channels."""
    if not samples:
        return []
    fs = [s.fcs for s in samples]
    dates = sorted({fcs.when(f.meta)[:10] for f in fs if fcs.when(f.meta)})
    runs = sorted({fcs.pick(f.meta, ("$PROJ",)) for f in fs} - {""})
    folders = sorted({s.path.replace("\\", "/").rsplit("/", 2)[-2] for s in samples})
    ev = [f.n for f in fs]
    vol = [v for v in (fcs.volume_ul(f.meta) for f in fs) if v]
    sec = [v for v in (fcs.acquired_s(f.meta) for f in fs) if v]
    out = [("files", f"{len(fs)} in {len(folders)} folder{'s' if len(folders) > 1 else ''}"),
           ("date", ", ".join(dates)),
           ("runs", ", ".join(runs)),
           ("events per file", f"{min(ev):,} – {max(ev):,}".replace(",", " ")),
           ("volume per file", f"{min(vol):.0f} – {max(vol):.0f} µL" if vol else ""),
           ("acquisition per file", f"{min(sec):.0f} – {max(sec):.0f} s" if sec else ""),
           ("wells", ", ".join(sorted({fcs.pick(f.meta, ("$WELLID",)) for f in fs} - {""})))]
    return [(k, v) for k, v in out if v]


def miflowcyt(rec: dict, samples, gates: dict) -> list[tuple[str, bool, str]]:
    """The MIFlowCyt items this record can hold: (item, filled?, what fills it)."""
    g = rec["general"]
    groups = {s.group for s in samples}
    reag = rec["reagents"]
    items = [
        ("1.1 purpose", bool(g.get("aim")), "Experiment › aim"),
        ("1.2 keywords / title", bool(g.get("title")), "Experiment › title"),
        ("1.3 date", True, "the files' $DATE"),
        ("1.4 operator", bool(g.get("operator")), "Experiment › operator"),
        ("2.1 sample source (cell line)",
         all(rec["groups"].get(x, {}).get("cell line") for x in groups),
         "Experiment › groups › cell line"),
        ("2.2 treatment", any(rec["groups"].get(x, {}).get("treatment") for x in groups),
         "Experiment › groups › treatment (if any)"),
        ("2.4 reagents: analyte / reporter",
         bool(reag) and all(r.get("name") for r in reag),
         "Experiment › reagents"),
        ("2.4 reagents: manufacturer, catalog #",
         bool(reag) and any(r.get("supplier") and r.get("catalog #") for r in reag),
         "Experiment › reagents"),
        ("3 instrument (model, lasers, filters)", True, "from the files"),
        ("4.1 list-mode data files", True, "the files"),
        ("4.2 compensation", True, "from the files"),
        ("4.3 gating", all(gates.get(x) for x in groups), "the gates of every group"),
        ("procedure", bool(rec["procedure"]), "Experiment › procedure"),
    ]
    return items


if __name__ == "__main__":
    assert describe({"name": "Anti his PE", "kind": "secondary"}) == \
        "PE-labelled anti-His-tag secondary antibody", describe({"name": "Anti his PE"})
    assert parse_reagent("29A1") == {} and fcs.fluor_of("PE-A") == "PE"
    assert fluorochromes({"reagents": [{"name": "anti-his PE"}, {"name": "24E8"}]}) == {"PE"}
    print("record self-check OK")
