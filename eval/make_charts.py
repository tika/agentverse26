"""Draws the evaluation charts (PNG, for GitHub) from eval/results/summary.json."""
import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
S = json.load(open(os.path.join(R, "summary.json")))
main = {r["metric"]: r for r in S["runs"]["main"]["table"]}
ROB = [("A", "Autowalk-style A\n(stops if blocked)", "#9aa3ad"), ("B", "Autowalk-style B\n(re-routes)", "#5f6b78"),
       ("CANIS", "CANIS", "#76b900")]
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})


def bars(ax, metric, ylabel):
    r = main[metric]
    for i, (k, lab, col) in enumerate(ROB):
        m, lo, hi = r[k]
        ax.bar(i, m, color=col, width=0.6)
        ax.errorbar(i, m, yerr=[[m - lo], [hi - m]], color="black", capsize=4, lw=1)
        ax.text(i, hi, f"{m:.1f}" if m < 20 else f"{m:.0f}%", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(range(3), [l for _, l, _ in ROB], fontsize=8)
    ax.set_ylabel(ylabel)


fig, axs = plt.subplots(1, 2, figsize=(9, 3.6))
bars(axs[0], "Defects found", "Faulty drums found (%)"); axs[0].set_ylim(0, 105); axs[0].set_title("Found (flagged at conf ≥ 0.25)")
bars(axs[1], "Defects settled by the robot (no human)", "Faulty drums settled by robot (%)"); axs[1].set_ylim(0, 105)
axs[1].set_title("Settled by the robot, no human visit")
fig.suptitle("Same detector, so the same drums are found; CANIS settles far more of them itself", fontsize=10)
fig.tight_layout(); fig.savefig(os.path.join(R, "defects.png"), dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(5, 3.6))
bars(ax, "Human follow-up entries per walk", "Human entries per walk")
ax.set_title("Times a person must enter the hall (per walk)")
fig.tight_layout(); fig.savefig(os.path.join(R, "human_entries.png"), dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(5.4, 3.8))
h, rd = main["Human dose from follow-ups per walk"], main["Robot dose per walk"]
for k, lab, col in ROB:
    ax.errorbar(rd[k][0], h[k][0], xerr=[[rd[k][0] - rd[k][1]], [rd[k][2] - rd[k][0]]],
                yerr=[[h[k][0] - h[k][1]], [h[k][2] - h[k][0]]], fmt="o", color=col, capsize=3, ms=8)
    ax.annotate(lab.replace("\n", " "), (rd[k][0], h[k][0]), textcoords="offset points", xytext=(8, 4), fontsize=8)
ax.set_xlabel("Robot dose per walk (sim units)"); ax.set_ylabel("Human dose per walk (sim units)")
ax.set_xlim(2.0, 3.2); ax.set_ylim(0, 16)
ax.set_title("Dose trade-off: lower is better on both axes")
fig.tight_layout(); fig.savefig(os.path.join(R, "dose_tradeoff.png"), dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(6.4, 3.4))
names = {"main": "Measured detector", "correlated_looks": "Correlated extra looks",
         "worse_eyes": "Catch rates 20% lower", "both_worse": "Both"}
for i, (k, lab) in enumerate(names.items()):
    t = {r["metric"]: r for r in S["runs"][k]["table"]}["Defects settled by the robot (no human)"]["diff_vs_B"]
    ax.errorbar(t["point"], i, xerr=[[t["point"] - t["ci95"][0]], [t["ci95"][1] - t["point"]]], fmt="o",
                color="#76b900", capsize=4)
    ax.text(t["point"], i + 0.18, f"+{t['point']:.1f}", ha="center", fontsize=8)
ax.axvline(0, color="grey", lw=1)
ax.set_yticks(range(4), list(names.values())); ax.invert_yaxis(); ax.set_xlim(-2, 26)
ax.set_xlabel("CANIS minus Autowalk-style B: defects settled by robot (percentage points, 95% CI)")
ax.set_title("Sensitivity check: CANIS still wins under worse assumptions", fontsize=10)
fig.tight_layout(); fig.savefig(os.path.join(R, "sensitivity.png"), dpi=150); plt.close(fig)
print("charts written")
