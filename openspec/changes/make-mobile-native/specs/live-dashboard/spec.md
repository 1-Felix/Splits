## ADDED Requirements

### Requirement: The readiness card displays its score and status
The readiness card SHALL render its numeric score and its status label as visible text at every width.

The value is the card's headline. It SHALL NOT be reachable only by inspecting the ring.

#### Scenario: The score is visible
- **WHEN** the cockpit is rendered at any width and readiness data is present
- **THEN** the readiness score and its status label are rendered as visible, non-zero-sized text within the ring

#### Scenario: Absent readiness stays honest
- **WHEN** readiness data is absent
- **THEN** the card degrades to its existing absent state rather than rendering an empty ring

### Requirement: Coach long-form content is summarised, with the whole available in one activation
The coach note and the coach log SHALL be presented in a bounded form at every width, with their full text one activation away.

The bounded form SHALL lead with the part that is acted on — the current instruction, and the most recent adjustments. No coach content is removed; the full text SHALL remain reachable and complete.

#### Scenario: The cockpit is not dominated by coach text
- **WHEN** the cockpit is rendered at 390px
- **THEN** the coach note and coach log together occupy less than one quarter of the document height, and the document is under six viewport heights

#### Scenario: The full text is one activation away
- **WHEN** the viewer activates the coach note's or the coach log's expand affordance
- **THEN** the complete text is presented, with nothing omitted

### Requirement: Coach prose renders as paragraphs
Coach prose SHALL be rendered as discrete paragraphs rather than as a single unbroken block of text.

#### Scenario: Paragraph structure exists
- **WHEN** a coach note containing multiple entries or separated passages is rendered, at any width
- **THEN** it renders as multiple paragraph elements rather than one continuous text node

### Requirement: The cockpit is composed for a phone
The cockpit SHALL present a phone composition in which each screen has a distinct purpose, rather than a single stacked column ordered by desktop source order.

The first screen SHALL answer what today is. Peer items that are meant to be compared — the weeks of a training block, the cockpit's chart set — SHALL remain comparable rather than being stacked into separate screens.

#### Scenario: Today is answered first
- **WHEN** the cockpit is opened at 390px
- **THEN** the first viewport carries the race countdown, readiness with its score, and the coach's current instruction

#### Scenario: Block weeks stay comparable
- **WHEN** the training block is rendered at 390px
- **THEN** its weeks are presented so that more than one is visible at a time, and the section occupies substantially less height than one card per week
