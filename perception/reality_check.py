"""Reality-check helper (prompt v1.2): frames at real resolution + colour-cast numbers.

Usage:
  python perception/reality_check.py <video.mp4 | image.png ...> --out <dir> [--floor-box x0 y0 x1 y1]

Writes start/mid/end frames, a contact sheet, and report.json with per-channel
means over the whole frame and over a floor region (default: bottom 30% of the
frame, or the given pixel box). F4 asks for grey-floor channel means within
+/-15% of each other; report.json records max/min channel ratio and PASS/FAIL
for that one numeric check. All other F1-F5 items are judged by looking.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def frames_from(paths):
    if len(paths) == 1 and paths[0].suffix.lower() in (".mp4", ".mov", ".mkv"):
        import av
        with av.open(str(paths[0])) as f:
            frames = [fr.to_ndarray(format="rgb24") for fr in f.decode(video=0)]
        n = len(frames)
        picks = sorted({0, n // 2, n - 1})
        return [(f"frame_{i:04d}", frames[i]) for i in picks], n
    return [(p.stem, np.asarray(Image.open(p).convert("RGB"))) for p in paths], len(paths)


def channel_stats(rgb):
    means = rgb.reshape(-1, 3).astype(float).mean(axis=0)
    ratio = float(means.max() / max(means.min(), 1e-6))
    return {"mean_rgb": [round(float(v), 1) for v in means], "max_min_ratio": round(ratio, 3)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--floor-box", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--tolerance", type=float, default=0.15)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    picked, total = frames_from(args.inputs)
    report = {"inputs": [str(p) for p in args.inputs], "frames_in_source": total, "frames": {}}
    worst = 1.0
    for name, rgb in picked:
        h, w, _ = rgb.shape
        x0, y0, x1, y1 = args.floor_box or (0, int(h * 0.7), w, h)
        floor = rgb[y0:y1, x0:x1]
        stats = {"size_px": [w, h], "whole": channel_stats(rgb), "floor_box": [x0, y0, x1, y1],
                 "floor": channel_stats(floor)}
        worst = max(worst, stats["floor"]["max_min_ratio"])
        report["frames"][name] = stats
        Image.fromarray(rgb).save(args.out / f"{name}.png")
    report["f4_floor_channel_balance"] = {"worst_max_min_ratio": round(worst, 3),
                                          "limit": round(1 + args.tolerance, 3),
                                          "pass": worst <= 1 + args.tolerance}
    imgs = [Image.fromarray(rgb) for _, rgb in picked]
    sheet = Image.new("RGB", (max(i.width for i in imgs), sum(i.height for i in imgs)), (0, 0, 0))
    y = 0
    for i in imgs:
        sheet.paste(i, (0, y))
        y += i.height
    sheet.save(args.out / "contact_sheet.png")
    (args.out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report["f4_floor_channel_balance"]), "->", args.out)


if __name__ == "__main__":
    main()
