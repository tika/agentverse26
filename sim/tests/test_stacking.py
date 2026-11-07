import json
import math
import sys
import unittest
from collections import Counter
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM))
import stacking  # noqa: E402
from sensors import SensorWorld, intersects_drum, load_config  # noqa: E402

INVENTORY = json.loads((SIM / 'drums.json').read_text())


class Stacking(unittest.TestCase):
    def setUp(self):
        self.out = stacking.stack_inventory(INVENTORY)
        self.by_id = {e['id']: e for e in self.out}

    def test_counts_and_ids(self):
        self.assertEqual(Counter(e['location']['tier'] for e in self.out), {1: 28, 2: 28, 3: 16})
        self.assertEqual(sorted(self.by_id)[:2], ['D01', 'D02'])
        self.assertEqual({e['id'] for e in self.out if e['location']['tier'] > 1},
                         {f'D{n:02d}' for n in range(29, 73)})
        self.assertEqual(len({e['display_id'] for e in self.out}), len(self.out))

    def test_originals_keep_id_and_xy(self):
        for e in INVENTORY:
            s = self.by_id[e['id']]
            self.assertEqual((s['x'], s['y'], s['legacy_id'], s['location']['tier']), (e['x'], e['y'], e['id'], 1))

    def test_deterministic(self):
        again = stacking.stack_inventory(INVENTORY)
        self.assertEqual(json.dumps(self.out, sort_keys=True), json.dumps(again, sort_keys=True))

    def test_location_codes(self):
        # D01 (row A, y 3.45) faces aisle 1 (y 2) from +y: lane A, left, first column.
        self.assertEqual(self.by_id['D01']['display_id'], 'A-L-01-T1')
        self.assertEqual(self.by_id['D05']['display_id'], 'B-R-01-T1')
        self.assertEqual(self.by_id['D28']['display_id'], 'C-R-07-T1')
        self.assertEqual(self.by_id['D29']['display_id'], 'A-L-01-T2')
        for e in self.out:
            loc = e['location']
            self.assertEqual(loc['location_code'], f"{loc['lane']}-{loc['side']}-{loc['column']:02d}-T{loc['tier']}")
            self.assertEqual(loc['tier_count'], 3 if e['category'] == 'LLW' else 2)

    def test_tiers_rest_on_pallets_without_overlap(self):
        p = stacking.load_config()['pallet']['height_m']
        for stack in {e['stack_id'] for e in self.out}:
            tiers = sorted((e for e in self.out if e['stack_id'] == stack), key=lambda e: e['location']['tier'])
            self.assertAlmostEqual(tiers[0]['base_z'], p)
            for lower, upper in zip(tiers, tiers[1:]):
                self.assertAlmostEqual(upper['base_z'], lower['base_z'] + lower['height'] + p, places=4)
        self.assertLess(max(e['base_z'] + e['height'] for e in self.out), 5.0)  # below crane rail 5.15 m

    def test_aisle_clearance(self):
        self.assertEqual(stacking.clearance_errors(self.out), [])

    def test_upper_drums_are_clean(self):
        for e in self.out:
            if e['location']['tier'] > 1:
                self.assertEqual((e['faults'], e['defects'], e['state']), ([], [], 'clean'))

    def test_disabled_config_is_identity(self):
        cfg = dict(stacking.load_config(), enabled=False)
        self.assertEqual(len(stacking.stack_inventory(INVENTORY, cfg)), 28)


class StackedSensors(unittest.TestCase):
    def test_shielding_respects_base_height(self):
        drum = {'x': 0.0, 'y': 0.0, 'radius': 0.3, 'height': 0.9, 'base_z': 1.0}
        self.assertFalse(intersects_drum((-2, 0, 0.5), (2, 0, 0.5), drum))   # passes under it
        self.assertTrue(intersects_drum((-2, 0, 1.4), (2, 0, 1.4), drum))

    def test_upper_source_is_higher(self):
        out = stacking.stack_inventory(INVENTORY)
        cfg = load_config()
        cfg['radiation']['noise_fraction'] = 0.0
        world = SensorWorld(out, cfg)
        top = next(e for e in out if e['id'] == 'D30')  # A-L-01-T3
        src = next(s for s, _ in world._sources((0, 0, 0)) if math.isclose(s[0], top['x']) and s[2] > 2)
        self.assertAlmostEqual(src[2], top['base_z'] + top['height'] / 2)


if __name__ == '__main__':
    unittest.main()
