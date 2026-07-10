# live-dashboard Specification (delta)

## MODIFIED Requirements

### Requirement: The cockpit renders complete without any API
The cockpit page SHALL render its full content from static files alone, served
by the application's own origin. No cockpit surface SHALL require an API
response to display, and no cockpit surface SHALL require a request to any
third-party origin. API-dependent surfaces belong to non-cockpit pages. (The
sync pill enriches with `/api/status` but the page SHALL be complete without
it.)

#### Scenario: Cockpit under total API failure
- **WHEN** every `/api/*` route fails while static files serve
- **THEN** the cockpit renders all of its sections with correct data from the
  static files

#### Scenario: Cockpit with every third-party origin unreachable
- **WHEN** every request to an origin other than the serving origin is aborted
- **THEN** the cockpit renders the hero, THIS WEEK, and the heatmap with correct
  data, and the browser console reports no errors

## ADDED Requirements

### Requirement: Pages load no third-party origins
Every page SHALL load its scripts, styles, fonts, and any other subresource from
the serving origin only. The client runtime (React), the typefaces, and any
future client library SHALL be vendored into the repository and served by the
application. No page source SHALL contain an absolute `http://` or `https://`
subresource URL.

#### Scenario: The progress page under an origin block
- **WHEN** every non-same-origin request is aborted and `/progress` is loaded
- **THEN** the page renders, and its same-origin archive-API requests still
  succeed

#### Scenario: A reintroduced CDN reference fails at the source
- **WHEN** a page template or stylesheet gains an absolute third-party
  subresource URL
- **THEN** the test suite fails, naming the file and the URL

### Requirement: The vendored React version is pinned and its constraint recorded
The application SHALL pre-populate `window.React` and `window.ReactDOM` from
vendored UMD builds before the dc-runtime boots, so the runtime's CDN fallback
is never taken. The vendored version SHALL be React 18.3.1 — the last release
published as a UMD build — and the reason SHALL be recorded beside the script
tags, because a routine version bump would otherwise leave the page blank.

#### Scenario: The runtime short-circuits its CDN loader
- **WHEN** a page boots with the vendored React scripts present
- **THEN** the dc-runtime detects both globals and issues no request to any CDN

#### Scenario: The dc-runtime remains unmodified
- **WHEN** the vendoring is in place
- **THEN** `support.js` is byte-identical to the generated artifact it ships as
