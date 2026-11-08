"""Warehouse v3 shell: slab, clad walls, portal columns, steel roof trusses, purlins,
metal decking and high-bay lighting. Pure pxr (runs in Isaac Sim or with usd-core).

Frame (shared contract, teamwork.md): metres, Z-up, origin at the south-west inside
corner, +X along the rack banks, front wall (roller shutter, personnel door) at x=0.
Everything above the eaves that blocks a top-down view lives under /World/Hall/Roof,
so an overhead review only needs to hide that one prim.
"""
import math

import numpy as np
from PIL import Image

WALL_T = 0.30          # wall thickness, outside the interior footprint
# Heights are derived from what the building must clear (see design note in build_shell):
#   tallest stack top 4.03 m (ILW, 3 x 1.344 m) -> crane hook must lift a 1.2 m ILW drum over it
#   -> hook parked/working >= 5.6 m -> runway 6.6 m, girder top 7.33 m, trolley top 7.68 m
#   -> truss bottom chord 8.0 m (0.25 m over the trolley) -> 0.725 m truss depth at the eaves,
#   5 deg duo pitch, purlins on the top chord, decking on the purlins.
CHORD_Z = 8.00         # truss bottom chord centreline = column cap / bearing level
TRUSS_DEPTH = 0.725     # top-chord centreline above bottom chord at the eaves
PITCH_DEG = 5.0
TC_H = 0.16            # top chord section depth
PURLIN_H = 0.275        # Z-purlin depth (sits on the top chord)
DECK_T = 0.04
BAY = 5.0              # portal frame spacing along x
FIXTURE_Z = 7.92       # lamp face: 0.15 m over the crane trolley top (7.77 m), just under the 8.0 m chord level
RUNWAY_Z = 6.60        # crane runway beam centreline
GATE_W, GATE_H = 4.0, 4.5   # clear opening of the end-wall roller shutters


def roof_line(y, D):
    """Top-chord centreline height at y (duo pitch, ridge at D/2)."""
    return CHORD_Z + TRUSS_DEPTH + math.tan(math.radians(PITCH_DEG)) * min(y, D - y)


def deck_underside(y, D):
    return roof_line(y, D) + TC_H / 2 + PURLIN_H


def _normal_map(path, period_px, depth, profile='sine', horizontal=False):
    """Tileable 512 px normal map with ribs running along v (trapezoidal or sine)."""
    u = np.arange(512) / 512
    if profile == 'trapezoid':
        phase = (u * 512 / period_px) % 1.0
        height = np.clip(np.minimum(phase, 1 - phase) * 6 - 0.6, 0, 1) * depth
        slope = np.gradient(height, 1 / 512)
    else:
        slope = depth * 2 * np.pi * (512 / period_px) * np.cos(2 * np.pi * u * 512 / period_px)
    normals = np.stack((-slope, np.zeros_like(slope), np.ones_like(slope)), axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    pixels = np.broadcast_to((normals * .5 + .5)[None, :, :], (512, 512, 3))
    if horizontal:
        pixels = pixels.transpose(1, 0, 2).copy()
        pixels[:, :, 1] = 1 - pixels[:, :, 0]
        pixels[:, :, 0] = .5
    Image.fromarray(np.uint8(pixels * 255)).save(path)
    return path


def _floor_maps(assets, layout, seed, px_per_m=128):
    """One non-repeating map set for the whole slab (no tiling): power-trowelled concrete with
    multi-scale tonal variation, sawn control joints, and restrained wear along robot routes."""
    from PIL import ImageFilter
    W, D, _ = layout['hall']
    sw, sd = W + 2 * WALL_T, D + 2 * WALL_T
    nx, ny = int(sw * px_per_m), int(sd * px_per_m)
    rng = np.random.default_rng(seed + 7)

    def octave(cells, amp):
        g = rng.normal(0, 1, (cells[1], cells[0])).astype(np.float32)
        img = Image.fromarray(np.uint8(np.clip(128 + g * 40, 0, 255))).resize((nx, ny), Image.BICUBIC)
        return (np.asarray(img, np.float32) - 128) / 40 * amp
    tone = octave((6, 5), 2.9) + octave((24, 20), 2.1) + octave((96, 80), 1.6) + rng.normal(0, 1.4, (ny, nx)).astype(np.float32)
    # Trowel sheen: long soft arcs, very low contrast.
    yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float32) / px_per_m
    sheen = np.sin((xx * 1.7 + np.sin(yy * .9) * 1.3) * 2.1) * np.sin((yy * 1.3 + np.cos(xx * .7)) * 1.7)
    tone += sheen * 1.2
    rough = 0.58 + octave((40, 34), .05) - sheen * .02
    # Wear: tyre/foot traffic along route edges (map graph), darker and slightly polished.
    wear = np.zeros((ny, nx), np.float32)
    nodes = layout['nodes']
    for a_, b_ in layout['edges']:
        (ax, ay), (bx, by) = nodes[a_], nodes[b_]
        for off in (-.28, .28):
            if ay == by:
                x0, x1 = sorted((ax, bx)); y0 = ay + off
                r0, r1 = int((y0 + WALL_T - .12) * px_per_m), int((y0 + WALL_T + .12) * px_per_m)
                wear[max(r0, 0):r1, int((x0 + WALL_T) * px_per_m):int((x1 + WALL_T) * px_per_m)] += 1
            else:
                y0, y1 = sorted((ay, by)); x0 = ax + off
                c0, c1 = int((x0 + WALL_T - .12) * px_per_m), int((x0 + WALL_T + .12) * px_per_m)
                wear[int((y0 + WALL_T) * px_per_m):int((y1 + WALL_T) * px_per_m), max(c0, 0):c1] += 1
    wear = np.asarray(Image.fromarray(np.uint8(np.clip(wear, 0, 1) * 255)).filter(ImageFilter.GaussianBlur(px_per_m * .12)), np.float32) / 255
    wear *= np.clip(.6 + octave((60, 50), .5), 0, 1)
    tone -= wear * 7.0
    rough -= wear * .08
    # Control joints: sawn every 6 m (x) and 5 m (y) on the interior grid, 4 mm wide, slightly dark.
    joints = np.zeros((ny, nx), np.float32)
    for x in np.arange(6.0, W - .1, 6.0):
        c = int((x + WALL_T) * px_per_m); joints[:, c:c + 1] = 1
    for y in np.arange(5.0, D - .1, 5.0):
        r = int((y + WALL_T) * px_per_m); joints[r:r + 1, :] = 1
    soft = np.asarray(Image.fromarray(np.uint8(joints * 255)).filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255
    tone -= joints * 26 + soft * 6
    base = np.clip(112 + tone, 0, 255)
    rgb = np.stack((base * 1.0, base * .995, base * .975), axis=-1)
    paths = {k: assets / f'v3_floor_{k}.png' for k in ('diffuse', 'roughness', 'normal')}
    Image.fromarray(np.uint8(np.clip(rgb, 0, 255))[::-1]).save(paths['diffuse'])
    Image.fromarray(np.uint8(np.clip(rough, .35, .8) * 255)[::-1]).save(paths['roughness'])
    # Normal map: joint grooves plus very faint trowel undulation.
    height = -joints * 1.0 - soft * .3 + sheen * .02
    gy, gx = np.gradient(height)
    n = np.stack((-gx * 1.5, -gy * 1.5, np.ones_like(gx)), axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    Image.fromarray(np.uint8((n * .5 + .5) * 255)[::-1]).save(paths['normal'])
    return paths


def shell_materials(stage, assets, seed=42, layout=None):
    from materials import material
    assets.mkdir(parents=True, exist_ok=True)
    cladding = _normal_map(assets / 'v3_cladding_normal.png', 51.2, .006)
    decking = _normal_map(assets / 'v3_decking_normal.png', 128, .02, 'trapezoid')
    shutter = _normal_map(assets / 'v3_shutter_normal.png', 64, .008, 'trapezoid', horizontal=True)
    floor = _floor_maps(assets, layout, seed)
    return {
        'floor': material(stage, 'V3Floor', (1, 1, 1), .58, textures={'diffuseColor': floor['diffuse'], 'roughness': floor['roughness'],
                                                                  'normal': floor['normal']}, uv_scale=(1, 1)),
        'plinth': material(stage, 'V3Plinth', (.46, .46, .44), .85),
        'wall': material(stage, 'V3WallCladding', (.52, .55, .57), .55, .3, textures={'normal': cladding}, uv_scale=(30, 6)),
        'end': material(stage, 'V3EndCladding', (.52, .55, .57), .55, .3, textures={'normal': cladding}, uv_scale=(16, 6)),
        'deck': material(stage, 'V3RoofDecking', (.62, .64, .65), .5, .45, textures={'normal': decking}, uv_scale=(30, 1)),
        'steel': material(stage, 'V3StructSteel', (.20, .23, .25), .45, .6),
        'purlin': material(stage, 'V3Purlin', (.31, .34, .36), .45, .55),
        'lamp_body': material(stage, 'V3HighBayBody', (.16, .17, .18), .5, .5),
        'lamp_face': material(stage, 'V3HighBayFace', (.95, .95, .95), .3, emission=(6., 6., 6.)),
        'shutter': material(stage, 'V3RollerShutter', (.35, .38, .40), .52, .35, textures={'normal': shutter}, uv_scale=(1, 6)),
        'door': material(stage, 'V3PersonnelDoor', (.17, .28, .24), .5, .2),
        'glass': material(stage, 'V3DarkGlass', (.025, .055, .065), .16, .1),
        'yellow': material(stage, 'V3SafetyYellow', (.80, .58, .03), .5, .1),
        'black': material(stage, 'V3HazardBlack', (.03, .03, .03), .6),
        'monitor': material(stage, 'V3MonitorHousing', (.42, .45, .43), .6, .1),
        'amber': material(stage, 'V3Amber', (.85, .32, .025), .3, emission=(.6, .15, .01)),
        'red': material(stage, 'V3FireRed', (.60, .035, .02), .45),
        'duct': material(stage, 'V3Duct', (.45, .48, .49), .5, .5),
    }


def _beam(stage, path, a, b, width, height, mat):
    """Rectangular steel member from a to b (centre line)."""
    from pxr import Gf, UsdGeom
    from geometry import box
    a, b = Gf.Vec3d(*a), Gf.Vec3d(*b)
    v = b - a
    part = box(stage, path, tuple((a + b) * .5), (width, height, v.GetLength()), mat)
    UsdGeom.Xformable(part).AddOrientOp().Set(Gf.Quatf(Gf.Rotation(Gf.Vec3d(0, 0, 1), v).GetQuat()))
    return part


def _i_column(stage, path, x, y, z0, z1, mat, flange=.30, depth=.30):
    """Universal-column look: two flanges + web, flanges parallel to the wall."""
    from geometry import box
    h, zc = z1 - z0, (z0 + z1) / 2
    tf = .02
    box(stage, path + '_FlangeA', (x, y - depth / 2 + tf / 2, zc), (flange, tf, h), mat, collision=True)
    box(stage, path + '_FlangeB', (x, y + depth / 2 - tf / 2, zc), (flange, tf, h), mat, collision=True)
    box(stage, path + '_Web', (x, y, zc), (.015, depth - 2 * tf, h), mat)


def build_shell(stage, layout, assets, seed=42):
    from pxr import Gf, UsdGeom, UsdLux
    from geometry import box, cylinder, panel, mesh
    W, D, _ = layout['hall']
    m = shell_materials(stage, assets, seed, layout)
    for p in ('/World/Hall', '/World/Hall/Structure', '/World/Hall/Details', '/World/Hall/Roof',
              '/World/Hall/Roof/Trusses', '/World/Hall/Roof/Purlins', '/World/Hall/Roof/Decking',
              '/World/Hall/Roof/Fixtures', '/World/Hall/Lights'):
        UsdGeom.Xform.Define(stage, p)
    S, R, H = '/World/Hall/Structure/', '/World/Hall/Roof/', '/World/Hall/Details/'

    # Slab: collision unchanged (one 0.3 m box, top at z=0); finish comes from the full-slab maps.
    box(stage, S + 'Floor', (W / 2, D / 2, -.15), (W + 2 * WALL_T, D + 2 * WALL_T, .3), m['floor'], collision=True)
    eave_top = deck_underside(0, D)              # side walls run up to the decking underside
    ridge_under = deck_underside(D / 2, D)
    for name, c, sz in (('WallSouth', (W / 2, -WALL_T / 2, eave_top / 2), (W + 2 * WALL_T, WALL_T, eave_top)),
                        ('WallNorth', (W / 2, D + WALL_T / 2, eave_top / 2), (W + 2 * WALL_T, WALL_T, eave_top))):
        box(stage, S + name, c, sz, m['wall'], collision=True)
    # End walls with a framed roller-shutter opening on the main aisle (y = D/2):
    #   West = robot / LLW / personnel entrance; East = ILW receipt bay served by the crane.
    gy0, gy1 = D / 2 - GATE_W / 2, D / 2 + GATE_W / 2
    for end, xw, n in (('Front', -WALL_T / 2, 1), ('Back', W + WALL_T / 2, -1)):
        box(stage, S + f'Wall{end}', (xw, gy0 / 2, eave_top / 2), (WALL_T, gy0, eave_top), m['end'], collision=True)
        box(stage, S + f'Wall{end}R', (xw, (gy1 + D) / 2, eave_top / 2), (WALL_T, D - gy1, eave_top), m['end'], collision=True)
        box(stage, S + f'Wall{end}Lintel', (xw, D / 2, (GATE_H + eave_top) / 2), (WALL_T, GATE_W, eave_top - GATE_H), m['end'], collision=True)
        # Gable: exact triangle from the eave line to the decking underside at the ridge.
        x0, x1 = xw - WALL_T / 2, xw + WALL_T / 2
        pts = [(x, y, z) for x in (x0, x1) for (y, z) in ((0, eave_top), (D, eave_top), (D / 2, ridge_under))]
        mesh(stage, R + f'Decking/Gable{end}', pts, [(0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)],
             [(0, 0), (1, 0), (.5, 1)] * 2 + [(0, 0), (1, 0), (1, 1), (0, 1)] * 3, m['end'])
    # Concrete upstand (0.9 m) along the long walls and either side of the gates.
    for name, c, sz in (('PlinthSouth', (W / 2, .06, .45), (W, .12, .9)), ('PlinthNorth', (W / 2, D - .06, .45), (W, .12, .9))):
        box(stage, S + name, c, sz, m['plinth'], collision=True)

    # Portal frames at x = 2, 7, ..., 22: I-columns to the bearing level, cap plate, truss on top.
    xs = [2.0 + i * BAY for i in range(int((W - 2.0) / BAY) + 1)]
    tan = math.tan(math.radians(PITCH_DEG))
    ya, yb = .27, D - .27                       # column centrelines = truss bearings
    for i, x in enumerate(xs):
        for side, y in (('S', ya), ('N', yb)):
            _i_column(stage, S + f'Column{i:02d}{side}', x, y, 0, CHORD_Z - .09, m['steel'])
            box(stage, S + f'Column{i:02d}{side}_Cap', (x, y, CHORD_Z - .08), (.34, .34, .02), m['steel'])
            box(stage, R + f'Trusses/T{i:02d}_Bearing{side}', (x, y, CHORD_Z), (.14, .3, .14), m['steel'])
        T = R + f'Trusses/T{i:02d}'
        _beam(stage, T + '_Bottom', (x, ya, CHORD_Z), (x, yb, CHORD_Z), .14, .14, m['steel'])
        _beam(stage, T + '_TopS', (x, ya, roof_line(ya, D)), (x, D / 2, roof_line(D / 2, D)), .16, TC_H, m['steel'])
        _beam(stage, T + '_TopN', (x, D / 2, roof_line(D / 2, D)), (x, yb, roof_line(yb, D)), .16, TC_H, m['steel'])
        panels = 8
        for j in range(panels + 1):
            y = ya + (yb - ya) * j / panels
            _beam(stage, T + f'_Post{j}', (x, y, CHORD_Z + .07), (x, y, roof_line(y, D) - TC_H / 2), .08, .08, m['steel'])
            if j < panels:
                y2 = ya + (yb - ya) * (j + 1) / panels
                if y2 <= D / 2 + 1e-6:
                    a_, b_ = (y, CHORD_Z + .07), (y2, roof_line(y2, D) - TC_H / 2)
                else:
                    a_, b_ = (y, roof_line(y, D) - TC_H / 2), (y2, CHORD_Z + .07)
                _beam(stage, T + f'_Diag{j}', (x, a_[0], a_[1]), (x, b_[0], b_[1]), .06, .06, m['steel'])
    # Purlins along x, seated on the top chords (underside = top-chord top), ridge pair either side.
    ys_p = [ya + (D / 2 - .3 - ya) * k / 8 for k in range(9)]
    purl_y = sorted(set([round(v, 4) for v in ys_p] + [round(D - v, 4) for v in ys_p]))
    angle = math.degrees(math.atan(tan))
    # The Z section's flanges follow the pitch. Its lower flange bears on the
    # top chord and its upper flange sits just below the sheet contact plane.
    for k, y in enumerate(purl_y):
        rot = angle if y < D / 2 else -angle
        sin_pitch, cos_pitch = math.sin(math.radians(rot)), math.cos(math.radians(rot))
        z = deck_underside(y, D) - PURLIN_H / (2 * cos_pitch) - .0008
        flange_t = .006
        flange_z = (PURLIN_H - flange_t) / 2
        section = (
            ("Web", 0, 0, .006, PURLIN_H - 2 * flange_t),
            ("Seat", -.036, -flange_z, .078, flange_t),
            ("Cap", .036, flange_z, .078, flange_t),
        )
        for name, dy, dz, width, height in section:
            center = (W / 2, y + dy * cos_pitch - dz * sin_pitch,
                      z + dy * sin_pitch + dz * cos_pitch)
            box(stage, R + f'Purlins/P{k:02d}/{name}', center,
                (W + 2 * WALL_T, width, height), m['purlin'], rotation=(rot, 0, 0))
    # Decking: two pitched sheets whose underside lies on the purlin tops (no framing pokes through).
    half = (D / 2 + WALL_T + .25) / math.cos(math.radians(angle))
    for side, yc0, rot in (('S', -WALL_T - .25, angle), ('N', D + WALL_T + .25, -angle)):
        mid_y = (yc0 + D / 2) / 2
        z_mid = deck_underside(mid_y, D) + DECK_T / 2 / math.cos(math.radians(angle))   # roof_line extends past the walls
        box(stage, R + f'Decking/Roof{side}', (W / 2, mid_y, z_mid), (W + 2 * WALL_T + .5, half, DECK_T), m['deck'], rotation=(rot, 0, 0))
    for side, y, rot in (('S', D / 2 - .12, angle), ('N', D / 2 + .12, -angle)):
        # Folded flashing laps both sheets across the ridge seam.
        center_z = deck_underside(y, D) + (DECK_T + .002) / math.cos(math.radians(rot))
        box(stage, R + f'Decking/RidgeFlashing{side}', (W / 2, y, center_z),
            (W + 2 * WALL_T + .5, .246, .006), m['deck'], rotation=(rot, 0, 0))
    for name, y in (('South', .45), ('North', D - .45)):
        box(stage, H + 'CableTray' + name, (W / 2, y, 3.6), (W - .6, .25, .1), m['purlin'])

    # High-bay lights: one row over each robot route line, between truss lines (no clashes).
    lights, ys = [], sorted({round(v[1], 3) for k, v in layout['nodes'].items() if k.startswith('N') and 1 < v[1] < D - 1})
    edges = [0.0] + xs + [W]
    xs_l = [round((a + b) / 2, 3) for a, b in zip(edges, edges[1:])]
    for r, y in enumerate(ys):
        for c, x in enumerate(xs_l):
            name = f'HB_R{r}_C{c}'
            top = roof_line(y, D) + TC_H / 2          # hang from the purlin line above (purlin underside)
            cylinder(stage, R + f'Fixtures/{name}_Rod', (x, y, (FIXTURE_Z + .17 + top) / 2), .012, top - FIXTURE_Z - .17, m['steel'])
            cylinder(stage, R + f'Fixtures/{name}_Body', (x, y, FIXTURE_Z + .09), .26, .16, m['lamp_body'], segments=32)
            cylinder(stage, R + f'Fixtures/{name}_Face', (x, y, FIXTURE_Z), .22, .02, m['lamp_face'], segments=32)
            light = UsdLux.DiskLight.Define(stage, f'/World/Hall/Lights/{name}')
            light.CreateRadiusAttr(.22)
            # v2 accepted ~110-130/255 floor at ISO400 f2.8 1/60 with 8 x 0.63 m2 RectLights @10000
            # over 240 m2 at 4.8 m. 42 x 0.152 m2 disks over 480 m2 at 5.55 m was ~20000.
            light.CreateIntensityAttr(40000.0)   # mount raised 5.55 -> 7.8 m: ~(7.8/5.55)^2 x 20000
            light.CreateEnableColorTemperatureAttr(False)
            light.CreateColorAttr(Gf.Vec3f(1, 1, 1))
            UsdGeom.Xformable(light).AddTranslateOp().Set(Gf.Vec3d(x, y, FIXTURE_Z - .015))
            # Uplight component (~10 % of output, typical of open high-bay reflectors) so the
            # trusses and decking read in Isaac's real-time RTX mode, which has little bounce light.
            up = UsdLux.DiskLight.Define(stage, f'/World/Hall/Lights/{name}_Up')
            up.CreateRadiusAttr(.22)
            up.CreateIntensityAttr(4000.0)
            up.CreateEnableColorTemperatureAttr(False)
            up.CreateColorAttr(Gf.Vec3f(1, 1, 1))
            uxf = UsdGeom.Xformable(up)
            uxf.AddTranslateOp().Set(Gf.Vec3d(x, y, FIXTURE_Z + .2))
            uxf.AddRotateXOp().Set(180.0)
            lights.append(name)
    ambient = UsdLux.DomeLight.Define(stage, '/World/Hall/Lights/Ambient')
    ambient.CreateIntensityAttr(150)
    UsdLux.ShadowAPI.Apply(ambient.GetPrim()).CreateShadowEnableAttr(False)

    # Roller shutters in the framed end-wall openings (closed state; the curtain carries the collider).
    gates = {}
    for end, x0, n in (('West', 0.0, 1), ('East', W, -1)):
        G = H + end + 'Gate/'
        UsdGeom.Xform.Define(stage, H + end + 'Gate')
        box(stage, G + 'Curtain', (x0 - n * WALL_T / 2, D / 2, GATE_H / 2), (.05, GATE_W + .1, GATE_H), m['shutter'], collision=True)
        box(stage, G + 'BottomRail', (x0 - n * (WALL_T / 2 - .03), D / 2, .04), (.08, GATE_W + .1, .08), m['steel'])
        for side, yy in (('L', D / 2 - GATE_W / 2 - .06), ('R', D / 2 + GATE_W / 2 + .06)):
            box(stage, G + f'Guide{side}', (x0 - n * WALL_T / 2, yy, (GATE_H + .5) / 2), (.12, .12, GATE_H + .5), m['steel'], collision=True)
            for k in range(6):  # yellow/black impact-protection bollards inside each guide
                box(stage, G + f'Bollard{side}{k}', (x0 + n * .45, yy + (-.3 if side == 'L' else .3), .1 + k * .2), (.18, .18, .2),
                    m['yellow' if k % 2 == 0 else 'black'], collision=(k == 0))
        box(stage, G + 'HeadBox', (x0 - n * WALL_T / 2, D / 2, GATE_H + .29), (.5, GATE_W + .5, .6), m['steel'])
        box(stage, G + 'Threshold', (x0 - n * .02, D / 2, .004), (WALL_T + .3, GATE_W, .008), m['steel'])
        gates[end] = {'opening_y': [round(D / 2 - GATE_W / 2, 3), round(D / 2 + GATE_W / 2, 3)], 'clear_height': GATE_H, 'state': 'closed',
                      'collider': G + 'Curtain'}
    box(stage, H + 'PersonnelDoor', (.045, 2.6, 1.1), (.08, 1.0, 2.2), m['door'])
    box(stage, H + 'DoorWindow', (.09, 2.6, 1.62), (.02, .42, .52), m['glass'])
    box(stage, H + 'FirePoint', (.13, 11.0, 1.35), (.16, .8, 1.05), m['red'])
    cylinder(stage, H + 'Extinguisher', (.3, 11.7, .45), .11, .62, m['red'])
    # Area gamma monitors with amber beacons on the long walls, CCTV in two corners.
    for name, y, n in (('South', .2, 1), ('North', D - .2, -1)):
        for k, x in enumerate((7.5, 22.5), 1):
            box(stage, H + f'GammaMonitor{name}{k}', (x, y, 1.95), (.38, .22, .42), m['monitor'])
            cylinder(stage, H + f'GammaBeacon{name}{k}', (x, y + .05 * n, 2.26), .06, .14, m['amber'])
    for k, (c, d) in enumerate((((.3, .5, 4.8), 1), ((W - .3, D - .5, 4.8), -1)), 1):
        box(stage, H + f'CCTV{k}Body', c, (.4, .2, .18), m['monitor'])
        cylinder(stage, H + f'CCTV{k}Lens', (c[0] + .23 * d, c[1], c[2]), .065, .08, m['glass'], rotation=(0, 90, 0))
    # Overhead travelling crane over the ILW bank (zone B): ILW packages are crane-handled.
    crane = {}
    b_racks = [r for r in layout.get('racks', []) if r.get('zone') == 'B']
    if b_racks:
        x0 = min(r['center'][0] for r in b_racks) - 1.2
        x1 = max(r['center'][0] for r in b_racks) + 1.2
        x1 = W - .7                               # runway reaches the east receipt bay
        rail_z, girder_z = RUNWAY_Z, RUNWAY_Z + .475   # runway 6.4-6.8, girder 6.78-7.33
        C = '/World/Hall/Roof/Crane/'
        UsdGeom.Xform.Define(stage, '/World/Hall/Roof/Crane')
        for side, y in (('S', .62), ('N', D - .62)):
            box(stage, C + f'Runway{side}', ((x0 + x1) / 2, y, rail_z), (x1 - x0, .30, .40), m['steel'])
            box(stage, C + f'Rail{side}', ((x0 + x1) / 2, y, rail_z + .23), (x1 - x0, .06, .06), m['steel'])
            for k, x in enumerate([c for c in xs if x0 - .1 <= c <= x1 + .1]):
                cy = .27 if side == 'S' else D - .27
                box(stage, C + f'Corbel{side}{k}', (x, (y + cy) / 2, rail_z - .3), (.3, abs(y - cy) + .1, .2), m['steel'])
        bx = 18.0 if x0 < 18.0 < x1 else (x0 + x1) / 2
        for k, dx in enumerate((-.45, .45)):
            box(stage, C + f'Girder{k}', (bx + dx, D / 2, girder_z + .065), (.35, D - 1.0, .55), m['yellow'])
        for side, y in (('S', .62), ('N', D - .62)):
            box(stage, C + f'EndCarriage{side}', (bx, y, rail_z + .43), (1.9, .45, .35), m['yellow'])
        hook_y = D / 2
        box(stage, C + 'Trolley', (bx, hook_y, girder_z + .52), (1.3, 1.0, .35), m['yellow'])
        box(stage, C + 'Hoist', (bx, hook_y, girder_z - .35), (.6, .7, .45), m['yellow'])
        rope_top, hook_top = girder_z - .58, 5.95
        for k, dy in enumerate((-.08, .08)):
            cylinder(stage, C + f'Rope{k}', (bx, hook_y + dy, (rope_top + hook_top) / 2), .012, rope_top - hook_top, m['steel'])
        box(stage, C + 'HookBlock', (bx, hook_y, hook_top - .15), (.32, .22, .30), m['yellow'])
        crane = {'span_x': [round(x0, 2), round(x1, 2)], 'parked_x': round(bx, 2), 'hook_bottom_z': round(hook_top - .3, 3),
                 'trolley_top_z': round(girder_z + .695, 3), 'girder_top_z': round(girder_z + .34, 3)}

    # Zone and radiation signage (v2 sign artwork), facing into the hall on both long walls.
    import textures
    from materials import material
    textures.ASSETS = assets
    signs = {k: material(stage, 'V3Sign_' + k, (1, 1, 1), .6, textures=textures.sign(n, lines, trefoil=True))
             for k, n, lines in (('llw', 'v3_zone_llw', ['LLW', 'STORE - ZONE A']),
                                 ('ilw', 'v3_zone_ilw', ['ILW', 'STORE - ZONE B']),
                                 ('rad', 'v3_radiation', ['CAUTION', 'RADIATION', 'CONTROLLED AREA']))}
    for zone, key in (('A', 'llw'), ('B', 'ilw')):
        zr = [r['center'][0] for r in layout.get('racks', []) if r.get('zone') == zone]
        if not zr:
            continue
        x = (min(zr) + max(zr)) / 2
        panel(stage, H + f'ZoneSign{zone}South', (x, .015, 3.2), 1.1, 1.1, (0, 1, 0), signs[key])
        panel(stage, H + f'ZoneSign{zone}North', (x, D - .015, 3.2), 1.1, 1.1, (0, -1, 0), signs[key])
    for end, x, n in (('West', .015, (1, 0, 0)), ('East', W - .015, (-1, 0, 0))):
        panel(stage, H + f'RadSign{end}', (x, D / 2 - 2.9, 2.0), .6, .6, n, signs['rad'])

    return {'crane': crane, 'hall_interior_m': [W, D], 'gates': gates, 'eave_deck_underside_z': round(deck_underside(0, D), 3), 'truss_bottom_chord_z': CHORD_Z,
            'ridge_deck_top_z': round(deck_underside(D / 2, D) + DECK_T, 3), 'pitch_deg': PITCH_DEG, 'fixture_face_z': FIXTURE_Z,
            'portal_frames': len(xs), 'high_bay_lights': len(lights), 'roof_prim': '/World/Hall/Roof',
            'columns_xy': [[x, y] for x in xs for y in (.27, D - .27)], 'light_xy': [[x, y] for y in ys for x in xs_l]}
