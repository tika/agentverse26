# Short live preflight: real navigation and two angles for the first drum; all 28 remain on the map.
class CoveragePreflight(FullStoreMission):
    def tick(self,*args,**kwargs):
        super().tick(*args,**kwargs)
        robot=args[0]
        if self.ledger.counts()['complete']>=1:
            self.finished=True;robot.status='PREFLIGHT PASS';robot.hold=True


scene=copy.deepcopy(BASE_SCENE)
scene.update(job_drums=[d['id'] for d in inventory],coverage_mission=True)
a=Agent(29,'Coverage preflight | live YOLO + Cosmos',scene,[])
a.mission=CoveragePreflight(inventory)
a.look=np.array([DRUMS['D01']['x'],DRUMS['D01']['y']])
run_agent(a,'coverage_preflight',duration=20.,use_cosmos=True,report_seconds=0.)
assert a.mission.ledger.counts()['complete']>=1,'No two-angle completed inspection'
assert all(d['source']=='Cosmos Reason 2' for d in a.decisions),'Planner fallback occurred'
