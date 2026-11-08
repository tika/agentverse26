import { useState } from 'react';
import { useConsole, useConsoleState } from '../state/context';
import { FixtureBadge, Panel, SeverityTag } from './common';

export function Alerts({ compact }: { compact?: boolean }) {
  const state = useConsoleState();
  const { store, selectPackage, openTab } = useConsole();
  const [sev, setSev] = useState<'' | 'info' | 'warning' | 'alert'>('');
  const [hideAcked, setHideAcked] = useState(false);
  const alerts = [...state.alerts].reverse()
    .filter((a) => !sev || a.msg.severity === sev)
    .filter((a) => !hideAcked || !state.acknowledged.has(a.msg.alert_id));
  return (
    <Panel title="Active alerts / proposed actions" id="alerts" className="alerts-panel"
      right={<span className="dim">read-only · nothing is sent to the robot</span>}>
      {!compact && (
        <div className="filters">
          <select aria-label="Severity filter" value={sev} onChange={(e) => setSev(e.target.value as typeof sev)}>
            <option value="">All severities</option><option value="alert">Alert</option><option value="warning">Warning</option><option value="info">Info</option>
          </select>
          <label className="check"><input type="checkbox" checked={hideAcked} onChange={(e) => setHideAcked(e.target.checked)} /> Hide acknowledged</label>
        </div>
      )}
      {alerts.length === 0 ? (
        <div className="empty-reason" data-testid="alerts-empty">
          {state.alerts.length ? 'No alerts match the filter.' : state.mode === 'offline' ? 'No alert source connected. Feed and data-quality events are in Logs.' : 'No alerts received.'}
        </div>
      ) : (
        <ul className="alert-list" data-testid="alert-list">
          {alerts.map((a) => {
            const acked = state.acknowledged.has(a.msg.alert_id);
            return (
              <li key={a.msg.alert_id} className={`alert alert-${a.msg.severity} ${acked ? 'acked' : ''}`}>
                <div className="alert-top">
                  <SeverityTag severity={a.msg.severity} />
                  <span className="alert-title">{a.msg.title}</span>
                  {a.fixture && <FixtureBadge label="DEMO FIXTURE" />}
                </div>
                {a.msg.detail && <div className="dim">{a.msg.detail}</div>}
                {a.msg.proposed_action && (
                  <div className="proposal"><span className="prop-tag">PROPOSED · NOT SENT</span> {a.msg.proposed_action.text}</div>
                )}
                <div className="alert-meta">
                  <span className="mono">{a.msg.source.id}</span>
                  <span className="num">t {a.msg.t_sim_s?.toFixed(0) ?? '—'} s</span>
                  {a.msg.package_id && <button className="link" onClick={() => selectPackage(a.msg.package_id)}>package {a.msg.package_id}</button>}
                  {a.msg.evidence.map((e) => (
                    <button key={e.ref} className="link" onClick={() => (e.kind === 'log' ? openTab('logs') : a.msg.package_id ? selectPackage(a.msg.package_id) : openTab('sensors'))}>
                      {e.kind}:{e.ref}
                    </button>
                  ))}
                  {acked ? <span className="faint">acknowledged (local)</span>
                    : <button className="ack" onClick={() => store.acknowledge(a.msg.alert_id)}>Acknowledge</button>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

export function Findings() {
  const state = useConsoleState();
  const { selectPackage } = useConsole();
  return (
    <Panel title="Findings (evidence summaries)" id="findings">
      {state.findings.length === 0 ? <div className="empty-reason">No findings. Detector and assessment conclusions are left to future integrations.</div> : (
        <ul className="alert-list">
          {[...state.findings].reverse().map((f) => (
            <li key={f.msg.finding_id} className="alert">
              <div className="alert-top">
                <span className={`ist ist-${f.msg.status === 'observation_only' ? 'inspected' : f.msg.status}`}>{f.msg.status.replace('_', ' ').toUpperCase()}</span>
                <span className="alert-title">{f.msg.summary}</span>
                {f.fixture && <FixtureBadge label="DEMO FIXTURE" />}
              </div>
              <div className="alert-meta">
                {f.msg.package_id ? <button className="link" onClick={() => selectPackage(f.msg.package_id)}>package {f.msg.package_id}</button> : <span className="faint">package attribution inconclusive</span>}
                {f.msg.evidence.map((e) => <span key={e.ref} className="mono faint">{e.kind}:{e.ref}</span>)}
              </div>
              {f.msg.limits.length > 0 && <ul className="limits">{f.msg.limits.map((l) => <li key={l}>{l}</li>)}</ul>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
