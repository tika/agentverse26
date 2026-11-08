"""Read policy-runner visual configuration from the pinned Isaac image; CPU only."""
from pathlib import Path
import modal

app=modal.App('agentverse-inspect-spot-source')
image=modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',add_python='3.13',setup_dockerfile_commands=['USER root']).entrypoint([])

@app.function(image=image,cpu=1,memory=2048,timeout=300)
def inspect_source():
    root=Path('/isaac-sim/exts/isaacsim.robot.policy.examples')
    result={}
    for path in root.rglob('*.py'):
        text=path.read_text()
        if 'get_spot_spec' in text or 'class RobotPolicyRunner' in text:
            result[str(path)]=text
    return result

@app.local_entrypoint()
def main():
    out=Path(__file__).resolve().parents[1]/'out/spot_source'
    out.mkdir(parents=True,exist_ok=True)
    for path,source in inspect_source.remote().items():
        target=out/Path(path).name;target.write_text(source);print(target)
