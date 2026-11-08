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

describe('assessment records (camera result layer + map)', () => {
  const base = {
    schema: 'canis.v1', kind: 'assessment', source: { id: 'assessor', kind: 'assessment' }, quality: 'ok',
    assessment_id: 'AS-1', run_id: 'seed-42', package_id: 'A-L-01-T1', tier: 1, status: 'unsure',
    reason: 'single view', evidence_frame_ids: ['sensor_patrol-00042'],
    shapes: [{ camera_id: 'rgb', frame_id: 'sensor_patrol-00042', bbox_px: [10, 20, 30, 40] }],
  };
  it('accepts a valid record and keeps it separate from coverage', async () => {
    const { assessmentsByPackage } = await import('../src/lib/inspection');
    const store = new ConsoleStore('live');
    const bus = new FeedBus(store);
    expect(bus.ingest({ ...base, seq: 0 }, 't')).toBe('accepted');
    expect(assessmentsByPackage(store.getState()).get('A-L-01-T1')!.msg.status).toBe('unsure');
    expect(packageStatuses(store.getState()).get('A-L-01-T1')?.coverage ?? 'unseen').toBe('unseen');
  });
  it('rejects a tier that disagrees with the printed code, and defect without a type', () => {
    const bus = new FeedBus(new ConsoleStore('live'));
    expect(bus.ingest({ ...base, seq: 0, tier: 2 }, 't')).toBe('schema_failure');
    expect(bus.ingest({ ...base, seq: 1, status: 'defect' }, 't')).toBe('schema_failure');
    expect(bus.ingest({ ...base, seq: 2, status: 'defect', defect_types: ['corrosion'] }, 't')).toBe('accepted');
    expect(bus.ingest({ ...base, seq: 3, evidence_frame_ids: [] }, 't')).toBe('schema_failure');
  });
});

describe('Codex exporter compatibility (detector/canis_frame_events.py shape)', () => {
  it('accepts an exported rgb frame and a YOLO detection on the same frame_id', () => {
    const store = new ConsoleStore('live');
    const bus = new FeedBus(store);
    const env = (kind: string, source: string, seq: number, fields: object) =>
      ({ schema: 'canis.v1', kind, source: { kind: source, id: `warehouse-${source}` }, seq, quality: 'ok', ...fields });
    expect(bus.ingest(env('camera_frame', 'isaac', 0, { camera_id: 'rgb', frame_id: 'seed42-stop1-front', width: 640, height: 360, uri: 'data:image/png;base64,AA==', encoding: 'png' }), 'x')).toBe('accepted');
    expect(bus.ingest(env('detection', 'detector', 0, { camera_id: 'rgb', frame_id: 'seed42-stop1-front', detection_id: 'seed42-stop1-front:0', class_id: 0, bbox_px: [1, 2, 3, 4], confidence: 0.9, model_id: 'run:' + 'a'.repeat(64) }), 'x')).toBe('accepted');
    expect(bus.ingest({ ...env('detection', 'detector', 1, { camera_id: 'rgb', frame_id: 'seed42-stop1-front', detection_id: 'p:1', class_id: 0, bbox_px: [1, 2, 3, 4], confidence: 0.5, model_id: 'optical-flow-preview' }), quality: 'degraded' }, 'x')).toBe('accepted');
    expect(store.getState().detections).toHaveLength(2);
  });
});
