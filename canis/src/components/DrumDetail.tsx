import { useConsole, useConsoleState } from '../state/context';
import { DETECTOR_CLASSES } from '../contracts/messages';
import { packageStatuses, statusOf, REQUIRED_VIEWS } from '../lib/inspection';
import { FixtureBadge } from './common';

const CONTEXT_RADIUS_M = 3;

export function DrumDetail() {
  const { map, selectedDrumId, selectDrum } = useConsole();
  const state = useConsoleState();
  const d = map.drums.find((x) => x.id === selectedDrumId);
  if (!d) return null;
  const code = d.location_code;
  const st = statusOf(packageStatuses(state), d);
  const records = state.inspections.filter((r) => r.msg.package_id === code);
  const detections = state.detections.filter((x) => x.msg.drum_attribution?.package_id === code);
  const findings = state.findings.filter((f) => f.msg.package_id === code);
  const near = (xyz: [number, number, number]) => Math.hypot(xyz[0] - d.x_m, xyz[1] - d.y_m) <= CONTEXT_RADIUS_M;
  const doseContext = state.sensorHistory.filter((s) => !s.late && near(s.msg.gamma_xyz_m)).slice(-6);
  const swabs = state.swabs.filter((s) => s.msg.near_package_id === code || Math.hypot(s.msg.contact_xyz[0] - d.x_m, s.msg.contact_xyz[1] - d.y_m) < 1.5);

  const known: [string, string][] = [
    ['Drum ID (canonical)', d.id],
    ['Printed location code', d.location_code],
    ['Waste class', d.category],
    ['Zone · row', `${d.zone} · ${d.row}`],
    ['Rack / stack', d.stack_id],
    ['Lane · side · column', `${d.lane} · ${d.side} · ${d.column}`],
    ['Tier', `T${d.tier} of ${d.tier_count}`],
    ['Depth (row position)', String(d.depth)],
    ['Dimensions', `Ø ${(d.radius_m * 2).toFixed(3)} m × ${d.height_m.toFixed(2)} m (${d.category === 'LLW' ? '208 L' : '500 L'} nominal)`],
    ['Base position (x, y, z)', `(${d.x_m.toFixed(3)}, ${d.y_m.toFixed(3)}, ${d.base_z_m.toFixed(3)}) m`],
    ['Yaw', `${(d.yaw_rad * 180 / Math.PI).toFixed(1)}°`],
    ['Inspection aisle', `aisle ${d.facing_aisle} · route y = ${d.inspection_route_y_m} m · print faces ${d.face_sign > 0 ? '+Y' : '−Y'}`],
    ['USD prim', d.prim_path],
  ];

  return (
    <aside className="drawer" role="dialog" aria-labelledby="drum-detail-title" data-testid="drum-detail">
      <header className="drawer-head">
        <h2 id="drum-detail-title"><span className="mono">{d.id}</span> · <span className="mono">{d.location_code}</span> <span className={`cat cat-${d.category}`}>{d.category}</span></h2>
        <span className={`ist ist-${st.coverage}`}>{st.coverage.toUpperCase()}</span>
        <button onClick={() => selectDrum(null)} aria-label="Close drum detail">✕</button>
      </header>
      <div className="drawer-body">
        <section>
          <h3>1 · Known inventory <span className="faint">public map</span></h3>
          <dl className="kv">{known.map(([k, v]) => <div key={k} className="kv-row"><dt>{k}</dt><dd className="mono">{v}</dd></div>)}</dl>
        </section>

        <section>
          <h3>2 · Observations <span className="faint">accepted ledger records &amp; detections</span></h3>
          <p className="faint small">Coverage: <strong>{st.coverage}</strong> · views {st.views.length ? st.views.join(', ') : 'none'} · needs {REQUIRED_VIEWS.join(' + ')} for inspected.</p>
          {records.length === 0 && detections.length === 0 ? <p className="empty-reason">No inspection records or attributed detections for this drum.</p> : (
            <ul className="obs">
              {records.map((r) => (
                <li key={`${r.msg.source.id}:${r.msg.frame_id}:${r.msg.view}`} className={r.late ? 'row-late' : ''}>
                  <span className="num">t {r.msg.t_sim_s?.toFixed(0) ?? '—'} s</span> Ledger record · view <strong>{r.msg.view}</strong> · frame <span className="mono">{r.msg.frame_id}</span>
                  {r.msg.finding && <> · finding “{r.msg.finding}”</>}{r.msg.run_id && <> · run <span className="mono">{r.msg.run_id}</span></>} · src <span className="mono">{r.msg.source.id}</span>
                  {r.late && ' · late/out-of-order'} {r.fixture && <FixtureBadge />}
                </li>
              ))}
              {detections.map((x) => (
                <li key={x.msg.detection_id}>
                  <span className="num">t {x.msg.t_sim_s?.toFixed(0) ?? '—'} s</span> Detection <span className="mono">{x.msg.detection_id}</span>: {DETECTOR_CLASSES[x.msg.class_id]} · detector confidence <span className="num">{x.msg.confidence.toFixed(2)}</span> on frame <span className="mono">{x.msg.frame_id}</span>
                  · attribution {x.msg.drum_attribution?.status}{x.msg.drum_attribution?.note ? ` (${x.msg.drum_attribution.note})` : ''} {x.fixture && <FixtureBadge />}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h3>3 · Supporting evidence</h3>
          <div className="evidence-grid">
            <EvidenceSlot title="Images (RGB)" body={detections.length ? `${detections.length} frame reference(s): ${detections.map((x) => x.msg.frame_id).join(', ')}` : 'No image evidence linked.'} />
            <EvidenceSlot title="Depth / deformation" body="Reserved: aligned depth or silhouette compared to the nominal drum profile. No depth evidence linked." />
            <EvidenceSlot title="Apparent LWIR" body="Reserved: apparent °C at comparable view angles. No thermal evidence linked. Apparent ≠ internal temperature." />
            <EvidenceSlot title={`Dose context (≤ ${CONTEXT_RADIUS_M} m)`} body={doseContext.length
              ? doseContext.map((s) => `t ${s.msg.t_sim_s?.toFixed(0)} s: ${s.msg.dose_rate_uSv_h.toFixed(2)} µSv/h total at detector (${s.msg.gamma_xyz_m.slice(0, 2).map((v) => v.toFixed(1)).join(', ')})`).join('\n')
              : 'No readings with a detector pose near this drum. Total dose is not a per-package value.'} fixture={doseContext.some((s) => s.fixture)} />
            <EvidenceSlot title="Wipe results" body={swabs.length
              ? swabs.map((s) => `t ${s.msg.time_s} s · ${s.msg.area_cm2} cm² at (${s.msg.contact_xyz.slice(0, 2).map((v) => v.toFixed(2)).join(', ')}): α ${s.msg.alpha_status === 'below_detection' ? `< ${s.msg.alpha_detection_limit_bq_cm2} BDL` : s.msg.alpha_bq_cm2?.toFixed(2)}, β/γ ${s.msg.beta_gamma_status === 'below_detection' ? `< ${s.msg.beta_gamma_detection_limit_bq_cm2} BDL` : s.msg.beta_gamma_bq_cm2?.toFixed(2)} Bq/cm²`).join('\n')
              : 'No wipe of a footprint near this drum.'} fixture={swabs.some((s) => s.fixture)} />
          </div>
        </section>

        <section>
          <h3>4 · Findings &amp; assessments</h3>
          {findings.length === 0 ? <p className="empty-reason">No findings recorded.</p> : (
            <ul className="obs">
              {findings.map((f) => (
                <li key={f.msg.finding_id}>
                  <span className={`ist ist-${f.msg.status === 'observation_only' ? 'inspected' : f.msg.status}`}>{f.msg.status.replace('_', ' ').toUpperCase()}</span> {f.msg.summary} {f.fixture && <FixtureBadge />}
                  {f.msg.limits.length > 0 && <ul className="limits">{f.msg.limits.map((l) => <li key={l}>{l}</li>)}</ul>}
                </li>
              ))}
            </ul>
          )}
          <p className="reserved">Assessment: <strong>reserved</strong> — no assessment service connected. The console does not diagnose packages.</p>
          <p className="faint small">Evidence is not diagnosis: rust can appear on a cool, intact drum; a bulged drum can be cool with hydrogen below detection in the surrounding air; elevated total gamma can come from several packages; a wipe samples one surface footprint. Internal pressure and headspace are not observable here.</p>
        </section>
      </div>
    </aside>
  );
}

function EvidenceSlot({ title, body, fixture }: { title: string; body: string; fixture?: boolean }) {
  return (
    <div className="evidence">
      <div className="evidence-title">{title} {fixture && <FixtureBadge />}</div>
      <div className="evidence-body">{body}</div>
    </div>
  );
}
