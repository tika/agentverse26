"""One bounded Isaac Sim 6.2 check of the composed v3 stage on one RTX PRO 6000.

    cd ~/Desktop/agentverse/warehouse-v3
    /Users/levi/agentverse-isaac/.venv311/bin/python -m modal run wt-claude/sim/v3/modal_isaac_check.py --output review/isaac
"""
import io
import json
import os
import tempfile
import subprocess
import tarfile
import time
from pathlib import Path

import modal

SNAP = Path('/stage')

HERE = Path(__file__).resolve().parent
WS = HERE
FILES = ['warehouse-v3.usda', 'shell.usda', 'site.usda', 'storage.usda', 'map.json']
# Upload an immutable snapshot (the other agent may rewrite layers while the image builds).
if modal.is_local():
    import hashlib, shutil
    SNAP = Path(tempfile.mkdtemp(prefix='warehouse-isaac-'))
    shutil.copytree(WS / 'assets', SNAP / 'assets')
    for script in ('isaac_check.py', 'drum_faults.py', 'storage.py'):
        shutil.copy2(HERE / script, SNAP / script)
    shutil.copy2(HERE.parent / 'build_environment.py', SNAP / 'build_environment.py')
    shutil.copytree(HERE / 'baseline', SNAP / 'baseline', ignore=shutil.ignore_patterns('__pycache__'))
    for f in FILES:
        shutil.copy2(WS / f, SNAP / f)
    (SNAP / 'snapshot_sha256.json').write_text(json.dumps({f: hashlib.sha256((SNAP / f).read_bytes()).hexdigest() for f in FILES}, indent=1))
image = (modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0', add_python='3.13',
                                   setup_dockerfile_commands=['USER root'])
         .entrypoint([])
         .env({'ACCEPT_EULA': 'Y', 'PRIVACY_CONSENT': 'N', 'NVIDIA_DRIVER_CAPABILITIES': 'all'})
         .add_local_dir(SNAP, '/stage', copy=True))
app = modal.App('agentverse-v3-isaac-check', image=image)


@app.function(gpu='RTX-PRO-6000', cpu=8, memory=32768, timeout=900, max_containers=1, scaledown_window=5)
def check(tour: bool = False, fault_seed: int | None = None):
    out = Path('/tmp/v3check')
    out.mkdir()
    hw = subprocess.check_output(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'], text=True).strip()
    version = Path('/isaac-sim/VERSION').read_text().strip()
    start = time.perf_counter()
    with (out / 'isaac.log').open('w') as log:
        rc = subprocess.run(['/isaac-sim/python.sh', '/stage/isaac_check.py', '--stage', '/stage/warehouse-v3.usda',
                             '--map', '/stage/map.json', '--out', str(out)] + (['--tour'] if tour else []) +
                            (['--fault-seed', str(fault_seed)] if fault_seed is not None else []),
                            stdout=log, stderr=subprocess.STDOUT, timeout=780, cwd='/isaac-sim').returncode
    (out / 'hardware.json').write_text(json.dumps({'gpu': hw, 'isaac_version': version, 'returncode': rc,
                                                   'wall_s': round(time.perf_counter() - start, 1)}, indent=2))
    if fault_seed is not None:
        # Exercise the public entry point separately from the capture code.
        smoke = Path('/tmp/warehouse-entry-smoke')
        smoke.mkdir()
        with (out / 'warehouse_entry.log').open('w') as log:
            entry_rc = subprocess.run(
                ['/isaac-sim/python.sh', '/stage/build_environment.py', '--warehouse-v3',
                 '--no-robot', '--output', str(smoke / 'warehouse.usda')],
                stdout=log, stderr=subprocess.STDOUT, timeout=180, cwd='/isaac-sim',
                env={**os.environ, 'AGENTVERSE_WAREHOUSE_DIR': '/stage'},
            ).returncode
        (out / 'warehouse_entry.json').write_text(json.dumps({'returncode': entry_rc}))
    import shutil as _sh
    _sh.copy('/stage/snapshot_sha256.json', out / 'snapshot_sha256.json')
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for p in out.rglob('*'):
            if p.is_file() and 'warehouse-session_textures' not in p.parts and p.name != 'warehouse-session.usda':
                tar.add(p, arcname=p.relative_to(out))
    return buf.getvalue()


@app.local_entrypoint()
def main(output: str, tour: bool = False, fault_seed: int | None = None):
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(check.remote(tour, fault_seed))) as tar:
        tar.extractall(dest, filter='data')
    print(dest, (dest / 'hardware.json').read_text())
