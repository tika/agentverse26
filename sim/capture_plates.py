"""Close-ups of the printed drum ID plates in the full hall, one camera moved between shots."""
import json
from pathlib import Path
import shutil
import numpy as np
from PIL import Image

SIM=Path(__file__).resolve().parent
OUTPUT=SIM/'out/plates'
ROW_FACING={'A':-1,'B':1,'C':-1,'D':1}  # Plates face their aisle along world y (drums.py ROWS).
CLOSE_UPS=('A01','B02','C05','D06')


if __name__=='__main__':
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'RayTracedLighting','display_options':0})
    import omni.usd
    import omni.replicator.core as rep
    from pxr import Gf,UsdLux
    from layouts import load_layout
    from training_capture import camera
    from capture_presentation import fixed_exposure,set_pose
    OUTPUT.mkdir(parents=True,exist_ok=True)
    context=omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM/'scene_plates.usda'))
    context.open_stage(str(SIM/'scene_plates.usda'))
    load_layout()
    stage=context.get_stage()
    drums={d['display_id']:d for d in json.loads((SIM/'drums.json').read_text())}
    views={}
    for drum_id in CLOSE_UPS:
        drum=drums[drum_id]
        facing=ROW_FACING[drum['row']]
        x,y,z=drum['x'],drum['y'],drum['height']*.6
        lamp=UsdLux.SphereLight.Define(stage,f'/World/PlateLight_{drum_id}')
        lamp.CreateIntensityAttr(650);lamp.CreateRadiusAttr(.25)
        lamp.AddTranslateOp().Set(Gf.Vec3d(x+.32,y+facing*1.1,z+.45))
        views[drum_id]=((x,y+facing*(drum['radius']+.85),z),(x,y,z),42)
    # Row C ILW drums from their aisle, so several IDs are legible in one frame.
    views['aisle_C05_C07']=((12.6,5.6,1.15),(14.6,7.45,.6),18)
    path=camera(stage,'/World/PlateCamera',(0,0,1),(1,0,1),42,(1024,640))
    product=rep.create.render_product(path,(1024,640))
    writer=rep.WriterRegistry.get('BasicWriter')
    raw=OUTPUT/'frames';raw.mkdir(exist_ok=True)
    writer.initialize(output_dir=str(raw),rgb=True)
    writer.attach([product])
    for _ in range(40):
        app.update();fixed_exposure()
    for eye,target,focal in views.values():
        set_pose(stage,path,eye,target,focal)
        fixed_exposure()
        for _ in range(4): app.update()
        rep.orchestrator.step(rt_subframes=8,delta_time=0.,pause_timeline=True)
    rep.orchestrator.wait_until_complete()
    writer.detach()
    images=sorted(raw.glob('rgb*.png'))
    assert len(images)==len(views),(len(images),len(views))
    for name,source in zip(views,images):
        pixels=np.asarray(Image.open(source))[:,:,:3]
        assert pixels.mean()>10,'Badly exposed plate view '+name
        shutil.copy2(source,OUTPUT/(name+'.png'))
    shutil.rmtree(raw)
    (OUTPUT/'views.json').write_text(json.dumps(views,indent=2)+'\n')
    print('PLATES_CAPTURE_OK',flush=True)
    app.close(wait_for_replicator=False)
