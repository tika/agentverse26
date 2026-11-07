# The demo job: Spot's inspection round of the ILW rows (B05-B07, C05-C07), ending in a report.
# World (unknown to the robot): C06 is heating from an internal reaction and venting hydrogen.
# Run: python tools/hot_hall.py run scripts/hot/sensing.py scripts/hot/scenario_lib.py scripts/hot/agent.py scripts/hot/agent_ilw_round.py
C06 = DRUMS['D24']
VENT = [C06['x'] + 0.11, C06['y'], 1.2]
scene = copy.deepcopy(BASE_SCENE)
scene['drum_offsets_c'] = {'D24': 24.0}
scene['gas_vents'] = [{'position_m': VENT, 'hydrogen_ppm': 900.0}]
scene['acoustic'] = [{'kind': 'hiss', 'position_m': VENT, 'time_s': 0.0, 'duration_s': 60.0, 'amplitude': 0.02}]
a = Agent(1, 'ILW inspection round  |  rows B and C, drums 05-07', scene, [(16.6, AISLE_Y)])
run_agent(a, 'ilw_round')
