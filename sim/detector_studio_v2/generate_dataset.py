"""One Isaac process per RTX worker; five new scene seeds, 150 accepted frames."""
import argparse,json,math,sys,time,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--assets',required=True);p.add_argument('--plan',required=True);p.add_argument('--out',required=True)
a,_=p.parse_known_args();assets=Path(a.assets);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
plan=json.loads(Path(a.plan).read_text());started=time.perf_counter()
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'renderer':'RayTracedLighting','disable_viewport_updates':True,'limit_cpu_threads':8})
import numpy as np
import carb,omni.usd,omni.replicator.core as rep
from PIL import Image,ImageDraw
from pxr import Usd,UsdGeom,UsdShade,Gf,Sdf
from isaacsim.core.api import World
from isaacsim.sensors.camera import Camera
from isaacsim.core.experimental.utils.semantics import add_labels
sys.path.insert(0,str(assets))
import drum_faults as faults
from warehouse_physics import generate_inventory
from storage import print_texture

names=['normal','rust','bulge','rust_and_bulge'];layout=json.loads((assets/'map.json').read_text());drums={d['id']:d for d in layout['drums']}
original_rust=faults._rust;original_bulge=faults._bulge
class FacingRandom:
    def __init__(self,rng,drum,mode):self.rng=rng;self.mode=mode;self.center=math.atan2(drum['face_sign'],0)-drum['yaw'];self.first=True
    def __getattr__(self,name):return getattr(self.rng,name)
    def uniform(self,low=0,high=1,*args,**kwargs):
        if self.mode=='rust' and low==0 and high==1:return (self.center/(2*math.pi)+self.rng.uniform(-.18,.18))%1
        if self.mode=='bulge' and low==-math.pi and high==math.pi and self.first:
            self.first=False;return (self.center+self.rng.uniform(-.3,.3)+math.pi)%(2*math.pi)-math.pi
        return self.rng.uniform(low,high,*args,**kwargs)
def rust(source,target,d,severity,rng):
    return original_rust(source,target,d,severity,FacingRandom(rng,d,'rust') if d['category']=='ILW' else rng)
def bulge(body,d,severity,rng):return original_bulge(body,d,severity,FacingRandom(rng,d,'bulge'))
faults._rust=rust;faults._bulge=bulge

context=omni.usd.get_context()
settings=carb.settings.get_settings();settings.set_bool('/rtx/post/histogram/enabled',False);settings.set_float('/rtx/post/tonemap/fNumber',2.8);settings.set_float('/rtx/post/tonemap/cameraShutter',60.);settings.set_int('/rtx/post/aa/op',0)
world=None;seg=None
records=[];class_counts=[0]*4
for session_index,s in enumerate(plan['sessions']):
    seed=s['seed'];rng=np.random.default_rng(seed);folder=out/'private'/str(seed);folder.mkdir(parents=True)
    print('DATA_PROGRESS '+json.dumps(dict(state='authoring',seed=seed,frames=len(records))),flush=True)
    physical=generate_inventory(layout,seed)
    for entry in physical['drums']:
        c=s['conditions'].get(entry['drum_id'],0)
        sev=lambda:float(rng.uniform(.20,.35) if rng.random()<.33 else rng.uniform(.35,.95))
        entry['visual_plan'].update(corrosion_severity=sev() if c in (1,3) else 0.,bulging_severity=sev() if c in (2,3) else 0.)
    path=faults.generate_session(folder/'scene.usda',seed=seed,inventory=physical,base_stage=assets/'warehouse-v3.usda',map_path=assets/'map.json')
    # Load a composed session before constructing sensors/physics, matching the
    # approved pilot. Replacing a live stage's sublayers invalidates PhysX views
    # and can silently remove all instanced drums from the render.
    if seg is not None:seg.detach([camera.get_render_product_path()])
    if world is not None:World.clear_instance()
    context.open_stage(str(path));stage=context.get_stage()
    for d in drums.values():
        prim=stage.GetPrimAtPath(d['prim_path'])
        if not prim:raise RuntimeError('Missing drum '+d['id'])
        add_labels(prim,labels=['drum'],taxonomy='class');add_labels(prim,labels=[d['id']],taxonomy='drum_id')
    world=World(physics_dt=1/60,rendering_dt=1/60)
    camera=Camera('/World/ConditionDataCamera',resolution=(384,384))
    for key,value in (('horizontalAperture',36.),('verticalAperture',36.),('focalLength',22.5)):
        camera.prim.GetAttribute(key).Set(value)
    camera.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05,60.))
    world.reset();camera.initialize()
    seg=rep.AnnotatorRegistry.get_annotator('semantic_segmentation',init_params={'semanticTypes':['class','drum_id'],'colorize':False});seg.attach([camera.get_render_product_path()])
    light_bases={str(prim.GetPath()):prim.GetAttribute('inputs:intensity').Get() for prim in stage.Traverse() if prim.HasAttribute('inputs:intensity')}
    # Every printed location/ID is randomized independently of condition. Render
    # metadata retains the simulator ID; these text strings are not model inputs.
    label_dir=folder/'prints';label_dir.mkdir()
    physical_by_id={d['drum_id']:d for d in physical['drums']}
    for key,c in s['conditions'].items():
        d=drums[key];fake={**d,'display_id':f'{chr(65+int(rng.integers(26)))}-{chr(65+int(rng.integers(26)))}-{int(rng.integers(100)):02d}-T{int(rng.integers(1,4))}',
                              'id':f'X{seed}_{key}'}
        print_texture(fake,label_dir);source=label_dir/f"{fake['id']}.png"
        material=UsdShade.MaterialBindingAPI(stage.GetPrimAtPath(d['prim_path']+'/Body')).ComputeBoundMaterial()[0]
        shader=UsdShade.Shader.Get(stage,str(material.GetPath())+'/Print')
        # Rebuild rust from the newly printed source using the exact same recipe.
        rust_sev=physical_by_id[key]['visual_plan']['corrosion_severity']
        if rust_sev:
            texture=folder/'scene_textures'/f'{key}.png'
            rust(source,texture,d,rust_sev,rng);source=texture
        shader.GetInput('file').Set(Sdf.AssetPath(str(source)))
        tint=tuple(float(v) for v in rng.uniform(.90,1.08,3))+(1.,)
        shader.CreateInput('scale',Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*tint))
    for key,value in light_bases.items():
        if value is not None:stage.GetPrimAtPath(key).GetAttribute('inputs:intensity').Set(float(value)*float(rng.uniform(.85,1.2)))
    split=s['split'];(out/'images'/split).mkdir(parents=True,exist_ok=True);(out/'labels'/split).mkdir(parents=True,exist_ok=True)
    for f in s['frames']:
        d=drums[f['drum_id']];angle=f['angle_deg'];distance=f['distance_m'];exposure=f['exposure_scale']
        chosen=None
        for attempt in range(5):
            az=math.radians(angle);eye=np.array([d['x']+distance*math.sin(az)+f['jitter_x_m'],d['y']+d['face_sign']*distance*math.cos(az),.62])
            horizontal=np.array([d['x']-eye[0],d['y']-eye[1],0.]);horizontal/=np.linalg.norm(horizontal)
            pitch=math.atan2(d['base_z']+d['height']*.52-eye[2],distance)
            target=eye+horizontal*distance+[0,0,distance*math.tan(pitch)]
            matrix=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float,eye)),Gf.Vec3d(*map(float,target)),Gf.Vec3d(0,0,1));q=matrix.GetInverse().ExtractRotationQuat()
            camera.set_world_pose(position=eye,orientation=np.array([q.GetReal(),*q.GetImaginary()]),camera_axes='usd')
            settings.set_float('/rtx/post/tonemap/filmIso',400.*exposure)
            for _ in range(24 if not records or f is s['frames'][0] else 4):world.render()
            packet=seg.get_data();ids=np.asarray(packet['data']).squeeze();rgb=np.asarray(camera.get_rgba())[:,:,:3].astype(np.uint8)
            masks={}
            for sid,label in packet['info']['idToLabels'].items():
                key=str(label.get('drum_id','')).upper()
                if key in drums:masks[key]=masks.get(key,np.zeros(ids.shape,bool))|(ids==int(sid))
            target_mask=masks.get(d['id']);box=None
            if target_mask is not None and target_mask.any():
                yy,xx=np.nonzero(target_mask);box=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)];x0,y0,x1,y1=box
                good=(min(x0,y0,384-x1,384-y1)>2 and y1-y0>=64 and target_mask.sum()/((x1-x0)*(y1-y0))>=.60 and float(rgb[target_mask].mean())>=40.)
                if good:chosen=(rgb,masks,box);break
            # Keep the condition/category/tier fixed; improve lighting and angle.
            exposure=min(2.,exposure*1.25);angle*=.45
            if attempt>=2:distance=max(distance,2.35 if f['tier']==2 else 1.5)
        if chosen is None:
            rejected=out/'rejected';rejected.mkdir(exist_ok=True);Image.fromarray(rgb).save(rejected/(f['name']+'.png'))
            debug={**f,'last_box':box,'rgb_mean':float(rgb.mean()),'target_pixels':int(target_mask.sum()) if target_mask is not None else 0,
                   'intrinsics':camera.get_intrinsics_matrix().tolist(),'visible_ids':[k for k,v in masks.items() if v.any()],
                   'target_transform':str(UsdGeom.Xformable(stage.GetPrimAtPath(d['prim_path'])).ComputeLocalToWorldTransform(Usd.TimeCode.Default()))}
            (rejected/(f['name']+'.json')).write_text(json.dumps(debug,indent=2))
            raise RuntimeError('No inspectable target after retries: '+json.dumps(debug))
        rgb,masks,target_box=chosen;annotations=[];lines=[]
        for key,mask in masks.items():
            yy,xx=np.nonzero(mask)
            if len(xx)<70:continue
            x0,y0,x1,y1=int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)
            if min(x1-x0,y1-y0)<12:continue
            c=s['conditions'].get(key,0);class_counts[c]+=1
            lines.append(f'{c} {(x0+x1)/768:.6f} {(y0+y1)/768:.6f} {(x1-x0)/384:.6f} {(y1-y0)/384:.6f}')
            annotations.append(dict(drum_id=key,class_id=c,box=[x0,y0,x1,y1],category=drums[key]['category'],tier=drums[key]['location']['tier']))
        image_path=out/'images'/split/(f['name']+'.png');Image.fromarray(rgb).save(image_path)
        (out/'labels'/split/(f['name']+'.txt')).write_text('\n'.join(lines)+'\n')
        record={**f,'seed':seed,'split':split,'actual_angle_deg':angle,'actual_distance_m':distance,'exposure_scale':exposure,'capture_attempt':attempt,
                'target_box':target_box,'camera_eye':eye.tolist(),'pitch_deg':math.degrees(pitch),'intrinsics':camera.get_intrinsics_matrix().tolist(),
                'annotations':annotations,'image_sha256':hashlib.sha256(image_path.read_bytes()).hexdigest(),
                'severity':physical_by_id[d['id']]['visual_plan']}
        records.append(record)
        if len(records)%10==0:print('DATA_PROGRESS '+json.dumps(dict(state='rendering',frames=len(records),seed=seed,seconds=round(time.perf_counter()-started,2))),flush=True)
    (out/'manifest.json').write_text(json.dumps(dict(frames=records,classes=names,class_counts=class_counts,render_seconds=round(time.perf_counter()-started,3)),indent=2))
    print('DATA_PROGRESS '+json.dumps(dict(state='scene_complete',frames=len(records),seed=seed)),flush=True)
print('DATA_COMPLETE '+json.dumps(dict(frames=len(records),seconds=round(time.perf_counter()-started,3))),flush=True)
app.close()
