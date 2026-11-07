"""Step 1: re-runnable, empty 20 x 12 x 6 m waste-storage hall."""
from pathlib import Path
import time

SIM = Path(__file__).resolve().parent


def build_scene(seed=42):
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
    mats = {
        'floor':material(stage,'Floor',(.6,.6,.6),textures=bank['floor']),
        'side':material(stage,'SideWall',(.6,.6,.6),textures=bank['wall'],uv_scale=(20/4.8,1)),
        'end':material(stage,'EndWall',(.6,.6,.6),textures=bank['wall'],uv_scale=(13/4.8,1)),
        'ceiling':material(stage,'Ceiling',(.50,.52,.48),.85),
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
    for name,x in (('llw',1.5),('ilw',10.8)):
        points = [(-.3,2.5,0),(-.3,-2.5,0),(.3,-2.5,0),(.3,2.5,0)]
        mesh(stage,root+'Markings/'+name.upper(),points,[(0,1,2,3)],
             [(0,0),(1,0),(1,1),(0,1)],mats['floor_'+name],(x,6,.0015))
    for name,center,size,kind in (
        ('WallSouth',(10,-.25,3),(20,.5,6),'side'),
        ('WallNorth',(10,12.25,3),(20,.5,6),'side'),
        ('WallFront',(-.25,6,3),(.5,13,6),'end'),
        ('WallBack',(20.25,6,3),(.5,13,6),'end')):
        box(stage,root+name,center,size,mats[kind],collision=True)
    box(stage,root+'Ceiling',(10,6,6.15),(21,13,.3),mats['ceiling'])
    details = root+'Details/'
    def detail(name,center,size,kind,**kwargs):
        return box(stage,details+name,center,size,mats[kind],**kwargs)
    detail('RollerShutter',(.035,6,2.05),(.06,3,4.1),'roller')
    for side,y in (('Left',4.42),('Right',7.58)):
        detail('ShutterRail'+side,(.10,y,2.08),(.17,.12,4.16),'steel')
    detail('PersonnelDoor',(.045,2.5,1.1),(.08,1,2.2),'door')
    detail('DoorWindow',(.091,2.5,1.62),(.018,.42,.52),'glass')
    detail('DoorHandle',(.12,2.14,1.05),(.06,.04,.22),'steel')
    panel(stage,details+'RadiationSign',(.11,3.55,1.95),.8,.8,(1,0,0),mats['radiation'])
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
        panel(stage,details+name.upper()+'ZoneSign',(x,11.985,2.35),1.35,1.05,(0,-1,0),mats[name])
    detail('FirePoint',(.13,9.65,1.35),(.16,.8,1.05),'fire')
    cylinder(stage,details+'Extinguisher',(.34,10.35,.9),.11,.62,mats['red'])
    # Dry grates stay inside wall margins, leaving every aisle clear.
    for name,y in (('South',.5),('North',11.5)):
        detail('Drain'+name,(10,y,.003),(.5,.5,.006),'drain')

    for row,y in enumerate((4,8),1):
        for number,x in enumerate((3.8,7.8,12.3,16.3),1):
            name = f'Row{row}_L{number:02d}'
            box(stage,root+'Lights/'+name+'_Housing',(x,y,5.56),(1.6,.65,.14),mats['fixture'])
            light = UsdLux.RectLight.Define(stage,root+'Lights/'+name)
            light.CreateWidthAttr(1.4)
            light.CreateHeightAttr(.45)
            light.CreateIntensityAttr(4500 * (.4 if (row,number)==(2,4) else 1))
            light.CreateEnableColorTemperatureAttr(True)
            light.CreateColorTemperatureAttr(5000)
            UsdGeom.Xformable(light).AddTranslateOp().Set(Gf.Vec3d(x,y,5.48))
    ambient = UsdLux.DomeLight.Define(stage,root+'Lights/Ambient')
    ambient.CreateIntensityAttr(90)
    UsdLux.ShadowAPI.Apply(ambient.GetPrim()).CreateShadowEnableAttr(False)
    write_aisles()
    return {'seed':seed,'build_seconds':round(time.perf_counter()-started,3),
            'hall_interior':[20,12,6],'extra_detail_meshes':32,'failed_fixture':'Row2_L04',
            'camera_exposure':{'iso':400,'f_number':2.8,'shutter_reciprocal_seconds':60}}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed',type=int,default=42)
    args,_ = parser.parse_known_args()
    from isaacsim import SimulationApp
    app = SimulationApp({'headless':True,'renderer':'RayTracedLighting'})
    import omni.usd
    stage = omni.usd.get_context().get_stage()
    stage.GetRootLayer().Export(str(SIM/'hall.usda'))
    omni.usd.get_context().open_stage(str(SIM/'hall.usda'))
    print(build_scene(args.seed),flush=True)
    omni.usd.get_context().get_stage().GetRootLayer().Save()
    app.close(wait_for_replicator=False)
