"""Stationary physical inspection clip; load the recording setup first.

Uses the fixed +15 degree body mount, latest YOLO and the approved CANIS HUD.
By default this is a camera/model test. Load ambiguity_cosmos.py immediately
before this file to run the two-drum Cosmos evidence acquisition scenario.
"""
ambiguity_planner = globals().pop('rigid_ambiguity_planner', None)
inspection_course = state.pop('rigid_inspection_course', False)
TILT_NAME = ('canis_inspection_course' if inspection_course else
             'canis_ambiguous_view' if ambiguity_planner else 'canis_middle_upper_original_layout')
run_dir=OUT/TILT_NAME
frames_dir=run_dir/'frames';frames_dir.mkdir(parents=True,exist_ok=True)
(run_dir/'inputs').mkdir(exist_ok=True)
TARGET_IDS=['D30','D32']
target=next(d for d in inventory if d['id']==TARGET_IDS[0])
goal=(target['x']-1.3,AISLE_Y)
goal_yaw=_math.atan2(target['y']-goal[1],target['x']-goal[0])
mission.update(phase='walk',hold=None,look=None)
TEST_IDS=set(TARGET_IDS)
rec.update(status={},finding={},best={},views={},first={},detections=[],telemetry=[],decisions=[],stills=[],yolo_calls=0,yolo_fail=0)
rec['banners']=[(0.,'Two drum test: A-L-01-T2 then A-L-01-T3, fixed mount +15 deg','info')]
boxes=[];tbox=None;_input_native=None;_input_rgb=None
posture.leave()

class DeepRigidPosture(RigidPosture):
    def targets(self,elevation):
        # Same joint PD and leg IK, expanded only for this controlled sim test.
        elevation=float(np.clip(elevation,-.20,_math.radians(30)))
        r=_rz1(self.yaw)@_ry1(-elevation)
        desired={leg:r.T@(pt-self.base) for leg,pt in self.feet.items()}
        for leg,idx in self.idx.items():
            q=self.target[idx].copy()
            for _ in range(16):
                err=desired[leg]-_leg_fk(leg,q)
                if np.linalg.norm(err)<.0003:break
                eps=.0001
                j=np.column_stack([(_leg_fk(leg,q+np.eye(3)[i]*eps)-_leg_fk(leg,q-np.eye(3)[i]*eps))/(2*eps) for i in range(3)])
                delta=np.linalg.solve(j.T@j+np.eye(3)*1e-6,j.T@err)
                q+=np.clip(delta,-.06,.06)
            self.target[idx]=q

posture=DeepRigidPosture()
_rigid_samples=[];tilt_samples=[];tilt_frames=0;recording_t=0.
_still_time=0.;cmd_s=_np2.zeros(3,dtype=_np2.float32)
dt=spot.physics_dt;stride=max(1,round(1/(24*dt)));FPS=24;FRAME_DT=stride*dt
onboard.prim.GetAttribute('focalLength').Set(20.955/(2*_math.tan(_math.radians(55))))
FX=float(onboard.get_intrinsics_matrix()[0,0])*640/720
stop_reason=None
next_view = 'Start with middle tier'
detector_unavailable = None
first_upper_pitch = 2. if ambiguity_planner else 5.
course_ambient_c = 19.
course_spike_c = 34.
course_moves = []

def tilt_frame(label):
    global _rigid_pose,_last_front,recording_t,tilt_frames
    bp,bq,roll,pitch,yaw=body_angles();r=rigid_rotation(bq)
    e=bp+r@_np2.array([.60,0,.12]);_rigid_pose=(e,r)
    cam_r=r@MOUNT_BIAS_R;_rigid_pose=(e,cam_r)
    mission['eye_view']=(e,e+cam_r[:,0]*3);mission['pitch']=-pitch
    aim(chase,_np2.array([max(bp[0]-2.4,.6),AISLE_Y,3.2]),bp+[.6,0,.2])
    world.render();crop=grab(onboard)
    canvas=bias_compose(recording_t,bp,grab(chase),Image.fromarray(crop),boxes,tbox)
    draw=ImageDraw.Draw(canvas);draw.rectangle((0,64,1280,100),fill=BLK)
    detail = next_view if ambiguity_planner else 'fixed mount +15 deg, 110-deg lens'
    if inspection_course:
        draw.rectangle((210, 0, 1450, 58), fill='#10151c')
        draw.text((224, 14), 'INSPECTION COURSE   /   WALK TO A SECOND VIEW', font=FB[24], fill=YEL)
    draw.text((16,71),label+' | '+detail,font=FB[20],fill=YEL)
    canvas.save(frames_dir/f'{tilt_frames:05d}.jpg',quality=88)
    tilt_frames+=1;recording_t+=FRAME_DT
    return crop


def move_to_second_view(drum, start_xy):
    """Use Spot's walking controller to move across the aisle and face the drum."""
    posture.leave()
    goal = start_xy + _np2.array([0.25, -0.85])
    aim_at = _np2.array([drum['x'], drum['y']])
    settled = 0
    for _ in range(7 * FPS):
        position, yaw = pose()
        delta = goal - position[:2]
        distance = float(_np2.linalg.norm(delta))
        bearing = _math.atan2(*(aim_at - position[:2])[::-1])
        yaw_error = _math.remainder(bearing - yaw, _math.tau)
        velocity = delta * min(1.5, .60 / max(distance, .01))
        c, s = _math.cos(yaw), _math.sin(yaw)
        command = _np2.array([c * velocity[0] + s * velocity[1],
                             -s * velocity[0] + c * velocity[1],
                             _np2.clip(1.8 * yaw_error, -.65, .65)], dtype=_np2.float32)
        settled = settled + 1 if distance < .14 and abs(yaw_error) < .10 else 0
        if settled:
            command = zero
        for _ in range(stride):
            spot.step(dt, command)
            world.step(render=False)
        tilt_frame(f"{drum['display_id']} | WALK TO SECOND VIEW")
        if settled >= FPS // 3:
            for _ in range(round(1.75 * FPS)):
                for __ in range(stride):
                    spot.step(dt, zero)
                    world.step(render=False)
                tilt_frame(f"{drum['display_id']} | SETTLE AT SECOND VIEW")
            end, _ = pose()
            return {'from_xy_m': start_xy.tolist(), 'to_xy_m': end[:2].tolist(),
                    'distance_m': float(_np2.linalg.norm(end[:2] - start_xy))}
    raise RuntimeError('Spot did not settle at the second viewpoint')

def check_posture():
    bp,bq,roll,pitch,yaw=body_angles()
    q=posture.art.get_dof_positions().numpy().reshape(-1)
    r=rigid_rotation(bq)
    error=max(float(np.linalg.norm(bp+r@_leg_fk(leg,q[idx])-posture.feet[leg])) for leg,idx in posture.idx.items())
    safe=bool(bp[2]>=.40 and abs(roll)<=_math.radians(8) and error<=.055)
    return dict(stable=safe,pitch_deg=-_math.degrees(pitch),roll_deg=_math.degrees(roll),height_m=float(bp[2]),max_foot_anchor_error_m=error,body_xyz=bp.tolist())

MOUNT_BIAS_Q=_np2.array([_math.cos(_math.radians(7.5)),0,-_math.sin(_math.radians(7.5)),0])
MOUNT_BIAS_R=rigid_rotation(MOUNT_BIAS_Q)

def bias_compose(t,p,chase_rgb,crop_rgb,boxes,tbox):
    canvas=_orig_compose(t,p,chase_rgb,crop_rgb,boxes,tbox)
    native=_input_native if mission.get('hold') and _input_native is not None else _last_front
    front=Image.fromarray(native);fd=ImageDraw.Draw(front)
    if mission.get('hold'):
        for box in boxes:
            if not box['target'] and not ambiguity_planner:continue
            b=box['box'];bb=[280+b[0]*720/640,b[1]*720/640,280+b[2]*720/640,b[3]*720/640]
            if not box['target']:
                fd.rectangle(bb,outline=(145,158,171),width=2)
                continue
            fd.rectangle(bb,outline=(70,220,150),width=4)
            fd.text((bb[0]+4,bb[1]+4),f"{box['cls']} {box['conf']:.2f}",font=F[18],fill=(70,220,150),stroke_width=1,stroke_fill=BLK)
    cov=frame_coverage(target)
    tb=cov['projected_bbox']
    if tb:fd.rectangle([280+tb[0]*720/640,tb[1]*720/640,280+tb[2]*720/640,tb[3]*720/640],outline=YEL,width=2)
    # Keep the existing header, caption, counters, right panel, map and log.
    # Fit the entire native camera image into the existing gap between the
    # phase caption and counters. No camera pixels are cropped or covered.
    from PIL import ImageOps
    image_region=(0,100,1280,780)
    contained=ImageOps.contain(front,(1280,680),Image.Resampling.LANCZOS)
    canvas.paste(Image.new('RGB',(1280,680),BLK),(0,100))
    canvas.paste(contained,((1280-contained.width)//2,100+(680-contained.height)//2))
    corner=Image.new('RGB',(620,620),BLK)
    corner.paste(Image.fromarray(chase_rgb).resize((620,349)),(0,118))
    cd=ImageDraw.Draw(corner);bp,bq,roll,pitch,yaw=body_angles()
    cd.text((12,12),'PHYSICAL ROBOT VIEW',font=FB[20],fill=YEL)
    cd.text((12,48),f'Body pitch {-_math.degrees(pitch):+.1f} deg',font=F[18],fill=WHITE)
    cd.text((12,80),'Fixed camera mount +15 deg',font=F[18],fill=YEL)
    tier_label='Middle' if target['location']['tier']==2 else 'Top'
    cd.text((12,490),f"{tier_label} drum box in frame: {cov['bbox_in_frame_fraction']:.0%}",font=F[18],fill=WHITE)
    cd.text((12,524),'No gimbal or camera tracking',font=F[18],fill=WHITE)
    if ambiguity_planner and boxes:
        cd.text((12,558),f"{sum(not box['target'] for box in boxes)} other boxes | candidates only",
                font=F[18],fill='#9fb2c4')
    if ambiguity_planner and rec['decisions']:
        latest = next((d for d in reversed(rec['decisions']) if 'planned' in d), None)
        if latest:
            count = len(latest['observation']['barrels'])
            cd.text((12,589),f"Planner considered {count} barrel records",
                    font=F[18],fill=YEL)
    canvas.paste(corner,(1290,64));d=ImageDraw.Draw(canvas)
    d.rectangle((1290,64,1910,684),outline=YEL,width=2)
    d.rectangle((0,1048,1920,1080),fill='#111822')
    planner_label = f'{ambiguity_planner.model} chooses follow-up | framing gate controls verdict' if ambiguity_planner else 'rules; no Cosmos'
    detector_label = 'YOLO26s unavailable; framing only' if detector_unavailable else 'YOLO26s'
    d.text((16,1054),'FIXED +15 deg mount | physical body pitch | '+detector_label+' | '+planner_label,font=F[14],fill='#9fb2c4')
    xyz,q=onboard.get_local_pose(camera_axes='world')
    if _np2.linalg.norm(xyz-_np2.array([.6,0,.12]))>1e-6 or abs(float(_np2.dot(q,MOUNT_BIAS_Q)))<1-1e-6:raise RuntimeError('Fixed biased mount moved')
    return canvas

course_layer = None
try:
    if inspection_course:
        from pxr import Sdf, Usd, UsdGeom
        course_layer = Sdf.Layer.CreateAnonymous('canis-inspection-course.usda')
        stage.GetSessionLayer().subLayerPaths.insert(0, course_layer.identifier)
        with Usd.EditContext(stage, course_layer):
            for drum in inventory:
                if _math.hypot(drum['x'] - target['x'], drum['y'] - target['y']) > 1.6:
                    UsdGeom.Imageable(stage.GetPrimAtPath(drum['prim_path'])).MakeInvisible()
    # Initialize the standing pose before filming; all recorded pitch comes
    # from leg torques, never root-pose or camera-pose animation.
    spot.restart_from_default_state(zero)
    for _ in range(round(1.5/dt)):spot.step(dt,zero);world.step(render=False)
    bp,yaw=pose()
    goal_yaw=_math.atan2(target['y']-bp[1],target['x']-bp[0])
    for _ in range(round(3/dt)):
        bp,yaw=pose();err=_math.remainder(goal_yaw-yaw,2*_math.pi)
        spot.step(dt,_np2.array([0,0,float(_np2.clip(err*1.4,-.5,.5))],dtype=_np2.float32));world.step(render=False)
    for _ in range(round(2/dt)):spot.step(dt,zero);world.step(render=False)
    onboard.set_local_pose(translation=_np2.array([.60,0,.12]),orientation=MOUNT_BIAS_Q,camera_axes='world')
    world.render()
    mission.update(phase='look',look={'drum':target['id'],'views':[],'pass':'side'})
    print('[hot] TILT_STANCE '+_json.dumps({'body':body_angles()[0].tolist(),'joint_vel_norm':float(np.linalg.norm(spot.articulation.get_dof_velocities().numpy()))}),flush=True)
    pending = [('D30',0.),('D32',first_upper_pitch)]
    if not ambiguity_planner:
        pending.append(('D32',10.))
    while pending:
        target_id,pitch_goal = pending.pop(0)
        next_view = ('NEXT: upper tier' if pending else 'NEXT: finish round') if pitch_goal != 10. else 'RECHECK: upper tier'
        target=next(d for d in inventory if d['id']==target_id)
        mission.update(phase='look',hold=None,look={'drum':target['id'],'views':[],'pass':'side'})
        _input_native=None;boxes=[];tbox=None
        if inspection_course and pitch_goal == 10. and course_moves:
            next_view = 'THERMAL SPIKE: change ground position'
            course_moves[-1].update(move_to_second_view(target, _np2.asarray(course_moves[-1]['from_xy_m'])))
        hold=[]
        for _ in range(int(2.8/FRAME_DT)):
            for __ in range(stride):posture.step(dt,_math.radians(pitch_goal));world.step(render=False)
            state_check=check_posture();hold.append(state_check)
            rgb=tilt_frame(f"{target['display_id']} | TILT TARGET {pitch_goal:.0f} deg")
            if not state_check['stable']:
                stop_reason=f'Posture limit at requested {pitch_goal} deg: {state_check}'
                break
        if stop_reason:
            tilt_samples.append(dict(requested_pitch_deg=pitch_goal,accepted=False,stop_reason=stop_reason,samples=hold))
            rec['banners'].append((recording_t,'Posture limit reached; returning to neutral','blocked'))
            if inspection_course:
                rec['status'][target_id] = 'Suspect'
                rec['decisions'].append(dict(t=recording_t, drum=target_id,
                    decision='defer_incomplete_recheck', source='posture guard'))
            print('[hot] TILT_LIMIT '+stop_reason,flush=True)
            break
        coverage=frame_coverage(target)
        native=_last_front.copy()
        model_input,result=Image.fromarray(rgb),{}
        if detector_unavailable is None:
            from urllib.error import URLError
            try:
                model_input,result=_orig_yolo(rgb)
            except (URLError, TimeoutError) as exc:
                if not ambiguity_planner:
                    raise
                detector_unavailable = f'HTTP {exc.code}' if hasattr(exc, 'code') else type(exc).__name__
                print(f'[hot] Detector unavailable ({detector_unavailable}); testing framing only',flush=True)
            else:
                if result.get('best_sha256')!='ba4c80bcb99f6152d8ee0a6523151c4640ad67d727431b9ec846235dcf895b6a':
                    raise RuntimeError('Wrong detector checkpoint')
        tb=coverage['projected_bbox'];others=all_boxes(*mission['eye_view']);boxes=[];matches=[]
        associated = {}
        for det in result.get('condition_detections',[]):
            b=det['bbox_xyxy'];cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
            owners=[(iou(b,clip(bb)),j) for j,bb in others.items() if bb[0]<=cx<=bb[2] and bb[1]<=cy<=bb[3]]
            overlap, owner = max(owners, default=(0., None))
            matched=bool(tb and owner == target['id'] and overlap >= .3)
            boxes.append(dict(box=b,cls=det['class_name'],conf=det['confidence'],target=matched))
            if matched:matches.append(det)
            if overlap >= .3 and (owner not in associated or det['confidence'] > associated[owner]['confidence']):
                associated[owner] = det
        bp,bq,roll,pitch,yaw=body_angles()
        sample=dict(drum_id=target['id'],display_id=target['display_id'],tier=target['location']['tier'],simulation_time_s=recording_t,requested_pitch_deg=pitch_goal,accepted=True,actual_pitch_deg=-_math.degrees(pitch),
            body_xyz=bp.tolist(),**coverage,matched_predictions=matches,model_sha=result.get('best_sha256'),
            max_abs_roll_deg=max(abs(x['roll_deg']) for x in hold),min_body_height_m=min(x['height_m'] for x in hold),
            max_foot_anchor_error_m=max(x['max_foot_anchor_error_m'] for x in hold),samples=hold)
        tilt_samples.append(sample)
        rec['yolo_calls']+=1
        voted=max(matches,key=lambda x:x['confidence']) if matches else None
        follow_up_selected = False
        clear_first_view = bool(coverage['full_in_frame'] and voted and
                                voted['class_name'] == 'normal' and voted['confidence'] >= .5)
        needs_evidence = (not coverage['full_in_frame'] or
                          (not detector_unavailable and (not voted or voted['confidence'] < .5)))
        first_upper_view = target_id == 'D32' and pitch_goal == first_upper_pitch
        if ambiguity_planner and ((first_upper_view and (needs_evidence or inspection_course)) or
                                  (inspection_course and target_id == 'D30' and pitch_goal == 0.)):
            planned = 'inspect_upper_tier' if target_id == 'D30' else 'finish_round'
            observation = {'drum': target['display_id'], 'full_in_frame': coverage['full_in_frame'],
                           'frame_fraction': coverage['bbox_in_frame_fraction'], 'detector_prediction': voted,
                           'planned_next': planned, 'barrels': []}
            for drum_id in dict.fromkeys([*TARGET_IDS, *associated]):
                drum = BY_ID[drum_id]
                prediction = associated.get(drum_id)
                framing = frame_coverage(drum)
                observation['barrels'].append({
                    'id': drum['display_id'], 'role': 'target' if drum_id == target_id else 'context',
                    'inventory_category': drum['category'], 'rack_tier': drum['location']['tier'],
                    'range_m': round(float(np.linalg.norm(bp[:2] - [drum['x'], drum['y']])), 2),
                    'projected_fraction_in_crop': round(framing['bbox_in_frame_fraction'], 3),
                    'visual_prediction': (
                        {'condition': prediction['class_name'], 'confidence': prediction['confidence']}
                        if prediction else None),
                    'inspection_status': rec['status'].get(drum_id, 'unresolved'),
                })
            observation['provenance'] = {
                'inventory_category': 'registered inventory, not OCR',
                'geometry': 'simulator pose and inventory map',
                'visual_prediction': 'live YOLO on the current crop, associated by projected overlap',
                'surface_temperature_c': 'not sampled', 'local_gamma_uSv_h': 'not sampled',
                'local_hydrogen_ppm': 'not sampled',
            }
            if inspection_course:
                observation['thermal'] = {'ambient_c': course_ambient_c,
                    'apparent_surface_c': course_spike_c if first_upper_view else course_ambient_c,
                    'source': 'scripted simulation fixture'}
                observation['provenance']['surface_temperature_c'] = 'scripted simulation fixture'
                observation['offered_actions'] = (
                    ['recheck_xy', 'defer_for_operator'] if first_upper_view else
                    ['continue_inspection', 'defer_for_operator'] if clear_first_view else ['defer_for_operator'])
            decision = ambiguity_planner(rgb, observation)
            rec['decisions'].append(dict(t=recording_t, drum=target_id, planned=planned,
                                         observation=observation, **decision))
            follow_up_selected = decision['decision'] != 'continue_inspection'
            if decision['decision'] in ('recheck_higher', 'recheck_xy'):
                pending.insert(0, (target_id, 10.))
                if decision['decision'] == 'recheck_xy':
                    course_moves.append({'drum': target['display_id'], 'from_xy_m': bp[:2].tolist()})
                    next_view = '34 C SURFACE / 19 C AIR: walk to second view'
                else:
                    next_view = 'PLAN CHANGE: recheck this drum'
            elif follow_up_selected:
                rec['status'][target_id] = 'Suspect'
                next_view = 'DEFER: drum needs operator review'
            else:
                next_view = 'FIRST LOOK SUFFICIENT: continue'
            rec['banners'].append((recording_t, 'Cosmos: '+next_view, 'info'))
        if follow_up_selected:
            pass
        elif not coverage['full_in_frame']:
            text=f"{target['display_id']} partial view -> look higher"
            if ambiguity_planner:
                text=f"{target['display_id']} partial view -> defer"
                rec['status'][target_id]='Suspect'
            rec['banners'].append((recording_t,text,'info'))
            rec['decisions'].append(dict(t=recording_t,drum=target['id'],decision='defer' if ambiguity_planner else 'look_higher',source='framing rule',full_in_frame=False))
        elif detector_unavailable:
            rec['status'][target_id]='Suspect'
            rec['banners'].append((recording_t,f"{target['display_id']} framed | condition unresolved",'info'))
        else:
            if voted and voted['confidence']>=.5:
                status='OK' if voted['class_name']=='normal' else 'Suspect'
                rec['status'][target['id']]=status
                rec['finding'][target['id']]='none' if status=='OK' else voted['class_name']
                rec['best'][target['id']]=voted['confidence']
                text=f"{target['display_id']} {voted['class_name']} {voted['confidence']:.2f} -> {status}"
                rec['banners'].append((recording_t,text,'cleared' if status=='OK' else 'suspect'))
                rec['decisions'].append(dict(t=recording_t,drum=target['id'],decision='visual_'+status,source='YOLO plus framing rule',full_in_frame=True,prediction=voted))
            else:
                rec['status'][target['id']]='Suspect'
                rec['banners'].append((recording_t,f"{target['display_id']} unclear -> SUSPECT",'suspect'))
        if ambiguity_planner and pitch_goal == 10.:
            next_view = ('FRAME ACQUIRED: condition unresolved' if detector_unavailable and coverage['full_in_frame']
                         else 'RECHECK COMPLETE: '+rec['status'].get(target_id,'Unresolved'))
        if inspection_course and target_id == 'D32':
            sample['thermal_fixture'] = {'ambient_c': course_ambient_c, 'apparent_surface_c': course_spike_c}
            if pitch_goal == 10.:
                rec['status'][target_id] = 'Suspect'
                next_view = 'HEAT CUE PERSISTS: flag for operator'
                rec['decisions'].append(dict(t=recording_t, drum=target_id, decision='flag_persistent_heat',
                                             source='scripted thermal fixture plus inspection rule'))
        evidence_stem = f'tilt_{int(pitch_goal)}'
        if inspection_course:
            evidence_stem = f'{target_id}_{evidence_stem}'
        Image.fromarray(native).save(run_dir/'inputs'/f'{evidence_stem}_front.png')
        model_input.save(run_dir/'inputs'/f'{evidence_stem}_model.png')
        (run_dir/'inputs'/f'{evidence_stem}_response.json').write_text(_json.dumps(result,indent=2))
        _input_native=native;tbox=tb;mission['hold']={'final':False}
        for _ in range(2*FPS):
            for __ in range(stride):posture.step(dt,_math.radians(pitch_goal));world.step(render=False)
            tilt_frame(f"{target['display_id']} | BODY TILT {-_math.degrees(pitch):.1f} deg - RESULT")
        mission['hold']=None;_input_native=None;boxes=[]
        print('[hot] TILT '+_json.dumps({k:v for k,v in sample.items() if k!='samples'}),flush=True)
finally:
    # Leave the experiment in a known standing state. Do not attempt blind
    # IK recovery after a guard trip (the cause of the earlier flip).
    if course_layer is not None:
        stage.GetSessionLayer().subLayerPaths.remove(course_layer.identifier)
    posture.leave()
    onboard.set_local_pose(translation=_np2.array([.60,0,.12]),orientation=_np2.array([1.,0,0,0]),camera_axes='world')
    spot.restart_from_default_state(zero)
    for _ in range(round(1.5/dt)):spot.step(dt,zero);world.step(render=False)

(run_dir/'tilt_report.json').write_text(_json.dumps(dict(targets=[{'drum_id':i,'display_id':CODE[i],'tier':BY_ID[i]['location']['tier']} for i in TARGET_IDS],camera_path=_BODY_CAMERA_PATH,
    fixed_mount_xyz=[.6,0,.12],fixed_mount_pitch_up_deg=15,fixed_mount_quat=MOUNT_BIAS_Q.tolist(),horizontal_fov_deg=110,vertical_fov_deg=77.552142222,
    samples=tilt_samples,stop_reason=stop_reason,returned_to_neutral=True,
    canvas=[1920,1080],camera_display_bounds=[0,100,1280,780],camera_fit='contain',camera_crop=False,
    decisions=rec['decisions'],status=rec['status'],ground_repositions=course_moves,
    method='Fixed +15 degree mount; body pitch from leg IK and joint torques.',
    planner=ambiguity_planner.model if ambiguity_planner else None,
    detector_unavailable=detector_unavailable),indent=2))
if ambiguity_planner:
    lines=['# CANIS inspection evidence', '', 'Warehouse-v3 simulation. Two planned visual checks.', '',
           '| Drum | View | In frame | Top matched detection | Final status |',
           '|---|---:|---:|---|---|']
    for sample in tilt_samples:
        if not sample['accepted']:
            continue
        best=max(sample['matched_predictions'],key=lambda x:x['confidence'],default=None)
        finding=f"{best['class_name']} ({best['confidence']:.0%})" if best else 'None matched'
        status=rec['status'].get(sample['drum_id'],'Unresolved')
        lines.append(f"| {sample['display_id']} | {sample['requested_pitch_deg']:.0f}° | "
                     f"{sample['bbox_in_frame_fraction']:.0%} | {finding} | {status} |")
    lines.extend(['', '## Decision log', ''])
    for decision in rec['decisions']:
        transition=f"{decision['planned']} → " if 'planned' in decision else ''
        lines.append(f"- {decision['t']:.1f}s · {CODE[decision['drum']]} · "
                     f"{transition}{decision['decision']} ({decision['source']})")
    unresolved=[CODE[drum] for drum in TARGET_IDS if rec['status'].get(drum) != 'OK']
    lines.extend(['', 'Operator review: '+(', '.join(unresolved) or 'No visual follow-up flagged on the two planned drums.'),
                  'Other drums were outside this test.'])
    if inspection_course:
        lines.append('Thermal cue: scripted apparent surface reading of 34 C against 19 C air. Dose was not sampled.')
        for move in course_moves:
            lines.append(f"Ground reposition for {move['drum']}: {move['distance_m']:.2f} m.")
    else:
        lines.append('Dose and thermal condition were not assessed.')
    if detector_unavailable:
        lines.append(f'YOLO26s unavailable ({detector_unavailable}). Framing was assessed; drum condition remains unresolved.')
    (run_dir/'report.md').write_text('\n'.join(lines)+'\n')
_ff=(_glob.glob('/usr/local/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*') or [_shutil.which('ffmpeg')])[0]
_sp.run([_ff,'-y','-loglevel','error','-framerate',str(FPS),'-i',str(frames_dir/'%05d.jpg'),'-c:v','libx264','-pix_fmt','yuv420p','-crf','20','-movflags','+faststart',str(run_dir.with_suffix('.mp4'))],check=True)
for f in frames_dir.glob('*.jpg'):f.unlink()
frames_dir.rmdir()
print('[hot] TWO_DRUM_VIDEO_COMPLETE '+str(rec['status']),flush=True)
