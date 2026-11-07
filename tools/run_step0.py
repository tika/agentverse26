"""Run the cube check on one L40S, download its output, then stop the GPU."""
from pathlib import Path
import tarfile
import modal

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / 'sim/out/step0'
output.mkdir(parents=True, exist_ok=True)
image = (modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0')
         .entrypoint([]).env({'ACCEPT_EULA': 'Y', 'PRIVACY_CONSENT': 'N',
                             'NVIDIA_DRIVER_CAPABILITIES': 'all'}))
app = modal.App.lookup('agentverse-isaac-sim', create_if_missing=True)
with modal.enable_output():
    sandbox = modal.Sandbox.create('sleep', '600', app=app, image=image,
                                  gpu='L40S', cpu=8, memory=32768, timeout=600)
try:
    process = sandbox.exec('mkdir', '-p', '/workspace/sim', timeout=10)
    process.wait()
    for name in ('hello_world.py', 'capture_step0.py'):
        sandbox.filesystem.copy_from_local(ROOT / 'sim' / name, '/workspace/sim/' + name)
    process = sandbox.exec('bash', '-lc',
        '/isaac-sim/python.sh /workspace/sim/hello_world.py --allow-root > /tmp/step0.log 2>&1', timeout=300)
    process.stdout.read()
    error = process.stderr.read()
    code = process.wait()
    log_process = sandbox.exec('cat', '/tmp/step0.log', timeout=10)
    log = log_process.stdout.read()
    log_process.wait()
    (output / 'run.log').write_text(log)
    if code or 'STEP0_CAPTURE_OK' not in log:
        print(log[-7000:])
        raise RuntimeError(f'Step 0 failed ({code}); see {output / "run.log"}. {error}')
    process = sandbox.exec('tar', '-czf', '/tmp/step0.tar.gz', '-C', '/workspace/sim/out/step0', '.', timeout=30)
    if process.wait():
        raise RuntimeError('Could not archive cube output')
    archive = output / 'download.tar.gz'
    sandbox.filesystem.copy_to_local('/tmp/step0.tar.gz', archive)
    with tarfile.open(archive) as package:
        package.extractall(output, filter='data')
    archive.unlink()
    print(f'STEP0_DOWNLOADED {output}')
finally:
    sandbox.terminate(wait=True)
    print('GPU_STOPPED')
