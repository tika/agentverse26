/**
 * Converts a WarehouseObservations checkpoint (scripts/hot/warehouse_observations.py,
 * Codex lane, commit 8fe63c9) into canis.v1 inspection_record messages.
 *
 * Checkpoint format: { run_id, packages: { "<printed code>": { "<frame_id>": { view, finding } } } }
 * The checkpoint carries no timestamps, so records have no t_sim_s.
 */
export interface LedgerCheckpoint {
  run_id: string;
  packages: Record<string, Record<string, { view: string; finding: unknown }>>;
}

export function isLedgerCheckpoint(value: unknown): value is LedgerCheckpoint {
  const v = value as LedgerCheckpoint;
  return Boolean(v) && typeof v.run_id === 'string' && typeof v.packages === 'object' && v.packages !== null;
}

function findingText(finding: unknown): string | null {
  if (finding === null || finding === undefined) return null;
  if (typeof finding === 'string') return finding;
  return JSON.stringify(finding);
}

export function ledgerToMessages(checkpoint: LedgerCheckpoint, sourceId = 'ledger-file'): unknown[] {
  const out: unknown[] = [];
  let seq = 0;
  for (const [packageId, frames] of Object.entries(checkpoint.packages)) {
    for (const [frameId, evidence] of Object.entries(frames ?? {})) {
      out.push({
        schema: 'canis.v1',
        kind: 'inspection_record',
        source: { id: sourceId, kind: 'ledger_file' },
        seq: seq++,
        quality: 'ok',
        run_id: checkpoint.run_id,
        package_id: packageId,
        frame_id: frameId,
        view: evidence?.view,
        finding: findingText(evidence?.finding),
        evidence: [{ kind: 'camera_frame', ref: frameId }],
      });
    }
  }
  return out;
}
