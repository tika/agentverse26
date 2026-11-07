"""Static screenshots of the 28-drum hall with the reviewed LLW barrel assets.

No robot mission, locomotion or time-varying incident runs in this entry point.
"""
import json
import hashlib
import math
from pathlib import Path
import numpy as np

SIM=Path(__file__).resolve().parent
OUT=SIM/'out/hall_barrel_v2'


if __name__=='__main__':
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'RayTracedLighting','display_options':0})
    import omni.usd
    from pxr import UsdGeom
    from layouts import load_layout
    from drums import make_inventory,set_drum_state
    from capture_hall import capture_views
    from capture_presentation import fixed_exposure
    OUT.mkdir(parents=True,exist_ok=True)
    context=omni.usd.get_context()
    scene=SIM/'scene_barrel_hall.usda'
    context.get_stage().GetRootLayer().Export(str(scene));context.open_stage(str(scene))
    metrics=load_layout()
    stage=context.get_stage()
    entries=json.loads((SIM/'drums.json').read_text())
    assert len(entries)==28 and len(stage.GetPrimAtPath('/World/Drums').GetChildren())==28
    reference={e['id']:e for e in make_inventory(42)}
    for entry in entries:
        original=reference[entry['id']]
        assert all(entry[key]==original[key] for key in ('x','y','yaw','category','display_id','paint_color'))
        assert stage.GetPrimAtPath(entry['prim_path']+'/Plate')
        if entry['category']=='LLW':
            assert entry['appearance_version']=='reviewed_llw_v2'
            assert not any(str(p.GetPath()).startswith('/World/Defects/'+entry['id']+'/Corrosion_') for p in stage.Traverse())
            if 'corrosion' in entry['faults']:
                assert stage.GetPrimAtPath('/World/Defects/'+entry['id']+'/SurfaceCorrosion')
    # Verify reset semantics with the actual USD API, then restore the fixture.
    set_drum_state('D05','clean');assert not json.loads((SIM/'drums.json').read_text())[4]['shape']['lid_rise']
    set_drum_state('D05','bulge',74)
    entries=json.loads((SIM/'drums.json').read_text())
    for identity in ('D05','D10'):
        entry=next(e for e in entries if e['id']==identity)
        assert math.isclose(entry['shape']['max_radius'],.31511137,abs_tol=1e-6)
        points=UsdGeom.Mesh(stage.GetPrimAtPath(entry['prim_path']+'/Lid')).GetPointsAttr().Get()
        assert math.isclose(max(p[2] for p in points),.935,abs_tol=1e-6)
    # Existing release fixtures remain in inventory, but the solid-waste review
    # does not show puddles. The live agent already uses this same hide policy.
    hidden=[]
    for prim in stage.Traverse():
        if prim.GetName().startswith('Spill_'):
            UsdGeom.Imageable(prim).MakeInvisible();hidden.append(str(prim.GetPath()))
    for _ in range(8):app.update();fixed_exposure(250)
    views={
        'hall_overview':((1.3,1.4,4.8),(10.0,6.0,.8),20),
        'centre_aisle':((1.3,6.0,1.65),(9.0,6.0,.65),21),
        'A03_normal_rusted':((6.25,1.6,1.25),(6.0,3.45,.45),44),
        'B01_bulged_clean':((3.35,6.4,1.26),(3.0,4.55,.46),44),
        'C02_bulged_rusted':((4.85,5.55,1.25),(4.5,7.45,.46),44),
        'C02_lid_detail':((4.75,6.2,1.35),(4.5,7.45,.76),56),
    }
    captures=capture_views(app,stage,views,OUT)
    from PIL import Image
    for name,detail in captures.items():
        pixels=np.asarray(Image.open(OUT/detail['image']).convert('RGB'))
        assert pixels.mean()>8 and np.percentile(pixels,99)>30,'Missing/black image '+name
    stage.GetRootLayer().Save()
    report=dict(scope='Static reviewed-appearance preview; no full robot mission run',
                source_hashes={name:hashlib.sha256((SIM/name).read_bytes()).hexdigest() for name in
                    ('barrel_appearance.py','corrosion_preview.py','drums.py','layouts/layout_training.json','capture_barrel_hall.py')},
                seed=42,drums=28,categories={'LLW':16,'ILW':12},layout_preserved=True,
                ids_and_plates_preserved=True,reviewed_design='7035539 / reviewed_llw_v2',
                variants={e['display_id']:dict(id=e['id'],category=e['category'],paint=e['paint_color'],
                    faults=e['faults'],shape=e['shape'],appearance_version=e['appearance_version']) for e in entries},
                views=captures,hidden_release_fixtures=hidden,metrics=metrics,
                exposure=dict(iso=250,f_number=2.8,shutter_reciprocal_s=60),
                limitations=['LLW bulge is authored geometry, not measured gas pressure',
                             'Stainless ILW design remains category-specific',
                             'No new dataset generation or model training'])
    (OUT/'report.json').write_text(json.dumps(report,indent=2))
    print('HALL_BARREL_REVIEW_OK',flush=True)
    app.close(wait_for_replicator=False)
