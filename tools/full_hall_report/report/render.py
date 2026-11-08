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


def fig_map(drums, colours, zs, tele):
    pts = [(d['x'], d['y']) for d in drums if d.get('x') is not None]
    route = [(t['x'], t['y']) for t in tele if t.get('x') is not None]
    if not pts:
        return '<p class="note">Drum positions were not logged, so no plan can be drawn.</p>'
    xs = [p[0] for p in pts + route] + [z['lo'] for z in zs] + [z['hi'] for z in zs]
    ys = [p[1] for p in pts + route]
    pad = 0.9
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    W = 680
    s = W / (x1 - x0)
    H = (y1 - y0) * s
    if H > 330:
        s = 330 / (y1 - y0); H = 330
    W = (x1 - x0) * s
    X = lambda x: (x - x0) * s
    Y = lambda y: (y1 - y) * s
    o = [f'<svg class="map" viewBox="0 0 {W:.0f} {H:.0f}" style="max-width:{W:.0f}px" xmlns="http://www.w3.org/2000/svg">',
         '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
         '<line x1="0" y1="0" x2="0" y2="6" stroke="#8a8a85" stroke-width="1.2" opacity=".45"/></pattern></defs>']
    geo = R.aisles(drums)
    # 1 m grid
    for gx in range(int(x0) + 1, int(x1) + 1):
        o.append(f'<line x1="{X(gx):.1f}" y1="0" x2="{X(gx):.1f}" y2="{H:.1f}" stroke="#e6e6e2" stroke-width="1"/>')
    for z in zs:
        g = geo[z['aisle']]
        band = g['half'] * 0.62
        fill = 'url(#hatch)' if z['zone'] == 'NOT CHECKED' else ZCOL[z['zone']]
        op = '1' if z['zone'] == 'NOT CHECKED' else '.22'
        o.append(f'<rect x="{X(z["lo"]):.1f}" y="{Y(g["centre"] + band):.1f}" width="{(z["hi"] - z["lo"]) * s:.1f}" '
                 f'height="{2 * band * s:.1f}" fill="{fill}" fill-opacity="{op}" stroke="#fff" stroke-width="2"/>')
        o.append(f'<text x="{X(z["lo"]) + 4:.1f}" y="{Y(g["centre"] - band) - 4:.1f}" font-family="IBM Plex Mono" '
                 f'font-size="9" fill="#5d636a">{e(z["aisle"])} · {e(z["part"])}</text>')
    # stacks: one cell per tier, coloured by drum result
    stacks = defaultdict(list)
    for d in drums:
        p = R.parse_id(d['drum_id'])
        stacks[(p['aisle'], p['side'], p['column']) if p else d['drum_id']].append(d)
    cell = 15
    for key, ds in sorted(stacks.items(), key=lambda kv: str(kv[0])):
        ds = sorted(ds, key=lambda d: d['drum_id'])
        cx = sum(d['x'] for d in ds) / len(ds)
        cy = sum(d['y'] for d in ds) / len(ds)
        n = len(ds)
        bx, by = X(cx) - n * cell / 2, Y(cy) - cell / 2
        for i, d in enumerate(ds):
            o.append(f'<rect x="{bx + i * cell:.1f}" y="{by:.1f}" width="{cell}" height="{cell}" '
                     f'fill="{COL[colours[d["drum_id"]][0]]}" stroke="#111315" stroke-width="1"/>')
            p = R.parse_id(d['drum_id'])
            o.append(f'<text x="{bx + i * cell + cell / 2:.1f}" y="{by + cell / 2 + 3:.1f}" text-anchor="middle" '
                     f'font-family="IBM Plex Mono" font-size="8" font-weight="600" fill="#fff">'
                     f'{"T" + str(p["tier"]) if p else ""}</text>')
        name = f'{key[0]}-{key[1]}-{key[2]:02d}' if isinstance(key, tuple) else key
        above = cy >= (geo[key[0]]['centre'] if isinstance(key, tuple) and key[0] in geo else cy)
        ly = by - 5 if above else by + cell + 11
        o.append(f'<text x="{X(cx):.1f}" y="{ly:.1f}" text-anchor="middle" font-family="IBM Plex Mono" '
                 f'font-size="9.5" font-weight="500" fill="#111315">{e(name)}</text>')
    if route:
        step = max(1, len(route) // 600)
        pts_s = ' '.join(f'{X(x):.1f},{Y(y):.1f}' for x, y in route[::step] + [route[-1]])
        o.append(f'<polyline points="{pts_s}" fill="none" stroke="#111315" stroke-width="1.4" stroke-linejoin="round"/>')
        sx, sy = route[0]
        ex, ey = route[-1]
        o.append(f'<circle cx="{X(sx):.1f}" cy="{Y(sy):.1f}" r="4" fill="#f1c543" stroke="#111315" stroke-width="1.2"/>')
        o.append(f'<rect x="{X(ex) - 3.5:.1f}" y="{Y(ey) - 3.5:.1f}" width="7" height="7" fill="#111315"/>')
    # scale bar
    o.append(f'<line x1="10" y1="{H - 10:.1f}" x2="{10 + s:.1f}" y2="{H - 10:.1f}" stroke="#111315" stroke-width="2"/>'
             f'<text x="{14 + s:.1f}" y="{H - 7:.1f}" font-family="IBM Plex Mono" font-size="9" fill="#111315">1 m</text>')
    o.append('</svg>')
    return ''.join(o)


def fig_trace(tele, key, label, unit, lines=(), events=(), height=96, fmt='{:.1f}'):
    pts = [(t['t'], t[key]) for t in tele if t.get(key) is not None]
    if not pts:
        return None
    W, H, L, B, T, R_ = 680, height, 46, 18, 8, 22
    t0, t1 = min(p[0] for p in pts), max(p[0] for p in pts)
    vmin, vmax = min(p[1] for p in pts), max(p[1] for p in pts)
    shown = [v for v, _, _ in lines if v <= vmax * 1.6]
    lo = 0 if key == 'gamma' else vmin - (vmax - vmin) * 0.15 - 0.1
    hi = max([vmax] + shown) * (1.12 if key == 'gamma' else 1) + (0 if key == 'gamma' else (vmax - vmin) * 0.15 + 0.1)
    X = lambda t: L + (t - t0) / ((t1 - t0) or 1) * (W - L - R_)
    Y = lambda v: T + (hi - v) / ((hi - lo) or 1) * (H - T - B)
    o = [f'<svg class="trace" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    for v in (lo, (lo + hi) / 2, hi):
        o.append(f'<line x1="{L}" x2="{W - 6}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#ececE8"/>'
                 f'<text x="{L - 5}" y="{Y(v) + 3:.1f}" text-anchor="end" font-family="IBM Plex Mono" font-size="8" '
                 f'fill="#5d636a">{fmt.format(v)}</text>')
    for et, txt in events:
        o.append(f'<line x1="{X(et):.1f}" x2="{X(et):.1f}" y1="{T}" y2="{H - B}" stroke="#f1c543" stroke-width="1.2"/>')
    step = max(1, len(pts) // 900)
    o.append('<polyline fill="none" stroke="#111315" stroke-width="1.1" points="' +
             ' '.join(f'{X(t):.1f},{Y(v):.1f}' for t, v in pts[::step] + [pts[-1]]) + '"/>')
    for v, name, c in lines:
        if v <= hi:
            o.append(f'<line x1="{L}" x2="{W - 6}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{c}" stroke-dasharray="4 3"/>'
                     f'<text x="{W - 8}" y="{Y(v) - 3:.1f}" text-anchor="end" font-family="IBM Plex Mono" '
                     f'font-size="8" fill="{c}">{e(name)}</text>')
    for i in range(6):
        t = t0 + (t1 - t0) * i / 5
        o.append(f'<text x="{X(t):.1f}" y="{H - 5}" text-anchor="middle" font-family="IBM Plex Mono" font-size="8" '
                 f'fill="#5d636a">{clock(t)}</text>')
    o.append(f'<text x="{L + 4}" y="{T + 9}" font-family="IBM Plex Mono" font-size="8.5" font-weight="600" '
             f'fill="#111315">{e(label)} ({e(unit)})</text></svg>')
    return ''.join(o)


# ---- document ---------------------------------------------------------------------------------------
def build(run, out, commit=None, store='Drum Store 1 (simulated)'):
    out = Path(out)
    (out / 'evidence').mkdir(parents=True, exist_ok=True)
    drums = run['drums']
    max_tier = max([R.parse_id(d['drum_id'])['tier'] for d in drums if R.parse_id(d['drum_id'])] or [1])
    colours = {d['drum_id']: R.drum_colour(d) for d in drums}
    zs = R.zones(run['tele'], drums, colours, run.get('aisle_length_m'))
    order = {'RED': 0, 'AMBER': 1, 'GREEN': 2}
    reg = sorted(drums, key=lambda d: (order[colours[d['drum_id']][0]], d['drum_id']))
    n = {k: sum(1 for c in colours.values() if c[0] == k) for k in order}
    zc = defaultdict(int)
    for z in zs:
        zc[z['zone']] += 1
    inspected = sum(1 for d in drums if d['status'] != "Couldn't inspect")
    gmax = max((t['gamma'] for t in run['tele'] if t.get('gamma') is not None), default=None)
    t_gmax = next((t['t'] for t in run['tele'] if t.get('gamma') == gmax), None) if gmax is not None else None

    def cls_colour(c):
        return COL['RED'] if R.is_fault_class(c) else COL['GREEN']

    def copy(path):
        if not path:
            return None
        src = Path(path)
        try:  # re-encode frames as JPEG to keep the PDF small; fall back to a plain copy
            from PIL import Image
            dst = out / 'evidence' / (src.stem + '.jpg')
            if not dst.exists():
                Image.open(src).convert('RGB').save(dst, quality=86, optimize=True)
        except ImportError:
            dst = out / 'evidence' / src.name
            if not dst.exists():
                shutil.copy(src, dst)
        return f'evidence/{dst.name}'

    def best_view(d):
        vs = [v for v in d['view_list'] if v.get('image')]
        if not vs:
            return None
        fault = [v for v in vs if R.is_fault_class(v.get('cls'))]
        pool = fault or vs
        return max(pool, key=lambda v: v.get('conf') or 0)

    # what was never measured anywhere in this run
    nothing = []
    if all(d.get('heat_rise_c') is None for d in drums):
        nothing.append('drum surface temperature')
    if not any(d.get('swab') for d in drums):
        nothing.append('surface wipes (swabs)')
    h2_any = any(t.get('h2') is not None for t in run['tele']) or any((d.get('h2') or {}).get('ppm') is not None for d in drums)
    h2_status = next(((d.get('h2') or {}).get('status') for d in drums if (d.get('h2') or {}).get('status')), None)
    h2_limit = next(((d.get('h2') or {}).get('limit') for d in drums if (d.get('h2') or {}).get('limit')), None)
    if not h2_any and h2_status != 'below_detection':
        nothing.append('hydrogen')
    if all(d.get('category') is None for d in drums):
        nothing.append('waste category (LLW / ILW)')

    # verdict sentence
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

    rid = f'CANIS-{run["id"]}'
    C = []
    w = C.append
    w(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      f'<title>Inspection report {e(rid)}</title><style>{font_face()}\n{(HERE / "style.css").read_text()}</style></head>'
      f'<body><main class="doc">')

    # ================= page 1: verdict and actions
    w('<header class="band">' + svg_inline('dog-head.svg', 'mark') +
      f'<div><img class="word" src="{data_uri(ASSETS / "wordmark-white.png")}" alt="C.A.N.I.S.">'
      '<div class="sub">Drum store inspection report</div></div>'
      f'<div class="id"><b>{e(rid)}</b>{e(store)}<br>{e(run.get("started") or "start time not logged")}</div></header>')
    if run.get('note'):
        w(f'<div class="callout mono" style="font-size:7.6pt">{e(run["note"])}</div>')
    w(f'<section class="verdict"><div class="eyebrow">Verdict</div><p>{e(verdict)}</p>')
    if area:
        w(f'<p style="font-size:10.5pt;font-weight:400;margin-top:4px;color:#2a2f34">{e("; ".join(area).capitalize())}. '
          'Aisle ratings are simulation flags; site staff decide access.</p>')
    tot = max(1, len(drums))
    w('<div class="statusbar">' + ''.join(f'<span style="width:{100 * n[k] / tot:.2f}%;background:{COL[k]}"></span>'
                                          for k in order if n[k]) + '</div>')
    w('<div class="statusbar-key">' + ''.join(f'<span><i class="dot" style="background:{COL[k]}"></i>{R.COLOUR_WORD[k]} {n[k]}</span>'
                                              for k in order) + '</div></section>')

    kp = [('Drums checked', f'{inspected}<small>/ {run["expected"]}</small>', 'clear look and confirmed identity'),
          ('Action needed', n['RED'], 'red'), ('Check again', n['AMBER'], 'amber'), ('No problem found', n['GREEN'], 'green'),
          ('Peak gamma', f'{gmax:.2f}<small>µSv/h</small>' if gmax is not None else '—',
           f'at {clock(t_gmax)} · restricted above 7.5' if gmax is not None else 'not measured'),
          ('Aisle sections', f'{len(zs)}', ' · '.join(f'{zc[z]} {R.ZONE_WORD[z].lower()}' for z in R.ZONE_ORDER if zc[z])),
          ('Robot dose', f'{run["dose_uSv"]:.4f}<small>µSv</small>' if run.get('dose_uSv') is not None else '—',
           f'limit {run["budget_uSv"]} µSv' if run.get('budget_uSv') else 'no limit logged'),
          ('Mission time', e(duration(run.get('duration_s')) or '—'), 'simulated time')]
    w('<div class="kpis">' + ''.join(f'<div class="kpi"><div class="k">{k}</div><div class="v">{v}</div><div class="s">{e(s)}</div></div>'
                                     for k, v, s in kp) + '</div>')

    w('<div class="sec-head"><div class="eyebrow">What to do now</div><div class="eyebrow">most urgent first</div></div>')
    todo = [d for d in reg if colours[d['drum_id']][0] != 'GREEN']
    if todo:
        w('<table class="actions"><thead><tr><th></th><th>Drum</th><th>Result</th><th>Do this</th></tr></thead><tbody>')
        for i, d in enumerate(todo, 1):
            w(f'<tr><td>{i}</td><td><b>{e(d["drum_id"])}</b></td><td>{chip(colours[d["drum_id"]][0])}</td>'
              f'<td class="do">{e(R.action_for(d))}</td></tr>')
        w('</tbody></table>')
    else:
        w('<p>No drum needs follow-up from this inspection. Continue routine inspections.</p>')

    w('<div class="sec-head" style="margin-top:14px"><div class="eyebrow">This inspection</div></div><dl class="facts">')
    facts = [('Store', store), ('Report', rid), ('Started', run.get('started') or 'not logged'),
             ('Mission time', duration(run.get('duration_s')) or 'not logged'),
             ('Inspected by', 'C.A.N.I.S. robot (Spot)'), ('Drums in scope', run['expected']),
             ('Software', commit or 'not recorded'), ('Input format', run['source_format'])]
    for k, v in facts:
        w(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>')
    w('</dl>')
    if nothing:
        w(f'<p class="note">Not measured in this inspection: {e(", ".join(nothing))}. '
          'Tables print “not measured”; no value is estimated.</p>')

    # ================= 1. aisle survey
    w('<section class="page"><div class="sec-head"><h2><span class="n">01</span>Aisle survey</h2>'
      f'<div class="eyebrow">{len(zs)} sections · {R.SECTION_M:g} m each</div></div>')
    w('<p class="lede">The robot measured gamma radiation as it walked. Each aisle is split into 2-metre sections, and '
      'each section takes the worst rating that applies. A section is only rated low gamma if the robot measured it.</p>')
    w(fig_map(drums, colours, zs, run['tele']))
    lg = [(f'background:{ZCOL[z]};opacity:{1 if z == "NOT CHECKED" else .35}', R.ZONE_WORD[z]) for z in R.ZONE_ORDER]
    lg += [(f'background:{COL[k]}', f'Drum: {R.COLOUR_WORD[k].lower()}') for k in order]
    lg += [('background:#f1c543;border-radius:50%;border:1px solid #111', 'Start'), ('background:#111315', 'End'),
           ('height:2px;background:#111315;vertical-align:3px', "Robot's route")]
    w('<div class="legend">' + ''.join(f'<span><i style="{s}"></i>{e(t)}</span>' for s, t in lg) +
      '<span>T1–T3 = shelf, bottom to top</span></div>')
    w('<table><thead><tr><th>Aisle</th><th>Section</th><th>Rating</th><th class="r">Peak gamma <span class="u">µSv/h</span></th>'
      '<th class="r">H₂ <span class="u">ppm</span></th><th class="r">Samples</th><th>Why</th></tr></thead><tbody>')
    for z in sorted(zs, key=lambda z: (R.ZONE_ORDER.index(z['zone']), z['aisle'], z['lo'])):
        h2 = (num(z['h2max'], '{:.0f}') if z['h2max'] is not None else
              (f'&lt; {h2_limit:g}' if h2_status == 'below_detection' and z['samples'] else NM))
        w(f'<tr><td><b>{e(z["aisle"])}</b></td><td>{e(z["part"])}</td><td>{zchip(z["zone"])}</td>'
          f'<td class="r">{num(z["gmax"]) if z["samples"] else "—"}</td><td class="r">{h2 if z["samples"] else "—"}</td>'
          f'<td class="r">{z["samples"]}</td><td><span class="p">{e(z["reason"])}</span></td></tr>')
    w('</tbody></table><p class="note">Sections are measured along the aisle from its first stack. '
      'H₂ “&lt; n” means below the sensor’s detection limit.</p></section>')

    # ================= 2. register
    w('<section style="margin-top:24px"><div class="sec-head"><h2><span class="n">02</span>Every drum at a glance</h2>'
      f'<div class="eyebrow">{len(drums)} drums · most urgent first</div></div>')
    w('<table><thead><tr><th>Drum</th><th>Result</th><th>What was seen</th><th class="r">How sure</th>'
      '<th class="r">Fault views</th><th class="r">Gamma <span class="u">µSv/h</span></th><th>Label</th><th>Where</th></tr></thead><tbody>')
    for d in reg:
        c = colours[d['drum_id']][0]
        ce = R.certainty(d.get('confidence'))
        lab = d.get('label')
        lt = NL if not lab else ('read' if lab['readable'] else '<b style="color:var(--amber)">unreadable</b>')
        w(f'<tr><td><b>{e(d["drum_id"])}</b></td><td>{chip(c)}</td><td>{e(R.finding_word(d["finding"]))}</td>'
          f'<td class="r">{f"{ce[0]} {ce[1]}%" if ce else NL}</td>'
          f'<td class="r">{d.get("fault_views", 0)}/{d.get("views") or 0}</td>'
          f'<td class="r">{num(d.get("dose_rate_at_drum_uSv_h"))}</td><td>{lt}</td>'
          f'<td><span class="p">{e(R.where(d, max_tier))}</span></td></tr>')
    w('</tbody></table>')
    w('<p class="note">How sure = the detector’s confidence in what it reported: High ≥ 70%, Medium ≥ 50%, Low below. '
      'Fault views = camera views that showed damage, out of all views taken. '
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
        rel = copy(bv['image']) if bv else None
        w(f'<article class="finding"><div class="finding-head"><div><span class="id">{e(d["drum_id"])}</span> '
          f'<span class="where">{e(R.where(d, max_tier))}</span></div>{chip(c)}</div><div class="finding-body"><div>')
        cap = None
        if bv:
            cap = (f'{e(bv.get("label") or "evidence")} · {clock(bv.get("t"), True)} into the run'
                   + (f' · frame {bv["frame"]}' if bv.get('frame') is not None else '')
                   + (f' · body pitch {bv["pitch"]:.1f}°' if bv.get('pitch') is not None else '')
                   + '. Box and label are the detector’s own output.')
        w(shot(bv or {}, rel, cls_colour, True, cap))
        others = [v for v in d['view_list'] if v.get('image')]
        if len(others) > 1:
            w('<div class="strip">' + ''.join(
                f'<figure>{shot(v, copy(v["image"]), cls_colour, False)}'
                f'<figcaption>{e((v.get("cls") or "?").upper())} {v["conf"]:.2f}</figcaption></figure>'
                for v in others[:6]) + '</div>')
        w('</div><div><table class="kv"><tbody>')
        ce = R.certainty(d.get('confidence'))
        lab = d.get('label') or {}
        rows = [('What was seen', e(R.finding_word(d['finding']))),
                ('How sure', f'{ce[0]} ({ce[1]}%)' if ce else NL),
                ('Views', f'{d.get("fault_views", 0)} of {d.get("views") or 0} showed damage'),
                ('Why this rating', f'<span class="p">{e("; ".join(why).capitalize())}.</span>'),
                ('Gamma at drum', (f'{R.radiation_word(d["dose_rate_at_drum_uSv_h"])} · ' + num(d['dose_rate_at_drum_uSv_h'], unit='µSv/h'))
                 if d.get('dose_rate_at_drum_uSv_h') is not None else NM),
                ('Air', (num(d['air_c'], '{:.1f}', '°C') + (f' · RH {d["rh"]:.0f}%' if d.get('rh') is not None else ''))
                 if d.get('air_c') is not None else NM),
                ('Surface temp.', NM if d.get('heat_rise_c') is None else num(d['heat_rise_c'], '{:+.1f}', '°C vs air')),
                ('Hydrogen', (num(d['h2']['ppm'], '{:.0f}', 'ppm') if (d.get('h2') or {}).get('ppm') is not None else
                              f'below detection (&lt; {d["h2"]["limit"]:g} ppm)' if (d.get('h2') or {}).get('status') == 'below_detection'
                              else NM)),
                ('Surface wipe', 'not taken' if not d.get('swab') else
                 ('above limit' if R.swab_over(d['swab']) else 'below limit')),
                ('Label', NL if not lab else ('read: ' + e(' → '.join(lab.get('reads') or [])) if lab.get('readable')
                                              else '<b>not confirmed</b> · reads: ' + e(' → '.join(lab.get('reads') or [])))),
                ]
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
    if greens:
        w('<section class="keep" style="margin-top:18px"><div class="sec-head"><h2><span class="n">04</span>Drums with no problem found</h2>'
          f'<div class="eyebrow">{len(greens)} drums · best view each</div></div><div class="gallery">')
        for d in greens:
            bv = best_view(d)
            ce = R.certainty(d.get('confidence'))
            w(f'<figure>{shot(bv or {}, copy(bv["image"]) if bv else None, cls_colour, False)}'
              f'<div class="cap"><b>{e(d["drum_id"])}</b><span class="muted">{f"{ce[1]}%" if ce else ""} · '
              f'{d.get("views") or 0} views</span></div></figure>')
        w('</div></section>')
    w('</section>')

    # ================= 5. gaps, accuracy, method
    w('<section class="page"><div class="sec-head"><h2><span class="n">05</span>What this report cannot tell you</h2></div>')
    ci = [d for d in drums if d['status'] == "Couldn't inspect"]
    ns = [z for z in zs if z['zone'] == 'NOT CHECKED']
    items = [f'<b class="mono">{e(d["drum_id"])}</b>: {e(d.get("reason") or "no clear look")}.' for d in ci]
    items += [f'<b class="mono">Aisle {e(z["aisle"])} {e(z["part"])}</b>: {e(z["reason"])}' for z in ns]
    items += [f'<b class="mono">{e(x[:1].upper() + x[1:])}</b>: not measured anywhere in this inspection.' for x in nothing]
    w('<ul class="plain">' + ''.join(f'<li>{x}</li>' for x in items) + '</ul>' if items
      else '<p>Every drum and every aisle section in scope was checked.</p>')

    w('<h3>How accurate was the robot?</h3>')
    if run.get('truth'):
        truth = run['truth']
        flagged_ids = {d['drum_id'] for d in drums if d['status'] in ('Confirmed defect', 'Suspect')}
        cant = {d['drum_id'] for d in ci}
        found = sorted(k for k, v in truth.items() if v and k in flagged_ids)
        missed = sorted(k for k, v in truth.items() if v and k not in flagged_ids and k not in cant)
        false = sorted(k for k, v in truth.items() if not v and k in flagged_ids)
        w('<p class="lede">In a simulated store we know which drums were really damaged. The robot was never told; '
          'the comparison is only made here.</p><table><thead><tr><th>Damaged drums</th><th>Found</th><th>Missed</th>'
          '<th>False alarms</th><th>Could not inspect</th></tr></thead><tbody>'
          f'<tr><td class="r">{sum(truth.values())}</td><td>{len(found)} {e(" ".join(found))}</td>'
          f'<td><b>{len(missed)}</b> {e(" ".join(missed))}</td><td>{len(false)} {e(" ".join(false))}</td>'
          f'<td>{len(cant)} {e(" ".join(sorted(cant)))}</td></tr></tbody></table>'
          '<p class="note">A missed drum is the more serious error. A false alarm costs one extra human check.</p>')
    else:
        w('<p class="note">This run folder has no ground-truth file, so the self-check was not made. '
          'Ground truth is never written into the robot’s logs; add it as ground_truth.json to score the run.</p>')

    w('<h3>How the ratings were made</h3><table><thead><tr><th>Part</th><th>Does</th><th>Never does</th></tr></thead><tbody>'
      '<tr><td><b>Detector</b></td><td><span class="p">Draws a box and a class (normal / rust / bulge) on each camera view.</span></td>'
      '<td><span class="p">Decide a rating.</span></td></tr>'
      '<tr><td><b>Planner</b></td><td><span class="p">Chooses the next drum or a closer look. Its reasons are quoted in the record.</span></td>'
      '<td><span class="p">Change a rating, zone or number.</span></td></tr>'
      '<tr><td><b>Rules</b></td><td><span class="p">Turn views and readings into drum results and aisle ratings, the same way every time.</span></td>'
      '<td><span class="p">Read free text.</span></td></tr>'
      '<tr><td><b>Report</b></td><td><span class="p">Lays out what the run logged.</span></td>'
      '<td><span class="p">Estimate a value that was not logged.</span></td></tr></tbody></table>')
    w('<h3>Limits used</h3><table><thead><tr><th>Rating</th><th>Level</th><th>Source</th></tr></thead><tbody>' +
      ''.join(f'<tr><td><b>{e(a)}</b></td><td>{e(b)}</td><td><span class="p">{e(c)}</span></td></tr>' for a, b, c in R.LIMITS) +
      '</tbody></table>')
    w('<h3>How to read the labels</h3><div class="key">'
      f'{chip("RED")}<span class="p">Damage confirmed from more than one view. An engineer should assess the drum.</span>'
      f'{zchip("KEEP OUT")}<span class="p">Highest-priority simulation flag.</span>'
      f'{chip("AMBER")}<span class="p">Possible damage, or the robot could not confirm the drum.</span>'
      f'{zchip("RESTRICTED")}<span class="p">Raised gamma, or an unresolved drum in the section.</span>'
      f'{chip("GREEN")}<span class="p">No damage seen in this inspection.</span>'
      f'{zchip("LOW GAMMA")}<span class="p">Gamma measured and below 7.5 µSv/h.</span>'
      f'<span></span><span></span>{zchip("NOT CHECKED")}<span class="p">No readings here: treat as unknown.</span></div>')
    w('<p class="note">Practice run in a computer-simulated store (NVIDIA Isaac Sim). Radiation comes from a simplified model; '
      'the detector was trained on synthetic images; rust extent is judged from photos, not measured. Only a surface wipe can '
      'show contamination. The structure follows the themes of the NDA’s Guidance on Monitoring of Waste Packages During '
      'Storage (WPS/640).</p></section>')

    # ================= appendix A: traces
    w('<section class="page"><div class="sec-head"><h2><span class="n">A</span>Readings over time</h2>'
      '<div class="eyebrow">mission clock mm:ss</div></div>')
    w('<p class="lede">Every sensor sample the robot logged. Yellow lines mark planner decisions.</p>')
    ev = [(x['t'], x.get('action') or '') for x in run['events'] if x['kind'] == 'plan' and x.get('t') is not None]
    g = fig_trace(run['tele'], 'gamma', 'Gamma', 'µSv/h',
                  [(R.GAMMA_RESTRICT, 'restricted 7.5', '#b26a00'), (R.GAMMA_KEEPOUT, 'keep out 100', '#b3261e')],
                  ev, 120, '{:.2f}')
    w(g or '<p class="note">Gamma: not measured.</p>')
    if gmax is not None and gmax < R.GAMMA_RESTRICT:
        w(f'<p class="note">The restricted level (7.5 µSv/h) is {R.GAMMA_RESTRICT / gmax:.1f}× the highest reading, '
          'so it is off this scale.</p>')
    for key, lab, unit in (('air_c', 'Air temperature', '°C'), ('rh', 'Relative humidity', '%'), ('h2', 'Hydrogen', 'ppm'),
                           ('dose_uSv', 'Robot dose', 'µSv')):
        f = fig_trace(run['tele'], key, lab, unit, (), ev, 86)
        if f:
            w(f)
    if not h2_any:
        w('<p class="note">Hydrogen: ' + (f'below the detection limit ({h2_limit:g} ppm) for every logged sample.'
                                          if h2_status == 'below_detection' else 'not measured.') + '</p>')
    w('</section>')

    # ================= appendix B: record
    w('<section style="margin-top:24px"><div class="sec-head"><h2><span class="n">B</span>Step-by-step record</h2>'
      f'<div class="eyebrow">{len(run["events"])} logged events</div></div>')
    w('<p class="lede">What the robot decided and why, in order. Planner reasons are quoted exactly as logged; '
      'they explain a choice of route and never set a rating.</p>')
    w('<table><thead><tr><th>Time</th><th>Drum</th><th>Source</th><th>What happened</th><th class="r">ms</th></tr></thead><tbody>')
    for x in run['events']:
        src = x.get('source') or ''
        is_c = 'cosmos' in src.lower()
        txt = x.get('text') or ''
        if is_c:
            act = x.get('action') or ''
            txt = (f'<b class="mono">{e("Go to " + act if act in colours else act.replace("_", " ").capitalize())}.</b> '
                   f'<span class="p">“{e(txt)}”</span>')
        else:
            txt = f'<span class="p">{e(txt)}</span>'
        w(f'<tr><td class="num">{clock(x.get("t"), True)}</td><td><b>{e(x.get("drum") or "")}</b></td>'
          f'<td><span class="src{" cosmos" if is_c else ""}">{e(src)}</span></td><td>{txt}</td>'
          f'<td class="r">{x["latency_ms"] if x.get("latency_ms") is not None else ""}</td></tr>')
    w('</tbody></table></section>')

    # ================= appendix C: technical
    w('<section class="page"><div class="sec-head"><h2><span class="n">C</span>Technical details</h2>'
      '<div class="eyebrow">for engineers and auditors</div></div><table class="kv"><tbody>')
    for k, v in [('Report', rid), ('Run folder', '/'.join(Path(run['run_dir']).parts[-3:])), ('Input format', run['source_format']),
                 ('Report software', commit or 'not recorded')] + list(run.get('tech') or []):
        w(f'<tr><td>{e(k)}</td><td style="overflow-wrap:anywhere">{e(v) if v is not None else NL}</td></tr>')
    w('<tr><td>Status names</td><td>Action needed = Confirmed defect · Check again = Suspect or Couldn’t inspect · '
      'No problem found = OK</td></tr></tbody></table>')
    w('<h3>Evidence frames</h3><table><thead><tr><th>Drum</th><th>View</th><th class="r">Time</th><th class="r">Frame</th>'
      '<th>Class</th><th class="r">Conf.</th><th class="r">Pitch</th><th>Input SHA-256</th></tr></thead><tbody>')
    for d in sorted(drums, key=lambda d: d['drum_id']):
        for v in d['view_list']:
            conf = f"{v['conf']:.3f}" if v.get('conf') is not None else ''
            pitch = f"{v['pitch']:.1f}°" if v.get('pitch') is not None else ''
            frame = v.get('frame') if v.get('frame') is not None else ''
            sha = (v.get('sha') or '')[:16] + ('…' if v.get('sha') else '')
            w(f'<tr><td><b>{e(d["drum_id"])}</b></td><td>{e(v.get("label"))}</td><td class="r">{clock(v.get("t"), True)}</td>'
              f'<td class="r">{e(frame)}</td><td>{e(v.get("cls"))}</td><td class="r">{conf}</td>'
              f'<td class="r">{pitch}</td><td>{e(sha)}</td></tr>')
    w('</tbody></table></section></main></body></html>')

    (out / 'index.html').write_text('\n'.join(C))
    summary = dict(report=rid, drums={k: n[k] for k in order}, zones=dict(zc), inspected=inspected,
                   expected=run['expected'], peak_gamma_uSv_h=gmax, verdict=verdict,
                   results={d['drum_id']: dict(colour=colours[d['drum_id']][0], status=d['status'],
                                               why=colours[d['drum_id']][1], action=R.action_for(d)) for d in reg},
                   sections=[{k: z[k] for k in ('aisle', 'part', 'zone', 'reason', 'gmax', 'samples')} for z in zs])
    return summary
