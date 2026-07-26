#!/usr/bin/env python3
"""Tests for the course-lens engine (add-course-lens).

The oracle is the REAL race course — Garmin course 493447940, 1 196 points,
captured to fixtures/course/sonthofen-hm-2026.json. Asserting against a
synthetic profile would prove the arithmetic and miss the thing that actually
bit: a summary-statistics read that put the climb in the wrong place.
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

import activity_archive
import course_lens as cl

FIXTURE = Path(__file__).parent / "fixtures" / "course" / "sonthofen-hm-2026.json"


def load_raw() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class CostCurveTests(unittest.TestCase):
    def test_flat_is_unity(self):
        self.assertAlmostEqual(cl.cost_ratio(0.0), 1.0, places=6)

    def test_uphill_costs_more(self):
        self.assertGreater(cl.cost_ratio(0.08), cl.cost_ratio(0.04))
        self.assertGreater(cl.cost_ratio(0.04), cl.cost_ratio(0.0))

    def test_descent_reverses(self):
        """The whole reason for a polynomial rather than a linear rule: cost
        bottoms out and RISES again on steep descents. A linear model would
        price this course's -6 % kilometre as free speed."""
        moderate = cl.cost_ratio(-0.20)
        extreme = cl.cost_ratio(-0.40)
        self.assertLess(moderate, 1.0)
        self.assertGreater(extreme, moderate)

    def test_damping_scales_deviation_only(self):
        self.assertAlmostEqual(cl.pace_factor(0.0, 0.33), 1.0, places=6)
        raw = cl.cost_ratio(0.08) - 1.0
        self.assertAlmostEqual(cl.pace_factor(0.08, 0.5) - 1.0, raw * 0.5, places=6)

    def test_extreme_grades_are_clamped_not_exploded(self):
        for g in (-3.0, 3.0):
            self.assertTrue(0.0 < cl.cost_ratio(g) < 10.0)


class SmoothingTests(unittest.TestCase):
    def test_window_is_distance_not_samples(self):
        """Points bunched at one end must not be smoothed harder than points
        spread at the other — the real course spans 0.1-35 m spacing."""
        d = [0, 1, 2, 3, 4, 500, 1000, 1500]
        elev = [100, 200, 100, 200, 100, 150, 150, 150]
        out = cl.smooth_elevation(d, elev, half_window_m=10)
        # The bunched cluster averages toward its own mean...
        self.assertTrue(all(120 < v < 180 for v in out[:5]), out[:5])
        # ...while the isolated points keep their own value.
        self.assertAlmostEqual(out[6], 150.0, places=3)

    def test_missing_elevation_leaves_no_holes(self):
        d = [0, 50, 100, 150, 200]
        elev = [100, None, None, None, 110]
        out = cl.smooth_elevation(d, elev, half_window_m=100)
        self.assertTrue(all(v is not None for v in out), out)

    def test_all_missing_yields_all_none(self):
        out = cl.smooth_elevation([0, 10, 20], [None, None, None])
        self.assertEqual(out, [None, None, None])

    def test_empty_input(self):
        self.assertEqual(cl.smooth_elevation([], []), [])


class RealCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = load_raw()
        cls.points = cl.distill_points(cls.raw)
        cls.lens = cl.build_lens(
            cls.points,
            {"curve": cl.COST_CURVE_ID, "calibrated": False, "damping": 1.0},
            {"gainM": cls.raw.get("elevationGainMeter"),
             "lossM": cls.raw.get("elevationLossMeter"), "source": "garmin"})

    def test_distillation_keeps_every_usable_point(self):
        self.assertEqual(len(self.points["d"]), 1196)
        for col in ("lat", "lon", "elev", "elevSmooth"):
            self.assertEqual(len(self.points[col]), 1196, col)

    def test_distance_axis_is_monotonic(self):
        d = self.points["d"]
        self.assertTrue(all(d[i] <= d[i + 1] for i in range(len(d) - 1)))
        self.assertAlmostEqual(d[-1], 21114.2, places=1)

    def test_elevation_coverage_is_complete(self):
        self.assertAlmostEqual(cl.elevation_coverage(self.points), 1.0, places=6)
        self.assertFalse(self.lens["degraded"])

    def test_the_wall_is_found_at_km_12_to_13(self):
        """The finding that started this change: the climb is at km 12->13, NOT
        km 15-17 where a summary-stats read put it."""
        climbs = [s for s in self.lens["segments"] if s["kind"] == "climb"]
        self.assertTrue(climbs, "no climb detected on a course with a 82 m wall")
        wall = max(climbs, key=lambda s: s["changeM"])
        self.assertLess(wall["startKm"], 13.0)
        self.assertGreater(wall["endKm"], 12.5)
        self.assertGreater(wall["changeM"], 80.0)
        self.assertGreater(wall["grade"], 0.05)

    def test_the_descent_is_found_after_the_wall(self):
        descents = [s for s in self.lens["segments"] if s["kind"] == "descent"]
        self.assertTrue(descents)
        steepest = min(descents, key=lambda s: s["grade"])
        self.assertGreater(steepest["startKm"], 13.0)
        self.assertLess(steepest["endKm"], 16.0)
        self.assertLess(steepest["grade"], -0.05)

    def test_first_twelve_km_are_effectively_flat(self):
        early = [r for r in self.lens["perKm"] if r["km"] <= 12]
        self.assertAlmostEqual(sum(r["deltaM"] for r in early), 44.0, delta=15.0)
        self.assertTrue(all(abs(r["grade"]) < 0.02 for r in early),
                        [(r["km"], r["grade"]) for r in early])

    def test_per_km_rows_cover_the_whole_course(self):
        rows = self.lens["perKm"]
        self.assertAlmostEqual(sum(r["lengthM"] for r in rows), 21114.2, delta=1.0)
        self.assertTrue(rows[-1]["partial"], "the 114 m stub must be flagged partial")
        self.assertFalse(rows[0]["partial"])

    def test_totals_are_reported_beside_garmins_not_instead_of_them(self):
        """Garmin says 197/200 m, outdooractive says 143/143. The document must
        carry both its own figure and the source's, never silently pick one."""
        self.assertIn("gainM", self.lens["totals"])
        self.assertEqual(self.lens["totals"]["source"], "smoothed")
        self.assertEqual(self.lens["reportedTotals"]["source"], "garmin")
        self.assertAlmostEqual(self.lens["reportedTotals"]["gainM"], 197.43, places=2)

    def test_smoothing_reduces_gain_without_destroying_it(self):
        smoothed = self.lens["totals"]["gainM"]
        self.assertLess(smoothed, 260.0)
        self.assertGreater(smoothed, 140.0)

    def test_determinism(self):
        """Same course + same version -> identical document (spec requirement,
        mirroring route-basemap's tile-rect determinism)."""
        again = cl.build_lens(
            cl.distill_points(load_raw()),
            {"curve": cl.COST_CURVE_ID, "calibrated": False, "damping": 1.0},
            {"gainM": self.raw.get("elevationGainMeter"),
             "lossM": self.raw.get("elevationLossMeter"), "source": "garmin"})
        self.assertEqual(json.dumps(again, sort_keys=True),
                         json.dumps(self.lens, sort_keys=True))


class PaceTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pts = cl.distill_points(load_raw())
        cls.lens = cl.build_lens(
            pts, {"curve": cl.COST_CURVE_ID, "calibrated": True, "damping": 0.33}, {})

    def test_table_hits_its_target(self):
        for target in (7199, 7308, 8068):
            table = cl.pace_table(self.lens, target)
            self.assertAlmostEqual(table[-1]["cumulativeSeconds"], target, delta=1.0)

    def test_the_wall_kilometre_is_the_slowest(self):
        table = cl.pace_table(self.lens, 7199)
        wall = max(table, key=lambda r: r["paceSecPerKm"])
        self.assertEqual(wall["km"], 13)

    def test_descent_kilometres_are_faster_than_flat_ones(self):
        table = {r["km"]: r for r in cl.pace_table(self.lens, 7199)}
        self.assertLess(table[15]["paceSecPerKm"], table[5]["paceSecPerKm"])

    def test_any_target_works_without_a_pipeline_change(self):
        """Design D5: parameters, not baked tables. An arbitrary target is just
        arithmetic over the stored document."""
        table = cl.pace_table(self.lens, 7777)
        self.assertAlmostEqual(table[-1]["cumulativeSeconds"], 7777, delta=1.0)

    def test_declining_the_descent_has_a_price(self):
        """The cost of caution: refusing downhill speed does not refund the
        climb, so the same target demands faster running everywhere else."""
        optimal = cl.pace_table(self.lens, 7199)
        declined = cl.pace_table(self.lens, 7199, decline_descents_steeper_than=-0.02)
        self.assertAlmostEqual(declined[-1]["cumulativeSeconds"], 7199, delta=1.0)
        by_km = {r["km"]: r for r in optimal}
        dec_km = {r["km"]: r for r in declined}
        # the -6.1 % kilometre is no longer run faster than level
        self.assertLess(by_km[15]["paceSecPerKm"], dec_km[15]["paceSecPerKm"])
        # ...and the flat kilometres must speed up to still hit the target
        self.assertLess(dec_km[5]["paceSecPerKm"], by_km[5]["paceSecPerKm"])

    def test_giveaway_is_reported_at_two_thresholds(self):
        """Declining EVERY descent is not what an injured runner does — the
        gently-downhill last 6 km are run normally. The steep figure is the
        honest headline; the all-descents figure is strictly larger."""
        steep = self.lens["steepDescentGiveawayFraction"]
        every = self.lens["descentGiveawayFraction"]
        self.assertIsNotNone(steep)
        self.assertGreater(every, steep, "declining more descent must cost more")
        # on this course: ~56 s steep, ~74 s if every descent is refused
        self.assertAlmostEqual(steep * 7199, 56.0, delta=8.0)
        self.assertAlmostEqual(every * 7199, 74.0, delta=10.0)
        self.assertAlmostEqual(self.lens["steepDescentThreshold"], -0.02, places=6)

    def test_a_flat_course_prices_caution_at_nothing(self):
        flat = cl.build_lens(
            {"d": [0, 1000, 2000], "lat": [0, 0, 0], "lon": [0, 0, 0],
             "elev": [10, 10, 10], "elevSmooth": [10, 10, 10]},
            {"damping": 0.33}, {})
        self.assertAlmostEqual(flat["descentGiveawayFraction"], 0.0, places=6)
        self.assertAlmostEqual(flat["steepDescentGiveawayFraction"], 0.0, places=6)

    def test_rows_carry_their_real_span_not_just_a_label(self):
        """`km` is a LABEL. Marks snap to stored points, so km 1 ends at 991 m,
        and the final row is a 113 m stub labelled 22 — reconstructing bounds
        as km*1000 drifts by metres and puts the stub past the finish."""
        table = cl.pace_table(self.lens, 7199)
        for r in table:
            self.assertIn("startM", r)
            self.assertIn("endM", r)
            self.assertAlmostEqual(r["endM"] - r["startM"], r["lengthM"], places=1)
        self.assertAlmostEqual(table[0]["startM"], 0.0, places=1)
        self.assertAlmostEqual(table[-1]["endM"], 21114.2, places=1)
        self.assertTrue(table[-1]["partial"])
        # the failure this guards: the label times 1000 is past the finish
        self.assertGreater(table[-1]["km"] * 1000, table[-1]["endM"])

    def test_degenerate_targets_are_refused_not_divided_by(self):
        self.assertEqual(cl.pace_table(self.lens, 0), [])
        self.assertEqual(cl.pace_table(self.lens, -5), [])
        self.assertEqual(cl.pace_table({"perKm": []}, 7199), [])


class ParityOracleTests(unittest.TestCase):
    """The other half of the JS-mirrors-Python contract.

    `course-plan.js` reimplements `pace_table()` so the browser can price any
    target without a sync. test_course_parity.mjs asserts the JS matches
    fixtures/course/sonthofen-pace-tables.json; this asserts PYTHON still does
    too. Without both, the oracle could drift with one implementation and the
    'pinned to each other' claim would quietly become false."""

    def test_python_still_matches_the_shared_oracle(self):
        oracle = json.loads(
            (Path(__file__).parent / "fixtures" / "course" /
             "sonthofen-pace-tables.json").read_text(encoding="utf-8"))
        lens = json.loads(
            (Path(__file__).parent / "fixtures" / "course" /
             "sonthofen-lens.json").read_text(encoding="utf-8"))
        for case in oracle["cases"]:
            got = cl.pace_table(lens, case["target"], case["decline"])
            self.assertEqual(len(got), len(case["rows"]),
                             f"row count for target={case['target']}")
            for i, (a, b) in enumerate(zip(got, case["rows"])):
                self.assertEqual(a, b,
                                 f"target={case['target']} decline={case['decline']} row {i}")


class CalibrationTests(unittest.TestCase):
    def test_insufficient_samples_is_disclosed_not_guessed(self):
        fit = cl.fit_damping([(0.05, 1.2)] * 10)
        self.assertFalse(fit["ok"])
        self.assertEqual(fit["reason"], "insufficient-samples")

    def test_a_clean_synthetic_athlete_is_recovered(self):
        """Generate observations from a known damping and check the fit finds
        it — the fit must be right before its output is trusted anywhere."""
        truth = 0.4
        obs = []
        for step in range(-20, 21):
            grade = step / 200.0
            for _ in range(60):
                obs.append((grade, cl.pace_factor(grade, truth)))
        fit = cl.fit_damping(obs)
        self.assertTrue(fit["ok"], fit)
        self.assertAlmostEqual(fit["damping"], truth, places=2)
        self.assertLess(fit["residual"], 0.01)

    def test_model_falls_back_when_the_archive_is_empty(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(activity_archive.SCHEMA_SQL)
        model = cl.build_model(conn)
        self.assertFalse(model["calibrated"])
        self.assertEqual(model["damping"], 1.0)
        self.assertIsNotNone(model["fallbackReason"])
        conn.close()


class AcquisitionTests(unittest.TestCase):
    class _Client:
        def __init__(self, payload=None, boom=False):
            self.payload, self.boom, self.calls = payload, boom, 0

        def connectapi(self, path):
            self.calls += 1
            if self.boom:
                raise RuntimeError("garmin is having a day")
            return self.payload

    def _conn(self):
        conn = sqlite3.connect(":memory:")
        for script in (activity_archive.SCHEMA_SQL, activity_archive.SCHEMA_V2_SQL,
                       activity_archive.SCHEMA_V3_SQL, activity_archive.SCHEMA_V8_SQL,
                       activity_archive.SCHEMA_V9_SQL, activity_archive.SCHEMA_V10_SQL):
            conn.executescript(script)
        return conn

    def test_no_course_id_is_a_silent_no_op(self):
        conn = self._conn()
        client = self._Client(load_raw())
        self.assertIsNone(cl.course_step(conn, client, {"name": "R"}, log=lambda *_: None))
        self.assertEqual(client.calls, 0, "must not call Garmin without a courseId")
        conn.close()

    def test_first_sync_stores_and_derives(self):
        conn = self._conn()
        raw = load_raw()
        doc = cl.course_step(conn, self._Client(raw), {"courseId": 493447940},
                             log=lambda *_: None)
        self.assertIsNotNone(doc)
        self.assertEqual(doc["courseId"], 493447940)
        self.assertTrue(doc["perKm"])
        self.assertTrue(doc["segments"])
        conn.close()

    def test_unchanged_update_stamp_skips_rederivation(self):
        conn = self._conn()
        raw = load_raw()
        cl.course_step(conn, self._Client(raw), {"courseId": 493447940}, log=lambda *_: None)
        before = activity_archive.course_document(conn, 493447940)["updatedAt"]
        client = self._Client(raw)
        cl.course_step(conn, client, {"courseId": 493447940}, log=lambda *_: None)
        after = activity_archive.course_document(conn, 493447940)["updatedAt"]
        self.assertEqual(before, after, "an unchanged course must not be rewritten")
        conn.close()

    def test_offline_keeps_the_stored_course(self):
        conn = self._conn()
        cl.course_step(conn, self._Client(load_raw()), {"courseId": 493447940},
                       log=lambda *_: None)
        doc = cl.course_step(conn, self._Client(boom=True), {"courseId": 493447940},
                             log=lambda *_: None)
        self.assertIsNotNone(doc, "a failed fetch must serve the stored copy")
        self.assertTrue(doc["perKm"])
        conn.close()

    def test_failure_with_nothing_stored_is_survivable(self):
        conn = self._conn()
        self.assertIsNone(cl.course_step(conn, self._Client(boom=True),
                                         {"courseId": 493447940}, log=lambda *_: None))
        conn.close()

    def test_a_live_refetch_stamps_fetched_at_fresh(self):
        """`fetched_at` means 'when did we last talk to Garmin'. Carrying the
        stored value through a branch where a fetch DID happen freezes it at
        the first-ever sync, so staleness checks report a course as unchecked
        while it is in fact re-fetched nightly."""
        conn = self._conn()
        raw = load_raw()
        cl.course_step(conn, self._Client(raw), {"courseId": 493447940}, log=lambda *_: None)
        # backdate the stored row far enough that any fresh stamp differs
        conn.execute("UPDATE courses SET fetched_at = ?, update_date = ? "
                     "WHERE course_id = ?",
                     ("2020-01-01T00:00:00+00:00", "old-stamp", 493447940))
        conn.commit()
        changed = dict(raw)
        changed["updateDate"] = "2026-07-27T09:00:00.0"   # edited on Garmin
        cl.course_step(conn, self._Client(changed), {"courseId": 493447940},
                       log=lambda *_: None)
        fetched_at = conn.execute(
            "SELECT fetched_at FROM courses WHERE course_id = ?",
            (493447940,)).fetchone()[0]
        self.assertNotEqual(fetched_at, "2020-01-01T00:00:00+00:00",
                            "a real fetch must move fetched_at")
        conn.close()

    def test_an_offline_rederive_preserves_fetched_at(self):
        """The mirror of the above: no fetch happened, so the stamp must NOT
        move — that is the branch the preservation logic exists for."""
        conn = self._conn()
        cl.course_step(conn, self._Client(load_raw()), {"courseId": 493447940},
                       log=lambda *_: None)
        conn.execute("UPDATE courses SET fetched_at = ?, lens_version = 0 "
                     "WHERE course_id = ?",
                     ("2020-01-01T00:00:00+00:00", 493447940))
        conn.commit()
        cl.course_step(conn, self._Client(boom=True), {"courseId": 493447940},
                       log=lambda *_: None)
        fetched_at = conn.execute(
            "SELECT fetched_at FROM courses WHERE course_id = ?",
            (493447940,)).fetchone()[0]
        self.assertEqual(fetched_at, "2020-01-01T00:00:00+00:00",
                         "an offline re-derive must not claim a fetch happened")
        conn.close()

    def test_payload_without_geo_points_is_refused(self):
        conn = self._conn()
        self.assertIsNone(cl.course_step(conn, self._Client({"courseName": "x", "geoPoints": []}),
                                         {"courseId": 1}, log=lambda *_: None))
        conn.close()


class TrackTests(unittest.TestCase):
    def test_track_is_downsampled_but_keeps_its_endpoints(self):
        points = cl.distill_points(load_raw())
        track = cl.downsample_track(points)
        self.assertLessEqual(len(track["lat"]), cl.TRACK_MAX_POINTS + 2)
        self.assertGreater(len(track["lat"]), 100)
        self.assertEqual(track["lat"][0], points["lat"][0])
        self.assertEqual(track["lat"][-1], points["lat"][-1])
        self.assertEqual(len(track["lat"]), len(track["lon"]))

    def test_a_short_track_is_returned_whole(self):
        pts = {"lat": [1.0, 2.0], "lon": [3.0, 4.0]}
        self.assertEqual(cl.downsample_track(pts), {"lat": [1.0, 2.0], "lon": [3.0, 4.0]})

    def test_an_empty_track_is_empty_not_an_error(self):
        self.assertEqual(cl.downsample_track({"lat": [], "lon": []}), {})

    def test_the_document_stays_small_enough_to_ship_statically(self):
        """It rides inside garmin-data.js, which the cockpit loads every time."""
        points = cl.distill_points(load_raw())
        lens = cl.build_lens(points, {"damping": 0.33}, {})
        self.assertLess(len(json.dumps(lens)) / 1024, 40.0)


class CourseMapTests(unittest.TestCase):
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        for s in (activity_archive.SCHEMA_SQL, activity_archive.SCHEMA_V8_SQL,
                  activity_archive.SCHEMA_V10_SQL):
            conn.executescript(s)
        return conn

    def test_tiles_are_fetched_once_and_the_row_lands_complete(self):
        conn = self._conn()
        points = cl.distill_points(load_raw())
        calls = []

        def fake_fetch(z, x, y):
            calls.append((z, x, y))
            return b"PNG" + bytes([z, x % 256, y % 256])

        status = activity_archive.ensure_course_map(
            conn, 493447940, points, fetch=fake_fetch, _sleep=lambda *_: None)
        self.assertEqual(status, "done")
        self.assertTrue(calls)
        row = activity_archive.course_map_row(conn, 493447940)
        self.assertIsNotNone(row)
        self.assertIn("cropSize", row)
        # a second pass is a no-op: the rect already exists
        again = activity_archive.ensure_course_map(
            conn, 493447940, points, fetch=fake_fetch, _sleep=lambda *_: None)
        self.assertEqual(again, "exists")
        conn.close()

    def test_a_failed_tile_writes_no_row(self):
        conn = self._conn()
        points = cl.distill_points(load_raw())
        status = activity_archive.ensure_course_map(
            conn, 1, points, fetch=lambda *_: None, _sleep=lambda *_: None)
        self.assertEqual(status, "failed")
        self.assertIsNone(activity_archive.course_map_row(conn, 1))
        conn.close()

    def test_a_course_without_gps_is_skipped(self):
        conn = self._conn()
        status = activity_archive.ensure_course_map(
            conn, 2, {"lat": [], "lon": []}, fetch=lambda *_: b"x", _sleep=lambda *_: None)
        self.assertEqual(status, "skipped")
        conn.close()


class RaceComparisonTests(unittest.TestCase):
    """The comparison is DERIVED HERE, not in the browser — matching,
    normalising and resampling establish what happened, which is the sync's
    job (design D6)."""

    @classmethod
    def setUpClass(cls):
        raw = load_raw()
        cls.points = cl.distill_points(raw)
        cls.lens = cl.build_lens(cls.points, {"damping": 0.33}, {})
        cls.total = raw["distanceMeter"]

    def _streams_on_plan(self, target=7199, penalty_km=None, penalty_s=0,
                         drift_m=0):
        """A synthetic race built FROM the plan, so any delta the comparison
        reports is one this test deliberately introduced."""
        plan = cl.pace_table(self.lens, target, -0.02)
        actual_total = self.total + drift_m
        scale = actual_total / self.total
        d, t = [0.0], [0.0]
        elapsed = 0.0
        for r in plan:
            elapsed += r["secondsForKm"] + (penalty_s if r["km"] == penalty_km else 0)
            d.append(round(r["endM"] * scale, 1))
            t.append(round(elapsed, 1))
        return {"d": d, "t": t, "hr": [160] * len(d)}, plan

    def test_alignment_recovers_the_plan_it_was_built_from(self):
        streams, plan = self._streams_on_plan()
        rows = cl.align_actual(self.lens["perKm"], streams, self.total)
        self.assertEqual(len(rows), len(plan))
        for r, p in zip(rows, plan):
            self.assertAlmostEqual(r["actualSeconds"], p["secondsForKm"], delta=1.0,
                                   msg=f"km {r['km']}")

    def test_gps_drift_is_normalised_away(self):
        """A 64 m error over 21 km must not walk the kilometre boundaries."""
        streams, plan = self._streams_on_plan(drift_m=-64)
        rows = cl.align_actual(self.lens["perKm"], streams, self.total)
        for r, p in zip(rows, plan):
            self.assertAlmostEqual(r["actualSeconds"], p["secondsForKm"], delta=1.5,
                                   msg=f"km {r['km']} drifted")

    def test_a_penalty_lands_on_the_kilometre_that_earned_it(self):
        streams, _ = self._streams_on_plan(penalty_km=13, penalty_s=30)
        rows = {r["km"]: r for r in cl.align_actual(self.lens["perKm"], streams, self.total)}
        plan = {r["km"]: r for r in cl.pace_table(self.lens, 7199, -0.02)}
        self.assertAlmostEqual(rows[13]["actualSeconds"] - plan[13]["secondsForKm"],
                               30, delta=2)
        self.assertAlmostEqual(rows[5]["actualSeconds"] - plan[5]["secondsForKm"],
                               0, delta=2)

    def test_the_finish_stub_is_included(self):
        """The row whose label (22) times 1000 overshoots the course — the one
        a km*1000 reconstruction silently drops."""
        streams, _ = self._streams_on_plan()
        rows = cl.align_actual(self.lens["perKm"], streams, self.total)
        self.assertTrue(rows[-1]["partial"])
        self.assertAlmostEqual(rows[-1]["endM"], self.total, places=1)
        covered = rows[-1]["endM"] - rows[0]["startM"]
        self.assertAlmostEqual(covered, self.total, delta=1.0,
                               msg="the comparison must cover the whole course")

    def test_a_short_recording_yields_no_row_it_cannot_support(self):
        streams = {"d": [i * 100 for i in range(50)], "t": [i * 30 for i in range(50)]}
        rows = cl.align_actual(self.lens["perKm"], streams, self.total)
        # a 4.9 km recording normalised over a 21 km course still covers it,
        # but a stream too short to interpolate at all yields nothing
        self.assertTrue(rows is None or len(rows) <= len(self.lens["perKm"]))
        self.assertIsNone(cl.align_actual(self.lens["perKm"], {"d": [0], "t": [0]}, self.total))

    def test_the_shakeout_does_not_win_the_race(self):
        conn = self._archive()
        streams, _ = self._streams_on_plan()
        ins = ("INSERT INTO activities (activity_id, start_time_local, type_key, name, "
               "distance_m, duration_s, summary_json, detail_streams_json, "
               "first_seen_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)")
        conn.execute(ins, (1, "2026-08-09 07:00:00", "running", "Shakeout",
                           2000, 700, "{}", json.dumps({"d": [0, 2000], "t": [0, 700]}), "x", "x"))
        conn.execute(ins, (2, "2026-08-09 09:15:00", "running", "The Race",
                           self.total - 60, streams["t"][-1], "{}", json.dumps(streams), "x", "x"))
        conn.commit()
        match = cl.find_race_activity(conn, "2026-08-09", self.total)
        self.assertIsNotNone(match)
        self.assertEqual(match[1], "The Race")
        cmp = cl.build_comparison(conn, self.lens, "2026-08-09", self.total)
        self.assertEqual(cmp["activityId"], 2)
        self.assertEqual(len(cmp["perKm"]), len(self.lens["perKm"]))
        conn.close()

    def _archive(self):
        """detail_streams_json arrives with the v6 migration, not the base
        schema — an in-memory archive must apply it like a real one does."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(activity_archive.SCHEMA_SQL)
        activity_archive._apply_schema_v6(conn)
        return conn

    def test_no_activity_means_no_comparison_not_an_error(self):
        conn = self._archive()
        self.assertIsNone(cl.build_comparison(conn, self.lens, "2026-08-09", self.total))
        self.assertIsNone(cl.build_comparison(conn, self.lens, None, self.total))
        conn.close()


class DegradedElevationTests(unittest.TestCase):
    def test_sparse_elevation_marks_the_profile_degraded(self):
        raw = load_raw()
        for i, p in enumerate(raw["geoPoints"]):
            if i % 3:
                p["elevation"] = None
        points = cl.distill_points(raw)
        lens = cl.build_lens(points, {"damping": 1.0}, {})
        self.assertTrue(lens["degraded"])
        self.assertLess(lens["elevationCoverage"], cl.MIN_ELEVATION_COVERAGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
