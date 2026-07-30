# progress-views Specification (delta)

## ADDED Requirements

### Requirement: /progress hosts The Block section static-first
The `/progress` page SHALL include the "The Block" section (defined in the
`block-lens` capability) rendered static-first from `blockLens` in
`garmin-data.js`, with the archive API used only for past-block drill and the
block comparison's full documents. Absence of `blockLens` SHALL leave the rest
of `/progress` unaffected.

#### Scenario: Section present with a current block
- **WHEN** `/progress` loads and `blockLens.current` exists
- **THEN** The Block section renders between page load and any network activity, from static data alone

#### Scenario: Section absent without a lens
- **WHEN** `garmin-data.js` has no `blockLens`
- **THEN** `/progress` renders its existing sections with no Block section and no errors
