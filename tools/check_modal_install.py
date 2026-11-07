"""CPU-only inspection of our clean NVIDIA image; always stop the probe."""
import json
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
image = modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0').entrypoint([])
app = modal.App.lookup('agentverse-isaac-sim', create_if_missing=True)
with modal.enable_output():
    sandbox = modal.Sandbox.create('sleep', '180', app=app, image=image,
                                  cpu=1, memory=2048, timeout=180)
try:
    sandbox.filesystem.copy_from_local(ROOT / 'sim/check_installation.py', '/tmp/check_installation.py')
    process = sandbox.exec('/isaac-sim/python.sh', '/tmp/check_installation.py', timeout=30)
    output = process.stdout.read()
    error = process.stderr.read()
    if process.wait():
        raise RuntimeError(error or output)
    # The shell launcher may print other setup messages before the JSON.
    report = json.loads(output[output.index('{'):])
    destination = ROOT / 'sim/installation_report.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(destination)
    print(json.dumps(report, indent=2))
finally:
    sandbox.terminate(wait=True)
