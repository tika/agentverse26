"""Author portable USD storage from map.json and the v2 revolved profiles."""
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "baseline"))
from PIL import Image, ImageDraw, ImageFont
from profiles import drum_profile, make_drum_mesh

HEADER = '#usda 1.0\n(\n    defaultPrim = "World"\n    metersPerUnit = 1\n    upAxis = "Z"\n)\n'
PAINT = {"LLW": (.72, .44, .033), "ILW": (.18, .31, .36),
         "Steel": (.13, .17, .19), "Deck": (.23, .25, .25), "Yellow": (.85, .55, .04)}


PRINT_CENTER = {"LLW": .50, "ILW": .48}


def vector(values):
    return "(" + ", ".join(f"{v:.7g}" for v in values) + ")"


def box(name, center, dimensions, material=None, collision=False, invisible=False):
    apis = []
    if collision:
        apis.append("PhysicsCollisionAPI")
        if not invisible:
            apis.append("PhysicsMeshCollisionAPI")
    if material:
        apis.append("MaterialBindingAPI")
    schemas = f" (prepend apiSchemas = {json.dumps(apis)})" if apis else ""
    prim = "Cube" if invisible else "Mesh"
    lines = [f'def {prim} "{name}"{schemas} {{',
             f'double3 xformOp:translate = {vector(center)}',
             f'float3 xformOp:scale = {vector(dimensions)}',
             'uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]']
    if invisible:
        lines.append("double size = 1")
    else:
        lines += [
            'uniform token subdivisionScheme = "none"',
            "point3f[] points = [(-.5,-.5,-.5), (.5,-.5,-.5), (.5,.5,-.5), (-.5,.5,-.5),"
            " (-.5,-.5,.5), (.5,-.5,.5), (.5,.5,.5), (-.5,.5,.5)]",
            "int[] faceVertexCounts = [4,4,4,4,4,4]",
            "int[] faceVertexIndices = [3,2,1,0, 4,5,6,7, 0,1,5,4, 1,2,6,5, 2,3,7,6, 3,0,4,7]",
        ]
        if collision:
            lines.append('uniform token physics:approximation = "boundingCube"')
    if material:
        lines += [f'rel material:binding = </World/StorageMaterials/{material}>']
    if invisible:
        lines.append('token visibility = "invisible"')
    return "\n".join(lines + ["}"])


def material(name, rgb):
    return f'''def Material "{name}" {{
        token outputs:surface.connect = </World/StorageMaterials/{name}/Shader.outputs:surface>
        def Shader "Shader" {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor = {vector(rgb)}
            float inputs:roughness = 0.38
            float inputs:metallic = 0.22
            token outputs:surface
        }}
    }}'''


def drum_mesh(category):
    profile = drum_profile(category)
    mesh = make_drum_mesh(profile)
    ring = range(len(mesh["points"]) - 64, len(mesh["points"]))
    faces = mesh["faces"] + [tuple(ring)]
    normals = mesh["normals"] + [(0, 0, 1)] * 64
    points = ", ".join(map(vector, mesh["points"]))
    normals = ", ".join(map(vector, normals))
    counts = ", ".join(str(len(face)) for face in faces)
    indices = ", ".join(str(i) for face in faces for i in face)
    uv = ", ".join(map(vector, mesh["uv"][:-64] + [(0, 0)] * 128))
    return f'''class Xform "{category}" {{
        def Mesh "Body" (prepend apiSchemas = ["MaterialBindingAPI"]) {{
            rel material:binding = </World/StorageMaterials/{category}>
            uniform token subdivisionScheme = "none"
            point3f[] points = [{points}]
            int[] faceVertexCounts = [{counts}]
            int[] faceVertexIndices = [{indices}]
            texCoord2f[] primvars:st = [{uv}] (interpolation = "faceVarying")
            normal3f[] normals = [{normals}] (interpolation = "faceVarying")
        }}
    }}'''


def rack_geometry(rack, height):
    x, y = rack["center"]
    edge = rack["size"] / 2
    top = rack["deck_tops"][-1] + height
    parts = [f'def Xform "{rack["id"].replace("-", "_")}" {{']
    parts.append(box("Collision", (x, y, top / 2), (2*edge, 2*edge, top),
                     collision=True, invisible=True))
    for i, (dx, dy) in enumerate(((-1,-1), (-1,1), (1,-1), (1,1))):
        px, py = x + dx*(edge-.038), y + dy*(edge-.038)
        parts.append(box(f"Upright{i}", (px, py, top/2), (.054,.054,top), "Steel"))
        parts.append(box(f"Guard{i}", (px, py, .125), (.075,.075,.25), "Yellow"))
    for i, z in enumerate(rack["deck_tops"], 1):
        parts.append(box(f"Deck{i}", (x,y,z-.017), (1.25,1.25,.034), "Deck"))
        for side, dy in enumerate((-edge+.035, edge-.035)):
            parts.append(box(f"Beam{i}_{side}", (x,y+dy,z-.065), (1.31,.07,.095), "Steel"))
    return "\n".join(parts + ["}"])


def print_font(size):
    font_path = os.environ.get("WAREHOUSE_PRINT_FONT",
                               "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
    if Path(font_path).is_file():
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default(size=size)


def print_texture(drum, directory):
    """Bake one matte ink panel into the cylindrical shell's base color."""
    category = drum["category"]
    width, height = 1536, 768
    paint = tuple(round(255 * (1.055 * channel ** (1 / 2.4) - .055))
                  for channel in PAINT[category])
    ink = (26, 28, 27)
    stock = (231, 222, 185)
    image = Image.new("RGB", (width, height), paint)
    draw = ImageDraw.Draw(image)
    radius = .287 if category == "LLW" else .390
    panel_width = round(.34 * width / (2 * math.pi * radius))
    panel_height = round(.153 * height / drum["height"])
    left = (width - panel_width) // 2
    top = round(height * (1 - PRINT_CENTER[category])) - panel_height // 2
    right, bottom = left + panel_width, top + panel_height
    draw.rounded_rectangle((left, top, right, bottom), radius=4, fill=stock,
                           outline=ink, width=2)
    symbol_size = round(panel_height * .62)
    # Draw the trefoil in a square and compensate for cylindrical UV texel aspect.
    symbol = Image.new("RGB", (200, 200), stock)
    mark = ImageDraw.Draw(symbol)
    for angle in (30, 150, 270):
        mark.pieslice((8, 8, 192, 192), angle - 30, angle + 30, fill=ink)
    mark.ellipse((65, 65, 135, 135), fill=stock)
    mark.ellipse((82, 82, 118, 118), fill=ink)
    symbol_width = round(symbol_size * width * drum["height"] / (height * 2 * math.pi * radius))
    image.paste(symbol.resize((symbol_width, symbol_size), Image.Resampling.LANCZOS),
                (left + 10, top + (panel_height - symbol_size) // 2))
    text_left = left + symbol_width + 20
    line_width = right - text_left - 8
    lines = (("RADIOACTIVE", .24, .23),
             (drum["display_id"], .48, .51),
             (f'{category}  /  {drum["id"]}', .24, .81))
    for label, scale, position in lines:
        size = round(panel_height * scale)
        font = print_font(size)
        while font.getlength(label) > line_width:
            size -= 1
            font = print_font(size)
        draw.text((text_left, top + round(panel_height * position)), label,
                  font=font, fill=ink, anchor="lm")

    aisle_angle = drum["face_sign"] * math.pi / 2
    center = round(width * ((aisle_angle - drum["yaw"]) / math.tau % 1)) % width
    shift = (center - width // 2) % width
    if shift:
        wrapped = Image.new("RGB", image.size)
        wrapped.paste(image.crop((0, 0, width - shift, height)), (shift, 0))
        wrapped.paste(image.crop((width - shift, 0, width, height)), (0, 0))
        image = wrapped
    image.save(directory / f'{drum["id"]}.png')


def print_material(drum):
    name = drum["id"]
    root = f"/World/StorageMaterials/{name}"
    return f'''def Material "{name}" {{
        token outputs:surface.connect = <{root}/Surface.outputs:surface>
        def Shader "Surface" {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = <{root}/Print.outputs:rgb>
            float inputs:roughness = 0.38
            float inputs:metallic = 0.22
            token outputs:surface
        }}
        def Shader "Print" {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @assets/drums/{name}.png@
            token inputs:sourceColorSpace = "sRGB"
            token inputs:wrapS = "repeat"
            token inputs:wrapT = "clamp"
            float2 inputs:st.connect = <{root}/UV.outputs:result>
            float3 outputs:rgb
        }}
        def Shader "UV" {{
            uniform token info:id = "UsdPrimvarReader_float2"
            string inputs:varname = "st"
            float2 outputs:result
        }}
    }}'''


def write_storage(layout, path):
    lines = [HEADER, drum_mesh("LLW"), drum_mesh("ILW"), 'def Xform "World" {',
             'def Scope "StorageMaterials" {']
    lines.extend(material(name, rgb) for name, rgb in PAINT.items())
    texture_directory = path.parent / "assets" / "drums"
    texture_directory.mkdir(parents=True, exist_ok=True)
    for drum in layout["drums"]:
        print_texture(drum, texture_directory)
        lines.append(print_material(drum))
    lines += ['}', 'def Xform "Racks" {']
    heights = {d["category"]: d["height"] for d in layout["drums"]}
    lines.extend(rack_geometry(rack, heights[rack["category"]]) for rack in layout["racks"])
    lines += ['}', 'def Xform "Drums" {']
    for drum in layout["drums"]:
        lines.append(f'''def Xform "{drum["id"]}" (
            prepend inherits = </{drum["category"]}>
            instanceable = true
            prepend apiSchemas = ["MaterialBindingAPI"]
        ) {{
            rel material:binding = </World/StorageMaterials/{drum["id"]}> (
                bindMaterialAs = "strongerThanDescendants"
            )
            custom float warehouse:printCenterFraction = {PRINT_CENTER[drum["category"]]}
            custom string warehouse:zone = "{drum["zone"]}"
            custom string warehouse:locationCode = "{drum["display_id"]}"
            double3 xformOp:translate = {vector((drum["x"], drum["y"], drum["base_z"]))}
            float xformOp:rotateZ = {math.degrees(drum["yaw"]):.7g}
            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateZ"]
        }}''')
    lines += ['}', '}']
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    write_storage(json.loads((ROOT / "map.json").read_text()), ROOT / "storage.usda")
