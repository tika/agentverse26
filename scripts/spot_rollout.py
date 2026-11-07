"""Collect a short, scripted Spot sensor rollout in headless Isaac Sim 6.2."""

import argparse
import json
import math
import os
from pathlib import Path
import traceback
import uuid


def run(args):
    from isaacsim import SimulationApp

    app = SimulationApp({"headless": True, "extra_args": [
        "--enable", "isaacsim.robot.policy.examples",
        "--enable", "isaacsim.sensors.camera",
    ]})
    try:
        collect(args)
    except Exception:
        traceback.print_exc()
        app.close(wait_for_replicator=False, exit_code=1)
        raise
    else:
        app.close(wait_for_replicator=False)


def collect(args):
    import numpy as np
    import omni.usd
    from PIL import Image
    from pxr import Gf, UsdGeom, UsdLux, UsdPhysics
    from isaacsim.core.api import World
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot.policy.examples import RobotPolicyRunner, get_spot_spec
    from isaacsim.sensors.camera import Camera

    rng = np.random.default_rng(args.seed)
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    SimulationManager.set_physics_sim_device("cpu")
    spot = RobotPolicyRunner(get_spot_spec(), prim_path="/World/Spot")
    spot.spawn()
    try:
        world = World(physics_dt=spot.physics_dt, rendering_dt=spot.physics_dt)
        world.scene.add_default_ground_plane()
        light = UsdLux.DistantLight.Define(stage, "/World/Sun")
        light.CreateIntensityAttr(2000)
        UsdGeom.Xformable(light).AddRotateXYZOp().Set(Gf.Vec3f(35, -30, 0))

        drums = []
        for index, x in enumerate((2.5, 4.0, 5.5)):
            y = float(rng.uniform(0.65, 0.9)) * (-1 if index == 1 else 1)
            drum = UsdGeom.Cylinder.Define(stage, f"/World/Drum_{index}")
            drum.CreateHeightAttr(0.9)
            drum.CreateRadiusAttr(0.28)
            drum.AddTranslateOp().Set(Gf.Vec3d(x, y, 0.45))
            drum.CreateDisplayColorAttr([(0.8, 0.48, 0.08) if index != 1 else (0.32, 0.12, 0.05)])
            UsdPhysics.CollisionAPI.Apply(drum.GetPrim())
            drums.append({
                "id": f"drum_{index}", "position_m": [x, y, 0.45],
                "condition": "rusted" if index == 1 else "ok",
                "radiation_strength_sim": float(rng.uniform(0.7, 2.5)),
                "thermal_strength_sim": float(rng.uniform(0.5, 2.0)),
            })

        camera = Camera("/World/SpotFrontCamera", resolution=(320, 240))
        camera.set_clipping_range(0.05, 30.0)
        world.reset()
        camera.initialize()
        camera.add_distance_to_image_plane_to_frame()
        stand = np.zeros(3, dtype=np.float32)
        walk = np.array([args.speed, 0, 0], dtype=np.float32)
        world.step(render=False)
        spot.restart_from_default_state(stand)
        dt = spot.physics_dt
        stride = max(1, round(1 / (args.hz * dt)))

        def sample_camera():
            position, orientation = spot.articulation.get_world_poses()
            position = position.numpy().reshape(3)
            orientation = orientation.numpy().reshape(4)
            rotation = Gf.Rotation(Gf.Quatd(float(orientation[0]), Gf.Vec3d(*map(float, orientation[1:]))))
            mount = rotation.TransformDir(Gf.Vec3d(0.48, 0, 0.17))
            sensor_position = position + np.asarray(tuple(mount))
            camera.set_world_pose(position=sensor_position, orientation=orientation)
            return position, orientation, sensor_position

        # Prime the render product before the first capture at a moving simulation time.
        start, _, _ = sample_camera()
        for _ in range(20):
            world.render()
            rgb, depth = camera.get_rgba(), camera.get_depth()
            if rgb is not None and rgb.size and depth is not None and depth.size:
                break
        else:
            raise RuntimeError("Front camera did not return RGB and depth during warmup")

        def capture_camera(elapsed_s):
            # Keep physics frozen until both annotators have rendered this state.
            for _ in range(20):
                world.render()
                frame = camera.get_current_frame()
                stamp = frame.get("rendering_frame")
                if not isinstance(stamp, dict):
                    continue
                render_time = stamp["referenceTimeNumerator"] / stamp["referenceTimeDenominator"]
                rgb, depth = camera.get_rgba(), camera.get_depth()
                if render_time >= elapsed_s - dt / 2 and rgb is not None and depth is not None:
                    if rgb.size and depth.size and np.isfinite(depth).any():
                        return rgb, depth, render_time
            return None

        run_id = f"seed-{args.seed}-{uuid.uuid4().hex[:8]}"
        output = Path(os.environ.get("OUTPUT_DIR", "out")) / "spot" / run_id
        (output / "rgb").mkdir(parents=True)
        (output / "depth").mkdir()
        (output / "scene_truth.json").write_text(json.dumps({
            "run_id": run_id, "seed": args.seed, "drums": drums,
            "rgb_size_px": [320, 240], "intrinsics": camera.get_intrinsics_matrix().tolist(),
            "mount_offset_m": [0.48, 0, 0.17], "physics_dt_s": dt,
        }, indent=2))

        count = 0
        dropped = 0
        steps = math.ceil(args.seconds / dt)
        with (output / "samples.jsonl").open("w") as manifest:
            for step in range(1, steps + 1):
                command = stand if step * dt <= 0.5 else walk
                spot.step(dt, command)
                world.step(render=False)
                if step != steps and step % stride:
                    continue
                position, orientation, sensor_position = sample_camera()
                capture = capture_camera(step * dt)
                if capture is None:
                    dropped += 1
                    continue
                rgb, depth, render_time = capture

                # Synthetic point-source proxies. Units intentionally stay simulation-specific.
                distances_sq = [max(0.09, float(np.sum((sensor_position - drum["position_m"]) ** 2)))
                                for drum in drums]
                radiation = 0.1 + sum(d["radiation_strength_sim"] / r for d, r in zip(drums, distances_sq))
                thermal = 0.3 + max(d["thermal_strength_sim"] / r for d, r in zip(drums, distances_sq))
                rgb_path = f"rgb/{count:05d}.png"
                depth_path = f"depth/{count:05d}.npy"
                Image.fromarray(rgb[:, :, :3].astype(np.uint8)).save(output / rgb_path)
                np.save(output / depth_path, depth.astype(np.float32))
                record = {
                    "run_id": run_id, "seed": args.seed, "sample": count,
                    "elapsed_sim_s": step * dt, "physics_step": step,
                    "camera_reference_time_s": render_time,
                    "rgb_path": rgb_path, "depth_path": depth_path,
                    "base_position_m": position.tolist(), "base_quaternion_wxyz": orientation.tolist(),
                    "sensor_position_m": sensor_position.tolist(),
                    "readings": {
                        "radiation": {"value": max(0.0, radiation + rng.normal(0, 0.02)),
                                      "unit": "sim_rad", "age_s": 0.0},
                        "thermal": {"value": max(0.0, thermal + rng.normal(0, 0.02)),
                                    "unit": "sim_heat", "age_s": 0.0},
                    },
                    "command_vx_vy_yaw_rate": command.tolist(),
                }
                manifest.write(json.dumps(record, allow_nan=False) + "\n")
                count += 1

        distance = float(np.linalg.norm(position[:2] - start[:2]))
        print(f"[spot] {count} samples, {dropped} dropped, {distance:.2f} m net horizontal displacement: {output}", flush=True)
        if not count:
            raise RuntimeError("No synchronized camera samples were captured")
        if distance < 0.25 or position[2] < 0.2:
            raise RuntimeError("Spot did not complete an upright walking rollout")
    finally:
        spot.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--speed", type=float, default=1.0, help="Forward command in m/s")
    parser.add_argument("--hz", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if not (1 <= args.seconds <= 12 and 0.3 <= args.speed <= 1.5 and 1 <= args.hz <= 10):
        parser.error("Use 1–12 seconds, 0.3–1.5 m/s and 1–10 Hz for this short rollout")
    run(args)
