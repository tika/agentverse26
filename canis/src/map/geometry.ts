import type { PublicDrum, PublicMap } from '../contracts/publicMap';

/**
 * World frame: metres, +X east along the hall width (0..24), +Y north along
 * the hall length (0..28.3), Z up. SVG screen space has +Y pointing down, so
 * every world point is converted with an explicit flip about the hall length.
 * 1 SVG user unit = 1 metre, so aspect ratio is preserved by construction.
 */
export function toScreen(map: Pick<PublicMap, 'hall_m'>, x: number, y: number): [number, number] {
  return [x, map.hall_m.y - y];
}

export function toWorld(map: Pick<PublicMap, 'hall_m'>, sx: number, sy: number): [number, number] {
  return [sx, map.hall_m.y - sy];
}

/** Pick a round scale-bar length (m) that is roughly a fifth of the hall width. */
export function scaleBarMetres(widthM: number): number {
  const target = widthM / 5;
  const options = [1, 2, 5, 10, 20, 50];
  return options.reduce((best, v) => (Math.abs(v - target) < Math.abs(best - target) ? v : best), options[0]);
}

export interface Stack {
  stack_id: string;
  x_m: number;
  y_m: number;
  category: PublicDrum['category'];
  /** Drums at this XY, ordered by tier (T1 floor upward). */
  drums: PublicDrum[];
}

/** Drums at the same XY share a stack; selection resolves the tier explicitly. */
export function groupStacks(drums: PublicDrum[]): Stack[] {
  const byXY = new Map<string, Stack>();
  for (const d of drums) {
    const key = `${d.x_m.toFixed(3)},${d.y_m.toFixed(3)}`;
    let s = byXY.get(key);
    if (!s) {
      s = { stack_id: d.stack_id, x_m: d.x_m, y_m: d.y_m, category: d.category, drums: [] };
      byXY.set(key, s);
    }
    s.drums.push(d);
  }
  for (const s of byXY.values()) s.drums.sort((a, b) => a.tier - b.tier);
  return [...byXY.values()];
}
