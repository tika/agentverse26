"""Score a walk per drum colour against the seeded truth. Yellow = LLW, blue = ILW.
    HOT_FORCE_FAULTS='<same json as the run>' python3 scripts/hot/full_hall/wh_score_color.py <run_dir> [seed]"""
import json, math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'sim' / 'warehouse-v3'))
from warehouse_physics import generate_inventory

FORCED = {'A-L-01-T1', 'A-R-01-T1'}


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


run = Path(sys.argv[1]); seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
layout = json.loads((ROOT / 'sim' / 'warehouse-v3' / 'map.json').read_text())
plans = {d['drum_id']: d['visual_plan'] for d in generate_inventory(layout, seed)['drums']}
info = {d['display_id']: d for d in layout['drums']}
memory = json.loads((run / 'memory.json').read_text())


def outcome(row):
    p = plans[info[row['drum_id']]['id']]
    faulty = p['corrosion_severity'] > 0 or p['bulging_severity'] > 0
    s = row['status']
    if s == 'Confirmed defect':
        return faulty, 'caught' if faulty else 'false alarm', p
    if s == 'OK':
        return faulty, 'missed' if faulty else 'correct clear', p
    return faulty, 'unresolved', p


report, rows = {}, []
for label, category in (('yellow', 'LLW'), ('blue', 'ILW')):
    for scope, keep in (('all drums', lambda r: True), ('excluding the 2 planted drums', lambda r: r['drum_id'] not in FORCED)):
        sel = [r for r in memory['drums'] if info[r['drum_id']]['category'] == category and keep(r)]
        if not sel:
            continue
        got = [outcome(r)[1] for r in sel]
        count = {k: got.count(k) for k in ('caught', 'missed', 'correct clear', 'false alarm', 'unresolved')}
        n, right = len(sel), count['caught'] + count['correct clear']
        firm = n - count['unresolved']
        fault_total = sum(1 for r in sel if outcome(r)[0])
        report[f'{label} | {scope}'] = {
            'drums': n, 'faulty_drums': fault_total, **count, 'accuracy_all_drums': round(right / n, 3),
            'accuracy_all_95ci': [round(v, 3) for v in wilson(right, n)], 'firm_calls': firm,
            'accuracy_firm_calls': round(right / firm, 3) if firm else None,
            'faults_caught': f"{count['caught']}/{fault_total}"}
for r in memory['drums']:
    faulty, result, p = outcome(r)
    rows.append([r['drum_id'], info[r['drum_id']]['category'], r['status'], r['finding'], round(p['corrosion_severity'], 2), round(p['bulging_severity'], 2), result])
(run / 'colour_accuracy.json').write_text(json.dumps({'seed': seed, 'detector': memory.get('detector'), 'report': report, 'rows': rows}, indent=1))
for key, value in report.items():
    print(key, json.dumps(value))
for row in rows:
    print(*row)
