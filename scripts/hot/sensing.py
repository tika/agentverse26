# Real onboard sensing for the hot worker. Load before scenario_lib.py.
# Sensors are Isaac sensors mounted on Spot (RTX LiDAR, physics IMU, joint encoders, RGB + depth).
# Estimation uses only their outputs plus the store map (walls, drum footprints), never Spot's true pose.
import json
import math
from pathlib import Path
from isaacsim.sensors.rtx import LidarRtx
from isaacsim.sensors.experimental.physics import IMU, IMUSensor, JointStateSensor

LIDAR_MOUNT_Z = 0.18
HALL_X, HALL_Y = 20.0, 12.0
# Spot leg geometry from the Boston Dynamics URDF (hip offsets, upper/lower leg). Model error is real error.
HIPS = {'fl': (0.29785, 0.055), 'fr': (0.29785, -0.055), 'hl': (-0.29785, 0.055), 'hr': (-0.29785, -0.055)}
HY_OFFSET, KNEE_OFFSET, LOWER_LEG = 0.110945, (0.025, -0.3205), 0.35

if 'real_sensors' not in state:
    lidar = LidarRtx('/World/WalkingSpot/body/Lidar', translation=np.array([0.0, 0.0, LIDAR_MOUNT_Z]),
                     config_file_name='OS1_REV6_32ch10hz512res')
    lidar.initialize()
    lidar.attach_annotator('IsaacCreateRTXLidarScanBuffer')
    imu = IMUSensor(IMU.create('/World/WalkingSpot/body/Imu'))
    joints = JointStateSensor('/World/WalkingSpot')
    state['real_sensors'] = (lidar, imu, joints)
LIDAR, IMU_SENSOR, JOINTS = state['real_sensors']
if 'onboard_depth' not in state:
    onboard.add_distance_to_image_plane_to_frame()
    state['onboard_depth'] = True


def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def feet_in_body(reading):
    """Forward kinematics from joint encoders: foot positions in the body frame."""
    q = dict(zip(reading['dof_names'], np.asarray(reading['positions'], dtype=float)))
    feet = {}
    for leg, (hx_x, hx_y) in HIPS.items():
        side = 1 if leg[1] == 'l' else -1
        knee = np.array([KNEE_OFFSET[0], 0, KNEE_OFFSET[1]])
        shank = _ry(q[f'{leg}_kn']) @ np.array([0, 0, -LOWER_LEG])
        thigh = _ry(q[f'{leg}_hy']) @ (knee + shank)
        feet[leg] = np.array([hx_x, hx_y, 0]) + _rx(q[f'{leg}_hx']) @ (np.array([0, side * HY_OFFSET, 0]) + thigh)
    return feet


def store_map():
    """Prior map: inner wall faces and drum footprints at LiDAR height."""
    pts = []
    for x in np.arange(0, HALL_X, 0.05):
        pts += [(x, 0.0), (x, HALL_Y)]
    for y in np.arange(0, HALL_Y, 0.05):
        pts += [(0.0, y), (HALL_X, y)]
    for d in inventory:
        for a in np.arange(0, 2 * math.pi, 0.03 / d['radius']):
            pts.append((d['x'] + d['radius'] * math.cos(a), d['y'] + d['radius'] * math.sin(a)))
    return np.array(pts)


MAP_POINTS = store_map()


GRID = 0.05


def _nearest_grid():
    """Nearest map point for every 5 cm cell of the hall, computed once (lookup replaces KD-tree)."""
    xs, ys = np.arange(-1, HALL_X + 1, GRID), np.arange(-1, HALL_Y + 1, GRID)
    cells = np.stack(np.meshgrid(xs, ys, indexing='ij'), -1).reshape(-1, 2)
    nearest = np.empty(len(cells), dtype=np.int32)
    for start in range(0, len(cells), 4000):
        chunk = cells[start:start + 4000]
        nearest[start:start + 4000] = ((chunk[:, None, :] - MAP_POINTS[None]) ** 2).sum(-1).argmin(1)
    return nearest.reshape(len(xs), len(ys))


if 'map_grid' not in state or state['map_grid'][0] != len(MAP_POINTS):
    state['map_grid'] = (len(MAP_POINTS), _nearest_grid())
NEAREST = state['map_grid'][1]


def icp_2d(scan, guess, iterations=10, max_pair=0.45):
    """Point-to-point ICP of a 2D scan (sensor frame) against the store map. Returns pose, inlier ratio, rms."""
    x, y, th = guess
    inliers, rms = 0.0, float('nan')
    for _ in range(iterations):
        c, s = math.cos(th), math.sin(th)
        world = scan @ np.array([[c, s], [-s, c]]) + [x, y]
        i = np.clip(((world[:, 0] + 1) / GRID).astype(int), 0, NEAREST.shape[0] - 1)
        j = np.clip(((world[:, 1] + 1) / GRID).astype(int), 0, NEAREST.shape[1] - 1)
        matched = MAP_POINTS[NEAREST[i, j]]
        dist = np.linalg.norm(world - matched, axis=1)
        keep = dist < max_pair
        inliers = float(keep.mean())
        if keep.sum() < 20:
            break
        a, b = world[keep], matched[keep]
        ca, cb = a.mean(0), b.mean(0)
        h = (a - ca).T @ (b - cb)
        dth = math.atan2(h[0, 1] - h[1, 0], h[0, 0] + h[1, 1])
        rot = np.array([[math.cos(dth), -math.sin(dth)], [math.sin(dth), math.cos(dth)]])
        t = cb - rot @ ca
        x, y = rot @ [x, y] + t
        th = wrap(th + dth)
        rms = float(np.sqrt((dist[keep] ** 2).mean()))
        max_pair = max(0.15, max_pair * 0.7)
    return np.array([x, y, th]), inliers, rms


class RealNav:
    """Leg odometry (encoders + FK) and IMU gyro at physics rate; LiDAR ICP against the map at frame rate."""

    def __init__(self, start_pose):
        self.odom = np.array(start_pose, dtype=float)   # dead reckoning only
        self.fused = np.array(start_pose, dtype=float)  # dead reckoning corrected by ICP
        self.prev_feet = None
        self.gyro = 0.0
        self.accel = np.zeros(3)
        self.roll = self.pitch = 0.0
        self.speed = 0.0
        self.icp_inliers, self.icp_rms, self.scan_points = 0.0, float('nan'), 0
        self.icp_accepted = False
        self.hits_world = np.zeros((0, 2))
        self.touchdowns = []
        self._stance = set()
        self._distance = 0.0

    def physics_update(self, dt, t):
        imu = IMU_SENSOR.get_data()
        self.gyro = float(imu['angular_velocity'][2])
        self.accel = np.asarray(imu['linear_acceleration'], dtype=float)
        w, x, y, z = imu['orientation']
        self.roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        self.pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
        feet = feet_in_body(JOINTS.get_data())
        level = _ry(self.pitch) @ _rx(self.roll)
        heights = {leg: (level @ p)[2] for leg, p in feet.items()}
        lowest = min(heights.values())
        stance = {leg for leg, h in heights.items() if h < lowest + 0.02}
        for leg in stance - self._stance:
            self.touchdowns.append((t, leg))
        if self.prev_feet is not None:
            shared = stance & self._stance
            if shared:
                step = -np.mean([level @ (feet[l] - self.prev_feet[l]) for l in shared], 0)[:2]
                for estimate in (self.odom, self.fused):
                    estimate[2] = wrap(estimate[2] + self.gyro * dt)
                    c, s = math.cos(estimate[2]), math.sin(estimate[2])
                    estimate[:2] += [c * step[0] - s * step[1], s * step[0] + c * step[1]]
                self._distance += float(np.linalg.norm(step))
            else:
                for estimate in (self.odom, self.fused):
                    estimate[2] = wrap(estimate[2] + self.gyro * dt)
        self.prev_feet, self._stance = feet, stance

    def lidar_update(self, frame_dt):
        frame = LIDAR.get_current_frame().get('IsaacCreateRTXLidarScanBuffer', {})
        points = np.asarray(frame.get('data', np.zeros((0, 3))), dtype=float).reshape(-1, 3)
        rng_ = np.linalg.norm(points[:, :2], axis=1)
        z = points[:, 2]
        keep = (z > -0.45) & (z < 0.25) & (rng_ > 0.6) & (rng_ < 14)
        scan = points[keep, :2]
        self.scan_points = int(len(points))
        self.speed = self._distance / frame_dt
        self._distance = 0.0
        if len(scan) > 1200:
            scan = scan[np.random.default_rng(0).choice(len(scan), 1200, replace=False)]
        if len(scan) < 50:
            return
        pose, self.icp_inliers, self.icp_rms = icp_2d(scan, self.fused)
        jump = float(np.linalg.norm(pose[:2] - self.fused[:2]))
        turn = abs(wrap(pose[2] - self.fused[2]))
        # Gate: a frame cannot move the estimate further than odometry could plausibly be wrong.
        self.icp_accepted = self.icp_inliers > 0.6 and jump < 0.4 and turn < math.radians(10)
        if self.icp_accepted:
            self.fused = pose
        c, s = math.cos(self.fused[2]), math.sin(self.fused[2])
        self.hits_world = scan @ np.array([[c, s], [-s, c]]) + self.fused[:2]

    def errors(self, p, yaw):
        """Truth is used only here, for display and scoring."""
        return (float(np.linalg.norm(self.odom[:2] - p[:2])), float(np.linalg.norm(self.fused[:2] - p[:2])),
                math.degrees(abs(wrap(self.fused[2] - yaw))))


def camera_rays_to_world(camera, pixels_uv, depths, body_truth, estimate):
    """Back-project pixels with depth, then express via the camera mount on the *estimated* body pose."""
    k = camera.get_intrinsics_matrix()
    position, quat = camera.get_world_pose(camera_axes='world')
    w, x, y, z = quat
    rot = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    u, v = pixels_uv[:, 0], pixels_uv[:, 1]
    # World axes camera: +x forward, +y left, +z up.
    local = np.stack([depths, -(u - k[0, 2]) * depths / k[0, 0], -(v - k[1, 2]) * depths / k[1, 1]], 1)
    world_truth = local @ rot.T + position
    # Mount transform: camera relative to the true body, re-applied to the estimated body pose.
    bp, byaw = body_truth
    rel = world_truth[:, :2] - bp[:2]
    c, s = math.cos(-byaw), math.sin(-byaw)
    in_body = rel @ np.array([[c, s], [-s, c]])
    c, s = math.cos(estimate[2]), math.sin(estimate[2])
    return in_body @ np.array([[c, s], [-s, c]]) + estimate[:2]


def thermal_findings(thermal, depth, ambient, body_truth, estimate, rise=6.0, min_px=40):
    """Hotspot detection on the thermal image alone; association to a drum via the map."""
    hot = thermal > ambient + rise
    if hot.sum() < min_px or depth is None:
        return []
    vs, us = np.nonzero(hot)
    d = depth[vs, us]
    ok = np.isfinite(d) & (d > 0.2) & (d < 20)
    if ok.sum() < min_px:
        return []
    world = camera_rays_to_world(onboard, np.stack([us[ok], vs[ok]], 1).astype(float), d[ok], body_truth, estimate)
    centre = np.median(world, 0)
    drum = min(inventory, key=lambda e: math.dist(centre, (e['x'], e['y'])))
    offset = math.dist(centre, (drum['x'], drum['y']))
    return [{'kind': 'thermal_hotspot', 'temp_c': float(np.percentile(thermal[hot], 90)), 'pixels': int(hot.sum()),
             'position_m': centre.tolist(), 'drum_id': drum['id'] if offset < drum['radius'] + 0.6 else None,
             'map_offset_m': offset}]


MIC_FLOOR_RMS = 0.002  # Self-noise of the microphone channel, measured once with the robot idle.


def hiss_detector(audio, sample_rate=16000):
    """Sustained broadband hiss: 3-7.5 kHz band must exceed the mic noise floor in every sub-window.

    Footsteps are short impulses, so they fail the 'every sub-window' persistence test; fan hum is 120 Hz.
    """
    margins = []
    for part in np.array_split(audio, 4):
        spectrum = np.abs(np.fft.rfft(part)) ** 2
        freqs = np.fft.rfftfreq(len(part), 1 / sample_rate)
        band = (freqs > 3000) & (freqs < 7500)
        band_rms = math.sqrt(2 * spectrum[band].sum()) / len(part)
        floor_rms = MIC_FLOOR_RMS * math.sqrt(band.sum() / len(freqs))
        margins.append(20 * math.log10(max(band_rms, 1e-9) / floor_rms))
    margin_db = float(min(margins))
    level = 20 * math.log10(max(float(np.sqrt(np.mean(audio ** 2))), 1e-6))
    return {'hiss_score': float(np.clip((margin_db - 3) / 9, 0, 1)), 'band_margin_db': margin_db, 'level_dbfs': level}


def robot_audio(position, t, duration, scene_sources, touchdowns, sample_rate=16000):
    """Mic signal: authored world sources + Spot's own footsteps (from detected touchdowns) + fan hum."""
    events = list(scene_sources)
    for td_t, _ in touchdowns:
        if t - 0.05 <= td_t < t + duration:
            events.append({'kind': 'impulse', 'position_m': list(position), 'time_s': td_t, 'amplitude': 0.06})
    audio = microphone_window(tuple(position), t, events, duration_s=duration, sample_rate_hz=sample_rate,
                              seed=int(t * 1000) % 2**31)
    n = np.arange(len(audio)) / sample_rate
    return audio + 0.004 * np.sin(2 * math.pi * 120 * (t + n))


class LaggedGas:
    """Catalytic/electrochemical sensors respond with a first-order lag (T63 ~ 2 s)."""

    def __init__(self, tau=2.0):
        self.tau, self.value = tau, {}

    def update(self, reading, dt):
        for key in ('hydrogen_ppm', 'methane_ppm'):
            if key in reading:
                old = self.value.get(key, 0.0)
                self.value[key] = old + (reading[key] - old) * (1 - math.exp(-dt / self.tau))
        return dict(self.value)


print('[hot] real sensing loaded', flush=True)


DECIDE_PROMPT = (
    'You are the decision layer of a Spot robot doing a routine inspection round of a nuclear waste drum store. '
    'The waste is solid. Failure modes are corrosion, breach releasing particulate (only a swab detects alpha), '
    'heating from internal reactions, and gas generation. Criteria: dose above 7.5 uSv/h is amber and above 100 '
    'uSv/h requires backing off; a swab above 0.4 Bq/cm2 alpha or 4 Bq/cm2 beta/gamma is failing containment; a drum '
    'surface 5 C or more above ambient is a thermal anomaly. Hydrogen and hiss have no alarm setpoint; weigh them as '
    'evidence together with heat. You receive the onboard camera image, readings, findings and the actions the '
    'safety layer allows. Choose exactly one offered action. Answer with only JSON: '
    '{"action_id": <offered id>, "reason": <one short sentence citing the evidence>}.')
PLATE_PROMPT = ('Read the waste drum plate. It shows a category (LLW or ILW) and an ID of one uppercase letter '
                'followed by two digits. Read only visible characters. If no plate is readable return nulls. '
                'Answer with only JSON: {"drum_id": ..., "category": ...}.')


def extract_json(text):
    """Cosmos Reason may think aloud before answering; take the last JSON object in the output."""
    import re as _re
    for match in reversed(list(_re.finditer(r'\{[^{}]*\}', text, _re.S))):
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    raise ValueError(f'No JSON in model output: {text[-200:]}')


def cosmos_chat(content, system=None, max_tokens=512, timeout_s=180):
    """POST to the vLLM OpenAI-compatible endpoint. The simulation waits for the answer."""
    import os as _os
    import urllib.request as _url
    url, key = _os.environ.get('COSMOS_URL'), _os.environ.get('VLLM_API_KEY')
    if not url or not key:
        raise RuntimeError('COSMOS_URL / VLLM_API_KEY not set on this worker')
    messages = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': content}]
    body = json.dumps({'model': 'cosmos', 'messages': messages, 'max_tokens': max_tokens, 'temperature': 0.0}).encode()
    request = _url.Request(url.rstrip('/') + '/v1/chat/completions', data=body, method='POST',
                           headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    with _url.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read())['choices'][0]['message']['content']


def _image_part(rgb, max_side=640):
    import base64 as _b64
    import io as _io
    from PIL import Image as _Image
    image = _Image.fromarray(rgb)
    image.thumbnail((max_side, max_side))
    buffer = _io.BytesIO()
    image.save(buffer, format='JPEG', quality=92)
    return {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + _b64.b64encode(buffer.getvalue()).decode()}}


def cosmos_call(method, rgb, snapshot=None):
    """read_plate -> {drum_id, category}; decide -> {action_id, reason, valid}. Errors are returned, not raised."""
    import time as _time
    started = _time.perf_counter()
    try:
        if method == 'read_plate':
            text = cosmos_chat([_image_part(rgb), {'type': 'text', 'text': PLATE_PROMPT}], max_tokens=256)
            answer = extract_json(text)
            result = {'drum_id': answer.get('drum_id'), 'category': answer.get('category')}
        else:
            text = cosmos_chat([_image_part(rgb), {'type': 'text', 'text': json.dumps(snapshot)}], system=DECIDE_PROMPT)
            answer = extract_json(text)
            offered = {a['id'] for a in snapshot['actions']}
            valid = answer.get('action_id') in offered
            result = {'action_id': answer.get('action_id') if valid else None, 'valid': valid,
                      'reason': str(answer.get('reason', '')).strip() if valid else f"not offered: {answer.get('action_id')!r}"}
        result['raw'] = text[-800:]
    except Exception as error:
        result = {'error': repr(error)[-300:], 'valid': False}
    result['latency_s'] = _time.perf_counter() - started
    return result
