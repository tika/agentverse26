"""Build/capture Isaac scenes on Modal with 1–4 GPUs; download and release them."""
import io
import json
import os
import time
from pathlib import Path
import subprocess
import tarfile
import modal

ROOT = Path(__file__).resolve().parents[1]
GPU_COUNT = int(os.environ.get('ISAAC_RENDER_GPU_COUNT','1'))
WORKER_COUNT = int(os.environ.get('ISAAC_RENDER_WORKERS','1'))
if WORKER_COUNT not in (1,2,3,4): raise ValueError('ISAAC_RENDER_WORKERS must be 1–4')
if GPU_COUNT not in (1,2,3,4): raise ValueError('ISAAC_RENDER_GPU_COUNT must be 1–4')
GPU_OPTIONS = [f'{name}:{GPU_COUNT}' for name in ('L40S','L4','A10G')] if GPU_COUNT>1 else ['L40S','L4','A10G']
image = (modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',
                                 add_python='3.13',setup_dockerfile_commands=['USER root'])
         .entrypoint([])
         .env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all',
               'ISAAC_RENDER_GPU_COUNT':str(GPU_COUNT),
               'ISAAC_RENDER_WORKERS':str(WORKER_COUNT)})
         .add_local_dir(ROOT/'sim','/workspace/sim',copy=True,
                        ignore=['out/**','__pycache__/**','**/__pycache__/**','**/*.pyc','*.usda']))
app = modal.App('agentverse-hall-render')
JOBS={'hall':('capture_hall.py','step1','hall.usda','HALL_CAPTURE_OK'),
      'drums':('capture_drums.py','step2','scene_drums.usda','DRUM_CAPTURE_OK'),
      'sensors':('capture_sensors.py','sensors','scene_sensors.usda','SENSOR_CAPTURE_OK'),
      'training':('test_render.py','test_render','scene_training.usda','TRAINING_CAPTURE_OK'),
      'robot':('capture_robot.py','robot','scene_robot.usda','ROBOT_CAPTURE_OK'),
      'environment':('build_environment.py','environment','scene_environment.usda','ENVIRONMENT_BUILD_OK'),
      'presentation':('capture_presentation.py','presentation','scene_presentation.usda','PRESENTATION_CAPTURE_OK'),
      'barrel_preview':('render_barrel_preview.py','barrel_preview','scene_barrel_preview.usda','BARREL_PREVIEW_OK')}


@app.function(image=image,gpu=GPU_OPTIONS,cpu=max(6,GPU_COUNT*2),memory=max(24576,GPU_COUNT*8192),
              timeout=600,max_containers=WORKER_COUNT,single_use_containers=True)
def render(job='hall',shard=0,shards=1):
    script,step,scene,_=JOBS[job]
    root = Path('/workspace')
    log_path = Path('/tmp/hall.log')
    print('GPU_JOB_STARTED',flush=True)
    print(subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version','--format=csv'],text=True),flush=True)
    assert Path('/isaac-sim/VERSION').read_text().startswith('6.2.0')
    inventory = subprocess.check_output(['nvidia-smi','--query-gpu=index,name,uuid','--format=csv,noheader'],text=True).strip().splitlines()
    assert len(inventory)==GPU_COUNT,(GPU_COUNT,inventory)
    arguments=['/isaac-sim/python.sh','/workspace/sim/'+script,'--allow-root',
               '--/renderer/multiGpu/enabled=true',f'--/renderer/multiGpu/maxGpuCount={GPU_COUNT}']
    started=time.perf_counter()
    with log_path.open('w') as log:
        process = subprocess.run(arguments,
                                 cwd='/workspace/sim',stdout=log,stderr=subprocess.STDOUT,timeout=540,
                                 env={**os.environ,'ISAAC_VIEW_SHARD':str(shard),'ISAAC_VIEW_SHARDS':str(shards)})
    render_log=log_path.read_text(errors='replace')
    active_rows=[line for line in render_log.splitlines() if '| NVIDIA' in line and '| Yes:' in line]
    runtime={'requested_gpu_count':GPU_COUNT,'visible_gpus':inventory,
             'renderer_active_gpu_count':len(active_rows),'renderer_active_rows':active_rows,
             'subprocess_seconds':round(time.perf_counter()-started,3),
             'arguments':arguments,'return_code':process.returncode}
    runtime_dir=root/'sim/out'/step
    if shards>1:runtime_dir=runtime_dir/f'shard_{shard:02d}'
    runtime['shard']=shard;runtime['shards']=shards
    runtime_dir.mkdir(parents=True,exist_ok=True)
    (runtime_dir/'gpu_runtime.json').write_text(json.dumps(runtime,indent=2)+'\n')
    output = io.BytesIO()
    with tarfile.open(fileobj=output,mode='w:gz') as archive:
        paths=['sim/out/'+step]
        if shard==0:paths+=['sim/assets/generated','sim/aisles.json','sim/'+scene]
        if job in ('drums','sensors','training','robot','environment','presentation'): paths.append('sim/drums.json')
        for name in paths:
            path = root/name
            if path.exists(): archive.add(path,arcname=name)
    return {'code':process.returncode,'log':render_log,'archive':output.getvalue()}


def run_job(job='hall'):
    _,step,_,marker=JOBS[job]
    output = ROOT/'sim/out'/step
    output.mkdir(parents=True,exist_ok=True)
    with modal.enable_output(), app.run():
        result = render.remote(job)
    with tarfile.open(fileobj=io.BytesIO(result['archive'])) as archive:
        archive.extractall(ROOT,filter='data')
    (output/'run.log').write_text(result['log'])
    if result['code'] or marker not in result['log']:
        print(result['log'][-9000:])
        raise SystemExit(f'Capture failed; see {output}/run.log')
    runtime_path=output/'gpu_runtime.json'
    if GPU_COUNT>1 and runtime_path.exists():
        runtime=json.loads(runtime_path.read_text())
        if runtime.get('renderer_active_gpu_count')!=GPU_COUNT:
            raise RuntimeError('Requested GPUs were allocated but not all activated; see gpu_runtime.json')
    if job=='barrel_preview':
        from validate_barrel_preview import validate
        validate(output)
    print('SCENE_DOWNLOADED',output,flush=True)
    print('GPU_JOB_FINISHED',flush=True)


if __name__=='__main__':
    run_job('hall')
