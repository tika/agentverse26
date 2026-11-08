import { useConsole, useConsoleState, useTicker } from '../state/context';
import { ageSeconds } from '../ingest/freshness';
import { formatAge, type ValueState } from '../lib/values';
import { packageStatuses } from '../lib/inspection';
import { FixtureBadge, Panel, ValueCell } from './common';

export function RobotStatus() {
  const state = useConsoleState();
  const { map } = useConsole();
  const wall = useTicker();
  const p = state.pose;
  const run = state.runState;
  const feed = state.feeds.robot;
  const stale = Boolean(state.stale.pose);
  const age = p ? ageSeconds({ tSimS: p.msg.t_sim_s, recvMs: p.recvMs }, { simS: state.simClockS, wallMs: wall }) : undefined;
  const reason = feed.status === 'not_configured' ? 'no feed' : `feed ${feed.status.replace('_', ' ')}`;
  const missing = (r = reason): ValueState => ({ kind: 'missing', reason: r });
  const text = (v: string | undefined, r?: string) => (v !== undefined ? <span className={`num ${stale ? 'val-stale' : ''}`}>{v}</span> : <ValueCell state={missing(r)} />);

  const cov = [...packageStatuses(state).values()];
  const inspectedN = cov.filter((c) => c.coverage === 'inspected').length;
  const seenN = cov.filter((c) => c.coverage === 'seen').length;
  const m = p?.msg;
  const rows: [string, React.ReactNode][] = [
    ['Operating mode', text(m?.operating_mode, m ? 'not supplied by robot feed' : undefined)],
    ['Position (x, y, z)', text(m && `(${m.xyz_m.map((v) => v.toFixed(2)).join(', ')}) m · ${m.frame}`)],
    ['Pose source', m ? (m.pose_source === 'simulator_pose'
      ? <span className="warn-text">SIMULATOR POSE · smoke-test only</span>
      : m.pose_source === 'estimated' ? <span>robot estimate</span> : <span className="faint">not stated by feed</span>)
      : <ValueCell state={missing()} />],
    ['Orientation (roll, pitch, yaw)', text(m && `(${m.rpy_deg.map((v) => v.toFixed(1)).join('°, ')}°)`)],
    ['Navigation confidence', text(m?.nav_confidence?.toFixed(2), m ? 'not supplied' : undefined)],
    ['Waypoint / target', text(run?.msg.waypoint !== undefined ? `${run.msg.waypoint}${run.msg.target_package_id ? ` → ${run.msg.target_package_id}` : ''}` : undefined,
      run ? 'not supplied' : 'no mission feed')],
    ['Battery', text(m?.battery_pct !== undefined ? `${m.battery_pct.toFixed(0)} %${m.battery_runtime_s ? ` (≈ ${Math.floor(m.battery_runtime_s / 3600)} h ${Math.round((m.battery_runtime_s % 3600) / 60)} m)` : ''}` : undefined, m ? 'not supplied' : undefined)],
    ['System health', m?.health ? <span className={`health health-${m.health}`}>{m.health === 'ok' ? '● OK' : m.health === 'degraded' ? '◐ DEGRADED' : '✕ FAULT'}</span> : <ValueCell state={missing(m ? 'not supplied' : reason)} />],
    ['Mission progress', <span className="num" data-testid="mission-progress">{inspectedN} inspected · {seenN} seen{run?.msg.planned_packages !== undefined
      ? ` / ${run.msg.planned_packages} planned` : ''} <span className="faint">· from ledger records only{run?.msg.planned_packages === undefined ? ', no plan supplied' : ''}</span></span>],
  ];
  return (
    <Panel title="Robot status / navigation" id="robot-status" className="status-panel"
      right={p ? <span className="dim">{p.fixture && <FixtureBadge />} age {formatAge(age)}{stale ? ' · STALE' : ''}</span> : <span className="dim">no telemetry</span>}>
      {!p && <div className="panel-reason">{feed.status === 'not_configured' ? 'No robot telemetry source connected. Values stay unavailable until a robot_pose feed supplies them.' : `Robot feed ${feed.status.replace('_', ' ')}: ${feed.detail}`}</div>}
      <dl className="kv" data-testid="robot-status">
        {rows.map(([k, v]) => (<div key={k} className="kv-row"><dt>{k}</dt><dd>{v}</dd></div>))}
      </dl>
      <div className="faint small">Spawn (static, map): ({map.robot_start_m.join(', ')}) m. Coverage counts come only from accepted ledger records (inspected = front + oblique views).</div>
    </Panel>
  );
}
