"""Build the editable environment only. No screenshots, video or dataset capture.

Run with Isaac Sim's python.sh, from any working directory. Teammates can change
layout_training.json or pass --layout and --seed without changing the builder.
"""
import argparse
import json
from pathlib import Path

SIM=Path(__file__).resolve().parent

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--layout',type=Path,default=SIM/'layouts/layout_training.json')
    parser.add_argument('--seed',type=int,default=None)
    parser.add_argument('--output',type=Path,default=SIM/'scene_environment.usda')
    parser.add_argument('--no-robot',action='store_true')
    args,_=parser.parse_known_args()
    if args.output.resolve().parent != SIM.resolve():
        parser.error('--output must stay inside sim/ so relative texture references remain portable')
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'RayTracedLighting'})
    import omni.usd
    from pxr import UsdGeom
    from layouts import load_layout
    from robot import load_robot,attach_cameras
    context=omni.usd.get_context()
    # Keep the working layer next to the texture bank while authoring relative paths.
    working=SIM/'scene_environment.usda'
    context.get_stage().GetRootLayer().Export(str(working))
    context.open_stage(str(working))
    metrics=load_layout(args.layout,args.seed)
    stage=context.get_stage()
    if not args.no_robot:
        robot=load_robot((1,6,.55),0)
        attach_cameras(robot['body'])
        metrics['robot']=robot
    metrics['meshes']=sum(p.IsA(UsdGeom.Mesh) for p in stage.Traverse())
    metrics['output']=str(args.output)
    metrics['capture_performed']=False
    stage.GetRootLayer().Save()
    if args.output.resolve()!=working.resolve():
        stage.GetRootLayer().Export(str(args.output))
    output=SIM/'out/environment'; output.mkdir(parents=True,exist_ok=True)
    (output/'build_report.json').write_text(json.dumps(metrics,indent=2)+'\n')
    print('ENVIRONMENT_BUILD_OK',json.dumps(metrics),flush=True)
    app.close(wait_for_replicator=False)
