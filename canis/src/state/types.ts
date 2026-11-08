import type {
  Alert, Assessment, CameraFrame, CameraId, DetectionEvent, GammaBearing, InspectionFinding, InspectionRecord,
  RobotPose, RunState, SensorReading, SwabResult,
} from '../contracts/messages';

export type Mode = 'offline' | 'replay' | 'live';

export type FeedStatus = 'not_configured' | 'connecting' | 'connected' | 'stale' | 'disconnected';

/** One logical feed per source family. A disconnect affects only that feed's panels. */
export type FeedId = 'isaac' | 'mission' | 'robot' | 'sensors' | 'detector' | 'assessment';

export const FEED_IDS: FeedId[] = ['isaac', 'mission', 'robot', 'sensors', 'detector', 'assessment'];

export interface FeedState {
  id: FeedId;
  label: string;
  status: FeedStatus;
  /** Free-text reason shown next to the status. */
  detail: string;
  sourceId?: string;
  fixture: boolean;
  lastReceiveMs?: number;
}

/** Wraps a validated message with boundary metadata. */
export interface Received<T> {
  msg: T;
  recvMs: number;
  /** True when the message arrived out of order or late; history only, never "current". */
  late: boolean;
  fixture: boolean;
}

export type LogLevel = 'info' | 'warn' | 'error';
export type LogCategory =
  | 'feed' | 'mode' | 'replay' | 'schema' | 'privacy' | 'duplicate' | 'out_of_order' | 'late' | 'stale' | 'map' | 'ui';

export interface LogEntry {
  id: number;
  wallMs: number;
  simS?: number;
  level: LogLevel;
  category: LogCategory;
  source: string;
  message: string;
  fixture: boolean;
}

export interface ConsoleState {
  mode: Mode;
  /** Bumped on every change, for useSyncExternalStore. */
  version: number;
  feeds: Record<FeedId, FeedState>;
  /** Current source clock (simulation seconds) when a source supplies one. */
  simClockS?: number;
  simClockSource?: string;
  replay?: { playing: boolean; step: number; total: number };
  runState?: Received<RunState>;
  pose?: Received<RobotPose>;
  poseHistory: Received<RobotPose>[];
  frames: Partial<Record<CameraId, Received<CameraFrame>>>;
  sensor?: Received<SensorReading>;
  sensorHistory: Received<SensorReading>[];
  gammaBearing?: Received<GammaBearing>;
  swabs: Received<SwabResult>[];
  detections: Received<DetectionEvent>[];
  inspections: Received<InspectionRecord>[];
  findings: Received<InspectionFinding>[];
  alerts: Received<Alert>[];
  /** Latest assessment per printed package (camera result layer + map). */
  assessments: Received<Assessment>[];
  acknowledged: Set<string>;
  logs: LogEntry[];
  /** Per channel stale flags, so we only log transitions. */
  stale: Partial<Record<StaleChannel, boolean>>;
}

export type StaleChannel = 'pose' | 'sensor' | 'run_state' | `frame:${CameraId}`;

