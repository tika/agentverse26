"""Record a dry control and a camera-triggered spill detour in the storage hall."""

import argparse
import os
import sys
from pathlib import Path
import json
import math
import traceback
from time import perf_counter

from isaacsim import SimulationApp

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--fast", action="store_true", help="Use RTX Minimal and skip the default viewport")
parser.add_argument("--radiation", action="store_true", help="Walk the full hall with a gamma hotspot")
args = parser.parse_args()
config = {"headless": True, "fast_shutdown": True, "extra_args": [
    "--enable", "isaacsim.robot.policy.examples",
    "--enable", "isaacsim.sensors.camera",
]}
if args.fast:
    config.update(renderer="MinimalRendering", minimal_shading_mode=1, disable_viewport_updates=True)
started = perf_counter()
app = SimulationApp(config)
timing = {"renderer_profile": "fast" if args.fast else "default",
          "kit_start_s": perf_counter() - started}



def run():
    import numpy as np
    if args.radiation:
        import torch

        value = (torch.ones(1, device="cuda") + 1).item()
        assert value == 2
        timing["cuda"] = {
            "torch": torch.__version__, "runtime": torch.version.cuda,
            "device": torch.cuda.get_device_name(),
        }
    import omni.usd
    from PIL import Image, ImageDraw, ImageFont
    from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics, UsdShade
    from isaacsim.core.api import World
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot.policy.examples import RobotPolicyRunner, get_spot_spec
    from isaacsim.sensors.camera import Camera

    setup_started = perf_counter()
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    start_x = 3.0 if args.radiation else 8.6
    if args.radiation:
        from pxr import Usd
        import carb

        settings = carb.settings.get_settings()
        settings.set_bool("/rtx/post/histogram/enabled", False)
        settings.set_float("/rtx/post/tonemap/filmIso", 400.0)
        settings.set_float("/rtx/post/tonemap/fNumber", 2.8)
        settings.set_float("/rtx/post/tonemap/cameraShutter", 60.0)

        sys.path.insert(0, "/scene")
        from sensors import SensorWorld, author_gamma_source, load_config

        scene = UsdGeom.Xform.Define(stage, "/World")
        scene.GetPrim().GetReferences().AddReference("/scene/scene_environment.usda", "/World")
        stage.GetPrimAtPath("/World/Spot").SetActive(False)
        inventory = json.loads(Path("/scene/drums.json").read_text())
        scenario = load_config()
        for drum in inventory:
            if drum["id"] == "D23":
                drum["source_strength"] = 280.0  # Scenario-only source strength at 1 m.
            author_gamma_source(stage.GetPrimAtPath(drum["prim_path"]), drum)
        sensor = SensorWorld(inventory, scenario)
    else:
        hall = UsdGeom.Xform.Define(stage, "/World/Hall")
        hall.GetPrim().GetReferences().AddReference("/scene/hall.usda", "/World/Hall")
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    SimulationManager.set_physics_sim_device("cpu")
    spot = RobotPolicyRunner(get_spot_spec(default_spawn_position=(start_x, 6.0, 0.5)),
                             prim_path="/World/WalkingSpot" if args.radiation else "/World/Spot")
    spot.spawn()
    mount_height = 0.15
    if args.radiation:
        body = next(
            prim for prim in Usd.PrimRange(stage.GetPrimAtPath("/World/WalkingSpot"))
            if prim.GetName().lower() in {"body", "base", "base_link"}
            and prim.HasAPI(UsdPhysics.RigidBodyAPI)
        )
        mount = UsdGeom.Xform.Define(stage, body.GetPath().AppendChild("GammaDetector"))
        mount.AddTranslateOp().Set(Gf.Vec3d(0, 0, mount_height))

    def aim(camera, eye, target):
        matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1))
        quat = matrix.GetInverse().ExtractRotationQuat()
        camera.set_world_pose(position=np.array(eye),
                              orientation=np.array([quat.GetReal(), *quat.GetImaginary()]),
                              camera_axes="usd")

    try:
        dt = spot.physics_dt
        world = World(physics_dt=dt, rendering_dt=dt)
        light = UsdLux.DomeLight.Define(stage, "/World/InspectionFill")
        light.CreateIntensityAttr(250)
        for row, y in enumerate(() if args.radiation else (4.6, 7.4, 11.3)):
            for column, x in enumerate((11.4, 12.5, 13.6, 14.7)):
                drum = UsdGeom.Cylinder.Define(stage, f"/World/Drum_{row}_{column}")
                drum.CreateHeightAttr(0.88)
                drum.CreateRadiusAttr(0.29)
                drum.CreateDisplayColorAttr([(0.64, 0.35, 0.08)])
                drum.AddTranslateOp().Set(Gf.Vec3d(x, y, 0.44))
                UsdPhysics.CollisionAPI.Apply(drum.GetPrim())

        # A fluorescent inspection surrogate. The detector is deliberately specific to this tracer.
        spill_center = np.array([11.8, 6.0])
        spill_radii = np.array([0.64, 0.54])
        patch = UsdGeom.Mesh.Define(stage, "/World/Spill")
        patch.CreatePointsAttr([
            (float(spill_center[0] + spill_radii[0] * math.cos(t)),
             float(spill_center[1] + spill_radii[1] * math.sin(t)), 0.009)
            for t in np.linspace(0, 2 * math.pi, 36, endpoint=False)
        ])
        patch.CreateFaceVertexCountsAttr([36])
        patch.CreateFaceVertexIndicesAttr(list(range(36)))
        patch.CreateSubdivisionSchemeAttr("none")
        patch.CreateDoubleSidedAttr(True)
        material = UsdShade.Material.Define(stage, "/World/Tracer")
        shader = UsdShade.Shader.Define(stage, "/World/Tracer/Surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.8, 0.01, 0.63))
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.6, 0.0, 0.43))
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI.Apply(patch.GetPrim()).Bind(material)
        patch.MakeInvisible()

        side = Camera("/World/Side", resolution=(480, 270))
        front = Camera("/World/RobotCamera", resolution=(480, 270))
        for camera in (side, front):
            camera.prim.GetAttribute("focalLength").Set(15.0)
        if args.radiation:
            aim(side, (6.8, 1.3, 5.45), (7.0, 6.0, 0.25))
        else:
            aim(side, (10.7, 2.2, 5.5), (11.7, 7.7, 0.1))
        world.reset()
        for camera in (side, front):
            camera.initialize()
        front.add_distance_to_image_plane_to_frame()
        zero = np.zeros(3, dtype=np.float32)
        world.step(render=False)
        spot.restart_from_default_state(zero)
        stride = round(1 / (8 * dt))
        frame_seconds = stride * dt
        root = Path(os.environ.get("OUTPUT_DIR", "out")) / ("spot-radiation" if args.radiation else "spot-spill")
        root.mkdir(parents=True, exist_ok=True)
        font = ImageFont.load_default(size=17)
        direct = [(12.5 if args.radiation else 14.2, 6.0)]
        alternate = [(10.0, 6.0), (10.0, 10.0), (14.2, 10.0)]

        def pose():
            p, q = spot.articulation.get_world_poses()
            p, q = p.numpy().reshape(3), q.numpy().reshape(4)
            w, x, y, z = q
            yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
            sensor_position = p + mount_height * np.array([
                2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y),
            ])
            return p, yaw, sensor_position

        def camera_basis(position, yaw):
            heading = np.array([math.cos(yaw), math.sin(yaw), 0.0])
            eye = position + 0.47 * heading + np.array([0, 0, 0.22])
            forward = heading + np.array([0, 0, -0.29])
            forward /= np.linalg.norm(forward)
            right = np.cross(forward, [0, 0, 1])
            right /= np.linalg.norm(right)
            up = np.cross(right, forward)
            aim(front, tuple(eye), tuple(eye + forward))
            return eye, forward, right, up

        def detect(rgb, basis):
            r, g, b = rgb.astype(np.float32).transpose(2, 0, 1)
            mask = (r > 80) & (b > 70) & (r > 1.6 * g) & (b > 1.5 * g)
            ys, xs = np.nonzero(mask)
            if len(xs) < 24:
                return mask, None
            eye, forward, right, up = basis
            intrinsics = front.get_intrinsics_matrix()
            u, v = np.median(xs), np.median(ys)
            ray = (forward + right * ((u - intrinsics[0, 2]) / intrinsics[0, 0])
                   - up * ((v - intrinsics[1, 2]) / intrinsics[1, 1]))
            if ray[2] >= -0.04:
                return mask, None
            hit = eye + ray * (-eye[2] / ray[2])
            return mask, hit[:2]

        def pixels(camera):
            rgba = camera.get_rgba()
            return None if rgba is None or not rgba.size else rgba[:, :, :3].astype(np.uint8)

        def annotate(side_rgb, rgb, mask, robot, estimate, message, t, nearest, mode, radiation, trail):
            canvas = Image.new("RGB", (960, 356 if args.radiation else 344), "#111822")
            if args.radiation:
                # Lift shadow detail in the review only. Depth and sensor values stay raw.
                display = (255 * (np.arange(256) / 255) ** 0.65).astype(np.uint8)
                side_rgb, rgb = display[side_rgb], display[rgb]
            canvas.paste(Image.fromarray(side_rgb), (0, 28))
            marked = rgb.copy()
            marked[mask] = (0.45 * marked[mask] + 0.55 * np.array([255, 88, 220])).astype(np.uint8)
            canvas.paste(Image.fromarray(marked), (480, 28))
            draw = ImageDraw.Draw(canvas)
            draw.text((10, 4), f"HALL  |  {mode.upper()}  |  {t:04.1f}s", font=font, fill="white")
            draw.text((490, 4), ("ONBOARD RGB  |  gamma sensor history" if args.radiation else "ONBOARD RGB  |  predicted tracer mask"), font=font, fill="white")
            draw.text((10, 307), message, font=font, fill="white")
            depth_text = f"{nearest:.1f} m" if nearest is not None else "unavailable"
            draw.text((10, 325), f"Central depth: {depth_text}  |  planner: rules baseline", font=font, fill="#b9c8d6")
            if radiation is not None:
                color = {"green": "#5fe2af", "amber": "#ffc55e", "red": "#ff6767"}
                draw.text((10, 330), f"SIM GAMMA  {radiation['dose_rate_uSv_h']:5.1f} uSv/h  |  "
                          f"accumulated proxy {1000 * radiation['mission_dose_mSv']:.4f} uSv  |  "
                          f"centre depth {depth_text}  |  {radiation['status'].upper()}", font=font,
                          fill=color[radiation["status"]])
                draw.rectangle((640, 34, 947, 94), fill="#111822")
                stop_rate = scenario["thresholds"]["hot_spot"]
                draw.line([(645, 54), (943, 54)], fill="#ff6767")
                draw.text((648, 36), f"Dose history  |  demo retreat above {stop_rate:g} uSv/h",
                          font=ImageFont.load_default(size=12), fill="white")
                points = [(646 + i * 5, 89 - min(rate / stop_rate, 1.4) * 35)
                          for i, rate in enumerate(trail[-59:])]
                if len(points) > 1:
                    draw.line(points, fill=color[radiation["status"]], width=2)
            def map_point(point):
                return (17 + (point[0] - (3 if args.radiation else 8)) * (13 if args.radiation else 20), 42 + (10.5 - point[1]) * 15)
            draw.rectangle((9, 35, 151, 121), fill="#111822")
            draw.line([map_point(p) for p in [(start_x, 6), *direct]], fill="#999999", width=2)
            if estimate is not None:
                draw.line([map_point(p) for p in [(start_x, 6), *alternate]], fill="#5fe2af", width=2)
                x, y = map_point(estimate)
                draw.ellipse((x-5, y-5, x+5, y+5), fill="#ff57d9")
            x, y = map_point(robot)
            draw.ellipse((x-3, y-3, x+3, y+3), fill="white")
            return canvas

        timing["scene_setup_s"] = perf_counter() - setup_started
        warm_started = perf_counter()
        camera_basis(*pose()[:2])
        for _ in range(30):
            world.render()
            if pixels(side) is not None and pixels(front) is not None:
                break
        else:
            raise RuntimeError("Camera warm-up failed")

        timing["camera_warmup_s"] = perf_counter() - warm_started
        print(f"[spot-timing] {timing}", flush=True)
        scores = {}
        for mode in (("radiation",) if args.radiation else ("dry", "spill")):
            episode_started = perf_counter()
            totals = dict(render_s=0.0, perception_s=0.0, overlay_and_write_s=0.0, physics_s=0.0)
            patch.MakeInvisible()
            spot.restart_from_default_state(zero)
            output = root / mode
            output.mkdir(exist_ok=True)
            path = list(direct)
            estimate = None
            reached = False
            detection_time = None
            min_distance = math.inf
            message = "Patrolling direct aisle"
            trail = []
            radiation = None
            retreating = False
            retreated = False
            last_clear = None
            with (output / "events.jsonl").open("w") as log:
                for index in range(175 if args.radiation else 145):
                    t = index * frame_seconds
                    if mode == "spill" and index == 10:
                        patch.MakeVisible()
                        log.write(json.dumps({"event": "scene_spill_appeared", "time_s": t}) + "\n")
                    position, yaw, sensor_position = pose()
                    phase = perf_counter()
                    basis = camera_basis(position, yaw)
                    world.render()
                    world.render()
                    rgb, side_rgb = pixels(front), pixels(side)
                    if rgb is None or side_rgb is None:
                        raise RuntimeError("Camera dropped out")
                    totals["render_s"] += perf_counter() - phase
                    phase = perf_counter()
                    mask, hit = (np.zeros(rgb.shape[:2], dtype=bool), None) if args.radiation else detect(rgb, basis)
                    depth = front.get_depth()
                    nearest = None
                    if depth is not None and depth.size:
                        core = depth[95:180, 190:290]
                        valid = core[np.isfinite(core) & (core > 0)]
                        if valid.size:
                            nearest = float(np.percentile(valid, 10))
                            if args.radiation and index in (0, 40, 80):
                                np.save(output / f"depth-{index:05d}.npy", depth)
                    if args.radiation:
                        radiation = sensor.sample(sensor_position, t)
                        radiation["gamma"]["yaw_rad"] = (yaw + math.pi) % (2 * math.pi) - math.pi
                        rate = radiation["dose_rate_uSv_h"]
                        limits = scenario["thresholds"]
                        radiation["status"] = ("red" if rate > limits["hot_spot"]
                                               else "amber" if rate > limits["controlled_zone"] else "green")
                        trail.append(rate)
                        log.write(json.dumps({"event": "dose_sample", "position_m": sensor_position.tolist(),
                                              "frame": index, "central_depth_m": nearest,
                            "camera": {
                                "timestamp_s": t, "image_size_px": [480, 270],
                                "intrinsics": front.get_intrinsics_matrix().tolist(),
                                "world_eye_m": basis[0].tolist(), "world_forward": basis[1].tolist(),
                                "world_right": basis[2].tolist(), "world_up": basis[3].tolist(),
                            },
                            **radiation}) + "\n")
                        if not retreating:
                            if rate < 0.7 * limits["hot_spot"]:
                                last_clear = tuple(map(float, position[:2]))
                            if radiation["status"] == "red":
                                retreating = True
                                detection_time = t
                                path = [last_clear] if last_clear is not None else []
                                message = "Gamma limit crossed | backing off to last below-threshold position"
                                log.write(json.dumps({"event": "radiation_veto", "time_s": t,
                                                      "dose_rate_uSv_h": rate, "retreat_target": last_clear}) + "\n")
                    hold = False
                    if not args.radiation and estimate is None and hit is not None and abs(hit[1] - 6.0) < 0.8:
                        estimate = hit
                        detection_time = t
                        path = list(alternate)
                        hold = True
                        message = "Spill detected | direct aisle blocked | taking north cross-aisle"
                        log.write(json.dumps({"event": "detour", "time_s": t,
                                              "estimated_xy_m": hit.tolist(), "route": path}) + "\n")
                    if path and np.linalg.norm(position[:2] - path[0]) < 0.26:
                        path.pop(0)
                    if not path:
                        if retreating:
                            retreated = radiation["status"] != "red"
                            message = ("Stopped after retreat | gamma reading below alert threshold" if retreated
                                       else "Holding | no below-threshold retreat point reached")
                        else:
                            reached = True
                            message = "Inspection viewpoint reached"
                    command = zero
                    if path and not hold:
                        delta = np.array(path[0]) - position[:2]
                        velocity = delta * min(1.4, 0.78 / max(np.linalg.norm(delta), 0.01))
                        c, s = math.cos(yaw), math.sin(yaw)
                        command = np.array([c * velocity[0] + s * velocity[1],
                                            -s * velocity[0] + c * velocity[1], 0], dtype=np.float32)
                    totals["perception_s"] += perf_counter() - phase
                    phase = perf_counter()
                    if (mode == "dry" and index == 11 and estimate is None) or hold:
                        Image.fromarray(rgb).save(output / "decision.png")
                        snapshot = {
                            "rgb_path": "decision.png",
                            "readings": {"central_depth": {"value": nearest, "unit": "m", "age_s": 0}},
                            "goals": [
                                {"id": "direct_aisle", "route_clear": not hold},
                                {"id": "north_viewpoint", "route_clear": True},
                            ],
                            "findings": ([{"id": "tracer_1", "label": "possible spill",
                                           "position_m": hit.tolist()}] if hold else []),
                            "target": {
                                "goal_id": "north_viewpoint" if hold else "direct_aisle",
                                "reason": ("A possible spill blocks the direct aisle."
                                           if hold else "The direct aisle is clear."),
                            },
                        }
                        (output / "decision.json").write_text(json.dumps(snapshot, indent=2))
                    annotate(side_rgb, rgb, mask, position[:2], estimate, message, t, nearest, mode, radiation, trail).save(
                        output / f"{index:05d}.jpg", quality=80)
                    if mode == "spill" and index >= 10:
                        min_distance = min(min_distance, float(np.linalg.norm(position[:2] - spill_center)))
                    totals["overlay_and_write_s"] += perf_counter() - phase
                    phase = perf_counter()
                    for _ in range(stride):
                        spot.step(dt, command)
                        world.step(render=False)
                    totals["physics_s"] += perf_counter() - phase
                    if (reached or (retreating and not path)) and index > 15:
                        break
            score = {"mode": mode, "detection_time_s": detection_time, "reached": reached,
                     "minimum_base_to_spill_center_m": min_distance if math.isfinite(min_distance) else None}
            if args.radiation:
                score.update(retreated=retreated, peak_dose_rate_uSv_h=max(trail),
                             final_dose_rate_uSv_h=trail[-1])
            scores[mode] = score
            (output / "score.json").write_text(json.dumps(score, indent=2))
            timing[mode] = {**totals, "frames": index + 1, "simulated_s": (index + 1) * frame_seconds,
                            "episode_wall_s": perf_counter() - episode_started}
            print(f"[spot-spill] {score}", flush=True)
        timing["passed"] = scores["radiation"]["retreated"] if args.radiation else (
            scores["dry"]["reached"] and scores["dry"]["detection_time_s"] is None
            and scores["spill"]["reached"] and scores["spill"]["detection_time_s"] is not None
            and scores["spill"]["minimum_base_to_spill_center_m"] > 1.5
        )
        (root / "timing.json").write_text(json.dumps(timing, indent=2))
        print(f"[spot-timing] {timing}", flush=True)
    finally:
        spot.close()


try:
    run()
except Exception:
    traceback.print_exc()
    app.close(wait_for_replicator=False, skip_cleanup=True, exit_code=1)
    raise
else:
    app.close(wait_for_replicator=False, skip_cleanup=True)
