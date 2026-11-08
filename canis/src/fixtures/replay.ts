/**
 * DEMO REPLAY fixture. Deterministic, local, and entirely fictional.
 *
 * - Drum IDs, location codes, route nodes and the spawn come from the real public map
 *   so selection works. Every reading, detection, finding and alert is invented.
 * - Every message carries source.fixture = true and source.kind = "replay".
 * - Nothing here is derived from private simulator truth.
 */
import type { PublicDrum, PublicMap } from '../contracts/publicMap';
import { depthFixture, lwirFixture, rgbFixture, thirdPersonFixture } from './frames';

export interface ReplayStep {
  t: number;
  messages: unknown[];
  note?: string;
}

const MODEL = 'yolo26s_20261107T225757Z_d625ef (fixture: no model was run)';

function src(id: string) {
  return { id: `replay:${id}`, kind: 'replay' as const, fixture: true };
}

function lerp(a: number, b: number, f: number) {
  return a + (b - a) * f;
}

/** Route polyline: spawn → front_spawn_link → N0_1 → along aisle 1 toward N1_1. */
function routePoints(map: PublicMap): [number, number][] {
  const n = map.nodes;
  return [n.spawn, n.front_spawn_link, n.N0_1, [9.5, n.N0_1[1]]];
}

function poseAt(map: PublicMap, t: number, total: number): { xyz: [number, number, number]; yaw: number; waypoint: string } {
  const pts = routePoints(map);
  const names = ['spawn', 'front_spawn_link', 'N0_1', 'N1_1 (en route)'];
  const lengths = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  const totalLen = lengths.reduce((a, b) => a + b, 0);
  let d = Math.min(1, t / (total * 0.9)) * totalLen;
  for (let i = 0; i < lengths.length; i++) {
    if (d <= lengths[i] || i === lengths.length - 1) {
      const f = lengths[i] ? Math.min(1, d / lengths[i]) : 1;
      const a = pts[i], b = pts[i + 1];
      return {
        xyz: [+lerp(a[0], b[0], f).toFixed(3), +lerp(a[1], b[1], f).toFixed(3), 0],
        yaw: Math.atan2(b[1] - a[1], b[0] - a[0]),
        waypoint: names[i + 1],
      };
    }
    d -= lengths[i];
  }
  return { xyz: [pts[0][0], pts[0][1], 0], yaw: 0, waypoint: names[0] };
}

/** Real drums on the robot's side of aisle 1, ground tier, nearest the route first. */
export function replayDrums(map: PublicMap): PublicDrum[] {
  return map.drums
    .filter((d) => d.facing_aisle === 1 && d.inspection_route_y_m === map.nodes.N0_1[1] && d.tier === 1 && d.x_m < 9.5)
    .sort((a, b) => a.x_m - b.x_m || a.y_m - b.y_m)
    .slice(0, 4);
}

export const REPLAY_TOTAL_S = 60;

export function buildReplay(map: PublicMap): ReplayStep[] {
  const [d1, d2, d3, d4] = replayDrums(map);
  const steps: ReplayStep[] = [];
  const seq: Record<string, number> = {};
  const next = (k: string) => (seq[k] = (seq[k] ?? -1) + 1);
  let doseMsv = 0;
  let prevDose = 0.1;
  let lastSensorT = 0;

  const rgbFrame = (t: number) => `F-rgb-${String(t).padStart(4, '0')}`;

  for (let t = 0; t <= REPLAY_TOTAL_S; t++) {
    const m: unknown[] = [];
    let note: string | undefined;
    const pose = poseAt(map, t, REPLAY_TOTAL_S);
    const envelope = (source: string, kind: string, extra: object) => ({
      schema: 'canis.v1', kind, source: src(source), seq: next(`${source}:${kind}`), t_sim_s: t, quality: 'ok', ...extra,
    });

    m.push(envelope('isaac', 'run_state', {
      mode: 'replay', mission_state: t < REPLAY_TOTAL_S ? 'DEMO · aisle 1 traverse' : 'DEMO · complete',
      run_id: 'demo-replay', sim_clock_s: t, waypoint: pose.waypoint,
      planned_path: ['spawn', 'front_spawn_link', 'N0_1', 'N1_1'], planned_packages: 4,
      target_package_id: (t < 14 ? d1 : t < 30 ? d2 : t < 50 ? d3 : d4)?.location_code,
    }));
    m.push(envelope('robot', 'robot_pose', {
      frame: 'world_m_zup', xyz_m: pose.xyz, rpy_deg: [0.2, -0.8, +(pose.yaw * 180 / Math.PI).toFixed(1)],
      nav_confidence: 0.94, battery_pct: +(81 - t * 0.05).toFixed(1), battery_runtime_s: 5400 - t * 4,
      health: 'ok', operating_mode: t < REPLAY_TOTAL_S ? 'DEMO TRAVERSE' : 'DEMO HOLD',
      pose_source: 'simulator_pose',
    }));

    // Sensor feed: every 2 s (dose integration window), with a deliberate gap 32–44 s.
    const inGap = t >= 32 && t < 45;
    if (t % 2 === 0 && !inGap) {
      const near = Math.max(0, 1 - Math.abs(pose.xyz[0] - (d2?.x_m ?? 5)) / 3);
      const dose = +(0.11 + 0.52 * near + ((t * 7) % 5) * 0.01).toFixed(3);
      doseMsv += ((prevDose + dose) / 2) * (t - lastSensorT) / 3_600_000;
      prevDose = dose;
      lastSensorT = t;
      const h2Detected = t === 22 || t === 24;
      m.push(envelope('sensors', 'sensor_reading', {
        frame: 'world_m_zup', time_s: t, dose_timestamp_s: t, dose_rate_uSv_h: dose, dose_integration_s: 2,
        mission_dose_mSv: doseMsv, temperature_c: +(19.1 + (t % 3) * 0.04).toFixed(2),
        relative_humidity_pct: +(62.2 + (t % 4) * 0.1).toFixed(1),
        hydrogen_ppm: h2Detected ? 3.1 : null, hydrogen_status: h2Detected ? 'detected' : 'below_detection',
        hydrogen_detection_limit_ppm: 2,
        gamma_xyz_m: [pose.xyz[0], pose.xyz[1], 0.55], gas_inlet_xyz_m: [pose.xyz[0], pose.xyz[1], 1.0],
      }));
    }
    if (t % 4 === 0) {
      m.push(envelope('isaac', 'camera_frame', {
        camera_id: 'third_person', frame_id: `F-tp-${String(t).padStart(4, '0')}`, width: 960, height: 540, fps: 0.25,
        encoding: 'svg', uri: thirdPersonFixture(`F-tp-${t}`), caption: 'Fixture third-person frame',
      }));
    }
    if (t >= 4 && t % 2 === 0) {
      m.push(envelope('robot', 'camera_frame', {
        camera_id: 'rgb', frame_id: rgbFrame(t), width: 640, height: 480, fps: 0.5, encoding: 'svg', uri: rgbFixture(rgbFrame(t)),
      }));
      m.push(envelope('robot', 'camera_frame', {
        camera_id: 'depth', frame_id: `F-depth-${String(t).padStart(4, '0')}`, width: 640, height: 480, fps: 0.5,
        encoding: 'svg', uri: depthFixture(`F-depth-${t}`), units: 'depth_m', range: [0.3, 8],
      }));
      if (!inGap) {
        m.push(envelope('sensors', 'camera_frame', {
          camera_id: 'lwir', frame_id: `F-lwir-${String(t).padStart(4, '0')}`, width: 640, height: 480, fps: 0.5,
          encoding: 'svg', uri: lwirFixture(`F-lwir-${t}`), units: 'apparent_c', range: [18.4, 21.9],
        }));
      }
    }

    if (t === 10 && d1) {
      note = 'Detection on an RGB fixture frame (confidence belongs to the detection)';
      m.push(envelope('detector', 'detection', {
        detection_id: 'DET-0001', camera_id: 'rgb', frame_id: rgbFrame(10), class_id: 1,
        bbox_px: [44, 262, 64, 92], confidence: 0.71, model_id: MODEL,
        drum_attribution: {
          package_id: d1.location_code, status: 'attributed',
          evidence: [{ kind: 'camera_frame', ref: rgbFrame(10) }],
          note: `Printed code ${d1.location_code} read in the same frame (fixture)`,
        },
      }));
    }
    const record = (d: PublicDrum, frame: string, view: string, finding: string | null) =>
      envelope('mission', 'inspection_record', {
        run_id: 'demo-replay', package_id: d.location_code, frame_id: frame, view, finding,
        evidence: [{ kind: 'camera_frame', ref: frame }],
      });
    if (t === 10 && d1) m.push(record(d1, rgbFrame(10), 'front', 'corrosion candidate (fixture)'));
    if (t === 14 && d1) {
      m.push(record(d1, rgbFrame(14), 'oblique', null));
      m.push(envelope('assessment', 'inspection_finding', {
        finding_id: 'FND-0001', package_id: d1.location_code, status: 'observation_only',
        summary: 'Surface discolouration consistent with corrosion product on lower chime (fixture)',
        evidence: [{ kind: 'detection', ref: 'DET-0001' }],
        limits: ['Rust alone does not establish leakage, wall loss or internal condition', 'Single first-tier view'],
      }));
    }
    if (t === 18 && d2) {
      note = 'Elevated total dose with inconclusive package attribution';
      m.push(record(d2, rgbFrame(18), 'front', null));
      m.push(envelope('sensors', 'gamma_bearing', {
        bearing_frame: 'robot_yaw', bin_count: 16,
        intensity_uSv_h: [0.02, 0.03, 0.05, 0.09, 0.14, 0.11, 0.06, 0.03, 0.02, 0.02, 0.02, 0.03, 0.05, 0.08, 0.07, 0.03],
        detector_xyz_m: [pose.xyz[0], pose.xyz[1], 0.55], yaw_rad: pose.yaw,
      }));
      m.push(envelope('assessment', 'inspection_finding', {
        finding_id: 'FND-0002', package_id: null, status: 'inconclusive',
        summary: `Total dose rate above the aisle trend near ${d2.location_code}; bearing is broad and spans several packages`,
        evidence: [{ kind: 'sensor_reading', ref: 'replay:sensors#t=18' }, { kind: 'gamma_bearing', ref: 'replay:sensors#bearing-t=18' }],
        limits: ['Total dose sums contributions from several packages', 'Attribution needs additional detector poses'],
      }));
      m.push(envelope('assessment', 'alert', {
        alert_id: 'AL-0001', severity: 'warning', title: `Dose above aisle trend near ${d2.location_code}`,
        detail: 'Package attribution inconclusive (fixture)', package_id: d2.location_code,
        evidence: [{ kind: 'sensor_reading', ref: 'replay:sensors#t=18' }],
      }));
    }
    if (t === 22) note = 'Hydrogen resolved above the detection limit at the inlet';
    if (t === 24) {
      note = 'Possible bulge detection with no package attribution';
      m.push(envelope('detector', 'detection', {
        detection_id: 'DET-0002', camera_id: 'rgb', frame_id: rgbFrame(24), class_id: 2,
        bbox_px: [470, 244, 78, 104], confidence: 0.48, model_id: MODEL,
        drum_attribution: { package_id: null, status: 'inconclusive', evidence: [{ kind: 'camera_frame', ref: rgbFrame(24) }],
          note: 'Printed code not legible in this view (fixture)' },
      }));
    }
    if (t === 26 && d3) {
      note = 'Inconclusive finding and a proposed action (not sent)';
      m.push(envelope('assessment', 'inspection_finding', {
        finding_id: 'FND-0003', package_id: d3.location_code, status: 'inconclusive',
        summary: `Possible flank deformation (DET-0002); printed code ${d3.location_code} read in the next frame; single view, specular highlight not excluded`,
        evidence: [{ kind: 'detection', ref: 'DET-0002' }, { kind: 'camera_frame', ref: rgbFrame(24) }, { kind: 'camera_frame', ref: rgbFrame(26) }],
        limits: ['Bulge does not establish internal pressure', 'Hydrogen below detection in surrounding air does not prove absence', 'Needs a second oblique view and depth profile'],
      }));
      m.push(envelope('assessment', 'alert', {
        alert_id: 'AL-0002', severity: 'warning', title: `Possible deformation near ${d3.location_code} — inconclusive`,
        package_id: d3.location_code, evidence: [{ kind: 'detection', ref: 'DET-0002' }],
        proposed_action: { text: `Reacquire ${d3.id} (${d3.location_code}) from a second oblique view and compare depth to the nominal profile`, status: 'proposed_not_sent' },
      }));
    }
    if (t === 28) {
      note = 'Duplicate and out-of-order messages are handled at the boundary';
      // Duplicate: re-send this step's sensor reading with the same sequence number.
      m.push({ ...(m.find((x) => (x as { kind: string }).kind === 'sensor_reading') as object) });
      // Out of order: an older robot pose sequence.
      m.push({ ...(steps[20].messages.find((x) => (x as { kind: string }).kind === 'robot_pose') as object) });
    }
    if (t === 30) {
      note = 'Invalid payload (below-detection hydrogen reported as 0) is rejected';
      m.push({
        schema: 'canis.v1', kind: 'sensor_reading', source: src('sensors'), seq: 9999, t_sim_s: 30, quality: 'ok',
        frame: 'world_m_zup', time_s: 30, dose_timestamp_s: 30, dose_rate_uSv_h: 0.12, dose_integration_s: 2,
        mission_dose_mSv: doseMsv, temperature_c: 19.1, relative_humidity_pct: 62.1,
        hydrogen_ppm: 0, hydrogen_status: 'below_detection', hydrogen_detection_limit_ppm: 2,
        gamma_xyz_m: [0, 0, 0.55], gas_inlet_xyz_m: [0, 0, 1],
      });
    }
    if (t === 32) note = 'Sensor feed gap begins; values go stale after 8 s';
    if (t === 46 && d2) {
      note = 'Wipe result: below detection on both channels for one footprint';
      m.push(envelope('sensors', 'swab_result', {
        frame: 'world_m_zup', status: 'complete', time_s: 46,
        contact_xyz: [+(d2.x_m).toFixed(3), +(map.nodes.N0_1[1] - 1.2).toFixed(3), 0], area_cm2: 100,
        alpha_bq_cm2: null, alpha_status: 'below_detection', alpha_detection_limit_bq_cm2: 0.03,
        beta_gamma_bq_cm2: null, beta_gamma_status: 'below_detection', beta_gamma_detection_limit_bq_cm2: 0.15,
        near_package_id: d2.location_code,
      }));
    }
    // Identity for d3 is read in a later frame; the t=24 detection itself stays unattributed.
    if (t === 26 && d3) m.push(record(d3, rgbFrame(26), 'front', 'possible deformation, single view (fixture)'));
    if (t === 48 && d2) m.push(record(d2, rgbFrame(48), 'oblique', null));
    if (t === 50 && d4) m.push(record(d4, rgbFrame(50), 'front', null));
    if (t === REPLAY_TOTAL_S) {
      m.push(envelope('assessment', 'alert', {
        alert_id: 'AL-0003', severity: 'info', title: 'Demo replay complete', evidence: [],
      }));
    }
    steps.push({ t, messages: m, note });
  }
  return steps;
}
