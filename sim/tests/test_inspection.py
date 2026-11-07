"""Behaviour checks for units, information boundaries and safety precedence."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sensors import SensorWorld, intersects_drum, load_config
from criteria import classify_condition, safety_decision


class InspectionChecks(unittest.TestCase):
    def setUp(self):
        self.c = load_config()
        self.c['radiation']['noise_fraction'] = 0
        self.drum = {'id':'D01','x':0.,'y':0.,'height':1.,'radius':.3,'source_strength':10.}

    def test_inverse_square_and_dose_units(self):
        w = SensorWorld([self.drum], self.c)
        near = w.sample((1,0,.5),0)
        self.assertAlmostEqual(near['dose_rate_uSv_h'],10.2)
        self.assertAlmostEqual(w.sample((1,0,.5),3600)['mission_dose_mSv'],.0102)
        far = SensorWorld([self.drum],self.c).sample((2,0,.5),0)
        self.assertAlmostEqual(far['dose_rate_uSv_h']-.2,2.5)
        with self.assertRaises(ValueError): w.sample((1,0,.5),1)

    def test_gamma_failure_and_saturation_leave_dose_gap(self):
        self.c['radiation']['saturation_uSv_h'] = 20
        world = SensorWorld([self.drum], self.c)
        pose = (1, 0, .5)
        world.sample(pose, 0)
        first = world.sample(pose, 1)
        failed = world.sample(pose, 2, gamma_operational=False)
        self.assertEqual(failed['gamma']['status'], 'failed')
        self.assertIsNone(failed['dose_rate_uSv_h'])
        saturated = world.sample((.5, 0, .5), 3)
        self.assertEqual(saturated['gamma']['status'], 'saturated')
        self.assertEqual(saturated['dose_rate_uSv_h'], 20)
        self.assertFalse(saturated['gamma']['valid'])
        self.assertFalse(saturated['dose_complete'])
        recovered = world.sample(pose, 4)
        self.assertEqual(recovered['gamma']['timestamp_s'], 4)
        self.assertEqual(recovered['mission_dose_mSv'], first['mission_dose_mSv'])
        self.assertGreater(world.sample(pose, 5)['mission_dose_mSv'], first['mission_dose_mSv'])
        observation = {**saturated, 'camera_timestamp_s': 3, 'nearest_drum_surface_m': 1.1}
        self.assertEqual(safety_decision(observation, 3)['action'], 'back_off_last_safe_waypoint')
        self.assertEqual(safety_decision(observation, 6)['action'], 'stop')

    def test_shielding_and_sensor_packet_boundary(self):
        blocker = {**self.drum,'id':'D02','x':1.,'source_strength':0.}
        self.assertTrue(intersects_drum((2,0,.5),(0,0,.5),blocker))
        self.assertFalse(intersects_drum((2,0,2),(0,0,2),blocker))
        w = SensorWorld([self.drum,blocker],self.c)
        packet = w.sample((2,0,.5),0)
        self.assertAlmostEqual(packet['dose_rate_uSv_h'],1.45)
        self.assertNotIn('D01', json.dumps(packet))
        self.assertNotIn('source_strength', json.dumps(packet))
        self.assertAlmostEqual(sum(w.gamma_bins((2,0,.5))['intensity_uSv_h']),1.25)

    def test_seeded_readings_and_environment_event(self):
        a,b = SensorWorld([self.drum]),SensorWorld([self.drum])
        for i in range(3): self.assertEqual(a.sample((1,0,.5),i),b.sample((1,0,.5),i))
        a.inject_water_ingress('A')
        self.assertGreater(a.sample((1,0,.5),4)['relative_humidity_pct'],60)

    def test_swab_requires_contact_and_ten_seconds(self):
        w = SensorWorld([self.drum],self.c)
        with self.assertRaises(ValueError): w.start_swab((.3,0,0),0)
        with self.assertRaises(ValueError): w.start_swab((5,5,0),0,robot_stopped=True)
        w.inject_leak('D01')
        w.start_swab((.3,0,0),0,robot_stopped=True)
        self.assertEqual(w.poll_swab(9.99)['status'],'sampling')
        result = w.poll_swab(10)
        self.assertGreater(result['alpha_bq_cm2'],.4)
        self.assertEqual(w.poll_swab(11)['status'],'idle')
        self.assertNotIn('D01', json.dumps(result))

    def test_synthetic_payloads_keep_measurements_separate(self):
        import numpy as np
        from inspection_payloads import dew_point_c, microphone_window, thermal_image

        self.assertAlmostEqual(dew_point_c(20, 50), 9.3, places=1)
        self.assertIsNone(dew_point_c(20, 0))
        config = {**self.c, 'gas_vents': [{'position_m': [1, 0, 1], 'hydrogen_ppm': 90}]}
        world = SensorWorld([self.drum], config)
        near = world.sample((1, 0, 1), 0)
        far = world.sample((2, 0, 1), 1)
        self.assertEqual(near['hydrogen_ppm'], 90)
        self.assertEqual(far['hydrogen_ppm'], 45)
        self.assertEqual(near['methane_ppm'], 0)
        self.assertNotIn('hydrogen_ppm', SensorWorld([self.drum], self.c).sample((1, 0, 1), 0))

        pixels = thermal_image(np.array([[0, 1, 2]]), {1: 26, 3: 90}, 18)
        np.testing.assert_array_equal(pixels, [[18, 26, 18]])
        events = [{'kind': 'impulse', 'position_m': [0, 0, 0], 'time_s': 1, 'amplitude': 0.3}]
        before = microphone_window((0, 0, 0), 0, events)
        after = microphone_window((0, 0, 0), 1, events)
        self.assertLess(np.abs(before).max(), 0.02)
        self.assertGreater(np.abs(after).max(), 0.25)

        world.set_surface_chemistry('D01', ph=3.8, conductivity_us_cm=120, chloride_mg_m2=5)
        world.start_swab((.3, 0, 0), 0, robot_stopped=True)
        world.set_surface_chemistry('D01', ph=7)
        sample = world.poll_swab(10)
        self.assertEqual(sample['ph'], 3.8)
        self.assertEqual(sample['alpha_bq_cm2'], 0)

    def test_condition_boundaries_and_missing_measurements(self):
        for field, first, second in (('rust_pct',1,10),('bulge_pct',2,5)):
            self.assertEqual(classify_condition({field:first})['zone'],'Tolerable')
            self.assertEqual(classify_condition({field:second})['zone'],'Tolerable')
            self.assertEqual(classify_condition({field:second+.01})['zone'],'Failing')
        self.assertEqual(classify_condition({})['zone'],'Unknown')
        self.assertEqual(classify_condition({'rust_pct':.1,'rust_near_lifting_features':True})['zone'],'Failing')
        self.assertIn('request_swab_if_safe', classify_condition({'floor_condition':'residue'})['actions'])
        self.assertEqual(classify_condition({'swab':{'alpha_bq_cm2':.5,'beta_gamma_bq_cm2':0}})['zone'],'Failing')
        self.assertEqual(classify_condition({'reference_dose_uSv_h':30,'baseline_dose_uSv_h':10})['zone'],'Unknown')
        self.assertEqual(classify_condition({'reference_dose_uSv_h':30,'baseline_dose_uSv_h':10,'dose_reference_matched':True})['zone'],'Failing')
        complete = {'rust_pct':0,'bulge_pct':0,'reference_dose_uSv_h':10,'baseline_dose_uSv_h':10,
                    'dose_reference_matched':True,'floor_condition':'none','label_readability':'readable','confidence':.95}
        self.assertEqual(classify_condition(complete)['zone'],'Ideal')
        self.assertEqual(classify_condition({**complete,'confidence':.6})['zone'],'Unknown')

    def test_hard_rules_override_and_budget_units(self):
        o = {'camera_timestamp_s':0,'dose_timestamp_s':0,'dose_rate_uSv_h':10,
             'nearest_drum_surface_m':1.1,'mission_dose_mSv':0}
        self.assertEqual(safety_decision(o,0)['action'],'continue')
        self.assertEqual(safety_decision(o,0)['map_zone'],'amber')
        self.assertEqual(safety_decision(o,2.01)['action'],'stop')
        self.assertEqual(safety_decision({**o,'dose_rate_uSv_h':101},0)['action'],'back_off_last_safe_waypoint')
        self.assertEqual(safety_decision({**o,'mission_dose_mSv':40},0)['action'],'return_to_dock')
        combined = {**o,'mission_dose_mSv':40,'person_distance_m':1}
        self.assertEqual(safety_decision(combined,0)['action'],'stop')
        self.assertEqual(safety_decision({**o,'nearest_drum_surface_m':.49,'swabbing':True},0)['action'],'stop')
        self.assertEqual(safety_decision(o,0)['speed_limit_mps'],.5)
        self.assertEqual(safety_decision({**o,'dose_rate_uSv_h':float('nan')},0)['action'],'stop')
        self.assertEqual(safety_decision({**o,'mission_dose_mSv':None},0)['action'],'stop')


if __name__ == '__main__': unittest.main()
