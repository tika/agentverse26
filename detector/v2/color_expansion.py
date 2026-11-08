"""Append 750 yellow and 250 blue-teal warehouse frames without changing old splits."""
import json,os,sys,time,subprocess,random
from pathlib import Path
import modal
ROOT=Path(__file__).resolve().parents[2] if modal.is_local() else Path('/workspace')
WAREHOUSE=ROOT/'.runtime/drum-pilot15-assets/CANIS_YOLO_DRUM_ASSETS_FOUR_CONDITIONS_V1/warehouse-v3' if modal.is_local() else Path('/assets/warehouse')
image=(modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',add_python='3.13',setup_dockerfile_commands=['USER root'])
 .entrypoint([]).env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all'}))
if modal.is_local():
 image=(image.add_local_dir(WAREHOUSE,'/assets/warehouse',copy=True)
 .add_local_dir(ROOT/'sim','/workspace/sim',copy=True,ignore=['out/**','__pycache__/**','**/__pycache__/**','*.usda'])
 .add_local_dir(ROOT/'detector','/workspace/detector',copy=True,ignore=['__pycache__/**','**/__pycache__/**']))
app=modal.App('canis-color-expansion');volume=modal.Volume.from_name('detector-data')
progress=modal.Dict.from_name('canis-color-expansion-progress',create_if_missing=True)
CLASSES=['normal','rust','bulge','rust_and_bulge']

def yellow_plan():
 layout=json.loads((WAREHOUSE/'map.json').read_text());sessions=[]
 for i in range(25):
  seed=260812000+i;rng=random.Random(seed);split='train' if i<20 else 'val' if i<22 else 'test';conditions={};targets=[]
  for tier in (1,2):
   pool=[d for d in layout['drums'] if d['category']=='LLW' and d['location']['tier']==tier and d['location']['depth']==1]
   chosen=rng.sample(pool,15)
   for j,d in enumerate(chosen):
    c=(j+i+(tier-1)*15)%4;conditions[d['id']]=c;targets.append({'drum_id':d['id'],'condition':c,'category':'LLW','tier':tier,'source_color':'yellow'})
  selected=[d for d in layout['drums'] if d['id'] in conditions]
  for d in layout['drums']:
   if d['category']=='LLW' and d['location']['tier']<=2 and d['id'] not in conditions and any(abs(d['x']-p['x'])<1.35 and abs(d['y']-p['y'])<1.3 for p in selected):conditions[d['id']]=rng.randrange(4)
  rng.shuffle(targets);frames=[]
  for j,d in enumerate(targets):
   angle=rng.uniform(-60,60);dist=rng.uniform(1.25,1.85) if d['tier']==1 else rng.uniform(1.9,2.5)
   frames.append({**d,'name':f'y{seed}_f{j:02d}','angle_deg':angle,'distance_m':dist,'exposure_scale':rng.uniform(.95,1.35),'jitter_x_m':rng.uniform(-.12,.12)})
  sessions.append({'seed':seed,'split':split,'conditions':conditions,'frames':frames})
 return {'classes':CLASSES,'sessions':sessions}

def blue_plan():
 layout=json.loads((WAREHOUSE/'map.json').read_text());sessions=[]
 for i in range(10):
  seed=260814000+i;rng=random.Random(seed);split='train' if i<8 else 'val' if i<9 else 'test';conditions={};targets=[];serial=0
  for tier,n in ((1,12+i%2),(2,13-i%2)):
   pool=[d for d in layout['drums'] if d['category']=='ILW' and d['location']['tier']==tier and d['location']['depth']==1]
   for d in rng.sample(pool,n):
    c=(i*25+serial)%4;serial+=1;conditions[d['id']]=c;targets.append({'drum_id':d['id'],'condition':c,'category':'ILW','tier':tier,'source_color':'blue'})
  selected=[d for d in layout['drums'] if d['id'] in conditions]
  for d in layout['drums']:
   if d['category']=='ILW' and d['location']['tier']<=2 and d['id'] not in conditions and any(abs(d['x']-p['x'])<1.35 and abs(d['y']-p['y'])<1.3 for p in selected):conditions[d['id']]=rng.randrange(4)
  rng.shuffle(targets);frames=[]
  for j,d in enumerate(targets):
   distance=rng.uniform(1.4,2.1) if d['tier']==1 else rng.uniform(2.0,2.65)
   frames.append({**d,'name':f'i{seed}_f{j:02d}','angle_deg':rng.uniform(-60,60),'distance_m':distance,'exposure_scale':rng.uniform(.95,1.35),'jitter_x_m':rng.uniform(-.12,.12)})
  sessions.append({'seed':seed,'split':split,'conditions':conditions,'frames':frames})
 return {'classes':CLASSES,'sessions':sessions}

@app.function(image=image,gpu='RTX-PRO-6000',cpu=8,memory=65536,timeout=3600,max_containers=10,single_use_containers=True,volumes={'/data':volume})
def render(kind,run_id,worker,shard):
 key=f'{run_id}/{kind}{worker}';out=Path('/data/color_expansions')/run_id/'shards'/f'{kind}{worker}';out.mkdir(parents=True,exist_ok=True)
 expected=sum(len(s.get('frames',range(5))) for s in shard['sessions']);started=time.perf_counter()
 gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True).strip();assert 'RTX PRO 6000' in gpu
 progress[key]={'state':'initializing','frames':0,'expected':expected,'gpu':gpu}
 task=Path('/tmp/plan.json');task.write_text(json.dumps(shard))
 script='generate_dataset.py'
 args=['/isaac-sim/python.sh','/workspace/sim/detector_studio_v2/'+script,'--assets','/assets/warehouse','--plan',str(task),'--out',str(out),'--allow-root']
 try:
  process=subprocess.Popen(args,cwd='/workspace/sim',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
  with (out/'isaac.log').open('w') as log:
   for line in process.stdout:
    log.write(line);log.flush()
    if line.startswith('DATA_PROGRESS '):
     status=json.loads(line.split(' ',1)[1]);status.update(expected=expected,gpu=gpu,worker=worker,kind=kind,seconds=round(time.perf_counter()-started,2));progress[key]=status;volume.commit();print('EXPANSION_PROGRESS '+json.dumps(status),flush=True)
  code=process.wait();volume.commit();manifest=json.loads((out/'manifest.json').read_text()) if (out/'manifest.json').exists() else {}
  if code or len(manifest.get('frames',[]))!=expected:raise RuntimeError((out/'isaac.log').read_text(errors='replace')[-4000:])
  status={'state':'complete','frames':expected,'expected':expected,'gpu':gpu,'seconds':round(time.perf_counter()-started,2)};progress[key]=status;return status
 except Exception as e:
  status={'state':'failed','frames':(progress.get(key) or {}).get('frames',0),'error':str(e)[-4000:]};progress[key]=status;volume.commit();return status

def start(kind):
 pointer=ROOT/'.runtime/color_expansion.json'
 if pointer.exists():state=json.loads(pointer.read_text())
 else:
  state={'run_id':'canis_colors_'+time.strftime('%Y%m%dT%H%M%SZ'),'base_dataset':'canis_conditions_1500_20261108T043410Z','old_comparison':'compare_20261108T043410Z','calls':{},'requested':{'yellow':750,'blue':250}}
  pointer.write_text(json.dumps(state,indent=2))
 plan=yellow_plan() if kind=='yellow' else blue_plan();folder=ROOT/'out/color_expansion'/state['run_id'];folder.mkdir(parents=True,exist_ok=True);(folder/f'{kind}_plan.json').write_text(json.dumps(plan,indent=2))
 shards=[{**plan,'sessions':plan['sessions'][i::5]} for i in range(5)]
 with modal.enable_output(),app.run(detach=True):
  workers=list(map(int,sys.argv[2].split(','))) if len(sys.argv)>2 else list(range(5))
  for i in workers:
   shard=shards[i]
   name=f'{kind}{i}';progress[f'{state["run_id"]}/{name}']={'state':'queued','frames':0};state['calls'][name]=render.spawn(kind,state['run_id'],i,shard).object_id
   pointer.write_text(json.dumps(state,indent=2))
 print('EXPANSION_STARTED '+json.dumps(state),flush=True)

if __name__=='__main__':start(sys.argv[1])
