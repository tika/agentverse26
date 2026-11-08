import { useConsoleState, useTicker } from '../state/context';
import { sensorRows } from '../lib/sensorRows';
import { formatAge } from '../lib/values';
import { FixtureBadge, Panel, ValueCell } from './common';

export function Sensors({ detailed }: { detailed?: boolean }) {
  const state = useConsoleState();
  const wall = useTicker();
  const rows = sensorRows(state, wall);
  const r = state.sensor;
  return (
    <Panel title="Environmental sensors" id="sensors" className="sensors-panel"
      right={r ? <span className="dim">{r.fixture && <FixtureBadge />} <span className="mono">{r.msg.source.id}</span></span> : <span className="dim">no sensor feed</span>}>
      {!r && <div className="panel-reason">{state.feeds.sensors.status === 'not_configured' ? 'No sensor source connected. Readings appear only when a sensor_reading feed supplies them.' : `Sensor feed ${state.feeds.sensors.status.replace('_', ' ')}: ${state.feeds.sensors.detail}`}</div>}
      <table className="sensor-table" data-testid="sensor-table">
        <thead>
          <tr><th>Channel</th><th>Value</th>{detailed && <><th>t (sim)</th><th>Age</th><th>Quality</th><th>Source</th></>}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} data-channel={row.key}>
              <th scope="row">{row.label}{row.note && <div className="faint small">{row.note}</div>}</th>
              <td><ValueCell state={row.state} /></td>
              {detailed && <>
                <td className="num">{row.tSimS !== undefined ? `${row.tSimS.toFixed(1)} s` : '—'}</td>
                <td className="num">{formatAge(row.ageS)}</td>
                <td>{row.quality ?? '—'}</td>
                <td className="mono">{row.source ?? '—'}</td>
              </>}
            </tr>
          ))}
        </tbody>
      </table>
      {!detailed && r && <div className="faint small">t {r.msg.t_sim_s?.toFixed(1) ?? '—'} s · age {formatAge(rows[0].ageS)} · quality {r.msg.quality}</div>}
    </Panel>
  );
}

export function SensorHistory() {
  const state = useConsoleState();
  const hist = [...state.sensorHistory].reverse().slice(0, 40);
  return (
    <Panel title="Sensor reading history" id="sensor-history">
      {hist.length === 0 ? <div className="empty-reason">No readings received.</div> : (
        <table className="log-table">
          <thead><tr><th>t (s)</th><th>γ µSv/h</th><th>mSv</th><th>H₂</th><th>°C</th><th>RH %</th><th>Flags</th></tr></thead>
          <tbody>
            {hist.map((h, i) => (
              <tr key={i} className={h.late ? 'row-late' : ''}>
                <td className="num">{h.msg.t_sim_s?.toFixed(0)}</td>
                <td className="num">{h.msg.dose_rate_uSv_h.toFixed(2)}</td>
                <td className="num">{h.msg.mission_dose_mSv.toExponential(2)}</td>
                <td className="num">{h.msg.hydrogen_status === 'below_detection' ? `< ${h.msg.hydrogen_detection_limit_ppm} (BDL)` : h.msg.hydrogen_ppm?.toFixed(1)}</td>
                <td className="num">{h.msg.temperature_c.toFixed(1)}</td>
                <td className="num">{h.msg.relative_humidity_pct.toFixed(0)}</td>
                <td>{h.late ? 'late/out-of-order' : ''}{h.fixture ? ' fixture' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

export function GammaBearingPanel() {
  const state = useConsoleState();
  const g = state.gammaBearing?.msg;
  return (
    <Panel title="Gamma bearing (16 bins)" id="gamma-bearing" right={state.gammaBearing?.fixture ? <FixtureBadge /> : undefined}>
      {!g ? <div className="empty-reason">No directional gamma source connected. Bins carry no package identity.</div> : (
        <div className="bearing">
          <svg viewBox="-1.2 -1.2 2.4 2.4" className="bearing-svg" role="img" aria-label="Gamma bearing bins relative to robot yaw">
            {g.intensity_uSv_h.map((v, i) => {
              const max = Math.max(...g.intensity_uSv_h) || 1;
              const a0 = (i / 16) * 2 * Math.PI, a1 = ((i + 1) / 16) * 2 * Math.PI, r = 0.2 + 0.8 * (v / max);
              // bearing frame: 0 = robot forward (+x), counter-clockwise; screen Y flipped
              const p = (a: number, rr: number) => `${(rr * Math.cos(a)).toFixed(3)},${(-rr * Math.sin(a)).toFixed(3)}`;
              return <polygon key={i} points={`0,0 ${p(a0, r)} ${p(a1, r)}`} fill="var(--warn)" fillOpacity={0.25 + 0.6 * (v / max)} stroke="#111" strokeWidth={0.01} />;
            })}
            <line x1={0} y1={0} x2={1.1} y2={0} stroke="var(--robot)" strokeWidth={0.03} />
            <text x={0.75} y={-0.06} fontSize={0.14} fill="var(--robot)">fwd</text>
          </svg>
          <div className="faint small">Blurred synthetic bearing cue at detector ({g.detector_xyz_m.map((v) => v.toFixed(2)).join(', ')}) m. Elevated total dose can come from several packages; attribution needs additional poses.</div>
        </div>
      )}
    </Panel>
  );
}

export function SwabPanel() {
  const state = useConsoleState();
  return (
    <Panel title="Wipe (swab) results" id="swabs">
      {state.swabs.length === 0 ? <div className="empty-reason">No wipe results. A wipe samples one 100 cm² floor footprint and does not characterise a whole package.</div> : (
        <table className="log-table">
          <thead><tr><th>t (s)</th><th>Contact (m)</th><th>α Bq/cm²</th><th>β/γ Bq/cm²</th><th>Near</th></tr></thead>
          <tbody>
            {state.swabs.map((s, i) => (
              <tr key={i}>
                <td className="num">{s.msg.time_s}</td>
                <td className="num">({s.msg.contact_xyz.map((v) => v.toFixed(2)).join(', ')})</td>
                <td className="num">{s.msg.alpha_status === 'below_detection' ? `< ${s.msg.alpha_detection_limit_bq_cm2} · BDL` : s.msg.alpha_bq_cm2?.toFixed(2)}</td>
                <td className="num">{s.msg.beta_gamma_status === 'below_detection' ? `< ${s.msg.beta_gamma_detection_limit_bq_cm2} · BDL` : s.msg.beta_gamma_bq_cm2?.toFixed(2)}</td>
                <td className="mono">{s.msg.near_package_id ?? '—'} {s.fixture && <FixtureBadge />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
