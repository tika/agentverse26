import type { SensorReading } from '../contracts/messages';
import type { ConsoleState, Received } from '../state/types';
import { ageSeconds } from '../ingest/freshness';
import type { ValueState } from './values';

export interface SensorRow {
  key: string;
  label: string;
  state: ValueState;
  source?: string;
  tSimS?: number;
  ageS?: number;
  quality?: string;
  fixture?: boolean;
  note?: string;
}

const NO_FEED = 'no feed';

export function sensorRows(state: ConsoleState, wallMs: number): SensorRow[] {
  const r = state.sensor as Received<SensorReading> | undefined;
  const feed = state.feeds.sensors;
  const missingReason = feed.status === 'not_configured' ? NO_FEED : `feed ${feed.status.replace('_', ' ')}, no reading yet`;
  const stale = Boolean(state.stale.sensor);
  const age = r ? ageSeconds({ tSimS: r.msg.t_sim_s, recvMs: r.recvMs }, { simS: state.simClockS, wallMs }) : undefined;
  const invalid = r?.msg.quality === 'invalid';

  const base = (key: string, label: string, pick: (m: SensorReading) => ValueState, note?: string): SensorRow => {
    if (!r) return { key, label, state: { kind: 'missing', reason: missingReason }, note };
    return {
      key, label, note,
      state: invalid ? { kind: 'invalid', reason: 'source flagged quality invalid' } : pick(r.msg),
      source: r.msg.source.id, tSimS: r.msg.t_sim_s, ageS: age, quality: r.msg.quality, fixture: r.fixture,
    };
  };
  const num = (value: number, unit: string, digits: number): ValueState => ({ kind: 'value', value, unit, digits, stale, ageS: age });

  return [
    base('dose', 'Gamma dose rate (total)', (m) => num(m.dose_rate_uSv_h, 'µSv/h', 2),
      r ? `detector @ (${r.msg.gamma_xyz_m.map((v) => v.toFixed(2)).join(', ')}) m · ${r.msg.dose_integration_s} s integration` : 'total reading at the detector pose; not attributed to a package'),
    base('mission_dose', 'Cumulative mission dose', (m) => num(m.mission_dose_mSv, 'mSv', 6)),
    base('h2', 'Hydrogen (H₂) at inlet', (m) => m.hydrogen_status === 'below_detection'
      ? { kind: 'below_detection', limit: m.hydrogen_detection_limit_ppm, unit: 'ppm', stale, ageS: age }
      : num(m.hydrogen_ppm as number, 'ppm', 1),
    r ? `inlet @ (${r.msg.gas_inlet_xyz_m.map((v) => v.toFixed(2)).join(', ')}) m · below detection ≠ absent` : 'local air at the inlet; below detection ≠ absent'),
    base('temp', 'Ambient temperature', (m) => num(m.temperature_c, '°C', 1)),
    base('rh', 'Relative humidity', (m) => num(m.relative_humidity_pct, '%', 0)),
    (() => {
      const row = base('ch4', 'Methane (CH₄) · optional', (m) => m.methane_status === undefined
        ? { kind: 'not_supplied', reason: 'optional, not in this feed' }
        : m.methane_status === 'below_detection'
          ? { kind: 'below_detection', limit: m.methane_detection_limit_ppm ?? NaN, unit: 'ppm', stale, ageS: age }
          : num(m.methane_ppm as number, 'ppm', 1));
      if (!r) row.state = { kind: 'not_supplied', reason: 'optional channel' };
      return row;
    })(),
  ];
}
