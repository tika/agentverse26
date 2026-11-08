"""CANIS vs Autowalk-style baselines: evaluation harness with the REAL YOLO26s test rates.

Same robot, same hall, same faults, same surprises, same detector draws in every paired walk.
Only the decision logic differs.

  Baseline A (Autowalk-style, strict): fixed recorded route, one photo per drum. A confident
      flag is recorded as a defect, an unsure one goes to a human, and the mission stops at a
      blocked aisle. Not dose-aware.
  Baseline B (Autowalk-style, re-routing): the same, but it walks around a blocked aisle
      (real Spot can step around obstacles). This is the fair, HEADLINE comparison.
  CANIS: the same first photo, then up to two extra looks when unsure, a dose budget
      (backs off from spikes and returns), re-routes around a blocked aisle, and says
      "Couldn't inspect" instead of guessing.

Detector model, per look (run compare_colors_20261108T053740Z_continued, cut-off 0.25):
  Faults: 233/265 held-out test images classified correctly, used for both rust and bulge.
  Flagged rust views, sure vs unsure, from the final showcase run: 18 at conf >= 0.50, 1 at 0.25-0.50.
  Clean drums, from the showcase's 75 first-look views: rust 0.25-0.50: 2/75, >= 0.50: 0/75; bulge >= 0.25: 1/75.
  No unsure band is measured for bulges, so a bulge look is caught / not caught.
The headline cut-off is 0.25: a look at >= 0.25 means "found". The 0.50 level splits a confident
flag from an unsure one.

Usage: .venv/bin/python eval/canis_eval.py --walks 2000 --boot 10000 --seed 20261108
"""
import argparse, json, math, os
import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
DRUMS = os.path.join(HERE, "source", "drums_36.json")
OUT = os.path.join(HERE, "results")

# ---------- world: aisle A of warehouse-v3, the 36 drums in the final showcase run ----------
AISLE_Y = {1: 4.83}
SPEED, DWELL, CLOSE_DWELL = 0.8, 10.0, 20.0
BACKGROUND, HUMAN_CHECK_S = 0.05, 300.0
P_DEFECT, P_BULGE = 0.30, 0.35
P_HOTSPOT, P_BLOCKED = 0.5, 0.3
SPIKE = 3.0

# ---------- detector: measured rates ----------
REAL = dict(
    # compare_colors_20261108T053740Z_continued: 233/265 held-out photos correct at conf 0.25.
    # Sure/unsure split and clean-drum rates: first looks in the final showcase run.
    rust_hi=(233 / 265) * (18 / 19), rust_mid=(233 / 265) * (1 / 19),   # rusty drum: P(conf>=0.5), P(0.25<=conf<0.5)
    clean_hi=0 / 75, clean_mid=2 / 75,            # clean drum, rust false alarm
    bulge_hit=233 / 265, bulge_false=1 / 75,      # bulge caught / false bulge per look
)


def load_drums():
    d = json.load(open(DRUMS))
    return [dict(id=r["id"], cat=r["category"], x=r["x"], y=r["y"], aisle=r["facing_aisle"],
                 S=float(r["source_strength"])) for r in d]


def dose_rate(px, py, drums, hotspot, t):
    r = BACKGROUND
    for d in drums:
        r += d["S"] / max((px - d["x"]) ** 2 + (py - d["y"]) ** 2, 0.25)
    if hotspot and hotspot["t0"] <= t < hotspot["t1"]:
        r += hotspot["S"] / max((px - hotspot["x"]) ** 2 + (py - hotspot["y"]) ** 2, 0.25)
    return r


def make_episode(rng, drums):
    ep = []
    for d in drums:
        bad = rng.random() < P_DEFECT
        kind = ("bulge" if rng.random() < P_BULGE else "rust") if bad else None
        ep.append(dict(d, kind=kind))
    ilw = [d for d in drums if d["cat"] == "ILW"]
    h = ilw[rng.integers(len(ilw))]
    hot = dict(x=h["x"], y=AISLE_Y[h["aisle"]], S=400.0, t0=rng.uniform(60, 600))
    hot["t1"] = hot["t0"] + 480
    if rng.random() > P_HOTSPOT:
        hot["t0"] = hot["t1"] = -1.0
    bl = dict(aisle=1)
    bl["xmin"], bl["xmax"] = (5.0, 6.5) if rng.random() < 0.5 else (13.0, 15.0)
    if rng.random() > P_BLOCKED:
        bl["aisle"] = -1
    return ep, hot, bl


def route(drums):
    order = []
    for a, rev in ((1, False),):
        order += sorted([d for d in drums if d["aisle"] == a], key=lambda d: d["x"], reverse=rev)
    return order


def is_blocked(bl, aisle, x0, x1):
    if aisle != bl["aisle"]:
        return False
    lo, hi = min(x0, x1), max(x0, x1)
    return not (hi < bl["xmin"] or lo > bl["xmax"])


class Robot:
    def __init__(self, drums, hot):
        self.x, self.y, self.t, self.dose, self.drums, self.hot = 1.0, 6.0, 0.0, 0.0, drums, hot

    def rate(self, x=None, y=None):
        return dose_rate(self.x if x is None else x, self.y if y is None else y, self.drums, self.hot, self.t)

    def walk(self, x, y, extra=0.0):
        dist = math.hypot(x - self.x, y - self.y) + extra
        n = max(1, int(dist / 0.5))
        for i in range(n):
            f = (i + 0.5) / n
            px, py = self.x + f * (x - self.x), self.y + f * (y - self.y)
            self.dose += dose_rate(px, py, self.drums, self.hot, self.t) * (dist / SPEED / n) / 3600
            self.t += dist / SPEED / n
        self.x, self.y = x, y

    def stay(self, s):
        self.dose += self.rate() * s / 3600
        self.t += s


class Eyes:
    """Pre-drawn detector outcomes per drum and look, shared by all robots in a walk (paired)."""

    def __init__(self, rng, ep, det, corr):
        self.u = {d["id"]: rng.random(3) for d in ep}
        self.det, self.corr = det, corr
        self.kind = {d["id"]: d["kind"] for d in ep}

    def look(self, did, k):
        """Band of look k (0 = first): 'hi' confident flag, 'mid' unsure flag, 'lo' nothing."""
        u, kind, D = self.u[did][k], self.kind[did], self.det
        if kind == "bulge":
            p = D["bulge_hit"] * (self.corr if k else 1.0)
            return "hi" if u < p else "lo"
        if kind == "rust":
            hi = D["rust_hi"] * (self.corr if k else 1.0)
            mid = D["rust_mid"]
            return "hi" if u < hi else ("mid" if u < hi + mid else "lo")
        # clean drum: rust false alarm or bulge false alarm
        if u < D["clean_hi"]:
            return "hi"
        if u < D["clean_hi"] + D["clean_mid"]:
            return "mid"
        return "hi" if u > 1 - D["bulge_false"] else "lo"


def verdict(band):
    return {"hi": "Confirmed defect", "mid": "Suspect", "lo": "OK"}[band]


def run_baseline(ep, hot, bl, eyes, budget, reroute):
    rob, out = Robot(ep, hot), {}
    for d in route(ep):
        sx, sy = d["x"], AISLE_Y[d["aisle"]]
        detour = 0.0
        if is_blocked(bl, d["aisle"], rob.x, sx):
            if not reroute:
                break                      # recorded route blocked: mission stops, operator needed
            detour = 10.0                  # walk round via the cross aisle
        rob.walk(sx, sy, extra=detour)
        rob.stay(DWELL)
        out[d["id"]] = verdict(eyes.look(d["id"], 0))
    return finish(ep, out, rob, budget)


def run_canis(ep, hot, bl, eyes, budget):
    rob, out, flagged = Robot(ep, hot), {}, set()
    todo, deferred = list(route(ep)), []
    while todo or deferred:
        if not todo:
            if hot["t0"] <= rob.t < hot["t1"]:
                rob.walk(1.0, 6.0)
                rob.stay(min(60.0, max(hot["t1"] - rob.t, 1.0)))
                continue
            todo, deferred = deferred, []
        if rob.rate() > SPIKE * dose_rate(rob.x, rob.y, ep, None, 0):
            rob.walk(1.0, 6.0)
        d = todo.pop(0)
        sx, sy = d["x"], AISLE_Y[d["aisle"]]
        if rob.rate(sx, sy) > SPIKE * dose_rate(sx, sy, ep, None, 0):
            deferred.append(d)
            continue
        detour = 10.0 if is_blocked(bl, d["aisle"], rob.x, sx) else 0.0
        est = rob.rate(sx, sy) * (DWELL + (math.hypot(sx - rob.x, sy - rob.y) + detour + 12) / SPEED) / 3600
        if rob.dose + est > budget:
            for r in [d] + todo + deferred:
                out[r["id"]] = "Couldn't inspect"
            break
        rob.walk(sx, sy, extra=detour)
        rob.stay(DWELL)
        band = eyes.look(d["id"], 0)
        status, clear = verdict(band), 0
        k = 1
        while status == "Suspect" and k < 3:       # second look (closer), then a side view
            near = 0.9 if k == 1 else 1.2
            ny = d["y"] + (sy - d["y"]) * near / abs(sy - d["y"])
            if rob.dose + rob.rate(d["x"], ny) * CLOSE_DWELL / 3600 > 0.9 * budget:
                break                                # never spend the reserve
            rob.walk(d["x"], ny)
            rob.stay(CLOSE_DWELL)
            b = eyes.look(d["id"], k)
            if b == "hi":
                status = "Confirmed defect"
            elif b == "lo":
                clear += 1
                if clear == 2:                       # two clear extra looks: OK
                    status = "OK"
            k += 1
        if status == "Suspect":                       # still unsure after the extra looks:
            status = "Couldn't inspect"               # report it as flagged, for a human
            flagged.add(d["id"])
        out[d["id"]] = status
    return finish(ep, out, rob, budget, flagged)


def finish(ep, out, rob, budget, flagged=()):
    rows, m = [], dict(defects=0, found=0, settled=0, false_alarm=0, human=0, human_dose=0.0,
                       robot_dose=rob.dose, minutes=rob.t / 60, over=rob.dose > budget,
                       aborted=len(out) < len(ep), n=len(ep))
    for d in ep:
        s = out.get(d["id"])
        bad = d["kind"] is not None
        # found = reported as a defect, or flagged (a look at >= 0.25) and handed to a human
        found = s in ("Confirmed defect", "Suspect") or d["id"] in flagged
        needs_human = s in (None, "Suspect", "Couldn't inspect")
        if bad:
            m["defects"] += 1
            m["found"] += found
            m["settled"] += s == "Confirmed defect"
        elif s == "Confirmed defect":
            m["false_alarm"] += 1
        if needs_human:
            m["human"] += 1
            m["human_dose"] += dose_rate(d["x"], d["y"] + 1.0, ep, None, 0) * HUMAN_CHECK_S / 3600
        rows.append(dict(id=d["id"], kind=d["kind"], status=s or "Not reached", found=found))
    return m, rows


def simulate(walks, seed, det=REAL, corr=1.0):
    rng = np.random.default_rng(seed)
    drums = load_drums()
    probe = Robot([dict(d, kind=None) for d in drums], None)
    for d in route(drums):
        probe.walk(d["x"], AISLE_Y[d["aisle"]]); probe.stay(DWELL)
    budget = 3.0 * probe.dose
    res = {k: [] for k in ("A", "B", "CANIS")}
    per_drum = []
    for w in range(walks):
        ep, hot, bl = make_episode(rng, drums)
        eyes = Eyes(rng, ep, det, corr)
        ra = run_baseline(ep, hot, bl, eyes, budget, reroute=False)
        rb = run_baseline(ep, hot, bl, eyes, budget, reroute=True)
        rc = run_canis(ep, hot, bl, eyes, budget)
        for k, r in zip(("A", "B", "CANIS"), (ra, rb, rc)):
            res[k].append(r[0])
        for a, b, c in zip(ra[1], rb[1], rc[1]):
            per_drum.append(dict(walk=w, id=a["id"], kind=a["kind"], A=a["status"], B=b["status"],
                                 CANIS=c["status"], A_found=a["found"], B_found=b["found"], C_found=c["found"]))
    return res, per_drum, budget


# ---------- statistics ----------
METRICS = [  # name, per-walk numerator, per-walk denominator (None = mean per walk), unit
    ("Defects found", "found", "defects", "%"),
    ("Defects settled by the robot (no human)", "settled", "defects", "%"),
    ("Human follow-up entries per walk", "human", None, "entries"),
    ("Human dose from follow-ups per walk", "human_dose", None, "sim units"),
    ("Robot dose per walk", "robot_dose", None, "sim units"),
    ("False alarms per walk", "false_alarm", None, "drums"),
    ("Walks over the dose budget", "over", None, "%"),
    ("Missions stopped by a blocked aisle", "aborted", None, "%"),
    ("Mission time", "minutes", None, "min"),
]


def arr(res, k, f):
    return np.array([float(m[f]) for m in res[k]])


def stat(res, k, num, den, idx=None):
    x = arr(res, k, num)
    if idx is None:
        idx = np.arange(len(x))[None, :]
    if den is None:
        v = x[idx].mean(1)
        return v * (100 if num in ("over", "aborted") else 1)
    return 100 * x[idx].sum(1) / arr(res, k, den)[idx].sum(1)


def analyse(res, per_drum, boot, seed):
    rng = np.random.default_rng(seed + 1)
    W = len(res["A"])
    idx = rng.integers(0, W, size=(boot, W))       # resample whole walks, keeps each pair together
    table = []
    for name, num, den, unit in METRICS:
        row = dict(metric=name, unit=unit)
        for k in ("A", "B", "CANIS"):
            pt = float(stat(res, k, num, den)[0])
            bs = stat(res, k, num, den, idx)
            row[k] = [pt, *np.percentile(bs, [2.5, 97.5]).tolist()]
        for base in ("A", "B"):
            pt = float(stat(res, "CANIS", num, den)[0] - stat(res, base, num, den)[0])
            bs = stat(res, "CANIS", num, den, idx) - stat(res, base, num, den, idx)
            row[f"diff_vs_{base}"] = dict(point=pt, ci95=np.percentile(bs, [2.5, 97.5]).tolist(),
                                          ci99=np.percentile(bs, [0.5, 99.5]).tolist())
        table.append(row)

    tests = []
    bad = [r for r in per_drum if r["kind"] is not None]
    mcn = {}
    for base, col in (("A", "A_found"), ("B", "B_found")):
        both = sum(r[col] and r["C_found"] for r in bad)
        only_c = sum((not r[col]) and r["C_found"] for r in bad)
        only_b = sum(r[col] and not r["C_found"] for r in bad)
        neither = sum((not r[col]) and not r["C_found"] for r in bad)
        p = stats.binomtest(only_c, only_c + only_b, 0.5).pvalue if only_c + only_b else 1.0
        mcn[base] = dict(both=both, only_canis=only_c, only_baseline=only_b, neither=neither, p=p)
        tests.append((f"McNemar, defects found, CANIS vs {base}", p))
        # settled by robot (Confirmed) per defective drum
        s_c = sum(r["CANIS"] == "Confirmed defect" and r[base] != "Confirmed defect" for r in bad)
        s_b = sum(r[base] == "Confirmed defect" and r["CANIS"] != "Confirmed defect" for r in bad)
        p2 = stats.binomtest(s_c, s_c + s_b, 0.5).pvalue if s_c + s_b else 1.0
        mcn[base + "_settled"] = dict(only_canis=s_c, only_baseline=s_b, p=p2)
        tests.append((f"McNemar, defects settled by robot, CANIS vs {base}", p2))
        for f, label in (("human", "human entries"), ("human_dose", "human dose"),
                         ("robot_dose", "robot dose"), ("minutes", "mission time")):
            dlt = arr(res, "CANIS", f) - arr(res, base, f)
            p3 = stats.wilcoxon(dlt).pvalue if np.any(dlt != 0) else 1.0
            tests.append((f"Wilcoxon signed-rank, {label}, CANIS vs {base}", p3))
    # Holm-Bonferroni
    order = np.argsort([p for _, p in tests])
    m, holm, running = len(tests), [None] * len(tests), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * tests[i][1]))
        holm[i] = running
    tests = [dict(test=t, p=p, p_holm=h, survives_holm=h < 0.05) for (t, p), h in zip(tests, holm)]
    return table, mcn, tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--walks", type=int, default=2000)
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20261108)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    runs = {
        "main": dict(det=REAL, corr=1.0, note="Measured YOLO26s rates, cut-off 0.25, extra looks independent"),
        "correlated_looks": dict(det=REAL, corr=0.5, note="Extra looks half as likely to give a confident flag (views of one drum are correlated)"),
        "worse_eyes": dict(det=dict(REAL, rust_hi=REAL["rust_hi"] * 0.8, rust_mid=REAL["rust_mid"] * 0.8,
                                    bulge_hit=REAL["bulge_hit"] * 0.8), corr=1.0,
                           note="Every catch rate 20% lower"),
        "both_worse": dict(det=dict(REAL, rust_hi=REAL["rust_hi"] * 0.8, rust_mid=REAL["rust_mid"] * 0.8,
                                    bulge_hit=REAL["bulge_hit"] * 0.8), corr=0.5,
                           note="20% lower catch rates AND correlated looks"),
    }
    summary = dict(walks=a.walks, boot=a.boot, seed=a.seed, detector_rates=REAL, runs={})
    for name, cfg in runs.items():
        res, per_drum, budget = simulate(a.walks, a.seed, cfg["det"], cfg["corr"])
        table, mcn, tests = analyse(res, per_drum, a.boot if name == "main" else 2000, a.seed)
        summary["runs"][name] = dict(note=cfg["note"], budget=budget, table=table, mcnemar=mcn, tests=tests)
        if name == "main":
            import csv
            with open(os.path.join(OUT, "per_walk.csv"), "w", newline="") as f:
                w = csv.writer(f)
                keys = list(res["A"][0].keys())
                w.writerow(["walk", "robot"] + keys)
                for k in ("A", "B", "CANIS"):
                    for i, m in enumerate(res[k]):
                        w.writerow([i, k] + [m[x] for x in keys])
            with open(os.path.join(OUT, "per_drum.csv"), "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(per_drum[0].keys()))
                w.writeheader(); w.writerows(per_drum)
        print(f"\n=== {name}: {cfg['note']}")
        for r in table:
            d = r["diff_vs_B"]
            print(f"{r['metric']:42s} A {r['A'][0]:7.2f}  B {r['B'][0]:7.2f}  CANIS {r['CANIS'][0]:7.2f} | "
                  f"C-B {d['point']:+7.2f} 95% [{d['ci95'][0]:+.2f},{d['ci95'][1]:+.2f}] 99% [{d['ci99'][0]:+.2f},{d['ci99'][1]:+.2f}]")
        for k, v in mcn.items():
            print("McNemar", k, v)
    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, default=float)


if __name__ == "__main__":
    main()
