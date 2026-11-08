import { useState } from 'react';
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
  return (
    <Panel title="First-person camera" id="first-person" className="fp-panel"
      right={
        <span className="seg" role="group" aria-label="First-person channel">
          {(['rgb', 'depth'] as const).map((c) => (
            <button key={c} aria-pressed={cam === c} className={cam === c ? 'seg-on' : ''} onClick={() => setCam(c)}>{c.toUpperCase()}</button>
          ))}
        </span>
      }>
      <div className="slot-fill" data-testid={`camera-${cam}`}>
        {frame ? <FrameView frame={frame} stale={Boolean(state.stale[`frame:${cam}`])} compact fit={fit} /> : (
          <EmptyState title={`${cam === 'rgb' ? 'RGB' : 'Depth'} — no frame`}
            reason={feed.status === 'not_configured' ? 'Robot camera feed not configured' : `Feed ${feed.status.replace('_', ' ')}`} />
        )}
      </div>
    </Panel>
  );
}

/** Tertiary panel: apparent LWIR from WarehouseSensors.thermal_from_camera(). */
export function Thermal({ fit }: { fit?: boolean }) {
  const state = useConsoleState();
  const frame = state.frames.lwir;
  const feed = state.feeds.sensors;
  return (
    <Panel title="Thermal · apparent LWIR" id="thermal" className="thermal-panel">
      <div className="thermal-row" data-testid="camera-lwir">
        <div className="slot-fill">
          {frame ? <FrameView frame={frame} stale={Boolean(state.stale['frame:lwir'])} compact fit={fit} /> : (
            <EmptyState title="Apparent LWIR — no frame"
              reason={feed.status === 'not_configured' ? 'Thermal feed not configured' : `Feed ${feed.status.replace('_', ' ')}`} />
          )}
        </div>
        <ThermalScale range={frame?.msg.range} />
      </div>
    </Panel>
  );
}

export function ThermalScale({ range }: { range?: [number, number] }) {
  return (
    <div className="thermal-scale" aria-label={range ? `Apparent temperature scale ${range[0]} to ${range[1]} °C` : 'Apparent temperature scale, no data'}>
      <div className="thermal-title">APPARENT °C</div>
      <div className="thermal-vbar" />
      <div className="thermal-vticks num"><span>{range ? range[1].toFixed(1) : '—'}</span><span>{range ? range[0].toFixed(1) : '—'}</span></div>
      <div className="thermal-note faint">Emissivity and reflections affect it. Not internal temperature.</div>
    </div>
  );
}
