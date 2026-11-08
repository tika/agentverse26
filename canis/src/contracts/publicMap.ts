/** Shape of public/data/warehouse-map.public.json (built by scripts/build-public-map.mjs). */
export type Category = 'LLW' | 'ILW';

export interface PublicDrum {
  id: string;
  /** Printed location code, e.g. "A-L-01-T1" (map.json display_id / location.location_code). */
  location_code: string;
  category: Category;
  zone: string;
  row: string;
  stack_id: string;
  lane: string;
  side: string;
  column: number;
  tier: number;
  tier_count: number;
  depth: number;
  x_m: number;
  y_m: number;
  base_z_m: number;
  yaw_rad: number;
  radius_m: number;
  height_m: number;
  face_sign: number;
  facing_aisle: number;
  inspection_route_y_m: number;
  prim_path: string;
}

export interface PublicRack {
  id: string;
  zone: string;
  category: Category;
  center: [number, number];
  size: number;
  deck_tops: number[];
}

export interface PublicMap {
  schema: 'canis.public-map.v1';
  source: { file: string; sha256: string; map_schema_version: number; baseline_revision: string };
  units: string;
  up_axis: string;
  frame: 'world_m_zup';
  hall_m: { x: number; y: number; z: number };
  robot_start_m: [number, number, number];
  zones: Record<string, Category>;
  staging_bounds_m: [number, number, number, number][];
  racks: PublicRack[];
  nodes: Record<string, [number, number]>;
  edges: [string, string][];
  drums: PublicDrum[];
}
