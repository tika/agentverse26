"""Regression checks for curved fault geometry and the real Replicator export format."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from drums import make_inventory
from defects import corrosion_specs
from defect_geometry import surface_mesh
from profiles import radius_at,drum_profile
from training_capture import export_boxes


class HandoffChecks(unittest.TestCase):
    def test_seeded_faults_are_separate_curved_geometry(self):
        for entry in (make_inventory()[11],make_inventory()[17]):
            a=corrosion_specs(entry,0,3)
            self.assertEqual(a,corrosion_specs(entry,0,3))
            for spec in a:
                if spec['subtype']=='rust_flakes':continue
                points,faces,uv=surface_mesh(entry,spec)
                self.assertEqual(len(uv),sum(map(len,faces)))
                for x,y,z in points:
                    self.assertGreaterEqual(z,0)
                    self.assertLessEqual(z,entry['height'])
                    self.assertAlmostEqual(math.hypot(x-entry['x'],y-entry['y']),radius_at(drum_profile(entry['category']),z)+.003,places=7)

    def test_replicator_lowercase_ids_and_yolo_class_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            Image.new('RGB',(640,640),(120,120,120)).save(d/'rgb_0000.png')
            rows=np.array([(5,20,30,100,150)],dtype=[('semanticId','u4'),('x_min','u4'),('y_min','u4'),('x_max','u4'),('y_max','u4')])
            np.save(d/'bounding_box_2d_tight_0000.npy',rows)
            (d/'bounding_box_2d_tight_labels_0000.json').write_text(json.dumps({'5':{'class':'corrosion','drum_id':'d10'}}))
            report=export_boxes(d)
            self.assertEqual(report['boxes'][0]['drum_id'],'D10')
            self.assertTrue((d/'labels.txt').read_text().startswith('1 '))
            Image.new('RGB',(640,640),(0,0,0)).save(d/'rgb_0000.png')
            with self.assertRaises(AssertionError):export_boxes(d)

    def test_drums_are_real_scale_next_to_spot(self):
        # The bundled Spot USD is real scale: 1.10 m long, 0.50 m wide (Boston Dynamics spec).
        spot_width=.50
        llw=2*max(r for r,_ in drum_profile('LLW'))
        ilw=2*max(r for r,_ in drum_profile('ILW'))
        self.assertTrue(.584<=llw<=.603,llw)  # 55 US gal / 208 L steel drum OD
        self.assertAlmostEqual(ilw,.80,3)     # 500 L ILW drum
        self.assertAlmostEqual(llw/spot_width,1.196,2)
        for entry in make_inventory():
            self.assertAlmostEqual(entry['radius'],max(r for r,_ in drum_profile(entry['category'])))


if __name__=='__main__':unittest.main()
