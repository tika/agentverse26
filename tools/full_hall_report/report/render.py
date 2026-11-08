"""Turn the run model + rule results into one self-describing HTML document (screen and print).

Only formatting happens here. Every value comes from the run model (loaders.py) or a rule (rules.py).
"""
import base64
import html
import shutil
from collections import defaultdict
from pathlib import Path

import rules as R

HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'assets'
COL = {'RED': '#b3261e', 'AMBER': '#b26a00', 'GREEN': '#2e7d32', 'GREY': '#8a8a85'}
ZCOL = {'KEEP OUT': COL['RED'], 'RESTRICTED': '#e0913a', 'LOW GAMMA': COL['GREEN'], 'NOT CHECKED': COL['GREY']}
NM = '<span class="nm">not measured</span>'
NL = '<span class="nm">not logged</span>'


def e(s):
    return html.escape('' if s is None else str(s))


def clock(t, frac=False):
    if t is None:
        return '--:--'
    m, s = divmod(t, 60)
    return f'{int(m):02d}:{s:04.1f}' if frac else f'{int(m):02d}:{int(round(s)) % 60:02d}'


def duration(t):
    if t is None:
        return None
    m, s = divmod(int(round(t)), 60)
    return f'{m} min {s:02d} s' if m else f'{s} s'


def chip(colour):
    return f'<span class="chip c-{colour}">{R.COLOUR_WORD[colour]}</span>'


def zchip(z):
    return f'<span class="chip z-{z.replace(" ", "-")}">{R.ZONE_WORD[z]}</span>'


def num(v, fmt='{:.2f}', unit=''):
    return NM if v is None else f'<span class="num">{fmt.format(v)}</span>{(" " + unit) if unit else ""}'


def plural(n, w):
    return f'{n} {w}{"" if n == 1 else "s"}'


def font_face():
    out = []
    for fam, key in (('IBM Plex Mono', 'mono'), ('IBM Plex Sans', 'sans')):
        for w in (400, 500, 600):
            f = ASSETS / 'fonts' / f'ibm-plex-{key}-latin-{w}-normal.woff2'
            b = base64.b64encode(f.read_bytes()).decode()
            out.append(f"@font-face{{font-family:'{fam}';font-weight:{w};font-style:normal;"
                       f"src:url(data:font/woff2;base64,{b}) format('woff2');}}")
    return '\n'.join(out)


def svg_inline(name, cls):
    s = (ASSETS / name).read_text()
    s = s[s.index('<svg'):]
    return s.replace('<svg ', f'<svg class="{cls}" aria-hidden="true" ', 1)


def data_uri(path, mime='image/png'):
    return f'data:{mime};base64,' + base64.b64encode(Path(path).read_bytes()).decode()


# ---- figures (inline SVG, no plotting library) -----------------------------------------------------
def shot(view, rel, colour_of_cls, big=True, note=None):
    """An evidence frame with the detector's own box drawn on it, HUD style."""
    if not rel:
        return '<div class="muted mono" style="font-size:7.4pt;padding:18px 0">photo not logged</div>'
    o = f'<figure class="shot"><img src="{e(rel)}" alt="">'
    if view.get('box') and view.get('size'):
        w, h = view['size']
        x1, y1, x2, y2 = view['box']
        c = colour_of_cls(view.get('cls'))
        lab = f"{(view.get('cls') or '').upper()} {view['conf']:.2f}" if view.get('conf') is not None else ''
        fs = w * (0.034 if big else 0.06)
        sw = w * (0.006 if big else 0.009)
        ty = y1 - fs * 0.45 if y1 > fs * 1.6 else y2 + fs * 1.25
        o += (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
              f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" fill="none" '
              f'stroke="{c}" stroke-width="{sw:.1f}"/>')
        if lab:
            bw = fs * 0.62 * len(lab) + fs * 0.6
            o += (f'<rect x="{x1:.1f}" y="{ty - fs * 1.05:.1f}" width="{bw:.1f}" height="{fs * 1.4:.1f}" fill="{c}"/>'
                  f'<text x="{x1 + fs * 0.3:.1f}" y="{ty:.1f}" font-family="IBM Plex Mono" font-weight="600" '
                  f'font-size="{fs:.1f}" fill="#fff">{e(lab)}</text>')
        o += '</svg>'
    o += '</figure>'
    if note:
        o += f'<figcaption>{note}</figcaption>'
    return o




def fig_map(drums, colours, zs, tele, geo, planted, lateral=True):
    """Plan of each aisle: 2 m sections along the aisle, racks folded out flat on both sides
    (the shelf nearest the aisle is the bottom one), one cell per drum coloured by result."""
    if not geo or not drums:
        return '<p class="note">Drum positions were not logged, so no plan can be drawn.</p>'
    route = [(t['x'], t['y']) for t in tele if t.get('x') is not None]
    out = []
    for g in geo.values():
        ds = g['drums']
        stacks = defaultdict(list)
        for d in ds:
            p = R.parse_id(d['drum_id'])
            stacks[(p['side'], p['column'])].append(d)
        xs = sorted({round(sum(d['x'] for d in v) / len(v), 3) for v in stacks.values()})
        gap = min([b - a for a, b in zip(xs, xs[1:]) if b - a > 0.05] or [1.5])
        x0 = g['x0']
        x1 = x0 + g['n'] * R.SECTION_M
        W, L = 680, 64
        s = (W - L - 10) / (x1 - x0)
        cell = max(7.0, min(15.0, gap * s * 0.82))
        tiers = max(R.parse_id(d['drum_id'])['tier'] for d in ds)
        band = 26
        rack = tiers * cell
        H = 26 + rack + 16 + band + 16 + rack + 34
        X = lambda x: L + (x - x0) * s
        yb0 = 26 + rack + 16                      # aisle band top
        o = [f'<svg class="map" viewBox="0 0 {W} {H:.0f}" xmlns="http://www.w3.org/2000/svg">',
             '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
             '<line x1="0" y1="0" x2="0" y2="6" stroke="#8a8a85" stroke-width="1.2" opacity=".45"/></pattern></defs>']
        for z in (z for z in zs if z['aisle'] == g['name']):
            fill = 'url(#hatch)' if z['zone'] == 'NOT CHECKED' and not z['samples'] else ZCOL[z['zone']]
            op = '1' if fill.startswith('url') else ('.16' if z['zone'] == 'NOT CHECKED' else '.3')
            o.append(f'<rect x="{X(z["lo"]):.1f}" y="{yb0}" width="{R.SECTION_M * s:.1f}" height="{band}" fill="{fill}" '
                     f'fill-opacity="{op}" stroke="#fff" stroke-width="1.5"/>')
            o.append(f'<text x="{X(z["lo"]) + R.SECTION_M * s / 2:.1f}" y="{yb0 + band + 11}" text-anchor="middle" '
                     f'font-family="IBM Plex Mono" font-size="8" fill="#5d636a">{e(z["part"])}</text>')
        o.append(f'<text x="{L - 8}" y="{yb0 + band / 2 + 3}" text-anchor="end" font-family="IBM Plex Mono" '
                 f'font-size="9" font-weight="600" fill="#111315">Aisle {e(g["name"])}</text>')
        for side, sign in (('L', -1), ('R', 1)):
            edge = yb0 if sign < 0 else yb0 + band + 16
            o.append(f'<text x="{L - 8}" y="{edge + sign * rack / 2 + (0 if sign < 0 else rack) + 3:.1f}" text-anchor="end" '
                     f'font-family="IBM Plex Mono" font-size="8.5" fill="#5d636a">{"Left" if side == "L" else "Right"}</text>')
        for (side, col), v in sorted(stacks.items()):
            cx = X(sum(d['x'] for d in v) / len(v))
            for d in v:
                t = R.parse_id(d['drum_id'])['tier']
                if side == 'L':
                    y = yb0 - 4 - t * cell
                else:
                    y = yb0 + band + 16 + 4 + (t - 1) * cell
                o.append(f'<rect x="{cx - cell / 2:.1f}" y="{y:.1f}" width="{cell:.1f}" height="{cell:.1f}" '
                         f'fill="{COL[colours[d["drum_id"]][0]]}" stroke="#fff" stroke-width="1"/>')
                if d['drum_id'] in planted:
                    o.append(f'<circle cx="{cx:.1f}" cy="{y + cell / 2:.1f}" r="{cell * 0.22:.1f}" fill="#fff"/>')
            ly = yb0 - 8 - tiers * cell if side == 'L' else yb0 + band + 16 + 4 + tiers * cell + 10
            o.append(f'<text x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle" font-family="IBM Plex Mono" font-size="8" '
                     f'fill="#111315">{col}</text>')
        if route:
            step = max(1, len(route) // 600)
            ry = lambda y: yb0 + band / 2 + (0 if not lateral else max(-1, min(1, (y - g['centre']) / g['half'])) * band * 0.4)
            pts = ' '.join(f'{X(x):.1f},{ry(y):.1f}' for x, y in route[::step] + [route[-1]])
            o.append(f'<polyline points="{pts}" fill="none" stroke="#111315" stroke-width="1.4" stroke-linejoin="round"/>')
            o.append(f'<circle cx="{X(route[0][0]):.1f}" cy="{ry(route[0][1]):.1f}" r="4" fill="#f1c543" stroke="#111315" stroke-width="1.2"/>')
            o.append(f'<rect x="{X(route[-1][0]) - 3.5:.1f}" y="{ry(route[-1][1]) - 3.5:.1f}" width="7" height="7" fill="#111315"/>')
        o.append(f'<line x1="{L}" y1="{H - 10}" x2="{L + s:.1f}" y2="{H - 10}" stroke="#111315" stroke-width="2"/>'
                 f'<text x="{L + s + 4:.1f}" y="{H - 7}" font-family="IBM Plex Mono" font-size="8" fill="#111315">1 m</text>')
        o.append('</svg>')
        out.append(''.join(o))
    return ''.join(out)


def fig_trace(tele, key, label, unit, lines=(), events=(), height=96, fmt='{:.1f}', dots=(), zero=None):
    pts = [(t['t'], t[key]) for t in tele if t.get(key) is not None]
    if not pts:
        return None
    W, H, L, B, T, R_ = 680, height, 46, 18, 8, 22
    t0, t1 = min(p[0] for p in pts), max(p[0] for p in pts)
    vmin, vmax = min(p[1] for p in pts), max(p[1] for p in pts)
    shown = [v for v, _, _ in lines if v <= vmax * 1.6]
    if zero is None:
        zero = key == 'gamma'
    lo = 0 if zero else vmin - (vmax - vmin) * 0.15 - 0.1
    hi = max([vmax] + shown) * (1.12 if zero else 1) + (0 if zero else (vmax - vmin) * 0.15 + 0.1)
    X = lambda t: L + (t - t0) / ((t1 - t0) or 1) * (W - L - R_)
    Y = lambda v: T + (hi - v) / ((hi - lo) or 1) * (H - T - B)
    o = [f'<svg class="trace" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    for v in (lo, (lo + hi) / 2, hi):
        o.append(f'<line x1="{L}" x2="{W - R_}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#ececE8"/>'
                 f'<text x="{L - 5}" y="{Y(v) + 3:.1f}" text-anchor="end" font-family="IBM Plex Mono" font-size="8" '
                 f'fill="#5d636a">{fmt.format(v)}</text>')
    for et, _ in events:
        o.append(f'<line x1="{X(et):.1f}" x2="{X(et):.1f}" y1="{T}" y2="{H - B}" stroke="#f1c543" stroke-width="1.2"/>')
    step = max(1, len(pts) // 900)
    o.append('<polyline fill="none" stroke="#111315" stroke-width="1.1" points="' +
             ' '.join(f'{X(t):.1f},{Y(v):.1f}' for t, v in pts[::step] + [pts[-1]]) + '"/>')
    for v, name, c in lines:
        if v <= hi:
            o.append(f'<line x1="{L}" x2="{W - R_}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{c}" stroke-dasharray="4 3"/>'
                     f'<text x="{W - R_ - 2}" y="{Y(v) - 3:.1f}" text-anchor="end" font-family="IBM Plex Mono" '
                     f'font-size="8" fill="{c}">{e(name)}</text>')
    for dt, dv, name in dots:
        o.append(f'<circle cx="{X(dt):.1f}" cy="{Y(dv):.1f}" r="3.6" fill="#b3261e" stroke="#fff" stroke-width="1"/>'
                 f'<text x="{X(dt) + 5:.1f}" y="{Y(dv) - 4:.1f}" font-family="IBM Plex Mono" font-size="7" '
                 f'fill="#b3261e">{e(name)}</text>')
    for i in range(6):
        t = t0 + (t1 - t0) * i / 5
        o.append(f'<text x="{X(t):.1f}" y="{H - 5}" text-anchor="middle" font-family="IBM Plex Mono" font-size="8" '
                 f'fill="#5d636a">{clock(t)}</text>')
    o.append(f'<text x="{L + 4}" y="{T + 9}" font-family="IBM Plex Mono" font-size="8.5" font-weight="600" '
             f'fill="#111315">{e(label)} ({e(unit)})</text></svg>')
    return ''.join(o)


COSMOS_DO = {'accept': 'Accepted the rules’ result.', 'closer look': 'Asked for a closer look.',
             'mark suspect': 'Marked for a person to check.'}


def event_html(x, drum_ids, short=False):
    src = x.get('source') or ''
    txt = x.get('text') or ''
    if 'cosmos' in src.lower():
        act = x.get('action') or ''
        head = COSMOS_DO.get(act) or (f'Go to {act}.' if act in drum_ids else act.replace('_', ' ').capitalize() + '.')
        return f'<b class="mono">{e(head)}</b> <span class="p">“{e(txt)}”</span>'
    return f'<span class="p">{e(txt)}</span>'


# ---- document ---------------------------------------------------------------------------------------
CAMERA_PANEL = (0, 60, 1280, 780)   # camera panel of the 1920x1080 walk overlay frame


def build(run, out, commit=None, store='Drum Store 1 (simulated)'):
    out = Path(out)
    (out / 'evidence').mkdir(parents=True, exist_ok=True)
    drums = run['drums']
    ids = {d['drum_id'] for d in drums}
    max_tier = max([R.parse_id(d['drum_id'])['tier'] for d in drums if R.parse_id(d['drum_id'])] or [1])
    colours = {d['drum_id']: R.drum_colour(d) for d in drums}
    zs = R.zones(run['tele'], drums, colours, run.get('aisle_length_m'), run.get('aisle_start_x'))
    geo = R.aisles(drums, run.get('aisle_length_m'), run.get('aisle_start_x'))
    order = {'RED': 0, 'AMBER': 1, 'GREEN': 2}
    reg = sorted(drums, key=lambda d: (order[colours[d['drum_id']][0]], d['drum_id']))
    n = {k: sum(1 for c in colours.values() if c[0] == k) for k in order}
    zc = defaultdict(int)
    for z in zs:
        zc[z['zone']] += 1
    inspected = sum(1 for d in drums if d['status'] != "Couldn't inspect")
    gmax = max((t['gamma'] for t in run['tele'] if t.get('gamma') is not None), default=None)
    t_gmax = next((t['t'] for t in run['tele'] if t.get('gamma') == gmax), None) if gmax is not None else None
    planted = run.get('planted') or {}
    has_cat = any(d.get('category') for d in drums)
    by_drum = defaultdict(list)
    for x in run['events']:
        if x.get('drum'):
            by_drum[x['drum']].append(x)

    def cls_colour(c):
        return COL['RED'] if R.is_fault_class(c) else COL['GREEN']

    def copy(path, overlay=False):
        if not path:
            return None
        src = Path(path)
        try:  # re-encode frames as JPEG to keep the PDF small; fall back to a plain copy
            from PIL import Image
            dst = out / 'evidence' / (src.stem + '.jpg')
            if not dst.exists():
                im = Image.open(src)
                if overlay and im.size == (1920, 1080):
                    im = im.crop(CAMERA_PANEL)
                im.convert('RGB').save(dst, quality=86, optimize=True)
        except ImportError:
            dst = out / 'evidence' / src.name
            if not dst.exists():
                shutil.copy(src, dst)
        return f'evidence/{dst.name}'

    def best_view(d):
        vs = [v for v in d['view_list'] if v.get('image')]
        if not vs:
            return None
        if any(v.get('overlay') for v in vs):
            return vs[0]
        fault = [v for v in vs if R.is_fault_class(v.get('cls'))]
        return max(fault or vs, key=lambda v: v.get('conf') or 0)

    def wide(v):
        return bool(v and v.get('overlay')) or bool(v and v.get('size') and v['size'][0] / v['size'][1] > 1.4)

    # what was never measured anywhere in this run
    nothing = []
    if gmax is None and all(d.get('dose_rate_at_drum_uSv_h') is None for d in drums):
        nothing.append('radiation')
    if all(d.get('heat_rise_c') is None for d in drums):
        nothing.append('drum surface temperature')
    h2_any = any(t.get('h2') is not None for t in run['tele']) or any((d.get('h2') or {}).get('ppm') is not None for d in drums)
    h2_status = next(((d.get('h2') or {}).get('status') for d in drums if (d.get('h2') or {}).get('status')), None)
    h2_limit = next(((d.get('h2') or {}).get('limit') for d in drums if (d.get('h2') or {}).get('limit')), None)
    if not h2_any and h2_status != 'below_detection':
        nothing.append('hydrogen')
    if not any(d.get('swab') for d in drums):
        nothing.append('surface wipes (swabs)')
    if not has_cat:
        nothing.append('waste category (LLW / ILW)')

    # verdict
    parts = []
    if n['RED']:
        parts.append(f'{plural(n["RED"], "drum")} need{"s" if n["RED"] == 1 else ""} action')
    if n['AMBER']:
        parts.append(f'{n["AMBER"]} need{"s" if n["AMBER"] == 1 else ""} a second check')
    verdict = (' and '.join(parts) or 'No drum needs action') + '.'
    if n['GREEN']:
        verdict += f' {n["GREEN"]} showed no problem.'
    area = []
    if zc['KEEP OUT']:
        area.append(f'{plural(zc["KEEP OUT"], "aisle section")} flagged keep out')
    if zc['RESTRICTED']:
        area.append(f'{plural(zc["RESTRICTED"], "aisle section")} restricted')
    if zc['NOT CHECKED']:
        area.append(f'{zc["NOT CHECKED"]} not checked')
    area_line = '; '.join(area)
    area_line = (area_line[:1].upper() + area_line[1:] + '. ') if area_line else ''
    if 'radiation' in nothing:
        area_line += 'Radiation was not measured on this round, so no part of the aisle can be called low gamma yet.'
    else:
        area_line += 'Aisle ratings are simulation flags; site staff decide access.'

    rid = f'CANIS-{run["id"]}'
    C = []
    w = C.append
    w(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      f'<title>Inspection report {e(rid)}</title><style>{font_face()}\n{(HERE / "style.css").read_text()}</style></head>'
      f'<body><main class="doc">')

    # ================= page 1: verdict and actions
    w('<header class="band">' + svg_inline('dog-head.svg', 'mark') +
      f'<div><img class="word" src="{data_uri(ASSETS / "wordmark-white.png")}" alt="C.A.N.I.S.">'
      f'<div class="sub">{e(R.EXPANSION)}</div><div class="title">Drum Store Inspection Report</div></div>'
      f'<div class="id"><b>{e(rid)}</b>{e(store)}<br>{e(run.get("started") or "start time not logged")}</div></header>')
    if run.get('note'):
        w(f'<div class="callout mono" style="font-size:7.6pt">{e(run["note"])}</div>')
    w(f'<section class="verdict"><div class="eyebrow">Verdict</div><p>{e(verdict)}</p>')
    w(f'<p class="verdict-sub">{e(area_line)}</p>')
    tot = max(1, len(drums))
    w('<div class="statusbar">' + ''.join(f'<span style="width:{100 * n[k] / tot:.2f}%;background:{COL[k]}"></span>'
                                          for k in order if n[k]) + '</div>')
    w('<div class="statusbar-key">' + ''.join(f'<span><i class="dot" style="background:{COL[k]}"></i>{R.COLOUR_WORD[k]} {n[k]}</span>'
                                              for k in order) + '</div></section>')

    kp = [('Drums checked', f'{inspected}<small>/ {run["expected"]}</small>', 'verdict reached'),
          ('Action needed', n['RED'], 'red'), ('Check again', n['AMBER'], 'amber'), ('No problem found', n['GREEN'], 'green'),
          ('Peak gamma', f'{gmax:.2f}<small>µSv/h</small>' if gmax is not None else '<span class="nmv">n/m</span>',
           f'at {clock(t_gmax)} · restricted above 7.5' if gmax is not None else 'not measured this round'),
          ('Aisle sections', f'{len(zs)}', ' · '.join(f'{zc[z]} {R.ZONE_WORD[z].lower()}' for z in R.ZONE_ORDER if zc[z])),
          ('Robot dose', f'{run["dose_uSv"]:.4f}<small>µSv</small>' if run.get('dose_uSv') is not None else '<span class="nmv">n/m</span>',
           (f'limit {run["budget_uSv"]} µSv' if run.get('budget_uSv') else 'no limit logged') if run.get('dose_uSv') is not None
           else 'not measured this round'),
          ('Mission time', e(duration(run.get('duration_s')) or '—'), 'simulated time')]
    w('<div class="kpis">' + ''.join(f'<div class="kpi"><div class="k">{k}</div><div class="v">{v}</div><div class="s">{e(s)}</div></div>'
                                     for k, v, s in kp) + '</div>')

    w('<div class="sec-head"><div class="eyebrow">What to do now</div><div class="eyebrow">most urgent first</div></div>')
    todo = [d for d in reg if colours[d['drum_id']][0] != 'GREEN']
    if todo:
        w('<table class="actions"><thead><tr><th></th><th>Drum</th><th>Result</th><th>Seen</th><th>Do this</th></tr></thead><tbody>')
        for i, d in enumerate(todo, 1):
            w(f'<tr><td>{i}</td><td><b>{e(d["drum_id"])}</b></td><td>{chip(colours[d["drum_id"]][0])}</td>'
              f'<td>{e(R.finding_word(d["finding"]))}</td><td class="do">{e(R.action_for(d))}</td></tr>')
        w('</tbody></table>')
    else:
        w('<p>No drum needs follow-up from this inspection. Continue routine inspections.</p>')

    w('<div class="sec-head" style="margin-top:14px"><div class="eyebrow">This inspection</div></div><dl class="facts">')
    facts = [('Store', store), ('Report', rid), ('Started', run.get('started') or 'not logged'),
             ('Mission time', duration(run.get('duration_s')) or 'not logged'),
             ('Inspected by', 'C.A.N.I.S. robot (Spot)'), ('Drums in scope', run['expected']),
             ('Report software', commit or 'not recorded'), ('Status', 'Practice run, simulated store')]
    for k, v in facts:
        w(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>')
    w('</dl>')
    notes = []
    if nothing:
        notes.append(f'Not measured on this round: {", ".join(nothing)}. Tables print “not measured”; no value is estimated.')
    if planted:
        notes.append('Planted on purpose so the robot’s response shows early: ' +
                     ', '.join(f'{v} on {k}' for k, v in sorted(planted.items())) + '.')
    for x in notes:
        w(f'<p class="note">{e(x)}</p>')

    # ================= 1. aisle survey
    w('<section class="page"><div class="sec-head"><h2><span class="n">01</span>Aisle survey</h2>'
      f'<div class="eyebrow">{len(zs)} sections · {R.SECTION_M:g} m each</div></div>')
    w('<p class="lede">Each aisle is split into 2-metre sections measured from where the robot started, and each section '
      'takes the worst rating that applies. A section is only rated low gamma if radiation was measured there.</p>')
    w(fig_map(drums, colours, zs, run['tele'], geo, planted, run.get('lateral_pose', True)))
    lg = [(f'background:{ZCOL[z]};opacity:{1 if z == "NOT CHECKED" else .4}', R.ZONE_WORD[z]) for z in R.ZONE_ORDER]
    lg += [('background:repeating-linear-gradient(45deg,#c9c9c4 0 2px,#fff 2px 5px)', 'Not walked')]
    lg += [(f'background:{COL[k]}', f'Drum: {R.COLOUR_WORD[k].lower()}') for k in order]
    if planted:
        lg += [('background:radial-gradient(circle,#fff 0 30%,#b3261e 32%)', 'Fault planted on purpose')]
    lg += [('background:#f1c543;border-radius:50%;border:1px solid #111', 'Start'), ('background:#111315', 'End'),
           ('height:2px;background:#111315;vertical-align:3px', "Robot's route")]
    w('<div class="legend">' + ''.join(f'<span><i style="{s}"></i>{e(t)}</span>' for s, t in lg) + '</div>')
    cap = ('Racks are drawn folded out flat: the shelf nearest the aisle is the bottom one. Numbers are stack numbers.')
    if not run.get('lateral_pose', True):
        cap += ' Only distance along the aisle was available for the route, so it is drawn on the centre line.'
    w(f'<p class="note" style="margin-top:0">{e(cap)}</p>')
    show_g = 'radiation' not in nothing
    show_h = 'hydrogen' not in nothing
    w('<table class="survey"><thead><tr><th>Aisle</th><th>Section</th><th>Rating</th>' +
      ('<th class="r">Peak gamma <span class="u">µSv/h</span></th>' if show_g else '') +
      ('<th class="r">H₂ <span class="u">ppm</span></th>' if show_h else '') +
      '<th class="r">Samples</th><th>Why</th></tr></thead><tbody>')
    for z in sorted(zs, key=lambda z: (R.ZONE_ORDER.index(z['zone']), z['aisle'], z['lo'])):
        h2 = (num(z['h2max'], '{:.0f}') if z['h2max'] is not None else
              (f'&lt; {h2_limit:g}' if h2_status == 'below_detection' and z['samples'] else NM))
        gcell = f'<td class="r">{num(z["gmax"]) if z["samples"] else "—"}</td>' if show_g else ''
        hcell = f'<td class="r">{h2 if z["samples"] else "—"}</td>' if show_h else ''
        w(f'<tr><td><b>{e(z["aisle"])}</b></td><td class="nw">{e(z["part"])}</td><td>{zchip(z["zone"])}</td>'
          f'{gcell}{hcell}<td class="r">{z["samples"]}</td><td><span class="p">{e(z["reason"])}</span></td></tr>')
    gone = [x for x in ('radiation', 'hydrogen') if x in nothing]
    w('</tbody></table><p class="note">Samples = telemetry records logged in the section. '
      + ('H₂ “&lt; n” means below the sensor’s detection limit. ' if show_h else '')
      + (f'No {" or ".join(gone)} readings were logged on this round, so those columns are left out.' if gone else '')
      + '</p></section>')

    # ================= 2. register
    w('<section class="page"><div class="sec-head"><h2><span class="n">02</span>Every drum at a glance</h2>'
      f'<div class="eyebrow">{len(drums)} drums · most urgent first</div></div>')
    w('<table class="register"><thead><tr><th>Drum</th>' + ('<th>Waste</th>' if has_cat else '') +
      '<th>Where</th><th>Result</th><th>What was seen</th><th class="r">How sure</th>'
      '<th class="r">Fault views</th>' + ('<th class="r">Gamma <span class="u">µSv/h</span></th>' if show_g else '') +
      '</tr></thead><tbody>')
    for d in reg:
        c = colours[d['drum_id']][0]
        ce = R.certainty(d.get('confidence'))
        p = R.parse_id(d['drum_id'])
        loc = f'{R.SIDE[p["side"]].capitalize()} {p["column"]} · {R.tier_word(p["tier"], max_tier)}' if p else R.where(d, max_tier)
        fv = '—' if d.get('fault_views') is None else f'{d["fault_views"]}/{d.get("views") or 0}'
        star = ' <span class="tag">planted</span>' if d['drum_id'] in planted else ''
        w(f'<tr><td><b>{e(d["drum_id"])}</b>{star}</td>' + (f'<td>{e(d.get("category") or "—")}</td>' if has_cat else '') +
          f'<td>{e(loc)}</td><td>{chip(c)}</td><td>{e(R.finding_word(d["finding"]))}</td>'
          f'<td class="r">{f"{ce[0]} {ce[1]}%" if ce else NL}</td><td class="r">{fv}</td>' +
          (f'<td class="r">{num(d.get("dose_rate_at_drum_uSv_h"))}</td>' if show_g else '') + '</tr>')
    w('</tbody></table>')
    w('<p class="note">How sure = the detector’s confidence in what it reported: High ≥ 70%, Medium ≥ 50%, Low below. '
      'Fault views = camera views that showed damage, out of all views taken. Drum names read aisle, side (L / R), stack, '
      'shelf (T1 = bottom). ' + ('LLW = low-level waste (yellow drums), ILW = intermediate-level waste (blue drums). ' if has_cat else '') +
      'This is the first report for these drums, so there is no earlier inspection to compare with.</p></section>')

    # ================= 3. findings
    flagged = [d for d in reg if colours[d['drum_id']][0] != 'GREEN']
    w('<section class="page"><div class="sec-head"><h2><span class="n">03</span>Drums that need attention</h2>'
      f'<div class="eyebrow">{len(flagged)} drums</div></div>')
    if not flagged:
        w('<p>No drum needs attention.</p>')
    for d in flagged:
        c, why = colours[d['drum_id']]
        bv = best_view(d)
        rel = copy(bv['image'], bv.get('overlay')) if bv else None
        layout = 'finding-body wide' if wide(bv) else 'finding-body'
        cat = R.WASTE.get(d.get('category'))
        w(f'<article class="finding"><div class="finding-head"><div><span class="id">{e(d["drum_id"])}</span> '
          f'<span class="where">{e(R.where(d, max_tier))}{" · " + e(cat) if cat else ""}</span></div>{chip(c)}</div>'
          f'<div class="{layout}"><div>')
        cap = None
        if bv:
            cap = (f'{e(bv.get("label") or "evidence")} · {clock(bv.get("t"), True)} into the run'
                   + (f' · frame {bv["frame"]}' if bv.get('frame') is not None else '')
                   + (f' · body pitch {bv["pitch"]:.1f}°' if bv.get('pitch') is not None else '')
                   + ('. Overlay, boxes and labels are the robot’s own, as recorded.' if bv.get('overlay')
                      else '. Box and label are the detector’s own output.'))
        w(shot(bv or {}, rel, cls_colour, True, cap))
        others = [v for v in d['view_list'] if v.get('image') and v is not bv]
        if others:
            w('<div class="strip">' + ''.join(
                f'<figure>{shot(v, copy(v["image"], v.get("overlay")), cls_colour, False)}'
                f'<figcaption>{e((v.get("cls") or "?").upper())} {v["conf"]:.2f}</figcaption></figure>'
                for v in others[:6] if v.get('conf') is not None) + '</div>')
        w('</div><div><table class="kv"><tbody>')
        ce = R.certainty(d.get('confidence'))
        lab = d.get('label') or {}
        h2d = d.get('h2') or {}
        rows = [('What was seen', e(R.finding_word(d['finding']))),
                ('How sure', f'{ce[0]} ({ce[1]}%)' if ce else NL),
                ('Views', f'{d.get("fault_views", 0)} of {d.get("views") or 0} showed damage'),
                ('Why this rating', f'<span class="p">{e("; ".join(why).capitalize())}.</span>'),
                ('Gamma at drum', (f'{R.radiation_word(d["dose_rate_at_drum_uSv_h"])} · ' + num(d['dose_rate_at_drum_uSv_h'], unit='µSv/h'))
                 if d.get('dose_rate_at_drum_uSv_h') is not None else NM),
                ('Surface temp.', NM if d.get('heat_rise_c') is None else num(d['heat_rise_c'], '{:+.1f}', '°C vs air')),
                ('Hydrogen', (num(h2d['ppm'], '{:.0f}', 'ppm') if h2d.get('ppm') is not None else
                              f'below detection (&lt; {h2d["limit"]:g} ppm)' if h2d.get('status') == 'below_detection' else NM)),
                ('Surface wipe', 'not taken' if not d.get('swab') else ('above limit' if R.swab_over(d['swab']) else 'below limit'))]
        unm = [k for k, v in rows if v == NM]
        rows = [(k, v) for k, v in rows if v != NM]
        if unm:
            rows.append(('Not measured', '<span class="nm">' + e(', '.join(unm).lower()) + '</span>'))
        if d.get('air_c') is not None:
            rows.insert(5, ('Air', num(d['air_c'], '{:.1f}', '°C') + (f' · RH {d["rh"]:.0f}%' if d.get('rh') is not None else '')))
        if lab:
            rows.append(('Label', ('read: ' + e(' → '.join(lab.get('reads') or []))) if lab.get('readable')
                         else '<b>not confirmed</b> · reads: ' + e(' → '.join(lab.get('reads') or []))))
        if d.get('test_note'):
            rows.append(('Test note', f'<span class="p">This fault ({e(d["test_note"])}) was planted on purpose for the demonstration.</span>'))
        trail = by_drum.get(d['drum_id']) or []
        if trail:
            rows.append(('What the robot did', '<br>'.join(f'<span class="num">{clock(x["t"])}</span> {event_html(x, ids)}'
                                                           for x in trail)))
        for k, v in rows:
            w(f'<tr><td>{k}</td><td>{v}</td></tr>')
        w('</tbody></table>')
        if lab.get('crop'):
            w(f'<div class="plate"><img src="{e(copy(lab["crop"]))}" alt=""><span class="reads muted">Label crop the '
              'reader used</span></div>')
        w(f'<div class="do-box"><div class="eyebrow">What to do</div><p>{e(R.action_for(d))}</p></div>')
        w('</div></div></article>')

    # ================= 4. evidence for green drums
    greens = [d for d in reg if colours[d['drum_id']][0] == 'GREEN']
    if greens and any(best_view(d) for d in greens):
        w('<section class="keep" style="margin-top:18px"><div class="sec-head"><h2><span class="n">04</span>Drums with no problem found</h2>'
          f'<div class="eyebrow">{len(greens)} drums · best view each</div></div><div class="gallery">')
        for d in greens:
            bv = best_view(d)
            ce = R.certainty(d.get('confidence'))
            w(f'<figure>{shot(bv or {}, copy(bv["image"], bv.get("overlay")) if bv else None, cls_colour, False)}'
              f'<div class="cap"><b>{e(d["drum_id"])}</b><span class="muted">{f"{ce[1]}%" if ce else ""} · '
              f'{d.get("views") or 0} views</span></div></figure>')
        w('</div></section>')
    w('</section>')

    # ================= 5. gaps, accuracy, method
    w('<section class="page"><div class="sec-head"><h2><span class="n">05</span>What this report cannot tell you</h2></div>')
    ci = [d for d in drums if d['status'] == "Couldn't inspect"]
    ns = [z for z in zs if z['zone'] == 'NOT CHECKED']
    items = [f'<b class="mono">{e(d["drum_id"])}</b>: {e(d.get("reason") or "no clear look")}.' for d in ci]
    if not ci:
        items.append(f'The robot reached a verdict on all {len(drums)} drums it was sent to look at.')
    walked = [z for z in ns if z['samples']]
    unwalked = [z for z in ns if not z['samples']]
    if walked:
        items.append(f'<b class="mono">{len(walked)} section{"s" if len(walked) != 1 else ""}</b> '
                     f'({e(", ".join(z["aisle"] + " " + z["part"] for z in walked))}): walked, but radiation was not measured.')
    if unwalked:
        items.append(f'<b class="mono">{len(unwalked)} section{"s" if len(unwalked) != 1 else ""}</b> '
                     f'({e(", ".join(z["aisle"] + " " + z["part"] for z in unwalked))}): not walked on this round.')
    items += [f'<b class="mono">{e(x[:1].upper() + x[1:])}</b>: not measured anywhere on this round.' for x in nothing]
    w('<ul class="plain">' + ''.join(f'<li>{x}</li>' for x in items) + '</ul>')

    w('<h3>How accurate was the robot?</h3>')
    truth = run.get('truth')
    if truth:
        flagged_ids = {d['drum_id'] for d in drums if d['status'] in ('Confirmed defect', 'Suspect')}
        cant = {d['drum_id'] for d in ci}
        faulty = {k for k, v in truth.items() if v['faulty']}
        found = sorted(faulty & flagged_ids)
        missed = sorted(faulty - flagged_ids - cant)
        false = sorted(k for k in flagged_ids if k in truth and not truth[k]['faulty'])

        def sev(k):
            v = truth[k]
            return ', '.join(f'{nm} {v[f]:.2f}' for f, nm in (('rust', 'rust'), ('bulge', 'bulge')) if v.get(f))

        w('<p class="lede">This was a practice run in a simulated store, so we know which drums were really damaged. '
          'The robot was not told; the comparison is made only for this report.</p>')
        w('<div class="kpis three">'
          f'<div class="kpi"><div class="k">Damaged drums found</div><div class="v">{len(found)}<small>/ {len(faulty)}</small></div>'
          f'<div class="s">{"incl. " + str(len(set(planted) & faulty)) + " planted" if planted else ""}</div></div>'
          f'<div class="kpi"><div class="k">Missed</div><div class="v">{len(missed)}</div><div class="s">the more serious error</div></div>'
          f'<div class="kpi"><div class="k">False alarms</div><div class="v">{len(false)}</div><div class="s">each costs one extra check</div></div>'
          '</div>')
        if missed:
            w('<table><thead><tr><th>Missed drum</th><th>Simulated damage (0–1)</th><th>Where</th></tr></thead><tbody>' +
              ''.join(f'<tr><td><b>{e(k)}</b></td><td>{e(sev(k) or "—")}</td>'
                      f'<td><span class="p">{e(R.where({"drum_id": k}, max_tier))}</span></td></tr>' for k in missed) +
              '</tbody></table>')
        if run.get('groups'):
            names = {'yellow': 'Yellow (low-level)', 'blue': 'Blue (intermediate-level)'}
            w('<table style="margin-top:10px"><thead><tr><th>Drum colour</th><th class="r">Drums</th><th class="r">Correct</th>'
              '<th class="r">Accuracy</th><th class="r">95% range</th><th class="r">Damaged found</th><th class="r">False alarms</th>'
              '</tr></thead><tbody>')
            for g in (g for g in run['groups'] if g['scope'] == 'all drums'):
                ci_ = f'{g["ci"][0] * 100:.0f}–{g["ci"][1] * 100:.0f}%' if g.get('ci') else '—'
                w(f'<tr><td><b>{e(names.get(g["group"], g["group"]))}</b></td><td class="r">{g["drums"]}</td>'
                  f'<td class="r">{g["correct"]}</td><td class="r"><b>{g["accuracy"] * 100:.1f}%</b></td><td class="r">{ci_}</td>'
                  f'<td class="r">{g["found"]} of {g["faulty"]}</td><td class="r">{g["false"]}</td></tr>')
            w('</tbody></table>')
            extra = [g for g in run['groups'] if g['scope'] != 'all drums']
            note = 'A drum counts as correct if it was damaged and flagged, or undamaged and cleared. '
            for g in extra:
                note += (f'{names.get(g["group"], g["group"]).split(" ")[0]} {g["scope"]}: {g["accuracy"] * 100:.1f}% '
                         f'({g["correct"]} of {g["drums"]}). ')
            note += 'With this few drums the 95% ranges are wide, so small differences between colours should not be over-read.'
            w(f'<p class="note">{e(note)}</p>')
    else:
        w('<p class="note">This run folder has no ground truth, so the self-check was not made. Ground truth is never '
          'written into the robot’s logs; add ground_truth.json or colour_accuracy.json to score the run.</p>')

    w('<h3>How the ratings were made</h3><table><thead><tr><th>Part</th><th>Does</th><th>Never does</th></tr></thead><tbody>'
      '<tr><td><b>Detector</b></td><td><span class="p">Draws a box and a class (normal / rust / bulge) on each camera view.</span></td>'
      '<td><span class="p">Decide a rating.</span></td></tr>'
      '<tr><td><b>Rules</b></td><td><span class="p">Turn views and readings into drum results and aisle ratings, the same way every time.</span></td>'
      '<td><span class="p">Read free text.</span></td></tr>'
      '<tr><td><b>Cosmos Reason 2</b></td><td><span class="p">Chooses from a fixed list of options: accept the rules’ result, '
      'ask for a closer look, or mark a drum for a person. Its reasons are quoted in the record.</span></td>'
      '<td><span class="p">Clear a drum, confirm damage, or change any rating, zone or number.</span></td></tr>'
      '<tr><td><b>Report</b></td><td><span class="p">Lays out what the run logged.</span></td>'
      '<td><span class="p">Estimate a value that was not logged.</span></td></tr></tbody></table>')
    cz = [x for x in run['events'] if 'cosmos' in (x.get('source') or '').lower()]
    if cz:
        acts = defaultdict(int)
        for x in cz:
            acts[x.get('action') or 'other'] += 1
        w(f'<p class="note">On this round Cosmos Reason 2 made {len(cz)} reviews: ' +
          ', '.join(f'{v} {COSMOS_DO.get(k, k).lower().rstrip(".")}' for k, v in sorted(acts.items(), key=lambda kv: -kv[1])) +
          '.</p>')
    w('<h3>Limits used</h3><table><thead><tr><th>Rating</th><th>Level</th><th>Source</th></tr></thead><tbody>' +
      ''.join(f'<tr><td><b>{e(a)}</b></td><td>{e(b)}</td><td><span class="p">{e(c)}</span></td></tr>' for a, b, c in R.LIMITS) +
      '</tbody></table>')
    w('<h3>How to read the labels</h3><div class="key">'
      f'{chip("RED")}<span class="p">Damage confirmed from more than one view. An engineer should assess the drum.</span>'
      f'{zchip("KEEP OUT")}<span class="p">Highest-priority simulation flag.</span>'
      f'{chip("AMBER")}<span class="p">Possible damage, or the robot could not confirm the drum.</span>'
      f'{zchip("RESTRICTED")}<span class="p">Raised gamma, or a damaged or unresolved drum in the section.</span>'
      f'{chip("GREEN")}<span class="p">No damage seen in this inspection.</span>'
      f'{zchip("LOW GAMMA")}<span class="p">Gamma measured and below 7.5 µSv/h.</span>'
      f'<span></span><span></span>{zchip("NOT CHECKED")}<span class="p">No radiation reading here: treat as unknown.</span></div>')
    w('<p class="note">Practice run in a computer-simulated store (NVIDIA Isaac Sim). The detector was trained on synthetic '
      'images; rust extent is judged from photos, not measured. Only a surface wipe can show contamination. The structure '
      'follows the themes of the NDA’s Guidance on Monitoring of Waste Packages During Storage (WPS/640).</p>')

    vid = run.get('video')
    if vid:
        w('<h3>Video evidence</h3>')
        if vid.get('summary'):
            w(f'<p class="lede">{e(vid["summary"])}</p>')
        w('<table><thead><tr><th>In the cut</th><th>What it shows</th></tr></thead><tbody>' +
          ''.join(f'<tr><td class="num" style="white-space:nowrap">{e(a)}</td><td><span class="p">{e(b)}</span></td></tr>'
                  for a, b in vid.get('moments', [])) + '</tbody></table>')
    w('</section>')

    # ================= appendix A: traces
    w('<section class="page"><div class="sec-head"><h2><span class="n">A</span>Readings over time</h2>'
      '<div class="eyebrow">mission clock mm:ss</div></div>')
    ev = [(x['t'], x.get('action') or '') for x in run['events']
          if 'cosmos' in (x.get('source') or '').lower() and x.get('t') is not None]
    drawn = 0
    g = fig_trace(run['tele'], 'gamma', 'Gamma', 'µSv/h',
                  [(R.GAMMA_RESTRICT, 'restricted 7.5', '#b26a00'), (R.GAMMA_KEEPOUT, 'keep out 100', '#b3261e')],
                  ev, 120, '{:.2f}')
    if g:
        w('<p class="lede">Every sensor sample the robot logged. Yellow lines mark Cosmos Reason 2 decisions.</p>' + g)
        drawn += 1
        if gmax is not None and gmax < R.GAMMA_RESTRICT:
            w(f'<p class="note">The restricted level (7.5 µSv/h) is {R.GAMMA_RESTRICT / gmax:.1f}× the highest reading, '
              'so it is off this scale.</p>')
    for key, lab, unit in (('air_c', 'Air temperature', '°C'), ('rh', 'Relative humidity', '%'), ('h2', 'Hydrogen', 'ppm'),
                           ('dose_uSv', 'Robot dose', 'µSv')):
        f = fig_trace(run['tele'], key, lab, unit, (), ev, 86)
        if f:
            w(f)
            drawn += 1
    if not drawn:
        w('<p class="lede">No sensor readings were logged on this round, so this shows how far down the aisle the robot was. '
          'Flat stretches are where it stopped to look at drums; dots mark drums found to need action; yellow lines mark '
          'Cosmos Reason 2 decisions.</p>')
    x0 = run.get('aisle_start_x') or 0
    pos = {d['drum_id']: d['x'] for d in drums}
    dots = [(x['t'], pos[x['drum']] - x0, '') for x in run['events']
            if x.get('drum') in pos and colours[x['drum']][0] == 'RED' and 'Action needed' in (x.get('text') or '')]
    tl = [dict(t=t['t'], xa=t['x'] - x0) for t in run['tele'] if t.get('x') is not None]
    f = fig_trace(tl, 'xa', 'Distance along aisle', 'm', (), ev, 190 if not drawn else 120, '{:.1f}', dots, zero=True)
    if f:
        w(f)
    if not h2_any and 'hydrogen' not in nothing:
        w(f'<p class="note">Hydrogen: below the detection limit ({h2_limit:g} ppm) for every logged sample.</p>')
    w('</section>')

    # ================= appendix B: record
    w('<section style="margin-top:24px"><div class="sec-head"><h2><span class="n">B</span>Step-by-step record</h2>'
      f'<div class="eyebrow">{len(run["events"])} logged events</div></div>')
    w('<p class="lede">What the robot decided and why, in order. Cosmos Reason 2 reasons are quoted exactly as logged '
      '(the log shortens long ones); they choose the next step and never set a rating.</p>')
    w('<table class="record"><thead><tr><th>Time</th><th>Drum</th><th>Source</th><th>What happened</th><th class="r">ms</th></tr></thead><tbody>')
    for x in run['events']:
        src = x.get('source') or ''
        is_c = 'cosmos' in src.lower()
        w(f'<tr><td class="num">{clock(x.get("t"), True)}</td><td><b>{e(x.get("drum") or "")}</b></td>'
          f'<td><span class="src{" cosmos" if is_c else ""}">{e(src)}</span></td><td>{event_html(x, ids)}</td>'
          f'<td class="r">{x["latency_ms"] if x.get("latency_ms") is not None else ""}</td></tr>')
    w('</tbody></table></section>')

    # ================= appendix C: technical
    w('<section class="page"><div class="sec-head"><h2><span class="n">C</span>Technical details</h2>'
      '<div class="eyebrow">for engineers and auditors</div></div><table class="kv"><tbody>')
    for k, v in [('Report', rid), ('Run folder', '/'.join(Path(run['run_dir']).parts[-3:])), ('Input format', run['source_format']),
                 ('Report software', commit or 'not recorded')] + list(run.get('tech') or []):
        if v is None:
            continue
        w(f'<tr><td>{e(k)}</td><td style="overflow-wrap:anywhere">{e(v)}</td></tr>')
    w('<tr><td>Status names</td><td>Action needed = Confirmed defect · Check again = Suspect or Couldn’t inspect · '
      'No problem found = OK</td></tr></tbody></table>')
    frames = [(d, v) for d in sorted(drums, key=lambda d: d['drum_id']) for v in d['view_list']
              if v.get('image') or v.get('sha')]
    if frames:
        w('<h3>Evidence frames</h3><table><thead><tr><th>Drum</th><th>View</th><th class="r">Time</th><th class="r">Frame</th>'
          '<th>Class</th><th class="r">Conf.</th><th class="r">Pitch</th><th>Source</th></tr></thead><tbody>')
        for d, v in frames:
            conf = f"{v['conf']:.3f}" if v.get('conf') is not None else ''
            pitch = f"{v['pitch']:.1f}°" if v.get('pitch') is not None else ''
            frame = v.get('frame') if v.get('frame') is not None else ''
            srcf = ((v.get('sha') or '')[:16] + '…') if v.get('sha') else Path(v['image']).name
            w(f'<tr><td><b>{e(d["drum_id"])}</b></td><td>{e(v.get("label"))}</td><td class="r">{clock(v.get("t"), True)}</td>'
              f'<td class="r">{e(frame)}</td><td>{e(v.get("cls") or "")}</td><td class="r">{conf}</td>'
              f'<td class="r">{pitch}</td><td>{e(srcf)}</td></tr>')
        w('</tbody></table>')
    w('</section></main></body></html>')

    (out / 'index.html').write_text('\n'.join(C))
    summary = dict(report=rid, drums={k: n[k] for k in order}, zones=dict(zc), inspected=inspected,
                   expected=run['expected'], peak_gamma_uSv_h=gmax, verdict=verdict,
                   results={d['drum_id']: dict(colour=colours[d['drum_id']][0], status=d['status'],
                                               why=colours[d['drum_id']][1], action=R.action_for(d)) for d in reg},
                   sections=[{k: z[k] for k in ('aisle', 'part', 'zone', 'reason', 'gmax', 'samples')} for z in zs])
    return summary
