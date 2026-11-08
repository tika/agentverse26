"""Build the four-condition warehouse asset sampler inside a copied scene tree."""
from collections import Counter
import json
from pathlib import Path

import numpy as np
from pxr import Usd

from drum_faults import DEFAULT_MAP, DEFAULT_STAGE, generate_session
from warehouse_physics import generate_inventory


def main():
    layout = json.loads(DEFAULT_MAP.read_text())
    seed = 20261108
    rng = np.random.default_rng(seed)
    inventory = generate_inventory(layout, seed)
    records = {drum["drum_id"]: drum for drum in inventory["drums"]}
    for record in records.values():
        record["visual_plan"].update(corrosion_severity=0, bulging_severity=0)
    conditions = ("normal", "bulge_only", "corrosion_only", "bulge_and_corrosion")
    catalog = []
    for category in ("LLW", "ILW"):
        for tier in (1, 2, 3):
            candidates = [drum for drum in layout["drums"]
                          if drum["category"] == category and drum["location"]["tier"] == tier]
            for condition, index in zip(conditions, rng.permutation(len(candidates))[:4]):
                drum = candidates[index]
                rust = round(float(rng.uniform(.35, .95)), 3) if "corrosion" in condition else 0
                bulge = round(float(rng.uniform(.35, .95)), 3) if "bulge" in condition else 0
                records[drum["id"]]["visual_plan"].update(
                    corrosion_severity=rust, bulging_severity=bulge)
                catalog.append({
                    "package_id": drum["display_id"], "category": category, "tier": tier,
                    "prim_path": drum["prim_path"], "condition": condition,
                    "corrosion_severity": rust, "bulging_severity": bulge,
                    "inspection_stop_xy": [drum["x"], drum["inspection_route_y"]],
                })
    output = DEFAULT_STAGE.with_name("CANIS_YOLO_FOUR_CONDITION.usda")
    generate_session(output, seed=seed, inventory=inventory)
    stage = Usd.Stage.Open(str(output))
    stage.GetRootLayer().subLayerPaths = ["./" + DEFAULT_STAGE.name]
    stage.GetRootLayer().Save()
    assert Counter(entry["condition"] for entry in catalog) == dict.fromkeys(conditions, 6)
    output.with_name("sample_catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")


if __name__ == "__main__":
    main()
