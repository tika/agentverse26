"""Re-runnable 20 x 12 x 6 m storage hall and the fixed clean-drum layout."""
from pathlib import Path
import time
import math

SIM = Path(__file__).resolve().parent


def build_scene(seed=42, include_drums=True):
    import carb
    from pxr import Gf, UsdGeom, UsdLux
    from isaacsim.core.experimental.utils.stage import get_current_stage
    from textures import generate_textures
    from materials import material
    from geometry import box, cylinder, panel, mesh
    from aisles import write_aisles

    started = time.perf_counter()
    # Fixed indoor camera exposure; keep the physical lights at their set power.
    settings = carb.settings.get_settings()
    settings.set_bool('/rtx/post/histogram/enabled',False)
    settings.set_float('/rtx/post/tonemap/filmIso',400.0)
    settings.set_float('/rtx/post/tonemap/fNumber',2.8)
    settings.set_float('/rtx/post/tonemap/cameraShutter',60.0)
    stage = get_current_stage()
    UsdGeom.Xform.Define(stage,'/World')
    for path in ('/World/Hall', '/World/Drums', '/World/Defects', '/World/Obstructions'):
        if stage.GetPrimAtPath(path): stage.RemovePrim(path)
        UsdGeom.Xform.Define(stage,path)
    stage.SetDefaultPrim(stage.GetPrimAtPath('/World'))
    UsdGeom.SetStageMetersPerUnit(stage,1.0)
    UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    for folder in ('Materials','Details','Lights','Markings'):
        UsdGeom.Scope.Define(stage,'/World/Hall/'+folder)
    bank = generate_textures(seed)
    # One 1 m square tile, ten vertical corrugations with 6 mm peak amplitude.
    import numpy as np
    from PIL import Image
    normal_path = SIM / 'assets/generated/cladding_1m_normal.png'
    u = np.arange(512) / 512
    slope = .006 * 2 * np.pi * 10 * np.cos(2 * np.pi * 10 * u)
    normals = np.stack((-slope, np.zeros_like(slope), np.ones_like(slope)), axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    pixels = np.broadcast_to((normals * .5 + .5)[None, :, :], (512,512,3))
    Image.fromarray(np.uint8(pixels * 255)).save(normal_path)
    mats = {
        'floor':material(stage,'Floor',(.38,.38,.38),.72),
        'side':material(stage,'SideWall',(.40,.44,.47),.55,.25, textures={'normal':normal_path},uv_scale=(20,6)),
        'end':material(stage,'EndWall',(.40,.44,.47),.55,.25,textures={'normal':normal_path},uv_scale=(12,6)),
        'ceiling':material(stage,'Ceiling',(.78,.78,.78),.85,emission=(.08,.08,.08)),
        'steel':material(stage,'Steel',(.23,.27,.28),.43,.65),
        'duct':material(stage,'Duct',(.38,.42,.42),.55,.45),
        'yellow':material(stage,'CraneYellow',(.72,.48,.035),.48,.25),
        'door':material(stage,'PersonnelDoor',(.17,.28,.24),.5,.2),
        'glass':material(stage,'DarkGlass',(.025,.055,.065),.16,.1),
        'monitor':material(stage,'MonitorHousing',(.42,.45,.43),.6,.1),
        'amber':material(stage,'Amber',(.85,.32,.025),.3,emission=(.6,.15,.01)),
        'red':material(stage,'FireRed',(.60,.035,.02),.45),
        'fixture':material(stage,'Fixture',(.58,.61,.60),.4,.35,emission=(.8,.85,1.0)),
        'roller':material(stage,'RollerShutter',(.5,.5,.5),.48,.35,textures=bank['roller']),
    }
    for name in ('radiation','llw','ilw','fire','floor_llw','floor_ilw','drain'):
        mats[name] = material(stage,name,(1,1,1),.65,textures=bank[name])
    root = '/World/Hall/'
    box(stage,root+'Floor',(10,6,-.15),(20,12,.3),mats['floor'],collision=True)
    for name,center,size,kind in (
        ('WallSouth',(10,-.25,3),(20,.5,6),'side'),
        ('WallNorth',(10,12.25,3),(20,.5,6),'side'),
        ('WallFront',(-.25,6,3),(.5,13,6),'end'),
        ('WallBack',(20.25,6,3),(.5,13,6),'end')):
        box(stage,root+name,center,size,mats[kind],collision=True)
    # Two pitched roof planes meet at z=6 m, with eaves at z=5.2 m.
    for side,y in ((-1,3),(1,9)):
        box(stage,root+f'Roof{side+1}',(10,y,5.6),(20.5,6.05,.12),mats['ceiling'],
            rotation=(side * -math.degrees(math.atan2(.8,6)),0,0))
    skylight = material(stage,'Skylight',(.74,.77,.79),.45,emission=(3.,3.,3.))
    for x in (4,10,16):
        box(stage,root+f'Skylight{x}',(x,4.4,5.69),(1.6,2.2,.025),skylight,
            rotation=(math.degrees(math.atan2(.8,6)),0,0))
    def beam(name,a,b,width=.09):
        vector=Gf.Vec3d(*b)-Gf.Vec3d(*a)
        centre=(Gf.Vec3d(*a)+Gf.Vec3d(*b))*.5
        part=box(stage,root+'Details/'+name,tuple(centre),(width,width,vector.GetLength()),mats['steel'])
        UsdGeom.Xformable(part).AddOrientOp().Set(Gf.Quatf(Gf.Rotation(Gf.Vec3d(0,0,1),vector).GetQuat()))
    for x in (2,6,10,14,18):
        beam(f'Truss{x}Bottom',(x,.2,5.1),(x,11.8,5.1),.12)
        beam(f'Truss{x}Left',(x,.2,5.15),(x,6,5.9),.12)
        beam(f'Truss{x}Right',(x,6,5.9),(x,11.8,5.15),.12)
        for j,y in enumerate((2,4,6,8,10)):
            top=5.9-abs(y-6)*.75/5.8
            beam(f'Truss{x}Web{j}',(x,y-1,5.1),(x,y,top))
    details = root+'Details/'
    def detail(name,center,size,kind,**kwargs):
        return box(stage,details+name,center,size,mats[kind],**kwargs)
    detail('RollerShutter',(.035,6,2.05),(.06,3,4.1),'roller')
    for side,y in (('Left',4.42),('Right',7.58)):
        detail('ShutterRail'+side,(.10,y,2.08),(.17,.12,4.16),'steel')
    detail('PersonnelDoor',(.045,2.5,1.1),(.08,1,2.2),'door')
    detail('DoorWindow',(.091,2.5,1.62),(.018,.42,.52),'glass')
    detail('DoorHandle',(.12,2.14,1.05),(.06,.04,.22),'steel')
    panel(stage,details+'RadiationSign',(.11,3.55,1.95),.5,.5,(1,0,0),mats['radiation'])
    for name,y in (('South',.35),('North',11.65)):
        detail('CraneRail'+name,(10,y,5.15),(20,.12,.18),'steel')
    detail('CraneBridge',(18.5,6,5.15),(.5,11.4,.45),'yellow')
    detail('CraneHoist',(18.5,6,4.76),(.72,1,.5),'yellow')
    detail('VentilationDuct',(10,6,5.73),(19,.7,.4),'duct')
    for name,y in (('South',.12),('North',11.88)):
        detail('CableTray'+name,(10,y,3.05),(19,.22,.12),'steel')
        for number,x in enumerate((6,15),1):
            detail(f'GammaMonitor{name}{number}',(x,y,1.95),(.38,.22,.42),'monitor')
            cylinder(stage,details+f'GammaBeacon{name}{number}',(x,y,2.26),.06,.14,mats['amber'])
    for number,center,direction in ((1,(1,.25,3.6),1),(2,(19,11.75,3.6),-1)):
        detail(f'CCTV{number}Body',center,(.4,.2,.18),'monitor')
        x,y,z = center
        cylinder(stage,details+f'CCTV{number}Lens',(x+.23*direction,y,z),.065,.08,mats['glass'],rotation=(0,90,0))
    for name,x in (('llw',4.8),('ilw',13.8)):
        panel(stage,details+name.upper()+'ZoneSign',(x,11.985,2.35),.6,.45,(0,-1,0),mats[name])
    detail('FirePoint',(.13,9.65,1.35),(.16,.8,1.05),'fire')
    cylinder(stage,details+'Extinguisher',(.34,10.35,.9),.11,.62,mats['red'])
    # Dry grates stay inside wall margins, leaving every aisle clear.
    for name,y in (('South',.5),('North',11.5)):
        detail('Drain'+name,(10,y,.003),(.5,.5,.006),'drain')

    for row,y in enumerate((4,8),1):
        for number,x in enumerate((3.8,7.8,12.3,16.3),1):
            name = f'Row{row}_L{number:02d}'
            cylinder(stage,root+'Lights/'+name+'_Stem',(x,y,5.2),.018,.55,mats['steel'])
            cylinder(stage,root+'Lights/'+name+'_Housing',(x,y,4.91),.25,.12,mats['steel'])
            cylinder(stage,root+'Lights/'+name+'_Diffuser',(x,y,4.84),.22,.02,mats['fixture'])
            light = UsdLux.RectLight.Define(stage,root+'Lights/'+name)
            light.CreateWidthAttr(1.4)
            light.CreateHeightAttr(.45)
            # Stage-2 F4: neutral white (no colour-temperature tint; the RTX tonemapper is not
            # white-balanced to 4500 K, which produced the rejected warm cast). 11000 overexposed the floor (~225/255); 6500 targets ~110-130.
            light.CreateIntensityAttr(10000 * (.4 if (row,number)==(2,4) else 1))
            light.CreateEnableColorTemperatureAttr(False)
            light.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
            UsdGeom.Xformable(light).AddTranslateOp().Set(Gf.Vec3d(x,y,4.81))
    ambient = UsdLux.DomeLight.Define(stage,root+'Lights/Ambient')
    ambient.CreateIntensityAttr(180)
    ambient.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
    UsdLux.ShadowAPI.Apply(ambient.GetPrim()).CreateShadowEnableAttr(False)
    write_aisles()
    if include_drums:
        from drums import build_drums
        build_drums(seed)
    return {'seed':seed,'build_seconds':round(time.perf_counter()-started,3),
            'drum_count':len(stage.GetPrimAtPath('/World/Drums').GetChildren()) if include_drums else 0,
            'cladding_tile_m':[1,1], 'corrugation_pitch_m':.1,
            'hall_interior':[20,12,6],'extra_detail_meshes':32,'failed_fixture':'Row2_L04',
            'camera_exposure':{'iso':400,'f_number':2.8,'shutter_reciprocal_seconds':60}}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--hall-only',action='store_true')
    args,_ = parser.parse_known_args()
    from isaacsim import SimulationApp
    app = SimulationApp({'headless':True,'renderer':'RayTracedLighting'})
    import omni.usd
    stage = omni.usd.get_context().get_stage()
    scene_file=SIM/('hall.usda' if args.hall_only else 'scene_drums.usda')
    stage.GetRootLayer().Export(str(scene_file))
    omni.usd.get_context().open_stage(str(scene_file))
    print(build_scene(args.seed,include_drums=not args.hall_only),flush=True)
    omni.usd.get_context().get_stage().GetRootLayer().Save()
    app.close(wait_for_replicator=False)
