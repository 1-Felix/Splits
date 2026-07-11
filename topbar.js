// topbar.js — shared topbar BEHAVIOR for every SPLITS page (progress-views
// design D8). The ~25 lines of topbar markup stay duplicated per .dc.html (the
// dc-component model has no cross-page include); everything that markup calls
// lives here exactly once: the theme registry + persistence, the sync-pill
// state machine, the greeting, and the nav model.
//
// Loaded from each page's real <head> as <script type="module"> — module
// scripts are deferred, so window.SplitsTopbar exists before support.js mounts
// the component on DOMContentLoaded. That makes the persisted theme readable
// synchronously at component init: no flash of the default theme. The same
// functions are exported for Node (test_topbar.mjs).

export const THEME_KEY = "splits.theme";
export const DEFAULT_THEME = "volt";

// Theme registry — every value becomes a CSS variable on the page root; the
// picker's swatch is each theme's accent.
//
// Token roles (chart-engine D5) — no token serves two roles:
//   accent/accent2   UI chrome (buttons, highlights, progress) — NOT chart series
//   series1…series4  chart series identity, assigned in fixed order, never cycled
//   good/warn        status — reserved meaning, never worn by a series
//   z1…z5            HR zones — an ORDINAL ramp, monotone in lightness in each
//                    theme's own hue (a rainbow collapses under deuteranopia)
//   hm0…hm4          heatmap — sequential single-hue ramp over the surface
// series and zone values are VALIDATED, not eyeballed: test_palette.mjs runs
// the vendored validator (tools/validate-palette.mjs) against each theme's own
// panel surface — lightness band, chroma floor, adjacent-pair CVD separation,
// contrast. Edit a value here and the suite tells you if it stopped being legal.
export const THEMES = {
  volt: {bg:'#0E0F12',panel:'#15171C',panel2:'#1B1E25',ink:'#F3F5F0',sub:'#8B919B',line:'#23262E',grid:'#1E232B',accent:'#C7F646',accent2:'#4DA3FF',accentFade:'rgba(199,246,70,.13)',good:'#34D399',warn:'#FF6A4D',
    series1:'#78A326',series2:'#3E89D7',series3:'#CD5A97',series4:'#C0851F',
    hm0:'#191D24',hm1:'rgba(199,246,70,.22)',hm2:'rgba(199,246,70,.42)',hm3:'rgba(199,246,70,.66)',hm4:'#C7F646',
    z1:'#4A6125',z2:'#668336',z3:'#83A748',z4:'#A2D055',z5:'#BFFD4A',
    mapFilter:'grayscale(1) invert(.92) brightness(1.06) contrast(.88)'},
  track:{bg:'#ECEAE3',panel:'#FFFFFF',panel2:'#F6F4EE',ink:'#181612',sub:'#6E6A60',line:'#E0DCD2',grid:'#ECE9E1',accent:'#E8472B',accent2:'#1F6FEB',accentFade:'rgba(232,71,43,.12)',good:'#1F9D57',warn:'#B45309',
    series1:'#DA452C',series2:'#245FD4',series3:'#7A41AF',series4:'#009390',
    hm0:'#E6E3DA',hm1:'rgba(232,71,43,.22)',hm2:'rgba(232,71,43,.42)',hm3:'rgba(232,71,43,.64)',hm4:'#E8472B',
    z1:'#D79E92',z2:'#CC7867',z3:'#BF4E3A',z4:'#A52C18',z5:'#791B0C',
    mapFilter:'grayscale(.85) brightness(1.03) contrast(.9)'},
  sunset:{bg:'#150F0C',panel:'#1E1612',panel2:'#261B15',ink:'#F8EFE7',sub:'#A89486',line:'#2C211A',grid:'#271C16',accent:'#FF7A3D',accent2:'#FFC24B',accentFade:'rgba(255,122,61,.15)',good:'#6BD49A',warn:'#FF5A4D',
    series1:'#DB703B',series2:'#388EC4',series3:'#BC598C',series4:'#479D73',
    hm0:'#221813',hm1:'rgba(255,122,61,.24)',hm2:'rgba(255,122,61,.46)',hm3:'rgba(255,122,61,.7)',hm4:'#FF7A3D',
    z1:'#794B36',z2:'#A36649',z3:'#D57F57',z4:'#FF9C6B',z5:'#FFBD7F',
    mapFilter:'grayscale(1) invert(.9) sepia(.28) brightness(1.02) contrast(.88)'},
};

function defaultStorage() {
  try { return globalThis.localStorage; } catch { return null; }  // privacy modes can throw
}

// The persisted theme, defaulting when unset/unknown/unreadable — called from
// each component's state initializer so the first paint is already themed.
export function initialTheme(storage = defaultStorage()) {
  try {
    const t = storage && storage.getItem(THEME_KEY);
    return THEMES[t] ? t : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

export function persistTheme(name, storage = defaultStorage()) {
  try { if (storage && THEMES[name]) storage.setItem(THEME_KEY, name); } catch { /* storage full/blocked */ }
}

// The theme picker's swatch row: pick handlers + current-theme ring.
export function themePicker(current, pick) {
  return Object.keys(THEMES).map((name) => ({
    name,
    pick: () => pick(name),
    swatch: THEMES[name].accent,
    ring: current === name ? THEMES[name].accent : "transparent",
  }));
}

// ── navigation ────────────────────────────────────────────────────────────────
// Relative hrefs so every entry URL works (/, /progress, and the original
// /Running%20Dashboard.dc.html all resolve them to the clean routes).
const NAV_PAGES = [
  { key: "cockpit", label: "Cockpit", href: "./" },
  { key: "progress", label: "Progress", href: "./progress" },
  { key: "archive", label: "Archive", href: "./archive" },
];

export function navModel(currentPage) {
  return NAV_PAGES.map((p) => {
    const current = p.key === currentPage;
    return {
      ...p,
      current,
      aria: current ? "page" : "false",
      style: "padding:var(--sp-1) var(--sp-3);border-radius:var(--r-pill);" +
        "font-size:var(--fs-sm);font-weight:700;text-decoration:none;white-space:nowrap;" +
        (current ? "background:var(--accentFade);color:var(--ink)" : "color:var(--sub)"),
    };
  });
}

// ── greeting ──────────────────────────────────────────────────────────────────
export function dayBucket(d) {
  const h = d.getHours();
  return h < 5 ? "night" : h < 12 ? "morning" : h < 18 ? "afternoon" : "evening";
}

export function greetingText(d) {
  return { night: "Good night", morning: "Good morning",
           afternoon: "Good afternoon", evening: "Good evening" }[dayBucket(d)];
}

// ── sync pill ─────────────────────────────────────────────────────────────────
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const mDate = (iso) => { const d = new Date(iso); return MONTHS[d.getMonth()] + " " + d.getDate(); };
const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);

// Pure label/dot/title model: component state in, presentation out. `syncedOn`
// is the telemetry's baked date (D.today); `today` the live local date.
export function syncPillModel({ syncState, syncError, lastSync, lastResult, syncedOn, today }) {
  const ageDays = Math.max(0, daysBetween(syncedOn, today));
  const dateLabel = mDate(syncedOn);
  const freshLabel = ageDays <= 0 ? "today" : ageDays === 1 ? "yesterday" : ageDays + " days ago";
  const stale = ageDays >= 2;
  const ss = syncState;
  // a background (boot/nightly) sync that failed and the user hasn't overridden
  // this session → prompt to connect Garmin rather than a normal "synced" pill
  const bootFailed = ss === "idle" && lastResult && lastResult.ok === false;
  const noData = !lastSync; // garmin-data.js never written = first run
  const bootErr = bootFailed ? String(lastResult.error || "could not reach Garmin").split("\n")[0] : "";
  const problem = ss === "error" || bootFailed || stale;
  return {
    label: ss === "syncing" ? "Syncing…"
      : ss === "error" ? "Sync failed — retry"
      : bootFailed ? (noData ? "Connect Garmin" : "Sync failed — retry")
      : "Garmin · " + freshLabel,
    title: (ss === "error" && syncError) ? ("Sync failed: " + syncError + " — click to retry")
      : bootFailed ? ((noData ? "Not connected — " : "Last sync failed: ") + bootErr + " — check credentials, then click to retry")
      : ("Telemetry synced " + dateLabel + " (" + freshLabel + ") — click to sync now"),
    dotStyle: "width:6px;height:6px;border-radius:50%;background:" +
      (ss === "syncing" ? "var(--accent)" : problem ? "var(--warn)" : "var(--good)") +
      (ss === "syncing" ? ";animation:pulse 1s infinite" : ""),
    dateLabel,
  };
}

// Trigger a sync (POST /api/sync, reload on success). `host` is the component
// ({state, setState}) — one machine, every page.
export function syncNow(host) {
  if (host.state.syncState === "syncing") return;
  host.setState({ syncState: "syncing", syncError: null });
  fetch("./api/sync", { method: "POST" })
    .then((r) => r.json().then((b) => ({ status: r.status, ok: r.ok, b })).catch(() => ({ status: r.status, ok: r.ok, b: null })))
    .then(({ status, ok, b }) => {
      if (ok && b && b.ok) { window.location.reload(); return; } // fresh telemetry
      if (status === 409 || (b && b.status === "already-running")) { waitForSync(host); return; }
      const msg = (b && (b.error || b.status)) || (ok ? "empty response" : "request failed");
      host.setState({ syncState: "error", syncError: msg });
    })
    .catch((err) => host.setState({ syncState: "error", syncError: String((err && err.message) || err) }));
}

// A sync (boot/nightly) is already running — show "Syncing…" and poll until it
// finishes, then reload to pick up the result.
export function waitForSync(host) {
  host.setState({ syncState: "syncing", syncError: null });
  const poll = () => fetch("./api/status").then((r) => r.ok ? r.json() : null).then((s) => {
    if (s && !s.syncing) { window.location.reload(); return; }
    setTimeout(poll, 2000);
  }).catch(() => host.setState({ syncState: "error", syncError: "lost connection to server" }));
  setTimeout(poll, 2000);
}

// componentDidMount half of the pill: the last-sync indicator (silently absent
// when opened as a static file / no server API) + attach to a running sync.
export function initSyncStatus(host) {
  fetch("./api/status").then((r) => r.ok ? r.json() : null)
    .then((s) => {
      if (!s) return;
      host.setState({ lastSync: s.lastSync, lastResult: s.lastResult, statusReady: true });
      if (s.syncing) waitForSync(host);
    })
    .catch(() => {});
}

// Browser entry point: the dc components read everything through this global
// (their inline scripts can't use static imports).
if (typeof window !== "undefined") {
  window.SplitsTopbar = {
    THEME_KEY, DEFAULT_THEME, THEMES,
    initialTheme, persistTheme, themePicker,
    navModel, dayBucket, greetingText,
    syncPillModel, syncNow, waitForSync, initSyncStatus,
  };
}
