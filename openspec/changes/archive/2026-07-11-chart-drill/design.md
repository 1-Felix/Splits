# Design — chart-drill

## Context

Aggregate charts summarize runs; the evidence lives elsewhere. What exists
already: per-run band aggregates and best efforts in `run_metrics` (versioned,
self-healing via `METRICS_VERSION`); monthly/weekly series assembled at sync
into the static `insights` block; the chart engine's pin interaction (click or
Enter/Space pins a reading and renders a floating card, Escape dismisses —
`chart-view.js` `hover.onPin`); `/run/:id` pages for any archived run; the
`/archive` browser with URL-mirrored filters; a read-only archive API with
type/year/date-range/name filters, fail-soft 503s, and a strict no-derivation
contract.

The pooled monthly charts are *filtered* aggregates — pace @ ref HR counts
only seconds inside the 125–145 bpm band, cadence @ ref pace only seconds
inside the pace band — so "the runs of the month" and "the runs that fed this
point" are different sets. A drill-down that ignores that difference answers
the wrong question.

Architecture principles inherited: the cockpit renders complete without any
API (interactions may reach the archive, display may not); deep views talk to
the archive API and degrade to honest offline states; derivation lives in the
Python sync — the server serves columns verbatim, the chart modules compute no
training metric the data file doesn't carry; presentation arithmetic over
already-derived data is allowed (the reference-layer carve-out).

## Goals / Non-Goals

**Goals:**

- Every run-backed aggregate point can be walked to its evidence: point →
  period composition → `/run/:id`.
- The composition view is honest: contributed runs with their in-band weight
  and value, non-contributing runs with the reason — the panel that finally
  explains hollow dots and gaps.
- The affordance is engine-level and keyboard-complete, like the rest of the
  a11y contract — no chart can ship a mouse-only drill.
- Evidence data is lazy-fetched on drill; nothing new is added to the static
  payload except the trajectory anchor ids; all failure modes degrade inside
  the panel.

**Non-Goals:**

- Wellness charts (sleep, HRV) — nightly readings, not run aggregates.
- No compare-from-panel flow (the panel links into `/archive`, where the
  existing compare tray lives; a future change may add checkboxes).
- No URL mirroring of an open drill panel; no month-granular archive-page
  filter UI (the panel itself is the month view).
- No server-side derivation, no new training metrics outside the sync, no
  change to how the plotted points themselves are computed.

## Decisions

### D1 — Drill is the pin's second activation, owned by the engine

The interaction ladder extends the shipped one: hover/arrows read, click/Enter
pins, **activating the pinned reading again drills**, Escape walks back one
rung (panel → pin → nothing). A chart opts in by declaring a `drill`
descriptor in its chart description; `buildSpec` threads it through, and
`renderChart` renders the affordance row on the pinned card (e.g. "8 runs ·
view evidence →"), wires click on the card, Enter on the pinned point, and the
Escape ladder. Charts without a descriptor keep today's behavior exactly.
Alternatives rejected: a per-chart button outside the plot (clutter, per-chart
a11y wiring drifts) and navigate-on-first-click (accidental navigation, loses
the read-then-decide step). Enter on a chart with no descriptor keeps its
current pin-toggle meaning — no behavior change outside opted-in charts.

### D2 — The engine owns the affordance; pages own the drill action

The descriptor carries a label and an action per point index. Two action
shapes cover every chart: a **panel** action (the page opens its contribution
panel for that point) and a **link** action (the page navigates — trajectory
anchor, heatmap day). The engine never fetches, never routes, never knows what
a month is; it renders the affordance, announces it, and invokes the action.
This keeps chart-core pure (geometry + descriptor pass-through, testable
without DOM) and keeps network and navigation in the pages, where the
fail-soft patterns already live.

### D3 — Per-run display values become sync-written columns (version bump)

The panel shows each run's in-band pace and in-band cadence. Those are
training metrics (`refhr_time_s / refhr_dist_m`, `refpace_cadence_x_time /
refpace_time_s`), so they are computed in `insight_metrics.py` at extraction
and stored as new `run_metrics` columns — `refhr_pace_s_per_km`,
`refpace_cadence_spm` — null when the run has no in-band distance/time.
`METRICS_VERSION` bumps; the existing self-heal recomputes every row on the
next sync (seconds for years of data, per the module's own doc). Alternative
rejected: dividing stored columns client-side or server-side — both violate
the "derivation lives in Python" contract that keeps every number auditable in
one place.

### D4 — One new archive endpoint: `GET /api/archive/run-metrics?from&to`

Serves, for running activities whose local start date falls in `[from, to]`,
one row per activity: promoted columns for identity and context (activity id,
local start time, name, distance, duration, `is_treadmill`) LEFT-JOINed with
the `run_metrics` band-aggregate columns (`refhr_time_s`, `refhr_dist_m`,
`refhr_pace_s_per_km`, `refpace_time_s`, `refpace_cadence_spm`,
`metrics_version`) — verbatim, newest-first. A run without a `run_metrics` row
appears with null aggregates (the client renders "not yet analysed"). Spans
longer than 92 days are rejected with 400 — the endpoint exists to explain one
period, not to bulk-export; no pagination needed under that bound. Non-GET
rejected; read-only per-request open, fail-soft 503, no raw payloads — the
existing archive-API blanket requirements already cover every "archive
endpoint". Alternative rejected: extending the listing endpoint with
`?include=metrics` — its contract is explicitly "promoted columns only", and
widening it complicates a shipped, tested surface.

### D5 — The panel is evidence, not recomputation

The panel header restates the pinned point's plotted value **from the static
insights block** — it never re-derives it from fetched rows. Below, rows split
into **contributed** (in-band minutes, per-run in-band value, share of the
month's pool — share is presentation arithmetic over served columns, per the
reference-layer carve-out) and **didn't count** (reason from served columns:
zero in-band seconds → "no time in band"; null aggregates → "not yet
analysed"; treadmill runs *do* contribute to pools and are never listed as
excluded here). If the archive has synced newer runs than the loaded page,
rows may not sum exactly to the plotted point; the panel makes no claim that
they do. The excluded section sits behind a disclosure ("n runs didn't count
▸") to bound panel height.

### D6 — Panel placement: inline expanse under the chart card

The panel renders as a full-width region directly beneath its chart (bottom
sheet feel on phones, no popover — the table is too wide for the floating
card). One panel open per page at a time (the THIS WEEK expand precedent).
On open, focus moves to the panel heading; Escape or close returns focus to
the chart with the pin intact. Rows are plain links to `/run/<id>`; a footer
link "open <year> in archive →" points at `/archive?type=running&year=YYYY`
(the archive page's URL filters are type/year/name — month granularity lives
in the panel itself, so the year link is a browse-around convenience, not the
answer).

### D7 — YoY bars drill through the existing listing endpoint

A YoY month is a plain sum — every run counts. Its panel lists the month's
runs from `GET /api/archive/activities?type=running&from=…&to=…` (the listing
already supports date ranges) with distance/duration/date, no exclusion
section, no metrics columns. Same panel shell, same offline behavior.

### D8 — Trajectory weekly points carry their anchor id (static link drill)

`weekly_trajectory` keeps the anchor's activity id alongside its seconds and
emits `anchorId` on weeks with a non-null `riegelSec` (precedent:
`bestEfforts.byYear` carries activity ids for exactly this purpose). The
cockpit's trajectory card gains a link drill: pinned week → "view anchor run
→" → `/run/<anchorId>`. No API involved, works offline — consistent with the
cockpit's static-first rule. Weeks with null Riegel declare no drill.
Validation shape-checks `anchorId` when present; older data files stay valid.

### D9 — Heatmap day cells drill via lazy lookup

Cells with km > 0 declare a link drill. Activation fetches the day's runs from
the listing endpoint (`from=to=day, type=running`): exactly one → navigate to
`/run/<id>`; several → a minimal chooser (date-named links) in place; 503 or
network failure → an inline "archive offline" note, cell and page otherwise
untouched. Zero-km cells declare nothing and stay inert. The cockpit's
*display* still requires no API — the fetch happens only on activation, the
same shape as `/progress` record click-throughs. Alternative rejected:
embedding day→activity-id maps into the static payload — grows the hot file
forever to save one on-demand request on a rare interaction.

## Risks / Trade-offs

- **[Enter semantics change on opted-in charts]** Enter on an already-pinned
  point currently re-pins; it will drill where a descriptor exists. →
  Mitigation: only opted-in charts change; the affordance row on the card
  makes the second action visible before it's invoked; Escape always walks
  back.
- **[Panel rows vs plotted point drift after a fresh sync]** → D5: the panel
  is evidence, not recomputation; it restates the static value and never
  asserts the sum.
- **[Old server + new page (or vice versa)]** New page fetching a missing
  endpoint gets 404/503 → the panel's offline state covers both; old pages
  ignore the new columns and `anchorId` (additive contract, validation keeps
  older files passing).
- **[METRICS_VERSION bump recomputes every row]** → Documented cost is seconds
  for years of data; self-healing, no manual step, no raw-table loss.
- **[Interactive region flakiness in page tests]** → Follow the shipped
  Playwright pattern (`domcontentloaded` + `waitForFunction`, never
  `networkidle`), drive the drill via keyboard where possible.

## Migration Plan

1. Sync first: new columns + version bump + `anchorId` + validation. The next
   nightly (or manual) sync self-heals every `run_metrics` row and emits the
   enriched insights block. Old dashboards ignore both additions.
2. Server: add the run-metrics endpoint (additive route; no existing route
   touched).
3. Engine + pages: drill affordance, panels, links — all feature-detect their
   data (`anchorId` present? endpoint reachable?) and degrade to today's
   behavior when absent.
4. Rollback: revert the page/engine commit — the data contract additions are
   inert without consumers; no schema rollback needed (`run_metrics` columns
   are additive, version-stamped).

## Open Questions

None blocking — the fork points (endpoint shape, Enter semantics, panel
placement, heatmap lookup) are decided above.
