"""One isolated barrel design plus a normal/bulged pressure-risk comparison."""
import copy
import json
import os
from pathlib import Path
SIM=Path(__file__).resolve().parent
OUT=SIM/'out/barrel_preview'
SHARD=int(os.environ.get('ISAAC_VIEW_SHARD','0'))
SHARDS=int(os.environ.get('ISAAC_VIEW_SHARDS','1'))
if SHARDS>1:OUT=OUT/f'shard_{SHARD:02d}'

if __name__=='__main__':
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'RayTracedLighting','display_options':0})
    import omni.usd
    import carb
    from pxr import UsdGeom,UsdLux,Gf,UsdShade,UsdPhysics
    from drums import make_inventory,drum_materials,create_drum,create_plate
    from materials import material
    from geometry import box,mesh
    from profiles import make_drum_mesh,drum_profile
    from corrosion_preview import weathered_maps,build_oxide,swollen_profile,dome_lid
    from capture_hall import capture_views
    OUT.mkdir(parents=True,exist_ok=True)
    context=omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM/'scene_barrel_preview.usda'))
    context.open_stage(str(SIM/'scene_barrel_preview.usda'))
    stage=context.get_stage()
    UsdGeom.SetStageMetersPerUnit(stage,1.)
    UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    UsdGeom.Xform.Define(stage,'/World')
    stage.SetDefaultPrim(stage.GetPrimAtPath('/World'))
    ground=material(stage,'PreviewFloor',(.29,.31,.30),.65)
    wall=material(stage,'PreviewWall',(.40,.43,.43),.9)
    box(stage,'/World/Floor',(0,0,-.055),(12,12,.1),ground)
    box(stage,'/World/Backdrop',(0,2,2),(12,.1,4),wall)
    for name,xyz,width,height,power in [('Key',(-2,-3,3),3,3,1800),('Fill',(3,-1,2.4),2,2,1000),('Top',(0,1,3),2,2,1400)]:
        light=UsdLux.RectLight.Define(stage,'/World/'+name)
        light.CreateWidthAttr(width);light.CreateHeightAttr(height);light.CreateIntensityAttr(power)
        pose=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*xyz),Gf.Vec3d(0,0,.4),Gf.Vec3d(0,0,1)).GetInverse()
        UsdGeom.Xformable(light).AddTransformOp().Set(pose)
    dome=UsdLux.DomeLight.Define(stage,'/World/Ambient');dome.CreateIntensityAttr(160)
    UsdLux.ShadowAPI.Apply(dome.GetPrim()).CreateShadowEnableAttr(False)
    base_maps,oxide_maps,alpha=weathered_maps()
    materials=drum_materials(stage,42)
    materials['faded_yellow']=material(stage,'PreviewWeatheredPaint',(1,1,1),.5,textures=base_maps)
    materials['faded_yellow_lid']=materials['faded_yellow']
    details=[]
    for name,x,bulged,rusty,drum_id in [('NormalRusted',-.95,False,True,'D03'),('BulgedClean',0.,True,False,'D05'),('BulgedRusted',.95,True,True,'D10')]:
        entry=copy.deepcopy(next(e for e in make_inventory() if e['id']==drum_id))
        tag=entry['display_id']
        entry['paint_color']='faded_yellow'
        entry.update(x=x,y=0,yaw=0.,prim_path='/World/'+name)
        create_drum(stage,entry,materials)
        profile=swollen_profile() if bulged else drum_profile('LLW')
        if bulged:
            data=make_drum_mesh(profile)
            stage.RemovePrim(entry['prim_path']+'/Body')
            body=mesh(stage,entry['prim_path']+'/Body',data['points'],data['faces'],data['uv'],materials['faded_yellow'])
            body.CreateNormalsAttr(data['normals']);body.SetNormalsInterpolation('faceVarying')
            dome_lid(stage,entry,materials['faded_yellow_lid'])
            # Lift bung centres to follow the dome surface.
            for part,xy in [('BungLarge',(.13,.04)),('BungSmall',(-.13,-.04))]:
                prim=stage.GetPrimAtPath(entry['prim_path']+'/'+part)
                ops=UsdGeom.Xformable(prim).GetOrderedXformOps()
                t=ops[0].Get(); r=(xy[0]**2+xy[1]**2)**.5
                t[2]+=.070*(1-(r/.278)**2)**1.5
                ops[0].Set(t)
            # Plate stays on the outside of the swollen body, never buried in steel.
            plate=UsdGeom.Mesh(stage.GetPrimAtPath(entry['prim_path']+'/Plate'))
            from profiles import radius_at
            pts=plate.GetPointsAttr().Get()
            for p in pts:
                old=(p[0]**2+p[1]**2)**.5
                factor=(radius_at(profile,p[2])+.002)/old
                p[0]*=factor;p[1]*=factor
            plate.GetPointsAttr().Set(pts)
        # Use the actual repository plate generator, with all preview plates facing the review camera.
        stage.RemovePrim(entry['prim_path']+'/Plate')
        create_plate(stage,{**entry,'row':'A'},profile)
        if rusty: build_oxide(stage,entry,oxide_maps,alpha,profile)
        details.append({'name':name,'display_label':tag,'internal_id':entry['id'],'rusted':rusty,'nominal_radius_m':.299,'height_m':.88,
                        'radial_swelling_fraction':.08 if bulged else 0,
                        'lid_dome_rise_m':.07 if bulged else 0})
    # Reapply fixed exposure after creating assets and materials.
    settings=carb.settings.get_settings()
    settings.set_bool('/app/viewport/grid/enabled',False)
    settings.set_bool('/app/viewport/defaults/guide/grid/visible',False)
    settings.set_bool('/rtx/post/histogram/enabled',False)
    settings.set_float('/rtx/post/tonemap/filmIso',200.)
    settings.set_float('/rtx/post/tonemap/fNumber',4.)
    settings.set_float('/rtx/post/tonemap/cameraShutter',60.)
    views={'rust_barrel':((-.60,-2.0,1.25),(-.95,0,.44),49),
           'normal_vs_bulged':((0,-4.3,1.6),(0,0,.46),49),
           'bulged_clean':((.20,-1.9,1.20),(0,0,.46),49),
           'bulged_rusted':((1.20,-1.9,1.20),(.95,0,.46),49),
           'bulged_lid':((1.2,-1.5,1.12),(.95,0,.76),56)}
    views={name:pose for index,(name,pose) in enumerate(views.items()) if index%SHARDS==SHARD}
    assert views,'Empty view shard'
    report={'shard':SHARD,'shards':SHARDS,'seed':74,'scope':'isolated appearance study; full hall not changed',
            'barrels':details,'views':capture_views(app,stage,views,OUT),
            'renderer_gpu_settings':{key:settings.get(key) for key in ('/renderer/multiGpu/enabled','/renderer/multiGpu/maxGpuCount','/renderer/multiGpu/activeCudaGpus')},
            'limits':['Bulge is an illustrative pressure/expansion cue, not a confirmed gas measurement',
                      'No pressure, gas chemistry, shell mechanics or rupture physics simulated']}
    stage.GetRootLayer().Save()
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('BARREL_PREVIEW_OK',flush=True)
    app.close(wait_for_replicator=False)
