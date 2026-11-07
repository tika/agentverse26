# Probe: mount real Isaac sensors on Spot, walk 3 s, and dump what they actually return.
import inspect
import json
import traceback
from isaacsim.sensors.rtx import LidarRtx
from isaacsim.sensors.experimental.physics import IMU, IMUSensor, JointStateSensor
from PIL import Image, ImageDraw

report = {'imu_create': str(inspect.signature(IMU.create))}


def summarise(value):
    if isinstance(value, dict):
        return {k: summarise(v) for k, v in value.items()}
    array = np.asarray(value) if not isinstance(value, (str, bytes)) else None
    if array is not None and np.issubdtype(array.dtype, np.number) and array.size > 6:
        return {'shape': list(array.shape), 'dtype': str(array.dtype),
                'min': float(np.nanmin(array)) if array.size else None, 'max': float(np.nanmax(array)) if array.size else None}
    try:
        if array is not None and array.size > 12:
            return {'shape': list(array.shape), 'dtype': str(array.dtype), 'head': array.ravel()[:6].tolist()}
        return array.tolist() if array is not None else repr(value)
    except Exception:
        return repr(value)


if 'real_sensors' not in state:
    lidar = LidarRtx('/World/WalkingSpot/body/Lidar', translation=np.array([0.0, 0.0, 0.18]),
                     config_file_name='OS1_REV6_32ch10hz512res')
    lidar.initialize()
    lidar.attach_annotator('IsaacCreateRTXLidarScanBuffer')
    imu = IMUSensor(IMU.create('/World/WalkingSpot/body/Imu'))
    joints = JointStateSensor('/World/WalkingSpot')
    state['real_sensors'] = (lidar, imu, joints)
lidar, imu, joints = state['real_sensors']

zero = np.zeros(3, dtype=np.float32)
spot.restart_from_default_state(zero)
world.step(render=False)
dt = spot.physics_dt
samples = []
for frame in range(36):  # 3 s at 12 Hz
    for _ in range(round(1 / (12 * dt))):
        spot.step(dt, np.array([0.7, 0.0, 0.0], dtype=np.float32))
        world.step(render=False)
    world.render()
    entry = {'t': frame / 12}
    for name, getter in (('imu', lambda: imu.get_data()), ('joints', lambda: joints.get_data()),
                         ('lidar', lambda: lidar.get_current_frame())):
        try:
            entry[name] = getter()
        except Exception:
            entry[name] = {'error': traceback.format_exc()[-800:]}
    samples.append(entry)
report['last'] = summarise(samples[-1])
report['imu_series'] = [summarise(s['imu']) for s in samples[::6]]
frame = samples[-1]['lidar']
report['lidar_keys'] = list(frame.keys()) if isinstance(frame, dict) else repr(frame)
# Top-down picture of whatever point data came back.
points = None
for key, value in (frame.items() if isinstance(frame, dict) else []):
    if isinstance(value, dict) and 'data' in value:
        candidate = np.asarray(value['data'])
        if candidate.ndim == 2 and candidate.shape[1] == 3 and len(candidate) > 10:
            points = candidate
            report['lidar_points_key'] = key
if points is not None:
    image = Image.new('RGB', (600, 600), 'black')
    draw = ImageDraw.Draw(image)
    for x, y, z in points[::2]:
        u, v = 300 + x * 30, 300 - y * 30
        draw.point((u, v), fill=(int(min(255, 80 + z * 120)), 220, 255))
    draw.ellipse((295, 295, 305, 305), outline='red')
    image.save(OUT / 'lidar_topdown.png')
    report['lidar_points'] = {'count': int(len(points)), 'z_range': [float(points[:, 2].min()), float(points[:, 2].max())],
                              'range_m': [float(np.linalg.norm(points, axis=1).min()), float(np.linalg.norm(points, axis=1).max())]}
(OUT / 'real_sensors.json').write_text(json.dumps(report, indent=1, default=repr))
print('[hot] real sensor probe done', flush=True)
