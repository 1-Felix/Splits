## ADDED Requirements

### Requirement: Navigation is permanently reachable on a phone
Every page SHALL keep its navigation reachable at all times below the phone breakpoint, without the viewer scrolling back to the top of the document.

Below the phone breakpoint the page nav SHALL render as a fixed bar anchored to the bottom of the viewport, within thumb reach, and the page header SHALL be `position: sticky` at the top. Above that breakpoint the bottom bar SHALL NOT render and the header SHALL be exactly as it is today.

#### Scenario: Navigation survives a long scroll
- **WHEN** the viewer scrolls 1200px down any page at 390px wide
- **THEN** the bottom navigation bar is still fixed at the bottom of the viewport and the header is still pinned at `top: 0`

#### Scenario: Desktop chrome is untouched
- **WHEN** any page is rendered at 1200px or wider
- **THEN** no bottom bar exists in the document, the header is in normal flow, and its computed styles are unchanged from before this change

#### Scenario: The bar reflects the instance, not a hardcoded list
- **WHEN** the bar renders on an instance whose archive is unavailable, or on an instance with no course
- **THEN** it shows exactly the destinations the page's own nav model offers — two, three or four tabs — and marks the current page as current

### Requirement: The chrome declares its own height as a contract
The stylesheet SHALL publish the bottom bar's occupied height, including the device's safe-area inset, as a custom property that every other fixed or sticky surface reads.

No surface may hardcode the bar's height. The property SHALL resolve to zero above the phone breakpoint, so the same rule is correct at every width.

#### Scenario: Nothing is hidden behind the bar
- **WHEN** the archive's comparison tray is raised at 390px, and when a bottom sheet is open, and when the run page's crosshair readout bar is shown
- **THEN** each sits above the bottom bar rather than beneath it, and the page's last content is scrollable clear of it

#### Scenario: The safe area is respected
- **WHEN** the app is viewed on a device reporting a non-zero bottom safe-area inset
- **THEN** the bar's touch targets sit above the home indicator and the bar's background extends behind it

### Requirement: The app is installable to the home screen
The application SHALL serve a web app manifest and icons from its own origin, so it can be installed and launched without browser chrome.

The manifest SHALL declare a relative start URL, standalone display, and a theme colour; the theme colour SHALL track the theme the viewer has chosen. No manifest, icon or font may be requested from a third-party origin.

#### Scenario: The manifest is served correctly
- **WHEN** the manifest is requested
- **THEN** the server responds 200 with the `application/manifest+json` media type, and every icon it references also responds 200

#### Scenario: The installed app opens where it was launched
- **WHEN** the app is installed to the home screen and opened
- **THEN** it launches to the cockpit in standalone display with no browser address bar

#### Scenario: Origin purity holds
- **WHEN** the pages are loaded with every non-same-origin request aborted
- **THEN** they render completely, and no manifest or icon request goes to another origin

### Requirement: Long-form and secondary content opens in a sheet
Detail that would otherwise be dumped inline SHALL open in a shared bottom sheet below the phone breakpoint, rather than expanding the document.

The sheet SHALL be dismissible by Escape, by tapping outside it, and by dragging it down; it SHALL trap focus while open; and a scroll gesture inside it SHALL NOT chain to the page behind it. Content routed to a sheet SHALL remain fully present — nothing is removed, only relocated.

#### Scenario: Nothing is lost to the sheet
- **WHEN** a viewer opens the coach note, the coach log, a chart's evidence panel, or a planned day's detail on a phone
- **THEN** the full content is present inside the sheet, reachable in one activation from where it was summarised

#### Scenario: The sheet does not leak scroll
- **WHEN** the viewer flings past the end of a sheet's scrollable content
- **THEN** the page behind the sheet does not scroll

### Requirement: A page swipe never competes with a local gesture
A horizontal swipe MAY navigate between top-level pages below the phone breakpoint, and it SHALL yield to any element that owns the horizontal axis.

The gesture SHALL be recognised passively, so it can never suppress native scrolling or pinch-zoom, and it SHALL end in an ordinary document navigation rather than a moving track — no element may extend the document horizontally. It SHALL NOT arm when the gesture begins inside a chart, a horizontally scrollable region, a form field, or an active text selection, nor for multi-touch. Vertical intent SHALL always win.

#### Scenario: Charts and rails keep their axis
- **WHEN** a horizontal drag begins on a chart, on the heatmap's scroller, on the block strip, or in the search field
- **THEN** no page navigation occurs and the element's own behaviour is unaffected

#### Scenario: The document never widens
- **WHEN** any page is measured at 360px, 390px, 768px and 1200px
- **THEN** `document.documentElement.scrollWidth` does not exceed the viewport width

#### Scenario: Vertical scrolling is never captured
- **WHEN** the viewer scrolls the page vertically with a slight horizontal drift
- **THEN** the page scrolls normally and no navigation is triggered

### Requirement: Theme tokens are readable from the document root
The theme's custom properties SHALL be applied to the document root element, so surfaces rendered outside the application's mounted subtree are themed correctly.

The properties SHALL be re-applied whenever the theme changes, and the document background SHALL derive from the active theme rather than a hardcoded colour.

#### Scenario: Chrome outside the mounted tree is themed
- **WHEN** the viewer selects the light theme
- **THEN** the document body, the bottom bar and any open sheet all render in that theme's surface colours, with no black background remaining

#### Scenario: The theme does not go stale
- **WHEN** the viewer switches themes twice
- **THEN** the properties on the document root match the currently selected theme after each switch

### Requirement: Every page identifies itself
Every page SHALL carry a document title and a single top-level heading naming what the page is.

#### Scenario: The page is identifiable
- **WHEN** any of the six pages is loaded
- **THEN** `document.title` is a non-empty string naming the page, and the page renders exactly one top-level heading
