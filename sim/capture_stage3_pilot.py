"""Render a compact real-camera pilot of Stage 3 scene and independent sensor cases."""
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

SIM = Path(__file__).resolve().parent
OUT = Path(os.environ.get('OUTPUT_DIR', SIM/'out'/'stage3-pilot'))
SCENARIOS = SIM/'scenarios'
RES = (1280, 720)


def fixed_exposure():
    import carb
    settings = carb.settings.get_settings()
    settings.set_bool('/rtx/post/histogram/enabled', False)
    settings.set_float('/rtx/post/tonemap/filmIso', 400.0)
    settings.set_float('/rtx/post/tonemap/fNumber', 2.8)
    settings.set_float('/rtx/post/tonemap/cameraShutter', 60.0)


if __name__ == '__main__':
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'fast_shutdown': True,
                         'extra_args': ['--enable', 'isaacsim.sensors.camera']})
    import omni.usd
    from pxr import Gf
    from isaacsim.core.api import World
    from isaacsim.sensors.camera import Camera
    from build_hall import build_scene
    from scenario_scene import apply_visual_scenario
    from hazards import HazardSensors, load_scenario

    sys.path.insert(0, str(SIM))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'frames').mkdir(exist_ok=True)
    scenarios = [load_scenario(p) for p in sorted(SCENARIOS.glob('*.json'))]
    fixed_exposure()
    stage = omni.usd.get_context().get_stage()
    world = World(physics_dt=1/60, rendering_dt=1/60)
    metrics = build_scene(42)
    entries = json.loads((SIM/'drums.json').read_text())
    visible = []
    for scenario in scenarios:
        visible.append(apply_visual_scenario(stage, scenario, SIM/'drums.json'))
    (OUT/'scene_scenarios.json').write_text(json.dumps(visible, indent=2)+'\n')
    plans = [((1.4, 6.0, 4.6), (10.0, 6.0, 1.0), 18.0, 'overview')]
    for scenario in scenarios:
        entry = next((e for e in entries if e['id'] == scenario.get('asset_id')), None)
        if entry and scenario['runtime'].get('defects'):
            face = int(entry.get('face_sign', 1))
            defect = next(iter(scenario['runtime'].get('defects', [])), {})
            if defect.get('kind') == 'corrosion' and defect.get('surface_region') == 'lower_chime':
                local_z = float(defect.get('center_z_m', .08))
            else:
                local_z = float(defect.get('center_z_m', entry['height']*.42))
            target = (entry['x'], entry['y'], entry.get('base_z',0)+local_z)
            # Back the camera away and use a longer focal length for a readable
            # silhouette without clipping labels or nearby tiers.
            eye = (entry['x']-1.00, entry['y']+face*(entry['radius']+1.20), target[2]+.18)
            plans.append((eye, target, 62.0, scenario['scenario_id']))
        wet = scenario['runtime'].get('wet_case')
        if wet:
            center = wet.get('location_m', [entry['x'], entry['y']-entry['radius']-.45, 0.0]) if entry else [5.4,.7,0.0]
            normal = (int(entry.get('face_sign',-1)) if entry and wet.get('fluid_kind') != 'external_water' else 1)
            plans.append(((center[0], center[1]+normal*1.25, 1.0), (center[0],center[1],.01), 40.0,
                          scenario['scenario_id']+'_wet_patch'))
        obstruction = scenario['runtime'].get('obstruction')
        if obstruction:
            center = obstruction['geometry_m']['center']
            # Keep the review camera inside the marked cross-aisle, clear of drum rows.
            plans.append(((8.1, 6.0, 2.2), (center[0], center[1], center[2]), 32.0,
                          scenario['scenario_id']+'_obstruction'))

    cam = Camera('/World/Stage3ReviewCamera', resolution=RES)
    cam.prim.GetAttribute('horizontalAperture').Set(36.0)
    cam.prim.GetAttribute('verticalAperture').Set(36.0*RES[1]/RES[0])
    cam.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05, 40.0))
    # Use the verified Stage-2 building lights only. No capture-only fill light.
    world.reset(); cam.initialize(); cam.add_distance_to_image_plane_to_frame()

    def aim(eye, target, focal):
        matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0,0,1))
        q = matrix.GetInverse().ExtractRotationQuat()
        cam.set_world_pose(position=np.asarray(eye), orientation=np.asarray([q.GetReal(),*q.GetImaginary()]), camera_axes='usd')
        cam.prim.GetAttribute('focalLength').Set(float(focal))

    def rgb_now():
        pixels = cam.get_rgba()
        return None if pixels is None or not pixels.size else pixels[:,:,:3].astype(np.uint8)

    aim(*plans[0][:3]); start=time.perf_counter(); warm=0
    while rgb_now() is None:
        if time.perf_counter()-start > 300:
            raise RuntimeError(f'RTX warmup timed out after {warm} renders')
        fixed_exposure(); app.update(); world.render(); warm += 1
    for _ in range(8): world.render()

    frames=[]
    for i,(eye,target,focal,label) in enumerate(plans):
        aim(eye,target,focal); fixed_exposure()
        # Match the verified Stage-2 tour path: two render flushes per paused
        # camera pose, then capture exactly that pose.
        world.render(); world.render()
        pixels=rgb_now()
        if pixels is None: raise RuntimeError(f'camera returned no RGB at pilot frame {i}')
        Image.fromarray(pixels).save(OUT/'frames'/f'{i:05d}.jpg',quality=92)
        depth=cam.get_depth(); d=None
        if depth is not None and depth.size:
            h,w=depth.shape[:2]; tile=depth[h//2-4:h//2+5,w//2-4:w//2+5]
            tile=tile[np.isfinite(tile)&(tile>0)]; d=float(np.median(tile)) if tile.size else None
        frames.append({'frame':i,'label':label,'eye_m':list(eye),'target_m':list(target),
                       'mean_luma':float(pixels.mean()),'center_depth_m':d})
    traces=[]
    for scenario in scenarios:
        source=HazardSensors(scenario)
        # Samples exercise the startup lag and then a valid observation. Truth is not copied.
        trace={'scenario_id':scenario['scenario_id'],'samples':[source.sample([1.0,6.0,.55],0.0),
                source.sample([1.0,6.0,.55],5.0)]}
        swab=scenario['runtime'].get('swab')
        if swab:
            trace['independent_observations']=[{'kind':'virtual_contact_swab','timestamp_s':swab['t_s'],
                'units':'Bq/cm2','alpha':swab['alpha_bq_cm2'],'beta_gamma':swab['beta_gamma_bq_cm2'],
                'calibration':swab['calibration'],'cause':swab['cause']}]
        traces.append(trace)
    (OUT/'sensor_traces.json').write_text(json.dumps(traces,indent=2)+'\n')
    report={'renderer':'RayTracedLighting (RTX)','resolution':list(RES),'warmup_renders':warm,
            'scene_metrics':metrics,'frame_count':len(frames),'frames':frames,
            'camera_fill_light':{'enabled':False,'reason':'use scene lighting without capture-only exposure aid'},
            'note':'scenario truth is excluded from sensor_traces; no leak/source conclusion is inferred from a visual defect'}
    (OUT/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print('STAGE3_PILOT_OK',len(frames),'frames',flush=True)
    app.close()
