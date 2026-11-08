import json
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mission_coverage import StoreRouter,CoverageLedger
from pressure_screen import screen_visual_pressure


class FullStoreChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drums=json.loads((Path(__file__).resolve().parents[1]/'drums.json').read_text())

    def test_every_drum_has_two_reachable_clear_views(self):
        router=StoreRouter(self.drums,robot_radius=.70)
        for d in self.drums:
            for goal in router.viewpoints(d)[:2]:
                path=router.route((1.3,2.),goal)
                self.assertIsNotNone(path,d['display_id'])
                for a,b in zip([(1.3,2.)]+path,path):
                    self.assertTrue(router.line_free(a,b),d['display_id'])

    def test_cannot_cut_through_rows_or_walls(self):
        router=StoreRouter(self.drums)
        self.assertFalse(router.line_free((3,2),(3,6)))
        path=router.route((3,2),(3,6))
        self.assertGreater(router.length((3,2),path),4.5)
        self.assertIsNone(router.route((-.1,6),(1,6)))

    def test_repeated_frames_do_not_complete_inspection(self):
        ledger=CoverageLedger(self.drums);key=self.drums[0]['id']
        memory={d['id']:{'checks':{}} for d in self.drums}
        memory[key]['checks']={'id':{'result':'match'},'thermal':{'surface_c':20},'visual':{}}
        for t in range(20):ledger.visual(key,(2.7,2),range_m=1.5,area=5000,confidence=.8,time_s=t)
        ledger.sync(memory);self.assertFalse(memory[key]['complete'])
        ledger.visual(key,(3.3,2),range_m=1.5,area=5000,confidence=.8,time_s=21)
        ledger.sync(memory);self.assertTrue(memory[key]['complete'])
        memory[key]['checks']['id']['result']='unreadable'
        ledger.sync(memory);self.assertFalse(memory[key]['complete'])

    def test_checkpoint_identity_and_pressure_filter(self):
        ledger=CoverageLedger(self.drums);other=CoverageLedger(self.drums)
        other.restore(ledger.snapshot())
        wrong=ledger.snapshot();wrong['map_sha256']='wrong'
        with self.assertRaises(ValueError):other.restore(wrong)
        for bulge,temp,want in [(True,22,False),(False,30,False),(True,23,True),(True,None,False)]:
            r=screen_visual_pressure(bulge_observed=bulge,surface_c=temp,ambient_c=18)
            self.assertEqual(r['suspected_pressurisation'],want)
            self.assertFalse(r['gas_confirmed'])


if __name__=='__main__':unittest.main()
