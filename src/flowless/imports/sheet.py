"""A procedure sheet (.xlsx) as the lab writes them, free-form: read what can be found,
the rest stays in the sheet. No Qt.

    python -m flowless.imports.sheet SHEET.xlsx     what a sheet gives
"""

from __future__ import annotations

import difflib
import re
import sys

from .. import record


def _fix(v) -> str:
    """The sheets lost µ and ° (saved through a codepage): '4�C' is 4 °C, '2�L' 2 µL."""
    s = str(v).strip()
    s = re.sub(r"(\d)\s*�\s*C\b", r"\1 °C", s)
    return s.replace("�", "µ")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _head(h: str) -> str:
    """A conditions table's column, as a sample field: the antibody amounts are the
    primary's and the secondary's µL whatever the sheet calls them."""
    if re.search(r"[µu]L\b", h):
        return "secondary µL" if re.search(r"anti|2nd|second", h, re.I) else "primary µL"
    return h.strip().lower()


def read(path) -> dict:
    """The steps down column A (notes in B), the primaries' table (names over an 'MW' /
    'PM da' row and a 'conc mg/ml' one), a conditions table per cell line (a header
    '<cell line> | <primary>, µL | <secondary>, µL | cells', numbered rows below), reagent
    lines to the right ('Anti his PE | AB9108 | abcam | 1/50'). Returns {"procedure",
    "reagents", "conditions": {cell line: [row…]}}. Every sheet is read; a sheet that
    repeats the first's steps adds nothing."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    steps, reagents, conds = [], [], {}
    for ws in wb.worksheets:
        grid = {(c.row, c.column): c.value for row in ws.iter_rows() for c in row
                if c.value is not None and str(c.value).strip()}
        if not grid:
            continue
        rows = sorted({r for r, _ in grid})
        # conditions: a header cell ending in µL with a name to its left
        cond_cols = set()
        for (r, c), v in sorted(grid.items()):
            if isinstance(v, str) and re.search(r"[µ�]L$", v.strip()) and \
                    not v.strip()[0].isdigit() and \
                    any(_num(grid.get((r + k, c - 2))) for k in (1, 2)) and \
                    isinstance(grid.get((r, c - 1)), str) and \
                    not re.search(r"[µ�]L$", grid[(r, c - 1)].strip()):
                name_col = c - 1
                heads = {}
                k = c
                while isinstance(grid.get((r, k)), str):
                    heads[k] = _head(_fix(grid[(r, k)]))
                    k += 1
                line = _fix(grid[(r, name_col)])
                out = conds.setdefault(line, [])
                rr = r + 1
                while rr <= max(rows) + 1:
                    n = grid.get((rr, name_col - 1))
                    if _num(n) and (rr, name_col) in grid:
                        if not any(x["#"] == int(n) for x in out):
                            out.append({"#": int(n), "condition": _fix(grid[(rr, name_col)]),
                                        **{h: grid.get((rr, k), "") for k, h in heads.items()}})
                    elif out and (rr, name_col) not in grid and not _num(n):
                        if (rr, name_col - 1) not in grid and rr > r + 2:
                            break
                    rr += 1
                cond_cols |= set(range(name_col - 1, k))
        right = max(cond_cols) + 1 if cond_cols else 99
        left = min(cond_cols) if cond_cols else right
        # the primaries: names over an 'MW' / 'PM' row
        for (r, c), v in grid.items():
            if c == 1 and isinstance(v, str) and re.match(r"^(PM|MW)\b", v.strip(), re.I):
                names = {k: _fix(grid[(r - 1, k)]) for k in range(2, left)
                         if (r - 1, k) in grid}
                conc = next((rr for rr in (r + 1, r + 2) if isinstance(grid.get((rr, 1)), str)
                             and grid[(rr, 1)].lower().startswith("conc")), None)
                for k, nm in names.items():
                    if any(x["name"] == nm for x in reagents):
                        continue
                    reagents.append({"name": nm, "kind": "sample",     # what is tested
                                     "MW (Da)": _txt(grid.get((r, k), "")),
                                     "stock (mg/mL)": _txt(grid.get((conc, k), "")) if conc else ""})
        # reagent lines right of the conditions: name | catalog | supplier | dilution, or
        # name | per tube
        for r in rows:
            cells = [_fix(grid[(r, k)]) for k in range(right, right + 8) if (r, k) in grid]
            if len(cells) >= 4:
                _merge(reagents, {"name": cells[0], "catalog #": cells[1],
                                  "supplier": cells[2], "dilution": cells[3]})
            elif len(cells) == 2 and re.search(r"\d\s*[µu][gl]\b", cells[1], re.I):
                _merge(reagents, {"name": cells[0], "per tube": cells[1]})
        # steps: column A text, B notes; table rows (numbers in B…F) and their titles left out
        sheet_steps = []
        for r in rows:
            a, b = grid.get((r, 1)), grid.get((r, 2))
            table = any(_num(grid.get((r, k))) for k in range(2, 7))
            nxt_table = any(_num(grid.get((r + 1, k))) for k in range(2, 7))
            if isinstance(a, str) and not table and not (nxt_table and len(a) < 25):
                if (r, 2) not in grid or isinstance(b, str):
                    sheet_steps.append(_fix(a) + (f" — {_fix(b)}" if isinstance(b, str) else ""))
            elif a is None and isinstance(b, str) and sheet_steps and \
                    not any((r, k) in grid for k in range(3, 7)):
                sheet_steps[-1] += f" — {_fix(b)}"
        if sheet_steps and sheet_steps[0].lower().startswith("facs protocol"):
            sheet_steps = sheet_steps[1:]
        if not steps:
            steps = sheet_steps
    # '<word> | 1 µg' where the conditions start with that word: the amount of each primary
    words = {c["condition"].split()[0].lower() for rows in conds.values() for c in rows
             if c["condition"].split()}
    for r in [r for r in reagents if r["name"].lower() in words and "kind" not in r]:
        reagents.remove(r)
        for p in reagents:
            if p.get("kind") in record.BINDERS and not p.get("per tube"):
                p["per tube"] = r.get("per tube", "")
    for r in reagents:
        r.setdefault("kind", "secondary" if re.search(r"anti|2nd|second", r["name"], re.I)
                     else "primary")
    return {"procedure": steps,
            "reagents": [record.complete({k: r.get(k, "") for k in record.REAGENT_FIELDS})
                         for r in reagents],
            "conditions": conds}


def _txt(v) -> str:
    if _num(v):
        return f"{v:.4g}" if isinstance(v, float) else str(v)
    return _fix(v) if v else ""


def _merge(reagents: list, new: dict) -> None:
    """Same reagent written twice ('anti-his PE' / 'Anti his PE'): one entry."""
    key = re.sub(r"[^a-z0-9]", "", new["name"].lower())
    for r in reagents:
        if re.sub(r"[^a-z0-9]", "", r["name"].lower()) == key:
            r.update({k: v for k, v in new.items() if v and not r.get(k)})
            return
    reagents.append(dict(new))


def apply(rec: dict, sheet: dict, samples, groups) -> list[str]:
    """Put what a sheet gives into the record and the samples: the steps (if none yet),
    the reagents (new names), each group's conditions matched to its cell line (closest
    name) and each sample to its condition (the label in it; 'unstained', '… only' by
    role). Returns the log."""
    log = []
    if sheet["procedure"] and not rec["procedure"]:
        rec["procedure"] = list(sheet["procedure"])
        log.append(f"✓ procedure: {len(sheet['procedure'])} steps")
    have = {r["name"].lower() for r in rec["reagents"]}
    new = [r for r in sheet["reagents"] if r["name"].lower() not in have]
    rec["reagents"] += new
    if new:
        log.append(f"✓ reagents: {', '.join(r['name'] for r in new)}")
    names = list(sheet["conditions"])
    for g in groups:
        best = difflib.get_close_matches(_key(g), [_key(n) for n in names], n=1, cutoff=0.6)
        if not best:
            continue
        line = names[[_key(n) for n in names].index(best[0])]
        rec["groups"].setdefault(g, {})["cell line"] = rec["groups"].get(g, {}).get(
            "cell line") or line
        rows = sheet["conditions"][line]
        hits = 0
        for s in [s for s in samples if s.group == g]:
            row = _condition_for(s, rows)
            if row is None:
                continue
            hits += 1
            s.fields["condition"] = row["condition"]
            for k, v in row.items():
                if k not in ("#", "condition") and v not in ("", None):
                    s.fields[k] = _txt(v)
        log.append(f"✓ {g}: conditions of '{line}' — {hits} of "
                   f"{len([s for s in samples if s.group == g])} samples matched")
    return log


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _condition_for(s, rows):
    lab = _key(s.label)
    for row in rows:
        c = row["condition"].lower()
        if s.role == "unstained" and "unstained" in c:
            return row
        if s.role == "secondary only" and "only" in c:
            return row
        if lab and s.role not in ("unstained", "secondary only") and \
                lab in _key(row["condition"]):
            return row
    return None


if __name__ == "__main__":
    import json
    print(json.dumps(read(sys.argv[1]), indent=1, ensure_ascii=False))
