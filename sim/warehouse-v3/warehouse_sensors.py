"""Simulator-side warehouse sensors. Only observations cross the agent boundary."""
import json
import math
from pathlib import Path

import numpy as np

from warehouse_physics import GAS_R, gas_state


def _position(xyz):
    value = np.asarray(xyz, dtype=float)
    if value.shape != (3,) or not np.isfinite(value).all():
        raise ValueError("Position must be three finite metre coordinates")
    return value


def _time(value):
    if not math.isfinite(value) or value < 0:
        raise ValueError("Simulation time must be finite and nonnegative")
    return value


class WarehouseSensors:
    """One instance per session and robot. All timestamps use simulation time."""

    @classmethod
    def from_manifest(cls, path):
        return cls(json.loads(Path(path).read_text())["physical_inventory"])

    def __init__(self, inventory):
        if inventory["schema_version"] != 1:
            raise ValueError("Unsupported physical inventory version")
        self._config = inventory["sensor_config"]
        self._drums = inventory["drums"]
        self._by_id = {d["drum_id"]: d for d in self._drums}
        self._rng = np.random.default_rng(np.random.SeedSequence([inventory["seed"], 0x53454E]))
        self._base = np.array([d["xyz_m"] for d in self._drums])
        self._height = np.array([d["height_m"] for d in self._drums])
        self._radius = np.array([d["radius_m"] for d in self._drums])
        self._mu = np.array([d["radiation"]["effective_attenuation_m_inv"] for d in self._drums])
        self._source = np.repeat(self._base, 3, axis=0)
        self._source[:, 2] += (self._height[:, None] * np.array([.28, .50, .72])).ravel()
        self._strength = np.repeat([d["radiation"]["unshielded_strength_usv_h_m2"] / 3 for d in self._drums], 3)
        self._gas = [d["gas"] for d in self._drums if d["gas"]["h2_exchange_per_day"]]
        self._patches = [p for d in self._drums for p in d["containment"]["patches"]]
        self._last_time = None
        self._previous_rate = 0.0
        self._dose_msv = 0.0
        self._gas_filtered = 0.0
        self._swab = None

    def _gamma_contributions(self, xyz):
        # Each source-to-sensor ray intersects a finite set of nominal cylinders,
        # including its own package. Lengths therefore include self-shielding.
        direction = xyz - self._source
        distance = np.linalg.norm(direction, axis=1)
        offset = self._source[:, None, :2] - self._base[None, :, :2]
        xy = direction[:, None, :2]
        a = (xy * xy).sum(axis=-1)
        b = (offset * xy).sum(axis=-1)
        c = (offset * offset).sum(axis=-1) - self._radius[None, :] ** 2
        disc = b * b - a * c
        root = np.sqrt(np.maximum(disc, 0))
        radial = np.maximum(a, 1e-12)
        lo = np.where(a > 1e-12, (-b - root) / radial, -np.inf)
        hi = np.where(a > 1e-12, (-b + root) / radial, np.inf)
        valid = (disc >= 0) & ((a > 1e-12) | (c <= 0))
        dz = direction[:, None, 2]
        z0 = self._base[None, :, 2] - self._source[:, None, 2]
        z1 = z0 + self._height[None, :]
        denom = np.where(abs(dz) > 1e-12, dz, 1)
        z_lo = np.where(abs(dz) > 1e-12, np.minimum(z0 / denom, z1 / denom), -np.inf)
        z_hi = np.where(abs(dz) > 1e-12, np.maximum(z0 / denom, z1 / denom), np.inf)
        valid &= (abs(dz) > 1e-12) | ((z0 <= 0) & (z1 >= 0))
        length_fraction = np.maximum(0, np.minimum(np.minimum(hi, z_hi), 1) -
                                     np.maximum(np.maximum(lo, z_lo), 0))
        optical_depth = ((length_fraction * valid) @ self._mu) * distance
        return self._strength * np.exp(-optical_depth) / np.maximum(distance, .12) ** 2

    def _air(self, xyz):
        # Blend across the cross aisle instead of creating a discontinuity.
        fraction = float(np.clip((xyz[0] - 10) / 4, 0, 1))
        return 19 + fraction, 62 + 4 * fraction

    def _gas_ppm(self, xyz, time_s):
        cfg = self._config
        airflow = np.array([*cfg["airflow_xy_m_s"], .02])
        speed = np.linalg.norm(airflow)
        diffusivity = cfg["gas_diffusivity_m2_s"]
        concentration = 0.0
        for source in self._gas:
            displacement = xyz - source["vent_xyz_m"]
            distance = max(.12, float(np.linalg.norm(displacement)))
            travel_s = distance / speed
            emitted_at = time_s - travel_s
            rate = gas_state(source, max(0, emitted_at))["h2_emission_mol_s"]
            if 0 <= emitted_at < source["pulse_duration_s"]:
                rate += source["pulse_h2_mol_s"]
            dispersion = math.exp((float(airflow @ displacement) - speed * distance) / (2 * diffusivity))
            concentration += rate * dispersion / (4 * math.pi * diffusivity * distance)
        ambient, _ = self._air(xyz)
        return concentration * (GAS_R * (ambient + 273.15) / 101325) * 1e6

    def sample(self, position, time_s, *, gamma_xyz=None, gas_xyz=None):
        """Sample at robot pose or supplied instrument inlet/detector poses."""
        robot = _position(position)
        gamma = robot if gamma_xyz is None else _position(gamma_xyz)
        inlet = robot if gas_xyz is None else _position(gas_xyz)
        _time(time_s)
        if self._last_time is not None and time_s < self._last_time:
            raise ValueError("Simulation time must be monotonic")
        elapsed = 0.0 if self._last_time is None else time_s - self._last_time
        cfg = self._config
        field = cfg["gamma_background_usv_h"] + self._gamma_contributions(gamma).sum()
        exposure = cfg["gamma_counts_per_usv_h_s"] * cfg["gamma_integration_s"]
        counts = self._rng.poisson(field * exposure)
        rate = float(counts / exposure)
        if self._last_time is not None:
            self._dose_msv += (self._previous_rate + rate) * .5 * elapsed / 3_600_000
        self._last_time, self._previous_rate = time_s, rate
        actual_h2 = self._gas_ppm(inlet, time_s)
        self._gas_filtered += (actual_h2 - self._gas_filtered) * (
            -math.expm1(-math.log(10) * elapsed / cfg["gas_t90_s"]))
        h2 = max(0.0, float(self._rng.normal(self._gas_filtered,
                                            cfg["gas_relative_noise"] * self._gas_filtered + .15)))
        air, rh = self._air(robot)
        return {
            "time_s": time_s, "dose_timestamp_s": time_s, "dose_rate_uSv_h": rate,
            "dose_integration_s": cfg["gamma_integration_s"], "mission_dose_mSv": self._dose_msv,
            "temperature_c": float(self._rng.normal(air, cfg["air_noise_c"])),
            "relative_humidity_pct": float(self._rng.normal(rh, cfg["rh_noise_pct"])),
            "hydrogen_ppm": h2 if h2 >= cfg["gas_detection_ppm"] else None,
            "hydrogen_status": "detected" if h2 >= cfg["gas_detection_ppm"] else "below_detection",
            "hydrogen_detection_limit_ppm": cfg["gas_detection_ppm"],
        }

    def gamma_bins(self, position, yaw_rad=0.0):
        xyz = _position(position)
        offsets = self._source - xyz
        bins = np.zeros(16)
        centre = (np.arctan2(offsets[:, 1], offsets[:, 0]) - yaw_rad) % math.tau
        index = (centre * 16 / math.tau).astype(int)
        values = self._gamma_contributions(xyz)
        for step, weight in ((-1, .25), (0, .5), (1, .25)):
            np.add.at(bins, (index + step) % 16, values * weight)
        return {"bearing_frame": "robot_yaw", "bin_count": 16, "intensity_uSv_h": bins.tolist()}

    def thermal_from_camera(self, optical_depth, segmentation, intrinsics, camera_to_world):
        """Adapt Isaac optical depth and backend-only Replicator segmentation.

        Camera-to-world uses the USD frame (+X right, +Y up, -Z forward).
        """
        depth = np.asarray(optical_depth, dtype=float).squeeze()
        ids = np.asarray(segmentation["data"]).squeeze()
        if depth.ndim != 2 or ids.shape != depth.shape:
            raise ValueError("Depth and segmentation must be co-registered 2D arrays")
        depth = np.where(np.isfinite(depth) & (depth > 0), depth, np.nan)
        rows, cols = np.indices(depth.shape)
        fx, fy = intrinsics[0, 0], intrinsics[1, 1]
        cx, cy = intrinsics[0, 2], intrinsics[1, 2]
        rays = np.stack(((cols + .5 - cx) / fx, -(rows + .5 - cy) / fy, -np.ones_like(depth)), axis=-1)
        matrix = np.asarray(camera_to_world, dtype=float)
        # Gf.Matrix4d uses row-vector transforms and a translation in the last row.
        xyz = (rays * depth[..., None]) @ matrix[:3, :3] + matrix[3, :3]
        labels = np.full(ids.shape, "", dtype="<U16")
        for key, label in segmentation["info"]["idToLabels"].items():
            drum_id = label.get("drum_id", "")
            if label.get("class") == "drum" and drum_id:
                labels[ids == int(key)] = str(drum_id).upper()
        return self.thermal_frame(xyz, labels, camera_xyz=matrix[3, :3])

    def thermal_frame(self, world_xyz, private_drum_ids, *, camera_xyz=None):
        """Render apparent LWIR from co-registered world XYZ and private hit IDs.

        The caller supplies backend-only hit IDs from Isaac segmentation, not
        detector predictions. IDs never appear in the returned float image.
        """
        points = np.asarray(world_xyz, dtype=float)
        labels = np.asarray(private_drum_ids)
        if points.shape != (*labels.shape, 3):
            raise ValueError("Thermal XYZ and hit ID images must have matching dimensions")
        valid = np.isfinite(points).all(axis=-1)
        result = np.where(points[..., 0] < 12, 19.0, 20.0)
        camera = None if camera_xyz is None else _position(camera_xyz)
        for key in np.unique(labels[valid]):
            drum = self._by_id.get(str(key))
            if drum is None:
                continue
            selected = (labels == key) & valid
            xyz = points[selected]
            x, y, z = drum["xyz_m"]
            angle = np.arctan2(xyz[:, 1] - y, xyz[:, 0] - x)
            z_fraction = (xyz[:, 2] - z) / drum["height_m"]
            face = drum["face_sign"] * math.pi / 2
            azimuth = (angle - face + math.pi) % math.tau - math.pi
            thermal = drum["thermal"]
            local = np.exp(-.5 * ((z_fraction - .58) / .16) ** 2 - .5 * (azimuth / .45) ** 2)
            true_c = thermal["shell_c"] + thermal["hotspot_delta_c"] * local
            emissivity = np.full(len(xyz), thermal["emissivity"])
            if camera is not None:
                view = camera - xyz
                cosine = (np.cos(angle) * view[:, 0] + np.sin(angle) * view[:, 1])
                cosine /= np.maximum(np.linalg.norm(view, axis=1), 1e-6)
                emissivity *= .70 + .30 * np.clip(cosine, 0, 1)
            corrosion = drum.get("appearance", {}).get("corrosion", {})
            u = ((angle - drum["yaw_rad"]) / math.tau) % 1
            for site in corrosion.get("sites", []):
                angular = (u - site["u"] + .5) % 1 - .5
                patch = np.exp(-.5 * ((angular / .022) ** 2 + ((z_fraction - site["height_fraction"]) / .03) ** 2))
                emissivity += (.92 - emissivity) * .55 * patch
            reflected = thermal["ambient_c"] + (1.4 if drum["category"] == "ILW" else .4)
            result[selected] = (emissivity * (true_c + 273.15) ** 4 +
                                (1 - emissivity) * (reflected + 273.15) ** 4) ** .25 - 273.15
        result += self._rng.normal(0, self._config["thermal_noise_c"], result.shape)
        result[~valid] = np.nan
        return result.astype(np.float32)

    def start_swab(self, floor_contact_xyz, time_s, *, robot_xyz, robot_stopped=False):
        point = _position(floor_contact_xyz)
        robot = _position(robot_xyz)
        _time(time_s)
        if not robot_stopped or abs(point[2]) > .02:
            raise ValueError("Swabbing requires a stopped robot and floor contact")
        if np.linalg.norm(point[:2] - robot[:2]) > self._config["swab_max_reach_m"]:
            raise ValueError("Contact is outside configured tool reach")
        if self._swab is not None:
            raise RuntimeError("Swab already in progress")
        ready = time_s + self._config["swab_dwell_s"]
        self._swab = (ready, point)
        return {"status": "sampling", "ready_at_s": ready}

    def poll_swab(self, time_s):
        _time(time_s)
        if self._swab is None:
            return {"status": "idle"}
        ready, point = self._swab
        if time_s < ready:
            return {"status": "sampling", "ready_at_s": ready}
        self._swab = None
        cfg = self._config
        area = cfg["swab_area_cm2"]
        radius = math.sqrt(area / math.pi) / 100
        offsets = np.linspace(-radius, radius, 17)
        u, v = np.meshgrid(offsets, offsets)
        disk = (u * u + v * v) <= radius * radius
        xy = np.column_stack((u[disk], v[disk])) + point[:2]
        result = {"status": "complete", "time_s": time_s,
                  "contact_xyz": point.tolist(), "area_cm2": area}
        for channel in ("alpha", "beta_gamma"):
            key = f"{channel}_bq_cm2"
            activity = sum(p[key] * np.mean(np.linalg.norm(xy - p["xyz_m"][:2], axis=1) <= p["radius_m"])
                           for p in self._patches)
            limit = cfg[f"swab_{channel}_mda_bq_cm2"]
            sensitivity = area * cfg["swab_recovery"] * .25 * cfg["swab_dwell_s"]
            measured = float(self._rng.poisson(activity * sensitivity) / sensitivity)
            result[key] = measured if measured >= limit else None
            result[f"{channel}_status"] = "detected" if measured >= limit else "below_detection"
            result[f"{channel}_detection_limit_bq_cm2"] = limit
        return result
