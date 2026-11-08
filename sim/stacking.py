"""Dense stacked inventory (prompt v1.2.1, Levi's reference photo).

Pure functions (no Isaac imports) so tests, the studio and the runtime map can
reuse them. The floor plan lives in sim/layouts/stacking.json.

Rules:
- Rows of 1.2 m pallets run along x on both sides of each robot aisle (y = 2, 6, 10),
  plus one row against each long wall. LLW pallets carry 2x2 drums, ILW pallets one.
- Every tier sits on its own pallet resting on the drum lids below.
- Lane A/B/C = aisle 1/2/3 that the row faces. Side L/R as seen looking along +x:
  L means the row lies on the +y side of its aisle. Columns are numbered by drum x
  within lane+side; tiers count up from 1. Second-row (back) drums get suffix -D2.
- display_id (plate text) is the location code. Only aisle-facing drums carry a
  plate/stencil; back drums are physically hidden (identity stays unknown).
- D01-D28 keep their immutable IDs on the nearest tier-1 aisle-facing drum of the
  same category; original x/y are kept as legacy_x/legacy_y. New drums: D29 upward.
- A moved drum keeps its ID and gets a new location (not handled here).
"""
import copy
import json
import math
from pathlib import Path

import numpy as np

SIM = Path(__file__).resolve().parent
CONFIG = SIM / 'layouts' / 'stacking.json'
AISLE_Y = {1: 1.0, 2: 6.0, 3: 11.0}  # Aisle 2 widened to 3 m; aisles 1/3 run along the walls.


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text())


def location_code(lane, side, column, tier, depth=1):
    return f'{lane}-{side}-{column:02d}-T{tier}' + ('' if depth == 1 else f'-D{depth}')


def _slots(config):
    """Every drum slot: dict with geometry/location but no ID yet."""
    from drums import CATEGORIES
    lanes = {int(k): v for k, v in config['lanes_by_aisle'].items()}
    half = config['pallet']['size_m'] / 2
    gap = config['drum_gap_m']
    pallet_no = {}
    slots = []
    for row in config['rows']:
        lane, side = lanes[row['aisle']], row['side']
        face = -1 if side == 'L' else 1  # +1: front faces +y
        for zone in config['zones']:
            cat = zone['category']
            radius, height, _ = CATEGORIES[cat]
            for px in zone['pallet_x']:
                if any(px - half <= v <= px + half for v in row.get('skip_x_containing', [])):
                    continue
                key = (lane, side)
                pallet_no[key] = pallet_no.get(key, 0) + 1
                stack_id = f'{lane}-{side}-P{pallet_no[key]:02d}'
                if zone['per_pallet'] == 4:
                    off = radius + gap / 2
                    cells = [(px + dx, row['y'] + face * off, 1) for dx in (-off, off)] + \
                            [(px + dx, row['y'] - face * off, 2) for dx in (-off, off)]
                else:
                    cells = [(px, row['y'], 1)]
                for tier in range(1, row['tiers'][cat] + 1):
                    base_z = tier * config['pallet']['height_m'] + (tier - 1) * height
                    for x, y, depth in cells:
                        slots.append({'category': cat, 'x': round(x, 4), 'y': round(y, 4), 'depth': depth,
                                      'tier': tier, 'tier_count': row['tiers'][cat], 'lane': lane, 'side': side,
                                      'aisle': row['aisle'], 'face_sign': face, 'stack_id': stack_id,
                                      'pallet_xy': [px, row['y']], 'base_z': round(base_z, 4), 'height': height})
    # Column numbers: by drum x within lane+side (front and back drums share a column).
    for key in {(s['lane'], s['side']) for s in slots}:
        xs = sorted({s['x'] for s in slots if (s['lane'], s['side']) == key})
        for s in slots:
            if (s['lane'], s['side']) == key:
                s['column'] = xs.index(s['x']) + 1
    for s in slots:
        s['code'] = location_code(s['lane'], s['side'], s['column'], s['tier'], s['depth'])
    return sorted(slots, key=lambda s: (s['lane'], s['side'], s['column'], s['tier'], s['depth']))


def stack_inventory(entries, config=None, seed=None):
    """Build the full dense inventory. `entries` are the original 28 (for ID mapping)."""
    from drums import nominal_entry
    config = config or load_config()
    originals = sorted((copy.deepcopy(e) for e in entries), key=lambda e: e['id'])
    if not config.get('enabled', True):
        return originals
    seed = originals[0].get('scene_seed', 42) if seed is None else seed
    slots = _slots(config)
    # Map D01-D28 to the nearest free tier-1, aisle-facing slot of the same category.
    taken = {}
    for e in originals:
        free = [i for i, s in enumerate(slots) if i not in taken.values() and s['tier'] == 1
                and s['depth'] == 1 and s['category'] == e['category']]
        best = min(free, key=lambda i: (math.hypot(slots[i]['x'] - e['x'], slots[i]['y'] - e['y']), i))
        taken[e['id']] = best
    by_slot = {i: e for e, i in ((next(o for o in originals if o['id'] == k), v) for k, v in taken.items())}
    rng = np.random.default_rng(seed)
    shades = config['paint_shades']
    next_id = config['first_new_id']
    out = []
    for i, s in enumerate(slots):
        original = by_slot.get(i)
        if original:
            name = original['id']
        else:
            name = f'D{next_id:02d}'
            next_id += 1
        appearance = int(rng.integers(2 ** 31))
        yaw = float(rng.uniform(0, 2 * math.pi))
        base = {'id': name, 'category': s['category'], 'zone': 'A' if s['x'] < 10 else 'B',
                'row': f"{s['lane']}-{s['side']}", 'display_id': s['code'], 'x': s['x'], 'y': s['y'],
                'yaw': yaw, 'facing_aisle': s['aisle'], 'prim_path': '/World/Drums/' + name,
                'scene_seed': seed, 'appearance_seed': appearance}
        d = nominal_entry(base, s['category'])
        d['paint_color'] = shades[appearance % len(shades)]
        d.update({
            'legacy_id': original['id'] if original else None,
            'legacy_display_id': original.get('display_id') if original else None,
            'legacy_x': original['x'] if original else None,
            'legacy_y': original['y'] if original else None,
            'face_sign': s['face_sign'], 'visible_face': s['depth'] == 1,
            'stack_id': s['stack_id'], 'pallet_xy': s['pallet_xy'], 'base_z': s['base_z'],
            'location': {'lane': s['lane'], 'side': s['side'], 'column': s['column'], 'tier': s['tier'],
                         'tier_count': s['tier_count'], 'depth': s['depth'], 'stack_id': s['stack_id'],
                         'base_z_m': s['base_z'], 'location_code': s['code']},
        })
        out.append(d)
    return sorted(out, key=lambda e: (len(e['id']), e['id']))


def pallets(entries, config=None):
    """One pallet per (stack, tier): (stack_id, tier, centre_xyz_of_pallet_bottom, pallet_spec)."""
    config = config or load_config()
    p = config['pallet']
    seen = {}
    for e in entries:
        key = (e['stack_id'], e['location']['tier'])
        if key not in seen:
            px, py = e.get('pallet_xy', (e['x'], e['y']))
            seen[key] = (e['stack_id'], e['location']['tier'], (px, py, e['base_z'] - p['height_m']), p)
    return sorted(seen.values(), key=lambda v: (v[0], v[1]))


def clearance_errors(entries, config=None):
    """Aisles stay >= aisle_clear_min_m wide; pallets never overlap; drums stay on their pallet;
    cross-aisles (x < 2.0, 9.2-10.8, x > 18.0) stay free."""
    config = config or load_config()
    half = config['pallet']['size_m'] / 2
    errors = []
    t1 = [p for p in pallets(entries, config) if p[1] == 1]
    for aisle, cy in AISLE_Y.items():
        below = max((p[2][1] + half for p in t1 if p[2][1] < cy), default=0.0)
        above = min((p[2][1] - half for p in t1 if p[2][1] > cy), default=12.0)
        if above - below < config['aisle_clear_min_m'] - 1e-9:
            errors.append(f'aisle {aisle} clear width {above - below:.2f} m')
    for i, a in enumerate(t1):
        ax, ay = a[2][:2]
        if ax - half < 2.0 or (ax + half > 9.2 and ax - half < 10.8) or ax + half > 18.0:
            errors.append(f'pallet {a[0]} enters a cross-aisle')
        for b in t1[i + 1:]:
            bx, by = b[2][:2]
            if abs(ax - bx) < 2 * half - 1e-9 and abs(ay - by) < 2 * half - 1e-9:
                errors.append(f'pallets {a[0]} and {b[0]} overlap')
    for e in entries:
        px, py = e['pallet_xy']
        if abs(e['x'] - px) + e['radius'] > half + 1e-9 or abs(e['y'] - py) + e['radius'] > half + 1e-9:
            errors.append(f"{e['id']} overhangs its pallet")
    return errors


def column_tiers(entries, lane, side, column):
    """All tiers of one aisle-facing drum column, bottom first (for review/plate tours)."""
    out = [e for e in entries if e['location']['lane'] == lane and e['location']['side'] == side
           and e['location']['column'] == column and e['location']['depth'] == 1]
    if not out:
        raise KeyError(f'no aisle-facing column {lane}-{side}-{column:02d}')
    return sorted(out, key=lambda e: e['location']['tier'])
