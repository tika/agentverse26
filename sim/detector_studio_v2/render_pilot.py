"""Render the exact packaged drum designs; whole-barrel condition labels only."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

parser=argparse.ArgumentParser()
parser.add_argument('--assets',required=True);parser.add_argument('--views',required=True);parser.add_argument('--out',required=True)
parser.add_argument('--keep-alive',action='store_true')
args,_=parser.parse_known_args();root=Path(args.assets);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
views=json.loads(Path(args.views).read_text());started=time.perf_counter()
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'renderer':'RayTracedLighting','disable_viewport_updates':True,'limit_cpu_threads':8})
import carb
import numpy as np
import omni.usd
import omni.replicator.core as rep
from pxr import Gf,UsdGeom
from PIL import Image,ImageDraw
from isaacsim.core.api import World
from isaacsim.core.experimental.utils.semantics import add_labels
from isaacsim.sensors.camera import Camera

condition_map={'normal':'normal','corrosion_only':'rust','bulge_only':'bulge','bulge_and_corrosion':'rust_and_bulge'}
names=['normal','rust','bulge','rust_and_bulge'];colors=['#69df9b','#ff993f','#db80ff','#ff6868']
layout=json.loads((root/'map.json').read_text());drums={d['id']:d for d in layout['drums']}
catalog=json.loads((root/'sample_catalog.json').read_text())
conditions={Path(d['prim_path']).name:condition_map[d['condition']] for d in catalog}
context=omni.usd.get_context();context.open_stage(str(root/'CANIS_YOLO_FOUR_CONDITION.usda'));stage=context.get_stage()
for key,d in drums.items():
    prim=stage.GetPrimAtPath(d['prim_path'])
    if not prim:raise RuntimeError('Missing packaged drum '+key)
    add_labels(prim,labels=['drum'],taxonomy='class');add_labels(prim,labels=[key],taxonomy='drum_id')
settings=carb.settings.get_settings()
settings.set_bool('/rtx/post/histogram/enabled',False);settings.set_float('/rtx/post/tonemap/filmIso',400.)
settings.set_float('/rtx/post/tonemap/fNumber',2.8);settings.set_float('/rtx/post/tonemap/cameraShutter',60.)
settings.set_int('/rtx/post/aa/op',0)
world=World(physics_dt=1/60,rendering_dt=1/60)
camera=Camera('/World/PilotCamera',resolution=(384,384))
camera.prim.GetAttribute('focalLength').Set(22.5)
camera.prim.GetAttribute('horizontalAperture').Set(36.)
camera.prim.GetAttribute('verticalAperture').Set(36.)
camera.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05,60.))
world.reset();camera.initialize()
seg=rep.AnnotatorRegistry.get_annotator('semantic_segmentation',init_params={'semanticTypes':['class','drum_id'],'colorize':False})
seg.attach([camera.get_render_product_path()])
# CAPTURE_BEGIN
for folder in ('images','labels','overlays','crops'): (out/folder).mkdir(parents=True,exist_ok=True)
reports=[]
for v in views:
    d=drums[v['target_id']];distance=v['distance_m'];angle=math.radians(v['angle_deg'])
    normal=float(d['face_sign']);eye=np.array([d['x']+distance*math.sin(angle),d['y']+normal*distance*math.cos(angle),.62])
    target=np.array([d['x'],d['y'],d['base_z']+d['height']*.52])
    matrix=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float,eye)),Gf.Vec3d(*map(float,target)),Gf.Vec3d(0,0,1))
    q=matrix.GetInverse().ExtractRotationQuat()
    camera.set_world_pose(position=eye,orientation=np.array([q.GetReal(),*q.GetImaginary()]),camera_axes='usd')
    settings.set_float('/rtx/post/tonemap/filmIso',400.*v['exposure_scale'])
    for _ in range(32 if not reports else 5):world.render()
    packet=seg.get_data();ids=np.asarray(packet['data']).squeeze();rgb=np.asarray(camera.get_rgba())[:,:,:3].astype(np.uint8)
    if ids.shape!=rgb.shape[:2] or float(rgb.std())<5:raise RuntimeError('Blank or misaligned sensor frame')
    masks={}
    for sid,label in packet['info']['idToLabels'].items():
        key=str(label.get('drum_id','')).upper()
        if key in drums:masks[key]=masks.get(key,np.zeros(ids.shape,bool))|(ids==int(sid))
    boxes=[];lines=[];image=Image.fromarray(rgb);overlay=image.copy();draw=ImageDraw.Draw(overlay)
    for key,mask in masks.items():
        yy,xx=np.nonzero(mask)
        if len(xx)<100:continue
        box=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]
        x0,y0,x1,y1=box
        if min(x1-x0,y1-y0)<12:continue
        state=conditions.get(key,'normal');cls=names.index(state)
        # These are visible body boxes, never rust patch boxes. Off-frame / tiny
        # neighbours are explicitly review-only, not trusted condition labels.
        inspectable=min(x0,y0,384-x1,384-y1)>1 and y1-y0>=60 and len(xx)/((x1-x0)*(y1-y0))>=.45
        record=dict(drum_id=key,package_id=drums[key]['display_id'],condition=state,box=box,
                    visible_pixels=len(xx),condition_label_accepted=bool(inspectable))
        boxes.append(record)
        if inspectable:
            lines.append(f'{cls} {(x0+x1)/768:.6f} {(y0+y1)/768:.6f} {(x1-x0)/384:.6f} {(y1-y0)/384:.6f}')
            draw.rectangle(box,outline=colors[cls],width=2)
            draw.text((x0+2,max(0,y0-12)),drums[key]['display_id']+' '+state,fill=colors[cls],stroke_width=1,stroke_fill='black')
    selected=next((b for b in boxes if b['drum_id']==v['target_id']),None)
    target_accepted=bool(selected and selected['condition_label_accepted'])
    stem=v['name'];image.save(out/'images'/f'{stem}.png');overlay.save(out/'overlays'/f'{stem}.png')
    (out/'labels'/f'{stem}.txt').write_text('\n'.join(lines)+'\n')
    if selected:
        x0,y0,x1,y1=selected['box'];pad=round(.1*max(x1-x0,y1-y0))
        image.crop((max(0,x0-pad),max(0,y0-pad),min(384,x1+pad),min(384,y1+pad))).resize((224,224)).save(out/'crops'/f'{stem}.png')
    reports.append({**v,'condition':conditions[v['target_id']],'camera_eye':eye.tolist(),'camera_target':target.tolist(),
                    'intrinsics':camera.get_intrinsics_matrix().tolist(),'resolution':[384,384],
                    'target':selected,'target_condition_label_accepted':target_accepted,'visible_drums':boxes,
                    'sha256':hashlib.sha256((out/'images'/f'{stem}.png').read_bytes()).hexdigest()})
    print('PILOT_FRAME '+json.dumps({'name':stem,'condition':conditions[v['target_id']],'boxes':len(lines),'elapsed_s':round(time.perf_counter()-started,2)}),flush=True)
(out/'manifest.json').write_text(json.dumps({'frames':reports,'classes':names,'pilot_only':True,'render_seconds':round(time.perf_counter()-started,3),
    'annotation_policy':'Whole visible barrel condition boxes; tiny/clipped neighbours excluded. Target conditions are authored catalog labels requiring visual review; no rust patch annotations.'},indent=2))
# CAPTURE_END
if args.keep_alive:
    request_dir=Path('/tmp/canis-warm-requests');request_dir.mkdir(exist_ok=True)
    capture_source=Path(__file__).read_text().split('# CAPTURE_BEGIN\n',1)[1].split('# CAPTURE_END\n',1)[0]
    print('PILOT_WARM_READY',flush=True)
    while app.is_running():
        for request_path in sorted(request_dir.glob('*.json')):
            request=json.loads(request_path.read_text());out=Path(request['out']);out.mkdir(parents=True,exist_ok=True)
            views=request['views'];started=time.perf_counter()
            try:exec(compile(capture_source,'warm_capture','exec'),globals())
            except Exception:
                import traceback
                (out/'error.txt').write_text(traceback.format_exc())
            (out/'done').touch();request_path.unlink()
        app.update();time.sleep(.05)
app.close()
