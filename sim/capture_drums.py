"""Step 2 proof: exact layout, category swapping, inventory and five camera views."""
import hashlib
import json
import math
from pathlib import Path

SIM=Path(__file__).resolve().parent
OUTPUT=SIM/'out/step2'
VIEWS={
    'overview':((1.2,1.5,4.6),(12,6,1.5),20),
    'boundary_compare':((9.75,1.2,1.55),(9.75,4.15,.55),18),
    'llw_closeup':((3,1.95,1.2),(3,3.45,.44),32),
    'ilw_closeup':((12,1.4,1.6),(12,3.45,.60),30),
    'aisle2':((1,6,1.1),(14,6,.8),21),
}


def check_drums(stage,entries):
    from pxr import UsdGeom
    from drums import make_inventory
    assert entries==make_inventory(42)
    assert len(entries)==28
    assert sum(e['category']=='LLW' for e in entries)==16
    assert sum(e['category']=='ILW' for e in entries)==12
    anchors={'D01':(3,3.45),'D04':(7.5,3.45),'D06':(4.5,4.55),'D07':(6,4.55),
             'D16':(7.5,8.55),'D17':(12,3.45),'D20':(12,4.55),
             'D22':(16,4.55),'D25':(16,7.45),'D28':(16,8.55)}
    assert all((entry['x'],entry['y'])==anchors[entry['id']] for entry in entries if entry['id'] in anchors)
    for entry in entries:
        root=stage.GetPrimAtPath(entry['prim_path'])
        transform=UsdGeom.Xformable(root).GetLocalTransformation()
        position=transform.ExtractTranslation()
        assert abs(position[0]-entry['x'])<1e-8 and abs(position[1]-entry['y'])<1e-8
        body=UsdGeom.Mesh(stage.GetPrimAtPath(entry['prim_path']+'/Body'))
        points=body.GetPointsAttr().Get()
        assert max(abs(p[2]) for p in points)<=entry['height']+1e-6
        assert abs(max(math.hypot(p[0],p[1]) for p in points)-entry['radius'])<1e-6
        assert body.GetNormalsInterpolation()=='faceVarying'
        assert len(body.GetNormalsAttr().Get())==len(body.GetFaceVertexIndicesAttr().Get())
        sign=-1 if entry['row'] in ('A','C') else 1
        plate=UsdGeom.Mesh(stage.GetPrimAtPath(entry['prim_path']+'/Plate'))
        average=tuple(sum(p[k] for p in plate.GetPointsAttr().Get())/len(plate.GetPointsAttr().Get()) for k in range(3))
        # Transform the plate's radial centre into the world frame.
        world_x=average[0]*math.cos(entry['yaw'])-average[1]*math.sin(entry['yaw'])
        world_y=average[0]*math.sin(entry['yaw'])+average[1]*math.cos(entry['yaw'])
        assert abs(world_x)<1e-6 and world_y*sign>0
        assert entry['state']=='clean' and entry['faults']==[] and not entry['defects']
        assert not entry['internal_corrosion'] and not entry['obstructed']
    return {'count':28,'LLW':16,'ILW':12,'exact_inventory':True,
            'body_bounds_and_smooth_normals':True,'all_plates_face_their_aisle':True,'all_drums_clean':True}


if __name__=='__main__':
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'RayTracedLighting'})
    import omni.usd
    from build_hall import build_scene
    from drums import set_drum_category
    from capture_hall import check_scene,capture_views
    OUTPUT.mkdir(parents=True,exist_ok=True)
    context=omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM/'scene_drums.usda'))
    context.open_stage(str(SIM/'scene_drums.usda'))
    first=build_scene(42)
    stage=context.get_stage()
    fingerprint=hashlib.sha256(stage.GetRootLayer().ExportToString().encode()).hexdigest()
    original=json.loads((SIM/'drums.json').read_text())
    second=build_scene(42)
    assert fingerprint==hashlib.sha256(stage.GetRootLayer().ExportToString().encode()).hexdigest()
    assert original==json.loads((SIM/'drums.json').read_text())
    assert first['build_seconds']<120 and second['build_seconds']<120
    changed=set_drum_category('D01','ILW')
    assert changed['radius']==.4 and changed['height']==1.2 and changed['source_strength']==20
    changed_points=stage.GetPrimAtPath('/World/Drums/D01/Body').GetAttribute('points').Get()
    assert abs(max(p[2] for p in changed_points)-1.2)<1e-6
    restored=set_drum_category('D01','LLW')
    assert restored==original[0]
    build_scene(42)  # Remove unused swap-test material nodes and restore canonical ordering.
    checks=check_drums(stage,original)
    report={'first_build':first,'cached_build':second,'identical_rebuild':True,'category_swap_verified':True,
            'drums':checks,'scene':check_scene(stage,expected_drums=28)}
    rows=['ID   CATEGORY ROW X      Y      YAW     RADIUS HEIGHT STRENGTH PAINT']
    rows += [f"{e['id']}  {e['category']:8} {e['row']}   {e['x']:5.2f}  {e['y']:5.2f}  {e['yaw']:6.3f}  {e['radius']:.2f}   {e['height']:.2f}   {e['source_strength']:2}       {e['paint_color'] or 'stainless'}" for e in original]
    table='\n'.join(rows)+'\n'
    print(table,flush=True)
    (OUTPUT/'inventory.txt').write_text(table)
    print('DRUM_BUILD_OK',json.dumps(report),flush=True)
    report['views']=capture_views(app,stage,VIEWS,OUTPUT)
    stage.GetRootLayer().Save()
    (OUTPUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('DRUM_CAPTURE_OK',flush=True)
    app.close(wait_for_replicator=False)
