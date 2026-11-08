"""Short main-branch hall experiment: live NVIDIA grounding and Cosmos planning."""
class LocateAnythingMission(FullStoreMission):
    def __init__(self,drums):
        super().__init__(drums,dwell_s=1.15)
        # Authored demo positions only. No fault labels/profiles enter the planner.
        self.scope=[d['id'] for d in drums if d['display_id'] in ('B01','C02','C03','C04')]

    def choose(self,a,t,frame,reading):
        if all(self.ledger.drums[k]['complete'] or self.ledger.drums[k]['deferred'] for k in self.scope):
            self.finished=True;self.phase='done';a.status='LOCATEANYTHING DEMO ENDED';a.hold=True;return
        super().choose(a,t,frame,reading)

    def final_report(self,a,report):
        report=super().final_report(a,report)
        report.update(perception_backend='NVIDIA LocateAnything-3B (zero-shot)',
            confidence_available=False,visual_fallback_enabled=False,
            recording_scope=[self.drums[k]['display_id'] for k in self.scope],
            note='Observation coverage is separate from classification accuracy. Unscored proposals require review.')
        return report


assert state['yolo_vision'].__class__.__name__=='LocateAnythingVision','Wrong perception backend'
scene=copy.deepcopy(BASE_SCENE)
scene.update(job_drums=[d['id'] for d in inventory],coverage_mission=True,show_spills=True,output_size=(1280,720))
a=Agent(31,'NVIDIA LocateAnything-3B + Cosmos | zero-shot, unscored',scene,[])
a.mission=LocateAnythingMission(inventory);a.scene['mission_scope']=a.mission.scope
a.look=np.array([DRUMS[a.mission.scope[0]]['x'],DRUMS[a.mission.scope[0]]['y']])
state['save_detector_inputs']=False
run_agent(a,'locateanything_demo',duration=105.,use_cosmos=True,report_seconds=3.)
assert state['yolo_vision'].calls>0,'No LocateAnything requests'
assert state['yolo_vision'].failures==0,'LocateAnything API failures occurred; inspect logs'
