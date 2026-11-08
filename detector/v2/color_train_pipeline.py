"""Assemble the 2,500-image extension, shuffle training, then retrain small."""
import json,sys,time,zipfile,subprocess,hashlib,random,io,collections,shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import modal
ROOT=Path(__file__).resolve().parents[2] if modal.is_local() else Path('/workspace')
sys.path.insert(0,str(ROOT/'detector'))
if modal.is_local():
 from training_image import image as training_image
else:
 training_image=modal.Image.debian_slim(python_version='3.12')
cpu=modal.Image.debian_slim(python_version='3.12').pip_install('pillow==11.3.0')
app=modal.App('canis-color-retrain-small');data=modal.Volume.from_name('detector-data');models=modal.Volume.from_name('detector-models')
status=modal.Dict.from_name('canis-color-training-progress',create_if_missing=True)
NAMES=['normal','rust','bulge','rust_and_bulge']

@app.function(image=cpu,cpu=8,memory=16384,timeout=1200,volumes={'/data':data})
def assemble(state):
 from PIL import Image,ImageDraw
 started=time.perf_counter();data.reload();remote=Path('/data/color_expansions')/state['run_id'];local=Path('/tmp/release');local.mkdir()
 with zipfile.ZipFile(Path('/data/datasets')/state['base_dataset']/'dataset.zip') as z:z.extractall(local)
 base=json.loads((local/'manifest.json').read_text())['frames'];hashes={f['image_sha256'] for f in base};assert len(base)==1500 and len(hashes)==1500
 for f in base:
  f.update(origin='legacy',source_color='yellow' if f['category']=='LLW' else 'metallic')
 jobs=[]
 for shard_name in sorted(state['calls']):
  shard=remote/'shards'/shard_name
  manifest_path=shard/'selected_manifest.json' if (shard/'selected_manifest.json').exists() else shard/'manifest.json'
  m=json.loads(manifest_path.read_text());expected=150 if shard.name.startswith('yellow') else 50;assert len(m['frames'])==expected
  for f in m['frames']:jobs.append((shard,f))
 assert len(jobs)==1000
 def copy_validate(job):
  shard,f=job;split=f['split'];source_split=f.get('capture_split',split);name=f['name'];raw=(shard/'images'/source_split/(name+'.png')).read_bytes();label=(shard/'labels'/source_split/(name+'.txt')).read_text()
  assert hashlib.sha256(raw).hexdigest()==f['image_sha256']
  with Image.open(io.BytesIO(raw)) as im:assert im.size==(384,384)
  for line in label.splitlines():
   c,x,y,w,h=map(float,line.split());assert c in (0,1,2,3) and 0<w<=1 and 0<h<=1 and min(x-w/2,y-h/2)>=-1e-5 and max(x+w/2,y+h/2)<=1.00001
  (local/'images'/split/(name+'.png')).write_bytes(raw);(local/'labels'/split/(name+'.txt')).write_text(label)
  f['origin']='new';return f
 frames=list(base)
 with ThreadPoolExecutor(max_workers=32) as pool:
  for f in pool.map(copy_validate,jobs):
   assert f['image_sha256'] not in hashes;hashes.add(f['image_sha256']);frames.append(f)
 assert len(frames)==2500
 expected={'train':2000,'val':235,'test':265};assert dict(collections.Counter(f['split'] for f in frames))==expected
 seeds={s:{f['seed'] for f in frames if f['split']==s} for s in expected};assert not(seeds['train']&seeds['val'] or seeds['train']&seeds['test'] or seeds['val']&seeds['test'])
 train=[f for f in frames if f['split']=='train'];random.Random(42).shuffle(train)
 (local/'train.txt').write_text('\n'.join('./images/train/'+f['name']+'.png' for f in train)+'\n')
 (local/'data.yaml').write_text('train: train.txt\nval: images/val\ntest: images/test\nnames:\n'+''.join(f'  {i}: {v}\n' for i,v in enumerate(NAMES)))
 manifest={'frames':frames};(local/'manifest.json').write_text(json.dumps(manifest,indent=2))
 summary={'dataset_id':state['run_id'],'base_dataset':state['base_dataset'],'images':expected,'total':2500,'primary_target_colors':dict(collections.Counter(f['source_color'] for f in frames)),
 'new_images':{'yellow':750,'blue':250},'classes':NAMES,'resolution':[384,384],'train_list_shuffled_seed':42,'split_policy':'Original split unchanged; extra scene seeds disjoint by split; no held-out data enters training.',
 'blue_design':'User CANIS_BLUE_TEAL_ILW_ASSETS: original warehouse 1.2m-high, nominal 0.8m-diameter ILW profile, metallic blue-teal shaders, localized bulge lobe and ILW pitting/staining recipe. All 24 supplied textures matched the original warehouse pack by SHA-256.',
 'blue_domain':'Warehouse context, tiers 1–2, independent seeds, randomized defects, printed IDs, lighting and viewpoints. Earlier blue-painted LLW studio captures are excluded.',
 'material_targets':{'yellow_LLW':1500,'blue_teal_ILW':1000}}
 (local/'summary.json').write_text(json.dumps(summary,indent=2))
 sheet=Image.new('RGB',(4*384,3*410),'#202b38');draw=ImageDraw.Draw(sheet)
 for row,group in enumerate(('legacy_yellow','new_yellow','new_blue')):
  for c in range(4):
   f=next(f for f in frames if f['origin']+'_'+f['source_color']==group and f['condition']==c and f['split']=='test');im=Image.open(local/'images/test'/(f['name']+'.png')).convert('RGB');ImageDraw.Draw(im).rectangle(f['target_box'],outline='#ffc55e',width=2)
   sheet.paste(im,(c*384,row*410));draw.text((c*384+4,row*410+386),group+' | '+NAMES[c],fill='white')
 sheet.save(local/'contact_sheet.jpg',quality=93)
 archive=Path('/tmp/dataset.zip')
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  for p in local.rglob('*'):
   if p.is_file() and p.name not in ('runtime.yaml',):z.write(p,p.relative_to(local))
 release=remote/'release';release.mkdir(exist_ok=True)
 def publish(p):
  t=release/p.relative_to(local);t.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,t)
 with ThreadPoolExecutor(max_workers=32) as pool:list(pool.map(publish,(p for p in local.rglob('*') if p.is_file())))
 shutil.copyfile(archive,remote/'dataset.zip');summary.update(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),archive_bytes=archive.stat().st_size,assembly_seconds=round(time.perf_counter()-started,2))
 (remote/'dataset_summary.json').write_text(json.dumps(summary,indent=2));data.commit();print('COLOR_DATASET_COMPLETE '+json.dumps(summary),flush=True);return summary

@app.function(image=training_image,gpu='RTX-PRO-6000',cpu=12,memory=49152,timeout=3600,max_containers=1,volumes={'/data':data,'/models':models},single_use_containers=True)
def train(state):
 import torch
 assert torch.cuda.device_count()==1 and 'RTX PRO 6000' in torch.cuda.get_device_name(0)
 data.reload();models.reload();root=Path('/tmp/data');root.mkdir()
 with zipfile.ZipFile(Path('/data/color_expansions')/state['run_id']/'dataset.zip') as z:z.extractall(root)
 comparison=state['run_id'].replace('canis_colors_','compare_colors_');run=Path('/models/condition_v2')/comparison/'yolo26s';run.mkdir(parents=True)
 (run/'dataset.json').write_text(json.dumps(state,indent=2))
 command=[sys.executable,'/workspace/detector/v2/train_compare.py','--scale','s','--data',str(root),'--run',str(run)]
 with (run/'train.log').open('w') as log:
  process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
  for line in process.stdout:
   log.write(line);log.flush()
   if line.startswith(('TRAIN_PROGRESS ','TRAIN_EVALUATING ','MODEL_COMPLETE ')):
    models.commit();status[comparison]=json.loads((run/'progress.json').read_text());print(line.rstrip(),flush=True)
  code=process.wait()
 if code:models.commit();raise RuntimeError((run/'train.log').read_text(errors='replace')[-5000:])
 result=json.loads((run/'results.json').read_text());result.update(dataset_id=state['run_id'],comparison_id=comparison);(run/'results.json').write_text(json.dumps(result,indent=2))
 status[comparison]={'state':'comparing_old_model'};models.commit()
 old=Path('/models/condition_v2')/state['old_comparison']/'yolo26s/best.pt'
 compare=subprocess.run([sys.executable,'/workspace/detector/v2/compare_color_models.py','--data',str(root),'--run',str(run),'--old',str(old)],capture_output=True,text=True)
 (run/'comparison.log').write_text(compare.stdout+compare.stderr);models.commit()
 if compare.returncode:raise RuntimeError(compare.stdout[-1000:]+compare.stderr[-4000:])
 report=json.loads((run/'comparison.json').read_text());status[comparison]={'state':'complete','groups':report['groups']};print('COLOR_MODEL_COMPLETE '+json.dumps(report['groups']),flush=True);return report

@app.function(image=training_image,gpu='RTX-PRO-6000',cpu=8,memory=32768,timeout=1200,volumes={'/data':data,'/models':models},single_use_containers=True)
def compare_only(state):
 data.reload();models.reload();root=Path('/tmp/data');root.mkdir()
 with zipfile.ZipFile(Path('/data/color_expansions')/state['run_id']/'dataset.zip') as z:z.extractall(root)
 (root/'runtime.yaml').write_text('path: '+str(root)+'\ntrain: train.txt\nval: images/val\ntest: images/test\nnames:\n'+''.join(f'  {i}: {v}\n' for i,v in enumerate(NAMES)))
 comparison=state['run_id'].replace('canis_colors_','compare_colors_');run=Path('/models/condition_v2')/comparison/'yolo26s';old=Path('/models/condition_v2')/state['old_comparison']/'yolo26s/best.pt'
 proc=subprocess.run([sys.executable,'/workspace/detector/v2/compare_color_models.py','--data',str(root),'--run',str(run),'--old',str(old)],capture_output=True,text=True)
 (run/'comparison.log').write_text(proc.stdout+proc.stderr);models.commit()
 if proc.returncode:raise RuntimeError(proc.stdout[-1000:]+proc.stderr[-4000:])
 result=json.loads((run/'comparison.json').read_text());status[comparison]={'state':'complete','groups':result['groups']};return result

def finish_comparison():
 state=json.loads((ROOT/'.runtime/color_expansion.json').read_text())
 with modal.enable_output(),app.run(detach=True):report=compare_only.remote(state)
 out=ROOT/'out/color_expansion'/state['run_id'];(out/'comparison.json').write_text(json.dumps(report,indent=2))
 comparison=state['run_id'].replace('canis_colors_','compare_colors_')
 for name in ('comparison.md','results.json','sampler.json'):
  (out/name).write_bytes(b''.join(models.read_file(f'/condition_v2/{comparison}/yolo26s/{name}')))
 print('COLOR_COMPARISON_COMPLETE '+json.dumps(report['groups']),flush=True)

@app.function(image=training_image,gpu='RTX-PRO-6000',cpu=12,memory=49152,timeout=1800,volumes={'/data':data,'/models':models},single_use_containers=True)
def continue_checkpoint(state):
 data.reload();models.reload();root=Path('/tmp/data');root.mkdir()
 with zipfile.ZipFile(Path('/data/color_expansions')/state['run_id']/'dataset.zip') as z:z.extractall(root)
 comparison=state['run_id'].replace('canis_colors_','compare_colors_')+'_continued';run=Path('/models/condition_v2')/comparison/'yolo26s';run.mkdir(parents=True)
 old=Path('/models/condition_v2')/state['old_comparison']/'yolo26s/best.pt'
 args=[sys.executable,'/workspace/detector/v2/train_compare.py','--scale','s','--data',str(root),'--run',str(run),'--initial',str(old),'--epochs','20','--lr','.0001']
 with (run/'train.log').open('w') as log:
  proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
  for line in proc.stdout:
   log.write(line);log.flush()
   if line.startswith(('TRAIN_PROGRESS ','TRAIN_EVALUATING ','MODEL_COMPLETE ')):
    models.commit();status[comparison]=json.loads((run/'progress.json').read_text());print(line.rstrip(),flush=True)
  code=proc.wait()
 if code:models.commit();raise RuntimeError((run/'train.log').read_text()[-5000:])
 r=json.loads((run/'results.json').read_text());r.update(dataset_id=state['run_id'],comparison_id=comparison);(run/'results.json').write_text(json.dumps(r,indent=2));models.commit()
 proc=subprocess.run([sys.executable,'/workspace/detector/v2/compare_color_models.py','--data',str(root),'--run',str(run),'--old',str(old)],capture_output=True,text=True)
 (run/'comparison.log').write_text(proc.stdout+proc.stderr);models.commit()
 if proc.returncode:raise RuntimeError(proc.stdout[-500:]+proc.stderr[-3500:])
 r=json.loads((run/'comparison.json').read_text());status[comparison]={'state':'complete','groups':r['groups']};return r

def finish_continuation():
 state=json.loads((ROOT/'.runtime/color_expansion.json').read_text());comparison=state['run_id'].replace('canis_colors_','compare_colors_')+'_continued'
 with modal.enable_output(),app.run(detach=True):r=continue_checkpoint.remote(state)
 out=ROOT/'out/color_expansion'/state['run_id']/'continued';out.mkdir(exist_ok=True);(out/'comparison.json').write_text(json.dumps(r,indent=2))
 for name in ('comparison.md','results.json','sampler.json'):(out/name).write_bytes(b''.join(models.read_file(f'/condition_v2/{comparison}/yolo26s/{name}')))
 print('CONTINUATION_COMPLETE '+json.dumps(r['groups']),flush=True)

def main():
 state=json.loads((ROOT/'.runtime/color_expansion.json').read_text());progress=modal.Dict.from_name('canis-color-expansion-progress');last=-1
 while True:
  s={k:progress.get(state['run_id']+'/'+k) or {} for k in state['calls']}
  ready=ROOT/'out/color_expansion'/state['run_id']/'blue_selection_ready.json'
  if ready.exists():
   for k,n in json.loads(ready.read_text()).items():s[k]={'state':'complete','frames':n}
  for k,call in state['calls'].items():
   if s[k].get('state') in ('complete','failed'):continue
   try:modal.FunctionCall.from_id(call).get(timeout=0)
   except TimeoutError:pass
   except Exception as e:raise RuntimeError(k+': '+str(e))
  failed={k:v for k,v in s.items() if v.get('state')=='failed'}
  if failed:raise RuntimeError(json.dumps(failed))
  count=sum(x.get('frames',0) for x in s.values())
  if count!=last:print('EXPANSION_TOTAL',count,1000,flush=True);last=count
  if len(s)==10 and all(x.get('state')=='complete' for x in s.values()):break
  time.sleep(5)
 with modal.enable_output(),app.run(detach=True):
  summary=assemble.remote(state)
  out=ROOT/'out/color_expansion'/state['run_id'];out.mkdir(parents=True,exist_ok=True);(out/'dataset_summary.json').write_text(json.dumps(summary,indent=2))
  (out/'contact_sheet.jpg').write_bytes(b''.join(data.read_file(f'/color_expansions/{state["run_id"]}/release/contact_sheet.jpg')))
  report=train.remote(state)
  (out/'comparison.json').write_text(json.dumps(report,indent=2))
  comparison=state['run_id'].replace('canis_colors_','compare_colors_')
  for name in ('comparison.md','results.json','sampler.json'):
   (out/name).write_bytes(b''.join(models.read_file(f'/condition_v2/{comparison}/yolo26s/{name}')))
 print('COLOR_RETRAIN_COMPLETE',str(out),flush=True)
if __name__=='__main__':
 if sys.argv[1:]==['continue']:finish_continuation()
 elif sys.argv[1:]==['compare']:finish_comparison()
 else:main()
