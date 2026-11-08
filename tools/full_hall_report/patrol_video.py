"""Walk video + its inspection report: build the PDF from the run folder, then append the report pages.

    uv run --no-project --with matplotlib --with pillow --with pymupdf \
        python tools/full_hall_report/patrol_video.py out/canis_wh/<RID>/canis_aisle_patrol [--speed 4]

Writes <run>/report/CANIS_report_<run>.pdf, <run>_with_report.mp4 and, with --speed, a sped-up copy where only
the walk is faster and the report pages keep their reading time. Needs ffmpeg and pdflatex (or a shim to tectonic).
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image

HERE = Path(__file__).resolve().parent
BG = (10, 10, 10)


def pages_to_frames(pdf, folder, seconds):
    """Two A4 pages per 1920x1080 frame, shown in order."""
    doc = pymupdf.open(pdf)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        images.append(im.resize((int(im.width * 1040 / im.height), 1040), Image.LANCZOS))
    spreads = []
    for k in range(0, len(images), 2):
        frame = Image.new('RGB', (1920, 1080), BG)
        pair = images[k:k + 2]
        width = sum(im.width for im in pair) + 24 * (len(pair) - 1)
        x = (1920 - width) // 2
        for im in pair:
            frame.paste(im, (x, 20))
            x += im.width + 24
        path = folder / f'spread_{k // 2:02d}.png'
        frame.save(path)
        spreads.append(path)
    listing = folder / 'report.txt'
    listing.write_text(''.join(f"file '{p}'\nduration {seconds}\n" for p in spreads) + f"file '{spreads[-1]}'\n")
    return listing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--speed', type=float, default=0)
    ap.add_argument('--page-seconds', type=float, default=6.0)
    ap.add_argument('--store', default='Warehouse v3, aisle A (simulated)')
    a = ap.parse_args()
    run = Path(a.run_dir).resolve()
    walk = run.with_suffix('.mp4')
    commit = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    subprocess.run([sys.executable, str(HERE / 'pdf/build_pdf_report.py'), str(run), '--drums', str(run / 'drums.json'),
                    '--commit', commit or 'not recorded', '--store', a.store], check=True)
    pdf = run / 'report' / f'CANIS_report_{run.name}.pdf'
    enc = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-r', '24', '-movflags', '+faststart']
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        report = tmp / 'report.mp4'
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i',
                        str(pages_to_frames(pdf, tmp, a.page_seconds)), *enc, str(report)], check=True)
        for speed in [1.0] + ([a.speed] if a.speed and a.speed != 1 else []):
            out = run.parent / (f'{run.name}_with_report.mp4' if speed == 1 else f'{run.name}_{speed:g}x_with_report.mp4')
            subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(walk), '-i', str(report), '-filter_complex',
                            f'[0:v]setpts=PTS/{speed},fps=24,format=yuv420p[w];[1:v]fps=24,format=yuv420p[r];'
                            '[w][r]concat=n=2:v=1:a=0[v]', '-map', '[v]', *enc, str(out)], check=True)
            print(out)
    print(pdf)


if __name__ == '__main__':
    main()
