"""Multi-seed calibration and paired sensor controls. Outputs evaluator-only evidence."""
import argparse
import json
from pathlib import Path
import statistics

import numpy as np

from drum_faults import DEFAULT_MAP
from warehouse_physics import generate_inventory, gas_state
from warehouse_sensors import WarehouseSensors


def _scenario(records, category, name):
    return next(d for d in records if d["category"] == category and d["scenario"] == name)


def _swab(sensor, xy, time_s, *, outward=0):
    point = [*xy, 0.0]
    robot = [xy[0], xy[1] + .55 * outward, .55] if outward else [xy[0] + .35, xy[1], .55]
    start = sensor.start_swab(point, time_s, robot_xyz=robot, robot_stopped=True)
    assert sensor.poll_swab(time_s + 1)["status"] == "sampling"
    return sensor.poll_swab(start["ready_at_s"])


def check(seed):
    layout = json.loads(DEFAULT_MAP.read_text())
    inventory = generate_inventory(layout, seed)
    assert inventory == generate_inventory(layout, seed)
    records = inventory["drums"]
    assert len(records) == len({d["drum_id"] for d in records}) == 420
    assert {d["drum_id"] for d in records} == {d["id"] for d in layout["drums"]}
    sensor = WarehouseSensors(inventory)
    results = {"seed": seed, "categories": {}}
    for category in ("LLW", "ILW"):
        group = [d for d in records if d["category"] == category]
        for d in group:
            per_kg_alpha = d["activity_bq"]["alpha_equivalent"] / d["net_mass_kg"]
            per_kg_beta = sum(v for k, v in d["activity_bq"].items() if k != "alpha_equivalent") / d["net_mass_kg"]
            below = per_kg_alpha <= 4e6 and per_kg_beta <= 12e6
            assert below == (category == "LLW")
            assert d["gas"]["h2_emission_mol_s"] >= 0
            assert 0 <= d["gas"]["h2_headspace_ppm"] <= 1e6
            assert d["gas"]["gauge_pressure_kpa"] >= 0
        rust = _scenario(records, category, "exterior_corrosion")
        ordinary = _scenario(records, category, "ordinary")
        transfer = _scenario(records, category, "transfer")
        restriction = _scenario(records, category, "restricted_vent")
        venting = _scenario(records, category, "warm_venting")
        warm = _scenario(records, category, "warm_no_release")
        quiet_bulge = _scenario(records, category, "residual_deformation" if category == "LLW" else "solid_expansion")
        outlier = _scenario(records, category, "gamma_outlier")
        assert rust["visual_plan"]["corrosion_severity"] > 0 and not rust["containment"]["patches"]
        assert not transfer["visual_plan"]["corrosion_severity"] and not transfer["containment"]["breached"]
        assert quiet_bulge["visual_plan"]["bulging_severity"] > 0 and quiet_bulge["thermal"]["chemical_heat_w"] == 0
        assert warm["thermal"]["chemical_heat_w"] > 0 and warm["gas"]["pulse_h2_mol_s"] == 0
        assert restriction["gas"]["gauge_pressure_kpa"] > venting["gas"]["gauge_pressure_kpa"]
        assert not any(outlier["visual_plan"].values())
        reference = "isolated_aisle_face_1m_usv_h"
        assert outlier["radiation"][reference] > max(d["radiation"][reference] for d in group if d is not outlier)
        source = venting["gas"]
        # A ventilated field is read at a point, with a sensor pose and time,
        # rather than by querying a package's internal gas state.
        near = np.array(source["vent_xyz_m"]) + [.45, .14, .05]
        far = np.array(source["vent_xyz_m"]) + [-4, -4, 0]
        assert sensor._gas_ppm(near, 40) > sensor._gas_ppm(far, 40)
        assert sensor._gas_ppm(near, 40) > inventory["sensor_config"]["gas_detection_ppm"]
        assert sensor._gas_ppm(near, 0) < sensor._gas_ppm(near, 40)
        assert gas_state(source, 40)["h2_headspace_ppm"] != sensor._gas_ppm(near, 40)
        gas_probe = WarehouseSensors(inventory)
        gas_trace = [gas_probe.sample(near, t) for t in (0, 2, 8, 40, 90)]
        assert gas_trace[0]["hydrogen_status"] == "below_detection"
        assert gas_trace[3]["hydrogen_status"] == "detected"
        assert gas_trace[-1]["hydrogen_status"] == "below_detection"
        x, y, _ = source["vent_xyz_m"]
        aisle = (x + .70, y + .83 * venting["face_sign"], 1.0)
        clearance = min(float(np.linalg.norm(np.maximum(
            np.abs(np.asarray(aisle[:2]) - rack["center"]) - rack["size"] / 2, 0)))
            for rack in layout["racks"])
        assert clearance >= .4
        aisle_sensor = WarehouseSensors(inventory)
        aisle_sensor.sample((aisle[0], aisle[1], .55), 0, gas_xyz=aisle)
        aisle_observation = aisle_sensor.sample((aisle[0], aisle[1], .55), 40, gas_xyz=aisle)
        pos = []
        for d in (warm, ordinary):
            x, y, z = d["xyz_m"]
            pos.append([x, y + d["face_sign"] * d["radius_m"], z + .58 * d["height_m"]])
        ids = [[warm["drum_id"], ordinary["drum_id"]]]
        frame = sensor.thermal_frame([pos], ids)
        assert frame[0, 0] > frame[0, 1] + .5
        # Isaac may lowercase label values. Verify the camera adapter uses
        # the physical record rather than silently rendering room temperature.
        transform = np.eye(4)
        transform[3, :3] = np.asarray(pos[0]) + [0, 0, 1]
        intrinsics = np.array([[200, 0, 1], [0, 200, 1], [0, 0, 1]])
        seg = {"data": np.ones((2, 2)), "info": {"idToLabels": {
            "1": {"class": "drum", "drum_id": warm["drum_id"].lower()}}}}
        image = sensor.thermal_from_camera(np.ones((2, 2)), seg, intrinsics, transform)
        assert image.mean() > warm["thermal"]["ambient_c"] + 1.0
        clean_swab = _swab(sensor, [1.0, 1.0], 0)
        patch = transfer["containment"]["patches"][0]
        positive = _swab(sensor, patch["xyz_m"][:2], 20, outward=transfer["face_sign"])
        assert clean_swab["alpha_status"] == "below_detection"
        assert positive["alpha_status"] == "detected"
        assert positive["beta_gamma_status"] == "detected"
        median = lambda extract: statistics.median(extract(d) for d in group)
        results["categories"][category] = {
            "drums": len(group),
            "median_decay_heat_w": median(lambda d: d["thermal"]["decay_heat_w"]),
            "median_reference_gamma_usv_h": median(lambda d: d["radiation"]["isolated_aisle_face_1m_usv_h"]),
            "median_headspace_l": median(lambda d: 1000 * d["gas"]["headspace_m3"]),
            "restricted_pressure_kpa": restriction["gas"]["gauge_pressure_kpa"],
            "vented_pressure_kpa": venting["gas"]["gauge_pressure_kpa"],
            "gas_pulse_near_ppm": sensor._gas_ppm(near, 40),
            "gas_pulse_far_ppm": sensor._gas_ppm(far, 40),
            "gas_inlet_trace": [{k: row[k] for k in ("time_s", "hydrogen_ppm", "hydrogen_status")}
                                for row in gas_trace],
            "aisle_gas_probe": {"inlet_xyz_m": aisle, "rack_clearance_m": clearance,
                                "hydrogen_ppm": aisle_observation["hydrogen_ppm"],
                                "status": aisle_observation["hydrogen_status"]},
            "warm_vs_ordinary_apparent_c": frame[0].tolist(),
            "clean_swab": clean_swab,
            "transfer_swab": positive,
        }
    trace = [{"pose_xyz_m": [x, y, .60], **sensor.sample((x, y, .60), index * 2)}
             for index, (x, y) in enumerate(layout["nodes"].values())]
    rates = [entry["dose_rate_uSv_h"] for entry in trace]
    assert all(np.isfinite(rates)) and max(rates) < 15  # synthetic reference field, not an alarm
    assert all(b["mission_dose_mSv"] >= a["mission_dose_mSv"] for a, b in zip(trace, trace[1:]))
    assert all(not ({"drum_id", "scenario", "headspace", "activity_bq", "category"} & entry.keys())
               for entry in trace)
    results["route_gamma_usv_h"] = {"min": min(rates), "median": statistics.median(rates), "max": max(rates)}
    results["route_trace"] = trace
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = {"runs": [check(seed) for seed in (42, 2026, 3858)]}
    for category in ("LLW", "ILW"):
        assert any(run["categories"][category]["aisle_gas_probe"]["status"] == "detected"
                   for run in report["runs"])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
    for run in report["runs"]:
        print(run["seed"], run["route_gamma_usv_h"])
