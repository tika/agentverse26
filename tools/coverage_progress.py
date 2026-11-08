"""Read the latest committed full-store checkpoint without interrupting Isaac.

python3 tools/coverage_progress.py RUN_ID [--json]
"""
import json
import sys
import modal

run_id=sys.argv[1]
if '/' in run_id or '..' in run_id:raise SystemExit('Supply the run ID, not a path')
volume=modal.Volume.from_name('agentverse-mission-runs')
data=json.loads(b''.join(volume.read_file('/checkpoints/'+run_id+'.json')))
counts=data['coverage']['counts']
if '--json' in sys.argv:
    print(json.dumps(data))
else:
    print(f"t={data['time_s']:.1f}s | coverage {counts['complete']}/{counts['total']} | "
          f"pending {counts['pending']} | deferred {counts['deferred']} | "
          f"phase {data['phase']} | target {data['active_drum']} | estimated travel {data['travelled_m']:.1f} m")
    if data['decisions']:
        d=data['decisions'][-1]
        print(f"{d['source']}: {d['action_id']} at {d['t']:.1f}s — {d['reason']}")
