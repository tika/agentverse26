import { useMemo, useState } from 'react';
import { useConsole, useConsoleState } from '../state/context';
import { groupStacks, scaleBarMetres, toScreen, type Stack } from '../map/geometry';
import { Panel } from './common';
import { packageStatuses, statusOf } from '../lib/inspection';

const PAD = 1.6;

export function NavMap({ tall }: { tall?: boolean }) {
  const { map, selectDrum, selectedDrumId, selectRack, selectedRackId } = useConsole();
  const state = useConsoleState();
  const [picked, setPicked] = useState<Stack | null>(null);
  const stacks = useMemo(() => groupStacks(map.drums), [map]);
  const W = map.hall_m.x, H = map.hall_m.y;
  const S = (x: number, y: number) => toScreen(map, x, y);

  const statuses = packageStatuses(state);
  const covOf = (d: (typeof map.drums)[number]) => statusOf(statuses, d);
  const selectedDrum = map.drums.find((d) => d.id === selectedDrumId);

  const zoneBoxes = Object.entries(map.zones).map(([zone, category]) => {
    const racks = map.racks.filter((r) => r.zone === zone);
    const xs = racks.flatMap((r) => [r.center[0] - r.size / 2, r.center[0] + r.size / 2]);
    const ys = racks.flatMap((r) => [r.center[1] - r.size / 2, r.center[1] + r.size / 2]);
    return { zone, category, x0: Math.min(...xs) - 0.35, x1: Math.max(...xs) + 0.35, y0: Math.min(...ys) - 0.35, y1: Math.max(...ys) + 0.35 };
  });

  const run = state.runState?.msg;
  const planned: [number, number][] = run?.planned_path_m
    ?? run?.planned_path?.map((n) => map.nodes[n]).filter(Boolean) ?? [];
  const pose = state.pose?.msg;
  const poseStale = Boolean(state.stale.pose);
  const trail = state.poseHistory.filter((p) => !p.late).map((p) => p.msg.xyz_m);
  const scale = scaleBarMetres(W);
  const spawn = map.nodes.spawn ?? [map.robot_start_m[0], map.robot_start_m[1]];

  return (
    <Panel title="Navigation map (bird's-eye)" id="navmap" className={`map-panel ${tall ? 'map-tall' : ''}`}
      right={<span className="num dim">warehouse-v3 · {W.toFixed(2)} × {H.toFixed(2)} m · world frame</span>}>
      <div className="map-wrap">
        <svg className="navmap" viewBox={`${-PAD} ${-PAD} ${W + 2 * PAD} ${H + 2 * PAD + 1.6}`} role="img"
          aria-label={`Warehouse map ${W} by ${H} metres with ${map.racks.length} racks and ${map.drums.length} drums`}>
          <defs>
            <pattern id="hatch" width="0.5" height="0.5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="0.5" stroke="#3a4046" strokeWidth="0.12" />
            </pattern>
            <pattern id="hatch-ilw" width="0.45" height="0.45" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
              <line x1="0" y1="0" x2="0" y2="0.45" stroke="#5aa3ae" strokeOpacity="0.35" strokeWidth="0.1" />
            </pattern>
          </defs>
          {/* hall */}
          <rect x={0} y={0} width={W} height={H} fill="#1d2023" stroke="#8a9198" strokeWidth={0.12} />
          {map.staging_bounds_m.map(([x0, y0, x1, y1], i) => {
            const [sx, sy] = S(x0, y1);
            return <rect key={i} x={sx} y={sy} width={x1 - x0} height={y1 - y0} fill="url(#hatch)" />;
          })}
          {zoneBoxes.map((z) => {
            const [sx, sy] = S(z.x0, z.y1);
            return (
              <g key={z.zone}>
                <rect x={sx} y={sy} width={z.x1 - z.x0} height={z.y1 - z.y0} fill={z.category === 'ILW' ? 'url(#hatch-ilw)' : 'none'}
                  stroke={z.category === 'ILW' ? 'var(--ilw)' : 'var(--llw)'} strokeWidth={0.06} strokeDasharray="0.3 0.2" />
                <text x={sx + 0.15} y={sy - 0.25} className="map-label" fill={z.category === 'ILW' ? 'var(--ilw)' : 'var(--llw)'}>ZONE {z.zone} · {z.category}</text>
              </g>
            );
          })}
          {/* route graph (mapped) */}
          <g className="route" aria-label="Mapped route graph">
            {map.edges.map(([a, b]) => {
              const pa = map.nodes[a], pb = map.nodes[b];
              if (!pa || !pb) return null;
              const [x1, y1] = S(pa[0], pa[1]); const [x2, y2] = S(pb[0], pb[1]);
              return <line key={`${a}-${b}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--route)" strokeWidth={0.07} />;
            })}
            {Object.entries(map.nodes).map(([id, p]) => {
              const [x, y] = S(p[0], p[1]);
              return <circle key={id} cx={x} cy={y} r={0.14} fill="#1d2023" stroke="var(--route)" strokeWidth={0.05}><title>{id}</title></circle>;
            })}
          </g>
          {/* racks */}
          {map.racks.map((r) => {
            const [x, y] = S(r.center[0] - r.size / 2, r.center[1] + r.size / 2);
            const sel = selectedRackId === r.id;
            return (
              <rect key={r.id} x={x} y={y} width={r.size} height={r.size} className="rack"
                fill={r.category === 'ILW' ? '#22393d' : '#3b3520'} stroke={sel ? 'var(--brand)' : r.category === 'ILW' ? '#3f6f77' : '#7d6b2c'}
                strokeWidth={sel ? 0.12 : 0.05} onClick={() => selectRack(sel ? null : r.id)}>
                <title>Rack {r.id} · {r.category}</title>
              </rect>
            );
          })}
          {/* stacks (drums sharing XY) */}
          {stacks.map((s) => {
            const [x, y] = S(s.x_m, s.y_m);
            const r = s.drums[0].radius_m;
            const anyInspected = s.drums.some((d) => covOf(d).coverage !== 'unseen');
            const anyFlag = s.drums.some((d) => ['inconclusive', 'finding'].includes(covOf(d).finding));
            const isSel = s.drums.some((d) => d.id === selectedDrumId);
            const inRack = selectedRackId && s.drums[0].stack_id === selectedRackId;
            return (
              <g key={`${s.x_m},${s.y_m}`} className="stack" onClick={() => setPicked(s)} role="button" tabIndex={0}
                aria-label={`Stack at ${s.x_m.toFixed(2)}, ${s.y_m.toFixed(2)}: ${s.drums.map((d) => d.id).join(', ')}`}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setPicked(s); }}>
                <circle cx={x} cy={y} r={r * 0.92} fill={s.category === 'ILW' ? '#4d8f99' : '#c9a93a'}
                  fillOpacity={inRack ? 1 : 0.8} stroke={isSel ? '#fff' : anyFlag ? 'var(--warn)' : anyInspected ? 'var(--ok)' : '#111'}
                  strokeWidth={isSel || anyFlag || anyInspected ? 0.1 : 0.03} />
                {anyFlag && <text x={x} y={y + 0.16} textAnchor="middle" className="map-glyph" fill="#111">?</text>}
                {!anyFlag && anyInspected && <text x={x} y={y + 0.16} textAnchor="middle" className="map-glyph" fill="#111">✓</text>}
              </g>
            );
          })}
          {/* future planned path (separate layer) */}
          {planned.length > 1 && (
            <polyline points={planned.map((p) => S(p[0], p[1]).join(',')).join(' ')} fill="none" stroke="var(--planned)"
              strokeWidth={0.1} strokeDasharray="0.35 0.25" aria-label="Planned path from run state" />
          )}
          {/* static spawn vs observed pose */}
          {(() => {
            const [x, y] = S(spawn[0], spawn[1]);
            return (
              <g aria-label="Static spawn">
                <circle cx={x} cy={y} r={0.38} fill="none" stroke="#e8eaec" strokeWidth={0.08} />
                <line x1={x - 0.25} y1={y} x2={x + 0.25} y2={y} stroke="#e8eaec" strokeWidth={0.05} />
                <line x1={x} y1={y - 0.25} x2={x} y2={y + 0.25} stroke="#e8eaec" strokeWidth={0.05} />
              </g>
            );
          })()}
          {trail.length > 1 && <polyline points={trail.map((p) => S(p[0], p[1]).join(',')).join(' ')} fill="none" stroke="var(--robot)" strokeOpacity={0.45} strokeWidth={0.08} />}
          {pose && (() => {
            const [x, y] = S(pose.xyz_m[0], pose.xyz_m[1]);
            const yaw = -pose.rpy_deg[2]; // screen Y is flipped, so rotation sense flips too
            return (
              <g transform={`translate(${x} ${y}) rotate(${yaw})`} opacity={poseStale ? 0.45 : 1}
                aria-label={`Observed robot pose (${pose.pose_source ?? 'source not stated'})`}>
                <polygon points="0.6,0 -0.4,0.38 -0.25,0 -0.4,-0.38" fill="var(--robot)" stroke="#0b0c0d" strokeWidth={0.05} />
              </g>
            );
          })()}
          {selectedDrum && (() => {
            const [x, y] = S(selectedDrum.x_m, selectedDrum.y_m);
            return <circle cx={x} cy={y} r={selectedDrum.radius_m + 0.25} fill="none" stroke="#fff" strokeWidth={0.08} strokeDasharray="0.2 0.12" />;
          })()}
          {/* scale bar and axes */}
          <g transform={`translate(0 ${H + 0.9})`} className="map-scale">
            <rect x={0} y={0} width={scale} height={0.18} fill="#d9dcdf" />
            <rect x={0} y={0} width={scale / 2} height={0.18} fill="#555" />
            <text x={0} y={1.05} className="map-label">0</text>
            <text x={scale} y={1.05} className="map-label" textAnchor="middle">{scale} m</text>
            <g transform={`translate(${W - 3.2} 0)`}>
              <line x1={0} y1={0.6} x2={1.4} y2={0.6} stroke="#9aa1a8" strokeWidth={0.07} markerEnd="" />
              <text x={1.55} y={0.8} className="map-label">+X</text>
              <line x1={0} y1={0.6} x2={0} y2={-0.8} stroke="#9aa1a8" strokeWidth={0.07} />
              <text x={-0.2} y={-0.95} className="map-label">+Y</text>
            </g>
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
              </button>
            ))}
          </div>
        )}
      </div>
      <ul className="legend" aria-label="Map legend">
        <li><span className="lg lg-llw" />LLW stack (zone A)</li>
        <li><span className="lg lg-ilw" />ILW stack (zone B)</li>
        <li><span className="lg lg-rack" />Rack footprint</li>
        <li><span className="lg lg-route" />Mapped route graph</li>
        <li><span className="lg lg-planned" />Planned path (from run state)</li>
        <li><span className="lg lg-spawn" />Spawn (static, map)</li>
        <li><span className="lg lg-robot" />Observed robot pose</li>
        <li><span className="lg lg-staging" />Staging area</li>
        <li><span className="lg-glyph">✓</span>Seen / inspected (ledger)</li>
        <li><span className="lg-glyph warn">?</span>Inconclusive finding</li>
      </ul>
      <div className="map-foot faint">
        {pose ? '' : 'No robot pose feed — spawn shown from map only. '}Click a rack to highlight it; click a stack to choose a tier (3 drums share each XY).
      </div>
    </Panel>
  );
}
