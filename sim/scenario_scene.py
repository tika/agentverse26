"""Apply a scenario's visible defects to an already built hall and drum inventory."""
import json
import math
from pathlib import Path


def apply_visual_scenario(stage, scenario, inventory_path=None):
    """Build only runtime-visible geometry; hidden faults stay in scenario['truth']."""
    from pxr import Gf, UsdGeom
    from drums import INVENTORY

    entries = json.loads(Path(inventory_path or INVENTORY).read_text())
    by_id = {entry['id']: entry for entry in entries}
    asset_id = scenario.get('asset_id')
    entry = by_id.get(asset_id)
    if not entry and scenario.get('runtime', {}).get('defects'):
        raise KeyError(f"scenario asset {asset_id!r} is absent from the current inventory")
    result = {'scenario_id': scenario['scenario_id'], 'visible_defects': [], 'measured_shape': {},
              'obstructions': [], 'truth_exposed': False}

    if entry:
        from defects import build_corrosion, build_release
        from isaacsim.core.experimental.utils.semantics import add_labels
        for idx, defect in enumerate(scenario['runtime'].get('defects', [])):
            kind = defect['kind']
            if float(defect.get('visible_fraction', 0.0)) <= 0:
                continue
            if kind == 'corrosion':
                built = build_corrosion(stage, entry, int(scenario['seed']) + idx*991,
                                        int(defect.get('severity', 2)))
                for mesh in built:
                    add_labels(stage.GetPrimAtPath(mesh['prim_path']), labels=['corrosion'], taxonomy='class')
                    add_labels(stage.GetPrimAtPath(mesh['prim_path']), labels=[entry['id']], taxonomy='drum_id')
                    result['visible_defects'].append(mesh)
            elif kind in ('bulge', 'dent'):
                magnitude = float(defect['dimensions_m'][-1])
                vertical_extent = float(defect['dimensions_m'][0])
                angular_extent = float(defect['dimensions_m'][1])
                body = UsdGeom.Mesh.Get(stage, entry['prim_path'] + '/Body')
                if not body:
                    raise RuntimeError(f"missing body mesh for {entry['id']}")
                points_attr = body.GetPointsAttr()
                points = points_attr.Get()
                theta_center = float(defect.get('angle_rad', entry.get('yaw', 0.0)))
                z_center = float(defect.get('center_z_m', entry['height']*.42))
                deformed = []
                max_delta = 0.0
                for point in points:
                    x, y, z = float(point[0]), float(point[1]), float(point[2])
                    radius = math.hypot(x, y)
                    theta = math.atan2(y, x)
                    da = math.atan2(math.sin(theta-theta_center), math.cos(theta-theta_center))
                    vertical = math.exp(-.5*((z-z_center)/max(vertical_extent*.42,.015))**2)
                    if kind == 'bulge':
                        # Broad circumferential expansion with a smooth measured profile.
                        scale = magnitude * vertical
                    else:
                        # A local inward dent, with its extent defined as arc length in metres.
                        arc_extent = max(angular_extent, .015)
                        lateral = math.exp(-.5*((da*max(radius,.01))/(arc_extent*.42))**2)
                        scale = -magnitude * vertical * lateral
                    new_radius = radius + scale
                    max_delta = max(max_delta, abs(scale))
                    deformed.append(Gf.Vec3f(x*new_radius/max(radius, 1e-6),
                                              y*new_radius/max(radius, 1e-6), z))
                points_attr.Set(deformed)
                observed_delta = (2*max_delta if kind == 'bulge' else -2*max_delta)
                result['measured_shape'][entry['id']] = {'kind': kind,
                    'observed_diameter_change_m': round(observed_delta, 5),
                    'nominal_diameter_m': round(2*float(entry['radius']), 5),
                    'measurement_source': 'scene mesh geometry'}
                result['visible_defects'].append({'kind': kind, 'asset_id': entry['id'],
                    'region': defect.get('surface_region'), 'visible_fraction': defect.get('visible_fraction'),
                    'dimensions_m': defect['dimensions_m']})
            else:
                raise ValueError(f'unsupported visible defect kind: {kind}')

        wet = scenario['runtime'].get('wet_case')
        if wet:
            # A visible wet patch is evidence of moisture only. The mechanism is
            # recorded in the scenario; it never changes dose or proves contamination.
            source = wet.get('location_m', [entry['x'], entry['y']-entry['radius']-.45, .002])
            from geometry import mesh
            from materials import material
            from fault_textures import release_maps
            import numpy as np
            from defect_geometry import floor_mesh
            bank = release_maps(entry['category'], True, entry['scene_seed'])
            paint = material(stage, 'ScenarioWet_'+scenario['scenario_id'], (1,1,1), .08, textures=bank)
            center = (float(source[0]), float(source[1]))
            wet_mesh = mesh(stage, f"/World/Defects/{entry['id']}/Wet_{scenario['scenario_id']}",
                            *floor_mesh(np.random.default_rng(int(scenario['seed'])), center, .42, .68, z=.003), paint)
            result['visible_defects'].append({'kind':'wet_surface','prim_path':str(wet_mesh.GetPath()),
                                               'mechanism':wet['mechanism'],'fluid_kind':wet['fluid_kind']})

    obstruction = scenario['runtime'].get('obstruction')
    if obstruction:
        from geometry import box
        from materials import material
        geom = obstruction['geometry_m']
        center, size = geom['center'], geom['size']
        paint = material(stage, 'ScenarioObstruction', (.27,.29,.28), .86)
        prim = box(stage, '/World/Obstructions/Scenario_'+scenario['scenario_id'], center, size, paint, collision=True)
        result['obstructions'].append({'path':str(prim.GetPath()), 'route_id':obstruction['route_id'],
                                       'geometry_m':geom})
    return result
