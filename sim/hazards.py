"""Independent, explicitly synthetic hazard-channel proxies for Stage 3.

Truth parameters are used only inside this simulator-side module. The returned
packet contains measurements and channel validity, never fault flags or source
parameters. This is not radiation transport, a calibrated gas detector, or a
certified thermal instrument.
"""
from __future__ import annotations

import copy
import json
import math
import random
from pathlib import Path


def load_scenario(path):
    return json.loads(Path(path).read_text())


class HazardSensors:
    """Deterministic, independently controllable gamma/H2/thermal sample proxy."""

    def __init__(self, scenario):
        self.scenario = copy.deepcopy(scenario)
        self._rng = random.Random(int(scenario['seed']))
        self._last = {}

    @staticmethod
    def _distance(a, b):
        return math.sqrt(sum((float(a[i])-float(b[i]))**2 for i in range(3)))

    def _true_value(self, name, pose):
        src = self.scenario.get('truth', {}).get('source_params', {})
        if name == 'gamma':
            location = src.get('gamma_source_location_m', [0.0, 0.0, 0.5])
            strength = max(0.0, float(src.get('gamma_dose_rate_uSv_h_at_1m', 0.0)))
            return max(0.0, float(src.get('gamma_background_uSv_h', 0.2)) + strength / max(self._distance(pose, location)**2, 0.01))
        if name == 'hydrogen':
            channel = self.scenario['runtime']['channels'][name]
            if channel.get('measures') == 'package_headspace':
                # A headspace value is a separate virtual probe mode; it is never
                # inferred from a robot's ambient sample.
                return max(0.0, float(src.get('hydrogen_headspace', 0.0)))
            location = src.get('hydrogen_source_location_m', [0.0, 0.0, 1.0])
            concentration = max(0.0, float(src.get('hydrogen_source_ppm', 0.0)))
            distance = self._distance(pose, location)
            vertical = max(0.1, 1.0 + (float(pose[2])-float(location[2]))*.15)
            return concentration * math.exp(-distance/3.0) / vertical
        if name == 'thermal':
            location = src.get('thermal_source_location_m', [0.0, 0.0, 0.5])
            surface = float(src.get('surface_temperature_c', 18.0))
            ambient = float(src.get('ambient_temperature_c', 18.0))
            distance = self._distance(pose, location)
            return ambient + (surface-ambient) * math.exp(-distance/2.0)
        raise KeyError(name)

    def sample(self, pose_m, time_s, operational=None):
        """Return current channel observations; no ground-truth fields are emitted."""
        if len(pose_m) != 3 or not all(math.isfinite(float(v)) for v in pose_m):
            raise ValueError('pose_m must contain three finite metres')
        if not math.isfinite(float(time_s)) or time_s < 0:
            raise ValueError('time_s must be finite and nonnegative')
        packets = {}
        operational = operational or {}
        for name, cfg in self.scenario['runtime'].get('channels', {}).items():
            op = operational.get(name, {})
            if op.get('failed'):
                packets[name] = {'value': None, 'units': cfg['units'], 'timestamp_s': float(time_s),
                                 'age_s': 0.0, 'validity': 'failed', 'cause': cfg['cause']}
                continue
            if op.get('stale'):
                old = self._last.get(name)
                packets[name] = {'value': old['value'] if old else None, 'units': cfg['units'],
                                 'timestamp_s': old['timestamp_s'] if old else None,
                                 'age_s': float(time_s-old['timestamp_s']) if old else None,
                                 'validity': 'stale', 'cause': cfg['cause']}
                continue
            if not cfg.get('enabled', False):
                packets[name] = {'value': None, 'units': cfg['units'], 'timestamp_s': float(time_s),
                                 'age_s': None, 'validity': 'failed', 'cause': cfg['cause']}
                continue
            dt = float(cfg.get('sample_period_s', 1.0))
            if name in self._last and time_s-self._last[name]['timestamp_s'] < dt:
                old = self._last[name]
                packets[name] = {**old, 'age_s': float(time_s-old['timestamp_s'])}
                continue
            lag = float(cfg.get('response_lag_s', 0.0))
            if time_s < lag:
                packets[name] = {'value': None, 'units': cfg['units'], 'timestamp_s': float(time_s),
                                 'age_s': 0.0, 'validity': 'warming_up', 'cause': cfg['cause']}
                continue
            raw = self._true_value(name, pose_m)
            noise = max(0.0, float(cfg.get('noise', 0.0)))
            value = max(0.0, self._rng.gauss(raw, noise))
            limit = cfg.get('saturation')
            validity = 'valid'
            if limit is not None and value >= float(limit):
                value, validity = float(limit), 'saturated'
            elif value < float(cfg.get('detection_limit', 0.0)):
                validity = 'below_detection_limit'
            if cfg.get('calibration') != 'synthetic' or op.get('calibration_valid') is False:
                validity = 'calibration_expired'
            packet = {'value': value, 'units': cfg['units'], 'timestamp_s': float(time_s),
                      'age_s': 0.0, 'validity': validity, 'cause': cfg['cause'],
                      'measures': cfg.get('measures')}
            self._last[name] = packet
            packets[name] = packet
        return {'time_s': float(time_s), 'pose_m': list(map(float, pose_m)), 'channels': packets}
