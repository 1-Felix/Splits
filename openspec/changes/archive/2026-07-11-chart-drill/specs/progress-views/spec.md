# progress-views Delta

## ADDED Requirements

### Requirement: Aggregate progress charts drill to their evidence
The progress page's pooled monthly charts SHALL drill to the contribution
panel defined by the chart-drill capability — pace at reference HR and
cadence at reference pace — fed by the archive run-metrics endpoint for the
pinned month. The year-over-year monthly bars SHALL drill to the same panel
shell listing every run of the pinned month (fed by the existing listing
endpoint's date-range filter), without a didn't-count section — volume counts
every run. Panels SHALL render beneath their chart, one open at a time, with
focus moving into the panel on open and returning to the chart on close.

#### Scenario: A pooled month drills to its contribution split
- **WHEN** the viewer drills a pinned month on the pace-at-reference-HR chart
- **THEN** a panel opens beneath the chart showing that month's contributing
  runs (in-band minutes, per-run in-band pace, share) and its didn't-count
  disclosure, each run linking to its `/run/<activityId>` page

#### Scenario: A YoY month drills to all of its runs
- **WHEN** the viewer drills a pinned month on the year-over-year bars
- **THEN** the panel lists every running activity of that month and year with
  date, name, and distance — no didn't-count section — each linking to its run
  page

#### Scenario: Focus is managed across open and close
- **WHEN** the viewer drills a point via keyboard and then presses Escape
- **THEN** focus moves into the panel on open and returns to the chart with
  the pin intact on close

## MODIFIED Requirements

### Requirement: The progress page is static-first
The progress page SHALL render all of its views from static data files alone;
the archive API SHALL be required only for drill-down interactions — record
click-throughs and chart evidence panels. API unavailability MUST NOT blank
any statically-renderable content.

#### Scenario: Full render with the API down
- **WHEN** the progress page loads while archive endpoints return 503
- **THEN** the records wall, year-over-year view, and all relocated sections
  render fully; only drill-down interactions surface the offline state

#### Scenario: A drill against a down API degrades inside its panel
- **WHEN** the viewer drills a chart point while archive endpoints return 503
- **THEN** the panel shows the honest offline state with a retry, and every
  chart and section of the page remains fully usable
