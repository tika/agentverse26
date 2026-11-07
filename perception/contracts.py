"""Versioned team message contracts (stage 1 draft, owner: Claude Code; review: Codex).

Pure Python, no third-party imports, so the same validators run in Isaac's bundled
Python, the training environment and plain CI. Every validator returns a list of
human-readable errors; an empty list means the message conforms.

Design rules taken from AGENTVERSE_SHARED_PROMPT v1.1:
- YOLO class order is fixed: 0 drum, 1 corrosion, 2 spill. Detector confidence is
  a visual score only, never a condition probability or priority.
- Existing detection fields (class, drum_id, xyxy as in boxes.json) are preserved;
  richer state lives in a separate versioned inspection record.
- Sensor messages carry timestamp, sensor ID, units, pose, sample age, validity,
  uncertainty and status, and state whether they come from the robot or a facility feed.
- Cumulative dose is a simulated proxy: uSv += uSv/h * dt_s / 3600. Not dosimetry.
- A priority index is a 0-100 ranking score. A calibrated probability is only allowed
  with a declared domain, target event and held-out evaluation reference.
- High-level (Cosmos) proposals must pick from offered goals, cite known evidence and
  can never override a safety hold/retreat.
"""
import math
import re

CONTRACT_VERSION = "1.0.0"
YOLO_CLASSES = ("drum", "corrosion", "spill")

SENSOR_KINDS = {
    # kind: allowed units
    "gamma_dose_rate": ("uSv/h",),
    "cumulative_dose": ("uSv",),
    "hydrogen": ("ppm", "%LEL", "%vol"),
    "temperature": ("degC",),
    "relative_humidity": ("%RH",),
}
SENSOR_SOURCES = ("robot", "facility")
VALIDITY = ("valid", "stale", "saturated", "below_detection_limit",
            "failed", "calibration_expired", "warming_up")
# Validity states that must never be treated as a usable measurement value.
UNUSABLE_VALIDITY = ("stale", "failed", "calibration_expired", "warming_up")
INTEGRATION_METHODS = ("left_rectangle", "trapezoid")

ACTIONS = ("inspect_goal", "second_view", "standoff", "alternate_route", "retreat", "hold_alert")
SAFETY_ACTIONS = ("retreat", "hold_alert")
CONDITION_STATUS = ("unknown", "insufficient_coverage", "no_visible_defect_in_inspected_area",
                    "finding_suspected", "finding_confirmed_multi_view", "ambiguous")
IDENTITY_STATUS = ("confirmed", "ambiguous", "unread", "conflict")

LANES, SIDES = ("A", "B", "C"), ("L", "R")
LOCATION_RE = re.compile(r"^([ABC])-([LR])-(\d{2})-T([123])(?:-D(2))?$")  # -D2: hidden back-row drum
DRUM_ID_RE = re.compile(r"^D\d{2,3}$")


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _require(msg, fields, errors, where=""):
    for f in fields:
        if f not in msg:
            errors.append(f"{where}missing field '{f}'")


def _pose_errors(pose, where):
    errors = []
    if not isinstance(pose, dict):
        return [f"{where}pose must be an object"]
    if pose.get("frame") not in ("world", "robot_base", "sensor"):
        errors.append(f"{where}pose.frame must be world, robot_base or sensor")
    xyz = pose.get("xyz_m")
    if not (isinstance(xyz, (list, tuple)) and len(xyz) == 3 and all(_finite(v) for v in xyz)):
        errors.append(f"{where}pose.xyz_m must be three finite metres")
    if "yaw_rad" in pose and not _finite(pose["yaw_rad"]):
        errors.append(f"{where}pose.yaw_rad must be finite radians")
    return errors


# --------------------------------------------------------------------------- yaw

def normalize_yaw_rad(yaw):
    """Wrap to (-pi, pi]. The scene convention is radians; convert legacy degrees explicitly."""
    if not _finite(yaw):
        raise ValueError("yaw must be finite")
    wrapped = math.atan2(math.sin(yaw), math.cos(yaw))
    return math.pi if math.isclose(wrapped, -math.pi) else wrapped


def legacy_degrees_to_rad(yaw_deg):
    return normalize_yaw_rad(math.radians(yaw_deg))


# ---------------------------------------------------------------------- location

def format_location(lane, side, column, tier, depth=1):
    code = f"{lane}-{side}-{int(column):02d}-T{int(tier)}" + ("" if int(depth) == 1 else f"-D{int(depth)}")
    if not LOCATION_RE.match(code) or int(column) < 1:
        raise ValueError(f"invalid location parts {lane!r},{side!r},{column!r},{tier!r}")
    return code


def parse_location(code):
    m = LOCATION_RE.match(code or "")
    if not m or int(m.group(3)) < 1:
        raise ValueError(f"invalid location code {code!r}")
    return {"lane": m.group(1), "side": m.group(2), "column": int(m.group(3)), "tier": int(m.group(4)),
            "depth": int(m.group(5) or 1)}


def location_errors(loc, where="location: "):
    errors = []
    _require(loc, ("lane", "side", "column", "tier", "tier_count", "stack_id",
                   "base_z_m", "location_code"), errors, where)
    if errors:
        return errors
    try:
        parts = parse_location(loc["location_code"])
    except ValueError as e:
        return [where + str(e)]
    for k in ("lane", "side", "column", "tier", "depth"):
        if parts[k] != loc.get(k, 1 if k == "depth" else None):
            errors.append(f"{where}{k}={loc[k]!r} disagrees with location_code {loc['location_code']}")
    if loc["tier_count"] not in (1, 2, 3) or not 1 <= loc["tier"] <= loc["tier_count"]:
        errors.append(f"{where}tier must lie in 1..tier_count (1-3)")
    if not _finite(loc["base_z_m"]) or loc["base_z_m"] < 0:
        errors.append(f"{where}base_z_m must be finite and non-negative")
    return errors


# ----------------------------------------------------------------------- sensors

def uncertainty_errors(unc):
    """Either a measured std (finite, >= 0, value units) or explicitly unknown.
    Unknown is {"std": None, "status": "unknown"}; it is never encoded as 0."""
    if not isinstance(unc, dict):
        return ["uncertainty must be an object"]
    if unc.get("std") is None:
        return [] if unc.get("status") == "unknown" else ["missing uncertainty must be marked status='unknown'"]
    if not (_finite(unc["std"]) and unc["std"] >= 0):
        return ["uncertainty.std must be finite and non-negative (same units as value)"]
    if unc.get("status") == "unknown":
        return ["uncertainty cannot be both measured and unknown"]
    return []


def sensor_message_errors(msg):
    """Validate one sensor sample (robot instrument or facility feed)."""
    errors = []
    _require(msg, ("contract_version", "sensor_id", "kind", "source", "timestamp_s", "units",
                   "value", "pose", "sample_age_s", "validity", "uncertainty", "status"), errors)
    if errors:
        return errors
    kind = msg["kind"]
    if kind not in SENSOR_KINDS:
        return [f"unknown sensor kind {kind!r}"]
    if msg["units"] not in SENSOR_KINDS[kind]:
        errors.append(f"{kind} units must be one of {SENSOR_KINDS[kind]}, got {msg['units']!r}")
    if msg["source"] not in SENSOR_SOURCES:
        errors.append("source must be 'robot' or 'facility'")
    if not _finite(msg["timestamp_s"]) or msg["timestamp_s"] < 0:
        errors.append("timestamp_s must be finite non-negative simulation seconds")
    if not _finite(msg["sample_age_s"]) or msg["sample_age_s"] < 0:
        errors.append("sample_age_s must be finite and non-negative")
    if msg["validity"] not in VALIDITY:
        errors.append(f"validity must be one of {VALIDITY}")
    value = msg["value"]
    if msg["validity"] in UNUSABLE_VALIDITY:
        pass  # value may be null or a last-known reading; consumers must not use it
    elif not _finite(value) or value < 0:
        errors.append("a usable reading needs a finite non-negative value")
    errors += uncertainty_errors(msg["uncertainty"])
    errors += _pose_errors(msg["pose"], "")
    if not isinstance(msg["status"], str):
        errors.append("status must be a short string")
    if kind == "cumulative_dose":
        if msg.get("integration_method") not in INTEGRATION_METHODS:
            errors.append(f"cumulative_dose needs integration_method in {INTEGRATION_METHODS}")
        if not msg.get("simulated_proxy", False):
            errors.append("cumulative_dose must declare simulated_proxy=true (not certified dosimetry)")
        if not isinstance(msg.get("complete"), bool):
            errors.append("cumulative_dose must state complete=true/false")
        elif not msg["complete"] and msg["status"] == "ok":
            errors.append("an incomplete integral must not report status 'ok' (it is a lower bound)")
    if kind == "hydrogen":
        if msg.get("measures") not in ("ambient", "package_headspace"):
            errors.append("hydrogen must state measures='ambient' or 'package_headspace'")
        if not _finite(msg.get("detection_limit")):
            errors.append("hydrogen must state a finite detection_limit")
    if kind == "gamma_dose_rate" and not _finite(msg.get("saturation_limit")):
        errors.append("gamma_dose_rate must state a finite saturation_limit")
    return errors


def usable(msg, now_s, max_age_s):
    """True only for a conforming, fresh, valid reading. Stale/failed/saturated readings are
    not usable as point values; a saturated reading still means 'at least the limit'."""
    if sensor_message_errors(msg) or msg["validity"] in UNUSABLE_VALIDITY + ("saturated",):
        return False
    age = now_s - msg["timestamp_s"] + msg["sample_age_s"]
    return 0 <= age <= max_age_s


def integrate_dose_uSv(rates, method="left_rectangle"):
    """Reference integration of (timestamp_s, uSv/h) samples to cumulative uSv.

    left_rectangle: each interval uses the earlier rate (dose_rate * dt / 3600).
    trapezoid: each interval uses the mean of its end rates.
    Returns a list of cumulative values aligned with the input. Timestamps must be
    strictly increasing; the first sample contributes no exposure.
    """
    if method not in INTEGRATION_METHODS:
        raise ValueError(f"method must be one of {INTEGRATION_METHODS}")
    out, total = [], 0.0
    for i, (t, r) in enumerate(rates):
        if not (_finite(t) and _finite(r)) or r < 0:
            raise ValueError(f"sample {i} must have finite time and non-negative rate")
        if i:
            t0, r0 = rates[i - 1]
            if t <= t0:
                raise ValueError(f"timestamps must strictly increase (sample {i})")
            rate = r0 if method == "left_rectangle" else (r0 + r) / 2
            total += rate * (t - t0) / 3600.0
        out.append(total)
    return out


def dose_stream_errors(rate_msgs, cumulative_msgs, rel_tol=1e-6, abs_tol_uSv=1e-9):
    """Conformance oracle for a simulator's dose-rate + cumulative-dose stream.

    Recomputes the cumulative proxy from the valid rate messages and compares it with
    the published cumulative messages at matching timestamps. Intended to test the
    Codex sensor implementation without importing it.
    """
    errors = []
    for m in list(rate_msgs) + list(cumulative_msgs):
        errors += [f"{m.get('sensor_id')}@{m.get('timestamp_s')}: {e}" for e in sensor_message_errors(m)]
    if errors:
        return errors
    methods = {m["integration_method"] for m in cumulative_msgs}
    if len(methods) != 1:
        return [f"cumulative stream mixes integration methods {sorted(methods)}"]
    samples = [(m["timestamp_s"], m["value"]) for m in rate_msgs if m["validity"] == "valid"]
    expected = dict(zip((t for t, _ in samples), integrate_dose_uSv(samples, methods.pop())))
    previous = -math.inf
    for m in cumulative_msgs:
        if m["value"] < previous:
            errors.append(f"cumulative dose decreased at t={m['timestamp_s']}")
        previous = m["value"]
        want = expected.get(m["timestamp_s"])
        if want is not None and not math.isclose(m["value"], want, rel_tol=rel_tol, abs_tol=abs_tol_uSv):
            errors.append(f"t={m['timestamp_s']}: cumulative {m['value']} uSv != expected {want} uSv")
    return errors


# -------------------------------------------------------------------- detections

def detection_errors(det):
    """Per-box detector output. Keeps existing boxes.json fields (class, drum_id, xyxy)."""
    errors = []
    _require(det, ("contract_version", "frame_id", "camera_id", "timestamp_s", "class_id",
                   "class", "confidence", "xyxy", "image_size_px", "model"), errors)
    if errors:
        return errors
    if det["class_id"] not in range(len(YOLO_CLASSES)) or YOLO_CLASSES[det["class_id"]] != det["class"]:
        errors.append(f"class_id/class must follow fixed order {YOLO_CLASSES}")
    if not _finite(det["confidence"]) or not 0 <= det["confidence"] <= 1:
        errors.append("confidence must be a detector score in [0,1]")
    size = det["image_size_px"]
    box = det["xyxy"]
    if not (isinstance(size, (list, tuple)) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size)):
        errors.append("image_size_px must be [width, height] positive integers")
    elif not (isinstance(box, (list, tuple)) and len(box) == 4 and all(_finite(v) for v in box)
              and 0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]):
        errors.append("xyxy must be a non-empty pixel box inside the image")
    # drum_id is an *association*, never read from ground truth by the detector.
    if det.get("drum_id") is not None and not DRUM_ID_RE.match(str(det["drum_id"])):
        errors.append("drum_id must be null or an immutable Dxx ID")
    if det.get("drum_id") is not None and det.get("association") not in ("plate_read", "geometry_map", "track"):
        errors.append("a non-null drum_id must name its association source")
    for banned in ("probability", "severity", "priority", "fault", "truth"):
        if banned in det:
            errors.append(f"detections must not carry '{banned}'; use the inspection record")
    model = det["model"]
    if not (isinstance(model, dict) and model.get("name") and model.get("revision")):
        errors.append("model must name name and revision")
    return errors


# ------------------------------------------------------------- inspection record

def inspection_record_errors(rec):
    errors = []
    _require(rec, ("contract_version", "drum_id", "legacy_id", "location", "identity",
                   "visibility", "finding_tracks", "sensor_context", "hypotheses",
                   "condition_status", "priority", "updated_s"), errors)
    if errors:
        return errors
    if not DRUM_ID_RE.match(str(rec["drum_id"])):
        errors.append("drum_id must be an immutable Dxx ID")
    errors += location_errors(rec["location"])
    ident = rec["identity"]
    if ident.get("status") not in IDENTITY_STATUS:
        errors.append(f"identity.status must be one of {IDENTITY_STATUS}")
    elif ident["status"] in ("ambiguous", "conflict") and len(ident.get("candidates", [])) < 2:
        errors.append("ambiguous/conflicting identity must list at least two candidates")
    vis = rec["visibility"]
    cov = vis.get("surface_coverage_fraction")
    if not (_finite(cov) and 0 <= cov <= 1):
        errors.append("visibility.surface_coverage_fraction must lie in [0,1]")
    for i, tr in enumerate(rec["finding_tracks"]):
        w = f"finding_tracks[{i}]: "
        _require(tr, ("track_id", "class", "first_seen_s", "last_seen_s", "frames",
                      "distinct_views", "max_confidence", "evidence_ids"), errors, w)
        if tr.get("class") not in YOLO_CLASSES[1:] + ("deformation",):
            errors.append(w + "class must be corrosion, spill or deformation")
        if "combined_probability" in tr:
            errors.append(w + "do not combine correlated frame confidences into a probability")
        if not tr.get("evidence_ids"):
            errors.append(w + "a finding must cite evidence_ids")
    status = rec["condition_status"]
    if status not in CONDITION_STATUS:
        errors.append(f"condition_status must be one of {CONDITION_STATUS}")
    if status == "no_visible_defect_in_inspected_area" and _finite(cov) and cov == 0:
        errors.append("'no visible defect' needs some inspected surface (coverage > 0)")
    if _finite(cov) and cov == 1 and not vis.get("full_coverage_verified"):
        errors.append("coverage of 1.0 needs visibility.full_coverage_verified")
    pr = rec["priority"]
    if pr.get("kind") != "ranking_score":
        errors.append("priority.kind must be 'ranking_score'")
    if not (_finite(pr.get("index")) and 0 <= pr["index"] <= 100):
        errors.append("priority.index must be a 0-100 ranking score")
    if not pr.get("breakdown"):
        errors.append("priority needs an explained breakdown")
    cal = rec.get("calibrated_probability")
    if cal is not None:
        for k in ("value", "target_event", "domain", "heldout_eval_ref"):
            if k not in cal:
                errors.append(f"calibrated_probability requires '{k}'")
    for banned in ("rupture_probability", "failure_probability", "is_safe", "ground_truth", "faults"):
        if banned in rec:
            errors.append(f"inspection record must not contain '{banned}'")
    return errors


# --------------------------------------------------------- high-level proposals

def proposal_errors(proposal, offered_goal_ids, known_evidence_ids, safety_action=None):
    """Validate a Cosmos/rules high-level proposal before it reaches the controller.

    safety_action is the independent safety layer's decision for this tick
    (None, 'retreat' or 'hold_alert'). It always wins; a proposal that tries to
    move toward a goal while safety demands retreat/hold is rejected.
    """
    errors = []
    _require(proposal, ("action", "goal_id", "evidence_ids", "reason", "model"), errors)
    if errors:
        return errors
    action = proposal["action"]
    if action not in ACTIONS:
        errors.append(f"action must be one of {ACTIONS}")
    if action in ("inspect_goal", "second_view", "standoff", "alternate_route"):
        if proposal["goal_id"] not in set(offered_goal_ids):
            errors.append("goal_id must be one of the offered reachable goals")
    unknown = set(proposal["evidence_ids"]) - set(known_evidence_ids)
    if unknown:
        errors.append(f"cites unknown evidence {sorted(unknown)}")
    if action != "hold_alert" and not proposal["evidence_ids"]:
        errors.append("an action must cite at least one evidence id")
    if not isinstance(proposal["reason"], str) or not proposal["reason"].strip():
        errors.append("reason must be a non-empty sentence")
    if safety_action in SAFETY_ACTIONS and action not in SAFETY_ACTIONS:
        errors.append(f"safety layer demands {safety_action}; proposal cannot override it")
    return errors
