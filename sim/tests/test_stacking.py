import json
import math
import sys
import unittest
from collections import Counter
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM))
import stacking  # noqa: E402
from drums import YELLOWS  # noqa: E402
from sensors import SensorWorld, intersects_drum, load_config  # noqa: E402

INVENTORY = json.loads((SIM / 'drums.json').read_text())


class DenseLayout(unittest.TestCase):
    """Prompt v1.2.1 / Levi reference photo: all-yellow, densely stacked drums."""

    @classmethod
    def setUpClass(cls):
        cls.out = stacking.stack_inventory(INVENTORY)
        cls.by_id = {e['id']: e for e in cls.out}

    def test_counts(self):
        self.assertEqual(len(self.out), 200)  # Aisle 2 widened: wall rows and tier 3 removed.
        self.assertEqual(Counter((e['category'], e['location']['tier']) for e in self.out),
                         {('LLW', 1): 80, ('LLW', 2): 80, ('ILW', 1): 20, ('ILW', 2): 20})
        self.assertEqual(len(stacking.pallets(self.out)), 80)

    def test_ids_and_codes_unique_and_deterministic(self):
        self.assertEqual(len(self.by_id), len(self.out))
        self.assertEqual(len({e['display_id'] for e in self.out}), len(self.out))
        again = stacking.stack_inventory(INVENTORY)
        self.assertEqual(json.dumps(self.out, sort_keys=True), json.dumps(again, sort_keys=True))

    def test_originals_keep_ids_near_their_old_place(self):
        for e in INVENTORY:
            s = self.by_id[e['id']]
            self.assertEqual((s['category'], s['legacy_id'], s['location']['tier'], s['location']['depth']),
                             (e['category'], e['id'], 1, 1))
            self.assertEqual((s['legacy_x'], s['legacy_y']), (e['x'], e['y']))
            self.assertLess(math.hypot(s['x'] - e['x'], s['y'] - e['y']), 2.1)  # Wall rows removed and rows moved to widen aisle 2.
        self.assertEqual({e['id'] for e in self.out if e['legacy_id'] is None},
                         {f'D{n:02d}' for n in range(29, 201)})

    def test_all_yellow(self):  # F11
        # Every drum wears the detector's training paint.
        self.assertEqual({e['paint_color'] for e in self.out}, {'faded_yellow'})

    def test_dense_packing(self):  # F12
        llw = [e for e in self.out if e['category'] == 'LLW']
        for stack in {e['stack_id'] for e in llw}:
            t1 = [e for e in llw if e['stack_id'] == stack and e['location']['tier'] == 1]
            self.assertEqual(len(t1), 4)
            xs = sorted({e['x'] for e in t1})
            self.assertLessEqual(xs[1] - xs[0] - 2 * t1[0]['radius'], 0.021)  # drums touch (2 cm gap)
        cfg = stacking.load_config()
        for zone in cfg['zones']:
            gaps = [b - a - cfg['pallet']['size_m'] for a, b in zip(zone['pallet_x'], zone['pallet_x'][1:])]
            self.assertTrue(all(0 <= g <= 0.1 for g in gaps), gaps)

    def test_location_codes(self):
        for e in self.out:
            loc = e['location']
            code = f"{loc['lane']}-{loc['side']}-{loc['column']:02d}-T{loc['tier']}" + ('' if loc['depth'] == 1 else '-D2')
            self.assertEqual((e['display_id'], loc['location_code']), (code, code))
            self.assertEqual(loc['tier_count'] >= loc['tier'], True)
            self.assertEqual(e['visible_face'], loc['depth'] == 1)
        # Side L lies on the +y side of its aisle and faces -y.
        for e in self.out:
            aisle_y = stacking.AISLE_Y[e['facing_aisle']]
            self.assertEqual(e['location']['side'] == 'L', e['y'] > aisle_y)
            self.assertEqual(e['face_sign'], -1 if e['location']['side'] == 'L' else 1)

    def test_tiers_rest_on_pallets(self):
        p = stacking.load_config()['pallet']['height_m']
        for (stack, x, y), group in self._columns().items():
            tiers = sorted(group, key=lambda e: e['location']['tier'])
            self.assertAlmostEqual(tiers[0]['base_z'], p)
            for lower, upper in zip(tiers, tiers[1:]):
                self.assertAlmostEqual(upper['base_z'], lower['base_z'] + lower['height'] + p, places=4)
        self.assertLess(max(e['base_z'] + e['height'] for e in self.out), 5.0)  # under crane rail 5.15 m

    def _columns(self):
        cols = {}
        for e in self.out:
            cols.setdefault((e['stack_id'], e['x'], e['y']), []).append(e)
        return cols

    def test_clearance(self):  # F16
        self.assertEqual(stacking.clearance_errors(self.out), [])
        import aisles
        import tempfile
        data = aisles.write_aisles(Path(tempfile.mkdtemp()) / 'a.json')
        for a in data['aisles']:
            self.assertGreaterEqual(a['rect'][3] - a['rect'][1], 1.4)
            for e in self.out:  # no drum footprint inside an aisle band
                self.assertFalse(a['rect'][1] < e['y'] + math.copysign(e['radius'], a['center_y'] - e['y']) < a['rect'][3]
                                 and abs(e['y'] - a['center_y']) < 1.5, e['id'])

    def test_wall_rows_avoid_gamma_monitors(self):
        for e in self.out:
            if e['location']['stack_id'] and (e['y'] < 1.5 or e['y'] > 10.5):
                self.assertFalse(abs(e['pallet_xy'][0] - 6.0) < 0.6 or abs(e['pallet_xy'][0] - 15.0) < 0.6)

    def test_upper_drums_are_clean(self):
        for e in self.out:
            self.assertEqual((e['faults'], e['defects'], e['state']), ([], [], 'clean'))

    def test_disabled_config_returns_originals(self):
        cfg = dict(stacking.load_config(), enabled=False)
        self.assertEqual(len(stacking.stack_inventory(INVENTORY, cfg)), 28)


class StackedSensors(unittest.TestCase):
    def test_shielding_respects_base_height(self):
        drum = {'x': 0.0, 'y': 0.0, 'radius': 0.3, 'height': 0.9, 'base_z': 1.0}
        self.assertFalse(intersects_drum((-2, 0, 0.5), (2, 0, 0.5), drum))
        self.assertTrue(intersects_drum((-2, 0, 1.4), (2, 0, 1.4), drum))

    def test_upper_source_is_higher(self):
        out = stacking.stack_inventory(INVENTORY)
        top = next(e for e in out if e['location']['tier'] == 2)
        cfg = load_config()
        cfg['radiation']['noise_fraction'] = 0.0
        world = SensorWorld([top], cfg)
        src = next(s for s, _ in world._sources((0, 0, 0)))
        self.assertAlmostEqual(src[2], top['base_z'] + top['height'] / 2)


if __name__ == '__main__':
    unittest.main()
