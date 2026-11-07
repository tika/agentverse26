# RGB/depth -> trained API -> map association. Makes no Cosmos requests.
p,yaw,_,_=full_pose()
scene=copy.deepcopy(BASE_SCENE)
scene['look']=[DRUMS['D10']['x'],DRUMS['D10']['y']]
place_cameras(p,yaw,scene,onboard_yaw=yaw)
for _ in range(8):world.render()
rgb=_rgb(onboard)
depth=onboard.get_depth()
observation=state['yolo_vision'].observe(rgb,depth,p,yaw,np.array([p[0],p[1],yaw]),0.0)
Image.fromarray(rgb).save(OUT/'hall_rgb.png')
view=Image.fromarray(rgb);draw=ImageDraw.Draw(view)
for detection in observation['detections']:
    color={'drum':'#35d7ff','corrosion':'#ff9829','bulge':'#ed67f5'}[detection['class_name']]
    draw.rectangle(detection['bbox_xyxy'],outline=color,width=2)
    x,y,_,_=detection['bbox_xyxy']
    draw.text((x,max(0,y-13)),f"{detection['class_name']} {detection['confidence']:.2f}",font=FONT[14],fill=color,stroke_width=1,stroke_fill='black')
view.save(OUT/'hall_yolo.png')
(OUT/'hall_yolo.json').write_text(json.dumps(observation,indent=2))
print('[hot] YOLO hall probe '+json.dumps({key:observation.get(key) for key in ('status','run_id','calls','failures','wall_seconds','associations')}),flush=True)
assert observation['status']=='ok' and observation['calls']>0,'YOLO API failed on hall camera'
assert len({item['drum_id'] for item in observation['associations']})==len(observation['associations']),'Duplicate physical-drum observations'
