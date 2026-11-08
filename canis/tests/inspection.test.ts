import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { PublicMap } from '../src/contracts/publicMap';
import { ConsoleStore } from '../src/state/store';
import { FeedBus } from '../src/ingest/FeedBus';
import { ledgerToMessages } from '../src/adapters/ledger';
import { EMPTY_FILTER, filterDrums, matchesQuery, packageStatuses } from '../src/lib/inspection';

const map: PublicMap = JSON.parse(readFileSync(resolve(__dirname, '../public/data/warehouse-map.public.json'), 'utf8'));
const d = (id: string) => map.drums.find((x) => x.id === id)!;

describe('search and filters', () => {
  it('matches canonical IDs and printed codes', () => {
    expect(matchesQuery(d('D07'), 'd7')).toBe(true);
    expect(matchesQuery(d('D07'), '007')).toBe(true);
    expect(matchesQuery(d('D70'), 'D7')).toBe(true); // substring on prefixed form
    expect(matchesQuery(d('D07'), '70')).toBe(false);
    expect(matchesQuery(d('D01'), 'a-l-01-t1')).toBe(true);
    expect(filterDrums(map.drums, { ...EMPTY_FILTER, query: 'A-L-01-T1' }, new Map()).map((x) => x.id)).toContain('D01');
  });
  it('filters by class, rack, tier and starts everything unseen', () => {
    const none = new Map();
    expect(filterDrums(map.drums, { ...EMPTY_FILTER, category: 'ILW' }, none)).toHaveLength(84);
    expect(filterDrums(map.drums, { ...EMPTY_FILTER, tier: '3' }, none)).toHaveLength(140);
    expect(filterDrums(map.drums, { ...EMPTY_FILTER, coverage: 'unseen' }, none)).toHaveLength(420);
    const rack = map.racks[0].id;
    expect(filterDrums(map.drums, { ...EMPTY_FILTER, rack }, none).every((x) => x.stack_id === rack)).toBe(true);
  });
});

describe('ledger compatibility (scripts/hot/warehouse_observations.py)', () => {
  it('derives unseen / seen / inspected exactly like WarehouseObservations.coverage()', () => {
    const store = new ConsoleStore('offline');
    const bus = new FeedBus(store);
    const checkpoint = {
      run_id: 'seed-42-walk',
      packages: {
        'A-L-01-T1': { 'f0001': { view: 'front', finding: null }, 'f0007': { view: 'oblique', finding: 'corrosion' } },
        'A-L-04-T1': { 'f0010': { view: 'front', finding: null } },
        'A-L-06-T1': {},
      },
    };
    const results = ledgerToMessages(checkpoint).map((m) => bus.ingest(m, 'ledger'));
    expect(results).toEqual(['accepted', 'accepted', 'accepted']);
    const st = packageStatuses(store.getState());
    expect(st.get('A-L-01-T1')!.coverage).toBe('inspected');
    expect(st.get('A-L-04-T1')!.coverage).toBe('seen');
    expect(st.get('A-L-06-T1')).toBeUndefined();
    expect(store.getState().feeds.mission.status).toBe('connected');
  });
  it('rejects ledger entries keyed by something other than a printed code', () => {
    const store = new ConsoleStore('offline');
    const bus = new FeedBus(store);
    const [msg] = ledgerToMessages({ run_id: 'r', packages: { D01: { f: { view: 'front', finding: null } } } });
    expect(bus.ingest(msg, 'ledger')).toBe('schema_failure');
  });
});
