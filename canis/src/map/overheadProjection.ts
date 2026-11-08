/**
 * Projection for sim/warehouse-v3/review/wide-aisles/overhead.png (1600 × 1000).
 *
 * The still was rendered by sim/warehouse-v3/isaac_check.py ("overhead" view):
 * a perspective camera at (W/2, D/2, 45 m) looking straight down with up = +Y,
 * horizontal aperture 36 mm and focal = 36·45 / max(W + 4, (D + 4)·1.6).
 * A world point (x, y, z) therefore lands at
 *   px = 800 + (x − W/2)·k/(45 − z),   py = 500 − (y − D/2)·k/(45 − z),   k = 1600·focal/36.
 * Points higher up (drum tops) appear further from the image centre than the floor.
 */
export const STILL = { url: '/assets/stills/warehouse-wide-aisles-overhead.png', width: 1600, height: 1000 } as const;
export const CAMERA_HEIGHT_M = 45;
const APERTURE_MM = 36;

export interface OverheadProjection {
  /** Pixels per metre × (camera height − z). */
  k: number;
  focalMm: number;
  W: number;
  D: number;
  project(x: number, y: number, z?: number): [number, number];
  /** Image pixels per metre for a plane at height z. */
  pxPerM(z?: number): number;
}

export function overheadProjection(hallW: number, hallD: number): OverheadProjection {
  const focalMm = (APERTURE_MM * CAMERA_HEIGHT_M) / Math.max(hallW + 4, (hallD + 4) * 1.6);
  const k = (STILL.width * focalMm) / APERTURE_MM;
  const cx = STILL.width / 2, cy = STILL.height / 2;
  return {
    k, focalMm, W: hallW, D: hallD,
    project(x, y, z = 0) {
      const s = k / (CAMERA_HEIGHT_M - z);
      return [cx + (x - hallW / 2) * s, cy - (y - hallD / 2) * s];
    },
    pxPerM(z = 0) {
      return k / (CAMERA_HEIGHT_M - z);
    },
  };
}
