"""Stage-3 semantic/data checks on hazard scenario files (Claude Code; review: Codex).

Consumes the scenario schema agreed on TEAM_BOARD 21:40-21:43 (Codex proposal + Claude
additions). Usage: python perception/scenario_checks.py sim/scenarios/*.json

Checks per scenario: required fields, case tags, truth/runtime separation, channel units
and hydrogen scope, per-channel cause, mechanism for wet cases, synthetic dose calibration,
and that one scenario never drives every hazard channel. Across a set: required case
coverage (prompt v1.1 stage 3).
"""
import json
import sys
from pathlib import Path

from contracts import SENSOR_KINDS

CASE_TAGS = {"sound_but_radioactive", "corroded_no_dose_change", "hidden_condition", "wet_external_water",
             "wet_suspected_release", "deformation_only", "gas_area_concern", "thermal_only", "obstruction",
             "healthy_control"}
REQUIRED_CASES = {"sound_but_radioactive", "corroded_no_dose_change", "hidden_condition", "healthy_control"}
CHANNEL_KIND = {"gamma": "gamma_dose_rate", "hydrogen": "hydrogen", "thermal": "temperature"}
TRUTH_ONLY_KEYS = {"faults", "internal_corrosion", "true_shape", "source_strength", "source_params",
                   "hidden", "truth", "defect_truth"}
CHANNEL_FIELDS = ("enabled", "units", "sample_period_s", "noise", "detection_limit", "saturation",
                  "response_lag_s", "calibration", "mount_height_m", "cause")


def _walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}" if path else k, k
            yield from _walk_keys(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_keys(v, f"{path}[{i}]")


def scenario_errors(sc):
    e = []
    for k in ("scenario_id", "seed", "case_tags", "truth", "runtime"):
        if k not in sc:
            e.append(f"missing '{k}'")
    if e:
        return e
    tags = set(sc["case_tags"])
    if not tags or tags - CASE_TAGS:
        e.append(f"case_tags must be a non-empty subset of {sorted(CASE_TAGS)}; got {sorted(tags)}")
    for path, key in _walk_keys(sc["runtime"]):
        if key in TRUTH_ONLY_KEYS:
            e.append(f"truth key '{path}' leaked into runtime")
    channels = sc["runtime"].get("channels", {})
    active = []
    for name, ch in channels.items():
        w = f"channel {name}: "
        if name not in CHANNEL_KIND:
            e.append(w + f"unknown channel; expected one of {sorted(CHANNEL_KIND)}")
            continue
        for f in CHANNEL_FIELDS:
            if f not in ch:
                e.append(w + f"missing '{f}'")
        if ch.get("units") not in SENSOR_KINDS[CHANNEL_KIND[name]]:
            e.append(w + f"units must be one of {SENSOR_KINDS[CHANNEL_KIND[name]]}")
        if name == "hydrogen" and ch.get("measures") not in ("ambient", "package_headspace"):
            e.append(w + "hydrogen must state measures: ambient | package_headspace")
        if ch.get("enabled") and ch.get("anomaly"):
            active.append(name)
            if not str(ch.get("cause", "")).strip():
                e.append(w + "an anomaly needs a cause tying it to a mechanism")
    for d in sc["runtime"].get("defects", []):
        if d.get("dose_effect") not in (None, "none") and sc["truth"].get("calibration", "synthetic") != "synthetic":
            e.append("dose_effect requires calibration: synthetic")
    wet = sc["runtime"].get("wet_case")
    if wet and not str(wet.get("mechanism", "")).strip():
        e.append("wet_case needs a mechanism (e.g. external water ingress, condensation, suspected release)")
    if wet and "wet_suspected_release" in tags and not ({"gamma", "hydrogen"} & set(active)
                                                         or sc["truth"].get("contamination")):
        e.append("wet_suspected_release must be backed by an independent channel or truth contamination")
    if len(active) == len(CHANNEL_KIND):
        e.append("every hazard channel is anomalous: faults must not raise every sensor")
    # Tag consistency with the channels/defects actually present.
    visible = [d for d in sc["runtime"].get("defects", []) if d.get("visible_fraction", 0) > 0]
    if "sound_but_radioactive" in tags and (visible or "gamma" not in active):
        e.append("sound_but_radioactive: no visible defects and an elevated gamma channel expected")
    if "corroded_no_dose_change" in tags and ("gamma" in active
                                               or not any(d.get("kind") == "corrosion" for d in visible)):
        e.append("corroded_no_dose_change: visible corrosion and no gamma anomaly expected")
    if "hidden_condition" in tags and visible:
        e.append("hidden_condition: the condition must not be visible to the camera")
    if "hidden_condition" in tags and not sc["truth"]:
        e.append("hidden_condition: the hidden fault must be recorded in truth")
    if "healthy_control" in tags and (visible or active or wet):
        e.append("healthy_control: no defects, anomalies or wet case")
    return e


def set_errors(scenarios):
    errs = {}
    for sc in scenarios:
        e = scenario_errors(sc)
        if e:
            errs[sc.get("scenario_id", "?")] = e
    covered = set().union(*(set(sc.get("case_tags", [])) for sc in scenarios)) if scenarios else set()
    missing = REQUIRED_CASES - covered
    if missing:
        errs["<set>"] = [f"required cases missing: {sorted(missing)}"]
    return errs


if __name__ == "__main__":
    files = [Path(p) for p in sys.argv[1:]]
    scs = [json.loads(p.read_text()) for p in files]
    result = set_errors(scs)
    print(json.dumps({"files": len(files), "errors": result, "pass": not result}, indent=2))
    sys.exit(0 if not result else 1)
