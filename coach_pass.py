"""coach_pass.py — the coach loop's derived state, for every pipeline.

Both producers of `garmin-data.js` must derive compliance, the block lens and
the insights block IDENTICALLY: the Garmin sync (sync_garmin.py) and the Health
Connect builder (ingest_builder.py). This module is the single definition of
that work, for the same reason interval_lens.zone_bounds is the single
definition of a zone boundary — two copies is how two instances start
disagreeing about the athlete's week.

Nothing here reads the environment or the clock: `today`, `max_hr` and the
parsed plan are always passed in, so both pipelines derive from exactly the
values they built their telemetry with.
"""
import activity_archive
import block_lens
import coach_briefing
import insight_metrics
import plan_compliance


def _noop(_msg: str) -> None:
    pass


def _safe(fn, label: str, log):
    """Run an assembly, returning None (and warning) if it throws. Each block is
    an independent fail domain (design D4): a dead trajectory must not take the
    compliance block down with it."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — resilience is the point here
        log(f"  ! {label} failed ({type(e).__name__}: {e}); block omitted")
        return None


def derive(conn, plan_raw, plan, today, max_hr, log=_noop) -> dict:
    """Bank today's plan snapshot, rescore compliance, refresh the block-lens
    rows. Writes the archive; assembles nothing.

    Runs AFTER the archive is current (it matches against archived activities)
    and BEFORE the telemetry is assembled (attach_blocks reads what this
    wrote). The caller wraps it fail-soft: a plan problem is a warning, never a
    failed build."""
    stats = plan_compliance.run_compliance(conn, plan_raw, plan, today, max_hr)

    # Ratchet the coverage expectation --verify-archive checks against: scored
    # weeks only ever accumulate, so a shrink is a regression.
    weeks_now = activity_archive.compliance_coverage(
        conn, plan_compliance.COMPLIANCE_VERSION)["weeks_scored"]
    prev = activity_archive.get_meta(conn, "expected_compliance_weeks")
    if weeks_now > int(prev or 0):
        activity_archive.set_meta(conn, "expected_compliance_weeks", weeks_now)

    parts = [f"{stats['weeks_scored']} weeks scored"]
    if stats["weeks_healed"]:
        parts.append(f"{stats['weeks_healed']} stale weeks healed")
    log("✓ compliance: " + ", ".join(parts))

    lens = block_lens.derive_block_lens(conn, today)
    if lens["blocks"]:
        log(f"✓ block lens: {lens['blocks']} blocks, {lens['recomputed']} recomputed")
    else:
        log("✓ block lens: no plan snapshots — nothing to derive")

    return {**stats, **lens}


def attach_blocks(conn, plan, today, data, log=_noop) -> list[str]:
    """Assemble every archive-derived block into `data` and fill
    predictions.trend from the trajectory. Returns the keys attached.

    `plan` may be None (unreadable plan file): the plan-dependent blocks are
    then omitted and insights/blockLens still assemble."""
    attached = []

    insights = _safe(lambda: insight_metrics.assemble_insights(conn, today),
                     "insights assembly", log)
    if insights:
        data["insights"] = insights
        attached.append("insights")
        trend = insight_metrics.trend_verdict(insights["trajectory"]["weekly"])
        if trend:
            data.setdefault("predictions", {})["trend"] = trend
        log(f"✓ insights assembled ({len(insights['efficiency']['monthly'])} months, "
            f"{len(insights['trajectory']['weekly'])} weeks)")

    if plan:
        compliance = _safe(
            lambda: plan_compliance.assemble_compliance(conn, plan, today),
            "compliance assembly", log)
        if compliance:
            data["compliance"] = compliance
            attached.append("compliance")
            log(f"✓ compliance assembled ({len(compliance['days'])} days, "
                f"{len(compliance['weeks'])} weeks)")

    lens = _safe(lambda: block_lens.assemble_block_lens(conn, today),
                 "block lens assembly", log)
    if lens:
        data["blockLens"] = lens
        attached.append("blockLens")
        log("✓ block lens assembled ("
            + ("current + " if lens.get("current") else "")
            + f"{len(lens['past'])} past)")

    if plan:
        course = _safe(lambda: _course(conn, plan), "course lens assembly", log)
        if course:
            data["courseLens"] = course
            attached.append("courseLens")

    return attached


def _course(conn, plan):
    """The stored course document for the plan's race, or None — a race without
    a `courseId` has no course, which is the normal state."""
    course_id = ((plan or {}).get("race") or {}).get("courseId")
    if not course_id:
        return None
    doc = activity_archive.course_document(conn, course_id)
    if doc:
        doc["map"] = activity_archive.course_map_row(conn, course_id)
    return doc
