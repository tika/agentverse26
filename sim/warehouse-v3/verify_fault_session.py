"""OpenUSD regression check for seeded and fresh session overlays."""
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

from drum_faults import DEFAULT_MAP, DEFAULT_STAGE, generate_session


def verify():
    layout = json.loads(DEFAULT_MAP.read_text())
    by_id = {d["id"]: d for d in layout["drums"]}
    base = Usd.Stage.Open(str(DEFAULT_STAGE))
    with TemporaryDirectory() as folder:
        root = Path(folder)

        def launch(name, seed=None):
            truth = root / f"{name}.json"
            path = generate_session(root / name / "warehouse.usda", seed=seed, manifest=truth)
            return path, json.loads(truth.read_text())

        path, truth = launch("reference", 42)
        replay, repeated = launch("replay", 42)
        assert truth == repeated
        inventory = truth["physical_inventory"]["drums"]
        assert {d["drum_id"] for d in inventory} == set(by_id)
        assert all(d["appearance"] for d in inventory if any(d["visual_plan"].values()))
        assert all(not d.get("appearance") for d in inventory if not any(d["visual_plan"].values()))
        assert all(term not in path.read_text() for term in ("activity_bq", "gauge_pressure_kpa", "headspace_m3"))
        original_textures = sorted(path.parent.glob("*_textures/*.png"))
        replay_textures = sorted(replay.parent.glob("*_textures/*.png"))
        assert len(original_textures) == len(replay_textures)
        assert all(a.read_bytes() == b.read_bytes() for a, b in zip(original_textures, replay_textures))
        assert path.read_bytes() == replay.read_bytes()
        _, fresh_a = launch("fresh-a")
        _, fresh_b = launch("fresh-b")
        assert fresh_a["seed"] != fresh_b["seed"]
        assert {e["drum_id"] for e in fresh_a["drums"]} != {e["drum_id"] for e in fresh_b["drums"]}
        affected = {e["drum_id"]: e for e in truth["drums"]}
        assert 0 < len(affected) < len(by_id)
        stage = Usd.Stage.Open(str(path))
        assert not UsdUtils.ComputeAllDependencies(Sdf.AssetPath(str(path)))[2]
        assert stage.GetPrimAtPath("/World/RobotSpawn").GetAttribute("xformOp:translate").Get() == (1, 6, 0)
        assert {p.GetName() for p in stage.GetPrimAtPath("/World/Drums").GetChildren()} == set(by_id)
        before_cache, after_cache = UsdGeom.XformCache(), UsdGeom.XformCache()
        bounds = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_], False, True)
        for drum_id, drum in by_id.items():
            before, after = (s.GetPrimAtPath(drum["prim_path"]) for s in (base, stage))
            assert before_cache.GetLocalToWorldTransform(before) == after_cache.GetLocalToWorldTransform(after)
            assert before.GetAttribute("warehouse:locationCode").Get() == after.GetAttribute("warehouse:locationCode").Get()
            entry = affected.get(drum_id, {})
            body = stage.GetPrimAtPath(drum["prim_path"] + "/Body")
            material, _ = UsdShade.MaterialBindingAPI(body).ComputeBoundMaterial()
            if "corrosion" in entry:
                assert str(material.GetPath()).startswith("/World/SessionMaterials/")
                surface = material.GetSurfaceOutput().GetConnectedSource()[0]
                for name in ("diffuseColor", "roughness", "metallic", "normal"):
                    assert UsdShade.Shader(surface.GetPrim()).GetInput(name).HasConnectedSource()
            if "bulging" in entry:
                proxy = stage.GetPrimAtPath("/World/Racks/" + drum["stack_id"].replace("-", "_") + "/Collision")
                box = bounds.ComputeWorldBound(proxy).ComputeAlignedRange()
                transform = after_cache.GetLocalToWorldTransform(body)
                assert 0 < entry["bulging"]["peak_radial_displacement_mm"] < 60
                assert .39 < entry["bulging"]["peak_height_fraction"] < .61
                for vertex in UsdGeom.Mesh(body).GetPointsAttr().Get():
                    assert math.hypot(vertex[0], vertex[1]) < (.309 if drum["category"] == "LLW" else .50)
                    world = transform.Transform(Gf.Vec3d(*vertex))
                    assert all(a - 1e-5 <= p <= b + 1e-5 for p, a, b in zip(world, box.GetMin(), box.GetMax()))
        print(json.dumps({"drums": len(by_id), "affected_seed_42": len(affected),
                          "same_seed_replay": True, "fresh_draws_differ": True,
                          "all_assets_resolved": True, "bulges_contained_in_static_proxies": True}))


if __name__ == "__main__":
    verify()
