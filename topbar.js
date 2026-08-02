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

// ── theme variables on the document root (mobile-chrome D2) ──────────────────
// The 27 theme tokens are written onto the JS-built root <div> by each page's
// renderVals(), which means getComputedStyle(document.documentElement) returns
// "" for --accent: anything rendered OUTSIDE that div — the body, the bottom
// tab bar, a sheet — is unthemed. Applying them to :root as well is purely
// additive (the root div keeps its own copy, so every existing rule cascades
// exactly as before) and it must be RE-applied on every switch, or the hoisted
// values go stale while the div's do not.
export function applyThemeVars(name, el) {
  const theme = THEMES[name] || THEMES[DEFAULT_THEME];
  const target = el || (typeof document !== "undefined" ? document.documentElement : null);
  if (!target || !target.style) return theme;
  for (const k in theme) target.style.setProperty("--" + k, theme[k]);
  // the installed app's chrome takes its colour from the active theme too
  if (typeof document !== "undefined") {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme.bg);
  }
  return theme;
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
  applyThemeVars(name);   // every page's setTheme already calls this — zero page edits
}

// The theme picker's swatch row: pick handlers + current-theme ring. The
// swatches were three unlabelled circles named only by `title` — invisible to a
// screen reader and unreachable on touch — so the model now carries the
// accessible name and the pressed state the markup states explicitly.
export function themePicker(current, pick) {
  return Object.keys(THEMES).map((name) => ({
    name,
    pick: () => pick(name),
    swatch: THEMES[name].accent,
    ring: current === name ? THEMES[name].accent : "transparent",
    aria: name + " theme",
    on: String(current === name),
  }));
}

// ── navigation ────────────────────────────────────────────────────────────────
// Relative hrefs so every entry URL works (/, /progress, and the original
// /Running%20Dashboard.dc.html all resolve them to the clean routes).
const NAV_PAGES = [
  { key: "cockpit", label: "Cockpit", href: "./" },
  { key: "progress", label: "Progress", href: "./progress" },
  { key: "archive", label: "Archive", href: "./archive" },
  { key: "course", label: "Course", href: "./course" },
];

// opts.archive === false drops the Archive tab — an instance without an
// archive db (ingest-fed) has no archive pages to offer. Default keeps it:
// unknown (static file, status not yet fetched) must not hide navigation.
//
// Course is the MIRROR of that rule: opt-IN. A race names a course or it does
// not, and most do not, so the tab appears only when opts.course === true —
// otherwise an instance with no race (or no courseId) would advertise a page
// with nothing on it. Unknown availability therefore hides it, which is the
// opposite default to Archive and deliberately so.
export function navModel(currentPage, opts = {}) {
  let pages = opts.course === true ? NAV_PAGES : NAV_PAGES.filter((p) => p.key !== "course");
  if (opts.archive === false) pages = pages.filter((p) => p.key !== "archive");
  return pages.map((p) => {
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
      host.setState({
        lastSync: s.lastSync, lastResult: s.lastResult, statusReady: true,
        // instance shape: ingest-fed hides the Garmin pill; a missing archive
        // db hides the Archive tab + drill links. Absent fields (older server)
        // leave the defaults: pill shown, archive assumed present.
        ingestFed: Boolean(s.ingestFed),
        archiveAvail: s.archive !== false,
      });
      if (s.syncing) waitForSync(host);
    })
    .catch(() => {});
}

// ── the phone tier ────────────────────────────────────────────────────────────
// 700, not 560: the audit measured a BACKWARDS CLIFF — 561–700px rendered
// measurably worse than 560px, because the re-composition rules stopped
// applying while the desktop grids still did not fit. Must stay in step with
// dashboard.css's phone media query.
export const PHONE_MAX = 700;

// ── the width a chart is actually rendered at (chart-engine D5) ──────────────
// Every chart is drawn in a 600-unit frame and stretched to its card. Passing
// the rendered CSS width lets the engine make density decisions on screen
// instead of in frame units. It is DERIVED from the layout contract, not
// measured: .app-root's padding is clamp(16px, 4vw, 40px), a .card adds 16px of
// padding and a 1px border on each side, and below the phone tier every chart
// grid is a single column. That is exactly the 324px the audit measured a
// cockpit chart at on a 390px viewport.
//
// Above the phone tier it returns null, and the engine then leaves the frame
// alone: a chart rendered wider than 600 CSS px keeps today's geometry, so
// there is nothing to correct and nothing to risk.
export function chartCssWidth(vw) {
  const w = vw != null ? vw : (typeof window !== "undefined" ? window.innerWidth : null);
  if (!w || w > PHONE_MAX) return null;
  const pad = Math.min(40, Math.max(16, w * 0.04));
  const card = 17;   // .card padding (16) + border (1)
  return Math.max(200, Math.round(w - 2 * pad - 2 * card));
}

// Re-render a page when the viewport width actually changes (a rotation, a
// desktop window drag), so charts re-decide their density against the width
// they are now rendered at. Height changes are ignored: a mobile browser's
// collapsing toolbar fires resize constantly and nothing here depends on it.
export function watchWidth(host) {
  if (typeof window === "undefined" || !host || typeof host.setState !== "function") return () => {};
  let last = window.innerWidth, timer = null;
  const onResize = () => {
    if (window.innerWidth === last) return;
    last = window.innerWidth;
    clearTimeout(timer);
    timer = setTimeout(() => host.setState({ vw: last }), 150);
  };
  window.addEventListener("resize", onResize);
  return () => { clearTimeout(timer); window.removeEventListener("resize", onResize); };
}

const TAB_ICON = { cockpit: "home", progress: "chart", archive: "archive", course: "route" };
const tabKey = (label) => String(label || "").trim().toLowerCase().replace(/[^a-z]/g, "");

// Pure model for the bottom bar: nav entries in, tabs out. Takes whatever
// carries {label, href, current} — navModel's output, or anchors mirrored out
// of the page's own rendered nav — so the bar can never offer a destination
// the page itself does not.
export function tabModel(entries) {
  const list = Array.isArray(entries) ? entries : [];
  return list
    .filter((e) => e && e.href && String(e.label || "").trim())
    .map((e) => {
      const key = e.key || tabKey(e.label);
      return {
        key,
        label: String(e.label).trim(),
        href: e.href,
        current: e.current === true || e.aria === "page",
        icon: TAB_ICON[key] || "dot",
      };
    });
}

// ── the bottom tab bar (mobile-chrome D1) ─────────────────────────────────────
// MIRRORED from the page's own rendered nav rather than authored six times, so
// tab availability and aria-current are correct on every instance for free —
// including one with no archive db or no course. Three rules the prototype
// proved load-bearing:
//   • scope the selector to #dc-root — unscoped it also matches the raw,
//     un-mounted <x-dc> template and returns href="{{ n.href }}";
//   • read a.href (absolute), because run.dc.html carries <base href="/">;
//   • give the bar a DIFFERENT aria-label than "Pages" — two landmarks with
//     one name is an a11y smell, and test_course_page.mjs asserts over
//     nav[aria-label="Pages"] a.
const TAB_SELECTOR = '#dc-root header.topbar nav[aria-label="Pages"] a';

export function mountTabBar(doc) {
  const d = doc || (typeof document !== "undefined" ? document : null);
  if (!d || !d.body) return null;
  const tabs = tabModel([...d.querySelectorAll(TAB_SELECTOR)].map((a) => ({
    label: a.textContent, href: a.href,
    current: a.getAttribute("aria-current") === "page",
  })));
  let bar = d.querySelector("nav.tabbar");
  if (!tabs.length) { if (bar) bar.remove(); return null; }
  const sig = tabs.map((t) => t.key + "|" + t.href + (t.current ? "*" : "")).join(",");
  if (bar && bar.getAttribute("data-sig") === sig) return bar;   // nothing moved
  if (!bar) {
    bar = d.createElement("nav");
    bar.className = "tabbar";
    bar.setAttribute("aria-label", "Sections");
    d.body.appendChild(bar);
  }
  bar.setAttribute("data-sig", sig);
  bar.textContent = "";
  for (const t of tabs) {
    const a = d.createElement("a");
    a.className = "tab" + (t.current ? " tab--current" : "");
    a.href = t.href;
    if (t.current) a.setAttribute("aria-current", "page");
    const ico = d.createElement("span");
    ico.className = "tab-ico tab-ico--" + t.icon;
    ico.setAttribute("aria-hidden", "true");
    const lab = d.createElement("span");
    lab.className = "tab-label";
    lab.textContent = t.label;
    a.appendChild(ico);
    a.appendChild(lab);
    bar.appendChild(a);
  }
  return bar;
}

// ── the header's one control (mobile-chrome 3.6) ─────────────────────────────
// On a phone the header carried a 22px-per-swatch theme picker and a sync pill
// — three unlabelled circles and a control well under the touch floor, on a bar
// that also had to stay under 62px. Both move behind ONE 44px control that
// opens them in the sheet, where each has a real label and a real target.
//
// The control is appended to document.body, not into header.topbar: the header
// is React-owned, and this way nothing is ever inserted into a subtree React
// reconciles. CSS places it inside the sticky header's frame.
function headerControls(d) {
  const bar = d.querySelector("#dc-root header.topbar");
  if (!bar) return { themes: [], sync: null };
  const themes = Object.keys(THEMES)
    .map((name) => ({ name, el: bar.querySelector('button[title="' + name + '"]') }))
    .filter((t) => t.el);
  const sync = [...bar.querySelectorAll(".topbar-actions button")]
    .find((b) => !THEMES[b.getAttribute("title")]) || null;
  return { themes, sync };
}

function openHeaderSheet(d) {
  const { themes, sync } = headerControls(d);
  const body = d.createElement("div");
  const current = initialTheme();

  if (sync) {
    const h = d.createElement("div");
    h.className = "sheet-section";
    h.textContent = "TELEMETRY";
    const line = d.createElement("p");
    line.className = "sheet-p";
    line.textContent = (sync.textContent || "").trim() || "Sync";
    const btn = d.createElement("button");
    btn.type = "button";
    btn.className = "sheet-btn";
    btn.textContent = "Sync now";
    btn.addEventListener("click", () => { closeSheet(); sync.click(); });
    const row = d.createElement("div");
    row.className = "sheet-row";
    row.appendChild(btn);
    body.appendChild(h); body.appendChild(line); body.appendChild(row);
  }

  if (themes.length) {
    const h = d.createElement("div");
    h.className = "sheet-section";
    h.textContent = "THEME";
    const row = d.createElement("div");
    row.className = "sheet-row";
    for (const t of themes) {
      const b = d.createElement("button");
      b.type = "button";
      b.className = "sheet-swatch";
      b.style.background = THEMES[t.name].accent;
      b.setAttribute("aria-label", t.name + " theme");
      b.setAttribute("aria-pressed", String(t.name === current));
      b.addEventListener("click", () => { t.el.click(); closeSheet(); });
      row.appendChild(b);
    }
    body.appendChild(h); body.appendChild(row);
  }

  if (!body.childNodes.length) {
    const p = d.createElement("p");
    p.className = "sheet-p";
    p.textContent = "This page carries no settings of its own.";
    body.appendChild(p);
  }
  openSheet({ title: "Settings", node: body });
}

export function mountHeaderMore(doc) {
  const d = doc || (typeof document !== "undefined" ? document : null);
  if (!d || !d.body) return null;
  const hasHeader = d.querySelector("#dc-root header.topbar") !== null;
  let btn = d.querySelector("button.hdr-more");
  if (!hasHeader) { if (btn) btn.remove(); return null; }
  if (btn) return btn;
  btn = d.createElement("button");
  btn.type = "button";
  btn.className = "hdr-more";
  btn.setAttribute("aria-label", "Settings, theme and sync");
  btn.addEventListener("click", () => openHeaderSheet(d));
  d.body.appendChild(btn);
  return btn;
}

// Re-run the mirror whenever React re-renders the header (a theme change, the
// archive-availability probe resolving, a sync starting). The signature check
// above makes every no-op re-render free.
function watchChrome() {
  if (typeof MutationObserver === "undefined") return;
  let queued = false;
  const run = () => {
    queued = false;
    try { mountTabBar(document); mountHeaderMore(document); } catch { /* mid-render */ }
  };
  const schedule = () => {
    if (queued) return;
    queued = true;
    (typeof requestAnimationFrame === "function" ? requestAnimationFrame : setTimeout)(run, 0);
  };
  const root = document.getElementById("dc-root") || document.body;
  new MutationObserver(schedule).observe(root, {
    childList: true, subtree: true, attributes: true,
    attributeFilter: ["aria-current", "href"],
  });
  schedule();
}

// ── horizontal scrollers disclose that they scroll (responsive-layout) ───────
// A region narrower than its content used to give no sign of it: 49% of the
// records wall was unreachable behind a scroller nothing announced. Every
// [data-scroller] carries a data-overflow attribute naming which edge still
// has content — "start", "end", "both", or absent when it all fits — and the
// stylesheet paints an edge only for what the attribute says. The attribute is
// also what a test can assert, which a painted gradient is not.
export function scrollerState(el) {
  if (!el) return null;
  if (el.scrollWidth <= el.clientWidth + 1) return null;
  const atStart = el.scrollLeft <= 1;
  const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1;
  return atStart && atEnd ? null : atStart ? "end" : atEnd ? "start" : "both";
}

export function armScrollers(doc) {
  const d = doc || (typeof document !== "undefined" ? document : null);
  if (!d || typeof MutationObserver === "undefined") return;
  const update = (el) => {
    const s = scrollerState(el);
    if (s) el.setAttribute("data-overflow", s);
    else el.removeAttribute("data-overflow");
  };
  const sweep = () => {
    for (const el of d.querySelectorAll("[data-scroller]")) {
      if (!el.dataset.scrollerArmed) {
        el.dataset.scrollerArmed = "1";
        el.addEventListener("scroll", () => update(el), { passive: true });
        // "the scroller opens where it matters" — a year-long heatmap opens on
        // today, not on the oldest half of the year
        if (el.getAttribute("data-scroller") === "end") el.scrollLeft = el.scrollWidth;
      }
      update(el);
    }
  };
  let queued = false;
  const schedule = () => {
    if (queued) return;
    queued = true;
    (typeof requestAnimationFrame === "function" ? requestAnimationFrame : setTimeout)(() => {
      queued = false;
      try { sweep(); } catch { /* mid-render */ }
    }, 0);
  };
  new MutationObserver(schedule).observe(d.getElementById("dc-root") || d.body,
    { childList: true, subtree: true });
  if (typeof window !== "undefined") window.addEventListener("resize", schedule);
  schedule();
}

// ── the shared sheet layer (mobile-chrome: "long-form content opens in a
// sheet") ─────────────────────────────────────────────────────────────────────
// Body-level, so it is outside React's reconciliation by construction and one
// implementation serves every page. Dismissed by Escape, by the backdrop, and
// by dragging it down; focus is trapped while open and returned on close;
// scrolling inside it never chains to the page behind it.
let openSheetState = null;

export function closeSheet() {
  const s = openSheetState;
  if (!s) return;
  openSheetState = null;
  document.removeEventListener("keydown", s.onKey, true);
  s.backdrop.remove();
  if (s.restoreFocus && typeof s.restoreFocus.focus === "function") {
    try { s.restoreFocus.focus(); } catch { /* detached */ }
  }
  if (typeof s.onClose === "function") s.onClose();
}

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function openSheet(opts) {
  const o = opts || {};
  if (typeof document === "undefined" || !document.body) return null;
  closeSheet();
  // A tap inside a body-level sheet does not bubble to the page root, whose
  // onClick dismisses pinned chart popovers — so say so explicitly.
  if (typeof o.onDismiss === "function") { try { o.onDismiss(); } catch { /* page state */ } }

  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop";
  const sheet = document.createElement("div");
  sheet.className = "sheet";
  sheet.setAttribute("role", "dialog");
  sheet.setAttribute("aria-modal", "true");

  const head = document.createElement("div");
  head.className = "sheet-head";
  const grip = document.createElement("div");
  grip.className = "sheet-grip";
  grip.setAttribute("aria-hidden", "true");
  const title = document.createElement("h2");
  title.className = "sheet-title";
  title.id = "sheet-title-" + Math.random().toString(36).slice(2, 8);
  title.textContent = o.title || "Detail";
  sheet.setAttribute("aria-labelledby", title.id);
  const close = document.createElement("button");
  close.className = "sheet-close";
  close.type = "button";
  close.setAttribute("aria-label", "Close");
  close.textContent = "✕";
  head.appendChild(title);
  head.appendChild(close);

  const body = document.createElement("div");
  body.className = "sheet-body";
  const content = o.node;
  if (content instanceof Node) body.appendChild(content);
  else if (Array.isArray(content)) {
    for (const part of content) {
      if (part instanceof Node) { body.appendChild(part); continue; }
      const p = document.createElement("p");
      p.className = "sheet-p";
      p.textContent = String(part);
      body.appendChild(p);
    }
  } else if (content != null) {
    const p = document.createElement("p");
    p.className = "sheet-p";
    p.textContent = String(content);
    body.appendChild(p);
  }

  sheet.appendChild(grip);
  sheet.appendChild(head);
  sheet.appendChild(body);
  backdrop.appendChild(sheet);
  document.body.appendChild(backdrop);

  const onKey = (ev) => {
    if (ev.key === "Escape") { ev.stopPropagation(); ev.preventDefault(); closeSheet(); return; }
    if (ev.key !== "Tab") return;
    const items = [...sheet.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === close);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
    else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
  };
  document.addEventListener("keydown", onKey, true);
  close.addEventListener("click", closeSheet);
  backdrop.addEventListener("click", (ev) => { if (ev.target === backdrop) closeSheet(); });

  // drag the sheet down to dismiss — the gesture a phone viewer reaches for
  let dragY = null, moved = 0;
  sheet.addEventListener("touchstart", (ev) => {
    if (ev.touches.length !== 1 || body.scrollTop > 0) { dragY = null; return; }
    dragY = ev.touches[0].clientY; moved = 0;
  }, { passive: true });
  sheet.addEventListener("touchmove", (ev) => {
    if (dragY == null || ev.touches.length !== 1) return;
    moved = ev.touches[0].clientY - dragY;
    sheet.style.transform = moved > 0 ? "translateY(" + moved + "px)" : "";
  }, { passive: true });
  sheet.addEventListener("touchend", () => {
    if (dragY == null) return;
    if (moved > 90) closeSheet(); else sheet.style.transform = "";
    dragY = null;
  }, { passive: true });

  openSheetState = { backdrop, sheet, onKey, onClose: o.onClose,
                     restoreFocus: document.activeElement };
  const target = sheet.querySelector(FOCUSABLE) || close;
  try { target.focus(); } catch { /* not focusable yet */ }
  return { sheet, body, close: closeSheet };
}

export function sheetIsOpen() { return openSheetState !== null; }

// ── page swipe (mobile-chrome D7) ─────────────────────────────────────────────
// Three listeners at module scope, ALL { passive: true } — so the handler can
// never preventDefault and therefore can never break native scrolling or
// pinch-zoom. It ends in an ordinary document navigation, never a moving
// track: five pages assert documentElement.scrollWidth <= width + 1, which any
// carousel or 100vw element would fail outright.
const SWIPE = { armDX: 12, dropDY: 8, ratio: 2, minFrac: 0.25, minVel: 0.5 };
const FORM_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT", "BUTTON", "OPTION", "LABEL"]);

// The refusal guard: anything that owns the horizontal axis keeps it.
export function swipeRefused(el) {
  if (!el) return false;
  if (typeof window !== "undefined" && window.getSelection) {
    const sel = window.getSelection();
    if (sel && String(sel).length > 0) return true;
  }
  for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
    if (n.nodeType !== 1) continue;
    const tag = n.tagName;
    if (tag === "svg" || tag === "SVG") return true;
    if (typeof n.closest === "function" && n.closest("svg")) return true;
    if (FORM_TAGS.has(tag) || n.isContentEditable) return true;
    if (n.hasAttribute && n.hasAttribute("data-no-swipe")) return true;
    const cs = getComputedStyle(n);
    if (cs.touchAction && cs.touchAction !== "auto") return true;
    const ox = cs.overflowX;
    if ((ox === "auto" || ox === "scroll") && n.scrollWidth > n.clientWidth + 1) return true;
  }
  return false;
}

export function armSwipe(doc) {
  const d = doc || (typeof document !== "undefined" ? document : null);
  if (!d || !d.addEventListener) return;
  let x0 = 0, y0 = 0, t0 = 0, live = false, locked = false;

  d.addEventListener("touchstart", (ev) => {
    live = false; locked = false;
    if (window.innerWidth > PHONE_MAX) return;
    if (!ev.touches || ev.touches.length !== 1) return;
    if (sheetIsOpen()) return;
    if (swipeRefused(ev.target)) return;
    const t = ev.touches[0];
    x0 = t.clientX; y0 = t.clientY; t0 = ev.timeStamp || Date.now();
    live = true;
  }, { passive: true });

  d.addEventListener("touchmove", (ev) => {
    if (!live || !ev.touches || ev.touches.length !== 1) { live = false; return; }
    const dx = ev.touches[0].clientX - x0, dy = ev.touches[0].clientY - y0;
    // vertical intent always wins
    if (Math.abs(dy) > SWIPE.dropDY && Math.abs(dy) > Math.abs(dx)) { live = false; return; }
    if (Math.abs(dx) > SWIPE.armDX && Math.abs(dx) > SWIPE.ratio * Math.abs(dy)) locked = true;
  }, { passive: true });

  d.addEventListener("touchend", (ev) => {
    if (!live || !locked) { live = false; locked = false; return; }
    live = false; locked = false;
    const t = (ev.changedTouches && ev.changedTouches[0]) || null;
    if (!t) return;
    const dx = t.clientX - x0;
    const dt = Math.max(1, (ev.timeStamp || Date.now()) - t0);
    const far = Math.abs(dx) >= window.innerWidth * SWIPE.minFrac;
    const fast = Math.abs(dx) / dt >= SWIPE.minVel;
    if (!far && !fast) return;
    const tabs = tabModel([...d.querySelectorAll(TAB_SELECTOR)].map((a) => ({
      label: a.textContent, href: a.href,
      current: a.getAttribute("aria-current") === "page",
    })));
    if (tabs.length < 2) return;
    const at = tabs.findIndex((n) => n.current);
    if (at < 0) return;
    const next = at + (dx < 0 ? 1 : -1);
    if (next < 0 || next >= tabs.length) return;
    window.location.href = tabs[next].href;
  }, { passive: true });
}

// Browser entry point: the dc components read everything through this global
// (their inline scripts can't use static imports).
if (typeof window !== "undefined") {
  window.SplitsTopbar = {
    THEME_KEY, DEFAULT_THEME, THEMES, PHONE_MAX,
    initialTheme, persistTheme, themePicker, applyThemeVars,
    navModel, dayBucket, greetingText,
    syncPillModel, syncNow, waitForSync, initSyncStatus,
    tabModel, mountTabBar, mountHeaderMore, openSheet, closeSheet, sheetIsOpen,
    chartCssWidth, watchWidth, armScrollers, scrollerState,
    armSwipe, swipeRefused,
  };
  // Theme the document root before first paint: the body background, the tab
  // bar and any sheet all live outside the mounted subtree and would otherwise
  // render untokenised on a hardcoded black body.
  applyThemeVars(initialTheme());
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { watchChrome(); armSwipe(document); armScrollers(document); }, { once: true });
  } else {
    watchChrome();
    armSwipe(document);
    armScrollers(document);
  }
}
