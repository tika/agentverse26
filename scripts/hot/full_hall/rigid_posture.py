"""Stationary, actuator-driven posture control; never moves a camera transform."""
import math,json
import numpy as np
from front_camera import rotation as rigid_rotation, expected_world_pose
_HIPS={'fl':(.29785,.055),'fr':(.29785,-.055),'hl':(-.29785,.055),'hr':(-.29785,-.055)}
def _rx1(a):
 c,s=math.cos(a),math.sin(a);return np.array([[1,0,0],[0,c,-s],[0,s,c]])
def _ry1(a):
 c,s=math.cos(a),math.sin(a);return np.array([[c,0,s],[0,1,0],[-s,0,c]])
def _rz1(a):
 c,s=math.cos(a),math.sin(a);return np.array([[c,-s,0],[s,c,0],[0,0,1]])
def _leg_fk(leg,q):
 hx,hy=_HIPS[leg];side=1 if leg[1]=='l' else -1
 return np.array([hx,hy,0.])+_rx1(q[0])@(np.array([0,side*.110945,0])+_ry1(q[1])@(np.array([.025,0,-.3205])+_ry1(q[2])@np.array([0.,0.,-.35])))
def body_angles():
 p,q=spot.articulation.get_world_poses();p=p.numpy().reshape(3);q=q.numpy().reshape(4);w,x,y,z=q
 return p,q,math.atan2(2*(w*x+y*z),1-2*(x*x+y*y)),math.asin(float(np.clip(2*(w*y-z*x),-1,1))),math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
class RigidPosture:
 def __init__(self):
  self.art=spot.articulation;self.names=list(self.art.dof_names);self.idx={leg:[self.names.index(leg+'_'+x) for x in ('hx','hy','kn')] for leg in _HIPS};self.active=False;self.elevation=0.;self.last_target=None
 def enter(self):
  p,q,roll,pitch,yaw=body_angles();self.base=p.copy();self.yaw=yaw;self.qref=self.art.get_dof_positions().numpy().reshape(-1).copy();r=rigid_rotation(q)
  self.feet={leg:p+r@_leg_fk(leg,self.qref[ids]) for leg,ids in self.idx.items()};self.feed=self.art.get_dof_efforts().numpy().reshape(-1).copy();self.gains=self.art.get_dof_gains();self.gains=[x.numpy().copy() for x in self.gains]
  spot._actuators.disable_auto_step_pre_physics();self.art.set_dof_gains(0.,0.,update_default_gains=False);self.target=self.qref.copy();self.elevation=-pitch;self.active=True
 def targets(self,elevation):
  elevation=float(np.clip(elevation,-.20,.20));r=_rz1(self.yaw)@_ry1(-elevation)
  desired={leg:r.T@(pt-self.base) for leg,pt in self.feet.items()}
  for leg,idx in self.idx.items():
   q=self.target[idx].copy()
   for _ in range(12):
    err=desired[leg]-_leg_fk(leg,q)
    if np.linalg.norm(err)<.0003:break
    eps=.0001;j=np.column_stack([(_leg_fk(leg,q+np.eye(3)[i]*eps)-_leg_fk(leg,q-np.eye(3)[i]*eps))/(2*eps) for i in range(3)])
    delta=np.linalg.solve(j.T@j+np.eye(3)*1e-6,j.T@err);q+=np.clip(delta,-.06,.06)
   self.target[idx]=q
 def step(self,dt,elevation):
  if not self.active:self.enter()
  self.elevation+=float(np.clip(elevation-self.elevation,-.18*dt,.18*dt));self.targets(self.elevation)
  q=self.art.get_dof_positions().numpy().reshape(-1);dq=self.art.get_dof_velocities().numpy().reshape(-1)
  torque=np.clip(self.feed+100.*(self.target-q)-5.*dq,-45.,45.)
  self.art.set_dof_efforts(torque[None,:].astype(np.float32))
 def leave(self):
  if self.active:
   self.art.set_dof_gains(self.gains[0],self.gains[1],update_default_gains=False);spot.initialize();spot._actuators.enable_auto_step_pre_physics();self.active=False
posture=RigidPosture()
