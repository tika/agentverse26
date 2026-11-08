"""Record Spot navigating a separate, temporary mobility arena in Isaac Sim."""
import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade
from isaacsim.sensors.camera import Camera

from front_camera import MOUNT_QUAT, MOUNT_XYZ


def record_obstacle_course():
    root = '/World/CANISMobilityCourse'
    stage.RemovePrim(root)
    UsdGeom.Xform.Define(stage, root)
    origin = np.array(warehouse_map['robot_start'][:2], dtype=float)
    goal = np.array([6., 0.])
    detour = [np.array(p) for p in [(1.65, 1.65), (4.45, 1.65), (5.4, 0.), (6., 0.)]]

    def box(name, xy, bottom, size, color, collision=True):
        prim = UsdGeom.Cube.Define(stage, f'{root}/{name}')
        prim.CreateSizeAttr(1.)
        prim.AddTranslateOp().Set(Gf.Vec3d(*(origin + xy), bottom + size[2]/2))
        prim.AddScaleOp().Set(Gf.Vec3f(*size))
        prim.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        material = UsdShade.Material.Define(stage, f'{root}/Material{name}')
        shader = UsdShade.Shader.Define(stage, f'{root}/Material{name}/Surface')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(.7)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
        UsdShade.MaterialBindingAPI.Apply(prim.GetPrim()).Bind(material)
        if collision:
            UsdPhysics.CollisionAPI.Apply(prim.GetPrim())
        return prim

    box('Deck', (3., 0.), -.22, (10., 6., .22), (.18, .23, .28))
    box('OrangeBarrier', (3., 0.), 0., (.65, 1.5, 1.15), (.95, .25, .035))
    for i, x in enumerate(np.arange(.2, 6., .55)):
        box(f'Lane{i}', (x, 0.), .002, (.22, .05, .01), (.9, .72, .15), False)
    for side, y in enumerate((-1., 1.)):
        box(f'Gate{side}', (6.2, y), 0., (.16, .16, 1.4), (.08, .75, .48))
    box('Finish', (6.2, 0.), .003, (.26, 2., .01), (.08, .75, .48), False)
    sun = UsdLux.DistantLight.Define(stage, root + '/Sun')
    sun.CreateIntensityAttr(650.)
    sun.AddRotateXYZOp().Set(Gf.Vec3f(30., -22., -15.))

    out = OUT / 'spot_obstacle_course'
    frames = out / 'frames'
    frames.mkdir(parents=True, exist_ok=True)
    step = spot.physics_dt
    stride = max(1, round(1 / (12 * step)))
    zero = np.zeros(3, dtype=np.float32)
    font = lambda size: ImageFont.load_default(size=size)
    fonts = {size: font(size) for size in (15, 20, 24, 30)}
    trajectory, events = [], []
    active_route = [goal]
    phase = 'DIRECT ROUTE'
    result = 'timeout'
    path_m = 0.
    near_count = 0
    complete_at = None

    try:
        onboard.set_local_pose(translation=MOUNT_XYZ, orientation=MOUNT_QUAT, camera_axes='world')
        spot.restart_from_default_state(zero)
        for _ in range(round(1. / step)):
            spot.step(step, zero)
            world.step(render=False)
        # Fixed elevated camera for the whole course. The depth decision uses the body camera.
        overview_eye = np.array([*origin, 0.]) + [2.0, -6.5, 6.0]
        overview_target = np.array([*origin, 0.]) + [3., 0., .1]
        transform = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*overview_eye), Gf.Vec3d(*overview_target), Gf.Vec3d(0,0,1))
        quat = transform.GetInverse().ExtractRotationQuat()
        overview = Camera(root + '/Overview', resolution=(784, 441))
        overview.prim.GetAttribute('focalLength').Set(14.)
        overview.initialize()
        overview.set_world_pose(position=overview_eye, orientation=np.array([quat.GetReal(), *quat.GetImaginary()]), camera_axes='usd')
        for _ in range(5):
            world.render()
        for index in range(24 * 12):
            t = index * stride * step
            position, yaw = pose()
            xy = position[:2] - origin
            if trajectory:
                path_m += math.dist(trajectory[-1]['xy_m'], xy)
            world.render()
            packet = capture_front(index, t)
            depth = packet['depth']
            h, w = depth.shape
            roi = depth[int(.38*h):int(.54*h),int(.43*w):int(.57*w)]
            finite = roi[np.isfinite(roi) & (roi > .1)]
            front_m = float(np.quantile(finite, .2)) if len(finite) else None
            near_count = near_count + 1 if front_m is not None and front_m < 1.75 else 0
            if phase == 'DIRECT ROUTE' and near_count >= 3:
                active_route = detour.copy()
                events.append({'time_s': round(t, 2), 'front_depth_m': round(front_m, 2),
                               'from': 'direct', 'to': 'left detour', 'frame_id': packet['info']['frame_id']})
                phase = 'DEPTH BLOCKED  >  LEFT DETOUR'
            if active_route and np.linalg.norm(xy - active_route[0]) < .24:
                active_route.pop(0)
            if not active_route and complete_at is None:
                result, complete_at = 'goal reached', t
                phase = 'GOAL REACHED'
            if position[2] < .25:
                result = 'posture limit'
                break
            trajectory.append({'time_s': round(t, 3), 'xy_m': xy.tolist(), 'front_depth_m': front_m,
                               'phase': phase})
            rgb = Image.fromarray(packet['rgb']).resize((484, 272))
            corner = overview.get_rgba()
            frame = Image.new('RGB', (1280, 720), '#10151c')
            frame.paste(Image.fromarray(corner[:, :, :3].astype(np.uint8)).resize((784, 441)), (12, 80))
            frame.paste(rgb, (804, 80))
            draw = ImageDraw.Draw(frame)
            draw.text((22, 18), 'CANIS / MOBILITY COURSE', font=fonts[30], fill='#ffd447')
            draw.text((22, 54), 'ISAAC SIM  |  BLOCKED ROUTE TEST', font=fonts[15], fill='#b7c6d0')
            draw.text((812, 364), 'BODY CAMERA  /  DEPTH GATE', font=fonts[20], fill='#ffd447')
            draw.text((812, 398), 'Forward range: ' + (f'{front_m:.2f} m' if front_m is not None else 'unresolved'),
                      font=fonts[20], fill='white')
            draw.text((22, 548), phase, font=fonts[30], fill='#76e2ce')
            draw.text((22, 596), f'{t:.1f} s sim   |   {path_m:.1f} m travelled   |   {np.linalg.norm(xy-goal):.1f} m to goal',
                      font=fonts[24], fill='white')
            draw.text((22, 660), 'DEPTH TRIGGERS REPLAN  /  BOUNDED DETOUR  /  LEARNED SPOT LOCOMOTION',
                      font=fonts[15], fill='#b7c6d0')
            # Course map with measured trajectory and barrier.
            point = lambda p: (830 + 58*p[0], 550 - 58*p[1])
            draw.rectangle((*point((2.675,.75)),*point((3.325,-.75))),fill='#d3562b')
            if len(trajectory)>1:
                draw.line([point(p['xy_m']) for p in trajectory],fill='#76e2ce',width=4)
            gx, gy = point(goal)
            draw.ellipse((gx-8,gy-8,gx+8,gy+8),fill='#ffd447')
            frame.save(frames / f'{index:05d}.jpg',quality=88)
            if complete_at is not None and t - complete_at >= 1.5:
                break
            command = zero
            if active_route:
                delta = active_route[0] - xy
                velocity = delta * min(1.6, 1.15 / max(np.linalg.norm(delta), .01))
                c, s = math.cos(yaw), math.sin(yaw)
                command = np.array([c*velocity[0]+s*velocity[1],-s*velocity[0]+c*velocity[1],
                                    np.clip(-2.*yaw,-.65,.65)],dtype=np.float32)
            for _ in range(stride):
                spot.step(step,command)
                world.step(render=False)
    finally:
        spot.restart_from_default_state(zero)
        world.step(render=False)
        stage.RemovePrim(root)

    (out/'course_report.json').write_text(json.dumps({'result':result,'goal_xy_m':goal.tolist(),
        'goal_time_s':complete_at,'path_m':round(path_m,2),'events':events,'trajectory':trajectory},indent=2))
    print(f'[hot] Course: {result}; path {path_m:.2f} m; replans {len(events)}',flush=True)

def run_in_separate_arena():
    session = stage.GetSessionLayer()
    course_layer = Sdf.Layer.CreateAnonymous('canis-mobility-course.usda')
    session.subLayerPaths.insert(0, course_layer.identifier)
    try:
        with Usd.EditContext(stage, course_layer):
            keep = {'WalkingSpot', 'HotChase', 'PhysicsScene'}
            for prim in stage.GetPrimAtPath('/World').GetChildren():
                if prim.GetName() not in keep and prim.IsA(UsdGeom.Imageable):
                    stage.OverridePrim(prim.GetPath()).SetActive(False)
            record_obstacle_course()
    finally:
        session.subLayerPaths.remove(course_layer.identifier)


run_in_separate_arena()
