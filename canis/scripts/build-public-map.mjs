// Build the public map/inventory payload served to the browser.
// Source of truth: ../sim/warehouse-v3/map.json. Only allowlisted keys are copied.
// Baseline placeholder fields (state, faults, defects, corrosion_severity, shape,
// source_strength, seeds, legacy_*) are deliberately dropped: they are not
// observations and showing "clean" would assert a diagnosis.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const mapPath = resolve(here, '../../sim/warehouse-v3/map.json');
const outPath = resolve(here, '../public/data/warehouse-map.public.json');

const raw = readFileSync(mapPath);
const map = JSON.parse(raw.toString('utf8'));

const pick = (obj, keys) => Object.fromEntries(keys.filter((k) => k in obj).map((k) => [k, obj[k]]));

const drums = map.drums.map((d) => ({
  id: d.id,
  location_code: d.location.location_code,
  category: d.category,
  zone: d.zone,
  row: d.row,
  stack_id: d.stack_id,
  lane: d.location.lane,
  side: d.location.side,
  column: d.location.column,
  tier: d.location.tier,
  tier_count: d.location.tier_count,
  depth: d.location.depth,
  x_m: d.x,
  y_m: d.y,
  base_z_m: d.base_z,
  yaw_rad: d.yaw,
  radius_m: d.radius,
  height_m: d.height,
  face_sign: d.face_sign,
  facing_aisle: d.facing_aisle,
  inspection_route_y_m: d.inspection_route_y,
  prim_path: d.prim_path,
}));

const out = {
  schema: 'canis.public-map.v1',
  source: {
    file: 'sim/warehouse-v3/map.json',
    sha256: createHash('sha256').update(raw).digest('hex'),
    map_schema_version: map.schema_version,
    baseline_revision: map.baseline_revision,
  },
  units: map.units,
  up_axis: map.up_axis,
  frame: 'world_m_zup',
  hall_m: { x: map.hall[0], y: map.hall[1], z: map.hall[2] },
  robot_start_m: map.robot_start,
  zones: map.zones,
  staging_bounds_m: map.staging_bounds,
  racks: map.racks.map((r) => pick(r, ['id', 'zone', 'category', 'center', 'size', 'deck_tops'])),
  nodes: map.nodes,
  edges: map.edges,
  drums,
};

mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, JSON.stringify(out) + '\n');
const llw = drums.filter((d) => d.category === 'LLW').length;
console.log(`public map: ${drums.length} drums (${llw} LLW / ${drums.length - llw} ILW), ${out.racks.length} racks -> ${outPath}`);
