"""Warm Isaac process: build the hall and walking Spot once, then exec request scripts against it.

Requests arrive as /tmp/hot/req/<id>.py. Each runs in a shared namespace (definitions persist
between requests) with OUT set to /tmp/hot/out/<id>. The server touches OUT/done afterwards and
writes OUT/error.txt if the script raised. Directories under OUT holding frames/*.jpg are
encoded to <dir>.mp4 by tools/hot_hall.py.
"""
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
import hashlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SIM = Path(__file__).resolve().parent
HOT = Path('/tmp/hot')
SPAWN = (float(os.environ.get('HOT_SPAWN_X','10')),float(os.environ.get('HOT_SPAWN_Y','6')))
from front_camera import CAMERA_PATH, BODY_PATH, RESOLUTION, MOUNT_XYZ, MOUNT_QUAT, HORIZONTAL_APERTURE, FOCAL_LENGTH, expected_world_pose, rotation
VIEW = RESOLUTION


if __name__ == '__main__':
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'renderer': 'RayTracedLighting', 'display_options': 0,
                         'disable_viewport_updates': True, 'multi_gpu': True,
                         'limit_cpu_threads': 16,
                         'extra_args': ['--enable', 'isaacsim.robot.policy.examples',
                                        '--enable', 'isaacsim.sensors.camera']})
    started = time.perf_counter()
    import omni.usd
    from pxr import Gf, UsdPhysics, UsdGeom
    from isaacsim.core.api import World
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot.policy.examples import RobotPolicyRunner, get_spot_spec
    from isaacsim.sensors.camera import Camera
    from layouts import load_layout
    from capture_presentation import fixed_exposure
    from sensors import SensorWorld, load_config

    context = omni.usd.get_context()
    warehouse_mode = os.environ.get('HOT_WAREHOUSE') == '1'
    warehouse_map = None
    spawn = SPAWN
    if warehouse_mode:
        warehouse_dir = SIM / 'warehouse-v3'
        sys.path.insert(0, str(warehouse_dir))
        from drum_faults import generate_session

        warehouse_map = json.loads((warehouse_dir / 'map.json').read_text())
        spawn = tuple(warehouse_map['robot_start'][:2])
        seed_text = os.environ.get('HOT_WAREHOUSE_SEED')
        session = generate_session(HOT / 'warehouse-session' / 'warehouse.usda',
                                   seed=int(seed_text) if seed_text else None)
        if not context.open_stage(str(session)):
            raise RuntimeError(f'Could not open {session}')
    else:
        context.get_stage().GetRootLayer().Export(str(SIM / 'scene_hot.usda'))
        context.open_stage(str(SIM / 'scene_hot.usda'))
        load_layout()
    stage = context.get_stage()
    UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
    SimulationManager.set_physics_sim_device('cpu')
    spot = RobotPolicyRunner(get_spot_spec(default_spawn_position=(*spawn, 0.5)), prim_path='/World/WalkingSpot')
    spot.spawn()
    dt = spot.physics_dt
    world = World(physics_dt=dt, rendering_dt=dt)
    onboard = Camera(CAMERA_PATH,resolution=VIEW,translation=MOUNT_XYZ)
    onboard.set_local_pose(translation=MOUNT_XYZ,orientation=MOUNT_QUAT,camera_axes='world')
    UsdGeom.Xformable(onboard.prim).SetResetXformStack(False)
    onboard.prim.GetAttribute('horizontalAperture').Set(HORIZONTAL_APERTURE)
    onboard.prim.GetAttribute('verticalAperture').Set(HORIZONTAL_APERTURE*VIEW[1]/VIEW[0])
    onboard.prim.GetAttribute('focalLength').Set(FOCAL_LENGTH)
    onboard.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05,40.))
    # Presentation-only chase camera; the inspection camera stays rigid on the body.
    chase = Camera('/World/HotChase', resolution=(640, 360))
    chase.prim.GetAttribute('focalLength').Set(15.0)
    world.reset()
    chase.initialize()
    onboard.initialize()
    onboard.add_distance_to_image_plane_to_frame()
    zero = np.zeros(3, dtype=np.float32)
    world.step(render=False)
    spot.restart_from_default_state(zero)
    inventory = warehouse_map['drums'] if warehouse_mode else json.loads((SIM / 'drums.json').read_text())
    sensor = None if warehouse_mode else SensorWorld(inventory, load_config())
    font = ImageFont.load_default(size=16)
    state={'onboard_depth':True,'camera_mode':'rigid_front_only'}

    def aim(camera, eye, target):
        matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float, eye)), Gf.Vec3d(*map(float, target)), Gf.Vec3d(0, 0, 1))
        quat = matrix.GetInverse().ExtractRotationQuat()
        camera.set_world_pose(position=np.array(eye, dtype=float),
                              orientation=np.array([quat.GetReal(), *quat.GetImaginary()]), camera_axes='usd')

    def place_chase(position, yaw):
        heading = np.array([math.cos(yaw), math.sin(yaw), 0.0])
        if warehouse_mode:
            # Fixed interior overview for the first aisle route. A rear follow
            # offset at the dock crosses the west wall when Spot faces east.
            aim(chase, [1.65, 3.65, 2.2], position + [0, 0, -0.1])
        else:
            aim(chase, position - 2.4 * heading + [0, 0, 1.5], position + 1.2 * heading + [0, 0, 0.2])

    def pose():
        p, q = spot.articulation.get_world_poses()
        p, (w, x, y, z) = p.numpy().reshape(3), q.numpy().reshape(4)
        return p, math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))

    def capture_front(index,t):
        translation,orientation=onboard.get_local_pose(camera_axes='world')
        if np.linalg.norm(translation-MOUNT_XYZ)>1e-6 or abs(float(np.dot(orientation,MOUNT_QUAT)))<1-1e-6:
            raise RuntimeError('Rigid front-camera calibration changed during execution')
        bp,bq=spot.articulation.get_world_poses()
        expected_p,expected_r=expected_world_pose(bp.numpy().reshape(3),bq.numpy().reshape(4))
        cp,cq=onboard.get_world_pose(camera_axes='world')
        mount_error=float(np.linalg.norm(cp-expected_p));rotation_error=float(np.linalg.norm(rotation(cq)-expected_r))
        if mount_error>.002 or rotation_error>.002:
            raise RuntimeError(f'Front camera detached from physical body: {mount_error:.6f} m, {rotation_error:.6f} rotation error')
        native=onboard.get_current_frame()
        rgba=native.get('rgba')
        if rgba is None or not np.asarray(rgba).size:rgba=onboard.get_rgba()
        rgb=np.asarray(rgba)[:,:,:3].astype(np.uint8,copy=True)
        depth=onboard.get_depth()
        if depth is None or rgb.shape[:2]!=depth.shape[:2]:raise RuntimeError('Front RGB/depth not aligned')
        depth=np.array(depth,copy=True)
        info=dict(camera_path=CAMERA_PATH,parent=BODY_PATH,frame_id=f'front-{index:06d}',simulation_time_s=float(t),
                  native_frame=native.get('rendering_frame'),native_time=native.get('rendering_time'),
                  mount_position_error_m=mount_error,mount_rotation_error=rotation_error,
                  width=rgb.shape[1],height=rgb.shape[0],rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest())
        rgb.setflags(write=False);depth.setflags(write=False)
        state['front_frame']=dict(rgb=rgb,depth=depth,info=info)
        return state['front_frame']

    def pixels(camera):
        rgba = camera.get_rgba()
        return None if rgba is None or not rgba.size else rgba[:, :, :3].astype(np.uint8)

    def nearest_drum(position):
        drum = min(inventory, key=lambda d: math.dist(position[:2], (d['x'], d['y'])))
        return drum['display_id'], math.dist(position[:2], (drum['x'], drum['y']))

    def default_hud(draw, t, position, reading):
        if not reading:
            draw.text((10, VIEW[1] + 6), f'Locomotion smoke | t={t:.1f}s | simulator pose',
                      font=font, fill='white')
            return
        drum_id, distance = nearest_drum(position)
        dew = reading.get('dew_point_c')
        lines = [f"t {t:5.1f}s   Spot ({position[0]:.1f}, {position[1]:.1f})   nearest drum {drum_id} @ {distance:.1f} m",
                 f"SIM gamma {reading['dose_rate_uSv_h']:6.1f} uSv/h   air {reading['temperature_c']:.1f} C   "
                 f"RH {reading['relative_humidity_pct']:.0f}%   dew point {'n/a' if dew is None else f'{dew:.1f} C'}"]
        for row, text in enumerate(lines):
            draw.text((10, VIEW[1] + 6 + 20 * row), text, font=font, fill='white')

    def snapshot(t, position, hud):
        world.render()
        world.render()
        packet=capture_front(round(t*12),t)
        canvas = Image.new('RGB', (VIEW[0], VIEW[1] + 50), '#111822')
        canvas.paste(Image.fromarray(packet['rgb']), (0, 0))
        reading = sensor.sample(position, t) if sensor is not None else {}
        (hud or default_hud)(ImageDraw.Draw(canvas), t, position, reading)
        return canvas, reading

    def walk(route, name='walk', fps=12, max_s=40.0, speed=0.78, hud=None, final_yaw=None):
        """Walk Spot from the spawn point through (x, y) waypoints; save frames under OUT/name/frames."""
        frames = OUT / name / 'frames'
        frames.mkdir(parents=True, exist_ok=True)
        spot.restart_from_default_state(zero)
        world.step(render=False)
        path = [np.array(p, dtype=float) for p in route]
        stride = max(1, round(1 / (fps * dt)))
        readings = []
        settled_s = 0.0
        ready = False
        for index in range(int(max_s * fps)):
            t = index * stride * dt
            position, yaw = pose()
            place_chase(position, yaw)
            canvas, reading = snapshot(t, position, hud)
            canvas.save(frames / f'{index:05d}.jpg', quality=88)
            if path and np.linalg.norm(position[:2] - path[0]) < 0.26:
                path.pop(0)
            phase = 'approach'
            if path:
                delta = path[0] - position[:2]
                velocity = delta * min(1.4, speed / max(np.linalg.norm(delta), 0.01))
                c, s = math.cos(yaw), math.sin(yaw)
                command = np.array([c * velocity[0] + s * velocity[1],
                                    -s * velocity[0] + c * velocity[1], 0], dtype=np.float32)
            elif final_yaw is None:
                ready = True
            else:
                error = math.remainder(final_yaw - yaw, math.tau)
                if abs(error) > math.radians(8):
                    phase = 'turn_to_target'
                    settled_s = 0.0
                    command = np.array([0, 0, np.clip(1.5 * error, -0.6, 0.6)], dtype=np.float32)
                else:
                    phase = 'hold_for_capture'
                    command = zero
                    settled_s += stride * dt
                    ready = settled_s >= 0.75
            readings.append({'time_s': t, 'position_m': position.tolist(),
                             'yaw_rad': yaw, 'phase': phase, **reading})
            if ready:
                break
            for _ in range(stride):
                spot.step(dt, command)
                world.step(render=False)
        (OUT / name / 'readings.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in readings))
        final_position, actual_yaw = pose()
        summary = {'frames': index + 1, 'reached': not path, 'ready_for_capture': ready,
                   'final_xy': final_position[:2].tolist(), 'final_yaw_rad': actual_yaw}
        print('[hot] walk', name, summary, flush=True)
        return summary

    def front_still(name='front'):
        for _ in range(6):
            world.render()
        Image.fromarray(capture_front(0,0)['rgb']).save(OUT/f'{name}.png')

    def still(eye, target, name='still', focal=24):
        """Render one frame from an arbitrary viewpoint with the chase camera."""
        chase.prim.GetAttribute('focalLength').Set(float(focal))
        aim(chase, eye, target)
        for _ in range(6):
            world.render()
        Image.fromarray(pixels(chase)).save(OUT / f'{name}.png')
        chase.prim.GetAttribute('focalLength').Set(15.0)

    for _ in range(40):
        world.render()
        fixed_exposure()
    namespace = {'app': app, 'stage': stage, 'world': world, 'spot': spot, 'sensor': sensor,
                 'inventory': inventory, 'walk': walk, 'front_still': front_still, 'pose': pose, 'np': np,
                 'still': still, 'chase': chase, 'onboard': onboard, 'capture_front':capture_front, 'state': state,
                 'warehouse_map': warehouse_map}
    (HOT / 'req').mkdir(parents=True, exist_ok=True)
    (HOT / 'out').mkdir(parents=True, exist_ok=True)
    print(f'HOT_READY {time.perf_counter() - started:.1f}s', flush=True)
    while True:
        requests = sorted((HOT / 'req').glob('*.py'))
        if not requests:
            time.sleep(0.2)
            continue
        request = requests[0]
        OUT = HOT / 'out' / request.stem
        OUT.mkdir(parents=True, exist_ok=True)
        namespace['OUT'] = OUT
        began = time.perf_counter()
        try:
            exec(compile(request.read_text(), request.name, 'exec'), namespace)
        except Exception:
            (OUT / 'error.txt').write_text(traceback.format_exc())
            traceback.print_exc()
        (OUT / 'elapsed_s').write_text(f'{time.perf_counter() - began:.2f}\n')
        request.unlink()
        (OUT / 'done').touch()
        print('[hot] finished', request.stem, flush=True)
