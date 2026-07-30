# Design: add-plan-prescription

## Context

Decided with Felix during brainstorming, 2026-07-30 (all three by explicit
choice): **compliance only** — the engine keeps the workout prior and there is
no `INTERVAL_VERSION` change; surfaces are **compliance row + briefing +
/run/:id plan card** (block lens and /compare are out); grammar is
**Approach A, tiny with honest refusal**; the verdict is **annotate-only** —
day status semantics stay stable ten days before the race, and status-flipping
is reconsidered after Sonthofen.

The parse target is the live plan's `segments[].val` corpus: 29 distinct
strings today, of which the structured core is rep sets and `@ ~pace` steady
targets; the rest is HR bands, race-plan km rows and prose that no parser
should pretend to read. `plan_compliance` already matches days to activities
and owns versioned rescoring; the interval document already knows what was
executed. This change is the join.

## Goals / Non-Goals

**Goals:**
- One pure parser whose entire behavior is pinned by the live corpus: every
  string parses to an exact shape or is explicitly refused.
- A per-day quality verdict joining prescription × interval document, worded
  for the coach and stored on the compliance row.
- The verdict visible in the briefing and on the run page's plan card.
- Works identically on Max's instance (his only prescription source).

**Non-Goals:**
- No engine prior from the plan (the watch's workout owns that; Max's
  engine-prior gap is a future change if the annotation proves valuable).
- No HR-band or race-km parsing; no /compare or block-lens integration.
- No status/reason changes from the verdict (annotate-only).
- No plan authoring-format changes.

## Decisions

### D1 — the prescription shape

```python
{"kind": "reps", "count": 4,
 "repDistM": 1000,          # OR "repDurS": 20 — never both
 "paceBandS": [325, 335],   # None on zone/effort sets
 "zone": None,              # 4 on `Z4`-prescribed sets
 "text": "4×1 km @ 5:25–5:35"}   # verbatim, for display
{"kind": "steady", "paceS": 370, "text": "16 km easy @ ~6:10"}
None                        # refusal — the day is not a parseable prescription
```

One prescription per day: segments are scanned in order and the first rep set
wins (the plan never prescribes two sets in one day; the embedded
`3 km easy · 3×400 m @ 5:41 inside` yields the 3×400 m). A single prescribed
pace (`@ 5:41`) becomes the band `[pace − 5, pace + 5]` s/km. `–` and `-`
both accepted as range dashes; `×` and `x` both as rep marks.

### D2 — the verdict object (`quality_json`)

Computed in `_score_run`'s caller once per matched run day, only when a
prescription parsed AND the activity has an interval document (fetched by
activity_id from `run_intervals`; absent → verdict records
`"no interval document"` honestly rather than guessing):

```python
{"planned": "4×1 km @ 5:25–5:35",       # display text
 "kind": "reps",
 "prescribed": 4, "found": 4,           # found from doc set (0 when steady doc)
 "inBand": 3,                            # pace sets: work paceS within band
 "zoneOk": None,                         # zone sets: doc quality.zone == f"Z{zone}"
 "verdict": "4/4 reps, 3 inside 5:25–5:35"}
```

Steady targets: `{"kind": "steady", "targetS": 370, "actualS": 373,
"verdict": "6:13 vs ~6:10 — on target"}` with ±10 s/km tolerance; rep-set
bands use their own edges (the coach chose them; no extra grace beyond D1's
±5 widening of single paces). Time-based rep sets (`4×20 s`) verdict on count
only — per-rep pace on a 20 s stride is noise. The wording never says
"failed": it states counts and bands; judgment stays with the coach
(coach-loop's standing rule).

### D3 — annotate-only, enforced structurally

The verdict writer touches ONLY `quality_json`. `_score_run` is not modified;
a test pins that two identical days with and without a parseable prescription
carry identical `status`/`reason`.

### D4 — storage and rescore

Schema v14: guarded `ALTER TABLE plan_compliance ADD COLUMN quality_json
TEXT`. `COMPLIANCE_VERSION = 2`; `_rescore_stale` already re-scores weeks
whose stored version is old, so the current block gains verdicts on the first
post-deploy sync without any new machinery. Historic snapshot rows stay as
their snapshots recorded them.

### D5 — surfaces

- Briefing: the compliance section appends the verdict sentence to quality
  days (`Tue — interval: done · 4/4 reps, 3 inside 5:25–5:35`).
- `serve.mjs`: the by-id `plan` object gains `quality` (parsed from
  `quality_json`; omitted when NULL — same absence rule as everywhere).
- `run.dc.html`: the plan card renders `planned` + `verdict` under the
  existing planned-vs-actual line. Absent → renders nothing new.

### D6 — the corpus is the test

`tests/fixtures/plan_vals.json` pins all 29 distinct live `val` strings (and
the day-shape context where the embedded form needs it) to expected parses or
explicit refusals. A sweep test asserts the corpus is CURRENT — it re-extracts
the distinct strings from `plan-data.js` at test time and fails if a new
string appears unpinned, so the grammar can never silently drift behind the
live plan. (Read-only on the symlinked plan file.)

## Risks / Trade-offs

- [Coach edits plan wording mid-block → refusals appear] → refusal is the safe
  state (distance-only scoring, no verdict); the corpus-currency test flags
  the new string on the next local run.
- [Per-rep pace vs band judged on `paceS` while some sets are hilly] → the
  band was prescribed as raw pace by the coach; raw is also what P2.1 decided
  the set reports. Zone sets already sidestep this.
- [`quality_json` bloat in the contract] → briefing/serve read it lazily;
  rows without verdicts carry NULL.
- [Rescore changes compliance chips mid-race-week] → annotate-only means
  status/reason cannot move; only new information appears.

## Migration Plan

Schema v14 is additive; `COMPLIANCE_VERSION` bump rescoress the current block
on first sync. Standard CI → NUC deploy; post-deploy check: verdicts present
on the block's quality days, statuses byte-identical to pre-deploy, briefing
renders, `verify_archive` exit 0.

## Open Questions

None.
