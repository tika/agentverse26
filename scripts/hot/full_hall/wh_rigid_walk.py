# CANIS side-look walk in Levi's warehouse-v3, aisle A (y = 4.83): one LLW section (yellow, first 2 pallets)
# then, further down the same aisle, one ILW section (blue, 1.2 m drums). Both sides, 3 tiers. One straight pass.
# Detector: retrained YOLO26s whole-barrel conditions (normal / rust / bulge / rust_and_bulge), 8 Nov 2026.
# RIGID CAMERA: the inspection camera is fixed to Spot's body. It aims only by the body turning (policy yaw) and
# leaning on its legs (joint-target posture from team sim/body_observation.py, max 0.12 rad). No pan/tilt head.
# Environment and seeded faults used as built (HOT_WAREHOUSE_SEED=42). Existing YOLO26s.
import io as _io
import json as _json
import math as _math
import os as _os
import time as _wtime
import urllib.request as _url
from pathlib import Path as _Path
from PIL import Image, ImageDraw, ImageFont

W_NAME = globals().get('W_NAME', 'canis_wh_cond')
W_MAX_COLS = int(globals().get('W_MAX_COLS', 99))
W_LLW_XMAX = float(globals().get('W_LLW_XMAX', 5.0))
W_ILW_XMAX = float(globals().get('W_ILW_XMAX', 16.6))
W_MAX_S = float(globals().get('W_MAX_S', 400.0))
W_MOUNT_PITCH = float(globals().get('W_MOUNT_PITCH', 0.0))   # rad, fixed upward mount angle (0 = level, like the team camera)
LEAN_MAX = 0.10
LEAN_SIGN = [1.0]        # flipped once if a lean moves the camera the wrong way (checked on the first lean)
STILL_S = 1.0           # stand still this long (policy, zero command) before leaning
TURN_MAX = 0.32          # rad/s; the body (and so the camera) turns at a walking-dog pace
FPS = int(globals().get('W_FPS', 24))     # previews render 12 fps; the encoder blends up to 24
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
if globals().get('W_DEMO_TAIL'):              # demo: after the last stop, walk on to the next column and finish
    _nxt = _plan()[(W_STOPS or [0])[-1] + 1]
    PLAN.append({**_nxt, 'sides': []})

# ------------------------------------------------------------------ chase camera (presentation only)
from isaacsim.sensors.camera import Camera as _Camera
if 'canis_chase_small' not in state:          # shown at 620x349, so render it small
    _chase = _Camera('/World/CanisChaseSmall', resolution=(640, 360))
    _chase.prim.GetAttribute('focalLength').Set(14.0)
    _chase.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05, 60.))
    _chase.initialize()
    state['canis_chase_small'] = _chase
chase = state['canis_chase_small']


def aim(camera, eye, target):
    m = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float, eye)), Gf.Vec3d(*map(float, target)), Gf.Vec3d(0, 0, 1))
    q = m.GetInverse().ExtractRotationQuat()
    camera.set_world_pose(position=_np2.array(eye, dtype=float), orientation=_np2.array([q.GetReal(), *q.GetImaginary()]),
                          camera_axes='usd')


def CHASE_EYE(p):
    """Behind and above the robot, inside the hall."""
    return (max(p[0] - 2.4, 0.6), AISLE_Y, 2.6)


if 'canis_eye' in state:                     # older square eye camera from earlier runs: stop rendering it
    try:
        state['canis_eye'].pause()
    except Exception:
        pass
if 'canis_eye_wide' not in state:
    _eye = _Camera('/World/CanisEyeWide', resolution=(1280, 720))
    _eye.prim.GetAttribute('horizontalAperture').Set(20.955)
    _eye.prim.GetAttribute('verticalAperture').Set(20.955 * 720 / 1280)
    _eye.prim.GetAttribute('focalLength').Set(20.955 / 2 / _math.tan(_math.radians(110.0) / 2))
    _eye.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05, 60.))
    _eye.initialize()
    state['canis_eye_wide'] = _eye
eye_cam = state['canis_eye_wide']
CROP_S = 1280 * _math.tan(_math.radians(77.3) / 2) / _math.tan(_math.radians(110.0) / 2)   # px, square YOLO crop
CROP_X0, CROP_Y0 = (1280 - CROP_S) / 2, (720 - CROP_S) / 2
CROP_K = CROP_S / 640


def to_wide(b):
    """Crop (640 px) coordinates -> wide camera coordinates."""
    return [CROP_X0 + b[0] * CROP_K, CROP_Y0 + b[1] * CROP_K, CROP_X0 + b[2] * CROP_K, CROP_Y0 + b[3] * CROP_K]


FX = 320 / _math.tan(_math.radians(77.3) / 2)
MOUNT_F, MOUNT_Z = 0.35, 0.45      # forward of / above the body origin (inspection camera mount)


def eye_pos(p, yaw):
    return _np2.array([p[0] + MOUNT_F * _math.cos(yaw), p[1] + MOUNT_F * _math.sin(yaw), p[2] + MOUNT_Z])


def basis(eye, target):
    target = _np2.asarray(target, float)
    if target.shape == (3, 3):                      # rigid camera: columns are forward, left, up
        return target[:, 0], -target[:, 1], target[:, 2]
    f = target - eye; f /= _np2.linalg.norm(f)
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



# ------------------------------------------------------------------ body posture (team sim/body_observation.py, unchanged maths)
def _rpy(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = _math.cos(roll), _math.sin(roll), _math.cos(pitch), _math.sin(pitch), _math.cos(yaw), _math.sin(yaw)
    return _np2.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                       [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                       [-sp, cp * sr, cp * cr]])


_HIPS = {'fl': (.29785, .055), 'fr': (.29785, -.055), 'hl': (-.29785, .055), 'hr': (-.29785, -.055)}


def _foot(q, leg):
    hx, hy, kn = q; side = 1 if leg[1] == 'l' else -1
    knee = _np2.array([.025, 0., -.3205])
    shank = _rpy(0, kn, 0) @ _np2.array([0., 0., -.35])
    thigh = _rpy(0, hy, 0) @ (knee + shank)
    return _np2.array([*_HIPS[leg], 0.]) + _rpy(hx, 0, 0) @ (_np2.array([0., side * .110945, 0.]) + thigh)


def _solve_foot(target, seed, leg):
    q = _np2.array(seed, dtype=float)
    for _ in range(70):
        pos = _foot(q, leg); e = _np2.asarray(target) - pos
        if _np2.linalg.norm(e) < 1e-5:
            return q
        jac = _np2.column_stack([(_foot(q + _np2.eye(3)[i] * 1e-5, leg) - pos) / 1e-5 for i in range(3)])
        q += _np2.clip(jac.T @ _np2.linalg.solve(jac @ jac.T + _np2.eye(3) * 1e-5, e), -.10, .10)
    if _np2.linalg.norm(_np2.asarray(target) - _foot(q, leg)) > .002:
        raise ValueError('Unreachable observation posture')
    return q


def posture_targets(names, positions, pitch_delta=0.):
    values = dict(zip(names, map(float, positions))); result = values.copy()
    if abs(pitch_delta) > .14:
        raise ValueError('Observation posture outside tested limits')
    rot = _rpy(0, pitch_delta, 0)
    for leg in _HIPS:
        keys = [leg + '_' + s for s in ('hx', 'hy', 'kn')]
        seed = _np2.array([values[k] for k in keys])
        solved = _solve_foot(rot.T @ _foot(seed, leg), seed, leg)
        if _np2.max(_np2.abs(solved - seed)) > .6:
            raise ValueError('Observation pose changes a joint too far')
        result.update(zip(keys, solved))
    return _np2.array([result[n] for n in names], dtype=_np2.float32)


class Lean:
    """Stand still and lean the body on its legs (joint position targets, physics). Never sets a pose directly."""
    RAMP = 2.0                                # s to lean back / stand up again, eased

    def __init__(self, robot, pitch_delta):
        art = robot.articulation
        self.robot, self.u, self.releasing, self.finished, self.pitch = robot, 0.0, False, False, pitch_delta
        self.start = art.get_dof_positions().numpy().reshape(-1).copy()
        self.target = posture_targets(list(art.dof_names), self.start, pitch_delta)
        lo, hi = art.get_dof_limits()
        if _np2.any(self.target < lo.numpy().reshape(-1)) or _np2.any(self.target > hi.numpy().reshape(-1)):
            raise ValueError('Observation joint target exceeds limits')

    @property
    def at_view(self):
        return self.u >= 1.0 and not self.releasing

    def step(self, dt):
        if self.finished:
            return
        self.u = max(0.0, self.u - dt / self.RAMP) if self.releasing else min(1.0, self.u + dt / self.RAMP)
        s = self.u * self.u * (3 - 2 * self.u)
        self.robot.articulation.set_dof_position_targets((self.start + (self.target - self.start) * s).reshape(1, -1))
        if self.releasing and self.u <= 0.0:
            self.finished = True
            self.robot.initialize()          # reset policy feedback at the current physical state; no teleport


def body_R():
    _, q = spot.articulation.get_world_poses()
    w, x, y, z = q.numpy().reshape(4)
    return _np2.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                       [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                       [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _quat(R):
    w = _math.sqrt(max(1e-12, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    return _np2.array([w, (R[2, 1] - R[1, 2]) / (4 * w), (R[0, 2] - R[2, 0]) / (4 * w), (R[1, 0] - R[0, 1]) / (4 * w)])


MOUNT_R = _rpy(0, -W_MOUNT_PITCH, 0)         # negative rotation about body y = camera nose up


def rigid_camera(p):
    R = body_R() @ MOUNT_R
    eye = _np2.asarray(p, float) + body_R() @ _np2.array([MOUNT_F, 0.0, MOUNT_Z])
    eye_cam.set_world_pose(position=eye, orientation=_quat(R), camera_axes='world')
    return eye, R


def needed_lean(eye, d):
    c = _np2.array(centre(d)) - eye
    want = _math.atan2(c[2], _math.hypot(c[0], c[1]))      # elevation the camera must point at
    up = float(_np2.clip(want - W_MOUNT_PITCH, -LEAN_MAX, LEAN_MAX))
    if abs(up) < 0.03:
        up = 0.0
    return -up * LEAN_SIGN[0], up                           # (posture pitch delta, intended camera change)


def lean_checked(t):
    L = mission['lean']
    if getattr(L, 'checked', True) or abs(getattr(L, 'intended', 0.0)) < 0.03:
        return True
    moved = mission['pitch'] - L.e0
    L.checked = True
    if moved * L.intended < 0 and abs(moved) > 0.02:
        LEAN_SIGN[0] *= -1.0
        rec['banners'].append((t, 'lean direction calibrated (flipped)', 'info'))
    rec.setdefault('lean_cal', []).append({'t': round(t, 2), 'intended': round(L.intended, 3), 'moved': round(moved, 3), 'sign': LEAN_SIGN[0]})
    return True


def set_tilt(pitch):
    mission['pitch'] = pitch


def grab(camera):
    rgba = camera.get_rgba()
    return None if rgba is None or not _np2.asarray(rgba).size else _np2.asarray(rgba)[:, :, :3].astype(_np2.uint8)


# ------------------------------------------------------------------ YOLO (training-equivalent 77.3 deg crop)
X0, Y0, SIDE = 0, 0, 640


def yolo(rgb):
    crop = Image.fromarray(rgb).crop((round(CROP_X0), round(CROP_Y0), round(CROP_X0 + CROP_S), round(CROP_Y0 + CROP_S))).resize((640, 640), Image.LANCZOS)
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
       'decisions': [], 'banners': [], 'stills': [], 'yolo_calls': 0, 'yolo_fail': 0}
mission = {'eye_view': (_np2.array([0.0, 0, 1]), _np2.array([1.0, 0, 1])), 'stop_i': 0, 'phase': 'walk', 'looks': [], 'look': None, 'second': [], 'goal': None, 'settled': None,
           'last_yolo': -1e9, 'shown': None, 'pitch': 0.0}


def log(t, code, text, kind, still=False):
    rec['decisions'].append({'t': round(t, 2), 'drum': code, 'kind': kind, 'text': text, 'source': 'CANIS rules'})
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
            log(t, code, f'{code} {"top tier" if tier == 3 else "unclear"} ({summ(views)}) -> closer look', 'suspect')
            return
    else:
        views = rec['first'].get(i, []) + look['views']
        status, finding, best = judge(views, False, tier)
    rec['status'][i], rec['finding'][i], rec['best'][i], rec['views'][i] = status, finding, best, views
    n, k = len(views), sum(1 for v in views if faults_of(v))
    if status == 'Confirmed defect':
        log(t, code, f'{code} {finding.upper()} -> DEFECT ({best:.2f}, {k}/{n} views)', 'confirmed', True)
    elif status == 'OK':
        log(t, code, f'{code} normal ({summ(views)}) -> OK', 'cleared')
    elif status == 'Suspect':
        log(t, code, f'{code} mixed ({summ(views)}) -> SUSPECT (orange)', 'suspect', True)
    else:
        log(t, code, f"{code} no clear view -> couldn't inspect", 'blocked', True)


def command_to(p, yaw, goal_xy, goal_yaw, tol=0.10):
    """Walk the aisle centre line to the stop, then turn in place to the view yaw (as scripts/hot/dense_walk.py)."""
    dx, dy = goal_xy[0] - p[0], goal_xy[1] - p[1]
    if _math.hypot(dx, dy) > tol:
        heading = _math.atan2(dy, dx)
        error = _math.remainder(heading - yaw, 2 * _math.pi)
        if abs(error) > 0.5:
            return _np2.array([0.0, 0.0, float(_np2.clip(1.2 * error, -TURN_MAX, TURN_MAX))], _np2.float32), False
        c, s = _math.cos(yaw), _math.sin(yaw)
        vx, vy = c * dx + s * dy, -s * dx + c * dy
        speed = min(0.32, 0.6 * _math.hypot(dx, dy))
        norm = max(1e-6, _math.hypot(vx, vy))
        return _np2.array([speed * vx / norm, speed * vy / norm, float(_np2.clip(1.2 * error, -TURN_MAX, TURN_MAX))], _np2.float32), False
    error = _math.remainder(goal_yaw - yaw, 2 * _math.pi)
    return _np2.array([0.0, 0.0, float(_np2.clip(1.2 * error, -TURN_MAX, TURN_MAX))], _np2.float32), abs(error) < 0.05


def walk_cmd(p, yaw, goal_xy, tol=0.15):
    """Between stops: face straight down the aisle (+x) and side-step onto the line; never turn towards the goal."""
    err = _math.remainder(0.0 - yaw, 2 * _math.pi)
    wz = float(_np2.clip(1.2 * err, -TURN_MAX, TURN_MAX))
    dx, dy = goal_xy[0] - p[0], goal_xy[1] - p[1]
    dist = _math.hypot(dx, dy)
    if abs(err) > 0.6 or dist <= tol:              # still turned to a side from the last look: square up first
        return _np2.array([0.0, 0.0, wz], _np2.float32), dist <= tol
    c, s_ = _math.cos(yaw), _math.sin(yaw)
    vx, vy = c * dx + s_ * dy, -s_ * dx + c * dy
    speed = min(0.32, 0.6 * dist)
    vx, vy = speed * vx / dist, speed * vy / dist
    vy = float(_np2.clip(vy, -0.2, 0.2))           # gentle side-step
    return _np2.array([vx, vy, wz], _np2.float32), False


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


def compose(t, p, chase_rgb, crop, boxes, tbox):
    canvas = Image.new('RGB', (1920, 1080), BLK)
    dr = ImageDraw.Draw(canvas)
    dr.rectangle((0, 0, 1920, 58), fill=(14, 16, 20))
    canvas.paste(LOGO_D, (16, 29 - LOGO_D.height // 2), LOGO_D)
    canvas.paste(LOGO_W, (24 + LOGO_D.width, 29 - LOGO_W.height // 2), LOGO_W)
    xs_ = 40 + LOGO_D.width + LOGO_W.width
    dr.line((xs_, 12, xs_, 46), fill=(70, 74, 80), width=2)
    dr.text((xs_ + 18, 14), 'CANIS | warehouse-v3, aisle A: LLW + ILW | YOLO26s side looks', font=F[24], fill=YEL)
    dr.text((1790, 12), f'{int(t) // 60:02d}:{int(t) % 60:02d}', font=FB[30], fill=YEL)
    # first-person view: the rigid body camera, full width (team layout)
    view = crop.copy() if crop is not None else Image.new('RGB', (1280, 720), (20, 20, 20))
    look = mission['look']
    focus = tbox or (project_box(BY_ID[look['drum']], *mission['eye_view']) if look else None)
    focus = to_wide(focus) if focus else None
    if focus:                                   # one drum at a time: everything else is dimmed
        fx0, fy0, fx1, fy1 = [int(round(v)) for v in focus]
        fx0, fy0 = max(0, fx0 - 10), max(0, fy0 - 10)
        fx1, fy1 = min(1280, fx1 + 10), min(720, fy1 + 10)
        dim = Image.blend(view, Image.new('RGB', view.size, BLK), 0.65)
        if fx1 > fx0 and fy1 > fy0:
            dim.paste(view.crop((fx0, fy0, fx1, fy1)), (fx0, fy0))
        view = dim
    vd = ImageDraw.Draw(view)
    vd.rectangle((CROP_X0, CROP_Y0, CROP_X0 + CROP_S, CROP_Y0 + CROP_S - 1), outline=(90, 96, 104), width=1)
    vd.text((CROP_X0 + 6, 720 - 24), 'YOLO 77 deg', font=F[14], fill=(120, 128, 138))
    hold = mission.get('hold')
    verdict = rec['status'].get(look['drum']) if look else None
    frame_col = RGB.get(verdict, YEL) if hold and hold['final'] else ((255, 160, 40) if hold else WHITE)
    if focus:
        vd.rectangle(focus, outline=frame_col, width=6 if hold else 3)
    for b in sorted(boxes, key=lambda b: bool(b.get('target'))):   # background barrels first, target on top
        col = {'normal': (60, 220, 140), 'rust': (255, 70, 70), 'bulge': (255, 140, 0), 'rust_and_bulge': (255, 60, 200)}.get(b['cls'], (120, 200, 255))
        bw = to_wide(b['box'])
        if b.get('target'):                     # the drum being inspected: bold box and label
            vd.rectangle(bw, outline=col, width=4)
            vd.text((bw[0] + 5, bw[1] + 3), f"{b['cls']} {b['conf']:.2f}", font=FB[20], fill=col)
        else:                                   # everything else the detector registers: faint, thin, small label
            soft = tuple(int(c * 0.45) for c in col)
            vd.rectangle(bw, outline=soft, width=1)
            vd.text((bw[0] + 3, bw[1] + 1), f"{b['cls']} {b['conf']:.2f}", font=F[14], fill=soft)
    if hold:
        code_ = CODE[look['drum']]
        word = {'OK': 'OK', 'Confirmed defect': 'DEFECT', 'Suspect': 'SUSPECT', "Couldn't inspect": "COULDN'T INSPECT"}.get(verdict, 'CLOSER LOOK')
        conf_ = rec['best'].get(look['drum'], 0.0)
        tag = f"{code_}  {word}" + (f"  {rec['finding'][look['drum']]} {conf_:.2f}" if verdict in ('Confirmed defect', 'Suspect') and conf_ else '')
        vd.rectangle((0, 656, 1280, 720), fill=BLK)
        vd.text((18, 668), tag, font=FB[30], fill=frame_col)
    status_line, marks_line = 'walking to next column', ''
    if look:
        d = BY_ID[look['drum']]
        tilt = _math.degrees(mission['pitch'])
        status_line = (f"{CODE[look['drum']]} {d['category']} {'LEFT' if d['location']['side'] == 'L' else 'RIGHT'} "
                       f"{'close look' if look['pass'] == 'second' else 'side look'}  cam {tilt:+.0f} deg")
        marks_line = f"view {len(look['views'])}/{VIEWS if look['pass'] == 'side' else CLOSE_VIEWS}: " + ' '.join(vlabel(v) for v in look['views'])
    elif mission['phase'] == 'done':
        status_line = 'round complete'
    shade = Image.new('RGBA', (1280, 70 if marks_line else 40), (0, 0, 0, 150))
    view.paste(shade, (0, 0), shade)
    vd.text((14, 7), status_line, font=FB[24], fill=YEL)
    if marks_line:
        vd.text((14, 40), marks_line, font=F[20], fill=WHITE)
    canvas.paste(view, (0, 60))
    dr.rectangle((0, 60, 1279, 779), outline=YEL, width=2)
    # third-person chase view, small
    if chase_rgb is not None:
        canvas.paste(Image.fromarray(chase_rgb).resize((620, 349), Image.LANCZOS), (1290, 64))
    dr.rectangle((1290, 64, 1910, 413), outline=(70, 74, 80), width=2)
    dr.text((1300, 70), 'THIRD PERSON', font=F[14], fill=(200, 200, 200))
    # body / camera sync panel
    by_, bl_ = mission.get('body', (0.0, 0.0))
    ln = mission.get('lean')
    dr.rectangle((1290, 780, 1910, 1040), fill=(14, 18, 24), outline=(70, 74, 80), width=2)
    dr.text((1306, 790), 'BODY -> CAMERA (rigid mount)', font=FB[18], fill=YEL)
    rows_ = [('body yaw', f'{_math.degrees(by_):+6.1f} deg'), ('body pitch (lean)', f'{_math.degrees(-bl_):+6.1f} deg'),
             ('camera elevation', f"{_math.degrees(mission['pitch']):+6.1f} deg"),
             ('legs', 'leaning back' if ln is not None and not getattr(ln, 'releasing', False) and getattr(ln, 'u', 0) > 0 else
                      ('standing up' if ln is not None else 'walking / turning')),
             ('phase', mission['phase'])]
    for k_, (a_, b_) in enumerate(rows_):
        dr.text((1306, 826 + 40 * k_), a_, font=F[20], fill=(170, 178, 188))
        dr.text((1600, 826 + 40 * k_), b_, font=FB[20], fill=WHITE)
    # counters
    seen = list(rec['status'].values())
    n = {k: seen.count(k) for k in ('OK', 'Suspect', 'Confirmed defect', "Couldn't inspect")}
    dr.rectangle((0, 780, 1280, 830), fill=BLK)
    dr.text((20, 792), f"INSPECTED {len(seen)}/{len(SECTION)}   OK {n['OK']}   SUSPECT {n['Suspect'] + n[chr(67) + 'ouldn' + chr(39) + 't inspect']}"
            f"   DEFECT {n['Confirmed defect']}", font=FB[26], fill=YEL)
    minimap(dr, (1290, 424, 1910, 768), p)
    # decision log
    dr.rectangle((0, 838, 1280, 1040), fill=(14, 18, 24))
    yy = 846
    for tt, text, kind in rec['banners'][-6:]:
        col = {'confirmed': (255, 70, 70), 'suspect': (255, 160, 40), 'cleared': (60, 220, 140)}.get(kind, WHITE)
        dr.text((20, yy), f'{int(tt) // 60:02d}:{int(tt) % 60:02d}  {text}', font=F[20], fill=col)
        yy += 32
    live = [b for b in rec['banners'] if t - b[0] < 2.5 and b[2] in ('confirmed', 'suspect', 'blocked')]
    if live:
        _, text, kind = live[-1]
        w = int(24 + 0.6 * 24 * len(text))
        dr.rectangle((640 - w // 2, 80, 640 + w // 2, 128), fill=BLK, outline=YEL, width=3)
        dr.text((640 - w // 2 + 12, 89), text, font=FB[24], fill=(255, 70, 70) if kind == 'confirmed' else (255, 160, 40))
    dr.rectangle((0, 1048, 1920, 1080), fill='#111822')
    dr.text((16, 1054), 'Detector: retrained YOLO26s whole-barrel conditions, live on the 77 deg centre of a 110 deg rigid body camera. Target drum from map + simulator pose. '
            'Camera fixed to body: aims by turning and leaning on legs. Warehouse and its seeded faults used as built. Rules decide; no Cosmos.', font=F[14], fill='#9fb2c4')
    return canvas


# ------------------------------------------------------------------ main loop
zero = _np2.zeros(3, dtype=_np2.float32)
spot.restart_from_default_state(zero)
world.step(render=False)
dt = spot.physics_dt
stride = max(1, round(1 / (FPS * dt)))
set_tilt(0.0)
boxes, tbox, crop_img, trail = [], None, None, []
index, t = 0, 0.0
done_at = None
rec['banners'].append((0.0, f'Route: aisle A, {len(PLAN)} stops (LLW then ILW), left then right, tiers 1-2-3', 'info'))
FRAME_DT = stride * dt
PERF = {'render': 0.0, 'compose_save': 0.0, 'yolo': 0.0, 'physics': 0.0}
_WALL0 = _wtime.perf_counter()
ACC_V, ACC_W = 0.4, 0.5                     # m/s^2 and rad/s^2 command slew limits (smooth gait changes)
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
            command, _ = walk_cmd(p, yaw, goal, tol=0.15)
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
        mission.pop('still_since', None)
        if mission['looks']:
            lk = mission['looks'].pop(0)
            mission['goal'] = lk.get('goal', mission['goal'])
            mission['look'] = {**lk, 'views': [], 't0': None}
            mission['settled'] = None
            mission.pop('still_since', None)
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
            command = zero                          # aligned: stop turning and stand still before leaning
            mission.setdefault('still_since', t)
            if mission.get('lean') is None and t - mission['still_since'] >= STILL_S:
                try:
                    _pd, _up = needed_lean(mission['eye_view'][0], BY_ID[look['drum']])
                    mission['lean'] = Lean(spot, _pd)
                    mission['lean'].intended, mission['lean'].e0, mission['lean'].checked = _up, mission['pitch'], False
                except Exception as error:
                    rec['banners'].append((t, f'lean failed: {str(error)[:40]}', 'info'))
                    mission['lean'] = Lean.__new__(Lean); mission['lean'].__dict__.update(u=1.0, releasing=False, finished=False, pitch=0.0, robot=None)
                    mission['lean'].step = lambda dt, L=mission['lean']: L.__dict__.update(finished=L.releasing)
                    mission['lean'].intended, mission['lean'].e0, mission['lean'].checked = 0.0, mission['pitch'], True
            if t - mission['settled'] > SETTLE_S and t - mission['last_yolo'] >= YOLO_EVERY_S and mission.get('lean') is not None and mission['lean'].at_view and lean_checked(t):
                mission['last_yolo'] = t
                rgb = grab(eye_cam)
                d = BY_ID[look['drum']]
                ev = mission['eye_view']
                tb = project_box(d, *ev) or [-1000.0, -1000.0, -999.0, -999.0]
                others = all_boxes(*ev)
                try:
                    _ty = _wtime.perf_counter()
                    _, result = yolo(rgb)
                    PERF['yolo'] += _wtime.perf_counter() - _ty
                    crop_img = Image.fromarray(rgb)
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
                                          'tilt_deg': round(_math.degrees(mission['pitch']), 1), 'lean_rad': round(getattr(mission.get('lean'), 'pitch', 0.0), 3),
                                          'model_run': result.get('run_id'), 'model_sha': result.get('best_sha256')})
            need = VIEWS if look['pass'] == 'side' else CLOSE_VIEWS
            if len(look['views']) >= need or (look['t0'] is not None and t - look['t0'] > LOOK_TIMEOUT_S + Lean.RAMP + STILL_S + (2.5 if look['pass'] == 'second' else 0)):
                decide(t, look)
                final = look['drum'] in rec['status']
                mission['hold'] = {'until': t + (2.0 if final else 1.0), 'final': final}
                mission['phase'] = 'hold'
        elif look['t0'] is None and mission['settled'] is None:
            if t - look['t_start'] > 8.0:              # could not turn into the view
                decide(t, look)
                mission['look'] = None
                mission['phase'] = 'unlean' if mission.get('lean') is not None else 'next_look'
                if mission.get('lean') is not None:
                    mission['lean'].releasing = True
    if mission['phase'] == 'hold':
        # stay on the drum and show the verdict, then release it and move on
        command, _ = command_to(p, yaw, mission['goal'], mission['look']['yaw'], tol=0.30)
        if t >= mission['hold']['until']:
            mission['look'], boxes, tbox, mission['hold'] = None, [], None, None
            if mission.get('lean') is not None:
                mission['lean'].releasing = True
                mission['phase'] = 'unlean'
            else:
                mission['phase'] = 'next_look'
    if mission['phase'] == 'unlean' and (mission.get('lean') is None or mission['lean'].finished):
        mission['lean'] = None
        cmd_s = _np2.zeros(3, dtype=_np2.float32)
        mission['stand_until'] = t + 1.0
        mission['phase'] = 'stand'
    if mission['phase'] == 'stand':
        command = zero
        if t >= mission['stand_until']:
            mission.pop('still_since', None)
            mission['phase'] = 'next_look'
    if mission['phase'] == 'done':
        done_at = done_at if done_at is not None else t
        if t - done_at > 2.0:
            break
    # chase view: behind and above the robot, looking down the aisle (presentation only)
    lk_now = mission['look']
    e, Rcam = rigid_camera(p)          # camera fixed to the body: no independent motion
    mission['eye_view'] = (e, Rcam)
    mission['pitch'] = _math.asin(max(-1.0, min(1.0, float(Rcam[2, 0]))))     # actual camera elevation
    _Rb = body_R(); mission['body'] = (_math.atan2(_Rb[1, 0], _Rb[0, 0]), -_math.asin(max(-1.0, min(1.0, float(_Rb[2, 0])))))
    ce = _np2.array([*CHASE_EYE(p)[:2], 2.6 if p[0] < 12 else 3.2]); cl = _np2.array([p[0] + 1.2, AISLE_Y, 0.6 if p[0] < 12 else 1.0])
    b = 1 - _math.exp(-FRAME_DT / TAU_CHASE)
    chase_s = _np2.concatenate([ce, cl]) if chase_s is None else chase_s + b * (_np2.concatenate([ce, cl]) - chase_s)
    aim(chase, chase_s[:3], chase_s[3:])
    _T0 = _wtime.perf_counter()
    world.render()
    live = grab(eye_cam)
    _T1 = _wtime.perf_counter()
    live_crop = Image.fromarray(live) if live is not None else crop_img
    frame = compose(t, p, grab(chase), crop_img if (mission.get('hold') and crop_img is not None) else live_crop, boxes, tbox)
    frame.save(frames_dir / f'{index:05d}.jpg', quality=88)
    _T2 = _wtime.perf_counter()
    PERF['render'] += _T1 - _T0; PERF['compose_save'] += _T2 - _T1
    due = rec.get('still_due')
    if due and t >= due[0] and len(rec['stills']) < 20:
        path = run_dir / 'stills' / f"{len(rec['stills']):02d}_{due[1]}_{due[2]}_{t:05.1f}s.jpg"
        frame.save(path, quality=88)
        rec['stills'].append({'t': round(t, 2), 'kind': due[1], 'drum': due[2], 'file': f'stills/{path.name}'})
        rec.pop('still_due')
    rec['telemetry'].append({'t': round(t, 2), 'pose': [round(float(p[0]), 3), round(float(p[1]), 3), round(float(yaw), 3)],
                             'phase': mission['phase'], 'tilt_deg': round(_math.degrees(mission['pitch']), 1),
                             'look': CODE[mission['look']['drum']] if mission['look'] else None})
    if index % (FPS * 10) == 0:
        print(f"[hot] 1 t {t:.0f}s stop {mission['stop_i']}/{len(PLAN)} decided {len(rec['status'])} yolo {rec['yolo_calls']}", flush=True)
    target_cmd = _np2.asarray(command, _np2.float32)
    lim = _np2.array([ACC_V, ACC_V, ACC_W], _np2.float32) * FRAME_DT
    cmd_s = (cmd_s + _np2.clip(target_cmd - cmd_s, -lim, lim)).astype(_np2.float32)
    _T3 = _wtime.perf_counter()
    lean = mission.get('lean')
    if lean is not None and getattr(lean, 'robot', None) is not None:
        cmd_s = _np2.zeros(3, dtype=_np2.float32)
        for _ in range(stride):
            lean.step(dt)
            world.step(render=False)
    else:
        if lean is not None:
            lean.step(FRAME_DT)
        for _ in range(stride):
            spot.step(dt, cmd_s)
            world.step(render=False)
    PERF['physics'] += _wtime.perf_counter() - _T3
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
    memory.append({'drum_id': d['display_id'], 'internal_id': d['id'], 'side': d['location']['side'],
                   'column': d['location']['column'], 'tier': d['location']['tier'], 'x': d['x'], 'y': d['y'],
                   'z': d['base_z'], 'status': s, 'finding': rec['finding'].get(d['id'], 'none') if s != 'OK' else 'none',
                   'confidence': round(rec['best'].get(d['id'], 0.0), 3), 'views': len(views),
                   'fault_views': sum(1 for v in views if faults_of(v)), 'view_detail': views})
(run_dir / 'memory.json').write_text(_json.dumps({'drums': memory, 'duration_s': t, 'started_utc': _START,
    'yolo_calls': rec['yolo_calls'], 'yolo_failures': rec['yolo_fail'], 'stills': rec['stills'], 'lean_calibration': rec.get('lean_cal', []),
    'detector': 'YOLO26s whole-barrel conditions compare_20261108T043410Z', 'rule_old': 'side look 3 views: >=2 fault views and best >= 0.72 -> defect, 0 -> OK; else second look 3 views: >=2 defect, 0 OK, 1 suspect'},
    indent=2, default=float))
(run_dir / 'decisions.jsonl').write_text(''.join(_json.dumps(x) + '\n' for x in rec['decisions']))
(run_dir / 'detections.jsonl').write_text(''.join(_json.dumps(x) + '\n' for x in rec['detections']))
(run_dir / 'telemetry.jsonl').write_text(''.join(_json.dumps(x) + '\n' for x in rec['telemetry']))
counts = {k: sum(m['status'] == k for m in memory) for k in ('OK', 'Suspect', 'Confirmed defect', "Couldn't inspect")}
card = Image.blend(frame, Image.new('RGB', (1920, 1080), BLK), .82)
cd = ImageDraw.Draw(card)
cd.text((80, 60), 'CANIS AISLE A ROUND COMPLETE (LLW + ILW)', font=F[36], fill=YEL)
cd.text((80, 130), f"Inspected {len(memory)} drums   OK {counts['OK']}   Suspect {counts['Suspect'] + counts[chr(67) + 'ouldn' + chr(39) + 't inspect']}   "
        f"Confirmed defect {counts['Confirmed defect']}   Time {int(t) // 60:02d}:{int(t) % 60:02d}", font=F[30], fill=WHITE)
yy = 200
for m in memory:
    if m['status'] != 'OK':
        cd.text((80, yy), f"{m['drum_id']}  {m['status']:17s} {m['finding']}  {m['confidence']:.2f}  ({m['fault_views']}/{m['views']} views)",
                font=F[26], fill=RGB[m['status']])
        yy += 36
start = len(list(frames_dir.glob('*.jpg')))
for k in range(4 * FPS):
    card.save(frames_dir / f'{start + k:05d}.jpg', quality=90)
import glob as _glob
import shutil as _shutil
import subprocess as _sp
_ff = (_glob.glob('/usr/local/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*') or [_shutil.which('ffmpeg')])[0]
if _ff:
    _sp.run([_ff, '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', str(frames_dir / '%05d.jpg'),
             *(['-vf', 'framerate=fps=24'] if FPS < 24 else []),
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
print('[hot] PERF wall', round(_wtime.perf_counter() - _WALL0, 1), {k: round(v, 1) for k, v in PERF.items()}, 'frames', index, flush=True)
print(f"[hot] CANIS dense walk {W_NAME}: {counts} in {t:.0f}s, yolo {rec['yolo_calls']} calls", flush=True)
