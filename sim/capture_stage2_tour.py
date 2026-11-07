"""Stage-2 review tour: corrected hall, stacked drums, plates at several tiers.

Only the review camera moves (no robot motion is claimed). Outputs under
$OUTPUT_DIR (default sim/out/stage2_tour):
  frames/00000.jpg ...      raw RGB (no overlays), JPEG q90
  manifest.json              per-frame camera eye/target/focal, centre depth (m),
                             and the GROUND-TRUTH aim label for review overlays only
  inventory_check.json       USD stage vs drums.json cross-check
"""
import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image

SIM = Path(__file__).resolve().parent
OUT = Path(os.environ.get('OUTPUT_DIR', SIM / 'out' / 'stage2_tour'))
RES = (1280, 720)


def fixed_exposure():
    import carb
    s = carb.settings.get_settings()
    s.set_bool('/rtx/post/histogram/enabled', False)
    s.set_float('/rtx/post/tonemap/filmIso', 400.0)
    s.set_float('/rtx/post/tonemap/fNumber', 2.8)
    s.set_float('/rtx/post/tonemap/cameraShutter', 60.0)


def inventory_check(stage, entries):
    from pxr import UsdGeom
    usd = {}
    for prim in stage.GetPrimAtPath('/World/Drums').GetChildren():
        t = UsdGeom.Xformable(prim).GetLocalTransformation().ExtractTranslation()
        usd[prim.GetName()] = (float(t[0]), float(t[1]), float(t[2]), bool(stage.GetPrimAtPath(str(prim.GetPath()) + '/Plate')))
    mismatches = []
    for e in entries:
        got = usd.get(e['id'])
        if got is None:
            mismatches.append(f"{e['id']} missing in USD")
            continue
        want = (e['x'], e['y'], e.get('base_z', 0.0))
        if max(abs(a - b) for a, b in zip(got[:3], want)) > 1e-4:
            mismatches.append(f"{e['id']} USD {got[:3]} != inventory {want}")
        if not got[3]:
            mismatches.append(f"{e['id']} has no plate")
    extra = sorted(set(usd) - {e['id'] for e in entries})
    pallets = len([p for p in stage.GetPrimAtPath('/World/Pallets').GetChildren() if p.GetName().endswith('_Deck')])
    tiers = {}
    for e in entries:
        tiers[e['location']['tier']] = tiers.get(e['location']['tier'], 0) + 1
    return {'usd_drums': len(usd), 'inventory_drums': len(entries), 'extra_in_usd': extra,
            'mismatches': mismatches, 'pallet_decks': pallets, 'by_tier': tiers,
            'location_codes_unique': len({e['display_id'] for e in entries}) == len(entries),
            'pass': not mismatches and not extra and pallets == len(entries)}


def plate_z(e):
    return e['base_z'] + 0.6 * e['height']


def shots(entries):
    by_code = {e['display_id']: e for e in entries}
    out = []
    # 1. High corner overview: floor, walls, lights, stacks (F1-F5 review).
    for i in range(14):
        t = i / 13
        out.append(((0.7 + 0.8 * t, 0.7, 4.7), (10, 6 + 1.0 * t, 0.8), 18, 'overview'))
    # 2. Back wall looking down the hall: walls, doors, signage, ducts.
    for i in range(10):
        t = i / 9
        out.append(((19.2, 6.0 - 0.6 * t, 1.8), (2, 6.0, 1.6 + 0.4 * t), 18, 'hall_end_view'))
    # 3. Walk the clear centre aisle (lane B) at robot-ish height.
    for i in range(28):
        x = 1.5 + 7.5 * i / 27
        out.append(((x, 6.0, 1.0), (x + 3.0, 6.25, 0.9), 24, 'aisle_B_walk'))
    # 4. Plate stops tilting T1 -> top tier (camera tilt coverage).
    for stack in ('B-L-01', 'B-R-02', 'B-L-05'):
        tiers = sorted((e for e in entries if e['stack_id'] == stack), key=lambda e: e['location']['tier'])
        e0 = tiers[0]
        eye_y = 6.0 + (-0.1 if e0['y'] > 6 else 0.1)
        eye = (e0['x'], eye_y, 1.55)
        zs = [plate_z(e) for e in tiers]
        steps = 22
        for i in range(steps):
            u = i / (steps - 1) * (len(zs) - 1)
            k = min(int(u), len(zs) - 2)
            z = zs[k] + (zs[k + 1] - zs[k]) * (u - k)
            tier = tiers[min(round(u), len(tiers) - 1)]
            out.append((eye, (e0['x'], e0['y'], z), 45, 'plate:' + tier['display_id']))
    # 5. Pull back to a wide aisle view.
    for i in range(10):
        t = i / 9
        out.append(((12.0 - 2 * t, 6.0, 1.55 + 0.9 * t), (16, 6.6, 1.2), 22, 'pull_back'))
    assert all(l.split(':')[1] in by_code for *_, l in out if l.startswith('plate:'))
    return out


if __name__ == '__main__':
    # Same capture path as the verified scripts/spot_spill.py: World + isaacsim Camera class.
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'fast_shutdown': True,
                         'extra_args': ['--enable', 'isaacsim.sensors.camera']})
    import sys
    sys.path.insert(0, str(SIM))
    import omni.usd
    from pxr import Gf
    from isaacsim.core.api import World
    from isaacsim.sensors.camera import Camera
    from build_hall import build_scene

    fixed_exposure()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'frames').mkdir(exist_ok=True)
    stage = omni.usd.get_context().get_stage()
    world = World(physics_dt=1 / 60, rendering_dt=1 / 60)
    metrics = build_scene(42)
    entries = json.loads((SIM / 'drums.json').read_text())
    check = inventory_check(stage, entries)
    (OUT / 'inventory_check.json').write_text(json.dumps(check, indent=2))
    print('INVENTORY_CHECK', json.dumps({k: check[k] for k in ('usd_drums', 'pallet_decks', 'pass')}), flush=True)

    plan = shots(entries)
    cam = Camera('/World/TourCamera', resolution=RES)
    cam.prim.GetAttribute('horizontalAperture').Set(36.0)
    cam.prim.GetAttribute('verticalAperture').Set(36.0 * RES[1] / RES[0])
    cam.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(0.05, 40.0))

    def aim(eye, target, focal):
        m = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1))
        q = m.GetInverse().ExtractRotationQuat()
        cam.set_world_pose(position=np.array(eye), orientation=np.array([q.GetReal(), *q.GetImaginary()]),
                           camera_axes='usd')
        cam.prim.GetAttribute('focalLength').Set(float(focal))

    world.reset()
    cam.initialize()
    cam.add_distance_to_image_plane_to_frame()
    aim(*plan[0][:3])

    def rgb_now():
        rgba = cam.get_rgba()
        return None if rgba is None or not rgba.size else rgba[:, :, :3].astype(np.uint8)

    # The first run showed ~116 steps before RTX produced frames (shader/texture warm-up),
    # so wait on time, not a fixed small count.
    import time
    warm_start = time.perf_counter()
    warm_renders = 0
    while rgb_now() is None:
        if time.perf_counter() - warm_start > 240:
            raise RuntimeError(f'Camera warm-up failed after {warm_renders} renders')
        fixed_exposure()
        app.update()
        world.render()
        warm_renders += 1
    for _ in range(10):  # let progressive RT settle on the first view
        world.render()
    print('WARMUP', warm_renders, 'renders', round(time.perf_counter() - warm_start, 1), 's', flush=True)

    frames = []
    for i, (eye, target, focal, label) in enumerate(plan):
        aim(eye, target, focal)
        fixed_exposure()
        for _ in range(4):
            app.update()
            world.render()
        pixels = rgb_now()
        for _ in range(20):
            if pixels is not None:
                break
            world.render()
            pixels = rgb_now()
        if pixels is None:
            raise RuntimeError(f'Camera dropped out at frame {i}')
        Image.fromarray(pixels).save(OUT / 'frames' / f'{i:05d}.jpg', quality=90)
        d = cam.get_depth()
        centre = None
        if d is not None and d.size:
            h, w = d.shape[:2]
            patch = d[h // 2 - 5:h // 2 + 6, w // 2 - 5:w // 2 + 6]
            patch = patch[np.isfinite(patch) & (patch > 0)]
            centre = float(np.median(patch)) if patch.size else None
        frames.append({'frame': i, 'eye': list(eye), 'target': list(target), 'focal_mm': focal,
                       'gt_review_label': label, 'mean_luma': float(pixels.mean()),
                       'depth_center_m': centre})
        if i % 20 == 0:
            print('TOUR_FRAME', i, flush=True)
    assert len(list((OUT / 'frames').glob('*.jpg'))) == len(plan)
    manifest = {'renderer': 'RayTracedLighting (default RTX)', 'resolution': list(RES), 'fps': 10,
                'fixed_exposure': {'iso': 400, 'f_number': 2.8, 'shutter_reciprocal_s': 60},
                'robot_motion': False, 'scene_metrics': metrics, 'frames': frames, 'warmup_renders': warm_renders,
                'intrinsics': cam.get_intrinsics_matrix().tolist(),
                'note': 'gt_review_label is ground truth for review overlays only, never a perception input'}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print('STAGE2_TOUR_OK', len(frames), flush=True)
    app.close()
