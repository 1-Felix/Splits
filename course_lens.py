#!/usr/bin/env python3
"""course_lens — the RACE COURSE engine (add-course-lens).

Everything else in this system looks backwards at what was run. This looks
forward at what the race will ask: the planned route's profile, what each
kilometre should cost at a given target, and — once the race has been run — where
the time actually went.

Three properties, each a design decision worth keeping in view:

  * **Acquisition is sync-time, never browser-time** (design D1/D8). The course
    comes from Garmin's course service through the credentials the sync already
    holds, exactly as `route-basemap` established for map tiles.

  * **Every gradient derives from a SMOOTHED elevation series** (design D3).
    Raw DEM elevation over ~18 m point spacing yields ±20 % grades on flat
    ground. Smoothing happens here, in Python, and both series are stored, so
    the pace model and the rendered profile can never disagree about the grade
    at a given kilometre.

  * **The stored document carries model PARAMETERS, not baked tables**
    (design D5). A per-kilometre pace table for any target finish is arithmetic
    over `perKm[].factor`; adding a target needs no sync and no schema change.

`points_json` (the raw track) is the source of truth. `lens_json` is a
disposable cache keyed by COURSE_LENS_VERSION, recomputed on bump exactly like
`block_lens` and `run_metrics`.
"""
from __future__ import annotations

import json
import math

import activity_archive

# Bump to force a recompute of every stored course document.
COURSE_LENS_VERSION = 1

# Elevation smoothing half-window, in METRES of course distance (design D3 —
# a sample window would breathe with GPS point density, which varies 0.1–35 m
# on the real course).
SMOOTH_HALF_WINDOW_M = 75.0

# A course whose points carry elevation for less than this fraction is marked
# degraded: the profile is disclosed as unreliable rather than drawn as though
# it were measured (design D8).
MIN_ELEVATION_COVERAGE = 0.95

# Decisive-segment detection (design: algorithmic, never hand-listed).
SEGMENT_MIN_GRADE = 0.02        # |grade| that opens a segment
SEGMENT_MIN_GAIN_M = 15.0       # discard anything smaller than a road camber
SEGMENT_MIN_LENGTH_M = 200.0
SEGMENT_BRIDGE_M = 150.0        # flat spell tolerated inside one segment

# Calibration guardrails (design D4).
CALIB_MIN_SAMPLES = 2000        # below this the fit is not attempted
CALIB_MIN_BINS = 5
CALIB_GRADE_LIMIT = 0.25        # ignore grades beyond the curve's sane range
CALIB_MIN_SPEED_MS = 1.2        # drop walking/standing samples
CALIB_MAX_RESIDUAL = 0.12       # RMSE above this → fall back to uncalibrated


# ──────────────────────────────────────────────────────────────────────────────
# the cost curve
# ──────────────────────────────────────────────────────────────────────────────
# Minetti et al., "Energy cost of walking and running at extreme uphill and
# downhill slopes", J Appl Physiol 93:1039-1046 (2002), Eq. for running:
#
#   Cr(i) = 155.4 i^5 - 30.4 i^4 - 43.3 i^3 + 46.3 i^2 + 19.5 i + 3.6
#
# with i the gradient as a fraction and Cr in J/kg/m. Fitted over i ∈ [-0.45,
# +0.45]. We use the RATIO Cr(i)/Cr(0), which is what makes it a pace factor.
#
# The reason this curve and not a linear "+12 s/km per 1 %" rule: it is
# non-monotonic downhill. Cost falls to a minimum near i ≈ -0.20 and RISES
# again beyond it, because braking and eccentric loading start costing more
# than gravity gives back. A linear rule would price this course's -6 %
# kilometre as free speed — actively dangerous advice for a runner three weeks
# out of a tibial stress injury.
_MINETTI = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)
COST_CURVE_ID = "minetti-2002"


def cost_ratio(grade: float) -> float:
    """Relative energy cost of running at `grade` (a fraction, +0.08 = 8 % up)
    against level running. 1.0 on the flat, >1 uphill, <1 on moderate descents."""
    i = max(-0.45, min(0.45, grade))
    a, b, c, d, e, f = _MINETTI
    cr = a * i**5 + b * i**4 + c * i**3 + d * i**2 + e * i + f
    return max(cr, 0.5) / f


def pace_factor(grade: float, damping: float) -> float:
    """Pace multiplier at `grade`. `damping` scales the curve's deviation from
    flat: 1.0 is raw metabolic cost, lower means the athlete gives up less pace
    than pure energetics predict — which is what real running does, because a
    climb is run above steady-state power rather than at it (design D4)."""
    return 1.0 + damping * (cost_ratio(grade) - 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# acquisition (design D1)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_course(client, course_id: int) -> dict | None:
    """Raw course payload from Garmin's course service, or None. Never raises:
    acquisition failure must leave the stored course in place and let the sync
    finish (design D8)."""
    try:
        return client.connectapi(f"/course-service/course/{int(course_id)}")
    except Exception:  # noqa: BLE001 — an unreachable course is not a sync failure
        return None


def distill_points(raw: dict) -> dict:
    """Reshape `geoPoints` into rounded COLUMNS, the way the run distiller
    reshapes streams: one array per metric, index-aligned, nulls preserved.

    Precision mirrors `_STREAM_COLUMNS` in sync_garmin: 5 dp on lat/lon (~1 m),
    1 dp on elevation and distance. `timestamp` is dropped — a course has no
    clock, only a shape."""
    pts = raw.get("geoPoints") or []
    d, lat, lon, elev = [], [], [], []
    for p in pts:
        dist = p.get("distance")
        if dist is None:
            continue                      # a point off the distance axis is unusable
        d.append(round(float(dist), 1))
        lat.append(_round_or_none(p.get("latitude"), 5))
        lon.append(_round_or_none(p.get("longitude"), 5))
        elev.append(_round_or_none(p.get("elevation"), 1))
    cols = {"d": d, "lat": lat, "lon": lon, "elev": elev}
    cols["elevSmooth"] = smooth_elevation(d, elev)
    return cols


def _round_or_none(v, nd):
    return None if v is None else round(float(v), nd)


def elevation_coverage(points: dict) -> float:
    elev = points.get("elev") or []
    if not elev:
        return 0.0
    return sum(1 for e in elev if e is not None) / len(elev)


# ──────────────────────────────────────────────────────────────────────────────
# profile derivation (design D3)
# ──────────────────────────────────────────────────────────────────────────────
def smooth_elevation(d: list, elev: list,
                     half_window_m: float = SMOOTH_HALF_WINDOW_M) -> list:
    """Rolling mean of elevation over a DISTANCE window.

    Point spacing on the real course ranges 0.1–35 m, so a sample-count window
    would smooth aggressively where points bunch and barely at all where they
    spread. A distance window is uniform in the only dimension that matters.

    Runs in O(n) with two moving edges. Points without elevation contribute
    nothing but still receive a smoothed value from their neighbourhood, so the
    output has no holes to special-case downstream."""
    n = len(d)
    if n == 0:
        return []
    out = [None] * n
    lo = hi = 0
    run_sum, run_cnt = 0.0, 0
    for i in range(n):
        target_lo, target_hi = d[i] - half_window_m, d[i] + half_window_m
        while hi < n and d[hi] <= target_hi:
            if elev[hi] is not None:
                run_sum += elev[hi]
                run_cnt += 1
            hi += 1
        while lo < n and d[lo] < target_lo:
            if elev[lo] is not None:
                run_sum -= elev[lo]
                run_cnt -= 1
            lo += 1
        out[i] = round(run_sum / run_cnt, 2) if run_cnt else None
    return out


def per_km_profile(points: dict) -> list:
    """One row per whole kilometre: the smoothed elevation at each km mark, the
    change across it, and the mean grade. The last row is the partial kilometre
    to the finish, whose grade is over its true length — not extrapolated."""
    d, es = points["d"], points["elevSmooth"]
    if not d:
        return []
    total = d[-1]
    marks = []
    km = 0
    while True:
        target = min(km * 1000.0, total)
        idx = _nearest_index(d, target)
        marks.append((km, d[idx], es[idx]))
        if target >= total:
            break
        km += 1
    rows = []
    for j in range(1, len(marks)):
        (_, d0, e0), (kmj, d1, e1) = marks[j - 1], marks[j]
        length = d1 - d0
        if length <= 0:
            continue
        delta = None if (e0 is None or e1 is None) else e1 - e0
        rows.append({
            "km": kmj,
            "startM": round(d0, 1),
            "endM": round(d1, 1),
            "lengthM": round(length, 1),
            # The course rarely ends on a whole kilometre — Sonthofen's last
            # row is a 113 m stub. Flagged so the surface can label it "21.1"
            # instead of announcing a 22nd kilometre that does not exist.
            # The threshold is loose because km marks snap to the nearest
            # stored point, so a FULL kilometre measures 988-1017 m on the real
            # course; only a genuine stub falls under 900.
            "partial": length < 900.0,
            "elevStart": e0,
            "elevEnd": e1,
            "deltaM": None if delta is None else round(delta, 1),
            "grade": None if delta is None else round(delta / length, 5),
        })
    return rows


def _nearest_index(d: list, target: float) -> int:
    lo, hi = 0, len(d) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if d[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    if lo > 0 and abs(d[lo - 1] - target) <= abs(d[lo] - target):
        return lo - 1
    return lo


def detect_segments(points: dict) -> list:
    """Find sustained climbs and descents from the smoothed profile.

    Deliberately algorithmic (spec: "decisive segments are detected, not
    hand-listed") — the renderer must never carry "the wall is at km 13" as a
    constant, because the next race has a different shape.

    A segment opens where the local grade passes ±SEGMENT_MIN_GRADE, absorbs
    contrary stretches shorter than SEGMENT_BRIDGE_M, and survives only if it
    clears both a minimum length and a minimum elevation change."""
    d, es = points["d"], points["elevSmooth"]
    n = len(d)
    if n < 3:
        return []

    runs = []   # (sign, start_idx, end_idx)
    sign_at = []
    for i in range(1, n):
        dd = d[i] - d[i - 1]
        if dd <= 0 or es[i] is None or es[i - 1] is None:
            sign_at.append(0)
            continue
        g = (es[i] - es[i - 1]) / dd
        sign_at.append(1 if g >= SEGMENT_MIN_GRADE else
                       -1 if g <= -SEGMENT_MIN_GRADE else 0)

    cur_sign, start = 0, 0
    for i, s in enumerate(sign_at):
        if s != cur_sign:
            if cur_sign != 0:
                runs.append((cur_sign, start, i))
            cur_sign, start = s, i
    if cur_sign != 0:
        runs.append((cur_sign, start, len(sign_at)))

    merged = []
    for sign, s, e in runs:
        if merged and merged[-1][0] == sign and d[s] - d[merged[-1][2]] <= SEGMENT_BRIDGE_M:
            merged[-1][2] = e
        else:
            merged.append([sign, s, e])

    segs = []
    for sign, s, e in merged:
        i0, i1 = s, min(e, n - 1)
        length = d[i1] - d[i0]
        if es[i0] is None or es[i1] is None:
            continue
        change = es[i1] - es[i0]
        if length < SEGMENT_MIN_LENGTH_M or abs(change) < SEGMENT_MIN_GAIN_M:
            continue
        segs.append({
            "kind": "climb" if sign > 0 else "descent",
            "startM": round(d[i0], 1),
            "endM": round(d[i1], 1),
            "lengthM": round(length, 1),
            "changeM": round(change, 1),
            "grade": round(change / length, 5),
            "startKm": round(d[i0] / 1000.0, 2),
            "endKm": round(d[i1] / 1000.0, 2),
        })
    segs.sort(key=lambda s: -abs(s["changeM"]))
    return segs


def profile_totals(points: dict) -> dict:
    """Gain and loss from the SMOOTHED series. Reported beside Garmin's own
    figures rather than replacing them: Garmin says 197/200 m for this course
    where outdooractive says 143/143, so the honest presentation is a range
    with each number's source named (design: risks)."""
    es = points["elevSmooth"]
    gain = loss = 0.0
    prev = None
    for e in es:
        if e is None:
            continue
        if prev is not None:
            delta = e - prev
            if delta > 0:
                gain += delta
            else:
                loss -= delta
        prev = e
    vals = [e for e in es if e is not None]
    return {
        "gainM": round(gain, 1),
        "lossM": round(loss, 1),
        "minElevM": round(min(vals), 1) if vals else None,
        "maxElevM": round(max(vals), 1) if vals else None,
        "source": "smoothed",
    }


# ──────────────────────────────────────────────────────────────────────────────
# calibration (design D4)
# ──────────────────────────────────────────────────────────────────────────────
def calibration_observations(conn) -> list:
    """(grade, observed_ratio) pairs mined from archived runs.

    Each stored run carries `v` (directSpeed), `gap` (directGradeAdjustedSpeed)
    and `elev` per sample. Garmin's GAP answers "what flat speed would this
    effort have produced?", so `gap / v` IS the observed pace penalty at the
    local grade — hundreds of thousands of measurements of how THIS athlete
    slows down on a hill, which is exactly what the analytic curve needs
    scaling against."""
    obs = []
    rows = conn.execute(
        "SELECT detail_streams_json FROM activities "
        "WHERE detail_streams_json IS NOT NULL").fetchall()
    for (raw,) in rows:
        try:
            s = json.loads(raw)
        except Exception:  # noqa: BLE001 — a corrupt stream is skipped, not fatal
            continue
        d, v, gap, elev = s.get("d"), s.get("v"), s.get("gap"), s.get("elev")
        if not (d and v and gap and elev):
            continue
        n = min(len(d), len(v), len(gap), len(elev))
        if n < 60:
            continue
        es = smooth_elevation(d[:n], elev[:n])
        for i in range(1, n):
            vi, gi = v[i], gap[i]
            if vi is None or gi is None or vi < CALIB_MIN_SPEED_MS or gi <= 0:
                continue
            dd = d[i] - d[i - 1]
            if dd <= 1.0 or es[i] is None or es[i - 1] is None:
                continue
            grade = (es[i] - es[i - 1]) / dd
            if abs(grade) > CALIB_GRADE_LIMIT:
                continue
            obs.append((grade, gi / vi))
    return obs


def fit_damping(obs: list) -> dict:
    """Fit the ONE free parameter: `damping` in factor = 1 + k·(cost_ratio-1).

    One scalar, by design (D4). A free-form curve fit would chase GPS noise and
    produce something nobody could defend at km 13; a single scale factor cannot
    overfit, keeps the physiologically-sound shape, and is trivially testable.

    Observations are binned by grade before fitting so that the flat samples —
    which vastly outnumber the graded ones — cannot drown out the signal.
    Returns the fit plus the residual that decides whether it is trusted."""
    if len(obs) < CALIB_MIN_SAMPLES:
        return {"ok": False, "reason": "insufficient-samples", "samples": len(obs)}

    bins: dict[int, list] = {}
    for grade, ratio in obs:
        bins.setdefault(int(round(grade * 200)), []).append(ratio)   # 0.5 % bins

    pts = []
    for key, ratios in bins.items():
        if len(ratios) < 20:
            continue
        grade = key / 200.0
        ratios.sort()
        median = ratios[len(ratios) // 2]        # robust to GPS spikes
        pts.append((grade, median, len(ratios)))
    if len(pts) < CALIB_MIN_BINS:
        return {"ok": False, "reason": "insufficient-bins", "samples": len(obs),
                "bins": len(pts)}

    # Weighted least squares through the origin on (cost_ratio-1) → (observed-1).
    num = den = 0.0
    for grade, observed, weight in pts:
        x = cost_ratio(grade) - 1.0
        y = observed - 1.0
        num += weight * x * y
        den += weight * x * x
    if den <= 0:
        return {"ok": False, "reason": "degenerate-fit", "samples": len(obs)}
    k = num / den

    sq = tot = 0.0
    for grade, observed, weight in pts:
        pred = pace_factor(grade, k)
        sq += weight * (pred - observed) ** 2
        tot += weight
    residual = math.sqrt(sq / tot) if tot else None

    trusted = residual is not None and residual <= CALIB_MAX_RESIDUAL and k > 0
    return {
        "ok": bool(trusted),
        "damping": round(k, 4),
        "residual": None if residual is None else round(residual, 4),
        "samples": len(obs),
        "bins": len(pts),
        "gradeRange": [round(min(p[0] for p in pts), 4),
                       round(max(p[0] for p in pts), 4)],
        "reason": None if trusted else "residual-above-threshold",
    }


def build_model(conn) -> dict:
    """The stored pace model: curve identity, the fitted scalar, and an honest
    account of how well it fits. A weak fit falls back to the uncalibrated curve
    and SAYS so — the surface must never imply precision the data cannot carry."""
    try:
        fit = fit_damping(calibration_observations(conn))
    except Exception as ex:  # noqa: BLE001 — calibration never breaks derivation
        fit = {"ok": False, "reason": f"error:{type(ex).__name__}"}
    calibrated = bool(fit.get("ok"))
    return {
        "curve": COST_CURVE_ID,
        "calibrated": calibrated,
        "damping": fit.get("damping") if calibrated else 1.0,
        "residual": fit.get("residual"),
        "samples": fit.get("samples"),
        "bins": fit.get("bins"),
        "gradeRange": fit.get("gradeRange"),
        "fallbackReason": None if calibrated else fit.get("reason"),
    }


# ──────────────────────────────────────────────────────────────────────────────
# the document
# ──────────────────────────────────────────────────────────────────────────────
def build_lens(points: dict, model: dict, raw_totals: dict | None = None) -> dict:
    """Assemble the derived document. Pure over its inputs — no clock, no
    network, no database — which is what makes the determinism requirement
    (same course + same version → identical document) testable at all."""
    per_km = per_km_profile(points)
    damping = model.get("damping") or 1.0
    for row in per_km:
        row["factor"] = (None if row["grade"] is None
                         else round(pace_factor(row["grade"], damping), 5))

    # Flat-equivalent cost: how much longer the course takes than a flat one at
    # the same effort. Independent of target pace, so it is a property of the
    # COURSE and belongs in the document rather than in any one pace table.
    weighted = total = 0.0
    for row in per_km:
        if row["factor"] is None:
            continue
        weighted += row["factor"] * row["lengthM"]
        total += row["lengthM"]
    cost_fraction = (weighted / total - 1.0) if total else None

    # The cost of caution. A runner who declines descent benefit — for a healing
    # tibia, say — does not get the flat-course time back: the climb is still
    # paid for and the refund is waived. Target-independent, so it belongs to
    # the COURSE, and it turns "I ran the downhill slowly" from an unexplained
    # deviation into a number the athlete chose to spend.
    #
    # TWO figures, because they answer different questions. Declining EVERY
    # descent is not what an injured runner actually does — a −0.5 % kilometre
    # is run normally. `steep` therefore clamps only descents at or beyond the
    # segment threshold, and it is the honest headline: on Sonthofen it is the
    # km 14–15 drop and nothing else.
    coverage = elevation_coverage(points)
    return {
        "lensVersion": COURSE_LENS_VERSION,
        "track": downsample_track(points),
        "descentGiveawayFraction": _giveaway(per_km, weighted, 0.0),
        "steepDescentGiveawayFraction": _giveaway(per_km, weighted, -SEGMENT_MIN_GRADE),
        "steepDescentThreshold": -SEGMENT_MIN_GRADE,
        "degraded": coverage < MIN_ELEVATION_COVERAGE,
        "elevationCoverage": round(coverage, 4),
        "smoothHalfWindowM": SMOOTH_HALF_WINDOW_M,
        "totals": profile_totals(points),
        "reportedTotals": raw_totals or {},
        "perKm": per_km,
        "segments": detect_segments(points),
        "model": model,
        "elevationCostFraction": None if cost_fraction is None else round(cost_fraction, 5),
        "comparison": None,          # filled once a matching activity exists
    }


# ──────────────────────────────────────────────────────────────────────────────
# race comparison (design D6/D7) — derived HERE, at sync time
# ──────────────────────────────────────────────────────────────────────────────
# Matching an activity to a course, normalising its distance axis and resampling
# it onto the course grid is DERIVATION, not rendering: it establishes what
# happened. The ROADMAP's rule puts that in the deterministic sync, and the D5
# carve-out that lets the browser evaluate a stored cost curve does not stretch
# to cover it.
#
# What is stored is deliberately TARGET-INDEPENDENT — the seconds the athlete
# actually spent on each kilometre of the course. Deltas against a chosen target
# stay arithmetic the page performs, exactly like the pace table, so switching
# target still costs no sync.
RACE_MATCH_DISTANCE_TOL = 0.08          # ±8 % of the course distance
# Slack at the finish boundary, in metres — absorbs the centimetre-scale
# disagreement between a course's reported length and its own last point.
END_TOLERANCE_M = 5.0


def find_race_activity(conn, race_date: str, course_distance_m: float) -> tuple | None:
    """(activity_id, name, distance_m, streams) for the run that IS the race, or
    None. A shakeout on race morning must not win, so candidates are filtered by
    distance tolerance first and the closest match takes it."""
    if not race_date or not course_distance_m:
        return None
    rows = conn.execute(
        "SELECT activity_id, name, distance_m, detail_streams_json "
        "FROM activities "
        "WHERE substr(start_time_local, 1, 10) = ? AND type_key = 'running' "
        "  AND distance_m IS NOT NULL AND detail_streams_json IS NOT NULL",
        (race_date,)).fetchall()
    best = None
    for aid, name, dist, raw in rows:
        if abs(dist - course_distance_m) / course_distance_m > RACE_MATCH_DISTANCE_TOL:
            continue
        gap = abs(dist - course_distance_m)
        if best is None or gap < best[0]:
            best = (gap, aid, name, dist, raw)
    if not best:
        return None
    try:
        streams = json.loads(best[4])
    except Exception:  # noqa: BLE001 — a corrupt stream means "no comparison"
        return None
    return (best[1], best[2], best[3], streams)


def align_actual(per_km: list, streams: dict, course_distance_m: float) -> list | None:
    """Resample a run onto the course's kilometre grid.

    Pure over its inputs. The run's own distance axis is NORMALISED to the
    course total first: GPS drifts by tens of metres over 21 km, and without
    that scaling every kilometre boundary walks and a decisive kilometre's cost
    smears across two rows.

    Each row uses its OWN startM/endM — never km*1000 — because kilometre marks
    snap to stored points and the final row is a stub."""
    d, t = streams.get("d") or [], streams.get("t") or []
    n = min(len(d), len(t))
    if n < 10 or not course_distance_m:
        return None
    total = d[n - 1]
    if not total:
        return None
    scale = course_distance_m / total
    hr = streams.get("hr") or []

    def at(course_m):
        want = course_m / scale
        if want <= d[0]:
            return t[0], (hr[0] if hr else None)
        if want > d[n - 1]:
            # Sub-metre overshoot at the finish is arithmetic, not a short
            # recording: Garmin's `distanceMeter` (21114.19) and the last stored
            # point (21114.20) disagree by a centimetre on the real course, and
            # without this tolerance the normalisation pushes the final row one
            # hundredth of a metre past the axis and the finish stretch vanishes
            # from the comparison. A genuinely short run still fails the check.
            if want - d[n - 1] <= END_TOLERANCE_M:
                return t[n - 1], (hr[n - 1] if len(hr) > n - 1 else None)
            return None, None
        lo, hi = 0, n - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if d[mid] < want:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return t[0], (hr[0] if hr else None)
        d0, d1, t0, t1 = d[lo - 1], d[lo], t[lo - 1], t[lo]
        frac = 0.0 if d1 == d0 else (want - d0) / (d1 - d0)
        return t0 + (t1 - t0) * frac, (hr[lo] if lo < len(hr) else None)

    out = []
    for r in per_km:
        a0, _ = at(r["startM"])
        a1, hr1 = at(r["endM"])
        if a0 is None or a1 is None:
            continue
        out.append({"km": r["km"], "startM": r["startM"], "endM": r["endM"],
                    "grade": r["grade"], "partial": r.get("partial", False),
                    "actualSeconds": round(a1 - a0, 1),
                    "hr": hr1})
    return out or None


def build_comparison(conn, lens: dict, race_date: str | None,
                     course_distance_m: float) -> dict | None:
    """The stored race comparison: what the athlete actually spent per kilometre
    of the course. Target-independent by design — the page turns it into deltas
    against whichever target is selected."""
    if not race_date:
        return None
    match = find_race_activity(conn, race_date, course_distance_m)
    if not match:
        return None
    activity_id, name, distance_m, streams = match
    rows = align_actual(lens.get("perKm") or [], streams, course_distance_m)
    if not rows:
        return None
    return {
        "activityId": activity_id,
        "name": name,
        "activityDistanceM": round(distance_m, 1),
        "normalisedBy": round(course_distance_m / distance_m, 6),
        "totalSeconds": round(sum(r["actualSeconds"] for r in rows), 1),
        "perKm": rows,
    }


TRACK_MAX_POINTS = 320


def downsample_track(points: dict, limit: int = TRACK_MAX_POINTS) -> dict:
    """The route reduced to a drawable polyline.

    The document rides inside `garmin-data.js`, which the cockpit loads on every
    page, so shipping all 1 196 lat/lon pairs to draw a 300 px map would be rent
    nobody collects. Evenly spaced sampling keeps the shape (the endpoints are
    always retained) at a twentieth of the bytes. The FULL track stays in
    `points_json` for anything that needs it."""
    lat, lon = points.get("lat") or [], points.get("lon") or []
    n = min(len(lat), len(lon))
    if n == 0:
        return {}
    if n <= limit:
        return {"lat": lat[:n], "lon": lon[:n]}
    step = (n - 1) / (limit - 1)
    idx = sorted({int(round(i * step)) for i in range(limit)} | {0, n - 1})
    return {"lat": [lat[i] for i in idx], "lon": [lon[i] for i in idx]}


def _giveaway(per_km: list, weighted: float, threshold: float):
    """Fractional time cost of refusing descent benefit at or beyond `threshold`
    (a negative grade; 0.0 means every descent). None when the profile carries
    no usable factors."""
    if not weighted:
        return None
    declined = 0.0
    for row in per_km:
        if row["factor"] is None:
            continue
        take = row["factor"]
        if row["grade"] is not None and row["grade"] <= threshold:
            take = max(take, 1.0)
        declined += take * row["lengthM"]
    return round((declined - weighted) / weighted, 5)


def pace_table(lens: dict, target_seconds: float,
               decline_descents_steeper_than: float | None = None) -> list:
    """Per-kilometre target paces for one finish time.

    Lives here so Python tests can assert it, but it is deliberately pure
    arithmetic over the stored document (design D5) — the page performs the
    identical computation client-side, which is what lets a target be any value
    the athlete types rather than one of three baked presets.

    `decline_descents_steeper_than` prices the cost of caution: on kilometres at
    or beyond that (negative) grade, the factor is clamped to level running,
    modelling a runner who refuses free speed where it would hurt. Pass 0.0 to
    decline every descent. The target is still hit — the time simply has to come
    from somewhere else, which is exactly the trade worth seeing."""
    rows = [dict(r) for r in lens.get("perKm") or [] if r.get("factor")]
    # `not (x > 0)` rather than `x <= 0`: NaN compares False to everything, so
    # `nan <= 0` is False and a NaN target would otherwise produce a full table
    # of NaN paces. This matches course-plan.js, which guards the same way.
    if not rows or not (target_seconds > 0):
        return []
    if decline_descents_steeper_than is not None:
        for r in rows:
            if r["grade"] is not None and r["grade"] <= decline_descents_steeper_than:
                r["factor"] = max(r["factor"], 1.0)
    weighted = sum(r["factor"] * r["lengthM"] for r in rows)
    if not (weighted > 0):
        return []                             # a degenerate profile, not a crash
    base = target_seconds / weighted          # flat-equivalent seconds per metre
    out, elapsed = [], 0.0
    for r in rows:
        secs = base * r["factor"] * r["lengthM"]
        elapsed += secs
        out.append({
            "km": r["km"],
            # The row's REAL span, carried through. `km` is a label: kilometre
            # marks snap to the nearest stored point, so km 1 can end at 991 m,
            # and the final row is a stub whose label (22) times 1000 is far
            # past the finish. Anything reconstructing bounds from the label
            # drifts by metres and drops the stub entirely.
            "startM": r["startM"],
            "endM": r["endM"],
            "partial": r.get("partial", False),
            "grade": r["grade"],
            "lengthM": r["lengthM"],
            "paceSecPerKm": round(base * r["factor"] * 1000.0, 1),
            "secondsForKm": round(secs, 1),
            "cumulativeSeconds": round(elapsed, 1),
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# the sync driver
# ──────────────────────────────────────────────────────────────────────────────
def course_step(conn, client, race: dict | None, log=print) -> dict | None:
    """Acquire (if needed) and derive the course named by `race.courseId`.

    Skips the fetch when the stored copy's update stamp matches and the lens is
    already at the current version; re-derives without re-fetching when only the
    version moved; leaves everything untouched when Garmin is unreachable. Never
    raises — a course problem is not a sync failure (design D8)."""
    course_id = (race or {}).get("courseId")
    if not course_id:
        return None                              # feature is opt-in and dark by default

    stored = activity_archive.course_row(conn, course_id)
    raw = fetch_course(client, course_id) if client else None

    if raw is None:
        if stored is None:
            log("  course     : unavailable and none stored — skipped")
            return None
        if stored[1] == COURSE_LENS_VERSION:
            return activity_archive.course_document(conn, course_id)
        points = activity_archive.course_points(conn, course_id)
        if not points:
            return None
        log("  course     : offline — re-deriving stored points at the new version")
        return _derive_and_store(conn, course_id, None, points, stored[2],
                                 (race or {}).get("date"))

    remote_update = raw.get("updateDate")
    if stored and stored[0] == remote_update and stored[1] == COURSE_LENS_VERSION:
        return activity_archive.course_document(conn, course_id)

    points = distill_points(raw)
    if not points["d"]:
        log("  course     : payload carried no usable geo points — skipped")
        return None
    # `fetched_at` means "when did we last talk to Garmin about this course".
    # We just did — so it must be stamped fresh. Carrying the stored value
    # forward here (as the offline branch legitimately does, where no fetch
    # happened) would freeze the column at the first-ever sync and make any
    # staleness check report a course as unchecked while it is re-fetched
    # nightly.
    return _derive_and_store(conn, course_id, raw, points, None,
                             (race or {}).get("date"))


def _derive_and_store(conn, course_id: int, raw: dict | None, points: dict,
                      fetched_at: str | None, race_date: str | None = None) -> dict:
    model = build_model(conn)
    raw_totals = {}
    if raw:
        raw_totals = {"gainM": raw.get("elevationGainMeter"),
                      "lossM": raw.get("elevationLossMeter"),
                      "source": "garmin"}
    lens = build_lens(points, model, raw_totals)
    # The comparison is derived HERE, not in the browser (design D6): matching,
    # normalising and resampling establish what happened, which is the sync's
    # job. It stays target-independent so switching target needs no re-derive.
    try:
        lens["comparison"] = build_comparison(
            conn, lens, race_date,
            float(raw.get("distanceMeter") or 0) if raw
            else float(points["d"][-1] if points.get("d") else 0))
    except Exception:  # noqa: BLE001 — no comparison is a normal state
        lens["comparison"] = None

    if raw:
        name = raw.get("courseName") or f"course {course_id}"
        distance = float(raw.get("distanceMeter") or (points["d"][-1] if points["d"] else 0))
        bbox = raw.get("boundingBox") or {}
        update_date = raw.get("updateDate")
        gain, loss = raw.get("elevationGainMeter"), raw.get("elevationLossMeter")
    else:
        prev = activity_archive.course_document(conn, course_id) or {}
        name = prev.get("courseName") or f"course {course_id}"
        distance = prev.get("distanceM") or (points["d"][-1] if points["d"] else 0)
        bbox = prev.get("bbox") or {}
        update_date = prev.get("updateDate")
        gain, loss = prev.get("gainM"), prev.get("lossM")

    # race_date is what `course_coverage()` reports as "latest race" and what
    # the archive API promotes to `raceDate`; sourcing it from the plan's race
    # mirrors how block_lens keys its rows. Preserved on an offline re-derive so
    # a lens-only recompute never blanks it.
    if race_date is None:
        prev_row = conn.execute("SELECT race_date FROM courses WHERE course_id = ?",
                                (course_id,)).fetchone()
        race_date = prev_row[0] if prev_row else None
    activity_archive.upsert_course(
        conn, course_id, name, race_date, distance, gain, loss, bbox, points,
        COURSE_LENS_VERSION, lens, update_date, fetched_at)
    return activity_archive.course_document(conn, course_id)


def course_map_step(conn, course_id: int, log=print) -> str:
    """Fetch the course's basemap tiles, reusing route-basemap's policy and
    throttle wholesale. Separated from derivation so a tile-server outage costs
    the map and nothing else — the profile and the pace plan never depend on
    it (design D8)."""
    points = activity_archive.course_points(conn, course_id)
    if not points:
        return "skipped"
    try:
        status = activity_archive.ensure_course_map(conn, course_id, points)
    except Exception as ex:  # noqa: BLE001 — the map is the least of the page
        log(f"  course map : failed ({type(ex).__name__})")
        return "failed"
    if status == "done":
        log("  course map : basemap tiles complete")
    elif status == "failed":
        log("  course map : tile fetch incomplete — the profile renders without it")
    return status
