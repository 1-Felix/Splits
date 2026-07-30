# Baseline before add-workout-prior

Read-only production sweep, captured 2026-07-30 at `INTERVAL_VERSION` 5
(after fix-lap-confidence deployed). Diff target for task 12.4: expected
movement is exactly the runs enumerated there and nothing else.

- shapes: steady 130 / reps 24 / block 14 / progression 2
- sources: stream 146 / laps 24
- 92 of 170 documents carry a `workoutId`

| date | shape | label | source | conf | asserts | found | workoutId |
|---|---|---|---|---|---|---|---|
| 2024-05-12 | reps | 3×800 m | stream | 0.95 | True | 3 | — |
| 2024-05-16 | steady | — | stream | 1.0 | True | — | — |
| 2024-05-18 | steady | — | stream | 1.0 | True | — | — |
| 2024-05-21 | block | 6 min block | stream | 1.0 | True | — | — |
| 2024-05-24 | reps | 3 reps | stream | 0.31 | False | 3 | — |
| 2024-05-26 | reps | 3 reps | stream | 0.75 | True | 3 | — |
| 2024-05-27 | steady | — | stream | 1.0 | True | — | — |
| 2024-06-15 | steady | — | stream | 1.0 | True | — | — |
| 2024-06-16 | steady | — | stream | 1.0 | True | — | — |
| 2024-06-19 | steady | — | stream | 1.0 | True | — | — |
| 2024-06-21 | steady | — | stream | 1.0 | True | — | — |
| 2024-06-25 | steady | — | stream | 0.78 | True | — | — |
| 2024-07-13 | block | 5 min block | laps | 1.0 | True | — | 960655494 |
| 2024-07-22 | steady | — | laps | 1.0 | True | — | 960686471 |
| 2024-09-08 | steady | — | stream | 1.0 | True | — | — |
| 2024-09-22 | steady | — | stream | 1.0 | True | — | — |
| 2025-03-22 | steady | — | stream | 1.0 | True | — | — |
| 2025-03-30 | steady | — | stream | 1.0 | True | — | — |
| 2025-04-08 | steady | — | stream | 1.0 | True | — | — |
| 2025-04-20 | steady | — | stream | 1.0 | True | — | — |
| 2025-05-11 | steady | — | stream | 1.0 | True | — | — |
| 2025-05-18 | steady | — | stream | 0.56 | True | — | — |
| 2025-05-21 | steady | — | stream | 1.0 | True | — | — |
| 2025-05-28 | steady | — | stream | 0.54 | True | — | — |
| 2025-06-01 | steady | — | stream | 0.51 | True | — | — |
| 2025-06-08 | steady | — | stream | 0.64 | True | — | — |
| 2025-06-22 | steady | — | stream | 0.68 | True | — | — |
| 2025-06-29 | steady | — | stream | 0.57 | True | — | — |
| 2025-07-02 | steady | — | stream | 0.75 | True | — | — |
| 2025-07-05 | steady | — | stream | 0.66 | True | — | — |
| 2025-07-06 | steady | — | stream | 0.67 | True | — | — |
| 2025-07-09 | steady | — | stream | 0.88 | True | — | — |
| 2025-07-11 | steady | — | stream | 0.48 | False | — | — |
| 2025-07-16 | steady | — | stream | 0.88 | True | — | — |
| 2025-07-19 | steady | — | stream | 1.0 | True | — | — |
| 2025-07-20 | steady | — | stream | 0.94 | True | — | — |
| 2025-07-23 | steady | — | stream | 0.5 | True | — | — |
| 2025-07-26 | steady | — | stream | 0.65 | True | — | — |
| 2025-07-31 | steady | — | stream | 0.54 | True | — | — |
| 2025-08-03 | steady | — | stream | 0.6 | True | — | — |
| 2025-08-06 | steady | — | stream | 0.76 | True | — | — |
| 2025-08-10 | steady | — | stream | 0.86 | True | — | — |
| 2025-08-13 | steady | — | stream | 0.56 | True | — | — |
| 2025-08-20 | steady | — | stream | 0.49 | False | — | — |
| 2025-08-27 | steady | — | stream | 0.48 | False | — | — |
| 2025-09-03 | steady | — | stream | 0.85 | True | — | — |
| 2025-09-07 | steady | — | stream | 0.47 | False | — | — |
| 2025-09-10 | steady | — | stream | 0.47 | False | — | 1324566738 |
| 2025-09-14 | steady | — | stream | 0.46 | False | — | 1324566748 |
| 2025-09-17 | block | 7 min block | stream | 1.0 | True | — | — |
| 2025-09-19 | reps | 6×200 m | laps | 1.0 | True | 6 | 1332425595 |
| 2025-09-21 | steady | — | stream | 0.41 | False | — | — |
| 2025-09-21 | steady | — | stream | 1.0 | True | — | 1332478234 |
| 2025-09-24 | steady | — | stream | 0.78 | True | — | 1332481148 |
| 2025-09-26 | block | 14 min block | laps | 1.0 | True | — | 1332482179 |
| 2025-09-28 | steady | — | stream | 0.52 | True | — | 1332483142 |
| 2025-10-01 | steady | — | stream | 0.0 | False | — | 1344457192 |
| 2025-10-03 | block | 18 min block | laps | 1.0 | True | — | 1344458458 |
| 2025-10-05 | steady | — | stream | 0.59 | True | — | 1344461278 |
| 2025-10-08 | steady | — | stream | 0.44 | False | — | 1344462095 |
| 2025-10-10 | steady | — | stream | 1.0 | True | — | — |
| 2025-10-12 | steady | — | stream | 0.5 | True | — | — |
| 2025-10-12 | steady | — | stream | 0.46 | False | — | — |
| 2025-10-15 | steady | — | stream | 0.4 | False | — | 1357219235 |
| 2025-10-17 | reps | 6 reps | laps | 1.0 | True | 6 | 1357916773 |
| 2025-10-19 | steady | — | stream | 0.41 | False | — | 1357917591 |
| 2025-10-22 | steady | — | stream | 0.79 | True | — | 1357918534 |
| 2025-10-24 | block | 19 min block | laps | 1.0 | True | — | 1357919142 |
| 2025-10-26 | steady | — | stream | 0.0 | False | — | 1357919993 |
| 2025-10-31 | steady | — | stream | 0.98 | True | — | — |
| 2025-11-13 | steady | — | stream | 0.5 | True | — | 1357219235 |
| 2025-11-14 | reps | 6 reps | laps | 1.0 | True | 6 | 1357916773 |
| 2025-11-16 | steady | — | stream | 0.48 | False | — | 1357917591 |
| 2025-11-19 | steady | — | stream | 0.62 | True | — | 1357921717 |
| 2025-11-21 | reps | 8×200 m | laps | 1.0 | True | 8 | 1357922074 |
| 2025-11-23 | steady | — | stream | 0.0 | False | — | 1357923364 |
| 2025-11-26 | steady | — | stream | 1.0 | True | — | 1394844627 |
| 2025-11-28 | block | 12 min block | laps | 1.0 | True | — | 1394845410 |
| 2025-11-30 | steady | — | stream | 0.0 | False | — | 1394846711 |
| 2025-12-03 | steady | — | stream | 0.0 | False | — | 1400464400 |
| 2025-12-05 | reps | 2-0.32-2 km | laps | 1.0 | True | 3 | 1400466807 |
| 2025-12-07 | steady | — | stream | 0.42 | False | — | 1400469634 |
| 2025-12-10 | steady | — | stream | 0.45 | False | — | 1400471031 |
| 2025-12-12 | reps | 6×300 m | laps | 1.0 | True | 6 | 1400471692 |
| 2025-12-14 | progression | — | stream | 0.52 | True | — | 1400475370 |
| 2025-12-17 | steady | — | stream | 0.53 | True | — | 1400476209 |
| 2025-12-19 | block | 14 min block | laps | 1.0 | True | — | 1400476957 |
| 2025-12-20 | steady | — | stream | 0.0 | False | — | 1400478152 |
| 2025-12-24 | block | 7 min block | stream | 0.61 | True | — | 1400478920 |
| 2025-12-26 | block | 24 min block | laps | 0.4 | False | — | 1400481293 |
| 2025-12-28 | block | 6 min block | stream | 0.52 | True | — | 1400487345 |
| 2025-12-31 | steady | — | stream | 0.53 | True | — | — |
| 2026-01-02 | steady | — | stream | 0.0 | False | — | — |
| 2026-01-05 | steady | — | stream | 1.0 | True | — | — |
| 2026-01-07 | steady | — | stream | 0.45 | False | — | 1434227753 |
| 2026-01-09 | steady | — | stream | 0.82 | True | — | 1436008759 |
| 2026-01-11 | steady | — | stream | 0.63 | True | — | 1437578548 |
| 2026-01-14 | steady | — | stream | 0.41 | False | — | 1437579885 |
| 2026-01-16 | reps | 2-1-2 km | laps | 1.0 | True | 3 | 1437580975 |
| 2026-01-18 | steady | — | stream | 0.43 | False | — | 1437583281 |
| 2026-01-21 | steady | — | stream | 0.42 | False | — | 1437583814 |
| 2026-01-23 | reps | 4 reps | stream | 0.55 | True | 4 | 1437584206 |
| 2026-01-25 | steady | — | stream | 0.41 | False | — | 1437586419 |
| 2026-01-28 | steady | — | stream | 0.43 | False | — | 1437587146 |
| 2026-01-30 | steady | — | stream | 0.45 | False | — | — |
| 2026-02-01 | steady | — | stream | 0.45 | False | — | 1437589641 |
| 2026-02-04 | steady | — | stream | 0.86 | True | — | 1437590649 |
| 2026-02-06 | reps | 6×0.23 km | laps | 1.0 | True | 6 | 1437591268 |
| 2026-02-08 | steady | — | stream | 0.43 | False | — | 1437596909 |
| 2026-02-11 | steady | — | stream | 0.55 | True | — | 1471771899 |
| 2026-02-13 | steady | — | stream | 1.0 | True | — | 1473206120 |
| 2026-02-15 | steady | — | stream | 0.45 | False | — | 1473208024 |
| 2026-02-18 | steady | — | stream | 0.47 | False | — | 1473208544 |
| 2026-02-22 | steady | — | stream | 0.5 | True | — | 1473211012 |
| 2026-02-26 | steady | — | stream | 0.46 | False | — | 1473212140 |
| 2026-02-27 | steady | — | stream | 1.0 | True | — | 1473209499 |
| 2026-03-01 | steady | — | stream | 0.5 | True | — | 1473212872 |
| 2026-03-04 | steady | — | stream | 0.0 | False | — | 1473213397 |
| 2026-03-08 | steady | — | stream | 0.44 | False | — | 1473217231 |
| 2026-03-11 | steady | — | stream | 0.42 | False | — | 1473217935 |
| 2026-03-13 | reps | 2.66-1.04-0.408-0.39 km | stream | 0.76 | True | 4 | 1473218732 |
| 2026-03-15 | steady | — | stream | 0.0 | False | — | 1473219847 |
| 2026-03-18 | steady | — | stream | 0.48 | False | — | 1473220710 |
| 2026-03-20 | reps | 5×1 km | laps | 1.0 | True | 5 | 1473221166 |
| 2026-03-22 | steady | — | stream | 0.0 | False | — | 1473222523 |
| 2026-03-25 | steady | — | stream | 0.0 | False | — | 1473223453 |
| 2026-03-26 | progression | — | stream | 1.0 | True | — | — |
| 2026-03-29 | steady | — | stream | 1.0 | True | — | 1473224989 |
| 2026-04-01 | reps | 1.45-0.278-1.58 km | stream | 0.82 | True | 3 | 1473225707 |
| 2026-04-03 | reps | 8 reps | stream | 0.62 | True | 8 | 1473226042 |
| 2026-04-05 | steady | — | stream | 0.0 | False | — | 1473227318 |
| 2026-04-08 | steady | — | stream | 0.43 | False | — | 1530137791 |
| 2026-04-10 | reps | 3×2 km | laps | 1.0 | True | 3 | 1530138485 |
| 2026-04-12 | steady | — | stream | 0.0 | False | — | 1530140869 |
| 2026-04-15 | steady | — | stream | 0.45 | False | — | 1530141773 |
| 2026-04-19 | steady | — | stream | 0.0 | False | — | 1530143128 |
| 2026-04-22 | steady | — | stream | 1.0 | True | — | 1530144210 |
| 2026-04-24 | block | 22 min block | stream | 0.77 | True | — | 1530144683 |
| 2026-04-26 | steady | — | stream | 0.45 | False | — | 1530145363 |
| 2026-04-29 | reps | 5 reps | stream | 0.38 | False | 5 | 1530145977 |
| 2026-05-13 | steady | — | stream | 1.0 | True | — | — |
| 2026-05-15 | steady | — | stream | 0.0 | False | — | — |
| 2026-05-20 | steady | — | stream | 0.71 | True | — | — |
| 2026-05-22 | reps | 7 reps | stream | 0.32 | False | 7 | — |
| 2026-05-27 | steady | — | stream | 0.49 | False | — | — |
| 2026-05-29 | reps | 4×1 km | laps | 1.0 | True | 4 | 1583193160 |
| 2026-05-31 | steady | — | stream | 0.52 | True | — | — |
| 2026-06-03 | steady | — | stream | 0.0 | False | — | — |
| 2026-06-05 | reps | 2 reps | laps | 1.0 | True | 2 | 1590767773 |
| 2026-06-07 | steady | — | stream | 0.0 | False | — | — |
| 2026-06-10 | steady | — | stream | 1.0 | True | — | — |
| 2026-06-14 | steady | — | stream | 0.0 | False | — | — |
| 2026-06-19 | steady | — | stream | 0.46 | False | — | 1599924823 |
| 2026-06-21 | steady | — | stream | 0.48 | False | — | 1599924840 |
| 2026-06-24 | steady | — | stream | 1.0 | True | — | — |
| 2026-06-26 | reps | 1-2-1 km | laps | 1.0 | True | 3 | 1612063026 |
| 2026-06-28 | steady | — | stream | 0.0 | False | — | — |
| 2026-06-29 | steady | — | stream | 0.65 | True | — | — |
| 2026-07-01 | steady | — | stream | 0.0 | False | — | — |
| 2026-07-03 | reps | 4×1 km | laps | 1.0 | True | 4 | 1619957757 |
| 2026-07-05 | steady | — | stream | 0.0 | False | — | — |
| 2026-07-06 | steady | — | stream | 0.0 | False | — | — |
| 2026-07-08 | steady | — | stream | 1.0 | True | — | — |
| 2026-07-10 | reps | 5×1 km | laps | 1.0 | True | 5 | 1626627551 |
| 2026-07-19 | steady | — | stream | 0.42 | False | — | — |
| 2026-07-22 | steady | — | stream | 1.0 | True | — | — |
| 2026-07-25 | steady | — | stream | 0.0 | False | — | — |
| 2026-07-27 | block | 11 min block | stream | 0.52 | True | — | — |
| 2026-07-29 | block | 32 min block | laps | 0.4 | False | — | 1646850327 |
| 2026-07-29 | steady | — | stream | 0.75 | True | — | — |
