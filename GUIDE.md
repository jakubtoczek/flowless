# Flowless — user guide

Everything the window does, the files it reads and how the numbers are made. For installing,
see the [README](README.md).

## An experiment, step by step

1. **Load.** Drop the run's FCS files, or its whole folder, anywhere on the window (or
   **Import…**, Ctrl+I). A folder per cell line is the easiest: the folder becomes the group.
2. **Samples.** Check each file's group, label and role; tick *plot* for what the figure
   shows.
3. **Gating.** Check the *cells (auto)* gate of each group, add *singlets* if the doublets
   matter, a **range** for the positive events if wanted.
4. **Figure.** Pick a style, drag the boxes into the layout you want, set the sizes.
5. **Results.** Read or copy the values.
6. **Experiment.** Record what was done (or drop the procedure sheet).
7. **Report…** and **Save** (Ctrl+S).

Ctrl+Z / Ctrl+Y undo and redo each change (the figure's settings too); the log at the bottom
names what happened and what looks wrong (✗ ⚠). Numbers are written with a decimal point
whatever the system's language; the mouse wheel scrolls past the lists and number boxes, it
never changes them. The version is in the window title and on every report. Should something
break inside Flowless, the log says so (*internal error*) and `flowless_errors.log`, beside
`Flowless.bat`, keeps the details: send it along with what you were doing.

## Samples

A row per file. *Group* is a block of the table and a panel of the figure (a cell line, a
treatment); *label* is a series (the stain); *role*: sample, negative control, secondary only,
unstained; *plot* ticks what the figure shows. They are guessed from the folders and names
(`MDA-MB-157 parental cells/24E8_PC.fcs` → group the folder, label 24E8; `PC3-29A1.fcs` →
PC3 / 29A1; "unstained", "… only" set the role; a label once marked as a negative control is
one again).

- Edit a cell with several rows selected: they all take the value.
- Click a column's title to sort by it; right-click it (or *Options*) for the columns shown.
- **⤢** opens everything about a sample: its fields, and what its file says (date, start /
  end, volume, events off scale, instrument, every keyword).
- On the right, the selected sample at a glance: its events on FSC-A × SSC-A with its gate,
  its histogram.

## Gating

A group's populations, each a gate on its parent: a **polygon** on two channels (the dot
plot) or a **range** on one (the histogram).

- **Drag the populations** to order or nest them. The figure and the values use the one in
  **bold**: the first gate, and the first polygon below it (cells › singlets).
- **Groups / samples**: a group shows all its samples; expand it and pick one sample, or
  several (Ctrl, Shift), to see only those (plots and counts). Drag the groups to order them.
- **The dot plot's channels** are picked above it: FSC-A × SSC-A (cells), FSC-A × FSC-H
  (singlets), the pairs the group's gates use, or *custom…* (any two channels). They stay as
  picked when the group, the samples or the population change; a gate on other channels
  says so, with a link to show them. Scatter channels are linear, fluorescence log —
  **logicle** when the files hold values below 0 (below).
- **The histogram's y axis**: count (the default), % of max, or % of events (each
  histogram's area 100 %).

### Gates

- **A new group** gets a *cells (auto)* gate: the main cluster on FSC × SSC, debris, the
  off-scale pile and a second cluster left out. Check it. **Auto gate** redraws the selected
  polygon that way; with *All events* selected it adds a *cells (auto)* gate beside the
  others.
- **+ Polygon**: click its corners (a click outside the plot puts the corner on its edge: the
  gate then takes the events piled there, off scale), then the first one again, a
  double-click or Enter.
- **Editing a polygon**: drag a corner; click a side to add a corner; click a corner to select
  it, **Del** deletes it; drag inside to move the gate.
- **+ Singlets** adds a *singlets (auto)* gate on FSC-A × FSC-H, first under the selected
  polygon (else the main population), so the figure and the values use it: doublets (about
  twice the area for the same height) are left out.
- **+ Live**, with a viability dye (below): a *live (auto)* gate on the dye × SSC-A, first
  under the selected polygon (else the main population), so the figure and the values use
  the live cells: the dye-bright (dead) ones are left out.
- **+ Range** starts above 99 % of the negative control's events; drag its limits.
- **Del** deletes the selected population, **F2** renames it.
- **This sample's own gate** (one sample picked) gives it its own version of the selected
  gate (◆ in the tree); the group's stays the default.
- A ⚠ under the tree says when ranges hang from a population the figure doesn't show, with a
  link that shows it instead (or right-click a population: *Show … in the figure*).
- Click a plot, **Ctrl+C** copies it.

### A viability dye

Nothing about viability shows until the experiment has a dye: a reagent of kind *viability
dye* in **Experiment** (its fluorochrome tells the channel: DRAQ7, TO-PRO-3 or SYTOX Red are
read like APC, on an Accuri's FL4; 7-AAD like PerCP, on FL3; PI like PE), or a channel the
cytometer named for one (*DRAQ7-A*, *Live/Dead*…). Then the dot plot's list has *the dye ×
SSC-A* and **+ Live** appears. On an Accuri, a far-red dye on FL4 (red laser) doesn't spill
into PE on FL2, and tells whether the minor FSC × SSC cluster is dying cells.

### Values below 0: logicle axes

Compensated files hold values below 0 (a log axis would drop them). A channel with such
values gets a **logicle** axis everywhere (histograms, dot plots): linear around 0, log above,
its linear part as wide as the files' negatives need. Accuri files never hold any: their axes
stay log. A polygon drawn on a log or logicle plot keeps its sides straight there.

### Gates in and out

**Export…** writes every group's gates as a Gating-ML 2.0 file, the ISAC standard most flow
cytometry software reads. Dropping such a file brings them back: Flowless's own go to their
group; another program's go to every group. Gates on a transformed or compensated scale are
not read (their numbers aren't the file's); the log names them.

## Figure

On the left, the figure's **items**: its panels and the legend. Select the first line for the
whole figure's options, a panel for its own (they override the figure's; **↺** undoes that),
the legend for its options. **+** adds a panel (a copy of the selected one), **−** or Del
removes one. The order of the list is only an order: it doesn't place anything (the boxes do);
for a group shown twice, the summary table follows its first panel. The options come in
sections: click a section's title to fold it (remembered).

A panel shows one group:

- **Histograms**: a channel, overlaid or offset; % of max, count or % of events. The range
  gates under the population shown are drawn as brackets above the plot.
- **Dot plot**: two channels, the gates on them with their %.
- **Values (bars)**: the statistic per label; for replicates, the mean ± SD, a dot per run.

### Options

- **Series, in order** (first; each label, in every panel): colour, dashes, fill, and
  **▲ ▼** for its place. The order is the legend's (read across, line by line), the tables'
  within each group, the bars', and the histograms' (the control drawn first, at the back),
  and it sets the automatic colours and dashes (the first series solid, then dashed…). Saved
  with the experiment; Ctrl+Z undoes a move. Labels shown under one name (▤ Aliases) are one
  series: one style, one legend entry, one place.
- **Style**: black & white (black lines with dashes, the control filled grey), overlaid or
  offset, the y axis, smoothed, filled, line widths (data, axes; two decimals: 0.75 can be
  typed), range gates, the value above each bar.
- **Text**: the sizes of the titles, axis titles, x and y tick labels, range labels, legend;
  the tick before a size shows or drops those texts — the titles, the x and the y axis
  titles each, the x and the y tick labels (a panel can drop its own). What is dropped gives
  its room to the plot; every plot stays the same size. A title wider than its panel goes on
  two lines, at its size.
- **style ▸ Apply**: a set at once (colour, black & white, offset, one column 85 mm, large for
  slides).
- *Options ▸ Figure options* sets which options are listed.

### The legend

Select it. Its place: below, above or right of the figure, **in the grid** (a place of its own,
dragged like a panel) or **in each panel**. Its columns or lines (*as many as fit*, *as
needed*: the default), alignment across (left / centred / right, with a margin) and up / down
(with an offset), line spacing, size. The alignment, margin and offset apply within its place:
the grid's place, the band above or below, the column on the right, or, in each panel, the
plot. **Del** (on it in the list or in the boxes, or right-click ▸ *Remove*) takes the legend
out of the figure; **+ legend** (under the list, or the dashed box under the layout) puts it
back where it was.

### Layout

In the middle, the figure as **boxes**, with its size above them: **panel / plot** and the
width × height, the columns, the width at most, the legend's place.

- **Drag a box** anywhere on the grid of quarter panels (dotted while dragging, halves a
  little brighter): its outline shows where it lands, red when it would cover another box
  (then it isn't taken). Nothing else moves. A panel can sit half a panel down, between two
  rows, or a quarter across.
- **The legend's place** takes as many quarters as its entries need; drag its corner **◢** to
  size it (down to a quarter of a panel each way); right-click it: *Size: as its entries
  need* undoes that.
- **A panel's shift** (in the Panel box, mm across and down) nudges its plot inside its place,
  the others staying put; dragging the panel elsewhere sets it back to 0. The margins
  themselves are the figure's, one set, so that every plot stays the same size.
- **+** adds a panel at the first free place. Right-click a box for its menu.
- **Columns** puts the panels back in rows of that many, in the list's order (the places
  they were dragged to are dropped). *As many as fit*: by the width.
- **Width at most**: a layout wider than this isn't drawn: the width turns red, a red line in
  the boxes shows where it ends and a message says by how much. Move a panel back, or raise
  the width. The figure isn't saved or copied meanwhile.
- **Panel / plot**: whether the width × height typed is each panel's (the title, ranges and
  axis labels inside it) or each plot's (the axes alone, the margins added around).
  Switching keeps the figure as it is. Either way **every plot of a figure is the same size**:
  the margins are the widest any panel needs, and the titles all sit at one height.

### The preview

On the right, the figure as exported: wheel to zoom, drag to move, double-click to fit,
**100 %** for its real size, a checker behind it (shows a transparent background). **res** 1–5×
draws the panels larger, the text as set (*export* ticked: the exports too). Click a panel to
select it; **Ctrl+C** copies the figure. **Save…** writes PNG / TIFF (at the dpi set) or SVG /
PDF (the text stays text); **Colour + B&W…** both at once.

## Results

- **The figure's table**: group, label, sub-population, events, % of parent, value and
  ÷ control, for each group's population the figure shows and the ranges below it.
- **Replicates**: runs pooled (below): each label's n, mean ± SD of the value and of
  ÷ control, each run's value.
- **Every sample and population**: count, % of parent, geometric mean, median, mean, CV.

*Population* names what was measured: the population each group's figure shows, or a range
below it (◆: the sample's own version of the gate). **Click a column's title** to sort by it,
again for the other way, a third time for the order as computed (empty cells always last);
hover a title for what the column is. The value and the channel measured are chosen here.
**⧉** (Ctrl+C: the selected rows, else all) copies the table as shown, to paste as a table in
Excel, Word or PowerPoint; **Export…** writes `.xlsx` (every sheet) or `.csv`.

## Experiment

What was done: title, date, operator, aim; each group's cells (cell line, transfection,
treatment, detachment); the reagents (kind — *sample* for what is tested, e.g. the sdAbs: in
the tube it is the primary —, target, fluorochrome, supplier, catalog #, lot, MW, stock, per
tube, dilution) and how each reads (*Anti his PE* → a PE-labelled anti-His-tag secondary
antibody); the procedure, one step per line (record it to reuse it); the acquisition and the
instrument as the files describe them. ⤢ opens a group or a reagent whole. The MIFlowCyt list
says what a report of this experiment holds and what is missing.

## Aliases

**▤ Aliases…** sets what the figure, the tables and the report call the groups, labels,
samples, channels and populations (*FL2-A :: PE-A* → *anti-His PE*). It opens on the groups;
the list above the table picks another kind, or *everything* (last). Double-click a *shown as*
cell to type; **Ctrl+C** copies a name, **Ctrl+V** pastes it as the selected rows' alias.
Remembered for the next experiments with the same names (untick to keep them to this one).

Two things under one name are one thing:

- **Labels**: one series. The controls of different cell lines (*0006*, *R3B23*) all shown as
  *Control*: one style, one legend entry.
- **Groups**: runs of one condition, pooled as **replicates**. Two groups whose names differ
  only by spaces, dashes or case (two runs' folders: *MDA-MB-157 parental cells* /
  *MDA-MB-157-parental cells*) get one name when they come in, and the log says so; clear
  the alias to keep them apart. Their tables add the run's day (*… · 2026-05-27*), and their
  figure panels too when both runs are in the figure. Each run is compared to its own control.

## Report

**Report…** (Ctrl+P): the format, the sections on the left (tick them, drag them in order;
each format keeps its own choice), the report as it will read on the right; **Save report…**.

- **PDF** and **web page**: the sections one after the other.
- **PowerPoint**: one slide, a figure page: the title, the figure at its size, the summary
  and the replicates as real tables (editable). Every other section ticked goes as text in
  the slide's notes (by default the experiment, procedure, gating, instrument and files).
- **Excel**: a sheet per section (Summary and Results, Replicates, Samples, Files, Experiment,
  Procedure, Gates, Instrument and Keywords, MIFlowCyt, the figure as a picture).

*Files* lists each FCS file (name, folder, last modified, SHA-256), and the gates' file while
the gates are as in it.

## Options

A page per topic: the sample columns shown; the channels offered (by default FSC-A, SSC-A and
the areas of the fluorochromes the reagents name; heights and other detectors hidden; a
channel a gate is on is always offered); the figure options listed. What Flowless remembers
(negative controls, aliases, recorded procedures, the columns and options shown, typed values)
is in `flowless_options.json` beside `Flowless.bat`.

## Files Flowless reads

- **FCS** 2.0 / 3.0 / 3.1 list-mode files (made on a BD Accuri C6 Plus; others read the same
  way): every channel, every keyword. Filters aren't in Accuri files: FL1 533/30, FL2 585/40,
  FL3 670 LP, FL4 675/25 are known.
- **An experiment** (`.json`): Flowless's own, saved with Ctrl+S. It finds the FCS files again
  from where it is, if the folder moves with them.
- **Gates**, Gating-ML 2.0 (`.xml`): polygons and ranges, nested.
- **FlowJo workspaces** (`.wsp`, FlowJo 10): the gates of each sample (polygons, rectangles,
  ranges, nested), so an analysis done in FlowJo opens here with the same populations. Its
  statistics aren't read (FlowJo recomputes them; Flowless computes its own). Ellipses,
  quadrants and Boolean gates are not read; the log names them. A workspace whose files have
  been renamed since is skipped (its event counts don't match).
- **BD Accuri C6 workspaces** (`.ci`): the run as the instrument saved it, no export needed.
  Its wells with events are written once as FCS files in a folder beside it
  (`<workspace>/<the run's start>/`), named as in the Accuri software (*PC-1* → group PC,
  label 1); wells already in (the same events) are skipped. Its polygons become the groups'
  gates, a well's adjusted version that sample's own. Other region kinds are not read; the
  log names them.
- **Procedure sheets** (`.xlsx`), free-form as the lab writes them: the steps, the reagents'
  MW and stock, the secondary antibody's line, the amounts, a conditions table per cell
  line. What can't be read stays in the sheet. µ and ° lost in old sheets are put back.

FlowJo is a trademark of Becton, Dickinson and Company. Flowless is not affiliated with it: it
reads the gates of FlowJo's workspace files (plain XML, the gates written in the Gating-ML
standard), uses none of its software and needs no FlowJo licence.

## How the numbers are made

- **Gates**: a polygon holds an event inside it, its sides straight on the plot it was drawn
  on (linear: the raw values; log, logicle: on those axes); a range holds low ≤ value < high.
  Events at the top of a channel's scale (an Accuri's FSC-A saturates for big cells: up to
  56 % of the events in the example runs; FSC-H never does) sit on the plot's edge: a gate
  drawn to that edge takes them; so do events below a log or logicle axis' bottom.
- **The auto gate**: a density contour (15 % of the peak) around the size-weighted peak,
  debris cut at the FSC dip, raised to the saddle when a second cluster would merge in. A
  starting point: 11–35 % wider than hand-drawn gates on the example runs.
- **Singlets**: the ridge A = c0 + c1·H through the densest area of each height slice (A/H
  grows with size, so one ratio would cut big singlets); a band −4σ / +3σ around it, σ from
  the singlets' side.
- **Live**: the dye's histogram on its axis; the gate ends at the lowest point between its
  main (dim) peak and a second (bright) one holding ≥ 3 % as much; with no second peak, 2.5
  half-widths above the main one. A starting point, as the other auto gates.
- **Logicle** (Parks et al. 2006): 4.5 decades, the top of the channel's scale at the top, the
  linear part W = (4.5 − log10(top / |r|)) / 2 decades wide, r the 5th percentile of the
  files' values below 0 (FlowJo's default is W 0.5).
- **Geometric mean**: exp(mean(ln x)) of the positive values. Median, mean and CV of all of
  them.
- **÷ control**: the value over the group's negative control's (else the secondary-only, else
  the unstained), in the same population.
- **Histograms**: 256 channels over the log scale, smoothed over a few channels when
  *smoothed* is ticked. *% of max* (the figure's default, "normalised to mode") scales each to
  its own peak, so samples with different event numbers compare (the table gives the events);
  *% of events* makes each histogram's area 100 % (fair when the peaks' widths differ).
- **Replicates**: per label and sub-population, n, mean and SD (n − 1) of the value and of
  ÷ control, each run over its own control (absolute intensities differ between runs).

Checked against FlowJo on the example runs: events per gate within 1.1 %, geometric means
within 0.2 %.

## Shortcuts

| Keys | |
|---|---|
| Ctrl+I | import files |
| Ctrl+S | save the experiment |
| Ctrl+P | report |
| Ctrl+Z / Ctrl+Y | undo / redo |
| Ctrl+C | copy the selected plot, table, figure or alias |
| Ctrl+V | paste an alias (▤ Aliases) |
| Del | delete the selected population, panel, legend or polygon corner |
| F2 | rename the selected population |
| Enter | close a polygon being drawn |
| Esc | cancel a drag |
