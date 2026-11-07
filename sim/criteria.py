"""Inspection and safety decisions on MEASURED observations; no world imports.

Explanations are concise evidence/reason codes, not model chain-of-thought.
Unmeasured conditions stay unknown. These are configurable hackathon rules.
"""
import math
from sensors import load_config


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def classify_condition(measured, config=None):
    c = config or load_config()
    t = c['thresholds']
    findings = []
    missing = []

    def record(indicator, zone, value, reason):
        findings.append({'indicator': indicator, 'zone': zone, 'value': value, 'reason': reason})

    for field, indicator, thresholds in (('rust_pct', 'corrosion', t['rust_pct']),
                                          ('bulge_pct', 'bulge', t['bulge_pct'])):
        value = measured.get(field)
        if value is None:
            missing.append(indicator)
            continue
        # Exact upper boundary is tolerable: document says OVER 10% / OVER 5%.
        zone = 'Failing' if value > thresholds['failing'] else 'Tolerable' if value >= thresholds['tolerable'] else 'Ideal'
        if field == 'rust_pct' and value > 0 and measured.get('rust_near_lifting_features') is True:
            zone = 'Failing'
        record(indicator, zone, value, field)
    # A comparison is valid only at the same reference pose/geometry (1 m surface stand-off).
    if measured.get('dose_reference_matched') is True and measured.get('baseline_dose_uSv_h', 0) > 0 and measured.get('reference_dose_uSv_h') is not None:
        change = (measured['reference_dose_uSv_h']/measured['baseline_dose_uSv_h']-1)*100
        zone = 'Failing' if change > t['dose_vs_baseline_pct']['failing'] else 'Tolerable' if change >= t['dose_vs_baseline_pct']['tolerable'] or change < -t['dose_vs_baseline_pct']['tolerable'] else 'Ideal'
        record('shielding', zone, change, 'dose_change_pct_at_matched_reference')
    else:
        missing.append('shielding')
    if measured.get('peak_dose_uSv_h', 0) > t['hot_spot']:
        record('hot_spot', 'Failing', measured['peak_dose_uSv_h'], 'peak_dose_above_threshold')
    visual = measured.get('floor_condition')  # none, residue, puddle; from detector, not drum table
    swab = measured.get('swab')
    swab_high = swab is not None and (swab['beta_gamma_bq_cm2'] > t['swab_bq_cm2']['beta_gamma'] or swab['alpha_bq_cm2'] > t['swab_bq_cm2']['alpha'])
    if swab_high or visual == 'puddle':
        record('containment', 'Failing', visual, 'puddle_or_contamination_above_threshold')
    elif visual == 'residue':
        record('containment', 'Tolerable', visual, 'residue_requires_swab' if swab is None else 'residue_below_swab_threshold')
    elif visual == 'none':
        record('containment', 'Ideal', visual, 'no_visible_leak')
    else:
        missing.append('containment')
    label = measured.get('label_readability')
    if label in ('readable', 'partial', 'unreadable'):
        record('identification', {'readable':'Ideal', 'partial':'Tolerable', 'unreadable':'Failing'}[label], label, 'ocr_readability')
    else:
        missing.append('identification')
    rank = {'Ideal':0, 'Tolerable':1, 'Failing':2}
    worst = max((f['zone'] for f in findings), key=rank.get, default='Unknown')
    # Unknown criteria prevent an all-clear, but cannot hide a known failure.
    overall = 'Unknown' if worst == 'Ideal' and missing else worst
    confidence = measured.get('confidence')
    low, high = t['detector_unsure']
    uncertain = confidence is None or confidence < high or bool(missing)
    if confidence is not None and confidence < low:
        uncertain = True
    if overall == 'Ideal' and uncertain:
        overall = 'Unknown'
    actions = {'Unknown':['reinspect_second_angle'], 'Ideal':['log_continue'],
               'Tolerable':['reinspect_second_angle','flag_next_shift'],
               'Failing':['stop','capture_best_angle','raise_alert','route_around_aisle']}[overall].copy()
    if uncertain and 'reinspect_second_angle' not in actions:
        actions.append('reinspect_second_angle')
    if visual in ('residue','puddle') and swab is None:
        actions.append('request_swab_if_safe')
    env = c['environment']
    flags = []
    temperature = measured.get('temperature_c')
    humidity = measured.get('relative_humidity_pct')
    if temperature is not None and not env['temperature_range_c'][0] <= temperature <= env['temperature_range_c'][1]:
        flags.append('temperature_out_of_range')
    if humidity is not None and humidity > env['humidity_flag_pct']:
        flags.append('high_humidity')
    if measured.get('standing_water_away_from_drum'):
        flags.append('water_ingress')
    return {'zone':overall, 'findings':findings, 'missing':missing, 'uncertain':uncertain,
            'actions':actions, 'environment_flags':flags}


def safety_decision(observation, now_s, config=None):
    c = config or load_config()
    r, t = c['robot'], c['thresholds']
    reasons = []
    action = 'continue'
    def override(value, reason):
        nonlocal action
        priority = {'continue':0,'back_off_last_safe_waypoint':1,'return_to_dock':2,'stop':3}
        reasons.append(reason)
        if priority[value] > priority[action]:
            action = value
    for sensor in ('camera', 'dose'):
        timestamp = observation.get(sensor+'_timestamp_s')
        if not finite(timestamp) or timestamp > now_s or now_s-timestamp > r['sensor_timeout_s']:
            override('stop', sensor+'_dropout')
    dose = observation.get('dose_rate_uSv_h')
    gamma = observation.get('gamma', {})
    if gamma.get('status') == 'saturated':
        override('back_off_last_safe_waypoint','gamma_saturation')
    elif not finite(dose) or dose < 0 or gamma.get('valid') is False:
        override('stop','dose_missing')
    elif dose > t['hot_spot']:
        # Deliberate entry into a hot zone is not authorised by a model's text.
        override('back_off_last_safe_waypoint','hot_zone')
    accumulated = observation.get('mission_dose_mSv')
    if not finite(accumulated) or accumulated < 0:
        override('stop','dosimeter_missing_or_invalid')
    elif accumulated >= r['mission_dose_budget_mSv']*r['return_at_fraction']:
        override('return_to_dock','mission_dose_budget')
    distance = observation.get('nearest_drum_surface_m')  # depth/geometry estimator, never ground truth
    if not finite(distance):
        override('stop','distance_unknown')
    elif distance < r['min_distance_m']:
        # The chassis never crosses the limit. Only the virtual tool may reach a swab patch.
        override('stop','minimum_distance')
    elif observation.get('approaching_drum') and distance <= r['standoff_m']:
        override('stop','inspection_standoff')
    if observation.get('person_distance_m',float('inf')) < r['person_stop_m']:
        override('stop','person_in_path')
    zone = 'unknown' if not finite(dose) or dose < 0 else 'red' if dose > t['hot_spot'] else 'amber' if dose > t['controlled_zone'] else 'green'
    return {'action':action,'reasons':reasons,'map_zone':zone,
            'speed_limit_mps': r['max_speed_near_drums_mps'] if finite(distance) and distance < r['near_drum_radius_m'] else None}
