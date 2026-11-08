import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { PublicMap } from '../src/contracts/publicMap';
import { buildReplay } from '../src/fixtures/replay';
import { findPrivateKeys } from '../src/contracts/privacy';
import { ConsoleStore } from '../src/state/store';
import { FeedBus } from '../src/ingest/FeedBus';
import { ReplayAdapter } from '../src/adapters/ReplayAdapter';
import { sensorRows } from '../src/lib/sensorRows';

const map: PublicMap = JSON.parse(readFileSync(resolve(__dirname, '../public/data/warehouse-map.public.json'), 'utf8'));

function run(until: number) {
  const store = new ConsoleStore('replay');
  const bus = new FeedBus(store);
  const replay = new ReplayAdapter(1e9);
  replay.start({ store, bus, map }); // applies step 0
  replay.pause();
  while ((store.getState().simClockS ?? 0) < until) replay.step();
  return store.getState();
}

describe('demo replay fixture', () => {
  const steps = buildReplay(map);
  const all = steps.flatMap((s) => s.messages) as { source: { fixture?: boolean; kind: string } }[];

  it('is deterministic', () => {
    expect(JSON.stringify(buildReplay(map))).toBe(JSON.stringify(steps));
  });
  it('marks every message as a replay fixture and carries no private truth', () => {
    expect(all.every((m) => m.source.fixture === true && m.source.kind === 'replay')).toBe(true);
    expect(findPrivateKeys(steps)).toEqual([]);
  });
  it('uses real map identities', () => {
    const codes = new Set(map.drums.map((d) => d.location_code));
    const used = all.flatMap((m) => [(m as any).package_id, (m as any).drum_attribution?.package_id]).filter(Boolean);
    expect(used.length).toBeGreaterThan(0);
    expect(used.every((c) => codes.has(c))).toBe(true);
  });
  it('demonstrates below-detection, stale, inconclusive and proposed-not-sent', () => {
    const at20 = run(20);
    expect(sensorRows(at20, 0).find((r) => r.key === 'h2')!.state.kind).toBe('below_detection');
    const at42 = run(42);
    expect(at42.stale.sensor).toBe(true);
    expect(at42.findings.some((f) => f.msg.status === 'inconclusive')).toBe(true);
    expect(at42.alerts.some((a) => a.msg.proposed_action?.status === 'proposed_not_sent')).toBe(true);
    const cats = at42.logs.map((l) => l.category);
    expect(cats).toEqual(expect.arrayContaining(['duplicate', 'out_of_order', 'schema', 'stale']));
    const end = run(60);
    expect(end.stale.sensor).toBe(false);
  });
});
