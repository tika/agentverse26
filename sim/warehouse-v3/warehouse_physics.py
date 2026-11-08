"""Private synthetic package inventory for the 420-drum warehouse."""
import json
import math
from pathlib import Path

import numpy as np

CONFIG_PATH = Path(__file__).with_name("physical_config.json")
SECONDS_PER_DAY = 86400
MOLAR_VOLUME_L = 22.414  # STP, 273.15 K and 101325 Pa
GAS_R = 8.314462618
PA_PER_KPA = 1000
MEV_J = 1.602176634e-13

# Rounded free-air effective coefficients for synthetic gamma calibration,
# µSv/h at 1 m per MBq. This is a dose proxy, not a dosimeter response library.
GAMMA_COEFFICIENT = {"Cs137": .08, "Co60": .35}
DEPOSITED_MEV = {"Cs137": .75, "Co60": 2.60, "alpha_equivalent": 5.5, "beta_equivalent": .55}


def load_config():
    return json.loads(CONFIG_PATH.read_text())


def _log_sample(rng, bounds):
    return float(np.exp(rng.uniform(*np.log(bounds))))


def gas_state(gas, elapsed_s):
    """Two first-order balances, for H2 exchange and total excess gas."""
    days = gas["elapsed_before_launch_days"] + elapsed_s / SECONDS_PER_DAY
    generation = gas["h2_ml_stp_day"] / (1000 * MOLAR_VOLUME_L)

    def retained(rate):
        if not rate:
            return generation * days
        return generation * -math.expm1(-rate * days) / rate

    excess = retained(gas["pressure_relaxation_per_day"])
    hydrogen = min(retained(gas["h2_exchange_per_day"]), gas["initial_air_mol"] + excess)
    pressure = excess * GAS_R * gas["temperature_k"] / gas["headspace_m3"]
    return {
        "h2_headspace_ppm": 1e6 * hydrogen / (gas["initial_air_mol"] + excess),
        "gauge_pressure_kpa": pressure / PA_PER_KPA,
        "h2_emission_mol_s": gas["h2_exchange_per_day"] * hydrogen / SECONDS_PER_DAY,
    }


def _drum_record(drum, profile, case, rust, bulge, rng):
    llw = drum["category"] == "LLW"
    mass = float(rng.uniform(*profile["net_mass_kg"]))
    gamma = _log_sample(rng, profile["gamma_activity_mbq"])
    alpha = _log_sample(rng, profile["alpha_activity_mbq"])
    beta = _log_sample(rng, profile["beta_activity_mbq"])
    cobalt = float(rng.uniform(*profile["cobalt_fraction"]))
    if case == "gamma_outlier":
        gamma = 1.4 * profile["gamma_activity_mbq"][1]
        cobalt = profile["cobalt_fraction"][1]
    activity = {"Cs137": gamma * (1 - cobalt) * 1e6, "Co60": gamma * cobalt * 1e6,
                "alpha_equivalent": alpha * 1e6, "beta_equivalent": beta * 1e6}
    decay = sum(activity[k] * energy * MEV_J for k, energy in DEPOSITED_MEV.items())
    # Avoid counting all escaping photon energy as package heat.
    decay *= .64 if llw else .92
    chemical = float(rng.uniform(6, 13)) if case in {"warm_venting", "warm_no_release"} else 0.0
    ambient = profile["ambient_c"] + float(rng.normal(0, .25))
    emissivity = float(np.clip(rng.normal(profile["emissivity"], .045), .25, .95))
    sign = drum["face_sign"]
    h = drum["height"]
    radius = drum["radius"]
    volume = (.208 if llw else .500) * float(rng.uniform(*profile["free_volume_fraction"]))
    temperature_k = 273.15 + ambient + decay / 2.0 + chemical * .30
    vent = profile["nominal_vent"]
    h2 = float(rng.uniform(*profile["baseline_h2_ml_day"]))
    elapsed_days = float(rng.uniform(10, 90))
    if case in {"warm_venting", "cool_venting", "restricted_vent"}:
        h2 = float(rng.uniform(*profile["reactive_h2_ml_day"]))
        vent = "restricted" if case == "restricted_vent" else "open_release"
        # A short, localized release pulse is explicit and independent of the
        # normal day-scale generation rate.
        elapsed_days = float(rng.uniform(45, 160))
    exchange, relaxation = {
        "sealed": (0.0, 0.0), "filtered": (.4, 3.0),
        "restricted": (.002, .004), "open_release": (1.2, 3.0),
    }[vent]
    gas = {
        "headspace_m3": volume, "vent_state": vent, "temperature_k": temperature_k,
        "h2_ml_stp_day": h2, "methane_ml_stp_day": 0.0,
        "h2_exchange_per_day": exchange, "pressure_relaxation_per_day": relaxation,
        "elapsed_before_launch_days": elapsed_days,
        "initial_air_mol": 101325 * volume / (GAS_R * temperature_k),
        "vent_xyz_m": [drum["x"], drum["y"] + sign * radius * .7, drum["base_z"] + h - .03],
        "pulse_h2_mol_s": .000055 if case in {"warm_venting", "cool_venting"} else 0.0,
        "pulse_duration_s": 60.0 if case in {"warm_venting", "cool_venting"} else 0.0,
    }
    # The optional pulse is a finite, separate release of retained gas.
    # Store the required inventory so the evaluator can verify mass balance.
    gas["pulse_reservoir_mol"] = gas["pulse_h2_mol_s"] * gas["pulse_duration_s"]
    area = 2 * math.pi * radius * (h + radius)
    surface_delta = (decay + chemical * .24) / (7.0 * area)
    hot_delta = chemical * .76 / (7.0 * .23)
    contamination = {"breached": case == "breach", "patches": []}
    if case in {"breach", "transfer"}:
        # Transfer can contaminate a reachable floor patch without a breach.
        contamination["patches"].append({
            "xyz_m": [drum["x"], drum["y"] + sign * (radius + .08), 0.0],
            "radius_m": .14,
            "alpha_bq_cm2": float(rng.uniform(.16, .95)),
            "beta_gamma_bq_cm2": float(rng.uniform(1.0, 7.0)),
        })
    mu = float(rng.uniform(*profile["effective_attenuation_m_inv"]))
    if case == "gamma_outlier":
        mu = profile["effective_attenuation_m_inv"][0]
    gamma_strength = sum(activity[k] / 1e6 * coeff for k, coeff in GAMMA_COEFFICIENT.items())
    initial_gas = gas_state(gas, 0)
    reference_radius = 1 + radius
    reference = 0.0
    for fraction in (.28, .50, .72):
        length = math.hypot(reference_radius, (.5 - fraction) * h)
        reference += gamma_strength * math.exp(-mu * radius * length / reference_radius) / (3 * length ** 2)
    return {
        "drum_id": drum["id"], "prim_path": drum["prim_path"], "category": drum["category"],
        "xyz_m": [drum["x"], drum["y"], drum["base_z"]], "radius_m": radius,
        "height_m": h, "face_sign": sign, "yaw_rad": drum["yaw"],
        "waste_form": str(rng.choice(profile["waste_forms"])), "net_mass_kg": mass,
        "fill_fraction": 1 - volume / (.208 if llw else .500),
        "age_years": float(rng.uniform(1, 24)),
        "activity_bq": activity, "scenario": case,
        "exterior": {"exposure": ("coating_loss_and_periodic_wetting" if llw else
                                  "crevice_deposits_and_periodic_wetting") if rust else "no_visible_attack",
                     "attack_index": rust},
        "visual_plan": {"corrosion_severity": rust,
                        "bulging_severity": min(.95, .25 + .10 * initial_gas["gauge_pressure_kpa"])
                        if case == "restricted_vent" else bulge},
        "radiation": {"unshielded_strength_usv_h_m2": gamma_strength,
                      "effective_attenuation_m_inv": mu,
                      "isolated_aisle_face_1m_usv_h": reference},
        "thermal": {"decay_heat_w": decay, "chemical_heat_w": chemical,
                    "ambient_c": ambient, "relative_humidity_pct": profile["relative_humidity_pct"],
                    "shell_c": ambient + surface_delta, "internal_c": temperature_k - 273.15,
                    "vent_c": ambient + .7 * (temperature_k - 273.15 - ambient),
                    "hotspot_delta_c": hot_delta, "emissivity": emissivity},
        "gas": {**gas, **initial_gas},
        "containment": contamination,
    }


def generate_inventory(layout, seed):
    """Sample causes and materials first, then supply appearance inputs."""
    config = load_config()
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0x574850]))
    records = []
    for category, profile in config["profiles"].items():
        drums = [d for d in layout["drums"] if d["category"] == category]
        ordered = rng.permutation(len(drums))
        n_rust = round(len(drums) * rng.uniform(*profile["corrosion_fraction"]))
        n_bulge = round(len(drums) * rng.uniform(*profile["bulge_fraction"]))
        ground = {i for i, d in enumerate(drums) if d["location"]["tier"] == 1}
        if not ground.intersection(ordered[:n_rust]):
            first_ground = next(j for j, i in enumerate(ordered) if i in ground)
            ordered[0], ordered[first_ground] = ordered[first_ground], ordered[0]
        overlap = min(n_rust, max(1, n_bulge // 5))
        rusted = set(ordered[:n_rust])
        deformed = list(ordered[:overlap]) + list(ordered[n_rust:n_rust + n_bulge - overlap])
        # Keep distinct observable controls. A restricted vent is one cause
        # among several for a bulge, and visual rust follows exterior exposure.
        cases = {i: "exterior_corrosion" for i in rusted}
        cases.update({i: "solid_expansion" if category == "ILW" else "residual_deformation"
                      for i in deformed})
        cases[deformed[-1]] = "restricted_vent"
        cases[next(i for i in ordered[:n_rust] if i in ground)] = "breach"
        available = ordered[n_rust + n_bulge - overlap:]
        independent = [i for i in available if i in ground][:5]
        cases.update(zip(independent, ("warm_venting", "warm_no_release", "cool_venting",
                                        "gamma_outlier", "transfer")))
        for i, drum in enumerate(drums):
            rust = float(rng.beta(2, 2)) if i in rusted else 0.0
            bulge = float(rng.beta(2, 2)) if i in deformed else 0.0
            records.append(_drum_record(drum, profile, cases.get(i, "ordinary"), rust, bulge, rng))
    _apply_forced_faults(layout, records)
    return {"schema_version": 1, "seed": seed, "drums": records, "sensor_config": config["sensor"]}


def _apply_forced_faults(layout, records):
    """Demo option: HOT_FORCE_FAULTS='{"A-L-01-T1": {"corrosion_severity": 0.85}}' pins a drum's appearance by display id."""
    import json as _json
    import os as _os
    forced = _json.loads(_os.environ.get("HOT_FORCE_FAULTS") or "{}")
    ids = {d["display_id"]: d["id"] for d in layout["drums"]}
    by_id = {r["drum_id"]: r for r in records}
    for display_id, plan in forced.items():
        by_id[ids[display_id]]["visual_plan"].update(plan)
