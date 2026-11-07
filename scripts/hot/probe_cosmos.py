# Probe: PTZ plate read + one decision through vLLM from inside Isaac. Send after sensing, scenario_lib, agent.
from PIL import Image
spot.restart_from_default_state(np.zeros(3, dtype=np.float32))
world.step(render=False)
p, yaw, _, _ = full_pose()
results = {}
for drum_id in ('D23', 'D20'):  # C05, B05
    aim_from_estimate(PTZ, p, yaw, np.array([p[0], p[1], yaw]), plate_world(DRUMS[drum_id]))
    for _ in range(6):
        world.render()
    rgb = _rgb(PTZ)
    Image.fromarray(rgb).save(OUT / f'ptz_{drum_id}.png')
    results[drum_id] = cosmos_call('read_plate', rgb)
snapshot = {'readings': {'gamma_uSv_h': 9.0, 'hydrogen_ppm': 140, 'air_temp_c': 18.0, 'microphone_hiss_score': 0.8},
            'findings': [{'id': 'thermal_D24', 'kind': 'thermal_hotspot', 'drum': 'C06', 'surface_temp_c': 42.0, 'air_temp_c': 18.0}],
            'robot': {'estimated_position_m': [13.9, 6.38], 'current_action': 'inspect_C06', 'stationary': True},
            'actions': [{'id': 'continue_patrol', 'description': 'Resume the patrol'},
                        {'id': 'hold', 'description': 'Stop and monitor'},
                        {'id': 'retreat_alert_C06', 'description': 'Raise an alert for C06 and back off'}]}
results['decide'] = cosmos_call('decide', _rgb(onboard), snapshot)
(OUT / 'cosmos.json').write_text(json.dumps(results, indent=2, default=str))
print('[hot] cosmos probe', json.dumps({k: {kk: v.get(kk) for kk in ('drum_id', 'category', 'action_id', 'reason', 'error', 'latency_s')} for k, v in results.items()}), flush=True)
