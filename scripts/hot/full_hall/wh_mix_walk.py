# CANIS side-look walk in Levi's warehouse-v3, aisle A (y = 4.83): one LLW section (yellow, first 2 pallets)
# then, further down the same aisle, one ILW section (blue, 1.2 m drums). Both sides, 3 tiers. One straight pass.
# Smoothed motion: 24 fps, acceleration-limited walk/turn commands, eased camera head and chase view.
# Environment and seeded faults used as built (HOT_WAREHOUSE_SEED=42). Existing YOLO26s.
import io as _io
import json as _json
import math as _math
import os as _os
import time as _wtime
import urllib.request as _url
from pathlib import Path as _Path
from PIL import Image, ImageDraw, ImageFont

W_NAME = globals().get('W_NAME', 'canis_wh_mix')
W_MAX_COLS = int(globals().get('W_MAX_COLS', 99))
W_LLW_XMAX = float(globals().get('W_LLW_XMAX', 5.0))
W_ILW_XMAX = float(globals().get('W_ILW_XMAX', 16.6))
W_MAX_S = float(globals().get('W_MAX_S', 400.0))
FPS = 24
FLAG, WEAK, CONFIRM, VIEWS, CLOSE_VIEWS = 0.50, 0.25, 0.72, 3, 5
TOP_TILT = 0.60          # rad; steeper upward views are outside the detector's training range
SETTLE_S, YOLO_EVERY_S, LOOK_TIMEOUT_S, SECOND_STEP = 0.35, 0.4, 3.5, 0.40
YEL, BLK, WHITE, GREY = (255, 212, 0), (10, 10, 10), (255, 255, 255), (110, 118, 128)
RGB = {'OK': (60, 220, 140), 'Suspect': (255, 160, 40), 'Confirmed defect': (255, 70, 70),
       "Couldn't inspect": (255, 160, 40), 'Checking': WHITE}
F = {s: ImageFont.load_default(size=s) for s in (14, 16, 18, 20, 22, 26, 30, 36)}
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


# ------------------------------------------------------------------ YOLO (training-equivalent 77.3 deg crop)
X0, Y0, SIDE = 0, 0, 640


def yolo(rgb):
    crop = Image.fromarray(rgb)
    buffer = _io.BytesIO()
    crop.save(buffer, format='JPEG', quality=92)
    boundary = 'canis-dense'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="f.jpg"\r\n'
            'Content-Type: image/jpeg\r\n\r\n').encode() + buffer.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
    request = _url.Request(_os.environ['DETECTOR_API_URL'].rstrip('/') + '/predict?band=fixed&confidence=0.25', data=body,
                           headers={'Modal-Key': _os.environ['DETECTOR_API_KEY'], 'Modal-Secret': _os.environ['DETECTOR_API_SECRET'],
                                    'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with _url.urlopen(request, timeout=120) as response:
        result = _json.loads(response.read())
    return crop, result                     # boxes stay in 640x640 crop pixels


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


def judge(views, first):
    """views: per view {class: conf} for every corrosion/bulge box on the target (conf >= WEAK).
    First look: >=2 strong views (>= FLAG) and best >= CONFIRM -> defect; nothing at all -> OK; else closer look.
    Closer look: >=2 strong views, or a box in >=4 of 5 views -> defect; nothing -> OK; else Suspect."""
    seen = sum(1 for v in views if v)
    strong = sum(1 for v in views if any(c >= FLAG for c in v.values()))
    best = max((c for v in views for c in v.values()), default=0.0)
    counts = {}
    for v in views:
        for f in v:
            counts[f] = counts.get(f, 0) + 1
    finding = '+'.join(sorted(f for f, n in counts.items() if n >= 2)) or '+'.join(sorted(counts)) or 'none'
    if first:
        if strong >= 2 and best >= CONFIRM:
            return 'Confirmed defect', finding, best
        return ('OK', 'none', best) if seen == 0 else (None, finding, best)
    if strong >= 2 or seen >= 4:
        return 'Confirmed defect', finding, best
    return ('OK', 'none', best) if seen == 0 else ('Suspect', finding, best)


def decide(t, look):
    i, views = look['drum'], look['views']
    code = CODE[i]
    if look['pass'] == 'side':
        status, finding, best = judge(views, True) if views else (None, 'none', 0.0)
        if status == 'OK' and look['pitch'] > TOP_TILT:
            status = None                        # top tier from below: look longer before calling it clear
        if status is None:
            rec['first'][i] = views
            mission['second'].append(i)
            why = 'no clear view' if not views else f"{finding} in {sum(1 for v in views if v)}/{len(views)} views"
            log(t, code, f'{code} unclear ({why}) -> second look', 'suspect')
            return
    else:
        status, finding, best = judge(views, False) if views else ("Couldn't inspect", 'none', 0.0)
        views = rec['first'].get(i, []) + views
    if status == 'OK' and look['pitch'] > TOP_TILT and look['pass'] == 'second':
        earlier = sorted({f for v in rec['first'].get(i, []) for f in v})
        status, finding = 'Suspect', ('weak ' + '+'.join(earlier) + ' from below' if earlier else 'top tier: not verifiable from below')
    rec['status'][i], rec['finding'][i], rec['best'][i], rec['views'][i] = status, finding, best, views
    n, k = len(views), sum(1 for v in views if v)
    if status == 'Confirmed defect':
        log(t, code, f'{code} {finding.upper()} -> DEFECT ({best:.2f}, {k}/{n} views)', 'confirmed', True)
    elif status == 'OK':
        log(t, code, f'{code} clear in {n} views -> OK', 'cleared')
    elif status == 'Suspect':
        log(t, code, f'{code} {finding} -> SUSPECT (orange, person to check)' if ('top tier' in finding or 'from below' in finding) else
            f'{code} weak {finding} in {k}/{n} views -> SUSPECT (orange)', 'suspect', 'top tier' not in finding)
    else:
        log(t, code, f"{code} no clear view -> couldn't inspect", 'blocked', True)


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
    if chase_rgb is not None:
        canvas.paste(Image.fromarray(chase_rgb), (0, 60))
    dr = ImageDraw.Draw(canvas)
    dr.rectangle((0, 0, 1920, 58), fill=BLK)
    dr.text((20, 12), 'CANIS  |  warehouse-v3, aisle A: LLW + ILW  |  live YOLO26s side looks', font=F[30], fill=YEL)
    dr.text((1700, 14), f'{int(t) // 60:02d}:{int(t) % 60:02d}', font=F[30], fill=YEL)
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
    for b in boxes:
        if not b.get('target'):
            continue                            # only the drum being inspected is classified
        col = {'corrosion': (255, 70, 70), 'bulge': (255, 140, 0)}.get(b['cls'], (120, 200, 255))
        if b['cls'] != 'drum':
            vd.rectangle(b['box'], outline=col, width=3)
            vd.text((b['box'][0] + 4, b['box'][1] + 2), f"{b['cls']} {b['conf']:.2f}", font=F[18], fill=col)
    if hold:
        code_ = CODE[look['drum']]
        word = {'OK': 'OK', 'Confirmed defect': 'DEFECT', 'Suspect': 'SUSPECT', "Couldn't inspect": "COULDN'T INSPECT"}.get(verdict, 'CLOSER LOOK')
        conf_ = rec['best'].get(look['drum'], 0.0)
        tag = f"{code_}  {word}" + (f"  {rec['finding'][look['drum']]} {conf_:.2f}" if verdict in ('Confirmed defect', 'Suspect') and conf_ else '')
        vd.rectangle((0, 586, 640, 640), fill=BLK)
        vd.text((14, 596), tag, font=F[30], fill=frame_col)
    canvas.paste(view.resize((620, 620)), (1290, 60))
    dr.rectangle((1290, 60, 1910, 680), outline=YEL, width=2)
    status_line = 'walking to next column'
    if look:
        d = BY_ID[look['drum']]
        tilt = _math.degrees(mission['pitch'])
        status_line = (f"{CODE[look['drum']]} {d['category']}  {'LEFT' if d['location']['side'] == 'L' else 'RIGHT'}  tier {d['location']['tier']}  "
                       f"{'second look' if look['pass'] == 'second' else 'side look'}  tilt {tilt:+.0f} deg")
        marks = ' '.join('FAULT' if any(c >= FLAG for c in v.values()) else 'weak' if v else 'clear' for v in look['views'])
        dr.text((1300, 690), f"view {len(look['views'])}/{VIEWS if look['pass'] == 'side' else CLOSE_VIEWS}: {marks}", font=F[22], fill=YEL)
    elif mission['phase'] == 'done':
        status_line = 'round complete'
    dr.text((1300, 66), status_line, font=F[20], fill=YEL)
    # counters
    seen = list(rec['status'].values())
    n = {k: seen.count(k) for k in ('OK', 'Suspect', 'Confirmed defect', "Couldn't inspect")}
    dr.rectangle((0, 780, 1280, 830), fill=BLK)
    dr.text((20, 790), f"INSPECTED {len(seen)}/{len(SECTION)}   OK {n['OK']}   SUSPECT {n['Suspect'] + n[chr(67) + 'ouldn' + chr(39) + 't inspect']}"
            f"   DEFECT {n['Confirmed defect']}", font=F[30], fill=YEL)
    minimap(dr, (1290, 730, 1910, 1040), p)
    # decision log
    dr.rectangle((0, 838, 1280, 1040), fill=(14, 18, 24))
    yy = 846
    for tt, text, kind in rec['banners'][-6:]:
        col = {'confirmed': (255, 70, 70), 'suspect': (255, 160, 40), 'cleared': (60, 220, 140)}.get(kind, WHITE)
        dr.text((20, yy), f'{int(tt) // 60:02d}:{int(tt) % 60:02d}  {text}', font=F[22], fill=col)
        yy += 32
    live = [b for b in rec['banners'] if t - b[0] < 2.5 and b[2] in ('confirmed', 'suspect', 'blocked')]
    if live:
        _, text, kind = live[-1]
        w = 24 + 14 * len(text)
        dr.rectangle((640 - w // 2, 80, 640 + w // 2, 132), fill=BLK, outline=YEL, width=3)
        dr.text((640 - w // 2 + 12, 90), text, font=F[30], fill=(255, 70, 70) if kind == 'confirmed' else (255, 160, 40))
    dr.rectangle((0, 1048, 1920, 1080), fill='#111822')
    dr.text((16, 1054), 'Detector: existing YOLO26s API, live, 640x640 77 deg camera (training optics). Target drum from map + simulator pose. '
            'Camera pan/tilt head simulated. Warehouse and its seeded faults used as built. Rules decide; no Cosmos.', font=F[16], fill='#9fb2c4')
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
                for det in result.get('detections', []):
                    b, cls = det['bbox_xyxy'], det['class_name']
                    frac = inside_frac(b, tb)
                    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                    inside = tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]
                    if cls == 'drum':
                        on_target = frac >= 0.6 and inside
                    else:   # a fault box belongs to the drum it overlaps most (the drum above/beside cannot lend its rust)
                        owners = [(inside_frac(b, bb), i) for i, bb in others.items() if bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]]
                        owner = max(owners)[1] if owners else None
                        on_target = owner == look['drum'] and frac >= 0.5
                    if cls == 'drum' and on_target:
                        has_drum = True
                    if cls in ('corrosion', 'bulge') and on_target and det['confidence'] >= WEAK:
                        conf[cls] = max(conf.get(cls, 0), det['confidence'])
                    boxes.append({'box': b, 'cls': cls, 'conf': det['confidence'], 'target': on_target})
                tbox = tb
                in_view = tb[0] > -40 and tb[1] > -40 and tb[2] < 680 and tb[3] < 680
                if has_drum or conf or in_view:
                    look['views'].append(conf)
                rec['detections'].append({'t': round(t, 2), 'drum': CODE[look['drum']], 'pass': look['pass'],
                                          'all_fault_boxes': [[b['cls'], round(b['conf'], 3), b['target']] for b in boxes if b['cls'] != 'drum'],
                                          'faults': sorted(conf), 'conf': {k: round(v, 3) for k, v in conf.items()},
                                          'drum_box_matched': has_drum, 'target_box': [round(v, 1) for v in tb],
                                          'tilt_deg': round(_math.degrees(mission['pitch']), 1),
                                          'model_run': result.get('run_id')})
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
    frame = compose(t, p, grab(chase), crop_img if (mission.get('hold') and crop_img is not None) else live_crop, boxes, tbox)
    frame.save(frames_dir / f'{index:05d}.jpg', quality=88)
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
    memory.append({'drum_id': d['display_id'], 'internal_id': d['id'], 'side': d['location']['side'],
                   'column': d['location']['column'], 'tier': d['location']['tier'], 'x': d['x'], 'y': d['y'],
                   'z': d['base_z'], 'status': s, 'finding': rec['finding'].get(d['id'], 'none') if s != 'OK' else 'none',
                   'confidence': round(rec['best'].get(d['id'], 0.0), 3), 'views': len(views),
                   'fault_views': sum(1 for v in views if v), 'view_detail': views})
(run_dir / 'memory.json').write_text(_json.dumps({'drums': memory, 'duration_s': t, 'started_utc': _START,
    'yolo_calls': rec['yolo_calls'], 'yolo_failures': rec['yolo_fail'], 'stills': rec['stills'],
    'rule': 'side look 3 views: >=2 fault views and best >= 0.72 -> defect, 0 -> OK; else second look 3 views: >=2 defect, 0 OK, 1 suspect'},
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
