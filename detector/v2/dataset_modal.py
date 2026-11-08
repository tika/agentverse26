"""Ten RTX PRO 6000 render workers, then assemble one portable YOLO release."""
import json,os,subprocess,time,hashlib,sys,zipfile
from pathlib import Path
import modal

LOCAL=modal.is_local();ROOT=Path(__file__).resolve().parents[2] if LOCAL else Path('/workspace')
ASSETS=ROOT/'.runtime/drum-pilot15-assets/CANIS_YOLO_DRUM_ASSETS_FOUR_CONDITIONS_V1/warehouse-v3' if LOCAL else Path('/assets/warehouse')
CODE=ROOT/'sim/detector_studio_v2/generate_dataset.py' if LOCAL else Path('/workspace/generate_dataset.py')
image=(modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',add_python='3.13',setup_dockerfile_commands=['USER root'])
       .entrypoint([]).env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all'})
       .add_local_dir(ASSETS,'/assets/warehouse',copy=True).add_local_file(CODE,'/workspace/generate_dataset.py',copy=True))
cpu_image=modal.Image.debian_slim(python_version='3.12').pip_install('pillow==11.3.0')
app=modal.App('canis-condition-1500-generation')
volume=modal.Volume.from_name('detector-data')
progress=modal.Dict.from_name('canis-condition-generation-progress',create_if_missing=True)

@app.function(image=image,gpu='RTX-PRO-6000',cpu=8,memory=65536,timeout=7200,max_containers=10,
              volumes={'/data':volume},single_use_containers=True)
def generate(run_id,worker,shard):
    directory=Path('/data/datasets')/run_id/'shards'/f'{worker:02d}';directory.mkdir(parents=True,exist_ok=True)
    task=Path('/tmp/shard.json');task.write_text(json.dumps(shard))
    gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'],text=True).strip()
    assert 'RTX PRO 6000' in gpu,gpu
    hardware=dict(gpu=gpu,isaac=Path('/isaac-sim/VERSION').read_text().strip(),worker=worker)
    (directory/'hardware.json').write_text(json.dumps(hardware,indent=2));volume.commit()
    key=f'{run_id}/{worker}';progress[key]={'state':'initializing','frames':0,**hardware};started=time.perf_counter()
    process=subprocess.Popen(['/isaac-sim/python.sh','/workspace/generate_dataset.py','--assets','/assets/warehouse',
        '--plan',str(task),'--out',str(directory),'--allow-root'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    with (directory/'isaac.log').open('w') as log:
        for line in process.stdout:
            log.write(line);log.flush()
            if line.startswith('DATA_PROGRESS '):
                status=json.loads(line.split(' ',1)[1]);status.update(worker=worker,wall_s=round(time.perf_counter()-started,2))
                progress[key]=status;volume.commit();print('SHARD_PROGRESS '+json.dumps(status),flush=True)
    code=process.wait();volume.commit()
    if code or not (directory/'manifest.json').exists():
        status=dict(state='failed',worker=worker,code=code,tail=(directory/'isaac.log').read_text(errors='replace')[-3500:])
        progress[key]=status;return status
    manifest=json.loads((directory/'manifest.json').read_text())
    if len(manifest['frames'])!=150:
        status=dict(state='failed',worker=worker,frames=len(manifest['frames']),tail=(directory/'isaac.log').read_text(errors='replace')[-3500:])
        progress[key]=status;return status
    status={**hardware,'state':'complete','frames':150,'seconds':round(time.perf_counter()-started,2)}
    progress[key]=status;return status

@app.function(image=cpu_image,cpu=8,memory=16384,timeout=1800,volumes={'/data':volume})
def assemble(run_id,plan):
    import shutil,collections,math,io
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image,ImageDraw,ImageFont
    started=time.perf_counter();volume.reload();root=Path('/data/datasets')/run_id
    release=Path('/tmp/canis-release');release.mkdir(exist_ok=True)
    frames=[];counts=[0]*4;seen_hashes=set();split_seeds={k:set() for k in ('train','val','test')};jobs=[]
    for shard in sorted((root/'shards').iterdir()):
        manifest=json.loads((shard/'manifest.json').read_text())
        for f in manifest['frames']:jobs.append((shard,f))
    def validate_copy(job):
        shard,f=job;split=f['split'];name=f['name']
        raw=(shard/'images'/split/(name+'.png')).read_bytes()
        labels=(shard/'labels'/split/(name+'.txt')).read_text()
        sha=hashlib.sha256(raw).hexdigest();assert sha==f['image_sha256']
        cts=[0]*4
        for line in labels.splitlines():
            c,x,y,w,h=map(float,line.split());assert int(c)==c and 0<=c<4 and all(math.isfinite(v) for v in (x,y,w,h))
            assert 0<w<=1 and 0<h<=1 and -1e-5<=x-w/2 and x+w/2<=1+1e-5 and -1e-5<=y-h/2 and y+h/2<=1+1e-5
            cts[int(c)]+=1
        with Image.open(io.BytesIO(raw)) as im:assert im.size==(384,384)
        image=release/'images'/split/(name+'.png');label=release/'labels'/split/(name+'.txt')
        image.parent.mkdir(parents=True,exist_ok=True);label.parent.mkdir(parents=True,exist_ok=True)
        image.write_bytes(raw);label.write_text(labels)
        return f,sha,cts
    with ThreadPoolExecutor(max_workers=32) as pool:
        for f,sha,cts in pool.map(validate_copy,jobs):
            assert sha not in seen_hashes;seen_hashes.add(sha);split_seeds[f['split']].add(f['seed']);frames.append(f)
            counts=[a+b for a,b in zip(counts,cts)]
            if len(frames)%300==0:print('ASSEMBLY_PROGRESS '+str(len(frames)),flush=True)
    assert len(frames)==1500 and not(split_seeds['train']&split_seeds['val'] or split_seeds['train']&split_seeds['test'] or split_seeds['val']&split_seeds['test'])
    assert dict(collections.Counter(f['split'] for f in frames))==plan['counts']
    assert dict(collections.Counter(f['condition'] for f in frames))=={i:375 for i in range(4)}
    yaml='train: images/train\nval: images/val\ntest: images/test\nnames:\n'+''.join(f'  {i}: {name}\n' for i,name in enumerate(plan['classes']))
    (release/'data.yaml').write_text(yaml)
    summary=dict(dataset_id=run_id,schema=plan['schema'],classes=plan['classes'],images=plan['counts'],
                 target_counts={plan['classes'][i]:375 for i in range(4)},annotation_counts=dict(zip(plan['classes'],counts)),
                 seeds_by_split={k:sorted(v) for k,v in split_seeds.items()},resolution=[384,384],
                 categories=dict(collections.Counter(f['category'] for f in frames)),tiers=dict(collections.Counter(f['tier'] for f in frames)),
                 label_policy='One whole visible barrel box with condition; no rust-patch labels. Raw RGB excludes annotation overlays.',
                 source_asset_revision='e4d31c8a323708db4af2f94e4396ca4872457eff')
    (release/'summary.json').write_text(json.dumps(summary,indent=2));(release/'manifest.json').write_text(json.dumps({'frames':frames},indent=2))
    examples=[]
    for split in ('train','val','test'):
        for c in range(4):examples.append(next(f for f in frames if f['split']==split and f['condition']==c))
    sheet=Image.new('RGB',(4*384,3*420),'#15202b');draw=ImageDraw.Draw(sheet);font=ImageFont.load_default(size=16)
    for i,f in enumerate(examples):
        im=Image.open(release/'images'/f['split']/(f['name']+'.png')).convert('RGB');d=ImageDraw.Draw(im);d.rectangle(f['target_box'],outline='#ffb85c',width=2)
        x=i%4*384;y=i//4*420;sheet.paste(im,(x,y));draw.text((x+4,y+386),f"{f['split']} | {plan['classes'][f['condition']]} | {f['category']} T{f['tier']}",font=font,fill='white')
    sheet.save(release/'contact_sheet.jpg',quality=94)
    local_archive=Path('/tmp/dataset.zip')
    with zipfile.ZipFile(local_archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in release.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(release))
    dest=root/'release';dest.mkdir(exist_ok=True)
    def publish(p):
        target=dest/p.relative_to(release);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
    with ThreadPoolExecutor(max_workers=32) as pool:list(pool.map(publish,(p for p in release.rglob('*') if p.is_file())))
    archive=root/'dataset.zip';shutil.copyfile(local_archive,archive)
    summary.update(archive_sha256=hashlib.sha256(local_archive.read_bytes()).hexdigest(),archive_bytes=local_archive.stat().st_size,
                   assembly_seconds=round(time.perf_counter()-started,2))
    (root/'dataset_summary.json').write_text(json.dumps(summary,indent=2));volume.commit();return summary

def finish_existing():
    state=json.loads((ROOT/'.runtime/condition_dataset.json').read_text());run_id=state['dataset_id'];local=Path(state['local']);plan=json.loads((local/'plan.json').read_text())
    with modal.enable_output(),app.run(detach=True):summary=assemble.remote(run_id,plan)
    (local/'summary.json').write_text(json.dumps(summary,indent=2))
    (local/'contact_sheet.jpg').write_bytes(b''.join(volume.read_file(f'/datasets/{run_id}/release/contact_sheet.jpg')))
    print('DATASET_COMPLETE '+json.dumps(summary),flush=True)

def main():
    from dataset_plan import make_plan
    run_id=os.environ.get('CANIS_DATASET_ID') or 'canis_conditions_1500_'+time.strftime('%Y%m%dT%H%M%SZ')
    plan=make_plan(json.loads((ASSETS/'map.json').read_text()));local=ROOT/'out/condition_v2'/run_id;local.mkdir(parents=True,exist_ok=True)
    (local/'plan.json').write_text(json.dumps(plan,indent=2));(ROOT/'.runtime/condition_dataset.json').write_text(json.dumps({'dataset_id':run_id,'local':str(local)}))
    shards=[{**{k:v for k,v in plan.items() if k!='sessions'},'sessions':plan['sessions'][i::10]} for i in range(10)]
    started=time.perf_counter()
    with modal.enable_output(),app.run(detach=True):
        progress[f'{run_id}/0']={'state':'queued','frames':0}
        calls=[generate.spawn(run_id,0,shards[0])]
        print('GENERATION_PREFLIGHT '+json.dumps({'dataset_id':run_id,'first_worker':calls[0].object_id}),flush=True)
        while True:
            status=progress.get(f'{run_id}/0') or {}
            if status.get('state')=='failed':raise RuntimeError(status['tail'])
            if status.get('frames',0)>=10:break
            time.sleep(3)
        calls.extend(generate.spawn(run_id,i,shards[i]) for i in range(1,10))
        print('TEN_WORKERS_LAUNCHED '+json.dumps({'dataset_id':run_id,'calls':[c.object_id for c in calls]}),flush=True)
        previous=None
        while True:
            statuses=[progress.get(f'{run_id}/{i}') or {} for i in range(10)]
            # Surface remote Python exceptions even if the worker could not write
            # a final status, rather than waiting indefinitely on stale progress.
            for i,call in enumerate(calls):
                if statuses[i].get('state') in ('complete','failed'):continue
                try:call.get(timeout=0)
                except TimeoutError:pass
                except Exception as exc:
                    statuses[i]={'state':'failed','worker':i,'tail':str(exc)}
                    progress[f'{run_id}/{i}']=statuses[i]
            if any(s.get('state')=='failed' for s in statuses):
                raise RuntimeError(json.dumps([s for s in statuses if s.get('state')=='failed']))
            count=sum(s.get('frames',0) for s in statuses)
            if count!=previous:print('DATASET_PROGRESS '+json.dumps({'images':count,'total':1500,'complete_workers':sum(s.get('state')=='complete' for s in statuses),'seconds':round(time.perf_counter()-started,1)}),flush=True);previous=count
            if all(s.get('state')=='complete' for s in statuses):break
            time.sleep(5)
        summary=assemble.remote(run_id,plan)
    (local/'summary.json').write_text(json.dumps(summary,indent=2))
    for name in ('contact_sheet.jpg',):
        source=f'/datasets/{run_id}/release/{name}'
        with (local/name).open('wb') as f:
            for chunk in volume.read_file(source):f.write(chunk)
    print('DATASET_COMPLETE '+json.dumps(summary),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['assemble']:finish_existing()
    else:main()
