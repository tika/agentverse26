"""Independent check of a stage take: dose stream vs contract/oracle + video decode.

Usage: python perception/check_take.py <run_dir> <frames_out_dir>   (needs numpy, av)
"""
import json, sys, math
from pathlib import Path
RUN = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contracts as c
from sim_adapter import gamma_messages
ev = [json.loads(l) for l in (RUN / "spot-radiation/radiation/events.jsonl").read_text().splitlines() if l.strip()]
kinds = {}
for e in ev: kinds[e["event"]] = kinds.get(e["event"], 0) + 1
print("events:", kinds)
ds = [e for e in ev if e["event"] == "dose_sample"]
R, C, errs = [], [], []
for e in ds:
    r, cu = gamma_messages(e)
    R.append(r); C.append(cu)
    errs += c.sensor_message_errors(r) + c.sensor_message_errors(cu)
print("contract errors:", errs[:5] or "none")
print("oracle (trapezoid):", c.dose_stream_errors(R, C, rel_tol=1e-9) or "conforms")
# Recompute with prompt's left-rectangle to show the method difference.
lr = c.integrate_dose_uSv([(r["timestamp_s"], r["value"]) for r in R if r["validity"] == "valid"])[-1]
print(f"final cumulative published {C[-1]['value']:.6f} uSv | left-rect recompute {lr:.6f} uSv | complete={C[-1]['complete']}")
ts = [e["time_s"] for e in ds]; dts = [b - a for a, b in zip(ts, ts[1:])]
print(f"samples {len(ds)} frames {ds[0]['frame']}..{ds[-1]['frame']} gaps_in_frame_idx={sum(1 for a,b in zip(ds,ds[1:]) if b['frame']-a['frame']!=1)}")
print(f"dt min {min(dts):.3f} max {max(dts):.3f} s; span {ts[-1]-ts[0]:.3f} s")
print("camera ts == dose ts:", all(math.isclose(e["camera"]["timestamp_s"], e["gamma"]["timestamp_s"], abs_tol=1e-6) for e in ds))
print("validity:", "".join({"valid": ".", "failed": "F", "saturated": "S"}[r["validity"]] for r in R))
peak = max(R, key=lambda r: r["value"] or 0); print(f"peak {peak['value']:.2f} uSv/h at t={peak['timestamp_s']}")
for e in ev:
    if e["event"] != "dose_sample": print("non-sample event:", json.dumps(e)[:300])
st = [e.get("status") for e in ds]; print("status transitions:", [(ds[i]['time_s'], st[i-1], st[i]) for i in range(1, len(st)) if st[i] != st[i-1]])
import av
with av.open(str(RUN / "stage1-review.mp4")) as f:
    s = f.streams.video[0]
    print(f"video codec={s.codec_context.name} {s.codec_context.width}x{s.codec_context.height} fps={s.average_rate} pix={s.codec_context.pix_fmt} dur={float(f.duration or 0)/1e6:.2f}s")
    pts, n = [], 0
    picks = None
    frames = []
    for fr in f.decode(video=0):
        pts.append(fr.pts); frames.append(fr); n += 1
    print("decoded frames:", n, "pts monotonic:", all(b > a for a, b in zip(pts, pts[1:])))
    for i in sorted({0, n // 4, n // 2, 3 * n // 4, n - 1}):
        frames[i].to_image().save(OUT / f"frame_{i:03d}.png")
    import numpy as np
    means = [float(np.asarray(fr.to_ndarray(format="gray")).mean()) for fr in frames]
    print(f"luma mean min {min(means):.1f} max {max(means):.1f}; black frames(<5): {sum(m < 5 for m in means)}")
    diffs = [float(np.abs(frames[i].to_ndarray(format='gray').astype(int) - frames[i-1].to_ndarray(format='gray').astype(int)).mean()) for i in range(1, n)]
    print(f"frame-to-frame mean abs diff: max {max(diffs):.1f}, frozen(<0.05): {sum(d < 0.05 for d in diffs)}")
