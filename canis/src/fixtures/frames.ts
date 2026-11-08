/**
 * Generated placeholder images for DEMO REPLAY. These are not renders of the
 * warehouse. Each carries a visible "FIXTURE FRAME" watermark.
 */
const enc = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

function watermark(w: number, _h: number, label: string) {
  return `<rect x="0" y="0" width="${w}" height="30" fill="#000" fill-opacity="0.55"/>
  <text x="12" y="20" font-family="monospace" font-size="15" fill="#f3c74d">FIXTURE FRAME · ${label} · NOT SENSOR DATA</text>`;
}

/** A schematic aisle (two rack faces converging to a vanishing point). */
export function rgbFixture(frameId: string, w = 640, h = 480): string {
  const vx = w / 2, vy = h * 0.42;
  const drums = [0, 1, 2, 3].map((i) => {
    const s = 1 - i * 0.2;
    const x = 40 + i * 70, y = 250 - i * 25;
    return `<rect x="${x}" y="${y}" width="${70 * s}" height="${110 * s}" rx="6" fill="#8a7a3a" stroke="#c9b25a"/>
      <rect x="${w - x - 70 * s}" y="${y}" width="${70 * s}" height="${110 * s}" rx="6" fill="#8a7a3a" stroke="#c9b25a"/>`;
  }).join('');
  return enc(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
  <rect width="${w}" height="${h}" fill="#3a3d40"/>
  <polygon points="0,${h} ${w},${h} ${vx + 40},${vy} ${vx - 40},${vy}" fill="#55585b"/>
  <line x1="${vx}" y1="${vy}" x2="${vx}" y2="${h}" stroke="#d9c05b" stroke-dasharray="14 12"/>
  ${drums}
  ${watermark(w, h, `RGB · ${frameId}`)}
</svg>`);
}

export function depthFixture(frameId: string, w = 640, h = 480): string {
  return enc(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
  <defs><linearGradient id="g" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#eee"/><stop offset="1" stop-color="#111"/></linearGradient></defs>
  <rect width="${w}" height="${h}" fill="url(#g)"/>
  <rect x="40" y="250" width="70" height="110" fill="#bbb"/><rect x="${w - 110}" y="250" width="70" height="110" fill="#bbb"/>
  ${watermark(w, h, `DEPTH · ${frameId}`)}
</svg>`);
}

/** Synthetic colour ramp; the console labels it apparent temperature with its range. */
export function lwirFixture(frameId: string, w = 640, h = 480): string {
  return enc(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
  <defs>
    <linearGradient id="t" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b0b3a"/><stop offset="0.6" stop-color="#6d1f7a"/><stop offset="1" stop-color="#c4462f"/></linearGradient>
    <radialGradient id="w" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#f5b13a"/><stop offset="1" stop-color="#f5b13a" stop-opacity="0"/></radialGradient>
  </defs>
  <rect width="${w}" height="${h}" fill="url(#t)"/>
  <ellipse cx="${w * 0.72}" cy="${h * 0.6}" rx="60" ry="45" fill="url(#w)"/>
  ${watermark(w, h, `APPARENT LWIR · ${frameId}`)}
</svg>`);
}

export function thirdPersonFixture(frameId: string, w = 960, h = 540): string {
  return enc(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
  <rect width="${w}" height="${h}" fill="#2c2f31"/>
  <polygon points="0,${h} ${w},${h} ${w * 0.56},${h * 0.38} ${w * 0.44},${h * 0.38}" fill="#4b4e50"/>
  ${[0, 1, 2, 3, 4].map((i) => `<rect x="${30 + i * 60}" y="${150 + i * 12}" width="${120 - i * 18}" height="${240 - i * 36}" fill="none" stroke="#7d6b2c" stroke-width="3"/>
  <rect x="${w - 150 - i * 60 + i * 18}" y="${150 + i * 12}" width="${120 - i * 18}" height="${240 - i * 36}" fill="none" stroke="#5f8790" stroke-width="3"/>`).join('')}
  <rect x="${w / 2 - 40}" y="${h - 150}" width="80" height="44" rx="8" fill="#d6b53f"/>
  ${watermark(w, h, `THIRD PERSON · ${frameId}`)}
</svg>`);
}
