"""An artificial experiment, to try what the bench's data don't have: compensated values
(below 0: a logicle axis), a viability dye, replicate runs. Known truth, written as FCS 3.1.

    python misc/make_artificial.py [OUT]      (default: ../data/artificial)

compensated/  a FACSCanto-like cytometer, float values already compensated (negatives),
              18-bit scale; DRAQ7 read on APC-A, its channel named for it ($PnS DRAQ7-A):
              found without being recorded. Two runs, two cell lines, six tubes each.
accuri-like/  an Accuri C6-like one (integers, 16 777 216 scale, nothing below 0); DRAQ7 on
              FL4-A, named APC-A: seen only once recorded as a reagent (its .json does);
              dropped as a folder, nothing about viability shows.
<kind>.json   each, set up: roles, the reagents, the auto gates; the live gate left to you.

Every tube: debris, live singlets, dead cells (smaller, more granular - the minor FSC × SSC
cluster - DRAQ7-bright, sticky: a dim PE stain), doublets. TRUTH.txt has the numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

N = 12000
TUBES = {"unstained": 0.0, "secondary only": 1.9, "isotype": 2.0,          # PE, log10 MFI
         "Ab1": 3.0, "Ab2": 3.7, "Ab3": 4.4}
PARENTAL = {"Ab1": 2.1, "Ab2": 2.4, "Ab3": 3.3}                            # less target
FRACTIONS = {"debris": 0.06, "live": 0.72, "dead": 0.14, "doublets": 0.08}


def write_fcs(path: Path, channels: list[tuple[str, str, np.ndarray]], meta: dict,
              ints: bool = False, top: float = 262144.0) -> None:
    """FCS 3.1, list mode: float32 little-endian (*ints*: 32-bit big-endian integers, as
    an Accuri writes)."""
    data = np.column_stack([a for _, _, a in channels])
    raw = (np.clip(np.round(data), 0, top - 1).astype(">u4") if ints
           else data.astype("<f4")).tobytes()
    kw = {"$BYTEORD": "4,3,2,1" if ints else "1,2,3,4", "$DATATYPE": "I" if ints else "F",
          "$MODE": "L", "$NEXTDATA": "0", "$PAR": str(len(channels)), "$TOT": str(len(data)),
          "$BEGINANALYSIS": "0", "$ENDANALYSIS": "0", "$BEGINSTEXT": "0", "$ENDSTEXT": "0",
          **meta}
    for i, (name, label, _) in enumerate(channels, 1):
        kw.update({f"$P{i}N": name, f"$P{i}S": label, f"$P{i}B": "32", f"$P{i}E": "0,0",
                   f"$P{i}R": str(int(top))})
    kw["$BEGINDATA"] = kw["$ENDDATA"] = "0" * 12          # fixed width: the TEXT's length
    text = "|" + "".join(f"{k}|{v}|" for k, v in kw.items())
    t0 = 58
    d0 = t0 + len(text.encode())
    kw["$BEGINDATA"], kw["$ENDDATA"] = f"{d0:012d}", f"{d0 + len(raw) - 1:012d}"
    text = ("|" + "".join(f"{k}|{v}|" for k, v in kw.items())).encode()
    head = f"FCS3.1    {t0:>8}{t0 + len(text) - 1:>8}{d0:>8}{d0 + len(raw) - 1:>8}{0:>8}{0:>8}"
    path.write_bytes(head.encode() + text + raw)


def tube(rng, pe_log: float, gain: float, scatter: float, accuri: bool):
    """One tube's events: (channels, how many of each kind)."""
    n = {k: int(N * f) for k, f in FRACTIONS.items()}
    k = scatter                                     # the scatter channels' scale
    fsc = np.concatenate([rng.exponential(12e3, n["debris"]),
                          rng.normal(110e3, 18e3, n["live"]),
                          rng.normal(70e3, 15e3, n["dead"]),
                          2 * rng.normal(110e3, 18e3, n["doublets"])]) * k
    ssc = np.concatenate([rng.exponential(10e3, n["debris"]),
                          rng.normal(60e3, 14e3, n["live"]),
                          rng.normal(88e3, 18e3, n["dead"]),
                          1.6 * rng.normal(60e3, 14e3, n["doublets"])]) * k
    ratio = np.concatenate([rng.normal(0.78, 0.03, n["debris"] + n["live"] + n["dead"]),
                            rng.normal(0.47, 0.03, n["doublets"])])  # height / area
    fsch = fsc * ratio
    live = n["debris"] + n["live"]                  # debris: no dye either
    m = len(fsc)
    spread = 30.0 if accuri else 110.0              # around 0 after compensation
    bright = 10 ** (rng.normal(4.2, 0.25, m - live) + (0.8 if accuri else 0))   # dead
    dim = 10 ** rng.normal(2.5, 0.2, live) if accuri else rng.normal(0, spread, live)
    dye = np.concatenate([dim, bright])
    stain = rng.normal(pe_log + np.log10(gain), 0.25, m) if pe_log else np.full(m, -9.0)
    auto = 10 ** rng.normal(2.0 if accuri else 1.6, 0.3, m)
    pe = 10 ** stain + auto * (1 if accuri else 0.3)
    pe[n["debris"] + n["live"]:n["debris"] + n["live"] + n["dead"]] += \
        10 ** rng.normal(3.3, 0.3, n["dead"]) * (gain if pe_log else 0.3)    # sticky dead cells
    if not accuri:
        pe = pe + rng.normal(0, spread, m)
    fitc = (10 ** rng.normal(2.0, 0.3, m)) if accuri else rng.normal(0, 60, m)
    order = rng.permutation(m)
    t = np.sort(rng.uniform(0, 3000, m))
    if accuri:
        top = 16777216.0
        fsc = np.minimum(fsc, top - 1)              # big cells off the scale, as on an Accuri
        ch = [("FSC-A", "FSC-A", fsc), ("SSC-A", "SSC-A", ssc), ("FL1-A", "FITC-A", fitc),
              ("FL2-A", "PE-A", pe), ("FL3-A", "PerCP-A", auto * 0.5),
              ("FL4-A", "APC-A", dye), ("FSC-H", "FSC-H", fsch), ("SSC-H", "SSC-H", ssc * 0.8),
              ("FL1-H", "FITC-H", fitc * 0.8), ("FL2-H", "PE-H", pe * 0.8),
              ("FL3-H", "PerCP-H", auto * 0.4), ("FL4-H", "APC-H", dye * 0.8),
              ("Width", "Width", rng.normal(900, 80, m)), ("Time", "Time", t)]
    else:
        ch = [("FSC-A", "FSC-A", fsc), ("FSC-H", "FSC-H", fsch), ("SSC-A", "SSC-A", ssc),
              ("SSC-H", "SSC-H", ssc * 0.8), ("FITC-A", "FITC-A", fitc),
              ("PE-A", "PE-A", pe), ("APC-A", "DRAQ7-A", dye), ("Time", "Time", t)]
    return [(a, b, np.asarray(c, float)[order]) for a, b, c in ch], n


def main(out: Path) -> int:
    from flowless import model, record

    rng = np.random.default_rng(20261016)
    truth = ["Artificial experiment (misc/make_artificial.py) - the numbers it was made with.",
             f"{N} events a tube: " + ", ".join(f"{k} {100 * v:.0f} %" for k, v in
                                                 FRACTIONS.items()),
             "PE (the stain), log10 of the live cells' median, before the run's gain:"]
    truth += [f"  {t}: transfected {v:g}, parental {PARENTAL.get(t, v):g}" for t, v in
              TUBES.items() if v]
    truth += ["Dead cells: DRAQ7 ~10^4.2 (compensated) / 10^5 (accuri-like), and a dim PE "
              "stain (10^3.3) whatever the tube: what a live gate leaves out.", ""]
    runs = [("compensated", "20261001_140000", "Line-A", 1.00, False),
            ("compensated", "20261008_141500", "Line A", 1.15, False),
            ("accuri-like", "20261015_100000", "Line B", 1.00, True)]
    for kind, run, line, gain, accuri in runs:
        for grp, table in ((f"{line} parental", PARENTAL), (f"{line} transfected", TUBES)):
            folder = out / kind / run / grp
            folder.mkdir(parents=True, exist_ok=True)
            for k, (name, pe) in enumerate(TUBES.items()):
                if accuri and name == "isotype":
                    continue
                chans, n = tube(rng, table.get(name, pe), gain, 60.0 if accuri else 1.0, accuri)
                day = f"{run[6:8]}-OCT-{run[:4]}"
                start = f"{run[9:11]}:{int(run[11:13]) + k:02d}:00"
                write_fcs(folder / f"{name}.fcs", chans,
                          {"$CYT": "Accuri-like (artificial)" if accuri else
                           "Artificial cytometer (compensated)", "$DATE": day,
                           "$BTIM": start, "$ETIM": start, "$FIL": f"{name}.fcs",
                           "$SMNO": name, "$PROJ": f"artificial {run}",
                           "#FLOWLESS": "artificial data: values " +
                           ("as acquired" if accuri else "already compensated")},
                          ints=accuri, top=16777216.0 if accuri else 262144.0)
            truth.append(f"{kind}/{run}/{grp}: gain ×{gain:g}")
    (out / "TRUTH.txt").write_text("\n".join(truth) + "\n", encoding="utf-8")
    # each part an experiment, set up: roles (isotype: the negative control), reagents
    # (DRAQ7 recorded for the accuri-like one: its channel isn't named for it), auto gates
    for kind in ("compensated", "accuri-like"):
        exp = model.Experiment(record=record.empty())
        exp.add([out / kind], negatives=["isotype"])
        for g in exp.groups():
            if g.startswith("Line-A"):                # the two runs: replicates
                exp.aliases.setdefault("group", {})[g] = g.replace("Line-A", "Line A")
            v = model.auto_gate(exp.in_group(g), "FSC-A", "SSC-A")
            if v:
                model.add_cells_gate(exp, g, "FSC-A", "SSC-A", v)
        rec = exp.record
        rec["general"].update(title=f"Artificial experiment, {kind}", aim="logicle axes, a "
                              "viability dye, replicate runs, on data of known truth")
        reagents = [{"name": f"Ab{i}", "kind": "sample", "fluorochrome": "PE"} for i in (1, 2, 3)]
        if kind == "accuri-like":
            reagents.append({"name": "DRAQ7", "kind": "viability dye", "fluorochrome": "DRAQ7",
                             "supplier": "(artificial)", "per tube": "3 µM"})
        rec["reagents"] = [{k: r.get(k, "") for k in record.REAGENT_FIELDS} for r in reagents]
        exp.marker = exp.default_marker()
        exp.save(out / f"{kind}.json")
        print(f"{kind}: {len(exp.samples)} files, {len(exp.groups())} groups, marker "
              f"{exp.marker}, viability dye on {exp.viability_channel() or '-'}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(main(Path(args[0]) if args else ROOT.parent / "data" / "artificial"))
