import { Info } from 'lucide-react';
import { useConsoleState, useTicker } from '../state/context';
import { ageSeconds } from '../ingest/freshness';
import { formatAge } from '../lib/values';
import { FixtureBadge, Pill } from './common';

/**
 * Column beside the third-person view. Offline it documents the static reference
 * used as the map base layer; with a live frame it shows that frame's metadata.
 */
export function FeedDetails() {
  const state = useConsoleState();
  const wall = useTicker();
  const frame = state.frames.third_person;
  if (frame) {
    const f = frame.msg;
    const overlays = state.detections.filter((d) => d.msg.camera_id === f.camera_id && d.msg.frame_id === f.frame_id).length;
    const age = ageSeconds({ tSimS: f.t_sim_s, recvMs: frame.recvMs }, { simS: state.simClockS, wallMs: wall });
    return (
      <section className="panel ref-panel" aria-label="Third-person frame details">
        <div className="ref-head ref-live">THIRD-PERSON FRAME {frame.fixture && <FixtureBadge />}</div>
        <dl className="ref-table">
          <Row k="Feed" v={<Pill tone={state.stale['frame:third_person'] ? 'warn' : 'ok'}>{state.stale['frame:third_person'] ? 'STALE' : 'CONNECTED'}</Pill>} />
          <Row k="Frame ID" v={<span className="mono">{f.frame_id}</span>} />
          <Row k="Source" v={<span className="mono">{f.source.id}</span>} />
          <Row k="Sim time" v={f.t_sim_s !== undefined ? `${f.t_sim_s.toFixed(1)} s` : '—'} />
          <Row k="Age" v={formatAge(age)} />
          <Row k="Resolution" v={`${f.width} × ${f.height}`} />
          <Row k="FPS" v={f.fps !== undefined ? String(f.fps) : '—'} />
          <Row k="Overlays" v={`${overlays} detection${overlays === 1 ? '' : 's'} on this frame`} />
        </dl>
        <p className="ref-note"><Info size={16} aria-hidden /> Detection overlays draw only on the frame whose camera and frame ID they reference.</p>
      </section>
    );
  }
  return (
    <section className="panel ref-panel" aria-label="Static reference" data-testid="static-reference">
      <div className="ref-head">STATIC REFERENCE — NOT LIVE</div>
      <dl className="ref-table">
        <Row k="Third-person feed" v={<Pill>NOT CONNECTED</Pill>} />
        <Row k="Shown" v="Isaac Sim 6.2 RTX still, roof-off overview (wide-aisles review)" />
        <Row k="File" v={<span className="mono">sim/warehouse-v3/review/wide-aisles/overhead.png</span>} />
        <Row k="Hall" v="24.00 × 28.30 m · 5 aisles × 3.32 m clear" />
        <Row k="Inventory" v="420 drums · 336 LLW · 84 ILW" />
        <Row k="Frame ID / clock" v="— (static image)" />
      </dl>
      <p className="ref-note"><Info size={16} aria-hidden /> When an Isaac feed connects, this panel shows timestamped camera_frame messages for camera_id: third_person. Detection overlays draw only on the frame they reference.</p>
    </section>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="ref-row"><dt>{k}</dt><dd>{v}</dd></div>;
}
