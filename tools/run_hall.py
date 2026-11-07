"""Run Step 1 as one Modal GPU job; download the hall and four screenshots."""
import io
from pathlib import Path
import subprocess
import tarfile
import modal

ROOT = Path(__file__).resolve().parents[1]
image = (modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',
                                 add_python='3.13',setup_dockerfile_commands=['USER root'])
         .entrypoint([])
         .env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all'})
         .add_local_dir(ROOT/'sim','/workspace/sim',copy=True,
                        ignore=['out/**','__pycache__/**','*.usda']))
app = modal.App('agentverse-hall-render')
JOBS={'hall':('capture_hall.py','step1','hall.usda','HALL_CAPTURE_OK'),
      'drums':('capture_drums.py','step2','scene_drums.usda','DRUM_CAPTURE_OK'),
      'sensors':('capture_sensors.py','sensors','scene_sensors.usda','SENSOR_CAPTURE_OK'),
      'training':('test_render.py','test_render','scene_training.usda','TRAINING_CAPTURE_OK'),
      'robot':('capture_robot.py','robot','scene_robot.usda','ROBOT_CAPTURE_OK')}


@app.function(image=image,gpu=['L40S','L4','A10G'],cpu=6,memory=24576,
              timeout=600,max_containers=1,single_use_containers=True)
def render(job='hall'):
    script,step,scene,_=JOBS[job]
    root = Path('/workspace')
    log_path = Path('/tmp/hall.log')
    print('GPU_JOB_STARTED',flush=True)
    print(subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version','--format=csv'],text=True),flush=True)
    assert Path('/isaac-sim/VERSION').read_text().startswith('6.2.0')
    with log_path.open('w') as log:
        process = subprocess.run(['/isaac-sim/python.sh','/workspace/sim/'+script,'--allow-root'],
                                 cwd='/workspace/sim',stdout=log,stderr=subprocess.STDOUT,timeout=540)
    output = io.BytesIO()
    with tarfile.open(fileobj=output,mode='w:gz') as archive:
        paths=['sim/out/'+step,'sim/assets/generated','sim/aisles.json','sim/'+scene]
        if job in ('drums','sensors','training','robot'): paths.append('sim/drums.json')
        for name in paths:
            path = root/name
            if path.exists(): archive.add(path,arcname=name)
    return {'code':process.returncode,'log':log_path.read_text(errors='replace'),'archive':output.getvalue()}


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
    print('SCENE_DOWNLOADED',output,flush=True)
    print('GPU_JOB_FINISHED',flush=True)


if __name__=='__main__':
    run_job('hall')
