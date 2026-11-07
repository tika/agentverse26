"""Stage-1 contract tests. Run: python -m unittest discover -s perception/tests -v"""
import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "perception"), str(ROOT / "sim")]
import contracts as c  # noqa: E402

POSE = {"frame": "world", "xyz_m": [1.0, 6.0, 0.6], "yaw_rad": 0.0}


def rate(t, value, validity="valid", **kw):
    m = {"contract_version": c.CONTRACT_VERSION, "sensor_id": "robot.gamma.0", "kind": "gamma_dose_rate",
         "source": "robot", "timestamp_s": t, "units": "uSv/h", "value": value, "pose": POSE,
         "sample_age_s": 0.0, "validity": validity, "uncertainty": {"std": 0.1 * (value or 0)},
         "status": "ok", "saturation_limit": 10_000.0}
    m.update(kw)
    return m


def cumulative(t, value, method="left_rectangle"):
    return {"contract_version": c.CONTRACT_VERSION, "sensor_id": "robot.gamma.0.cum",
            "kind": "cumulative_dose", "source": "robot", "timestamp_s": t, "units": "uSv",
            "value": value, "pose": POSE, "sample_age_s": 0.0, "validity": "valid",
            "uncertainty": {"std": 0.0}, "status": "ok", "integration_method": method,
            "simulated_proxy": True}


class DoseIntegration(unittest.TestCase):
    def test_left_rectangle_matches_prompt_formula(self):
        # 36 uSv/h for 100 s = 1 uSv; then 72 uSv/h for 50 s = 1 uSv.
        out = c.integrate_dose_uSv([(0, 36.0), (100, 72.0), (150, 0.0)])
        self.assertEqual(out[0], 0.0)
        self.assertAlmostEqual(out[1], 1.0)
        self.assertAlmostEqual(out[2], 2.0)

    def test_trapezoid(self):
        out = c.integrate_dose_uSv([(0, 0.0), (3600, 10.0)], "trapezoid")
        self.assertAlmostEqual(out[1], 5.0)

    def test_rejects_non_monotonic_and_bad_values(self):
        for bad in ([(0, 1.0), (0, 1.0)], [(5, 1.0), (4, 1.0)], [(0, -1.0)], [(0, math.nan)]):
            with self.assertRaises(ValueError):
                c.integrate_dose_uSv(bad)

    def test_oracle_accepts_correct_and_flags_wrong_stream(self):
        rates = [rate(0, 36.0), rate(100, 72.0), rate(150, 0.0)]
        good = [cumulative(t, v) for t, v in zip((0, 100, 150), (0.0, 1.0, 2.0))]
        self.assertEqual(c.dose_stream_errors(rates, good), [])
        wrong = copy.deepcopy(good)
        wrong[2]["value"] = 2.0 / 1000  # mSv mistakenly published as uSv
        self.assertTrue(c.dose_stream_errors(rates, wrong))
        decreasing = copy.deepcopy(good)
        decreasing[2]["value"] = 0.5
        self.assertTrue(any("decreased" in e for e in c.dose_stream_errors(rates, decreasing)))

    def test_cumulative_must_declare_proxy_and_method(self):
        m = cumulative(0, 0.0)
        del m["simulated_proxy"]
        self.assertTrue(c.sensor_message_errors(m))
        m = cumulative(0, 0.0, method="simpson")
        self.assertTrue(c.sensor_message_errors(m))


class SensorValidity(unittest.TestCase):
    def test_valid_reading_is_usable_when_fresh(self):
        self.assertEqual(c.sensor_message_errors(rate(10, 5.0)), [])
        self.assertTrue(c.usable(rate(10, 5.0), now_s=10.5, max_age_s=2))

    def test_stale_by_age(self):
        self.assertFalse(c.usable(rate(10, 5.0), now_s=13.0, max_age_s=2))
        self.assertFalse(c.usable(rate(10, 5.0, sample_age_s=1.5), now_s=11.0, max_age_s=2))

    def test_future_timestamp_not_usable(self):
        self.assertFalse(c.usable(rate(10, 5.0), now_s=9.0, max_age_s=2))

    def test_saturated_is_not_a_point_value(self):
        m = rate(10, 10_000.0, validity="saturated")
        self.assertEqual(c.sensor_message_errors(m), [])
        self.assertFalse(c.usable(m, now_s=10, max_age_s=2))

    def test_failed_sensor_may_have_null_value(self):
        m = rate(10, None, validity="failed", uncertainty={"std": 0.0}, status="no response")
        self.assertEqual(c.sensor_message_errors(m), [])
        self.assertFalse(c.usable(m, now_s=10, max_age_s=2))

    def test_units_and_source(self):
        self.assertTrue(c.sensor_message_errors(rate(0, 1.0, units="sim_rad")))
        self.assertTrue(c.sensor_message_errors(rate(0, 1.0, source="cloud")))
        self.assertTrue(c.sensor_message_errors(rate(0, 1.0, saturation_limit=None)))

    def test_hydrogen_requires_measurement_scope_and_limit(self):
        h2 = {**rate(0, 40.0), "kind": "hydrogen", "units": "ppm", "source": "facility",
              "sensor_id": "facility.h2.high.1", "measures": "ambient", "detection_limit": 10.0,
              "pose": {"frame": "world", "xyz_m": [10.0, 6.0, 5.5]}}
        self.assertEqual(c.sensor_message_errors(h2), [])
        self.assertTrue(c.sensor_message_errors({**h2, "measures": None}))
        self.assertTrue(c.sensor_message_errors({**h2, "detection_limit": None}))


class ExistingSimulatorConformance(unittest.TestCase):
    """Wrap the current sim/sensors.py output as messages and check it with the oracle."""

    def world(self, seed=None):
        from sensors import SensorWorld, load_config
        drums = json.loads((ROOT / "sim" / "drums.json").read_text())
        drums = drums["drums"] if isinstance(drums, dict) else drums
        config = load_config()
        if seed is not None:
            config["seed"] = seed
        return SensorWorld(drums, config)

    def stream(self, world):
        rates, cums = [], []
        for i in range(20):
            t = i * 0.5
            s = world.sample((1.0 + 0.4 * i, 6.0, 0.6), t)
            rates.append(rate(t, s["dose_rate_uSv_h"], saturation_limit=1e6))
            cums.append(cumulative(t, s["mission_dose_mSv"] * 1000.0, method="trapezoid"))
        return rates, cums

    def test_existing_integration_conforms(self):
        rates, cums = self.stream(self.world())
        self.assertEqual(c.dose_stream_errors(rates, cums, rel_tol=1e-9), [])
        self.assertGreater(cums[-1]["value"], 0)

    def test_adapter_messages_conform(self):
        from sim_adapter import gamma_messages
        w = self.world()
        rates, cums = [], []
        for i in range(10):
            r, cu = gamma_messages(w.sample((2.0 + 0.3 * i, 6.0, 0.6), i * 0.5), saturation_limit_uSv_h=1000.0)
            self.assertEqual(c.sensor_message_errors(r) + c.sensor_message_errors(cu), [])
            rates.append(r)
            cums.append(cu)
        self.assertEqual(c.dose_stream_errors(rates, cums, rel_tol=1e-9), [])

    def test_seeded_variation_is_repeatable(self):
        a = [m["value"] for m in self.stream(self.world(seed=7))[0]]
        b = [m["value"] for m in self.stream(self.world(seed=7))[0]]
        d = [m["value"] for m in self.stream(self.world(seed=8))[0]]
        self.assertEqual(a, b)
        self.assertNotEqual(a, d)


class Detections(unittest.TestCase):
    def det(self, **kw):
        d = {"contract_version": c.CONTRACT_VERSION, "frame_id": 12, "camera_id": "spot.front.rgbd",
             "timestamp_s": 6.0, "class_id": 1, "class": "corrosion", "confidence": 0.62,
             "xyxy": [100, 120, 180, 200], "image_size_px": [640, 640], "drum_id": None,
             "model": {"name": "yolo-nano", "revision": "untrained"}}
        d.update(kw)
        return d

    def test_valid(self):
        self.assertEqual(c.detection_errors(self.det()), [])
        self.assertEqual(c.detection_errors(self.det(drum_id="D10", association="plate_read")), [])

    def test_class_order_fixed(self):
        self.assertEqual(c.YOLO_CLASSES, ("drum", "corrosion", "spill"))
        self.assertTrue(c.detection_errors(self.det(class_id=2)))

    def test_box_and_confidence(self):
        self.assertTrue(c.detection_errors(self.det(xyxy=[10, 10, 5, 20])))
        self.assertTrue(c.detection_errors(self.det(xyxy=[0, 0, 700, 20])))
        self.assertTrue(c.detection_errors(self.det(confidence=1.2)))

    def test_no_truth_or_probability_leak(self):
        self.assertTrue(c.detection_errors(self.det(probability=0.6)))
        self.assertTrue(c.detection_errors(self.det(truth={"fault": "corrosion"})))
        self.assertTrue(c.detection_errors(self.det(drum_id="D10")))  # association source missing


class InspectionRecords(unittest.TestCase):
    def rec(self, **kw):
        r = {"contract_version": c.CONTRACT_VERSION, "drum_id": "D10", "legacy_id": "D10",
             "location": {"lane": "B", "side": "L", "column": 3, "tier": 1, "tier_count": 3,
                          "stack_id": "B-L-03", "base_z_m": 0.0, "location_code": "B-L-03-T1"},
             "identity": {"status": "confirmed", "candidates": ["D10"], "evidence": ["ev-plate-4"]},
             "visibility": {"surface_coverage_fraction": 0.35},
             "finding_tracks": [{"track_id": "trk-1", "class": "corrosion", "first_seen_s": 4.0,
                                 "last_seen_s": 6.0, "frames": 9, "distinct_views": 1,
                                 "max_confidence": 0.62, "evidence_ids": ["ev-det-12"]}],
             "sensor_context": ["ev-dose-6.0"], "hypotheses": ["external corrosion; extent unknown"],
             "condition_status": "finding_suspected",
             "priority": {"kind": "ranking_score", "index": 64,
                          "breakdown": {"visual": 30, "uncertainty": 20, "dose_cost": -6, "recency": 20}},
             "updated_s": 6.0}
        r.update(kw)
        return r

    def test_valid(self):
        self.assertEqual(c.inspection_record_errors(self.rec()), [])

    def test_priority_is_ranking_not_probability(self):
        self.assertTrue(c.inspection_record_errors(self.rec(priority={"kind": "probability", "index": 64, "breakdown": {"x": 1}})))
        self.assertTrue(c.inspection_record_errors(self.rec(rupture_probability=0.64)))
        self.assertTrue(c.inspection_record_errors(self.rec(calibrated_probability={"value": 0.3})))

    def test_ambiguous_identity_lists_candidates(self):
        self.assertTrue(c.inspection_record_errors(self.rec(identity={"status": "ambiguous", "candidates": ["D10"]})))
        self.assertEqual(c.inspection_record_errors(self.rec(identity={"status": "ambiguous", "candidates": ["D10", "D11"]})), [])

    def test_no_correlated_confidence_product(self):
        r = self.rec()
        r["finding_tracks"][0]["combined_probability"] = 0.99
        self.assertTrue(c.inspection_record_errors(r))

    def test_location_consistency(self):
        r = self.rec()
        r["location"]["tier"] = 2
        self.assertTrue(c.inspection_record_errors(r))
        self.assertEqual(c.format_location("A", "L", 3, 2), "A-L-03-T2")
        for bad in ("D-L-03-T1", "A-X-03-T1", "A-L-3-T1", "A-L-00-T1", "A-L-03-T4"):
            with self.assertRaises(ValueError):
                c.parse_location(bad)

    def test_full_coverage_must_be_verified(self):
        self.assertTrue(c.inspection_record_errors(self.rec(visibility={"surface_coverage_fraction": 1.0})))


class Proposals(unittest.TestCase):
    def p(self, **kw):
        d = {"action": "second_view", "goal_id": "view-D10-west", "evidence_ids": ["ev-det-12"],
             "reason": "Corrosion seen from one angle; collect a second view.",
             "model": {"name": "Cosmos-Reason2-2B", "revision": "pending"}}
        d.update(kw)
        return d

    def test_valid(self):
        self.assertEqual(c.proposal_errors(self.p(), ["view-D10-west"], ["ev-det-12"]), [])

    def test_goal_must_be_offered(self):
        self.assertTrue(c.proposal_errors(self.p(goal_id="anywhere"), ["view-D10-west"], ["ev-det-12"]))

    def test_evidence_must_exist(self):
        self.assertTrue(c.proposal_errors(self.p(evidence_ids=["ev-made-up"]), ["view-D10-west"], ["ev-det-12"]))

    def test_cannot_override_safety(self):
        errs = c.proposal_errors(self.p(), ["view-D10-west"], ["ev-det-12"], safety_action="retreat")
        self.assertTrue(any("cannot override" in e for e in errs))
        ok = self.p(action="retreat", goal_id=None)
        self.assertEqual(c.proposal_errors(ok, [], ["ev-det-12"], safety_action="retreat"), [])


class Yaw(unittest.TestCase):
    def test_normalize_and_legacy_degrees(self):
        self.assertAlmostEqual(c.normalize_yaw_rad(3 * math.pi), math.pi)
        self.assertAlmostEqual(c.normalize_yaw_rad(-math.pi), math.pi)
        self.assertAlmostEqual(c.legacy_degrees_to_rad(270), -math.pi / 2)


if __name__ == "__main__":
    unittest.main()
