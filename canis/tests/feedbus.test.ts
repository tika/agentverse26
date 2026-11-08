import { describe, expect, it } from 'vitest';
import { ConsoleStore } from '../src/state/store';
import { FeedBus } from '../src/ingest/FeedBus';
import { sensorRows } from '../src/lib/sensorRows';
import { formatValueState } from '../src/lib/values';

function reading(seq: number, t: number, extra: Record<string, unknown> = {}) {
  return {
    schema: 'canis.v1', kind: 'sensor_reading', source: { id: 'isaac-relay', kind: 'isaac' }, seq, t_sim_s: t, quality: 'ok',
    frame: 'world_m_zup', time_s: t, dose_timestamp_s: t, dose_rate_uSv_h: 1.81, dose_integration_s: 2, mission_dose_mSv: 0,
    temperature_c: 18.9, relative_humidity_pct: 62, hydrogen_ppm: null, hydrogen_status: 'below_detection',
    hydrogen_detection_limit_ppm: 2, gamma_xyz_m: [1, 6, 0.55], gas_inlet_xyz_m: [1, 6, 1], ...extra,
  };
}

function setup(mode: 'offline' | 'replay' | 'live' = 'live') {
  let wall = 1_000_000;
  const store = new ConsoleStore(mode, () => wall);
  const bus = new FeedBus(store);
  return { store, bus, advance: (ms: number) => { wall += ms; } };
}

describe('offline state', () => {
  it('has no observations and every sensor unavailable', () => {
    const { store } = setup('offline');
    const s = store.getState();
    expect(s.sensor).toBeUndefined();
    expect(s.pose).toBeUndefined();
    expect(s.inspections).toHaveLength(0);
    expect(s.simClockS).toBeUndefined();
    const rows = sensorRows(s, Date.now());
    expect(rows.filter((r) => r.key !== 'ch4').every((r) => r.state.kind === 'missing')).toBe(true);
    expect(rows.find((r) => r.key === 'ch4')!.state.kind).toBe('not_supplied');
  });
});

describe('FeedBus boundary', () => {
  it('accepts a WarehouseSensors.sample()-shaped reading', () => {
    const { store, bus } = setup();
    expect(bus.ingest(reading(0, 0), 'test')).toBe('accepted');
    expect(store.getState().feeds.sensors.status).toBe('connected');
  });

  it('renders below-detection hydrogen as a limit, never zero', () => {
    const { store, bus } = setup();
    bus.ingest(reading(0, 0), 'test');
    const h2 = sensorRows(store.getState(), 0).find((r) => r.key === 'h2')!;
    expect(h2.state.kind).toBe('below_detection');
    const text = formatValueState(h2.state);
    expect(text).toBe('< 2 ppm · BELOW DETECTION');
    expect(text).not.toMatch(/(^|\s)0(\.0+)?\s*ppm/);
  });

  it('rejects below_detection hydrogen carrying a 0 value (schema failure)', () => {
    const { store, bus } = setup();
    expect(bus.ingest(reading(0, 0, { hydrogen_ppm: 0 }), 'test')).toBe('schema_failure');
    expect(store.getState().sensor).toBeUndefined();
    expect(store.getState().logs.at(-1)!.category).toBe('schema');
  });

  it('drops duplicates and keeps out-of-order data out of "current"', () => {
    const { store, bus } = setup();
    bus.ingest(reading(5, 10), 'test');
    expect(bus.ingest(reading(5, 10), 'test')).toBe('duplicate');
    expect(bus.ingest(reading(3, 6, { dose_rate_uSv_h: 99 }), 'test')).toBe('out_of_order');
    const s = store.getState();
    expect(s.sensor!.msg.dose_rate_uSv_h).toBe(1.81);
    expect(s.sensorHistory.at(-1)!.late).toBe(true);
    expect(s.logs.map((l) => l.category)).toEqual(expect.arrayContaining(['duplicate', 'out_of_order']));
  });

  it('marks data older than the freshness window as late', () => {
    const { store, bus } = setup();
    store.setSimClock(100, 'test');
    expect(bus.ingest(reading(0, 50), 'test')).toBe('late');
    expect(store.getState().sensor).toBeUndefined();
  });

  it('turns readings stale on the source clock and logs the transition', () => {
    const { store, bus } = setup();
    store.setSimClock(0);
    bus.ingest(reading(0, 0), 'test');
    store.setSimClock(20);
    store.evaluateStaleness();
    const s = store.getState();
    expect(s.stale.sensor).toBe(true);
    expect(s.feeds.sensors.status).toBe('stale');
    expect(s.logs.some((l) => l.category === 'stale')).toBe(true);
    const dose = sensorRows(s, 0).find((r) => r.key === 'dose')!;
    expect(dose.state.kind === 'value' && dose.state.stale).toBe(true);
  });

  it('rejects payloads with private simulator truth and logs only key paths', () => {
    const { store, bus } = setup();
    const leaky = reading(0, 0, { thermal: { internal_c: 31.2, emissivity: 0.48 } });
    expect(bus.ingest(leaky, 'test')).toBe('privacy_reject');
    const log = store.getState().logs.at(-1)!;
    expect(log.category).toBe('privacy');
    expect(log.message).toContain('internal_c');
    expect(log.message).not.toContain('31.2');
    expect(bus.ingest({ physical_inventory: { drums: [] } }, 'test')).toBe('privacy_reject');
  });

  it('refuses fixture data outside replay mode', () => {
    const { bus } = setup('live');
    const r = reading(0, 0);
    expect(bus.ingest({ ...r, source: { ...r.source, fixture: true } }, 'test')).toBe('mode_mismatch');
  });

  it('isolates feeds: a sensor reading does not mark the robot connected', () => {
    const { store, bus } = setup();
    bus.ingest(reading(0, 0), 'test');
    expect(store.getState().feeds.robot.status).toBe('not_configured');
  });
});
