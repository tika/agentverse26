"""Freeze scene seeds and train/validation/test assignments for one workspace."""
import argparse
import hashlib
import json
from pathlib import Path

CLASSES = ['drum', 'corrosion', 'bulge']
CAMERA = dict(width=640, height=640, fx=400, fy=400, cx=320, cy=320)
SOURCE_FILES = ['detector/pilot_specs.py', 'detector/annotations.py', 'detector/dataset_plan.py',
                'sim/detector_studio/pilot.py', 'sim/corrosion_preview.py',
                'sim/drums.py', 'sim/drum_textures.py', 'sim/geometry.py',
                'sim/profiles.py', 'sim/materials.py', 'sim/textures.py',
                'sim/sensors.py', 'sim/inspection_config.json', 'sim/training_capture.py']


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def source_hashes(root):
    return {name:hashlib.sha256((Path(root)/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def make_plan(images=40, workers=10, frames_per_scene=None, seed_start=None):
    seed_start=seed_start or (1 if images<=40 else 1001)
    if images < 5 or not 1 <= workers <= 16 or seed_start < 1:
        raise ValueError('Use >=5 images, 1–16 workers, positive starting seed')
    frames_per_scene=frames_per_scene or (5 if images==40 else 20)
    if not 5<=frames_per_scene<=50:raise ValueError('Use 5–50 frames per scene')
    # Inspected pilot is never presented as an independent evaluation set.
    if images<=40:amounts=[('pilot',images)]
    else:
        train=int(images*.75);val=(images-train)//2
        amounts=[('train',train),('val',val),('test',images-train-val)]
    jobs=[];seed=seed_start
    for split,count in amounts:
        while count:
            take=min(count,frames_per_scene)
            if 0<count-take<5:take-=5-(count-take)
            if take<5:raise ValueError('Split too small for five-frame minimum; choose another image count')
            jobs.append(dict(seed=seed,frames=take,split=split));seed+=1;count-=take
    return dict(schema=1,images=images,workers=workers,classes=CLASSES,camera=CAMERA,jobs=jobs)


def validate_plan(plan):
    if plan.get('schema')!=1 or plan.get('classes')!=CLASSES or plan.get('camera')!=CAMERA:
        raise ValueError('Unsupported plan schema/classes/camera')
    jobs=plan['jobs']
    if len({j['seed'] for j in jobs})!=len(jobs) or any(j['seed']<1 or not 1<=j['frames']<=50 for j in jobs):
        raise ValueError('Duplicate seeds or invalid frame counts')
    if sum(j['frames'] for j in jobs)!=plan['images'] or not 1<=plan['workers']<=16:
        raise ValueError('Plan totals or worker count invalid')
    return plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--images',type=int,default=40)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--frames-per-scene',type=int)
    p.add_argument('--seed-start',type=int);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise SystemExit('Plan already exists; use it unchanged or select a new path')
    plan=validate_plan(make_plan(a.images,a.workers,a.frames_per_scene,a.seed_start))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(plan,indent=2)+'\n')
    print(json.dumps(dict(path=str(a.output),plan_sha256=digest(plan),images=plan['images'],
                         jobs=len(plan['jobs']),workers=plan['workers']),indent=2))


if __name__=='__main__':main()
