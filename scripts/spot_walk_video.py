"""Render a third-person clip of the bundled Spot walking policy."""

import argparse
import os
import time
import uuid
from pathlib import Path
import traceback

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "extra_args": [
    "--enable", "isaacsim.robot.policy.examples",
    "--enable", "isaacsim.sensors.camera",
]})


def record():
    import numpy as np
    import omni.usd
    from PIL import Image
    from pxr import Gf, UsdGeom, UsdLux, UsdPhysics
    from isaacsim.core.api import World
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot.policy.examples import RobotPolicyRunner, get_spot_spec
    from isaacsim.sensors.camera import Camera

    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    SimulationManager.set_physics_sim_device("cpu")
    spot = RobotPolicyRunner(get_spot_spec(), prim_path="/World/Spot")
    spot.spawn()
    try:
        dt = spot.physics_dt
        world = World(physics_dt=dt, rendering_dt=dt)
        world.scene.add_default_ground_plane()
        light = UsdLux.DistantLight.Define(stage, "/World/Sun")
        light.CreateIntensityAttr(2500)
        light.AddRotateXYZOp().Set(Gf.Vec3f(40, -30, 0))
        for i, x in enumerate((1.8, 3.2, 4.6)):
            drum = UsdGeom.Cylinder.Define(stage, f"/World/Drum_{i}")
            drum.CreateHeightAttr(0.9)
            drum.CreateRadiusAttr(0.28)
            drum.AddTranslateOp().Set(Gf.Vec3d(x, 1.0, 0.45))
            drum.CreateDisplayColorAttr([(0.65, 0.39, 0.12)])
        eye = Gf.Vec3d(2.0, -6.6, 2.6)
        target = Gf.Vec3d(2.0, 0, 0.6)
        look = Gf.Matrix4d().SetLookAt(eye, target, Gf.Vec3d(0, 0, 1)).GetInverse()
        quat = look.ExtractRotationQuat()
        camera = Camera("/World/SideCamera", resolution=(640, 360))
        camera.set_world_pose(
            position=np.array(eye), orientation=np.array([quat.GetReal(), *quat.GetImaginary()]),
            camera_axes="usd",
        )
        camera.prim.GetAttribute("focalLength").Set(15.0)
        world.reset()
        camera.initialize()
        world.step(render=False)
        stand = np.zeros(3, dtype=np.float32)
        walk = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        spot.restart_from_default_state(stand)
        for _ in range(24):
            world.render()
            rgb = camera.get_rgba()
            if rgb is not None and rgb.size:
                break
        else:
            raise RuntimeError("Side camera did not initialize")

        def capture(output):
            output.mkdir(parents=True, exist_ok=True)
            world.step(render=False)
            spot.restart_from_default_state(stand)
            stride = round(1 / (24 * dt))
            for frame in range(120):
                command = walk if 8 <= frame < 108 else stand
                for _ in range(stride):
                    spot.step(dt, command)
                    world.step(render=False)
                world.render()
                world.render()
                rgb = camera.get_rgba()
                if rgb is None or not rgb.size:
                    raise RuntimeError(f"Side camera returned no image for frame {frame}")
                Image.fromarray(rgb[:, :, :3].astype(np.uint8)).save(output / f"{frame:05d}.png")
            position, _ = spot.articulation.get_world_poses()
            displacement = float(np.linalg.norm(position.numpy().reshape(3)[:2]))
            if displacement < 2.0:
                raise RuntimeError(f"Spot traveled only {displacement:.2f} m")
            print(f"[spot-video] 120 frames; Spot traveled {displacement:.2f} m: {output}", flush=True)

        output_root = Path(os.environ.get("OUTPUT_DIR", "out"))
        if not args.warm:
            capture(output_root / "spot-walk-frames")
            return

        request = Path("/tmp/spot-record")
        while True:
            output = output_root / f"take-{uuid.uuid4().hex[:8]}"
            capture(output)
            (output / "complete").touch()
            print("[spot-video] Warm and waiting. Touch /tmp/spot-record for another take.", flush=True)
            while not request.exists():
                time.sleep(0.5)
            request.unlink(missing_ok=True)
    finally:
        spot.close()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--warm", action="store_true")
args = parser.parse_args()

try:
    record()
except Exception:
    traceback.print_exc()
    app.close(wait_for_replicator=False, exit_code=1)
    raise
else:
    app.close(wait_for_replicator=False)
