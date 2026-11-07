"""Record a dry control and a camera-triggered spill detour in the storage hall."""

import os
from pathlib import Path
import json
import math
import traceback

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "extra_args": [
    "--enable", "isaacsim.robot.policy.examples",
    "--enable", "isaacsim.sensors.camera",
]})


def run():
    import numpy as np
    import omni.usd
    from PIL import Image, ImageDraw, ImageFont
    from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics, UsdShade
    from isaacsim.core.api import World
    from isaacsim.core.simulation_manager import SimulationManager
    from isaacsim.robot.policy.examples import RobotPolicyRunner, get_spot_spec
    from isaacsim.sensors.camera import Camera

    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    hall = UsdGeom.Xform.Define(stage, "/World/Hall")
    hall.GetPrim().GetReferences().AddReference("/scene/hall.usda", "/World/Hall")
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    SimulationManager.set_physics_sim_device("cpu")
    spot = RobotPolicyRunner(get_spot_spec(default_spawn_position=(8.6, 6.0, 0.5)),
                             prim_path="/World/Spot")
    spot.spawn()

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
        for row, y in enumerate((4.6, 7.4, 11.3)):
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
        root = Path(os.environ.get("OUTPUT_DIR", "out")) / "spot-spill"
        root.mkdir(parents=True, exist_ok=True)
        font = ImageFont.load_default(size=17)
        direct = [(14.2, 6.0)]
        alternate = [(10.0, 6.0), (10.0, 10.0), (14.2, 10.0)]

        def pose():
            p, q = spot.articulation.get_world_poses()
            p, q = p.numpy().reshape(3), q.numpy().reshape(4)
            w, x, y, z = q
            yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
            return p, yaw

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

        def annotate(side_rgb, rgb, mask, robot, estimate, message, t, nearest, mode):
            canvas = Image.new("RGB", (960, 344), "#111822")
            canvas.paste(Image.fromarray(side_rgb), (0, 28))
            marked = rgb.copy()
            marked[mask] = (0.45 * marked[mask] + 0.55 * np.array([255, 88, 220])).astype(np.uint8)
            canvas.paste(Image.fromarray(marked), (480, 28))
            draw = ImageDraw.Draw(canvas)
            draw.text((10, 4), f"HALL  |  {mode.upper()}  |  {t:04.1f}s", font=font, fill="white")
            draw.text((490, 4), "ONBOARD RGB  |  predicted tracer mask", font=font, fill="white")
            draw.text((10, 307), message, font=font, fill="white")
            depth_text = f"{nearest:.1f} m" if nearest is not None else "unavailable"
            draw.text((10, 325), f"Central depth: {depth_text}  |  planner: rules baseline", font=font, fill="#b9c8d6")
            def map_point(point):
                return (17 + (point[0] - 8) * 20, 42 + (10.5 - point[1]) * 15)
            draw.rectangle((9, 35, 151, 121), fill="#111822")
            draw.line([map_point(p) for p in [(8.6, 6), *direct]], fill="#999999", width=2)
            if estimate is not None:
                draw.line([map_point(p) for p in [(8.6, 6), *alternate]], fill="#5fe2af", width=2)
                x, y = map_point(estimate)
                draw.ellipse((x-5, y-5, x+5, y+5), fill="#ff57d9")
            x, y = map_point(robot)
            draw.ellipse((x-3, y-3, x+3, y+3), fill="white")
            return canvas

        camera_basis(*pose())
        for _ in range(30):
            world.render()
            if pixels(side) is not None and pixels(front) is not None:
                break
        else:
            raise RuntimeError("Camera warm-up failed")

        for mode in ("dry", "spill"):
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
            with (output / "events.jsonl").open("w") as log:
                for index in range(145):
                    t = index * frame_seconds
                    if mode == "spill" and index == 10:
                        patch.MakeVisible()
                        log.write(json.dumps({"event": "scene_spill_appeared", "time_s": t}) + "\n")
                    position, yaw = pose()
                    basis = camera_basis(position, yaw)
                    world.render()
                    world.render()
                    rgb, side_rgb = pixels(front), pixels(side)
                    if rgb is None or side_rgb is None:
                        raise RuntimeError("Camera dropped out")
                    mask, hit = detect(rgb, basis)
                    depth = front.get_depth()
                    nearest = None
                    if depth is not None and depth.size:
                        core = depth[95:180, 190:290]
                        valid = core[np.isfinite(core) & (core > 0)]
                        if valid.size:
                            nearest = float(np.percentile(valid, 10))
                    hold = False
                    if estimate is None and hit is not None and abs(hit[1] - 6.0) < 0.8:
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
                        reached = True
                        message = "Inspection viewpoint reached"
                    command = zero
                    if path and not hold:
                        delta = np.array(path[0]) - position[:2]
                        velocity = delta * min(1.4, 0.78 / max(np.linalg.norm(delta), 0.01))
                        c, s = math.cos(yaw), math.sin(yaw)
                        command = np.array([c * velocity[0] + s * velocity[1],
                                            -s * velocity[0] + c * velocity[1], 0], dtype=np.float32)
                    annotate(side_rgb, rgb, mask, position[:2], estimate, message, t, nearest, mode).save(
                        output / f"{index:05d}.jpg", quality=80)
                    if mode == "spill" and index >= 10:
                        min_distance = min(min_distance, float(np.linalg.norm(position[:2] - spill_center)))
                    for _ in range(stride):
                        spot.step(dt, command)
                        world.step(render=False)
                    if reached and index > 15:
                        break
            score = {"mode": mode, "detection_time_s": detection_time, "reached": reached,
                     "minimum_base_to_spill_center_m": min_distance if math.isfinite(min_distance) else None}
            (output / "score.json").write_text(json.dumps(score, indent=2))
            print(f"[spot-spill] {score}", flush=True)
    finally:
        spot.close()


try:
    run()
except Exception:
    traceback.print_exc()
    app.close(wait_for_replicator=False, exit_code=1)
    raise
else:
    app.close(wait_for_replicator=False)
