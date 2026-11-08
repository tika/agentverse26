# NVIDIA LocateAnything branch: no YOLO inference is used.
# Load after sensing.py and scenario_lib.py, before agent.py. Inference runs in a
# separate authenticated Modal API; no ML packages are installed into Isaac Python.
import io as _yio
import os as _yos
import urllib.request as _yurl
import time as _ytime
import hashlib as _yhash
from front_camera import CAMERA_PATH


class LocateAnythingVision:
    def __init__(self, interval=1.0):
        self.interval=interval
        self.last_t=-1e6
        self.result=None
        self.calls=0
        self.failures=0

    def observe(self,rgb,depth,p,yaw,estimate,t):
        fresh=t-self.last_t>=self.interval-1e-6
        if fresh:
            self.last_t=t
            start=_ytime.perf_counter()
            try:
                info=state['front_frame']['info']
                rgb_sha=_yhash.sha256(rgb.tobytes()).hexdigest()
                if info['camera_path']!=CAMERA_PATH or rgb_sha!=info['rgb_sha256']:
                    raise ValueError('LocateAnything input is not the current rigid front camera')
                buffer=_yio.BytesIO();Image.fromarray(rgb).save(buffer,format='JPEG',quality=92)
                jpeg=buffer.getvalue();jpeg_sha=_yhash.sha256(jpeg).hexdigest()
                boundary='agentverse-frame'
                stamp=json.dumps(dict(camera_path=CAMERA_PATH,frame_id=info['frame_id'],time_s=t,rgb_sha256=rgb_sha))
                body=(f'--{boundary}\r\nContent-Disposition: form-data; name="frame_timestamp"\r\n\r\n'+stamp+'\r\n'+
                      f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{info["frame_id"]}.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode()+jpeg+f'\r\n--{boundary}--\r\n'.encode()
                req=_yurl.Request(_yos.environ['LOCATE_API_URL'].rstrip('/')+'/predict',data=body,
                    headers={'Modal-Key':_yos.environ['DETECTOR_API_KEY'],'Modal-Secret':_yos.environ['DETECTOR_API_SECRET'],
                             'Content-Type':'multipart/form-data; boundary='+boundary})
                with _yurl.urlopen(req,timeout=180 if self.calls==0 else 30) as response:
                    result=json.loads(response.read())
                if result.get('input_sha256')!=jpeg_sha:raise ValueError('Detector did not acknowledge the exact front-camera JPEG')
                if result['image']!={'width':rgb.shape[1],'height':rgb.shape[0]}:raise ValueError('Detector input dimensions mismatch')
                result.update(source_camera_path=CAMERA_PATH,source_frame_id=info['frame_id'],
                              source_rgb_sha256=rgb_sha,input_jpeg_sha256=jpeg_sha)
                if state.get('save_detector_inputs'):
                    folder=OUT/'detector_inputs';folder.mkdir(exist_ok=True)
                    (folder/(info['frame_id']+'.jpg')).write_bytes(jpeg)
                self.calls+=1
                associations=[]
                if depth is not None:
                    for barrel in result['barrels']:
                        x0,y0,x1,y1=barrel['bbox_xyxy']
                        # Interior depth samples avoid edges/background and plate glare.
                        u=np.linspace(x0+(x1-x0)*.3,x0+(x1-x0)*.7,7)
                        v=np.linspace(y0+(y1-y0)*.3,y0+(y1-y0)*.7,7)
                        uv=np.stack(np.meshgrid(u,v),-1).reshape(-1,2)
                        xy=np.round(uv).astype(int)
                        xy[:,0]=np.clip(xy[:,0],0,depth.shape[1]-1);xy[:,1]=np.clip(xy[:,1],0,depth.shape[0]-1)
                        distances=depth[xy[:,1],xy[:,0]]
                        valid=np.isfinite(distances)&(distances>.2)&(distances<12)
                        if valid.sum()<5:continue
                        points=camera_rays_to_world(onboard,uv[valid],distances[valid],(p,yaw),estimate)
                        centre=np.median(points,0)
                        drum=min(inventory,key=lambda d:math.dist(centre,(d['x'],d['y'])))
                        offset=math.dist(centre,(drum['x'],drum['y']))
                        if offset>drum['radius']+.45:continue
                        faults=[]
                        for name,key in [('corrosion','corrosion_observed'),('bulge','bulge_observed')]:
                            if barrel[key]:
                                faults.append(name)
                        associations.append(dict(drum_id=drum['id'],display_id=drum['display_id'],
                            association='geometry_map_from_rgb_depth_and_estimated_pose',box=barrel['bbox_xyxy'],
                            faults=faults,confidence=barrel['confidence'],range_m=float(np.median(distances[valid])),
                            map_offset_m=offset))
                # Several overlapping predicted boxes can map to one physical drum.
                # One inference contributes one observation per drum, never two views.
                by_id={}
                for item in associations:
                    old=by_id.get(item['drum_id'])
                    if old is None:by_id[item['drum_id']]=item;continue
                    def area(value):
                        x0,y0,x1,y1=value['box'];return (x1-x0)*(y1-y0)
                    merged=dict(max((old,item),key=area))
                    merged['faults']=sorted(set(old['faults'])|set(item['faults']))
                    merged['confidence']=None
                    by_id[item['drum_id']]=merged
                result.update(associations=list(by_id.values()),status='ok',wall_seconds=_ytime.perf_counter()-start,timestamp_s=t)
                self.result=result
            except Exception as error:
                self.failures+=1
                self.result=dict(status='failed',error=str(error)[:160],associations=[],detections=[],
                                 timestamp_s=t,wall_seconds=_ytime.perf_counter()-start)
                self.result.update(source_camera_path=CAMERA_PATH,source_frame_id=state['front_frame']['info']['frame_id'])
            with (OUT/'locateanything_requests.jsonl').open('a') as output:output.write(json.dumps(self.result)+'\n')
            if fresh and self.calls==1:
                Image.fromarray(rgb).save(OUT/'locateanything_first_input.jpg')
        return {**self.result,'fresh':fresh,'age_s':max(0,t-self.last_t),'calls':self.calls,'failures':self.failures}


state['yolo_vision']=LocateAnythingVision()
print('[hot] NVIDIA LocateAnything API bridge loaded; no YOLO or visual-truth fallback',flush=True)
