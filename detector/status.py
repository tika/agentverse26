"""Read durable per-worker progress without starting a GPU.

python detector/status.py RUN_ID
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
import modal


def main():
    if len(sys.argv)!=2:raise SystemExit('Usage: python detector/status.py RUN_ID')
    volume=modal.Volume.from_name('detector-data')
    base='/pilots/'+sys.argv[1]
    try:
        paths=[entry.path for entry in volume.iterdir(base) if entry.path.endswith('/progress.json')]
    except modal.exception.NotFoundError:
        print('TOTAL 0/40 validated; workers not started (image building or allocation pending)')
        return
    def read(path):return json.loads(b''.join(volume.read_file(path)))
    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(read,paths))
    for row in sorted(rows,key=lambda x:x['seed']):
        print(f"seed {row['seed']:02d}: {row['state']:16s} {row['completed']}/{row['target']} | {row['updated_utc']}")
    print(f"TOTAL {sum(r['completed'] for r in rows)}/40 validated; {len(rows)}/8 workers started")


if __name__=='__main__':main()
