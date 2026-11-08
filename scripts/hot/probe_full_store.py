# Check map/viewpoint reachability and real detector coverage before a long mission.
from mission_coverage import StoreRouter
router=StoreRouter(inventory,robot_radius=.70)
onboard.prim.GetAttribute('focalLength').Set(10.0)
p,yaw,_,_=full_pose()
rows=[]
for drum in inventory:
    point=router.viewpoints(drum)[0]
    assert router.route((1.3,2.),point),drum['display_id']
    eye=np.array([point[0],point[1],.95])
    _aim(onboard,eye,np.array([drum['x'],drum['y'],drum['height']*.52]))
    for _ in range(5):world.render()
    rgb=_rgb(onboard)
    vision=YoloVision().observe(rgb,onboard.get_depth(),p,yaw,np.array([p[0],p[1],yaw]),0.)
    Image.fromarray(rgb).save(OUT/f"view_{drum['display_id']}.jpg",quality=90)
    match=next((o for o in vision['associations'] if o['drum_id']==drum['id']),None)
    rows.append(dict(drum=drum['display_id'],category=drum['category'],route_reachable=True,
                     yolo_status=vision['status'],detected=bool(match),observation=match))
    print(f"[hot] viewpoint {drum['display_id']}: YOLO {'detected' if match else 'missing'}",flush=True)
(OUT/'viewpoint_probe.json').write_text(json.dumps(rows,indent=2))
assert all(r['yolo_status']=='ok' for r in rows),'Detector service failure'
answer=cosmos_chat([{'type':'text','text':'Reply with only JSON: {"ok":true}'}],max_tokens=64)
assert extract_json(answer).get('ok'),'Cosmos service unavailable'
print('[hot] full-store probe complete; '+str(sum(r['detected'] for r in rows))+'/28 detected from primary viewpoints',flush=True)
