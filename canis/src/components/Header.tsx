import { useConsole, useConsoleState, type TabId } from '../state/context';
import { formatClock } from '../lib/values';
import { FeedChip } from './common';
import { FEED_IDS, type Mode } from '../state/types';

export const TABS: { id: TabId; label: string }[] = [
  { id: 'simulation', label: 'Simulation' },
  { id: 'inspection', label: 'Inspection' },
  { id: 'sensors', label: 'Sensors' },
  { id: 'alerts', label: 'Alerts' },
  { id: 'logs', label: 'Logs' },
];

const MODE_LABEL: Record<Mode, string> = {
  offline: 'FRAMEWORK · OFFLINE',
  replay: 'DEMO REPLAY',
  live: 'LIVE ADAPTER',
};

export function Header({ tab, onTab }: { tab: TabId; onTab(t: TabId): void }) {
  const state = useConsoleState();
  const { setMode, replay } = useConsole();
  const feeds = FEED_IDS.map((id) => state.feeds[id]);
  const unacked = state.alerts.filter((a) => !state.acknowledged.has(a.msg.alert_id) && a.msg.severity !== 'info').length;

  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
    onTab(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  };

  return (
    <header className="app-header">
      <div className="brand-plate" aria-label="C.A.N.I.S. — Containment Analysis & Nuclear Intelligence System">
        <img className="brand-mark" src="/assets/brand/canis-dog-head.png" alt="" width={918} height={1019} />
        <div className="brand-text">
          <img className="brand-word" src="/assets/brand/canis-wordmark.png" alt="C.A.N.I.S." width={1092} height={293} />
          <span className="brand-sub">Containment Analysis &amp; Nuclear Intelligence System</span>
        </div>
      </div>

      <nav className="tabs" role="tablist" aria-label="Console sections">
        {TABS.map((t, i) => (
          <button key={t.id} id={`tab-${t.id}`} role="tab" aria-selected={tab === t.id} aria-controls={`panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1} className={`tab ${tab === t.id ? 'tab-active' : ''}`}
            onClick={() => onTab(t.id)} onKeyDown={(e) => onKey(e, i)}>
            {t.label.toUpperCase()}
            {t.id === 'alerts' && unacked > 0 && <span className="tab-count" aria-label={`${unacked} unacknowledged`}>{unacked}</span>}
          </button>
        ))}
      </nav>

      <div className="header-status">
        <div className="mode-row">
          <span className={`mode-chip mode-${state.mode}`} data-testid="mode-chip">{MODE_LABEL[state.mode]}</span>
          {state.simClockS !== undefined && (
            <span className="elapsed" data-testid="elapsed">
              {state.mode === 'replay' ? 'REPLAY CLOCK' : 'SIM ELAPSED'} <span className="num">{formatClock(state.simClockS)}</span>
            </span>
          )}
          <label className="mode-select">
            <span className="sr-only">Data mode</span>
            <select value={state.mode} onChange={(e) => setMode(e.target.value as Mode)} aria-label="Data mode">
              <option value="offline">Offline framework</option>
              <option value="replay">Demo replay (fixture)</option>
              <option value="live">Live adapter</option>
            </select>
          </label>
          {state.mode === 'replay' && replay && state.replay && (
            <span className="replay-controls">
              {state.replay.playing
                ? <button onClick={replay.pause} aria-label="Pause replay">❚❚ Pause</button>
                : <button onClick={replay.resume} disabled={state.replay.step >= state.replay.total} aria-label="Resume replay">▶ Resume</button>}
              <button onClick={replay.reset} aria-label="Reset replay">↺ Reset</button>
              <span className="num dim">{state.replay.step}/{state.replay.total}</span>
            </span>
          )}
        </div>
      </div>
      <div className="feed-row" aria-label="Feed connection status">
        <span className="feed-row-label">FEEDS</span>
        {feeds.map((f) => <FeedChip key={f.id} label={f.label} status={f.status} detail={f.detail} fixture={f.fixture} />)}
        <span className="feed-row-note faint">read-only · the console sends no commands</span>
      </div>
    </header>
  );
}

export function ReplayBanner() {
  const state = useConsoleState();
  if (state.mode !== 'replay') return null;
  return (
    <div className="replay-banner" role="status" data-testid="replay-banner">
      ◆ DEMO REPLAY · FICTIONAL FIXTURE DATA · Real map IDs, invented readings, detections, findings and alerts. Not an inspection result.
    </div>
  );
}

export function OfflineBanner() {
  const state = useConsoleState();
  if (state.mode !== 'offline') return null;
  return (
    <div className="offline-banner" role="status" data-testid="offline-banner">
      FRAMEWORK · OFFLINE — public map and static references only. No Isaac, robot, sensor, detector or assessment feed is connected; live values are unavailable.
    </div>
  );
}
