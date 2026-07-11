## Context

The run detail page (`/run/:id`) renders the GPS trace as a bare projected polyline — run-detail decision D2, "the route as a shape, never a basemap". That decision exists because the browser is bound by an executable golden rule: `test_offline.mjs` aborts every non-same-origin request and asserts the whole app still renders. React, fonts, and every asset are vendored for the same reason.

The sync side has no such constraint — `sync_garmin.py` already reaches Garmin's servers from the homeserver. The archive is a SQLite database (`activity_archive.py`, schema currently v2) exposed read-only through `serve.mjs` (`/api/archive/…`, `node:sqlite`, fail-soft 503s). The trace is drawn by two pure seams: `chart-core.js#projectTrack` (equirectangular, fitted, aspect-preserving) and `chart-view.js#renderTrace` (polyline + start/finish dots + crosshair pin).

This change was brainstormed interactively; the four user decisions are fixed inputs to this design: (1) map imagery is fetched at sync time and served same-origin, (2) the card stays a static fitted backdrop (no pan/zoom), (3) the map is on by default with a bare-shape toggle, (4) all ~165 archived runs are backfilled gently.

## Goals / Non-Goals

**Goals:**

- Real geography behind the route on `/run/:id`, for every archived GPS run, with zero non-same-origin browser requests — `test_offline.mjs` runs unmodified and stays green.
- Deterministic, testable tile math; policy-compliant OSM fetching (throttle, identifying User-Agent, attribution); storage that dedupes the athlete's recurring running areas.
- Exact tile/route alignment by construction (shared Web Mercator math), preserving the crosshair pin behavior.
- Honest degradation: a run without a stored map renders exactly as today.

**Non-Goals:**

- No pan/zoom, no map library (Leaflet/MapLibre), no interactive cartography.
- No tiles on any other page (archive browser, compare, progress).
- No re-projection of the existing bare-shape path: `projectTrack` and its consumers are untouched for mapless runs.
- No vector tiles, no self-hosted tile server, no offline tile pyramid beyond each run's rect.
- No printing/theming redesign beyond one dark-treatment CSS rule.

## Decisions

**D1 — Tiles are fetched at sync time and served from our own origin.**
The browser never learns tile.openstreetmap.org exists. The sync pipeline (which already holds network access) fetches; `serve.mjs` serves blobs from SQLite. Alternatives rejected: live third-party tiles (breaks the golden rule, the offline story, and an executable test); a self-hosted tile server (GBs and a new moving part for one card); synthetic backdrops (not a map).

**D2 — One globally deduped tile table, assembled in the browser; no stitching.**
`map_tiles(z, x, y, png BLOB, fetched_at, PRIMARY KEY (z,x,y))` is shared across all runs — the athlete's recurring areas mean run N mostly hits tiles already stored (whole-archive footprint estimated 5–20 MB). `activity_maps(activity_id PK, z, x0, y0, x1, y1, crop_x, crop_y, crop_size, updated_at)` records each run's rect plus its crop box (world pixels at zoom z) — the framing is computed once in Python and served, so the pad/squarify heuristics are never duplicated in JS; the client only applies pure Mercator math, which is what alignment depends on. The client lays a small `<image>` grid inside the existing SVG. Alternative rejected: server-side stitching to one PNG per run — adds Pillow as a dependency, duplicates shared geography per run, and needs georeferencing metadata carried alongside anyway.

**D3 — Deterministic tile-rect math, computed from the stored streams.**
From the run's lat/lon columns: bbox → pad ~8% → squarify (extend the shorter side symmetrically) → choose the highest zoom z ≤ 16 whose crop spans ≤ 3 tiles (768 world-px) on the long side → enumerate the covering tile rect (typically 4–12 tiles). Squarify-before-rect guarantees the tile rect fills the square viewport — no bare corners. Pure function, unit-tested with fixed coordinates.

**D4 — Web Mercator alignment by construction.**
When a run has a map rect, the polyline is projected with the same formula that positions tiles: world-pixel coordinates at zoom z, minus the crop origin. New `projectTrackMercator(lat, lon, map)` in chart-core, next to (not replacing) `projectTrack`; null samples still gap. The `map`/`shape` toggle only hides the tile layer — geometry stays Mercator, so the shape does not jump (equirect vs Mercator differences at run scale are sub-pixel). Mapless runs keep `projectTrack` byte-for-byte.

**D5 — Policy compliance is a requirement, not a courtesy.**
Fetches go to `https://tile.openstreetmap.org/{z}/{x}/{y}.png` at ~1 req/s with a User-Agent identifying SPLITS and a contact. Only missing tiles are fetched (PK probe first). The card carries "Basemap © OpenStreetMap contributors". The backfill reuses the same code path; dedup makes it a few hundred unique fetches, minutes not hours.

**D6 — Completeness or nothing.**
An `activity_maps` row is written only after every tile in its rect is stored. A failed fetch leaves tiles it did store (they're globally useful) but no per-run row — the next sync retries the run cleanly. The client therefore never needs a "partial map" state; a missing single blob at serve time (defensive) just leaves one unpainted `<image>` while the route renders regardless.

**D7 — Dark treatment in CSS, attribution in the card sub.**
One `dashboard.css` class on the tile `<g>` — `grayscale(1) invert(0.92)` plus brightness/contrast/opacity tuning — turns standard OSM tiles into a dim monochrome backdrop under all three themes; the themed route stays the hero. Alternative rejected: fetching a dark tile style (third-party styled-tile servers carry stricter usage terms; OSM standard is the policy-safe source).

**D8 — Schema v8 follows the additive pattern of v2–v7.**
Additive DDL only (`CREATE TABLE IF NOT EXISTS`), raw v1/v2 tables untouched, version bump in `archive_meta`. `--backfill-maps` on `sync_garmin.py` mirrors the existing backfill ergonomics.

## Risks / Trade-offs

- [OSM tile usage policy tightens or blocks bulk fetching] → Throttle + UA + dedup keep usage well inside "light"; tiles already stored keep working forever; worst case new runs lack maps until an alternate source is configured.
- [Tile blobs bloat the archive DB] → Deduped store bounds growth to *new geography*, not new runs; 256-px PNGs average ~15–40 KB; monitored simply by DB file size. Vacuum not needed (no deletes).
- [Upscaled 256-px tiles look soft on large viewports] → Zoom choice targets ≤ 3 tiles across a ~300–500 px card (≥ ~1.5 device-px per tile-px on typical layouts); the dark low-opacity treatment further hides softness. Accepted trade-off of the no-library approach.
- [SVG `<image>` + CSS filter rendering cost] → ≤ 12 images per card, filter on one group; trivially within budget for a single card. Verified visually on the NUC deploy.
- [Two projections in chart-core invite drift] → They share nothing but math helpers; the spec pins each with scenarios (fitted-aspect for equirect, tile-alignment for Mercator).
- [Same-origin 404 noise if a blob is missing] → D6 makes it near-impossible; `test_offline.mjs` already tolerates same-origin 4xx, and the endpoint 404s cheaply.

## Migration Plan

1. Ship schema v8 + tile math + fetch step + endpoint + frontend behind the natural gate: no `activity_maps` row → page renders exactly as today. Deploying code before any tiles exist is safe.
2. Run `--backfill-maps` on the homeserver once, throttled; watch the log line per run.
3. Nightly sync picks up new runs automatically thereafter.
4. Rollback: revert the frontend/serve commits — tile tables are inert data; no destructive migration in either direction.

## Open Questions

None — the four interactive decisions (source, interaction, default, backfill) and the storage model were settled with the user before this document.
