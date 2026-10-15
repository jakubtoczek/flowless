"""FCS 2.0 / 3.0 / 3.1 list-mode reader: the TEXT keywords and the events, one array per
channel. numpy only.

    python -m flowless.fcs FILE.fcs      prints the keywords and the channels
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class FCS:
    path: Path
    meta: dict[str, str]                 # every TEXT keyword, as written ($ and # kept)
    channels: list[str]                  # $PnN, in file order
    labels: list[str]                    # $PnS ("PE-A"), "" when absent
    data: dict[str, np.ndarray] = field(repr=False)   # channel -> float64 events

    @property
    def n(self) -> int:
        return len(next(iter(self.data.values()))) if self.data else 0

    def label(self, ch: str) -> str:
        """'FL2-A :: PE-A', as FlowJo writes it; the bare name when there's no $PnS."""
        s = self.labels[self.channels.index(ch)] if ch in self.channels else ""
        return f"{ch} :: {s}" if s and s != ch else ch

    def range(self, ch: str) -> float:
        """$PnR, the top of the channel's scale (16777216 on an Accuri C6)."""
        i = self.channels.index(ch) + 1
        try:
            return float(self.meta.get(f"$P{i}R", "0"))
        except ValueError:
            return 0.0


def _text(raw: bytes) -> dict[str, str]:
    """The TEXT segment: first byte is the delimiter; a doubled delimiter is a literal one."""
    s = raw.decode("utf-8", errors="replace")
    d = s[0]
    s = s[1:].replace(d + d, "\0")
    parts = [p.replace("\0", d) for p in s.split(d)]
    if parts and parts[-1] == "":
        parts.pop()
    return {k.strip(): v.strip() for k, v in zip(parts[0::2], parts[1::2])}


def read(path) -> FCS:
    path = Path(path)
    b = path.read_bytes()
    if not b[:3] == b"FCS":
        raise ValueError(f"{path.name}: not an FCS file")
    head = b[:58].decode("ascii", errors="replace")
    t0, t1, d0, d1 = (int(head[a:a + 8].strip() or 0) for a in (10, 18, 26, 34))
    meta = _text(b[t0:t1 + 1])
    up = {k.upper(): v for k, v in meta.items()}
    if not d0 or not d1:                          # > 99,999,999 bytes: offsets only in TEXT
        d0, d1 = int(up.get("$BEGINDATA", 0)), int(up.get("$ENDDATA", 0))
    if up.get("$MODE", "L") != "L":
        raise ValueError(f"{path.name}: $MODE {up.get('$MODE')} - only list mode is read")
    npar = int(up["$PAR"])
    tot = int(up.get("$TOT", 0))
    dt = up.get("$DATATYPE", "F")
    order = up.get("$BYTEORD", "1,2,3,4").replace(" ", "")
    end = "<" if order in ("1,2,3,4", "1,2", "1,2,3,4,5,6,7,8") else ">"
    names = [up.get(f"$P{i}N", f"P{i}") for i in range(1, npar + 1)]
    labels = [up.get(f"$P{i}S", "") for i in range(1, npar + 1)]
    bits = [int(up.get(f"$P{i}B", "32")) for i in range(1, npar + 1)]
    raw = b[d0:d1 + 1]

    if dt in ("F", "D"):
        a = np.frombuffer(raw, dtype=f"{end}{'f4' if dt == 'F' else 'f8'}")
    elif dt == "I" and len(set(bits)) == 1 and bits[0] in (8, 16, 32, 64):
        a = np.frombuffer(raw, dtype=f"{end}u{bits[0] // 8}")
    else:
        # ponytail: mixed / odd integer widths (rare outside old instruments) not read;
        # flowio handles them if one turns up
        raise ValueError(f"{path.name}: $DATATYPE {dt} with $PnB {sorted(set(bits))} not read")
    tot = tot or len(a) // npar
    a = a[: tot * npar].reshape(tot, npar).astype(np.float64)
    if dt == "I":                                 # $PnR masks the unused high bits
        for j, i in enumerate(range(1, npar + 1)):
            r = float(up.get(f"$P{i}R", "0") or 0)
            if r and r < 2 ** bits[j] and (int(r) & (int(r) - 1)) == 0:
                a[:, j] = np.mod(a[:, j], r)
    return FCS(path, meta, names, labels, {n: a[:, j] for j, n in enumerate(names)})


# what the report and the sample table show from an instrument's keywords, label: keys
INSTRUMENT = [("cytometer", ("$CYT",)), ("serial number", ("$CYTSN",)),
              ("software", ("#SoftwareVersion", "CREATOR", "$CREATOR")),
              ("lasers", ("#LASERCONFIGURATION",)),
              ("threshold", ("$TR",)), ("secondary threshold", ("#SECONDARYTHRESHOLD",))]
ACQUISITION = [("date", ("$DATE",)), ("start", ("$BTIM",)), ("end", ("$ETIM",)),
               ("well", ("$WELLID", "WELL ID")), ("original name", ("$FIL",)),
               ("run", ("$PROJ",))]

# filters the files don't carry; by the instrument's $CYT
FILTERS = {"BD Accuri C6 Plus": {"FL1": "533/30", "FL2": "585/40", "FL3": "670 LP",
                                 "FL4": "675/25"},
           "BD Accuri C6": {"FL1": "533/30", "FL2": "585/40", "FL3": "670 LP",
                            "FL4": "675/25"}}


# fluorochromes, by the name a cytometer gives the channel they're read on ($PnS "PE-A");
# the first name is that channel's
FLUORS = [["FITC", "GFP", "AF488", "Alexa Fluor 488", "CFSE"],
          ["PE", "R-PE", "PI"],
          ["PerCP", "PerCP-Cy5.5", "PE-Cy5", "7-AAD"],
          ["APC", "AF647", "Alexa Fluor 647", "DRAQ7"],
          ["PE-Cy7"], ["APC-Cy7"], ["BV421"], ["DAPI"]]


def fluor_of(name: str) -> str:
    """'PE-A' → 'PE', 'Alexa Fluor 488' → 'FITC': the channel name a fluorochrome is read
    as; '' if none."""
    n = re.sub(r"-[AHW]$", "", name.strip(), flags=re.I).lower()
    for names in FLUORS:
        if n in (x.lower() for x in names):
            return names[0]
    return ""


def find_fluor(text: str) -> str:
    """The fluorochrome a reagent's name holds: 'Anti his PE' → 'PE' (longest names first,
    whole words)."""
    names = sorted((x for ns in FLUORS for x in ns), key=len, reverse=True)
    for x in names:
        if re.search(rf"(?<![\w-]){re.escape(x)}(?![\w-])", text, re.I):
            return x
    return ""


def when(meta: dict) -> str:
    """'2026-06-29 14:41' from $DATE (29-JUN-2026) and $BTIM; the raw text if odd."""
    import datetime as dt

    d, t = pick(meta, ("$DATE",)), pick(meta, ("$BTIM",))
    try:
        day = dt.datetime.strptime(d, "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        day = d
    return f"{day} {t[:5]}".strip()


def pick(meta: dict, keys) -> str:
    low = {k.lower(): v for k, v in meta.items()}
    for k in keys:
        if low.get(k.lower(), "").strip():
            return low[k.lower()].strip()
    return ""


def volume_ul(meta: dict) -> float | None:
    """Volume acquired, µL: $VOL is nL in FCS 3.1."""
    v = pick(meta, ("$VOL",))
    try:
        return float(v) / 1000 if v else None
    except ValueError:
        return None


def acquired_s(meta: dict) -> float | None:
    v = pick(meta, ("#ACQUISITIONTIMEMILLI",))
    try:
        return float(v) / 1000 if v else None
    except ValueError:
        return None


if __name__ == "__main__":
    f = read(sys.argv[1])
    for k, v in f.meta.items():
        print(f"{k} = {v}")
    print(f"{f.n} events; channels:", ", ".join(f.label(c) for c in f.channels))
