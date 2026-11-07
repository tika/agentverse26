"""Build the inspection MVP and render proof artifacts on Modal."""
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

app = modal.App("isaac-inspection-mvp")

SCENE = r'''
import json
import math
from pathlib import Path
from pxr import UsdSemantics
from PIL import ImageDraw

out = Path(sys.argv[1])
seed = int(sys.argv[2])
inspection_height = .60
drums = {}
profiles = {}
paint = [
    material("PaintBlue", (.07,.18,.32), .65),
    material("PaintYellow", (.64,.40,.07), .65),
    material("PaintGrey", (.34,.37,.39), .65),
]
steel = material("DrumSteel", (.53,.57,.60), .54)
tint = material("WeldTint", (.38,.30,.21), .64)
rusts = [material("RustDark", (.15,.045,.014), .95),
         material("RustOrange", (.51,.17,.035), .94)]
wet = material("Leachate", (.095,.046,.018), .30)
dry = material("Residue", (.56,.49,.35), .88)

def label(prim, kind, drum_id):
    for taxonomy, value in (("class", kind), ("drum_id", drum_id)):
        UsdSemantics.LabelsAPI.Apply(prim, taxonomy).CreateLabelsAttr().Set([value])

def mesh(path, points, faces, uv, mat):
    obj = UsdGeom.Mesh.Define(stage, path)
    obj.CreatePointsAttr(points)
    obj.CreateFaceVertexCountsAttr([len(face) for face in faces])
    obj.CreateFaceVertexIndicesAttr([index for face in faces for index in face])
    obj.CreateSubdivisionSchemeAttr("none")
    obj.CreateDoubleSidedAttr(True)
    UsdGeom.PrimvarsAPI(obj).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, "vertex"
    ).Set(uv)
    prim = obj.GetPrim()
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(mat)
    return prim

def revolve(path, rings, mat):
    points, uv, faces = [], [], []
    for r, z in rings:
        for i in range(65):
            a = math.tau * i / 64
            points.append((r*math.cos(a), r*math.sin(a), z))
            uv.append((i/64, z/rings[-1][1]))
    for row in range(len(rings)-1):
        for i in range(64):
            j = 65*row+i
            faces.append((j, j+1, j+66, j+65))
    return mesh(path, points, faces, uv, mat)

def plate_material(drum_id, category):
    filename = f"plate_{drum_id}.png"
    img = Image.new("RGB", (200,140), (224,174,38))
    draw = ImageDraw.Draw(img)
    for angle in (0,120,240):
        draw.pieslice((9,15,74,80), angle, angle+59, fill="black")
    draw.ellipse((36,42,46,52), fill=(224,174,38))
    draw.text((90,18), category, fill="black", font_size=28)
    draw.text((90,55), drum_id, fill="black", font_size=27)
    for x in range(18,182,5):
        draw.rectangle((x,106,x+(x%3),124), fill="black")
    img.save(out / filename)
    mat = material("Plate" + drum_id, (.75,.52,.03), .72)
    shader = UsdShade.Shader.Get(stage, mat.GetPath().AppendChild("Surface"))
    tex = UsdShade.Shader.Define(stage, mat.GetPath().AppendChild("Texture"))
    tex.CreateIdAttr("UsdUVTexture")
    tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(str(out / filename))
    reader = UsdShade.Shader.Define(stage, mat.GetPath().AppendChild("UV"))
    reader.CreateIdAttr("UsdPrimvarReader_float2")
    reader.CreateInput("varname", Sdf.ValueTypeNames.String).Set("st")
    reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)
    tex.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), "result")
    tex.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
    shader.GetInput("diffuseColor").ConnectToSource(tex.ConnectableAPI(), "rgb")
    return tex.GetInput("file"), mat

def build_drums(layout_seed):
    rng = np.random.default_rng(layout_seed)
    for path in ("/World/Drums", "/World/Defects"):
        stage.RemovePrim(path)
    drums.clear()
    profiles.clear()
    plate_assets = []
    UsdGeom.Xform.Define(stage, "/World/Drums")
    for zone, xs in (("A",(3,4.5,6,7.5)), ("B",(12,14,16))):
        llw = zone == "A"
        category, r, h = ("LLW",.29,.88) if llw else ("ILW",.40,1.20)
        for row, y, side, aisle in zip("ABCD",(3.45,4.55,7.45,8.55),(-1,1,-1,1),(1,2,2,3)):
            for x in xs:
                drum_id = f"D{len(drums)+1:02}"
                path = "/World/Drums/" + drum_id
                root = UsdGeom.Xform.Define(stage, path)
                root.AddTranslateOp().Set(Gf.Vec3d(x,y,0))
                yaw = float(rng.uniform(0,math.tau))
                rings = [(0,0),(r-.018,0),(r,.018),(r,.045),(r-.012,.056)]
                if llw:
                    for z in (h/3,2*h/3):
                        rings += [(r-.012,z-.026),(r,z-.012),(r,z+.012),(r-.012,z+.026)]
                rings += [(r-.012,h-.052),(r,h-.038),(r,h),(r-.023,h),
                          (r-.033,h-.014),(0,h-.014)]
                # Radius lookup uses the exterior profile only.
                profiles[drum_id] = rings[1:-3]
                body = revolve(path+"/Body", rings, paint[int(rng.integers(3))] if llw else steel)
                label(body,"drum",drum_id)
                if not llw:
                    revolve(path+"/HeatTint",[(r-.0118,h-.066),(r-.0118,h-.052)],tint)
                for index, (offset, rad) in enumerate(((.16,.030),(-.10,.017)) if llw else ((.13,.044),)):
                    cap = UsdGeom.Cylinder.Define(stage,path+f"/LidPart{index}")
                    cap.CreateRadiusAttr(rad)
                    cap.CreateHeightAttr(.024 if llw else .045)
                    cap.AddTranslateOp().Set(Gf.Vec3d(offset*math.cos(yaw),offset*math.sin(yaw),h+.005))
                    UsdShade.MaterialBindingAPI.Apply(cap.GetPrim()).Bind(steel)
                tex, mat = plate_material(drum_id, category)
                plate_assets.append((tex, f"plate_{drum_id}.png"))
                py = side*(r+.002)
                mesh(path+"/Plate",[(side*.10,py,h*.60-.07),(-side*.10,py,h*.60-.07),
                    (-side*.10,py,h*.60+.07),(side*.10,py,h*.60+.07)],
                    [(0,1,2,3)],[(0,0),(1,0),(1,1),(0,1)],mat)
                drums[drum_id] = dict(id=drum_id,category=category,zone=zone,row=row,x=x,y=y,
                    yaw=yaw,radius=r,height=h,facing_aisle=aisle,source_strength=1 if llw else 20,
                    prim_path=path,state="clean",faults=[],corrosion_severity=0,defects=[],
                    shape=dict(max_radius=r,lid_rise=0,dents=[]),obstructed=False,internal_corrosion=False)
    return plate_assets

def write_inventory():
    (out/"drums.json").write_text(json.dumps(list(drums.values()),indent=2)+"\n")

def set_drum_state(drum_id, faults, severity=2, *, seed=0):
    """Replace this drum's visible defects with a reproducible set."""
    faults = sorted(set(faults))
    if set(faults) - {"corrosion","leak","residue"} or severity not in (1,2,3):
        raise ValueError("Expected corrosion, leak or residue and severity 1–3")
    d = drums[drum_id]
    root = "/World/Defects/"+drum_id
    stage.RemovePrim(root)
    UsdGeom.Xform.Define(stage,root)
    rand = np.random.default_rng([seed,int(drum_id[1:])])
    side = -1 if d["row"] in "AC" else 1
    a0 = side*math.pi/2
    x,y,r,h = (d[k] for k in ("x","y","radius","height"))
    defects = []

    def patch(name, kind, subtype, location, scale, mat, on_drum, phase):
        points, faces, uv = [], [], []
        for ring in (0,.45,1):
            for i in range(48):
                a = math.tau*i/48
                rho = ring*(1+.15*math.sin(3*a+phase)+.09*math.sin(7*a-phase)+.04*math.cos(13*a))
                u,v = rho*math.cos(a),rho*math.sin(a)
                s,t = location[0]+u*scale[0],location[1]+v*scale[1]
                if on_drum:
                    rr = np.interp(t,[z for _,z in profiles[drum_id]],
                                   [rad for rad,_ in profiles[drum_id]]) + .004
                    points.append((x+rr*math.cos(s),y+rr*math.sin(s),t))
                else:
                    points.append((s,t,.012 if subtype=="puddle" else .010))
                uv.append(((u+1)/2,(v+1)/2))
        for j in range(2):
            for i in range(48):
                a,b = j*48+i,j*48+(i+1)%48
                faces.append((a,b,b+48,a+48))
        path = root+"/"+name
        prim = mesh(path, points, faces, uv, mat)
        label(prim,kind,drum_id)
        defects.append(dict(type=kind,subtype=subtype,prim_path=path,
                            size=list(scale),z=location[1] if on_drum else 0,
                            angle=location[0] if on_drum else None))

    if "corrosion" in faults:
        for i in range(severity):
            angle = a0 + float(rand.uniform(-.15,.15)) + (i-(severity-1)/2)*.47
            z = h*(.14+.17*i) if d["category"]=="LLW" else h*(.78-.14*i)
            subtype = f"stage{severity}" if d["category"]=="LLW" else "tea_stain"
            mat = rusts[severity>1] if d["category"]=="LLW" else tint
            patch(f"Corrosion_{i}","corrosion",subtype,(angle,z),(.31,.056),mat,True,rand.uniform(0,6))
    for fault, subtype, mat, offset in (("leak","puddle",wet,0),("residue","residue",dry,.09)):
        if fault in faults:
            patch("Spill_"+subtype,"spill",subtype,(x+offset,y+side*(r+.23)),
                  (.25,.32),mat,False,rand.uniform(0,6))
            patch("Spill_"+fault+"_Trail","spill",fault+"_trail",(a0+.25,h*.44),
                  (.063,h*.34),mat,True,rand.uniform(0,6))
    d.update(state="+".join(faults) or "clean",faults=faults,
             corrosion_severity=severity if "corrosion" in faults else 0,defects=defects)
    write_inventory()

def build_layout(layout):
    plates = build_drums(layout["seed"])
    for drum_id, state in layout["drums"].items():
        set_drum_state(drum_id,state["faults"],state["severity"],seed=layout["seed"])
    write_inventory()
    return plates

camera = UsdGeom.Camera.Define(stage,"/World/InspectionCamera")
camera.CreateFocalLengthAttr(16)
camera.CreateHorizontalApertureAttr(27)
camera.CreateVerticalApertureAttr(15.1875)
camera.CreateClippingRangeAttr(Gf.Vec2f(.035,60))
transform = camera.AddTransformOp()
product = rep.create.render_product(str(camera.GetPath()),(768,432))
rgb = rep.AnnotatorRegistry.get_annotator("rgb")
rgb.attach([product])

def pose(eye, target):
    view = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1))
    transform.Set(view.GetInverse())

def capture_rgb(subframes=1):
    for _ in range(16):
        rep.orchestrator.step(rt_subframes=subframes)
        pixels = np.array(rgb.get_data(),copy=True)
        if pixels.ndim == 3 and pixels.size:
            return Image.fromarray(pixels).convert("RGB")
    raise RuntimeError("Inspection camera did not produce RGB after warmup")

def flythrough(name):
    folder = out/name
    folder.mkdir()
    for frame in range(72):
        x = 1.4 + 15.0*frame/71
        # A slight leftward inspection glance keeps the nearest row in view.
        angle = -.36-.24*math.sin(math.pi*frame/71)
        pose((x,6,inspection_height),(x+math.cos(angle),6+math.sin(angle),.53))
        capture_rgb(4 if frame==0 else 1).save(folder/f"{frame:03}.jpg",quality=91)
    print(f"CAPTURED {name}",flush=True)

import carb
carb.settings.get_settings().set("/exts/omni.replicator.core/maxAssetLoadingTime", 3)
flythrough("stage1_frames")
layout = dict(seed=seed,drums={
    "D10":dict(faults=["corrosion","leak"],severity=3),
    "D25":dict(faults=["corrosion","residue"],severity=2),
})
plate_assets = build_layout(dict(seed=seed,drums={}))
flythrough("stage2_frames")

for drum_id,state in layout["drums"].items():
    set_drum_state(drum_id,state["faults"],state["severity"],seed=seed)
(out/"layout_step4.json").write_text(json.dumps(layout,indent=2)+"\n")

boxes = rep.AnnotatorRegistry.get_annotator(
    "bounding_box_2d_tight",init_params={"semanticTypes":["class","drum_id"]})
boxes.attach([product])
pose((4.65,5.54,inspection_height),(4.58,7.44,.35))
frame = capture_rgb(8)
data = boxes.get_data()
print("BOX ANNOTATOR",data,flush=True)
frame.save(out/"step4_rgb.png")
draw = ImageDraw.Draw(frame)
entries = []
for item, path in zip(data["data"],data["info"]["primPaths"]):
    labels = data["info"]["idToLabels"][str(item["semanticId"])]
    kind = labels["class"]
    drum_id = labels["drum_id"].upper()
    rect = [int(item[key]) for key in ("x_min","y_min","x_max","y_max")]
    color = {"drum":"#4ff6ff","corrosion":"#ff7130","spill":"#f9f34e"}[kind]
    draw.rectangle(rect,outline=color,width=2)
    draw.text((rect[0]+2,max(0,rect[1]-17)),f"{kind} {drum_id}",
              fill=color,stroke_width=2,stroke_fill="black",font_size=15)
    entries.append(dict(class_name=kind,drum_id=drum_id,prim_path=path,xyxy=rect))
frame.save(out/"step4_boxes.png")
(out/"step4_boxes.json").write_text(json.dumps(entries,indent=2)+"\n")
for asset,name in plate_assets:
    asset.Set("./"+name)
stage.Export(str(out/"inspection_step4.usda"))
assert {"drum","corrosion","spill"} <= {e["class_name"] for e in entries}
puddle = next(e for e in entries if e["prim_path"].endswith("/Spill_puddle"))
assert puddle["xyxy"][3] < frame.height - 1
first_inventory = (out/"drums.json").read_bytes()
build_layout(layout)
assert (out/"drums.json").read_bytes() == first_inventory
print("SAME-SEED INVENTORY REBUILD PASSED",flush=True)
print("STEP 4 BOX CHECK PASSED",flush=True)
sim.close()
'''

@app.function(image=image, gpu="L40S", cpu=8, memory=32768, timeout=410, retries=0)
def render(source, seed):
    import io
    import subprocess
    import sys
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        with (root/"isaac.log").open("wb") as log:
            try:
                code = subprocess.run(
                    [sys.executable,"-u","-c",source+SCENE,folder,str(seed)],
                    stdout=log,stderr=subprocess.STDOUT,timeout=360,
                ).returncode
            except subprocess.TimeoutExpired:
                log.write(b"\nIsaac subprocess timed out after 360 seconds.\n")
                code = 124
        print((root/"isaac.log").read_text(errors="replace")[-5000:],flush=True)
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle,"w",zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(root.rglob("*")):
                if file.is_file():
                    archive.write(file,file.relative_to(root))
        return code,bundle.getvalue()

@app.local_entrypoint()
def main(seed: int=42, encoder: str="ffmpeg"):
    import io
    import subprocess
    import tempfile
    import zipfile

    hall = Path(__file__).with_name("empty_hall_stage1.py").read_text()
    source = hall.split("SCENE = r'''",1)[1].split("camera = rep.create.camera",1)[0]
    code,bundle = render.remote(source,seed)
    result = Path(__file__).resolve().parents[2]/"out"/"levi_step4"
    result.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            archive.extractall(temp)
        root = Path(temp)
        for path in root.iterdir():
            if path.is_file():
                (result/path.name).write_bytes(path.read_bytes())
        for step in ("stage1","stage2"):
            frames = root/(step+"_frames")
            if len(list(frames.glob("*.jpg"))) == 72:
                subprocess.run([encoder,"-hide_banner","-loglevel","error","-y",
                    "-framerate","15","-i",str(frames/"%03d.jpg"),
                    "-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",
                    str(result/(step+"_spot_height.mp4"))],check=True)
    if code:
        raise SystemExit(f"Isaac subprocess exited {code}. See {result/'isaac.log'}")
    print(f"Artifacts saved in {result}")
