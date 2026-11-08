scene=copy.deepcopy(BASE_SCENE)
scene['job_drums']=['D10','D12']
a=Agent(0,'Preflight | updated hall + YOLO26s + Cosmos',scene,[(4.5,6.0),(6.0,6.0)])
a.look=np.array([DRUMS['D10']['x'],DRUMS['D10']['y']])
run_agent(a,'cosmos_preflight',duration=2.0,use_cosmos=True,report_seconds=0.)
assert state['yolo_vision'].calls>0,'No trained YOLO inference'
assert any(d['source'].startswith('Cosmos') for d in a.decisions),'No successful Cosmos decision'
