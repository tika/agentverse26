"""Seeded fault assignment for the dense-aisle demo (docs/demo_video_plan.md, T4).

Pure Python: no Isaac imports. Faults use the existing mechanisms only:
- rust and bulge become stage-3 runtime defects in the sim/scenarios/*.json schema,
  rendered per drum by scenario_scene.apply_visual_scenario (corrosion overlay /
  deformed refined body mesh + relabel_deformed);
- heat becomes scene['drum_offsets_c'] (surface rise over ambient, scripts/hot/scenario_lib.py);
- h2 becomes a config['gas_vents'] entry (inspection_payloads.gas_at_pose) paired with an
  acoustic hiss, as in scripts/hot/agent_ilw_round.py.

Ground truth is written for the scorer only; the agent must never import truth files.
"""
import copy
import json
from pathlib import Path

import numpy as np

FAULT_KINDS = ('rust', 'bulge', 'heat', 'h2')
LAYOUT = Path(__file__).with_name('layouts') / 'layout_training.json'
DOUBLE_FAULT_P = .3  # Chance that the heat or h2 drum also carries the other (heating with gas generation).


def _aisle_facing(drums):
    return [d for d in drums if d.get('visible_face', True) and d['location'].get('depth', 1) == 1]


def assign_faults(section_drums, seed, count=(4, 6)):
    """drum_id -> {'kinds': [...], <kind>: params}. Deterministic per seed.

    One drum per (side, tier) stratum, so 4-6 faults always cover tiers 1-3 and both sides,
    and the first four drums get rust, bulge, heat and h2 in a shuffled order."""
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 4]))
    drums = sorted(_aisle_facing(section_drums), key=lambda d: d['id'])
    strata = {}
    for d in drums:
        strata.setdefault((d['location']['side'], d['location']['tier']), []).append(d)
    sides = sorted({side for side, _ in strata})
    tiers = sorted({tier for _, tier in strata})
    n = int(rng.integers(count[0], count[1] + 1))
    n = min(n, len(strata))
    if n < 1:
        return {}
    # One stratum per tier on a random side, then make sure both sides appear.
    chosen = [(sides[int(rng.integers(len(sides)))], tier) for tier in tiers]
    chosen = [c for c in chosen if c in strata]
    if len(sides) > 1 and len({side for side, _ in chosen}) == 1:
        i = int(rng.integers(len(chosen)))
        flipped = (next(s for s in sides if s != chosen[i][0]), chosen[i][1])
        if flipped in strata:
            chosen[i] = flipped
    rest = [k for k in sorted(strata) if k not in chosen]
    rng.shuffle(rest)
    chosen = (chosen + rest)[:n]
    rng.shuffle(chosen)
    kinds = list(FAULT_KINDS)
    rng.shuffle(kinds)
    kinds += [FAULT_KINDS[int(rng.integers(len(FAULT_KINDS)))] for _ in range(n - len(kinds))]
    faults = {}
    for stratum, kind in zip(chosen, kinds):
        options = strata[stratum]
        drum = options[int(rng.integers(len(options)))]
        entry = {'kinds': [kind]}
        if kind in ('heat', 'h2') and rng.random() < DOUBLE_FAULT_P:
            entry['kinds'].append('h2' if kind == 'heat' else 'heat')
        for k in entry['kinds']:
            entry[k] = _params(k, drum, rng)
        faults[drum['id']] = entry
    return faults


def _params(kind, drum, rng):
    height = float(drum['height'])
    if kind == 'rust':
        region = str(rng.choice(['lower_chime', 'mid_sidewall']))
        return {'severity': int(rng.integers(1, 4)), 'surface_region': region,
                'center_z_m': .08 if region == 'lower_chime' else round(height * float(rng.uniform(.45, .72)), 3),
                'dimensions_m': [round(float(rng.uniform(.12, .30)), 3), round(float(rng.uniform(.06, .14)), 3)],
                'visible_fraction': 1.0}
    if kind == 'bulge':
        # dimensions_m = [vertical extent, angular extent, radial expansion]; 0.015-0.025 m
        # radial is a 5-9% diameter increase, above the 5% failing criterion.
        return {'severity': 2, 'surface_region': 'mid_sidewall',
                'center_z_m': round(height * float(rng.uniform(.35, .50)), 3),
                'dimensions_m': [round(float(rng.uniform(.18, .30)), 3), round(float(rng.uniform(.40, .70)), 3),
                                 round(float(rng.uniform(.015, .025)), 4)],
                'visible_fraction': 1.0}
    if kind == 'heat':
        return {'surface_rise_c': round(float(rng.uniform(8, 30)), 1)}
    if kind == 'h2':
        z = float(drum.get('base_z', 0.0)) + height / 2
        return {'position_m': [round(float(drum['x']), 3), round(float(drum['y']), 3), round(z, 3)],
                'hydrogen_ppm': round(float(rng.uniform(300, 1200)))}
    raise ValueError(f'unknown fault kind {kind!r}')


def _runtime_defects(entry):
    out = []
    if 'rust' in entry:
        out.append({'kind': 'corrosion', **entry['rust']})
    if 'bulge' in entry:
        out.append({'kind': 'bulge', **entry['bulge']})
    return out


def apply_to_inventory(inventory, faults, section_ids=None):
    """New inventory: faulty drums carry their visual faults; every other drum in the section
    (all drums when section_ids is None) is reset to clean so no other faults leak in."""
    section = None if section_ids is None else set(section_ids)
    out = copy.deepcopy(inventory)
    for d in out:
        if d['id'] not in faults and (section is None or d['id'] in section):
            d.update({'state': 'clean', 'faults': [], 'corrosion_severity': 0, 'defects': [],
                      'internal_corrosion': False})
            d['shape'] = {**d.get('shape', {}), 'lid_rise': 0.0, 'dents': []}
            d['shape'].pop('bulge', None)
        elif d['id'] in faults:
            f = faults[d['id']]
            names = (['corrosion'] if 'rust' in f else []) + (['bulge'] if 'bulge' in f else [])
            d['faults'] = names
            d['state'] = '+'.join(names) or 'clean'
            d['corrosion_severity'] = f['rust']['severity'] if 'rust' in f else 0
            d['defects'] = _runtime_defects(f)
            d['shape'] = {**d.get('shape', {}), 'dents': []}
            if 'bulge' in f:
                d['shape']['bulge'] = {'center_z_m': f['bulge']['center_z_m'],
                                       'radial_expansion_m': f['bulge']['dimensions_m'][-1]}
    return out


def visual_scenarios(faults, seed):
    """One scenario dict per rust/bulge drum, for scenario_scene.apply_visual_scenario(stage, s)."""
    out = []
    for drum_id, f in sorted(faults.items()):
        defects = _runtime_defects(f)
        if defects:
            out.append({'scenario_id': f'demo_{seed}_{drum_id}', 'seed': int(seed) * 1000 + int(drum_id[1:]),
                        'asset_id': drum_id, 'runtime': {'defects': defects}})
    return out


def layout_resets(section_ids, layout_path=LAYOUT):
    """Section drums that load_layout() gives authored faults; reset each with set_drum_faults(id, [])."""
    authored = json.loads(Path(layout_path).read_text())['drums']
    return sorted(set(section_ids) & set(authored))


def scene_overrides(faults, inventory):
    """Merge into the hot agent scene: heat offsets, H2 vents and their paired hiss."""
    offsets, vents, acoustic = {}, [], []
    for drum_id, f in sorted(faults.items()):
        if 'heat' in f:
            offsets[drum_id] = f['heat']['surface_rise_c']
        if 'h2' in f:
            vents.append({'position_m': f['h2']['position_m'], 'hydrogen_ppm': f['h2']['hydrogen_ppm']})
            acoustic.append({'kind': 'hiss', 'position_m': f['h2']['position_m'], 'time_s': 0.0,
                             'duration_s': 600.0, 'amplitude': .02})
    return {'drum_offsets_c': offsets, 'gas_vents': vents, 'acoustic': acoustic}


def truth_record(faults, inventory, seed):
    by_id = {d['id']: d for d in inventory}
    record = {'seed': int(seed), 'count': len(faults), 'faults': {}}
    for drum_id, f in sorted(faults.items()):
        d = by_id[drum_id]
        loc = d['location']
        record['faults'][d['display_id']] = {
            'drum_id': drum_id, 'kinds': list(f['kinds']), 'double_fault': len(f['kinds']) > 1,
            'params': {k: f[k] for k in f['kinds']},
            'side': loc['side'], 'tier': loc['tier'], 'column': loc['column'],
            'x': d['x'], 'y': d['y'], 'base_z': d.get('base_z', 0.0)}
    return record


def write_truth(path, record):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(record, indent=2) + '\n')


def score(truth, statuses, second_looks):
    """statuses: display_id -> red/green/amber/grey; second_looks: count or list of looks."""
    faulty = set(truth['faults'])
    red = {k for k, v in statuses.items() if v == 'red'}
    used = second_looks if isinstance(second_looks, int) else len(second_looks)
    found = sorted(faulty & red)
    return {'found': found, 'missed': sorted(faulty - red), 'false_red': sorted(red - faulty),
            'second_looks_used': used,
            'recall': len(found) / len(faulty) if faulty else 1.0,
            'efficiency': len(found) / max(1, used)}
