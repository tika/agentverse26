"""Stage-3 evidence taxonomy, sensor validity, priority and scenario checks."""
import copy
import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
import contracts as c  # noqa: E402
import evidence as ev  # noqa: E402
import priority as pr  # noqa: E402
import scenario_checks as sck  # noqa: E402
import validity as va  # noqa: E402

POSE = {"frame": "world", "xyz_m": [5.0, 6.0, 0.6]}


def msg(kind="gamma_dose_rate", value=5.0, t=10.0, validity="valid", **kw):
    units = {"gamma_dose_rate": "uSv/h", "hydrogen": "ppm", "temperature": "degC"}[kind]
    m = {"contract_version": c.CONTRACT_VERSION, "sensor_id": f"robot.{kind}", "kind": kind, "source": "robot",
         "timestamp_s": t, "units": units, "value": value, "pose": POSE, "sample_age_s": 0.0,
         "validity": validity, "uncertainty": {"std": 0.1}, "status": "ok"}
    if kind == "gamma_dose_rate":
        m["saturation_limit"] = 1000.0
    if kind == "hydrogen":
        m.update(measures="ambient", detection_limit=10.0)
    m.update(kw)
    return m


class Taxonomy(unittest.TestCase):
    def test_every_kind_states_limits_and_known_hypotheses(self):
        for kind, spec in ev.KINDS.items():
            self.assertTrue(spec["cannot_establish"], kind)
            for h in spec["supports"]:
                self.assertIn(h, ev.HYPOTHESES)

    def test_high_dose_never_means_leak(self):
        e = ev.make_evidence("dose_rate_level", value=150, units="uSv/h", t_s=1, area="A-L")
        hyps = {f["hypothesis"] for f in ev.findings_for([e])}
        self.assertEqual(hyps, {"elevated_radiation_field"})
        self.assertIn("a leak", e["cannot_establish"])

    def test_bulge_never_means_hydrogen(self):
        e = ev.make_evidence("depth_deformation", value=0.03, units="m", t_s=1, drum_ids=["D10"], view_id="v1")
        self.assertIn("hydrogen", e["cannot_establish"])
        self.assertEqual({f["hypothesis"] for f in ev.findings_for([e])}, {"suspected_deformation"})

    def test_wet_alone_is_unexplained_and_release_needs_independent_channel(self):
        wet = ev.make_evidence("visual_wet_or_residue", value=1, units="detections", t_s=1, drum_ids=["D10"], view_id="v1")
        self.assertNotIn("suspected_release", {f["hypothesis"] for f in ev.findings_for([wet])})
        swab = ev.make_evidence("swab_contamination", value=6.0, units="Bq/cm2", t_s=2, area="A-L")
        self.assertIn("suspected_release", {f["hypothesis"] for f in ev.findings_for([wet, swab])})

    def test_correlated_frames_count_views_not_frames(self):
        frames = [ev.make_evidence("visual_corrosion", value=0.7, units="conf", t_s=i, drum_ids=["D10"],
                                   view_id="v1", frame_id=i) for i in range(30)]
        f = ev.findings_for(frames)[0]
        self.assertEqual((len(f["evidence_ids"]), f["distinct_views"]), (30, 1))
        self.assertEqual(ev.condition_status([f], 0.3), "finding_suspected")
        second = ev.make_evidence("visual_corrosion", value=0.6, units="conf", t_s=40, drum_ids=["D10"], view_id="v2")
        self.assertEqual(ev.condition_status(ev.findings_for(frames + [second]), 0.5), "finding_confirmed_multi_view")

    def test_status_never_safe(self):
        self.assertEqual(ev.condition_status([], 0.0), "insufficient_coverage")
        self.assertEqual(ev.condition_status([], 0.3), "no_visible_defect_in_inspected_area")
        self.assertEqual(ev.condition_status([], None), "unknown")
        for s in ("insufficient_coverage", "no_visible_defect_in_inspected_area", "unknown"):
            self.assertIn(s, c.CONDITION_STATUS)

    def test_area_scope_enforced(self):
        with self.assertRaises(ValueError):
            ev.make_evidence("visual_corrosion", value=1, units="conf", t_s=0)  # drum-scoped needs one drum
        with self.assertRaises(ValueError):
            ev.make_evidence("hydrogen_ambient", value=50, units="ppm", t_s=0, drum_ids=["D10"])

    def test_actions(self):
        gas = ev.make_evidence("hydrogen_ambient", value=400, units="ppm", t_s=0, area="B")
        self.assertIn("stand_off_and_alert", ev.actions_for(ev.findings_for([gas]), 0.5))
        rad = ev.make_evidence("dose_rate_level", value=150, units="uSv/h", t_s=0, area="B")
        self.assertIn("measure_at_matched_reference_pose", ev.actions_for(ev.findings_for([rad]), 0.5))


class Validity(unittest.TestCase):
    def test_fresh_stale_future(self):
        self.assertTrue(va.assess(msg(t=10), now_s=11)["usable"])
        self.assertEqual(va.assess(msg(t=10), now_s=13)["state"], "stale")
        self.assertEqual(va.assess(msg(t=10), now_s=9)["state"], "future")

    def test_saturated_is_lower_bound_and_dl_is_upper_bound(self):
        v = va.assess(msg(value=1000.0, validity="saturated"), now_s=10)
        self.assertEqual((v["usable"], v["bound"]), (False, "lower"))
        v = va.assess(msg("hydrogen", value=10.0, validity="below_detection_limit"), now_s=10)
        self.assertEqual((v["usable"], v["bound"]), (False, "upper"))

    def test_failed_and_calibration(self):
        for s in ("failed", "calibration_expired", "warming_up"):
            v = va.assess(msg(value=None, validity=s, uncertainty={"std": None, "status": "unknown"}), now_s=10)
            self.assertEqual((v["usable"], v["state"]), (False, s))

    def test_invalid_message(self):
        self.assertEqual(va.assess(msg(units="sim_rad"), now_s=10)["state"], "invalid_message")

    def test_low_mounted_hydrogen_cannot_clear_upper_space(self):
        low = msg("hydrogen", value=0.0, validity="below_detection_limit")
        ok, why = va.absence_claim_allowed(low, region_z_m=4.5)
        self.assertFalse(ok)
        self.assertTrue(any("buoyant" in r for r in why))
        high = msg("hydrogen", value=0.0, validity="below_detection_limit",
                   pose={"frame": "world", "xyz_m": [10, 6, 5.5]}, source="facility")
        self.assertTrue(va.absence_claim_allowed(high, region_z_m=4.5)[0])
        headspace = dict(high, measures="package_headspace")
        self.assertFalse(va.absence_claim_allowed(headspace, region_z_m=4.5)[0])

    def test_channel_summary_flags_critical_unusable(self):
        msgs = [msg(t=1), msg(t=9), msg("hydrogen", value=None, t=9, validity="failed",
                                        uncertainty={"std": None, "status": "unknown"})]
        s = va.channel_summary(msgs, now_s=10)
        self.assertTrue(s["verdicts"]["robot.gamma_dose_rate"]["usable"])
        self.assertEqual(s["critical_unusable"], ["robot.hydrogen"])


class Priority(unittest.TestCase):
    def test_ranking_not_probability_and_explained(self):
        f = ev.findings_for([ev.make_evidence("visual_corrosion", value=.7, units="conf", t_s=0,
                                              drum_ids=["D10"], view_id="v1")])
        p = pr.priority(f, coverage_fraction=0.3, identity_status="confirmed", last_seen_age_s=0)
        self.assertEqual((p["kind"], p["not_a_probability"]), ("ranking_score", True))
        self.assertAlmostEqual(p["index"], sum(p["breakdown"].values()), places=1)
        self.assertGreater(p["breakdown"]["uncertainty"], 0)  # single view -> needs second view
        self.assertIn("external corrosion", p["explanation"])
        rec = {"contract_version": c.CONTRACT_VERSION, "drum_id": "D10", "legacy_id": "D10",
               "location": {"lane": "B", "side": "L", "column": 4, "tier": 1, "tier_count": 3, "stack_id": "B-L-P02",
                            "base_z_m": 0.144, "location_code": "B-L-04-T1"},
               "identity": {"status": "confirmed", "candidates": ["D10"]}, "visibility": {"surface_coverage_fraction": 0.3},
               "finding_tracks": [], "sensor_context": [], "hypotheses": [], "condition_status": "finding_suspected",
               "priority": {"kind": p["kind"], "index": p["index"], "breakdown": p["breakdown"]}, "updated_s": 0}
        self.assertEqual(c.inspection_record_errors(rec), [])

    def test_unseen_ranks_above_clean_recent(self):
        clean = pr.priority([], coverage_fraction=0.6, identity_status="confirmed", last_seen_age_s=5)
        unseen = pr.priority([], coverage_fraction=0.0, identity_status="unread", last_seen_age_s=None)
        self.assertGreater(unseen["index"], clean["index"])

    def test_safety_and_dose_cost(self):
        gas = ev.findings_for([ev.make_evidence("hydrogen_ambient", value=400, units="ppm", t_s=0, area="B")])
        p = pr.priority(gas, coverage_fraction=0.5, identity_status="confirmed", last_seen_age_s=0)
        self.assertEqual(p["breakdown"]["safety"], pr.WEIGHTS["safety"])
        cheap = pr.priority([], coverage_fraction=.5, identity_status="confirmed", last_seen_age_s=0,
                            expected_dose_uSv=0.1, remaining_budget_uSv=100)
        dear = pr.priority([], coverage_fraction=.5, identity_status="confirmed", last_seen_age_s=0,
                           expected_dose_uSv=80, remaining_budget_uSv=100)
        self.assertLess(dear["breakdown"]["exposure"], cheap["breakdown"]["exposure"])
        self.assertGreaterEqual(dear["index"], 0)


def channel(units, anomaly=False, cause="", **kw):
    ch = {"enabled": True, "units": units, "sample_period_s": 0.5, "noise": 0.1, "detection_limit": 0.0,
          "saturation": 1000.0, "response_lag_s": 0.0, "calibration": "synthetic", "mount_height_m": 0.6,
          "cause": cause, "anomaly": anomaly}
    ch.update(kw)
    return ch


def scenario(sid, tags, defects=(), gamma=False, h2=False, thermal=False, wet=None, truth=None):
    return {"scenario_id": sid, "seed": 7, "case_tags": tags,
            "truth": truth if truth is not None else {"calibration": "synthetic"},
            "runtime": {"defects": list(defects), "wet_case": wet, "channels": {
                "gamma": channel("uSv/h", gamma, "package inventory raises the field" if gamma else ""),
                "hydrogen": channel("ppm", h2, "ventilation fault in zone B" if h2 else "", measures="ambient"),
                "thermal": channel("degC", thermal, "external heat source" if thermal else "")}}}


CORROSION = {"kind": "corrosion", "visible_fraction": 0.8, "dose_effect": "none"}
GOOD_SET = [
    scenario("s1", ["sound_but_radioactive"], gamma=True),
    scenario("s2", ["corroded_no_dose_change"], defects=[CORROSION]),
    scenario("s3", ["hidden_condition"], truth={"internal_corrosion": True, "calibration": "synthetic"}),
    scenario("s4", ["healthy_control"]),
    scenario("s5", ["wet_external_water"], wet={"mechanism": "roof leak dripping onto the floor", "fluid_kind": "water"}),
]


class ScenarioChecks(unittest.TestCase):
    def test_good_set_passes(self):
        self.assertEqual(sck.set_errors(GOOD_SET), {})

    def test_required_case_coverage(self):
        self.assertIn("<set>", sck.set_errors(GOOD_SET[1:]))

    def test_truth_leak_and_all_channels(self):
        bad = copy.deepcopy(GOOD_SET[0])
        bad["runtime"]["defects"].append({"kind": "corrosion", "visible_fraction": 0, "faults": ["x"]})
        self.assertTrue(any("leaked" in e for e in sck.scenario_errors(bad)))
        allc = scenario("x", ["gas_area_concern"], gamma=True, h2=True, thermal=True)
        self.assertTrue(any("every hazard channel" in e for e in sck.scenario_errors(allc)))

    def test_tag_consistency(self):
        self.assertTrue(sck.scenario_errors(scenario("x", ["sound_but_radioactive"], defects=[CORROSION], gamma=True)))
        self.assertTrue(sck.scenario_errors(scenario("x", ["corroded_no_dose_change"], defects=[CORROSION], gamma=True)))
        self.assertTrue(sck.scenario_errors(scenario("x", ["hidden_condition"], defects=[CORROSION])))
        self.assertTrue(sck.scenario_errors(scenario("x", ["wet_external_water"], wet={"mechanism": ""})))
        self.assertTrue(sck.scenario_errors(scenario("x", ["wet_suspected_release"], wet={"mechanism": "seal"})))

    def test_units_and_cause(self):
        sc = scenario("x", ["gas_area_concern"], h2=True)
        sc["runtime"]["channels"]["hydrogen"]["units"] = "sim_gas"
        sc["runtime"]["channels"]["hydrogen"]["cause"] = ""
        errs = sck.scenario_errors(sc)
        self.assertTrue(any("units" in e for e in errs) and any("cause" in e for e in errs))


class Assessment(unittest.TestCase):
    def test_rules_on_required_cases_never_read_truth(self):
        import stage3_assess as sa
        out = {r["scenario_id"]: r for r in (sa.assess_scenario(copy.deepcopy(sc)) for sc in GOOD_SET)}
        self.assertEqual({f["hypothesis"] for f in out["s1"]["findings"]}, {"elevated_radiation_field"})
        self.assertIn("measure_at_matched_reference_pose", out["s1"]["actions"])
        self.assertEqual({f["hypothesis"] for f in out["s2"]["findings"]}, {"external_corrosion"})
        self.assertEqual(out["s2"]["condition_status"], "finding_suspected")
        # Hidden condition: truth says internal corrosion, runtime shows nothing -> not 'safe', not detected.
        self.assertEqual(out["s3"]["findings"], [])
        self.assertEqual(out["s3"]["condition_status"], "no_visible_defect_in_inspected_area")
        self.assertEqual(out["s4"]["findings"], [])
        self.assertEqual({f["hypothesis"] for f in out["s5"]["findings"]}, {"wet_or_residue_unexplained"})
        self.assertIn("request_swab_if_safe", out["s5"]["actions"])
        poisoned = copy.deepcopy(GOOD_SET[2])
        poisoned["truth"] = {"internal_corrosion": True, "faults": ["corrosion"], "visible": True}
        self.assertEqual(sa.assess_scenario(poisoned)["findings"], [])


    def test_obstruction_and_swab(self):
        import stage3_assess as sa
        sc = scenario("ob", ["obstruction"])
        sc["runtime"]["obstruction"] = {"geometry_m": {"size": [0.8, 0.55, 0.9]}, "route_id": "middle_cross_aisle",
                                        "cause": "dropped tote"}
        r = sa.assess_scenario(sc)
        self.assertEqual({f["hypothesis"] for f in r["findings"]}, {"route_blocked"})
        self.assertIn("replan_route", r["actions"])
        self.assertEqual(r["condition_status"], "no_visible_defect_in_inspected_area")
        rel = scenario("rel", ["wet_suspected_release"], wet={"mechanism": "seal failure", "fluid_kind": "residue"},
                       truth={"contamination": True, "calibration": "synthetic"})
        self.assertNotIn("suspected_release", {f["hypothesis"] for f in sa.assess_scenario(rel)["findings"]})
        rel["runtime"]["swab"] = {"alpha_bq_cm2": 0.1, "beta_gamma_bq_cm2": 6.0, "t_s": 30}
        self.assertIn("suspected_release", {f["hypothesis"] for f in sa.assess_scenario(rel)["findings"]})
        self.assertIn("mark_area_avoid_tracking_and_alert", sa.assess_scenario(rel)["actions"])


if __name__ == "__main__":
    unittest.main()
