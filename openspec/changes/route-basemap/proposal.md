## Why

The run detail page renders the route as a bare projected polyline — deliberately, because the browser is bound by the golden rule of zero non-same-origin requests. But a shape without geography answers "what did the route look like?" while leaving "where did I actually run?" to memory. The sync pipeline already talks to the internet; it can fetch map imagery once, at sync time, and the browser can stay same-origin forever.

## What Changes

- The Python sync pipeline gains a map-tile step: for every archived run with GPS, it computes a deterministic tile rect (padded, squarified route bbox; highest zoom ≤ 16 spanning ≤ 3 tiles on the long side) and fetches only the missing OSM tiles — throttled to ~1 req/s with an identifying User-Agent, per the OSM tile usage policy.
- Schema v8 (v2–v7 are already taken by earlier features): a globally deduped `map_tiles(z, x, y, png, fetched_at)` blob table shared across all runs, plus `activity_maps(activity_id, z, x0, y0, x1, y1, updated_at)` recording each run's rect. A run's row is written only once its rect is complete — no partial maps. A `--backfill-maps` flag covers the ~165 already-archived runs.
- `serve.mjs` exposes `GET /api/archive/tiles/:z/:x/:y.png` (same-origin, long cache, 404 when absent), and the existing per-activity payload gains a `map` field when a rect exists.
- The chart engine gains a Web Mercator projection (`projectTrackMercator`) so the polyline aligns with the tiles exactly, and `renderTrace` gains an optional tile layer painted behind the route. Runs without a stored map keep the existing equirectangular path untouched.
- The run detail trace card renders the map by default with a `map`/`shape` chip toggle, a dark CSS treatment so the themed trace stays the hero, and the required "Basemap © OpenStreetMap contributors" attribution replacing "No basemap by design".
- The golden rule is unchanged: the browser makes zero non-same-origin requests, and `test_offline.mjs` runs unmodified.

## Capabilities

### New Capabilities
- `route-basemap`: Sync-time acquisition and durable storage of OSM map tiles for archived runs — deterministic tile-rect math, deduped tile store, policy-compliant fetching (throttle, User-Agent, attribution), completeness guarantee, and backfill.

### Modified Capabilities
- `archive-api`: gains a read-only same-origin tile endpoint and a `map` rect field on the per-activity payload.
- `chart-engine`: the geographic projection requirement gains a Web Mercator variant that aligns the trace with a stored tile rect; trace rendering gains an optional behind-the-route tile layer.
- `run-detail`: the "route renders as a trace, never from map tiles" requirement becomes "the route renders over the archive's own basemap by default, with a bare-shape toggle" — the third-party prohibition stays; tiles are served from the application's own origin.

## Impact

- **Python**: `activity_archive.py` (schema v8, tile math, tile fetch step), `sync_garmin.py` (pipeline hook, `--backfill-maps`), new tests in `test_activity_archive.py`.
- **Node/serve**: `serve.mjs` (tile endpoint, `map` field), `test_archive_api.mjs`.
- **Frontend**: `chart-core.js` (`projectTrackMercator`), `chart-view.js` (tile layer in `renderTrace`), `run.dc.html` (toggle, attribution), `dashboard.css` (dark-map treatment), `test_chart_core.mjs`, `test_run_page.mjs`.
- **External**: one-time throttled fetches to tile.openstreetmap.org from the homeserver at sync time; ~5–20 MB of tile blobs in the archive DB. No new runtime dependencies in browser or server; no new Python packages.
- **Unchanged**: `test_offline.mjs` (the golden-rule proof), `projectTrack`, all other pages.
