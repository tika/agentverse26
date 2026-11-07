"""Build the stage-2 review MP4 from a tour run (local post-processing, no GPU).

Usage: python perception/stage2_review.py <run_dir> <out.mp4> --sim <path to sim/ with stacking.py>

Per frame it overlays:
- what the camera shows (labelled GROUND-TRUTH REVIEW LABEL, never a perception input);
- a perception-side identity result that uses ONLY the centre depth + camera pose and
  the truth-free runtime asset map (no plate OCR yet, so plates are 'not read');
- the inventory cross-check result.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import asset_map as am  # noqa: E402
import identity as ident  # noqa: E402


def font(size):
    for name in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def centre_point(frame):
    eye, target, depth = frame["eye"], frame["target"], frame.get("depth_center_m")
    if depth is None:
        return None
    f = [t - e for t, e in zip(target, eye)]
    n = math.sqrt(sum(v * v for v in f))
    return tuple(e + v / n * depth for e, v in zip(eye, f))


def describe(result, by_id):
    status, cands = result["status"], result["candidates"]
    names = ", ".join(f"{c} ({by_id[c]['display_id']})" for c in cands if c in by_id)
    if status == "unread" and cands:
        return f"plate not read | position suggests {names} | status: UNREAD (provisional)", (240, 200, 90)
    if status == "ambiguous":
        return f"position fits {len(cands)} drums: {names} | status: AMBIGUOUS", (240, 140, 70)
    if status == "confirmed":
        return f"{names} | status: CONFIRMED", (120, 220, 140)
    return "no drum at image centre", (170, 175, 180)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--sim", type=Path, required=True)
    ap.add_argument("--inventory", type=Path, help="exact rendered inventory.json from the run (preferred)")
    ap.add_argument("--pose-lag", type=int, default=1,
                    help="image i shows camera pose i-lag (measured: frames 0/1 identical, 1 for tour 28bc52f)")
    args = ap.parse_args()
    sys.path.insert(0, str(args.sim))
    import stacking

    manifest = json.loads((args.run / "manifest.json").read_text())
    check = json.loads((args.run / "inventory_check.json").read_text())
    if args.inventory:
        stacked = json.loads(args.inventory.read_text())
        stacked = stacked["drums"] if isinstance(stacked, dict) else stacked
    else:
        stacked = stacking.stack_inventory(json.loads((args.sim / "drums.json").read_text()))
    rmap = am.runtime_view(stacked)
    assert am.map_errors(rmap) == [], am.map_errors(rmap)
    by_id = {d["id"]: d for d in rmap["drums"]}

    big, small = font(26), font(20)
    w, h = manifest["resolution"]
    bar_top, bar_bot = 44, 92
    import av
    args.out.parent.mkdir(parents=True, exist_ok=True)
    log = []
    with av.open(str(args.out), "w") as container:
        stream = container.add_stream("libx264", rate=manifest["fps"])
        stream.width, stream.height, stream.pix_fmt = w, h + bar_top + bar_bot, "yuv420p"
        stream.options = {"crf": "20"}
        frames = manifest["frames"]
        for idx, fr in enumerate(frames):
            pose = frames[max(idx - args.pose_lag, 0)]
            img = Image.open(args.run / "frames" / f"{fr['frame']:05d}.jpg").convert("RGB")
            canvas = Image.new("RGB", (w, h + bar_top + bar_bot), (16, 22, 34))
            canvas.paste(img, (0, bar_top))
            d = ImageDraw.Draw(canvas)
            t = fr["frame"] / manifest["fps"]
            d.text((14, 9), f"STAGE 2 REVIEW | stacked store tour | {t:04.1f}s | review camera only, robot not moving",
                   font=big, fill=(235, 238, 240))
            label = pose["gt_review_label"]
            gt = label.split(":", 1)[1] if label.startswith("plate:") else label.replace("_", " ")
            d.text((14, h + bar_top + 8), f"GROUND-TRUTH REVIEW LABEL (not a perception input): camera aimed toward {gt} (nearest tier, approximate)" if label.startswith("plate:") else f"GROUND-TRUTH REVIEW LABEL (not a perception input): {gt}",
                   font=small, fill=(150, 160, 175))
            if label.startswith("plate:"):
                p = centre_point({**pose, "depth_center_m": fr["depth_center_m"]})
                res = ident.associate(rmap, observed_xyz=p) if p else {"status": "unread", "candidates": []}
                text, colour = describe(res, by_id)
                d.text((14, h + bar_top + 36), "IDENTITY (depth at image centre + asset map): " + text,
                       font=small, fill=colour)
                cx, cy = w // 2, bar_top + h // 2
                d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), outline=colour, width=3)
                log.append({"frame": fr["frame"], "gt": gt, "point": p, "status": res["status"],
                            "candidates": res["candidates"]})
            else:
                inv = "PASS" if check["pass"] else "FAIL"
                d.text((14, h + bar_top + 36),
                       f"INVENTORY CHECK {inv}: {check['usd_drums']} drums in scene = {check['inventory_drums']} in inventory, "
                       f"{check['pallet_decks']} pallets, tiers {check['by_tier']}", font=small,
                       fill=(120, 220, 140) if check["pass"] else (240, 110, 90))
            for packet in stream.encode(av.VideoFrame.from_ndarray(np.asarray(canvas), format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    (args.out.with_suffix(".identity.json")).write_text(json.dumps(log, indent=2))
    agree = sum(1 for r in log if r["candidates"][:1] and by_id[r["candidates"][0]]["display_id"] == r["gt"])
    print(json.dumps({"frames": len(manifest["frames"]), "plate_frames": len(log),
                      "status_counts": {s: sum(r["status"] == s for r in log) for s in ("unread", "ambiguous", "confirmed")},
                      "top_candidate_matches_review_label": agree}))


if __name__ == "__main__":
    main()
