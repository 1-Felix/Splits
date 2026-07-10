# Wellness fixtures

Real Garmin payloads, captured 2026-07-10 from the live account, stored
**verbatim** apart from one scrub: `userProfilePk` / `userProfileId` are zeroed.

They exist because the sleep payload's shape has drifted over the account's
lifetime, and `promote_wellness()` must keep working against every era it will
meet during a backfill. See `openspec/changes/wellness-archive/design.md` (D6).

| fixture | date | why it is here |
|---|---|---|
| `era2024-onboarding-{sleep,hrv}.json` | 2024-05-12 | Oldest era: sleep payload has **7** top-level keys. HRV is mid-onboarding — `weeklyAvg` and `baseline` are `null`, `status` is `NONE`. The first activity in the archive, so this is the backfill's horizon. |
| `era2026-mature-{sleep,hrv}.json` | 2026-07-05 | Current era: sleep payload has **18** top-level keys (`avgOvernightHrv`, `hrvStatus`, `sleepStress`, `sleepBodyBattery`, `sleepHeartRate`, `respirationVersion`, … are all recent additions). HRV baseline established. |
| `empty-night-{sleep,hrv}.json` | 2024-09-02 | The watch was not worn. Sleep payload is **present but hollow**: 4 top-level keys, every sleep metric `null`, and `restingHeartRate` is `null`. HRV still carries `weeklyAvg` and `baseline` — only `lastNightAvg` is `null`. |

## What the empty night taught us

Two things, both of which corrected the design:

1. **A hollow payload is not an absent payload.** `restingHeartRate` is `null`
   inside a sleep payload that exists. The resting-HR fallback to
   `get_rhr_day` must therefore trigger on a **null value**, not on a missing
   payload. (`get_rhr_day("2024-09-02")` returns 56.0, so the fallback is worth
   making.)

2. **"No device data" is not all-or-nothing.** HRV's rolling `weeklyAvg` and
   `baseline` survive a night off the wrist while `lastNightAvg` goes null.
   Promoted columns must be independently nullable.

## Shape note

`hrvSummary.baseline` is an object, not a pair of bounds:

```json
"baseline": { "lowUpper": 51, "balancedLow": 53, "balancedUpper": 63, "markerValue": 0.5499878 }
```

`balancedLow` / `balancedUpper` are the band a chart should draw.

## Regenerating

These are inputs to tests, not to the archive. Nothing reads them at runtime.
Re-capture only if Garmin's shape drifts again — and if it does, add a new era
rather than overwriting an old one, because the old shape still exists in the
account's history.
