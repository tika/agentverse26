"""Headless Isaac Sim smoke test: drop a cube, step physics, render one camera frame."""

import os
import time

from isaacsim import SimulationApp

t0 = time.time()
simulation_app = SimulationApp({"headless": True, "width": 640, "height": 480})
print(f"[smoke] SimulationApp started in {time.time() - t0:.1f}s")

import numpy as np  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.api.objects import DynamicCuboid  # noqa: E402
import isaacsim.core.utils.numpy.rotations as rot_utils  # noqa: E402
from isaacsim.sensors.camera import Camera  # noqa: E402
from PIL import Image  # noqa: E402

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
cube = world.scene.add(
    DynamicCuboid(
        prim_path="/World/cube",
        name="cube",
        position=np.array([0.0, 0.0, 1.0]),
        scale=np.array([0.3, 0.3, 0.3]),
        color=np.array([0.1, 0.4, 0.9]),
    )
)
camera = Camera(
    prim_path="/World/camera",
    position=np.array([0.0, 0.0, 4.0]),
    resolution=(640, 480),
    orientation=rot_utils.euler_angles_to_quats(np.array([0, 90, 0]), degrees=True),
)
world.reset()
camera.initialize()

start_z = cube.get_world_pose()[0][2]
for _ in range(120):
    world.step(render=True)
end_z = cube.get_world_pose()[0][2]
print(f"[smoke] cube z: {start_z:.3f} -> {end_z:.3f}")

# The camera's render product can lag a few frames behind physics; render until a frame arrives.
rgba = camera.get_rgba()
deadline = time.time() + 60
while not (rgba is not None and rgba.size) and time.time() < deadline:
    simulation_app.update()
    rgba = camera.get_rgba()
print(f"[smoke] waited {time.time() - deadline + 60:.1f}s for camera frame")
out_dir = os.environ.get("OUTPUT_DIR", ".")
if rgba is not None and rgba.size:
    Image.fromarray(rgba[:, :, :3].astype(np.uint8)).save(os.path.join(out_dir, "smoke.png"))
    print(f"[smoke] saved frame {rgba.shape}, mean pixel {rgba[:, :, :3].mean():.1f}")

assert rgba is not None and rgba.size, "camera returned no frame; rendering is broken"

assert end_z < start_z - 0.3, "cube did not fall; physics is not stepping"
print("[smoke] OK")
simulation_app.close()
