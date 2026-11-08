"""Stationary physical inspection clip; load the recording setup first.

Uses the fixed +15 degree body mount, latest YOLO and the approved CANIS HUD.
This is a camera/model test; it does not invoke Cosmos or run an aisle mission.
"""
TILT_NAME='canis_one_drum_original_layout'
run_dir=OUT/TILT_NAME
frames_dir=run_dir/'frames';frames_dir.mkdir(parents=True,exist_ok=True)
(run_dir/'inputs').mkdir(exist_ok=True)
target=next(d for d in inventory if d['id']=='D32')
goal=(target['x']-1.3,AISLE_Y)
goal_yaw=_math.atan2(target['y']-goal[1],target['x']-goal[0])
mission.update(phase='walk',hold=None,look=None)
TEST_IDS={target['id']}
rec.update(status={},finding={},best={},views={},first={},detections=[],telemetry=[],decisions=[],stills=[],yolo_calls=0,yolo_fail=0)
rec['banners']=[(0.,'One drum test: A-L-01-T3, fixed camera mount +15 deg','info')]
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
    draw.text((16,71),label+' | fixed mount +15 deg, 110-deg lens',font=FB[20],fill=YEL)
    canvas.save(frames_dir/f'{tilt_frames:05d}.jpg',quality=88)
    tilt_frames+=1;recording_t+=FRAME_DT
    return crop

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
            if not box['target']:continue
            b=box['box'];bb=[280+b[0]*720/640,b[1]*720/640,280+b[2]*720/640,b[3]*720/640]
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
    cd.text((12,490),f"Top drum box in frame: {cov['bbox_in_frame_fraction']:.0%}",font=F[18],fill=WHITE)
    cd.text((12,524),'No gimbal or camera tracking',font=F[18],fill=WHITE)
    canvas.paste(corner,(1290,64));d=ImageDraw.Draw(canvas)
    d.rectangle((1290,64,1910,684),outline=YEL,width=2)
    d.rectangle((0,1048,1920,1080),fill='#111822')
    d.text((16,1054),'FIXED +15 deg mount | physical body pitch 0-10 deg | calibrated projection | live experimental YOLO26s | rules; no Cosmos',font=F[14],fill='#9fb2c4')
    xyz,q=onboard.get_local_pose(camera_axes='world')
    if _np2.linalg.norm(xyz-_np2.array([.6,0,.12]))>1e-6 or abs(float(_np2.dot(q,MOUNT_BIAS_Q)))<1-1e-6:raise RuntimeError('Fixed biased mount moved')
    return canvas

try:
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
    for pitch_goal in (0.,5.,10.):
        hold=[]
        for _ in range(int(2.8/FRAME_DT)):
            for __ in range(stride):posture.step(dt,_math.radians(pitch_goal));world.step(render=False)
            state_check=check_posture();hold.append(state_check)
            rgb=tilt_frame(f'PHYSICAL TILT TARGET {pitch_goal:.0f} deg')
            if not state_check['stable']:
                stop_reason=f'Posture limit at requested {pitch_goal} deg: {state_check}'
                break
        if stop_reason:
            tilt_samples.append(dict(requested_pitch_deg=pitch_goal,accepted=False,stop_reason=stop_reason,samples=hold))
            rec['banners'].append((recording_t,'Posture limit reached; returning to neutral','blocked'))
            print('[hot] TILT_LIMIT '+stop_reason,flush=True)
            break
        coverage=frame_coverage(target)
        native=_last_front.copy()
        model_input,result=_orig_yolo(rgb)
        if result.get('best_sha256')!='ba4c80bcb99f6152d8ee0a6523151c4640ad67d727431b9ec846235dcf895b6a':raise RuntimeError('Wrong detector')
        tb=coverage['projected_bbox'];others=all_boxes(*mission['eye_view']);boxes=[];matches=[]
        for det in result.get('condition_detections',[]):
            b=det['bbox_xyxy'];cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
            owners=[(iou(b,clip(bb)),j) for j,bb in others.items() if bb[0]<=cx<=bb[2] and bb[1]<=cy<=bb[3]]
            matched=bool(owners and max(owners)[1]==target['id'] and iou(b,clip(tb))>=.3)
            boxes.append(dict(box=b,cls=det['class_name'],conf=det['confidence'],target=matched))
            if matched:matches.append(det)
        bp,bq,roll,pitch,yaw=body_angles()
        sample=dict(requested_pitch_deg=pitch_goal,accepted=True,actual_pitch_deg=-_math.degrees(pitch),
            body_xyz=bp.tolist(),**coverage,matched_predictions=matches,model_sha=result['best_sha256'],
            max_abs_roll_deg=max(abs(x['roll_deg']) for x in hold),min_body_height_m=min(x['height_m'] for x in hold),
            max_foot_anchor_error_m=max(x['max_foot_anchor_error_m'] for x in hold),samples=hold)
        tilt_samples.append(sample)
        rec['yolo_calls']+=1
        if not coverage['full_in_frame']:
            text=f"{target['display_id']} partial view -> look higher"
            rec['banners'].append((recording_t,text,'info'))
            rec['decisions'].append(dict(t=recording_t,drum=target['id'],decision='look_higher',source='framing rule',full_in_frame=False))
        else:
            voted=max(matches,key=lambda x:x['confidence']) if matches else None
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
        Image.fromarray(native).save(run_dir/'inputs'/f'tilt_{int(pitch_goal)}_front.png')
        model_input.save(run_dir/'inputs'/f'tilt_{int(pitch_goal)}_model.png')
        (run_dir/'inputs'/f'tilt_{int(pitch_goal)}_response.json').write_text(_json.dumps(result,indent=2))
        _input_native=native;tbox=tb;mission['hold']={'final':False}
        for _ in range(2*FPS):
            for __ in range(stride):posture.step(dt,_math.radians(pitch_goal));world.step(render=False)
            tilt_frame(f'ACTUAL BODY TILT {-_math.degrees(pitch):.1f} deg - VIEW RESULT')
        mission['hold']=None;_input_native=None;boxes=[]
        print('[hot] TILT '+_json.dumps({k:v for k,v in sample.items() if k!='samples'}),flush=True)
finally:
    # Leave the experiment in a known standing state. Do not attempt blind
    # IK recovery after a guard trip (the cause of the earlier flip).
    posture.leave()
    onboard.set_local_pose(translation=_np2.array([.60,0,.12]),orientation=_np2.array([1.,0,0,0]),camera_axes='world')
    spot.restart_from_default_state(zero)
    for _ in range(round(1.5/dt)):spot.step(dt,zero);world.step(render=False)

(run_dir/'tilt_report.json').write_text(_json.dumps(dict(target=target['display_id'],camera_path=_BODY_CAMERA_PATH,
    fixed_mount_xyz=[.6,0,.12],fixed_mount_pitch_up_deg=15,fixed_mount_quat=MOUNT_BIAS_Q.tolist(),horizontal_fov_deg=110,vertical_fov_deg=77.552142222,
    samples=tilt_samples,stop_reason=stop_reason,returned_to_neutral=True,
    canvas=[1920,1080],camera_display_bounds=[0,100,1280,780],camera_fit='contain',camera_crop=False,
    decisions=rec['decisions'],status=rec['status'],
    method='A fixed +15 degree mount is set before filming and remains constant. Body pitch comes from physical leg IK and joint torques. All projection uses body rotation times mount rotation. No Cosmos.'),indent=2))
_ff=(_glob.glob('/usr/local/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*') or [_shutil.which('ffmpeg')])[0]
_sp.run([_ff,'-y','-loglevel','error','-framerate',str(FPS),'-i',str(frames_dir/'%05d.jpg'),'-c:v','libx264','-pix_fmt','yuv420p','-crf','20','-movflags','+faststart',str(run_dir.with_suffix('.mp4'))],check=True)
for f in frames_dir.glob('*.jpg'):f.unlink()
frames_dir.rmdir()
print('[hot] ONE_DRUM_VIDEO_COMPLETE '+str(rec['status']),flush=True)
