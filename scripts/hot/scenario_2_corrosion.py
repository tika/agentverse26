# Scenario 2/3: corroded LLW drum C02. Detect corrosion, stop at standoff, smear-swab the drum base
# for removable alpha (a breach releases particulate that gamma cannot see), then flag corrosion on C04.
# Run: python tools/hot_hall.py run scripts/hot/scenario_lib.py scripts/hot/scenario_2_corrosion.py
scene = copy.deepcopy(BASE_SCENE)
m = Mission(2, 'Corroded drum  |  smear swab for alpha', scene, [(15.0, 6.0)])
C02, C04 = DRUMS['D10'], DRUMS['D12']


def setup(m):
    # Scenario truth: through-wall corrosion at C02 has released particulate onto the floor at its base.
    m.sensor.inject_leak('D10', alpha_bq_cm2=0.8, beta_gamma_bq_cm2=8.0)
    m.sensor.set_surface_chemistry('D10', chloride_mg_m2=14)


def bearing_error(target, p, yaw):
    return abs(wrap(math.atan2(target[1] - p[1], target[0] - p[0]) - yaw))


def step(m, t, p, yaw, perception, reading):
    phase = m.data.setdefault('phase', 'patrol')
    limits = m.sensor.config['thresholds']['swab_bq_cm2']
    centre = np.array([C02['x'], C02['y']])
    if phase in ('patrol', 'resume'):
        m.look = p[:2] + [1.6, 1.0]  # Inspection pan towards the row C drums.
    if phase == 'patrol' and perception['corrosion_px'].get('D10', 0) > 150:
        m.data['phase'] = 'approach'
        m.status, m.speed = 'INVESTIGATE', 0.45
        m.route = [np.array([C02['x'] - 0.15, 6.35])]
        m.face = m.look = centre
        m.event(t, f"Corrosion on C02 ({perception['corrosion_px']['D10']} px)!")
        m.message = 'Corrosion seen on C02 shell. Slowing, moving to standoff for a smear sample'
    elif phase == 'approach' and not m.route and bearing_error(centre, p, yaw) < 0.2:
        m.data['phase'] = 'sampling'
        m.status, m.hold = 'SAMPLING', True
        direction = (p[:2] - centre) / np.linalg.norm(p[:2] - centre)
        contact = centre + (C02['radius'] + 0.03) * direction
        m.swab_contact = contact
        m.sensor.start_swab((float(contact[0]), float(contact[1]), 0.0), t, robot_stopped=True)
        m.swab_text = 'smear at C02 base...'
        m.event(t, 'Stopped. Virtual swab arm: smear at C02 base')
        m.message = 'Robot stationary. Smear swab of drum base: alpha, beta/gamma, chloride'
    elif phase == 'sampling':
        result = m.sensor.poll_swab(t)
        if result['status'] == 'complete':
            positive = result['alpha_bq_cm2'] > limits['alpha'] or result['beta_gamma_bq_cm2'] > limits['beta_gamma']
            m.swab_text = (f"a {result['alpha_bq_cm2']:.2f}  b/g {result['beta_gamma_bq_cm2']:.1f} Bq/cm2  "
                           f"Cl {result.get('chloride_mg_m2', 0):.0f} mg/m2")
            m.event(t, f"Smear: alpha {result['alpha_bq_cm2']:.2f} > {limits['alpha']} Bq/cm2!")
            m.flagged.append('D10')
            m.data['phase'] = 'resume'
            m.status, m.hold, m.speed = 'ALERT', False, 0.75
            m.swab_contact, m.face = None, None
            m.route = [np.array([15.0, 6.0])]
            m.message = ('Removable alpha at C02 base: possible breach through corrosion. Quarantine, '
                         'overpack review' if positive else 'Smear below limits; corrosion logged')
            m.event(t, 'C02 quarantined, report sent. Resuming patrol')
    elif phase == 'resume' and perception['corrosion_px'].get('D12', 0) > 150:
        m.data['phase'] = 'second'
        m.flagged.append('D12')
        m.route = [np.array([15.0, 6.0])]
        m.event(t, 'Corrosion on C04, smear queued!')
        m.message = 'C02 quarantined. Corrosion also on C04: logged, smear queued. Continuing to ILW rows'
    elif phase == 'second':
        m.look = None


run_mission(m, step, 'scenario_2_corrosion', setup=setup)
