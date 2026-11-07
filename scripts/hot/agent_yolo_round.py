# World authoring only. YOLO must discover visual faults from camera pixels;
# Cosmos receives measured findings, never these authored source settings.
scene=copy.deepcopy(BASE_SCENE)
scene['job_drums']=[d['id'] for d in inventory if d['category']=='LLW' and d['row'] in STANDOFF]
target=DRUMS['D12']  # C04, painted LLW, in the same asset domain as detector training.
vent=[target['x'],target['y'],.65]
scene['drum_offsets_c']={'D12':24.0}
scene['gas_vents']=[{'position_m':vent,'hydrogen_ppm':900.0}]
scene['acoustic']=[{'kind':'hiss','position_m':vent,'time_s':10.0,'duration_s':60.0,'amplitude':.02}]
a=Agent(1,'28-drum hall | YOLO26s + Cosmos inspection',scene,[(x,6.0) for x in (4.5,6.0,7.5,8.5)])
a.look=np.array([DRUMS['D10']['x'],DRUMS['D10']['y']])
run_agent(a,'yolo_cosmos_round',duration=32.0)
