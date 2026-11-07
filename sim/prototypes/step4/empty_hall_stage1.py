"""Render the empty Stage 1 hall on Modal."""
import modal
from pathlib import Path

# Self-contained image definition (same as render_check.py).
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        "libvulkan1", "libxext6", "libx11-6",
        "libgl1", "libegl1", "libgomp1"
    )
    .pip_install(
        "torch==2.11.0",
        index_url="https://download.pytorch.org/whl/cu128",
    )
    .pip_install(
        "isaacsim[all,extscache]==6.0.1.0",
        extra_index_url="https://pypi.nvidia.com",
    )
    .env({"OMNI_KIT_ACCEPT_EULA": "YES"})
)

app = modal.App("isaac-empty-hall-stage1")

SCENE = r'''
from isaacsim import SimulationApp

sim = SimulationApp({"headless": True, "fast_shutdown": True})

import sys
import numpy as np
import omni.usd
import omni.replicator.core as rep
from PIL import Image
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade

stage = omni.usd.get_context().get_stage()
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
hall = "/World/Hall"
UsdGeom.Xform.Define(stage, hall)
UsdGeom.Scope.Define(stage, hall + "/Lights")

def material(name, color, roughness):
    path = hall + "/Materials/" + name
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + "/Surface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat

def box(name, center, size, mat, yaw=0):
    cube = UsdGeom.Cube.Define(stage, hall + "/" + name)
    cube.CreateSizeAttr(1.0)
    cube.AddTranslateOp().Set(Gf.Vec3d(*center))
    if yaw:
        cube.AddRotateZOp().Set(float(yaw))
    cube.AddScaleOp().Set(Gf.Vec3f(*size))
    UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(mat)

floor = material("Epoxy", (.34, .36, .37), .48)
concrete = material("Concrete", (.52, .50, .47), .83)
coating = material("Coating", (.28, .39, .36), .55)
yellow = material("SafetyYellow", (.84, .54, .035), .5)
dark = material("DarkSteel", (.07, .085, .09), .55)
metal = material("Galvanized", (.42, .46, .48), .45)
joint = material("Joint", (.28, .28, .27), .88)
patch = material("Repair", (.30, .32, .33), .56)

box("Floor", (10, 6, -.15), (20, 12, .3), floor)
box("Ceiling", (10, 6, 6.2), (21, 13, .4), concrete)
for side, y, face in [("South", -.25, .012), ("North", 12.25, 11.988)]:
    box(side + "Wall", (10, y, 3), (21, .5, 6), concrete)
    box(side + "Coating", (10, face, .75), (20, .024, 1.5), coating)
    for i in range(1, 9):
        box(f"{side}JointV{i}", (2.4*i, face, 3.75), (.016, .004, 4.5), joint)
    for i in range(2, 5):
        box(f"{side}JointH{i}", (10, face, 1.2*i), (20, .004, .014), joint)
    inward = .28 if side == "South" else 11.72
    box(side + "CraneRail", (10, inward, 5.2), (20, .24, .25), dark)
    box(side + "CableTray", (10, inward, 3), (20, .19, .09), metal)
    for i, x in enumerate((4.5, 14.5)):
        box(f"{side}Monitor{i}", (x, inward, 2.0), (.28, .20, .34), metal)
        box(f"{side}Beacon{i}", (x, inward, 2.21), (.12, .12, .08), yellow)
    box(side + "Drain", (12, .55 if side == "South" else 11.45, .003),
        (.4, .4, .006), dark)

for end, x, face in [("Front", -.25, .012), ("Back", 20.25, 19.988)]:
    box(end + "Wall", (x, 6, 3), (.5, 12, 6), concrete)
    box(end + "Coating", (face, 6, .75), (.024, 12, 1.5), coating)

box("RollerDoor", (.055, 6, 1.85), (.11, 3, 3.7), metal)
for i in range(1, 19):
    box(f"ShutterSlat{i}", (.115, 6, .2*i), (.014, 2.98, .018), joint)
box("PersonnelDoor", (.06, 2.5, 1.08), (.12, .95, 2.16), dark)
box("CraneBridge", (18.5, 6, 5.02), (.48, 11.55, .35), yellow)
box("CraneHoist", (18.5, 6.6, 4.68), (.65, .58, .35), dark)
box("VentDuct", (10, 6, 5.69), (20, .65, .43), metal)

for i, y in enumerate((1, 3, 5, 7, 9, 11)):
    for j, (start, stop) in enumerate(((2.5, 9), (11, 17.5))):
        box(f"AisleEdge{i}_{j}", ((start+stop)/2, y, .003),
            (stop-start, .10, .006), yellow)
box("ZoneBoundary", (10, 6, .003), (.48, 12, .006), dark)
for i in range(30):
    box(f"BoundaryHatch{i}", (10, .21 + i*.4, .007), (.55, .15, .005), yellow, 35)
box("FloorRepairA", (5.6, 6.6, .001), (1.3, .68, .002), patch)
box("FloorRepairB", (15.2, 4.9, .001), (.84, 1.1, .002), patch)

dome = UsdLux.DomeLight.Define(stage, hall + "/Lights/Fill")
dome.CreateIntensityAttr(120)
for row, y in enumerate((4, 8)):
    for col, x in enumerate((2.5, 7.5, 12.5, 17.5)):
        name = f"HighBay{row}_{col}"
        box(name + "Housing", (x, y, 5.58), (1.35, .50, .14), metal)
        light = UsdLux.RectLight.Define(stage, hall + "/Lights/" + name)
        light.AddTranslateOp().Set(Gf.Vec3d(x, y, 5.499))
        light.CreateWidthAttr(1.26)
        light.CreateHeightAttr(.43)
        light.CreateIntensityAttr(5000 if (row, col) != (1, 2) else 2000)
        light.CreateExposureAttr(5.0)
        light.CreateEnableColorTemperatureAttr(True)
        light.CreateColorTemperatureAttr(5000)

camera = rep.create.camera(
    position=(0.85, 3.4, 2.6),
    look_at=(14.0, 6.5, 2.25),
    focal_length=15.0,
)
product = rep.create.render_product(camera, (1280, 720))
rgb = rep.AnnotatorRegistry.get_annotator("rgb")
rgb.attach([product])

for _ in range(2):
    rep.orchestrator.step(rt_subframes=8)

pixels = np.array(rgb.get_data(), copy=True)
if pixels.size == 0:
    raise RuntimeError("Camera returned no pixels")
print(f"PIXELS shape={pixels.shape} mean={pixels[..., :3].mean():.1f}",
      flush=True)

Image.fromarray(pixels).save(sys.argv[1])
print("RENDER SAVED", flush=True)
sim.close()
'''


@app.function(
    image=image,
    gpu="L40S",
    cpu=8,
    memory=32768,
    timeout=240,
    retries=0,
)
def render():
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "frame.png"
        try:
            result = subprocess.run(
                [sys.executable, "-u", "-c", SCENE, str(output)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=180,
            )
            log, code = result.stdout, result.returncode
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            log = out.decode(errors="replace") if isinstance(out, bytes) else out
            log += "\n[TIMEOUT] Isaac subprocess killed after 180s\n"
            code = -1
        print(log[-20000:], flush=True)
        print(f"Isaac process exit code: {code}", flush=True)
        png = output.read_bytes() if (code == 0 and output.exists()) else None
        return {"png": png, "log": log, "code": code}


@app.local_entrypoint()
def main():
    output_dir = Path(__file__).resolve().parents[2] / "out" / "levi_step4"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = render.remote()
    (output_dir / "empty_hall_stage1_isaac.log").write_text(result["log"])
    print("ISAAC LOG SAVED: empty_hall_stage1_isaac.log")
    if result["png"] is None:
        raise SystemExit(f"Render failed (exit code {result['code']})")
    output = output_dir / "empty_hall_stage1.png"
    output.write_bytes(result["png"])
    print(f"IMAGE SAVED: {output.resolve()}")
