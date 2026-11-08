# Settings can be overridden by a preceding request script.
mode = state.pop('dense_round_mode', 'routine')
if mode not in ('routine', 'cosmos', 'rules', 'transient'):
    raise ValueError(f'Unknown dense round mode {mode}')
scene = copy.deepcopy(BASE_SCENE)
scene['use_lidar'] = state.pop('dense_round_lidar', True)
scene['verify_at_stops'] = mode == 'routine'
job = [d for d in inventory if d['row'] in STANDOFF and d['visible_face']
       and d['location']['tier'] == 1 and d['location']['column'] in (11, 13)]
assert len(inventory) == 360 and len(job) == 4
scene['job_drums'] = [d['id'] for d in job]
scene['records'] = {d['id']: d['display_id'] for d in job}
# The dense inventory increases ambient gamma. Calibrate the scenario sources
# to a traversable baseline while preserving the same independent dose stop.
scene['dose_source_scale'] = 0.4
if mode != 'routine':
    target = next(d for d in job if d['display_id'] == 'B-L-13-T1')
    scene['timed_incident'] = {
        'at_s': 3.8, 'drum_id': target['id'], 'temperature_rise_c': 30.0,
        'gas_vents': [{'position_m': [target['x'], target['y'], 0.6], 'hydrogen_ppm': 900.0}],
    }
    if mode == 'transient':
        scene['timed_incident'].update({'clear_at_s': 5.8, 'gas_vents': []})
a = Agent(1, f'Dense hall | {mode} | four aisle-facing drums', scene,
          [(11.9, AISLE_Y), (14.5, AISLE_Y), (15.1, AISLE_Y)])
suffix = '' if scene['use_lidar'] else '_odometry'
run_agent(a, f'dense_{mode}{suffix}', duration=25.0, use_cosmos=mode != 'rules')
