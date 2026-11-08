"""Physical mount, body-motion and model-input audit. This is a calibration test, not a mission."""
from front_camera import expected_world_pose,rotation,MOUNT_XYZ,MOUNT_QUAT,CAMERA_PATH,BODY_PATH,HFOV_DEG
from pxr import UsdGeom
import hashlib

assert state.get('camera_mode')=='rigid_front_only'
cameras=[str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdGeom.Camera)]
scene_cameras={p for p in cameras if p.startswith('/World/')}
assert scene_cameras=={CAMERA_PATH,PRESENTATION_PATH},f'Unexpected scene camera prims: {cameras}'
assert str(onboard.prim.GetParent().GetPath())==BODY_PATH
state['save_detector_inputs']=True
state['yolo_vision'].interval=.5
zero=np.zeros(3,dtype=np.float32)
spot.restart_from_default_state(zero)
world.step(render=False)
bp,bq=spot.articulation.get_world_poses();bp=bp.numpy().reshape(3);bq=bq.numpy().reshape(4)
_,yaw,_,_=full_pose()
scene=copy.deepcopy(BASE_SCENE)
a=Agent(99,'Rigid front camera | physical motion and input audit',scene,[])
a.nav=RealNav([bp[0],bp[1],yaw]);a.sensor=SensorWorld(inventory,load_config())
a.use_cosmos=True
frames_dir=OUT/'front_camera_audit'/'frames';frames_dir.mkdir(parents=True,exist_ok=True)
dt=spot.physics_dt;stride=round(1/(FPS*dt));frame_dt=stride*dt
stages=[('stand',1.2),('walk_forward',1.6),('turn_left',1.5),('hold_left',.7),
        ('turn_right',3.),('hold_right',.7),('turn_centre',1.5),
        ('settle_before_pose',1.2),('look_up',3.2),('settle_up',.8),
        ('look_down',3.2),('settle_down',.8),('crouch',3.2),('settle',1.2)]
stages=state.pop('camera_audit_stages',stages)
phase_index=0;phase_start=0.;pose_motion=None;rows=[];failures=[]
for index in range(round(sum(v for _,v in stages)*FPS)):
    t=index*frame_dt
    name,duration=stages[phase_index]
    if t-phase_start>=duration and phase_index<len(stages)-1:
        phase_index+=1;phase_start=t;name,duration=stages[phase_index];pose_motion=None
    if name in ('look_up','look_down','crouch') and pose_motion is None:
        try:pose_motion=StationaryBodyObservation(spot,name)
        except Exception as error:
            failures.append(dict(phase=name,error=str(error)));pose_motion=False
    update_presentation();world.render();world.render()
    packet=capture_front(index,t);p,yaw,roll,pitch=full_pose()
    native_p,native_q=spot.articulation.get_world_poses();native_p=native_p.numpy().reshape(3);native_q=native_q.numpy().reshape(4)
    expected_p,expected_r=expected_world_pose(native_p,native_q)
    camera_p,camera_q=onboard.get_world_pose(camera_axes='world')
    position_error=float(np.linalg.norm(camera_p-expected_p))
    rotation_error=float(np.linalg.norm(rotation(camera_q)-expected_r))
    local_p,local_q=onboard.get_local_pose(camera_axes='world')
    assert position_error<.002 and rotation_error<.002,(name,position_error,rotation_error)
    assert np.linalg.norm(local_p-MOUNT_XYZ)<1e-6
    a.nav.lidar_update(frame_dt)
    if not a.trail or math.dist(a.trail[-1],a.nav.fused[:2])>.04:a.trail.append(tuple(a.nav.fused[:2]))
    reading=a.sensor.sample((p[0],p[1],.6),t);reading.update(hydrogen_ppm=0.,methane_ppm=0.)
    scene['ambient_c']=reading['temperature_c'];perception=perceive(scene)
    vision=state['yolo_vision'].observe(packet['rgb'],packet['depth'],p,yaw,a.nav.fused,t)
    perception['yolo']=vision;perception['corrosion_px']={}
    a.history['gamma'].append(reading['dose_rate_uSv_h']);a.history['h2'].append(0.)
    a.gas={'hydrogen_ppm':0.,'methane_ppm':0.};a.hiss={'hiss_score':0.,'band_margin_db':0.};a.mic_db=-60.
    a.nearest=('-',0.);a.status=name.upper().replace('_',' ')
    a.message='Scripted physical-camera audit; no independent camera movement'
    compose_agent(a,{'first':packet['rgb'],'frame_info':packet['info'],'presentation':presentation_pixels()},perception,reading,p,yaw,roll,pitch,t).save(frames_dir/f'{index:05d}.jpg',quality=90)
    rows.append(dict(t=t,phase=name,body_position=p.tolist(),body_quaternion=native_q.tolist(),
                     body_roll=roll,body_pitch=pitch,body_yaw=yaw,camera_position=camera_p.tolist(),
                     camera_quaternion=np.asarray(camera_q).tolist(),mount_position_error_m=position_error,
                     mount_rotation_error=rotation_error,frame_info=packet['info'],yolo_source_frame=vision.get('source_frame_id'),
                     yolo_status=vision['status']))
    if abs(roll)>.7 or abs(pitch)>.7 or p[2]<.25:
        failures.append(dict(phase=name,error='Posture safety bound exceeded'));break
    command=zero.copy()
    if name=='walk_forward':command[0]=.35
    if name in ('turn_left','turn_centre'):command[2]=.6
    if name=='turn_right':command[2]=-.6
    for _ in range(stride):
        if pose_motion and not pose_motion.finished:pose_motion.step(dt)
        else:spot.step(dt,command)
        world.step(render=False);a.nav.physics_update(dt,t)
    if index%24==0:print(f'[hot] fixed-camera audit t={t:.1f}s {name}, mount error {position_error:.6f} m',flush=True)

(OUT/'mount_trajectory.json').write_text(json.dumps(rows,indent=2,default=float))
groups={name:[r for r in rows if r['phase']==name] for name,_ in stages}
baseline=float(np.median([r['body_position'][2] for r in groups['stand']]))
pitch0=float(np.median([r['body_pitch'] for r in groups['stand']]))
capabilities=dict(turn_left=True,turn_right=True,reposition=True)
for name in ('look_up','look_down','crouch'):
    samples=groups.get(name,[])
    if name=='crouch':passed=bool(samples) and min(r['body_position'][2] for r in samples)<baseline-.025
    elif name=='look_up':passed=bool(samples) and min(r['body_pitch'] for r in samples)<pitch0-.04
    else:passed=bool(samples) and max(r['body_pitch'] for r in samples)>pitch0+.04
    capabilities[name]=passed and not any(f['phase']==name for f in failures)
state['verified_observation_motions']=capabilities
report=dict(camera_prims=cameras,camera_parent=BODY_PATH,independent_pan_tilt=False,
            model_visual_sources=[CAMERA_PATH],presentation_only_sources=[PRESENTATION_PATH],
            mount_xyz_m=MOUNT_XYZ.tolist(),horizontal_fov_deg=HFOV_DEG,
            calibration_status='simulation forward rectified RGB-D approximation; not measured Spot intrinsics',
            frames=len(rows),max_mount_position_error_m=max(r['mount_position_error_m'] for r in rows),
            max_mount_rotation_error=max(r['mount_rotation_error'] for r in rows),
            capabilities=capabilities,controller_failures=failures,
            body_height_range_m=[min(r['body_position'][2] for r in rows),max(r['body_position'][2] for r in rows)],
            body_pitch_range_rad=[min(r['body_pitch'] for r in rows),max(r['body_pitch'] for r in rows)],
            body_yaw_range_rad=[min(r['body_yaw'] for r in rows),max(r['body_yaw'] for r in rows)],
            yolo_requests=state['yolo_vision'].calls,yolo_failures=state['yolo_vision'].failures)
(OUT/'front_camera_audit.json').write_text(json.dumps(report,indent=2))
assert state['yolo_vision'].calls>0 and state['yolo_vision'].failures==0,'Detector provenance check failed'
print('[hot] fixed front-camera audit complete '+json.dumps(capabilities),flush=True)
