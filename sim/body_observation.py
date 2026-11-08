"""Small stationary leg-IK body poses for physical observation, not camera motion.

These commands use joint position targets and physics. They never set body or
camera poses directly. Hardware would use Spot's stand/body-pose command API.
"""
import math
import numpy as np
from front_camera import rpy_rotation

HIPS={'fl':(.29785,.055),'fr':(.29785,-.055),'hl':(-.29785,.055),'hr':(-.29785,-.055)}


def foot(q,leg):
    hx,hy,kn=q;side=1 if leg[1]=='l' else -1
    knee=np.array([.025,0.,-.3205])
    shank=rpy_rotation(0,kn,0)@np.array([0.,0.,-.35])
    thigh=rpy_rotation(0,hy,0)@(knee+shank)
    return np.array([*HIPS[leg],0.])+rpy_rotation(hx,0,0)@(np.array([0.,side*.110945,0.])+thigh)


def solve_foot(target,seed,leg):
    q=np.array(seed,dtype=float)
    for _ in range(70):
        position=foot(q,leg);error=np.asarray(target)-position
        if np.linalg.norm(error)<1e-5:return q
        jac=np.column_stack([(foot(q+np.eye(3)[i]*1e-5,leg)-position)/1e-5 for i in range(3)])
        delta=jac.T@np.linalg.solve(jac@jac.T+np.eye(3)*1e-5,error)
        q+=np.clip(delta,-.10,.10)
    if np.linalg.norm(np.asarray(target)-foot(q,leg))>.002:raise ValueError('Unreachable observation posture')
    return q


def posture_targets(names,positions,*,height_delta=0.,pitch_delta=0.):
    values=dict(zip(names,map(float,positions)));result=values.copy()
    if abs(height_delta)>.08 or abs(pitch_delta)>.14:raise ValueError('Observation posture outside tested limits')
    rotation=rpy_rotation(0,pitch_delta,0)
    for leg in HIPS:
        keys=[leg+'_'+suffix for suffix in ('hx','hy','kn')]
        seed=np.array([values[k] for k in keys]);goal=rotation.T@(foot(seed,leg)-[0,0,height_delta])
        solved=solve_foot(goal,seed,leg)
        if np.max(np.abs(solved-seed))>.6:raise ValueError('Observation pose changes a joint too far')
        result.update(zip(keys,solved))
    return np.array([result[name] for name in names],dtype=np.float32)


class StationaryBodyObservation:
    def __init__(self,robot,kind):
        if getattr(robot,'_actuators',None) is not None:
            raise RuntimeError('Stationary observation currently supports the native implicit joint drives only')
        self.robot=robot;self.kind=kind;self.elapsed=0.;self.duration=3.2;self.finished=False
        articulation=robot.articulation
        self.names=list(articulation.dof_names)
        self.start=articulation.get_dof_positions().numpy().reshape(-1).copy()
        cfg={'look_up':dict(pitch_delta=-.12),'look_down':dict(pitch_delta=.12),'crouch':dict(height_delta=-.06)}
        self.target=posture_targets(self.names,self.start,**cfg[kind])
        lower,upper=articulation.get_dof_limits()
        if np.any(self.target<lower.numpy().reshape(-1)) or np.any(self.target>upper.numpy().reshape(-1)):
            raise ValueError('Observation joint target exceeds limits')

    @property
    def at_view(self):return 1.2<=self.elapsed<=2.0

    def step(self,dt):
        self.elapsed+=dt
        u=min(self.elapsed/1.2,1.) if self.elapsed<=2. else max(0.,1-(self.elapsed-2.)/1.2)
        u=u*u*(3-2*u)
        target=self.start+(self.target-self.start)*u
        self.robot.articulation.set_dof_position_targets(target.reshape(1,-1))
        if self.elapsed>=self.duration:
            self.finished=True
            self.robot.initialize()  # Reset policy feedback at the current physical state; no teleport.
