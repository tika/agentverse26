"""CPU-only failure and assembly checks; no Modal calls or GPU allocation."""
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from detector.dataset_plan import make_plan,validate_plan,digest,CLASSES,CAMERA
from detector.dataset_release import build_release


def fixture(root):
    plan=make_plan(10,workers=1,frames_per_scene=5)
    gen=dict(plan=plan,plan_sha256=digest(plan),classes=CLASSES,camera=CAMERA,
             workspace='fixture',source_hashes={'fixture':'test'},run_id='fixture')
    (root/'generation.json').write_text(json.dumps(gen))
    for job in plan['jobs']:
        folder=root/f"seed_{job['seed']:02d}";folder.mkdir()
        (folder/'report.json').write_text(json.dumps(dict(seed=job['seed'],images=5,classes=CLASSES,
                                                        entries=[{'rust_seed':job['seed']}])) )
        (folder/'runtime.json').write_text(json.dumps({'return_code':0}))
        (folder/'progress.json').write_text(json.dumps({'state':'complete','completed':5}))
        for i in range(5):
            frame=folder/f'frame_{i:03d}';frame.mkdir()
            Image.new('RGB',(640,640),(job['seed']*70+i*10,100,110)).save(frame/'image.jpg')
            boxes=[dict(class_id=c,class_name=CLASSES[c],internal_id='D01',xyxy=[100,100,300,500]) for c in range(3)]
            (frame/'labels.txt').write_text('\n'.join(f'{c} 0.3125 0.46875 0.3125 0.625' for c in range(3))+'\n')
            meta=dict(boxes=boxes,pixel_mean=100,camera=dict(**CAMERA,mode='single',target_id='D01',eye=[0,-1,.6],target=[0,0,.47]))
            (frame/'metadata.json').write_text(json.dumps(meta))
    return plan


class ReleaseTests(unittest.TestCase):
    def test_1200_plan_is_frozen_900_150_150_with_ten_workers(self):
        p=validate_plan(make_plan(1200,workers=10))
        counts=Counter()
        for j in p['jobs']:counts[j['split']]+=j['frames']
        self.assertEqual(counts,{'train':900,'val':150,'test':150})
        self.assertEqual(len(p['jobs']),61)
        self.assertEqual(p['workers'],10)
        self.assertGreater(min(j['seed'] for j in p['jobs']),8)
        bad=json.loads(json.dumps(p));bad['jobs'][1]['seed']=bad['jobs'][0]['seed']
        with self.assertRaises(ValueError):validate_plan(bad)

    def test_complete_pilot_assembly_and_immutable_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run';root.mkdir();fixture(root)
            target=Path(tmp)/'release';build_release(root,target)
            m=json.loads((target/'manifest.json').read_text())
            self.assertEqual(m['images'],10)
            self.assertEqual(m['split_counts'],{'pilot':10})
            self.assertFalse((target/'data.yaml').exists())
            with self.assertRaises(ValueError):build_release(root,target)

    def test_missing_frame_and_corrupt_labels_are_rejected_without_partial_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run';root.mkdir();fixture(root)
            label=root/'seed_01/frame_000/labels.txt'
            label.write_text('2 0.5 0.5 0.1 0.1\n')
            target=Path(tmp)/'release'
            with self.assertRaises(ValueError):build_release(root,target)
            self.assertFalse(target.exists())
            self.assertFalse(list(Path(tmp).glob('release.building_*')))

    def test_duplicate_images_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run';root.mkdir();fixture(root)
            (root/'seed_01/frame_001/image.jpg').write_bytes((root/'seed_01/frame_000/image.jpg').read_bytes())
            with self.assertRaises(ValueError):build_release(root,Path(tmp)/'release')


if __name__=='__main__':unittest.main()
