"""CPU checks for label conversion and reproducible independent assignments."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from detector.pilot_specs import scene_spec, diversity_spec, clear_inspection_ray
from detector.annotations import merge_rust_boxes
from sim.detector_studio.pilot import export_frame


class PilotTests(unittest.TestCase):
    def test_diversity_camera_mix_and_reproducible_environment(self):
        seen_layouts=set();seen_bearings=set();seen_floors=set();seen_counts=set()
        for seed in range(1,33):
            spec=diversity_spec(seed,25)
            self.assertEqual(spec,diversity_spec(seed,25))
            views=spec['frames']
            self.assertEqual(sum(v['mode']=='inspection' for v in views),15)
            self.assertEqual(sum(v['mode']=='context' for v in views),10)
            ids={e['id'] for e in spec['entries']}
            for view in views:
                self.assertTrue(.45<=view['eye'][2]<=.8)
                if view['mode']=='inspection':
                    self.assertIn(view['target_id'],ids)
                    self.assertTrue(1.0<=view['distance_m']<=1.5)
                    self.assertTrue(clear_inspection_ray(view['eye'],view['target'],spec['entries'],view['target_id']))
                seen_bearings.add(round((view['bearing_rad']+np.pi/2)/(np.pi/2))%4)
            seen_layouts.add(spec['environment']['layout'])
            seen_floors.add(tuple(spec['environment']['floor_color']))
            seen_counts.add(len(spec['entries']))
        self.assertEqual(len(seen_layouts),3)
        self.assertEqual(len(seen_floors),4)
        self.assertEqual(len(seen_bearings),4)
        self.assertEqual(seen_counts,{4,6,8})

    def test_rust_merging_keeps_identity_and_limits_region_span(self):
        def rust(identity,xyxy):return dict(class_name='corrosion',class_id=1,internal_id=identity,xyxy=xyxy)
        boxes=[rust('D01',[10,80,13,84]),rust('D01',[14,80,18,84]),
               rust('D02',[14,80,18,84]),rust('D01',[70,10,90,20])]
        merged=merge_rust_boxes(boxes,{'D01':[0,0,100,200],'D02':[0,0,100,200]})
        self.assertEqual(len(merged),3)
        self.assertEqual(sum(b['source_cluster_count'] for b in merged),4)
        d1=[b for b in merged if b['internal_id']=='D01']
        self.assertEqual(len(d1),2)
        self.assertTrue(any(b['xyxy']==[10,80,18,84] for b in d1))

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
