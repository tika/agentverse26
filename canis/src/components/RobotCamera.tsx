import type { CameraId } from '../contracts/messages';
import { useConsoleState } from '../state/context';
import { EmptyState, Panel } from './common';
import { FrameView } from './FrameView';

const SLOTS: { id: CameraId; label: string }[] = [
  { id: 'rgb', label: 'RGB' },
  { id: 'depth', label: 'Depth' },
  { id: 'lwir', label: 'Apparent LWIR' },
];

export function RobotCamera({ layout = 'stack' }: { layout?: 'stack' | 'grid' }) {
  const state = useConsoleState();
  return (
    <Panel title="Robot camera (first-person)" id="robot-camera" className="camera-panel">
      <div className={`camera-slots camera-${layout}`}>
        {SLOTS.map((slot) => {
          const frame = state.frames[slot.id];
          const feed = slot.id === 'lwir' ? state.feeds.sensors : state.feeds.robot;
          return (
            <div key={slot.id} className={`camera-slot slot-${slot.id}`} data-testid={`camera-${slot.id}`}>
              <div className="slot-label">{slot.label}</div>
              {frame ? (
                <div className="slot-frame">
                  <FrameView frame={frame} stale={Boolean(state.stale[`frame:${slot.id}`])} compact />
                  {slot.id === 'lwir' && frame.msg.range && <ThermalScale range={frame.msg.range} />}
                  {slot.id === 'depth' && frame.msg.range && <div className="scale-note num">depth {frame.msg.range[0]}–{frame.msg.range[1]} m</div>}
                </div>
              ) : (
                <EmptyState title={`${slot.label} — no frame`}
                  reason={feed.status === 'not_configured' ? 'Camera feed not configured' : `Feed ${feed.status.replace('_', ' ')}`} />
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function ThermalScale({ range }: { range: [number, number] }) {
  return (
    <div className="thermal-scale" aria-label={`Apparent temperature scale ${range[0]} to ${range[1]} °C`}>
      <div className="thermal-title">APPARENT TEMPERATURE (°C)</div>
      <div className="thermal-bar" />
      <div className="thermal-ticks num"><span>{range[0].toFixed(1)}</span><span>{range[1].toFixed(1)}</span></div>
      <div className="thermal-note faint">Grey-body apparent value; emissivity and reflections affect it. Not internal temperature.</div>
    </div>
  );
}
