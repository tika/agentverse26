import ast
import math
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from front_camera import expected_world_pose,rotation,rpy_rotation,backproject_xy,project_points,crop_from_frame,MOUNT_XYZ
from body_observation import foot,posture_targets


class FixedFrontChecks(unittest.TestCase):
    def test_rigid_mount_follows_full_body_rotation_and_height(self):
        for angle in (0.,.2,-.2,math.pi/2):
            for axis in range(3):
                q=np.zeros(4);q[0]=math.cos(angle/2);q[axis+1]=math.sin(angle/2)
                for height in (.4,.5,.6):
                    position,r=expected_world_pose([2,3,height],q)
                    np.testing.assert_allclose(r.T@(position-[2,3,height]),MOUNT_XYZ,atol=1e-12)
                    np.testing.assert_allclose(r,rotation(q),atol=1e-12)

    def test_project_and_backproject_with_roll_pitch_yaw(self):
        k=np.array([[450,0,640],[0,450,360],[0,0,1.]])
        estimate=[3.,4.,.7];roll=.1;pitch=-.12;body_height=.45
        pixels=np.array([[640.,360.],[200.,200.],[1000.,500.]])
        depths=np.array([2.,3.,4.]);r=rpy_rotation(roll,pitch,estimate[2])
        local=np.column_stack([depths,-(pixels[:,0]-640)*depths/450,-(pixels[:,1]-360)*depths/450])
        world=(local+MOUNT_XYZ)@r.T+[estimate[0],estimate[1],body_height]
        uv,z=project_points(world,k,estimate,roll,pitch,body_height)
        np.testing.assert_allclose(uv,pixels,atol=1e-9)
        np.testing.assert_allclose(z,depths,atol=1e-9)
        np.testing.assert_allclose(backproject_xy(pixels,depths,k,estimate,roll,pitch),world[:,:2],atol=1e-9)

    def test_only_one_camera_constructed_and_no_runtime_aiming(self):
        root=Path(__file__).resolve().parents[2]
        tree=ast.parse((root/'sim/hot_server.py').read_text())
        camera_calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Camera']
        self.assertEqual(len(camera_calls),1)
        for name in ('agent.py','scenario_lib.py','coverage_mission.py'):
            code=(root/'scripts/hot'/name).read_text()
            self.assertNotIn('set_world_pose(',code)
            self.assertNotIn("Camera('/World/",code)
        image=np.arange(8*10*3).reshape(8,10,3)
        np.testing.assert_array_equal(crop_from_frame(image,(2,1,6,5)),image[1:5,2:6])

    def test_observation_ik_changes_legs_without_pose_teleport(self):
        names=[leg+'_'+s for leg in ('fl','fr','hl','hr') for s in ('hx','hy','kn')]
        start=np.array([0.,.8,-1.6]*4)
        for height,pitch in ((-.06,0),(0,.12),(0,-.12)):
            targets=posture_targets(names,start,height_delta=height,pitch_delta=pitch)
            r=rpy_rotation(0,pitch,0)
            for i,leg in enumerate(('fl','fr','hl','hr')):
                actual=r@foot(targets[3*i:3*i+3],leg)+[0,0,height]
                np.testing.assert_allclose(actual,foot(start[3*i:3*i+3],leg),atol=.002)


if __name__=='__main__':unittest.main()
