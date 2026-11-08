"""Check the composed USD stage using OpenUSD and the declared map."""
from collections import defaultdict
import json
import math
from pathlib import Path
import sys

from pxr import Usd, UsdGeom, UsdPhysics, UsdShade

from storage import PRINT_CENTER

ROOT = Path(__file__).resolve().parent


def verify(path):
    layout = json.loads((ROOT / "map.json").read_text())
    stage = Usd.Stage.Open(str(path))
    assert stage.GetDefaultPrim().GetPath().pathString == "/World"
    assert UsdGeom.GetStageUpAxis(stage) == "Z"
    assert UsdGeom.GetStageMetersPerUnit(stage) == 1
    group = stage.GetPrimAtPath("/World/Drums")
    assert {prim.GetName() for prim in group.GetChildren()} == {d["id"] for d in layout["drums"]}
    stacks = defaultdict(list)
    banks = defaultdict(set)
    for drum in layout["drums"]:
        stacks[drum["stack_id"], drum["x"], drum["y"]].append(drum["location"]["tier"])
        banks[drum["zone"], drum["pallet_xy"][1]].add(drum["y"])
        assert drum["face_sign"] * (drum["inspection_route_y"] - drum["y"]) > 0
        prim = stage.GetPrimAtPath(drum["prim_path"])
        assert prim.IsInstance()
        body = stage.GetPrimAtPath(f'{drum["prim_path"]}/Body')
        assert body.IsA(UsdGeom.Mesh)
        material, _ = UsdShade.MaterialBindingAPI(body).ComputeBoundMaterial()
        assert material.GetPrim().GetName() == drum["id"]
        texture = material.GetPrim().GetChild("Print").GetAttribute("inputs:file").Get()
        assert texture.resolvedPath and Path(texture.resolvedPath).is_file()
        assert UsdGeom.PrimvarsAPI(body).GetPrimvar("st").HasValue()
        assert prim.GetAttribute("warehouse:zone").Get() == drum["zone"]
        assert prim.GetAttribute("warehouse:locationCode").Get() == drum["display_id"]
        assert math.isclose(prim.GetAttribute("xformOp:rotateZ").Get(),
                            math.degrees(drum["yaw"]), abs_tol=1e-4)
        actual = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
        assert all(math.isclose(a, b, abs_tol=1e-5)
                   for a, b in zip(actual, (drum["x"], drum["y"], drum["base_z"])))
    assert all(sorted(tiers) == [1, 2, 3] for tiers in stacks.values())
    max_depth = max(map(len, banks.values()))
    assert max_depth <= 2
    spawn = UsdGeom.Xformable(stage.GetPrimAtPath("/World/RobotSpawn"))
    spawn_xyz = spawn.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
    assert list(spawn_xyz) == layout["robot_start"]
    expected_labels = {d["id"] for d in layout["drums"] if d["visible_face"]}
    assert not stage.GetPrimAtPath("/World/DrumLabels")
    for drum in layout["drums"]:
        z = drum["base_z"] + PRINT_CENTER[drum["category"]] * drum["height"]
        low_y, high_y = sorted((drum["y"], drum["inspection_route_y"]))
        for other in layout["drums"]:
            if other is drum or not other["base_z"] <= z <= other["base_z"] + other["height"]:
                continue
            dx = abs(drum["x"] - other["x"])
            dy = max(low_y - other["y"], other["y"] - high_y, 0)
            assert math.hypot(dx, dy) >= other["shape"]["max_radius"], (drum["id"], other["id"])
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"], False, True)
    colliders = []
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.CollisionAPI) and UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():
            bounds = cache.ComputeWorldBound(prim).ComputeAlignedRange()
            if bounds.GetMax()[2] > .001 and bounds.GetMin()[2] < 1.10:
                colliders.append((prim.GetPath().pathString, bounds.GetMin(), bounds.GetMax()))
    assert sum(path.startswith("/World/Racks/") for path, *_ in colliders) == len(layout["racks"])
    for rack in layout["racks"]:
        path = '/World/Racks/' + rack["id"].replace("-", "_")
        for i, z in enumerate(rack["deck_tops"], 1):
            deck = stage.GetPrimAtPath(f"{path}/Deck{i}")
            bounds = cache.ComputeWorldBound(deck).ComputeAlignedRange()
            assert math.isclose(bounds.GetMax()[2], z, abs_tol=1e-6)
    minimum = (math.inf, None, None)
    for a, b in layout["edges"]:
        ax, ay = layout["nodes"][a]
        bx, by = layout["nodes"][b]
        for path, low, high in colliders:
            dx = max(low[0] - max(ax, bx), min(ax, bx) - high[0], 0)
            dy = max(low[1] - max(ay, by), min(ay, by) - high[1], 0)
            distance = math.hypot(dx, dy)
            if distance < minimum[0]:
                minimum = (distance, path, [a, b])
    assert minimum[0] >= .40, minimum
    roof = stage.GetPrimAtPath("/World/Hall/Roof")
    assert roof
    assert UsdGeom.Imageable(roof).ComputeVisibility() == "inherited"
    return {
        "spawn_xyz_m": list(spawn_xyz),
        "drum_prims_and_poses": len(layout["drums"]),
        "inspection_lines_clear_of_other_drums": len(expected_labels),
        "body_print_materials": len(expected_labels),
        "three_high_columns": len(stacks),
        "maximum_bank_depth_drum_rows": max_depth,
        "rack_deck_heights": 3*len(layout["racks"]),
        "route_height_colliders": len(colliders),
        "minimum_route_clearance_m": round(minimum[0], 3),
        "limiting_collider": minimum[1],
        "limiting_route_edge": minimum[2],
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "warehouse-v3.usda"), indent=2))
