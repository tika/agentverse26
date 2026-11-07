"""One bounded Stage 3 pilot render on the approved RTX PRO 6000."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

import modal

ROOT = Path(__file__).resolve().parent
image = (modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0', add_python='3.13',
                                 setup_dockerfile_commands=['USER root'])
         .entrypoint([])
         .env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all'})
         .add_local_dir(ROOT/'sim','/scene',copy=True,ignore=['out/**','__pycache__/**'])
         .add_local_dir(ROOT/'scripts','/scripts',copy=True))
app = modal.App('agentverse-stage3-pilot', image=image)


@app.function(gpu='RTX-PRO-6000',cpu=8,memory=32768,timeout=900,max_containers=1,scaledown_window=5)
def render():
    root=Path('/tmp/stage3-pilot'); root.mkdir()
    hardware=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'],text=True).strip()
    assert 'RTX PRO 6000' in hardware, hardware
    version=Path('/isaac-sim/VERSION').read_text().strip(); assert version.startswith('6.2.0'),version
    start=time.perf_counter()
    with (root/'isaac.log').open('w') as log:
        result=subprocess.run(['/isaac-sim/python.sh','/scene/capture_stage3_pilot.py'],
            env={**os.environ,'OUTPUT_DIR':str(root)},stdout=log,stderr=subprocess.STDOUT,
            timeout=760,cwd='/isaac-sim')
    elapsed=time.perf_counter()-start
    (root/'hardware.json').write_text(json.dumps({'gpu':hardware,'isaac_version':version,
        'subprocess_wall_s':elapsed,'returncode':result.returncode},indent=2))
    payload=io.BytesIO()
    with tarfile.open(fileobj=payload,mode='w:gz') as archive:
        for path in root.rglob('*'):
            if path.is_file(): archive.add(path,arcname=path.relative_to(root))
    return payload.getvalue()


@app.local_entrypoint()
def main(output: str):
    dest=Path(output); dest.mkdir(parents=True,exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(render.remote())) as archive:
        archive.extractall(dest,filter='data')
    if not (dest/'manifest.json').is_file():
        raise RuntimeError(f'Pilot render failed; inspect {dest}/isaac.log')
    print(dest)
