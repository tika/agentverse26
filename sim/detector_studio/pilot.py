"""Diverse single/context pilot; camera reuse, no writes to hall USD/inventory."""
import json
import math
import os
import sys
import time
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(SIM.parents[0]))
from detector.pilot_specs import diversity_spec, CLASSES
from detector.annotations import merge_rust_boxes


def export_frame(directory, entries, camera_meta):
    import numpy as np
    from PIL import Image, ImageDraw
    rgb = next(directory.glob('rgb*.png'))
    image = Image.open(rgb).convert('RGB')
    pixels = np.asarray(image)
    assert pixels.mean() > 3 and np.percentile(pixels,99) > 15, 'Black frame'
    native = np.load(next(directory.glob('bounding_box_2d_tight_*.npy')), allow_pickle=False)
    labels = json.loads(next(directory.glob('bounding_box_2d_tight_labels*.json')).read_text())
    labels = labels.get('idToLabels', labels)
    by_id = {e['id']:e for e in entries}
    boxes = []; ignored = 0
    def scalar(value):
        return value[0] if isinstance(value,list) else value
    for row in native:
        semantic = labels[str(int(row['semanticId']))]
        cls = scalar(semantic.get('class'))
        internal_id = scalar(semantic.get('drum_id','')).upper()
        assert cls in CLASSES and internal_id in by_id, semantic
        xyxy = [max(0,min(640,int(row[k]))) for k in ('x_min','y_min','x_max','y_max')]
        x0,y0,x1,y1 = xyxy
        if x1<=x0 or y1<=y0:
            ignored += 1
            continue
        boxes.append(dict(class_name=cls,class_id=CLASSES.index(cls),internal_id=internal_id,xyxy=xyxy))
        # Bulge is one object-condition box, identical to the visible drum extent.
        # It is emitted from observed native drum boxes, never a second hidden overlay.
        if cls == 'drum' and by_id[internal_id]['bulge']:
            boxes.append(dict(class_name='bulge',class_id=2,internal_id=internal_id,xyxy=xyxy))
    drums={b['internal_id']:b['xyxy'] for b in boxes if b['class_name']=='drum'}
    assert drums, 'No drum annotations'
    raw_rust_count=sum(b['class_name']=='corrosion' for b in boxes)
    boxes=merge_rust_boxes(boxes,drums)
    # Merge first: nearby sub-pixel chips can form a useful visible patch.
    retained=[]
    for b in boxes:
        x0,y0,x1,y1=b['xyxy']
        minimum=3 if b['class_name']=='corrosion' else 2
        if x1-x0<minimum or y1-y0<minimum:ignored+=1
        else:retained.append(b)
    boxes=retained
    if camera_meta.get('mode')=='single':
        assert set(drums)=={camera_meta['target_id']}, ('Single frame contains other drums',drums)
    if camera_meta.get('mode')=='context':
        assert len(drums)>=2, ('Context frame has fewer than two drums',drums)
    lines=[]
    draw=ImageDraw.Draw(image)
    colors=['#35dc65','#ff7823','#42bfff']
    for b in boxes:
        x0,y0,x1,y1=b['xyxy']
        lines.append(f"{b['class_id']} {(x0+x1)/1280:.7f} {(y0+y1)/1280:.7f} {(x1-x0)/640:.7f} {(y1-y0)/640:.7f}")
        color=colors[b['class_id']]
        offset=3 if b['class_id']==2 else 0
        draw.rectangle((x0+offset,y0+offset,x1-offset,y1-offset),outline=color,width=1)
        if b['class_name']!='corrosion':
            draw.text((x0+2,y0+2+12*offset),b['class_name']+' '+b['internal_id'],fill=color,stroke_width=1,stroke_fill='black')
    image.save(directory/'boxes.jpg',quality=92)
    Image.open(rgb).convert('RGB').save(directory/'image.jpg',quality=95)
    (directory/'labels.txt').write_text('\n'.join(lines)+'\n')
    meta=dict(drums=entries,camera=camera_meta,boxes=boxes,ignored_small_boxes=ignored,
              raw_corrosion_boxes=raw_rust_count,
              annotation_policy='bulge: one visible whole-drum box; corrosion: bounded per-drum visible patch grouping before small-box filtering',
              pixel_mean=float(pixels.mean()))
    (directory/'metadata.json').write_text(json.dumps(meta,indent=2))
    return {name:sum(b['class_name']==name for b in boxes) for name in CLASSES}


def rust_clusters(stage, entry, maps, alpha, profile):
    """Preserve v2 chip geometry; partition adjacent occupied cells into local instances.

    Angular sectors bound instance span to 22.5 degrees; adjacency is by original
    256x144 grid cells. This avoids one barrel-wide box for disconnected rust.
    """
    import numpy as np
    from pxr import UsdGeom, UsdShade, Sdf, Gf
    from corrosion_preview import build_oxide
    from materials import material
    from geometry import mesh
    temp='/World/RustTemporary'
    UsdGeom.Xform.Define(stage,temp)
    original=build_oxide(stage,{**entry,'prim_path':temp},maps,alpha,profile)
    points=np.asarray(original.GetPointsAttr().Get())
    indices=np.asarray(original.GetFaceVertexIndicesAttr().Get()).reshape(-1,4)
    uvs=np.asarray(UsdGeom.PrimvarsAPI(original).GetPrimvar('st').Get()).reshape(-1,4,2)
    cells={}
    for face_index, uv in enumerate(uvs):
        column=int(round(uv[0,0]*256)); row=int(round(uv[0,1]*144))
        cells[(column,row)]=face_index
    paint=material(stage,'PilotOxide_'+entry['id'],(1,1,1),.9,textures=maps)
    UsdShade.Shader(stage.GetPrimAtPath(str(paint.GetPath())+'/Surface')).CreateInput('opacityThreshold',Sdf.ValueTypeNames.Float).Set(.17)
    parent='/World/Defects/'+entry['id']
    root=UsdGeom.Xform.Define(stage,parent)
    root.AddTranslateOp().Set(Gf.Vec3d(entry['x'],entry['y'],0))
    root.AddRotateZOp().Set(math.degrees(entry['yaw']))
    from isaacsim.core.experimental.utils.semantics import add_labels
    pending=set(cells); count=0
    while pending:
        start=min(pending); pending.remove(start)
        component=[start]; queue=[start]
        while queue:
            c,r=queue.pop()
            for dc,dr in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,-1),(1,-1),(-1,1)):
                nxt=(c+dc,r+dr)
                if nxt in pending and nxt[0]//16==start[0]//16:
                    pending.remove(nxt);component.append(nxt);queue.append(nxt)
        subset=[cells[c] for c in component]
        pp=points[indices[subset]].reshape(-1,3).tolist()
        ff=[tuple(range(i*4,i*4+4)) for i in range(len(subset))]
        prim=mesh(stage,f'{parent}/Rust_{count:04d}',pp,ff,uvs[subset].reshape(-1,2).tolist(),paint).GetPrim()
        add_labels(prim,labels=['corrosion'],taxonomy='class')
        add_labels(prim,labels=[entry['id']],taxonomy='drum_id')
        count+=1
    stage.RemovePrim(temp)
    return count


def main():
    started=time.perf_counter()
    seed=int(os.environ['PILOT_SEED'])
    frame_count=int(os.environ.get('PILOT_FRAMES','5'))
    out=Path(os.environ['PILOT_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'RayTracedLighting','display_options':0})
    import numpy as np
    import omni.usd
    import omni.replicator.core as rep
    import carb
    from pxr import UsdGeom,UsdLux,Gf,UsdPhysics
    from drums import make_inventory,drum_materials,create_drum,create_plate
    from drum_textures import ASSETS
    from geometry import box,mesh
    from materials import material
    from profiles import drum_profile,make_drum_mesh
    from corrosion_preview import weathered_maps,swollen_profile,dome_lid
    from training_capture import camera
    from isaacsim.core.experimental.utils.semantics import add_labels
    # A disk anchor makes relative texture paths unambiguous. Never export a hall file.
    context=omni.usd.get_context()
    anchor=out/'studio.usda'
    context.get_stage().GetRootLayer().Export(str(anchor));context.open_stage(str(anchor))
    stage=context.get_stage()
    UsdGeom.SetStageMetersPerUnit(stage,1.)
    UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    UsdGeom.Xform.Define(stage,'/World')
    stage.SetDefaultPrim(stage.GetPrimAtPath('/World'))
    rng=np.random.default_rng(seed)
    specification=diversity_spec(seed,frame_count)
    environment=specification['environment']
    floor=material(stage,'PilotFloor',environment['floor_color'],environment['floor_roughness'])
    wall=material(stage,'PilotWall',environment['wall_color'],.9)
    box(stage,'/World/Floor',(0,0,-.055),(14,14,.1),floor,collision=True)
    for name,center,size in [('North',(0,6,2),(12,.1,4)),('South',(0,-6,2),(12,.1,4)),
                             ('East',(6,0,2),(.1,12,4)),('West',(-6,0,2),(.1,12,4))]:
        box(stage,'/World/Walls/'+name,center,size,wall)
    dome=UsdLux.DomeLight.Define(stage,'/World/Ambient');dome.CreateIntensityAttr(environment['ambient_power'])
    lights=[]
    for light_spec in environment['lights']:
        name=light_spec['name'];xyz=light_spec['position'];power=light_spec['power']
        light=UsdLux.RectLight.Define(stage,'/World/'+name)
        light.CreateWidthAttr(light_spec['size_m']);light.CreateHeightAttr(light_spec['size_m']);light.CreateIntensityAttr(power)
        light.CreateColorTemperatureAttr(light_spec['temperature_k']);light.CreateEnableColorTemperatureAttr(True)
        pose=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*xyz),Gf.Vec3d(0,0,.4),Gf.Vec3d(0,0,1)).GetInverse()
        UsdGeom.Xformable(light).AddTransformOp().Set(pose)
        lights.append((light,power))
    clutter=material(stage,'Clutter',(.25,.27,.28),.8)
    for i,item in enumerate(environment['clutter']):
        box(stage,f'/World/Clutter/Crate{i}',item['position'],item['size'],clutter)
    occluder=box(stage,'/World/Occluder',(0,0,.16),(.46,.40,.32),clutter)
    entries=specification['entries']
    print('PILOT_PHASE '+json.dumps(dict(state='building_assets',seed=seed)),flush=True)
    materials=drum_materials(stage,42)
    canonical=make_inventory()
    for spec in entries:
        entry=next(dict(e) for e in canonical if e['id']==spec['id'])
        entry.update(spec);entry.update(prim_path='/World/Drums/'+entry['id'],row='A',paint_color='faded_yellow')
        base,oxide,alpha=weathered_maps(seed=spec['rust_seed'])
        # Move the field around the circumference without changing its physical style.
        # The same shift must be applied to all oxide maps and occupancy alpha.
        from PIL import Image
        shift=int(rng.integers(1024))
        for path in oxide.values():
            with Image.open(path) as img: arr=np.asarray(img).copy()
            Image.fromarray(np.roll(arr,shift,axis=1)).save(path)
        alpha=np.roll(alpha,shift,axis=1)
        paint=material(stage,'PilotPaint_'+entry['id'],(1,1,1),.5,textures=base)
        local_materials={**materials,'faded_yellow':paint,'faded_yellow_lid':paint}
        # Shared generator caches by stable ID. Invalidate only this container's copy.
        (ASSETS/f"plate_{entry['id']}_LLW_v2.png").unlink(missing_ok=True)
        create_drum(stage,entry,local_materials)
        profile=swollen_profile(spec['radial_fraction']) if spec['bulge'] else drum_profile('LLW')
        if spec['bulge']:
            stage.RemovePrim(entry['prim_path']+'/Body')
            data=make_drum_mesh(profile)
            body=mesh(stage,entry['prim_path']+'/Body',data['points'],data['faces'],data['uv'],paint)
            body.CreateNormalsAttr(data['normals']);body.SetNormalsInterpolation('faceVarying')
            UsdPhysics.CollisionAPI.Apply(body.GetPrim())
            dome_lid(stage,entry,paint,rise=spec['lid_rise_m'])
            for part in ('BungLarge','BungSmall'):
                op=UsdGeom.Xformable(stage.GetPrimAtPath(entry['prim_path']+'/'+part)).GetOrderedXformOps()[0]
                t=op.Get(); r=math.hypot(t[0],t[1]);t[2]+=spec['lid_rise_m']*(1-(r/.269)**2)**1.5;op.Set(t)
        stage.RemovePrim(entry['prim_path']+'/Plate');create_plate(stage,entry,profile)
        root=stage.GetPrimAtPath(entry['prim_path'])
        add_labels(root,labels=['drum'],taxonomy='class');add_labels(root,labels=[entry['id']],taxonomy='drum_id')
        spec['max_diameter_m']=2*max(r for r,z in profile)
        spec['rust_circumference_shift_px']=shift
        spec['rust_cluster_count']=rust_clusters(stage,entry,oxide,alpha,profile) if spec['rust'] else 0
    settings=carb.settings.get_settings()
    for key in ('/app/viewport/grid/enabled','/app/viewport/defaults/guide/grid/visible','/rtx/post/histogram/enabled'):
        settings.set_bool(key,False)
    settings.set_float('/rtx/post/tonemap/filmIso',200.)
    settings.set_float('/rtx/post/tonemap/fNumber',4.)
    settings.set_float('/rtx/post/tonemap/cameraShutter',60.)
    build_seconds=time.perf_counter()-started
    # One camera/product reused across frames: visibility is scene-wide, so a
    # single-barrel frame cannot share a simultaneous capture with context views.
    path=camera(stage,'/World/Cameras/Inspection',(0,-2,.6),(0,0,.47),22.5,(640,640))
    product=rep.create.render_product(path,(640,640))
    render_started=time.perf_counter()
    counts={c:0 for c in CLASSES}
    frame_reports=[]
    for i,view in enumerate(specification['frames']):
        print('PILOT_PHASE '+json.dumps(dict(state='rendering',seed=seed,frame=i,mode=view['mode'])),flush=True)
        active=[e for e in entries if view['mode']=='context' or e['id']==view['target_id']]
        active_ids={e['id'] for e in active}
        for entry in entries:
            for root in ('/World/Drums/','/World/Defects/'):
                prim=stage.GetPrimAtPath(root+entry['id'])
                if prim:
                    imageable=UsdGeom.Imageable(prim)
                    if entry['id'] in active_ids:imageable.MakeVisible()
                    else:imageable.MakeInvisible()
        if i%5==4:
            occluder.MakeVisible()
            ops=UsdGeom.Xformable(occluder).GetOrderedXformOps()
            angle=view['bearing_rad']
            ops[0].Set(Gf.Vec3d(1.35*math.cos(angle),1.35*math.sin(angle),.16))
        else:occluder.MakeInvisible()
        camera(stage,path,view['eye'],view['target'],22.5,(640,640))
        for light,power in lights:light.GetIntensityAttr().Set(power*view['light_scale'])
        directory=out/f'frame_{i:03d}';directory.mkdir()
        writer=rep.WriterRegistry.get('BasicWriter')
        writer.initialize(output_dir=str(directory),rgb=True,bounding_box_2d_tight=True,semantic_types=['class','drum_id'])
        writer.attach([product])
        # Flush the previous pose/visibility/lighting before requesting annotation.
        for _ in range(30 if i==0 else 6):app.update()
        rep.orchestrator.step(rt_subframes=4,delta_time=0.,pause_timeline=True)
        rep.orchestrator.wait_until_complete()
        writer.detach()
        meta=dict(**view,width=640,height=640,fx=400,fy=400,cx=320,cy=320,focal_mm=22.5,
                  horizontal_aperture_mm=36,environment=environment)
        frame_counts=export_frame(directory,active,meta)
        frame_reports.append(dict(frame=i,mode=view['mode'],class_counts=frame_counts,
                                  elapsed_seconds=time.perf_counter()-render_started))
        for c in counts:counts[c]+=frame_counts[c]
        print('PILOT_PROGRESS '+json.dumps(dict(seed=seed,completed=len(list(out.glob('frame_*/metadata.json'))),target=frame_count)),flush=True)
    rep.orchestrator.stop()
    assert all(counts.values()),counts
    report=dict(seed=seed,version=specification['version'],images=frame_count,classes=CLASSES,class_counts=counts,entries=entries,
                environment=environment,frames=frame_reports,build_seconds=build_seconds,
                capture_and_export_seconds=time.perf_counter()-render_started,
                total_script_seconds=time.perf_counter()-started)
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print('PILOT_OK '+json.dumps(report),flush=True)
    app.close(wait_for_replicator=False)


if __name__=='__main__':main()
