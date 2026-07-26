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

    def test_degenerate_targets_are_refused_not_divided_by(self):
        self.assertEqual(cl.pace_table(self.lens, 0), [])
        self.assertEqual(cl.pace_table(self.lens, -5), [])
        self.assertEqual(cl.pace_table({"perKm": []}, 7199), [])


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

    def test_payload_without_geo_points_is_refused(self):
        conn = self._conn()
        self.assertIsNone(cl.course_step(conn, self._Client({"courseName": "x", "geoPoints": []}),
                                         {"courseId": 1}, log=lambda *_: None))
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
