"""Stage-3 inspection-priority index (owner: Claude Code; review: Codex).

A 0-100 RANKING score for choosing what to inspect next. It is not a probability of
failure, rupture or release, and is never displayed as a percentage. Every point is
explained in a breakdown. Weights are synthetic demonstration settings.

Components (points):
  severity     0-45  strongest supported hypothesis (evidence.HYPOTHESES weight x 45)
  uncertainty  0-25  single-view visual findings, low coverage, unknown identity
  recency      0-15  time since the drum was last observed (unknown = max)
  safety       0-15  gas/thermal/contamination hypotheses (these also trigger stand-off)
  exposure    -15-0  cost of the dose needed to get a better view (simulated budget)
"""
from evidence import HYPOTHESES, SAFETY_HYPOTHESES

PRIORITY_VERSION = "1.0.0"
WEIGHTS = {"severity": 45, "uncertainty": 25, "recency": 15, "safety": 15, "exposure": 15}
RECENCY_FULL_S = 600.0   # synthetic: 10 min since last view gives full recency points


def priority(findings, *, coverage_fraction, identity_status, last_seen_age_s,
             expected_dose_uSv=0.0, remaining_budget_uSv=None):
    b = {}
    sev = max((HYPOTHESES[f["hypothesis"]][0] for f in findings), default=0.0)
    b["severity"] = round(WEIGHTS["severity"] * sev, 1)

    u = 0.0
    if any(HYPOTHESES[f["hypothesis"]][1] and f["distinct_views"] < 2 for f in findings):
        u += 0.5          # needs a second view
    if coverage_fraction is None or coverage_fraction < 0.25:
        u += 0.3          # most of the drum unseen: unknown, not 'fine'
    if identity_status in ("ambiguous", "conflict", "unread"):
        u += 0.2
    b["uncertainty"] = round(WEIGHTS["uncertainty"] * min(u, 1.0), 1)

    age = RECENCY_FULL_S if last_seen_age_s is None else min(max(last_seen_age_s, 0.0), RECENCY_FULL_S)
    b["recency"] = round(WEIGHTS["recency"] * age / RECENCY_FULL_S, 1)

    b["safety"] = WEIGHTS["safety"] if any(f["hypothesis"] in SAFETY_HYPOTHESES | {"surface_contamination"}
                                           for f in findings) else 0.0

    if remaining_budget_uSv is None or remaining_budget_uSv <= 0:
        frac = 1.0 if expected_dose_uSv > 0 else 0.0
    else:
        frac = min(expected_dose_uSv / remaining_budget_uSv, 1.0)
    b["exposure"] = round(-WEIGHTS["exposure"] * frac, 1)

    index = max(0.0, min(100.0, sum(b.values())))
    return {"kind": "ranking_score", "version": PRIORITY_VERSION, "index": round(index, 1),
            "breakdown": b, "not_a_probability": True,
            "explanation": explain(b, findings)}


def explain(b, findings):
    parts = []
    if findings:
        top = max(findings, key=lambda f: HYPOTHESES[f["hypothesis"]][0])["hypothesis"].replace("_", " ")
        parts.append(f"{top} (+{b['severity']})")
    if b["uncertainty"]:
        parts.append(f"uncertainty (+{b['uncertainty']})")
    if b["recency"]:
        parts.append(f"not seen recently (+{b['recency']})")
    if b["safety"]:
        parts.append(f"safety channel (+{b['safety']}; stand-off applies)")
    if b["exposure"]:
        parts.append(f"dose cost ({b['exposure']})")
    return "; ".join(parts) or "no findings, recently seen"
