"""Run the stage-3 rules on a scenario's RUNTIME observations (never its truth block).

Usage: python perception/stage3_assess.py sim/scenarios/*.json --traces <run>/sensor_traces.json [--out r.json]

With --traces (the normal path), gamma/hydrogen/thermal evidence comes ONLY from the
captured sensor samples: each sample -> contract message -> validity.assess -> stated
synthetic threshold. Scenario 'anomaly' flags are ignored. Camera/depth evidence still
comes from the scenario's visible defects, labelled 'declared visible (no trained
detector yet)' until YOLO replaces it. Without --traces the old declared-anomaly path is
used and every report says so (method: declared_channels).
"""
import argparse
import json
from pathlib import Path

import evidence as ev
import priority as pr
import validity as va
from contracts import CONTRACT_VERSION

# Synthetic screening thresholds (not site rules). Gamma and thermal reuse existing
# sim/inspection_config.json values; hydrogen has none there, so 100 ppm (0.25 % LEL) is stated here.
THRESHOLDS = {
    "gamma": {"kind": "dose_rate_level", "above": 7.5, "units": "uSv/h",
              "source": "inspection_config thresholds.controlled_zone"},
    "hydrogen": {"kind": "hydrogen_ambient", "above": 100.0, "units": "ppm",
                 "source": "synthetic 100 ppm = 0.25 % of H2 LEL (stated in perception/stage3_assess.py)"},
    "thermal": {"kind": "thermal_surface", "above_ambient": 5.0, "ambient_c": 18.0, "units": "degC",
                "source": "inspection_config pressure_screen.temperature_above_ambient_c, zone A 18 degC"},
}
SENSOR_KIND = {"gamma": "gamma_dose_rate", "hydrogen": "hydrogen", "thermal": "temperature"}


def trace_message(name, sample, channel_cfg):
    """Codex sensor_traces sample -> contract sensor message (config fields from the scenario)."""
    ch = sample["channels"][name]
    pose = list(sample["pose_m"][:2]) + [channel_cfg.get("mount_height_m", sample["pose_m"][2])]
    m = {"contract_version": CONTRACT_VERSION, "sensor_id": f"robot.{name}", "kind": SENSOR_KIND[name],
         "source": channel_cfg.get("source", "robot"), "timestamp_s": ch["timestamp_s"], "units": ch["units"],
         "value": ch["value"], "pose": {"frame": "world", "xyz_m": pose}, "sample_age_s": ch["age_s"],
         "validity": ch["validity"],
         "uncertainty": {"std": channel_cfg.get("noise", 0.0)} if ch["value"] is not None
         else {"std": None, "status": "unknown"}, "status": ch.get("cause", "")}
    if name == "gamma":
        m["saturation_limit"] = channel_cfg.get("saturation", 1000.0)
    if name == "hydrogen":
        m["measures"] = ch.get("measures") or channel_cfg.get("measures", "ambient")
        m["detection_limit"] = channel_cfg.get("detection_limit", 0.0)
    return m


def channel_evidence(trace, scenario, area):
    """Evidence from captured samples only. Returns (evidence list, per-channel provenance)."""
    evs, prov = [], {}
    for name, rule in THRESHOLDS.items():
        cfg = scenario["runtime"].get("channels", {}).get(name, {})
        latest = None
        for sample in trace["samples"]:
            if name not in sample["channels"]:
                continue
            msg = trace_message(name, sample, cfg)
            verdict = va.assess(msg, now_s=sample["time_s"])
            latest = (sample, msg, verdict)
        if latest is None:
            prov[name] = {"state": "no_samples"}
            continue
        sample, msg, verdict = latest
        limit = rule["above"] if "above" in rule else rule["ambient_c"] + rule["above_ambient"]
        if verdict["usable"]:
            exceeds = msg["value"] > limit
        elif verdict["bound"] == "lower":          # saturated: true value >= reading
            exceeds = True
        else:                                       # stale/failed/below DL: no exceedance claim
            exceeds = False
        prov[name] = {"value": msg["value"], "units": msg["units"], "validity": verdict["state"],
                      "bound": verdict["bound"], "threshold": limit, "threshold_source": rule["source"],
                      "exceeds": exceeds, "t_s": sample["time_s"]}
        if exceeds:
            evs.append(ev.make_evidence(rule["kind"], value=msg["value"], units=msg["units"], t_s=sample["time_s"],
                                        area=area, sensor_msg_id=f"{msg['sensor_id']}@{sample['time_s']}",
                                        note=f"measured {msg['value']} {msg['units']} > {limit} ({rule['source']})"))
    return evs, prov

DEFECT_TO_KIND = {"corrosion": "visual_corrosion", "residue": "visual_wet_or_residue",
                  "wet": "visual_wet_or_residue", "bulge": "depth_deformation", "dent": "depth_deformation"}
# Synthetic screening levels, same values as sim/inspection_config.json thresholds.swab_bq_cm2.
SWAB_LIMITS = {"beta_gamma": 4.0, "alpha": 0.4}
CHANNEL_TO_KIND = {"gamma": "dose_rate_level", "hydrogen": "hydrogen_ambient", "thermal": "thermal_surface"}


def assess_scenario(sc, trace=None):
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
        kind_text = str(wet.get("fluid_kind", "")).lower()
        water = ("water" in kind_text or "condensation" in kind_text) and "residue" not in kind_text
        evs.append(ev.make_evidence("visual_water" if water else "visual_wet_or_residue", value=1,
                                    units="detections", t_s=0, area=area,
                                    note=f"appearance: {wet.get('fluid_kind')}; mechanism (scenario): {wet.get('mechanism')}"))
    obs = runtime.get("obstruction")
    if obs:
        evs.append(ev.make_evidence("route_obstruction", value=obs.get("geometry_m", {}).get("size"), units="m",
                                    t_s=0, area=obs.get("route_id", area), note=f"cause: {obs.get('cause')}"))
    # Swab: on the measured path, ONLY the captured independent contact observation counts.
    if trace is not None:
        swabs = [{"alpha_bq_cm2": o.get("alpha", 0.0), "beta_gamma_bq_cm2": o.get("beta_gamma", 0.0),
                  "t_s": o.get("timestamp_s", 0.0), "source": "trace independent_observations"}
                 for o in trace.get("independent_observations", []) if o.get("kind") == "virtual_contact_swab"]
    else:
        swabs = [runtime["swab"]] if runtime.get("swab") else []
    swab_record = None
    for swab in swabs:
        above = (swab.get("beta_gamma_bq_cm2", 0) > SWAB_LIMITS["beta_gamma"] or
                 swab.get("alpha_bq_cm2", 0) > SWAB_LIMITS["alpha"])
        swab_record = {**swab, "screening": SWAB_LIMITS, "above": above}
        if above:
            evs.append(ev.make_evidence("swab_contamination", value=swab, units="Bq/cm2", t_s=swab.get("t_s", 0),
                                        area=area, note="virtual contact swab above synthetic screening level"))
    provenance = None
    if trace is not None:
        channel_evs, provenance = channel_evidence(trace, sc, area)
        evs.extend(channel_evs)
        method = "measured_traces"
    else:
        method = "declared_channels"
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
            "priority": rank, "notes": notes, "channel_method": method, "channel_provenance": provenance, "swab": swab_record,
            "camera_method": "declared visible defects (no trained detector yet)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--traces", type=Path, help="run's sensor_traces.json (measured path)")
    args = ap.parse_args()
    traces = {t["scenario_id"]: t for t in json.loads(args.traces.read_text())} if args.traces else {}
    scs = [json.loads(p.read_text()) for p in args.files]
    if args.traces:
        missing = [sc["scenario_id"] for sc in scs if sc["scenario_id"] not in traces]
        if missing:
            raise SystemExit(f"no traces for {missing}")
    reports = [assess_scenario(sc, traces.get(sc["scenario_id"]) if args.traces else None) for sc in scs]
    text = json.dumps(reports, indent=2)
    if args.out:
        args.out.write_text(text)
    for r in reports:
        hyps = ", ".join(f["hypothesis"] for f in r["findings"]) or "none"
        print(f"{r['scenario_id']:<28} {r['condition_status']:<38} priority {r['priority']['index']:>5}  "
              f"findings: {hyps}  actions: {', '.join(r['actions'])}")


if __name__ == "__main__":
    main()
