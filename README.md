# Flowless

<img src="src/flowless/assets/flowless.png" width="96" align="right" alt="Flowless icon">

Desktop GUI for **flow cytometry** fluorescence: drop the cytometer's FCS files, check the
gates, get overlay histograms (colour or black & white), the values (geometric mean, median…)
in a table, and a report that records how the experiment was done.

Made on BD Accuri C6 Plus files; any FCS 2.0 / 3.0 / 3.1 list-mode file is read.

## Install (Windows)

No admin rights, no PATH or registry changes, nothing written into your user profile.

1. On the GitHub page: **Code ▸ Download ZIP**.
2. **Right-click the ZIP ▸ Properties ▸ tick *Unblock* ▸ OK** — without it, SmartScreen stops
   the launcher with *"Windows protected your PC"*.
3. Extract it where it can stay (`C:\Users\Public\Flowless` serves every account).
4. Double-click **`Flowless.bat`**. The first time it downloads
   [`uv`](https://github.com/astral-sh/uv), Python and the libraries (about 350 MB, a minute or
   two) into the shared folder `C:\ProgramData\PyApps`, which other tools installed this way
   reuse, and puts a **Flowless** shortcut on the Desktop. Use the shortcut from then on; to pin
   it, right-click its taskbar button while it runs ▸ *Pin to taskbar*.

Self-contained instead: run **`Flowless.bat private`** the first time, and everything goes into
`C:\Users\Public\Flowless` (`FLOWLESS_RUNTIME` picks another place). **`uninstall.bat`**
removes it: the whole private folder, or only Flowless's part of the shared one.

What Flowless remembers (negative controls, aliases, recorded procedures, the columns and
options shown, typed values) is in `flowless_options.json` beside `Flowless.bat`; an internal
error's details, in `flowless_errors.log` there (send it along with a problem report).

## Use

**Drop files anywhere on the window**, or **Import…** (Ctrl+I): FCS files or whole folders, a
saved experiment (`.json`), gates (Gating-ML 2.0 `.xml`). Hover anything for what it does; the
log at the bottom says what happened and what looks wrong (✗ ⚠). The tabs follow the work:

1. **Samples** — a row per file: its *group* (a cell line: a panel of the figure), *label*
   (the stain: a series) and *role* (negative control, secondary only…), guessed from the
   folders and names. Check them.
2. **Gating** — each group's populations: a polygon on the dot plot, a range on the
   histogram. A new group gets a *cells (auto)* gate: check it. The population in **bold** is
   the one the figure and the values use.
3. **Figure** — its panels and the legend: drag their boxes where they go; sizes in mm,
   fonts, colour or black & white. **Save…** (PNG, TIFF, SVG, PDF) or **Copy**.
4. **Results** — the values (geometric mean…, ÷ control, replicates pooled); click a
   column's title to sort; **⧉** copies the table for Excel, Word or PowerPoint.
5. **Experiment** — what was done: cells, reagents, procedure; what a MIFlowCyt report still
   lacks.

**Report…** (Ctrl+P): PDF, web page, PowerPoint or Excel. **▤ Aliases**: what things are
called — two labels under one name are one series, two groups under one name are replicates.
**Ctrl+S** saves the experiment as one `.json`; **Ctrl+Z / Ctrl+Y** undo, redo.

Each tab in detail, the figure's layout, the files read and how the numbers are made:
**[the user guide](GUIDE.md)**.

## Dev

```
uv run python -m flowless                           # launch
uv run python -m flowless.model --self-check        # gates and values against the references
uv run python -m flowless.record                    # reagent names read
uv run python -m flowless.scale                     # log / logicle axes
uv run python misc/smoke_test.py [--shots DIR]      # the whole window, driven without a screen
uv run python misc/make_artificial.py [OUT]         # an artificial experiment (../data/artificial)
uv run python -m flowless.fcs FILE.fcs              # a file's keywords and channels
uv run python -m flowless.imports.sheet SHEET.xlsx  # what a procedure sheet gives
uv run python -m flowless.imports.gatingml F.xml    # the gates a Gating-ML file gives
uv run python misc/bump.py                          # stamp today's date as the version (CalVer)
uv run python misc/make_icon.py                     # redraw the icon (needs Pillow)
```

The checks read example runs (FCS files, FlowJo workspaces, procedure sheets) that are not in
this repository: by default from `../data/data` beside the folder, or a folder given at the end
of the command. The artificial experiment (compensated values for logicle axes, a viability
dye, replicate runs; its truth in `TRUTH.txt`) is made by `misc/make_artificial.py`; the smoke
test makes its own.

Layers: `fcs.py` the FCS reader · `model.py` the experiment, gates, statistics (no Qt) ·
`scale.py` the axes' scales (linear, log, logicle) · `record.py` the experiment's record,
reagents, MIFlowCyt · `imports/` other programs' files, best effort (`gatingml.py`,
`flowjo.py`, `sheet.py`…) · `plots.py` the figures, matplotlib only ·
`report.py` HTML, PDF, Excel, PowerPoint · `app.py` the window and its dialogs, `gating.py`,
`figtab.py`, `canvas.py` the Gating and Figure tabs. matplotlib is imported in a thread once the
window is up, to keep it off the startup path.
