"""Stage-2 identity and runtime-map tests. Run: python -m unittest discover -s perception/tests -v"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "perception")]
import asset_map as am  # noqa: E402
import identity as ident  # noqa: E402
import contracts as c  # noqa: E402

INVENTORY = json.loads((ROOT / "sim" / "drums.json").read_text())


class RuntimeMap(unittest.TestCase):
    def setUp(self):
        self.map = am.runtime_view(INVENTORY)

    def test_view_from_real_inventory_is_truth_free(self):
        self.assertEqual(am.map_errors(self.map), [])
        self.assertEqual(len(self.map["drums"]), 28)
        for d in self.map["drums"]:
            self.assertFalse(set(d) & am.KNOWN_TRUTH_FIELDS)

    def test_raw_inventory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "drums.json"
            raw.write_text(json.dumps(INVENTORY))
            with self.assertRaises(ValueError):
                am.load_runtime_map(raw)
            leaked = {"map_version": am.MAP_VERSION, "drums": [dict(self.map["drums"][0], faults=["corrosion"])]}
            raw.write_text(json.dumps(leaked))
            with self.assertRaisesRegex(ValueError, "truth"):
                am.load_runtime_map(raw)
            unknown = {"map_version": am.MAP_VERSION, "drums": [dict(self.map["drums"][0], new_field=1)]}
            raw.write_text(json.dumps(unknown))
            with self.assertRaisesRegex(ValueError, "allow-list"):
                am.load_runtime_map(raw)
            raw.write_text(json.dumps(self.map))
            self.assertEqual(len(am.load_runtime_map(raw)["drums"]), 28)

    def test_display_id_collisions_are_detected(self):
        # Plates print row+slot (e.g. 'D06' on drum D27); those strings are also immutable ids.
        collisions = am.display_id_collisions(self.map)
        self.assertIn(("D06", "D27"), collisions)


class Association(unittest.TestCase):
    def setUp(self):
        self.map = am.runtime_view(INVENTORY)
        self.by_id = {d["id"]: d for d in self.map["drums"]}

    def at(self, drum_id, dx=0.0, dy=0.0):
        d = self.by_id[drum_id]
        return (d["x"] + dx, d["y"] + dy)

    def test_plate_and_geometry_agree(self):
        d = self.by_id["D10"]
        r = ident.associate(self.map, plate_text=d["display_id"], observed_xyz=self.at("D10", 0.1), evidence_ids=["ev-1"])
        self.assertEqual((r["status"], r["candidates"]), ("confirmed", ["D10"]))

    def test_plate_text_is_never_treated_as_immutable_id(self):
        # Reading 'D06' on a plate means the drum whose display_id is D06 (D27), not drum D06.
        r = ident.associate(self.map, plate_text="D06", observed_xyz=self.at("D27"))
        self.assertEqual((r["status"], r["candidates"]), ("confirmed", ["D27"]))
        self.assertTrue(any("display_id" in n for n in r["notes"]))

    def test_moved_drum_gives_conflict_not_silent_relabel(self):
        r = ident.associate(self.map, plate_text=self.by_id["D10"]["display_id"], observed_xyz=self.at("D03"))
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(r["candidates"][0], "D10")
        self.assertIn("D03", r["candidates"])

    def test_geometry_only_is_provisional(self):
        r = ident.associate(self.map, observed_xyz=self.at("D03", 0.05))
        self.assertEqual((r["status"], r["candidates"]), ("unread", ["D03"]))

    def test_between_two_drums_is_ambiguous(self):
        a, b = self.by_id["D01"], self.by_id["D02"]
        mid = ((a["x"] + b["x"]) / 2, a["y"])
        r = ident.associate(self.map, observed_xyz=mid, gate_m=1.0)
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(set(r["candidates"]), {"D01", "D02"})

    def test_stacked_tiers_need_height_or_stay_ambiguous(self):
        base = dict(self.by_id["D01"])
        upper = dict(base, id="D29", legacy_id="D01", display_id="A21", base_z=base["height"] + 0.15)
        stacked = {"map_version": am.MAP_VERSION, "drums": [dict(base, base_z=0.0), upper]}
        self.assertEqual(am.map_errors(stacked), [])
        flat = ident.associate(stacked, observed_xyz=(base["x"], base["y"]))
        self.assertEqual(flat["status"], "ambiguous")
        top_z = upper["base_z"] + base["height"] / 2
        r = ident.associate(stacked, observed_xyz=(base["x"], base["y"], top_z))
        self.assertEqual((r["status"], r["candidates"]), ("unread", ["D29"]))

    def test_location_code_plates(self):
        # Codex stage-2 plate format: display_id == location_code; upper tiers D29+.
        base = dict(self.by_id["D01"], display_id="A-L-01-T1", base_z=0.0)
        upper = dict(base, id="D29", legacy_id="D01", display_id="A-L-01-T2", base_z=base["height"] + 0.15)
        stacked = {"map_version": am.MAP_VERSION, "drums": [base, upper]}
        self.assertEqual(am.map_errors(stacked), [])
        self.assertEqual(am.display_id_collisions(stacked), [])
        top = (base["x"], base["y"], upper["base_z"] + base["height"] / 2)
        r = ident.associate(stacked, plate_text="A-L-01-T2", observed_xyz=top)
        self.assertEqual((r["status"], r["candidates"]), ("confirmed", ["D29"]))
        # Plate says bottom tier but the box is at the top tier: conflict, both kept.
        r = ident.associate(stacked, plate_text="A-L-01-T1", observed_xyz=top)
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(r["candidates"], ["D01", "D29"])
        for bad in ("A-L-1-T1", "D-L-01-T1", "A-L-01-T4"):
            self.assertEqual(ident.associate(stacked, plate_text=bad)["status"], "unread")

    def test_unreadable_or_malformed_plate(self):
        r = ident.associate(self.map, plate_text="??", observed_xyz=self.at("D05"))
        self.assertEqual(r["status"], "unread")
        r = ident.associate(self.map, plate_text="Z99", observed_xyz=None)
        self.assertEqual((r["status"], r["candidates"]), ("unread", []))

    def test_output_fits_inspection_record_contract(self):
        r = ident.associate(self.map, observed_xyz=(4.0, 3.45), gate_m=1.0)
        rec = {"contract_version": c.CONTRACT_VERSION, "drum_id": "D01", "legacy_id": "D01",
               "location": {"lane": "A", "side": "L", "column": 1, "tier": 1, "tier_count": 1,
                            "stack_id": "A-L-01", "base_z_m": 0.0, "location_code": "A-L-01-T1"},
               "identity": r, "visibility": {"surface_coverage_fraction": 0.2}, "finding_tracks": [],
               "sensor_context": [], "hypotheses": [], "condition_status": "unknown",
               "priority": {"kind": "ranking_score", "index": 10, "breakdown": {"identity": 10}},
               "updated_s": 0.0}
        self.assertEqual(c.inspection_record_errors(rec), [])


if __name__ == "__main__":
    unittest.main()


class DenseLayoutIdentity(unittest.TestCase):
    """v1.2.1 dense store: -D2 back-row codes, stencilled package IDs, 3-digit IDs."""

    @classmethod
    def setUpClass(cls):
        scene_sim = Path("/Users/levi/Desktop/agentverse/worktrees/claude-s2-scene/sim")
        if not (scene_sim / "stacking.py").exists():
            raise unittest.SkipTest("scene worktree not available")
        sys.path.insert(0, str(scene_sim))
        import stacking
        cls.entries = stacking.stack_inventory(json.loads((scene_sim / "drums.json").read_text()))
        cls.map = am.runtime_view(cls.entries)
        cls.by_id = {d["id"]: d for d in cls.map["drums"]}

    def test_map_valid_and_codes_parse(self):
        self.assertEqual(am.map_errors(self.map), [])
        self.assertEqual(am.display_id_collisions(self.map), [])
        for d in self.map["drums"]:
            self.assertEqual(c.location_errors(d["location"]), [])

    def test_stencil_confirms_and_conflicts(self):
        e = next(x for x in self.entries if x["id"] == "D133")  # B-L-01-T2, 3-digit id
        surface = (e["x"], e["y"] - e["radius"], e["base_z"] + 0.72 * e["height"])
        r = ident.associate(self.map, stencil_text="D133", observed_xyz=surface)
        self.assertEqual((r["status"], r["candidates"]), ("confirmed", ["D133"]))
        r = ident.associate(self.map, stencil_text="D133", plate_text="B-L-01-T1")
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(ident.associate(self.map, stencil_text="D999")["status"], "unread")

    def test_hidden_back_row_drum_stays_unread_from_the_aisle(self):
        back = next(x for x in self.entries if x["location"]["depth"] == 2 and x["location"]["tier"] == 1)
        self.assertTrue(back["display_id"].endswith("-D2"))
        self.assertTrue(ident.PLATE_RE.match(back["display_id"]))
        front = next(x for x in self.entries if x["location"]["depth"] == 1 and x["x"] == back["x"]
                     and x["stack_id"] == back["stack_id"] and x["location"]["tier"] == 1)
        face_y = front["y"] + front["face_sign"] * front["radius"]
        r = ident.associate(self.map, observed_xyz=(front["x"], face_y, 0.5))
        self.assertEqual(r["candidates"], [front["id"]])  # only the visible drum, never the hidden one
