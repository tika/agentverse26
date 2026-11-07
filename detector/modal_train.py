"""Train ONE YOLO26s on eight H100s, then evaluate after releasing the training node."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime,timezone
import modal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,'/workspace/detector')
from training_image import image

app=modal.App('agentverse-yolo26s-training')
data_volume=modal.Volume.from_name('detector-data',environment_name='main')
models_volume=modal.Volume.from_name('detector-models',environment_name='main',create_if_missing=True)
MOUNTS={'/datasets':data_volume,'/models':models_volume}


def prepare_dataset():
    """One sequential ZIP read avoids thousands of network file opens on eight GPUs."""
    import hashlib,zipfile
    release=Path('/tmp/detector_dataset/barrels_v2_1200')
    if not release.exists():
        archive=Path('/datasets/archives/barrels_v2_1200.zip')
        expected='0aceb3703830010380ef1db2e04de3261a3aa2ae6f8858e8100a59bf9eeffb6f'
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected,'Dataset archive hash changed'
        with zipfile.ZipFile(archive) as z:z.extractall('/tmp/detector_dataset')
    manifest=json.loads((release/'manifest.json').read_text())
    assert manifest['images']==1200 and manifest['classes']==['drum','corrosion','bulge']
    assert manifest['split_counts']=={'train':900,'val':150,'test':150}
    for record in manifest['records']:
        for item in record['files'].values():
            assert hashlib.sha256((release/item['path']).read_bytes()).hexdigest()==item['sha256']
    # Make resolution independent of the framework's default datasets directory.
    (release/'training.yaml').write_text(f'path: {release}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: drum\n  1: corrosion\n  2: bulge\n')
    return release


def run_child(args,run_dir,log_name,markers,timeout):
    import threading
    process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,
                             cwd='/workspace',env={**os.environ,'PYTHONUNBUFFERED':'1'})
    timer=threading.Timer(timeout,process.kill);timer.start()
    try:
        with (run_dir/log_name).open('w') as log:
            for line in process.stdout:
                log.write(line);log.flush()
                if any(line.startswith(tag) for tag in markers):
                    models_volume.commit();print(line.rstrip(),flush=True)
            code=process.wait()
    finally:timer.cancel()
    models_volume.commit()
    if code:
        print((run_dir/log_name).read_text()[-12000:],flush=True)
        raise RuntimeError(f'Subprocess failed ({code}); saved {log_name}')


@app.function(image=image,gpu='H100:8',cpu=16,memory=65536,timeout=3600,
              volumes=MOUNTS,single_use_containers=True,max_containers=1)
def train(run_id,source_commit):
    import hashlib,platform
    import torch,ultralytics
    started=time.perf_counter();run_dir=Path('/models/runs')/run_id
    run_dir.mkdir(parents=True,exist_ok=False)
    inventory=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,uuid,driver_version','--format=csv,noheader'],text=True)
    assert torch.cuda.is_available() and torch.cuda.device_count()==8
    assert len(inventory.strip().splitlines())==8 and all('H100' in x for x in inventory.strip().splitlines())
    (run_dir/'hardware.json').write_text(json.dumps(dict(gpus=inventory.splitlines(),count=8,torch=torch.__version__,
                cuda=torch.version.cuda,ultralytics=ultralytics.__version__,python=platform.python_version(),
                topology=subprocess.check_output(['nvidia-smi','topo','-m'],text=True)),indent=2))
    release=prepare_dataset()
    metadata=dict(run_id=run_id,model='YOLO26s',source_commit=source_commit,dataset='barrels_v2_1200',
                  dataset_manifest_sha256=hashlib.sha256((release/'manifest.json').read_bytes()).hexdigest(),
                  classes=['drum','corrosion','bulge'],global_batch=64,epochs_cap=40,patience=10,
                  world_size=8,gpu_type='H100',created_utc=datetime.now(timezone.utc).isoformat())
    (run_dir/'run_manifest.json').write_text(json.dumps(metadata,indent=2))
    (run_dir/'progress.json').write_text(json.dumps(dict(state='initializing',epoch=0,max_epochs=40,world_size=8)))
    models_volume.commit()
    print('TRAIN_NODE_READY '+json.dumps(metadata),flush=True)
    from ultralytics import YOLO
    weights=Path('/tmp/yolo26s.pt')
    model=YOLO('yolo26s.pt')
    import shutil
    shutil.copy2('yolo26s.pt',weights)
    del model
    args=[sys.executable,'-m','torch.distributed.run','--standalone','--nnodes=1','--nproc_per_node=8',
          '/workspace/detector/train_yolo26s.py','--run-dir',str(run_dir),
          '--data',str(release/'training.yaml'),'--weights',str(weights)]
    run_child(args,run_dir,'training.log',('TRAIN_PROGRESS ','TRAIN_COMPLETE '),timeout=3000)
    ranks=[json.loads(p.read_text()) for p in sorted((run_dir/'ranks').glob('rank_*.json'))]
    assert {p['rank'] for p in ranks}==set(range(8)) and all(p['world_size']==8 for p in ranks)
    result=dict(run_id=run_id,training_node_seconds=time.perf_counter()-started,rank_count=len(ranks),
                best_bytes=(run_dir/'best.pt').stat().st_size)
    (run_dir/'training_runtime.json').write_text(json.dumps(result,indent=2));models_volume.commit()
    return result


@app.function(image=image,gpu='L4',cpu=4,memory=16384,timeout=1800,volumes=MOUNTS,
              single_use_containers=True,max_containers=1)
def evaluate(run_id):
    models_volume.reload();run_dir=Path('/models/runs')/run_id
    release=prepare_dataset()
    run_child([sys.executable,'/workspace/detector/evaluate_yolo26s.py','--run-dir',str(run_dir),
               '--data',str(release/'training.yaml'),'--dataset',str(release)],run_dir,'evaluation.log',
               ('EVAL_PROGRESS ','EVAL_COMPLETE '),timeout=1500)
    result=json.loads((run_dir/'evaluation/results.json').read_text())
    models_volume.commit()
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w:gz') as tar:
        for path in run_dir.rglob('*'):
            if path.is_file() and path.suffix in ('.json','.jsonl','.csv','.yaml','.md','.png','.jpg'):
                if path.name=='predictions.json':continue
                tar.add(path,arcname=str(path.relative_to(run_dir)))
    return dict(results=result,archive=archive.getvalue())


def main():
    sys.path.insert(0,str(ROOT))
    from detector.dataset_release import check_workspace
    check_workspace('paramsachdeva07')
    run_id='yolo26s_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6]
    output=ROOT/'out/detector_training'/run_id;output.mkdir(parents=True)
    (ROOT/'out/detector_training/latest.json').write_text(json.dumps(dict(run_id=run_id,local_path=str(output)),indent=2))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    print('TRAIN_RUN_ID '+run_id,flush=True)
    with modal.enable_output(),app.run():
        result=train.remote(run_id,commit)
        (output/'training_runtime.json').write_text(json.dumps(result,indent=2));print('TRAINING_FINISHED '+json.dumps(result),flush=True)
        evaluated=evaluate.remote(run_id)
    with tarfile.open(fileobj=io.BytesIO(evaluated['archive'])) as tar:tar.extractall(output,filter='data')
    print('TRAINING_AND_TEST_COMPLETE '+json.dumps(evaluated['results']),flush=True)
    print('LOCAL_RESULTS '+str(output),flush=True)


if __name__=='__main__':main()
