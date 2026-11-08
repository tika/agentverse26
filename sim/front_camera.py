"""Fixed front-camera calibration and projection; no target tracking or gimbal."""
import math
import numpy as np

CAMERA_PATH='/World/WalkingSpot/body/FrontCamera'
BODY_PATH='/World/WalkingSpot/body'
RESOLUTION=(1280,720)
MOUNT_XYZ=np.array([.60,0.,.12])
MOUNT_QUAT=np.array([1.,0.,0.,0.])  # Camera world convention: +X forward, +Z up.
HFOV_DEG=110.
HORIZONTAL_APERTURE=20.955
FOCAL_LENGTH=HORIZONTAL_APERTURE/(2*math.tan(math.radians(HFOV_DEG)/2))


def rotation(q):
    q=np.asarray(q,dtype=float);q=q/np.linalg.norm(q)
    w,x,y,z=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def rpy_rotation(roll,pitch,yaw):
    cr,sr=math.cos(roll),math.sin(roll);cp,sp=math.cos(pitch),math.sin(pitch);cy,sy=math.cos(yaw),math.sin(yaw)
    return np.array([[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],
                     [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]])


def expected_world_pose(body_position,body_quaternion):
    r=rotation(body_quaternion)
    return np.asarray(body_position)+r@MOUNT_XYZ,r


def backproject_xy(pixels,depths,k,estimate,roll=0.,pitch=0.):
    pixels=np.asarray(pixels);depths=np.asarray(depths)
    rays=np.column_stack([depths,-(pixels[:,0]-k[0,2])*depths/k[0,0],
                          -(pixels[:,1]-k[1,2])*depths/k[1,1]])
    points=(rays+MOUNT_XYZ)@rpy_rotation(roll,pitch,estimate[2]).T
    return points[:,:2]+np.asarray(estimate[:2])


def project_points(points,k,estimate,roll=0.,pitch=0.,body_height=.5):
    r=rpy_rotation(roll,pitch,estimate[2])
    camera_position=np.array([estimate[0],estimate[1],body_height])+r@MOUNT_XYZ
    local=(np.asarray(points)-camera_position)@r
    forward=local[:,0]
    uv=np.column_stack([k[0,2]-k[0,0]*local[:,1]/np.maximum(forward,1e-8),
                        k[1,2]-k[1,1]*local[:,2]/np.maximum(forward,1e-8)])
    return uv,forward


def crop_from_frame(rgb,box):
    x0,y0,x1,y1=map(int,box)
    if not (0<=x0<x1<=rgb.shape[1] and 0<=y0<y1<=rgb.shape[0]):
        raise ValueError('Crop is outside the front-camera frame')
    return rgb[y0:y1,x0:x1].copy()
