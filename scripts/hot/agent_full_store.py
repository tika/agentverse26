# World authoring only: the planner receives measurements, not these fault settings.
scene=copy.deepcopy(BASE_SCENE)
scene.update(job_drums=[d['id'] for d in inventory],coverage_mission=True)
# Make authored bulged barrels visibly warmer; the agent must discover both cues.
scene['drum_offsets_c']={d['id']:12.0 for d in inventory if 'bulge' in d.get('faults',[])}
a=Agent(28,'Full store | YOLO26s + Cosmos | 28 drums',scene,[])
a.mission=FullStoreMission(inventory,resume=state.pop('coverage_resume',None))


def after_round_incident(robot,t):
    # A new incident after coverage tests adaptation without ending the round early.
    key=robot.mission.active
    drum=DRUMS[key]
    vent=[drum['x'],drum['y'],.65]
    robot.scene['drum_offsets_c'][key]=24.
    robot.scene['gas_vents']=[dict(position_m=vent,hydrogen_ppm=900.)]
    robot.sensor.config['gas_vents']=robot.scene['gas_vents']
    robot.scene['acoustic']=[dict(kind='hiss',position_m=vent,time_s=t,duration_s=60.,amplitude=.02)]
    print('[hot] world event: new heat/gas source activated after coverage',flush=True)


a.mission.on_coverage_complete=after_round_incident
first=min(inventory,key=lambda d:math.dist((1.3,2.),(d['x'],d['y'])))
a.look=np.array([first['x'],first['y']])
run_agent(a,'full_store',duration=540.,use_cosmos=True,report_seconds=6.)
assert state['yolo_vision'].calls>0,'No live YOLO requests'
assert any(d['source']=='Cosmos Reason 2' for d in a.decisions),'No live Cosmos decisions'
