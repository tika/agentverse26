import { useState } from 'react';
import { isLedgerCheckpoint, ledgerToMessages } from '../adapters/ledger';
import { useConsole, useConsoleState } from '../state/context';

/**
 * Load a WarehouseObservations checkpoint (mission ledger JSON) from disk.
 * Records pass through the same FeedBus boundary as live data.
 */
export function LedgerLoader() {
  const { bus, store } = useConsole();
  const state = useConsoleState();
  const [msg, setMsg] = useState('');
  if (state.mode === 'replay') return null;
  const onFile = async (file: File | undefined) => {
    if (!file) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      setMsg('Not JSON');
      store.log('error', 'schema', 'ledger-file', `${file.name}: not JSON`);
      return;
    }
    if (!isLedgerCheckpoint(parsed)) {
      setMsg('Not a ledger checkpoint ({run_id, packages})');
      store.log('error', 'schema', 'ledger-file', `${file.name}: missing run_id/packages`);
      return;
    }
    const results = ledgerToMessages(parsed, `ledger-file:${file.name}`).map((m) => bus.ingest(m, 'ledger-file'));
    const ok = results.filter((r) => r === 'accepted').length;
    setMsg(`${ok} records accepted, ${results.length - ok} rejected`);
    store.log('info', 'feed', 'ledger-file', `Loaded ledger ${file.name} (run ${parsed.run_id}): ${ok}/${results.length} records accepted`);
  };
  return (
    <div className="ledger-loader">
      <label className="file-btn">
        Load mission ledger checkpoint…
        <input type="file" accept="application/json,.json" onChange={(e) => onFile(e.target.files?.[0])} />
      </label>
      <span className="faint small">WarehouseObservations JSON; coverage = front + oblique views. Read locally, nothing uploaded.</span>
      {msg && <span className="dim small" role="status">{msg}</span>}
    </div>
  );
}
