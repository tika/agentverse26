"""Assemble the warehouse stage and roof-off review stage using portable USDA."""
import json

from storage import ROOT, HEADER, box, material, vector, write_storage

PALETTE = {
    "Frame": (.12, .16, .18), "Traffic": (.94, .62, .045), "White": (.84, .87, .85),
    "Olive": (.15, .24, .20), "Plywood": (.41, .27, .14), "Red": (.56, .08, .044),
    "Blue": (.075, .21, .35),
}


def markings(layout):
    out = ['def Scope "Markings" {']
    for row in sorted({rack["center"][1] for rack in layout["racks"]}):
        for zone in layout["zones"]:
            xs = [rack["center"][0] for rack in layout["racks"]
                  if rack["zone"] == zone and rack["center"][1] == row]
            if not xs:
                continue
            a, b = min(xs)-.75, max(xs)+.75
            label = f'{zone}_{round(row*100)}'
            for i, y in enumerate((row-.73, row+.73)):
                out.append(box(f"Stripe_{label}_{i}", ((a+b)/2,y,.003), (b-a,.052,.004), "Traffic"))
            for i, x in enumerate((a, b)):
                out.append(box(f"End_{label}_{i}", (x,row,.003), (.052,1.46,.004), "Traffic"))
    width, depth = layout["hall"][:2]
    for x in range(3, width-2, 2):
        out.append(box(f"CentreDash_{x}", (x,depth/2,.003), (.75,.045,.004), "White"))
    for i, y in enumerate((2, 4, 6, 8, 12, 14, 16, 18)):
        out.append(box(f"CrossDash_{i}", (width/2,y,.003), (.045,.55,.004), "White"))
    for side, y in enumerate((.81, layout["hall"][1]-.81)):
        for x in range(3, width-2, 2):
            out.append(box(f"PerimeterDash_{side}_{x}", (x,y,.003),
                           (1.08,.048,.004), "Traffic"))
    for i in range(7):
        out.append(box(f"SpawnHatch_{i}", (.53+i*.14,6,.003), (.065,1.15,.004), "Traffic"))
    return out + ['}']


def staging(depth):
    out = ['def Scope "Staging" {']
    for side, y in enumerate((.38, depth-.38)):
        for index, x in enumerate((5.5, 8.5, 15.5, 18.5)):
            name = f"{side}_{index}"
            finish = ("Blue", "Olive", "Red", "Plywood")[index]
            out.append(box(f"Crate_{name}", (x,y,.56), (1.40,.58,.91), finish, collision=True))
            for rail, dx in enumerate((-.61, 0, .61)):
                out.append(box(f"Skid_{name}_{rail}", (x+dx,y,.055), (.11,.64,.11), "Plywood"))
            for strap, dx in enumerate((-.50,.50)):
                out.append(box(f"Band_{name}_{strap}", (x+dx,y,1.022), (.07,.62,.026), "Frame"))
            out.append(box(f"StageLine_{name}", (x, y+(.34 if side==0 else -.34),.003),
                           (1.65,.035,.004), "Traffic"))
    return out + ['}']


def write_site(layout):
    out = [HEADER, 'over "World" {', 'over "StorageMaterials" {']
    out.extend(material(name, rgb) for name, rgb in PALETTE.items())
    out += ['}', f'''def Xform "RobotSpawn" {{
        double3 xformOp:translate = {vector(layout["robot_start"])}
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }}''', 'over "Hall" {']
    out += markings(layout) + staging(layout["hall"][1]) + ['}', '}']
    (ROOT / "site.usda").write_text("\n".join(out) + "\n")


def write_stage(filename, hide_roof):
    header = HEADER.replace('    defaultPrim', '    subLayers = [@site.usda@, @shell.usda@, @storage.usda@]\n    defaultPrim')
    if hide_roof:
        header += 'over "World" {\n over "Hall" {\n  over "Roof" {\n   token visibility = "invisible"\n  }\n }\n}\n'
    (ROOT / filename).write_text(header)


if __name__ == "__main__":
    layout = json.loads((ROOT / "map.json").read_text())
    write_storage(layout, ROOT / "storage.usda")
    if not (ROOT / "shell.usda").is_file():
        raise SystemExit("Build the shell layer before composing the warehouse stage.")
    write_site(layout)
    write_stage("warehouse-v3.usda", False)
    write_stage("warehouse-overhead.usda", True)
    print("Wrote warehouse-v3.usda and warehouse-overhead.usda")
