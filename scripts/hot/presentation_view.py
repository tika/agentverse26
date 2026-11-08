"""Corner spectator for the recording only. Never a model/sensor input."""
from isaacsim.sensors.camera import Camera as PresentationCamera
from pxr import Gf
PRESENTATION_PATH='/World/Presentation/CornerCamera'
if 'presentation_camera' not in state:
    camera=PresentationCamera(PRESENTATION_PATH,resolution=(384,216))
    camera.prim.GetAttribute('focalLength').Set(16.)
    camera.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(.05,60.))
    camera.initialize()
    state['presentation_camera']=camera


def update_presentation():
    p,yaw=pose();heading=np.array([math.cos(yaw),math.sin(yaw),0.])
    eye=p-3.4*heading+[0,0,1.9]
    for angle in (yaw+math.pi,yaw+math.pi-.8,yaw+math.pi+.8,yaw):
        candidate=p+np.array([3.4*math.cos(angle),3.4*math.sin(angle),1.9])
        if .65<candidate[0]<19.35 and .65<candidate[1]<11.35:eye=candidate;break
    eye[:2]=np.clip(eye[:2],[.65,.65],[19.35,11.35])
    matrix=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float,eye)),Gf.Vec3d(*map(float,p+[0,0,.05])),Gf.Vec3d(0,0,1))
    q=matrix.GetInverse().ExtractRotationQuat()
    state['presentation_camera'].set_world_pose(position=np.array(eye),
        orientation=np.array([q.GetReal(),*q.GetImaginary()]),camera_axes='usd')


def presentation_pixels():
    return np.asarray(state['presentation_camera'].get_rgba())[:,:,:3].astype(np.uint8)
