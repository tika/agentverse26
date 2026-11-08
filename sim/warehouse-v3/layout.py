"""Generate deterministic v3 navigation and storage metadata from the v2 inventory."""
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "baseline"))
from drums import make_inventory
from stacking import load_config, stack_inventory

WIDTH, DEPTH, HEIGHT = 24, 20, 10
RACK_SIZE = 1.34
ROBOT_RADIUS = 0.40
ROW_Y = (2.5, 5.5, 8.5, 11.5, 14.5, 17.5)
ROUTE_Y = (1.3, 4, 7, 10, 13, 16, 18.7)
COLUMN_X = (3.1, 4.55, 6, 7.45, 8.9, 15.1, 16.55, 18, 19.45, 20.9)


def generate():
    config = load_config(ROOT / "baseline/stacking.json")
    old = stack_inventory(make_inventory(), config)
    old_y = {row["y"]: y for row, y in zip(config["rows"], ROW_Y)}
    old_x = dict(zip([x for zone in config["zones"] for x in zone["pallet_x"]], COLUMN_X))
    deck_pitch = config["pallet"]["height_m"]
    drums = []
    racks = {}
    for original in old:
        drum = dict(original)
        px, py = original["pallet_xy"]
        x, y = old_x[px], old_y[py]
        rack = racks.setdefault(drum["stack_id"], {
            "id": drum["stack_id"], "zone": drum["zone"], "category": drum["category"],
            "center": [x, y], "size": RACK_SIZE,
            "deck_tops": [round(deck_pitch + i * (deck_pitch + drum["height"]), 4)
                          for i in range(3)],
        })
        drum.update(v2_xyz=[drum["x"], drum["y"], drum["base_z"]],
                    x=round(x + drum["x"] - px, 4), y=round(y + drum["y"] - py, 4),
                    visible_face=True,
                    face_sign=drum["face_sign"] if drum["location"]["depth"] == 1 else -drum["face_sign"],
                    pallet_xy=rack["center"], location={**drum["location"], "tier_count": 3})
        drums.append(drum)
    existing_codes = {drum["display_id"] for drum in old}
    next_id = max(int(drum["id"][1:]) for drum in drums) + 1
    for drum in drums[:]:
        if drum["location"]["tier"] != 2:
            continue
        if drum["display_id"].replace("-T2", "-T3") in existing_codes:
            continue
        name = f"D{next_id:02d}"
        next_id += 1
        code = drum["display_id"].replace("-T2", "-T3")
        z = racks[drum["stack_id"]]["deck_tops"][2]
        drums.append(dict(drum, id=name, display_id=code, prim_path=f"/World/Drums/{name}",
                          v2_xyz=None, base_z=z, location={**drum["location"], "tier": 3,
                                                           "location_code": code, "base_z_m": z}))
    for drum in drums:
        row = ROW_Y.index(drum["pallet_xy"][1])
        drum["inspection_route_y"] = ROUTE_Y[row + (drum["face_sign"] > 0)]
    xs = (1.5, WIDTH/2, WIDTH-1.5)
    ys = ROUTE_Y
    nodes = {f"N{i}_{j}": [x, y] for i, x in enumerate(xs) for j, y in enumerate(ys)}
    edges = [[f"N{i}_{j}", f"N{i+1}_{j}"] for i in range(2) for j in range(len(ys))]
    edges += [[f"N{i}_{j}", f"N{i}_{j+1}"] for i in range(3) for j in range(len(ys)-1)]
    nodes.update(spawn=[1, 6], front_spawn_link=[1.5, 6])
    edges += [["spawn", "front_spawn_link"], ["front_spawn_link", "N0_1"], ["front_spawn_link", "N0_2"]]
    legacy_routes = json.loads((ROOT / "baseline/aisles.json").read_text())
    old_cross = (1.25, 10, 18.75)
    legacy_nodes = {}
    for node in legacy_routes["nodes"]:
        x = node["x"]
        section = 0 if x <= 10 else 1
        left = old_cross[section]
        fraction = min(1, max(0, (x-left)/(old_cross[section+1]-left)))
        legacy_nodes[node["id"]] = [
            round(xs[section] + fraction*(xs[section+1]-xs[section]), 4),
            ys[2 * node["aisle"] - 1],
        ]
    return {
        "schema_version": 1, "units": "metres", "up_axis": "Z",
        "baseline_revision": "50abf76e4bb7df2d885602ed35097fc7e2b706a0",
        "seed": 42, "hall": [WIDTH, DEPTH, HEIGHT], "robot_start": [1, 6, 0],
        "zones": {"A": "LLW", "B": "ILW"}, "racks": list(racks.values()), "drums": drums,
        "nodes": nodes, "edges": edges, "v2_node_positions_in_v3": legacy_nodes,
        "staging_bounds": [[0, 0, WIDTH, 0.75], [0, DEPTH-.75, WIDTH, DEPTH]],
    }


def validate(layout):
    racks = {rack["id"]: rack for rack in layout["racks"]}
    columns = defaultdict(list)
    seen = set()
    for drum in layout["drums"]:
        assert drum["id"] not in seen
        seen.add(drum["id"])
        rack = racks[drum["stack_id"]]
        tier = drum["location"]["tier"]
        assert drum["category"] == layout["zones"][drum["zone"]] == rack["category"]
        assert drum["base_z"] == rack["deck_tops"][tier - 1]
        for coordinate, center in zip((drum["x"], drum["y"]), rack["center"]):
            assert abs(coordinate - center) + drum["shape"]["max_radius"] <= rack["size"] / 2
        columns[(drum["stack_id"], drum["x"], drum["y"])].append(tier)
    assert all(sorted(tiers) == [1, 2, 3] for tiers in columns.values())
    old = stack_inventory(make_inventory(), load_config(ROOT / "baseline/stacking.json"))
    assert {d["id"]: (d["category"], d["display_id"]) for d in old} == {
        d["id"]: (d["category"], d["display_id"]) for d in layout["drums"] if d["v2_xyz"] is not None
    }
    assert WIDTH * DEPTH == 2 * 20 * 12
    boxes = []
    for rack in racks.values():
        x, y = rack["center"]
        half = rack["size"] / 2
        boxes.append([x-half, y-half, x+half, y+half])
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        assert 0 < x1 < x2 < WIDTH and 0 < y1 < y2 < DEPTH
        assert all(x2 <= a or c <= x1 or y2 <= b or d <= y1 for a, b, c, d in boxes[i+1:])
    boxes += layout["staging_bounds"]
    minimum = math.inf
    reachable = {"spawn"}
    while True:
        expanded = reachable | {v for a, b in layout["edges"] if a in reachable or b in reachable for v in (a, b)}
        if expanded == reachable:
            break
        reachable = expanded
    assert reachable == layout["nodes"].keys()
    for start, end in layout["edges"]:
        ax, ay = layout["nodes"][start]
        bx, by = layout["nodes"][end]
        assert ax == bx or ay == by
        minimum = min(minimum, ax, ay, bx, by, WIDTH-ax, WIDTH-bx, DEPTH-ay, DEPTH-by)
        for x1, y1, x2, y2 in boxes:
            dx = max(x1 - max(ax, bx), min(ax, bx) - x2, 0)
            dy = max(y1 - max(ay, by), min(ay, by) - y2, 0)
            minimum = min(minimum, math.hypot(dx, dy))
    assert minimum >= ROBOT_RADIUS
    through_widths = [ROW_Y[i+1] - ROW_Y[i] - RACK_SIZE for i in range(len(ROW_Y)-1)]
    assert min(through_widths) >= 1.4
    for rack_id, rack in racks.items():
        rows = {y for key, _, y in columns if key == rack_id}
        assert len(rows) <= 2
        for drum in (d for d in layout["drums"] if d["stack_id"] == rack_id):
            assert (drum["inspection_route_y"] - drum["y"]) * drum["face_sign"] > RACK_SIZE / 2
            if len(rows) == 2:
                expected_side = -1 if drum["y"] < rack["center"][1] else 1
                assert drum["face_sign"] == expected_side
    assert all(drum["visible_face"] for drum in layout["drums"])
    return {
        "floor_area_m2": [240, WIDTH * DEPTH],
        "v2_drums": dict(Counter(drum["category"] for drum in old)),
        "v3_drums": dict(Counter(drum["category"] for drum in layout["drums"])),
        "racks": len(racks), "three_high_columns": len(columns),
        "route_edges": len(layout["edges"]), "route_clearance_m": round(minimum, 3),
        "route_check_radius_m": ROBOT_RADIUS,
        "maximum_bank_depth_drum_rows": 2,
        "aisle_facing_drums": len(layout["drums"]),
        "through_aisle_widths_m": [round(width, 3) for width in through_widths],
    }


if __name__ == "__main__":
    layout = generate()
    report = validate(layout)
    (ROOT / "map.json").write_text(json.dumps(layout, indent=2) + "\n")
    (ROOT / "map-checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
