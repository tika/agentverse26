"""Checks on the composed v3 stage (pure pxr; usd-core or Isaac python).

    python sim/v3/checks_v3.py --stage ../warehouse-v3.usda --map ../map.json --out ../checks/stage-checks.json

Checks: stage conventions; interior floor area vs v2; drum inventory, IDs and categories;
three-high columns; colliders; geometric route clearance against every authored mesh below
robot height (columns, bollards, racks, drums, props), not only the declared envelopes;
staging props stay inside staging bounds; semantic labels; shell repeatability.
"""
import argparse
import hashlib
import json
import math
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
ROBOT_RADIUS = 0.40
ROBOT_HEIGHT = 1.10   # Spot standing body + payload; geometry above this cannot hit the base


def _segment_box_distance(a, b, box):
    """Min distance in XY between segment ab and an axis-aligned rectangle (sampled, 2 cm)."""
    x1, y1, x2, y2 = box
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / .02))
    best = math.inf
    for i in range(n + 1):
        t = i / n
        px, py = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        dx = max(x1 - px, 0, px - x2)
        dy = max(y1 - py, 0, py - y2)
        best = min(best, math.hypot(dx, dy))
    return best


def run(stage_path, map_path, seed=42):
    from pxr import Usd, UsdGeom, UsdPhysics
    layout = json.loads(Path(map_path).read_text())
    W, D, H = layout['hall']
    stage = Usd.Stage.Open(str(stage_path))
    out, fails = {}, []

    def check(name, ok, detail):
        out[name] = {'pass': bool(ok), 'detail': detail}
        if not ok:
            fails.append(name)

    check('stage_conventions', UsdGeom.GetStageMetersPerUnit(stage) == 1.0 and UsdGeom.GetStageUpAxis(stage) == 'Z'
          and stage.GetDefaultPrim().GetPath() == '/World',
          {'metersPerUnit': UsdGeom.GetStageMetersPerUnit(stage), 'upAxis': UsdGeom.GetStageUpAxis(stage),
           'defaultPrim': str(stage.GetDefaultPrim().GetPath())})

    bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default', 'render'])
    def bounds(prim):
        r = bbox.ComputeWorldBound(prim).ComputeAlignedRange()
        return [tuple(r.GetMin()), tuple(r.GetMax())]

    # Interior floor area measured from the wall meshes' inner faces.
    walls = {n: bounds(stage.GetPrimAtPath(f'/World/Hall/Structure/{n}')) for n in ('WallSouth', 'WallNorth', 'WallFront', 'WallBack')
             if stage.GetPrimAtPath(f'/World/Hall/Structure/{n}')}
    if len(walls) == 4:
        ix = walls['WallBack'][0][0] - walls['WallFront'][1][0]
        iy = walls['WallNorth'][0][1] - walls['WallSouth'][1][1]
        area = ix * iy
    else:
        ix = iy = area = None
    check('floor_area', area is not None and area >= 2 * 240 - 1e-6,
          {'v2_m2': 240.0, 'v3_m2': round(area, 3) if area else None, 'ratio': round(area / 240, 3) if area else None,
           'interior_m': [round(ix, 3), round(iy, 3)] if area else None, 'measured_from': 'wall inner faces in composed stage'})

    # Drum inventory, identities and stacks (stage vs map vs v2 baseline).
    drums_root = stage.GetPrimAtPath('/World/Drums')
    stage_ids = sorted(p.GetName() for p in drums_root.GetChildren()) if drums_root else []
    map_ids = sorted(d['id'] for d in layout['drums'])
    sys.path.insert(0, str(Path(map_path).resolve().parent / 'baseline'))
    try:
        from drums import make_inventory
        from stacking import load_config, stack_inventory
        v2 = stack_inventory(make_inventory(), load_config(Path(map_path).resolve().parent / 'baseline' / 'stacking.json'))
        v2_ids = {d['id']: (d['category'], d['display_id']) for d in v2}
    except Exception as exc:  # pragma: no cover - reported, not fatal
        v2_ids = {}
        out['v2_baseline_error'] = repr(exc)
    v3_by_id = {d['id']: d for d in layout['drums']}
    lost = [i for i in v2_ids if i not in v3_by_id]
    changed = [i for i, (cat, code) in v2_ids.items() if i in v3_by_id and v3_by_id[i]['category'] != cat]
    check('drum_inventory', stage_ids == map_ids and not lost and not changed and len(v2_ids) == 360,
          {'stage_drums': len(stage_ids), 'map_drums': len(map_ids), 'v2_drums': len(v2_ids),
           'v2_ids_missing_in_v3': lost[:10], 'v2_category_changed': changed[:10],
           'v3_by_category': dict(Counter(d['category'] for d in layout['drums'])),
           'v2_by_category': dict(Counter(c for c, _ in v2_ids.values())),
           'by_zone': dict(Counter((d['zone'], d['category']) for d in layout['drums']).items().__iter__()) if False else
                      {f"{z}:{c}": n for (z, c), n in Counter((d['zone'], d['category']) for d in layout['drums']).items()}})
    cache = UsdGeom.XformCache()
    pose_err = 0.0
    for d in layout['drums']:
        p = stage.GetPrimAtPath(d['prim_path'])
        if p:
            t = cache.GetLocalToWorldTransform(p).ExtractTranslation()
            pose_err = max(pose_err, abs(t[0] - d['x']), abs(t[1] - d['y']), abs(t[2] - d['base_z']))
    check('drum_poses_match_map', pose_err < 1e-3, {'max_abs_error_m': round(pose_err, 6)})
    columns = defaultdict(list)
    for d in layout['drums']:
        columns[(d['stack_id'], round(d['x'], 3), round(d['y'], 3))].append(d['location']['tier'])
    not3 = [k for k, v in columns.items() if sorted(v) != [1, 2, 3]]
    racks = Counter(d['stack_id'] for d in layout['drums'])
    check('three_high', not not3, {'drum_columns': len(columns), 'columns_not_exactly_1_2_3': len(not3),
                                   'stacks': len(racks), 'stack_sizes': dict(Counter(racks.values()))})
    # Vertical sanity: drums in a column do not interpenetrate (base_z + height <= next base_z).
    overlap = 0
    by_col = defaultdict(list)
    for d in layout['drums']:
        by_col[(d['stack_id'], round(d['x'], 3), round(d['y'], 3))].append(d)
    for col in by_col.values():
        col.sort(key=lambda d: d['base_z'])
        overlap += sum(1 for a, b in zip(col, col[1:]) if a['base_z'] + a['height'] > b['base_z'] + 1e-6)
    tallest = max(d['base_z'] + d['height'] for d in layout['drums'])
    chord = bounds(stage.GetPrimAtPath('/World/Hall/Roof/Trusses'))[0][2] if stage.GetPrimAtPath('/World/Hall/Roof/Trusses') else None
    lowest_light = min((bounds(p)[0][2] for p in stage.Traverse() if p.GetPath().pathString.startswith('/World/Hall/Roof/Fixtures/HB')), default=None)
    check('vertical_clearance', overlap == 0 and chord and lowest_light and tallest < lowest_light - .5,
          {'stacked_drum_overlaps': overlap, 'tallest_stack_top_m': round(tallest, 3),
           'truss_bottom_m': round(chord, 3) if chord else None, 'lowest_fixture_m': round(lowest_light, 3) if lowest_light else None})

    # Colliders.
    def has_collider(root):
        prim = stage.GetPrimAtPath(root)
        return bool(prim) and any(p.HasAPI(UsdPhysics.CollisionAPI) for p in Usd.PrimRange(prim))
    # Static map: drums are covered by collidable rack proxies (one per stack) instead of 420
    # overlapping shapes; per-drum contact/dynamics are outside this static map.
    rack_paths = [p for p in (stage.GetPrimAtPath('/World/Racks').GetChildren() if stage.GetPrimAtPath('/World/Racks') else [])]
    proxies = [bounds(c) for r in rack_paths for c in Usd.PrimRange(r) if c.HasAPI(UsdPhysics.CollisionAPI)]
    TOL = 0.05
    overhang = [0.0]
    def covered(d):
        if has_collider(d['prim_path']):
            return True
        # Exact extent from transformed mesh vertices (a yawed AABB re-boxed over-reports ~6 cm).
        pts = []
        for m in Usd.PrimRange(stage.GetPrimAtPath(d['prim_path']), Usd.TraverseInstanceProxies()):
            if m.IsA(UsdGeom.Mesh):
                xf = UsdGeom.Xformable(m).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
                pts += [xf.Transform(v) for v in (UsdGeom.Mesh(m).GetPointsAttr().Get() or [])]
        if not pts:
            return False
        x0, y0, z0 = (min(v[i] for v in pts) for i in range(3))
        x1, y1, z1 = (max(v[i] for v in pts) for i in range(3))
        best = min((max(a[0] - x0, a[1] - y0, a[2] - z0, x1 - b[0], y1 - b[1], z1 - b[2], 0.0) for a, b in proxies), default=9.0)
        overhang[0] = max(overhang[0], best)
        return best <= TOL
    no_col = [d['id'] for d in layout['drums'] if stage.GetPrimAtPath(d['prim_path']) and not covered(d)]
    out_overhang = round(overhang[0], 3)
    check('colliders', not no_col and has_collider('/World/Hall/Structure/Floor') and all(has_collider(f'/World/Hall/Structure/{n}') for n in walls)
          and all(has_collider(str(p.GetPath())) for p in rack_paths),
          {'drums_not_covered_by_own_or_rack_proxy_collider': len(no_col), 'examples': no_col[:5], 'max_overhang_beyond_rack_proxy_m': out_overhang, 'tolerance_m': 0.05, 'floor': has_collider('/World/Hall/Structure/Floor'),
           'walls': {n: has_collider(f'/World/Hall/Structure/{n}') for n in walls},
           'rack_prims': len(rack_paths), 'racks_without_collider': [p.GetName() for p in rack_paths if not has_collider(str(p.GetPath()))][:10]})

    # Geometric route clearance: every mesh whose world bounds start below robot height.
    obstacles = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh) or not UsdGeom.Imageable(prim).ComputeVisibility() == 'inherited':
            continue
        path = prim.GetPath().pathString
        if path.startswith('/World/Hall/Structure/Floor'):
            continue
        (x0, y0, z0), (x1, y1, z1) = bounds(prim)
        if z0 > ROBOT_HEIGHT or z1 < 0.02:   # overhead parts and floor paint/markings
            continue
        obstacles.append((path, (x0, y0, x1, y1)))
    nodes = layout['nodes']
    worst = (math.inf, None, None)
    per_edge = []
    for a, b in layout['edges']:
        pa, pb = nodes[a], nodes[b]
        near = [(o, _segment_box_distance(pa, pb, box)) for o, box in obstacles
                if box[0] - 1 < max(pa[0], pb[0]) and box[2] + 1 > min(pa[0], pb[0])
                and box[1] - 1 < max(pa[1], pb[1]) and box[3] + 1 > min(pa[1], pb[1])]
        d, o = min(((dist, o) for o, dist in near), default=(math.inf, None))
        per_edge.append({'edge': [a, b], 'clearance_m': round(d, 3), 'nearest': o})
        if d < worst[0]:
            worst = (d, [a, b], o)
    tight = [e for e in per_edge if e['clearance_m'] < ROBOT_RADIUS]
    check('route_clearance_geometric', not tight,
          {'robot_radius_m': ROBOT_RADIUS, 'robot_height_m': ROBOT_HEIGHT, 'obstacle_meshes': len(obstacles),
           'min_clearance_m': round(worst[0], 3), 'worst_edge': worst[1], 'worst_obstacle': worst[2],
           'edges_below_radius': tight[:10], 'edges': len(per_edge)})
    # Spawn: free disc of robot radius at robot_start.
    sx, sy = layout['robot_start'][:2]
    spawn_d = min((math.hypot(max(b[0] - sx, 0, sx - b[2]), max(b[1] - sy, 0, sy - b[3])), o) for o, b in obstacles)
    check('spawn_clear', spawn_d[0] >= ROBOT_RADIUS, {'spawn': layout['robot_start'], 'nearest_m': round(spawn_d[0], 3), 'nearest': spawn_d[1]})

    # Props inside staging bounds (anything under a Staging scope).
    staging = layout.get('staging_bounds', [])
    outside = []
    for o, box in obstacles:
        if '/Staging/' in o:
            if not any(box[0] >= s[0] - 1e-6 and box[1] >= s[1] - 1e-6 and box[2] <= s[2] + 1e-6 and box[3] <= s[3] + 1e-6 for s in staging):
                outside.append(o)
    check('staging_props_in_bounds', not outside, {'staging_bounds': staging, 'props_outside': outside[:10]})

    # Semantic labels (v2 perception contract: class + drum_id taxonomies).
    labelled = 0
    for d in layout['drums']:
        p = stage.GetPrimAtPath(d['prim_path'])
        if p and any(a.GetName().startswith(('semantics:labels:', 'semantic:')) for a in p.GetAttributes()):
            labelled += 1
    out['semantic_labels'] = {'pass': None, 'detail': {'drums_with_labels_authored': labelled,
                              'note': 'v2 applies labels at runtime in Isaac (labels.label_scene); authored labels optional'}}

    # Roof framing: no framing, fixture or crane vertex above the decking underside; decking sheets
    # actually lie on that plane; vertical clearances between stacks, crane, fixtures and chords.
    import shell as shell_mod
    def world_pts(prim):
        xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        return [xf.Transform(v) for v in (UsdGeom.Mesh(prim).GetPointsAttr().Get() or [])]
    poke, worst = [], -9.0
    for root in ('/World/Hall/Roof/Trusses', '/World/Hall/Roof/Purlins', '/World/Hall/Roof/Fixtures', '/World/Hall/Roof/Crane', '/World/Hall/Structure'):
        r = stage.GetPrimAtPath(root)
        if not r:
            continue
        for p in Usd.PrimRange(r):
            if not p.IsA(UsdGeom.Mesh) or '/Wall' in p.GetPath().pathString or 'Plinth' in p.GetName() or p.GetName() == 'Floor':
                continue
            over = max((v[2] - shell_mod.deck_underside(v[1], D) for v in world_pts(p)), default=-9)
            worst = max(worst, over)
            if over > .003:
                poke.append([p.GetPath().pathString, round(over, 3)])
    deck_err = 0.0
    for side in ('S', 'N'):
        p = stage.GetPrimAtPath(f'/World/Hall/Roof/Decking/Roof{side}')
        if p:
            pts = world_pts(p)
            lows = sorted(pts, key=lambda v: v[2] - shell_mod.deck_underside(v[1], D))[:4]
            deck_err = max(deck_err, max(abs(v[2] - shell_mod.deck_underside(v[1], D)) for v in lows))
    def zr(path, lo=True):
        p = stage.GetPrimAtPath(path)
        return round(bounds(p)[0 if lo else 1][2], 3) if p else None
    clear = {'stack_top': round(tallest, 3), 'hook_bottom': zr('/World/Hall/Roof/Crane/HookBlock'),
             'girder_top': zr('/World/Hall/Roof/Crane/Girder0', False), 'trolley_top': zr('/World/Hall/Roof/Crane/Trolley', False),
             'fixture_face_bottom': lowest_light, 'chord_underside': zr('/World/Hall/Roof/Trusses/T00_Bottom'),
             'eave_deck_underside': round(shell_mod.deck_underside(0, D), 3), 'ridge_deck_underside': round(shell_mod.deck_underside(D / 2, D), 3)}
    ok_clear = all(v is not None for v in clear.values()) and clear['hook_bottom'] - clear['stack_top'] >= .3 \
        and clear['fixture_face_bottom'] - clear['trolley_top'] >= .1 and clear['chord_underside'] - clear['trolley_top'] >= .1
    check('roof_framing', not poke and deck_err < .005 and ok_clear,
          {'members_above_deck_underside': poke[:10], 'max_vertex_above_deck_underside_m': round(worst, 4),
           'deck_sheet_underside_error_m': round(deck_err, 4), 'vertical_clearances_m': clear})
    # End-wall gates: framed opening, curtain collider spans the opening (closed state).
    gate_detail, gate_ok = {}, True
    for end, wall in (('West', 'Front'), ('East', 'Back')):
        cur = stage.GetPrimAtPath(f'/World/Hall/Details/{end}Gate/Curtain')
        segs = [stage.GetPrimAtPath(f'/World/Hall/Structure/Wall{wall}{s_}') for s_ in ('', 'R', 'Lintel')]
        if not cur or not all(segs):
            gate_ok = False; gate_detail[end] = 'missing'; continue
        (cx0, cy0, cz0), (cx1, cy1, cz1) = bounds(cur)
        left, right, lintel = (bounds(p_) for p_ in segs)
        gap = [left[1][1], right[0][1], lintel[0][2]]
        covered = cy0 <= gap[0] + 1e-3 and cy1 >= gap[1] - 1e-3 and cz0 <= .001 and cz1 >= gap[2] - 1e-3
        coll = cur.HasAPI(UsdPhysics.CollisionAPI) and all(p_.HasAPI(UsdPhysics.CollisionAPI) for p_ in segs)
        gate_ok &= covered and coll
        gate_detail[end] = {'opening_y': [round(gap[0], 3), round(gap[1], 3)], 'opening_height': round(gap[2], 3),
                            'curtain_covers_opening': covered, 'curtain_and_wall_colliders': coll, 'state': 'closed'}
    check('end_gates', gate_ok, gate_detail)

    # Repeatability: two fresh shell builds are byte-identical.
    from build_shell import build
    digests = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            build(map_path, Path(tmp) / 'shell.usda', seed)
            digests.append(hashlib.sha256((Path(tmp) / 'shell.usda').read_bytes()).hexdigest()
                           + ':' + ':'.join(hashlib.sha256(f.read_bytes()).hexdigest()[:12] for f in sorted((Path(tmp) / 'assets').iterdir())))
    check('shell_repeatable', digests[0] == digests[1], {'runs': 2, 'sha256': digests[0][:24]})
    out['summary'] = {'pass': not fails, 'failed': fails, 'stage': str(stage_path), 'map': str(map_path)}
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True)
    parser.add_argument('--map', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    result = run(args.stage, args.map)
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + '\n')
    print(json.dumps(result['summary']))
    for k, v in result.items():
        if k != 'summary' and isinstance(v, dict) and 'pass' in v:
            print(f"{k:28s} {v['pass']}  {json.dumps(v['detail'])[:220]}")
