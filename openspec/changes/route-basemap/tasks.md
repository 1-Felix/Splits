## 1. Tile math and schema (Python, pure first)

- [x] 1.1 Write failing tests in `test_activity_archive.py` for the tile-rect math: fixed lat/lon fixture → deterministic zoom + rect; padding ~8%; squarify extends the shorter side; zoom caps at 16; long routes drop zoom to keep ≤ 3 tiles on the long side; no-GPS streams → None
- [x] 1.2 Implement the pure tile math in `activity_archive.py` (lat/lon → Web Mercator world px → padded squarified crop → zoom → tile rect) until 1.1 passes
- [x] 1.3 Add schema v8 DDL (`map_tiles`, `activity_maps`, version bump in `archive_meta`) following the v2–v7 additive pattern, with a migration test asserting prior tables untouched

## 2. Tile fetching in the sync pipeline

- [x] 2.1 Write failing tests for the fetch step with a mocked fetcher: only missing tiles requested (dedup probe), ~1 req/s throttle honored, identifying User-Agent set, `activity_maps` row written only when the rect completes, failure leaves stored tiles but no row, retry fetches only the gap, treadmill/no-GPS skipped silently
- [x] 2.2 Implement the map step in `activity_archive.py` against tile.openstreetmap.org until 2.1 passes
- [x] 2.3 Hook the map step into the sync flow in `sync_garmin.py` after streams are written, and add the `--backfill-maps` flag reusing the same code path; log one line per run (tiles fetched / reused / skipped)

## 3. Serving (serve.mjs)

- [x] 3.1 Write failing tests in `test_archive_api.mjs`: `GET /api/archive/tiles/:z/:x/:y.png` returns the blob with `image/png` + cache headers, 404 on missing tile, GET-only, 503 fail-soft when the archive is away; `GET /api/archive/activities/:id` carries `map:{z,x0,y0,x1,y1,cropX,cropY,cropSize}` for a seeded mapped run and no `map` field otherwise
- [x] 3.2 Implement the tile endpoint and the `map` field in `serve.mjs` until 3.1 passes

## 4. Chart engine (projection + tile layer)

- [x] 4.1 Write failing tests in `test_chart_core.mjs` for `projectTrackMercator`: known lat/lon at a known zoom land on the world-pixel coordinates the tile math assigns; nulls stay null (gaps); crop-origin offset applied
- [x] 4.2 Implement `projectTrackMercator(lat, lon, map)` in `chart-core.js` beside the untouched `projectTrack`
- [x] 4.3 Extend `renderTrace` in `chart-view.js` with an optional tile layer: a `<g>` of 256×256 `<image>` elements at world positions painted before the route paths; pin/start/finish unchanged and on top; cover in `test_chart_view.mjs`

## 5. Run detail page + styling

- [x] 5.1 Add the dark-map treatment class to `dashboard.css` (grayscale/invert/brightness/contrast/opacity on the tile group; per-theme --mapFilter tokens in topbar.js — the light `track` theme desaturates instead of inverting) and verify the route stays the hero under all three themes (visual check in 6.3)
- [x] 5.2 Wire `run.dc.html`: when `run.map` exists use `projectTrackMercator` + tile layer, add the `map`/`shape` chip toggle (default map, hides tiles only), swap the card sub to "Basemap © OpenStreetMap contributors"; mapless runs keep today's path byte-for-byte
- [x] 5.3 Extend `test_run_page.mjs`: seeded-map case (tile `<image>` elements present and same-origin, toggle hides them, pin still tracks the crosshair) and no-map case (bare shape, no toggle, no tile requests)

## 6. Golden rule and full verification

- [x] 6.1 Run `test_offline.mjs` unmodified — must stay green (tiles same-origin under the origin block)
- [x] 6.2 Run the full test suite (Python + node) and fix any fallout
- [x] 6.3 Verify end-to-end locally: seed a mapped run, open `/run/:id`, confirm map behind route, alignment, toggle, attribution, crosshair pin (real OSM tiles for run 23543309396; all three themes screenshotted; alignment verified against named roads)

## 7. Deploy and backfill

- [ ] 7.1 Deploy to the NUC (watch the Windows CRLF docker gotcha from chart-drill), verify a mapped run renders at the deployed origin
- [ ] 7.2 Run `--backfill-maps` on the homeserver, throttled; confirm every GPS run gains a map row and spot-check tile reuse in the log
