import unittest
from detector.barrel_audit import assign_conditions


class BarrelAssociationTests(unittest.TestCase):
    def test_local_patch_and_whole_drum_bulge_associate_separately(self):
        drums=[dict(box=[0,0,100,200]),dict(box=[110,0,210,200])]
        faults=[dict(class_id=1,confidence=.8,box=[20,20,40,40]),
                dict(class_id=2,confidence=.9,box=[110,0,210,200]),
                dict(class_id=1,confidence=.9,box=[300,300,320,320])]
        states=assign_conditions(drums,faults,[.25]*3)
        self.assertEqual(states,[dict(corrosion=True,bulge=False),dict(corrosion=False,bulge=True)])

    def test_below_threshold_fault_is_not_a_barrel_finding(self):
        states=assign_conditions([dict(box=[0,0,100,200])],
                                 [dict(class_id=1,confidence=.1,box=[20,20,40,40])],[.25]*3)
        self.assertFalse(states[0]['corrosion'])


if __name__=='__main__':
    unittest.main()
