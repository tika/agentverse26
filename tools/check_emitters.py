"""Offline emitter check for the demo section (aisle 2, lane B, LLW): no Isaac, no Modal.

    python3 tools/check_emitters.py [--faults faults.json] [--out DIR]

Audits the dense inventory against the documented values, then walks the demo route
(y = 6.0, x 1.3 -> 8.6, 5 cm steps) through sim/sensors.py and prints a pass/fail table.
Gamma uses the same finite-cylinder shielding as scripts/hot/sensing.py DenseSensorWorld
(vectorised here and cross-checked against SensorWorld). Thermal is camera-based in the
agent (scenario_lib.perceive); here it is reproduced analytically for the visible face of
each drum from the aisle, so it is a model of the LWIR number, not a render.

faults.json: {"D123": {"kind": "heat", "rise_c": 20}, "D124": {"kind": "h2", "hydrogen_ppm": 900}, ...}
rust/bulge entries are listed but have no emitter (they are visual only).
"""
import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
from inspection_payloads import gas_at_pose  # noqa: E402
from sensors import SensorWorld, load_config  # noqa: E402
import stacking  # noqa: E402

AISLE_Y, SENSOR_Z, EYE_Z, MOUNT = 6.0, 0.6, 0.95, 0.35  # agent.py samples at z 0.6; eye from scenario_lib mount.
ROUTE_X = np.round(np.arange(1.3, 8.6 + 1e-9, 0.05), 3)
DOSE_SOURCE_SCALE = 0.4      # scripts/hot/dense_round.py
DOC_STRENGTH = {'LLW': 1, 'ILW': 20}                      # docs/sensors_and_criteria.md
DOC_GEOMETRY = {'LLW': (0.299, 0.88), 'ILW': (0.40, 1.20)}  # sim/drums.py CATEGORIES
EMISSIVITY, HEALTHY_OFFSET = 0.90, {'LLW': 0.3, 'ILW': 1.2}  # scenario_lib.py
H2_FLOOR_PPM = 10.0          # agent.py H2_DETECTED_PPM


def section(inventory):
    return [d for d in inventory if d['location']['lane'] == 'B' and d['category'] == 'LLW' and 2.4 <= d['x'] <= 9.0]


def audit(drums, config):
    problems = []
    for d in drums:
        for key in ('source_strength', 'category', 'radius', 'height', 'base_z'):
            if d.get(key) is None:
                problems.append(f"{d['id']}: missing {key}")
        if d['source_strength'] != DOC_STRENGTH[d['category']]:
            problems.append(f"{d['id']}: source_strength {d['source_strength']} != documented {DOC_STRENGTH[d['category']]}")
        if (round(d['radius'], 3), round(d['height'], 2)) != DOC_GEOMETRY[d['category']]:
            problems.append(f"{d['id']}: geometry {d['radius']}/{d['height']}")
        if not 0 <= d['base_z'] < 3.5:
            problems.append(f"{d['id']}: base_z {d['base_z']}")
    return problems


class Gamma:
    """Vectorised SensorWorld._sources (same maths as DenseSensorWorld)."""

    def __init__(self, drums, config):
        self.cfg = config['radiation']
        self.xy = np.array([(d['x'], d['y']) for d in drums])
        self.bottom = np.array([d['base_z'] for d in drums])
        self.top = self.bottom + np.array([d['height'] for d in drums])
        self.r2 = np.square([d['radius'] for d in drums])
        self.centres = np.column_stack((self.xy, (self.bottom + self.top) / 2))
        self.strength = np.array([d['source_strength'] for d in drums], float)
        self.other = ~np.eye(len(drums), dtype=bool)

    def contributions(self, position):
        start = np.asarray(position, float)
        direction = self.centres - start
        offset = start[:2] - self.xy
        a = np.square(direction[:, :2]).sum(1)[:, None]
        b = 2 * (direction[:, 0, None] * offset[:, 0] + direction[:, 1, None] * offset[:, 1])
        c = np.square(offset).sum(1) - self.r2
        disc = b * b - 4 * a * c
        root = np.sqrt(np.maximum(0, disc))
        div = 2 * np.where(a < 1e-12, 1, a)
        enter, leave = np.maximum(1e-6, (-b - root) / div), np.minimum(1 - 1e-6, (-b + root) / div)
        dz = direction[:, 2, None]
        flat = np.abs(dz) < 1e-12
        sdz = np.where(flat, 1, dz)
        lo, hi = (self.bottom - start[2]) / sdz, (self.top - start[2]) / sdz
        vertical = np.maximum(enter, np.minimum(lo, hi)) <= np.minimum(leave, np.maximum(lo, hi))
        height_hit = np.where(flat, (self.bottom <= start[2]) & (start[2] <= self.top), vertical)
        blockers = (self.other & (a >= 1e-12) & (disc >= 0) & (enter <= leave) & height_hit).sum(1)
        d2 = np.maximum(np.square(direction).sum(1), self.cfg['distance_floor_m'] ** 2)
        return self.strength / d2 * self.cfg['shielding_per_drum'] ** blockers

    def expected(self, position):
        return self.cfg['background'] + self.contributions(position).sum()


def apparent(true_c, eps, reflected_c):
    t, r = true_c + 273.15, reflected_c + 273.15
    return (eps * t ** 4 + (1 - eps) * r ** 4) ** 0.25 - 273.15


def corrected(app_c, eps, reflected_c):
    a, r = app_c + 273.15, reflected_c + 273.15
    return max((a ** 4 - (1 - eps) * r ** 4) / eps, 1.0) ** 0.25 - 273.15


def thermal_delta(drum, offset, ambient, eye):
    """Median LWIR apparent temperature over the visible face, emissivity-corrected as agent.py does."""
    theta = np.linspace(-math.pi, math.pi, 181)
    z = np.linspace(0, 1, 41)
    th, zz = np.meshgrid(theta, z)
    px = drum['x'] + drum['radius'] * np.cos(th)
    py = drum['y'] + drum['radius'] * np.sin(th)
    normal = np.stack([np.cos(th), np.sin(th)], -1)
    to_cam = np.stack([eye[0] - px, eye[1] - py], -1)
    to_cam /= np.linalg.norm(to_cam, axis=-1, keepdims=True)
    cos_view = (normal * to_cam).sum(-1)
    visible = cos_view > 0
    profile = 0.55 + 0.45 * np.exp(-((zz - 0.4) / 0.32) ** 2)
    eps = EMISSIVITY * (0.35 + 0.65 * np.clip(cos_view, 0, 1) ** 0.5)
    app = apparent(ambient + offset * profile, eps, ambient)
    return corrected(float(np.median(app[visible])), EMISSIVITY, ambient) - ambient


def walk(drums, hall, faults, config):
    gamma = Gamma([{**d, 'source_strength': d['source_strength'] * DOSE_SOURCE_SCALE} for d in hall], config)
    by_id = {d['id']: d for d in hall}
    vents = [{'position_m': [by_id[i]['x'], by_id[i]['y'], by_id[i]['base_z'] + 0.6], 'hydrogen_ppm': f.get('hydrogen_ppm', 900.0)}
             for i, f in faults.items() if f['kind'] == 'h2']
    world = SensorWorld(hall[:1], {**config, 'gas_vents': vents})  # Environment and gas only; gamma computed above.
    section_ids = {d['id'] for d in drums}
    rows = []
    for t, x in enumerate(ROUTE_X):
        position = (float(x), AISLE_Y, SENSOR_Z)
        contrib = gamma.contributions(position)
        local = contrib[[d['id'] in section_ids for d in hall]].sum()
        reading = world.sample(position, float(t) * 0.1)
        rows.append({'x': float(x), 'gamma': config['radiation']['background'] + contrib.sum(), 'gamma_section': float(local),
                     'temperature_c': reading['temperature_c'], 'rh_pct': reading['relative_humidity_pct'],
                     'h2_ppm': gas_at_pose(position, vents)['hydrogen_ppm'] if vents else 0.0})
    return rows, gamma


def plots(out, rows, drums, faults, thermal):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out.mkdir(parents=True, exist_ok=True)
    xs = [r['x'] for r in rows]
    columns = sorted({round(d['x'], 2) for d in drums})
    fault_x = {}
    for i, f in faults.items():  # Drums in one column share x: join their labels.
        for d in drums:
            if d['id'] == i:
                fault_x.setdefault(round(d['x'], 2), []).append(f['kind'])
    series = {'gamma': ('Gamma expected (uSv/h, scale 0.4, no noise)', [r['gamma'] for r in rows], [r['gamma_section'] for r in rows]),
              'h2': ('H2 (ppm)', [r['h2_ppm'] for r in rows], None),
              'temperature': ('Air temperature (C)', [r['temperature_c'] for r in rows], None),
              'humidity': ('Relative humidity (%)', [r['rh_pct'] for r in rows], None)}
    paths = []
    for name, (label, ys, extra) in series.items():
        fig, ax = plt.subplots(figsize=(9, 3.2))
        ax.plot(xs, ys, lw=1.4, label='total')
        if extra is not None:
            ax.plot(xs, extra, lw=1.2, ls='--', label='section drums only')
            ax.legend(loc='upper right', fontsize=8)
        for c in columns:
            ax.axvline(c, color='#bbb', lw=0.6, zorder=0)
        for x, kind in fault_x.items():
            ax.axvline(x, color='#d33', lw=1.2)
            ax.text(x, ax.get_ylim()[1], '+'.join(kind), color='#d33', fontsize=8, ha='center', va='bottom')
        ax.set_xlabel('route x (m), y = 6.0; grey = drum columns'); ax.set_ylabel(label)
        fig.tight_layout(); path = out / f'{name}.png'; fig.savefig(path, dpi=110); plt.close(fig); paths.append(path)
    fig, ax = plt.subplots(figsize=(9, 3.2))
    for tier in (1, 2, 3):
        pts = sorted((d['x'], v) for d, v in thermal if d['location']['tier'] == tier)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], 'o', ms=4, label=f'tier {tier}')
    ax.axhline(5.0, color='#d33', lw=1, ls='--', label='5 C anomaly threshold')
    ax.set_xlabel('drum x (m)'); ax.set_ylabel('LWIR delta vs air (C), analytic'); ax.legend(fontsize=8)
    fig.tight_layout(); path = out / 'thermal.png'; fig.savefig(path, dpi=110); plt.close(fig); paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--faults', type=Path)
    parser.add_argument('--out', type=Path, default=Path('out/emitters'))
    args = parser.parse_args()
    config = load_config()
    hall = stacking.stack_inventory(json.loads((ROOT / 'sim/drums.json').read_text()))
    drums = section(hall)
    visible = [d for d in drums if d['visible_face']]
    faults = json.loads(args.faults.read_text()) if args.faults else {}
    unknown = [i for i in faults if i not in {d['id'] for d in hall}]
    if unknown:
        raise SystemExit(f'Unknown drum ids in faults: {unknown}')

    # Cross-check the vectorised gamma against the reference SensorWorld.
    reference = SensorWorld(hall, config)
    fast = Gamma(hall, config)
    for x in (2.0, 5.0, 8.0):
        ref = config['radiation']['background'] + sum(v for _, v in reference._sources((x, AISLE_Y, SENSOR_Z)))
        assert abs(ref - fast.expected((x, AISLE_Y, SENSOR_Z))) < 1e-9 * max(1, ref), (x, ref)

    rows, gamma = walk(drums, hall, faults, config)
    ambient = config['environment']['zones']['A']['temperature_c']
    thermal = []
    for d in visible:
        offset = faults.get(d['id'], {}).get('rise_c', HEALTHY_OFFSET[d['category']]) if faults.get(d['id'], {}).get('kind') == 'heat' \
            else HEALTHY_OFFSET[d['category']]
        side = math.copysign(1, d['y'] - AISLE_Y)  # Plan T1 view: 1.5 m before the column, yawed 35 deg to the row.
        eye = (d['x'] - 1.5 + MOUNT * math.cos(math.radians(35)), AISLE_Y + side * MOUNT * math.sin(math.radians(35)), EYE_Z)
        thermal.append((d, thermal_delta(d, offset, ambient, eye)))

    g = np.array([r['gamma'] for r in rows]); gs = np.array([r['gamma_section'] for r in rows])
    noise = config['radiation']['noise_fraction']
    temps = np.array([r['temperature_c'] for r in rows]); rh = np.array([r['rh_pct'] for r in rows])
    h2 = np.array([r['h2_ppm'] for r in rows])
    problems = audit(drums, config)

    print(f'Section: {len(drums)} drums ({len(visible)} aisle-facing, {len(drums) - len(visible)} hidden); hall {len(hall)}')
    print(f'Gamma (scale {DOSE_SOURCE_SCALE}): {g.min():.2f}-{g.max():.2f} uSv/h, section drums give '
          f'{100 * gs.mean() / g.mean():.0f}% on average; peak/trough {g.max() / g.min():.2f}; noise 1-sigma {100 * noise:.0f}%')
    per_drum = []
    for d in visible:
        position = (d['x'], AISLE_Y, SENSOR_Z)
        c = gamma.contributions(position)
        own = c[[h['id'] == d['id'] for h in hall]].sum()
        per_drum.append(own / (config['radiation']['background'] + c.sum()))
    print(f'Single drum share of reading when level with it: median {100 * np.median(per_drum):.1f}% '
          f'(max {100 * max(per_drum):.1f}%) vs {100 * noise:.0f}% noise')
    print(f'Air temperature: {temps.mean():.2f} C +/- {temps.std():.2f}; RH {rh.mean():.1f}% +/- {rh.std():.2f} (zone-only)')
    if faults:
        print('H2: ' + (f'peak {h2.max():.0f} ppm at x={rows[int(h2.argmax())]["x"]:.2f}, '
              f'above {H2_FLOOR_PPM:.0f} ppm for {0.05 * (h2 > H2_FLOOR_PPM).sum():.1f} m of route' if h2.max() else 'none'))
    hot = [(d['display_id'], round(v, 1)) for d, v in thermal if v >= 5.0]
    healthy = [v for d, v in thermal if faults.get(d['id'], {}).get('kind') != 'heat']
    print(f'Thermal (analytic): healthy drums {min(healthy):.2f}-{max(healthy):.2f} C over air; above 5 C: {hot or "none"}')

    checks = [
        ('inventory matches documented values', not problems),
        ('gamma reading varies along route (> 3x noise)', (g.max() - g.min()) / g.mean() > 3 * noise),
        ('a single section drum stands out from noise', max(per_drum) > noise),
        ('air temperature / RH vary per drum', False),
        ('healthy drums stay below the 5 C thermal threshold', max(healthy) < 5.0),
    ]
    for drum_id, f in faults.items():
        d = next((x for x in hall if x['id'] == drum_id), None)
        if f['kind'] == 'heat':
            v = next((v for x, v in thermal if x['id'] == drum_id), None)
            checks.append((f'heat {drum_id}: LWIR delta >= 5 C ({v:.1f} C)' if v is not None else f'heat {drum_id}: drum hidden',
                           v is not None and v >= 5.0))
        elif f['kind'] == 'h2':
            i = int(np.argmin(np.abs(ROUTE_X - d['x'])))
            far = h2[np.abs(ROUTE_X - d['x']) > 3.0]
            checks.append((f'h2 {drum_id}: peak near drum ({h2[i]:.0f} ppm), < 1/3 beyond 3 m',
                           h2[i] > H2_FLOOR_PPM and (far.size == 0 or far.max() < h2[i] / 3)))
        else:
            checks.append((f'{f["kind"]} {drum_id}: visual only, no emitter', True))
    print('\nCheck'.ljust(66) + 'Result')
    for name, ok in checks:
        print(name.ljust(65) + ('PASS' if ok else 'FAIL'))
    for p in problems[:20]:
        print('  audit:', p)
    for path in plots(args.out, rows, drums, faults, thermal):
        print('plot:', path)


if __name__ == '__main__':
    main()
