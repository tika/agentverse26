# In-worker end-to-end smoke test: every service and sensor a mission depends on, checked once.
# Run after sensing.py, scenario_lib.py, yolo.py, agent.py. Writes OUT/smoke.json; raises if anything fails.
import os as _os

checks = []


def smoke(name, fn):
    try:
        checks.append({'check': name, 'ok': True, 'detail': str(fn())[:200]})
    except Exception as error:
        checks.append({'check': name, 'ok': False, 'detail': f'{type(error).__name__}: {error}'[:300]})


def _env():
    missing = [k for k in ('COSMOS_URL', 'VLLM_API_KEY', 'DETECTOR_API_URL', 'DETECTOR_API_KEY', 'DETECTOR_API_SECRET')
               if not _os.environ.get(k)]
    assert not missing, f'missing in worker: {missing}'
    return 'all service variables present'


def _cosmos_text():
    answer = cosmos_chat([{'type': 'text', 'text': 'Answer with only JSON: {"ok": true}'}], max_tokens=64)
    assert extract_json(answer).get('ok') is True, answer[-120:]
    return 'chat completion OK'


spot.restart_from_default_state(np.zeros(3, dtype=np.float32))
for _ in range(round(0.5 / spot.physics_dt)):  # Advance sim time so the 10 Hz LiDAR completes a scan.
    spot.step(spot.physics_dt, np.zeros(3, dtype=np.float32))
    world.step(render=False)
world.render()
p, yaw, _, _ = full_pose()
estimate = np.array([p[0], p[1], yaw])
plate_drum = min((d for d in inventory if d['row'] in STANDOFF), key=lambda d: math.dist(p[:2], (d['x'], d['y'])))


def _plate():
    aim_from_estimate(PTZ, p, yaw, estimate, plate_world(plate_drum))
    for _ in range(6):
        world.render()
    answer = cosmos_call('read_plate', _rgb(PTZ))
    assert 'error' not in answer, answer.get('error')
    expected = plate_drum['display_id']
    assert answer.get('drum_id') == expected, f"read {answer.get('raw_read')} at {expected}"
    return f"{answer['drum_id']} {answer['category']} in {answer['latency_s']:.1f}s"


def _decide():
    snapshot = {'readings': {'air_temp_c': 18.0}, 'findings': [], 'inspection_progress': {},
                'actions': [{'id': 'continue_patrol', 'description': 'Resume the round'},
                            {'id': 'hold', 'description': 'Stand still'}]}
    answer = cosmos_call('decide', _rgb(onboard), snapshot)
    assert answer.get('valid'), answer.get('reason') or answer.get('error')
    return f"{answer['action_id']} in {answer['latency_s']:.1f}s"


# YOLO26s was trained on painted (LLW-style) drums; check it on the nearest painted drum.
yolo_drum = min((d for d in inventory if d['category'] == 'LLW' and d['row'] in STANDOFF),
                key=lambda d: math.dist(p[:2], (d['x'], d['y'])))


def _yolo():
    _aim(onboard, p + [0.62, 0, 0.3], np.array([yolo_drum['x'], yolo_drum['y'], 0.5]))
    for _ in range(6):
        world.render()
    vision = YoloVision().observe(_rgb(onboard), onboard.get_depth(), p, yaw, estimate, 0.0)
    assert vision['status'] == 'ok', vision.get('error')
    mapped = [o['display_id'] for o in vision['associations']]
    assert yolo_drum['display_id'] in mapped, f"aimed at {yolo_drum['display_id']}, mapped {mapped}"
    return f"{len(vision['detections'])} boxes, mapped to {mapped}, {vision['wall_seconds']:.1f}s"


def _sensors():
    lidar_frame = state['real_sensors'][0].get_current_frame().get('IsaacCreateRTXLidarScanBuffer', {})
    points = np.asarray(lidar_frame.get('data', np.zeros((0, 3)))).reshape(-1, 3)
    imu = state['real_sensors'][1].get_data()
    assert len(points) > 1000, f'only {len(points)} LiDAR points'
    return f"LiDAR {len(points)} pts, IMU az {imu['linear_acceleration'][2]:.1f} m/s2"


smoke('worker environment', _env)
smoke('Cosmos text call', _cosmos_text)
smoke('Cosmos plate read', _plate)
smoke('Cosmos decision', _decide)
smoke('YOLO API + map association', _yolo)
smoke('LiDAR + IMU', _sensors)
(OUT / 'smoke.json').write_text(json.dumps(checks, indent=2))
for c in checks:
    print(f"[hot] smoke {'PASS' if c['ok'] else 'FAIL'} {c['check']}: {c['detail']}", flush=True)
if not all(c['ok'] for c in checks):
    raise RuntimeError('smoke test failed: ' + ', '.join(c['check'] for c in checks if not c['ok']))
