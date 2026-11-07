"""Build the stage-3 review MP4: one card per scenario close-up (local post-processing).

Usage: python perception/stage3_review.py <run_dir> <scenario_dir> <out.mp4> [--hold 25]

Per scenario frame the card shows, in this order:
  1. what the scene is set up to show (SCENARIO DESIGN, labelled; review only)
  2. sensor channels: last sample with value, units and validity verdict from
     perception/validity.py (bounds and the low-mount hydrogen limitation spelled out)
  3. measured shape (mesh measurement) when the scenario deforms a drum
  4. rule outputs from the runtime block only: findings -> condition status ->
     actions -> priority ranking (0-100, not a probability) with its breakdown
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stage3_assess as sa  # noqa: E402
import validity as va  # noqa: E402
from contracts import CONTRACT_VERSION  # noqa: E402

KIND = {"gamma": "gamma_dose_rate", "hydrogen": "hydrogen", "thermal": "temperature"}
SYMBOL = {"gamma": "GAMMA", "hydrogen": "H2", "thermal": "TEMP"}


def font(size):
    for name in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def to_message(name, sample, channel_cfg, pose):
    """Codex sensor_traces sample -> contract sensor message (fills config fields)."""
    ch = sample["channels"][name]
    m = {"contract_version": CONTRACT_VERSION, "sensor_id": f"robot.{name}", "kind": KIND[name],
         "source": channel_cfg.get("source", "robot"), "timestamp_s": ch["timestamp_s"], "units": ch["units"],
         "value": ch["value"], "pose": {"frame": "world", "xyz_m": list(pose)}, "sample_age_s": ch["age_s"],
         "validity": ch["validity"],
         "uncertainty": {"std": channel_cfg["noise"]} if ch["value"] is not None else {"std": None, "status": "unknown"},
         "status": ch.get("cause", "")}
    if name == "gamma":
        m["saturation_limit"] = channel_cfg["saturation"]
    if name == "hydrogen":
        m["measures"] = ch.get("measures") or channel_cfg.get("measures", "ambient")
        m["detection_limit"] = channel_cfg["detection_limit"]
    return m


def sensor_lines(trace, scenario):
    s = trace["samples"][-1]
    pose = list(s["pose_m"][:2]) + [scenario["runtime"]["channels"]["hydrogen"].get("mount_height_m", s["pose_m"][2])]
    out = []
    for name in ("gamma", "hydrogen", "thermal"):
        cfg = scenario["runtime"]["channels"][name]
        msg = to_message(name, s, cfg, pose)
        v = va.assess(msg, now_s=s["time_s"])
        val = "—" if msg["value"] is None else f"{msg['value']:.2f}"
        if v["bound"] == "upper":
            text = f"{SYMBOL[name]} < {msg.get('detection_limit', cfg['detection_limit'])} {msg['units']} (below detection limit)"
        elif v["bound"] == "lower":
            text = f"{SYMBOL[name]} ≥ {cfg['saturation']} {msg['units']} (saturated)"
        else:
            text = f"{SYMBOL[name]} {val} {msg['units']} ({v['state']})"
        if name == "hydrogen":
            ok, _ = va.absence_claim_allowed(msg, region_z_m=4.5)
            if not ok and v["state"] in ("fresh", "below_detection_limit"):
                text += f", sensor at {pose[2]:.2f} m cannot rule out gas higher up"
        out.append(text)
    return out


def wrap(text, fnt, max_w):
    words, rows, cur = text.split(" "), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            rows.append(cur)
            cur = "   " + wd
    rows.append(cur)
    return rows


def card(img, title, lines, colours, w, h, bar_top, bar_bot):
    canvas = Image.new("RGB", (w, h + bar_top + bar_bot), (16, 22, 34))
    canvas.paste(img, (0, bar_top))
    d = ImageDraw.Draw(canvas)
    d.text((14, 9), title, font=font(24), fill=(235, 238, 240))
    fnt = font(17)
    y = h + bar_top + 6
    for text, colour in zip(lines, colours):
        for row in wrap(text, fnt, w - 28):
            if y > h + bar_top + bar_bot - 20:
                raise ValueError("card text does not fit; increase bar_bot")
            d.text((14, y), row, font=fnt, fill=colour)
            y += 22
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("scenarios", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--hold", type=int, default=25, help="video frames per still (10 fps)")
    args = ap.parse_args()
    manifest = json.loads((args.run / "manifest.json").read_text())
    traces = {t["scenario_id"]: t for t in json.loads((args.run / "sensor_traces.json").read_text())}
    scene = {s["scenario_id"]: s for s in json.loads((args.run / "scene_scenarios.json").read_text())}
    scenarios = {json.loads(p.read_text())["scenario_id"]: json.loads(p.read_text())
                 for p in sorted(args.scenarios.glob("*.json"))}
    w, h = manifest["resolution"] if "resolution" in manifest else (1280, 720)
    bar_top, bar_bot = 42, 236
    grey, white, amber, green, red = (150, 160, 175), (230, 232, 235), (240, 200, 90), (120, 220, 140), (240, 120, 100)
    import av
    log = []
    with av.open(str(args.out), "w") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = w, h + bar_top + bar_bot, "yuv420p"
        stream.options = {"crf": "20"}
        for fr in manifest["frames"]:
            label = fr["label"]
            sid = next((k for k in sorted(scenarios, key=len, reverse=True) if label.startswith(k)), None)
            img = Image.open(args.run / "frames" / f"{fr['frame']:05d}.jpg").convert("RGB").resize((w, h))
            if sid is None:
                lines = ["Overview of the stage-3 hall. Each following card is one scenario close-up (camera only, no robot)."]
                cols = [white]
                title = "STAGE 3 REVIEW | overview"
            else:
                sc = scenarios[sid]
                rep = sa.assess_scenario(sc, traces.get(sid))  # measured channels (REALITY CHECK 3.2)
                view = label[len(sid):].strip("_").replace("_", " ") or "drum close-up"
                title = f"STAGE 3 REVIEW | {sid.replace('_', ' ')} | {view}"
                design = "SCENARIO DESIGN (review label, not a perception input): " + ", ".join(sc["case_tags"])
                causes = [c.get("cause") for c in sc["runtime"]["channels"].values() if c.get("anomaly")]
                if causes:
                    design += " — cause: " + "; ".join(causes)
                lines, cols = [design], [grey]
                if sid in traces:
                    lines.append("SENSORS: " + " | ".join(sensor_lines(traces[sid], sc)))
                    cols.append(white)
                shape = (scene.get(sid, {}) or {}).get("measured_shape") or {}
                for drum, m in shape.items():
                    key = "observed_dent_depth_m" if m["kind"] == "dent" else "observed_diameter_increase_m"
                    lines.append(f"SHAPE ({m['measurement_source']}): {drum} {m['kind']} "
                                 f"{m[key]*1000:.1f} mm on {m['nominal_diameter_m']*1000:.0f} mm drum — "
                                 "a shape change only; does not establish pressure or hydrogen")
                    cols.append(white)
                hyps = ", ".join(f["hypothesis"].replace("_", " ") for f in rep["findings"]) or "none"
                lines.append(f"RULES: findings: {hyps} → {rep['condition_status'].replace('_', ' ')} → "
                             f"actions: {', '.join(a.replace('_', ' ') for a in rep['actions'])}")
                cols.append(red if "stand_off_and_alert" in rep["actions"] or
                            "mark_area_avoid_tracking_and_alert" in rep["actions"] else amber if rep["findings"] else green)
                pr = rep["priority"]
                lines.append(f"PRIORITY {pr['index']:.0f}/100 (ranking, not a probability): {pr['explanation']}")
                cols.append(white)
                log.append({"frame": fr["frame"], "scenario": sid, "lines": lines})
            canvas = card(img, title, lines, cols, w, h, bar_top, bar_bot)
            frame = av.VideoFrame.from_ndarray(np.asarray(canvas), format="rgb24")
            for _ in range(args.hold):
                for packet in stream.encode(frame):
                    container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    args.out.with_suffix(".cards.json").write_text(json.dumps(log, indent=2))
    print(json.dumps({"stills": len(manifest["frames"]), "video_frames": len(manifest["frames"]) * args.hold,
                      "seconds": len(manifest["frames"]) * args.hold / 10}))


if __name__ == "__main__":
    main()
