import type { CameraFrame, DetectionEvent } from '../contracts/messages';
import { DETECTOR_CLASSES } from '../contracts/messages';
import type { Received } from '../state/types';
import { formatAge } from '../lib/values';
import { ageSeconds } from '../ingest/freshness';
import { useConsole, useConsoleState } from '../state/context';
import { FixtureBadge } from './common';

/** Shows one timestamped frame and only the detections tied to that exact camera + frame ID. */
export function FrameView({ frame, stale, compact }: { frame: Received<CameraFrame>; stale: boolean; compact?: boolean }) {
  const state = useConsoleState();
  const { selectPackage } = useConsole();
  const f = frame.msg;
  const overlays = state.detections.filter((d) => d.msg.camera_id === f.camera_id && d.msg.frame_id === f.frame_id);
  const age = ageSeconds({ tSimS: f.t_sim_s, recvMs: frame.recvMs }, { simS: state.simClockS, wallMs: Date.now() });
  return (
    <figure className={`frame ${stale ? 'frame-stale' : ''}`}>
      <div className="frame-img" style={{ aspectRatio: `${f.width} / ${f.height}` }}>
        <img src={f.uri} alt={`${f.camera_id} frame ${f.frame_id}`} />
        <svg className="overlay" viewBox={`0 0 ${f.width} ${f.height}`} preserveAspectRatio="none" aria-hidden={!overlays.length}>
          {overlays.map((d) => <Box key={d.msg.detection_id} det={d} onSelect={selectPackage} />)}
        </svg>
        {stale && <div className="stale-stamp">STALE · {formatAge(age)}</div>}
      </div>
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
  const label = `${cls} ${d.confidence.toFixed(2)} · ${attr ? (attr.status === 'attributed' ? attr.package_id : 'package ?') : 'no attribution'}`;
  const colour = d.class_id === 0 ? 'var(--ok)' : d.class_id === 1 ? 'var(--warn)' : 'var(--alert)';
  return (
    <g className="det" onClick={() => attr?.package_id && onSelect(attr.package_id)} style={{ cursor: attr?.package_id ? 'pointer' : 'default' }}>
      <rect x={x} y={y} width={w} height={h} fill="none" stroke={colour} strokeWidth={3} strokeDasharray={attr?.status === 'inconclusive' ? '8 5' : undefined} />
      <rect x={x} y={Math.max(0, y - 22)} width={Math.max(w, label.length * 8.2)} height={20} fill="#000" fillOpacity={0.75} />
      <text x={x + 4} y={Math.max(14, y - 7)} fill={colour} fontSize={14} fontFamily="monospace">{label}</text>
    </g>
  );
}
