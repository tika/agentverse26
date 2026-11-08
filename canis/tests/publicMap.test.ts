import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { PublicMap } from '../src/contracts/publicMap';
import { findPrivateKeys } from '../src/contracts/privacy';
import { groupStacks, scaleBarMetres, toScreen, toWorld } from '../src/map/geometry';

const map: PublicMap = JSON.parse(readFileSync(resolve(__dirname, '../public/data/warehouse-map.public.json'), 'utf8'));
const sourcePath = resolve(__dirname, '../../sim/warehouse-v3/map.json');
const source = JSON.parse(readFileSync(sourcePath, 'utf8'));

describe('public map matches sim/warehouse-v3/map.json', () => {
  it('records the exact source hash', () => {
    expect(map.source.sha256).toBe(createHash('sha256').update(readFileSync(sourcePath)).digest('hex'));
  });
  it('has the real warehouse extent and inventory', () => {
    expect(map.hall_m).toEqual({ x: 24, y: 28.3, z: source.hall[2] });
    expect(map.drums).toHaveLength(420);
    expect(map.drums.filter((d) => d.category === 'LLW')).toHaveLength(336);
    expect(map.drums.filter((d) => d.category === 'ILW')).toHaveLength(84);
    expect(map.racks).toHaveLength(56);
    expect(map.zones).toEqual({ A: 'LLW', B: 'ILW' });
    expect(map.robot_start_m).toEqual([1, 6, 0]);
    expect(map.edges).toHaveLength(source.edges.length);
  });
  it('keeps every drum identity, printed code and pose', () => {
    const byId = new Map(source.drums.map((d: { id: string }) => [d.id, d]));
    for (const d of map.drums) {
      const s = byId.get(d.id) as Record<string, any>;
      expect(d.location_code).toBe(s.display_id);
      expect(d.location_code).toBe(s.location.location_code);
      expect([d.x_m, d.y_m, d.base_z_m, d.tier, d.stack_id, d.prim_path]).toEqual([s.x, s.y, s.base_z, s.location.tier, s.stack_id, s.prim_path]);
    }
    expect(new Set(map.drums.map((d) => d.location_code)).size).toBe(420);
  });
  it('has five aisle route lines between rack rows (y = 4.83 … 23.47)', () => {
    const ys = [...new Set(Object.values(map.nodes).map((p) => p[1]))].sort((a, b) => a - b);
    expect(ys).toEqual(expect.arrayContaining([4.83, 9.49, 14.15, 18.81, 23.47]));
  });
  it('contains no private truth or baseline placeholder fields', () => {
    expect(findPrivateKeys(map)).toEqual([]);
    const drumKeys = new Set(map.drums.flatMap((d) => Object.keys(d)));
    for (const k of ['state', 'faults', 'defects', 'corrosion_severity', 'shape', 'source_strength', 'scene_seed', 'appearance_seed', 'paint_color', 'internal_corrosion']) {
      expect(drumKeys.has(k)).toBe(false);
    }
    expect('seed' in map).toBe(false);
  });
});

describe('map geometry', () => {
  it('flips Y explicitly and round-trips', () => {
    expect(toScreen(map, 0, 0)).toEqual([0, 28.3]);
    expect(toScreen(map, 24, 28.3)).toEqual([24, 0]);
    expect(toWorld(map, ...toScreen(map, 3.1, 7.16))).toEqual([3.1, expect.closeTo(7.16, 10)]);
  });
  it('groups 140 shared-XY stacks of three tiers', () => {
    const stacks = groupStacks(map.drums);
    expect(stacks).toHaveLength(140);
    for (const s of stacks) expect(s.drums.map((d) => d.tier)).toEqual([1, 2, 3]);
  });
  it('picks a round scale bar', () => {
    expect(scaleBarMetres(24)).toBe(5);
  });
});
