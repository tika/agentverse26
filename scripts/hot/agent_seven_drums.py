"""Short live mission: seven nearby drums, with the entire 28-drum map retained.

Run after sensing, scenario_lib, prepare_robot_visuals, presentation_view, yolo,
agent and coverage_mission. No pre-recorded detections or planner responses.
"""
class SevenDrumMission(FullStoreMission):
    def __init__(self,drums):
        super().__init__(drums,dwell_s=.65)
        # Choose scope by known inventory geometry only, never defect state.
        nearby=[d for d in drums if d['row'] in ('B','C')]
        self.scope=[d['id'] for d in sorted(nearby,key=lambda d:math.dist((4.,6.),(d['x'],d['y'])))[:7]]

    def choose(self,a,t,frame,reading):
        remaining=[k for k in self.scope if not self.ledger.drums[k]['complete'] and not self.ledger.drums[k]['deferred']]
        if not remaining:
            self.finished=True;self.phase='done';a.status='SEVEN-DRUM DEMO COMPLETE';a.hold=True
            a.event(t,'Seven-drum demo ended; the other 21 drums were outside this recording scope')
            return
        super().choose(a,t,frame,reading)

    def final_report(self,a,report):
        report=super().final_report(a,report)
        report['recording_scope']=[self.drums[k]['display_id'] for k in self.scope]
        report['recording_scope_complete']=sum(self.ledger.drums[k]['complete'] for k in self.scope)
        report['recording_scope_deferred']=sum(bool(self.ledger.drums[k]['deferred']) for k in self.scope)
        report['recording_scope_note']='Seven nearby drums; all 28 remain on map. Unfinished evidence remains unfinished.'
        return report


scene=copy.deepcopy(BASE_SCENE)
scene.update(job_drums=[d['id'] for d in inventory],coverage_mission=True,show_spills=True)
a=Agent(7,'Seven drums | fixed front camera | YOLO26s + Cosmos',scene,[])
a.mission=SevenDrumMission(inventory)
a.scene['mission_scope']=a.mission.scope
a.look=np.array([DRUMS[a.mission.scope[0]]['x'],DRUMS[a.mission.scope[0]]['y']])
state['save_detector_inputs']=False
run_agent(a,'seven_drums_front',duration=170.,use_cosmos=True,report_seconds=3.)
assert state['yolo_vision'].calls>0,'No live YOLO requests'
assert any(d['source']=='Cosmos Reason 2' for d in a.decisions),'No live Cosmos decisions'
