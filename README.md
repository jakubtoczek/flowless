# Flowless

<img src="src/flowless/assets/flowless.png" width="96" align="right" alt="Flowless icon">

Desktop GUI for **flow cytometry** fluorescence: drop the cytometer's FCS files, check the
gates, get overlay histograms (colour or black & white), the values (geometric mean, median…)
in a table, and a report that records how the experiment was done.

Made on BD Accuri C6 Plus files; any FCS 2.0 / 3.0 / 3.1 list-mode file is read.

## Install (Windows)

No admin rights, no PATH or registry changes.

1. Put the folder somewhere it can stay (`C:\Users\Public\Flowless`, or your Documents).
2. Double-click **`Flowless.bat`**. The first start downloads [`uv`](https://github.com/astral-sh/uv),
   Python and the libraries into `C:\ProgramData\PyApps` (shared with other tools set up the
   same way) and puts a **Flowless** shortcut on the Desktop; later starts are quick.
   `Flowless.bat private` the first time keeps everything in `C:\Users\Public\Flowless`
   instead; `FLOWLESS_RUNTIME` sets another place.
   To pin it to the taskbar: right-click its taskbar button while it runs ▸ *Pin to taskbar*.

`uninstall.bat` takes it all away again. What Flowless remembers (negative controls, aliases,
recorded procedures, the columns and options shown, typed values) is in
`flowless_options.json` beside `Flowless.bat`.

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
uv run python -m flowless                          # launch
uv run python -m flowless.model --self-check       # gates and values against the references
uv run python -m flowless.record                   # reagent names read
uv run python misc/smoke_test.py [--shots DIR]      # the whole window, driven without a screen
uv run python -m flowless.fcs FILE.fcs             # a file's keywords and channels
uv run python -m flowless.imports.sheet SHEET.xlsx # what a procedure sheet gives
uv run python -m flowless.imports.gatingml F.xml  # the gates a Gating-ML file gives
uv run python misc/bump.py                          # stamp today's date as the version
```

The checks read the example data kept beside this folder (`../data/data`); another folder can
be given at the end of the command.
