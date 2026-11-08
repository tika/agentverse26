"""Read the public geometry needed by the warehouse inspection mission."""
import argparse
import json
import math
from heapq import heappop, heappush
from pathlib import Path



def inspection_targets(layout):
    """Whitelist map fields; randomized condition and simulator IDs stay private."""
    return {
        drum["display_id"]: {
            "category": drum["category"],
            "tier": drum["location"]["tier"],
            "centre": [drum["x"], drum["y"], drum["base_z"] + drum["height"] / 2],
            "stop": [drum["x"], drum["inspection_route_y"]],
            "yaw": math.copysign(math.pi / 2, drum["y"] - drum["inspection_route_y"]),
        }
        for drum in layout["drums"]
    }


def route_from_spawn(layout, stop):
    """Route along authored edges, splitting the aisle edge at the scan stop."""
    nodes = {name: tuple(xy) for name, xy in layout["nodes"].items()}
    goal = tuple(stop)
    edges = list(layout["edges"])
    destination = next((name for name, xy in nodes.items() if xy == goal), None)
    if destination is None:
        destination = "inspection_stop"
        for index, (left, right) in enumerate(edges):
            a, b = nodes[left], nodes[right]
            if a[1] == b[1] == goal[1] and min(a[0], b[0]) < goal[0] < max(a[0], b[0]):
                edges[index:index + 1] = [(left, destination), (destination, right)]
                nodes[destination] = goal
                break
        else:
            raise ValueError(f"No aisle edge contains {goal}")
    graph = {name: [] for name in nodes}
    for left, right in edges:
        graph[left].append(right)
        graph[right].append(left)
    queue = [(0.0, ("spawn",))]
    visited = set()
    while queue:
        distance, path = heappop(queue)
        node = path[-1]
        if node in visited:
            continue
        if node == destination:
            return [nodes[name] for name in path]
        visited.add(node)
        for neighbor in graph[node]:
            if neighbor not in visited:
                cost = math.dist(nodes[node], nodes[neighbor])
                heappush(queue, (distance + cost, (*path, neighbor)))
    raise ValueError(f"No route from spawn to {goal}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="Printed package ID, e.g. A-L-01-T1")
    args = parser.parse_args()
    map_path = Path(__file__).resolve().parents[2] / "sim/warehouse-v3/map.json"
    layout = json.loads(map_path.read_text())
    targets = inspection_targets(layout)
    if args.package not in targets:
        parser.error(f"Unknown package {args.package}")
    target = targets[args.package]
    print(json.dumps({"package": args.package, **target,
                      "route": route_from_spawn(layout, target["stop"])}, indent=2))
