import { Activity, Bell, Camera, FileText, Pause, Play, RotateCcw, type LucideIcon } from 'lucide-react';
import { useConsole, useConsoleState, type TabId } from '../state/context';
import { formatClock } from '../lib/values';
import { FeedChip } from './common';
import { FEED_IDS, type Mode } from '../state/types';

export const TABS: { id: TabId; label: string; icon: LucideIcon }[] = [
  { id: 'simulation', label: 'Simulation', icon: Play },
  { id: 'inspection', label: 'Inspection', icon: Camera },
  { id: 'sensors', label: 'Sensors', icon: Activity },
  { id: 'alerts', label: 'Alerts', icon: Bell },
  { id: 'logs', label: 'Logs', icon: FileText },
];

const MODE_LABEL: Record<Mode, string> = {
  offline: 'OFFLINE',
  replay: 'DEMO REPLAY',
  live: 'LIVE',
};

export function Header({ tab, onTab }: { tab: TabId; onTab(t: TabId): void }) {
  const state = useConsoleState();
  const { setMode } = useConsole();
  const feeds = FEED_IDS.map((id) => state.feeds[id]);
  const unacked = state.alerts.filter((a) => !state.acknowledged.has(a.msg.alert_id) && a.msg.severity !== 'info').length;
  const anyConnected = feeds.some((f) => f.status === 'connected' && !f.fixture);
  const dot = state.mode === 'replay' ? 'dot-replay' : state.mode === 'live' ? (anyConnected ? 'dot-live' : 'dot-wait') : 'dot-offline';

  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
    onTab(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  };

  return (
    <header className="app-header">
      <div className="brand" aria-label="C.A.N.I.S. — Containment Analysis & Nuclear Intelligence System">
        <img className="brand-mark" src="/assets/brand/canis-dog-head-dark.svg" alt="" width={160} height={160} />
        <div className="brand-text">
          <img className="brand-word" src="/assets/brand/canis-wordmark.png" alt="C.A.N.I.S." width={1092} height={293} />
          <span className="brand-sub">Containment Analysis &amp; Nuclear Intelligence System</span>
        </div>
      </div>
      <span className="hdr-divider" aria-hidden />

      <nav className="tabs" role="tablist" aria-label="Console sections">
        {TABS.map((t, i) => {
          const I = t.icon;
          return (
            <button key={t.id} id={`tab-${t.id}`} role="tab" aria-selected={tab === t.id} aria-controls={`panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1} className={`tab ${tab === t.id ? 'tab-active' : ''}`}
              onClick={() => onTab(t.id)} onKeyDown={(e) => onKey(e, i)}>
              <I size={15} strokeWidth={2} aria-hidden />
              {t.label.toUpperCase()}
              {t.id === 'alerts' && unacked > 0 && <span className="tab-count" aria-label={`${unacked} unacknowledged`}>{unacked}</span>}
            </button>
          );
        })}
      </nav>
      <span className="hdr-divider" aria-hidden />

      <div className="header-controls">
        <label className="hdr-field">
          <span className="hdr-label">System state</span>
          <span className={`hdr-select state-select ${dot}`}>
            <span className="state-dot" aria-hidden />
            <select value={state.mode} onChange={(e) => setMode(e.target.value as Mode)} aria-label="System state" data-testid="mode-chip-select">
              <option value="offline">OFFLINE</option>
              <option value="replay">DEMO REPLAY</option>
              <option value="live">LIVE</option>
            </select>
          </span>
          <span className="sr-only" data-testid="mode-chip">{state.mode === 'offline' ? 'FRAMEWORK · OFFLINE' : MODE_LABEL[state.mode]}</span>
        </label>
        <label className="hdr-field">
          <span className="hdr-label">Map</span>
          <span className="hdr-select">
            <select defaultValue="public" aria-label="Map source">
              <option value="public">Public (Static)</option>
              <option value="live" disabled>Live (needs Isaac)</option>
            </select>
          </span>
        </label>
        {state.mode !== 'replay' && state.simClockS !== undefined && (
          <div className="hdr-field">
            <span className="hdr-label">Sim elapsed</span>
            <span className="elapsed num" data-testid="elapsed"><span className="sr-only">SIM ELAPSED </span>{formatClock(state.simClockS)}</span>
          </div>
        )}
      </div>

      <div className="feed-row" aria-label="Feed connection status">
        <span className="feed-row-label">FEEDS</span>
        {feeds.map((f) => <FeedChip key={f.id} label={f.label} status={f.status} detail={f.detail} fixture={f.fixture} />)}
      </div>
    </header>
  );
}

export function ReplayBanner() {
  const state = useConsoleState();
  const { replay } = useConsole();
  if (state.mode !== 'replay') return null;
  return (
    <div className="replay-banner" data-testid="replay-banner">
      <span role="status">◆ DEMO REPLAY · FICTIONAL FIXTURE DATA · Real map IDs, invented readings, detections, findings and alerts. Not an inspection result.</span>
      <span className="replay-controls">
        {state.simClockS !== undefined && <span className="elapsed num" data-testid="elapsed"><span className="sr-only">REPLAY CLOCK </span>t {formatClock(state.simClockS)}</span>}
        {replay && state.replay && (state.replay.playing
          ? <button onClick={replay.pause} aria-label="Pause replay"><Pause size={13} aria-hidden /> Pause</button>
          : <button onClick={replay.resume} disabled={state.replay.step >= state.replay.total} aria-label="Resume replay"><Play size={13} aria-hidden /> Resume</button>)}
        {replay && <button onClick={replay.reset} aria-label="Reset replay"><RotateCcw size={13} aria-hidden /> Reset</button>}
      </span>
    </div>
  );
}
