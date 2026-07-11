# chart-drill Delta

## ADDED Requirements

### Requirement: A pinned reading drills down to its evidence
Charts whose points summarize runs SHALL offer a drill-down as the second
activation of the existing pin interaction: activating an already-pinned
reading (clicking its card or pressing Enter on the pinned point) SHALL invoke
the chart's declared drill, and Escape SHALL walk back one step at a time
(evidence view → pinned reading → nothing). The affordance SHALL be visible on
the pinned card before it is invoked, naming what the drill opens. The drill
SHALL be operable entirely by keyboard. Charts that declare no drill SHALL
behave exactly as before.

#### Scenario: Drilling via keyboard only
- **WHEN** the user focuses a drillable chart, pins a point with Enter, and
  presses Enter again
- **THEN** the point's evidence view opens, and pressing Escape returns to the
  pinned reading with focus back on the chart, and a second Escape dismisses
  the pin

#### Scenario: The affordance announces itself before acting
- **WHEN** a point on a drillable chart is pinned
- **THEN** the pinned card shows a drill affordance naming its target (e.g.
  "view evidence", "view anchor run") and no navigation or fetch has happened
  yet

#### Scenario: A chart without a drill is unchanged
- **WHEN** the user pins a point on a chart that declares no drill and presses
  Enter again
- **THEN** the pin behaves exactly as before this change and no drill
  affordance is rendered

### Requirement: The contribution panel shows the honest composition of a pooled point
Drilling a pooled aggregate point SHALL open a panel beneath the chart —
for the monthly pace-at-reference-HR and cadence-at-reference-pace charts —
listing the period's runs in two groups: **contributed** runs — each with its in-band
time, its own in-band value (pace or cadence), and its share of the period's
pool — and runs that **did not count**, each with its reason derived from the
served columns (no time in band; not yet analysed). The panel header SHALL
restate the plotted value from the static insights block and the panel SHALL
NOT re-derive or overwrite that value from fetched rows. Every listed run
SHALL link to its `/run/<activityId>` page, and the panel SHALL link to the
archive browser. The excluded group SHALL be collapsed behind a disclosure by
default. At most one panel SHALL be open per page at a time.

#### Scenario: A month's evidence is itemized
- **WHEN** the viewer drills a valid monthly pace-at-reference-HR point
- **THEN** the panel lists the month's contributing runs with in-band minutes,
  per-run in-band pace, and share, and its header shows the same value the
  chart plots for that month

#### Scenario: A hollow month explains itself
- **WHEN** the viewer drills a month rendered hollow or adjacent to a gap
- **THEN** the panel shows the runs that did not count with their reasons, so
  the thin evidence is explained rather than mysterious

#### Scenario: Rows navigate to run detail
- **WHEN** the viewer activates a run row in the panel
- **THEN** the browser navigates to that run's `/run/<activityId>` page

#### Scenario: Opening a second panel closes the first
- **WHEN** a panel is open for one chart and the viewer drills a point on
  another chart of the same page
- **THEN** the first panel closes and the second opens

### Requirement: Drill evidence is fetched lazily and degrades honestly
No drill SHALL fetch anything before its activation. When the archive API is
unavailable (503, network failure, or a server without the endpoint), the
panel SHALL render an explicit archive-offline state inside itself — the
chart, its pin, and the rest of the page remaining fully functional — and
SHALL offer a retry that works without a page reload.

#### Scenario: No fetch before the drill
- **WHEN** a drillable chart renders and the viewer hovers and pins points
  without drilling
- **THEN** no request to any archive endpoint is made

#### Scenario: The archive is offline at drill time
- **WHEN** the viewer drills a point while archive endpoints return 503
- **THEN** the panel shows an honest offline state with a retry control, and
  the chart and pinned reading remain usable

#### Scenario: Retry after the archive returns
- **WHEN** the viewer activates the panel's retry after the archive becomes
  reachable
- **THEN** the evidence loads and renders without a full page reload

### Requirement: Single-run points drill directly to the run
Where an aggregate point is backed by exactly one run, the drill SHALL be a
direct navigation to that run's page rather than a panel: the trajectory's
pinned week links to its anchoring effort's run from static data, and a
heatmap day cell resolves its day's runs on activation — navigating directly
when the day holds one run, offering a minimal chooser when it holds several.
Points with no backing run (null weeks, zero-km days) SHALL declare no drill
and remain inert.

#### Scenario: A day with one run navigates directly
- **WHEN** the viewer activates a heatmap cell for a day with exactly one run
- **THEN** the browser navigates to that run's `/run/<activityId>` page

#### Scenario: A day with several runs offers a chooser
- **WHEN** the viewer activates a heatmap cell for a day with two runs
- **THEN** a chooser names both runs and activating one navigates to its page

#### Scenario: An empty point is inert
- **WHEN** the viewer interacts with a zero-km heatmap cell or a trajectory
  week with a null Riegel value
- **THEN** no drill affordance is offered and nothing navigates
