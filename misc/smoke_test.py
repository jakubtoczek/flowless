"""The whole window, driven without a screen: add a run, import its procedure sheet and
workspace gates, every tab drawn, a gate drawn and edited with the mouse, a sample's own
gate, the figure's panels, aliases, figure / values / report saved, save and reopen, undo.

    .venv/Scripts/python misc/smoke_test.py [DATA] [--shots DIR]

DATA: the example data folder (default ../data/data). --shots: a screenshot per tab there.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv) -> int:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from quickflow import __main__ as entry
    from quickflow import app as qapp
    from quickflow import model

    assert "matplotlib" not in sys.modules, "the window module must not load matplotlib"
    from quickflow import report
    args = [a for a in argv if not a.startswith("--")]
    shots = Path(argv[argv.index("--shots") + 1]) if "--shots" in argv else None
    if shots:
        args = [a for a in args if Path(a) != shots]
    data = Path(args[0]) if args else ROOT.parent / "data" / "data"
    run = data / "20260629_145214"
    out = Path(tempfile.mkdtemp(prefix="quickflow_smoke_"))
    qapp.OPTIONS = out / "options.json"                  # leave the real options alone

    a = QApplication.instance() or QApplication([])
    entry._apply_dark(a)
    w = qapp.MainWindow()
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.resize(1500, 950)
    w.show()
    a.processEvents()

    def shot(name):
        a.processEvents()
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
            w.grab().save(str(shots / f"{name}.png"))

    def key(widget, k):
        widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))

    shot("0_empty")
    w.open_paths([run])
    exp = w.exp
    assert exp.groups() == ["OVCAR", "PC3"], exp.groups()
    assert all(exp.gates.get(g) for g in exp.groups()), "auto 'cells' gate on every group"
    roles = {(s.group, s.label): s.role for s in exp.samples}
    assert roles[("PC3", "R3B23")] == "negative control", roles
    assert roles[("PC3", "AcII only")] == "secondary only"
    w.open_paths([data / "procedures" / "TheraSen_260629_FACS_autres_lignees.xlsx"])
    rec = w.exp.record
    assert len(rec["procedure"]) > 10 and any(r["catalog #"] == "AB9108" for r in rec["reagents"])
    assert rec["groups"]["OVCAR"]["cell line"] == "OVCAR-3", rec["groups"]
    s = next(s for s in w.exp.samples if s.group == "PC3" and s.label == "29A1")
    assert "29A1" in s.fields.get("condition", "") and s.fields.get("secondary µL"), s.fields
    assert w.exp.fluorescence() == ["FL2-A"], "PE in the reagents: FL2-A only"
    assert w.exp.shown_channels() == ["FSC-A", "SSC-A", "FL2-A"], w.exp.shown_channels()
    w.samples_tab.table.selectRow(2)
    shot("1_samples")

    w.open_paths([run / "29-Jun-2026.wsp"])            # the workspace's gates replace the auto ones
    vals = {(r["group"], r["label"]): r["value"] for r in report.summary_rows(w.exp)}
    assert abs(vals[("PC3", "29A1")] - 70543) / 70543 < 0.005, vals
    assert abs(vals[("PC3", "R3B23")] - 3854) / 3854 < 0.005, vals

    for i, name in enumerate(["1_samples", "2_gating", "3_figure", "4_results", "5_experiment"]):
        w.tabs.setCurrentIndex(i)
        if i:
            shot(name)
    w.tabs.setCurrentIndex(1)
    g = w.gating_tab
    from matplotlib.backend_bases import MouseEvent

    def mouse(kind, xy, canvas=g.dot, ax=g.ax1, px=None, dbl=False):
        x, y = px if px is not None else ax.transData.transform(xy)
        MouseEvent(kind, canvas, x, y, button=1 if kind != "motion_notify_event" else None,
                   dblclick=dbl)._process()

    def click(xy, **kw):
        mouse("motion_notify_event", xy, **kw)
        mouse("button_press_event", xy, **kw)
        mouse("button_release_event", xy, **kw)

    g.dot.draw()
    n0 = len(g.gates())
    g.new_polygon()
    g.dot.draw()
    corners = [(3e6, 0.5e6), (8e6, 0.5e6), (8e6, 3e6), (3e6, 3e6)]
    for xy in corners + corners[:1]:
        click(xy)
    a.processEvents()
    assert len(g.gates()) == n0 + 1, "a polygon drawn with the mouse becomes a gate"
    new = g.gate()
    assert new is not None and len(new.vertices) == 4, new
    g.dot.draw()
    # drag a corner
    mouse("motion_notify_event", (8e6, 3e6))
    mouse("button_press_event", (8e6, 3e6))
    mouse("motion_notify_event", (10e6, 4e6))
    mouse("button_release_event", (10e6, 4e6))
    assert any(abs(x - 10e6) < 3e5 and abs(y - 4e6) < 3e5 for x, y in g.gate().vertices), \
        g.gate().vertices
    # a click on a side adds a corner there; a corner selected then Del deletes it
    g.dot.draw()
    click((5.5e6, 0.5e6))
    assert len(g.gate().vertices) == 5, g.gate().vertices
    g.dot.draw()
    click((5.5e6, 0.5e6))
    key(g.dot, Qt.Key_Delete)
    assert len(g.gate().vertices) == 4, g.gate().vertices
    # drawing: a click outside the plot puts the corner on its edge (the top of the scale)
    g.new_polygon()
    g.dot.draw()
    top = g.samples()[0].fcs.range("FSC-A")
    for xy in [(12e6, 0.5e6), (14e6, 0.5e6)]:
        click(xy)
    bx = g.ax1.bbox
    click(None, px=(bx.x1 + 15, g.ax1.transData.transform((0, 2e6))[1]))
    click((12e6, 2.5e6))
    key(g.dot, Qt.Key_Return)
    edge = g.gate()
    assert edge is not None and any(abs(x - top) < 1 for x, _ in edge.vertices), edge
    shot("2_gating_drawn")
    for _ in range(5):
        w.do_undo()
    assert len(w.exp.gates[g.group]) == n0, "undo every step"
    g = w.gating_tab
    g.new_range()
    assert any(x.kind == "range" for x in w.exp.gates[g.group]), "range gate added"
    shot("2_gating_range")
    w.do_undo()
    assert not any(x.kind == "range" for x in w.exp.gates[g.group]), "undo"
    w.do_redo()
    assert any(x.kind == "range" for x in w.exp.gates[g.group]), "redo"
    w.do_undo()
    # a sample's own gate: it alone changes
    g = w.gating_tab
    g.view.setCurrentIndex(1)
    first = g.gates()[0]
    g.pop = first.name
    g.fill_tree()
    g.own.setChecked(True)
    one = g.one()
    assert first.name in one.gates, "own gate made"
    g._poly_done([[1e6, 1e5], [1.6e7, 1e5], [1.6e7, 1.6e7], [1e6, 1.6e7]])
    assert w.exp.gates[g.group][0].vertices != one.gates[first.name].vertices
    r = {x["sample"]: x["own gate"] for x in w.exp.results() if x["population"] == first.name}
    assert r[one.name] and sum(r.values()) == 1, r
    g.own.setChecked(False)
    assert first.name not in g.one().gates

    # the figure: panels, options, the preview
    w.tabs.setCurrentIndex(2)
    f = w.figure_tab
    n = len(f.panels())
    f.items.setCurrentRow(1)
    f.add()
    f._panel_set("kind", "dot")
    f.items.setCurrentRow(0)
    f.preset.setCurrentText("black & white, offset")
    f._apply_preset()
    a.processEvents()
    f.render()
    assert len(f.panels()) == n + 1 and f.panels()[1]["kind"] == "dot", f.panels()
    x0, y0, x1, y1 = dict(f.fig.quickflow_cells)[1]
    f.view.clicked.emit((x0 + x1) / 2, (y0 + y1) / 2)
    assert f.sel == 1, f.sel
    f._set("lw", 2.0, f.panels()[f.sel])
    assert f.panels()[1]["opts"]["lw"] == 2.0, "a panel's own option"
    shot("3_figure_panels")
    f.items.setCurrentRow(0)
    f.preset.setCurrentText("colour")
    f._apply_preset()
    for ext in (".png", ".svg", ".pdf", ".tif"):
        f._write(out / f"fig{ext}")
        assert (out / f"fig{ext}").stat().st_size > 1000, ext
    f.copy()
    # aliases
    w.set_alias("channel", "FL2-A", "anti-His PE", remember=False)
    assert w.exp.name("channel", "FL2-A") == "anti-His PE"
    w.changed()
    report.save_xlsx(w.exp, out / "values.xlsx")
    text, images = report.build(w.exp, None, True)
    assert "anti-His PE" in text and "PE-labelled anti-His-tag secondary antibody" in text
    report.save_html(text, images, out / "report.html")
    qapp.to_pdf(text, images, out / "report.pdf")
    assert (out / "report.pdf").stat().st_size > 20000
    w.tabs.setCurrentIndex(0)
    w.samples_tab._sort(w.samples_tab.shown().index("label"))
    assert [s.label for s in w.exp.samples] == sorted([s.label for s in w.exp.samples],
                                                      key=lambda x: model._natural(Path(x)))

    w.exp.save(out / "exp.json")
    d = json.loads((out / "exp.json").read_text(encoding="utf-8"))
    assert d["samples"][0]["rel"], "relative paths kept"
    e2, problems = model.Experiment.open(out / "exp.json")
    assert not problems and len(e2.samples) == len(w.exp.samples), problems
    assert e2.results() == w.exp.results() and e2.aliases == w.exp.aliases
    w.dirty = False
    w.close()
    print(f"smoke test OK — outputs in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
