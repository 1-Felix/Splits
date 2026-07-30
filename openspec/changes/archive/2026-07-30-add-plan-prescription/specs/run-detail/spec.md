## ADDED Requirements

### Requirement: The plan card shows the prescription's verdict beside the executed structure

The `/run/:id` plan card SHALL render the planned prescription text and its
verdict alongside the existing planned-vs-actual line whenever the run's
matched plan day carries a rep-level verdict. When no verdict exists the card SHALL render
exactly as before — absence, not emptiness.

#### Scenario: A quality day's run shows the verdict

- **WHEN** the run's plan day carries a verdict (`4/4 reps, 3 inside
  5:25–5:35`)
- **THEN** the plan card renders the planned text and that verdict

#### Scenario: A day without a verdict renders unchanged

- **WHEN** the run's plan day has no `quality` annotation
- **THEN** the plan card renders exactly its pre-existing content
