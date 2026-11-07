"""Stage-3 evidence taxonomy and condition rules (owner: Claude Code; review: Codex).

Every observation becomes an evidence record of one KIND. Each kind states what it
can support and what it can NOT establish (prompt v1.1 research boundaries). Findings
are hypotheses about one drum or an area; condition status comes from explicit rules
over evidence, never from simulator truth.

Pure Python; no Isaac or third-party imports.
"""
import itertools

TAXONOMY_VERSION = "1.0.0"

# kind -> source, scope, supports (hypotheses), cannot_establish (stated limits)
KINDS = {
    "visual_corrosion": {
        "source": "camera+detector (YOLO class 1)", "scope": "drum",
        "supports": ["external_corrosion"],
        "cannot_establish": ["remaining wall thickness", "internal corrosion", "leak", "radioactivity"]},
    "visual_wet_or_residue": {
        "source": "camera+detector (YOLO class 2 'spill')", "scope": "drum_or_area",
        "supports": ["wet_or_residue_unexplained"],
        "cannot_establish": ["radioactivity", "contamination", "chemistry", "which drum released it"]},
    "depth_deformation": {
        "source": "depth residual vs nominal profile", "scope": "drum",
        "supports": ["suspected_deformation"],
        "cannot_establish": ["internal pressure", "hydrogen", "imminent burst", "a specific reaction"]},
    "dose_rate_level": {
        "source": "robot gamma dose-rate meter", "scope": "area",
        "supports": ["elevated_radiation_field"],
        "cannot_establish": ["a leak", "contamination", "which package is the source (without attribution)"]},
    "dose_rate_change": {
        "source": "gamma at matched reference pose vs baseline", "scope": "area",
        "supports": ["radiation_field_change"],
        "cannot_establish": ["a leak", "cause (movement, shielding or neighbouring sources possible)"]},
    "hydrogen_ambient": {
        "source": "robot or facility hydrogen sensor (ambient)", "scope": "area",
        "supports": ["gas_concern_area"],
        "cannot_establish": ["sealed-package headspace concentration", "the source package",
                             "absence above the sensor height"]},
    "hydrogen_headspace": {
        "source": "explicit package headspace sampling", "scope": "drum",
        "supports": ["gas_concern_package"],
        "cannot_establish": ["imminent burst", "ambient concentration elsewhere"]},
    "thermal_surface": {
        "source": "named simulated thermal/contact sensor", "scope": "drum_or_area",
        "supports": ["thermal_anomaly"],
        "cannot_establish": ["internal reaction (lag, emissivity)", "fire"]},
    "swab_contamination": {
        "source": "virtual swab tool (alpha, beta-gamma Bq/cm2)", "scope": "area",
        "supports": ["surface_contamination"],
        "cannot_establish": ["which drum (without position evidence)"]},
    "route_obstruction": {
        "source": "depth/camera geometry inside a planned route", "scope": "area",
        "supports": ["route_blocked"],
        "cannot_establish": ["what the object is", "whether it is hazardous", "drum condition"]},
    "coverage": {
        "source": "camera visibility of the drum surface", "scope": "drum",
        "supports": [], "cannot_establish": ["condition of unseen surfaces"]},
}

# Hypothesis -> (severity weight 0-1 for ranking, needs_second_view)
HYPOTHESES = {
    "external_corrosion": (0.45, True),
    "wet_or_residue_unexplained": (0.55, True),
    "suspected_deformation": (0.60, True),
    "elevated_radiation_field": (0.40, False),
    "radiation_field_change": (0.55, False),
    "gas_concern_area": (0.80, False),
    "gas_concern_package": (0.85, False),
    "thermal_anomaly": (0.70, False),
    "surface_contamination": (0.75, False),
    # Combined hypotheses need two independent evidence kinds.
    "suspected_release": (0.85, False),
    "route_blocked": (0.30, False),   # navigation finding, not a drum condition
}
COMBINED = {
    # A release is only suspected when visible wet/residue evidence AND an independent channel agree.
    "suspected_release": [("visual_wet_or_residue", "swab_contamination"),
                          ("visual_wet_or_residue", "dose_rate_change")],
}
SAFETY_HYPOTHESES = {"gas_concern_area", "gas_concern_package", "thermal_anomaly"}
NON_CONDITION = {"route_blocked"}  # navigation findings never change a drum's condition status

_ids = itertools.count(1)


def make_evidence(kind, *, value, units, t_s, drum_ids=(), area=None, sensor_msg_id=None,
                  frame_id=None, view_id=None, confidence=None, valid=True, note=""):
    if kind not in KINDS:
        raise ValueError(f"unknown evidence kind {kind!r}")
    scope = KINDS[kind]["scope"]
    if scope == "drum" and len(drum_ids) != 1:
        raise ValueError(f"{kind} is drum-scoped: give exactly one drum id")
    if scope == "area" and drum_ids and area is None:
        raise ValueError(f"{kind} is area-scoped: give an area; drum ids may only be candidates")
    return {"id": f"ev-{next(_ids):05d}", "taxonomy_version": TAXONOMY_VERSION, "kind": kind,
            "source": KINDS[kind]["source"], "value": value, "units": units, "t_s": t_s,
            "drum_ids": list(drum_ids), "area": area, "sensor_msg_id": sensor_msg_id,
            "frame_id": frame_id, "view_id": view_id, "confidence": confidence, "valid": valid,
            "cannot_establish": list(KINDS[kind]["cannot_establish"]), "note": note}


def findings_for(evidence):
    """Hypotheses supported by a set of evidence records (one drum or one area).

    Correlated frames are NOT multiplied: a finding counts distinct views, not frames.
    """
    usable = [e for e in evidence if e["valid"]]
    out = {}
    for e in usable:
        for h in KINDS[e["kind"]]["supports"]:
            f = out.setdefault(h, {"hypothesis": h, "evidence_ids": [], "views": set(), "kinds": set()})
            f["evidence_ids"].append(e["id"])
            f["kinds"].add(e["kind"])
            if e.get("view_id") is not None:
                f["views"].add(e["view_id"])
    kinds = {e["kind"] for e in usable}
    for h, pairs in COMBINED.items():
        for a, b in pairs:
            if a in kinds and b in kinds:
                ids = [e["id"] for e in usable if e["kind"] in (a, b)]
                out[h] = {"hypothesis": h, "evidence_ids": ids, "views": set(), "kinds": {a, b}}
    for f in out.values():
        f["distinct_views"] = len(f["views"])
        f["views"] = sorted(f["views"])
        f["kinds"] = sorted(f["kinds"])
    return sorted(out.values(), key=lambda f: f["hypothesis"])


def condition_status(findings, coverage_fraction):
    """Map findings + coverage to contracts.CONDITION_STATUS. Never returns a 'safe' state."""
    findings = [f for f in findings if f["hypothesis"] not in NON_CONDITION]
    if coverage_fraction is None:
        return "unknown"
    if not findings:
        return "insufficient_coverage" if coverage_fraction <= 0 else "no_visible_defect_in_inspected_area"
    visual = [f for f in findings if HYPOTHESES[f["hypothesis"]][1]]
    if visual and all(f["distinct_views"] >= 2 for f in visual):
        return "finding_confirmed_multi_view"
    return "finding_suspected"


def actions_for(findings, coverage_fraction):
    """Recommended inspection actions (proposals; the safety layer still decides motion)."""
    actions = []
    hyps = {f["hypothesis"] for f in findings}
    if hyps & SAFETY_HYPOTHESES:
        actions.append("stand_off_and_alert")
    if any(HYPOTHESES[f["hypothesis"]][1] and f["distinct_views"] < 2 for f in findings):
        actions.append("second_view")
    if "wet_or_residue_unexplained" in hyps and "suspected_release" not in hyps:
        actions.append("request_swab_if_safe")
    if "elevated_radiation_field" in hyps and "radiation_field_change" not in hyps:
        actions.append("measure_at_matched_reference_pose")
    if "route_blocked" in hyps:
        actions.append("replan_route")
    if coverage_fraction is not None and coverage_fraction < 0.25:
        actions.append("improve_coverage")
    return actions or ["log_continue"]
