"""Run the stage-3 rules on a scenario's RUNTIME observations (never its truth block).

Usage: python perception/stage3_assess.py sim/scenarios/*.json [--out report.json]

For each scenario it builds evidence from runtime defects (as camera/depth observations
would report them) and from channel readings, then reports findings, condition status,
actions and the priority ranking. Output feeds the stage-3 overlay and REALITY CHECK 3.2.
Readings here are the scenario's declared anomaly levels; live sensor traces replace
them when Codex's capture provides contract messages.
"""
import argparse
import json
from pathlib import Path

import evidence as ev
import priority as pr

DEFECT_TO_KIND = {"corrosion": "visual_corrosion", "residue": "visual_wet_or_residue",
                  "wet": "visual_wet_or_residue", "bulge": "depth_deformation", "dent": "depth_deformation"}
CHANNEL_TO_KIND = {"gamma": "dose_rate_level", "hydrogen": "hydrogen_ambient", "thermal": "thermal_surface"}


def assess_scenario(sc):
    runtime = sc["runtime"]  # truth is deliberately not read
    drum = runtime.get("asset_id") or sc.get("asset_id") or "unknown"
    area = runtime.get("area", "scenario_area")
    evs, notes = [], []
    for i, d in enumerate(runtime.get("defects", [])):
        kind = DEFECT_TO_KIND.get(d.get("kind"))
        if kind is None:
            notes.append(f"defect kind {d.get('kind')!r} has no evidence mapping")
            continue
        if d.get("visible_fraction", 0) <= 0:
            notes.append(f"{d.get('kind')} not visible: no camera evidence (stays hidden)")
            continue
        evs.append(ev.make_evidence(kind, value=d.get("severity", 1), units="severity", t_s=0,
                                    drum_ids=[drum], view_id="view-1", note=d.get("surface_region", "")))
    wet = runtime.get("wet_case")
    if wet:
        evs.append(ev.make_evidence("visual_wet_or_residue", value=1, units="detections", t_s=0,
                                    area=area, note=f"mechanism: {wet.get('mechanism')}"))
    for name, ch in runtime.get("channels", {}).items():
        if ch.get("enabled") and ch.get("anomaly"):
            evs.append(ev.make_evidence(CHANNEL_TO_KIND[name], value=ch.get("anomaly_level", 1),
                                        units=ch["units"], t_s=0, area=area, note=f"cause: {ch.get('cause')}"))
    findings = ev.findings_for(evs)
    coverage = runtime.get("coverage_fraction", 0.35)
    status = ev.condition_status(findings, coverage)
    rank = pr.priority(findings, coverage_fraction=coverage, identity_status=runtime.get("identity_status", "unread"),
                       last_seen_age_s=0)
    return {"scenario_id": sc["scenario_id"], "case_tags": sc["case_tags"], "asset_id": drum,
            "evidence": [{k: e[k] for k in ("id", "kind", "value", "units", "note", "cannot_establish")} for e in evs],
            "findings": [{k: f[k] for k in ("hypothesis", "evidence_ids", "distinct_views")} for f in findings],
            "condition_status": status, "actions": ev.actions_for(findings, coverage),
            "priority": rank, "notes": notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    reports = [assess_scenario(json.loads(p.read_text())) for p in args.files]
    text = json.dumps(reports, indent=2)
    if args.out:
        args.out.write_text(text)
    for r in reports:
        hyps = ", ".join(f["hypothesis"] for f in r["findings"]) or "none"
        print(f"{r['scenario_id']:<28} {r['condition_status']:<38} priority {r['priority']['index']:>5}  "
              f"findings: {hyps}  actions: {', '.join(r['actions'])}")


if __name__ == "__main__":
    main()
