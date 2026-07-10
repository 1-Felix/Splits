# Tasks: vendor-runtime

## 1. Vendor React (design D1, D2)

- [x] 1.1 Add `vendor/react.production.min.js` and `vendor/react-dom.production.min.js` at exactly **18.3.1** (10,751 and 131,835 bytes); record provenance and the SHA-384 hashes `support.js` pins in a short `vendor/README.md`
- [x] 1.2 Add both `<script>` tags ahead of `<script src="./support.js">` in `Running Dashboard.dc.html` and `progress.dc.html`, with an HTML comment stating that React 19 ships no UMD build and this pin therefore cannot be bumped without adopting a bundler
- [x] 1.3 Confirm `support.js` is byte-identical to before (it is a generated file — the change must not touch it) and that `loadReactUmd()` takes its `w.React && w.ReactDOM` early return
- [x] 1.4 Serve `vendor/` from `serve.mjs` with correct MIME types and `Cache-Control: public, max-age=31536000, immutable`; reject path traversal as the existing static route already does

## 2. Vendor fonts (design D3)

- [x] 2.1 Add latin-subset variable `woff2` for Archivo (400–900) and JetBrains Mono (400–700) under `vendor/fonts/`, plus the upstream `OFL.txt`
- [x] 2.2 Add `@font-face` rules to `dashboard.css` with `font-display: swap`; delete the `fonts.googleapis.com` `<link>` and both `preconnect` hints from every `.dc.html`
- [x] 2.3 Verify the German glyphs the UI actually renders (`ä ö ü ß` — "Allgäu Panorama Halbmarathon") and the typographic characters in use (`·` `→` `≈` `−` `₂`) are present in the subset; fall back to the full latin subset if any are missing

## 3. Compression (design D4)

- [x] 3.1 `serve.mjs`: gzip via `node:zlib` when `Accept-Encoding` includes `gzip` **and** the content type is `text/*`, `application/javascript`, or `application/json`; set `Content-Encoding` and `Vary: Accept-Encoding`; never set `Content-Length` alongside a streamed encoding
- [x] 3.2 Pass `woff2` and image responses through uncompressed (gzipping them costs CPU and grows the body)
- [x] 3.3 Extend the archive-API JSON responses through the same path (this is what makes `/run/:id` streams affordable later)
- [x] 3.4 Tests: `Accept-Encoding: gzip` yields a gzipped body that decodes to the identical bytes; no `Accept-Encoding` yields the plain body; `woff2` is never gzipped; `/api/archive/activities` is gzipped

## 4. The golden rule becomes a test (design D5)

- [x] 4.1 New `test_offline.mjs`: boot `serve.mjs` on an ephemeral port, `page.route('**/*', …)` aborting every request whose origin ≠ the server's own, load the cockpit
- [x] 4.2 Assert the hero (race name + countdown), THIS WEEK (seven day cards), and the heatmap all render; assert zero console errors
- [x] 4.3 Assert the same for `/progress`, allowing its archive-API calls to succeed (same origin) — the page must render, proving the block is origin-scoped, not blanket
- [x] 4.4 Add a guard asserting no `.dc.html` or `dashboard.css` contains an `http://` or `https://` URL, so the invariant fails at the source, not only in the browser

## 5. Deployment

- [x] 5.1 `Dockerfile`: copy `vendor/` into the image; confirm `.dockerignore` does not exclude it
- [ ] 5.2 Rebuild and run the image; load the cockpit from the LAN with the container's DNS pointed at a black hole, and confirm the page renders  _(SKIPPED — requires SSH to the homeserver/NUC; not runnable from this worktree)_
- [ ] 5.3 Confirm the served `Content-Encoding` and `Cache-Control` headers behind the real deployment (no proxy is double-compressing)  _(SKIPPED — requires SSH to the homeserver/NUC; not runnable from this worktree)_

## 6. Spec sync

- [x] 6.1 Update `openspec/specs/live-dashboard/spec.md` and `openspec/specs/containerized-deployment/spec.md` from the deltas
- [x] 6.2 `README.md`: document the `vendor/` directory, the React pin rationale, and that the project vendors rather than CDNs
- [x] 6.3 Run the full existing suite (`test_topbar.mjs`, `test_archive_api.mjs`, `tools/style-audit.mjs`) — nothing should move
