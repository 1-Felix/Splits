## ADDED Requirements

### Requirement: Every record in the wall is reachable on a phone
Every cell of the records wall SHALL be reachable at phone widths.

Where the wall's grid cannot fit, it SHALL be re-composed — one unit per distance, with the by-year detail behind a disclosure — rather than clipped inside a scroller that hides most of it without saying so.

#### Scenario: No record is unreachable
- **WHEN** the records wall is rendered at 390px
- **THEN** every record it carries is reachable, and no record is hidden behind an undisclosed horizontal scroll

#### Scenario: Records remain navigable
- **WHEN** the viewer activates a record at 390px
- **THEN** the run it was set in opens, as it does on desktop

### Requirement: The training block's week rows fit their frame
A training-block week row SHALL contain its own content at every width, both collapsed and expanded.

#### Scenario: The block does not overflow the page
- **WHEN** the progress page is rendered at 360px and 390px, with a week collapsed and with a week expanded
- **THEN** the document does not scroll horizontally, and each week row's content stays within the row

#### Scenario: An expanded day keeps its result
- **WHEN** a training-block week is expanded at 390px
- **THEN** each day's planned workout, its actual result and its link to the run are all within the viewport

### Requirement: Per-day plan detail opens where it can be read
A training-block week's per-day detail SHALL open within the viewport below the phone breakpoint.

#### Scenario: Detail is not opened below the fold
- **WHEN** the viewer opens a week's detail at 390px
- **THEN** the detail's first row is within the viewport

### Requirement: The block's day marks are readable without a pointer
Per-day compliance marks SHALL convey which day they refer to, and their meaning, without requiring a hover.

The marks SHALL also be exposed to assistive technology rather than hidden from it.

#### Scenario: A mark identifies its day
- **WHEN** the week rows are read at 390px
- **THEN** each day mark's weekday is visible, and its status is available to a screen reader through the row's accessible name

### Requirement: Progress charts open at a scope a phone can read
A chart offering scope controls SHALL open at a scope whose point spacing is usable at the current width.

The widest scope SHALL remain available, and an explicit choice by the viewer SHALL be respected.

#### Scenario: The default scope suits the width
- **WHEN** a scoped chart is first rendered at 390px
- **THEN** it opens at a scope whose points are spaced widely enough to be individually inspectable, with the full-history scope still one activation away
