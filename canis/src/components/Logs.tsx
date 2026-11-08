import { useState } from 'react';
import { useConsoleState } from '../state/context';
import type { LogCategory, LogEntry } from '../state/types';
import { Panel } from './common';

const CATEGORIES: LogCategory[] = ['feed', 'mode', 'replay', 'schema', 'privacy', 'duplicate', 'out_of_order', 'late', 'stale', 'map', 'ui'];

export function toJsonl(entries: LogEntry[]): string {
  return entries.map((e) => JSON.stringify({
    wall_time: new Date(e.wallMs).toISOString(), sim_s: e.simS ?? null, level: e.level,
    category: e.category, source: e.source, fixture: e.fixture, message: e.message,
  })).join('\n') + '\n';
}

export function Logs() {
  const state = useConsoleState();
  const [cat, setCat] = useState<'' | LogCategory>('');
  const [level, setLevel] = useState<'' | 'info' | 'warn' | 'error'>('');
  const [q, setQ] = useState('');
  const [copied, setCopied] = useState('');
  const visible = state.logs.filter((l) => (!cat || l.category === cat) && (!level || l.level === level)
    && (!q || `${l.source} ${l.message}`.toLowerCase().includes(q.toLowerCase())));

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toJsonl(visible));
      setCopied(`Copied ${visible.length} entries`);
    } catch {
      setCopied('Clipboard unavailable; use Export');
    }
  };
  const exportFile = () => {
    const blob = new Blob([toJsonl(visible)], { type: 'application/x-ndjson' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `canis-logs-${state.mode}-${new Date().toISOString().replace(/[:.]/g, '-')}.jsonl`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <Panel title="Logs" id="logs" className="logs-panel"
      right={<span className="dim">payload values and private truth are never logged</span>}>
      <div className="filters">
        <select aria-label="Log category" value={cat} onChange={(e) => setCat(e.target.value as typeof cat)}>
          <option value="">All categories</option>{CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select aria-label="Log level" value={level} onChange={(e) => setLevel(e.target.value as typeof level)}>
          <option value="">All levels</option><option value="info">info</option><option value="warn">warn</option><option value="error">error</option>
        </select>
        <input type="search" placeholder="Filter text" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter log text" />
        <button onClick={copy}>Copy visible</button>
        <button onClick={exportFile} data-testid="export-logs">Export .jsonl</button>
        <span className="num dim" data-testid="log-count">{visible.length} / {state.logs.length}</span>
        {copied && <span className="dim" role="status">{copied}</span>}
      </div>
      <div className="table-scroll logs-scroll">
        <table className="log-table" data-testid="log-table">
          <thead><tr><th>Wall time</th><th>Sim s</th><th>Level</th><th>Category</th><th>Source</th><th>Message</th></tr></thead>
          <tbody>
            {[...visible].reverse().map((l) => (
              <tr key={l.id} className={`log-${l.level}`}>
                <td className="num">{new Date(l.wallMs).toLocaleTimeString()}</td>
                <td className="num">{l.simS !== undefined ? l.simS.toFixed(0) : '—'}</td>
                <td>{l.level === 'error' ? '✕ error' : l.level === 'warn' ? '◆ warn' : 'ℹ info'}</td>
                <td>{l.category}</td>
                <td className="mono">{l.source}{l.fixture ? ' ◆' : ''}</td>
                <td>{l.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
