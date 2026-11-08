import { useMemo, useState } from 'react';
import { Layers } from 'lucide-react';
import { useConsole, useConsoleState } from '../state/context';
import { groupStacks, type Stack } from '../map/geometry';
import { overheadProjection, STILL } from '../map/overheadProjection';
import { assessmentsByPackage, packageStatuses, RESULT_COLOUR, statusOf, type ResultStatus } from '../lib/inspection';
import { Panel } from './common';

/** Crop of the still to the hall's outer wall line (image pixels; the still has light margins). */
const CROP = { x: 377, y: 0, w: 846, h: 1000 };

/**
 * Bird's-eye coverage map drawn over the Isaac RTX roof-off still. Overlays are
 * projected with the still's own camera model, so they sit on the rendered drums.
 */
export function OverheadMap() {
  const { map, selectDrum, selectedDrumId } = useConsole();
  const state = useConsoleState();
  const [picked, setPicked] = useState<Stack | null>(null);
  const proj = useMemo(() => overheadProjection(map.hall_m.x, map.hall_m.y), [map]);
  const stacks = useMemo(() => groupStacks(map.drums), [map]);
  const statuses = packageStatuses(state);
  const covOf = (d: (typeof map.drums)[number]) => statusOf(statuses, d);
  const results = assessmentsByPackage(state);
  const resultOf = (d: (typeof map.drums)[number]) => results.get(d.location_code)?.msg.status;
  const SEVERITY: Record<ResultStatus, number> = { ok: 1, unsure: 2, defect: 3 };

  const counts = { inspected: 0, seen: 0, unseen: 0, flagged: 0 };
  for (const d of map.drums) {
    const st = covOf(d);
    counts[st.coverage] += 1;
    if (st.finding === 'inconclusive' || st.finding === 'finding') counts.flagged += 1;
  }
  const pct = (n: number) => `${((100 * n) / map.drums.length).toFixed(1)}%`;

  const run = state.runState?.msg;
  const planned: [number, number][] = run?.planned_path_m ?? run?.planned_path?.map((n) => map.nodes[n]).filter(Boolean) ?? [];
  const pose = state.pose?.msg;
  const trail = state.poseHistory.filter((p) => !p.late).map((p) => p.msg.xyz_m);
  const spawn = map.nodes.spawn ?? [map.robot_start_m[0], map.robot_start_m[1]];
  const P = (x: number, y: number, z = 0) => proj.project(x, y, z);
  const pts = (list: number[][], z = 0) => list.map((p) => P(p[0], p[1], z).join(',')).join(' ');
  const floorScale = proj.pxPerM(0);
  const bar = 10;

  return (
    <Panel title="Bird's-eye · coverage" icon={Layers} id="navmap" className="map-panel overhead-panel"
      right={<span className="num dim">{map.hall_m.x.toFixed(1)} × {map.hall_m.y.toFixed(1)} m</span>}>
      <div className="coverage-bar" data-testid="coverage-bar" aria-label="Inspection coverage from ledger records">
        <span className="cov"><span className="sq sq-inspected" />Inspected <b>{pct(counts.inspected)}</b></span>
        <span className="cov"><span className="sq sq-seen" />Seen <b>{pct(counts.seen)}</b></span>
        <span className="cov"><span className="sq sq-unseen" />Unseen <b>{pct(counts.unseen)}</b></span>
        {counts.flagged > 0 && <span className="cov cov-flag">? {counts.flagged} flagged</span>}
        <span className="sr-only">{counts.inspected} inspected, {counts.seen} seen, {counts.unseen} unseen</span>
      </div>
      <div className="map-wrap overhead-wrap">
        <svg className="overhead" viewBox={`${CROP.x} ${CROP.y} ${CROP.w} ${CROP.h + 70}`} role="img"
          aria-label={`Isaac RTX overview of the ${map.hall_m.x} by ${map.hall_m.y} metre warehouse with inspection coverage for ${map.drums.length} drums`}>
          <image href={STILL.url} x={0} y={0} width={STILL.width} height={STILL.height} />
          <rect x={CROP.x} y={CROP.y} width={CROP.w} height={CROP.h} fill="#000" fillOpacity={0.18} />
          {/* mapped route graph (floor) */}
          <g aria-label="Mapped route graph">
            {map.edges.map(([a, b]) => {
              const pa = map.nodes[a], pb = map.nodes[b];
              if (!pa || !pb) return null;
              const [x1, y1] = P(pa[0], pa[1]); const [x2, y2] = P(pb[0], pb[1]);
              return <line key={`${a}-${b}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#fff" strokeOpacity={0.4} strokeWidth={1.5} />;
            })}
          </g>
          {/* coverage markers on the visible (top-tier) drum lids */}
          {stacks.map((s) => {
            const top = s.drums[s.drums.length - 1];
            const z = top.base_z_m + top.height_m;
            const [x, y] = P(s.x_m, s.y_m, z);
            const r = top.radius_m * proj.pxPerM(z) * 0.92;
            const covs = s.drums.map((d) => covOf(d).coverage);
            const nInspected = covs.filter((c) => c === 'inspected').length;
            const anySeen = covs.some((c) => c !== 'unseen');
            const flag = s.drums.some((d) => ['inconclusive', 'finding'].includes(covOf(d).finding));
            const sel = s.drums.some((d) => d.id === selectedDrumId);
            const all = nInspected === covs.length;
            const tierResults = s.drums.map((d) => [d.tier, resultOf(d)] as const).filter((t): t is readonly [number, ResultStatus] => Boolean(t[1]));
            const worst = tierResults.reduce<ResultStatus | null>((w, [, r]) => (!w || SEVERITY[r] > SEVERITY[w] ? r : w), null);
            const stroke = sel ? '#fff' : flag ? 'var(--warn)' : nInspected ? 'var(--ok)' : anySeen ? 'var(--seen)' : 'rgba(255,255,255,.55)';
            return (
              <g key={`${s.x_m},${s.y_m}`} className="stack" role="button" tabIndex={0} onClick={() => setPicked(s)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setPicked(s); }}
                aria-label={`Stack ${s.drums.map((d) => d.location_code).join(', ')}: ${covs.join(', ')}`}>
                <rect x={x - r} y={y - r} width={2 * r} height={2 * r} rx={2}
                  fill={all ? 'var(--ok)' : 'transparent'} fillOpacity={all ? 0.55 : 0}
                  stroke={stroke} strokeWidth={sel || flag || anySeen ? 3 : 1.2} />
                {worst ? (
                  <>
                    {/* assessment result layer: opaque fill keyed to package + tier */}
                    <rect x={x - r + 3} y={y - r + 3} width={2 * r - 6} height={2 * r - 6} fill={RESULT_COLOUR[worst]} fillOpacity={0.95} />
                    <text x={x} y={y + 5} textAnchor="middle" className="ov-tier" fill="#111">{tierResults.map(([t]) => t).join('·')}</text>
                  </>
                ) : (
                  <>
                    {flag && <text x={x} y={y + 6} textAnchor="middle" className="ov-glyph" fill="var(--warn)">?</text>}
                    {!flag && nInspected > 0 && !all && <text x={x} y={y + 6} textAnchor="middle" className="ov-glyph" fill="var(--ok)">{nInspected}</text>}
                  </>
                )}
                <title>{s.drums.map((d) => `T${d.tier} ${d.location_code} (${d.id}): ${covOf(d).coverage}${resultOf(d) ? ` · result ${resultOf(d)}` : ''}`).join('\n')}</title>
              </g>
            );
          })}
          {planned.length > 1 && <polyline points={pts(planned)} fill="none" stroke="var(--brand)" strokeWidth={4} strokeDasharray="14 9" aria-label="Planned path" />}
          {trail.length > 1 && <polyline points={pts(trail, 0.5)} fill="none" stroke="var(--robot)" strokeOpacity={0.6} strokeWidth={3} />}
          {(() => {
            const [x, y] = P(spawn[0], spawn[1]);
            return (
              <g aria-label="Robot spawn (static, from map)" className="spawn-mark">
                <circle cx={x} cy={y} r={13} fill="rgba(0,0,0,.45)" stroke="#fff" strokeWidth={2.5} />
                <line x1={x - 9} y1={y} x2={x + 9} y2={y} stroke="#fff" strokeWidth={2} />
                <line x1={x} y1={y - 9} x2={x} y2={y + 9} stroke="#fff" strokeWidth={2} />
              </g>
            );
          })()}
          {pose && (() => {
            const [x, y] = P(pose.xyz_m[0], pose.xyz_m[1], 0.5);
            return (
              <g transform={`translate(${x} ${y}) rotate(${-pose.rpy_deg[2]})`} opacity={state.stale.pose ? 0.45 : 1}
                aria-label={`Observed robot pose (${pose.pose_source ?? 'source not stated'})`}>
                <polygon points="22,0 -14,13 -8,0 -14,-13" fill="var(--robot)" stroke="#0b0c0d" strokeWidth={2} />
              </g>
            );
          })()}
          {/* scale bar (floor plane) and +Y arrow, below the image */}
          <g transform={`translate(${CROP.x + 16} ${CROP.h + 22})`} className="ov-scale">
            <rect x={0} y={0} width={bar * floorScale} height={5} fill="#d9dcdf" />
            <rect x={0} y={0} width={(bar / 2) * floorScale} height={5} fill="#6d747b" />
            {[0, 5, 10].map((m) => <text key={m} x={m * floorScale} y={30} textAnchor={m ? 'middle' : 'start'} className="ov-label">{m}{m === 10 ? ' m' : m === 5 ? ' m' : ''}</text>)}
          </g>
          <g transform={`translate(${CROP.x + CROP.w - 40} ${CROP.h + 10})`} aria-label="Map +Y direction">
            <text x={0} y={14} textAnchor="middle" className="ov-label">+Y</text>
            <path d="M0 22 L-9 48 L0 41 L9 48 Z" fill="#d9dcdf" />
          </g>
        </svg>
        {picked && (
          <div className="tier-picker" role="dialog" aria-label="Choose tier">
            <div className="tier-head">
              <span>Stack <span className="mono">{picked.stack_id}</span> @ <span className="num">({picked.x_m.toFixed(2)}, {picked.y_m.toFixed(2)}) m</span></span>
              <button onClick={() => setPicked(null)} aria-label="Close tier picker">✕</button>
            </div>
            {[...picked.drums].reverse().map((d) => (
              <button key={d.id} className="tier-btn" onClick={() => { selectDrum(d.id); setPicked(null); }}>
                <span className="num">T{d.tier}</span> <span className="mono">{d.id}</span> <span className="mono dim">{d.location_code}</span>
                <span className={`cat cat-${d.category}`}>{d.category}</span>
                <span className="faint">{covOf(d).coverage}</span>
                {resultOf(d) && <span className={`res res-${resultOf(d)}`}>{resultOf(d)!.toUpperCase()}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      <ul className="legend legend-ov" aria-label="Map legend">
        <li><span className="dot dot-llw" />LLW</li>
        <li><span className="dot dot-ilw" />ILW</li>
        <li><span className="sq sq-inspected" />Inspected</li>
        <li><span className="sq sq-seen" />Seen</li>
        <li><span className="sq sq-unseen" />Unseen</li>
        <li><span className="lg-spawn-ico" />Robot (spawn)</li>
        <li><span className="ln ln-planned" />Planned path</li>
        <li><span className="ln ln-route" />Route graph</li>
        <li><span className="sq res-ok-sq" />Result OK</li>
        <li><span className="sq res-unsure-sq" />Unsure</li>
        <li><span className="sq res-defect-sq" />Defect</li>
      </ul>
      <div className="ov-note faint">Base layer: static Isaac RTX still (not live). Markers sit on top-tier lids; click one to choose a tier.</div>
    </Panel>
  );
}
