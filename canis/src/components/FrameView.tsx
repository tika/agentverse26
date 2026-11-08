import type { CameraFrame, DetectionEvent } from '../contracts/messages';
import { DETECTOR_CLASSES } from '../contracts/messages';
import type { Received } from '../state/types';
import { formatAge } from '../lib/values';
import { ageSeconds } from '../ingest/freshness';
import { useConsole, useConsoleState } from '../state/context';
import { Eye, EyeOff } from 'lucide-react';
import { Fit, FixtureBadge } from './common';
import { RESULT_COLOUR, RESULT_LABEL } from '../lib/inspection';

/** Shows one timestamped frame and only the detections tied to that exact camera + frame ID. */
export function FrameView({ frame, stale, compact, fit }: { frame: Received<CameraFrame>; stale: boolean; compact?: boolean; fit?: boolean }) {
  const state = useConsoleState();
  const { selectPackage, overlays: showOverlays, setOverlays } = useConsole();
  const f = frame.msg;
  const overlays = state.detections.filter((d) => d.msg.camera_id === f.camera_id && d.msg.frame_id === f.frame_id);
  // Result layer: only shapes that reference this exact camera + frame (latest assessment per package).
  const latest = new Map<string, (typeof state.assessments)[number]>();
  for (const a of state.assessments) if (!a.late) latest.set(a.msg.package_id, a);
  const results = [...latest.values()].flatMap((a) => a.msg.shapes
    .filter((sh) => sh.camera_id === f.camera_id && sh.frame_id === f.frame_id)
    .map((sh) => ({ a: a.msg, fixture: a.fixture, sh })));
  const hasOverlays = overlays.length > 0 || results.length > 0;
  const age = ageSeconds({ tSimS: f.t_sim_s, recvMs: frame.recvMs }, { simS: state.simClockS, wallMs: Date.now() });
  return (
    <figure className={`frame ${stale ? 'frame-stale' : ''} ${fit ? 'frame-fit' : ''}`}>
      <Fit ratio={f.width / f.height} enabled={Boolean(fit)}>
        <div className="frame-img" style={{ aspectRatio: `${f.width} / ${f.height}` }}>
          <img src={f.uri} alt={`${f.camera_id} frame ${f.frame_id}`} />
          {showOverlays && (
          <svg className="overlay" viewBox={`0 0 ${f.width} ${f.height}`} preserveAspectRatio="none" aria-hidden={!hasOverlays}>
            {/* pending detector evidence: outline boxes */}
            <g className="layer-detections">{overlays.map((d) => <Box key={d.msg.detection_id} det={d} onSelect={selectPackage} />)}</g>
            {/* separate result layer: opaque shapes from assessment records */}
            <g className="layer-results">
              {results.map(({ a, sh }) => (
                <g key={`${a.assessment_id}:${sh.frame_id}`} onClick={() => selectPackage(a.package_id)} style={{ cursor: 'pointer' }}>
                  <rect x={sh.bbox_px[0]} y={sh.bbox_px[1]} width={sh.bbox_px[2]} height={sh.bbox_px[3]} fill={RESULT_COLOUR[a.status]} fillOpacity={0.82} stroke="#000" strokeWidth={2} />
                  <text x={sh.bbox_px[0] + 6} y={sh.bbox_px[1] + 18} fontSize={15} fontFamily="monospace" fontWeight={700} fill="#111">{a.package_id}</text>
                  <text x={sh.bbox_px[0] + 6} y={sh.bbox_px[1] + 36} fontSize={13} fontFamily="monospace" fill="#111">{a.status.toUpperCase()}{a.defect_types.length ? `: ${a.defect_types.join(' + ')}` : ''}</text>
                  <title>{`${a.package_id} · ${RESULT_LABEL[a.status]} · ${a.reason}`}</title>
                </g>
              ))}
            </g>
          </svg>
        )}
        {hasOverlays && (
          <button className="overlay-toggle" onClick={() => setOverlays(!showOverlays)} aria-pressed={!showOverlays}
            title={showOverlays ? 'Show the raw evidence image' : 'Show detections and results'}>
            {showOverlays ? <><EyeOff size={13} aria-hidden /> Raw view</> : <><Eye size={13} aria-hidden /> Overlays</>}
          </button>
        )}
          {stale && <div className="stale-stamp">STALE · {formatAge(age)}</div>}
        </div>
      </Fit>
      <figcaption className={compact ? 'frame-meta compact' : 'frame-meta'}>
        <span className="num">{f.frame_id}</span>
        <span>src <span className="mono">{f.source.id}</span></span>
        <span>t <span className="num">{f.t_sim_s !== undefined ? `${f.t_sim_s.toFixed(1)} s` : '—'}</span></span>
        <span>age <span className="num">{formatAge(age)}</span></span>
        <span className="num">{f.width} × {f.height}</span>
        {f.fps !== undefined && <span className="num">{f.fps} FPS</span>}
        {frame.fixture && <FixtureBadge />}
      </figcaption>
    </figure>
  );
}

function Box({ det, onSelect }: { det: Received<DetectionEvent>; onSelect(id: string): void }) {
  const d = det.msg;
  const [x, y, w, h] = d.bbox_px;
  const cls = DETECTOR_CLASSES[d.class_id];
  const attr = d.drum_attribution;
  // Tracked previews (optical flow between detector frames) are not detector evidence.
  const tracked = d.model_id === 'optical-flow-preview' || d.quality === 'degraded';
  const label = `${tracked ? 'TRACKED · ' : ''}${cls} ${d.confidence.toFixed(2)}${attr?.status === 'attributed' ? ` · ${attr.package_id}` : ''}`;
  // All pre-assessment boxes use the brand yellow; results use the separate opaque layer.
  const colour = 'var(--brand)';
  return (
    <g className="det" onClick={() => attr?.package_id && onSelect(attr.package_id)} style={{ cursor: attr?.package_id ? 'pointer' : 'default' }}>
      <rect x={x} y={y} width={w} height={h} fill="none" stroke={colour} strokeWidth={tracked ? 2 : 3} strokeDasharray={tracked ? '9 6' : undefined} />
      <rect x={x} y={Math.max(0, y - 22)} width={Math.max(w, label.length * 8.2)} height={20} fill="#000" fillOpacity={0.75} />
      <text x={x + 4} y={Math.max(14, y - 7)} fill={colour} fontSize={14} fontFamily="monospace">{label}</text>
    </g>
  );
}
