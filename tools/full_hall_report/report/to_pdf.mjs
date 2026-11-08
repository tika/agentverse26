// node to_pdf.mjs <index.html> <out.pdf> <report-id>
// A4 PDF with a mono footer (report id, disclaimer, page n / N) on every page.
// Playwright is resolved from this folder, then $PLAYWRIGHT_DIR (any folder whose node_modules has playwright).
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const tries = [here, process.env.PLAYWRIGHT_DIR].filter(Boolean);
let chromium;
for (const dir of tries) {
  try { ({ chromium } = createRequire(path.join(dir, 'package.json'))('playwright')); break; } catch {}
}
if (!chromium) {
  console.error(`playwright not found in ${tries.join(', ')}. Run "npm i playwright && npx playwright install chromium" in ${here}, or set PLAYWRIGHT_DIR.`);
  process.exit(2);
}
const [src, out, id = ''] = process.argv.slice(2);

async function launch() {
  try { return await chromium.launch(); } catch (err) {
    // fall back to any cached headless shell (older Playwright caches)
    const base = path.join(process.env.HOME, 'Library/Caches/ms-playwright');
    const d = fs.existsSync(base) && fs.readdirSync(base).filter(x => x.startsWith('chromium_headless_shell-')).sort().reverse()[0];
    if (!d) throw err;
    const sub = fs.readdirSync(path.join(base, d)).find(x => x.startsWith('chrome-headless-shell'));
    return chromium.launch({ executablePath: path.join(base, d, sub, 'chrome-headless-shell') });
  }
}

const browser = await launch();
const page = await browser.newPage();
await page.goto('file://' + path.resolve(src), { waitUntil: 'load' });
await page.evaluate(() => document.fonts.ready);
const esc = s => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const foot = `<div style="width:100%;margin:0 14mm;display:flex;justify-content:space-between;font-family:'IBM Plex Mono',Menlo,monospace;font-size:6.5pt;color:#5d636a;border-top:0.5pt solid #d9dcdf;padding-top:4px">
  <span>${esc(id)} · Practice run in a simulated store. Not for operational use.</span>
  <span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`;
await page.pdf({ path: out, format: 'A4', printBackground: true, displayHeaderFooter: true,
  headerTemplate: '<span></span>', footerTemplate: foot,
  margin: { top: '14mm', bottom: '16mm', left: '14mm', right: '14mm' } });
await browser.close();
console.log(out);
