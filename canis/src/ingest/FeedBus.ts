import { parseInbound } from '../contracts/messages';
import { findPrivateKeys } from '../contracts/privacy';
import type { ConsoleStore } from '../state/store';
import { windowFor } from './freshness';

export type IngestResult =
  | 'accepted' | 'late' | 'duplicate' | 'out_of_order' | 'schema_failure' | 'privacy_reject' | 'mode_mismatch';

/**
 * The single ingest boundary. Every adapter (static, replay, live) passes raw
 * payloads here. Nothing else writes observations into the store.
 *
 * Order of checks:
 *  1. privacy guard: reject any payload carrying private truth keys (DATA_DICTIONARY layer 3)
 *  2. schema validation (zod, by kind)
 *  3. replay/live separation: fixture data is refused outside replay mode
 *  4. per (source.id, kind) sequence: equal → duplicate (dropped); lower → out of order (history only)
 *  5. lateness: source time older than the freshness window on arrival → history only
 */
export class FeedBus {
  private lastSeq = new Map<string, number>();

  constructor(private store: ConsoleStore) {}

  resetSequences() {
    this.lastSeq.clear();
  }

  ingest(raw: unknown, connection: string): IngestResult {
    const store = this.store;
    const leaks = findPrivateKeys(raw);
    if (leaks.length) {
      // Log key paths only, never values.
      store.log('error', 'privacy', connection,
        `Rejected payload containing private simulator truth keys: ${leaks.slice(0, 5).join(', ')}${leaks.length > 5 ? ' …' : ''}`);
      return 'privacy_reject';
    }
    const parsed = parseInbound(raw);
    if (!parsed.ok) {
      store.log('error', 'schema', connection, `Schema failure${parsed.kind ? ` (${parsed.kind})` : ''}: ${parsed.error}`,
        Boolean((raw as { source?: { fixture?: boolean } })?.source?.fixture));
      return 'schema_failure';
    }
    const msg = parsed.msg;
    const fixture = Boolean(msg.source.fixture);
    const mode = store.getState().mode;
    if (fixture && mode !== 'replay') {
      store.log('warn', 'feed', connection, `Dropped fixture ${msg.kind} outside DEMO REPLAY mode`);
      return 'mode_mismatch';
    }
    const key = `${msg.source.id}:${msg.kind}${msg.kind === 'camera_frame' ? `:${msg.camera_id}` : ''}`;
    const last = this.lastSeq.get(key);
    const recvMs = store.wallNow();
    if (last !== undefined && msg.seq === last) {
      store.log('warn', 'duplicate', msg.source.id, `Duplicate ${msg.kind} seq ${msg.seq} dropped`, fixture);
      return 'duplicate';
    }
    if (last !== undefined && msg.seq < last) {
      store.log('warn', 'out_of_order', msg.source.id,
        `Out-of-order ${msg.kind} seq ${msg.seq} after ${last}: kept in history, not shown as current`, fixture);
      store.apply(msg, recvMs, true);
      return 'out_of_order';
    }
    this.lastSeq.set(key, msg.seq);

    const simNow = store.getState().simClockS;
    const channel = msg.kind === 'robot_pose' ? 'pose' : msg.kind === 'sensor_reading' ? 'sensor'
      : msg.kind === 'camera_frame' ? (`frame:${msg.camera_id}` as const) : null;
    if (channel && msg.t_sim_s !== undefined && simNow !== undefined && simNow - msg.t_sim_s > windowFor(channel)) {
      store.log('warn', 'late', msg.source.id,
        `Late ${msg.kind} seq ${msg.seq}: source time ${msg.t_sim_s.toFixed(1)} s, clock ${simNow.toFixed(1)} s; history only`, fixture);
      store.apply(msg, recvMs, true);
      return 'late';
    }
    store.apply(msg, recvMs, false);
    return 'accepted';
  }
}
