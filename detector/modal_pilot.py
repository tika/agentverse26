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
import uuid
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
def render(seed,run_id,frame_count=5,gpu_type='L40S'):
    start=time.perf_counter()
    output=Path('/datasets/pilots')/run_id/f'seed_{seed:02d}'
    if output.exists() and any(output.iterdir()):
        output.rename(output.with_name(output.name+'_previous_'+uuid.uuid4().hex[:6]))
    output.mkdir(parents=True,exist_ok=True)
    inventory=subprocess.check_output(['nvidia-smi','--query-gpu=name,uuid','--format=csv,noheader'],text=True).strip()
    expected='L40S' if gpu_type=='L40S' else 'RTX PRO 6000'
    assert expected in inventory and len(inventory.splitlines())==1,inventory
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
        update(state='failed',error=repr(exc))
        return dict(ok=False,seed=seed,log=''.join(log_lines)[-8000:]+repr(exc),
                    runtime=dict(seed=seed,gpu=inventory,return_code=-1,worker_seconds=time.perf_counter()-start))


def main():
    sys.path.insert(0,str(ROOT))
    from detector.dataset_plan import validate_plan,digest,source_hashes,CLASSES,CAMERA
    parser=argparse.ArgumentParser()
    parser.add_argument('--seeds',type=int,default=8)
    parser.add_argument('--frames-per-seed',type=int,default=5)
    parser.add_argument('--seed-start',type=int,default=1)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--workers',type=int)
    parser.add_argument('--gpu',choices=['L40S','RTX-PRO-6000'],default='L40S')
    parser.add_argument('--workspace',default='paramsachdeva07')
    parser.add_argument('--publish',help='Build and upload this named dataset release after validation')
    parser.add_argument('--resume',type=Path,help='Previous local run with generation.json; retry missing seeds only')
    parser.add_argument('--benchmark-l40s',action='store_true',help='Matched L40S control for first RTX scene')
    parser.add_argument('--preflight-seed',type=int,help='Run this planned scene first without changing split assignments')
    args=parser.parse_args()
    from detector.dataset_release import check_workspace,validate_seed
    check_workspace(args.workspace)
    if args.plan:
        plan=validate_plan(json.loads(args.plan.read_text()))
    elif args.resume:
        plan=validate_plan(json.loads((args.resume/'generation.json').read_text())['plan'])
    else:
        if not 1<=args.seeds<=16 or not 1<=args.frames_per_seed<=50 or args.seed_start<1:
            raise SystemExit('Use 1–16 seeds, positive starting seed and 1–50 frames per seed')
        plan=dict(schema=1,images=args.seeds*args.frames_per_seed,workers=args.workers or args.seeds,
                  classes=CLASSES,camera=CAMERA,jobs=[dict(seed=s,frames=args.frames_per_seed,split='pilot')
                  for s in range(args.seed_start,args.seed_start+args.seeds)])
    jobs=plan['jobs'];target_images=plan['images'];workers=args.workers or plan['workers']
    if not 1<=workers<=16:raise SystemExit('Use 1–16 workers')
    if args.publish:
        try:
            existing=json.loads(b''.join(volume.read_file('/releases/'+args.publish+'/manifest.json')))
        except modal.exception.NotFoundError:existing=None
        if existing is not None:
            if existing['images']!=target_images or existing['generation']['plan_sha256']!=digest(plan):
                raise SystemExit('Release name already exists with a different plan; choose a new version')
            print('RELEASE_ALREADY_EXISTS '+json.dumps(dict(release=args.publish,images=existing['images'],
                  volume='detector-data',workspace=args.workspace)),flush=True)
            return
    started=time.perf_counter()
    if args.resume:
        output=args.resume.resolve();run_id=output.name
        generation=json.loads((output/'generation.json').read_text())
        if generation['source_hashes']!=source_hashes(ROOT) or generation['plan_sha256']!=digest(plan):
            raise SystemExit('Resume source/plan differs; use the original checkout and frozen plan')
        if generation['workspace']!=args.workspace or generation['gpu_type']!=args.gpu:
            raise SystemExit('Resume must use original workspace and GPU type')
    else:
        run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6]
        output=ROOT/'out/detector_pilot'/run_id;output.mkdir(parents=True)
        generation=dict(schema=1,run_id=run_id,plan=plan,plan_sha256=digest(plan),classes=CLASSES,camera=CAMERA,
                        source_hashes=source_hashes(ROOT),gpu_type=args.gpu,workspace=args.workspace,
                        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
        (output/'generation.json').write_text(json.dumps(generation,indent=2))
        with volume.batch_upload() as upload:
            upload.put_file(output/'generation.json',f'/pilots/{run_id}/generation.json')
    complete=[]
    for job in jobs:
        folder=output/f"seed_{job['seed']:02d}"
        if folder.exists():
            try:validate_seed(output,job);complete.append(job['seed'])
            except (ValueError,AssertionError,FileNotFoundError):
                # Only archive this run's failed local outputs; completed ones are immutable.
                folder.rename(output/(folder.name+'_failed_'+uuid.uuid4().hex[:6]))
    pending=[j for j in jobs if j['seed'] not in complete]
    if args.preflight_seed is not None:
        if args.preflight_seed not in {j['seed'] for j in jobs}:raise SystemExit('Preflight seed is not in the plan')
        pending.sort(key=lambda j:j['seed']!=args.preflight_seed)
    summary=dict(run_id=run_id,requested_gpus=workers,target_jobs=len(jobs),gpu_type=args.gpu,
                 target_images=target_images,completed_images=sum(j['frames'] for j in jobs if j['seed'] in complete),
                 state='starting',workers=[],started_utc=datetime.now(timezone.utc).isoformat())
    (output/'progress.json').write_text(json.dumps(summary,indent=2))
    print(f'PILOT_RUN {run_id}\nOUTPUT {output}',flush=True)
    failures=[]
    def accept(result):
        if isinstance(result,Exception):
            failures.append('platform_error');print(repr(result),flush=True);return
        summary['workers'].append(result['runtime'])
        if result['ok']:
            with tarfile.open(fileobj=io.BytesIO(result['archive'])) as tar:tar.extractall(output,filter='data')
            summary['completed_images']+=next(j['frames'] for j in jobs if j['seed']==result['seed'])
        else:
            failures.append(result['seed']);(output/f"failed_seed_{result['seed']:02d}.log").write_text(result['log'])
            print(result['log'][-3000:],flush=True)
        summary.update(state='rendering',elapsed_seconds=round(time.perf_counter()-started,3))
        (output/'progress.json').write_text(json.dumps(summary,indent=2))
        print(f"DATASET_PROGRESS {summary['completed_images']}/{target_images} images; {summary['elapsed_seconds']}s",flush=True)
    with modal.enable_output(),app.run():
        batch_started=time.perf_counter()
        configured=render.with_options(gpu=args.gpu,max_containers=workers)
        if pending:
            first=pending[0]
            production=configured.spawn(first['seed'],run_id,first['frames'],args.gpu)
            control=None
            if args.benchmark_l40s and args.gpu=='RTX-PRO-6000':
                control=render.with_options(gpu='L40S',max_containers=1).spawn(first['seed'],run_id+'_l40s_control',first['frames'],'L40S')
            accept(production.get())
            if control:
                result=control.get()
                if result['ok']:
                    directory=output/'benchmark_l40s';directory.mkdir(exist_ok=True)
                    with tarfile.open(fileobj=io.BytesIO(result['archive'])) as tar:tar.extractall(directory,filter='data')
                    folder=f"seed_{first['seed']:02d}"
                    from detector.benchmark import compare
                    measurement=compare(json.loads((output/folder/'report.json').read_text()),
                                        json.loads((directory/folder/'report.json').read_text()),
                                        json.loads((output/folder/'runtime.json').read_text()),result['runtime'])
                    (output/'benchmark.json').write_text(json.dumps(measurement,indent=2))
                    print('GPU_BENCHMARK '+json.dumps(measurement),flush=True)
                else:
                    (output/'benchmark_failed.log').write_text(result['log']);print('L40S control failed; no speedup claim',flush=True)
            if failures:raise SystemExit(f'Compatibility scene failed. See {output}; remaining jobs were not launched.')
            if len(pending)>1:
                for result in configured.starmap([(j['seed'],run_id,j['frames'],args.gpu) for j in pending[1:]],
                                                  order_outputs=False,return_exceptions=True):accept(result)
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
    frames=[p for p in frames if p.parent.parent.name in {f"seed_{j['seed']:02d}" for j in jobs}]
    assert len(frames)==target_images,len(frames)
    # Avoid a 20,000-pixel-tall preview for production: retain up to 100 examples.
    frames=frames[::max(1,(len(frames)+99)//100)]
    grid=Image.new('RGB',(5*320,((len(frames)+4)//5)*344),(25,25,25));draw=ImageDraw.Draw(grid)
    for i,path in enumerate(frames):
        with Image.open(path) as image: grid.paste(image.resize((320,320)),((i%5)*320,(i//5)*344))
        draw.text(((i%5)*320+5,(i//5)*344+323),str(path.relative_to(output).parent),fill='white')
    grid.save(output/'contact_sheet.jpg',quality=92)
    (ROOT/'out/detector_pilot/latest.json').write_text(json.dumps(dict(run_id=run_id,path=str(output)),indent=2))
    if args.publish:
        from detector.dataset_release import build_release,upload_release
        release=ROOT/'out/detector_releases'/args.publish
        build_release(output,release)
        upload_release(release,args.workspace)


if __name__=='__main__':main()
