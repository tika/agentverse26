"""Standalone reproducible handoff check; includes Step 3/4 views and true box output."""
import hashlib
import json
from pathlib import Path
import time
SIM=Path(__file__).resolve().parent
OUTPUT=SIM/'out/test_render'


def checks(stage,entries):
    from pxr import UsdGeom
    from isaacsim.core.experimental.utils.semantics import get_labels
    from drums import make_inventory
    nominal=make_inventory(42)
    assert len(entries)==28
    defects=[]
    for e,n in zip(entries,nominal):
        for key in ('id','category','x','y','yaw','radius','height','source_strength'):
            assert e[key]==n[key],(e['id'],key)
        assert get_labels(stage.GetPrimAtPath(e['prim_path']))['class']==['drum']
        for d in e['defects']:
            prim=stage.GetPrimAtPath(d['prim_path']); assert prim
            assert get_labels(prim)['class']==[d['type']]
            assert get_labels(prim)['drum_id']==[e['id']]
            defects.append(d)
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            uv=UsdGeom.PrimvarsAPI(prim).GetPrimvar('st')
            assert uv and len(uv.Get())==len(UsdGeom.Mesh(prim).GetFaceVertexIndicesAttr().Get())
        if str(prim.GetPath()).startswith('/World/Hall'):
            assert not get_labels(prim).get('class')
    return {'drums':28,'fixed_layout_preserved':True,'defect_mesh_count':len(defects),
            'all_targets_have_class_and_drum_id':True,'all_meshes_have_uvs':True,
            'background_has_no_classes':True}


if __name__=='__main__':
    from isaacsim import SimulationApp
    # Minimal mode was tested but produced black RGB on this runtime; use verified real-time mode.
    import os
    renderer=os.environ.get('ISAAC_RENDERER','RayTracedLighting')
    app=SimulationApp({'headless':True,'display_options':0,'renderer':renderer,'minimal_shading_mode':1,
                       'extra_args':['--enable','isaacsim.robot.policy.examples']})
    import omni.usd
    import carb
    from layouts import load_layout
    from drums import INVENTORY,set_drum_state
    from training_capture import camera,attach_capture,finish_captures
    OUTPUT.mkdir(parents=True,exist_ok=True)
    context=omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM/'scene_training.usda'))
    context.open_stage(str(SIM/'scene_training.usda'))
    started=time.perf_counter()
    build=load_layout()
    stage=context.get_stage()
    inventory=INVENTORY.read_text()
    snapshot=stage.GetRootLayer().ExportToString()
    build2=load_layout()
    assert snapshot==stage.GetRootLayer().ExportToString()
    assert inventory==INVENTORY.read_text()
    # Replacement/cleaning must remove meshes and restore the same seeded faults.
    original=json.loads(inventory)
    set_drum_state('D10','clean')
    assert not stage.GetPrimAtPath('/World/Defects/D10')
    load_layout()
    assert snapshot==stage.GetRootLayer().ExportToString()
    entries=json.loads(INVENTORY.read_text())
    report={'build':build,'rebuild':build2,'same_seed_identical_stage_and_inventory':True,
            'fault_replacement_verified':True,'checks':checks(stage,entries),
            'renderer':{'name':renderer,'minimal_shading_mode':1,
                        'active':carb.settings.get_settings().get('/rtx/rendermode')}}
    captures=[]
    specs=[('llw_severity1','D03'),('llw_severity2','D04'),('llw_severity3','D12'),
           ('ilw_severity1','D17'),('ilw_severity3','D18'),
           ('llw_leak','D10'),('ilw_leak','D20'),('llw_residue','D06'),('ilw_residue','D25')]
    for name,id in specs:
        e=next(d for d in entries if d['id']==id)
        sign=-1 if e['row'] in ('A','C') else 1
        eye=(e['x']+.12,e['y']+sign*1.7,.95 if e['category']=='LLW' else 1.25)
        target=(e['x'],e['y'],e['height']*.48)
        path=camera(stage,'/World/ReviewCameras/'+name,eye,target,30)
        captures.append(attach_capture(stage,name,path,OUTPUT))
    for name,id in [('case_a_llw','D10'),('case_b_ilw','D25')]:
        e=next(d for d in entries if d['id']==id)
        sign=-1 if e['row'] in ('A','C') else 1
        eye=(e['x'],e['y']+sign*2,.6)
        target=(e['x'],e['y'],.6-2*.176327)
        path=camera(stage,'/World/ReviewCameras/'+name,eye,target,24)
        captures.append(attach_capture(stage,name,path,OUTPUT))
    path=camera(stage,'/World/ReviewCameras/overview',(1.2,1.5,4.6),(12,6,1.5),20,(960,640))
    captures.append(attach_capture(stage,'overview',path,OUTPUT,(960,640)))
    stage.GetRootLayer().Save()
    report['views']=finish_captures(app,captures)
    for name,id in [('case_a_llw','D10'),('case_b_ilw','D25')]:
        target={b['class'] for b in report['views'][name]['boxes'] if b['drum_id']==id}
        assert target=={'drum','corrosion','spill'},(name,target)
    report['training_start_signal']=True
    report['elapsed_seconds']=round(time.perf_counter()-started,3)
    report['robot_camera']='Run capture_robot.py for dog-mounted camera proof'
    (OUTPUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    stage.GetRootLayer().Save()
    print('TRAINING_CAPTURE_OK',json.dumps(report),flush=True)
    app.close(wait_for_replicator=False)
