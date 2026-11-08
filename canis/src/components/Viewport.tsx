import { Box, Link } from 'lucide-react';
import { useConsole, useConsoleState } from '../state/context';
import { EmptyState, Panel } from './common';
import { FrameView } from './FrameView';

/** Primary panel. Shows timestamped third-person frames only; never a static still. */
export function Viewport({ fit }: { fit?: boolean }) {
  const state = useConsoleState();
  const { openConfigure } = useConsole();
  const frame = state.frames.third_person;
  const feed = state.feeds.isaac;
  return (
    <Panel title="Simulation (third-person)" icon={Box} id="viewport" className="viewport-panel"
      right={frame ? <span className="dim">camera third_person · {feed.status.toUpperCase()}</span> : undefined}>
      {frame ? (
        <FrameView frame={frame} stale={Boolean(state.stale['frame:third_person'])} fit={fit} />
      ) : (
        <div className="slot-fill" data-testid="third-person-empty">
          <EmptyState icon={Box}
            title={feed.status === 'not_configured' ? 'Simulation Feed Not Configured' : `Simulation Feed ${feed.status.replace('_', ' ')}`}
            reason={<>Connect to NVIDIA Isaac Sim or select a recorded run<br />from the Simulation menu to display the third-person feed.</>}
            action={<button className="btn-outline" onClick={openConfigure}><Link size={15} aria-hidden /> Configure simulation</button>} />
        </div>
      )}
    </Panel>
  );
}
