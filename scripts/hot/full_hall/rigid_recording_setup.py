"""Load after brand_data.py and rigid_posture.py in a warm warehouse worker.
Shared camera calibration, front-frame HTTP client and the original CANIS HUD.
No mission runs when this file is loaded. No credentials are embedded.
"""
import io as _io
import json as _json
import math as _math
import os as _os
import time as _wtime
import urllib.request as _url
from pathlib import Path as _Path
from PIL import Image, ImageDraw, ImageFont

W_NAME = 'rigid_recording'
W_MAX_COLS = int(globals().get('W_MAX_COLS', 99))
W_LLW_XMAX = float(globals().get('W_LLW_XMAX', 5.0))
W_ILW_XMAX = float(globals().get('W_ILW_XMAX', 16.6))
W_MAX_S = 160.0
FPS = 24
FLAG, WEAK, CONFIRM, VIEWS, CLOSE_VIEWS = 0.50, 0.25, 0.72, 3, 5
TOP_TILT = 0.60          # rad; steeper upward views are outside the detector's training range
SETTLE_S, YOLO_EVERY_S, LOOK_TIMEOUT_S, SECOND_STEP = 0.35, 0.4, 12.0, 0.40
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
import hashlib as _hash
import glob as _glob
import shutil as _shutil
import subprocess as _sp
from front_camera import CAMERA_PATH as _BODY_CAMERA_PATH, rotation as rigid_rotation
zero=_np2.zeros(3,dtype=_np2.float32)
TEST_IDS=set()
eye_cam=onboard
_NATIVE_K=onboard.get_intrinsics_matrix()
_CROP_SIDE=720
_CROP_X=280
FX=float(_NATIVE_K[0,0])*640/_CROP_SIDE
_rigid_pose=None
_last_front=None
_input_native=None
_input_rgb=None
rec={'status':{},'finding':{},'best':{},'views':{},'first':{},'detections':[],
     'telemetry':[],'decisions':[],'banners':[],'stills':[],'yolo_calls':0,'yolo_fail':0}
mission={'eye_view':(_np2.array([0.,0,1]),_np2.array([1.,0,1])),
         'phase':'walk','look':None,'hold':None,'pitch':0.}
if 'canis_chase' not in state:
    from isaacsim.sensors.camera import Camera
    camera=Camera('/World/CanisChase',resolution=(1280,720))
    camera.prim.GetAttribute('focalLength').Set(14.)
    camera.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05,60.))
    camera.initialize()
    state['canis_chase']=camera
chase=state['canis_chase']

def aim(camera, eye, target):
    m = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float, eye)), Gf.Vec3d(*map(float, target)), Gf.Vec3d(0, 0, 1))
    q = m.GetInverse().ExtractRotationQuat()
    camera.set_world_pose(position=_np2.array(eye, dtype=float), orientation=_np2.array([q.GetReal(), *q.GetImaginary()]),
                          camera_axes='usd')

def outline(d, n=24):
    a = _np2.linspace(0, 2 * _math.pi, n, endpoint=False)
    ring = _np2.stack([d['x'] + d['radius'] * _np2.cos(a), d['y'] + d['radius'] * _np2.sin(a)], 1)
    return _np2.vstack([_np2.column_stack([ring, _np2.full(n, d['base_z'])]),
                        _np2.column_stack([ring, _np2.full(n, d['base_z'] + d['height'])])])

def _raw_grab(camera):
    rgba = camera.get_rgba()
    return None if rgba is None or not _np2.asarray(rgba).size else _np2.asarray(rgba)[:, :, :3].astype(_np2.uint8)

def grab(camera):
    global _last_front
    rgb=_raw_grab(camera)
    if camera is eye_cam and rgb is not None:
        _last_front=rgb.copy()
        return _np2.asarray(Image.fromarray(rgb[:,_CROP_X:_CROP_X+_CROP_SIDE]).resize((640,640),Image.Resampling.BILINEAR))
    return rgb

def project_box(d, eye, target):
    if _rigid_pose is None:return None
    _origin,_r=_rigid_pose
    local=(outline(d)-_origin)@_r
    if _np2.any(local[:,0]<.15):return None
    u=320-FX*local[:,1]/local[:,0];v=320-FX*local[:,2]/local[:,0]
    return [float(u.min()),float(v.min()),float(u.max()),float(v.max())]

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

def _orig_yolo(rgb):
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
    return crop, result

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

def _orig_compose(t, p, chase_rgb, crop, boxes, tbox):
    canvas = Image.new('RGB', (1920, 1080), BLK)
    if chase_rgb is not None:
        canvas.paste(Image.fromarray(chase_rgb), (0, 60))
    dr = ImageDraw.Draw(canvas)
    dr.rectangle((0, 0, 1920, 58), fill=(14, 16, 20))
    canvas.paste(LOGO_D, (16, 29 - LOGO_D.height // 2), LOGO_D)
    canvas.paste(LOGO_W, (24 + LOGO_D.width, 29 - LOGO_W.height // 2), LOGO_W)
    xs_ = 40 + LOGO_D.width + LOGO_W.width
    dr.line((xs_, 12, xs_, 46), fill=(70, 74, 80), width=2)
    dr.text((xs_ + 18, 14), 'CANIS | warehouse-v3, aisle A: LLW + ILW | YOLO26s side looks', font=F[24], fill=YEL)
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
    elif mission['phase'] == 'done':
        status_line = 'round complete'
    shade = Image.new('RGBA', (640, 58 if marks_line else 34), (0, 0, 0, 150))
    view.paste(shade, (0, 0), shade)
    vd.text((10, 6), status_line, font=FB[18], fill=YEL)
    if marks_line:
        vd.text((10, 32), marks_line, font=F[16], fill=WHITE)
    canvas.paste(view.resize((620, 620)), (1290, 64))
    dr.rectangle((1290, 64, 1910, 684), outline=YEL, width=2)
    # counters
    seen = list(rec['status'].values())
    n = {k: seen.count(k) for k in ('OK', 'Suspect', 'Confirmed defect', "Couldn't inspect")}
    dr.rectangle((0, 780, 1280, 830), fill=BLK)
    dr.text((20, 792), f"INSPECTED {len(seen)}/{len(TEST_IDS)}   OK {n['OK']}   SUSPECT {n['Suspect'] + n[chr(67) + 'ouldn' + chr(39) + 't inspect']}"
            f"   DEFECT {n['Confirmed defect']}", font=FB[26], fill=YEL)
    minimap(dr, (1290, 696, 1910, 1040), p)
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
    dr.text((16, 1054), 'Detector: retrained YOLO26s whole-barrel conditions, live, 640x640 77 deg camera. Target drum from map + simulator pose. '
            'Rigid body front camera; leg-driven pitch and physical yaw. Warehouse unchanged. Rules decide; no Cosmos.', font=F[14], fill='#9fb2c4')
    return canvas

def frame_coverage(d):
    tb=project_box(d,*mission['eye_view'])
    if tb is None:return {'full_in_frame':False,'bbox_in_frame_fraction':0.,'projected_bbox':None}
    w=max(0.,min(640.,tb[2])-max(0.,tb[0]));h=max(0.,min(640.,tb[3])-max(0.,tb[1]))
    area=max(1e-6,(tb[2]-tb[0])*(tb[3]-tb[1]))
    return {'full_in_frame':bool(min(tb[:2])>=4 and max(tb[2:])<=636),
            'bbox_in_frame_fraction':float(w*h/area),'projected_bbox':tb}
