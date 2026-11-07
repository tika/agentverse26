"""Stage-2 stacked inventory: pallets, tiers, immutable IDs and location codes.

Pure functions (no Isaac imports) so tests, the studio and the runtime map can
reuse them. The floor plan stays in sim/layouts/stacking.json.

Rules (prompt v1.2, ADDRESSING):
- D01-D28 keep their IDs and original x/y; they become tier T1 of their stack.
- Upper drums get deterministic IDs from D29 upward, in (base id, tier) order.
- Lane A/B/C = aisle 1/2/3 the stack faces (increasing y). Side L/R as seen
  looking along +x from that aisle: L means the stack is on the +y side.
- Column numbers increase with x within each lane+side; tiers count up from 1.
- display_id (the printed plate text) is the location code, e.g. A-L-01-T2.
- A moved drum keeps its ID and gets a new location (not handled here).
"""
import copy
import json
from pathlib import Path

SIM = Path(__file__).resolve().parent
CONFIG = SIM / 'layouts' / 'stacking.json'
AISLES = SIM / 'aisles.json'


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text())


def aisle_centres(path=AISLES):
    return {a['id']: a['center_y'] for a in json.loads(Path(path).read_text())['aisles']}


def location_code(lane, side, column, tier):
    return f'{lane}-{side}-{column:02d}-T{tier}'


def stack_inventory(entries, config=None, centres=None):
    """Return a new inventory with pallets/tiers applied. Input entries are not modified."""
    config = config or load_config()
    centres = centres or aisle_centres()
    pallet_h = config['pallet']['height_m']
    lanes = {int(k): v for k, v in config['lanes_by_aisle'].items()}
    base = sorted((copy.deepcopy(e) for e in entries), key=lambda e: e['id'])
    if not config.get('enabled', True):
        return base

    # Column numbering per lane+side, increasing x.
    groups = {}
    for e in base:
        lane = lanes[e['facing_aisle']]
        side = 'L' if e['y'] > centres[e['facing_aisle']] else 'R'
        groups.setdefault((lane, side), []).append(e)
    for (lane, side), members in groups.items():
        for column, e in enumerate(sorted(members, key=lambda m: m['x']), start=1):
            e['_lane'], e['_side'], e['_column'] = lane, side, column

    out, next_id = [], config['first_upper_id']
    uppers = []
    for e in base:
        tier_count = config['tiers'][e['category']]
        stack_id = f"{e['_lane']}-{e['_side']}-{e['_column']:02d}"
        for tier in range(1, tier_count + 1):
            d = copy.deepcopy(e) if tier == 1 else _upper_from(e, next_id, tier)
            if tier > 1:
                next_id += 1
            base_z = tier * pallet_h + (tier - 1) * e['height']
            code = location_code(e['_lane'], e['_side'], e['_column'], tier)
            for k in ('_lane', '_side', '_column'):
                d.pop(k, None)
            d.update({
                'legacy_id': e['id'] if tier == 1 else None,
                'legacy_display_id': e.get('display_id') if tier == 1 else None,
                'display_id': code, 'stack_id': stack_id, 'base_z': round(base_z, 4),
                'location': {'lane': e['_lane'], 'side': e['_side'], 'column': e['_column'],
                             'tier': tier, 'tier_count': tier_count, 'stack_id': stack_id,
                             'base_z_m': round(base_z, 4), 'location_code': code},
            })
            (out if tier == 1 else uppers).append(d)
    return out + uppers


def _upper_from(base_entry, number, tier):
    d = copy.deepcopy(base_entry)
    name = f'D{number:02d}'
    d['id'] = name
    d['prim_path'] = '/World/Drums/' + name
    # Deterministic, distinct appearance and yaw for each upper drum.
    d['appearance_seed'] = (base_entry['appearance_seed'] * 31 + tier * 7919) % (2 ** 31)
    d['yaw'] = (base_entry['yaw'] + 2.399963 * tier) % 6.283185307179586
    for k, v in (('state', 'clean'), ('faults', []), ('corrosion_severity', 0), ('defects', []),
                 ('obstructed', False), ('internal_corrosion', False)):
        d[k] = copy.deepcopy(v)
    if d.get('paint_color') is not None:
        from drums import PAINT_NAMES
        d['paint_color'] = PAINT_NAMES[d['appearance_seed'] % 3]
    return d


def pallets(entries, config=None):
    """One pallet under every drum: (stack_id, tier, centre_xyz, size_xyz)."""
    config = config or load_config()
    p = config['pallet']
    out = []
    for e in entries:
        z0 = e['base_z'] - p['height_m']
        out.append((e['stack_id'], e['location']['tier'], (e['x'], e['y'], z0), p))
    return out


def clearance_errors(entries, config=None, centres=None, aisle_half_width=1.0):
    """Pallet footprints must stay out of aisle rectangles and must not overlap each other."""
    config = config or load_config()
    centres = centres or aisle_centres()
    half = config['pallet']['size_m'] / 2
    errors = []
    t1 = [e for e in entries if e['location']['tier'] == 1]
    for e in t1:
        for aid, cy in centres.items():
            if abs(e['y'] - cy) < half + aisle_half_width - 1e-9:
                errors.append(f"{e['id']} pallet enters aisle {aid}")
    for i, a in enumerate(t1):
        for b in t1[i + 1:]:
            if abs(a['x'] - b['x']) < 2 * half - 1e-9 and abs(a['y'] - b['y']) < 2 * half - 1e-9:
                errors.append(f"pallets {a['id']} and {b['id']} overlap")
    return errors
