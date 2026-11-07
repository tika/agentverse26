# Scenario 1/3: routine patrol of a dry store. Navigation, ID plates against inventory, environment.
# Run: python tools/hot_hall.py run scripts/hot/scenario_lib.py scripts/hot/scenario_1_patrol.py
scene = copy.deepcopy(BASE_SCENE)
scene['records']['D11'] = 'C03 ILW'  # Planted inventory error: C03 is an LLW drum.
m = Mission(1, 'Routine patrol  |  navigation + inventory check', scene, [(17.6, 6.0)])


def step(m, t, p, yaw, perception, reading):
    if 'started' not in m.data:
        m.data['started'] = True
        m.event(t, 'Patrol start: centre aisle, LLW then ILW rows')
    if reading['dose_rate_uSv_h'] > 7.5 and 'controlled' not in m.data:
        m.data['controlled'] = True
        m.event(t, f"Entered ILW zone: {reading['dose_rate_uSv_h']:.1f} uSv/h")
    flags = [DRUMS[d]['display_id'] for d in m.flagged]
    if not m.route:
        m.status, m.hold = 'COMPLETE', True
        m.message = f'Patrol complete. {len(m.ids_read)} IDs read; record mismatch: {", ".join(flags) or "none"}'
        if 'done' not in m.data:
            m.data['done'] = True
            m.event(t, 'Patrol complete, report queued')
    elif flags:
        m.message = f'Patrolling. Inventory mismatch flagged at {", ".join(flags)}; continuing'
    else:
        m.message = 'Patrolling centre aisle, reading ID plates on both rows'


run_mission(m, step, 'scenario_1_patrol')
