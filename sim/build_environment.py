"""Build the editable environment only. No screenshots, video or dataset capture.

Run with Isaac Sim's python.sh, from any working directory. Teammates can change
layout_training.json or pass --layout and --seed without changing the builder.
"""
import argparse
import json
import os
import sys
from uuid import uuid4
from pathlib import Path

SIM=Path(__file__).resolve().parent

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--layout',type=Path,default=SIM/'layouts/layout_training.json')
    parser.add_argument('--seed',type=int,default=None)
    parser.add_argument('--output',type=Path,default=SIM/'scene_environment.usda')
    parser.add_argument('--warehouse-v3', action='store_true',
                        help='Open the 420-drum warehouse with fresh randomized faults')
    parser.add_argument('--fault-manifest', type=Path,
                        help='Optional private evaluator output for --warehouse-v3')
    parser.add_argument('--no-robot',action='store_true')
    args,_=parser.parse_known_args()
    if args.warehouse_v3:
        if args.output == SIM / 'scene_environment.usda':
            args.output = SIM / 'out/environment/runs' / uuid4().hex / 'warehouse.usda'
    elif args.fault_manifest:
        parser.error('--fault-manifest requires --warehouse-v3')
    if not args.warehouse_v3 and args.output.resolve().parent != SIM.resolve():
        parser.error('--output must stay inside sim/ so relative texture references remain portable')
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'RayTracedLighting'})
    import omni.usd
    from pxr import UsdGeom
    context=omni.usd.get_context()
    if args.warehouse_v3:
        warehouse = Path(os.environ.get('AGENTVERSE_WAREHOUSE_DIR', SIM / 'warehouse-v3')).resolve()
        sys.path.insert(0, str(warehouse))
        from drum_faults import generate_session
        output_path = generate_session(args.output, seed=args.seed, manifest=args.fault_manifest)
        if not context.open_stage(str(output_path)):
            raise RuntimeError(f'Could not open {output_path}')
        layout = json.loads((warehouse / 'map.json').read_text())
        from isaacsim.core.experimental.utils.semantics import add_labels
        for drum in layout['drums']:
            prim = context.get_stage().GetPrimAtPath(drum['prim_path'])
            for taxonomy, value in (('class', 'drum'), ('drum_id', drum['id']),
                                    ('waste_category', drum['category'])):
                add_labels(prim, labels=[value], taxonomy=taxonomy)
        metrics = {'drums': len(layout['drums'])}
    else:
        # Keep the working layer next to the legacy texture bank.
        working = SIM / 'scene_environment.usda'
        context.get_stage().GetRootLayer().Export(str(working))
        context.open_stage(str(working))
        from layouts import load_layout
        metrics = load_layout(args.layout, args.seed)
    stage=context.get_stage()
    if not args.no_robot:
        from robot import load_robot, attach_cameras
        spawn = layout['robot_start'] if args.warehouse_v3 else (1, 6, 0)
        robot=load_robot((spawn[0], spawn[1], spawn[2] + .55),0)
        attach_cameras(robot['body'])
        metrics['robot']=robot
    metrics['meshes']=sum(p.IsA(UsdGeom.Mesh) for p in stage.Traverse())
    metrics['output']=str(args.output)
    metrics['capture_performed']=False
    stage.GetRootLayer().Save()
    if not args.warehouse_v3 and args.output.resolve()!=working.resolve():
        stage.GetRootLayer().Export(str(args.output))
    output = args.output.resolve().parent if args.warehouse_v3 else SIM/'out/environment'
    output.mkdir(parents=True, exist_ok=True)
    (output/'build_report.json').write_text(json.dumps(metrics,indent=2)+'\n')
    print('ENVIRONMENT_BUILD_OK',json.dumps(metrics),flush=True)
    app.close(wait_for_replicator=False)
