"""C.A.N.I.S. post-run inspection report (PDF, typeset with LaTeX).

    python build_pdf_report.py <run_dir> [--drums sim/drums.json] [--previous old/memory.json]
                               [--commit <hash>] [--out <dir>] [--logo assets/logo.png]

Written for store managers and safety staff, not engineers: plain words, drum and aisle names
instead of coordinates, technical details only in the last appendix.

Reads ONLY the run's logged files (memory.json, telemetry.jsonl, decisions.jsonl, ground_truth.json,
route.json, stills/) plus the store inventory. Anything not logged is printed as "not measured".
No language model writes any fact in this report.
"""
import argparse
import json
import math
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent

# ---- criteria (sources printed in the report) ------------------------------------------------------
GAMMA_RESTRICT = 7.5       # uSv/h, HSE L121 reg. 17 paras 297-298
GAMMA_KEEPOUT = 100.0      # uSv/h, HSE L121
SWAB_ALPHA, SWAB_BG = 0.4, 4.0  # Bq/cm2, IAEA SSR-6 Rev. 2 para 508
HEAT_RISE = 5.0            # degC above air, team demo rule
SECTION_M = 2.0
CAMERA_CROP = (0, 100, 1280, 620)   # chase-camera panel of the 1920x1080 overlay frame

INK = '#1A1A18'
COL = {'RED': '#B3261E', 'AMBER': '#C98A00', 'GREEN': '#2E7D32', 'GREY': '#8A8A85'}
ZONE_COL = {'KEEP OUT': COL['RED'], 'RESTRICTED': COL['AMBER'], 'LOW GAMMA': COL['GREEN'], 'NOT CHECKED': COL['GREY']}
FINDING = {'corrosion': 'Rust', 'bulge': 'Bulging', 'bulge+corrosion': 'Rust and bulging',
           'corrosion+bulge': 'Rust and bulging', 'none': 'Nothing found', '': 'Nothing found'}
WASTE = {'LLW': 'Low-level', 'ILW': 'Intermediate-level'}


def jl(p):
    p = Path(p)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def tex(s):
    s = '' if s is None else str(s)
    rep = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
           '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    s = ''.join(rep.get(c, c) for c in s)
    return s.replace('µ', r'\textmu{}').replace('°', r'\textdegree{}').replace('–', '--').replace('—', '---')


def clock(t):
    t = int(round(t or 0))
    return f'{t // 60}:{t % 60:02d}'


def duration(t):
    t = int(round(t or 0))
    m, s = divmod(t, 60)
    return f'{m} min {s} s' if m else f'{s} s'


def finding(d):
    f = d.get('finding') or 'none'
    return FINDING.get(f, f.replace('+', ' and ').capitalize())


def certainty(c):
    if not c:
        return '--'
    word = 'High' if c >= 0.7 else 'Medium' if c >= 0.5 else 'Low'
    return f'{word} ({c * 100:.0f}\\%)'


def radiation(v):
    if v is None:
        return 'not measured'
    word = 'High' if v > GAMMA_KEEPOUT else 'Raised' if v > GAMMA_RESTRICT else 'Normal'
    return f'{word} ({v:.1f} µSv/h)' if v < 10 else f'{word} ({v:.0f} µSv/h)'


def where(d):
    m = re.match(r'([A-Z])(\d+)', d['drum_id'])
    return f'Row {m.group(1)}, drum {int(m.group(2))}' if m else f'Row {d.get("row", "?")}'


# ---- rules ------------------------------------------------------------------------------------------
def drum_colour(d):
    why = []
    swab, heat, dose = d.get('swab'), d.get('heat_rise_c'), d.get('dose_rate_at_drum_uSv_h')
    red = d['status'] == 'Confirmed defect'
    if red:
        why.append(f'{finding(d).lower()} recorded as a confirmed finding')
    if swab and (swab.get('alpha', 0) > SWAB_ALPHA or swab.get('beta_gamma', 0) > SWAB_BG):
        red = True; why.append('surface wipe found contamination above the limit')
    if heat is not None and heat >= HEAT_RISE and 'bulge' in (d.get('finding') or ''):
        red = True; why.append('bulging drum is warmer than the air around it')
    if dose is not None and dose > GAMMA_KEEPOUT:
        red = True; why.append('very high radiation at the drum')
    if red:
        return 'RED', why
    amber = d['status'] in ('Suspect', "Couldn't inspect")
    if d['status'] == 'Suspect':
        why.append(f'possible {finding(d).lower()}, flagged for review')
    if d['status'] == "Couldn't inspect":
        why.append('the robot could not get a clear look')
    if heat is not None and heat >= HEAT_RISE:
        amber = True; why.append('drum is warmer than the air around it')
    return ('AMBER' if amber else 'GREEN'), why


def action_for(d, colour):
    f, s = d.get('finding') or '', d['status']
    if s == "Couldn't inspect":
        return 'Inspect again once the area is clear and radiation is back to normal.'
    if s == 'Suspect':
        return 'Inspect again within 7 days, with a closer look and a surface wipe (swab).'
    if 'bulge' in f:
        if d.get('heat_rise_c') is None:
            return ('Limit access to this aisle. Ask an engineer to assess the drum for pressure build-up, '
                    'and measure its surface temperature (not measured in this inspection).')
        if d['heat_rise_c'] >= HEAT_RISE:
            return 'Keep people out of this aisle section. Isolate the drum and get an urgent engineering assessment.'
        return 'Limit access to this aisle. Ask an engineer to assess the drum. Inspect again at the next round.'
    if 'corrosion' in f:
        return ('Ask an engineer to assess how far the rust has gone. Take a surface wipe if none was taken. '
                'Consider placing the drum in an overpack (a larger outer drum).')
    return 'No action. Routine inspection.'


def row_positions(inventory):
    rows = defaultdict(list)
    for d in inventory:
        rows[d['row']].append(d['y'])
    return sorted((sum(v) / len(v), k) for k, v in rows.items())


def aisle_label(y, rows):
    below = [r for r in rows if r[0] < y]
    above = [r for r in rows if r[0] > y]
    if below and above:
        return f'Aisle between rows {below[-1][1]} and {above[0][1]}'
    if above:
        return f'Walkway beside row {above[0][1]}'
    return f'Walkway beside row {below[-1][1]}'


def zones(tele, drums, colours, rows):
    aisles = sorted({round(t['aisle_y'], 2) for t in tele if t.get('aisle_y') is not None})
    if not aisles or not drums:
        return []
    xs = [d['x'] for d in drums]
    x0 = math.floor(min(xs) - 1.0)
    n = math.ceil((max(xs) + 1.0 - x0) / SECTION_M)
    seen = defaultdict(list)
    for t in tele:
        x, y = t['truth'][0], t['truth'][1]
        a = min(aisles, key=lambda a: abs(a - y))
        if abs(a - y) > 1.2:
            continue
        k = int((x - x0) // SECTION_M)
        if 0 <= k < n:
            seen[(a, k)].append(t)
    out = []
    for a in aisles:
        for k in range(n):
            lo, hi = x0 + k * SECTION_M, x0 + (k + 1) * SECTION_M
            ts = seen.get((a, k), [])
            near = [d for d in drums if lo <= d['x'] < hi and abs(d['y'] - a) < 1.6]
            base = dict(aisle=a, name=aisle_label(a, rows), part=f'{k * SECTION_M:g}--{(k + 1) * SECTION_M:g} m',
                        lo=lo, hi=hi, drums=near, gmax=None, h2max=None)
            if not ts:
                out.append(dict(base, zone='NOT CHECKED', reason='The robot did not go here this time.'))
                continue
            gamma = [t['dose_rate_uSv_h'] for t in ts if t.get('dose_rate_uSv_h') is not None]
            g = max(gamma, default=None)
            h2 = [t['hydrogen_ppm'] for t in ts if 'hydrogen_ppm' in t]
            base.update(gmax=g, h2max=max(h2) if h2 else None)
            reds = [d['drum_id'] for d in near if colours[d['drum_id']][0] == 'RED']
            unresolved = [d['drum_id'] for d in near if colours[d['drum_id']][0] == 'AMBER']
            if g is not None and g > GAMMA_KEEPOUT:
                z, r = 'KEEP OUT', f'Radiation reached {g:.0f} µSv/h, above the keep-out level.'
            elif any(d.get('heat_rise_c') is not None and d['heat_rise_c'] >= HEAT_RISE
                     and 'bulge' in (d.get('finding') or '') for d in near):
                z, r = 'KEEP OUT', 'A bulging drum here is warmer than the air: possible pressure build-up.'
            elif g is not None and g > GAMMA_RESTRICT:
                z, r = 'RESTRICTED', f'Radiation reached {g:.0f} µSv/h, above the controlled-area level.'
            elif reds:
                z, r = 'RESTRICTED', 'Damaged drum here: ' + ', '.join(reds) + '.'
            elif unresolved:
                z, r = 'RESTRICTED', 'Unresolved drum findings: ' + ', '.join(unresolved) + '.'
            elif g is None:
                z, r = 'NOT CHECKED', 'No gamma reading was logged here.'
            else:
                z, r = 'LOW GAMMA', f'Highest logged gamma was {g:.1f} µSv/h.'
            out.append(dict(base, zone=z, reason=r))
    return out


def plain_step(x):
    """One plain-English line per logged decision: (drum, sentence)."""
    kind, txt, act = x.get('kind', ''), x.get('text', ''), x.get('action_id', '')
    m = re.match(r'(\w\d+) (corrosion|bulge|bulge\+corrosion|corrosion\+bulge) (?:confirmed )?([\d.]+)', txt)
    if kind == 'second_look' and m:
        return m.group(1), f'Possible {FINDING.get(m.group(2), m.group(2)).lower()} on {m.group(1)}. Went back for a second look.'
    if kind == 'confirmed' and m:
        return m.group(1), f'{FINDING.get(m.group(2), m.group(2))} on {m.group(1)} confirmed from a second angle.'
    if kind == 'back_off':
        d = re.search(r'near (\w\d+)', txt)
        return (d.group(1) if d else ''), 'Radiation rose sharply. The robot stepped back to a safer spot to wait.'
    if kind == 'return':
        return '', 'Radiation back to normal. The robot carried on with the round.'
    if act:
        drum = act.rsplit('_', 1)[-1] if '_' in act else ''
        if act.startswith('inspect_'):
            return drum, f'Went to drum {drum} for a closer inspection.'
        if act.startswith('swab_'):
            return drum, f'Took a surface wipe (swab) at drum {drum}.'
        if act.startswith('better_view_'):
            return drum, f'Moved for a clearer view of drum {drum}.'
        if act == 'continue_patrol':
            return '', 'Carried on with the round.'
    return x.get('drum', ''), txt


def crop_photo(src, dst):
    im = Image.open(src)
    if im.size == (1920, 1080):
        im = im.crop(CAMERA_CROP)
    im.convert('RGB').save(dst, quality=90)


# ---- figures ----------------------------------------------------------------------------------------
def setup_mpl():
    try:
        plt.rcParams.update({'text.usetex': True, 'font.family': 'sans-serif',
                             'text.latex.preamble': r'\usepackage[T1]{fontenc}\usepackage[default]{sourcesanspro}'
                                                    r'\usepackage{textcomp}'})
        fig = plt.figure(); fig.text(0.5, 0.5, 'test'); fig.savefig('/dev/null', format='pdf'); plt.close(fig)
    except Exception:
        plt.rcParams.update({'text.usetex': False, 'font.family': 'sans-serif',
                             'font.sans-serif': ['Source Sans 3', 'Source Sans Pro', 'Helvetica', 'DejaVu Sans']})
    plt.rcParams.update({'font.size': 9, 'axes.linewidth': 0.6, 'axes.edgecolor': INK,
                         'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'axes.labelcolor': INK})


def mu(s):
    return s.replace('µ', r'\textmu ') if plt.rcParams['text.usetex'] else s


def fig_map(path, inventory, drums, colours, zs, trail, spike, rows):
    fig, ax = plt.subplots(figsize=(6.6, 3.5))
    for z in zs:
        c = ZONE_COL[z['zone']]
        ax.add_patch(Rectangle((z['lo'], z['aisle'] - 0.5), z['hi'] - z['lo'], 1.0, facecolor=c,
                               alpha=0.10 if z['zone'] == 'NOT CHECKED' else 0.28, edgecolor='white', lw=1.2,
                               hatch='////' if z['zone'] == 'NOT CHECKED' else None))
    ids = {d['drum_id'] for d in drums}
    for d in inventory:
        if d['label'] not in ids:
            ax.add_patch(Circle((d['x'], d['y']), 0.3, facecolor='white', edgecolor='#C4C4BE', lw=0.7))
    mid = sum(r[0] for r in rows) / len(rows)
    for d in drums:
        ax.add_patch(Circle((d['x'], d['y']), 0.3, facecolor=COL[colours[d['drum_id']][0]], edgecolor=INK, lw=0.6))
        above = d['y'] > mid
        ax.text(d['x'], d['y'] + (0.42 if above else -0.42), d['drum_id'], ha='center',
                va='bottom' if above else 'top', fontsize=7.5)
    xs = [d['x'] for d in inventory]
    for y, r in rows:
        ax.text(min(xs) - 0.9, y, f'Row {r}', ha='right', va='center', fontsize=8, color='#555550')
    if trail:
        ax.plot([p[0] for p in trail], [p[1] for p in trail], color=INK, lw=1.0)
        ax.plot(*trail[0][:2], marker='o', ms=4, color=INK)
    if spike and spike.get('at'):
        ax.plot(*spike['at'][:2], marker='x', ms=7, mew=1.6, color=COL['RED'])
    ax.set_aspect('equal'); ax.axis('off')
    ys = [d['y'] for d in inventory]
    ax.set_xlim(min(xs) - 2.6, max(xs) + 0.8); ax.set_ylim(min(ys) - 1.4, max(ys) + 1.4)
    h = [Rectangle((0, 0), 1, 1, facecolor=ZONE_COL[k], alpha=0.4) for k in ('LOW GAMMA', 'RESTRICTED', 'KEEP OUT', 'NOT CHECKED')]
    h += [Line2D([], [], marker='o', ls='', mfc=COL[k], mec=INK, ms=7) for k in ('RED', 'AMBER', 'GREEN')]
    h += [Line2D([], [], marker='o', ls='', mfc='white', mec='#C4C4BE', ms=7), Line2D([], [], color=INK),
          Line2D([], [], marker='x', ls='', color=COL['RED'], mew=1.6)]
    names = ['Low gamma', 'Restricted area', 'Keep out', 'Not checked', 'Drum: action needed', 'Drum: check again',
             'Drum: no problem', 'Not in this round', "Robot's route", 'Robot stepped back']
    ax.legend(h, names, fontsize=7.5, ncol=5, loc='upper center', bbox_to_anchor=(0.5, -0.02), frameon=False,
              handlelength=1.3, columnspacing=1.2)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def fig_traces(path, tele, budget, spike, has):
    t = [x['t'] for x in tele]
    rows = 2 + int(has['temp']) + int(has['h2'])
    fig, axs = plt.subplots(rows, 1, figsize=(6.6, 1.8 * rows), sharex=True)
    ax = axs[0]
    ax.plot(t, [x['dose_rate_uSv_h'] for x in tele], color=INK, lw=0.9)
    ax.axhline(GAMMA_RESTRICT, color=COL['AMBER'], lw=0.8, ls='--')
    ax.axhline(GAMMA_KEEPOUT, color=COL['RED'], lw=0.8, ls='--')
    ax.text(t[-1], GAMMA_RESTRICT * 1.12, 'restricted level', ha='right', va='bottom', fontsize=7.5, color=COL['AMBER'])
    ax.text(t[-1], GAMMA_KEEPOUT * 1.12, 'keep-out level', ha='right', va='bottom', fontsize=7.5, color=COL['RED'])
    ax.set_yscale('log'); ax.set_ylim(top=GAMMA_KEEPOUT * 2.2)
    ax.set_ylabel(mu('Radiation (µSv/h)'))
    ax = axs[1]
    ax.plot(t, [x['dose_uSv'] for x in tele], color=INK, lw=0.9)
    ax.axhline(budget, color=COL['RED'], lw=0.8, ls='--')
    ax.text(t[-1], budget, "robot's limit", ha='right', va='bottom', fontsize=7.5, color=COL['RED'])
    ax.set_ylim(0, budget * 1.25)
    ax.set_ylabel(mu("Robot's dose (µSv)"))
    i = 2
    if has['temp']:
        axs[i].plot(t, [x.get('temperature_c') for x in tele], color=INK, lw=0.9)
        axs[i].set_ylabel(r'Air temp. (\textdegree C)' if plt.rcParams['text.usetex'] else 'Air temp. (°C)'); i += 1
    if has['h2']:
        axs[i].plot(t, [x.get('hydrogen_ppm') for x in tele], color=INK, lw=0.9)
        axs[i].set_ylabel('Hydrogen (ppm)')
    for a in axs:
        if spike:
            a.axvspan(spike['t0'], spike.get('returned', spike['t0']), color=COL['RED'], alpha=0.08, lw=0)
        for s in ('top', 'right'):
            a.spines[s].set_visible(False)
    axs[-1].set_xlabel('Time into the inspection (seconds)')
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


# ---- main -------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir'); ap.add_argument('--drums', default=None)
    ap.add_argument('--previous'); ap.add_argument('--commit', default='not recorded')
    ap.add_argument('--out', default=None, help='default: <run_dir>/report')
    ap.add_argument('--logo', default=str(HERE / 'assets/logo.png'))
    ap.add_argument('--store', default='Drum Store 1 (simulated)')
    a = ap.parse_args()
    run = Path(a.run_dir); out = Path(a.out) if a.out else run / 'report'; out.mkdir(parents=True, exist_ok=True)
    run_id = run.name
    mem = json.loads((run / 'memory.json').read_text())
    tele = jl(run / 'telemetry.jsonl')
    decisions = jl(run / 'decisions.jsonl')
    gt = json.loads((run / 'ground_truth.json').read_text()) if (run / 'ground_truth.json').exists() else None
    route = json.loads((run / 'route.json').read_text()) if (run / 'route.json').exists() else {}
    drums = sorted(mem['drums'], key=lambda d: d['drum_id'])
    inv_path = Path(a.drums) if a.drums else run.parents[2] / 'sim/drums.json'
    names = {d.get('internal_id'): d['drum_id'] for d in drums}
    if inv_path.exists():
        inventory = [dict(label=names.get(d['id'], d['id']), x=d['x'], y=d['y'], row=d['row'])
                     for d in json.loads(inv_path.read_text())]
    else:
        inventory = [dict(label=d['drum_id'], x=d['x'], y=d['y'], row=d['row']) for d in drums]
    rows = row_positions(inventory)
    prev = {}
    if a.previous and Path(a.previous).exists():
        prev = {d['drum_id']: d['status'] for d in json.loads(Path(a.previous).read_text())['drums']}
    has = {'temp': any('temperature_c' in t for t in tele), 'h2': any('hydrogen_ppm' in t for t in tele)}

    colours = {d['drum_id']: drum_colour(d) for d in drums}
    zs = zones(tele, drums, colours, rows)
    spike = mem.get('spike')

    setup_mpl()
    fig_map(out / 'map.pdf', inventory, drums, colours, zs, route.get('trail', []), spike, rows)
    fig_traces(out / 'traces.pdf', tele, mem.get('budget_uSv', 0), spike, has)
    shutil.copy(a.logo, out / 'logo.png')
    (out / 'photos').mkdir(exist_ok=True)
    photo = {}
    for s in mem.get('stills', []):
        src = run / s['file']
        if src.exists() and s['drum'] in colours and (s['kind'] == 'confirmed' or s['drum'] not in photo):
            dst = out / 'photos' / (src.stem + '.jpg')
            crop_photo(src, dst)
            photo[s['drum']] = (f'photos/{dst.name}', s['t'])

    order = {'RED': 0, 'AMBER': 1, 'GREEN': 2}
    reg = sorted(drums, key=lambda d: (order[colours[d['drum_id']][0]], d['drum_id']))
    n = {k: sum(1 for c in colours.values() if c[0] == k) for k in order}
    zc = defaultdict(int)
    for z in zs:
        zc[z['zone']] += 1
    expected = mem.get('expected_drums', len(drums))
    inspected = sum(1 for d in drums if d['status'] != "Couldn't inspect")
    dose, budget = mem.get('dose_uSv', 0), mem.get('budget_uSv', 0)
    pct = 100 * dose / budget if budget else 0
    started = mem.get('started_utc', '')
    date = started.split(' ')[0] if started else 'not recorded'
    measured_none = [k for k, v in (('drum surface temperature', any(d.get('heat_rise_c') is not None for d in drums)),
                                     ('hydrogen gas', has['h2']),
                                     ('surface wipe (swab) results', any(d.get('swab') for d in drums))) if not v]

    sc = None
    if gt:
        truth = {k: bool(v['faults']) for k, v in gt['drums'].items()}
        flagged = {d['drum_id'] for d in drums if d['status'] in ('Confirmed defect', 'Suspect')}
        cant = {d['drum_id'] for d in drums if d['status'] == "Couldn't inspect"}
        sc = dict(faulty=sum(truth.values()),
                  found=sum(1 for k, v in truth.items() if v and k in flagged),
                  missed=sorted(k for k, v in truth.items() if v and k not in flagged and k not in cant),
                  false=sorted(k for k, v in truth.items() if not v and k in flagged),
                  cant=sorted(cant))

    def plural(k, word):
        return f'{k} {word}{"" if k == 1 else "s"}'

    parts = []
    if n['RED']:
        parts.append(f'{plural(n["RED"], "drum")} need{"s" if n["RED"] == 1 else ""} action')
    if n['AMBER']:
        parts.append(f'{n["AMBER"]} should be checked again')
    verdict = (' and '.join(parts) or 'No drum needs action') + '. '
    if zc['KEEP OUT']:
        verdict += f'{plural(zc["KEEP OUT"], "area")} must be kept clear of people. '
    if zc['RESTRICTED']:
        verdict += f'{plural(zc["RESTRICTED"], "area")} {"is" if zc["RESTRICTED"] == 1 else "are"} restricted. '
    if zc['NOT CHECKED']:
        verdict += f'{plural(zc["NOT CHECKED"], "area")} {"was" if zc["NOT CHECKED"] == 1 else "were"} not checked.'

    C = []
    w = C.append

    # ---------- page 1
    w(r'\thispagestyle{first}')
    w(r'\begin{minipage}[c]{0.13\textwidth}\includegraphics[width=\linewidth]{logo.png}\end{minipage}\hfill')
    w(r'\begin{minipage}[c]{0.84\textwidth}\raggedleft')
    w(r'{\large\bfseries C.A.N.I.S.}\\[-1pt]{\small\color{muted} Containment Analysis \& Nuclear Intelligence System}\\[10pt]')
    w(r'{\fontsize{24}{28}\selectfont\bfseries Drum Store Inspection Report}\\[4pt]')
    w(rf'{{\color{{muted}} {tex(a.store)} \enspace\textbar\enspace {tex(date)}}}')
    w(r'\end{minipage}\par\vspace{8pt}\rule{\textwidth}{0.6pt}\par\vspace{8pt}')

    w(r'\noindent\begin{tabularx}{\textwidth}{@{}>{\color{muted}}l X >{\color{muted}}l X@{}}')
    w(rf'Store & {tex(a.store)} & Report number & CANIS-{tex(run_id)}\\')
    w(rf'Inspected on & {tex(started or "not recorded")} & Time taken & {duration(mem.get("duration_s"))}\\')
    w(r'Inspected by & C.A.N.I.S.\ inspection robot & Status & Practice run in a simulated store\\')
    w(r'\end{tabularx}\par\vspace{10pt}')

    w(r'\begin{summarybox}')
    w(r'{\bfseries\large Summary}\par\vspace{6pt}')
    w(r'\begin{tabularx}{\linewidth}{@{}X r@{\hspace{28pt}}X r@{}}')
    w(rf'Drums checked & \textbf{{{inspected} of {expected}}} & Areas with low gamma & \textbf{{{zc["LOW GAMMA"]}}}\\')
    w(rf'\dotR\ Need action & \textbf{{{n["RED"]}}} & Areas restricted & \textbf{{{zc["RESTRICTED"]}}}\\')
    w(rf'\dotA\ Check again & \textbf{{{n["AMBER"]}}} & Areas to keep out of & \textbf{{{zc["KEEP OUT"]}}}\\')
    w(rf'\dotG\ No problem found & \textbf{{{n["GREEN"]}}} & Areas not checked & \textbf{{{zc["NOT CHECKED"]}}}\\')
    w(rf'Radiation dose to the robot & \textbf{{{pct:.0f}\% of its limit}} & Time taken & \textbf{{{duration(mem.get("duration_s"))}}}\\')
    w(r'\end{tabularx}\par\vspace{8pt}')
    w(rf'{{\large {tex(verdict)}}}')
    w(r'\end{summarybox}\par\vspace{10pt}')

    w(r'{\bfseries How to read this report}\par\vspace{2pt}')
    w(r'\begin{tabularx}{\textwidth}{@{}l X@{\hspace{14pt}}l X@{}}')
    w(r'\dotR & \textbf{Action needed.} Damage seen clearly. An engineer should assess the drum. & '
      r'\zone{LOW GAMMA} & Gamma below the demo threshold.\\')
    w(r'\dotA & \textbf{Check again.} Possible damage, not yet confirmed. & '
      r'\zone{RESTRICTED} & Simulation flags this section for review.\\')
    w(r'\dotG & \textbf{No problem found} in this inspection. & '
      r'\zone{KEEP OUT} & Highest priority simulation flag.\\')
    w(r' & & \zone{NOT CHECKED} & The robot did not measure here: treat as unknown.\\')
    w(r'\end{tabularx}')
    w(r'\par\vspace{4pt}{\small\color{muted} Radiation is given in microsieverts per hour (\textmu Sv/h). '
      r'Simulation flags start above 7.5 and escalate above 100\,\textmu Sv/h.}')

    # ---------- areas
    w(r'\clearpage\section{Aisle survey results}')
    w(r'The robot measured radiation as it walked. Each aisle is split into 2-metre sections, and each section is given '
      r'a simulation rating. Site staff must assess access separately.')
    w(r'\begin{figure}[H]\centering\includegraphics[width=\textwidth]{map.pdf}'
      r'\caption{Plan of the store. Coloured bands are the aisle sections; circles are drums.}\end{figure}')
    w(r'\begin{longtable}{@{}p{0.32\textwidth} l l p{0.38\textwidth}@{}}\toprule')
    w(r'Where & Section & Rating & Why\\\midrule\endhead')
    for z in sorted(zs, key=lambda z: (['KEEP OUT', 'RESTRICTED', 'LOW GAMMA', 'NOT CHECKED'].index(z['zone']), z['aisle'], z['lo'])):
        w(rf'{tex(z["name"])} & {z["part"]} & \zone{{{z["zone"]}}} & {tex(z["reason"])}\\')
    w(r'\bottomrule\end{longtable}')
    w(r'{\small\color{muted} Sections are measured along the aisle from the end nearest drum 1. '
      + ('Hydrogen gas was not measured in this inspection.' if not has['h2'] else '') + '}')

    # ---------- register
    w(r'\clearpage\section{Every drum at a glance}')
    w(r'All drums in this inspection, most urgent first.')
    w(r'\begin{longtable}{@{}l l l l l l l@{}}\toprule')
    w(r'Drum & Waste & Where & Result & What was seen & How sure & Radiation\\\midrule\endhead')
    for d in reg:
        c = colours[d['drum_id']][0]
        w(rf'\textbf{{{d["drum_id"]}}} & {WASTE.get(d.get("category"), tex(d.get("category")))} & {where(d)} & '
          rf'\result{{{c}}} & {finding(d)} & {certainty(d["confidence"])} & {tex(radiation(d.get("dose_rate_at_drum_uSv_h")))}\\')
    w(r'\bottomrule\end{longtable}')
    notes = ['"How sure" is how confident the camera software was about the damage it saw.']
    notes.append('This is the first inspection of these drums, so there is nothing to compare with yet.' if not prev else
                 'Changes since the last inspection are listed in each finding.')
    if measured_none:
        notes.append('Not measured in this inspection: ' + ', '.join(measured_none) + '.')
    if all(str(d.get('label_readable')) == 'unreadable' for d in drums):
        notes.append('The robot could not read the drum labels, so drums were identified by their position in the store.')
    w(r'{\small\color{muted} ' + ' '.join(tex(x) for x in notes).replace('"How sure"', "``How sure''") + '}')

    # ---------- findings
    w(r'\clearpage\section{Drums that need attention}')
    for d in reg:
        c, why = colours[d['drum_id']]
        if c == 'GREEN':
            continue
        w(r'\begin{finding}')
        w(rf'{{\large\bfseries Drum {d["drum_id"]}}}\hfill\result{{{c}}}\par')
        w(rf'{{\color{{muted}} {WASTE.get(d.get("category"), "")} waste \textbar\ {where(d)}}}\par\vspace{{6pt}}')
        ph = photo.get(d['drum_id'])
        if ph:
            w(rf'\includegraphics[width=\linewidth]{{{ph[0]}}}\par')
            w(rf'{{\small\color{{muted}} Photo taken {clock(ph[1])} into the inspection. The ring on the floor marks drum {d["drum_id"]}.}}\par\vspace{{6pt}}')
        else:
            w(r'{\small\color{muted} No photo was saved for this drum.}\par\vspace{6pt}')
        w(r'\begin{tabularx}{\linewidth}{@{}>{\leavevmode\color{muted}}p{0.22\linewidth} X@{}}')
        w(rf'What was seen & {finding(d)}\\')
        w(rf'How sure & {certainty(d["confidence"])}\\')
        reason = '; '.join(why)
        w(rf'Why this rating & {tex(reason[:1].upper() + reason[1:])}.\\')
        w(rf'Radiation at drum & {tex(radiation(d.get("dose_rate_at_drum_uSv_h")))}\\')
        sw = d.get('swab')
        if sw:
            over = sw.get('alpha', 0) > SWAB_ALPHA or sw.get('beta_gamma', 0) > SWAB_BG
            swtxt = 'Taken; contamination ' + ('above' if over else 'below') + ' the limit'
        else:
            swtxt = 'Taken, but the result was not recorded' if 'swab' in (d.get('team_checks_done') or []) else 'Not taken'
        w(rf'Surface wipe (swab) & {swtxt}\\')
        hr = d.get('heat_rise_c')
        w('Surface temperature & ' + ('Not measured' if hr is None else f'{hr:+.1f}' + r'\,\textdegree C compared with the air') + r'\\')
        if d['drum_id'] in prev:
            w(rf'Last inspection & {tex(prev[d["drum_id"]])}\\')
        cos = d.get('cosmos')
        if cos and c == 'RED':
            w(r'Explanation & \textit{' + tex(cos) + r'}\\')
        w(r'\end{tabularx}\par\vspace{6pt}')
        w(rf'\action{{{tex(action_for(d, c))}}}')
        w(r'\end{finding}')

    # ---------- not checked / events
    w(r'\section{What was not checked}')
    ns = [z for z in zs if z['zone'] == 'NOT CHECKED']
    ci = [d for d in drums if d['status'] == "Couldn't inspect"]
    if not ns and not ci:
        w(r'Every drum and every aisle section in this inspection was checked.')
    else:
        w(r'\begin{itemize}[leftmargin=*,itemsep=2pt]')
        for d in ci:
            w(rf'\item Drum {d["drum_id"]} ({where(d)}): the robot could not get a clear look. Inspect again once the cause is cleared.')
        by = defaultdict(list)
        for z in ns:
            by[z['name']].append(z['part'])
        for name, ps in by.items():
            w(rf'\item {tex(name)}, sections {", ".join(ps)}: the robot did not walk here this time, so these are unknown.')
        w(r'\end{itemize}')
    if measured_none:
        w(r'Not measured anywhere in this inspection: ' + tex(', '.join(measured_none)) + '.')
    if spike:
        w(rf'\paragraph{{Radiation event}} {clock(spike["t0"])} into the inspection, radiation in the aisle rose from about '
          rf'{spike["base"]:.0f} to {spike["peak"]:.0f}\,\textmu Sv/h. The robot stepped back to a safer spot, waited for it to '
          rf'settle, and returned {clock(spike.get("returned"))} into the inspection to finish the drums it had skipped.')

    # ---------- accuracy
    if sc:
        w(r'\section{How accurate was the robot?}')
        w(r'This was a practice run in a simulated store, so we know which drums were really damaged. '
          r'The robot was not told; the comparison is made only for this report.')
        lines = [f'It found {sc["found"]} of the {sc["faulty"]} damaged drums.']
        if sc['missed']:
            lines.append(f'It missed {", ".join(sc["missed"])}.')
        if sc['false']:
            lines.append(f'It also raised {plural(len(sc["false"]), "false alarm")}: '
                         f'{", ".join(sc["false"])} {"was" if len(sc["false"]) == 1 else "were"} actually undamaged.')
        if sc['cant']:
            lines.append(f'It could not inspect {", ".join(sc["cant"])}.')
        w(r'\begin{itemize}[leftmargin=*,itemsep=2pt]' + ''.join(rf'\item {tex(x)}' for x in lines) + r'\end{itemize}')
        w(r'A false alarm costs a person an extra check. A missed drum is the more serious error.')

    # ---------- how made
    w(r'\section{How this report was made}')
    w(r'The robot walks the aisles with a camera and a radiation meter. Software trained to recognise rust and '
      r'bulging (swelling) on drums points out possible damage in the camera images. When it is unsure, the robot goes '
      r'back for a closer look from another angle. Fixed safety rules, the same every time, then decide each rating in '
      r'this report. An AI assistant may add a short written explanation for drums that need action, but it cannot '
      r'change any rating or number. Everything in this report comes from what the robot recorded during the inspection.')
    w(r'\par\vspace{4pt}{\bfseries Limits used}\par')
    w(r'\begin{tabularx}{\textwidth}{@{}l l X@{}}\toprule What & Level & Source\\\midrule')
    w(r'Restricted area & above 7.5\,\textmu Sv/h & HSE, \textit{Work with ionising radiation} (L121), regulation 17. Used here as an on-the-spot reading.\\')
    w(r'Keep out & above 100\,\textmu Sv/h & HSE, L121 guidance on high instantaneous dose rates.\\')
    w(r'Surface wipe & above 0.4 / 4\,Bq/cm$^2$ & IAEA, \textit{Regulations for the Safe Transport of Radioactive Material} (SSR-6), para.~508.\\')
    w(r'Warm drum & 5\,\textdegree C above the air & Our own rule for this project; not an official limit.\\')
    w(r'Hydrogen gas & no level set yet & We have not yet found an official alarm level to cite, so hydrogen does not change any rating.\\\bottomrule')
    w(r'\end{tabularx}')
    w(r'\paragraph{Please note} This inspection took place in a computer-simulated store, not a real one. '
      r'Radiation values come from a simplified model. The damage-spotting software was trained on computer-generated '
      r'images. How far rust has spread is estimated from photos, not measured. Only a surface wipe can show '
      r'contamination. The format follows the themes of the Nuclear Decommissioning Authority\textquotesingle s '
      r'\textit{Guidance on Monitoring of Waste Packages During Storage} (WPS/640).')

    # ---------- appendices
    w(r'\clearpage\appendix\section{Radiation during the inspection}')
    w(r'\begin{figure}[H]\centering\includegraphics[width=\textwidth]{traces.pdf}'
      r'\caption{Top: radiation measured by the robot as it walked (dashed lines are the restricted and keep-out levels). '
      r'Bottom: the total dose the robot received, against its limit. The shaded band is the radiation event.}\end{figure}')

    w(r'\section{Step-by-step record}')
    w(r'What the robot did and why, in order. Times are minutes:seconds into the inspection.')
    in_round = set(colours)
    elsewhere = set()
    w(r'\begin{longtable}{@{}l l p{0.74\textwidth}@{}}\toprule Time & Drum & What happened\\\midrule\endhead')
    for x in decisions:
        drum, line = plain_step(x)
        if drum and re.match(r'^[A-Z]\d+$', drum) and drum not in in_round:
            elsewhere.add(drum)
            continue
        w(rf'{clock(x["t"])} & {tex(drum)} & {tex(line)}\\')
    w(r'\bottomrule\end{longtable}')
    if elsewhere:
        w(r'{\small\color{muted} The robot also looked at drums ' + ', '.join(sorted(elsewhere)) +
          r' on its way. They are outside this inspection and not reported here.}')

    w(r'\section{Technical details}')
    w(r'{\small\color{muted} For engineers and auditors.}\par')
    w(r'\begin{tabularx}{\textwidth}{@{}>{\color{muted}}l X@{}}')
    w(rf'Run ID & \texttt{{{tex(run_id)}}}\\')
    w(rf'Software version & \texttt{{{tex(a.commit)}}}\\')
    w(rf'Damage detector run & {tex(mem.get("detector_run_id") or "not recorded")}\\')
    w(rf'Explanation model & {tex(mem.get("cosmos_model") or "not recorded")}\\')
    if any('HTTPError' in (x.get('source') or '') for x in decisions):
        w(r'Note & The explanation service was unavailable during this run, so the fixed rules made every decision.\\')
    w(r'Simulator & NVIDIA Isaac Sim\\')
    w(r'Status names & Action needed = \texttt{Confirmed defect}; Check again = \texttt{Suspect}; '
      r'No problem found = \texttt{OK}; Not inspected = \texttt{Couldn\textquotesingle t inspect}\\')
    w(r'\end{tabularx}')

    doc = (HERE / 'template.tex').read_text().replace('%%RUNID%%', tex(run_id)).replace('%%BODY%%', '\n'.join(C))
    (out / 'report.tex').write_text(doc)
    for _ in range(2):
        r = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 'report.tex'],
                           cwd=out, capture_output=True, text=True, errors='replace')
        if r.returncode:
            print(r.stdout[-3000:]); raise SystemExit('pdflatex failed')
    pdf = out / f'CANIS_report_{run_id}.pdf'
    shutil.move(out / 'report.pdf', pdf)
    print(pdf)


if __name__ == '__main__':
    main()
