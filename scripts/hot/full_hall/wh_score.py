"""Score a warehouse walk against the seeded faults (truth recomputed from map.json + seed; never seen by the agent).
    python3 scripts/hot/full_hall/wh_score.py <run_dir> [seed]"""
import json, sys, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'sim' / 'warehouse-v3'))
from warehouse_physics import generate_inventory
run = Path(sys.argv[1]); seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
layout = json.loads((ROOT / 'sim' / 'warehouse-v3' / 'map.json').read_text())
plans = {d['drum_id']: d['visual_plan'] for d in generate_inventory(layout, seed)['drums']}
code = {d['id']: d['display_id'] for d in layout['drums']}
truth = {code[i]: {'rust': round(p['corrosion_severity'], 2), 'bulge': round(p['bulging_severity'], 2)} for i, p in plans.items()}
mem = json.loads((run / 'memory.json').read_text())['drums']
res = collections.Counter(); rows = []
for m in mem:
    t = truth[m['drum_id']]; faulty = t['rust'] > 0 or t['bulge'] > 0; s = m['status']
    k = ('caught' if s == 'Confirmed defect' else 'orange' if s != 'OK' else 'MISSED') if faulty else \
        ('correct green' if s == 'OK' else 'FALSE RED' if s == 'Confirmed defect' else 'orange')
    res[(m['tier'], k)] += 1
    rows.append((m['drum_id'], s, m['finding'], m['confidence'], t['rust'], t['bulge'], k))
(run / 'truth_comparison.json').write_text(json.dumps({'seed': seed, 'rows': rows, 'by_tier': {f'{a}|{b}': n for (a, b), n in res.items()}}, indent=1))
for r in rows:
    print(*r)
print(sorted(res.items()))
