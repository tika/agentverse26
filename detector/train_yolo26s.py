"""One YOLO26s run; torchrun preserves callbacks for single or distributed training."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import time


def atomic_json(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2,allow_nan=False));temp.replace(path)


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--data',required=True);p.add_argument('--weights',required=True)
    p.add_argument('--expected-world-size',type=int,required=True)
    a=p.parse_args();rank=int(os.environ['RANK']);world=int(os.environ['WORLD_SIZE'])
    local=int(os.environ['LOCAL_RANK'])
    import torch
    import ultralytics
    from ultralytics import YOLO
    assert world==a.expected_world_size and torch.cuda.device_count()==world
    torch.cuda.set_device(local)
    torch.set_num_threads(2)
    (a.run_dir/'ranks').mkdir(parents=True,exist_ok=True)
    atomic_json(a.run_dir/'ranks'/f'rank_{rank}.json',dict(rank=rank,world_size=world,local_rank=local,
                device=torch.cuda.get_device_name(local),pid=os.getpid()))
    model=YOLO(a.weights)
    start=time.perf_counter();epoch_durations=[]

    def on_save(trainer):
        if rank!=0:return
        # Keep an atomic optimizer-bearing checkpoint before final_eval strips
        # library last.pt/best.pt. The API never loads a checkpoint mid-write.
        if trainer.last.exists():
            temp=a.run_dir/'resume_last.tmp'
            shutil.copy2(trainer.last,temp);temp.replace(a.run_dir/'resume_last.pt')

    def on_epoch(trainer):
        if rank!=0:return
        metrics={k:float(v) for k,v in trainer.metrics.items() if math.isfinite(float(v))}
        duration=float(getattr(trainer,'epoch_time',0))
        if duration>0:epoch_durations.append(duration)
        mean=sum(epoch_durations[-5:])/len(epoch_durations[-5:]) if epoch_durations else None
        completed_epoch=min(trainer.epoch+1,trainer.epochs)
        record=dict(state='training',phase='final_validation' if trainer.epoch>=trainer.epochs else 'epoch',model='YOLO26s',run_id=a.run_dir.name,epoch=completed_epoch,
                    max_epochs=trainer.epochs,metrics=metrics,best_fitness=float(trainer.best_fitness),
                    epoch_seconds=duration,elapsed_seconds=time.perf_counter()-start,
                    eta_seconds=max(0,trainer.epochs-completed_epoch)*mean if mean else None,
                    world_size=world,global_batch=64)
        atomic_json(a.run_dir/'progress.json',record)
        with (a.run_dir/'epoch_events.jsonl').open('a') as file:file.write(json.dumps(record)+'\n')
        print('TRAIN_PROGRESS '+json.dumps(record),flush=True)

    model.add_callback('on_model_save',on_save)
    model.add_callback('on_fit_epoch_end',on_epoch)
    # Batch is global and stays 64 when switching from eight H100s to one RTX.
    model.train(data=a.data,device=list(range(world)),imgsz=640,batch=64,epochs=40,patience=10,
                project=str(a.run_dir),name='train',exist_ok=True,pretrained=True,
                optimizer='AdamW',lr0=.001,lrf=.01,weight_decay=.0005,warmup_epochs=2.,
                seed=42,deterministic=True,amp=True,workers=0,cache=False,
                hsv_h=.005,hsv_s=.15,hsv_v=.15,degrees=3.,translate=.05,scale=.15,
                fliplr=.5,flipud=0.,mosaic=0.,mixup=0.,copy_paste=0.,close_mosaic=0,
                plots=True,save=True,save_period=10,val=True,verbose=False)
    if rank==0:
        best=a.run_dir/'train/weights/best.pt';assert best.exists()
        shutil.copy2(best,a.run_dir/'best.pt')
        shutil.copy2(a.run_dir/'train/weights/last.pt',a.run_dir/'last.pt')
        progress=json.loads((a.run_dir/'progress.json').read_text())
        progress.update(state='trained',training_seconds=time.perf_counter()-start,
                        best_checkpoint='best.pt',torch=torch.__version__,ultralytics=ultralytics.__version__)
        atomic_json(a.run_dir/'progress.json',progress)
        print('TRAIN_COMPLETE '+json.dumps(progress),flush=True)
    if torch.distributed.is_initialized():torch.distributed.destroy_process_group()


if __name__=='__main__':main()
