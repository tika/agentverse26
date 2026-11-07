"""Simulator-side sensor models. Only observation packets go to the future agent.

Truth is private to this backend and offline scoring. No drum IDs, source positions,
category labels, condition flags or source contributions appear in passive packets.
"""
import copy
import json
import math
from pathlib import Path
import random

from inspection_payloads import dew_point_c, gas_at_pose

CONFIG = Path(__file__).with_name('inspection_config.json')


def load_config():
    return json.loads(CONFIG.read_text())


def author_gamma_source(prim, entry):
    """Publish simulator-only source parameters on the drum prim."""
    from pxr import Sdf

    prim.CreateAttribute("inspection:gammaDoseRateAt1mUSvH", Sdf.ValueTypeNames.Double).Set(
        float(entry["source_strength"])
    )
    prim.CreateAttribute("inspection:gammaSourceHeightM", Sdf.ValueTypeNames.Double).Set(
        float(entry.get("base_z", 0.0)) + float(entry["height"]) / 2
    )


def intersects_drum(start, end, drum):
    """Segment intersection with a finite vertical nominal cylinder (toy shielding)."""
    dx, dy, dz = (end[i]-start[i] for i in range(3))
    ox, oy = start[0]-drum['x'], start[1]-drum['y']
    a = dx*dx+dy*dy
    if a < 1e-12:
        return False
    b, c = 2*(ox*dx+oy*dy), ox*ox+oy*oy-drum['radius']**2
    discriminant = b*b-4*a*c
    if discriminant < 0:
        return False
    lo, hi = sorted(((-b-math.sqrt(discriminant))/(2*a), (-b+math.sqrt(discriminant))/(2*a)))
    lo, hi = max(lo, 1e-6), min(hi, 1-1e-6)
    if lo > hi:
        return False
    if abs(dz) < 1e-12:
        return drum.get('base_z', 0.0) <= start[2] <= drum.get('base_z', 0.0)+drum['height']
    z0 = drum.get('base_z', 0.0)
    zl, zh = sorted(((z0-start[2])/dz, (z0+drum['height']-start[2])/dz))
    return max(lo, zl) <= min(hi, zh)


class SensorWorld:
    def __init__(self, drums, config=None):
        self.config = copy.deepcopy(config or load_config())
        self._drums = copy.deepcopy(drums)
        self._zones = copy.deepcopy(self.config['environment']['zones'])
        self._contamination = {d['id']: {'alpha': 0.0, 'beta_gamma': 0.0} for d in drums}
        seed = self.config['seed']
        self._dose_rng, self._env_rng, self._swab_rng = (random.Random(seed+i) for i in range(3))
        self._last_time = None
        self._dose_mSv = 0.0
        self._previous_rate = None
        self._dose_complete = True
        self._pending_swab = None
        self._surface_chemistry = {}

    def _sources(self, position):
        cfg = self.config['radiation']
        for drum in self._drums:
            source = (drum['x'], drum['y'], drum.get('base_z', 0.0)+drum['height']/2)
            distance2 = max(sum((position[i]-source[i])**2 for i in range(3)), cfg['distance_floor_m']**2)
            blockers = sum(intersects_drum(position, source, other) for other in self._drums if other['id'] != drum['id'])
            yield source, drum['source_strength']/distance2*cfg['shielding_per_drum']**blockers

    def sample(self, position, time_s, *, gamma_operational=True):
        """Call once per simulation tick. Time is simulation seconds, not wall clock.

        Trapezoidal dose integration; first sample contributes no elapsed exposure.
        Invalid readings interrupt integration and mark the cumulative proxy incomplete.
        Camera/depth timestamps are supplied separately by the RTX capture pipeline.
        """
        if len(position) != 3 or not all(math.isfinite(v) for v in position):
            raise ValueError('Position must contain three finite metre coordinates')
        if not math.isfinite(time_s) or time_s < 0 or (self._last_time is not None and time_s < self._last_time):
            raise ValueError('Simulation time must be finite, nonnegative and monotonic')
        cfg = self.config['radiation']
        saturation = cfg.get('saturation_uSv_h', 1000.0)
        rate = uncertainty = None
        status = 'failed'
        if gamma_operational:
            expected = cfg['background']+sum(value for _, value in self._sources(position))
            uncertainty = expected * cfg['noise_fraction']
            rate = max(0.0, self._dose_rng.gauss(expected, uncertainty))
            status = 'saturated' if rate >= saturation else 'ok'
            rate = min(rate, saturation)
        current_rate = rate if status == 'ok' else None
        if current_rate is None or (self._last_time is not None and self._previous_rate is None):
            self._dose_complete = False
        if self._previous_rate is not None and current_rate is not None:
            self._dose_mSv += (self._previous_rate+current_rate)/2*(time_s-self._last_time)/3_600_000
        self._last_time, self._previous_rate = time_s, current_rate
        gamma = {
            'sensor_id': 'spot_gamma', 'unit': 'uSv/h', 'value': rate,
            'timestamp_s': time_s, 'age_s': 0.0, 'position_m': list(map(float, position)),
            'saturation_limit_uSv_h': saturation,
            'uncertainty_uSv_h': uncertainty if status == 'ok' else None,
            'valid': status == 'ok', 'status': status,
        }
        zone = 'A' if position[0] < 10 else 'B'
        env = self.config['environment']
        values = self._zones[zone]
        temperature = self._env_rng.gauss(values['temperature_c'], env['temperature_noise_std_c'])
        humidity = min(100.0, max(0.0, self._env_rng.gauss(values['relative_humidity_pct'], env['humidity_noise_std_pct'])))
        return {'time_s': time_s, 'dose_rate_uSv_h': rate, 'dose_timestamp_s': time_s,
                'mission_dose_mSv': self._dose_mSv, 'dose_complete': self._dose_complete,
                'gamma': gamma, 'zone': zone,
                'temperature_c': temperature, 'relative_humidity_pct': humidity,
                'dew_point_c': dew_point_c(temperature, humidity),
                **(gas_at_pose(position, self.config['gas_vents']) if 'gas_vents' in self.config else {})}

    def gamma_bins(self, position, yaw_rad=0.0):
        """Stretch sensor: relative bearing/intensity in 16 blurred azimuth bins."""
        bins = [0.0]*16
        for source, value in self._sources(position):
            bearing = (math.atan2(source[1]-position[1], source[0]-position[0])-yaw_rad) % (2*math.pi)
            centre = int(bearing/(2*math.pi)*16)
            for offset, weight in ((-1, .25), (0, .5), (1, .25)):
                bins[(centre+offset) % 16] += value*weight
        return {'bearing_frame': 'robot_yaw', 'bin_count': 16, 'intensity_uSv_h': bins}

    def start_swab(self, floor_contact_xyz, time_s, *, robot_stopped=False):
        """Virtual tool contact; caller must stop the robot. No physical arm yet.

        Contact is spatial; the agent cannot request a hidden drum ID. Valid
        locations lie within 8 cm of a drum's nominal floor perimeter.
        """
        if not robot_stopped:
            raise ValueError('Robot must be stopped before sampling')
        if not math.isfinite(time_s) or time_s < 0:
            raise ValueError('Invalid simulation time')
        if len(floor_contact_xyz) != 3 or not all(math.isfinite(v) for v in floor_contact_xyz):
            raise ValueError('Invalid tool contact')
        if self._pending_swab:
            raise RuntimeError('Swab already in progress')
        if abs(floor_contact_xyz[2]) > .02:
            raise ValueError('Swab must contact the floor')
        reach = self.config['robot']['swab_reach_m']
        eligible = [(abs(math.hypot(floor_contact_xyz[0]-d['x'], floor_contact_xyz[1]-d['y'])-d['radius']), d)
                    for d in self._drums]
        distance, drum = min(eligible, key=lambda item: item[0])
        if distance > reach:
            raise ValueError('No drum-base swab patch in reach')
        self._pending_swab = {'ready_at': time_s+self.config['robot']['swab_duration_s'],
                              'contact': list(floor_contact_xyz), 'id': drum['id'],
                              'chemistry': self._surface_chemistry.get(drum['id'], {})}
        return {'status': 'sampling', 'ready_at_s': self._pending_swab['ready_at']}

    def poll_swab(self, time_s):
        pending = self._pending_swab
        if not pending:
            return {'status': 'idle'}
        if time_s < pending['ready_at']:
            return {'status': 'sampling', 'ready_at_s': pending['ready_at']}
        self._pending_swab = None
        fraction = self.config['robot']['swab_noise_fraction']
        values = {key: max(0.0, self._swab_rng.gauss(value, value*fraction))
                  for key, value in self._contamination[pending['id']].items()}
        return {'status': 'complete', 'time_s': time_s, 'contact_xyz': pending['contact'],
                'alpha_bq_cm2': values['alpha'], 'beta_gamma_bq_cm2': values['beta_gamma'],
                **pending['chemistry']}

    def inject_leak(self, drum_id, alpha_bq_cm2=0.8, beta_gamma_bq_cm2=8.0):
        """Simulator event hook only. Visible puddles are built in the later fault step."""
        drum = next(d for d in self._drums if d['id'] == drum_id)
        drum['source_strength'] = self.config['events']['leak_strength_at_1m']
        self._contamination[drum_id] = {'alpha': alpha_bq_cm2, 'beta_gamma': beta_gamma_bq_cm2}

    def set_surface_chemistry(self, drum_id, *, ph=None, conductivity_us_cm=None, chloride_mg_m2=None):
        """Author optional sample results independently of radiation and visible moisture."""
        if drum_id not in self._contamination:
            raise ValueError("Unknown drum ID")
        if ph is not None and (not math.isfinite(ph) or not 0 <= ph <= 14):
            raise ValueError("Fixture pH must be between 0 and 14")
        if any(value is not None and (not math.isfinite(value) or value < 0)
               for value in (conductivity_us_cm, chloride_mg_m2)):
            raise ValueError("Conductivity and chloride must be finite and nonnegative")
        self._surface_chemistry[drum_id] = {
            key: value for key, value in {
                "ph": ph, "conductivity_us_cm": conductivity_us_cm,
                "chloride_mg_m2": chloride_mg_m2,
            }.items() if value is not None
        }

    def inject_water_ingress(self, zone):
        self._zones[zone]['relative_humidity_pct'] = min(100.0, self._zones[zone]['relative_humidity_pct']+
                                                        self.config['events']['water_ingress_rh_increase_pct'])


def create_sensor_rig(stage, eye, target, parent='/World/SensorRig'):
    """Co-registered RGB/depth camera, ready to parent under the future robot."""
    from pxr import Gf, UsdGeom
    cfg = load_config()['camera']
    if stage.GetPrimAtPath(parent):
        stage.RemovePrim(parent)
    UsdGeom.Xform.Define(stage, parent)
    camera = UsdGeom.Camera.Define(stage, parent+'/RGBDepth')
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0,0,1))
    UsdGeom.Xformable(camera).AddTransformOp().Set(matrix.GetInverse())
    camera.CreateFocalLengthAttr(cfg['focal_length_mm'])
    camera.CreateHorizontalApertureAttr(36)
    camera.CreateVerticalApertureAttr(27)
    camera.CreateClippingRangeAttr(Gf.Vec2f(*cfg['clipping_m']))
    return str(camera.GetPath())
