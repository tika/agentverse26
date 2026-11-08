"""Load after agent.py. Full-store mission controller; no authored fault inputs."""
from mission_coverage import StoreRouter, CoverageLedger, AISLES
from pressure_screen import screen_visual_pressure
import os as _cov_os


class FullStoreMission:
    def __init__(self, drums, *, dwell_s=1.1, resume=None):
        self.drums={d['id']:d for d in drums}
        self.router=StoreRouter(drums,robot_radius=.70)
        self.ledger=CoverageLedger(drums)
        self.active=None; self.phase='choose'; self.finished=False
        self.dwell_s=dwell_s; self.since=0.; self.deadline=0.; self.last_checkpoint=-99.
        self.started=False; self.resume=resume; self.incident_started=None
        self.on_coverage_complete=None; self.planner_failures=0
        self.travelled_m=0.; self._previous=None
        self.previous_trails=[]
        self._visual_fallback_key=None

    def start(self,a,folder):
        self.folder=folder
        if self.resume:
            self.ledger.restore(self.resume['coverage'])
            a.memory.drums=self.resume['memory']
            a.decisions=self.resume.get('decisions',[])
            a.events=self.resume.get('events',[])
            self.previous_trails=self.resume.get('previous_trails',[])+[self.resume.get('estimated_trail',[])]
            a.trail=[]  # A resumed mission starts at the known dock; do not draw a teleport line.
            a.ids_read=self.resume.get('ids_read',{})
            a.findings=self.resume.get('findings',{})
            self.travelled_m=self.resume.get('travelled_m',0.)
        self.started=True
        a.event(0.,'Full-store job: all 28 drums; two distinct visual viewpoints required')

    def sync(self,a):
        self.ledger.sync(a.memory.drums)
        for drum_id,m in a.memory.drums.items():
            vis=m['checks'].get('visual',{}); th=m['checks'].get('thermal',{})
            result=screen_visual_pressure(bulge_observed=vis.get('bulge_observed',False),
                surface_c=th.get('surface_c'),ambient_c=th.get('surface_c',0)-th.get('delta_c',0),threshold_c=HEAT_RISE_C)
            m['pressure_screen']=result
            if result['suspected_pressurisation']:
                note=f"suspected pressurisation: bulge + heat ({result['delta_c']:+.1f} C); gas not confirmed"
                if note not in m['reasons']:m['reasons'].append(note)
                m['status']='bad'
            if m.get('deferred_reason'):
                m['reasons'].append('deferred: '+m['deferred_reason'])
            if vis.get('review_required'):
                m['reasons'].append('Cosmos visual assessment needs review; YOLO target box unavailable')
                if m['status']!='bad':m['status']='attention'
            if not m['complete'] and m['status']=='good':m['status']='inspecting'

    def observe(self,a,t,vision,est,rgb):
        if self._previous is not None:self.travelled_m+=float(np.linalg.norm(est[:2]-self._previous))
        self._previous=est[:2].copy()
        if self.phase!='capture' or not self.active or not vision or not vision['fresh'] or vision['status']!='ok':return
        matched=False
        for o in vision['associations']:
            if o['drum_id']!=self.active:continue
            matched=True
            x0,y0,x1,y1=o['box']
            added=self.ledger.visual(self.active,est,range_m=o['range_m'],area=(x1-x0)*(y1-y0),
                                     confidence=o['confidence'],time_s=t)
            if added:
                self.ledger.drums[self.active]['views'][-1]['source']='YOLO26s RGB + depth'
                Image.fromarray(rgb).save(OUT/f"view_{self.drums[self.active]['display_id']}_{len(self.ledger.drums[self.active]['views'])}.jpg",quality=90)
        fallback_key=(self.active,self.ledger.drums[self.active]['attempts'])
        if not matched and fallback_key!=self._visual_fallback_key:
            self._visual_fallback_key=fallback_key
            # The stainless assets are outside the detector training domain.
            # Ask the live VLM to inspect camera pixels; never substitute authored faults.
            h,w=rgb.shape[:2];crop=rgb[:,w//4:3*w//4]
            prompt=('Inspect only the large central foreground container in this RGB image. '
                    'Judge visible corrosion and visible bulging. Normal cylindrical curvature, hoops and reflections '
                    'are not bulges. Do not infer heat, gas or hidden faults. If the container is cropped or unclear, '
                    'set inspection_quality to insufficient. Return a JSON object with these fields: '
                    'object_visible (boolean), inspection_quality (good or insufficient), '
                    'corrosion_observed (boolean or null), bulge_observed (boolean or null), '
                    'reason (one sentence describing what you actually see). '
                    'Answer from the image, without copying these instructions. Null means you cannot judge.')
            start=_time.perf_counter()
            try:
                schema={'type':'object','properties':{'object_visible':{'type':'boolean'},
                    'inspection_quality':{'enum':['good','insufficient']},
                    'corrosion_observed':{'type':['boolean','null']},'bulge_observed':{'type':['boolean','null']},
                    'reason':{'type':'string'}},'required':['object_visible','inspection_quality','corrosion_observed','bulge_observed','reason'],
                    'additionalProperties':False}
                raw=cosmos_chat([front_image_part(crop,'cosmos_visual_fallback',(w//4,0,3*w//4,h)),{'type':'text','text':prompt}],max_tokens=256,schema=schema)
                answer=extract_json(raw)
                depth=state['front_frame']['depth'];patch=depth[h//3:2*h//3,2*w//5:3*w//5]
                vals=patch[np.isfinite(patch)&(patch>.2)&(patch<4)]
                quality=(answer.get('object_visible') is True and answer.get('inspection_quality')=='good' and
                         type(answer.get('corrosion_observed')) is bool and type(answer.get('bulge_observed')) is bool)
                # Coverage records the inspected camera evidence separately from
                # whether the model can confidently determine the condition.
                valid=answer.get('object_visible') is True and len(vals)>20
                if valid:
                    prior=a.memory.drums[self.active]['checks'].get('visual',{})
                    a.memory.record(self.active,'visual',t,
                        rust_observed=answer.get('corrosion_observed') is True or prior.get('rust_observed',False),
                        bulge_observed=answer.get('bulge_observed') is True or prior.get('bulge_observed',False),
                        detector='Cosmos RGB visual fallback (YOLO target box missing)',
                        coverage_measured=False,range_m=round(float(np.median(vals)),2),reason=answer.get('reason',''),
                        model_quality=answer.get('inspection_quality'),review_required=not quality or prior.get('review_required',False))
                    added=self.ledger.visual(self.active,est,range_m=float(np.median(vals)),area=crop.shape[0]*crop.shape[1],
                                              confidence=1.,time_s=t)
                    if added:
                        view=self.ledger.drums[self.active]['views'][-1]
                        view.update(source='Cosmos RGB visual fallback',confidence=None,
                                    quality_region='central RGB crop; VLM visibility plus measured depth',review_required=not quality)
                        Image.fromarray(crop).save(OUT/f"view_{self.drums[self.active]['display_id']}_{len(self.ledger.drums[self.active]['views'])}_cosmos.jpg",quality=90)
                    a.event(t,'Cosmos visual check '+self.drums[self.active]['display_id']+' (YOLO target box missing)')
                record=dict(t=t,drum=self.drums[self.active]['display_id'],valid=bool(valid),answer=answer,raw=raw,
                            latency_s=round(_time.perf_counter()-start,2))
            except Exception as error:
                record=dict(t=t,drum=self.drums[self.active]['display_id'],valid=False,error=str(error)[:200])
            with (OUT/'cosmos_visual_checks.jsonl').open('a') as output:output.write(json.dumps(record)+'\n')
        self.sync(a)

    def checkpoint(self,a,t,force=False):
        if not force and t-self.last_checkpoint<5:return
        self.sync(a)
        record=dict(coverage=self.ledger.snapshot(),memory=a.memory.drums,estimated_pose=a.nav.fused.tolist(),
                    estimated_trail=a.trail,active_drum=self.active,phase=self.phase,time_s=round(t,3),
                    travelled_m=round(self.travelled_m,3),previous_trails=self.previous_trails,
                    decisions=a.decisions,events=a.events,ids_read=a.ids_read,
                    findings=a.findings,planner_failures=self.planner_failures)
        text=json.dumps(record,indent=2,default=float)
        for path in (self.folder/'checkpoint.json',Path('/mission-runs/checkpoints')/(OUT.name+'.json')):
            path.parent.mkdir(parents=True,exist_ok=True)
            tmp=path.with_suffix('.tmp');tmp.write_text(text);tmp.replace(path)
        self.last_checkpoint=t

    def _alert(self,a,reading,est):
        candidates=[]
        for drum_id,f in a.findings.items():
            if f.get('kind')!='thermal_hotspot' or f.get('confidence')!='high':continue
            key=f['drum']; d=self.drums[key]
            if key in a.flagged or math.dist(est[:2],(d['x'],d['y']))>3:continue
            if reading.get('hydrogen_ppm',0)>H2_DETECTED_PPM or a.hiss_frames>=6:
                candidates.append({'id':'retreat_alert_'+d['display_id'],
                  'description':f"Retreat and stop: measured heat on {d['display_id']} {f['surface_temp_c']:.1f} C, "
                    f"H2 {reading.get('hydrogen_ppm',0):.0f} ppm near robot, hiss {a.hiss['hiss_score']:.2f}. "
                    'Gas source attribution and internal pressure remain unconfirmed.'})
        return candidates

    def choose(self,a,t,frame,reading):
        est=a.nav.fused
        alerts=self._alert(a,reading,est)
        options=[]
        if not alerts:
            for key,e in self.ledger.drums.items():
                if a.scene.get('mission_scope') and key not in a.scene['mission_scope']:continue
                if e['complete'] or e['deferred']:continue
                d=self.drums[key]; views=self.router.viewpoints(d)
                if len(e['views'])==0:goal=views[0]
                elif len(e['views'])==1:goal=views[1]
                else:goal=min(views,key=lambda p:math.dist(p,est[:2]))
                path=self.router.route(est[:2],goal)
                if path is None:
                    e['deferred']='No collision-free route to required viewpoint';continue
                cost=self.router.length(est[:2],path)
                name=('better_view_' if e['views'] else 'inspect_')+d['display_id']
                desc=(f"Inspect {d['display_id']} ({d['category']}); missing {', '.join(e['missing'])}; "
                      f"{len(e['views'])}/2 independent views, route {cost:.1f} m. "
                      'Reach its inspection viewpoint, collect RGB/depth/thermal, read plate. '
                      'Prefer finishing a nearby partially inspected drum before a long move.')
                options.append((cost,key,goal,path,dict(id=name,description=desc)))
            options.sort(key=lambda v:v[0])
        a.actions=alerts or [v[4] for v in options[:3]]
        if not a.actions:
            self.sync(a)
            counts=self.ledger.counts()
            if counts['complete']==counts['total'] and self.on_coverage_complete and self.incident_started is None:
                self.on_coverage_complete(a,t)
                self.incident_started=t;self.phase='watch';self.since=t
                a.status='MONITOR';a.hold=True
                a.event(t,'28/28 checks collected; monitoring new sensor change before final report')
                return
            a.status='MISSION COMPLETE' if not counts['deferred'] else 'COMPLETE / DEFERRED'
            a.hold=True;self.finished=True;self.phase='done'
            a.event(t,f"Mission ended: {counts['complete']}/28 complete, {counts['deferred']} deferred")
            return
        snapshot=snapshot_for(a,t,est,reading)
        snapshot['mission']={**self.ledger.counts(),'goal':'Analyse every drum with two independent visual viewpoints',
                             'active_drum':self.active and self.drums[self.active]['display_id'],
                             'distance_walked_m':round(self.travelled_m,1)}
        answer=cosmos_call('decide',frame,snapshot,structured=True) if a.use_cosmos else {}
        valid=answer.get('valid') and answer.get('action_id') in {v['id'] for v in a.actions}
        first_attempt=None
        if not valid and a.use_cosmos:
            first_attempt=answer
            snapshot['validation_feedback']='Previous response was invalid. Copy exactly one of these action IDs: '+', '.join(v['id'] for v in a.actions)
            answer=cosmos_call('decide',frame,snapshot,structured=True)
            valid=answer.get('valid') and answer.get('action_id') in {v['id'] for v in a.actions}
        choice=answer if valid else dict(action_id=a.actions[0]['id'],reason='Planner unavailable; nearest valid mission task')
        source='Cosmos Reason 2' if valid else 'rules (Cosmos unavailable)'
        if not valid:self.planner_failures+=1
        record=dict(t=round(t,2),action_id=choice['action_id'],reason=choice.get('reason',''),source=source,
                    latency_s=round(answer.get('latency_s',0)+(first_attempt or {}).get('latency_s',0),2),
                    offered=[v['id'] for v in a.actions],raw=answer.get('raw','')[-600:],
                    rejected_attempt=first_attempt,planner_error=answer.get('error'))
        a.decisions.append(record);a.cosmos=record
        a.event(t,('Cosmos: ' if valid else 'Rules: ')+choice['action_id'])
        a.action=dict(id=choice['action_id'],since=t);a.last_decision_t=t;a.pending_decision=False
        if choice['action_id'].startswith('retreat_alert_'):
            key=next(k for k,d in self.drums.items() if choice['action_id'].endswith('_'+d['display_id']))
            d=self.drums[key];a.flagged.append(key)
            y=AISLES[d['row']]
            goals=[(float(np.clip(est[0]+dx,1,19)),y) for dx in (-3.5,3.5)]
            paths=[(self.router.length(est[:2],p),p) for g in goals if (p:=self.router.route(est[:2],g))]
            a.route=[np.array(w,float) for w in min(paths,key=lambda q:q[0])[1]] if paths else []
            a.status='RETREAT';a.hold=False;self.phase='retreat';self.since=t
            self.deadline=t+30;a.event(t,'ALERT: retreating; inspection coverage retained')
        else:
            option=next(v for v in options if v[4]['id']==choice['action_id'])
            _,self.active,self.goal,path,_=option
            a.route=[np.array(w,float) for w in path]
            d=self.drums[self.active];a.look=np.array([d['x'],d['y']])
            a.scene['look_height']=d['height']*.52
            a.face=None;a.status='NAVIGATE';a.hold=False;self.phase='move';self.since=t
            self.deadline=t+self.router.length(est[:2],path)/SPEED_NEAR_DRUMS*2.5+15
            self.ledger.drums[self.active]['attempts']+=1
        self.checkpoint(a,t,True)

    def tick(self,a,t,frames,perception,reading,p,yaw):
        self.sync(a)
        if abs(a.nav.roll)>.85 or abs(a.nav.pitch)>.85:
            a.status='POSTURE STOP';a.hold=True;self.finished=True
            a.event(t,'IMU posture limit: stopped; remaining drums stay incomplete')
            self.checkpoint(a,t,True);return
        if reading['dose_rate_uSv_h']>DOSE_BACKOFF:
            a.status='DOSE STOP';a.hold=True;self.finished=True
            a.event(t,'Dose threshold: stopped; remaining drums stay incomplete')
            self.checkpoint(a,t,True);return
        if self.phase=='choose':self.choose(a,t,frames['first'],reading)
        elif self.phase=='move':
            if not a.route:
                self.phase='align';self.since=t;a.hold=False;a.status='ALIGN FRONT CAMERA'
            elif t>self.deadline:
                self.ledger.drums[self.active]['deferred']='Navigation did not converge before timeout'
                a.event(t,'Deferred '+self.drums[self.active]['display_id']+': navigation timeout')
                self.phase='choose';a.route=[];a.hold=True
        elif self.phase=='align':
            d=self.drums[self.active];est=a.nav.fused
            error=wrap(math.atan2(d['y']-est[1],d['x']-est[0])-est[2])
            if abs(error)<.06 and abs(a.nav.gyro)<.15:
                self.phase='capture';self.since=t;a.hold=True;a.status='INSPECT'
                d=self.drums[self.active]
                ident=a.memory.drums[self.active]['checks'].get('id',{})
                if ident.get('result')!='match' and ident.get('tries',0)<3:
                    read_plate_for(a,d,t,p,yaw)
                    self.sync(a)
            elif t-self.since>12:
                self.ledger.drums[self.active]['deferred']='Body could not align fixed front camera'
                self.phase='choose';a.hold=True
        elif self.phase=='capture' and t-self.since>=self.dwell_s:
            self.sync(a);entry=self.ledger.drums[self.active]
            a.event(t,f"{self.drums[self.active]['display_id']}: {len(entry['views'])}/2 valid angles; "+
                    ('inspection complete' if entry['complete'] else 'missing '+', '.join(entry['missing'])))
            if not entry['complete'] and entry['attempts']>=4:
                entry['deferred']='Required sensor evidence missing after four viewpoint attempts'
            self.phase='choose';a.hold=True
        elif self.phase=='watch':
            if t-self.since>=4:
                self.choose(a,t,frames['first'],reading)
        elif self.phase=='retreat':
            if not a.route or t>self.deadline:
                a.status='ALERT';a.hold=True;self.finished=True;self.phase='done'
                a.event(t,'Retreat complete; stopped with final coverage and alert')
        self.checkpoint(a,t)

    def command(self,a,est):
        if a.hold:return np.zeros(3,dtype=np.float32)
        if self.phase=='align':
            d=self.drums[self.active]
            error=wrap(math.atan2(d['y']-est[1],d['x']-est[0])-est[2])
            return np.array([0.,0.,float(np.clip(1.5*error,-.65,.65))],dtype=np.float32)
        if a.route and np.linalg.norm(est[:2]-a.route[0])<.14:a.route.pop(0)
        if not a.route:return np.zeros(3,dtype=np.float32)
        delta=a.route[0]-est[:2];dist=float(np.linalg.norm(delta));heading=math.atan2(delta[1],delta[0])
        error=wrap(heading-est[2])
        if dist<.45:
            c,s=math.cos(est[2]),math.sin(est[2])
            vx=.9*(c*delta[0]+s*delta[1]);vy=.9*(-s*delta[0]+c*delta[1]);wz=0.
        else:
            vx=SPEED_NEAR_DRUMS*max(0,math.cos(error)) if abs(error)<.5 else 0.
            vy=0.;wz=float(np.clip(1.5*error,-.8,.8))
        return np.array([vx,vy,wz],dtype=np.float32)

    def final_report(self,a,report):
        self.sync(a)
        for d in report['drums']:
            key=next(k for k,v in self.drums.items() if v['display_id']==d['drum'])
            m=a.memory.drums[key]
            d.update(complete=m['complete'],missing=m['missing'],grade=m['status'],notes=m['reasons'],
                     valid_viewpoints=m['valid_viewpoints'],inspection_state=m['inspection_state'],
                     deferred_reason=m['deferred_reason'],pressure_screen=m['pressure_screen'])
        report.update(coverage=self.ledger.snapshot(),travelled_estimate_m=round(self.travelled_m,2),
                      trajectory_source='LiDAR/IMU/encoder estimated pose',planner_failures=self.planner_failures)
        report['not_inspected']=[self.drums[k]['display_id'] for k,v in self.ledger.drums.items() if not v['complete']]
        review=sum(m['checks'].get('visual',{}).get('review_required',False) for m in a.memory.drums.values())
        report['visual_assessments_needing_review']=review
        counts=self.ledger.counts()
        report['summary']=(f"Observation coverage {counts['complete']}/28 drums (ID, thermal and two distinct visual viewpoints); "
            f"{counts['deferred']} deferred, {review} model visual assessments need review. "
            'Coverage completion does not mean the drum is fault-free or its condition is confidently resolved. '+factual_summary(report))
        report['summary']=report['summary'].replace('drums fully inspected:','drums with required observations:')
        return report

    def draw_map(self,canvas,a,t):
        im=Image.new('RGB',(640,360),'#14212a');dr=ImageDraw.Draw(im)
        def xy(p):return (18+float(p[0])*30.2,322-float(p[1])*23.2)
        for y in (2,6,10):
            x0,y0=xy((0,y+.85));x1,y1=xy((20,y-.85));dr.rectangle((x0,y0,x1,y1),fill='#24343b')
        dr.rectangle((*xy((0,12)),*xy((20,0))),outline='#71858c',width=1)
        for trail in self.previous_trails:
            if len(trail)>1:dr.line([xy(q) for q in trail],fill='#287f8a',width=2)
        if len(a.trail)>1:dr.line([xy(q) for q in a.trail],fill='#36dded',width=3)
        if a.route:dr.line([xy(a.nav.fused)]+[xy(q) for q in a.route],fill='#eef1ec',width=2)
        for key,d in self.drums.items():
            m=a.memory.drums[key];e=self.ledger.drums[key];u,v=xy((d['x'],d['y']))
            color=STATUS_COLORS.get(m['status'],(94,110,122)) if e['complete'] else (73,88,100)
            if e['deferred']:color=(158,98,36)
            dr.rounded_rectangle((u-14,v-10,u+14,v+10),radius=3,fill=color,
                                 outline='white' if key==self.active else None,width=2)
            dr.text((u-12,v-8),d['display_id'],font=FONT[14],fill='#0a1119' if e['complete'] else 'white')
        x,y=xy(a.nav.fused);h=a.nav.fused[2]
        dr.ellipse((x-5,y-5,x+5,y+5),fill='#ffc55e',outline='black',width=1)
        dr.line((x,y,x+12*math.cos(h),y-10*math.sin(h)),fill='#ffc55e',width=3)
        counts=self.ledger.counts()
        dr.rectangle((0,0,640,34),fill='#0d131b')
        dr.text((12,5),'WAREHOUSE MAP | estimated pose + full visited trail',font=FONT[16],fill='white')
        dr.rectangle((0,326,640,360),fill='#0d131b')
        dr.text((10,329),f"COVERAGE {counts['complete']}/28  PENDING {counts['pending']}  DEFERRED {counts['deferred']}  |  cyan = visited",font=FONT[14],fill='white')
        canvas.paste(im,(1280,360))
        draw=ImageDraw.Draw(canvas)
        draw.rectangle((10,945,475,972),fill='#111822')
        draw.text((16,946),f"Coverage {counts['complete']}/28 | walked {self.travelled_m:.1f} m | target "+
                  (self.drums[self.active]['display_id'] if self.active else '-'),font=FONT[16],fill='#36dded')
        if self.active:
            vis=a.memory.drums[self.active]['checks'].get('visual',{})
            source='Cosmos RGB fallback' if vis.get('detector','').startswith('Cosmos') else 'YOLO26s RGB'
            draw.text((500,944),'Visual check: '+source,font=FONT[14],fill='#9fb2c4')
            pressure=a.memory.drums[self.active].get('pressure_screen',{})
            if pressure.get('suspected_pressurisation'):
                draw.text((500,973),f"BULGE + HEAT {pressure['delta_c']:+.1f} C: suspected pressure",font=FONT[14],fill='#ff9f9f')

    def report_card(self,last,r):
        card=Image.new('RGB',(1920,1080),'#101c26');d=ImageDraw.Draw(card)
        counts=self.ledger.counts()
        d.text((50,32),'FULL WAREHOUSE INSPECTION REPORT',font=FONT[34],fill='white')
        d.text((50,87),f"{counts['complete']}/28 observation coverage | {counts['deferred']} deferred | {r['visual_assessments_needing_review']} need model review | end: {r['round_status']}",font=FONT[22],fill='#36dded')
        for i,item in enumerate(r['drums']):
            x=50+(i//14)*950;y=160+(i%14)*48
            color=STATUS_COLORS.get(item['grade'],(120,135,145))
            done='CHECKED' if item['complete'] else 'DEFERRED' if item.get('deferred_reason') else 'PENDING'
            text=f"{item['drum']} {item['category']}  {done}  {item.get('valid_viewpoints',0)}/2 views  {item['grade'].upper()}"
            d.text((x,y),text,font=FONT[22],fill=color)
            note=item.get('deferred_reason') or ('; '.join(item['notes'])) or 'ID + thermal + visual checks collected'
            d.text((x,y+25),note[:99],font=FONT[14],fill='#b7c9d5')
        e=r['environment']
        d.text((50,900),f"Peak H2 {e['max_h2_ppm']} ppm | gamma {e['max_gamma_uSv_h']} uSv/h | alerts: {', '.join(r['alerts']) or 'none'}",font=FONT[22],fill='white')
        d.text((50,945),'Pressure screen: visible bulge AND surface >= ambient + 5 C -> suspected pressurisation; internal gas not confirmed.',font=FONT[18],fill='#ffc55e')
        d.text((50,985),'Live YOLO26s + Cosmos; simulated sensor channels. Missing evidence is reported rather than replaced with authored faults.',font=FONT[18],fill='#9fb2c4')
        return card
