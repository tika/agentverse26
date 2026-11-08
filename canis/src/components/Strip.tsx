import { useConsole, useConsoleState, useTicker } from '../state/context';
import { ageSeconds } from '../ingest/freshness';
import { sensorRows } from '../lib/sensorRows';
import { packageStatuses } from '../lib/inspection';
import { formatAge, type ValueState } from '../lib/values';
import { FixtureBadge, Panel, SeverityTag, ValueCell } from './common';

/** Compact robot status for the single-screen Simulation tab. */
export function StatusStrip() {
  const state = useConsoleState();
  const wall = useTicker();
  const p = state.pose;
  const run = state.runState?.msg;
  const feed = state.feeds.robot;
  const m = p?.msg;
  const stale = Boolean(state.stale.pose);
  const age = p ? ageSeconds({ tSimS: m!.t_sim_s, recvMs: p.recvMs }, { simS: state.simClockS, wallMs: wall }) : undefined;
  const missing: ValueState = { kind: 'missing', reason: feed.status === 'not_configured' ? 'no feed' : feed.status.replace('_', ' ') };
  const v = (text: string | undefined, fallback: ValueState = missing) =>
    text !== undefined ? <span className={`num ${stale ? 'val-stale' : ''}`}>{text}</span> : <ValueCell state={fallback} />;
  const cov = [...packageStatuses(state).values()];
  const cells: [string, React.ReactNode][] = [
    ['Mode', v(m?.operating_mode, m ? { kind: 'missing', reason: 'not supplied' } : missing)],
    ['Position', v(m && `(${m.xyz_m.map((x) => x.toFixed(2)).join(', ')}) m`)],
    ['Heading', v(m && `${m.rpy_deg[2].toFixed(1)}°`)],
    ['Pose source', m ? (m.pose_source === 'simulator_pose' ? <span className="warn-text">SIM POSE · smoke test</span>
      : <span>{m.pose_source ?? 'not stated'}</span>) : <ValueCell state={missing} />],
    ['Waypoint → target', v(run?.waypoint !== undefined ? `${run.waypoint}${run.target_package_id ? ` → ${run.target_package_id}` : ''}` : undefined,
      { kind: 'missing', reason: run ? 'not supplied' : 'no mission feed' })],
    ['Battery', v(m?.battery_pct !== undefined ? `${m.battery_pct.toFixed(0)} %` : undefined, m ? { kind: 'missing', reason: 'not supplied' } : missing)],
    ['Health', m?.health ? <span className={`health health-${m.health}`}>{m.health === 'ok' ? '● OK' : m.health === 'degraded' ? '◐ DEGRADED' : '✕ FAULT'}</span>
      : <ValueCell state={m ? { kind: 'missing', reason: 'not supplied' } : missing} />],
    ['Progress', <span className="num" data-testid="mission-progress">✓{cov.filter((c) => c.coverage === 'inspected').length} ◐{cov.filter((c) => c.coverage === 'seen').length}{run?.planned_packages !== undefined ? ` / ${run.planned_packages} planned` : ' · no plan'}</span>],
  ];
  return (
    <Panel title="Robot status" id="robot-status" className="strip-panel"
      right={p ? <span className="dim">{p.fixture && <FixtureBadge />} age {formatAge(age)}{stale ? ' · STALE' : ''}</span> : <span className="dim">no robot telemetry</span>}>
      <dl className="cells" data-testid="robot-status">
        {cells.map(([k, val]) => <div key={k} className="cell"><dt>{k}</dt><dd>{val}</dd></div>)}
      </dl>
    </Panel>
  );
}

const SHORT: Record<string, string> = {
  dose: 'Dose rate γ', mission_dose: 'Mission dose', h2: 'H₂ at inlet', temp: 'Air temp', rh: 'Humidity', ch4: 'CH₄ (optional)',
};

export function SensorStrip() {
  const state = useConsoleState();
  const wall = useTicker();
  const rows = sensorRows(state, wall);
  const r = state.sensor;
  return (
    <Panel title="Environmental sensors" id="sensors" className="strip-panel"
      right={r ? <span className="dim">{r.fixture && <FixtureBadge />} t {r.msg.t_sim_s?.toFixed(0) ?? '—'} s · age {formatAge(rows[0].ageS)} · {r.msg.quality}</span> : <span className="dim">no sensor feed</span>}>
      <dl className="cells cells-3" data-testid="sensor-table">
        {rows.map((row) => (
          <div key={row.key} className="cell" data-channel={row.key} title={row.note}>
            <dt>{SHORT[row.key] ?? row.label}</dt><dd><ValueCell state={row.state} /></dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

export function AlertStrip() {
  const state = useConsoleState();
  const { openTab, selectPackage } = useConsole();
  const recent = [...state.alerts].reverse().filter((a) => !state.acknowledged.has(a.msg.alert_id)).slice(0, 3);
  return (
    <Panel title="Alerts / proposed actions" id="alerts" className="strip-panel"
      right={<button className="link" onClick={() => openTab('alerts')}>all alerts ({state.alerts.length})</button>}>
      {recent.length === 0 ? (
        <div className="empty-reason" data-testid="alerts-empty">
          {state.alerts.length ? 'All alerts acknowledged.' : state.mode === 'offline' ? 'No alert source connected. Feed and data-quality events are in Logs.' : 'No alerts received.'}
        </div>
      ) : (
        <ul className="alert-lines" data-testid="alert-list">
          {recent.map((a) => (
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
