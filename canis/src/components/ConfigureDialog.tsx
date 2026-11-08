import { useEffect, useRef, useState } from 'react';
import { Link, PlayCircle, Upload, X } from 'lucide-react';
import { useConsole } from '../state/context';
import { FEED_IDS, type FeedId } from '../state/types';
import { parseFeedConfig } from '../adapters/LiveAdapter';
import { LedgerLoader } from './LedgerLoader';

/**
 * Configure Simulation: choose where data comes from. Everything here only
 * changes what the console listens to; nothing is sent to Isaac or the robot.
 */
export function ConfigureDialog({ onClose }: { onClose(): void }) {
  const { setMode, openTab } = useConsole();
  const [urls, setUrls] = useState<Partial<Record<FeedId, string>>>(() =>
    parseFeedConfig(new URLSearchParams(window.location.search).get('feeds')));
  const [error, setError] = useState('');
  const first = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const connect = () => {
    const spec = FEED_IDS.filter((id) => urls[id]?.trim()).map((id) => `${id}=${urls[id]!.trim()}`).join(',');
    const parsed = parseFeedConfig(spec);
    if (!Object.keys(parsed).length) return setError('Enter at least one ws:// or wss:// URL.');
    if (Object.keys(parsed).length !== spec.split(',').length) return setError('Every URL must start with ws:// or wss://.');
    setMode('live', spec);
    onClose();
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="cfg-title" data-testid="configure-dialog">
        <header className="modal-head">
          <h2 id="cfg-title">Configure simulation</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </header>
        <p className="faint small">Read-only: these options choose what the console listens to. Nothing is sent to Isaac Sim or the robot.</p>

        <section className="cfg-section">
          <h3><PlayCircle size={15} aria-hidden /> Recorded run</h3>
          <p className="dim small">Deterministic demo on real map IDs with fictional readings, labelled DEMO REPLAY throughout.</p>
          <button ref={first} className="btn-primary" onClick={() => { setMode('replay'); openTab('simulation'); onClose(); }}>Start demo replay</button>
        </section>

        <section className="cfg-section">
          <h3><Link size={15} aria-hidden /> Live feeds (WebSocket, canis.v1)</h3>
          <div className="cfg-grid">
            {FEED_IDS.map((id) => (
              <label key={id} className="cfg-row">
                <span className="mono">{id}</span>
                <input type="url" placeholder={`ws://host:port (${id})`} value={urls[id] ?? ''}
                  onChange={(e) => { setUrls({ ...urls, [id]: e.target.value }); setError(''); }} />
              </label>
            ))}
          </div>
          {error && <div className="cfg-error" role="alert">{error}</div>}
          <button className="btn-primary" onClick={connect}>Connect live feeds</button>
          <p className="faint small">Message contract: docs/canis/INTEGRATION_CHECKLIST.md. Unfilled feeds stay "not configured".</p>
        </section>

        <section className="cfg-section">
          <h3><Upload size={15} aria-hidden /> Mission ledger checkpoint</h3>
          <LedgerLoader />
        </section>
      </div>
    </div>
  );
}
