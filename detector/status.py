"""Read durable per-worker progress without starting a GPU.

python detector/status.py RUN_ID
"""
import json
import sys
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import modal


def main():
    if len(sys.argv)!=2:raise SystemExit('Usage: python detector/status.py RUN_ID')
    volume=modal.Volume.from_name('detector-data')
    base='/pilots/'+sys.argv[1]
    local=Path(__file__).resolve().parents[1]/'out/detector_pilot'/sys.argv[1]/'progress.json'
    expected=json.loads(local.read_text()) if local.exists() else {'target_images':40,'requested_gpus':8,'target_jobs':8}
    if not local.exists():
        try:
            generation=json.loads(b''.join(volume.read_file(base+'/generation.json')))
            expected=dict(target_images=generation['plan']['images'],requested_gpus=generation['plan']['workers'],
                          target_jobs=len(generation['plan']['jobs']))
        except modal.exception.NotFoundError:pass
    try:
        paths=[entry.path for entry in volume.iterdir(base) if re.search(r'/seed_\d+/progress\.json$',entry.path)]
    except modal.exception.NotFoundError:
        print(f"TOTAL 0/{expected['target_images']} validated; workers not started (image building or allocation pending)")
        return
    def read(path):return json.loads(b''.join(volume.read_file(path)))
    with ThreadPoolExecutor(max_workers=10) as pool:rows=list(pool.map(read,paths))
    for row in sorted(rows,key=lambda x:x['seed']):
        print(f"seed {row['seed']:02d}: {row['state']:16s} {row['completed']}/{row['target']} | {row['updated_utc']}")
    active=sum(r['state'] not in ('complete','failed') for r in rows)
    finished=sum(r['state']=='complete' for r in rows)
    print(f"TOTAL {sum(r['completed'] for r in rows)}/{expected['target_images']} validated; "
          f"{finished}/{expected.get('target_jobs',expected['requested_gpus'])} scenes complete; "
          f"{active} active; concurrency cap {expected['requested_gpus']}")


if __name__=='__main__':main()
