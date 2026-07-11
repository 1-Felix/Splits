# run-comparison Specification

## Purpose
Side-by-side comparison of two to four archived runs, driven entirely by ids
in the URL: summary metrics with best-per-row marks, per-kilometre splits
aligned by index with honest tails, and per-measure stream tracks overlaid on
one shared distance axis — one scale per measure, one crosshair, a finished
run reading as ended. Entered from the archive browser's selection tray or any
shared link; degrades honestly per slot and wholesale.

## Requirements

### Requirement: Runs are selected for comparison from the archive browser

The archive page SHALL let the viewer select run rows for comparison and, with
at least two selected, offer a compare action that navigates to the comparison
view carrying the selected activity ids. Selection SHALL be capped at four
runs, refusing further selections with a visible hint rather than silently
dropping one. Only run rows SHALL be selectable.

#### Scenario: Two runs are compared
- **WHEN** the viewer selects two runs and activates the compare action
- **THEN** the browser navigates to the comparison view with both ids in the
  URL, in selection order

#### Scenario: The cap is enforced visibly
- **WHEN** four runs are selected and the viewer attempts a fifth
- **THEN** the fifth selection is refused with a visible indication and the
  existing selection is unchanged

### Requirement: The comparison view is driven by ids in the URL

The dashboard SHALL serve a comparison page whose compared runs are determined
entirely by activity ids in its URL, so any comparison is shareable and
bookmarkable without going through the browser page. Ids SHALL be validated as
numeric client-side before any request; invalid ids are dropped and duplicates
collapsed, keeping at most four. With fewer than two resolvable runs the page
SHALL render an honest prompt state instead of a comparison.

#### Scenario: A shared comparison URL renders
- **WHEN** a viewer opens the comparison URL carrying two archived run ids
  directly
- **THEN** the comparison renders those two runs without any prior selection
  state

#### Scenario: Garbage ids are dropped
- **WHEN** the URL carries a non-numeric id alongside two valid ones
- **THEN** the non-numeric id is ignored, no request is issued for it, and the
  two valid runs compare normally

#### Scenario: Too few runs to compare
- **WHEN** the URL resolves to fewer than two known runs
- **THEN** the page renders an honest state naming the problem, not a broken
  or empty comparison

### Requirement: Summary metrics compare side by side without recomputation

The comparison SHALL render one labelled column per run with the promoted
summary fields (date, name, distance, duration, average HR, average cadence,
elevation gain — plus average pace presented as duration ÷ distance over two
promoted fields), read from the archive API without domain recomputation, and
SHALL visually mark the best value per comparable row as presentation only.

#### Scenario: Columns render per run
- **WHEN** the comparison renders three runs
- **THEN** three labelled columns show each run's summary fields, with the
  best value per row marked

### Requirement: Per-kilometre splits align by kilometre index

The comparison SHALL render the compared runs' per-kilometre splits aligned by
kilometre index so kilometre N is read across runs at a glance. Where runs
differ in length, the longer run's extra kilometres SHALL render alone,
honestly — no truncation to the shortest run and no fabricated splits.

#### Scenario: Different-length runs stay honest
- **WHEN** a 12 km run is compared with a 21 km run
- **THEN** kilometres 1–12 render aligned across both runs and kilometres
  13–21 render for the longer run alone

### Requirement: Streams overlay per measure on shared, comparable scales

The comparison SHALL render one track per measure (pace, heart rate, cadence,
elevation), overlaying the compared runs as distinctly colored series with a
legend naming each run, consistent across all tracks. All tracks SHALL share
one distance-based x domain spanning the longest compared run, and each
measure's y domain SHALL be resolved over the union of the compared runs'
series through the established domain policies (pace keeps its quantile clip),
so every run is read against the same scale. No track SHALL plot two measures
against two scales.

#### Scenario: Runs share one scale per measure
- **WHEN** two runs with different pace ranges are compared
- **THEN** both pace series render against one shared y domain and axis, and a
  bar of the same height means the same pace for either run

#### Scenario: A GPS spike cannot own the shared scale
- **WHEN** one compared run's pace stream carries start-up spikes
- **THEN** the shared pace domain is resolved with the established clip policy
  and the other runs' series remain readable

### Requirement: One crosshair reads every run at the same distance

The comparison's tracks SHALL share a single crosshair indexed by distance:
one position reads every compared run's value at that distance across every
track, with a per-run readout. A run shorter than the crosshair position SHALL
read as ended at that distance, not as a value.

#### Scenario: Reading km 15 across runs
- **WHEN** the viewer moves the crosshair to the 15 km position
- **THEN** every track shows each run's value at 15 km, and a run that ended
  at 12 km reads as ended rather than showing a number

### Requirement: Missing data degrades per run and per track

A run missing a measure SHALL simply be absent from that measure's track; a
measure carried by no compared run SHALL omit its track entirely. A run
without a stored stream SHALL still occupy its summary and splits columns,
with the tracks' legend noting it carries no stream. An id unknown to the
archive SHALL render an honest per-slot unknown-run state while the remaining
runs compare normally.

#### Scenario: A run without cadence
- **WHEN** one compared run carries no cadence data
- **THEN** the cadence track renders the other runs only, without an error or
  an empty placeholder series

#### Scenario: A summary-only run
- **WHEN** a compared run has no stored stream
- **THEN** its summary and splits columns render and the legend states it has
  no stream, while other runs' tracks render normally

#### Scenario: One unknown id among known runs
- **WHEN** the URL carries one id the archive does not hold alongside two
  known runs
- **THEN** the unknown slot states the run is unknown and the two known runs
  compare normally

### Requirement: The comparison degrades honestly when the archive is unreachable

The comparison page SHALL render its chrome with an honest archive-offline
state when the archive API is unavailable, and MUST NOT render a broken page
or a partial, misleading comparison — it is a deep view. Per-run fetch
failures SHALL be reported in that run's slot without discarding runs that
loaded.

#### Scenario: Archive down at load
- **WHEN** the comparison page loads while the archive API returns 503
- **THEN** the page chrome renders with an archive-offline indication where
  the comparison would be

#### Scenario: One run's stream request fails
- **WHEN** one run's stream request returns 503 while the others resolve
- **THEN** that run's slot reports the failure and the resolved runs render,
  with scales computed over the runs actually shown
