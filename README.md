# QuickFlow

<img src="src/quickflow/assets/quickflow.png" width="96" align="right" alt="QuickFlow icon">

Desktop GUI for **flow cytometry** fluorescence: drop the cytometer's FCS files, check the
gates, get overlay histograms (colour or black & white), the values (geometric mean, median…)
in a table, and a report that records how the experiment was done.

Made on BD Accuri C6 Plus files; any FCS 2.0 / 3.0 / 3.1 list-mode file is read.

## Install (Windows)

No admin rights, no PATH or registry changes.

1. Put the folder somewhere it can stay (`C:\Users\Public\QuickFlow`, or your Documents).
2. Double-click **`QuickFlow.bat`**. The first start downloads [`uv`](https://github.com/astral-sh/uv),
   Python and the libraries into `C:\ProgramData\PyApps` (shared with other tools set up the
   same way) and puts a **QuickFlow** shortcut on the Desktop; later starts are quick.
   `QuickFlow.bat private` the first time keeps everything in `C:\Users\Public\QuickFlow`
   instead; `QUICKFLOW_RUNTIME` sets another place.
   To pin it to the taskbar: right-click its taskbar button while it runs ▸ *Pin to taskbar*.

`uninstall.bat` takes it all away again. What QuickFlow remembers (negative controls, aliases,
recorded procedures, the columns and options shown, typed values) is in
`quickflow_options.json` beside `QuickFlow.bat`.

## Use

**Drop files anywhere on the window**, or **Import…** (Ctrl+I): FCS files or whole folders, a
saved experiment (`.json`), gates (Gating-ML 2.0 `.xml`, the standard for gates). The kind of
file is told by the file. The tabs follow the work;
hover anything for what it does. The log at the bottom says what happened and what looks
wrong (✗ ⚠).

1. **Samples** — a row per file. *Group* is a block of the table and a panel of the figure (a
   cell line, a treatment); *label* is a series (the stain); *role*: sample, negative control,
   secondary only, unstained; *plot* ticks what the figure shows. They are guessed from the
   folders and names (`MDA-MB-157 parental cells/24E8_PC.fcs` → group the folder, label 24E8;
   `PC3-29A1.fcs` → PC3 / 29A1; "unstained", "… only" set the role; a label once marked as
   a negative control is one again). Edit a cell with several rows selected: they all take the
   value. Click a column's title to sort by it; right-click it (or *Options*) for the columns
   shown. **⤢** opens everything about a sample: its fields, and what its file says (date,
   start / end, volume, events off scale, instrument, every keyword). On the right, the selected
   sample at a glance: its events on FSC-A × SSC-A with its gate, its histogram.
2. **Gating** — a group's populations, each a gate on its parent: a **polygon** on two
   channels (the dot plot) or a **range** on one (the histogram). **Drag the populations** to
   order or nest them: the figure and the values use the one in **bold** — the first gate, and
   the first polygon below it (cells › singlets). **Groups / samples**: a group shows all
   its samples; expand it and pick one sample, or several (Ctrl, Shift), to see only those
   (plots and counts). Drag the groups to order them. The dot plot's channels are picked
   above it — FSC-A × SSC-A (cells), FSC-A × FSC-H (singlets), the pairs the group's gates
   use, or *custom…* (any two channels) — and stay as picked when the group, the samples or
   the population change; a gate on other channels says so, with a link to show them. A new group
   gets a *cells (auto)* gate (the main cluster on FSC × SSC; debris, the off-scale pile and a
   second cluster left out): check it. **Auto gate** redraws the selected polygon that way;
   with *All events* selected it adds a *cells (auto)* gate beside the others. A ⚠ under the
   tree says when ranges hang from a population the figure doesn't show, with a link that
   shows it instead (or right-click a population: *Show … in the figure*). The histogram's
   y axis: count (the default), % of max, or % of events (each histogram's area 100 %).
   **Export…** writes every group's gates as a Gating-ML 2.0 file, the standard most flow
   cytometry software reads; dropping such a file brings them back (a file from another
   program: its gates go to every group; gates on a transformed scale are not read, the log
   names them).
   Editing a polygon: drag a corner; click a side to add a corner; click a corner to select it,
   **Del** deletes it; drag inside to move the gate. **+ Polygon**: click its corners (a click
   outside the plot puts the corner on its edge: the gate then takes the events piled there,
   off scale), then the first one again, a double-click or Enter. **+ Singlets** adds a
   *singlets (auto)* gate on FSC-A × FSC-H first under the selected polygon (else the main
   population), so the figure and the values use it: doublets (about twice the area for
   the same height) are left out. **+ Range** starts above 99 %
   of the negative control's events; drag its limits. **Del** deletes the selected population,
   F2 renames it. With one sample picked, **this sample's own gate** gives it its own
   version of the selected gate (◆ in the tree), the group's being the default. Click a plot,
   **Ctrl+C** copies it.
3. **Figure** — on the left, the figure's items: its panels and the legend. **+** adds a panel
   (a copy of the selected one), drag them to order them. A panel shows one group: its
   **histograms** (a channel, % of max or count), a **dot plot** (two channels, the gates), or
   its **values** as bars. The legend goes below, above or right of the figure, in the grid at
   its place in the list, in each panel, or nowhere. Select the first line for the whole
   figure's options, a panel for its own (they override the figure's, ↺ undoes that): style,
   fonts (titles, axis labels, ticks, legend, range labels — a title wider than its panel
   goes on two lines, at its size), line widths (data, axes; numbers to two decimals: 0.75
   can be typed), fills; the legend (select it): across left / centred / right with a
   margin, up / down with an offset, line spacing, columns; the
   figure's size
   (panel width and height, the width at most — panels then go on the next row), background
   (white or transparent), and each series' colour and dashes. **style ▸ Apply**: a set of
   them at once (colour, black & white, offset, one column 85 mm, large for slides).
   *Options ▸ Figure options* sets which options are listed. In the middle, the **layout** as
   boxes, its size above them (panel width × height, columns, the width at most, the legend's
   place): click a box to select it; drag it and a bar shows where it goes — between two
   panels, at the end of a row, a new row above or below (so 3 + 1 becomes 2 × 2 by dragging
   one panel down); the legend also above, below or right of the figure, or into a free place
   in the grid. **+** adds a panel; right-click a box for its menu. On the right, the figure
   as exported:
   wheel to zoom, drag to move, double-click to fit, **100 %** for its real size, a checker
   behind it (shows a transparent background), **res** 1–5× (the panels larger, the text as
   set; *export* ticked: the exports too); click a panel to select it; **Ctrl+C** copies
   it. **Save…** PNG / TIFF (dpi) or SVG / PDF (text stays text), **Colour + B&W…** both at once.
4. **Results** — the figure's table (group, label, sub-population, events, % of parent, value,
   ÷ control: each group's population the figure shows, and the ranges below it), the
   **replicates** (runs pooled: each label's n, mean ± SD of the value and of ÷ control, each
   run's value),
   or every sample and population (count, % of parent, geometric mean, median, mean, CV). The
   value and the channel measured are chosen here. **⧉** (Ctrl+C) pastes as a table in
   Excel, Word or PowerPoint; **Export…** `.xlsx` (every sheet) or `.csv`; **Report…**.
5. **Experiment** — what was done: title, date, operator, aim; each group's cells (cell line,
   transfection, treatment, detachment); the reagents (kind — *sample* for what is tested, as
   the sdAbs: in the tube it is the primary —, target, fluorochrome, supplier,
   catalog #, lot, MW, stock, per tube, dilution) and how each reads (*Anti his PE* → a
   PE-labelled anti-His-tag secondary antibody); the procedure, one step per line (record it
   to reuse it); the acquisition and the instrument as the files describe them. ⤢ opens a
   group or a reagent whole. The MIFlowCyt list says what a report of this experiment holds and
   what is missing.

**▤ Aliases…**: what the figure, the tables and the report call the groups, labels, samples,
channels and populations (*FL2-A :: PE-A* → *anti-His PE*); remembered for the next
experiments with the same names.

**Options…**: a page per topic — the sample columns shown; the channels offered (by default
FSC-A, SSC-A and the areas of the fluorochromes the reagents name — heights and other
detectors hidden; a channel a gate is on is always offered); the figure options listed.

**Report… (Ctrl+P)**: the format, the sections on the left (tick them, drag them in order —
each format keeps its own choice), the report as it will read on the right; **Save report…**.
PDF and HTML: the sections one after the other. **PowerPoint**: one slide, a figure page —
the title, the figure at its size, the summary and the replicates as real tables (editable in
PowerPoint); every other section ticked goes as text in the slide's notes (by default the
experiment, procedure, gating, instrument and files; the samples table and the checklist
off). **Excel**: a sheet per section (Summary and Results, Replicates, Samples, Files,
Experiment, Procedure, Gates, Instrument and Keywords, MIFlowCyt, the figure as a picture).
*Files* lists each FCS file on a line (name, folder, last modified, SHA-256), and the gates'
file while the gates are as in it.

**Replicates**: groups shown under one name (▤ Aliases) are runs of one condition. Two
groups whose names differ only by spaces, dashes or case (two runs' folders: *MDA-MB-157
parental cells* / *MDA-MB-157-parental cells*) get one name when they come in, and the log
says so. Their figure panels and tables add the run's day (*… · 2026-05-27*); a **Values
(bars)** panel of one of them shows each label's mean over the runs ± SD, a dot per run.

Numbers are written with a decimal point whatever the system's language; the mouse wheel
scrolls past the lists and number boxes, it never changes them.

**Ctrl+S** saves the experiment as one `.json` (the files are found again from where it is, if
the folder moves with them); **Ctrl+Z / Ctrl+Y** undo, redo.

The version is in the window title and on every report.

## How the numbers are made

- **Gates**: a polygon holds an event inside it (the channels' raw values); a range holds
  low ≤ value < high. Events at the top of a channel's scale (an Accuri's FSC-A saturates for
  big cells: up to 56 % of the events in the example runs; FSC-H never does) sit on the plot's
  edge: a gate drawn to that edge takes them.
- **Geometric mean**: exp(mean(ln x)) of the positive values. Median, mean and CV of all of
  them.
- **÷ control**: the value over the group's negative control's (else the secondary-only,
  else the unstained), its main population.
- **Histograms**: 256 channels over the log scale, smoothed over a few channels when
  *smoothed* is ticked; *% of max* (the figure's default, "normalised to mode") scales each
  to its own peak, so samples with different event numbers compare — the table gives the
  events; *% of events* makes each histogram's area 100 % (fair when the peaks' widths
  differ).

Checked against FlowJo on the example runs: events per gate within 1.1 %, geometric means
within 0.2 %. FlowJo is a trademark of Becton, Dickinson and Company; QuickFlow only reads
the gates in its workspace files and is not affiliated with it.

## Dev

```
uv run python -m quickflow                          # launch
uv run python -m quickflow.model --self-check       # gates and values against the references
uv run python -m quickflow.record                   # reagent names read
uv run python misc/smoke_test.py [--shots DIR]      # the whole window, driven without a screen
uv run python -m quickflow.fcs FILE.fcs             # a file's keywords and channels
uv run python -m quickflow.imports.sheet SHEET.xlsx # what a procedure sheet gives
uv run python -m quickflow.imports.gatingml F.xml  # the gates a Gating-ML file gives
uv run python misc/bump.py                          # stamp today's date as the version
```

The checks read the example data kept beside this folder (`../data/data`); another folder can
be given at the end of the command.
