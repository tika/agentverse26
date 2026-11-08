"""Viewpoints for the aisle-2 LLW demo, computed for the robot's real camera.

Pure numpy, no Isaac imports. The camera is the rigid body-mounted front camera in
sim/front_camera.py (Param's): 1280x720, 110 deg horizontal FOV, 0.60 m forward and
0.12 m above the body origin, level. The walking policy cannot pitch the body, so
every view has pitch 0: to fit tier 3 (top 3.07 m) the robot stands farther back
instead of looking up. Views are chosen once, offline, as a greedy set cover of the
60 aisle-facing drums; the route is therefore deterministic.
"""
import math

import numpy as np

from front_camera import HFOV_DEG, MOUNT_XYZ, RESOLUTION

_FX = RESOLUTION[0] / 2 / math.tan(math.radians(HFOV_DEG) / 2)
CAMERA = dict(width=RESOLUTION[0], height=RESOLUTION[1], fx=_FX, fy=_FX, cx=RESOLUTION[0] / 2, cy=RESOLUTION[1] / 2)
MOUNT = tuple(float(v) for v in MOUNT_XYZ)  # Forward, left, up from the body origin (m).
AISLE_Y = 6.0
SECTION = dict(lane='B', category='LLW', x_min=2.4, x_max=9.0)
BODY_Z = 0.50                   # Measured standing base height (hot logs, truth z = 0.4999).
FRAME_MARGIN_PX = 12
MIN_DRUM_PX = 90                # Apparent drum height; below this YOLO boxes get unreliable.
MIN_CLEARANCE_M = 0.10
SPOT_FOOTPRINT = (1.1, 0.5)     # Length, width (m), centred on the body origin.
SECOND_LOOK_RANGE_M = 1.6
ROUTE_X = (1.2, 9.6)            # Aisle stretch the robot may stand on.


def _in_section(d):
    loc = d['location']
    return (loc['lane'] == SECTION['lane'] and d['category'] == SECTION['category']
            and SECTION['x_min'] <= d['x'] <= SECTION['x_max'])


def section_drums(inventory):
    """Aisle-facing drums of the section: the inspection job."""
    return [d for d in inventory if _in_section(d) and d['visible_face']]


def hidden_drums(inventory):
    """Second-row (-D2) drums of the section: physically hidden, never inspected."""
    return [d for d in inventory if _in_section(d) and not d['visible_face']]


def camera_pose(body_xyz, yaw, pitch):
    """World eye position, forward and up unit vectors of the onboard camera."""
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    fx, fl, fz = MOUNT
    # Pitch about the body's left axis (nose up), then yaw about world z.
    bx, bz = fx * cp - fz * sp, fx * sp + fz * cp
    eye = np.asarray(body_xyz, float) + [bx * cy - fl * sy, bx * sy + fl * cy, bz]
    forward = np.array([cp * cy, cp * sy, sp])
    up = np.array([-sp * cy, -sp * sy, cp])
    return eye, forward, up


def project(points_world, body_xyz, yaw, pitch):
    """Pinhole projection with CAMERA: (uv Nx2 with +u right, +v down; depth N along forward)."""
    eye, forward, up = camera_pose(body_xyz, yaw, pitch)
    right = np.cross(forward, up)
    rel = np.atleast_2d(np.asarray(points_world, float)) - eye
    depth = rel @ forward
    safe = np.where(np.abs(depth) < 1e-9, 1e-9, depth)
    u = CAMERA['cx'] + CAMERA['fx'] * (rel @ right) / safe
    v = CAMERA['cy'] - CAMERA['fy'] * (rel @ up) / safe
    return np.stack([u, v], 1), depth


def drum_outline(drum, samples=24):
    """Top and bottom rims; a vertical cylinder's silhouette is their convex hull."""
    a = np.linspace(0, 2 * math.pi, samples, endpoint=False)
    ring = np.stack([drum['x'] + drum['radius'] * np.cos(a), drum['y'] + drum['radius'] * np.sin(a)], 1)
    base = drum['base_z']
    return np.vstack([np.column_stack([ring, np.full(samples, base)]),
                      np.column_stack([ring, np.full(samples, base + drum['height'])])])


MAX_RANGE_M = 2.6               # Nearest range that still fits tier 2; farther drums are too small to judge.


def face_patch(drum):
    """The inspected surface: the aisle-facing side, 15-85 % of the drum height, +-0.7 radius wide."""
    normal = np.array([0.0, 1.0 if AISLE_Y > drum['y'] else -1.0])
    side = np.array([normal[1], -normal[0]]) * 0.7 * drum['radius']
    face = np.array([drum['x'], drum['y']]) + normal * drum['radius']
    return np.array([[*(face + k * side), drum['base_z'] + f * drum['height']] for k in (-1, 0, 1) for f in (0.15, 0.5, 0.85)])


def drum_in_frame(drum, view, body_z=BODY_Z, margin=FRAME_MARGIN_PX):
    """The inspected face patch is in frame (a close drum may be cropped top and bottom)."""
    uv, depth = project(face_patch(drum), (*view['stop_xy'], body_z), view['yaw'], view.get('pitch', 0.0))
    return bool(np.all(depth > 0.1) and np.all(depth < MAX_RANGE_M) and np.all(uv >= margin)
                and np.all(uv[:, 0] <= CAMERA['width'] - margin) and np.all(uv[:, 1] <= CAMERA['height'] - margin))


MAX_INCIDENCE = math.radians(70)  # Steeper than this, the drum face is too oblique to inspect.


def _blocked(eye, target, drum, others):
    """True if the straight ray eye->target passes through another drum's cylinder."""
    d = target - eye
    for o in others:
        if o['id'] == drum['id']:
            continue
        f = eye[:2] - (o['x'], o['y'])
        a, b, c = d[:2] @ d[:2], 2 * f @ d[:2], f @ f - o['radius'] ** 2
        disc = b * b - 4 * a * c
        if disc <= 0:
            continue
        for t in ((-b - math.sqrt(disc)) / (2 * a), (-b + math.sqrt(disc)) / (2 * a)):
            if 0.02 < t < 0.98 and o['base_z'] <= eye[2] + t * d[2] <= o['base_z'] + o['height']:
                return True
    return False


def face_visible(drum, view, others, body_z=BODY_Z):
    """The aisle-facing side is seen at <= MAX_INCIDENCE and at least 2 of 3 sight lines are unobstructed."""
    eye, _, _ = camera_pose((*view['stop_xy'], body_z), view['yaw'], view.get('pitch', 0.0))
    normal = np.array([0.0, 1.0 if AISLE_Y > drum['y'] else -1.0])
    to_eye = eye[:2] - (drum['x'], drum['y'])
    if math.acos(float(np.clip(to_eye @ normal / np.linalg.norm(to_eye), -1, 1))) > MAX_INCIDENCE:
        return False
    mid = drum['base_z'] + 0.5 * drum['height']
    side = np.array([normal[1], -normal[0]]) * 0.7 * drum['radius']
    face = np.array([drum['x'], drum['y']]) + normal * drum['radius'] * 0.9
    points = [np.array([*(face + k * side), mid]) for k in (-1, 0, 1)]
    return sum(not _blocked(eye, p, drum, others) for p in points) >= 2


def drum_pixels(drum, view, body_z=BODY_Z, others=None):
    """Apparent drum height in pixels (0 if not fully in frame, or its face is hidden/oblique)."""
    if not drum_in_frame(drum, view, body_z):
        return 0.0
    if others is not None and not face_visible(drum, view, others, body_z):
        return 0.0
    uv, _ = project(face_patch(drum), (*view['stop_xy'], body_z), view['yaw'], view.get('pitch', 0.0))
    return float(uv[:, 1].max() - uv[:, 1].min()) / 0.7  # Face patch spans 70 % of the drum height.


def _footprint(stop_xy, yaw):
    length, width = SPOT_FOOTPRINT
    c, s = math.cos(yaw), math.sin(yaw)
    corners = np.array([[length / 2, width / 2], [length / 2, -width / 2], [-length / 2, -width / 2], [-length / 2, width / 2]])
    return corners @ np.array([[c, s], [-s, c]]) + np.asarray(stop_xy, float)


def _point_polygon_distance(point, poly):
    inside = True
    best = float('inf')
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ab, ap = b - a, point - a
        t = np.clip(ap @ ab / (ab @ ab), 0, 1)
        best = min(best, float(np.linalg.norm(ap - t * ab)))
        if ab[0] * ap[1] - ab[1] * ap[0] < 0:
            inside = False
    return 0.0 if inside else best


def aisle_clearance(stop_xy, yaw, inventory=None):
    """Smallest gap (m) between Spot's footprint and the section's front drums; negative = collision."""
    if inventory is None:
        xs = [2.791, 3.411, 4.091, 4.711, 5.391, 6.011, 6.691, 7.311, 7.991, 8.611]
        drums = [(x, y, 0.299) for x in xs for y in (4.949, 7.051)]
    else:
        drums = {(round(d['x'], 3), round(d['y'], 3), d['radius']) for d in section_drums(inventory)}
    poly = _footprint(stop_xy, yaw)
    return min(_point_polygon_distance(np.array([x, y]), poly) - r for x, y, r in drums)


def _candidates():
    for x in np.arange(ROUTE_X[0], ROUTE_X[1] + 1e-9, 0.1):
        for sign in (-1.0, 1.0):
            for deg in np.arange(10.0, 172.5, 2.5):
                yield (round(float(x), 2), AISLE_Y), sign * math.radians(deg)


def inspection_views(inventory, body_z=BODY_Z):
    """Deterministic route, x ascending: views that show every inspectable drum face as large
    as possible within MAX_RANGE_M (greedy cover weighted by apparent size)."""
    drums = section_drums(inventory)
    options = []
    for stop, yaw in _candidates():
        if aisle_clearance(stop, yaw, inventory) <= MIN_CLEARANCE_M:
            continue
        view = dict(stop_xy=stop, yaw=yaw, pitch=0.0)
        seen = {d['id']: px for d in drums if (px := drum_pixels(d, view, body_z, drums)) >= MIN_DRUM_PX}
        if seen:
            options.append((view, seen))
    todo, chosen = {d['id'] for d in drums}, []
    while todo and options:
        # Prefer the views that show the remaining drums biggest (nearest), not merely the most drums.
        view, seen = max(options, key=lambda o: sum(o[1][i] for i in todo & o[1].keys()))
        gain = todo & seen.keys()
        if not gain:
            break  # The rest are not inspectable from the aisle with this camera; see uninspectable().
        chosen.append((view, sorted(gain)))
        todo -= gain
    by_id = {d['id']: d for d in drums}
    views = []
    for view, ids in sorted(chosen, key=lambda c: (c[0]['stop_xy'][0], c[0]['yaw'])):
        side = by_id[ids[0]]['location']['side']
        columns = sorted({by_id[i]['location']['column'] for i in ids})
        views.append(dict(name=f"{SECTION['lane']}-{side}-{columns[0]:02d}" + (f"-{columns[-1]:02d}" if len(columns) > 1 else ''),
                          stop_xy=view['stop_xy'], yaw=view['yaw'], pitch=0.0, side=side, column=columns[0],
                          columns=columns, drum_ids=sorted(ids, key=lambda i: (by_id[i]['location']['column'], by_id[i]['location']['tier']))))
    return views


def uninspectable(inventory, views):
    """Aisle-facing drums no view covers: reported as 'not inspectable from aisle'."""
    covered = {i for v in views for i in v['drum_ids']}
    return [d for d in section_drums(inventory) if d['id'] not in covered]


def second_look_view(drum, others, body_z=BODY_Z, avoid_yaw=None):
    """A closer view of one drum from a new angle, on the aisle line."""
    best = None
    for dx in np.arange(-3.0, 3.01, 0.05):
        stop = (round(float(drum['x'] + dx), 3), AISLE_Y)
        eye_target = math.atan2(drum['y'] - AISLE_Y, -dx)
        for offset in np.radians(np.arange(-20, 21, 2.5)):
            yaw = eye_target + offset
            if avoid_yaw is not None and abs(math.remainder(yaw - avoid_yaw, 2 * math.pi)) < math.radians(15):
                continue
            if aisle_clearance(stop, yaw) <= MIN_CLEARANCE_M:
                continue
            view = dict(name=f"second-{drum['display_id']}", stop_xy=stop, yaw=yaw, pitch=0.0,
                        side=drum['location']['side'], column=drum['location']['column'],
                        columns=[drum['location']['column']], drum_ids=[drum['id']])
            px = drum_pixels(drum, view, body_z, others)
            if px < MIN_DRUM_PX:
                continue
            score = -px  # Biggest view of the drum wins.
            if best is None or score < best[0]:
                best = (score, view)
    if best is None:
        raise ValueError(f"No second-look view fits {drum['display_id']}")
    return best[1]


def jitter_view(view, rng):
    """Training-render jitter: +-0.3 m along the aisle, +-0.15 m across, +-8 deg yaw, gait pitch/roll +-3 deg."""
    out = dict(view)
    out['stop_xy'] = (float(view['stop_xy'][0] + rng.uniform(-0.3, 0.3)),
                      float(view['stop_xy'][1] + rng.uniform(-0.15, 0.15)))
    out['yaw'] = float(view['yaw'] + rng.uniform(-math.radians(8), math.radians(8)))
    out['pitch'] = float(rng.uniform(-math.radians(3), math.radians(3)))
    return out
