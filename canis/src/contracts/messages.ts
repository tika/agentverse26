/**
 * C.A.N.I.S. inbound data contracts, schema "canis.v1".
 *
 * Every live, replay or static message is an envelope. Validation happens once,
 * at the ingest boundary (src/ingest/FeedBus.ts). There are no outbound command
 * types: the console is read-only with respect to the simulator and the robot.
 */
import { z } from 'zod';

export const SourceKind = z.enum(['isaac', 'mission', 'robot', 'detector', 'assessment', 'replay', 'static', 'ledger_file']);
export type SourceKind = z.infer<typeof SourceKind>;

export const Quality = z.enum(['ok', 'degraded', 'invalid']);
export type Quality = z.infer<typeof Quality>;

export const CameraId = z.enum(['third_person', 'rgb', 'depth', 'lwir']);
export type CameraId = z.infer<typeof CameraId>;

/** Warehouse world frame: metres, Z up, origin at the hall corner used by map.json. */
export const WORLD_FRAME = 'world_m_zup' as const;

const finite = z.number().finite();
/**
 * Printed package code, the observation key shared with the mission ledger
 * (scripts/hot/warehouse_observations.py). Same as map.json display_id, e.g. "A-L-01-T1".
 */
const PackageId = z.string().regex(/^[A-Z]-[LR]-\d{2}-T\d(-D\d)?$/, 'expected a printed location code like A-L-01-T1');
const xyz = z.tuple([finite, finite, finite]);

const Source = z.object({
  id: z.string().min(1),
  kind: SourceKind,
  /** True for demo/test fixtures. The UI badges every fixture-derived item. */
  fixture: z.boolean().optional(),
});

const envelope = {
  schema: z.literal('canis.v1'),
  source: Source,
  /** Per-source, per-kind monotonic sequence number. */
  seq: z.number().int().nonnegative(),
  /** Source simulation clock in seconds, when the source has one. */
  t_sim_s: finite.nonnegative().optional(),
  /** Source wall clock (ms since epoch), when the source has one. */
  t_wall_ms: finite.optional(),
  quality: Quality.default('ok'),
};

export const MapSnapshotMsg = z.object({
  ...envelope,
  kind: z.literal('map_snapshot'),
  frame: z.literal(WORLD_FRAME),
  map_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  drum_count: z.number().int(),
});

export const RunStateMsg = z.object({
  ...envelope,
  kind: z.literal('run_state'),
  mode: z.enum(['offline', 'replay', 'live']),
  mission_state: z.string().optional(),
  /** Elapsed simulation clock. The header shows elapsed time only when this is present. */
  sim_clock_s: finite.nonnegative().optional(),
  run_id: z.string().optional(),
  waypoint: z.string().optional(),
  /** Current target package (printed code), when the mission has one. */
  target_package_id: PackageId.optional(),
  /** Planned path as route-node names from map.json … */
  planned_path: z.array(z.string()).optional(),
  /** … or as world XY points, e.g. warehouse_routes.route_from_spawn() output. */
  planned_path_m: z.array(z.tuple([finite, finite])).optional(),
  planned_packages: z.number().int().nonnegative().optional(),
});

export const RobotPoseMsg = z.object({
  ...envelope,
  kind: z.literal('robot_pose'),
  frame: z.literal(WORLD_FRAME),
  xyz_m: xyz,
  rpy_deg: xyz,
  nav_confidence: finite.min(0).max(1).optional(),
  battery_pct: finite.min(0).max(100).optional(),
  battery_runtime_s: finite.nonnegative().optional(),
  health: z.enum(['ok', 'degraded', 'fault']).optional(),
  health_detail: z.string().optional(),
  operating_mode: z.string().optional(),
  /**
   * "simulator_pose" is ground-truth pose from Isaac, allowed only in the labelled
   * locomotion smoke test. "estimated" is the robot's own localisation.
   */
  pose_source: z.enum(['simulator_pose', 'estimated']).optional(),
});

export const CameraFrameMsg = z.object({
  ...envelope,
  kind: z.literal('camera_frame'),
  camera_id: CameraId,
  frame_id: z.string().min(1),
  /** Frame of the camera pose, e.g. "world_m_zup". */
  frame: z.string().optional(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  fps: finite.positive().optional(),
  encoding: z.enum(['png', 'jpeg', 'webp', 'svg', 'float32_apparent_c', 'float32_depth_m']),
  /** Image URI (http(s), blob: or data:). Raw float frames are colour-mapped by the adapter. */
  uri: z.string().min(1),
  intrinsics: z.array(z.array(finite).length(3)).length(3).optional(),
  camera_to_world: z.array(z.array(finite).length(4)).length(4).optional(),
  /** LWIR only: apparent (grey-body, emissivity-affected) temperature, never internal temperature. */
  units: z.enum(['apparent_c', 'depth_m', 'srgb']).optional(),
  range: z.tuple([finite, finite]).optional(),
  caption: z.string().optional(),
}).superRefine((m, ctx) => {
  if (m.camera_id === 'lwir' && (m.units !== 'apparent_c' || !m.range)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'LWIR frames need units "apparent_c" and a range' });
  }
});

/** Mirrors WarehouseSensors.sample() (sim/warehouse-v3/warehouse_sensors.py) plus the instrument poses. */
export const SensorReadingMsg = z.object({
  ...envelope,
  kind: z.literal('sensor_reading'),
  frame: z.literal(WORLD_FRAME),
  time_s: finite.nonnegative(),
  dose_timestamp_s: finite.nonnegative(),
  dose_rate_uSv_h: finite.nonnegative(),
  dose_integration_s: finite.positive(),
  mission_dose_mSv: finite.nonnegative(),
  temperature_c: finite,
  relative_humidity_pct: finite.min(0).max(100),
  hydrogen_ppm: finite.nonnegative().nullable(),
  hydrogen_status: z.enum(['detected', 'below_detection']),
  hydrogen_detection_limit_ppm: finite.positive(),
  /** Optional future channel. The current warehouse backend does not output methane. */
  methane_ppm: finite.nonnegative().nullable().optional(),
  methane_status: z.enum(['detected', 'below_detection']).optional(),
  methane_detection_limit_ppm: finite.positive().optional(),
  gamma_xyz_m: xyz,
  gas_inlet_xyz_m: xyz,
}).superRefine((m, ctx) => {
  if (m.hydrogen_status === 'below_detection' && m.hydrogen_ppm !== null) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'below_detection hydrogen must carry hydrogen_ppm: null' });
  }
  if (m.hydrogen_status === 'detected' && m.hydrogen_ppm === null) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'detected hydrogen needs a value' });
  }
});

/** Mirrors WarehouseSensors.gamma_bins(). Carries no source identity. */
export const GammaBearingMsg = z.object({
  ...envelope,
  kind: z.literal('gamma_bearing'),
  bearing_frame: z.literal('robot_yaw'),
  bin_count: z.literal(16),
  intensity_uSv_h: z.array(finite.nonnegative()).length(16),
  detector_xyz_m: xyz,
  yaw_rad: finite,
});

/** Mirrors WarehouseSensors.poll_swab() with status "complete". Samples one floor footprint only. */
export const SwabResultMsg = z.object({
  ...envelope,
  kind: z.literal('swab_result'),
  frame: z.literal(WORLD_FRAME),
  status: z.literal('complete'),
  time_s: finite.nonnegative(),
  contact_xyz: xyz,
  area_cm2: finite.positive(),
  alpha_bq_cm2: finite.nonnegative().nullable(),
  alpha_status: z.enum(['detected', 'below_detection']),
  alpha_detection_limit_bq_cm2: finite.positive(),
  beta_gamma_bq_cm2: finite.nonnegative().nullable(),
  beta_gamma_status: z.enum(['detected', 'below_detection']),
  beta_gamma_detection_limit_bq_cm2: finite.positive(),
  near_package_id: PackageId.optional(),
});

const EvidenceRef = z.object({
  kind: z.enum(['camera_frame', 'sensor_reading', 'gamma_bearing', 'swab_result', 'detection', 'log']),
  ref: z.string().min(1),
});
export type EvidenceRef = z.infer<typeof EvidenceRef>;

/** Detector contract from sim/warehouse-v3/DEFECTS.md: 0 drum, 1 corrosion, 2 bulge. */
export const DETECTOR_CLASSES = { 0: 'drum', 1: 'corrosion', 2: 'bulge' } as const;

export const DetectionEventMsg = z.object({
  ...envelope,
  kind: z.literal('detection'),
  detection_id: z.string().min(1),
  camera_id: CameraId,
  frame_id: z.string().min(1),
  class_id: z.union([z.literal(0), z.literal(1), z.literal(2)]),
  /** [x, y, w, h] in pixels of the referenced frame. */
  bbox_px: z.tuple([finite, finite, finite.positive(), finite.positive()]),
  /** Detector confidence for this box. It is not a package diagnosis. */
  confidence: finite.min(0).max(1),
  model_id: z.string().min(1),
  /** Package attribution needs its own evidence and may remain inconclusive. */
  drum_attribution: z.object({
    package_id: PackageId.nullable(),
    status: z.enum(['attributed', 'inconclusive']),
    evidence: z.array(EvidenceRef),
    note: z.string().optional(),
  }).optional(),
});

/**
 * One accepted ledger entry: a frame in which the mission verified the package
 * identity and capture quality. Mirrors WarehouseObservations.accept(package_id,
 * frame_id, view=..., finding=...). These records are the only input to coverage.
 */
export const InspectionRecordMsg = z.object({
  ...envelope,
  kind: z.literal('inspection_record'),
  run_id: z.string().optional(),
  package_id: PackageId,
  frame_id: z.string().min(1),
  /** Ledger view label. Coverage is "inspected" once both "front" and "oblique" exist. */
  view: z.string().min(1),
  /** Ledger finding for this frame, as produced by the mission. Null when none. */
  finding: z.union([z.string(), z.null()]).default(null),
  evidence: z.array(EvidenceRef).default([]),
});

export const InspectionFindingMsg = z.object({
  ...envelope,
  kind: z.literal('inspection_finding'),
  finding_id: z.string().min(1),
  /** Null when package attribution is inconclusive. */
  package_id: PackageId.nullable(),
  status: z.enum(['observation_only', 'inconclusive', 'finding']),
  summary: z.string().min(1),
  evidence: z.array(EvidenceRef),
  limits: z.array(z.string()).default([]),
  /** Reserved for a future assessment service. Null until one is connected. */
  assessment: z.null().default(null),
});

export const AlertMsg = z.object({
  ...envelope,
  kind: z.literal('alert'),
  alert_id: z.string().min(1),
  severity: z.enum(['info', 'warning', 'alert']),
  title: z.string().min(1),
  detail: z.string().optional(),
  package_id: PackageId.optional(),
  evidence: z.array(EvidenceRef).default([]),
  proposed_action: z.object({
    text: z.string().min(1),
    /** Proposals are displayed only. The console never sends them to the robot. */
    status: z.literal('proposed_not_sent'),
  }).optional(),
});

export const InboundMessage = z.union([
  MapSnapshotMsg, RunStateMsg, RobotPoseMsg, CameraFrameMsg, SensorReadingMsg, GammaBearingMsg,
  SwabResultMsg, DetectionEventMsg, InspectionRecordMsg, InspectionFindingMsg, AlertMsg,
]);

export type MapSnapshot = z.infer<typeof MapSnapshotMsg>;
export type RunState = z.infer<typeof RunStateMsg>;
export type RobotPose = z.infer<typeof RobotPoseMsg>;
export type CameraFrame = z.infer<typeof CameraFrameMsg>;
export type SensorReading = z.infer<typeof SensorReadingMsg>;
export type GammaBearing = z.infer<typeof GammaBearingMsg>;
export type SwabResult = z.infer<typeof SwabResultMsg>;
export type DetectionEvent = z.infer<typeof DetectionEventMsg>;
export type InspectionRecord = z.infer<typeof InspectionRecordMsg>;
export type InspectionFinding = z.infer<typeof InspectionFindingMsg>;
export type Alert = z.infer<typeof AlertMsg>;
export type Inbound = z.infer<typeof InboundMessage>;
export type InboundKind = Inbound['kind'];

const byKind = {
  map_snapshot: MapSnapshotMsg, run_state: RunStateMsg, robot_pose: RobotPoseMsg,
  camera_frame: CameraFrameMsg, sensor_reading: SensorReadingMsg, gamma_bearing: GammaBearingMsg,
  swab_result: SwabResultMsg, detection: DetectionEventMsg, inspection_record: InspectionRecordMsg,
  inspection_finding: InspectionFindingMsg, alert: AlertMsg,
} as const;

/** Validate by `kind` so schema errors name the right contract. */
export function parseInbound(raw: unknown): { ok: true; msg: Inbound } | { ok: false; error: string; kind?: string } {
  const kind = (raw as { kind?: unknown } | null)?.kind;
  if (typeof kind !== 'string' || !(kind in byKind)) {
    return { ok: false, error: `unknown or missing kind`, kind: typeof kind === 'string' ? kind : undefined };
  }
  const schema = byKind[kind as InboundKind];
  const result = schema.safeParse(raw);
  if (!result.success) {
    const issues = result.error.issues.slice(0, 4).map((i) => `${i.path.join('.') || '(root)'}: ${i.message}`);
    return { ok: false, error: issues.join('; '), kind };
  }
  return { ok: true, msg: result.data as Inbound };
}
