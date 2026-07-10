# Proposal: vendor-runtime

## Why

`live-dashboard` carries the requirement *"The cockpit renders complete without
any API"* — written so the dashboard survives race morning on hotel wifi. The
requirement is not met, and never has been.

`support.js` (the vendored dc-runtime, marked `GENERATED … do not edit`) loads
React from a CDN at boot:

```js
var REACT_URL     = "https://unpkg.com/react@18.3.1/umd/react.production.min.js";
var REACT_DOM_URL = "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js";
…
hideRawTemplate();                                   // x-dc { display:none !important }
loadReactUmd().then(init).catch((err) => { … throw err; });
```

`hideRawTemplate()` runs first and synchronously. If unpkg is unreachable — no
signal, captive portal, CDN outage, SRI mismatch after a republish — the
template is hidden, `init()` never runs, and **the cockpit is a blank page**.
There is no service worker, no vendored copy, and `node_modules` holds only
Playwright. The existing spec scenario ("every `/api/*` route fails while static
files serve") passes only because it never cut the origin the *static files
themselves* depend on.

The page also pulls Archivo and JetBrains Mono from `fonts.googleapis.com` /
`fonts.gstatic.com`, and `serve.mjs` sends every response uncompressed.

This change makes the cockpit's own rule true, and establishes the vendoring
policy (**this project vendors, it does not CDN**) that `chart-engine` and
`run-detail` will both rely on.

## What Changes

- **React 18.3.1 vendored.** `vendor/react.production.min.js` and
  `vendor/react-dom.production.min.js` are served from the app and loaded by two
  `<script>` tags ahead of `support.js` on every page. `loadReactUmd()` opens
  with `if (w.React && w.ReactDOM) return Promise.resolve();`, so the CDN path
  is never taken and `support.js` stays unmodified.
  - **The version pin is load-bearing and gets a comment.** React 19 stopped
    publishing UMD builds; 18.3.1 is the last version this runtime can vendor as
    a global. Moving off it means adopting a bundler.
  - `support.js` already tolerates both mount APIs
    (`ReactDOM.createRoot` with an `ReactDOM.render` fallback), so no behavioural
    change.
- **Fonts vendored.** Archivo and JetBrains Mono (latin subset, variable
  `woff2`) self-hosted under `vendor/fonts/` with `@font-face` in
  `dashboard.css` and `font-display: swap`; the two `<link>` tags and the
  `preconnect` hints are removed. The upstream OFL licence ships alongside.
- **`serve.mjs` gzips.** Content-negotiated `gzip` (via built-in `node:zlib`)
  for `text/*`, `application/javascript`, and `application/json`; already-
  compressed types (`woff2`, images) pass through untouched. React drops from
  143 KB to 47 KB on the wire, and the future `/run/:id` stream payload from
  105 KB to 28 KB. The server stays dependency-free.
- **The rule becomes testable.** A new Playwright check (`test_offline.mjs`)
  boots `serve.mjs`, aborts *every* request whose origin is not the server's
  own, loads the cockpit, and asserts the hero, THIS WEEK, and the heatmap all
  render. This is the first automated test of the golden rule.

Out of scope: the `dc-import` sibling fetch (unused today), any change to
`support.js` itself (it is generated), and the archive API's own network
behaviour (already spec'd to degrade).

## Capabilities

### Modified Capabilities

- `live-dashboard`: the static-file rule is tightened from "no API response" to
  "no third-party origin" — the cockpit SHALL render with every non-same-origin
  request blocked — and gains the React version-pin constraint.
- `containerized-deployment`: the image ships the vendored runtime assets, and
  the server negotiates response compression.

## Impact

- **Code:** new `vendor/` directory (React UMD ×2, two `woff2` files, `OFL.txt`);
  `Running Dashboard.dc.html` and `progress.dc.html` (script tags, font links
  removed); `dashboard.css` (`@font-face`); `serve.mjs` (gzip, `vendor/` route +
  correct MIME/`Cache-Control` for `woff2`); `Dockerfile` / `.dockerignore`
  (copy `vendor/`).
- **Tests:** new `test_offline.mjs` (Playwright, already a devDependency);
  `serve.mjs` compression assertions (`Accept-Encoding` honoured, `woff2` not
  double-compressed).
- **Deployment:** image rebuild. No volume change, no schema change, no data
  migration. Adds ~250 KB of static assets to the image.
- **Dependencies:** none added at runtime — `node:zlib` is built in, React is a
  checked-in artifact, Playwright was already present.
- **Sequencing:** independent of everything else and safe to land alone. It is a
  prerequisite for `chart-engine`, which vendors `d3-lite.js` under the policy
  this change establishes and relies on `test_offline.mjs` to keep it honest.
  Risk before Aug 9 is near zero: it removes failure modes rather than adding
  surfaces.
