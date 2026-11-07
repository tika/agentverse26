# Scenario 3/3: ILW drum C06 heating from an internal reaction (cf. WIPP 2014, Idaho 2018).
# Thermal flags it at range, Spot closes to a 2 m standoff, H2 at the vent and a hiss on the
# microphone confirm, then it raises an alert and backs off.
# Run: python tools/hot_hall.py run scripts/hot/scenario_lib.py scripts/hot/scenario_3_hot_drum.py
C06 = DRUMS['D24']
VENT = [C06['x'] + 0.11, C06['y'], 1.2]
scene = copy.deepcopy(BASE_SCENE)
scene['drum_offsets_c'] = {'D24': 24.0}
scene['gas_vents'] = [{'position_m': VENT, 'hydrogen_ppm': 900.0}]
scene['acoustic'] = [{'kind': 'hiss', 'position_m': VENT, 'time_s': 0.0, 'duration_s': 60.0, 'amplitude': 0.12}]
m = Mission(3, 'Hot drum  |  thermal + hydrogen + acoustic', scene, [(17.0, 6.0)])
STANDOFF = np.array([C06['x'] - 1.7, 6.15])


def step(m, t, p, yaw, perception, reading):
    phase = m.data.setdefault('phase', 'patrol')
    centre = np.array([C06['x'], C06['y']])
    temps = perception['drum_temps']
    ambient = m.scene['ambient_c']
    h2 = reading.get('hydrogen_ppm', 0.0)
    if phase == 'patrol' and temps.get('D24', ambient) > ambient + 8:
        m.data['phase'] = 'approach'
        m.status, m.speed = 'INVESTIGATE', 0.85
        m.route = [STANDOFF]
        m.face = m.look = centre
        m.flagged.append('D24')
        m.event(t, f"Thermal: C06 at {temps['D24']:.0f} C, +{temps['D24'] - ambient:.0f} C vs air!")
        m.message = 'C06 much warmer than its neighbours. Closing to 2 m standoff to sample gas at the vent'
    elif phase == 'approach' and not m.route:
        m.data['phase'] = 'confirm'
        m.data['confirm_t'] = t
        m.status, m.hold = 'SAMPLING', True
        m.event(t, 'At standoff, stationary gas and acoustic sample')
        m.message = 'Stationary at 2 m. Sampling H2 near the vent and listening for venting'
    elif phase == 'confirm' and t - m.data['confirm_t'] > 1.2:
        m.data['phase'] = 'retreat'
        m.event(t, f"H2 {h2:.0f} ppm > {m.scene['h2_limit']:g}, vent hiss {m.mic_db:.0f} dBFS!")
        m.event(t, 'ALERT raised: possible runaway reaction in C06')
        m.status, m.hold, m.speed = 'RETREAT', False, 0.8
        m.route = [np.array([C06['x'] - 5.0, 6.0])]
        m.message = 'Heat + hydrogen + venting at C06: alert sent, area cleared. Backing off to 5 m'
    elif phase == 'retreat' and not m.route:
        m.data['phase'] = 'hold'
        m.status, m.hold = 'ALERT', True
        m.event(t, 'Holding at 5 m, monitoring C06 temperature trend')
        m.message = 'Holding at safe distance. Monitoring C06 thermal trend for responders'


run_mission(m, step, 'scenario_3_hot_drum')
