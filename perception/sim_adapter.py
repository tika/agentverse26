"""Map simulator sensor samples (sim/sensors.py SensorWorld.sample) to contract messages.

Accepts both the f1a288b flat sample and the Codex stage-1 sample that adds a
'gamma' packet (sensor_id, unit, value, timestamp_s, age_s, position_m,
uncertainty_uSv_h, valid, status in ok/failed/saturated) plus 'dose_complete'.
The simulator stays the owner of the physics; this module only renames fields.

Provenance rules (agreed with Codex, board 19:28:06):
- Never invent a pose. A legacy sample without position_m needs a caller-supplied pose.
- Unknown uncertainty is {"std": None, "status": "unknown"}, never 0.
- The S1 integral excludes invalid intervals and latches dose_complete=false; an
  incomplete total is published as a lower bound, not an exact exposure.
"""
from contracts import CONTRACT_VERSION

_STATUS_TO_VALIDITY = {"ok": "valid", "failed": "failed", "saturated": "saturated"}
UNKNOWN = {"std": None, "status": "unknown"}


def gamma_messages(sample, *, saturation_limit_uSv_h, integration_method="trapezoid",
                   pose=None, source="robot"):
    """Return (dose_rate_msg, cumulative_dose_msg) for one SensorWorld sample.

    pose: {"frame", "xyz_m"[, "yaw_rad"]}. Required when the sample carries no
    position_m; when both exist, the caller's pose wins only if it agrees on xyz.
    """
    g = sample.get("gamma") or {
        "sensor_id": "spot_gamma", "unit": "uSv/h", "value": sample["dose_rate_uSv_h"],
        "timestamp_s": sample["dose_timestamp_s"], "age_s": 0.0, "position_m": None,
        "uncertainty_uSv_h": None, "valid": True, "status": "ok",
    }
    if g.get("position_m") is not None:
        packet_pose = {"frame": "world", "xyz_m": [float(v) for v in g["position_m"]]}
        if pose is not None:
            if [round(v, 6) for v in pose["xyz_m"]] != [round(v, 6) for v in packet_pose["xyz_m"]]:
                raise ValueError("caller pose disagrees with the sensor packet position")
            packet_pose = dict(pose)
        pose = packet_pose
    elif pose is None:
        raise ValueError("sample has no position_m; supply the sensor pose explicitly")

    validity = _STATUS_TO_VALIDITY.get(g["status"], "failed")
    unc = g.get("uncertainty_uSv_h")
    rate = {
        "contract_version": CONTRACT_VERSION, "sensor_id": g["sensor_id"], "kind": "gamma_dose_rate",
        "source": source, "timestamp_s": g["timestamp_s"], "units": g["unit"], "value": g["value"],
        "pose": pose, "sample_age_s": g["age_s"], "validity": validity,
        "uncertainty": {"std": float(unc)} if unc is not None else dict(UNKNOWN),
        "status": g["status"], "saturation_limit": saturation_limit_uSv_h,
    }
    complete = bool(sample.get("dose_complete", True))
    cumulative = {
        "contract_version": CONTRACT_VERSION, "sensor_id": g["sensor_id"] + ".cumulative",
        "kind": "cumulative_dose", "source": source, "timestamp_s": sample["time_s"], "units": "uSv",
        "value": sample["mission_dose_mSv"] * 1000.0, "pose": pose, "sample_age_s": 0.0,
        "validity": "valid",
        # Integral noise is not modelled by the simulator: say so instead of claiming 0.
        "uncertainty": dict(UNKNOWN),
        "status": "ok" if complete else "incomplete_lower_bound",
        "integration_method": integration_method, "simulated_proxy": True,
        "complete": complete,
    }
    return rate, cumulative
