# Hot-worker frame toolkit: cameras, thermal rendering, perception stand-ins and the 1920x1080 layout
# (third-person, first-person + thermal, bird's-eye, stats strip). Load after sensing.py, before agent.py.
import copy
import json
import math
import omni.replicator.core as rep
from PIL import Image, ImageDraw, ImageFont
from pxr import Gf, UsdGeom
from isaacsim.sensors.camera import Camera
from inspection_payloads import microphone_window, thermal_image
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
    bird.prim.GetAttribute('focalLength').Set(11.0)
    for camera in (third, bird):
        camera.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(0.05, 60))
    seg = rep.AnnotatorRegistry.get_annotator(
        'semantic_segmentation', init_params={'semanticTypes': ['class', 'drum_id'], 'colorize': False})
    seg.attach([onboard.get_render_product_path()])
    for _ in range(10):
        world.render()
    state['scenario_cams'] = (third, bird, seg)
THIRD, BIRD, SEG = state['scenario_cams']
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


def perceive(scene):
    """Ground-truth segmentation stands in for the detector; thermal is synthetic from the same mask."""
    data = SEG.get_data()
    ids = np.asarray(data['data'])
    by_drum, corrosion, temps = {}, {}, {}
    ambient = scene['ambient_c']
    for key, label in data['info']['idToLabels'].items():
        drum_id = label.get('drum_id', '').upper()
        if not drum_id:
            continue
        count = int((ids == int(key)).sum())
        if label.get('class') == 'drum':
            by_drum[drum_id] = count
            temps[int(key)] = ambient + scene['drum_offsets_c'].get(drum_id, 1.2 if DRUMS[drum_id]['category'] == 'ILW' else 0.3)
        elif label.get('class') == 'corrosion':
            corrosion[drum_id] = corrosion.get(drum_id, 0) + count
    thermal = thermal_image(ids, temps, ambient - 0.5)
    thermal = thermal + rng.normal(0, 0.15, thermal.shape).astype(np.float32)
    drum_temps = {d: float(np.median(thermal[np.isin(ids, [int(k) for k, l in data['info']['idToLabels'].items()
                                                         if l.get('drum_id', '').upper() == d and l.get('class') == 'drum'])]))
                  for d, n in by_drum.items() if n >= 60}
    return {'drum_px': by_drum, 'corrosion_px': corrosion, 'thermal': thermal, 'drum_temps': drum_temps}


def thermal_rgb(thermal, lo, hi):
    x = np.clip((thermal - lo) / max(hi - lo, 1e-3), 0, 1)
    stops = np.array([0, .25, .5, .75, 1.0])
    palette = np.array([[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]])
    return np.stack([np.interp(x, stops, palette[:, c]) for c in range(3)], -1).astype(np.uint8)


def place_cameras(p, cam_yaw, scene):
    heading = np.array([math.cos(cam_yaw), math.sin(cam_yaw), 0.0])
    _aim(THIRD, p - 2.9 * heading + [0, 0, 1.75], p + 1.6 * heading + [0, 0, 0.2])
    eye = p + 0.62 * heading + [0, 0, 0.30]  # Ahead of Spot's nose so close looks stay clear of the body.
    look = scene.get('look')
    target = np.array([*look, 0.5]) if look is not None else eye + heading + [0, 0, -0.32]
    _aim(onboard, eye, target)
    _aim(BIRD, (p[0], p[1], 5.5), (p[0], p[1], 0.0), up=(0, 1, 0))
    return eye


def project_bird(points_xy, centre, z=LIDAR_Z):
    k = BIRD.get_intrinsics_matrix()
    depth = 5.5 - z
    u = k[0, 2] + k[0, 0] * (points_xy[:, 0] - centre[0]) / depth
    v = k[1, 2] - k[1, 1] * (points_xy[:, 1] - centre[1]) / depth
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
    hottest_c = max(perception['drum_temps'].values(), default=m.scene['ambient_c'])
    lo, hi = m.scene['ambient_c'] - 4, max(m.scene['ambient_c'] + 6, hottest_c + 2)
    inset = Image.fromarray(thermal_rgb(perception['thermal'], lo, hi)).resize((256, 144))
    first.paste(inset, (640 - 262, 360 - 150))
    canvas.paste(first, (1280, 0))
    bird = Image.fromarray(frames['bird'])
    bd = ImageDraw.Draw(bird)
    if len(m.nav.hits_world):
        for u, v in project_bird(m.nav.hits_world, p):
            bd.rectangle((u - 1, v - 1, u + 1, v + 1), fill='#33e0ff')
    route = [tuple(p[:2])] + [tuple(w) for w in m.route]
    if len(route) > 1:
        bd.line([tuple(x) for x in project_bird(np.array(route), p, 0.0)], fill='#ffffff', width=2)
    if len(m.trail) > 1:
        bd.line([tuple(x) for x in project_bird(np.array(m.trail[-200:]), p, 0.0)], fill='#5fe2af', width=2)
    if m.swab_contact is not None:
        a, b = project_bird(np.array([p[:2], m.swab_contact]), p, 0.0)
        bd.line([tuple(a), tuple(b)], fill='#7cc4ff', width=3)
        bd.ellipse((b[0] - 5, b[1] - 5, b[0] + 5, b[1] + 5), outline='#7cc4ff', width=2)
    for drum_id in m.flagged:
        d = DRUMS[drum_id]
        (u, v), = project_bird(np.array([[d['x'], d['y']]]), p, 1.0)
        bd.ellipse((u - 22, v - 22, u + 22, v + 22), outline='#ff6767', width=3)
    est = project_bird(np.array([m.nav.fused[:2]]), p, 0.0)[0]
    bd.ellipse((est[0] - 6, est[1] - 6, est[0] + 6, est[1] + 6), outline='#ffc55e', width=2)
    canvas.paste(bird, (1280, 360))
    draw = ImageDraw.Draw(canvas)
    for x, y, text in ((10, 8, '3RD PERSON  |  chase camera'), (1290, 8, '1ST PERSON  |  onboard RGB'),
                       (1290, 368, "BIRD'S EYE  |  LiDAR hits (cyan), route, trail, estimate (amber)")):
        draw.rectangle((x - 6, y - 4, x + 9 * len(text) + 4, y + 22), fill='#0d131bcc')
        draw.text((x, y), text, font=FONT[16], fill='white')
    draw.text((1290 + 640 - 262, 360 - 172), f'THERMAL (synthetic LWIR)  {lo:.0f}-{hi:.0f} C', font=FONT[14], fill='white')
    # Title banner
    draw.rectangle((0, 668, 1280, 720), fill='#0d131bdd')
    draw.text((14, 674), f'{m.number}/3  {m.title}', font=FONT[34], fill='white')
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
