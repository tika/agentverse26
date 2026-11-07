"""Read durable per-worker progress without starting a GPU.

python detector/status.py RUN_ID
"""
import json
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import modal


def main():
    if len(sys.argv)!=2:raise SystemExit('Usage: python detector/status.py RUN_ID')
    volume=modal.Volume.from_name('detector-data')
    base='/pilots/'+sys.argv[1]
    local=Path(__file__).resolve().parents[1]/'out/detector_pilot'/sys.argv[1]/'progress.json'
    expected=json.loads(local.read_text()) if local.exists() else {'target_images':40,'requested_gpus':8}
    try:
        paths=[entry.path for entry in volume.iterdir(base) if entry.path.endswith('/progress.json')]
    except modal.exception.NotFoundError:
        print(f"TOTAL 0/{expected['target_images']} validated; workers not started (image building or allocation pending)")
        return
    def read(path):return json.loads(b''.join(volume.read_file(path)))
    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(read,paths))
    for row in sorted(rows,key=lambda x:x['seed']):
        print(f"seed {row['seed']:02d}: {row['state']:16s} {row['completed']}/{row['target']} | {row['updated_utc']}")
    print(f"TOTAL {sum(r['completed'] for r in rows)}/{expected['target_images']} validated; {len(rows)}/{expected['requested_gpus']} workers started")


if __name__=='__main__':main()
