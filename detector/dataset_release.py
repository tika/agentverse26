"""Validate one-workspace generation, assemble YOLO splits, publish to its Volume."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from detector.dataset_plan import CLASSES,CAMERA,digest,validate_plan


def check_workspace(expected):
    profiles=json.loads(subprocess.check_output(['modal','profile','list','--json'],text=True))
    active=[p for p in profiles if p.get('active')]
    if len(active)!=1 or active[0].get('workspace')!=expected:
        raise ValueError(f'Wrong active Modal workspace; activate a profile for {expected}')
    return active[0]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_frame(folder,job):
    from PIL import Image
    folder=Path(folder)
    meta=json.loads((folder/'metadata.json').read_text())
    image=folder/'image.jpg';labels=folder/'labels.txt'
    with Image.open(image) as im:
        im.load()
        if im.size!=(640,640):raise ValueError(f'Wrong image resolution: {image}')
    cam=meta['camera']
    if any(cam.get(k)!=v for k,v in CAMERA.items()):raise ValueError(f'Camera calibration differs: {folder}')
    if not all(math.isfinite(x) for k in ('eye','target') for x in cam[k]):raise ValueError('Non-finite camera pose')
    if not math.isfinite(meta['pixel_mean']) or meta['pixel_mean']<=3:raise ValueError('Invalid/black RGB')
    boxes=meta['boxes'];lines=labels.read_text().splitlines()
    if len(lines)!=len(boxes):raise ValueError(f'Label/metadata count differs: {folder}')
    for line,box in zip(lines,boxes):
        fields=line.split()
        if len(fields)!=5:raise ValueError('Invalid YOLO row')
        cls=int(fields[0]);v=list(map(float,fields[1:]))
        if cls not in range(3) or any(not math.isfinite(x) or not 0<=x<=1 for x in v):raise ValueError('Invalid class/box values')
        if v[2]<=0 or v[3]<=0 or v[0]-v[2]/2 < -1e-6 or v[0]+v[2]/2>1+1e-6 or v[1]-v[3]/2 < -1e-6 or v[1]+v[3]/2>1+1e-6:
            raise ValueError('Box outside image')
        if box['class_id']!=cls or box['class_name']!=CLASSES[cls]:raise ValueError('Class mapping differs')
        x0,y0,x1,y1=box['xyxy'];expected=[(x0+x1)/1280,(y0+y1)/1280,(x1-x0)/640,(y1-y0)/640]
        if any(abs(a-b)>1e-6 for a,b in zip(v,expected)):raise ValueError('YOLO/native metadata box differs')
    ids={b['internal_id'] for b in boxes if b['class_name']=='drum'}
    if any(b['internal_id'] not in ids for b in boxes):raise ValueError('Defect without visible drum')
    if cam['mode']=='single' and ids!={cam['target_id']}:raise ValueError('Single frame has incorrect drum count')
    if cam['mode']=='inspection' and cam['target_id'] not in ids:raise ValueError('Inspection target missing')
    if cam['mode']=='context' and len(ids)<2:raise ValueError('Context frame has fewer than two visible drums')
    if cam['mode'] not in ('single','inspection','context'):raise ValueError('Unknown view mode')
    return meta


def validate_seed(run,job):
    folder=Path(run)/f"seed_{job['seed']:02d}"
    report=json.loads((folder/'report.json').read_text())
    progress=json.loads((folder/'progress.json').read_text())
    runtime=json.loads((folder/'runtime.json').read_text())
    if report['seed']!=job['seed'] or report['images']!=job['frames'] or report['classes']!=CLASSES:
        raise ValueError('Seed report differs from plan')
    if progress['state']!='complete' or progress['completed']!=job['frames'] or runtime['return_code']!=0:
        raise ValueError('Incomplete/failed seed')
    frames=sorted(folder.glob('frame_*'))
    if [p.name for p in frames]!=[f'frame_{i:03d}' for i in range(job['frames'])]:raise ValueError('Missing/extra frames')
    return [(p,validate_frame(p,job)) for p in frames]


def build_release(run,output):
    run=Path(run);output=Path(output)
    if output.exists():raise ValueError('Release already exists; do not overwrite an immutable release')
    generation=json.loads((run/'generation.json').read_text());plan=validate_plan(generation['plan'])
    if generation['plan_sha256']!=digest(plan):raise ValueError('Plan fingerprint differs')
    if generation['classes']!=CLASSES or generation['camera']!=CAMERA:raise ValueError('Generation class/camera mismatch')
    stage=output.with_name(output.name+'.building_'+uuid.uuid4().hex[:6]);stage.mkdir(parents=True)
    counts=Counter();splits=Counter();modes=Counter();records=[];seen_hashes=set();rust_by_split={}
    try:
        for job in plan['jobs']:
            seed_folder=run/f"seed_{job['seed']:02d}"
            report=json.loads((seed_folder/'report.json').read_text())
            for entry in report['entries']:
                previous=rust_by_split.setdefault(entry['rust_seed'],job['split'])
                if previous!=job['split']:raise ValueError('Rust seed appears in multiple dataset splits')
            for frame,meta in validate_seed(run,job):
                name=seed_folder.name+'_'+frame.name
                image_hash=sha(frame/'image.jpg')
                if image_hash in seen_hashes:raise ValueError('Duplicate image content')
                seen_hashes.add(image_hash)
                record=dict(stem=name,seed=job['seed'],split=job['split'],files={})
                for kind,src,ext in [('images','image.jpg','jpg'),('labels','labels.txt','txt'),('metadata','metadata.json','json')]:
                    dst=stage/kind/job['split']/(name+'.'+ext);dst.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(frame/src,dst)
                    record['files'][kind]=dict(path=dst.relative_to(stage).as_posix(),sha256=sha(dst))
                records.append(record);splits[job['split']]+=1;modes[meta['camera']['mode']]+=1
                counts.update(b['class_name'] for b in meta['boxes'])
        if len(records)!=plan['images']:raise ValueError('Release image count differs from plan')
        for split in splits:
            classes={int(line.split()[0]) for p in (stage/'labels'/split).glob('*.txt') for line in p.read_text().splitlines()}
            if classes!=set(range(3)):raise ValueError(f'Missing class in {split}')
        manifest=dict(schema=1,release=output.name,images=len(records),classes=CLASSES,camera=CAMERA,
                      split_counts=dict(splits),view_modes=dict(modes),class_counts=dict(counts),records=records,
                      generation=generation)
        (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (stage/'generation.json').write_text(json.dumps(generation,indent=2)+'\n')
        if 'train' in splits:
            # Relative paths resolve against the data.yaml directory in Ultralytics.
            (stage/'data.yaml').write_text('train: images/train\nval: images/val\ntest: images/test\nnames:\n  0: drum\n  1: corrosion\n  2: bulge\n')
        else:(stage/'PILOT_ONLY.txt').write_text('Inspected pilot; no independent training/evaluation split.\n')
        stage.rename(output)
    except Exception:
        shutil.rmtree(stage);raise
    print('RELEASE_BUILT',output,len(records),flush=True)
    return output


def upload_release(release,workspace):
    import modal
    check_workspace(workspace)
    release=Path(release);manifest=json.loads((release/'manifest.json').read_text())
    if not re.fullmatch(r'[A-Za-z0-9_-]+',release.name):raise ValueError('Use an alphanumeric release name')
    if manifest['generation']['workspace']!=workspace:raise ValueError('Release belongs to another workspace')
    # Recheck immutable file integrity before uploading.
    records=[f for r in manifest['records'] for f in r['files'].values()]
    for item in records:
        if sha(release/item['path'])!=item['sha256']:raise ValueError('Local release changed after validation')
    volume=modal.Volume.from_name('detector-data',environment_name='main',create_if_missing=True)
    remote='/releases/'+release.name
    try:existing=volume.listdir(remote)
    except modal.exception.NotFoundError:existing=[]
    if existing:raise ValueError('Remote release already exists; use another name, never force-overwrite')
    with volume.batch_upload() as upload:upload.put_directory(release,remote)
    if b''.join(volume.read_file(remote+'/manifest.json'))!=(release/'manifest.json').read_bytes():raise ValueError('Uploaded manifest verification failed')
    def verify(item):
        content=b''.join(volume.read_file(remote+'/'+item['path']))
        if hashlib.sha256(content).hexdigest()!=item['sha256']:raise ValueError('Remote file hash mismatch: '+item['path'])
    with ThreadPoolExecutor(max_workers=10) as pool:list(pool.map(verify,records))
    receipt=dict(workspace=workspace,volume='detector-data',remote_path=remote,images=manifest['images'],
                 verified_files=len(records),manifest_sha256=sha(release/'manifest.json'))
    (release.parent/(release.name+'_upload_receipt.json')).write_text(json.dumps(receipt,indent=2))
    print('DATASET_PUBLISHED '+json.dumps(receipt),flush=True)
    return receipt


def recover_run(run_id,output,workspace):
    import modal
    check_workspace(workspace)
    if not re.fullmatch(r'[A-Za-z0-9_-]+',run_id):raise ValueError('Invalid run ID')
    output=Path(output)
    if output.exists():raise ValueError('Recovery destination must be new')
    volume=modal.Volume.from_name('detector-data',environment_name='main')
    base='/pilots/'+run_id
    generation=b''.join(volume.read_file(base+'/generation.json'))
    parsed=json.loads(generation)
    if parsed['workspace']!=workspace:raise ValueError('Generation workspace mismatch')
    output.mkdir(parents=True);(output/'generation.json').write_bytes(generation)
    seeds={f"seed_{j['seed']:02d}" for j in parsed['plan']['jobs']}
    paths=[]
    for item in volume.iterdir(base):
        relative=item.path.removeprefix(base+'/')
        parts=Path(relative).parts
        if parts and parts[0] in seeds and Path(relative).name in ('image.jpg','labels.txt','metadata.json','boxes.jpg','report.json','runtime.json','progress.json'):
            paths.append((item.path,relative))
    def copy(item):
        source,relative=item;path=output/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b''.join(volume.read_file(source)))
    with ThreadPoolExecutor(max_workers=10) as pool:list(pool.map(copy,paths))
    print('RUN_RECOVERED',output,len(paths),'files',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--run',type=Path,required=True);b.add_argument('--output',type=Path,required=True)
    u=sub.add_parser('upload');u.add_argument('--release',type=Path,required=True);u.add_argument('--workspace',default='paramsachdeva07')
    r=sub.add_parser('recover');r.add_argument('--run-id',required=True);r.add_argument('--output',type=Path,required=True);r.add_argument('--workspace',default='paramsachdeva07')
    a=p.parse_args()
    if a.command=='build':build_release(a.run,a.output)
    elif a.command=='upload':upload_release(a.release,a.workspace)
    else:recover_run(a.run_id,a.output,a.workspace)


if __name__=='__main__':main()
