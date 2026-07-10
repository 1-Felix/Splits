# vendor/ — third-party runtime assets, checked in

**This project vendors; it does not CDN.** Every script, style, font, and future
client library the pages need is served from our own origin. No page may load an
absolute `http://` / `https://` subresource. `test_offline.mjs` enforces this by
blocking every non-same-origin request and asserting the cockpit still renders.

To re-vendor an asset: download it, recompute its SHA-384, confirm it matches the
value recorded below (React must also match the SRI hash baked into `support.js`),
and update this file. If a hash does not match, stop — do not check the file in.

## React 18.3.1 (UMD)

Pinned to **18.3.1** on purpose: it is the last React published as a UMD global.
React 19 ships no UMD build, so bumping the version cannot be a one-line change —
it means adopting a bundler. The two `<script>` tags in each `*.dc.html` pre-seed
`window.React` / `window.ReactDOM` before `support.js` runs, so the dc-runtime's
`loadReactUmd()` takes its `if (w.React && w.ReactDOM) return` early exit and never
reaches for unpkg. The SHA-384s below are byte-identical to the SRI hashes
`support.js` pins (`REACT_SRI` / `REACT_DOM_SRI`), so the vendored bytes are exactly
what the generated runtime expects.

| file | version | bytes | source | sha384 (integrity) |
|------|---------|-------|--------|--------------------|
| `react.production.min.js` | 18.3.1 | 10751 | https://unpkg.com/react@18.3.1/umd/react.production.min.js | `sha384-DGyLxAyjq0f9SPpVevD6IgztCFlnMF6oW/XQGmfe+IsZ8TqEiDrcHkMLKI6fiB/Z` |
| `react-dom.production.min.js` | 18.3.1 | 131835 | https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js | `sha384-gTGxhz21lVGYNMcdJOyq01Edg0jhn/c22nsx0kyqP0TxaV5WVdsSH1fSDUf5YJj1` |

## Fonts (`fonts/`)

Archivo and JetBrains Mono, self-hosted so the pages request no `fonts.googleapis.com`
/ `fonts.gstatic.com` origin. These are the **latin** and **latin-ext** variable
`woff2` subsets Google serves to a modern browser for the exact family/weight query
the pages used before (`Archivo:wght@400..900`, `JetBrains Mono:wght@400..700`). The
`@font-face` rules in `dashboard.css` reproduce Google's exact `unicode-range` values,
so the same glyphs render from the font and the same characters (`→` U+2192, `≈`
U+2248, `₂` U+2082 — all outside the latin range) fall back to a system font, exactly
as before. The other Google subsets (vietnamese, cyrillic, greek) are not vendored:
nothing in the UI uses those scripts. Licensed under the SIL OFL 1.1 — see `fonts/OFL.txt`.

| file | family | subset | bytes | source (gstatic) | sha384 |
|------|--------|--------|-------|------------------|--------|
| `fonts/archivo-latin.woff2` | Archivo (v25) | latin | 34928 | `/s/archivo/v25/k3kPo8UDI-1M0wlSV9XAw6lQkqWY8Q82sLydOxI.woff2` | `sha384-4u9gB1owH4irVyp5uLjsGvNmHZiwtD3mU8L2KzBD5TJzQKw6yPNPPJwxJpJmZ0Bg` |
| `fonts/archivo-latin-ext.woff2` | Archivo (v25) | latin-ext | 32608 | `/s/archivo/v25/k3kPo8UDI-1M0wlSV9XAw6lQkqWY8Q82sLyTOxK-vA.woff2` | `sha384-yslX5lhiozxmtGv68yGapvj2s/g2Ep+9zeSl5MRNb0FQ0+eyl9DSphYrnO73Lfh5` |
| `fonts/jetbrains-mono-latin.woff2` | JetBrains Mono (v24) | latin | 31432 | `/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwg.woff2` | `sha384-9wWypBPwJyfsOnJFplExHD+Wz+6/I6+rtL7ITgA/6wSPgpj+tnQovOLWM9j2rhOF` |
| `fonts/jetbrains-mono-latin-ext.woff2` | JetBrains Mono (v24) | latin-ext | 11624 | `/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx7cwhsk.woff2` | `sha384-md7lI+WpzcaSgfuu+hCajR6cBH9KQiGR2BEnokGhah1MOLT+PY8Tb5r5PUYGeiuQ` |

Full gstatic host prefix for the font URLs: `https://fonts.gstatic.com`.
