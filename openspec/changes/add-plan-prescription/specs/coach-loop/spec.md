## ADDED Requirements

### Requirement: The plan's structured prescriptions are parsed, and everything else is refused

A pure parser SHALL extract at most one prescription per planned day from its
`segments[].val` strings: a rep set (count, rep distance or duration, optional
pace band, optional zone) or a steady pace target. Strings outside this
grammar SHALL be refused — the day then keeps distance-only scoring, and the
system SHALL NOT guess. Every distinct `val` string in the live plan SHALL be
pinned by a fixture to its parsed shape or to explicit refusal, and a test
SHALL fail when the live plan introduces a string the fixture does not pin.

#### Scenario: A rep set with a pace band parses

- **WHEN** a day's segment reads `4×1 km @ 5:25–5:35`
- **THEN** the prescription is a rep set with count 4, rep distance 1000 m,
  and the band 5:25–5:35

#### Scenario: An embedded rep set parses out of a hybrid day

- **WHEN** a day's segment reads `3 km easy · 3×400 m @ 5:41 inside`
- **THEN** the prescription is the 3×400 m rep set (single pace widened to a
  symmetric band)

#### Scenario: Prose is refused, not guessed

- **WHEN** a day's segments carry only prose or unsupported forms (HR bands,
  race-km rows)
- **THEN** no prescription is produced and the day's scoring is unchanged

### Requirement: Quality days carry a rep-level verdict that never changes their status

For a matched run day whose prescription parsed and whose activity holds an
interval document, the compliance row SHALL carry a verdict object recording
the planned text, prescribed vs found rep counts, the in-band count (pace
sets), or the zone agreement (zone sets), or target-vs-actual pace (steady
targets), worded as counts and bands — judgment stays with the coach. The
verdict SHALL be an annotation only: the day's `status` and `reason` SHALL be
byte-identical with and without a parseable prescription. When the activity
has no interval document, the verdict SHALL say so rather than guess.
Compliance versioning SHALL bump so existing scoreable weeks gain verdicts by
rescore.

#### Scenario: A completed set is annotated

- **WHEN** the plan prescribed `4×1 km @ 5:25–5:35` and the run's interval
  document found 4 reps of which 3 lie inside the band
- **THEN** the row's verdict reads counts and band (e.g. `4/4 reps, 3 inside
  5:25–5:35`) and the day's status is what distance/intensity scoring alone
  decides

#### Scenario: A bailed set is visible without a status change

- **WHEN** the prescription expected 4 reps and the document found 2
- **THEN** the verdict records `2/4` while `status`/`reason` are unchanged
  from distance-only scoring

#### Scenario: The briefing speaks the verdict

- **WHEN** the briefing renders a compliance section containing an annotated
  quality day
- **THEN** the day's line carries the verdict sentence
