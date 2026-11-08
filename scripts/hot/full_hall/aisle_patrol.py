# CANIS aisle patrol: wh_cond_walk.py's aisle A round (24 LLW + 12 ILW drums, both sides, 3 tiers) with the
# warehouse-v3 sensor backend live during the walk: LWIR thermal and depth from the inspection camera, gamma,
# air and hydrogen at the robot. Writes the run files tools/full_hall_report/pdf/build_pdf_report.py reads.
# Recorded at a constant 24 fps of simulation time (inference waits are not in the video), so it can be sped up.
# Environment and seeded faults used as built (HOT_WAREHOUSE_SEED=42). Existing YOLO26s.
import io as _io
import json as _json
import math as _math
import os as _os
import time as _wtime
import urllib.request as _url
from pathlib import Path as _Path
from PIL import Image, ImageDraw, ImageFont

W_NAME = globals().get('W_NAME', 'canis_aisle_patrol')
W_MAX_COLS = int(globals().get('W_MAX_COLS', 99))
W_LLW_XMAX = float(globals().get('W_LLW_XMAX', 5.0))
W_ILW_XMAX = float(globals().get('W_ILW_XMAX', 16.6))
W_MAX_S = float(globals().get('W_MAX_S', 600.0))
FPS = 24
FLAG, WEAK, CONFIRM, VIEWS, CLOSE_VIEWS = 0.50, 0.25, 0.72, 3, 5
TOP_TILT = 0.60          # rad; steeper upward views are outside the detector's training range
SETTLE_S, YOLO_EVERY_S, LOOK_TIMEOUT_S, SECOND_STEP = 0.35, 0.4, 3.5, 0.40
YEL, BLK, WHITE, GREY = (255, 212, 0), (10, 10, 10), (255, 255, 255), (110, 118, 128)
RGB = {'OK': (60, 220, 140), 'Suspect': (255, 160, 40), 'Confirmed defect': (255, 70, 70),
       "Couldn't inspect": (255, 160, 40), 'Checking': WHITE}
import base64 as _b64
_fd = _Path('/tmp/canis_fonts'); _fd.mkdir(parents=True, exist_ok=True)
for _w in ('400', '600'):
    (_fd / f'plexmono{_w}.ttf').write_bytes(_b64.b64decode(globals()[f'MONO_{_w}']))
SIZES = (12, 14, 16, 18, 20, 22, 24, 26, 30, 36)
F = {s: ImageFont.truetype(str(_fd / 'plexmono400.ttf'), s) for s in SIZES}      # IBM Plex Mono, console style
FB = {s: ImageFont.truetype(str(_fd / 'plexmono600.ttf'), s) for s in SIZES}
LOGO_D = Image.open(_io.BytesIO(_b64.b64decode(LOGO_DOG))).convert('RGBA')
LOGO_W = Image.open(_io.BytesIO(_b64.b64decode(LOGO_WORD))).convert('RGBA')
_START = _wtime.strftime('%Y-%m-%d %H:%M:%S UTC', _wtime.gmtime())
AISLE_Y = 4.83
SECTION = [d for d in inventory if d.get('inspection_route_y') == AISLE_Y and d.get('visible_face', True)
           and d['x'] <= (W_LLW_XMAX if d['category'] == 'LLW' else W_ILW_XMAX)]
XS = sorted({round(d['x'], 2) for d in SECTION})
SLOT = {x: k for k, x in enumerate(XS)}
BY_ID = {d['id']: d for d in inventory}
CODE = {d['id']: d['display_id'] for d in SECTION}
from pxr import Gf, UsdGeom
import numpy as _np2
run_dir = OUT / W_NAME

# ------------------------------------------------------------------ sensor backend (simulator side)
# Same seed as the rendered session, so the physical inventory matches the faults on screen.
from warehouse_physics import generate_inventory as _gen_inv
from warehouse_sensors import WarehouseSensors as _WS
_SEED = int(_os.environ.get('HOT_WAREHOUSE_SEED', '42'))
_physical = _gen_inv(warehouse_map, _SEED)
sensors = _WS(_physical)
PHYS = {d['drum_id']: d for d in _physical['drums']}
# Optional planted source (scenario only, simulator side): {'drum': display id, 'strength': uSv/h m^2, 'mu': 1/m}.
W_HOT = globals().get('W_HOT')
if W_HOT:
    _hot_id = next(d['id'] for d in inventory if d['display_id'] == W_HOT['drum'])
    _k = [d['drum_id'] for d in _physical['drums']].index(_hot_id)
    sensors._strength[3 * _k:3 * _k + 3] = W_HOT['strength'] / 3
    sensors._mu[_k] = W_HOT['mu']
GAMMA_Z, BUDGET_USV = 0.30, 50_000.0      # detector above the body origin; sim/inspection_config.json 50 mSv budget
DOSE_AMBER, DOSE_STOP = 7.5, 100.0        # uSv/h; sim/inspection_config.json controlled_zone and hot_spot
DOSE_CLEAR = 0.5 * DOSE_STOP              # retreat target: last pose read below half the stop limit
TH_STEP = 4                                # 640 -> 160 px LWIR (thermal cores are low resolution)
NEAR = [d for d in inventory if abs(d['y'] - AISLE_Y) < 3.0]
(run_dir / 'stills').mkdir(parents=True, exist_ok=True)
frames_dir = run_dir / 'frames'
frames_dir.mkdir(parents=True, exist_ok=True)


def _plan():
    groups = []
    for x in XS:
        cat = next(d['category'] for d in SECTION if round(d['x'], 2) == x)
        if groups and groups[-1]['cat'] == cat and x - groups[-1]['xs'][0] <= 0.8:
            groups[-1]['xs'].append(x)
        else:
            groups.append({'cat': cat, 'xs': [x]})
    stops = []
    for g in groups:
        stop = [round(g['xs'][0] - (1.0 if g['cat'] == 'LLW' else 1.3), 3), AISLE_Y]
        sides = []
        for side in ('L', 'R'):
            for x in g['xs']:
                col = sorted([d for d in SECTION if round(d['x'], 2) == x and d['location']['side'] == side],
                             key=lambda d: d['location']['tier'])
                if col:
                    sides.append({'side': side, 'column': col[0]['location']['column'],
                                  'yaw': _math.atan2(col[0]['y'] - stop[1], col[0]['x'] - stop[0]),
                                  'looks': [{'drum': d['id'], 'pitch': 0.0} for d in col]})
        stops.append({'columns': g['xs'], 'cat': g['cat'], 'stop_xy': stop, 'sides': sides})
    return stops


PLAN = _plan()[:W_MAX_COLS]
if globals().get('W_STOPS'):
    PLAN = [PLAN[k] for k in W_STOPS]

# ------------------------------------------------------------------ chase camera (presentation only)
from isaacsim.sensors.camera import Camera as _Camera
if 'canis_chase' not in state:
    _chase = _Camera('/World/CanisChase', resolution=(1280, 720))
    _chase.prim.GetAttribute('focalLength').Set(14.0)
    _chase.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05, 60.))
    _chase.initialize()
    state['canis_chase'] = _chase
chase = state['canis_chase']


def aim(camera, eye, target):
    m = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float, eye)), Gf.Vec3d(*map(float, target)), Gf.Vec3d(0, 0, 1))
    q = m.GetInverse().ExtractRotationQuat()
    camera.set_world_pose(position=_np2.array(eye, dtype=float), orientation=_np2.array([q.GetReal(), *q.GetImaginary()]),
                          camera_axes='usd')


def CHASE_EYE(p):
    """Behind and above the robot, inside the hall."""
    return (max(p[0] - 2.4, 0.6), AISLE_Y, 2.6)


if 'canis_eye' not in state:
    _eye = _Camera('/World/CanisEye', resolution=(640, 640))
    _eye.prim.GetAttribute('horizontalAperture').Set(20.955)
    _eye.prim.GetAttribute('verticalAperture').Set(20.955)
    _eye.prim.GetAttribute('focalLength').Set(20.955 / 2 / _math.tan(_math.radians(77.3) / 2))
    _eye.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05, 60.))
    _eye.initialize()
    state['canis_eye'] = _eye
eye_cam = state['canis_eye']
if 'canis_eye_depth' not in state:
    eye_cam.add_distance_to_image_plane_to_frame()
    state['canis_eye_depth'] = True
FX = 320 / _math.tan(_math.radians(77.3) / 2)
MOUNT_F, MOUNT_Z = 0.35, 0.45      # forward of / above the body origin (inspection camera mount)


def eye_pos(p, yaw):
    return _np2.array([p[0] + MOUNT_F * _math.cos(yaw), p[1] + MOUNT_F * _math.sin(yaw), p[2] + MOUNT_Z])


def basis(eye, target):
    f = _np2.asarray(target, float) - eye; f /= _np2.linalg.norm(f)
    r = _np2.cross(f, [0, 0, 1.0]); r /= _np2.linalg.norm(r)
    return f, r, _np2.cross(r, f)


def outline(d, n=24):
    a = _np2.linspace(0, 2 * _math.pi, n, endpoint=False)
    ring = _np2.stack([d['x'] + d['radius'] * _np2.cos(a), d['y'] + d['radius'] * _np2.sin(a)], 1)
    return _np2.vstack([_np2.column_stack([ring, _np2.full(n, d['base_z'])]),
                        _np2.column_stack([ring, _np2.full(n, d['base_z'] + d['height'])])])


def project_box(d, eye, target):
    f, r, u = basis(eye, target)
    rel = outline(d) - eye
    depth = rel @ f
    if _np2.any(depth < 0.3):
        return None
    uu = 320 + FX * (rel @ r) / depth
    vv = 320 - FX * (rel @ u) / depth
    return [float(uu.min()), float(vv.min()), float(uu.max()), float(vv.max())]


def centre(d):
    return (d['x'], d['y'], d['base_z'] + d['height'] / 2)


def set_tilt(pitch):
    mission['pitch'] = pitch


def grab(camera):
    rgba = camera.get_rgba()
    return None if rgba is None or not _np2.asarray(rgba).size else _np2.asarray(rgba)[:, :, :3].astype(_np2.uint8)


def grab_depth():
    """Distance to the image plane (m), sampled at the LWIR resolution."""
    depth = eye_cam.get_current_frame().get('distance_to_image_plane')
    if depth is None or not _np2.asarray(depth).size:
        return None
    return _np2.asarray(depth, float).squeeze()[TH_STEP // 2::TH_STEP, TH_STEP // 2::TH_STEP]


def thermal_view(depth, eye, target):
    """Apparent LWIR image from the warehouse backend. Drum hits come from depth + the map (simulator side only).
    Returns the temperature image and, per visible drum, the 95th-percentile apparent surface temperature."""
    f, r, u = basis(eye, target)
    n = depth.shape[0]
    pix = (_np2.arange(n) * TH_STEP + TH_STEP / 2 - 320) / FX
    rays = f[None, None, :] + r[None, None, :] * pix[None, :, None] - u[None, None, :] * pix[:, None, None]
    good = _np2.isfinite(depth) & (depth > 0.05) & (depth < 50)
    xyz = eye + rays * _np2.where(good, depth, _np2.nan)[..., None]
    labels = _np2.full(depth.shape, '', dtype='<U8')
    for d in NEAR:
        if _math.hypot(d['x'] - eye[0], d['y'] - eye[1]) > 9:
            continue
        hit = (_np2.hypot(xyz[..., 0] - d['x'], xyz[..., 1] - d['y']) <= d['radius'] + 0.03) & \
              (xyz[..., 2] >= d['base_z'] - 0.02) & (xyz[..., 2] <= d['base_z'] + d['height'] + 0.03)
        labels[hit] = d['id']
    image = sensors.thermal_frame(_np2.where(good[..., None], xyz, _np2.nan), labels, camera_xyz=eye)
    per = {}
    for i in _np2.unique(labels[labels != '']):
        values = image[(labels == i) & _np2.isfinite(image)]
        if values.size >= 12:
            per[str(i)] = float(_np2.percentile(values, 95))
    return image, per


_INFERNO = _np2.array([(0, 0, 4), (40, 11, 84), (101, 21, 110), (159, 42, 99), (212, 72, 66),
                       (245, 125, 21), (250, 193, 39), (252, 255, 164)], float)
_DEPTH = _np2.array([(253, 231, 37), (94, 201, 98), (33, 145, 140), (59, 82, 139), (68, 1, 84), (20, 0, 30)], float)


def colourise(values, lo, hi, lut, size):
    v = _np2.nan_to_num((values - lo) / max(1e-6, hi - lo), nan=1.0)
    k = _np2.clip(v, 0, 1) * (len(lut) - 1)
    a = _np2.floor(k).astype(int).clip(0, len(lut) - 2)
    w = (k - a)[..., None]
    rgb = (lut[a] * (1 - w) + lut[a + 1] * w).astype(_np2.uint8)
    return Image.fromarray(rgb).resize((size, size), Image.BILINEAR)


# ------------------------------------------------------------------ YOLO (training-equivalent 77.3 deg crop)
X0, Y0, SIDE = 0, 0, 640


def yolo(rgb):
    crop = Image.fromarray(rgb)
    buffer = _io.BytesIO()
    crop.save(buffer, format='PNG')
    boundary = 'canis-cond'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="front.png"\r\n'
            'Content-Type: image/png\r\n\r\n').encode() + buffer.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
    request = _url.Request(_os.environ['DETECTOR_API_URL'].rstrip('/') + '/predict?confidence=0.25', data=body,
                           headers={'Modal-Key': _os.environ['DETECTOR_API_KEY'], 'Modal-Secret': _os.environ['DETECTOR_API_SECRET'],
                                    'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with _url.urlopen(request, timeout=180) as response:
        result = _json.loads(response.read())
    return crop, result                     # boxes in the uploaded 640x640 image's pixels


COND = {'normal': ('normal',), 'rust': ('corrosion',), 'bulge': ('bulge',), 'rust_and_bulge': ('corrosion', 'bulge')}


def iou(a, b):
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / max(1e-6, u)


def clip(b):
    return [max(0.0, min(640.0, v)) for v in b]


def faults_of(v):
    return sorted(k for k, c in v.items() if k != 'normal' and c >= FLAG)


def vlabel(v):
    f = faults_of(v)
    if f:
        return {'corrosion': 'rust', 'bulge': 'bulge'}[f[0]] if len(f) == 1 else 'rust+bulge'
    return 'normal' if v.get('normal', 0) >= FLAG else ('weak' if v else 'none')


def all_boxes(eye, target):
    out = {}
    for d in SECTION:
        bx = project_box(d, eye, target)
        if bx:
            out[d['id']] = bx
    return out


def inside_frac(b, t):
    w = max(0, min(b[2], t[2]) - max(b[0], t[0]))
    h = max(0, min(b[3], t[3]) - max(b[1], t[1]))
    return w * h / max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))


def second_spot(stop, d):
    """Closer look: tiers 1-2 from 0.7 m before the drum and 0.6 m towards its side of the 3.3 m aisle;
    tier 3 from the same stop, longer (getting closer only steepens the view)."""
    if d['location']['tier'] == 3:
        return tuple(stop['stop_xy'])
    side = 1 if d['y'] > AISLE_Y else -1
    return (round(max(stop['stop_xy'][0], d['x'] - (0.7 if d['category'] == 'LLW' else 1.0)), 3), AISLE_Y + side * 0.6)


def aim_at(stop, d):
    return _math.atan2(d['y'] - stop[1], d['x'] - stop[0]), 0.0


# ------------------------------------------------------------------ plan -> queue of looks
def stop_looks(stop):
    out = []
    for side in stop['sides']:                       # L first, then R
        for lk in side['looks']:                     # tier 1, 2, 3
            out.append({'drum': lk['drum'], 'yaw': side['yaw'], 'pitch': lk['pitch'], 'pass': 'side'})
    return out


rec = {'status': {}, 'finding': {}, 'best': {}, 'views': {}, 'first': {}, 'detections': [], 'telemetry': [],
       'decisions': [], 'banners': [], 'stills': [], 'yolo_calls': 0, 'yolo_fail': 0,
       'heat': {}, 'dose_at': {}, 'reading': None, 'crops': {}, 'dose_trail': []}
mission = {'eye_view': (_np2.array([0.0, 0, 1]), _np2.array([1.0, 0, 1])), 'stop_i': 0, 'phase': 'walk', 'looks': [], 'look': None, 'second': [], 'goal': None, 'settled': None,
           'last_yolo': -1e9, 'shown': None, 'pitch': 0.0}


def log(t, code, text, kind, still=False, plain=None):
    rec['decisions'].append({'t': round(t, 2), 'drum': code, 'kind': kind, 'text': plain or text, 'detail': text,
                             'source': 'CANIS rules'})
    rec['banners'].append((t, text, kind))
    if still:
        rec['still_due'] = (t + .4, kind, code)


def judge(views, first, tier):
    """views: per view {class: conf} for the target barrel's box (normal / corrosion / bulge, conf >= 0.25).
    Side look (3 views): fault (>= 0.50) in >= 2 views -> DEFECT; normal in >= 2 and no fault -> OK; else closer look.
    Top tier (not in the detector's training range) always gets the closer look before a verdict.
    Closer look (all 8 views): fault in >= 4, or >= 3 and more than normal -> DEFECT; normal in >= 5 and fault <= 1 -> OK;
    nothing detected at all -> couldn't inspect; else SUSPECT. An empty detector response never gives OK."""
    fv = [v for v in views if faults_of(v)]
    nv = [v for v in views if not faults_of(v) and v.get('normal', 0) >= FLAG]
    best = max((c for v in fv for k, c in v.items() if k != 'normal'), default=0.0)
    counts = {}
    for v in fv:
        for f in faults_of(v):
            counts[f] = counts.get(f, 0) + 1
    finding = '+'.join(sorted(f for f, n in counts.items() if n >= 2)) or '+'.join(sorted(counts)) or 'none'
    if first:
        if tier == 3:
            return None, finding, best
        if len(fv) >= 2:
            return 'Confirmed defect', finding, best
        if len(nv) >= 2 and not fv:
            return 'OK', 'none', max((v['normal'] for v in nv), default=0.0)
        return None, finding, best
    if len(fv) >= 4 or (len(fv) >= 3 and len(fv) > len(nv)):
        return 'Confirmed defect', finding, best
    if len(nv) >= 5 and len(fv) <= 1:
        return 'OK', 'none', max((v['normal'] for v in nv), default=0.0)
    if not any(views):
        return "Couldn't inspect", 'none', 0.0
    return 'Suspect', finding if fv else 'unclear', best


def summ(views):
    n = len(views)
    fv = sum(1 for v in views if faults_of(v))
    nv = sum(1 for v in views if not faults_of(v) and v.get('normal', 0) >= FLAG)
    return f'fault {fv}/{n}, normal {nv}/{n}'


def decide(t, look):
    i = look['drum']
    code, tier = CODE[i], BY_ID[i]['location']['tier']
    if look['pass'] == 'side':
        views = look['views']
        status, finding, best = judge(views, True, tier)
        if status is None:
            rec['first'][i] = views
            mission['second'].append(i)
            log(t, code, f'{code} {"top tier" if tier == 3 else "unclear"} ({summ(views)}) -> closer look', 'suspect',
                plain=('Top-tier drum: moved for a closer second look before deciding.' if tier == 3 else
                       'First look was unclear. Moved for a closer second look.'))
            return
    else:
        views = rec['first'].get(i, []) + look['views']
        status, finding, best = judge(views, False, tier)
    rec['status'][i], rec['finding'][i], rec['best'][i], rec['views'][i] = status, finding, best, views
    n, k = len(views), sum(1 for v in views if faults_of(v))
    seen = {'corrosion': 'rust', 'bulge': 'bulging', 'bulge+corrosion': 'rust and bulging'}.get(finding, finding)
    if status == 'Confirmed defect':
        log(t, code, f'{code} {finding.upper()} -> DEFECT ({best:.2f}, {k}/{n} views)', 'confirmed', True,
            plain=f'{seen.capitalize()} seen in {k} of {n} camera views. Recorded as damage.')
    elif status == 'OK':
        log(t, code, f'{code} normal ({summ(views)}) -> OK', 'cleared',
            plain=f'No damage seen in {n} camera views.')
    elif status == 'Suspect':
        log(t, code, f'{code} mixed ({summ(views)}) -> SUSPECT (orange)', 'suspect', True,
            plain=f'Mixed result ({k} of {n} views showed possible damage). Flagged for a person to check.')
    else:
        log(t, code, f"{code} no clear view -> couldn't inspect", 'blocked', True,
            plain='The robot could not get a clear view.')


def command_to(p, yaw, goal_xy, goal_yaw, tol=0.10):
    """Walk the aisle centre line to the stop, then turn in place to the view yaw (as scripts/hot/dense_walk.py)."""
    dx, dy = goal_xy[0] - p[0], goal_xy[1] - p[1]
    if _math.hypot(dx, dy) > tol:
        heading = _math.atan2(dy, dx)
        error = _math.remainder(heading - yaw, 2 * _math.pi)
        if abs(error) > 0.5:
            return _np2.array([0.0, 0.0, float(_np2.clip(1.4 * error, -0.7, 0.7))], _np2.float32), False
        c, s = _math.cos(yaw), _math.sin(yaw)
        vx, vy = c * dx + s * dy, -s * dx + c * dy
        speed = min(0.45, 0.7 * _math.hypot(dx, dy))
        norm = max(1e-6, _math.hypot(vx, vy))
        return _np2.array([speed * vx / norm, speed * vy / norm, float(_np2.clip(1.4 * error, -0.7, 0.7))], _np2.float32), False
    error = _math.remainder(goal_yaw - yaw, 2 * _math.pi)
    return _np2.array([0.0, 0.0, float(_np2.clip(1.4 * error, -0.7, 0.7))], _np2.float32), abs(error) < 0.05


def back_off(p, yaw, goal_xy):
    """Walk backwards to the goal while facing down the aisle (+x, towards the source)."""
    dx, dy = goal_xy[0] - p[0], goal_xy[1] - p[1]
    c, s = _math.cos(yaw), _math.sin(yaw)
    vx, vy = c * dx + s * dy, -s * dx + c * dy
    speed = min(0.35, 0.7 * _math.hypot(dx, dy))
    norm = max(1e-6, _math.hypot(vx, vy))
    turn = float(_np2.clip(1.4 * _math.remainder(-yaw, 2 * _math.pi), -0.7, 0.7))
    return _np2.array([speed * vx / norm, speed * vy / norm, turn], _np2.float32)


def dose_check(t, p):
    """Fixed dose rule, checked on every gamma sample ahead of the inspection logic. Above DOSE_STOP the round
    stops and the robot backs off to the last pose read below DOSE_CLEAR; the drums left are for radiation protection."""
    rate = rec['reading']['dose_rate_uSv_h']
    rec['dose_trail'].append((t, rate))
    if mission['phase'] in ('retreat', 'done'):
        return
    if rate < DOSE_CLEAR:
        mission['last_clear'] = (float(p[0]), float(p[1]))
    if rate > DOSE_AMBER and not mission.get('amber'):
        mission['amber'] = True
        log(t, None, f'gamma {rate:.1f} uSv/h > {DOSE_AMBER:g}: controlled zone, dose watch', 'suspect',
            plain=f'Dose rate passed the {DOSE_AMBER:g} uSv/h controlled-zone level. Inspection continues under dose watch.')
    if rate > DOSE_STOP:
        to = mission.get('last_clear') or (float(p[0]) - 2.0, AISLE_Y)
        mission['retreat'] = {'t': round(t, 2), 'from': [round(float(p[0]), 3), round(float(p[1]), 3)],
                              'to': [round(to[0], 3), round(to[1], 3)], 'trigger_uSv_h': round(rate, 2)}
        mission['look'], mission['hold'], mission['phase'] = None, None, 'retreat'
        log(t, None, f'GAMMA {rate:.0f} uSv/h > {DOSE_STOP:g} -> STOP AND RETREAT', 'radiation',
            plain=f'Dose rate {rate:.0f} uSv/h, above the {DOSE_STOP:g} uSv/h hot-spot limit. Inspection stopped; '
                  f'backing off to the last point read below {DOSE_CLEAR:g} uSv/h.')


# ------------------------------------------------------------------ HUD
def minimap(draw, box, p):
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=(16, 20, 26), outline=YEL, width=2)
    draw.text((x0 + 12, y0 + 8), 'AISLE A - 2 sides x 3 tiers', font=F[18], fill=YEL)
    n = len(XS)
    cw, ch = (x1 - x0 - 100) / n, 30
    gap = 20
    rows = {'L': y0 + 40, 'R': y1 - 36 - 3 * ch}
    def cx_of(x):
        k = SLOT[x]
        ilw = any(d['category'] == 'ILW' and round(d['x'], 2) == x for d in SECTION)
        return x0 + 70 + k * cw + (gap if ilw else 0)
    for cat, label in (('LLW', 'LLW (yellow)'), ('ILW', 'ILW (blue)')):
        xs = [round(d['x'], 2) for d in SECTION if d['category'] == cat]
        if xs:
            draw.text((cx_of(min(xs)) + 4, y0 + 44 + 3 * ch + 6), label, font=F[14], fill=(200, 200, 200) if cat == 'LLW' else (150, 190, 220))
    for side, ry in rows.items():
        draw.text((x0 + 10, ry + ch - 8), 'LEFT' if side == 'L' else 'RIGHT', font=F[16], fill=WHITE)
        for d in SECTION:
            if d['location']['side'] != side:
                continue
            tier = d['location']['tier']
            ty = ry + (3 - tier) * ch if side == 'L' else ry + (tier - 1) * ch
            cx = cx_of(round(d['x'], 2))
            s_ = rec['status'].get(d['id']) or ('Checking' if mission['look'] and mission['look']['drum'] == d['id'] else None)
            col = RGB.get(s_, GREY)
            idle = (40, 46, 54) if d['category'] == 'LLW' else (30, 44, 60)
            draw.rectangle((cx + 3, ty + 3, cx + cw - 3, ty + ch - 3), fill=col if s_ else idle, outline=col if s_ else (70, 80, 92), width=2)
            draw.text((cx + 6, ty + 7), d['display_id'][4:], font=F[14], fill=BLK if s_ else (160, 168, 178))
    ay = rows['R'] - 12
    draw.line((x0 + 70, ay, x1 - 10, ay), fill=(80, 88, 98), width=2)
    # robot marker: interpolate between slot centres by world x
    xs = [x for x in XS]
    px = float(p[0])
    pts = [(x, cx_of(x) + cw / 2) for x in xs]
    if px <= pts[0][0]:
        rx = pts[0][1] - (pts[0][0] - px) * cw / 1.2
    elif px >= pts[-1][0]:
        rx = pts[-1][1] + (px - pts[-1][0]) * cw / 1.2
    else:
        for (xa, ua), (xb, ub) in zip(pts, pts[1:]):
            if xa <= px <= xb:
                rx = ua + (px - xa) / (xb - xa) * (ub - ua)
                break
    rx = max(x0 + 60, min(x1 - 14, rx))
    draw.ellipse((rx - 9, ay - 9, rx + 9, ay + 9), fill=YEL, outline=BLK)
    k = 0
    for name, st in (('OK', 'OK'), ('Suspect', 'Suspect'), ('Defect', 'Confirmed defect'), ('Checking', 'Checking')):
        draw.rectangle((x0 + 12 + 150 * k, y1 - 26, x0 + 26 + 150 * k, y1 - 12), fill=RGB[st])
        draw.text((x0 + 32 + 150 * k, y1 - 28), name, font=F[16], fill=WHITE)
        k += 1


def compose(t, p, chase_rgb, crop, boxes, tbox, therm=None, depth=None):
    canvas = Image.new('RGB', (1920, 1080), BLK)
    if chase_rgb is not None:
        canvas.paste(Image.fromarray(chase_rgb), (0, 60))
    dr = ImageDraw.Draw(canvas)
    dr.rectangle((0, 0, 1920, 58), fill=(14, 16, 20))
    canvas.paste(LOGO_D, (16, 29 - LOGO_D.height // 2), LOGO_D)
    canvas.paste(LOGO_W, (24 + LOGO_D.width, 29 - LOGO_W.height // 2), LOGO_W)
    xs_ = 40 + LOGO_D.width + LOGO_W.width
    dr.line((xs_, 12, xs_, 46), fill=(70, 74, 80), width=2)
    dr.text((xs_ + 18, 14), 'CANIS | warehouse-v3 aisle A patrol | RGB + LWIR + depth + gamma', font=F[24], fill=YEL)
    dr.text((1790, 12), f'{int(t) // 60:02d}:{int(t) % 60:02d}', font=FB[30], fill=YEL)
    # detector view
    view = crop.copy() if crop is not None else Image.new('RGB', (640, 640), (20, 20, 20))
    look = mission['look']
    focus = tbox or (project_box(BY_ID[look['drum']], *mission['eye_view']) if look else None)
    if focus:                                   # one drum at a time: everything else is dimmed
        fx0, fy0, fx1, fy1 = [int(round(v)) for v in focus]
        fx0, fy0 = max(0, fx0 - 8), max(0, fy0 - 8)
        fx1, fy1 = min(640, fx1 + 8), min(640, fy1 + 8)
        dim = Image.blend(view, Image.new('RGB', view.size, BLK), 0.65)
        if fx1 > fx0 and fy1 > fy0:
            dim.paste(view.crop((fx0, fy0, fx1, fy1)), (fx0, fy0))
        view = dim
    vd = ImageDraw.Draw(view)
    hold = mission.get('hold')
    verdict = rec['status'].get(look['drum']) if look else None
    frame_col = RGB.get(verdict, YEL) if hold and hold['final'] else ((255, 160, 40) if hold else WHITE)
    if focus:
        vd.rectangle(focus, outline=frame_col, width=5 if hold else 3)
    for b in sorted(boxes, key=lambda b: bool(b.get('target'))):   # background barrels first, target on top
        col = {'normal': (60, 220, 140), 'rust': (255, 70, 70), 'bulge': (255, 140, 0), 'rust_and_bulge': (255, 60, 200)}.get(b['cls'], (120, 200, 255))
        if b.get('target'):                     # the drum being inspected: bold box and label
            vd.rectangle(b['box'], outline=col, width=4)
            vd.text((b['box'][0] + 4, b['box'][1] + 2), f"{b['cls']} {b['conf']:.2f}", font=FB[16], fill=col)
        else:                                   # everything else the detector registers: faint, thin, small label
            soft = tuple(int(c * 0.45) for c in col)
            vd.rectangle(b['box'], outline=soft, width=1)
            vd.text((b['box'][0] + 3, b['box'][1] + 1), f"{b['cls']} {b['conf']:.2f}", font=F[12], fill=soft)
    if hold:
        code_ = CODE[look['drum']]
        word = {'OK': 'OK', 'Confirmed defect': 'DEFECT', 'Suspect': 'SUSPECT', "Couldn't inspect": "COULDN'T INSPECT"}.get(verdict, 'CLOSER LOOK')
        conf_ = rec['best'].get(look['drum'], 0.0)
        tag = f"{code_}  {word}" + (f"  {rec['finding'][look['drum']]} {conf_:.2f}" if verdict in ('Confirmed defect', 'Suspect') and conf_ else '')
        vd.rectangle((0, 586, 640, 640), fill=BLK)
        vd.text((14, 598), tag, font=FB[24], fill=frame_col)
    status_line, marks_line = 'walking to next column', ''
    if look:
        d = BY_ID[look['drum']]
        tilt = _math.degrees(mission['pitch'])
        status_line = (f"{CODE[look['drum']]} {d['category']} {'LEFT' if d['location']['side'] == 'L' else 'RIGHT'} "
                       f"{'close look' if look['pass'] == 'second' else 'side look'} tilt {tilt:+.0f}")
        marks_line = f"view {len(look['views'])}/{VIEWS if look['pass'] == 'side' else CLOSE_VIEWS}: " + ' '.join(vlabel(v) for v in look['views'])
    elif mission['phase'] == 'retreat':
        status_line = f'RETREAT: gamma above {DOSE_STOP:g} uSv/h'
    elif mission['phase'] == 'done':
        status_line = 'round stopped on dose' if mission.get('retreat') else 'round complete'
    shade = Image.new('RGBA', (640, 58 if marks_line else 34), (0, 0, 0, 150))
    view.paste(shade, (0, 0), shade)
    vd.text((10, 6), status_line, font=FB[18], fill=YEL)
    if marks_line:
        vd.text((10, 32), marks_line, font=F[16], fill=WHITE)
    canvas.paste(view.resize((620, 620)), (1290, 64))
    dr.rectangle((1290, 64, 1910, 684), outline=YEL, width=2)
    # LWIR and depth from the same camera mount
    look_id = look['drum'] if look else None
    for k, (title, img) in enumerate((('THERMAL (LWIR)', therm), ('DEPTH', depth))):
        x0 = 8 + k * 300
        dr.rectangle((x0, 788, x0 + 290, 1040), fill=(14, 18, 24), outline=(70, 80, 92), width=1)
        dr.text((x0 + 10, 792), title, font=FB[16], fill=YEL)
        if img is None:
            continue
        if k == 0:
            ok = img[_np2.isfinite(img)]
            want = (float(_np2.percentile(ok, 2)), float(_np2.percentile(ok, 99.5))) if ok.size else (18.0, 22.0)
            want = (want[0], max(want[1], want[0] + 1.5))            # auto range, at least 1.5 degC span
            old = mission.get('th_range') or want
            lo, hi = (old[0] + 0.15 * (want[0] - old[0]), old[1] + 0.15 * (want[1] - old[1]))
            mission['th_range'] = (lo, hi)
            canvas.paste(colourise(img, lo, hi, _INFERNO, 200), (x0 + 10, 816))
            for j in range(200):
                dr.line((x0 + 222, 1015 - j, x0 + 234, 1015 - j), fill=tuple(int(c) for c in colourise(
                    _np2.array([[lo + (hi - lo) * j / 199]]), lo, hi, _INFERNO, 1).getpixel((0, 0))))
            dr.text((x0 + 236, 808), f'{hi:.1f}', font=F[12], fill=WHITE)
            dr.text((x0 + 236, 1006), f'{lo:.1f}', font=F[12], fill=WHITE)
            heat = rec['heat'].get(look_id) if look_id else None
            air = rec['reading']['temperature_c'] if rec['reading'] else None
            if heat and air is not None:
                dr.text((x0 + 10, 1018), f'drum {_np2.median(heat):.1f}°C  air {air:.1f}°C', font=F[14], fill=WHITE)
        else:
            canvas.paste(colourise(img, 0.3, 8.0, _DEPTH, 200), (x0 + 10, 816))
            for j in range(200):
                dr.line((x0 + 222, 816 + j, x0 + 234, 816 + j), fill=tuple(int(c) for c in colourise(
                    _np2.array([[0.3 + 7.7 * j / 199]]), 0.3, 8.0, _DEPTH, 1).getpixel((0, 0))))
            dr.text((x0 + 238, 808), '0.3m', font=F[12], fill=WHITE)
            dr.text((x0 + 238, 1006), '8m+', font=F[12], fill=WHITE)
            centre_px = img[img.shape[0] // 2 - 4:img.shape[0] // 2 + 4, img.shape[1] // 2 - 4:img.shape[1] // 2 + 4]
            ok = centre_px[_np2.isfinite(centre_px)]
            if ok.size:
                dr.text((x0 + 10, 1018), f'range at centre {float(_np2.median(ok)):.2f} m', font=F[14], fill=WHITE)
    # counters and live readings
    seen = list(rec['status'].values())
    n = {k: seen.count(k) for k in ('OK', 'Suspect', 'Confirmed defect', "Couldn't inspect")}
    dr.rectangle((612, 788, 1280, 1040), fill=(14, 18, 24))
    dr.text((626, 794), f"INSPECTED {len(seen)}/{len(SECTION)}  OK {n['OK']}  SUSPECT {n['Suspect'] + n[chr(67) + 'ouldn' + chr(39) + 't inspect']}"
            f"  DEFECT {n['Confirmed defect']}", font=FB[22], fill=YEL)
    r_ = rec['reading']
    if r_:
        h2 = f"{r_['hydrogen_ppm']:.0f} ppm" if r_['hydrogen_ppm'] is not None else '<2 ppm'
        rate = r_['dose_rate_uSv_h']
        dr.text((626, 826), f"gamma {rate:.2f} uSv/h   dose {r_['mission_dose_mSv'] * 1000:.2f} uSv   "
                f"air {r_['temperature_c']:.1f}°C   H2 {h2}", font=F[16],
                fill=(255, 70, 70) if rate > DOSE_STOP else (255, 160, 40) if rate > DOSE_AMBER else (150, 210, 240))
    if any(rate > DOSE_AMBER for _, rate in rec['dose_trail']):
        dose_plot(dr, (16, 596, 456, 772), t)
    yy = 856
    for tt, text, kind in rec['banners'][-6:]:
        col = {'confirmed': (255, 70, 70), 'radiation': (255, 70, 70), 'suspect': (255, 160, 40),
               'cleared': (60, 220, 140)}.get(kind, WHITE)
        dr.text((626, yy), f'{int(tt) // 60:02d}:{int(tt) % 60:02d}  {text}'[:62], font=F[16], fill=col)
        yy += 30
    minimap(dr, (1290, 696, 1910, 1040), p)
    live = [b for b in rec['banners'] if t - b[0] < (5.0 if b[2] == 'radiation' else 2.5)
            and b[2] in ('confirmed', 'suspect', 'blocked', 'radiation')]
    if live:
        _, text, kind = live[-1]
        w = int(24 + 0.6 * 24 * len(text))
        dr.rectangle((640 - w // 2, 80, 640 + w // 2, 128), fill=BLK, outline=(255, 70, 70) if kind == 'radiation' else YEL, width=3)
        dr.text((640 - w // 2 + 12, 89), text, font=FB[24], fill=(255, 70, 70) if kind in ('confirmed', 'radiation') else (255, 160, 40))
    dr.rectangle((0, 1048, 1920, 1080), fill='#111822')
    dr.text((16, 1054), 'YOLO26s live on the 640x640 inspection camera. LWIR, gamma, air and H2 from the warehouse-v3 sensor backend. '
            f'Pan/tilt head simulated. Fixed rules decide; dose rule: stop above {DOSE_STOP:g} uSv/h.'
            + (' Hot source planted for this scenario.' if W_HOT else ''), font=F[14], fill='#9fb2c4')
    return canvas


def dose_plot(dr, box, t):
    """Gamma dose-rate history on a log axis, with the controlled-zone, retreat-target and stop levels."""
    x0, y0, x1, y1 = box
    dr.rectangle(box, fill=(14, 18, 24), outline=(70, 80, 92), width=1)
    dr.text((x0 + 10, y0 + 6), 'GAMMA DOSE RATE (uSv/h, log)', font=FB[16], fill=YEL)
    lo, hi = _math.log10(0.3), _math.log10(400.0)
    px0, py0, px1, py1 = x0 + 46, y0 + 30, x1 - 10, y1 - 10
    span = max(30.0, t)
    def xy(tt, r):
        v = (_math.log10(max(r, 0.3)) - lo) / (hi - lo)
        return px0 + (px1 - px0) * tt / span, py1 - (py1 - py0) * min(1.0, v)
    for level, col in ((DOSE_AMBER, (255, 160, 40)), (DOSE_CLEAR, (150, 210, 240)), (DOSE_STOP, (255, 70, 70))):
        yl = xy(0, level)[1]
        dr.line((px0, yl, px1, yl), fill=col, width=1)
        dr.text((x0 + 6, yl - 8), f'{level:g}', font=F[12], fill=col)
    pts = [xy(tt, r) for tt, r in rec['dose_trail']]
    if len(pts) > 1:
        dr.line(pts, fill=WHITE, width=2)
    rt = mission.get('retreat')
    if rt:
        xr = xy(rt['t'], 1)[0]
        dr.line((xr, py0, xr, py1), fill=(255, 70, 70), width=1)
        dr.text((xr + 4, py1 - 18), 'retreat', font=F[12], fill=(255, 70, 70))


# ------------------------------------------------------------------ main loop
zero = _np2.zeros(3, dtype=_np2.float32)
spot.restart_from_default_state(zero)
world.step(render=False)
dt = spot.physics_dt
stride = max(1, round(1 / (FPS * dt)))
set_tilt(0.0)
boxes, tbox, crop_img, trail = [], None, None, []
depth_img, therm_img, per_drum = None, None, {}
rec['air_at'] = {}
index, t = 0, 0.0
done_at = None
rec['banners'].append((0.0, f'Route: aisle A, {len(PLAN)} stops (LLW then ILW), left then right, tiers 1-2-3', 'info'))
FRAME_DT = stride * dt
ACC_V, ACC_W = 0.8, 1.6                     # m/s^2 and rad/s^2 command slew limits (smooth gait changes)
TAU_HEAD, TAU_CHASE = 0.30, 0.8             # s; eased camera head and chase view
cmd_s = _np2.zeros(3, dtype=_np2.float32)
head_s, chase_s = None, None
while t < W_MAX_S:
    t = index * stride * dt
    p, yaw = pose()
    p = _np2.asarray(p, float)
    trail.append((float(p[0]), float(p[1])))
    command = zero
    ph = mission['phase']
    if ph == 'walk':
        if mission['stop_i'] >= len(PLAN):
            mission['phase'] = 'done'
        else:
            stop = PLAN[mission['stop_i']]
            goal = tuple(stop['stop_xy'])
            command, _ = command_to(p, yaw, goal, 0.0, tol=0.15)
            mv = mission.setdefault('moved', [t, float(p[0]), float(p[1])])
            if _math.dist(p[:2], mv[1:]) > 0.10:
                mission['moved'] = [t, float(p[0]), float(p[1])]
            stalled = t - mission['moved'][0] > 4.0 and _math.dist(p[:2], goal) < 0.4
            if _math.dist(p[:2], goal) <= 0.18 or stalled:
                mission['looks'] = stop_looks(stop)
                mission['second'] = []
                mission['goal'] = goal
                mission['phase'] = 'next_look'
    if mission['phase'] == 'next_look':
        mission['hold'] = None
        if mission['looks']:
            lk = mission['looks'].pop(0)
            mission['goal'] = lk.get('goal', mission['goal'])
            mission['look'] = {**lk, 'views': [], 't0': None}
            mission['settled'] = None
            mission['phase'] = 'look'
        elif mission['second']:
            stop = PLAN[mission['stop_i']]
            for i in sorted(mission['second'], key=lambda i: (BY_ID[i]['location']['tier'] == 3, BY_ID[i]['x'])):
                g = second_spot(stop, BY_ID[i])
                yw, pt = aim_at(g, BY_ID[i])
                mission['looks'].append({'drum': i, 'yaw': yw, 'pitch': pt, 'pass': 'second', 'goal': g})
            mission['second'] = []
            lk = mission['looks'].pop(0)
            mission['goal'] = lk['goal']
            mission['look'] = {**lk, 'views': [], 't0': None}
            mission['settled'] = None
            mission['phase'] = 'look'
        else:
            mission['look'] = None
            mission['stop_i'] += 1
            mission['phase'] = 'walk'
            set_tilt(0.0); mission['pitch'] = 0.0
    if mission['phase'] == 'look':
        look = mission['look']
        look.setdefault('t_start', t)
        command, aligned = command_to(p, yaw, mission['goal'], look['yaw'], tol=0.30)
        err = abs(_math.remainder(look['yaw'] - yaw, 2 * _math.pi))
        aligned = aligned or err < 0.08 or (err < 0.15 and t - look['t_start'] > 2.5)
        if (aligned or mission['settled'] is not None) and err < 0.18:
            mission['settled'] = t if mission['settled'] is None else mission['settled']
            look['t0'] = look['t0'] if look['t0'] is not None else t
            if t - mission['settled'] > SETTLE_S and t - mission['last_yolo'] >= YOLO_EVERY_S and mission.get('head_err', 0) < 0.04:
                mission['last_yolo'] = t
                rgb = grab(eye_cam)
                d = BY_ID[look['drum']]
                ev = mission['eye_view']
                tb = project_box(d, *ev) or [-1000.0, -1000.0, -999.0, -999.0]
                others = all_boxes(*ev)
                try:
                    crop_img, result = yolo(rgb)
                    rec['yolo_calls'] += 1
                except Exception as error:
                    rec['yolo_fail'] += 1
                    result = {'detections': []}
                    rec['banners'].append((t, f'YOLO error {str(error)[:50]}', 'info'))
                boxes, conf, has_drum = [], {}, False
                tbc = clip(tb)
                for det in result.get('condition_detections', []):
                    b, cname, c = det['bbox_xyxy'], det['class_name'], det['confidence']
                    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                    # each box is one whole barrel: it belongs to the drum whose projected outline it overlaps most
                    owners = [(iou(b, clip(bb)), j) for j, bb in others.items() if bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]]
                    owner = max(owners)[1] if owners else None
                    on_target = owner == look['drum'] and iou(b, tbc) >= 0.3
                    if on_target and c >= WEAK:
                        has_drum = True
                        for k in COND.get(cname, ()):
                            conf[k] = max(conf.get(k, 0), c)
                    boxes.append({'box': b, 'cls': cname, 'conf': c, 'target': on_target})
                tbox = tb
                in_view = tb[0] > -40 and tb[1] > -40 and tb[2] < 680 and tb[3] < 680
                if has_drum or in_view:
                    look['views'].append(conf)
                rec['detections'].append({'t': round(t, 2), 'drum': CODE[look['drum']], 'pass': look['pass'],
                                          'boxes': [[b['cls'], round(b['conf'], 3), b['target'], [round(v, 1) for v in b['box']]] for b in boxes],
                                          'faults': faults_of(conf), 'conf': {k: round(v, 3) for k, v in conf.items()},
                                          'drum_box_matched': has_drum, 'target_box': [round(v, 1) for v in tb],
                                          'tilt_deg': round(_math.degrees(mission['pitch']), 1),
                                          'model_run': result.get('run_id'), 'model_sha': result.get('best_sha256')})
            need = VIEWS if look['pass'] == 'side' else CLOSE_VIEWS
            if len(look['views']) >= need or (look['t0'] is not None and t - look['t0'] > LOOK_TIMEOUT_S + (2.5 if look['pass'] == 'second' else 0)):
                decide(t, look)
                final = look['drum'] in rec['status']
                mission['hold'] = {'until': t + (2.0 if final else 1.0), 'final': final}
                mission['phase'] = 'hold'
        elif look['t0'] is None and mission['settled'] is None:
            if t - look['t_start'] > 8.0:              # could not turn into the view
                decide(t, look)
                mission['look'] = None
                mission['phase'] = 'next_look'
    if mission['phase'] == 'hold':
        # stay on the drum and show the verdict, then release it and move on
        command, _ = command_to(p, yaw, mission['goal'], mission['look']['yaw'], tol=0.30)
        if t >= mission['hold']['until']:
            mission['look'], boxes, tbox, mission['hold'] = None, [], None, None
            mission['phase'] = 'next_look'
    if mission['phase'] == 'retreat':
        rt = mission['retreat']
        boxes, tbox = [], None
        command = back_off(p, yaw, rt['to'])
        if 'reached_t' not in rt and _math.dist(p[:2], rt['to']) <= 0.15:
            rt['reached_t'] = round(t, 2)
            left = [lk['drum'] for s in PLAN for side in s['sides'] for lk in side['looks'] if lk['drum'] not in rec['status']]
            for i in left:
                rec['status'][i], rec['finding'][i], rec['best'][i] = "Couldn't inspect", 'dose limit', 0.0
            rate = rec['reading']['dose_rate_uSv_h']
            log(t, None, f'Retreat done, gamma {rate:.0f} uSv/h; {len(left)} drums left for RP', 'blocked',
                plain=f'Backed off to x = {p[0]:.1f} m (gamma {rate:.0f} uSv/h). Round stopped; {len(left)} drums not '
                      'inspected and handed to radiation protection.')
        if 'reached_t' in rt and t - rt['reached_t'] > 3.0:
            mission['phase'] = 'done'
    if mission['phase'] == 'done':
        done_at = done_at if done_at is not None else t
        if t - done_at > 2.0:
            break
    # chase view: behind and above the robot, looking down the aisle (presentation only)
    e = eye_pos(p, yaw)
    lk_now = mission['look']
    tgt = _np2.array(centre(BY_ID[lk_now['drum']])) if lk_now else e + 3.0 * _np2.array([_math.cos(yaw), _math.sin(yaw), -0.12])
    # eased head: the aim direction moves smoothly towards the target instead of snapping
    want = (tgt - e) / _np2.linalg.norm(tgt - e)
    a = 1 - _math.exp(-FRAME_DT / TAU_HEAD)
    head_s = want if head_s is None else head_s + a * (want - head_s)
    head_s = head_s / _np2.linalg.norm(head_s)
    mission['head_err'] = float(_np2.linalg.norm(want - head_s))
    tgt = e + head_s * _np2.linalg.norm(tgt - e)
    aim(eye_cam, e, tgt)            # simulated pan/tilt head on the inspection camera mount
    mission['eye_view'] = (e, tgt)
    if lk_now:
        lk_now['pitch'] = _math.atan2(tgt[2] - e[2], _math.hypot(tgt[0] - e[0], tgt[1] - e[1]))
        mission['pitch'] = lk_now['pitch']
    else:
        mission['pitch'] = 0.0
    ce = _np2.array([*CHASE_EYE(p)[:2], 2.6 if p[0] < 12 else 3.2]); cl = _np2.array([p[0] + 1.2, AISLE_Y, 0.6 if p[0] < 12 else 1.0])
    b = 1 - _math.exp(-FRAME_DT / TAU_CHASE)
    chase_s = _np2.concatenate([ce, cl]) if chase_s is None else chase_s + b * (_np2.concatenate([ce, cl]) - chase_s)
    aim(chase, chase_s[:3], chase_s[3:])
    world.render()
    live = grab(eye_cam)
    live_crop = Image.fromarray(live) if live is not None else crop_img
    if index % 2 == 0 or depth_img is None:
        depth_img = grab_depth()
        if depth_img is not None:
            therm_img, per_drum = thermal_view(depth_img, *mission['eye_view'])
    if index % 12 == 0:
        rec['reading'] = sensors.sample(p, t, gamma_xyz=p + [0, 0, GAMMA_Z], gas_xyz=p + [0, 0, 0.2])
        dose_check(t, p)
    lk_now = mission['look']
    if lk_now and mission['settled'] is not None and index % 2 == 0 and rec['reading']:
        if lk_now['drum'] in per_drum:
            rec['heat'].setdefault(lk_now['drum'], []).append(per_drum[lk_now['drum']])
            rec['air_at'].setdefault(lk_now['drum'], []).append(rec['reading']['temperature_c'])
        rec['dose_at'].setdefault(lk_now['drum'], []).append(rec['reading']['dose_rate_uSv_h'])
    frame = compose(t, p, grab(chase), crop_img if (mission.get('hold') and crop_img is not None) else live_crop, boxes, tbox,
                    therm_img, depth_img)
    frame.save(frames_dir / f'{index:05d}.jpg', quality=88)
    due = rec.get('still_due')
    if due and t >= due[0]:
        path = run_dir / 'stills' / f"{len(rec['stills']):02d}_{due[1]}_{due[2]}_{t:05.1f}s.jpg"
        frame.crop((1290, 64, 1910, 684)).save(path, quality=92)      # the inspection camera panel, drum outlined
        rec['stills'].append({'t': round(t, 2), 'kind': due[1], 'drum': due[2], 'file': f'stills/{path.name}'})
        rec.pop('still_due')
    r_ = rec['reading'] or {}
    tel = {'t': round(t, 2), 'pose': [round(float(p[0]), 3), round(float(p[1]), 3), round(float(yaw), 3)],
           'truth': [round(float(p[0]), 3), round(float(p[1]), 3)], 'aisle_y': AISLE_Y,
           'phase': mission['phase'], 'tilt_deg': round(_math.degrees(mission['pitch']), 1),
           'look': CODE[mission['look']['drum']] if mission['look'] else None}
    if index % 12 == 0 and r_:
        tel.update(dose_rate_uSv_h=round(r_['dose_rate_uSv_h'], 4), dose_uSv=round(r_['mission_dose_mSv'] * 1000, 5),
                   temperature_c=round(r_['temperature_c'], 2), relative_humidity_pct=round(r_['relative_humidity_pct'], 1),
                   hydrogen_status=r_['hydrogen_status'])
        if r_['hydrogen_ppm'] is not None:
            tel['hydrogen_ppm'] = round(r_['hydrogen_ppm'], 2)
        rec['telemetry'].append(tel)          # one record per sensor sample (2 Hz)
    if index % (FPS * 10) == 0:
        print(f"[hot] 1 t {t:.0f}s stop {mission['stop_i']}/{len(PLAN)} decided {len(rec['status'])} yolo {rec['yolo_calls']}", flush=True)
    target_cmd = _np2.asarray(command, _np2.float32)
    lim = _np2.array([ACC_V, ACC_V, ACC_W], _np2.float32) * FRAME_DT
    cmd_s = (cmd_s + _np2.clip(target_cmd - cmd_s, -lim, lim)).astype(_np2.float32)
    for _ in range(stride):
        spot.step(dt, cmd_s)
        world.step(render=False)
    index += 1
set_tilt(0.0)

# ------------------------------------------------------------------ save
planned = {lk['drum'] for s in PLAN for side in s['sides'] for lk in side['looks']}
memory = []
for d in SECTION:
    if d['id'] not in planned:
        continue
    s = rec['status'].get(d['id']) or "Couldn't inspect"
    views = rec['views'].get(d['id'], [])
    heat, air = rec['heat'].get(d['id']), rec['air_at'].get(d['id'])
    dose_at = rec['dose_at'].get(d['id'])
    memory.append({'drum_id': d['display_id'], 'internal_id': d['id'], 'category': d['category'], 'row': d['row'],
                   'side': d['location']['side'], 'column': d['location']['column'], 'tier': d['location']['tier'],
                   'x': d['x'], 'y': d['y'], 'z': d['base_z'], 'status': s,
                   'finding': rec['finding'].get(d['id'], 'none') if s != 'OK' else 'none',
                   'confidence': round(rec['best'].get(d['id'], 0.0), 3), 'views': len(views),
                   'fault_views': sum(1 for v in views if faults_of(v)), 'view_detail': views,
                   'surface_c': round(float(_np2.median(heat)), 2) if heat else None,
                   'heat_rise_c': round(float(_np2.median(heat) - _np2.median(air)), 2) if heat and air else None,
                   'dose_rate_at_drum_uSv_h': round(float(_np2.median(dose_at)), 3) if dose_at else None,
                   'label_readable': 'not attempted'})
reading = rec['reading'] or {}
(run_dir / 'memory.json').write_text(_json.dumps({'drums': memory, 'expected_drums': len(SECTION), 'duration_s': t,
    'started_utc': _START, 'yolo_calls': rec['yolo_calls'], 'yolo_failures': rec['yolo_fail'], 'stills': rec['stills'],
    'dose_uSv': round(reading.get('mission_dose_mSv', 0) * 1000, 4), 'budget_uSv': BUDGET_USV,
    'radiation_retreat': mission.get('retreat'), 'planted_source': W_HOT,
    'detector_run_id': 'YOLO26s whole-barrel conditions (expanded, 8 Nov 2026)', 'cosmos_model': 'not used in this round',
    'sensors': 'warehouse-v3 backend: gamma (Poisson counts), air T/RH, H2 inlet, LWIR from depth + map', 'seed': _SEED},
    indent=2, default=float))
(run_dir / 'decisions.jsonl').write_text(''.join(_json.dumps(x) + '\n' for x in rec['decisions']))
(run_dir / 'detections.jsonl').write_text(''.join(_json.dumps(x) + '\n' for x in rec['detections']))
(run_dir / 'telemetry.jsonl').write_text(''.join(_json.dumps(x) + '\n' for x in rec['telemetry']))
(run_dir / 'route.json').write_text(_json.dumps({'trail': [list(q) for q in trail[::6]]}))
# Self-check only: the simulator's seeded faults, never read by the rules above.
truth = {}
for m in memory:
    plan = PHYS[m['internal_id']]['visual_plan']
    truth[m['drum_id']] = {'faults': [k for k, v in (('corrosion', plan['corrosion_severity']),
                                                       ('bulge', plan['bulging_severity'])) if v > 0],
                           'severity': plan, 'hotspot_delta_c': PHYS[m['internal_id']]['thermal']['hotspot_delta_c']}
(run_dir / 'ground_truth.json').write_text(_json.dumps({'seed': _SEED, 'drums': truth}, indent=2))
_json.dump([{'id': d['display_id'], 'x': d['x'], 'y': d['y'], 'row': d['row']} for d in inventory
            if abs(d['y'] - AISLE_Y) < 3.0 and d['x'] < max(XS) + 1.5], open(run_dir / 'drums.json', 'w'))
counts = {k: sum(m['status'] == k for m in memory) for k in ('OK', 'Suspect', 'Confirmed defect', "Couldn't inspect")}
import glob as _glob
import shutil as _shutil
import subprocess as _sp
_ff = (_glob.glob('/usr/local/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*') or [_shutil.which('ffmpeg')])[0]
if _ff:
    _sp.run([_ff, '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', str(frames_dir / '%05d.jpg'),
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-movflags', '+faststart',
             str(run_dir.with_suffix('.mp4'))], check=True)
    for _pth in frames_dir.glob('*.jpg'):
        _pth.unlink()
    frames_dir.rmdir()
else:                                   # fall back to the worker encoder (12 fps): keep every other frame
    for k, _pth in enumerate(sorted(frames_dir.glob('*.jpg'))):
        if k % 2:
            _pth.unlink()
    for k, _pth in enumerate(sorted(frames_dir.glob('*.jpg'))):
        _pth.rename(frames_dir / f'{k:05d}.jpg')
print(f"[hot] CANIS dense walk {W_NAME}: {counts} in {t:.0f}s, yolo {rec['yolo_calls']} calls", flush=True)
