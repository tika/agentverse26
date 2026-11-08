"""Generate one seedable warehouse inspection session as a USD overlay.

This module is callable from OpenUSD or Isaac Sim. See DEFECTS.md for the
team integration contract, source evidence and limits of the visual model.
"""
import argparse
import json
import math
from pathlib import Path
import secrets

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from pxr import Sdf, Usd, UsdGeom, UsdShade, Vt

from storage import PAINT, PRINT_CENTER, drum_profile, make_drum_mesh

ROOT = Path(__file__).resolve().parent
DEFAULT_STAGE = ROOT / "warehouse-v3.usda"
DEFAULT_MAP = ROOT / "map.json"


def _distance(u, center):
    """Angular distance on the unwrapped cylinder, in turns."""
    return (u - center + .5) % 1 - .5


def _field(rng, size, grid):
    pixels = rng.integers(0, 256, (grid[1], grid[0]), dtype=np.uint8)
    # Wrap the texture horizontally so damage crossing U=0 joins seamlessly.
    padded = np.concatenate((pixels[:, -2:], pixels, pixels[:, :2]), axis=1)
    pad = round(size[0] * 2 / grid[0])
    image = Image.fromarray(padded).resize((size[0] + 2 * pad, size[1]), Image.Resampling.BICUBIC)
    return np.asarray(image, dtype=np.float32)[:, pad:pad + size[0]] / 255


def _llw_chips(rng, size, severity, attack):
    """Adapt the frozen LLW studio recipe to randomly placed coating loss."""
    width, height = size
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    count = round(540 + 1800 * severity)
    for _ in range(count):
        x = int(rng.integers(width))
        branch = rng.random()
        if branch < .43:
            y = height - 1 - rng.exponential(.045 * height)
        elif branch < .62:
            y = rng.exponential(.031 * height)
        elif branch < .88:
            y = rng.choice((height / 3, 2 * height / 3)) + rng.normal(0, .010 * height)
        else:
            y = rng.uniform(0, height)
        radius = float(rng.choice((1, 1.6, 2.3, 3.2, 5.2, 8.0), p=(.23, .26, .22, .15, .10, .04)))
        radius *= .7 + .6 * severity
        opacity = int(rng.integers(125, 256))
        for shifted in (x - width, x, x + width):
            draw.ellipse((shifted - radius, y - radius * .43,
                          shifted + radius, y + radius * .43), fill=opacity)
    chips = np.asarray(mask, dtype=np.float32) / 255
    halo = np.asarray(mask.filter(ImageFilter.GaussianBlur(.65)), dtype=np.float32) / 255
    return np.clip(chips * (.60 + .40 * attack) + attack * (chips > .25) * .40, 0, 1), halo


def _rust(source, target, drum, severity, rng):
    llw = drum["category"] == "LLW"
    width, height = size = (768, 384)
    u = (np.arange(width)[None, :] + .5) / width
    z = 1 - (np.arange(height)[:, None] + .5) / height
    mottling = .58 * _field(rng, size, (43, 26)) + .42 * _field(rng, size, (187, 122))
    attack = np.zeros((height, width), np.float32)
    runoff = np.zeros_like(attack)

    # The seam angle is a manufacturing assumption for the simplified drum
    # model. Chime contacts and under-hoop edges are tied to the actual profile.
    count = 2 + round(severity * (7 if llw else 4))
    anchors = (.026, .32, .655, .951) if llw else (.027, .042, .971)
    sites = []
    for i in range(count):
        site = rng.choice(("chime", "seam", "damage"), p=(.64, .22, .14) if llw else (.75, .23, .02))
        center = float(rng.uniform(0, 1))
        if site == "seam":
            center = .125 + float(rng.normal(0, .006))
        level = float(rng.uniform(.1, .91) if site != "chime" else rng.choice(anchors, p=(.42, .19, .19, .20) if llw else (.45, .20, .35)))
        sx = rng.uniform(.012, .038) * (.7 + severity) * (1 if llw else .72)
        sy = rng.uniform(.009, .026) * (.7 + severity)
        if site == "seam":
            sx *= .48
            sy *= 1.65
        envelope = np.exp(-.5 * ((_distance(u, center) / sx) ** 2 + ((z - level) / sy) ** 2))
        local = np.clip((envelope * (.62 + .82 * mottling) - (.64 - .29 * severity)) * 3.3, 0, 1)
        if not llw:
            # Small dark pits on a larger, weakly stained halo.
            local *= np.clip((mottling - .48) * 6, .08, 1)
        attack = np.maximum(attack, local)
        if level > .12:
            for _ in range(1 + int(severity * 4)):
                start = center + rng.uniform(-sx, sx)
                length = rng.uniform(.035, .16) * (.65 + severity) * (1 if llw else .8)
                fall = (level - z) / length
                drift = rng.uniform(-.012, .012) * np.clip(fall, 0, 1)
                taper = rng.uniform(.0012, .0045) * (1 - .6 * np.clip(fall, 0, 1))
                streak = np.exp(-.5 * (_distance(u, start + drift) / taper) ** 2)
                streak *= np.where((fall >= 0) & (fall <= 1), (1 - np.clip(fall, 0, 1)) ** .8, 0)
                runoff = np.maximum(runoff, streak * (.5 + .5 * mottling))
        sites.append({"feature": str(site), "u": center, "height_fraction": level})

    halo = np.zeros_like(attack)
    if llw:
        chips, halo = _llw_chips(rng, size, severity, attack)
        attack = np.maximum(chips, attack * np.clip((mottling - .36) * 4, 0, 1))
    base = Image.open(source).convert("RGB")
    dim = base.size
    # Keep the existing printed safety panel intact. This scenario generator
    # models corrosion of exposed shell and staining adjacent to the print.
    rgb = np.asarray(base, dtype=np.float32)
    paint = np.array([round(255 * (1.055 * channel ** (1 / 2.4) - .055))
                      for channel in PAINT[drum["category"]]])
    bare = np.all(rgb == paint, axis=-1)
    bare[-2:] = False  # Cap UVs sample the bottom edge of the texture.

    def resize(field):
        return np.asarray(Image.fromarray(np.uint8(np.clip(field, 0, 1) * 255))
                          .resize(dim, Image.Resampling.BILINEAR), dtype=np.float32) / 255
    pits = resize(attack) * bare
    stains = resize(runoff) * bare
    grain = resize(mottling)
    dark = np.array((58, 38, 25) if llw else (67, 49, 40))
    orange = np.array((116, 65, 34) if llw else (143, 100, 67))
    rust = dark + np.clip((grain - .20) * 1.5, 0, 1)[..., None] * (orange - dark)
    if llw:
        fresh_edges = np.clip(resize(halo) - pits, 0, 1)[..., None]
        rust = rust * (1 - fresh_edges) + np.array((155, 91, 42)) * fresh_edges
    stain_color = np.array((126, 62, 29) if llw else (133, 96, 65))
    stain_opacity = (stains * (.65 if llw else .42))[..., None]
    under = rgb * (1 - stain_opacity) + stain_color * stain_opacity
    opacity = pits[..., None] * (1 if llw else .88)
    Image.fromarray(np.uint8(under * (1 - opacity) + rust * opacity)).save(target)
    roughness = .38 + (.46 if llw else .27) * np.maximum(pits, stains * .45)
    metallic = .22 * (1 - pits * .94)
    surface = np.stack((roughness, metallic, np.zeros_like(roughness)), axis=-1)
    Image.fromarray(np.uint8(surface * 255)).save(target.with_suffix(".surface.png"))
    # Visual microrelief only: fine oxide scale and pits, without changing shell thickness.
    relief = pits * ((grain - .5) * (1.6 if llw else .6) - .22)
    dz, du = np.gradient(relief)
    normal = np.stack((-du * 2.5, dz * 2.5, np.ones_like(du)), axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    Image.fromarray(np.uint8((normal * .5 + .5) * 255)).save(target.with_suffix(".normal.png"))
    return {"sites": sites, "body_uv_attack_fraction": float(np.mean(attack > .25))}


def _bulge(body, drum, severity, rng):
    category = drum["category"]
    llw = category == "LLW"
    nominal = drum_profile(category)
    height = drum["height"]
    profile = []
    for a, b in zip(nominal, nominal[1:]):
        divisions = max(1, math.ceil(abs(b[1] - a[1]) / .018))
        profile.extend(tuple(x + (y - x) * i / divisions for x, y in zip(a, b)) for i in range(divisions))
    profile.append(nominal[-1])
    data = make_drum_mesh(profile)
    points = np.asarray(data["points"], dtype=float)
    z = points[:, 2] / height
    azimuth = np.arctan2(points[:, 1], points[:, 0])
    center = rng.uniform(-math.pi, math.pi)
    if llw:
        # The studio reference swells around mid-height. Keep both chimes
        # seated and cap the radius to fit the warehouse's 618 mm spacing.
        t = np.clip((z - .10) / .80, 0, 1)
        shape = np.sin(np.pi * t) ** 2 * (.9 + .1 * np.cos(azimuth - center))
        peak = .008 + severity * .016
    else:
        # Local mid-body lobe from an internal expansion scenario.
        level = rng.uniform(.43, .57)
        sigma = rng.uniform(.11, .19)
        delta = (azimuth - center + math.pi) % (2 * math.pi) - math.pi
        shape = np.exp(-.5 * ((z - level) / sigma) ** 2 - .5 * (delta / .62) ** 2)
        shape *= np.sin(np.pi * np.clip((z - .04) / .92, 0, 1)) ** .65
        peak = .012 + severity * .044
    offsets = peak * shape
    radii = np.linalg.norm(points[:, :2], axis=1)
    if llw:
        offsets = np.minimum(offsets, .308 - radii)
    points[:, :2] *= (1 + offsets / radii)[:, None]

    rings = points.reshape(-1, 64, 3)
    angular = np.roll(rings, -1, axis=1) - np.roll(rings, 1, axis=1)
    axial = np.gradient(rings, axis=0)
    normals = np.cross(angular, axial).reshape(-1, 3)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)
    faces = data["faces"] + [tuple(range(len(points) - 64, len(points)))]
    indices = [i for face in faces for i in face]
    mesh = UsdGeom.Mesh(body)
    mesh.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points.astype(np.float32)))
    mesh.GetFaceVertexIndicesAttr().Set(indices)
    mesh.GetFaceVertexCountsAttr().Set([len(f) for f in faces])
    face_normals = normals[np.asarray(indices)].astype(np.float32)
    face_normals[-128:-64] = (0, 0, -1)
    face_normals[-64:] = (0, 0, 1)
    mesh.GetNormalsAttr().Set(Vt.Vec3fArray.FromNumpy(face_normals))
    mesh.SetNormalsInterpolation("faceVarying")
    uv = data["uv"][:-64] + [(0, 0)] * 128
    UsdGeom.PrimvarsAPI(mesh).GetPrimvar("st").Set(Vt.Vec2fArray(uv))
    mesh.CreateExtentAttr().Set([tuple(points.min(axis=0)), tuple(points.max(axis=0))])
    return {"peak_radial_displacement_mm": float(offsets.max() * 1000),
            "peak_height_fraction": float(z[np.argmax(offsets)]),
            "azimuth_rad": float(center), "shape": "centered_sidewall_expansion" if llw else "localized_shell_lobe"}


def _bind_rust(stage, prim, target):
    # Inherit the existing print shader and override only its image input.
    name = prim.GetName()
    source = f"/World/StorageMaterials/{name}"
    path = f"/World/SessionMaterials/{name}"
    material = UsdShade.Material.Define(stage, path)
    material.GetPrim().GetInherits().AddInherit(source)
    # Source connections are remapped by USD inheritance to the new material.
    print_shader = UsdShade.Shader.Get(stage, f"{path}/Print")
    print_shader.GetInput("file").Set(Sdf.AssetPath(f"./{target.parent.name}/{target.name}"))
    uv = UsdShade.Shader.Get(stage, f"{path}/UV").GetOutput("result")
    surface = UsdShade.Shader.Get(stage, f"{path}/Surface")
    for role, outputs in (("surface", ("r", "g")), ("normal", ("rgb",))):
        texture = UsdShade.Shader.Define(stage, f"{path}/{role.title()}Map")
        texture.CreateIdAttr("UsdUVTexture")
        texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(
            Sdf.AssetPath(f"./{target.parent.name}/{target.stem}.{role}.png"))
        texture.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("raw")
        texture.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
        texture.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("clamp")
        texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(uv)
        if role == "normal":
            texture.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set((2, 2, 2, 1))
            texture.CreateInput("bias", Sdf.ValueTypeNames.Float4).Set((-1, -1, -1, 0))
            normal = texture.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
            surface.CreateInput("normal", Sdf.ValueTypeNames.Normal3f).ConnectToSource(normal)
        else:
            for channel, material_input in zip(outputs, ("roughness", "metallic")):
                output = texture.CreateOutput(channel, Sdf.ValueTypeNames.Float)
                surface.GetInput(material_input).ConnectToSource(output)
    UsdShade.MaterialBindingAPI(prim).Bind(material, UsdShade.Tokens.strongerThanDescendants)


def generate_session(output, *, seed=None, manifest=None, base_stage=DEFAULT_STAGE, map_path=DEFAULT_MAP):
    """Return a session stage path. A supplied seed reproduces the same faults."""
    output = Path(output).resolve()
    base_stage = Path(base_stage).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or (manifest is not None and Path(manifest).exists()):
        raise FileExistsError("Use a fresh session output and manifest path")
    layout = json.loads(Path(map_path).read_text())
    seed = secrets.randbits(64) if seed is None else seed
    rng = np.random.default_rng(seed)
    textures = output.parent / f"{output.stem}_textures"
    textures.mkdir(exist_ok=False)
    stage = Usd.Stage.CreateNew(str(output))
    stage.GetRootLayer().subLayerPaths = [str(base_stage)]
    stage.SetDefaultPrim(stage.GetPrimAtPath("/World"))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    entries = []
    for category in ("LLW", "ILW"):
        drums = [d for d in layout["drums"] if d["category"] == category]
        # Exercise examples in every launch. These are training mix settings,
        # not estimates of real corrosion prevalence.
        order = rng.permutation(len(drums))
        rust_count = round(len(drums) * rng.uniform(.13, .22) * (1 if category == "LLW" else .6))
        bulge_count = round(len(drums) * rng.uniform(.055, .10))
        overlap = max(1, bulge_count // 5)
        rust_indices = set(order[:rust_count])
        bulge_indices = set(order[:overlap]) | set(order[rust_count:rust_count + bulge_count - overlap])
        for i in sorted(rust_indices | bulge_indices):
            drum = drums[i]
            prim = stage.GetPrimAtPath(drum["prim_path"])
            entry = {"drum_id": drum["id"], "category": category, "prim_path": drum["prim_path"]}
            if i in rust_indices:
                material, _ = UsdShade.MaterialBindingAPI(stage.GetPrimAtPath(drum["prim_path"] + "/Body")).ComputeBoundMaterial()
                asset = material.GetPrim().GetChild("Print").GetAttribute("inputs:file").Get()
                target = textures / f'{drum["id"]}.png'
                severity = float(rng.beta(2, 2))
                entry["corrosion"] = {"severity": severity, **_rust(asset.resolvedPath, target, drum, severity, rng)}
                _bind_rust(stage, prim, target)
            if i in bulge_indices:
                prim.SetInstanceable(False)
                body = stage.GetPrimAtPath(drum["prim_path"] + "/Body")
                severity = float(rng.beta(2, 2))
                entry["bulging"] = {"severity": severity, **_bulge(body, drum, severity, rng)}
            entries.append(entry)
    stage.GetRootLayer().Save()
    if manifest is not None:
        manifest = Path(manifest)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("x") as handle:
            json.dump({"schema_version": 1, "seed": seed, "drums": entries}, handle, indent=2)
            handle.write("\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    print(generate_session(args.output, seed=args.seed, manifest=args.manifest))
