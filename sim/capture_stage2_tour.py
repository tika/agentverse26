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
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'renderer': 'RayTracedLighting', 'display_options': 0})
    import sys
    sys.path.insert(0, str(SIM))
    import omni.usd
    import omni.replicator.core as rep
    from pxr import Gf, UsdGeom
    from build_hall import build_scene
    from training_capture import camera

    OUT.mkdir(parents=True, exist_ok=True)
    stage = omni.usd.get_context().get_stage()
    metrics = build_scene(42)
    entries = json.loads((SIM / 'drums.json').read_text())
    check = inventory_check(stage, entries)
    (OUT / 'inventory_check.json').write_text(json.dumps(check, indent=2))
    print('INVENTORY_CHECK', json.dumps({k: check[k] for k in ('usd_drums', 'pallet_decks', 'pass')}), flush=True)

    plan = shots(entries)
    cam = camera(stage, '/World/TourCamera', plan[0][0], plan[0][1], plan[0][2], RES)
    product = rep.create.render_product(cam, RES)
    # Read annotators directly after every step (BasicWriter dropped frames with a paused timeline).
    rgb_ann = rep.AnnotatorRegistry.get_annotator('rgb')
    depth_ann = rep.AnnotatorRegistry.get_annotator('distance_to_image_plane')
    rgb_ann.attach([product])
    depth_ann.attach([product])
    (OUT / 'frames').mkdir(exist_ok=True)
    for _ in range(40):
        app.update()
        fixed_exposure()

    def set_pose(eye, target, focal):
        prim = UsdGeom.Camera(stage.GetPrimAtPath(cam))
        pose = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1)).GetInverse()
        UsdGeom.Xformable(prim).GetOrderedXformOps()[0].Set(pose)
        prim.GetFocalLengthAttr().Set(focal)

    frames = []
    for i, (eye, target, focal, label) in enumerate(plan):
        set_pose(eye, target, focal)
        fixed_exposure()
        app.update()
        app.update()
        rep.orchestrator.step(rt_subframes=2, delta_time=0.0, pause_timeline=True)
        pixels = np.asarray(rgb_ann.get_data())[:, :, :3].astype(np.uint8)
        d = np.asarray(depth_ann.get_data(), dtype=np.float32).reshape(RES[1], RES[0])
        Image.fromarray(pixels).save(OUT / 'frames' / f'{i:05d}.jpg', quality=90)
        patch = d[RES[1] // 2 - 5:RES[1] // 2 + 6, RES[0] // 2 - 5:RES[0] // 2 + 6]
        patch = patch[np.isfinite(patch) & (patch > 0)]
        frames.append({'frame': i, 'eye': list(eye), 'target': list(target), 'focal_mm': focal,
                       'gt_review_label': label, 'mean_luma': float(pixels.mean()),
                       'depth_center_m': float(np.median(patch)) if patch.size else None})
        if i % 20 == 0:
            print('TOUR_FRAME', i, flush=True)
    rep.orchestrator.wait_until_complete()
    assert len(list((OUT / 'frames').glob('*.jpg'))) == len(plan)
    manifest = {'renderer': 'RayTracedLighting', 'resolution': list(RES), 'fps': 10,
                'fixed_exposure': {'iso': 400, 'f_number': 2.8, 'shutter_reciprocal_s': 60},
                'robot_motion': False, 'scene_metrics': metrics, 'frames': frames,
                'note': 'gt_review_label is ground truth for review overlays only, never a perception input'}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print('STAGE2_TOUR_OK', len(frames), flush=True)
    app.close(wait_for_replicator=False)
