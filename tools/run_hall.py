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


@app.function(image=image,gpu=['L4','L40S','A10G'],cpu=4,memory=16384,
              timeout=600,max_containers=1,single_use_containers=True)
def render():
    root = Path('/workspace')
    log_path = Path('/tmp/hall.log')
    print('GPU_JOB_STARTED',flush=True)
    print(subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version','--format=csv'],text=True),flush=True)
    assert Path('/isaac-sim/VERSION').read_text().startswith('6.2.0')
    with log_path.open('w') as log:
        process = subprocess.run(['/isaac-sim/python.sh','/workspace/sim/capture_hall.py','--allow-root'],
                                 cwd='/workspace/sim',stdout=log,stderr=subprocess.STDOUT,timeout=540)
    output = io.BytesIO()
    with tarfile.open(fileobj=output,mode='w:gz') as archive:
        for name in ('sim/out/step1','sim/assets/generated','sim/aisles.json','sim/hall.usda'):
            path = root/name
            if path.exists(): archive.add(path,arcname=name)
    return {'code':process.returncode,'log':log_path.read_text(errors='replace'),'archive':output.getvalue()}


if __name__ == '__main__':
    output = ROOT/'sim/out/step1'
    output.mkdir(parents=True,exist_ok=True)
    with modal.enable_output(), app.run():
        result = render.remote()
    with tarfile.open(fileobj=io.BytesIO(result['archive'])) as archive:
        archive.extractall(ROOT,filter='data')
    (output/'run.log').write_text(result['log'])
    if result['code'] or 'HALL_CAPTURE_OK' not in result['log']:
        print(result['log'][-9000:])
        raise SystemExit('Hall capture failed; see sim/out/step1/run.log')
    print('HALL_DOWNLOADED',output,flush=True)
    print('GPU_JOB_FINISHED',flush=True)
