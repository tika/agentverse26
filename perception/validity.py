"""Stage-3 sensor validity handling (owner: Claude Code; review: Codex).

Turns one contract sensor message (perception/contracts.py) into a validity verdict:
  usable     - may be used as a point value
  bound      - None, 'lower' (true value >= reading, e.g. saturated) or 'upper'
               (true value <= reading, e.g. below detection limit)
  state      - fresh | stale | future | saturated | below_detection_limit | failed |
               calibration_expired | warming_up | invalid_message
  reasons    - human-readable explanation
All limits are synthetic demonstration settings (MAX_AGE_S), not site rules.
"""
from contracts import sensor_message_errors

POLICY_VERSION = "1.0.0"

# Synthetic per-kind freshness limits, seconds. Configurable; not operational limits.
MAX_AGE_S = {"gamma_dose_rate": 2.0, "cumulative_dose": 2.0, "hydrogen": 10.0,
             "temperature": 15.0, "relative_humidity": 30.0}


def assess(msg, now_s, max_age_s=None):
    errors = sensor_message_errors(msg)
    if errors:
        return {"usable": False, "bound": None, "state": "invalid_message", "reasons": errors}
    limit = max_age_s if max_age_s is not None else MAX_AGE_S[msg["kind"]]
    age = now_s - msg["timestamp_s"] + msg["sample_age_s"]
    v = msg["validity"]
    if v in ("failed", "calibration_expired", "warming_up"):
        return {"usable": False, "bound": None, "state": v, "reasons": [f"sensor reports {v}"]}
    if now_s < msg["timestamp_s"]:
        return {"usable": False, "bound": None, "state": "future", "reasons": ["timestamp is in the future"]}
    if age > limit:
        return {"usable": False, "bound": None, "state": "stale",
                "reasons": [f"sample age {age:.2f} s exceeds {limit} s"]}
    if v == "saturated":
        return {"usable": False, "bound": "lower", "state": "saturated",
                "reasons": [f"at or above instrument limit {msg.get('saturation_limit')} {msg['units']}"]}
    if v == "below_detection_limit":
        return {"usable": False, "bound": "upper", "state": "below_detection_limit",
                "reasons": [f"below detection limit {msg.get('detection_limit')} {msg['units']}"]}
    if v == "stale":
        return {"usable": False, "bound": None, "state": "stale", "reasons": ["sensor flags data stale"]}
    return {"usable": True, "bound": None, "state": "fresh", "reasons": []}


def absence_claim_allowed(msg, region_z_m, tolerance_m=0.5):
    """May a low/zero hydrogen reading be used to say 'no gas' at region_z_m?

    No if the sensor sits well below the region (hydrogen is buoyant), if it measures
    ambient air while the question is a sealed package, or if the reading is not usable.
    """
    reasons = []
    if msg["kind"] != "hydrogen":
        return False, ["only hydrogen readings are assessed for absence claims"]
    z = msg["pose"]["xyz_m"][2]
    if z + tolerance_m < region_z_m:
        reasons.append(f"sensor at {z:.2f} m cannot establish absence at {region_z_m:.2f} m (buoyant gas)")
    if msg.get("measures") != "ambient":
        reasons.append("headspace sample says nothing about ambient air elsewhere")
    if msg["validity"] not in ("valid", "below_detection_limit"):
        reasons.append(f"reading not usable ({msg['validity']})")
    return not reasons, reasons


def channel_summary(msgs, now_s):
    """Latest verdict per sensor_id, plus which critical channels are unusable (for the safety layer)."""
    latest = {}
    for m in msgs:
        sid = m.get("sensor_id")
        if sid not in latest or m.get("timestamp_s", -1) > latest[sid].get("timestamp_s", -1):
            latest[sid] = m
    verdicts = {sid: {**assess(m, now_s), "kind": m.get("kind"), "source": m.get("source")}
                for sid, m in latest.items()}
    critical_down = sorted(sid for sid, v in verdicts.items()
                           if v["kind"] in ("gamma_dose_rate", "hydrogen") and not v["usable"] and v["bound"] != "lower")
    return {"policy_version": POLICY_VERSION, "verdicts": verdicts, "critical_unusable": critical_down}
