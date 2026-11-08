// Derive the dark-header dog mark from the original artwork (brand-src/canis-logo.svg,
// a byte copy of assets/canis logo.svg). Only the three fill colours change; paths,
// viewBox and proportions are untouched.
//   .st0 #161615 (black body)    -> #f2c545 brand yellow
//   .st2 #f2c545 (yellow accent) -> #111315 header charcoal
//   .st1 #fefefe (eye)           -> #111315 header charcoal
// The wordmark (canis-type.svg) is live text in a font that is not shipped, so the
// console keeps the original wordmark PNG and inverts it to white in CSS instead.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const SWAPS = [['#161615', '#f2c545'], ['#f2c545', '#111315'], ['#fefefe', '#111315']];

export function darkVariant(svg) {
  const marker = (i) => `@@SWAP${i}@@`;
  let out = svg;
  SWAPS.forEach(([from], i) => {
    if (!out.includes(`fill: ${from};`)) throw new Error(`expected fill ${from} in source SVG`);
    out = out.replace(`fill: ${from};`, `fill: ${marker(i)};`);
  });
  SWAPS.forEach(([, to], i) => { out = out.replace(marker(i), to); });
  return out;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const src = readFileSync(resolve(here, '../brand-src/canis-logo.svg'), 'utf8');
  const outPath = resolve(here, '../public/assets/brand/canis-dog-head-dark.svg');
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, darkVariant(src));
  console.log(`brand: wrote ${outPath}`);
}
