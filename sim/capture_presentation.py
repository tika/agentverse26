"""Picture-ready environment stills and a real-rendered camera flythrough.

No actor motion is claimed: Spot is parked, and only the review camera moves.
The camera is reused so review-camera frustums do not clutter other views.
"""
import json
import math
from pathlib import Path
import shutil
import numpy as np
from PIL import Image

SIM=Path(__file__).resolve().parent
OUTPUT=SIM/'out/presentation'


def fixed_exposure(iso=400):
    import carb
    settings=carb.settings.get_settings()
    settings.set_bool('/app/viewport/grid/enabled',False)
    settings.set_bool('/app/viewport/defaults/guide/grid/visible',False)
    settings.set_bool('/rtx/post/histogram/enabled',False)
    settings.set_float('/rtx/post/tonemap/filmIso',float(iso))
    settings.set_float('/rtx/post/tonemap/fNumber',2.8)
    settings.set_float('/rtx/post/tonemap/cameraShutter',60.)


def set_pose(stage,path,eye,target,focal=24):
    from pxr import Gf,UsdGeom
    camera=UsdGeom.Camera(stage.GetPrimAtPath(path))
    transform=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse()
    UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Set(transform)
    camera.CreateFocalLengthAttr(focal)


if __name__=='__main__':
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'RayTracedLighting','display_options':0})
    import omni.usd
    import omni.replicator.core as rep
    from layouts import load_layout
    from robot import load_robot,attach_cameras
    from training_capture import camera
    OUTPUT.mkdir(parents=True,exist_ok=True)
    context=omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM/'scene_presentation.usda'))
    context.open_stage(str(SIM/'scene_presentation.usda'))
    load_layout()
    stage=context.get_stage()
    robot=load_robot((4.5,5.5,.55),math.pi/2)
    attach_cameras(robot['body'])
    path=camera(stage,'/World/PresentationCamera',(1.4,1.4,4.4),(11,6,1),22,(960,640))
    product=rep.create.render_product(path,(960,640))
    writer=rep.WriterRegistry.get('BasicWriter')
    raw=OUTPUT/'frames';raw.mkdir(exist_ok=True)
    writer.initialize(output_dir=str(raw),rgb=True)
    writer.attach([product])
    # Set exposure after asset load and camera creation, rather than relying on viewer defaults.
    for _ in range(40):
        app.update();fixed_exposure()
    manifest={'renderer':'RayTracedLighting','resolution':[960,640],
              'fixed_exposure':{'iso':400,'f_number':2.8,'shutter_reciprocal_s':60},
              'robot_motion':False,'stills':{},'video_frames':[]}
    frame=0
    def snap(eye,target,focal=24):
        global frame
        set_pose(stage,path,eye,target,focal)
        fixed_exposure()
        app.update();app.update()
        rep.orchestrator.step(rt_subframes=2,delta_time=0.,pause_timeline=True)
        manifest['video_frames'].append({'frame':frame,'eye':list(eye),'target':list(target),'focal_mm':focal})
        frame+=1
    stills={
      'hall_overview':((1.4,1.4,4.4),(11,6,1),22),
      'robot_in_hall':((1.6,4.0,2.2),(4.5,5.5,.55),24),
      'llw_corrosion':((7.7,5.65,1.15),(7.5,7.45,.42),35),
      'ilw_corrosion':((14.2,1.65,1.3),(14,3.45,.65),35),
      'llw_leak':((4.65,5.65,.95),(4.5,7.45,.40),34),
      'ilw_residue':((16.15,5.65,1.25),(16,7.45,.54),34)}
    for name,pose in stills.items():
        manifest['stills'][name]={'frame':frame,'eye':pose[0],'target':pose[1],'focal_mm':pose[2]}
        snap(*pose)
    # 80 actual rendered frames, 10 fps / 8 seconds; smooth orbit in clear aisle 2.
    manifest['video_start_frame']=frame
    for i in range(80):
        t=i/79
        angle=-math.pi*.70+math.pi*.42*t
        eye=(10+7*math.cos(angle),6+3*math.sin(angle),3.4-.7*t)
        target=(9.5+3*t,6, .65)
        snap(eye,target,22)
        if i%20==0: print('FLYTHROUGH_FRAME',i,flush=True)
    rep.orchestrator.wait_until_complete()
    writer.detach()
    images=sorted(raw.glob('rgb*.png'))
    assert len(images)==frame,(len(images),frame)
    for name,spec in manifest['stills'].items():
        source=images[spec['frame']]
        pixels=np.asarray(Image.open(source))[:,:,:3]
        assert pixels.mean()>10 and np.percentile(pixels,99)>40,'Badly exposed still '+name
        shutil.copy2(source,OUTPUT/(name+'.png'))
    video=OUTPUT/'video_frames';video.mkdir(exist_ok=True)
    for i,source in enumerate(images[manifest['video_start_frame']:]):
        shutil.copy2(source,video/f'{i:05d}.png')
    manifest['video_fps']=10
    manifest['video_frame_count']=80
    stage.GetRootLayer().Save()
    (OUTPUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('PRESENTATION_CAPTURE_OK',flush=True)
    app.close(wait_for_replicator=False)
