"""Shared camera and viewpoint contract for the aisle-2 LLW demo (docs/demo_video_plan.md).

Pure numpy, no Isaac imports. The agent (scripts/hot) and the detector training
renders (P1) both import this file, so the robot's onboard camera and the
training camera are the same camera at the same poses.

Frames: world z up. Body origin is Spot's base link (z ~ 0.50 m standing, from the
hot-worker logs). Pitch rotates the camera mount about the body origin;
positive pitch looks up. The Isaac Spot walking policy has no pitch input, so a
pitched view is simulated while the robot stands still and must be labelled so.
"""
import math

import numpy as np

CAMERA = dict(width=640, height=640, fx=400.0, fy=400.0, cx=320.0, cy=320.0)  # detector/dataset_plan.py CAMERA
MOUNT = (0.35, 0.0, 0.45)       # Forward, left, up from the body origin (m). Level mount: 0 deg pitch.
AISLE_Y = 6.0
SECTION = dict(lane='B', category='LLW', x_min=2.4, x_max=9.0)
BODY_Z = 0.50                   # Measured standing base height (hot logs, truth z = 0.4999).
MAX_BODY_PITCH = 0.3            # rad; within what a standing Spot can pitch its body.
# One view per pallet face: 2 columns x 3 tiers. Stand VIEW_LEAD_M before the pallet
# centre on the aisle centre line, yaw towards the row, pitch up. 1.5 m / 35 deg puts the
# pallet near the image centre horizontally; 10 deg pitch lifts tier 3 (top 3.07 m) into frame.
VIEW_PITCH = math.radians(10)
VIEW_YAW = math.radians(35)
VIEW_LEAD_M = 1.5
FRAME_MARGIN_PX = 10
SPOT_FOOTPRINT = (1.1, 0.5)     # Length, width (m), centred on the body origin.
SECOND_LOOK_RANGE_M = 1.3


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


def drum_in_frame(drum, view, body_z=BODY_Z, margin=FRAME_MARGIN_PX):
    uv, depth = project(drum_outline(drum), (*view['stop_xy'], body_z), view['yaw'], view['pitch'])
    return bool(np.all(depth > 0.1) and np.all(uv >= margin)
                and np.all(uv[:, 0] <= CAMERA['width'] - margin) and np.all(uv[:, 1] <= CAMERA['height'] - margin))


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


def inspection_views(inventory, body_z=BODY_Z):
    """Fixed route, x ascending: one view per pallet face, right row then left row at each stop."""
    faces = {}
    for d in section_drums(inventory):
        loc = d['location']
        faces.setdefault((d['pallet_xy'][0], loc['side']), []).append(d)
    views = []
    for (pallet_x, side), drums in sorted(faces.items(), key=lambda item: (item[0][0], item[0][1] != 'R')):
        row_y = drums[0]['y']
        toward = 1.0 if row_y > AISLE_Y else -1.0
        columns = sorted({d['location']['column'] for d in drums})
        views.append(dict(name=f"{SECTION['lane']}-{side}-{columns[0]:02d}-{columns[-1]:02d}",
                          stop_xy=(round(pallet_x - VIEW_LEAD_M, 3), AISLE_Y), yaw=toward * VIEW_YAW,
                          pitch=VIEW_PITCH, side=side, column=columns[0], columns=columns,
                          drum_ids=[d['id'] for d in sorted(drums, key=lambda d: (d['location']['column'], d['location']['tier']))]))
    return views


def _inspection_yaw(drum):
    return (1.0 if drum['y'] > AISLE_Y else -1.0) * VIEW_YAW


def second_look_view(drum, body_z=BODY_Z):
    """A closer view from a new angle: on the aisle line, aimed at the drum, about 1.3 m away."""
    best = None
    for dx in np.arange(-2.0, 2.01, 0.05):
        stop = (round(float(drum['x'] + dx), 3), AISLE_Y)
        yaw = math.atan2(drum['y'] - AISLE_Y, -dx)  # Body faces the drum.
        if abs(math.remainder(yaw - _inspection_yaw(drum), 2 * math.pi)) < math.radians(15):
            continue
        if aisle_clearance(stop, yaw) <= 0.05:
            continue
        for pitch in np.linspace(0.0, MAX_BODY_PITCH, 13):
            view = dict(name=f"second-{drum['display_id']}", stop_xy=stop, yaw=yaw, pitch=float(pitch),
                        side=drum['location']['side'], column=drum['location']['column'], columns=[drum['location']['column']],
                        drum_ids=[drum['id']])
            if not drum_in_frame(drum, view, body_z):
                continue
            eye, _, _ = camera_pose((*stop, body_z), yaw, pitch)
            rng = math.dist(eye[:2], (drum['x'], drum['y']))
            # Closest to 1.3 m; prefer looking back along the aisle (dx > 0, a clearly new angle).
            score = abs(rng - SECOND_LOOK_RANGE_M) + (0.0 if dx > 0 else 0.05)
            if best is None or score < best[0]:
                best = (score, view)
            break  # Smallest pitch that fits.
    if best is None:
        raise ValueError(f"No second-look view fits {drum['display_id']}")
    return best[1]


def jitter_view(view, rng):
    """Training-render jitter around a view: +-0.3 m position, +-10 deg yaw, pitch 0..15 deg."""
    out = dict(view)
    out['stop_xy'] = (float(view['stop_xy'][0] + rng.uniform(-0.3, 0.3)),
                      float(view['stop_xy'][1] + rng.uniform(-0.3, 0.3)))
    out['yaw'] = float(view['yaw'] + rng.uniform(-math.radians(10), math.radians(10)))
    out['pitch'] = float(rng.uniform(0.0, math.radians(15)))
    return out
