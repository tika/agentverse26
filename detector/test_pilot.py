"""CPU checks for label conversion and reproducible independent assignments."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from detector.pilot_specs import scene_spec
from sim.detector_studio.pilot import export_frame


class PilotTests(unittest.TestCase):
    def test_reproducible_independent_labels_and_shape_ranges(self):
        self.assertEqual(scene_spec(4),scene_spec(4))
        conditions_by_plate={}
        for seed in range(1,101):
            specs=scene_spec(seed)
            self.assertEqual(len({e['display_id'] for e in specs}),4)
            self.assertEqual({(e['rust'],e['bulge']) for e in specs},{(False,False),(True,False),(False,True),(True,True)})
            for e in specs:
                conditions_by_plate.setdefault(e['display_id'],set()).add((e['rust'],e['bulge']))
                if e['bulge']:
                    self.assertTrue(.07<=e['radial_fraction']<=.09)
                    self.assertTrue(.065<=e['lid_rise_m']<=.075)
        self.assertTrue(all(len(states)>1 for states in conditions_by_plate.values()))

    def test_export_class_mapping_and_one_bulge_per_drum(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            Image.new('RGB',(640,640),(120,120,100)).save(directory/'rgb_0000.png')
            dtype=[('semanticId','i4'),('x_min','i4'),('y_min','i4'),('x_max','i4'),('y_max','i4')]
            np.save(directory/'bounding_box_2d_tight_0000.npy',np.array([(1,100,100,300,500),(2,150,200,170,230)],dtype=dtype))
            (directory/'bounding_box_2d_tight_labels_0000.json').write_text(json.dumps({'1':{'class':'drum','drum_id':'d01'},'2':{'class':'corrosion','drum_id':'d01'}}))
            counts=export_frame(directory,[{'id':'D01','bulge':True}],{})
            self.assertEqual(counts,{'drum':1,'corrosion':1,'bulge':1})
            self.assertEqual({line.split()[0] for line in (directory/'labels.txt').read_text().splitlines()},{'0','1','2'})


if __name__=='__main__':unittest.main()
