"""Isaac Sim 6.2 check of the composed v3 warehouse (the real target, not the Blender proxy).

Run inside the Isaac container:  /isaac-sim/python.sh isaac_check.py --stage /stage/warehouse-v3.usda --out /tmp/out
1. Opens the composed stage (shell + site + storage sublayers) and records prim/mesh/light counts.
2. Physics: drops a 0.2 m test sphere above every route node and one above each rack's top deck;
   after 3 s of simulation the aisle spheres must rest on the floor and the rack spheres on the rack
   proxy (nothing falls through, nothing is caught by unexpected geometry).
3. Applies the v2 semantic taxonomies (class=drum + LLW/ILW, drum_id) to /World/Drums/Dnn.
4. Renders RTX views with v2's fixed exposure: overhead (near clip above the eaves removes the
   roof) and interior views of the main aisle, an LLW aisle and the ILW bank.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--stage', required=True)
parser.add_argument('--map', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--fault-seed', type=int)
args, _ = parser.parse_known_args()
OUT = Path(args.out)
OUT.mkdir(parents=True, exist_ok=True)

from isaacsim import SimulationApp  # noqa: E402
app = SimulationApp({'headless': True, 'fast_shutdown': True, 'extra_args': ['--enable', 'isaacsim.sensors.camera']})

import carb  # noqa: E402
import omni.timeline  # noqa: E402
import omni.usd  # noqa: E402
from pxr import Gf, Usd, UsdGeom, UsdLux, UsdPhysics, PhysxSchema  # noqa: E402

report = {'stage': args.stage, 'started': time.time()}
layout = json.loads(Path(args.map).read_text())
W, D, _ = layout['hall']
ctx = omni.usd.get_context()
t0 = time.perf_counter()
faults = []
if args.fault_seed is not None:
    from drum_faults import generate_session
    manifest = OUT / 'evaluator-fault-manifest.json'
    session = generate_session(OUT / 'warehouse-session.usda', seed=args.fault_seed,
                               manifest=manifest, base_stage=args.stage, map_path=args.map)
    faults = json.loads(manifest.read_text())['drums']
    report['fault_session'] = {'affected': len(faults), 'seed': args.fault_seed}
    ctx.open_stage(str(session))
else:
    ctx.open_stage(args.stage)
for _ in range(20):
    app.update()
stage = ctx.get_stage()
report['open_seconds'] = round(time.perf_counter() - t0, 2)
report['counts'] = {
    'prims': sum(1 for _ in stage.Traverse()),
    'meshes': sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)),
    'lights': sum(1 for p in stage.Traverse() if p.HasAPI(UsdLux.LightAPI) or p.IsA(UsdLux.BoundableLightBase) or p.IsA(UsdLux.NonboundableLightBase)),
    'drums': len(stage.GetPrimAtPath('/World/Drums').GetChildren()),
    'colliders': sum(1 for p in stage.Traverse() if p.HasAPI(UsdPhysics.CollisionAPI)),
    'meters_per_unit': UsdGeom.GetStageMetersPerUnit(stage), 'up_axis': UsdGeom.GetStageUpAxis(stage)}
print('ISAAC_OPEN_OK', json.dumps(report['counts']), flush=True)

# --- semantics (v2 contract: class + drum_id taxonomies) ---------------------------------
try:
    from isaacsim.core.experimental.utils.semantics import add_labels
    by_id = {d['id']: d for d in layout['drums']}
    report['fault_samples'] = {}
    n = 0
    for prim in stage.GetPrimAtPath('/World/Drums').GetChildren():
        d = by_id.get(prim.GetName())
        if d:
            add_labels(prim, labels=['drum'], taxonomy='class')
            add_labels(prim, labels=[d['id']], taxonomy='drum_id')
            add_labels(prim, labels=[d['category']], taxonomy='waste_category')
            n += 1
    report['semantics'] = {'labelled_drums': n, 'taxonomies': ['class', 'drum_id', 'waste_category']}
except Exception as exc:
    report['semantics'] = {'error': repr(exc)}

# --- physics drop test --------------------------------------------------------------------
scene = UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
scene.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
scene.CreateGravityMagnitudeAttr(9.81)
probes = {}
UsdGeom.Scope.Define(stage, '/World/Probes')
def probe(name, x, y, z):
    s = UsdGeom.Sphere.Define(stage, f'/World/Probes/{name}')
    s.CreateRadiusAttr(.2)
    UsdGeom.Xformable(s).AddTranslateOp().Set(Gf.Vec3d(x, y, z))
    UsdPhysics.CollisionAPI.Apply(s.GetPrim())
    UsdPhysics.RigidBodyAPI.Apply(s.GetPrim())
    UsdPhysics.MassAPI.Apply(s.GetPrim()).CreateMassAttr(5.0)
    probes[name] = (x, y, z)
for k, (x, y) in layout['nodes'].items():
    probe('Node_' + k.replace('-', '_'), x, y, 1.0)
for r in layout['racks']:
    x, y = r['center']
    probe('Rack_' + r['id'].replace('-', '_'), x, y, 5.0)
timeline = omni.timeline.get_timeline_interface()
timeline.play()
for _ in range(240):
    app.update()
timeline.pause()
cache = UsdGeom.XformCache()
results, bad = {}, []
for name, (x, y, z) in probes.items():
    p = stage.GetPrimAtPath(f'/World/Probes/{name}')
    t = cache.GetLocalToWorldTransform(p).ExtractTranslation()
    results[name] = [round(t[0], 3), round(t[1], 3), round(t[2], 3)]
    if name.startswith('Node_'):
        ok = abs(t[2] - .2) < .05 and math.hypot(t[0] - x, t[1] - y) < .3
    else:
        ok = t[2] > 1.0 and math.hypot(t[0] - x, t[1] - y) < .8   # resting on the rack proxy, not the floor
    if not ok:
        bad.append(name)
report['physics_drop'] = {'probes': len(probes), 'failed': bad, 'final_xyz': results,
                          'pass': not bad}
print('ISAAC_PHYSICS', json.dumps({'probes': len(probes), 'failed': bad}), flush=True)
timeline.stop()
stage.RemovePrim('/World/Probes')
for _ in range(10):
    app.update()

# --- RTX review renders ---------------------------------------------------------------------
settings = carb.settings.get_settings()
settings.set_bool('/rtx/post/histogram/enabled', False)
settings.set_float('/rtx/post/tonemap/filmIso', 400.0)
settings.set_float('/rtx/post/tonemap/fNumber', 2.8)
settings.set_float('/rtx/post/tonemap/cameraShutter', 60.0)
settings.set_bool('/app/viewport/grid/enabled', False)
import omni.replicator.core as rep  # noqa: E402
main_y = D / 2
a_x = sorted(r['center'][0] for r in layout['racks'] if r['zone'] == 'A')
b_x = sorted(r['center'][0] for r in layout['racks'] if r['zone'] == 'B')
rows = sorted({r['center'][1] for r in layout['racks']})
aisle_y = (rows[0] + rows[1]) / 2
dist = 45.0
def drum_pick(category):
    ds = [d for d in layout['drums'] if d['category'] == category and d['location']['tier'] == 1 and d.get('inspection_route_y') is not None]
    return sorted(ds, key=lambda d: (d['location']['lane'], d['location']['column']))[len(ds) // 3]
llw_d, ilw_d = drum_pick('LLW'), drum_pick('ILW')
def label_z(d):
    prim = stage.GetPrimAtPath(d['prim_path'])
    return d['base_z'] + prim.GetAttribute('warehouse:printCenterFraction').Get() * d['height']
def close(d, dist=.95):
    ry = d['inspection_route_y']; sgn = 1 if ry > d['y'] else -1
    ez = label_z(d)
    return ((d['x'], d['y'] + sgn * (d['radius'] + dist), ez), (d['x'], d['y'], ez), 30, (.05, 200))
views = {
    # near clip at z=4.3 m (above the 4.03 m stack tops) strips roof, crane and fixtures.
    'overhead': ((W / 2, D / 2, dist), (W / 2, D / 2 + 1e-3, 0), 36 * dist / (W + 2), (dist - 4.3, 200)),
    'ceiling_from_aisle': ((1.4, main_y, 1.5), (13.0, main_y, 7.4), 14, (.05, 200)),
    'roof_section': ((1.0, main_y, 5.7), (7.0, main_y, 8.0), 15, (.05, 200)),
    'rear_elevation': ((37.0, main_y, 4.6), (W, main_y, 4.6), 20, (.05, 200)),
    'rear_wall_approach': ((13.6, main_y, 1.7), (W, main_y, 3.0), 16, (.05, 200)),
    'interior_main_aisle': ((1.3, main_y - .3, 1.7), (W - 2, main_y + .6, 4.2), 14, (.05, 200)),
    'llw_aisle': ((a_x[0] - 1.8, aisle_y, 1.6), (a_x[-1] + 1, aisle_y + .2, 1.8), 16, (.05, 200)),
    'ilw_bank': ((W / 2, main_y - 3.0, 2.2), (b_x[-1], main_y + 2.0, 2.0), 16, (.05, 200)),
    'floor_detail': ((5.0, main_y - .2, 1.3), (8.5, main_y - 1.0, 0.0), 24, (.05, 200)),
    'close_llw_' + llw_d['id']: close(llw_d),
    'close_ilw_' + ilw_d['id']: close(ilw_d, 1.1),
}
if faults:
    by_id = {d['id']: d for d in layout['drums']}
    report['fault_samples'] = {}
    for category in ('LLW', 'ILW'):
        for feature in ('corrosion', 'bulging'):
            candidates = [e for e in faults if e['category'] == category and feature in e]
            def score(entry):
                d = by_id[entry['drum_id']]
                facing = (d['face_sign'] * math.pi / 2 - d['yaw']) / math.tau
                data = entry[feature]
                angles = [site['u'] for site in data['sites']] if feature == 'corrosion' else [data['azimuth_rad'] / math.tau]
                proximity = min(abs((angle - facing + .5) % 1 - .5) for angle in angles)
                return data['severity'] - 1.7 * proximity - .10 * (d['location']['tier'] - 1)
            entry = max(candidates, key=score)
            d = by_id[entry['drum_id']]
            x, y = d['x'], d['y']
            level = .47
            offset = .48
            if feature == 'corrosion':
                facing = (d['face_sign'] * math.pi / 2 - d['yaw']) / math.tau
                site = min(entry[feature]['sites'], key=lambda site: abs((site['u'] - facing + .5) % 1 - .5))
                level = min(.79, max(.18, site['height_fraction']))
                offset = .07
            z = d['base_z'] + level * d['height']
            name = f'fault_{category}_{feature}_{d["id"]}'
            views[name] = ((x + offset, d['inspection_route_y'], z),
                           (x, y, z), 24, (.05, 40))
            report['fault_samples'][name] = entry
report['close_drums'] = {'LLW': [llw_d['id'], llw_d['display_id']], 'ILW': [ilw_d['id'], ilw_d['display_id']]}
# v2-proven capture path (stage-3 pilot): isaacsim Camera + World.render() until RGB arrives.
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.sensors.camera import Camera  # noqa: E402
world = World(physics_dt=1 / 60, rendering_dt=1 / 60)
cam = Camera(prim_path='/World/ReviewCameras/Cam', resolution=(1600, 1000))
world.reset()
cam.initialize()
def aim(eye, target, focal, clip, up=(0, 0, 1)):
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(*up))
    q = matrix.GetInverse().ExtractRotationQuat()
    cam.set_world_pose(position=np.asarray(eye), orientation=np.asarray([q.GetReal(), *q.GetImaginary()]), camera_axes='usd')
    cam.prim.GetAttribute('focalLength').Set(float(focal))
    cam.prim.GetAttribute('horizontalAperture').Set(36.0)
    cam.prim.GetAttribute('verticalAperture').Set(22.5)
    cam.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(*clip))
def rgb_now():
    px = cam.get_rgba()
    return None if px is None or not px.size else px[:, :, :3].astype(np.uint8)
saved = {}
first = next(iter(views.values()))
aim(*first)
t_warm, warm = time.perf_counter(), 0
while rgb_now() is None and time.perf_counter() - t_warm < 300:
    app.update(); world.render(); warm += 1
for name, (eye, target, focal, clip) in views.items():
    if name == 'overhead':
        focal = 36 * dist / max(W + 4, (D + 4) * 1.6)  # fit both axes
        aim(eye, target, focal, clip, up=(0, 1, 0))
    else:
        aim(eye, target, focal, clip)
    for _ in range(40):
        world.render()
    px = rgb_now()
    if px is not None:
        (OUT / name).mkdir(exist_ok=True)
        Image.fromarray(px).save(OUT / name / 'rgb.png')
        saved[name] = {'file': f'{name}/rgb.png', 'mean': round(float(px.mean()), 1)}
        print('VIEW_SAVED', name, saved[name], flush=True)
# Actual v2 inspection camera (robot.attach_cameras): 0.6 m, 10 deg down, 22.5 mm on 36 mm (78 deg), 640x640,
# robot standing on the drum's inspection route, camera turned to face the stack.
icam = Camera(prim_path='/World/ReviewCameras/Inspection', resolution=(640, 640))
icam.initialize()
if faults:
    from warehouse_sensors import WarehouseSensors
    sensor_backend = WarehouseSensors.from_manifest(manifest)
    render_path = icam.get_render_product_path()
    depth_capture = rep.AnnotatorRegistry.get_annotator('distance_to_image_plane')
    seg_capture = rep.AnnotatorRegistry.get_annotator(
        'semantic_segmentation', init_params={'semanticTypes': ['class', 'drum_id'], 'colorize': False})
    depth_capture.attach([render_path])
    seg_capture.attach([render_path])
    report['physical_sensors'] = {'inventory_drums': len(sensor_backend._drums), 'frames': {}}
for _ in range(10):
    world.render()
inspection_samples = [('llw', llw_d), ('ilw', ilw_d)]
if faults:
    warm = next(d for d in sensor_backend._drums
                if d['category'] == 'ILW' and d['scenario'] == 'warm_venting')
    inspection_samples.append(('warm_ilw', by_id[warm['drum_id']]))
for index, (tag, d) in enumerate(inspection_samples):
    ry = d['inspection_route_y']
    # The robot body is on the route. Its forward-mounted lens is 0.48 m closer.
    eye_y = ry + math.copysign(.48, d['y'] - ry)
    eye = (d['x'], eye_y, .6)
    target = (d['x'], d['y'], .6 - math.tan(math.radians(10)) * abs(eye_y - d['y']))
    mtx = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1))
    q = mtx.GetInverse().ExtractRotationQuat()
    icam.set_world_pose(position=np.asarray(eye), orientation=np.asarray([q.GetReal(), *q.GetImaginary()]), camera_axes='usd')
    icam.prim.GetAttribute('focalLength').Set(22.5)
    icam.prim.GetAttribute('horizontalAperture').Set(36.0)
    icam.prim.GetAttribute('verticalAperture').Set(36.0)
    icam.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05, 40.0))
    for _ in range(40):
        world.render()
    px = icam.get_rgba()
    if px is not None and px.size:
        name = f'inspection_cam_{tag}_{d["id"]}'
        (OUT / name).mkdir(exist_ok=True)
        Image.fromarray(px[:, :, :3].astype(np.uint8)).save(OUT / name / 'rgb.png')
        saved[name] = {'file': f'{name}/rgb.png', 'eye': eye, 'body_xy': [d['x'], ry], 'drum': d['id'], 'display_id': d['display_id'],
                       'label_z': round(label_z(d), 3), 'camera': 'v2 Spot inspection camera: 0.6 m, -10 deg, 78 deg FOV, 640x640'}
        print('VIEW_SAVED', name, flush=True)

    if faults:
        depth = depth_capture.get_data()
        seg = seg_capture.get_data()
        if isinstance(depth, dict):
            depth = depth['data']
        thermal = sensor_backend.thermal_from_camera(depth, seg, icam.get_intrinsics_matrix(), mtx.GetInverse())
        hit_count = sum(int((seg['data'] == int(key)).sum())
                        for key, label in seg['info']['idToLabels'].items()
                        if label.get('class') == 'drum' and label.get('drum_id'))
        if not hit_count or not np.isfinite(thermal).any():
            raise RuntimeError('Thermal review has no valid package pixels')
        if tag == 'warm_ilw' and float(np.nanmax(thermal)) <= warm['thermal']['ambient_c'] + 1.0:
            raise RuntimeError('The warm ILW control was not resolved in the thermal image')
        file = f'physical_{tag}_apparent_c.npy'
        np.save(OUT / file, thermal)
        readings = sensor_backend.sample((d['x'], ry, .6), 2 * index,
                                         gamma_xyz=eye, gas_xyz=eye)
        report['physical_sensors']['frames'][tag] = {
            'file': file, 'package_pixels': hit_count,
            'finite_pixels': int(np.isfinite(thermal).sum()),
            'apparent_range_c': [float(np.nanmin(thermal)), float(np.nanmax(thermal))],
            'observations': readings,
        }


# 30 s RTX tour (24 fps): roof-off overview, entry + ceiling, LLW close pass, ILW close pass, rear gate.
if '--tour' in sys.argv:
    tcam = Camera(prim_path='/World/ReviewCameras/Tour', resolution=(1280, 720))
    tcam.initialize()
    tcam.prim.GetAttribute('horizontalAperture').Set(36.0)
    tcam.prim.GetAttribute('verticalAperture').Set(20.25)
    tcam.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05, 200.0))
    roof = UsdGeom.Imageable(stage.GetPrimAtPath('/World/Hall/Roof'))
    tdir = OUT / 'tour_frames'; tdir.mkdir(exist_ok=True)
    def smooth(t):
        return t * t * (3 - 2 * t)
    lr, ir = llw_d['inspection_route_y'], ilw_d['inspection_route_y']
    segs = [  # (seconds, eye0, eye1, look0, look1, roof_visible, focal)
        (6, (5, 4, 31), (19, 4, 31), (W / 2, D / 2, 0), (W / 2, D / 2, 0), False, 18),
        (6, (.8, main_y, 1.5), (10.5, main_y, 1.7), (12, main_y, 6.5), (20, main_y, 3.0), True, 14),
        (6, (llw_d['x'] - .36, lr, label_z(llw_d)), (llw_d['x'] + .29, lr, label_z(llw_d)),
         (llw_d['x'], llw_d['y'], label_z(llw_d)), (llw_d['x'], llw_d['y'], label_z(llw_d)), True, 31),
        (6, (ilw_d['x'] - .35, ir, label_z(ilw_d)), (ilw_d['x'] + .29, ir, label_z(ilw_d)),
         (ilw_d['x'], ilw_d['y'], label_z(ilw_d)), (ilw_d['x'], ilw_d['y'], label_z(ilw_d)), True, 36),
        (6, (14.0, main_y, 1.7), (21.3, main_y, 2.2), (W, main_y, 2.6), (W, main_y, 5.0), True, 16),
    ]
    k = 0
    for secs, e0, e1, l0, l1, roof_on, focal in segs:
        if roof_on:
            roof.MakeVisible()
        else:
            roof.MakeInvisible()
        n = secs * 24
        for i in range(n):
            t = smooth(i / (n - 1))
            eye = [a + (b - a) * t for a, b in zip(e0, e1)]
            look = [a + (b - a) * t for a, b in zip(l0, l1)]
            mtx = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*look), Gf.Vec3d(0, 0, 1))
            q = mtx.GetInverse().ExtractRotationQuat()
            tcam.set_world_pose(position=np.asarray(eye), orientation=np.asarray([q.GetReal(), *q.GetImaginary()]), camera_axes='usd')
            tcam.prim.GetAttribute('focalLength').Set(float(focal))
            for _ in range(3 if i else 12):
                world.render()
            px = tcam.get_rgba()
            if px is not None and px.size:
                Image.fromarray(px[:, :, :3].astype(np.uint8)).save(tdir / f'f{k:04d}.jpg', quality=90)
            k += 1
    roof.MakeVisible()
    report['tour'] = {'frames': k, 'fps': 24, 'seconds': k / 24, 'resolution': [1280, 720]}
    print('TOUR_DONE', k, flush=True)
report['render'] = {'warmup_renders': warm, 'views': saved}
report['views'] = {n: [v['file']] for n, v in saved.items()}
report['seconds_total'] = round(time.time() - report['started'], 1)
(OUT / 'isaac_report.json').write_text(json.dumps(report, indent=2) + '\n')
print('ISAAC_CHECK_DONE', json.dumps({k: report[k] for k in ('counts', 'views')}), flush=True)
app.close(wait_for_replicator=False)
