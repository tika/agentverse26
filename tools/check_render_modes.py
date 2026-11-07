"""Inspect installed renderer launch options without allocating a GPU."""
from pathlib import Path
import modal
image = (modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',add_python='3.13',
                                 setup_dockerfile_commands=['USER root']).entrypoint([]))
app = modal.App('agentverse-render-mode-check')

@app.function(image=image,cpu=1,memory=1024,timeout=120)
def inspect():
    result = {}
    for path in Path('/isaac-sim/exts/isaacsim.simulation_app').rglob('*.py'):
        source = path.read_text(errors='replace')
        lines = source.splitlines()
        hits = [i for i,line in enumerate(lines) if 'minimal' in line.lower() or 'RaytracedLighting' in line]
        if hits:
            indices = sorted({j for i in hits for j in range(max(0,i-2),min(len(lines),i+4))})
            result[str(path)] = '\n'.join(f'{i+1}: {lines[i]}' for i in indices)
    for path in Path('/isaac-sim/exts/isaacsim.robot.policy.examples').rglob('*.py'):
        if path.name in ('spot.py','runner.py','robot_policy_runner.py'):
            result[str(path)] = path.read_text(errors='replace')[:25000]
    return result

if __name__ == '__main__':
    import json
    with modal.enable_output(),app.run():
        result = inspect.remote()
    output = Path(__file__).resolve().parents[1]/'sim/out/renderer_probe.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
