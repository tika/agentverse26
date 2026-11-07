"""Run once in the Isaac Sim Script Editor on an empty stage."""

import numpy as np
import omni.timeline
import omni.usd
from pxr import Gf, UsdGeom, UsdLux, UsdPhysics

from isaacsim.core.utils.extensions import enable_extension

enable_extension("isaacsim.robot.policy.examples")

from isaacsim.core.api.objects import GroundPlane
from isaacsim.core.rendering_manager import RenderingManager
from isaacsim.core.simulation_manager import SimulationManager
from isaacsim.core.simulation_manager.impl.isaac_events import IsaacEvents
from isaacsim.core.utils.viewports import set_camera_view
from isaacsim.robot.policy.examples import RobotPolicyRunner, get_spot_spec


class LiveSpot:
    def __init__(self):
        self.timeline = omni.timeline.get_timeline_interface()
        stage = omni.usd.get_context().get_stage()
        if self.timeline.is_playing() or stage.GetPrimAtPath("/World/Spot").IsValid():
            raise RuntimeError("Stop the timeline and use an empty stage for initial setup")
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
        SimulationManager.set_physics_sim_device("cpu")
        GroundPlane(prim_path="/World/GroundPlane", size=100)
        light = UsdLux.DistantLight.Define(stage, "/World/Sun")
        light.CreateIntensityAttr(2500)
        light.AddRotateXYZOp().Set(Gf.Vec3f(40, -30, 0))
        for i, x in enumerate((1.8, 3.2, 4.6)):
            drum = UsdGeom.Cylinder.Define(stage, f"/World/Drum_{i}")
            drum.CreateHeightAttr(0.9)
            drum.CreateRadiusAttr(0.28)
            drum.AddTranslateOp().Set(Gf.Vec3d(x, 1.0, 0.45))
            drum.CreateDisplayColorAttr([(0.65, 0.39, 0.12)])
            UsdPhysics.CollisionAPI.Apply(drum.GetPrim())

        self.spot = RobotPolicyRunner(get_spot_spec(), prim_path="/World/Spot")
        self.spot.spawn()
        SimulationManager.set_physics_dt(self.spot.physics_dt)
        RenderingManager.set_dt(1 / 30)
        set_camera_view(eye=[2.1, -5.8, 2.3], target=[2.1, 0, 0.65])
        self.walk = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        self.stand = np.zeros(3, dtype=np.float32)
        self.elapsed = None
        self.stop_subscription = self.timeline.get_timeline_event_stream().create_subscription_to_pop_by_type(
            int(omni.timeline.TimelineEventType.STOP), self.on_stop
        )
        self.callback = SimulationManager.register_callback(self.on_step, IsaacEvents.POST_PHYSICS_STEP)

    def on_stop(self, _event):
        self.elapsed = None

    def on_step(self, dt, _context):
        if self.elapsed is None:
            self.spot.restart_from_default_state(self.stand)
            self.elapsed = 0.0
            return
        command = self.walk if 0.35 <= self.elapsed < 4.5 else self.stand
        self.spot.step(dt, command)
        self.elapsed += dt

    def close(self):
        SimulationManager.deregister_callback(self.callback)
        self.stop_subscription = None
        self.spot.close()


# Retain the controller in the Script Editor's persistent globals.
live_spot = LiveSpot()
print("Spot ready. Click Play to walk. Click Stop, edit the scene, then Play to rerun.")
