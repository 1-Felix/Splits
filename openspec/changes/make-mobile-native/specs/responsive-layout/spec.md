## ADDED Requirements

### Requirement: The layout declares named width tiers
The stylesheet SHALL express its responsive behaviour as named tiers, and every layout rule SHALL belong to one of them.

The tiers are: phone at 700px and below; tablet from 701px to 900px; desktop from 901px; and wide from 1600px. The phone tier SHALL be a single boundary — no surface may improve at a narrower width and regress at a wider one within it.

#### Scenario: No backwards cliff
- **WHEN** any page is measured at 360px, 390px, 560px, 640px and 700px
- **THEN** no page is measurably worse at a wider width than at a narrower one — no new overflow, no reduction in touch-target size, and no loss of a phone composition

#### Scenario: The tiers are asserted, not assumed
- **WHEN** the responsive harness runs
- **THEN** it exercises every page at 360, 390, 768, 1200, 1600 and 1920px, including the course page

### Requirement: No page overflows its viewport horizontally
No page SHALL cause the document to scroll horizontally at any supported width.

An element that legitimately exceeds the viewport SHALL live inside its own clipped, scrollable container and SHALL NOT extend the document.

#### Scenario: The document stays within the viewport
- **WHEN** every page is loaded at 320px, 360px, 390px, 768px and 1200px, including with a training block expanded
- **THEN** `document.documentElement.scrollWidth` does not exceed the viewport width by more than one pixel

#### Scenario: A failure names its cause
- **WHEN** the responsive harness detects horizontal overflow
- **THEN** it reports the offending leaf element, ignoring elements clipped by a scrollable ancestor, rather than only the measured width

### Requirement: Interactive controls meet a minimum touch size
Every interactive control SHALL present a touch target of at least 44 by 44 CSS pixels below the phone breakpoint.

Where a control's visible ink is legitimately smaller, its hit area SHALL be enlarged to meet the floor. Two adjacent controls SHALL NOT overlap, and a control whose activation is destructive or navigational SHALL NOT sit within the miss radius of a different action.

#### Scenario: The floor holds everywhere
- **WHEN** every page is loaded at 390px and every anchor, button, input, select and element with an activation handler is measured
- **THEN** each has a touch target of at least 44 by 44 CSS pixels

#### Scenario: A miss does not destroy work
- **WHEN** the viewer aims for a row's selection control on the archive and misses it
- **THEN** the miss does not navigate away and does not discard the current selection

### Requirement: Text meets a minimum legible size
No text SHALL render below 11 CSS pixels at any width, and no text-entry field SHALL render below 16 CSS pixels below the phone breakpoint.

The 16px floor on entry fields exists because smaller values cause the browser to zoom the whole page on focus.

#### Scenario: The type floor holds
- **WHEN** every page is loaded at 390px
- **THEN** no rendered text node computes to a font size below 11 pixels, including chart axis ticks and annotation labels

#### Scenario: Focusing a field does not zoom the page
- **WHEN** the viewer focuses the archive's search field on a phone
- **THEN** the page does not zoom

### Requirement: Dense surfaces are re-composed for a phone, not squeezed
A table or grid that cannot be read at phone width SHALL be given a phone composition, rather than being narrowed until its columns collide or its labels truncate.

A phone composition SHALL preserve every value the wide composition shows — content parity is not negotiable — and SHALL present each record as a bounded unit rather than as run-together inline text. Where the runtime supports conditional rendering, only one composition SHALL exist in the document at a time.

#### Scenario: Records stay identifiable
- **WHEN** a list, comparison or table is read at 390px
- **THEN** every record is visually bounded, every value it carries on desktop is present, and no identifying label is truncated to the point of ambiguity

#### Scenario: Placeholders do not become noise
- **WHEN** a phone composition renders records with absent measures
- **THEN** absent measures are omitted from the record rather than rendered as a row of placeholder marks

### Requirement: Horizontal scrollers disclose that they scroll
Any container that scrolls horizontally SHALL indicate that more content exists beyond its visible edge.

The indication SHALL appear only while the container actually overflows. Such a container SHALL claim the horizontal axis locally so that a page-level swipe does not compete with it, and SHALL open on its most relevant end.

#### Scenario: Hidden content announces itself
- **WHEN** a horizontally scrollable region is rendered narrower than its content at 390px
- **THEN** an edge affordance shows that it scrolls, and the region does not chain its scroll to the page

#### Scenario: The scroller opens where it matters
- **WHEN** the training heatmap is first rendered
- **THEN** it is scrolled to the most recent period, not the oldest

### Requirement: Information is never carried by hover alone
No information SHALL be available only through a pointer hover state.

Content currently reachable only by hovering SHALL be reachable by activation on a touch device, and SHALL be exposed to assistive technology. Interface copy SHALL NOT instruct the reader to perform a gesture their device does not have.

#### Scenario: Hover-only content is reachable by touch
- **WHEN** an element that carries explanatory content is activated on a touch device
- **THEN** that content is presented, and the same content is available to a screen reader

#### Scenario: Copy is device-neutral
- **WHEN** interface copy describes how to inspect a value
- **THEN** it does not name a pointer-only gesture

### Requirement: Activation is visibly acknowledged
Every interactive control SHALL give immediate visible feedback when pressed, and SHALL show a visible focus indicator when focused by keyboard.

The focus indicator SHALL be drawn from the active theme rather than left to the user agent's default.

#### Scenario: A press is acknowledged
- **WHEN** the viewer presses any control
- **THEN** the control changes appearance for the duration of the press

#### Scenario: Keyboard focus is visible in every theme
- **WHEN** the viewer tabs to any control in any theme
- **THEN** a focus indicator is drawn with sufficient contrast against that theme's background

### Requirement: A short surface is never stretched by a tall neighbour
Below the desktop breakpoint, a card SHALL NOT be stretched to the height of a taller row partner.

Content whose length is unbounded SHALL remain contained at every width, not only on desktop.

#### Scenario: No empty panel
- **WHEN** the cockpit is rendered at any width between 561px and 900px
- **THEN** no card renders more than one viewport of empty space below its content

#### Scenario: Unbounded content stays bounded
- **WHEN** a card whose content is unbounded is rendered at 390px
- **THEN** the card is bounded and its content scrolls or summarises within it, rather than extending the page

### Requirement: Wide displays use the width they are given
Above the wide breakpoint the layout SHALL use the additional width for content rather than for margin.

All pages SHALL share one container width so the chrome does not change width as the viewer navigates between them.

#### Scenario: The container scales up
- **WHEN** any page is rendered at 1920px
- **THEN** the content container is wider than it is at 1440px

#### Scenario: The chrome does not jump
- **WHEN** the viewer navigates between any two pages at the same width
- **THEN** the header and content container render at the same width on both
