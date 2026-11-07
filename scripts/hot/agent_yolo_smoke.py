# Short integrated YOLO/navigation/memory/HUD check; explicitly no Cosmos calls.
scene=copy.deepcopy(BASE_SCENE)
scene['job_drums']=['D10','D12']
a=Agent(0,'YOLO integration check | Cosmos intentionally off',scene,[(4.5,6.0),(6.0,6.0)])
a.look=np.array([DRUMS['D10']['x'],DRUMS['D10']['y']])
run_agent(a,'yolo_smoke',duration=3.0,use_cosmos=False,report_seconds=1.0)
assert state['yolo_vision'].calls>0,'No successful trained-detector requests'
assert all('rust_pct' not in entry['checks'].get('visual',{}) for entry in a.memory.drums.values()),'YOLO boxes must not masquerade as rust coverage measurements'
assert not any(entry.get('complete',False) for entry in a.memory.drums.values()),'A run without plate reads cannot claim every required check complete'
