import json
import sys
import unittest
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM))
import demo_faults as df  # noqa: E402
import stacking  # noqa: E402

INVENTORY = stacking.stack_inventory(json.loads((SIM / 'drums.json').read_text()))
# Aisle 2 LLW section (docs/demo_video_plan.md); sim/inspection_viewpoints.py will own this selection.
SECTION_ALL = [d for d in INVENTORY if d['location']['lane'] == 'B' and d['category'] == 'LLW']
SECTION = [d for d in SECTION_ALL if d['visible_face']]
IDS = {d['id'] for d in SECTION}


class DemoFaults(unittest.TestCase):
    def test_section_size(self):
        self.assertEqual((len(SECTION_ALL), len(SECTION)), (120, 60))

    def test_deterministic(self):
        self.assertEqual(df.assign_faults(SECTION, 1), df.assign_faults(SECTION, 1))

    def test_seeds_differ(self):
        runs = [json.dumps(df.assign_faults(SECTION, s), sort_keys=True) for s in range(10)]
        self.assertEqual(len(set(runs)), 10)

    def test_count_kinds_and_section(self):
        for seed in range(200):
            faults = df.assign_faults(SECTION_ALL, seed)  # Hidden back drums must never be chosen.
            self.assertTrue(4 <= len(faults) <= 6)
            self.assertTrue(set(faults) <= IDS)
            kinds = {k for f in faults.values() for k in f['kinds']}
            self.assertEqual(kinds, set(df.FAULT_KINDS))
            for f in faults.values():
                self.assertTrue(set(f['kinds']) <= set(df.FAULT_KINDS))
                self.assertTrue(all(k in f for k in f['kinds']))
                if len(f['kinds']) > 1:
                    self.assertEqual(set(f['kinds']), {'heat', 'h2'})

    def test_spread(self):
        doubles = 0
        for seed in range(200):
            faults = df.assign_faults(SECTION, seed)
            located = [d['location'] for d in SECTION if d['id'] in faults]
            self.assertEqual({l['tier'] for l in located}, {1, 2, 3})
            self.assertEqual({l['side'] for l in located}, {'L', 'R'})
            doubles += any(len(f['kinds']) > 1 for f in faults.values())
        self.assertTrue(20 < doubles < 180)

    def test_param_ranges(self):
        for seed in range(100):
            for f in df.assign_faults(SECTION, seed).values():
                if 'heat' in f:
                    self.assertTrue(8 <= f['heat']['surface_rise_c'] <= 30)
                if 'h2' in f:
                    self.assertTrue(300 <= f['h2']['hydrogen_ppm'] <= 1200)
                if 'bulge' in f:
                    self.assertTrue(.015 <= f['bulge']['dimensions_m'][-1] <= .025)
                if 'rust' in f:
                    self.assertIn(f['rust']['severity'], (1, 2, 3))

    def test_apply_cleans_rest_of_section(self):
        dirty = [dict(d, faults=['corrosion'], state='corrosion', corrosion_severity=2, defects=[{'x': 1}])
                 if d['id'] in IDS else d for d in INVENTORY]
        faults = df.assign_faults(SECTION, 3)
        out = {d['id']: d for d in df.apply_to_inventory(dirty, faults, section_ids=IDS)}
        for drum_id in IDS - set(faults):
            d = out[drum_id]
            self.assertEqual((d['faults'], d['state'], d['corrosion_severity'], d['defects']), ([], 'clean', 0, []))
        for drum_id, f in faults.items():
            self.assertEqual('corrosion' in out[drum_id]['faults'], 'rust' in f)
            self.assertEqual('bulge' in out[drum_id]['faults'], 'bulge' in f)
            self.assertEqual(len(out[drum_id]['defects']), ('rust' in f) + ('bulge' in f))
        self.assertEqual(dirty[0], [d for d in dirty if d['id'] == dirty[0]['id']][0])  # Input untouched.
        outside = next(d for d in dirty if d['id'] not in IDS)
        self.assertEqual(out[outside['id']], outside)

    def test_visual_scenarios_match_runtime_schema(self):
        faults = df.assign_faults(SECTION, 5)
        scenarios = df.visual_scenarios(faults, 5)
        visual = {i for i, f in faults.items() if 'rust' in f or 'bulge' in f}
        self.assertEqual({s['asset_id'] for s in scenarios}, visual)
        for s in scenarios:
            for defect in s['runtime']['defects']:
                self.assertIn(defect['kind'], ('corrosion', 'bulge'))
                self.assertGreater(defect['visible_fraction'], 0)
                self.assertIn('dimensions_m', defect)

    def test_layout_resets(self):
        self.assertEqual(df.layout_resets(IDS), ['D05', 'D06', 'D10', 'D12'])

    def test_scene_overrides(self):
        for seed in range(50):
            faults = df.assign_faults(SECTION, seed)
            scene = df.scene_overrides(faults, INVENTORY)
            self.assertEqual(set(scene), {'drum_offsets_c', 'gas_vents', 'acoustic'})
            self.assertFalse(any(word in key for key in scene for word in ('dose', 'retreat', 'gamma')))
            self.assertEqual(set(scene['drum_offsets_c']), {i for i, f in faults.items() if 'heat' in f})
            self.assertEqual(len(scene['gas_vents']), sum('h2' in f for f in faults.values()))
            self.assertEqual(len(scene['acoustic']), len(scene['gas_vents']))

    def test_truth_and_score(self):
        faults = df.assign_faults(SECTION, 1)
        truth = df.truth_record(faults, INVENTORY, 1)
        json.dumps(truth)
        codes = sorted(truth['faults'])
        statuses = {code: 'red' for code in codes[:-1]}
        statuses[codes[-1]] = 'amber'
        statuses['B-R-01-T1' if 'B-R-01-T1' not in codes else 'B-R-02-T1'] = 'red'
        result = df.score(truth, statuses, ['a', 'b'])
        self.assertEqual(result['found'], codes[:-1])
        self.assertEqual(result['missed'], [codes[-1]])
        self.assertEqual(len(result['false_red']), 1)
        self.assertEqual(result['second_looks_used'], 2)
        self.assertAlmostEqual(result['efficiency'], (len(codes) - 1) / 2)
        self.assertEqual(df.score(truth, {}, 0)['efficiency'], 0)


if __name__ == '__main__':
    unittest.main()
