"""Synthetic payload observations for scenario tests, in simulation coordinates."""

import math

import numpy as np


def dew_point_c(air_c, relative_humidity_pct):
    """Magnus approximation for moist air, with no finite result at zero RH."""
    if relative_humidity_pct <= 0:
        return None
    a, b = 17.62, 243.12
    factor = math.log(relative_humidity_pct / 100.0) + a * air_c / (b + air_c)
    return b * factor / (a - factor)


def gas_at_pose(position, vents):
    """Sample independent H2 and CH4 fixture fields. This is not a dispersion model."""
    readings = {"hydrogen_ppm": 0.0, "methane_ppm": 0.0}
    for vent in vents:
        distance_squared = math.dist(position, vent["position_m"]) ** 2
        for key in readings:
            readings[key] += vent.get(key, 0.0) / (1.0 + distance_squared)
    return readings


def thermal_image(instance_ids, temperature_by_id, ambient_c):
    """Make a synthetic temperature image from a registered visible-instance buffer."""
    temperatures = np.full(instance_ids.shape, ambient_c, dtype=np.float32)
    for instance_id, temperature in temperature_by_id.items():
        temperatures[instance_ids == instance_id] = temperature
    return temperatures


def microphone_window(position, start_s, events, *, duration_s=0.25, sample_rate_hz=16000, seed=42):
    """Render a short mono waveform with independently authored hiss and impulse sources."""
    rng = np.random.default_rng(seed)
    relative_time = np.arange(round(duration_s * sample_rate_hz)) / sample_rate_hz
    signal = rng.normal(0.0, 0.002, relative_time.shape)
    for event in events:
        elapsed = start_s + relative_time - event["time_s"]
        gain = event["amplitude"] / (1.0 + math.dist(position, event["position_m"]))
        if event["kind"] == "hiss":
            active = (elapsed >= 0) & (elapsed < event["duration_s"])
            signal[active] += gain * rng.normal(0.0, 1.0, np.count_nonzero(active))
        elif event["kind"] == "impulse":
            active = (elapsed >= 0) & (elapsed < 0.03)
            signal[active] += gain * np.exp(-elapsed[active] / 0.005)
        else:
            raise ValueError(f"Unknown acoustic fixture: {event['kind']}")
    return np.clip(signal, -1.0, 1.0).astype(np.float32)
