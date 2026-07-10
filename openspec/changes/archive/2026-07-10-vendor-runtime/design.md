# Design: vendor-runtime

## Context

Every page is a Design-Claude component (`*.dc.html`) booted by `support.js`, a
build artifact of an external `dc-runtime` project whose header reads
`GENERATED from dc-runtime/src/*.ts — do not edit`. The repo has no bundler:
`package.json` lists Playwright as its only devDependency, `serve.mjs` is
deliberately dependency-free (`node:sqlite`, `node:http`), and all client code is
served as raw files.

`support.js` boots like this:

```js
hideRawTemplate();                       // injects  x-dc { display:none !important }
loadReactUmd().then(init).catch((err) => { console.error(…); throw err; });
```

and `loadReactUmd()` begins:

```js
function loadReactUmd() {
  const w = window;
  if (w.React && w.ReactDOM) return Promise.resolve();     // ← the seam
  return Promise.all([loadScript(REACT_URL, REACT_SRI), …]);
}
```

That early return is the entire mechanism this change uses. Nothing else about
the runtime needs to move.

Constraints: single user on a trusted LAN; race Aug 9, so the cockpit must get
*more* boring, not less; `support.js` cannot be edited; the homeserver volume is
canonical and holds data only — application code ships in the image.

## Goals / Non-Goals

**Goals**

- The cockpit renders with every third-party origin blocked.
- Establish the vendoring policy and the regeneration discipline that
  `chart-engine` (d3) will follow.
- Make the golden rule an executable test rather than a paragraph.

**Non-Goals**

- Editing or forking `support.js`.
- Adopting a bundler, a package manager for client code, or a service worker.
- Offline *data* freshness — a cached `garmin-data.js` is already the contract.
- Compressing anything beyond what `node:zlib` gives for free.

## Decisions

### D1 — Pre-seed `window.React` rather than patch the runtime

Two `<script src="./vendor/react*.js">` tags before `<script src="./support.js">`.
`support.js` sees both globals and short-circuits.

*Alternatives rejected.* Editing `support.js` violates its generated-file
contract and would be silently reverted by any future DC pull. A service worker
adds a cache-invalidation problem to a page whose whole point is predictability.
An import map does not help: the runtime fetches UMD via `<script>`, not ESM.

### D2 — Pin React 18.3.1, and say why in the markup

React 19 does not ship UMD builds. 18.3.1 is therefore not "the version that
happens to match the SRI hash" — it is the newest version compatible with this
strategy at all. A bare version bump would take the page down, so the constraint
is recorded as an HTML comment beside the script tags *and* as a spec
requirement, not just in this document.

`support.js` guards the mount with `if (ReactDOM.createRoot) … else ReactDOM.render(…)`,
so the vendored UMD needs no shim.

### D3 — Vendor fonts too; "no third-party origins" is the invariant

A half-vendored page rots: the next contributor sees one CDN link and adds
another. `font-display: swap` means the Google Fonts link is *cosmetically*
survivable, which is exactly why it would never get fixed on its own. Self-host
the latin-subset variable `woff2` for Archivo and JetBrains Mono, ship `OFL.txt`,
delete the `<link>` and `preconnect` tags. The invariant that
`test_offline.mjs` enforces is then simple enough to state in one sentence.

### D4 — Compression in `serve.mjs`, allow-list by content type

`node:zlib` gzip when the request carries `Accept-Encoding: gzip` **and** the
resolved content type is `text/*`, `application/javascript`, or
`application/json`. `woff2` and images are already compressed and are passed
through with `Cache-Control: public, max-age=31536000, immutable` (the vendored
assets are content-stable and version-pinned).

Chosen over Brotli: `node:zlib` has `createBrotliCompress`, but gzip is the
lowest-risk win, universally accepted, and the payloads here are small enough
that the marginal Brotli gain does not pay for the extra negotiation branch. The
allow-list matters — gzipping `woff2` costs CPU and *grows* the response.

### D5 — The test blocks origins, not URLs

`test_offline.mjs` uses Playwright (already a devDependency) and routes `**/*`,
aborting any request whose origin differs from the server under test. It then
asserts three cockpit surfaces are present in the DOM. Blocking by *origin*
rather than by a list of known CDN hosts means a future contributor who adds
`cdn.example.com` fails the test without anyone having to remember to update it.

Asserting on rendered surfaces (hero, THIS WEEK, heatmap) rather than on
"React loaded" keeps the test honest about what the requirement actually
promises.

## Risks / Trade-offs

- **The vendored React drifts from what DC expects.** If a future `support.js`
  pull targets React 19, the globals we pre-seed are the wrong major. Mitigated
  by D2's comment and by `test_offline.mjs` failing loudly (the page would not
  render). Accepted: the alternative is a bundler.
- **~250 KB added to the image.** Trivially acceptable; it is static, cached
  immutably, and gzip halves the JS on the wire.
- **Font subsetting is eyeballed, not automated.** The latin subset is taken
  from Google's own `woff2`. If a glyph is missing (the German `ß`, `ä`, `ö`,
  `ü` all matter here) it degrades to the system fallback rather than breaking.
  A task explicitly checks the umlauts render.
- **gzip on `garmin-data.js` means the sync's write and the server's read race
  on a partially-written file.** Already true before this change (the file is
  read and served as bytes); compression does not widen the window because the
  file is read fully into memory before encoding.

## Open Questions

None blocking. Whether to also vendor the fonts' *italic* faces is deferred —
nothing in the design language uses them today.
