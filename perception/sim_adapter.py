"""Map simulator sensor samples (sim/sensors.py SensorWorld.sample) to contract messages.

Accepts both the f1a288b flat sample and the Codex stage-1 sample that adds a
'gamma' packet (sensor_id, unit, value, timestamp_s, age_s, position_m,
uncertainty_uSv_h, valid, status in ok/failed/saturated) plus 'dose_complete'.
The simulator stays the owner of the physics; this module only renames fields.
"""
from contracts import CONTRACT_VERSION

_STATUS_TO_VALIDITY = {"ok": "valid", "failed": "failed", "saturated": "saturated"}


def gamma_messages(sample, *, saturation_limit_uSv_h, integration_method="trapezoid",
                   yaw_rad=None, source="robot"):
    """Return (dose_rate_msg, cumulative_dose_msg) for one SensorWorld sample."""
    g = sample.get("gamma") or {
        "sensor_id": "spot_gamma", "unit": "uSv/h", "value": sample["dose_rate_uSv_h"],
        "timestamp_s": sample["dose_timestamp_s"], "age_s": 0.0, "position_m": None,
        "uncertainty_uSv_h": None, "valid": True, "status": "ok",
    }
    pose = {"frame": "world", "xyz_m": list(g["position_m"]) if g["position_m"] is not None else [0.0, 0.0, 0.0]}
    if yaw_rad is not None:
        pose["yaw_rad"] = yaw_rad
    validity = _STATUS_TO_VALIDITY.get(g["status"], "failed")
    rate = {
        "contract_version": CONTRACT_VERSION, "sensor_id": g["sensor_id"], "kind": "gamma_dose_rate",
        "source": source, "timestamp_s": g["timestamp_s"], "units": g["unit"], "value": g["value"],
        "pose": pose, "sample_age_s": g["age_s"], "validity": validity,
        "uncertainty": {"std": g["uncertainty_uSv_h"] if g["uncertainty_uSv_h"] is not None else 0.0},
        "status": g["status"], "saturation_limit": saturation_limit_uSv_h,
    }
    complete = sample.get("dose_complete", True)
    cumulative = {
        "contract_version": CONTRACT_VERSION, "sensor_id": g["sensor_id"] + ".cumulative",
        "kind": "cumulative_dose", "source": source, "timestamp_s": sample["time_s"], "units": "uSv",
        "value": sample["mission_dose_mSv"] * 1000.0, "pose": pose, "sample_age_s": 0.0,
        # An interrupted integral is still a valid lower bound; flag it rather than hide it.
        "validity": "valid", "uncertainty": {"std": 0.0},
        "status": "ok" if complete else "incomplete_lower_bound",
        "integration_method": integration_method, "simulated_proxy": True,
        "complete": complete,
    }
    return rate, cumulative
