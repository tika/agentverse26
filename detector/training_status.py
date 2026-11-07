"""Read one saved progress snapshot without starting a GPU worker."""
import argparse
import json
from pathlib import Path
import modal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id', nargs='?')
    args = parser.parse_args()
    run_id = args.run_id
    if not run_id:
        run_id = json.loads((Path(__file__).resolve().parents[1]/'out/detector_training/latest.json').read_text())['run_id']
    volume = modal.Volume.from_name('detector-models', environment_name='main')
    raw = b''.join(volume.read_file(f'/runs/{run_id}/progress.json'))
    print(json.dumps(json.loads(raw), indent=2))


if __name__ == '__main__':
    main()
