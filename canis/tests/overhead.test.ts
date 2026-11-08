import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { PublicMap } from '../src/contracts/publicMap';
import { overheadProjection, STILL } from '../src/map/overheadProjection';

const map: PublicMap = JSON.parse(readFileSync(resolve(__dirname, '../public/data/warehouse-map.public.json'), 'utf8'));
const proj = overheadProjection(map.hall_m.x, map.hall_m.y);

describe('overhead still projection (isaac_check.py "overhead" camera)', () => {
  it('reproduces the camera model', () => {
    expect(proj.focalMm).toBeCloseTo((36 * 45) / Math.max(24 + 4, (28.3 + 4) * 1.6), 6);
    expect(proj.pxPerM(0)).toBeCloseTo(30.96, 1);
    expect(proj.project(12, 14.15)).toEqual([800, 500]);
  });
  it('keeps +Y up the image and X to the right', () => {
    const [x0, y0] = proj.project(0, 0);
    const [x1, y1] = proj.project(24, 28.3);
    expect(x1).toBeGreaterThan(x0);
    expect(y1).toBeLessThan(y0);
  });
  it('places the whole hall and every drum top inside the 1600 × 1000 still', () => {
    for (const [x, y] of [[0, 0], [24, 0], [0, 28.3], [24, 28.3]]) {
      const [px, py] = proj.project(x, y);
      expect(px).toBeGreaterThan(0); expect(px).toBeLessThan(STILL.width);
      expect(py).toBeGreaterThan(0); expect(py).toBeLessThan(STILL.height);
    }
    for (const d of map.drums) {
      const [px, py] = proj.project(d.x_m, d.y_m, d.base_z_m + d.height_m);
      expect(px).toBeGreaterThan(377); expect(px).toBeLessThan(377 + 846);
      expect(py).toBeGreaterThan(0); expect(py).toBeLessThan(1000);
    }
  });
  it('pushes higher points away from the image centre (perspective)', () => {
    const floor = proj.project(2.8, 6.85, 0);
    const top = proj.project(2.8, 6.85, 3.1);
    expect(Math.abs(top[0] - 800)).toBeGreaterThan(Math.abs(floor[0] - 800));
  });
});

describe('dark brand variant', () => {
  it('changes only fill colours of the original dog mark', () => {
    const src = readFileSync(resolve(__dirname, '../brand-src/canis-logo.svg'), 'utf8');
    const out = readFileSync(resolve(__dirname, '../public/assets/brand/canis-dog-head-dark.svg'), 'utf8');
    const strip = (s: string) => s.replace(/#[0-9a-f]{6}/gi, '#');
    expect(strip(out)).toBe(strip(src));
    expect(out).toContain('fill: #f2c545;');
    expect(out).toContain('fill: #111315;');
    expect(out).not.toContain('#fefefe');
    expect(out.match(/fill: #111315;/g)).toHaveLength(2);
  });
  it('vendored source matches the workspace original when available', () => {
    const original = '/Users/levi/Desktop/agentverse/assets/canis logo.svg';
    let ws: string | null = null;
    try { ws = readFileSync(original, 'utf8'); } catch { /* not on this machine */ }
    if (ws) expect(readFileSync(resolve(__dirname, '../brand-src/canis-logo.svg'), 'utf8')).toBe(ws);
  });
});
