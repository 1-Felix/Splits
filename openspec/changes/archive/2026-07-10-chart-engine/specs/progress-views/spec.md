# progress-views Specification (delta)

## ADDED Requirements

### Requirement: Progress charts offer scope controls where the data supports them
Each trend chart on the progress page SHALL offer a scope control that
re-derives its domain over the selected tail of its series, so a deviation
invisible across the full range becomes visible across a shorter one. A scope
option SHALL be offered only where the underlying series carries enough points to
honour it, and each chart SHALL state its actual span alongside its title.

#### Scenario: Narrowing the scope resolves a deviation
- **WHEN** the user selects a six-month scope on a thirty-month series
- **THEN** the chart re-derives its domain and its axes over the last six months
  only, and the subtitle states that span

#### Scenario: A chip is never offered beyond the data
- **WHEN** a series carries fewer points than a scope option requires
- **THEN** that option is not offered, and no chart implies a range it cannot
  render

### Requirement: Year-over-year bars share one domain
The year-over-year comparison SHALL plot every year against a single shared y
domain anchored at zero, so bar heights are comparable across years.

#### Scenario: Years are visually comparable
- **WHEN** the year-over-year chart renders three years of monthly volume
- **THEN** all years share one zero-anchored y domain, and a month's bar height
  is comparable to the same month in another year

### Requirement: Timeline charts carry annotations
Where a chart plots a timeline, it SHALL mark the events already present in the
data file — race day, and the dates on which records fell (`insights.recordsFeed`)
— as annotations that name what happened. Annotation flags SHALL be placed
without overlapping one another.

#### Scenario: A record is marked where it fell
- **WHEN** a timeline chart spans a date in `insights.recordsFeed`
- **THEN** an annotation marks that date and names the distance whose record fell

#### Scenario: Crowded annotations do not collide
- **WHEN** several annotations fall close together on the x axis
- **THEN** they are placed in separate lanes and remain individually legible
