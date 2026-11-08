# Hot-worker frame toolkit: cameras, thermal rendering, perception stand-ins and the 1920x1080 layout
# (third-person, first-person + thermal, bird's-eye, stats strip). Load after sensing.py, before agent.py.
import copy
import json
import math
import omni.replicator.core as rep
from PIL import Image, ImageDraw, ImageFont
from pxr import Gf, UsdGeom
from isaacsim.sensors.camera import Camera
from inspection_payloads import microphone_window
from sensors import SensorWorld, load_config

W, H = 1920, 1080
FPS = 12
HALL = (0.0, 20.0, 0.0, 12.0)
LIDAR_Z, LIDAR_BEAMS, LIDAR_RANGE = 0.45, 240, 10.0
COLORS = {'PATROL': '#5fe2af', 'INVESTIGATE': '#ffc55e', 'SAMPLING': '#7cc4ff', 'ALERT': '#ff6767',
          'HOLD': '#ff6767', 'COMPLETE': '#5fe2af', 'RETREAT': '#ff9f5e'}
DRUMS = {d['id']: d for d in inventory}
FONT = {size: ImageFont.load_default(size=size) for size in (14, 16, 18, 22, 28, 34)}
ROW_FACING = {'A': -1, 'B': 1, 'C': -1, 'D': 1}


def _aim(camera, eye, target, up=(0, 0, 1)):
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float, eye)), Gf.Vec3d(*map(float, target)), Gf.Vec3d(*up))
    quat = matrix.GetInverse().ExtractRotationQuat()
    camera.set_world_pose(position=np.array(eye, dtype=float),
                          orientation=np.array([quat.GetReal(), *quat.GetImaginary()]), camera_axes='usd')


def _rgb(camera):
    rgba = camera.get_rgba()
    if rgba is None or not rgba.size:
        raise RuntimeError('Camera dropped out')
    return rgba[:, :, :3].astype(np.uint8)


if 'scenario_cams' not in state:
    third = Camera('/World/ScnThird', resolution=(1280, 720))
    bird = Camera('/World/ScnBird', resolution=(640, 360))
    third.initialize()
    bird.initialize()
    third.prim.GetAttribute('focalLength').Set(16.0)
    bird.prim.GetAttribute('focalLength').Set(4.2)
    for camera in (third, bird):
        camera.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(0.05, 60))
    seg = rep.AnnotatorRegistry.get_annotator(
        'semantic_segmentation', init_params={'semanticTypes': ['class', 'drum_id'], 'colorize': False})
    seg.attach([onboard.get_render_product_path()])
    for _ in range(10):
        world.render()
    state['scenario_cams'] = (third, bird, seg)
THIRD, BIRD, SEG = state['scenario_cams']
BIRD.prim.GetAttribute('focalLength').Set(4.2)
# Match the chase camera's near clip so an aisle-side drum renders at standoff.
onboard.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(0.05, 60))
SPILLS = [str(p.GetPath()) for p in stage.Traverse() if p.GetName().startswith('Spill_')]


def show_spills(visible):
    for path in SPILLS:
        imageable = UsdGeom.Imageable(stage.GetPrimAtPath(path))
        imageable.MakeVisible() if visible else imageable.MakeInvisible()


def full_pose():
    p, q = spot.articulation.get_world_poses()
    p, (w, x, y, z) = p.numpy().reshape(3), q.numpy().reshape(4)
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    return p, yaw, roll, pitch


def wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


EMISSIVITY = {'ILW': 0.30, 'LLW': 0.90, 'floor': 0.95, 'wall': 0.92}  # Bare stainless vs painted steel/concrete.
LWIR_RES = (160, 90)        # Microbolometer-class resolution, upscaled for display.
NETD_C = 0.05               # Sensor noise (noise-equivalent temperature difference).


def _apparent(true_c, emissivity, reflected_c):
    """Radiometric mix: emitted part plus reflected surroundings (grey body, Stefan-Boltzmann)."""
    t, r = np.asarray(true_c) + 273.15, np.asarray(reflected_c) + 273.15
    return (emissivity * t ** 4 + (1 - emissivity) * r ** 4) ** 0.25 - 273.15


def correct_emissivity(apparent_c, emissivity, reflected_c):
    """What a thermographer does once the material is known: undo the reflected component."""
    a, r = apparent_c + 273.15, reflected_c + 273.15
    return float(max((a ** 4 - (1 - emissivity) * r ** 4) / emissivity, 1.0) ** 0.25 - 273.15)


def _pixel_world(depth, camera):
    """World xyz of each pixel from the camera's (physical) pose, intrinsics and depth."""
    k = camera.get_intrinsics_matrix()
    h, w = depth.shape
    sx, sy = 640 / w, 360 / h
    vs, us = np.mgrid[0:h, 0:w]
    u, v = (us + 0.5) * sx, (vs + 0.5) * sy
    position, quat = camera.get_world_pose(camera_axes='world')
    qw, qx, qy, qz = quat
    rot = np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                    [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                    [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
    local = np.stack([depth, -(u - k[0, 2]) * depth / k[0, 0], -(v - k[1, 2]) * depth / k[1, 1]], -1)
    return local @ rot.T + position


def perceive(scene):
    """Segmentation masks (stand-in detector) plus a physically shaped synthetic LWIR frame."""
    data = SEG.get_data()
    ids_full = np.asarray(data['data'])
    labels = data['info']['idToLabels']
    by_drum, corrosion, drum_keys = {}, {}, {}
    ambient = scene['ambient_c']
    for key, label in labels.items():
        drum_id = label.get('drum_id', '').upper()
        if not drum_id:
            continue
        count = int((ids_full == int(key)).sum())
        if label.get('class') == 'drum':
            by_drum[drum_id] = count
            drum_keys[int(key)] = drum_id
        elif label.get('class') == 'corrosion':
            corrosion[drum_id] = corrosion.get(drum_id, 0) + count
            # This is the thermal sensor's rendering backend, not a visual
            # detection result: oxide on a drum shares that surface temperature.
            drum_keys[int(key)] = drum_id
    # Render at sensor resolution: nearest-neighbour ids and depth.
    h, w = LWIR_RES[1], LWIR_RES[0]
    rows = (np.arange(h) * ids_full.shape[0] / h).astype(int)
    cols = (np.arange(w) * ids_full.shape[1] / w).astype(int)
    ids = ids_full[np.ix_(rows, cols)]
    depth_full = onboard.get_depth()
    depth = np.nan_to_num(depth_full[np.ix_(rows, cols)], nan=20.0, posinf=20.0) if depth_full is not None else np.full((h, w), 20.0)
    xyz = _pixel_world(np.clip(depth, 0.05, 40.0), onboard)
    # Background: floor (warmed near hot drums) and walls (mild vertical stratification).
    true = ambient - 0.6 + 0.35 * np.clip(xyz[..., 2], 0, 6)
    emiss = np.where(xyz[..., 2] < 0.05, EMISSIVITY['floor'], EMISSIVITY['wall'])
    for drum_id, offset in scene['drum_offsets_c'].items():
        d = DRUMS[drum_id]
        gap = np.hypot(xyz[..., 0] - d['x'], xyz[..., 1] - d['y']) - d['radius']
        true = true + np.where(xyz[..., 2] < 0.05, 0.22 * offset * np.exp(-np.clip(gap, 0, None) / 0.35), 0.0)
    # Drums: per-material emissivity, vertical gradient around the fill height, angular fall-off at the rim.
    for key, drum_id in drum_keys.items():
        mask = ids == key
        if not mask.any():
            continue
        d = DRUMS[drum_id]
        offset = scene['drum_offsets_c'].get(drum_id, 1.2 if d['category'] == 'ILW' else 0.3)
        z = np.clip(xyz[..., 2] / d['height'], 0, 1)
        profile = 0.55 + 0.45 * np.exp(-((z - 0.4) / 0.32) ** 2)       # Hottest near the waste mid-height.
        rel = np.stack([xyz[..., 0] - d['x'], xyz[..., 1] - d['y']], -1)
        normal = rel / np.maximum(np.linalg.norm(rel, axis=-1, keepdims=True), 1e-6)
        to_cam = onboard.get_world_pose(camera_axes='world')[0][:2] - np.stack([xyz[..., 0], xyz[..., 1]], -1)
        to_cam /= np.maximum(np.linalg.norm(to_cam, axis=-1, keepdims=True), 1e-6)
        cos_view = np.clip((normal * to_cam).sum(-1), 0, 1)
        eps = EMISSIVITY[d['category']] * (0.35 + 0.65 * cos_view ** 0.5)  # Emissivity drops at grazing angles.
        true = np.where(mask, ambient + offset * profile, true)
        emiss = np.where(mask, eps, emiss)
    apparent = _apparent(true, emiss, ambient)
    noise = rng.normal(0, NETD_C, apparent.shape) + rng.normal(0, NETD_C, (1, w))  # Pixel + column pattern noise.
    small = (apparent + noise).astype(np.float32)
    big = np.asarray(Image.fromarray(small, mode='F').resize((ids_full.shape[1], ids_full.shape[0]), Image.BICUBIC))
    drum_temps = {}
    for drum_id, n in by_drum.items():
        keys = [k for k, dd in drum_keys.items() if dd == drum_id]
        if n >= 60:
            drum_temps[drum_id] = float(np.median(big[np.isin(ids_full, keys)]))
    return {'drum_px': by_drum, 'corrosion_px': corrosion, 'thermal': big, 'thermal_small': small,
            'drum_temps': drum_temps}


IRONBOW = np.array([[0, 0, 10], [32, 0, 96], [110, 0, 140], [184, 30, 110], [230, 90, 40], [250, 170, 20],
                    [255, 230, 110], [255, 255, 235]])


def thermal_rgb(thermal, lo, hi):
    x = np.clip((thermal - lo) / max(hi - lo, 1e-3), 0, 1)
    stops = np.linspace(0, 1, len(IRONBOW))
    return np.stack([np.interp(x, stops, IRONBOW[:, c]) for c in range(3)], -1).astype(np.uint8)


def thermal_inset(perception, size=(256, 144)):
    """Camera-style display: ironbow, auto range, colour bar and a crosshair on the hottest spot."""
    small = perception['thermal_small']
    lo, hi = float(np.percentile(small, 1)), float(max(np.percentile(small, 99.8), np.percentile(small, 1) + 4))
    image = Image.fromarray(thermal_rgb(small, lo, hi)).resize(size, Image.BILINEAR)
    draw = ImageDraw.Draw(image)
    j, i = np.unravel_index(np.argmax(small), small.shape)
    cx, cy = (i + 0.5) * size[0] / small.shape[1], (j + 0.5) * size[1] / small.shape[0]
    draw.line((cx - 7, cy, cx + 7, cy), fill='white', width=1)
    draw.line((cx, cy - 7, cx, cy + 7), fill='white', width=1)
    draw.text((min(cx + 6, size[0] - 52), max(cy - 16, 0)), f'{small.max():.1f}', font=FONT[14], fill='white')
    bar = np.linspace(1, 0, size[1])[:, None].repeat(8, 1)
    image.paste(Image.fromarray(thermal_rgb(lo + bar * (hi - lo), lo, hi)), (size[0] - 10, 0))
    return image, lo, hi


def place_cameras(p, cam_yaw, scene, onboard_yaw=None):
    onboard.prim.GetAttribute('focalLength').Set(10.0 if scene.get('coverage_mission') else 15.0)
    heading = np.array([math.cos(cam_yaw), math.sin(cam_yaw), 0.0])
    chase_eye = p - 3.4 * heading + [0, 0, 1.70]
    if scene.get('coverage_mission'):
        for angle in (cam_yaw+math.pi,cam_yaw+math.pi-.8,cam_yaw+math.pi+.8,cam_yaw):
            candidate=p+np.array([3.4*math.cos(angle),3.4*math.sin(angle),2.0])
            if .65<candidate[0]<19.35 and .65<candidate[1]<11.35:
                chase_eye=candidate;break
    # Keep the presentation camera inside the 20 x 12 m hall at the docking pose.
    chase_eye[:2] = np.clip(chase_eye[:2], [.65, .65], [19.35, 11.35])
    _aim(THIRD, chase_eye, p + .65 * heading + [0, 0, .10])
    if onboard_yaw is not None:
        heading = np.array([math.cos(onboard_yaw), math.sin(onboard_yaw), 0.0])
    if onboard_yaw is not None:
        # Match the elevated PTZ mount and leave clearance from the drum at standoff.
        eye = p + 0.35 * heading + [0, 0, 0.45]
    else:
        eye = p + 0.62 * heading + [0, 0, 0.30]
        if scene.get('coverage_mission'):eye=p+.25*heading+[0,0,.45]
    look = scene.get('look')
    target = np.array([*look, scene.get('look_height',0.5)]) if look is not None else eye + heading + [0, 0, -0.32]
    if not scene.get('coverage_mission') and onboard_yaw is not None and np.dot(target[:2] - eye[:2], heading[:2]) <= 0.1:
        target = eye + heading + [0, 0, -0.32]
    _aim(onboard, eye, target)
    _aim(BIRD, (10.0, 6.0, 5.5), (10.0, 6.0, 0.0), up=(0, 1, 0))
    return eye


def project_bird(points_xy, centre, z=LIDAR_Z):
    k = BIRD.get_intrinsics_matrix()
    depth = 5.5 - z
    u = k[0, 2] + k[0, 0] * (points_xy[:, 0] - 10.0) / depth
    v = k[1, 2] - k[1, 1] * (points_xy[:, 1] - 6.0) / depth
    return np.stack([u, v], 1)


def spark(draw, box, values, limit, color, label):
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline='#2a3644')
    draw.text((x0 + 6, y0 + 4), label, font=FONT[14], fill='#9fb2c4')
    if len(values) > 1:
        top = max((limit or 0) * 1.3, max(values) * 1.1, 1e-6)
        n = min(len(values), 120)
        pts = [(x0 + 4 + (x1 - x0 - 8) * i / 119, y1 - 4 - (y1 - y0 - 26) * v / top) for i, v in enumerate(values[-n:])]
        if limit:
            ly = y1 - 4 - (y1 - y0 - 26) * limit / top
            draw.line([(x0 + 2, ly), (x1 - 2, ly)], fill='#ff6767')
        draw.line(pts, fill=color, width=2)


def compose(m, frames, perception, reading, nav_err, p, yaw, roll, pitch, t):
    canvas = Image.new('RGB', (W, H), '#0d131b')
    canvas.paste(Image.fromarray(frames['third']), (0, 0))
    first = Image.fromarray(frames['first'])
    inset, lo, hi = thermal_inset(perception)
    first.paste(inset, (640 - 262, 360 - 150))
    canvas.paste(first, (1280, 0))
    bird = Image.fromarray(frames['bird'])
    bd = ImageDraw.Draw(bird)
    if len(m.nav.hits_world):
        for u, v in project_bird(m.nav.hits_world, p):
            bd.rectangle((u - 1, v - 1, u + 1, v + 1), fill='#33e0ff')
    route = [tuple(m.nav.fused[:2])] + [tuple(w) for w in m.route]
    if len(route) > 1:
        bd.line([tuple(x) for x in project_bird(np.array(route), p, 0.0)], fill='#ffffff', width=2)
    if len(m.trail) > 1:
        bd.line([tuple(x) for x in project_bird(np.array(m.trail[-200:]), p, 0.0)], fill='#5fe2af', width=2)
    if m.swab_contact is not None:
        a, b = project_bird(np.array([p[:2], m.swab_contact]), p, 0.0)
        bd.line([tuple(a), tuple(b)], fill='#7cc4ff', width=3)
        bd.ellipse((b[0] - 5, b[1] - 5, b[0] + 5, b[1] + 5), outline='#7cc4ff', width=2)
    est = project_bird(np.array([m.nav.fused[:2]]), p, 0.0)[0]
    bd.ellipse((est[0] - 6, est[1] - 6, est[0] + 6, est[1] + 6), outline='#ffc55e', width=2)
    canvas.paste(bird, (1280, 360))
    draw = ImageDraw.Draw(canvas)
    for x, y, text in ((10, 8, '3RD PERSON  |  chase camera'), (1290, 8, '1ST PERSON  |  onboard RGB'),
                       (1290, 368, "BIRD'S EYE  |  LiDAR hits (cyan), route, trail, estimate (amber)")):
        draw.rectangle((x - 6, y - 4, x + 9 * len(text) + 4, y + 22), fill='#0d131bcc')
        draw.text((x, y), text, font=FONT[16], fill='white')
    draw.text((1290 + 640 - 262, 360 - 172), f'LWIR 160x90 (synthetic)  {lo:.0f}-{hi:.0f} C', font=FONT[14], fill='white')
    # Title banner
    draw.rectangle((0, 668, 1280, 720), fill='#0d131bdd')
    draw.text((14, 674), m.title, font=FONT[34], fill='white')
    draw.text((1120, 680), f't = {t:4.1f} s', font=FONT[28], fill='#9fb2c4')
    # Stats strip
    y0 = 728
    status_color = COLORS.get(m.status, 'white')
    draw.rectangle((0, y0, W, H), fill='#111822')
    col = [16, 500, 980, 1460]
    draw.text((col[0], y0 + 8), 'NAVIGATION  LiDAR + IMU + leg odometry', font=FONT[18], fill='#9fb2c4')
    odom_err, fused_err, yaw_err = nav_err
    nav_lines = [f'Truth      ({p[0]:5.2f}, {p[1]:5.2f})  yaw {math.degrees(yaw):6.1f} deg',
                 f'Estimate   ({m.nav.fused[0]:5.2f}, {m.nav.fused[1]:5.2f})  yaw {math.degrees(m.nav.fused[2]):6.1f} deg',
                 f'Error  odom-only {odom_err:4.2f} m  |  fused {fused_err:4.2f} m  {yaw_err:3.1f} deg',
                 f'LiDAR  {LIDAR_BEAMS} beams, {len(m.nav.hits_world)} returns, {m.nav.landmarks} drum landmarks',
                 f'IMU  gyro z {math.degrees(m.nav.gyro):6.1f} deg/s  roll {math.degrees(roll):4.1f}  pitch {math.degrees(pitch):4.1f}',
                 f'Speed {m.nav.speed:4.2f} m/s   nearest drum {m.nearest[0]} @ {m.nearest[1]:.1f} m']
    for i, line in enumerate(nav_lines):
        draw.text((col[0], y0 + 40 + 26 * i), line, font=FONT[18], fill='white')
    draw.text((col[1], y0 + 8), 'SENSORS', font=FONT[18], fill='#9fb2c4')
    hottest = max(perception['drum_temps'].items(), key=lambda kv: kv[1], default=(None, None))
    dew = reading.get('dew_point_c')
    sensor_lines = [f"Gamma   {reading['dose_rate_uSv_h']:6.1f} uSv/h   dose {reading['mission_dose_mSv'] * 1000:5.2f} uSv",
                    f"H2  {reading.get('hydrogen_ppm', 0):6.0f} ppm    CH4 {reading.get('methane_ppm', 0):5.0f} ppm",
                    (f"Thermal max drum {hottest[0] and DRUMS[hottest[0]]['display_id']}  {hottest[1]:5.1f} C" if hottest[0]
                     else 'Thermal  no drum in view'),
                    f"Air {reading['temperature_c']:4.1f} C   RH {reading['relative_humidity_pct']:3.0f}%   "
                    f"dew pt {'n/a' if dew is None else f'{dew:4.1f} C'}",
                    f"Mic  {m.mic_db:5.1f} dBFS  {'HISS' if getattr(m, 'hiss', {}).get('hiss_score', 0) > 0.5 else 'quiet'}",
                    f"Swab  {m.swab_text}"]
    for i, line in enumerate(sensor_lines):
        draw.text((col[1], y0 + 40 + 26 * i), line, font=FONT[18], fill='white')
    spark(draw, (col[2], y0 + 10, col[2] + 460, y0 + 158), m.history['gamma'], m.scene.get('gamma_limit', 100.0),
          '#ffc55e', f"Gamma uSv/h  (limit {m.scene.get('gamma_limit', 100.0):g})")
    spark(draw, (col[2], y0 + 168, col[2] + 460, y0 + 316), m.history['h2'], m.scene.get('h2_limit'),
          '#33e0ff', 'H2 ppm  (no alarm setpoint: evidence only)' if m.scene.get('h2_limit') is None
          else f"H2 ppm  (demo alert {m.scene['h2_limit']:g})")
    draw.text((col[3], y0 + 8), 'DECISION', font=FONT[18], fill='#9fb2c4')
    draw.rectangle((col[3], y0 + 34, W - 16, y0 + 78), fill=status_color)
    draw.text((col[3] + 10, y0 + 40), m.status, font=FONT[28], fill='#0d131b')
    draw.text((col[3], y0 + 86), m.message[:52], font=FONT[16], fill='white')
    draw.text((col[3], y0 + 106), m.message[52:104], font=FONT[16], fill='white')
    draw.text((col[3], y0 + 132), f"IDs read {len(m.ids_read)}   flags {len(m.flagged)}", font=FONT[16], fill='#9fb2c4')
    for i, (et, text) in enumerate(m.events[-7:]):
        draw.text((col[3], y0 + 158 + 25 * i), f'{et:4.1f}s  {text}'[:56], font=FONT[16],
                  fill='#ff9f9f' if '!' in text else 'white')
    draw.text((col[0], H - 26), 'SIMULATION: perception = simulator ground-truth segmentation; thermal, gas, mic, swab, LiDAR, '
              'IMU, odometry = synthetic sensor models. Thresholds are demo values, not site setpoints.',
              font=FONT[14], fill='#6f8396')
    return canvas


rng = np.random.default_rng(7)
RECORDS = {d['id']: f"{d['display_id']} {d['category']}" for d in inventory}
# Solid waste: the layout's authored spill/leak decals are always hidden in these scenarios.
BASE_SCENE = {'records': RECORDS, 'drum_offsets_c': {}, 'ambient_c': 18.0,
              'gamma_limit': 100.0, 'h2_limit': None}
print('[hot] scenario lib loaded', flush=True)
