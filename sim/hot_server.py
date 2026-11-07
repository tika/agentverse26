"""Warm Isaac process: build the hall and walking Spot once, then exec request scripts against it.

Requests arrive as /tmp/hot/req/<id>.py. Each runs in a shared namespace (definitions persist
between requests) with OUT set to /tmp/hot/out/<id>. The server touches OUT/done afterwards and
writes OUT/error.txt if the script raised. Directories under OUT holding frames/*.jpg are
encoded to <dir>.mp4 by tools/hot_hall.py.
"""
import json
import math
from pathlib import Path
import time
import traceback
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SIM = Path(__file__).resolve().parent
HOT = Path('/tmp/hot')
SPAWN = (10.0, 6.0)  # West edge of the ILW rows, centre aisle.
VIEW = (640, 360)


if __name__ == '__main__':
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'renderer': 'RayTracedLighting', 'display_options': 0,
                         'extra_args': ['--enable', 'isaacsim.robot.policy.examples',
                                        '--enable', 'isaacsim.sensors.camera']})
    started = time.perf_counter()
    import omni.usd
    from pxr import Gf, UsdPhysics
    from isaacsim.core.api import World
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot.policy.examples import RobotPolicyRunner, get_spot_spec
    from isaacsim.sensors.camera import Camera
    from layouts import load_layout
    from capture_presentation import fixed_exposure
    from sensors import SensorWorld, load_config

    context = omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM / 'scene_hot.usda'))
    context.open_stage(str(SIM / 'scene_hot.usda'))
    load_layout()
    stage = context.get_stage()
    UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
    SimulationManager.set_physics_sim_device('cpu')
    spot = RobotPolicyRunner(get_spot_spec(default_spawn_position=(*SPAWN, 0.5)), prim_path='/World/WalkingSpot')
    spot.spawn()
    dt = spot.physics_dt
    world = World(physics_dt=dt, rendering_dt=dt)
    chase = Camera('/World/HotChase', resolution=VIEW)
    onboard = Camera('/World/HotOnboard', resolution=VIEW)
    for camera in (chase, onboard):
        camera.prim.GetAttribute('focalLength').Set(15.0)
    world.reset()
    for camera in (chase, onboard):
        camera.initialize()
    zero = np.zeros(3, dtype=np.float32)
    world.step(render=False)
    spot.restart_from_default_state(zero)
    inventory = json.loads((SIM / 'drums.json').read_text())
    sensor = SensorWorld(inventory, load_config())
    font = ImageFont.load_default(size=16)

    def aim(camera, eye, target):
        matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float, eye)), Gf.Vec3d(*map(float, target)), Gf.Vec3d(0, 0, 1))
        quat = matrix.GetInverse().ExtractRotationQuat()
        camera.set_world_pose(position=np.array(eye, dtype=float),
                              orientation=np.array([quat.GetReal(), *quat.GetImaginary()]), camera_axes='usd')

    def pose():
        p, q = spot.articulation.get_world_poses()
        p, (w, x, y, z) = p.numpy().reshape(3), q.numpy().reshape(4)
        return p, math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))

    def place_cameras(position, yaw):
        heading = np.array([math.cos(yaw), math.sin(yaw), 0.0])
        aim(chase, position - 2.4 * heading + [0, 0, 1.5], position + 1.2 * heading + [0, 0, 0.2])
        eye = position + 0.47 * heading + [0, 0, 0.22]
        aim(onboard, eye, eye + heading + [0, 0, -0.12])

    def pixels(camera):
        rgba = camera.get_rgba()
        return None if rgba is None or not rgba.size else rgba[:, :, :3].astype(np.uint8)

    def nearest_drum(position):
        drum = min(inventory, key=lambda d: math.dist(position[:2], (d['x'], d['y'])))
        return drum['display_id'], math.dist(position[:2], (drum['x'], drum['y']))

    def default_hud(draw, t, position, reading):
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
        left, right = pixels(chase), pixels(onboard)
        if left is None or right is None:
            raise RuntimeError('Camera dropped out')
        canvas = Image.new('RGB', (2 * VIEW[0], VIEW[1] + 50), '#111822')
        canvas.paste(Image.fromarray(left), (0, 0))
        canvas.paste(Image.fromarray(right), (VIEW[0], 0))
        reading = sensor.sample(position, t)
        (hud or default_hud)(ImageDraw.Draw(canvas), t, position, reading)
        return canvas, reading

    def walk(route, name='walk', fps=12, max_s=40.0, speed=0.78, hud=None):
        """Walk Spot from the spawn point through (x, y) waypoints; save frames under OUT/name/frames."""
        frames = OUT / name / 'frames'
        frames.mkdir(parents=True, exist_ok=True)
        spot.restart_from_default_state(zero)
        world.step(render=False)
        path = [np.array(p, dtype=float) for p in route]
        stride = max(1, round(1 / (fps * dt)))
        readings = []
        for index in range(int(max_s * fps)):
            t = index * stride * dt
            position, yaw = pose()
            place_cameras(position, yaw)
            canvas, reading = snapshot(t, position, hud)
            canvas.save(frames / f'{index:05d}.jpg', quality=88)
            readings.append({'time_s': t, 'position_m': position.tolist(), **reading})
            if path and np.linalg.norm(position[:2] - path[0]) < 0.26:
                path.pop(0)
            if not path:
                break
            delta = path[0] - position[:2]
            velocity = delta * min(1.4, speed / max(np.linalg.norm(delta), 0.01))
            c, s = math.cos(yaw), math.sin(yaw)
            command = np.array([c * velocity[0] + s * velocity[1], -s * velocity[0] + c * velocity[1], 0],
                               dtype=np.float32)
            for _ in range(stride):
                spot.step(dt, command)
                world.step(render=False)
        (OUT / name / 'readings.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in readings))
        summary = {'frames': index + 1, 'reached': not path, 'final_xy': pose()[0][:2].tolist()}
        print('[hot] walk', name, summary, flush=True)
        return summary

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
                 'inventory': inventory, 'walk': walk, 'still': still, 'pose': pose, 'np': np,
                 'chase': chase, 'onboard': onboard, 'state': {}}
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
