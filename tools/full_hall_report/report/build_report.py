"""C.A.N.I.S. post-run inspection report: one run folder in, one HTML + PDF report out.

    python tools/full_hall_report/report/build_report.py <run_dir> [--out DIR] [--format auto|framework|canis.v1]
                                                       [--commit HASH] [--store NAME] [--no-pdf]

Writes <out>/index.html (screen), <out>/CANIS_report_<run>.pdf (print), <out>/summary.json (machine-readable
results) and <out>/evidence/ (the frames the report shows). Default <out> is <run_dir>/report.
The PDF needs Node + Playwright (see README.md). If the PDF step fails, the HTML and JSON are still written.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import loaders  # noqa: E402
import render  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run_dir')
    ap.add_argument('--out')
    ap.add_argument('--format', default='auto', choices=['auto', 'framework', 'canis.v1'])
    ap.add_argument('--commit', help='report software version (default: git HEAD of this repo)')
    ap.add_argument('--store', default='Drum Store 1 (simulated)')
    ap.add_argument('--aisle-start', type=float, help='x (m) where section 0 m starts, e.g. 1.0 for warehouse-v3 walks')
    ap.add_argument('--aisle-length', type=float, help='aisle length (m) so unreached sections still appear, e.g. 18')
    ap.add_argument('--no-pdf', action='store_true')
    a = ap.parse_args()

    run = loaders.load(a.run_dir, a.format)
    if a.aisle_start is not None:
        run['aisle_start_x'] = a.aisle_start
    if a.aisle_length is not None:
        run['aisle_length_m'] = a.aisle_length
    out = Path(a.out) if a.out else Path(a.run_dir) / 'report'
    commit = a.commit
    if not commit:
        r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=HERE, capture_output=True, text=True)
        commit = r.stdout.strip() or None
    summary = render.build(run, out, commit=commit, store=a.store)
    (out / 'summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False) + '\n')
    print(out / 'index.html')
    if a.no_pdf:
        return
    pdf = out / f'CANIS_report_{run["id"]}.pdf'
    r = subprocess.run(['node', str(HERE / 'to_pdf.mjs'), str(out / 'index.html'), str(pdf), f'CANIS-{run["id"]}'],
                       capture_output=True, text=True, env=os.environ)
    if r.returncode:
        (out / 'report_error.txt').write_text(r.stdout + r.stderr)
        sys.exit(f'PDF step failed (HTML is still at {out / "index.html"}): see {out / "report_error.txt"}')
    print(r.stdout.strip())


if __name__ == '__main__':
    main()
