// Scan everything the browser can receive for private simulator / evaluator truth.
// - JSON files: any denylisted key at any depth fails.
// - JS/CSS/HTML bundles: a denylisted name used as an object key ("key": or key:) fails.
//   The denylist array itself is shipped as plain strings and does not match.
// - Any file: references to evaluator outputs or private manifests fail.
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const { keys } = JSON.parse(readFileSync(join(root, 'src/contracts/private-keys.json'), 'utf8'));
const KEYS = new Set(keys);
const PATH_PATTERNS = [/out\/evaluator/, /physical-sensor-calibration/, /fault[-_]manifest/i];
const targets = ['public', 'dist', 'src/fixtures'].map((p) => join(root, p)).filter(existsSync);

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else yield p;
  }
}

function jsonKeys(value, path, out) {
  if (Array.isArray(value)) value.forEach((v, i) => jsonKeys(v, `${path}[${i}]`, out));
  else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) {
      if (KEYS.has(k)) out.push(`${path}.${k}`);
      jsonKeys(v, `${path}.${k}`, out);
    }
  }
  return out;
}

// Generic words that are private only as map.json/manifest fields; enforced in JSON and at the
// ingest boundary, but too common to scan for in minified UI code.
const BUNDLE_SKIP = new Set(['state', 'shape', 'sites']);
const bundleKeys = keys.filter((k) => !BUNDLE_SKIP.has(k));
const keyPattern = new RegExp(`(?:[{,]\\s*)(?:"|')?(${bundleKeys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?:"|')?\\s*:`, 'g');
const problems = [];
let files = 0;
for (const dir of targets) {
  for (const file of walk(dir)) {
    const rel = relative(root, file);
    if (/\.(png|jpe?g|webp|woff2?|ttf|ico)$/i.test(file)) continue;
    files += 1;
    const text = readFileSync(file, 'utf8');
    if (rel.endsWith('private-keys.json')) continue;
    if (file.endsWith('.json')) {
      for (const hit of jsonKeys(JSON.parse(text), '$', [])) problems.push(`${rel}: private key ${hit}`);
    } else if (/\.(m?js|ts|tsx|css|html)$/.test(file)) {
      for (const m of text.matchAll(keyPattern)) {
        // Allow the denylist module and the guard itself, which name keys only as strings.
        problems.push(`${rel}: private key used as object key "${m[1]}" near …${text.slice(Math.max(0, m.index - 30), m.index + 40).replace(/\s+/g, ' ')}…`);
      }
    }
    for (const re of PATH_PATTERNS) if (re.test(text)) problems.push(`${rel}: references private output ${re}`);
  }
}
if (problems.length) {
  console.error(`PRIVACY CHECK FAILED (${problems.length})`);
  for (const p of problems.slice(0, 50)) console.error(' - ' + p);
  process.exit(1);
}
console.log(`privacy check passed: ${files} files in ${targets.map((t) => relative(root, t)).join(', ')}; ${KEYS.size} private keys, ${PATH_PATTERNS.length} path patterns`);
