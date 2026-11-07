import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pressure_screen import screen_pressure_risk


class PressureScreenChecks(unittest.TestCase):
    def test_independent_heat_and_shape_channels(self):
        def screen(bulge,surface,lid=0):
            return screen_pressure_risk(bulge_pct=bulge,surface_temperatures_c=surface,ambient_c=18,lid_rise_mm=lid)
        self.assertEqual(screen(0,[20,20.1,19.9])['status'],'no_two_cue_anomaly')
        self.assertEqual(screen(3,[20,20.1,19.9])['status'],'shape_anomaly')
        self.assertEqual(screen(0,[30,30.1,29.9])['status'],'thermal_anomaly')
        both=screen(3,[30,30.1,29.9])
        self.assertEqual(both['status'],'suspected_pressurisation')
        self.assertFalse(both['gas_confirmed'])
        self.assertEqual(screen(0,[20,55,20])['status'],'no_two_cue_anomaly')
        self.assertEqual(screen(0,[30,30,30],lid=25)['status'],'suspected_pressurisation')
        self.assertEqual(screen_pressure_risk(bulge_pct=3,surface_temperatures_c=[],ambient_c=18)['status'],'insufficient_data')

if __name__=='__main__':unittest.main()
