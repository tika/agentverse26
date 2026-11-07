# Validation: walk the centre aisle with C06 hot and venting H2; log what the real sensors and
# estimators report against truth. Send after sensing.py and scenario_lib.py.
scene = copy.deepcopy(BASE_SCENE)
C06 = DRUMS['D24']
VENT = [C06['x'] + 0.11, C06['y'], 1.2]
scene['drum_offsets_c'] = {'D24': 24.0}
scene['gas_vents'] = [{'position_m': VENT, 'hydrogen_ppm': 900.0}]
sources = [{'kind': 'hiss', 'position_m': VENT, 'time_s': 0.0, 'duration_s': 60.0, 'amplitude': 0.02}]
config = copy.deepcopy(load_config())
config['gas_vents'] = scene['gas_vents']
world_sensors = SensorWorld(inventory, config)
show_spills(False)

zero = np.zeros(3, dtype=np.float32)
spot.restart_from_default_state(zero)
world.step(render=False)
p, yaw, _, _ = full_pose()
nav = RealNav([p[0], p[1], yaw])  # Known start pose (docking point); everything after is estimated.
gas = LaggedGas()
dt = spot.physics_dt
stride = max(1, round(1 / (FPS * dt)))
frame_dt = stride * dt
rows = []
for index in range(int(20 * FPS)):
    t = index * frame_dt
    p, yaw, roll, pitch = full_pose()
    scene['look'] = p[:2] + [2.0, 1.0]
    place_cameras(p, yaw, scene)
    world.render()
    world.render()
    nav.lidar_update(frame_dt)
    reading = world_sensors.sample(np.array([p[0], p[1], 0.6]), t)
    scene['ambient_c'] = reading['temperature_c']
    perception = perceive(scene)
    depth = onboard.get_depth()
    findings = thermal_findings(perception['thermal'], depth, reading['temperature_c'], (p, yaw), nav.fused)
    audio = robot_audio((p[0], p[1], 0.6), t, frame_dt, sources, nav.touchdowns)
    quiet = robot_audio((p[0], p[1], 0.6), t, frame_dt, [], nav.touchdowns)
    lagged = gas.update(reading, frame_dt)
    odom_err, fused_err, yaw_err = nav.errors(p, yaw)
    rows.append({'t': round(t, 3), 'truth': [round(v, 3) for v in (p[0], p[1], math.degrees(yaw))],
                 'odom': [round(v, 3) for v in (*nav.odom[:2], math.degrees(nav.odom[2]))],
                 'fused': [round(v, 3) for v in (*nav.fused[:2], math.degrees(nav.fused[2]))],
                 'odom_err_m': round(odom_err, 3), 'fused_err_m': round(fused_err, 3), 'yaw_err_deg': round(yaw_err, 2),
                 'icp_inliers': round(nav.icp_inliers, 3), 'icp_rms': round(nav.icp_rms, 3), 'lidar_points': nav.scan_points,
                 'imu_gyro_z': round(nav.gyro, 4), 'imu_accel': [round(v, 2) for v in nav.accel],
                 'roll_deg': round(math.degrees(nav.roll), 2), 'pitch_deg': round(math.degrees(nav.pitch), 2),
                 'leg_speed': round(nav.speed, 3), 'touchdowns': len(nav.touchdowns),
                 'thermal_findings': findings, 'hiss': hiss_detector(audio),
                 'hiss_control': hiss_detector(quiet), 'h2_raw': round(reading.get('hydrogen_ppm', 0), 1),
                 'h2_sensor': round(lagged.get('hydrogen_ppm', 0), 1), 'gamma': round(reading['dose_rate_uSv_h'], 2),
                 'dist_to_vent_m': round(math.dist(p[:2], VENT[:2]), 2)})
    command = np.array([0.75, 0.0, float(np.clip(1.6 * wrap(0 - yaw), -0.9, 0.9))], dtype=np.float32)
    if p[0] > 16.5:
        command = zero
    for k in range(stride):
        spot.step(dt, command)
        world.step(render=False)
        nav.physics_update(dt, t + (k + 1) * dt)
(OUT / 'validation.jsonl').write_text(''.join(json.dumps(r, default=float) + '\n' for r in rows))
print('[hot] validation rows', len(rows), flush=True)
