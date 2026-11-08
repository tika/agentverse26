"""Execute after warehouse_routes.py on a warehouse warm worker."""
if warehouse_map is None:
    raise RuntimeError("Start the warehouse worker with HOT_WAREHOUSE=1")
package = "A-L-01-T1"
target = inspection_targets(warehouse_map)[package]
route = route_from_spawn(warehouse_map, target["stop"])
result = walk(route, name="warehouse_walk", max_s=20.0, speed=0.4)
(OUT / "walk_summary.json").write_text(json.dumps({
    "package": package,
    "route": route,
    "navigation_source": "simulator_pose",
    **result,
}, indent=2))
if not result["reached"]:
    raise RuntimeError("Spot did not reach the first aisle stop")
