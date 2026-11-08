# Cheapest end-to-end check of the dense demo: load after demo_hud.py.
#   python tools/hot_hall.py run scripts/hot/demo_hud.py scripts/hot/dense_walk.py
# Deterministic route through aisle 2 (LLW), body turns to each precomputed view, the rigid
# front camera feeds the YOLO API, and the demo HUD records what happened. No Cosmos, no
# LiDAR: the pose is the simulator's, labelled as such. Statuses here are only "seen by a
# view" (green) or "YOLO fault box on this drum" (amber); the belief layer comes later.
import io as _io
import json
import math
import os
import time as _time
import urllib.request as _url
from pathlib import Path
from PIL import Image
import inspection_viewpoints as vp

FPS = 12
SECTION = vp.section_drums(inventory)
# Precomputed offline (inspection_views takes ~50 s): sim/demo_views.json.
_PLAN = json.loads((Path(vp.__file__).with_name('demo_views.json')).read_text())
VIEWS, UNSEEN = _PLAN['views'], set(_PLAN['uninspectable'])
BY_ID = {d['id']: d for d in inventory}
CODE = {d['id']: d['display_id'] for d in SECTION}
DWELL_S, YOLO_EVERY_S, MAX_S = 1.2, 0.4, float(state.pop('dense_walk_max_s', 75.0))


def yolo(rgb):
    """Send the training-equivalent view: centre crop of the 110 deg frame at 77.3 deg, as 640x640.
    Boxes come back in full-frame pixels."""
    x0, y0, x1, y1 = (round(v) for v in vp.DETECT_BOX)
    side = x1 - x0
    crop = Image.fromarray(rgb[y0:y1, x0:x1]).resize((640, 640), Image.BILINEAR)
    result = _yolo_request(crop)
    k = side / 640
    for det in result.get('detections', []):
        bx = det['bbox_xyxy']
        det['bbox_xyxy'] = [bx[0] * k + x0, bx[1] * k + y0, bx[2] * k + x0, bx[3] * k + y0]
    return result


def _yolo_request(image):
    buffer = _io.BytesIO()
    image.save(buffer, format='JPEG', quality=90)
    boundary = 'dense-walk'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="f.jpg"\r\n'
            'Content-Type: image/jpeg\r\n\r\n').encode() + buffer.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
    request = _url.Request(os.environ['DETECTOR_API_URL'].rstrip('/') + '/predict?band=fixed&confidence=0.25', data=body,
                           headers={'Modal-Key': os.environ['DETECTOR_API_KEY'], 'Modal-Secret': os.environ['DETECTOR_API_SECRET'],
                                    'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with _url.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def drum_boxes(p, yaw):
    """Image-space box of every section drum fully in view (map projection from the pose)."""
    view = dict(stop_xy=(float(p[0]), float(p[1])), yaw=yaw, pitch=0.0)
    out = {}
    for d in SECTION:
        if vp.drum_pixels(d, view, float(p[2]), SECTION) > 0:
            uv, _ = vp.project(vp.drum_outline(d), p, yaw, 0.0)
            lo = np.clip(uv.min(0), 0, [vp.CAMERA['width'], vp.CAMERA['height']])
            hi = np.clip(uv.max(0), 0, [vp.CAMERA['width'], vp.CAMERA['height']])
            out[d['id']] = (*lo, *hi)
    return out


def iou(a, b):
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / max(union, 1e-6)


def overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h) / max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))


def command_to(p, yaw, view):
    """Walk the aisle centre line to the stop, then turn in place to the view yaw."""
    gx, gy = view['stop_xy']
    dx, dy = gx - p[0], gy - p[1]
    if math.hypot(dx, dy) > 0.12:
        heading = math.atan2(dy, dx)
        error = math.remainder(heading - yaw, 2 * math.pi)
        if abs(error) > 0.5:
            return np.array([0.0, 0.0, float(np.clip(1.5 * error, -1.0, 1.0))], np.float32), False
        c, s = math.cos(yaw), math.sin(yaw)
        vx, vy = c * dx + s * dy, -s * dx + c * dy
        speed = min(0.6, 0.9 * math.hypot(dx, dy))
        norm = max(1e-6, math.hypot(vx, vy))
        return np.array([speed * vx / norm, speed * vy / norm, float(np.clip(1.5 * error, -1.0, 1.0))], np.float32), False
    error = math.remainder(view['yaw'] - yaw, 2 * math.pi)
    return np.array([0.0, 0.0, float(np.clip(1.6 * error, -1.0, 1.0))], np.float32), abs(error) < 0.05


zero = np.zeros(3, dtype=np.float32)
spot.restart_from_default_state(zero)
world.step(render=False)
dt = spot.physics_dt
stride = max(1, round(1 / (FPS * dt)))
frames_dir = OUT / 'dense_walk' / 'frames'
frames_dir.mkdir(parents=True, exist_ok=True)
statuses = {CODE[i]: 'grey' for i in CODE}
history = {'gamma': [], 'surface_c': [], 'h2_ppm': [], 'hiss': []}
events, trail, log = [], [], []
view_index, settled_at, last_yolo, boxes = 0, None, -1e9, []
hits, faults = {}, {}  # Per drum: YOLO drum-box matches; fault boxes (class, confidence).
calls, failures, wall = 0, 0, _time.perf_counter()
events.append((0.0, f'Route: {len(VIEWS)} views cover {len(SECTION) - len(UNSEEN)}/{len(SECTION)} drums'))
if UNSEEN:
    events.append((0.0, f'{len(UNSEEN)} tier-3 drums not inspectable: level camera, 1.5 m aisle'))

for index in range(int(MAX_S * FPS)):
    t = index * stride * dt
    world.render()
    p, yaw = pose()
    p = np.asarray(p, float)
    trail.append((float(p[0]), float(p[1])))
    packet = capture_front(index, t)
    rgb = packet['rgb']
    view = VIEWS[view_index] if view_index < len(VIEWS) else None
    activity = 'Route complete'
    if view is not None:
        command, aligned = command_to(p, yaw, view)
        aligned = aligned or settled_at is not None  # Once settled, gait wobble must not restart the dwell.
        activity = f"Walking to view {view_index + 1}/{len(VIEWS)}  ({view['name']})"
        if aligned:
            settled_at = t if settled_at is None else settled_at
            activity = f"Inspecting {view['name']}  ({len(view['drum_ids'])} drums)"
            if t - settled_at > 0.25 and t - last_yolo >= YOLO_EVERY_S:
                last_yolo = t
                try:
                    result = yolo(rgb)
                    calls += 1
                except Exception as error:
                    failures += 1
                    result = {'detections': []}
                    events.append((t, f'YOLO error: {str(error)[:60]}!'))
                expected = drum_boxes(p, yaw)
                boxes, matched = [], {}
                for det in result.get('detections', []):
                    box = det['bbox_xyxy']
                    if det['class_name'] == 'drum':
                        owner = max(expected, key=lambda i: iou(box, expected[i]), default=None)
                        owner = owner if owner and iou(box, expected[owner]) >= 0.4 else None
                        if owner:
                            matched[owner] = max(matched.get(owner, 0), det['confidence'])
                    else:  # Fault boxes belong to the drum whose box contains their centre.
                        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                        inside = [i for i, b in expected.items() if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
                        owner = min(inside, key=lambda i: (expected[i][2] - expected[i][0]), default=None)
                        if owner:
                            faults.setdefault(owner, []).append((det['class_name'], det['confidence']))
                            if statuses[CODE[owner]] != 'amber':
                                statuses[CODE[owner]] = 'amber'
                                events.append((t, f"YOLO {det['class_name']} {det['confidence']:.2f} on {CODE[owner]}"))
                    boxes.append(dict(box=box, label=det['class_name'], conf=det['confidence'],
                                      drum_code=CODE.get(owner, '') if owner else ''))
                for i in matched:
                    hits[i] = hits.get(i, 0) + 1
                    if hits[i] >= 2 and i not in faults and statuses[CODE[i]] == 'grey':
                        statuses[CODE[i]] = 'green'
                log.append(dict(t=round(t, 2), view=view['name'], pose=[*p[:2].round(3).tolist(), round(yaw, 3)],
                                expected=sorted(CODE[i] for i in expected), matched=sorted(CODE[i] for i in matched), detections=result.get('detections', [])))
            if t - settled_at >= DWELL_S:
                view_index, settled_at, boxes = view_index + 1, None, []
        else:
            settled_at = None
    else:
        command = zero
    state_hud = dict(title=f'Dense hall · aisle 2 LLW · smoke test (sim pose, no Cosmos)', t=t, activity=activity,
                     yolo_boxes=boxes, statuses=statuses, robot_xy=(float(p[0]), float(p[1])), robot_yaw=float(yaw),
                     view_half_fov_deg=55.0, trail=trail[-400:], events=events[-4:], history=history,
                     faults_confirmed=0, second_looks_used=0, second_look_budget=None,
                     decision=dict(t=t, action_id='deterministic route', source='rules (smoke)',
                                   reason='Fixed route through precomputed views; no planner in this test.',
                                   evidence=[f'YOLO calls {calls}, errors {failures}',
                                             f'{sum(s == "green" for s in statuses.values())}/{len(statuses)} confirmed clear by YOLO']))
    compose_demo(rgb, state_hud).save(frames_dir / f'{index:05d}.jpg', quality=88)
    if view is None and index % FPS == 0 and t > 1.0 and all(c == 0 for c in command):
        break
    for _ in range(stride):
        spot.step(dt, command)
        world.step(render=False)

(OUT / 'dense_walk' / 'yolo_log.json').write_text(json.dumps(log, indent=1))
summary = dict(views=len(VIEWS), views_done=view_index, sim_s=round(t, 1), wall_s=round(_time.perf_counter() - wall, 1),
               yolo_calls=calls, yolo_failures=failures, clear=sum(s == 'green' for s in statuses.values()),
               detected_once=sorted(CODE[i] for i, n in hits.items() if n == 1), never_detected=sorted(CODE[i] for i in CODE if i not in hits and i not in UNSEEN),
               suspected=sorted(k for k, s in statuses.items() if s == 'amber'), not_inspectable=sorted(CODE[i] for i in UNSEEN))
(OUT / 'dense_walk' / 'summary.json').write_text(json.dumps(summary, indent=1))
print('[dense_walk]', summary, flush=True)
