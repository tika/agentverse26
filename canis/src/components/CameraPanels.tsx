import { useState } from 'react';
import { Camera, CameraOff, Thermometer } from 'lucide-react';
import type { CameraId } from '../contracts/messages';
import { useConsoleState } from '../state/context';
import { EmptyState, Panel } from './common';
import { FrameView } from './FrameView';

/** Secondary panel: the robot's first-person RGB view, with depth as a toggle. */
export function FirstPerson({ fit }: { fit?: boolean }) {
  const state = useConsoleState();
  const [cam, setCam] = useState<Extract<CameraId, 'rgb' | 'depth'>>('rgb');
  const frame = state.frames[cam];
  const feed = state.feeds.robot;
  const f = frame?.msg;
  return (
    <Panel title="First-person camera" icon={Camera} id="first-person" className="fp-panel"
      right={
        <span className="seg" role="group" aria-label="First-person channel">
          {(['rgb', 'depth'] as const).map((c) => (
            <button key={c} aria-pressed={cam === c} className={cam === c ? 'seg-on' : ''} onClick={() => setCam(c)}>{c.toUpperCase()}</button>
          ))}
        </span>
      }>
      <div className="slot-fill" data-testid={`camera-${cam}`}>
        {frame ? <FrameView frame={frame} stale={Boolean(state.stale[`frame:${cam}`])} compact fit={fit} /> : (
          <EmptyState icon={CameraOff}
            title={feed.status === 'not_configured' ? 'Camera Not Configured' : `Camera ${feed.status.replace('_', ' ')} — no frame`}
            reason={feed.status === 'not_configured' ? `Robot ${cam === 'rgb' ? 'camera' : 'depth'} feed is not connected.` : feed.detail} />
        )}
      </div>
      {!frame && (
        <div className="cam-foot">
          <span>Source <b>{f?.source.id ?? '—'}</b></span>
          <span>Resolution <b>{f ? `${f.width} × ${f.height}` : '—'}</b></span>
          <span>FPS <b>{f?.fps ?? '—'}</b></span>
        </div>
      )}
    </Panel>
  );
}

/** Default display scale when no frame is present; replaced by the frame's own range. */
const DEFAULT_RANGE: [number, number] = [-40, 60];

/** Tertiary panel: apparent LWIR from WarehouseSensors.thermal_from_camera(). */
export function Thermal({ fit }: { fit?: boolean }) {
  const state = useConsoleState();
  const frame = state.frames.lwir;
  const feed = state.feeds.sensors;
  return (
    <Panel title="Thermal · apparent LWIR" icon={Thermometer} id="thermal" className="thermal-panel">
      <div className="thermal-row" data-testid="camera-lwir">
        <div className="slot-fill">
          {frame ? <FrameView frame={frame} stale={Boolean(state.stale['frame:lwir'])} compact fit={fit} /> : (
            <EmptyState icon={Thermometer}
              title={feed.status === 'not_configured' ? 'Thermal Feed Not Configured' : `Thermal feed ${feed.status.replace('_', ' ')} — no frame`}
              reason="Apparent LWIR is not available." />
          )}
        </div>
        <ThermalScale range={frame?.msg.range} />
      </div>
    </Panel>
  );
}

export function ThermalScale({ range }: { range?: [number, number] }) {
  const [lo, hi] = range ?? DEFAULT_RANGE;
  const ticks = range
    ? [hi, hi - (hi - lo) / 3, lo + (hi - lo) / 3, lo]
    : [60, 40, 20, 0, -20, -40];
  return (
    <div className="thermal-scale" aria-label={`Apparent temperature scale ${lo} to ${hi} °C${range ? '' : ' (default display range, no data)'}`}
      title={range ? 'Range supplied by the LWIR frame' : 'Default display range; no thermal data'}>
      <div className="thermal-title">APPARENT °C</div>
      <div className="thermal-scale-body">
        <div className="thermal-vbar" />
        <div className="thermal-vticks num">{ticks.map((t) => <span key={t}>– {Number.isInteger(t) ? t : t.toFixed(1)}</span>)}</div>
      </div>
    </div>
  );
}
