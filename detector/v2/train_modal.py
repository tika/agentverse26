"""Train YOLO26 nano/small concurrently on one RTX PRO 6000 each."""
import json,sys,time,subprocess,zipfile
from pathlib import Path
import modal
ROOT=Path(__file__).resolve().parents[2] if modal.is_local() else Path('/workspace')
sys.path.insert(0,str(ROOT/'detector'))
from training_image import image
app=modal.App('canis-condition-nano-small-training')
data=modal.Volume.from_name('detector-data');models=modal.Volume.from_name('detector-models')
progress=modal.Dict.from_name('canis-condition-training-progress',create_if_missing=True)

@app.function(image=image,gpu='RTX-PRO-6000',cpu=12,memory=49152,timeout=3600,max_containers=2,
              volumes={'/data':data,'/models':models},single_use_containers=True)
def train(scale,dataset_id,comparison_id):
    import torch
    assert torch.cuda.device_count()==1 and 'RTX PRO 6000' in torch.cuda.get_device_name(0)
    data.reload();root=Path('/tmp/dataset');root.mkdir()
    with zipfile.ZipFile(Path('/data/datasets')/dataset_id/'dataset.zip') as z:z.extractall(root)
    run=Path('/models/condition_v2')/comparison_id/f'yolo26{scale}';run.mkdir(parents=True,exist_ok=True)
    (run/'dataset.json').write_text(json.dumps({'dataset_id':dataset_id,'comparison_id':comparison_id}))
    process=subprocess.Popen([sys.executable,'/workspace/detector/v2/train_compare.py','--scale',scale,'--data',str(root),'--run',str(run)],
                             stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    with (run/'train.log').open('w') as log:
        for line in process.stdout:
            log.write(line);log.flush()
            if line.startswith(('TRAIN_PROGRESS ','TRAIN_EVALUATING ','MODEL_COMPLETE ')):
                models.commit();progress[f'{comparison_id}/{scale}']=json.loads((run/'progress.json').read_text());print(line.rstrip(),flush=True)
    code=process.wait();models.commit()
    if code:
        status={'state':'failed','code':code,'tail':(run/'train.log').read_text(errors='replace')[-5000:]};progress[f'{comparison_id}/{scale}']=status;return status
    result=json.loads((run/'results.json').read_text());result.update(dataset_id=dataset_id,comparison_id=comparison_id)
    (run/'results.json').write_text(json.dumps(result,indent=2));models.commit()
    progress[f'{comparison_id}/{scale}']={'state':'complete','results':result};return result

def main():
    state=json.loads((ROOT/'.runtime/condition_dataset.json').read_text());dataset_id=state['dataset_id']
    comparison_id=dataset_id.replace('canis_conditions_1500_','compare_')
    (ROOT/'.runtime/condition_models.json').write_text(json.dumps({'dataset_id':dataset_id,'comparison_id':comparison_id}))
    with modal.enable_output(),app.run(detach=True):
        calls=[train.spawn(scale,dataset_id,comparison_id) for scale in ('n','s')]
        print('TWO_TRAINERS_LAUNCHED '+json.dumps({'comparison_id':comparison_id,'calls':[c.object_id for c in calls]}),flush=True)
        results=[call.get() for call in calls]
    out=ROOT/'out/condition_v2'/comparison_id;out.mkdir(parents=True,exist_ok=True)
    for scale,result in zip(('n','s'),results):
        (out/f'yolo26{scale}_results.json').write_text(json.dumps(result,indent=2))
        if result.get('state')=='failed':raise RuntimeError(result['tail'])
    print('COMPARISON_COMPLETE '+comparison_id,flush=True)

if __name__=='__main__':main()
