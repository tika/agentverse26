import type { CameraId, Inbound } from '../contracts/messages';
import { ageSeconds, frameChannel, windowFor } from '../ingest/freshness';
import type {
  ConsoleState, FeedId, FeedState, FeedStatus, LogCategory, LogEntry, LogLevel, Mode, Received, StaleChannel,
} from './types';

const FEED_LABELS: Record<FeedId, string> = {
  isaac: 'Isaac Sim',
  mission: 'Mission',
  robot: 'Robot',
  sensors: 'Sensors',
  detector: 'Detector',
  assessment: 'Assessment',
};

/** Which feed (and therefore which panels) a message belongs to. */
export function feedForMessage(msg: Inbound): FeedId {
  switch (msg.kind) {
    case 'map_snapshot':
      return 'isaac';
    case 'run_state':
    case 'inspection_record':
      return 'mission';
    case 'camera_frame':
      if (msg.camera_id === 'third_person') return 'isaac';
      if (msg.camera_id === 'lwir') return 'sensors';
      return 'robot';
    case 'robot_pose':
      return 'robot';
    case 'sensor_reading':
    case 'gamma_bearing':
    case 'swab_result':
      return 'sensors';
    case 'detection':
      return 'detector';
    case 'inspection_finding':
    case 'alert':
    case 'assessment':
      return 'assessment';
  }
}

function initialFeeds(): Record<FeedId, FeedState> {
  const feeds = {} as Record<FeedId, FeedState>;
  (Object.keys(FEED_LABELS) as FeedId[]).forEach((id) => {
    feeds[id] = { id, label: FEED_LABELS[id], status: 'not_configured', detail: 'No source configured', fixture: false };
  });
  return feeds;
}

const HISTORY_LIMIT = 500;
const LOG_LIMIT = 2000;

export function initialState(mode: Mode = 'offline'): ConsoleState {
  return {
    mode,
    version: 0,
    feeds: initialFeeds(),
    poseHistory: [],
    frames: {},
    sensorHistory: [],
    swabs: [],
    detections: [],
    inspections: [],
    findings: [],
    alerts: [],
    assessments: [],
    acknowledged: new Set(),
    logs: [],
    stale: {},
  };
}

type Listener = () => void;

/**
 * Single in-memory store. Adapters never touch it directly: they hand raw
 * payloads to the FeedBus, which validates them and calls `apply`.
 */
export class ConsoleStore {
  private state: ConsoleState;
  private listeners = new Set<Listener>();
  private logSeq = 0;
  /** Wall clock source, injectable for tests. */
  wallNow: () => number;

  constructor(mode: Mode = 'offline', wallNow: () => number = () => Date.now()) {
    this.state = initialState(mode);
    this.wallNow = wallNow;
  }

  getState = (): ConsoleState => this.state;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private commit(patch: Partial<ConsoleState>) {
    this.state = { ...this.state, ...patch, version: this.state.version + 1 };
    this.listeners.forEach((l) => l());
  }

  /** Clear all data and logs-preserving reset for a new mode. Logs are kept so mode transitions stay visible. */
  reset(mode: Mode) {
    const logs = this.state.logs;
    const fresh = initialState(mode);
    this.state = { ...fresh, logs, version: this.state.version + 1 };
    this.listeners.forEach((l) => l());
  }

  log(level: LogLevel, category: LogCategory, source: string, message: string, fixture = false) {
    const entry: LogEntry = {
      id: ++this.logSeq,
      wallMs: this.wallNow(),
      simS: this.state.simClockS,
      level, category, source, message, fixture,
    };
    const logs = [...this.state.logs, entry];
    if (logs.length > LOG_LIMIT) logs.splice(0, logs.length - LOG_LIMIT);
    this.commit({ logs });
  }

  setFeed(id: FeedId, status: FeedStatus, detail: string, extra: Partial<FeedState> = {}) {
    const prev = this.state.feeds[id];
    if (prev.status === status && prev.detail === detail && !Object.keys(extra).length) return;
    this.commit({ feeds: { ...this.state.feeds, [id]: { ...prev, status, detail, ...extra } } });
  }

  setReplay(replay: ConsoleState['replay']) {
    this.commit({ replay });
  }

  /** Advance the source clock (simulation seconds) supplied by the active source. */
  setSimClock(simS: number | undefined, source?: string) {
    this.commit({ simClockS: simS, simClockSource: source });
  }

  acknowledge(alertId: string) {
    const acknowledged = new Set(this.state.acknowledged);
    acknowledged.add(alertId);
    this.commit({ acknowledged });
    this.log('info', 'ui', 'operator', `Alert ${alertId} acknowledged locally (not sent to any system)`);
  }

  now() {
    return { simS: this.state.simClockS, wallMs: this.wallNow() };
  }

  /** Apply one validated message. `late` messages are kept in history only. */
  apply(msg: Inbound, recvMs: number, late: boolean) {
    const fixture = Boolean(msg.source.fixture);
    const s = this.state;
    const feed = feedForMessage(msg);
    const feedPatch = {
      feeds: {
        ...s.feeds,
        [feed]: {
          ...s.feeds[feed],
          status: 'connected' as const,
          detail: fixture ? 'Demo replay fixture' : `Receiving from ${msg.source.id}`,
          sourceId: msg.source.id,
          fixture,
          lastReceiveMs: recvMs,
        },
      },
    };
    const wrap = <T>(m: T): Received<T> => ({ msg: m, recvMs, late, fixture });
    const push = <T>(list: T[], item: T) => {
      const next = [...list, item];
      if (next.length > HISTORY_LIMIT) next.splice(0, next.length - HISTORY_LIMIT);
      return next;
    };

    switch (msg.kind) {
      case 'map_snapshot':
        this.commit(feedPatch);
        return;
      case 'run_state':
        this.commit({
          ...feedPatch,
          runState: late ? s.runState : wrap(msg),
          ...(late || msg.sim_clock_s === undefined ? {} : { simClockS: msg.sim_clock_s, simClockSource: msg.source.id }),
        });
        return;
      case 'robot_pose':
        this.commit({ ...feedPatch, pose: late ? s.pose : wrap(msg), poseHistory: push(s.poseHistory, wrap(msg)) });
        return;
      case 'camera_frame':
        this.commit({ ...feedPatch, frames: late ? s.frames : { ...s.frames, [msg.camera_id]: wrap(msg) } });
        return;
      case 'sensor_reading':
        this.commit({ ...feedPatch, sensor: late ? s.sensor : wrap(msg), sensorHistory: push(s.sensorHistory, wrap(msg)) });
        return;
      case 'gamma_bearing':
        this.commit({ ...feedPatch, gammaBearing: late ? s.gammaBearing : wrap(msg) });
        return;
      case 'swab_result':
        this.commit({ ...feedPatch, swabs: push(s.swabs, wrap(msg)) });
        return;
      case 'detection':
        this.commit({ ...feedPatch, detections: push(s.detections, wrap(msg)) });
        return;
      case 'inspection_record':
        this.commit({ ...feedPatch, inspections: push(s.inspections, wrap(msg)) });
        return;
      case 'inspection_finding':
        this.commit({ ...feedPatch, findings: push(s.findings, wrap(msg)) });
        return;
      case 'alert':
        this.commit({ ...feedPatch, alerts: push(s.alerts, wrap(msg)) });
        return;
      case 'assessment':
        this.commit({ ...feedPatch, assessments: push(s.assessments, wrap(msg)) });
        return;
    }
  }

  /** Re-evaluate staleness for every channel and log transitions. Call on each tick. */
  evaluateStaleness() {
    const s = this.state;
    const now = this.now();
    const channels: [StaleChannel, { tSimS?: number; recvMs: number } | undefined, FeedId][] = [
      ['pose', s.pose && { tSimS: s.pose.msg.t_sim_s, recvMs: s.pose.recvMs }, 'robot'],
      ['sensor', s.sensor && { tSimS: s.sensor.msg.t_sim_s, recvMs: s.sensor.recvMs }, 'sensors'],
      ['run_state', s.runState && { tSimS: s.runState.msg.t_sim_s, recvMs: s.runState.recvMs }, 'mission'],
      ...(Object.entries(s.frames) as [CameraId, Received<{ t_sim_s?: number }>][]).map(
        ([id, f]) => [frameChannel(id), { tSimS: f.msg.t_sim_s, recvMs: f.recvMs }, feedForMessage({ kind: 'camera_frame', camera_id: id } as Inbound)] as [StaleChannel, { tSimS?: number; recvMs: number }, FeedId],
      ),
    ];
    const stale = { ...s.stale };
    const feeds = { ...s.feeds };
    const logs = [...s.logs];
    let changed = false;
    for (const [channel, sample, feed] of channels) {
      if (!sample) continue;
      const isStale = ageSeconds(sample, now) > windowFor(channel);
      if (Boolean(stale[channel]) !== isStale) {
        stale[channel] = isStale;
        changed = true;
        const age = ageSeconds(sample, now).toFixed(1);
        this.logSeq += 1;
        logs.push({
          id: this.logSeq, wallMs: now.wallMs, simS: now.simS,
          level: isStale ? 'warn' : 'info', category: 'stale', source: feeds[feed].sourceId ?? feed,
          message: isStale
            ? `${channel} stale: last sample ${age} s old (window ${windowFor(channel)} s)`
            : `${channel} fresh again`,
          fixture: feeds[feed].fixture,
        });
      }
    }
    // A feed whose every channel is stale is reported as stale in the header.
    (['robot', 'sensors', 'isaac', 'mission'] as FeedId[]).forEach((feed) => {
      const own = channels.filter(([, sample, f]) => f === feed && sample).map(([c]) => c);
      if (!own.length || feeds[feed].status === 'disconnected' || feeds[feed].status === 'not_configured') return;
      const allStale = own.every((c) => stale[c]);
      const status: FeedStatus = allStale ? 'stale' : 'connected';
      if (feeds[feed].status !== status) {
        feeds[feed] = { ...feeds[feed], status };
        changed = true;
      }
    });
    if (changed) this.commit({ stale, feeds, logs });
  }

  isStale(channel: StaleChannel): boolean {
    return Boolean(this.state.stale[channel]);
  }
}
