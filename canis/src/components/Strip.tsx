import { AlertTriangle, Bot, CircleCheck, Activity } from 'lucide-react';
import { useConsole, useConsoleState, useTicker } from '../state/context';
import { ageSeconds } from '../ingest/freshness';
import { sensorRows, type SensorRow } from '../lib/sensorRows';
import { packageStatuses } from '../lib/inspection';
import { formatAge } from '../lib/values';
import { EmptyState, FixtureBadge, Panel, Pill, SeverityTag } from './common';

function Dash({ unit }: { unit?: string }) {
  return <span className="dash" data-state="missing">— {unit && <span className="unit">{unit}</span>}</span>;
}

/** Compact robot status for the single-screen Simulation tab. */
export function StatusStrip() {
  const state = useConsoleState();
  const { map } = useConsole();
  const wall = useTicker();
  const p = state.pose;
  const run = state.runState?.msg;
  const m = p?.msg;
  const stale = Boolean(state.stale.pose);
  const age = p ? ageSeconds({ tSimS: m!.t_sim_s, recvMs: p.recvMs }, { simS: state.simClockS, wallMs: wall }) : undefined;
  const val = (text: string | undefined, unit?: string) =>
    text !== undefined ? <span className={`num ${stale ? 'val-stale' : ''}`}>{text}{unit && <span className="unit"> {unit}</span>}</span> : <Dash unit={unit} />;
  const unavailable = <span data-state="missing"><Pill>UNAVAILABLE</Pill></span>;

  const cov = [...packageStatuses(state).values()];
  const inspected = cov.filter((c) => c.coverage === 'inspected').length;
  const seen = cov.filter((c) => c.coverage === 'seen').length;
  const denominator = run?.planned_packages ?? map.drums.length;
  const pct = denominator ? (100 * inspected) / denominator : 0;
  const dose = state.sensor;

  const left: [string, React.ReactNode][] = [
    ['Mode', m?.operating_mode ? <span className="num">{m.operating_mode}</span> : unavailable],
    ['Status', m?.health ? <span className={`health health-${m.health}`}>{m.health === 'ok' ? '● OK' : m.health === 'degraded' ? '◐ DEGRADED' : '✕ FAULT'}</span> : unavailable],
    ['Position (x, y, θ)', val(m && `(${m.xyz_m[0].toFixed(2)}, ${m.xyz_m[1].toFixed(2)}, ${m.rpy_deg[2].toFixed(1)}°)`)],
    ['Heading', m ? <span className="num">{m.rpy_deg[2].toFixed(1)}° {m.pose_source === 'simulator_pose' ? <span className="warn-text">· SIM POSE</span> : m.pose_source === 'estimated' ? '· estimate' : ''}</span> : <Dash />],
    ['Waypoint / Target', val(run?.waypoint !== undefined ? `${run.waypoint}${run.target_package_id ? ` → ${run.target_package_id}` : ''}` : undefined)],
  ];
  const right: [string, React.ReactNode][] = [
    ['Progress', <span className="num" data-testid="mission-progress">{pct.toFixed(1)} %<span className="faint"> · ✓{inspected} ◐{seen}{run?.planned_packages !== undefined ? ` / ${run.planned_packages}` : ` / ${map.drums.length}`}</span></span>],
    ['__bar__', null],
    ['Mission dose', val(dose ? dose.msg.mission_dose_mSv.toFixed(6) : undefined, 'mSv')],
    ['Radiation (γ)', val(dose ? dose.msg.dose_rate_uSv_h.toFixed(2) : undefined, 'µSv/h')],
    ['Battery', val(m?.battery_pct !== undefined ? m.battery_pct.toFixed(0) : undefined, '%')],
  ];
  return (
    <Panel title="Robot status" icon={Bot} id="robot-status" className="strip-panel"
      right={p ? <span className="dim">{p.fixture && <FixtureBadge />} age {formatAge(age)}{stale ? ' · STALE' : ''}</span> : <Pill>No robot telemetry</Pill>}>
      <div className="two-col" data-testid="robot-status">
        <dl className="kvt">{left.map(([k, v]) => <div key={k} className="kvt-row"><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        <dl className="kvt">
          {right.map(([k, v]) => k === '__bar__'
            ? <div key={k} className="progress" aria-hidden><span style={{ width: `${Math.min(100, pct)}%` }} /></div>
            : <div key={k} className="kvt-row"><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
      </div>
    </Panel>
  );
}

const UNIT: Record<string, string> = { dose: 'µSv/h', mission_dose: 'mSv', h2: 'ppm', temp: '°C', rh: '%RH', ch4: 'ppm', pressure: 'kPa' };
const LABEL: Record<string, React.ReactNode> = {
  dose: 'Dose rate (γ)', temp: 'Air temp.', rh: 'Humidity', h2: <>H<sub>2</sub> (at inlet)</>, ch4: <>CH<sub>4</sub> (optional)</>, pressure: 'Air pressure',
};

function valueText(row: SensorRow): string {
  const s = row.state;
  switch (s.kind) {
    case 'value': return `${s.value.toFixed(s.digits)} ${UNIT[row.key] ?? s.unit}`;
    case 'below_detection': return `< ${s.limit} ${UNIT[row.key] ?? s.unit}`;
    default: return `— ${UNIT[row.key] ?? ''}`;
  }
}

function statusText(row: SensorRow): { text: string; tone: string } {
  const s = row.state;
  switch (s.kind) {
    case 'value': return s.stale ? { text: `STALE ${formatAge(s.ageS)}`, tone: 'warn' } : { text: 'OK', tone: 'ok' };
    case 'below_detection': return s.stale ? { text: `BELOW DL · STALE`, tone: 'warn' } : { text: 'BELOW DETECTION', tone: 'info' };
    case 'invalid': return { text: 'INVALID', tone: 'alert' };
    case 'not_supplied': return { text: row.source ? 'N/S' : '—', tone: 'faint' };
    case 'missing': return { text: '—', tone: 'faint' };
  }
}

export function SensorStrip() {
  const state = useConsoleState();
  const wall = useTicker();
  const rows = sensorRows(state, wall);
  const byKey = new Map(rows.map((r) => [r.key, r]));
  const r = state.sensor;
  const table = (keys: string[]) => (
    <table className="sensor-mini">
      <thead><tr><th>Sensor</th><th>Value</th><th>Status</th></tr></thead>
      <tbody>
        {keys.map((k) => {
          const row = byKey.get(k)!;
          const st = statusText(row);
          return (
            <tr key={k} data-channel={k} title={row.note}>
              <th scope="row">{LABEL[k]}</th>
              <td className="num" data-state={row.state.kind === 'value' || row.state.kind === 'below_detection' ? (row.state.stale ? 'stale' : row.state.kind) : row.state.kind}>{valueText(row)}</td>
              <td className={`st st-${st.tone}`}>{st.text}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
  return (
    <Panel title="Environmental sensors" icon={Activity} id="sensors" className="strip-panel"
      right={r ? <span className="dim">{r.fixture && <FixtureBadge />} t {r.msg.t_sim_s?.toFixed(0) ?? '—'} s · age {formatAge(rows[0].ageS)} · {r.msg.quality}</span>
        : <Pill>{state.feeds.sensors.status === 'not_configured' ? 'No sensor feed' : `Sensor feed ${state.feeds.sensors.status.replace('_', ' ')}`}</Pill>}>
      <div className="two-col" data-testid="sensor-table">
        {table(['dose', 'temp', 'rh'])}
        {table(['h2', 'ch4', 'pressure'])}
      </div>
    </Panel>
  );
}

export function AlertStrip() {
  const state = useConsoleState();
  const { openTab, selectPackage } = useConsole();
  const active = [...state.alerts].reverse().filter((a) => !state.acknowledged.has(a.msg.alert_id));
  return (
    <Panel title="Alerts / proposed actions" icon={AlertTriangle} id="alerts" className="strip-panel"
      right={<button className="pill pill-neutral pill-btn" onClick={() => openTab('alerts')} aria-label="Open the Alerts tab">{active.length} active</button>}>
      {active.length === 0 ? (
        <div className="slot-fill" data-testid="alerts-empty">
          <EmptyState icon={CircleCheck} title={state.alerts.length ? 'All Alerts Acknowledged' : 'No Alerts'}
            reason={state.mode === 'offline' ? 'No alert source connected. Feed and data-quality events are in Logs.' : 'No unacknowledged alerts.'} />
        </div>
      ) : (
        <ul className="alert-lines" data-testid="alert-list">
          {active.slice(0, 3).map((a) => (
            <li key={a.msg.alert_id} className={`alert-line alert-${a.msg.severity}`}>
              <SeverityTag severity={a.msg.severity} />
              <button className="alert-line-title" onClick={() => a.msg.package_id ? selectPackage(a.msg.package_id) : openTab('alerts')}>{a.msg.title}</button>
              {a.msg.proposed_action && <span className="prop-tag">PROPOSED · NOT SENT</span>}
              {a.fixture && <FixtureBadge label="DEMO FIXTURE" />}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
