import type { ReactNode } from 'react';
import type { FeedStatus } from '../state/types';
import { formatAge, formatValueState, type ValueState } from '../lib/values';

export function Panel(props: {
  title: string;
  id?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${props.className ?? ''}`} aria-labelledby={props.id ? `${props.id}-title` : undefined}>
      <header className="panel-head">
        <h2 id={props.id ? `${props.id}-title` : undefined}>{props.title}</h2>
        {props.right && <div className="panel-head-right">{props.right}</div>}
      </header>
      <div className="panel-body">{props.children}</div>
    </section>
  );
}

/**
 * Scales its child to the largest box of the given aspect ratio that fits the
 * available width AND height (CSS container query units), so images and their
 * overlays stay aligned without page scrolling. Disabled → normal width-driven flow.
 */
export function Fit({ ratio, enabled = true, children }: { ratio: number; enabled?: boolean; children: ReactNode }) {
  if (!enabled) return <>{children}</>;
  return (
    <div className="fit">
      <div className="fit-box" style={{ width: `min(100cqw, calc(100cqh * ${ratio}))`, aspectRatio: String(ratio) }}>{children}</div>
    </div>
  );
}

export function FixtureBadge({ label = 'FIXTURE' }: { label?: string }) {
  return <span className="badge badge-fixture" title="Fictional demo fixture data, not an observation">◆ {label}</span>;
}

const FEED_ICON: Record<FeedStatus, string> = {
  not_configured: '○',
  connecting: '◌',
  connected: '●',
  stale: '◐',
  disconnected: '✕',
};
const FEED_TEXT: Record<FeedStatus, string> = {
  not_configured: 'NOT CONFIGURED',
  connecting: 'CONNECTING',
  connected: 'CONNECTED',
  stale: 'STALE',
  disconnected: 'DISCONNECTED',
};

export function FeedChip({ label, status, detail, fixture }: { label: string; status: FeedStatus; detail: string; fixture: boolean }) {
  return (
    <span className={`feed-chip feed-${status}`} title={`${label}: ${FEED_TEXT[status]} — ${detail}`}>
      <span aria-hidden>{FEED_ICON[status]}</span> {label} <span className="feed-state">{fixture && status === 'connected' ? 'REPLAY' : FEED_TEXT[status]}</span>
    </span>
  );
}

export function EmptyState({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      <div className="empty-reason">{reason}</div>
    </div>
  );
}

export function ValueCell({ state }: { state: ValueState }) {
  if (state.kind === 'missing' || state.kind === 'not_supplied' || state.kind === 'invalid') {
    const word = state.kind === 'missing' ? 'UNAVAILABLE' : state.kind === 'invalid' ? 'INVALID' : 'NOT SUPPLIED';
    return (
      <span className={`val val-${state.kind}`} data-state={state.kind} title={`${word}: ${state.reason}`}>
        <span className="num">{word}</span> <span className="val-reason">· {state.reason}</span>
      </span>
    );
  }
  const stale = state.stale;
  const cls = stale ? 'val val-stale' : state.kind === 'below_detection' ? 'val val-bdl' : 'val val-ok';
  return (
    <span className={cls} data-state={stale ? 'stale' : state.kind}>
      <span className="num">{formatValueState(state)}</span>
      {stale && <span className="val-tag"> · STALE {formatAge(state.ageS)}</span>}
    </span>
  );
}

export function SeverityTag({ severity }: { severity: 'info' | 'warning' | 'alert' }) {
  const icon = severity === 'alert' ? '▲' : severity === 'warning' ? '◆' : 'ℹ';
  return <span className={`sev sev-${severity}`}><span aria-hidden>{icon}</span> {severity.toUpperCase()}</span>;
}
