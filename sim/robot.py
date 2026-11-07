"""Bundled Spot asset and body-mounted RGB/depth capture. No walking policy here."""
import json
import math
from pathlib import Path
import shutil
import numpy as np

_camera_path=None
_robot_path='/World/Spot'


def load_robot(position=(1,6,.55),yaw=0):
    from isaacsim.storage.native import get_assets_root_path
    from isaacsim.core.experimental.utils.stage import get_current_stage
    from pxr import UsdGeom,Gf,Usd,UsdPhysics
    stage=get_current_stage()
    if stage.GetPrimAtPath(_robot_path): stage.RemovePrim(_robot_path)
    root=UsdGeom.Xform.Define(stage,_robot_path)
    root.AddTranslateOp().Set(Gf.Vec3d(*position))
    root.AddRotateZOp().Set(math.degrees(yaw))
    asset=str(get_assets_root_path())+'/Isaac/Robots/BostonDynamics/spot/spot.usd'
    model=stage.DefinePrim(_robot_path+'/Robot','Xform')
    if not model.GetReferences().AddReference(asset): raise RuntimeError('Failed to load bundled Spot asset')
    bodies=[p for p in Usd.PrimRange(model) if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    body=next((p for p in bodies if p.GetName().lower() in ('body','base','base_link')),None)
    if body is None:
        raise RuntimeError('Spot body link not found: '+str([str(p.GetPath()) for p in bodies]))
    return {'root':_robot_path,'body':str(body.GetPath()),'asset':asset,'mode':'static_pose_camera_validation'}


def attach_cameras(body_path,height_world_m=.6):
    """A real camera child of the body link: local +X, 10 degrees down, 78 deg FOV."""
    global _camera_path
    from isaacsim.core.experimental.utils.stage import get_current_stage
    from pxr import UsdGeom,Gf
    from training_capture import camera
    stage=get_current_stage()
    body=stage.GetPrimAtPath(body_path)
    body_world=UsdGeom.XformCache().GetLocalToWorldTransform(body)
    local_height=height_world_m-body_world.ExtractTranslation()[2]
    eye=(.48,0,float(local_height)); target=(1.48,0,float(local_height)-math.tan(math.radians(10)))
    _camera_path=camera(stage,body_path+'/InspectionCamera',eye,target,22.5,(640,640))
    return _camera_path


def capture_frame(out_dir,app,frame_index=0,sim_time_s=0.0):
    """Save RGB, float32 optical depth, metadata, tight boxes and YOLO labels."""
    from isaacsim.core.experimental.utils.stage import get_current_stage
    from pxr import UsdGeom
    from training_capture import attach_capture,finish_captures
    if _camera_path is None: raise RuntimeError('Call attach_cameras after loading Spot')
    stage=get_current_stage()
    output=Path(out_dir); name=f'frame_{frame_index:04d}'
    captures=[attach_capture(stage,name,_camera_path,output)]
    reports=finish_captures(app,captures)
    directory=output/name
    rgb=next(directory.glob('rgb*.png'))
    raw=next(directory.glob('distance_to_image_plane*.npy'))
    shutil.copy2(rgb,output/f'rgb_{frame_index:04d}.png')
    depth=np.load(raw).astype(np.float32)
    np.save(output/f'depth_{frame_index:04d}.npy',depth)
    camera=UsdGeom.Camera(stage.GetPrimAtPath(_camera_path))
    cache=UsdGeom.XformCache()
    transform=cache.GetLocalToWorldTransform(camera.GetPrim())
    robot=cache.GetLocalToWorldTransform(stage.GetPrimAtPath(_robot_path))
    pos=robot.ExtractTranslation(); rotation=robot.ExtractRotationMatrix()
    camera_pos=transform.ExtractTranslation()
    focal=camera.GetFocalLengthAttr().Get(); aperture=camera.GetHorizontalApertureAttr().Get()
    meta={'robot_pose':{'x':pos[0],'y':pos[1],'yaw':math.atan2(rotation[0][1],rotation[0][0])},
          'camera_prim_path':_camera_path,'camera_world_position':list(camera_pos),
          'camera_world_transform':[[transform[i][j] for j in range(4)] for i in range(4)],
          'camera_axes':'USD: right +X, up +Y, view -Z; row-major world matrix',
          'intrinsics':{'fx':640*focal/aperture,'fy':640*focal/aperture,'cx':320,'cy':320,'width':640,'height':640},
          'sim_time_s':sim_time_s,'depth_units':'metres','depth_type':'optical_axis',
          'mode':'static_pose; no autonomous navigation or gait claimed'}
    (output/f'meta_{frame_index:04d}.json').write_text(json.dumps(meta,indent=2)+'\n')
    finite=np.isfinite(depth)&(depth>0)
    assert depth.shape==(640,640) and finite.mean()>.5
    return {'metadata':meta,'capture':reports[name],'depth_min_m':float(depth[finite].min()),
            'depth_max_m':float(depth[finite].max())}
