# Baseline before fix-lap-confidence

Read-only production sweep, captured 2026-07-30 against `INTERVAL_VERSION` 4
(all 170 documents). This is the diff target for task 7.4: after the
rescore at version 5, **every shape and label below must be identical** —
this change alters only confidence. The expected confidence movement is
`2026-07-29` and `2025-12-26` dropping below the assert threshold, and
nothing else (task 7.5).

- shapes: steady 131 / reps 24 / block 13 / progression 2
- sources: stream 146 / laps 24
- every document reads `confidence` as shown; all 24 lap-sourced documents
  carry the constant `1.0` this change removes.

| date | shape | label | source | confidence | found |
|---|---|---|---|---|---|
| 2024-05-12 | reps | 3×800 m | stream | 0.95 | 3 |
| 2024-05-16 | steady | — | stream | 1.0 | — |
| 2024-05-18 | steady | — | stream | 1.0 | — |
| 2024-05-21 | block | 6 min block | stream | 1.0 | — |
| 2024-05-24 | reps | 3 reps | stream | 0.31 | 3 |
| 2024-05-26 | reps | 3 reps | stream | 0.75 | 3 |
| 2024-05-27 | steady | — | stream | 1.0 | — |
| 2024-06-15 | steady | — | stream | 1.0 | — |
| 2024-06-16 | steady | — | stream | 1.0 | — |
| 2024-06-19 | steady | — | stream | 1.0 | — |
| 2024-06-21 | steady | — | stream | 1.0 | — |
| 2024-06-25 | steady | — | stream | 0.78 | — |
| 2024-07-13 | block | 5 min block | laps | 1.0 | — |
| 2024-07-22 | steady | — | laps | 1.0 | — |
| 2024-09-08 | steady | — | stream | 1.0 | — |
| 2024-09-22 | steady | — | stream | 1.0 | — |
| 2025-03-22 | steady | — | stream | 1.0 | — |
| 2025-03-30 | steady | — | stream | 1.0 | — |
| 2025-04-08 | steady | — | stream | 1.0 | — |
| 2025-04-20 | steady | — | stream | 1.0 | — |
| 2025-05-11 | steady | — | stream | 1.0 | — |
| 2025-05-18 | steady | — | stream | 0.56 | — |
| 2025-05-21 | steady | — | stream | 1.0 | — |
| 2025-05-28 | steady | — | stream | 0.54 | — |
| 2025-06-01 | steady | — | stream | 0.51 | — |
| 2025-06-08 | steady | — | stream | 0.64 | — |
| 2025-06-22 | steady | — | stream | 0.68 | — |
| 2025-06-29 | steady | — | stream | 0.57 | — |
| 2025-07-02 | steady | — | stream | 0.75 | — |
| 2025-07-05 | steady | — | stream | 0.66 | — |
| 2025-07-06 | steady | — | stream | 0.67 | — |
| 2025-07-09 | steady | — | stream | 0.88 | — |
| 2025-07-11 | steady | — | stream | 0.48 | — |
| 2025-07-16 | steady | — | stream | 0.88 | — |
| 2025-07-19 | steady | — | stream | 1.0 | — |
| 2025-07-20 | steady | — | stream | 0.94 | — |
| 2025-07-23 | steady | — | stream | 0.5 | — |
| 2025-07-26 | steady | — | stream | 0.65 | — |
| 2025-07-31 | steady | — | stream | 0.54 | — |
| 2025-08-03 | steady | — | stream | 0.6 | — |
| 2025-08-06 | steady | — | stream | 0.76 | — |
| 2025-08-10 | steady | — | stream | 0.86 | — |
| 2025-08-13 | steady | — | stream | 0.56 | — |
| 2025-08-20 | steady | — | stream | 0.49 | — |
| 2025-08-27 | steady | — | stream | 0.48 | — |
| 2025-09-03 | steady | — | stream | 0.85 | — |
| 2025-09-07 | steady | — | stream | 0.47 | — |
| 2025-09-10 | steady | — | stream | 0.47 | — |
| 2025-09-14 | steady | — | stream | 0.46 | — |
| 2025-09-17 | steady | — | stream | 1.0 | — |
| 2025-09-19 | reps | 6×200 m | laps | 1.0 | 6 |
| 2025-09-21 | steady | — | stream | 0.41 | — |
| 2025-09-21 | steady | — | stream | 1.0 | — |
| 2025-09-24 | steady | — | stream | 0.78 | — |
| 2025-09-26 | block | 14 min block | laps | 1.0 | — |
| 2025-09-28 | steady | — | stream | 0.52 | — |
| 2025-10-01 | steady | — | stream | 0.0 | — |
| 2025-10-03 | block | 18 min block | laps | 1.0 | — |
| 2025-10-05 | steady | — | stream | 0.59 | — |
| 2025-10-08 | steady | — | stream | 0.44 | — |
| 2025-10-10 | steady | — | stream | 1.0 | — |
| 2025-10-12 | steady | — | stream | 0.5 | — |
| 2025-10-12 | steady | — | stream | 0.46 | — |
| 2025-10-15 | steady | — | stream | 0.4 | — |
| 2025-10-17 | reps | 6 reps | laps | 1.0 | 6 |
| 2025-10-19 | steady | — | stream | 0.41 | — |
| 2025-10-22 | steady | — | stream | 0.79 | — |
| 2025-10-24 | block | 19 min block | laps | 1.0 | — |
| 2025-10-26 | steady | — | stream | 0.0 | — |
| 2025-10-31 | steady | — | stream | 0.98 | — |
| 2025-11-13 | steady | — | stream | 0.5 | — |
| 2025-11-14 | reps | 6 reps | laps | 1.0 | 6 |
| 2025-11-16 | steady | — | stream | 0.48 | — |
| 2025-11-19 | steady | — | stream | 0.62 | — |
| 2025-11-21 | reps | 8×200 m | laps | 1.0 | 8 |
| 2025-11-23 | steady | — | stream | 0.0 | — |
| 2025-11-26 | steady | — | stream | 1.0 | — |
| 2025-11-28 | block | 12 min block | laps | 1.0 | — |
| 2025-11-30 | steady | — | stream | 0.0 | — |
| 2025-12-03 | steady | — | stream | 0.0 | — |
| 2025-12-05 | reps | 2-0.32-2 km | laps | 1.0 | 3 |
| 2025-12-07 | steady | — | stream | 0.42 | — |
| 2025-12-10 | steady | — | stream | 0.45 | — |
| 2025-12-12 | reps | 6×300 m | laps | 1.0 | 6 |
| 2025-12-14 | progression | — | stream | 0.52 | — |
| 2025-12-17 | steady | — | stream | 0.53 | — |
| 2025-12-19 | block | 14 min block | laps | 1.0 | — |
| 2025-12-20 | steady | — | stream | 0.0 | — |
| 2025-12-24 | block | 7 min block | stream | 0.61 | — |
| 2025-12-26 | block | 24 min block | laps | 1.0 | — |
| 2025-12-28 | block | 6 min block | stream | 0.52 | — |
| 2025-12-31 | steady | — | stream | 0.53 | — |
| 2026-01-02 | steady | — | stream | 0.0 | — |
| 2026-01-05 | steady | — | stream | 1.0 | — |
| 2026-01-07 | steady | — | stream | 0.45 | — |
| 2026-01-09 | steady | — | stream | 0.82 | — |
| 2026-01-11 | steady | — | stream | 0.63 | — |
| 2026-01-14 | steady | — | stream | 0.41 | — |
| 2026-01-16 | reps | 2-1-2 km | laps | 1.0 | 3 |
| 2026-01-18 | steady | — | stream | 0.43 | — |
| 2026-01-21 | steady | — | stream | 0.42 | — |
| 2026-01-23 | reps | 4 reps | stream | 0.55 | 4 |
| 2026-01-25 | steady | — | stream | 0.41 | — |
| 2026-01-28 | steady | — | stream | 0.43 | — |
| 2026-01-30 | steady | — | stream | 0.45 | — |
| 2026-02-01 | steady | — | stream | 0.45 | — |
| 2026-02-04 | steady | — | stream | 0.86 | — |
| 2026-02-06 | reps | 6×0.23 km | laps | 1.0 | 6 |
| 2026-02-08 | steady | — | stream | 0.43 | — |
| 2026-02-11 | steady | — | stream | 0.55 | — |
| 2026-02-13 | steady | — | stream | 1.0 | — |
| 2026-02-15 | steady | — | stream | 0.45 | — |
| 2026-02-18 | steady | — | stream | 0.47 | — |
| 2026-02-22 | steady | — | stream | 0.5 | — |
| 2026-02-26 | steady | — | stream | 0.46 | — |
| 2026-02-27 | steady | — | stream | 1.0 | — |
| 2026-03-01 | steady | — | stream | 0.5 | — |
| 2026-03-04 | steady | — | stream | 0.0 | — |
| 2026-03-08 | steady | — | stream | 0.44 | — |
| 2026-03-11 | steady | — | stream | 0.42 | — |
| 2026-03-13 | reps | 2.66-1.04-0.408-0.39 km | stream | 0.76 | 4 |
| 2026-03-15 | steady | — | stream | 0.0 | — |
| 2026-03-18 | steady | — | stream | 0.48 | — |
| 2026-03-20 | reps | 5×1 km | laps | 1.0 | 5 |
| 2026-03-22 | steady | — | stream | 0.0 | — |
| 2026-03-25 | steady | — | stream | 0.0 | — |
| 2026-03-26 | progression | — | stream | 1.0 | — |
| 2026-03-29 | steady | — | stream | 1.0 | — |
| 2026-04-01 | reps | 1.45-0.278-1.58 km | stream | 0.82 | 3 |
| 2026-04-03 | reps | 8 reps | stream | 0.62 | 8 |
| 2026-04-05 | steady | — | stream | 0.0 | — |
| 2026-04-08 | steady | — | stream | 0.43 | — |
| 2026-04-10 | reps | 3×2 km | laps | 1.0 | 3 |
| 2026-04-12 | steady | — | stream | 0.0 | — |
| 2026-04-15 | steady | — | stream | 0.45 | — |
| 2026-04-19 | steady | — | stream | 0.0 | — |
| 2026-04-22 | steady | — | stream | 1.0 | — |
| 2026-04-24 | block | 22 min block | stream | 0.77 | — |
| 2026-04-26 | steady | — | stream | 0.45 | — |
| 2026-04-29 | reps | 5 reps | stream | 0.38 | 5 |
| 2026-05-13 | steady | — | stream | 1.0 | — |
| 2026-05-15 | steady | — | stream | 0.0 | — |
| 2026-05-20 | steady | — | stream | 0.71 | — |
| 2026-05-22 | reps | 7 reps | stream | 0.32 | 7 |
| 2026-05-27 | steady | — | stream | 0.49 | — |
| 2026-05-29 | reps | 4×1 km | laps | 1.0 | 4 |
| 2026-05-31 | steady | — | stream | 0.52 | — |
| 2026-06-03 | steady | — | stream | 0.0 | — |
| 2026-06-05 | reps | 2 reps | laps | 1.0 | 2 |
| 2026-06-07 | steady | — | stream | 0.0 | — |
| 2026-06-10 | steady | — | stream | 1.0 | — |
| 2026-06-14 | steady | — | stream | 0.0 | — |
| 2026-06-19 | steady | — | stream | 0.46 | — |
| 2026-06-21 | steady | — | stream | 0.48 | — |
| 2026-06-24 | steady | — | stream | 1.0 | — |
| 2026-06-26 | reps | 1-2-1 km | laps | 1.0 | 3 |
| 2026-06-28 | steady | — | stream | 0.0 | — |
| 2026-06-29 | steady | — | stream | 0.65 | — |
| 2026-07-01 | steady | — | stream | 0.0 | — |
| 2026-07-03 | reps | 4×1 km | laps | 1.0 | 4 |
| 2026-07-05 | steady | — | stream | 0.0 | — |
| 2026-07-06 | steady | — | stream | 0.0 | — |
| 2026-07-08 | steady | — | stream | 1.0 | — |
| 2026-07-10 | reps | 5×1 km | laps | 1.0 | 5 |
| 2026-07-19 | steady | — | stream | 0.42 | — |
| 2026-07-22 | steady | — | stream | 1.0 | — |
| 2026-07-25 | steady | — | stream | 0.0 | — |
| 2026-07-27 | block | 11 min block | stream | 0.52 | — |
| 2026-07-29 | block | 32 min block | laps | 1.0 | — |
| 2026-07-29 | steady | — | stream | 0.75 | — |
