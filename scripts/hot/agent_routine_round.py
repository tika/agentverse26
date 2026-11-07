# Routine ILW round using the hall's existing drum conditions and no injected incident.
scene = copy.deepcopy(BASE_SCENE)
patrol = [(x, AISLE_Y) for x in (12.0, 14.0, 16.0, 16.6)]
a = Agent(1, 'Routine ILW inspection  |  rows B and C, drums 05-07', scene, patrol)
run_agent(a, 'routine_round', duration=28.0)
