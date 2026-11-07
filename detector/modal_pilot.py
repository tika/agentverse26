"""40 real Isaac images on eight independent L40S workers, with durable progress.

Run from the repo root: python detector/modal_pilot.py
Inspect progress: modal volume ls detector-data /pilots
"""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
import modal

ROOT=Path(__file__).resolve().parents[1]
image=(modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',add_python='3.13',
                                setup_dockerfile_commands=['USER root'])
       .entrypoint([]).env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all',
                            'ISAAC_RENDER_GPU_COUNT':'1','ISAAC_RENDER_WORKERS':'1'}))
if modal.is_local():
    image=(image.add_local_dir(ROOT/'sim','/workspace/sim',copy=True,
                               ignore=['out/**','__pycache__/**','**/__pycache__/**','**/*.pyc','*.usda'])
           .add_local_dir(ROOT/'detector','/workspace/detector',copy=True,
                          ignore=['__pycache__/**','**/*.pyc']))
volume=modal.Volume.from_name('detector-data',create_if_missing=True)
app=modal.App('agentverse-detector-pilot')


@app.function(image=image,gpu='L40S',cpu=8,memory=32768,timeout=1200,max_containers=16,
              single_use_containers=True,volumes={'/datasets':volume})
def render(seed,run_id,frame_count=5):
    start=time.perf_counter()
    output=Path('/datasets/pilots')/run_id/f'seed_{seed:02d}'
    output.mkdir(parents=True,exist_ok=True)
    inventory=subprocess.check_output(['nvidia-smi','--query-gpu=name,uuid','--format=csv,noheader'],text=True).strip()
    assert inventory.startswith('NVIDIA L40S') and len(inventory.splitlines())==1,inventory
    status=dict(seed=seed,state='starting_isaac',completed=0,target=frame_count,gpu=inventory,
                started_utc=datetime.now(timezone.utc).isoformat())
    def update(**values):
        status.update(values);status['updated_utc']=datetime.now(timezone.utc).isoformat()
        (output/'progress.json').write_text(json.dumps(status,indent=2));volume.commit()
    update()
    args=['/isaac-sim/python.sh','/workspace/sim/detector_studio/pilot.py','--allow-root',
          '--/renderer/multiGpu/enabled=false']
    log_lines=[]
    try:
        process=subprocess.Popen(args,cwd='/workspace/sim',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                 text=True,bufsize=1,env={**os.environ,'PILOT_SEED':str(seed),'PILOT_FRAMES':str(frame_count),'PILOT_OUTPUT':str(output)})
        # Keep the Modal timeout as an outer bound and terminate the owned process earlier.
        import threading
        timer=threading.Timer(1080,process.kill);timer.start()
        try:
            for line in process.stdout:
                log_lines.append(line)
                if line.startswith('PILOT_PHASE '):
                    phase=json.loads(line[len('PILOT_PHASE '):])
                    update(state=phase['state'],frame=phase.get('frame'))
                if line.startswith('PILOT_PROGRESS '):
                    progress=json.loads(line[len('PILOT_PROGRESS '):])
                    update(state='validating',completed=progress['completed'])
                    print(f"seed {seed}: {progress['completed']}/{frame_count} validated",flush=True)
            code=process.wait()
        finally:timer.cancel()
        log=''.join(log_lines)
        (output/'run.log').write_text(log)
        active_rows=[line for line in log.splitlines() if '| NVIDIA' in line and '| Yes:' in line]
        runtime=dict(seed=seed,gpu=inventory,active_gpu_rows=active_rows,return_code=code,
                     worker_seconds=time.perf_counter()-start)
        (output/'runtime.json').write_text(json.dumps(runtime,indent=2))
        if code or 'PILOT_OK ' not in log:
            update(state='failed',error=log[-2500:])
            return dict(ok=False,seed=seed,runtime=runtime,log=log[-8000:])
        update(state='complete',completed=frame_count,worker_seconds=runtime['worker_seconds'])
        payload=io.BytesIO()
        with tarfile.open(fileobj=payload,mode='w:gz') as tar:
            tar.add(output,arcname=f'seed_{seed:02d}')
        return dict(ok=True,seed=seed,runtime=runtime,archive=payload.getvalue())
    except Exception as exc:
        update(state='failed',error=repr(exc));raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seeds',type=int,default=8)
    parser.add_argument('--frames-per-seed',type=int,default=5)
    parser.add_argument('--seed-start',type=int,default=1)
    args=parser.parse_args()
    if not 1<=args.seeds<=16 or not 5<=args.frames_per_seed<=50:
        raise SystemExit('Use 1–16 seeds and 5–50 frames per seed for this review runner')
    target_images=args.seeds*args.frames_per_seed
    started=time.perf_counter()
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output=ROOT/'out/detector_pilot'/run_id;output.mkdir(parents=True)
    summary=dict(run_id=run_id,requested_gpus=args.seeds,target_images=target_images,completed_images=0,
                 state='starting',workers=[],started_utc=datetime.now(timezone.utc).isoformat())
    (output/'progress.json').write_text(json.dumps(summary,indent=2))
    print(f'PILOT_RUN {run_id}\nOUTPUT {output}',flush=True)
    failures=[]
    with modal.enable_output(),app.run():
        batch_started=time.perf_counter()
        for result in render.starmap([(s,run_id,args.frames_per_seed) for s in range(args.seed_start,args.seed_start+args.seeds)],order_outputs=False):
            summary['workers'].append(result['runtime'])
            if result['ok']:
                with tarfile.open(fileobj=io.BytesIO(result['archive'])) as tar:
                    tar.extractall(output,filter='data')
                summary['completed_images']+=args.frames_per_seed
            else:
                failures.append(result['seed']);(output/f"failed_seed_{result['seed']:02d}.log").write_text(result['log'])
                print(result['log'][-3000:],flush=True)
            summary.update(state='rendering',elapsed_seconds=round(time.perf_counter()-started,3))
            (output/'progress.json').write_text(json.dumps(summary,indent=2))
            print(f"PILOT_TOTAL {summary['completed_images']}/{target_images} images; {len(summary['workers'])}/{args.seeds} workers finished; {summary['elapsed_seconds']}s",flush=True)
        summary['dispatch_through_download_seconds']=round(time.perf_counter()-batch_started,3)
    summary.update(state='failed' if failures else 'complete',failed_seeds=failures,
                   total_wall_seconds=round(time.perf_counter()-started,3),
                   finished_utc=datetime.now(timezone.utc).isoformat(),
                   unique_gpu_count=len({w['gpu'] for w in summary['workers']}))
    (output/'timing.json').write_text(json.dumps(summary,indent=2))
    (output/'progress.json').write_text(json.dumps(summary,indent=2))
    print('PILOT_FINISHED '+json.dumps(summary),flush=True)
    if failures:raise SystemExit(f'Failed seeds {failures}; see {output}')
    from PIL import Image,ImageDraw
    frames=sorted(output.glob('seed_*/frame_*/boxes.jpg'))
    assert len(frames)==target_images,len(frames)
    grid=Image.new('RGB',(5*320,((target_images+4)//5)*344),(25,25,25));draw=ImageDraw.Draw(grid)
    for i,path in enumerate(frames):
        with Image.open(path) as image: grid.paste(image.resize((320,320)),((i%5)*320,(i//5)*344))
        draw.text(((i%5)*320+5,(i//5)*344+323),str(path.relative_to(output).parent),fill='white')
    grid.save(output/'contact_sheet.jpg',quality=92)
    (ROOT/'out/detector_pilot/latest.json').write_text(json.dumps(dict(run_id=run_id,path=str(output)),indent=2))


if __name__=='__main__':main()
