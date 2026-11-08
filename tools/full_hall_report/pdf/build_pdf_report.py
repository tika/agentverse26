"""C.A.N.I.S. post-run inspection report (PDF, typeset with LaTeX).

    python build_pdf_report.py <run_dir> [--drums sim/drums.json] [--previous old/memory.json]
                               [--commit <hash>] [--out <dir>] [--logo assets/logo.png]

Reads ONLY the run's logged files (memory.json, telemetry.jsonl, decisions.jsonl, detections.jsonl,
ground_truth.json, route.json, stills/) plus the store inventory, writes report.tex, figures and
CANIS_report_<RUN_ID>.pdf. Anything the run did not log is printed as "not measured" / "not logged".
No language model writes any fact in this report. Cosmos text is used only if the run logged it.
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
from matplotlib.patches import Rectangle, Circle  # noqa: E402

HERE = Path(__file__).resolve().parent

# ---- criteria (sources printed in the report's Method section) ----------------------------------
GAMMA_RESTRICT = 7.5      # uSv/h, HSE L121 reg. 17 paras 297-298 (controlled-area level)
GAMMA_KEEPOUT = 100.0     # uSv/h, HSE L121 (instantaneous readings above 100 uSv/h)
SWAB_ALPHA, SWAB_BG = 0.4, 4.0  # Bq/cm2, IAEA SSR-6 Rev. 2 para 508
HEAT_RISE = 5.0           # degC above air, team demo rule (two-cue pressure screen)
H2_WARN = H2_ALARM = None  # no cited level yet: H2 is reported but does not change any zone
SECTION_M = 2.0
DETECTOR_RUN = 'yolo26s_20261107T225757Z_d625ef'

INK, ACCENT = '#1A1A18', '#F2C744'
COL = {'RED': '#B3261E', 'AMBER': '#C98A00', 'GREEN': '#2E7D32', 'GREY': '#8A8A85'}
ZONE_COL = {'KEEP OUT': COL['RED'], 'RESTRICTED': COL['AMBER'], 'SAFE': COL['GREEN'],
            'NOT SURVEYED': COL['GREY']}


def jl(p):
    p = Path(p)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def tex(s):
    s = '' if s is None else str(s)
    rep = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
           '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    s = ''.join(rep.get(c, c) for c in s)
    return s.replace('->', r'$\rightarrow$').replace('µ', r'\textmu{}')


def hms(t):
    t = int(round(t or 0))
    return f'{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}'


def fmt(v, nd=1, unit=''):
    if v is None:
        return r'\textit{n/m}'
    return f'{v:.{nd}f}{unit}'


def norm_decision(x):
    """Decision lines come in two shapes: rule banners and planner (Cosmos-or-rules) choices."""
    x = dict(x)
    if 'text' not in x:
        act = x.get('action_id', '')
        x['text'] = f"{act.replace('_', ' ')}: {x.get('reason', '')}"
        x.setdefault('drum', act.rsplit('_', 1)[-1] if '_' in act else '')
    src = x.get('source', '')
    x['source'] = 'Rules (Cosmos unavailable)' if 'HTTPError' in src or 'rules (' in src else src
    return x


# ---- rules ----------------------------------------------------------------------------------------
def drum_colour(d):
    """Deterministic drum colour from the logged status and sensor values."""
    why = []
    swab = d.get('swab')  # {"alpha": .., "beta_gamma": ..} if logged
    heat = d.get('heat_rise_c')
    dose = d.get('dose_rate_at_drum_uSv_h')
    red = d['status'] == 'Confirmed defect'
    if red:
        why.append('confirmed ' + d.get('finding', 'defect'))
    if swab and (swab.get('alpha', 0) > SWAB_ALPHA or swab.get('beta_gamma', 0) > SWAB_BG):
        red = True; why.append('swab above limit')
    if heat is not None and heat >= HEAT_RISE and 'bulge' in d.get('finding', ''):
        red = True; why.append('bulge with heat')
    if dose is not None and dose > GAMMA_KEEPOUT:
        red = True; why.append(f'dose {dose:.0f} µSv/h')
    if red:
        return 'RED', why
    amber = d['status'] in ('Suspect', "Couldn't inspect")
    if amber:
        why.append(d['status'].lower())
    if heat is not None and heat >= HEAT_RISE:
        amber = True; why.append('heat anomaly')
    return ('AMBER' if amber else 'GREEN'), why


def action_for(d, colour):
    f, s = d.get('finding', ''), d['status']
    if s == "Couldn't inspect":
        return 'Re-inspect when the cause is cleared (dose normal / aisle clear).'
    if s == 'Suspect':
        return 'Re-inspect within 7 days: closer look and swab.'
    if 'bulge' in f:
        if d.get('heat_rise_c') is None:
            return ('Restrict access; arrange an engineering assessment for pressurisation; '
                    'measure surface temperature (not measured this run).')
        if d['heat_rise_c'] >= HEAT_RISE:
            return 'Keep out of section; isolate drum; engineering assessment for pressurisation.'
        return 'Restrict access; engineering assessment; re-inspect at next round.'
    if 'corrosion' in f:
        return 'Engineering assessment of container integrity; swab if not taken; consider overpacking.'
    if colour == 'AMBER':
        return 'Re-measure at next round.'
    return 'No action. Routine inspection.'


def zones(tele, drums, colours):
    """2 m sections along each aisle; worst logged value decides the zone."""
    aisles = sorted({round(t['aisle_y'], 2) for t in tele if t.get('aisle_y') is not None})
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
            if not ts:
                out.append(dict(aisle=a, lo=lo, hi=hi, zone='NOT SURVEYED', reason='no readings logged',
                                gmax=None, tmax=None, drums=near))
                continue
            top = max(ts, key=lambda t: t['dose_rate_uSv_h'])
            g = top['dose_rate_uSv_h']
            h2 = [t['hydrogen_ppm'] for t in ts if 'hydrogen_ppm' in t]
            zone, reason = 'SAFE', f'max gamma {g:.1f} µSv/h'
            reds = [d['drum_id'] for d in near if colours[d['drum_id']][0] == 'RED']
            if g > GAMMA_KEEPOUT:
                zone, reason = 'KEEP OUT', f'gamma {g:.1f} µSv/h at {hms(top["t"])}'
            elif any(d.get('heat_rise_c') is not None and d['heat_rise_c'] >= HEAT_RISE
                     and 'bulge' in d.get('finding', '') for d in near):
                zone, reason = 'KEEP OUT', 'bulged drum with heat'
            elif g > GAMMA_RESTRICT:
                zone, reason = 'RESTRICTED', f'gamma {g:.1f} µSv/h at {hms(top["t"])}'
            elif reds:
                zone, reason = 'RESTRICTED', 'defective drum ' + ', '.join(reds)
            out.append(dict(aisle=a, lo=lo, hi=hi, zone=zone, reason=reason, gmax=g,
                            h2max=max(h2) if h2 else None, tmax=top['t'], drums=near))
    return out


# ---- figures --------------------------------------------------------------------------------------
def setup_mpl():
    try:
        plt.rcParams.update({'text.usetex': True, 'font.family': 'serif',
                             'text.latex.preamble': r'\usepackage{lmodern}'})
        fig = plt.figure(); fig.text(0.5, 0.5, r'test $\mu$'); fig.savefig('/dev/null', format='pdf'); plt.close(fig)
    except Exception:
        plt.rcParams.update({'text.usetex': False, 'font.family': 'serif', 'mathtext.fontset': 'cm',
                             'font.serif': ['CMU Serif', 'DejaVu Serif']})
    plt.rcParams.update({'font.size': 8.5, 'axes.linewidth': 0.6, 'axes.edgecolor': INK,
                         'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'axes.labelcolor': INK})


def lbl(s):
    return s.replace('µ', r'$\mu$') if plt.rcParams['text.usetex'] else s.replace('µ', 'μ')


def fig_map(path, inventory, drums, colours, zs, trail, spike):
    fig, ax = plt.subplots(figsize=(6.3, 3.0))
    for z in zs:
        c = ZONE_COL[z['zone']]
        ax.add_patch(Rectangle((z['lo'], z['aisle'] - 0.55), z['hi'] - z['lo'], 1.1, facecolor=c,
                               alpha=0.18 if z['zone'] != 'NOT SURVEYED' else 0.08, edgecolor=c, lw=0.5,
                               hatch='////' if z['zone'] == 'NOT SURVEYED' else None))
    ids = {d['drum_id'] for d in drums}
    for d in inventory:
        if d['label'] not in ids:
            ax.add_patch(Circle((d['x'], d['y']), 0.3, facecolor='white', edgecolor='#BBBBB5', lw=0.6))
    for d in drums:
        c = COL[colours[d['drum_id']][0]]
        ax.add_patch(Circle((d['x'], d['y']), 0.3, facecolor=c, edgecolor=INK, lw=0.6))
        ax.text(d['x'], d['y'] - 0.55, d['drum_id'], ha='center', va='top', fontsize=7)
    if trail:
        ax.plot([p[0] for p in trail], [p[1] for p in trail], color=INK, lw=0.9, label='robot route')
        ax.plot(*trail[0][:2], marker='o', ms=4, color=INK)
    if spike and spike.get('at'):
        ax.plot(*spike['at'][:2], marker='x', ms=7, mew=1.6, color=COL['RED'], label='dose back-off')
    ax.set_aspect('equal')
    ax.set_xlabel('x (m)'); ax.set_ylabel('y (m)')
    xs = [d['x'] for d in inventory]; ys = [d['y'] for d in inventory]
    ax.set_xlim(min(xs) - 1.5, max(xs) + 1.5); ax.set_ylim(min(ys) - 1.2, max(ys) + 1.2)
    from matplotlib.lines import Line2D
    h = [Rectangle((0, 0), 1, 1, facecolor=ZONE_COL[k], alpha=0.35) for k in ZONE_COL]
    h += [Line2D([], [], marker='o', ls='', mfc=COL[k], mec=INK) for k in ('RED', 'AMBER', 'GREEN')]
    h += [Line2D([], [], marker='o', ls='', mfc='white', mec='#BBBBB5'), Line2D([], [], color=INK)]
    names = ['keep out', 'restricted', 'safe', 'not surveyed', 'drum: red', 'drum: amber', 'drum: green',
             'not in this round', 'route']
    ax.legend(h, names, fontsize=6.5, ncol=1, loc='center left', bbox_to_anchor=(1.01, 0.5), frameon=False)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def fig_traces(path, tele, budget, spike, has):
    t = [x['t'] for x in tele]
    rows = 2 + int(has['temp']) + int(has['h2'])
    fig, axs = plt.subplots(rows, 1, figsize=(6.3, 1.55 * rows), sharex=True)
    ax = axs[0]
    ax.plot(t, [x['dose_rate_uSv_h'] for x in tele], color=INK, lw=0.8)
    for v, ls in ((GAMMA_RESTRICT, '--'), (GAMMA_KEEPOUT, ':')):
        ax.axhline(v, color=COL['AMBER'] if v == GAMMA_RESTRICT else COL['RED'], lw=0.7, ls=ls)
    ax.set_ylabel(lbl('gamma (µSv/h)')); ax.set_yscale('log')
    ax = axs[1]
    ax.plot(t, [x['dose_uSv'] for x in tele], color=INK, lw=0.8)
    ax.axhline(budget, color=COL['RED'], lw=0.7, ls='--')
    ax.set_ylabel(lbl('robot dose (µSv)'))
    i = 2
    if has['temp']:
        axs[i].plot(t, [x.get('temperature_c') for x in tele], color=INK, lw=0.8)
        axs[i].set_ylabel(lbl('air temp (°C)')); i += 1
    if has['h2']:
        axs[i].plot(t, [x.get('hydrogen_ppm') for x in tele], color=INK, lw=0.8)
        axs[i].set_ylabel('H$_2$ (ppm)')
    for a in axs:
        if spike:
            a.axvspan(spike['t0'], spike.get('returned', spike['t0']), color=COL['RED'], alpha=0.08, lw=0)
        for s in ('top', 'right'):
            a.spines[s].set_visible(False)
    axs[-1].set_xlabel('mission time (s)')
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


# ---- main -----------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir'); ap.add_argument('--drums', default=None)
    ap.add_argument('--previous'); ap.add_argument('--commit', default='not recorded')
    ap.add_argument('--out', default=None, help='default: <run_dir>/report'); ap.add_argument('--logo', default=str(HERE / 'assets/logo.png'))
    ap.add_argument('--store', default='Drum Store 1 (simulated)')
    a = ap.parse_args()
    run = Path(a.run_dir); out = Path(a.out) if a.out else run / 'report'; out.mkdir(parents=True, exist_ok=True)
    run_id = run.name
    mem = json.loads((run / 'memory.json').read_text())
    tele = jl(run / 'telemetry.jsonl')
    decisions = [norm_decision(x) for x in jl(run / 'decisions.jsonl')]
    gt = json.loads((run / 'ground_truth.json').read_text()) if (run / 'ground_truth.json').exists() else None
    route = json.loads((run / 'route.json').read_text()) if (run / 'route.json').exists() else {}
    inv_path = Path(a.drums) if a.drums else run.parents[2] / 'sim/drums.json'
    drums = sorted(mem['drums'], key=lambda d: d['drum_id'])
    inventory = []
    if inv_path.exists():
        raw = json.loads(inv_path.read_text())
        names = {d.get('internal_id'): d['drum_id'] for d in mem['drums']}
        for d in raw:
            inventory.append(dict(label=names.get(d['id'], d['id']), x=d['x'], y=d['y']))
    if not inventory:
        inventory = [dict(label=d['drum_id'], x=d['x'], y=d['y']) for d in drums]
    prev = {}
    if a.previous and Path(a.previous).exists():
        prev = {d['drum_id']: d['status'] for d in json.loads(Path(a.previous).read_text())['drums']}
    has = {'temp': any('temperature_c' in t for t in tele), 'h2': any('hydrogen_ppm' in t for t in tele)}

    colours = {d['drum_id']: drum_colour(d) for d in drums}
    zs = zones(tele, drums, colours)
    spike = mem.get('spike')

    setup_mpl()
    fig_map(out / 'map.pdf', inventory, drums, colours, zs, route.get('trail', []), spike)
    fig_traces(out / 'traces.pdf', tele, mem.get('budget_uSv', 0), spike, has)
    shutil.copy(a.logo, out / 'logo.png')
    stills_dir = out / 'stills'; stills_dir.mkdir(exist_ok=True)
    best_still = {}
    for s in mem.get('stills', []):
        src = run / s['file']
        if src.exists() and s['drum'] in colours:
            dst = stills_dir / src.name; shutil.copy(src, dst)
            if s['kind'] == 'confirmed' or s['drum'] not in best_still:
                best_still[s['drum']] = (f'stills/{src.name}', s['t'], s['kind'])

    order = {'RED': 0, 'AMBER': 1, 'GREEN': 2}
    reg = sorted(drums, key=lambda d: (order[colours[d['drum_id']][0]], d['drum_id']))
    n = {k: sum(1 for c in colours.values() if c[0] == k) for k in order}
    zc = defaultdict(int)
    for z in zs:
        zc[z['zone']] += 1
    worst = [z for z in zs if z['zone'] == 'KEEP OUT'] or [z for z in zs if z['zone'] == 'RESTRICTED']
    expected = mem.get('expected_drums', len(drums))
    inspected = sum(1 for d in drums if d['status'] != "Couldn't inspect")
    dose, budget = mem.get('dose_uSv', 0), mem.get('budget_uSv', 0)

    # ---- self-check
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

    C = []  # LaTeX body
    w = C.append
    started = mem.get('started_utc', '')
    date = started.split(' ')[0] if started else 'not recorded'
    verdict = (f"{n['RED']} drum{'s' if n['RED'] != 1 else ''} need{'s' if n['RED'] == 1 else ''} action; "
               f"{n['AMBER']} need{'s' if n['AMBER'] == 1 else ''} re-inspection. ")
    if worst:
        z = worst[0]
        verdict += (f"{len(worst)} aisle section{'s' if len(worst) != 1 else ''} "
                    f"{'KEEP OUT' if z['zone'] == 'KEEP OUT' else 'RESTRICTED'} for personnel.")
    else:
        verdict += 'No access restrictions from this round.'

    # Title block
    w(r'\thispagestyle{first}')
    w(r'\begin{minipage}[c]{0.16\textwidth}\includegraphics[width=\linewidth]{logo.png}\end{minipage}\hfill')
    w(r'\begin{minipage}[c]{0.80\textwidth}\raggedleft')
    w(r'{\large\scshape C.A.N.I.S.}\\[-1pt]{\footnotesize Corrosion And Nuclear Inspection System}\\[8pt]')
    w(r'{\LARGE\bfseries Store Inspection Report}\\[3pt]')
    w(rf'{{\normalsize Report CANIS-{tex(run_id)} \quad\textperiodcentered\quad {tex(date)}}}')
    w(r'\end{minipage}\par\vspace{6pt}{\color{accent}\rule{\textwidth}{2.2pt}}\par\vspace{10pt}')

    # Document control
    w(r'\noindent\begin{tabularx}{\textwidth}{@{}>{\scshape}l X >{\scshape}l X@{}}\toprule')
    w(rf'facility & {tex(a.store)} & run id & \texttt{{{tex(run_id)}}}\\')
    w(rf'started & {tex(started or "not recorded")} & duration & {hms(mem.get("duration_s"))}\\')
    w(rf'inspector & C.A.N.I.S.\ (autonomous quadruped) & software & \texttt{{{tex(a.commit)}}}\\')
    w(rf'detector & \multicolumn{{3}}{{l}}{{YOLO26s, run \texttt{{{tex(DETECTOR_RUN)}}}, cut-off 0.25}}\\')
    w(r'reasoning & \multicolumn{3}{l}{Cosmos Reason 2B (context for red drums only)}\\')
    w(r'status & \multicolumn{3}{l}{Simulated store (NVIDIA Isaac Sim). Not for operational use.}\\\bottomrule')
    w(r'\end{tabularx}\par\vspace{12pt}')

    # Summary
    w(r'\begin{summarybox}')
    w(r'\begin{tabularx}{\linewidth}{@{}X r X r@{}}')
    w(rf'Drums inspected & \textbf{{{inspected} / {expected}}} & Drums needing a person & \textbf{{{n["RED"] + n["AMBER"]}}}\\')
    w(rf'\tagR{{Red}} action required & \textbf{{{n["RED"]}}} & Areas keep out & \textbf{{{zc["KEEP OUT"]}}}\\')
    w(rf'\tagA{{Amber}} re-inspect & \textbf{{{n["AMBER"]}}} & Areas restricted & \textbf{{{zc["RESTRICTED"]}}}\\')
    w(rf'\tagG{{Green}} no action & \textbf{{{n["GREEN"]}}} & Areas not surveyed & \textbf{{{zc["NOT SURVEYED"]}}}\\')
    pct = 100 * dose / budget if budget else 0
    w(rf'Robot dose & \textbf{{{dose:.2f} / {budget:.2f}\,\textmu Sv}} & Mission time & \textbf{{{hms(mem.get("duration_s"))}}}\\')
    w(r'\end{tabularx}\par\vspace{4pt}')
    w(rf'\dosebar{{{min(pct, 100):.1f}}}{{{pct:.0f}\% of dose budget}}\par\vspace{{6pt}}')
    w(rf'\textbf{{Verdict.}} {tex(verdict)}')
    w(r'\end{summarybox}')

    # 1 Safety verdict per area
    w(r'\section{Access verdict by area}')
    w(r'Each aisle is divided into 2\,m sections. A section is \zone{SAFE} only if the robot logged readings there '
      r'and none of the criteria in Section~\ref{sec:method} were met. Sections without readings are '
      r'\zone{NOT SURVEYED}, never safe.')
    w(r'\begin{figure}[H]\centering\includegraphics[width=\textwidth]{map.pdf}'
      r'\caption{Store plan with access zones, drum status and the robot\textquotesingle s route.}\end{figure}')
    w(r'\begin{longtable}{@{}l l l l r l@{}}\toprule')
    w(r'Aisle & Section & Zone & Basis & Max $\gamma$ (\textmu Sv/h) & H$_2$ (ppm)\\\midrule\endhead')
    for z in zs:
        w(rf'y\,=\,{z["aisle"]:g} & {z["lo"]:g}--{z["hi"]:g}\,m & \zone{{{z["zone"]}}} & {tex(z["reason"])} & '
          rf'{fmt(z["gmax"])} & {fmt(z.get("h2max"), 0)}\\')
    w(r'\bottomrule\end{longtable}')

    # 2 Register
    w(r'\section{Drum register}')
    w(r'All drums in this round, worst first. Status is set by deterministic rules from the detector and sensor '
      r'logs; no language model sets any value in this table.')
    w(r'\begin{longtable}{@{}l l l l l r r r l l@{}}\toprule')
    w(r'Drum & Cat. & Loc. & Status & Finding & Conf. & Looks & $\gamma$ & Heat & Change\\'
      r'& & & & & & & {\scriptsize\textmu Sv/h} & {\scriptsize$\Delta$\textdegree C} & \\\midrule\endhead')
    for d in reg:
        c = colours[d['drum_id']][0]
        ch = f"{prev[d['drum_id']]} -> {d['status']}" if d['drum_id'] in prev else 'Baseline'
        fnd = d.get('finding') or 'none'
        w(rf'\textbf{{{d["drum_id"]}}} & {d.get("category", "")} & {d["row"]}, x={d["x"]:g} & '
          rf'\status{{{c}}}{{{tex(d["status"])}}} & {tex(fnd)} & '
          rf'{d["confidence"]:.2f} & {d.get("looks", "")} & {fmt(d.get("dose_rate_at_drum_uSv_h"))} & '
          rf'{fmt(d.get("heat_rise_c"))} & {tex(ch)}\\')
    w(r'\bottomrule\end{longtable}')
    w(r'{\footnotesize \textit{n/m}: not measured in this run. Conf.: highest YOLO confidence for the fault class. '
      r'Label legibility: ' + tex(', '.join(sorted({str(d.get("label_readable")) for d in drums}))) +
      r' for all drums (camera only).}')

    # 3 Findings
    w(r'\clearpage\section{Findings and recommended actions}')
    for d in reg:
        c, why = colours[d['drum_id']]
        if c == 'GREEN':
            continue
        w(r'\begin{finding}{' + rf'\status{{{c}}}{{{c}}}\quad Drum {d["drum_id"]} \textperiodcentered\ '
          rf'{tex(d.get("category", ""))} \textperiodcentered\ row {d["row"]}, x\,=\,{d["x"]:g}\,m' + '}')
        st = best_still.get(d['drum_id'])
        w(r'\begin{minipage}[t]{0.47\linewidth}\vspace{0pt}')
        if st:
            w(rf'\includegraphics[width=\linewidth]{{{st[0]}}}\par{{\scriptsize Evidence frame at '
              rf'{hms(st[1])} ({tex(st[2].replace("_", " "))}); YOLO boxes as drawn by the detector.}}')
        else:
            w(r'{\footnotesize No evidence frame logged for this drum.}')
        w(r'\end{minipage}\hfill\begin{minipage}[t]{0.49\linewidth}\vspace{0pt}\small')
        fv = d.get('fault_views') or {}
        w(r'\begin{tabular}{@{}>{\scshape}l l@{}}')
        w(rf'finding & {tex(d.get("finding") or "none")}\\')
        w(rf'confidence & {d["confidence"]:.2f} (cut-off 0.25)\\')
        w(rf'views & {tex(", ".join(f"{k} {v}" for k, v in fv.items()) or "--")} of {d.get("views", "--")} frames\\')
        w(rf'looks & {d.get("looks", "--")}\\')
        w(rf'gamma & {fmt(d.get("dose_rate_at_drum_uSv_h"))} \textmu Sv/h\\')
        sw = d.get('swab')
        swtxt = (f"α {sw['alpha']} / βγ {sw['beta_gamma']} Bq/cm²" if sw else
                 ('taken, result not logged' if 'swab' in (d.get('team_checks_done') or []) else 'not taken'))
        w(rf'swab & {tex(swtxt).replace("α", "$\\alpha$").replace("βγ", "$\\beta\\gamma$").replace("²", "$^2$")}\\')
        hr = d.get('heat_rise_c')
        w('heat & ' + ('not measured' if hr is None else f'+{hr:.1f}' + r'\,\textdegree C') + r'\\')
        w(r'\end{tabular}\par\medskip')
        w(rf'\textbf{{Basis.}} {tex(d.get("reason", ""))}; {tex(", ".join(why))}.\par\smallskip')
        trail = [x for x in decisions if x.get('drum') == d['drum_id']]
        if trail:
            w(r'\textbf{Decision trail.}\par{\footnotesize')
            for x in trail[:6]:
                w(rf'\texttt{{{hms(x["t"])}}} {tex(x["text"])}\\')
            w(r'}')
        cos = d.get('cosmos')
        w(r'\smallskip\textbf{Context (Cosmos Reason).} ' + (r'\textit{``' + tex(cos) + "''}" if cos and c == 'RED'
          else r'\textit{Not logged in this run.}'))
        w(r'\end{minipage}\par\medskip')
        w(rf'\action{{{tex(action_for(d, c))}}}')
        w(r'\end{finding}')

    # 4 Not inspected
    w(r'\section{Not inspected}')
    ns = [z for z in zs if z['zone'] == 'NOT SURVEYED']
    ci = [d for d in drums if d['status'] == "Couldn't inspect"]
    if not ns and not ci:
        w(r'Every drum in the round was inspected and every aisle section was surveyed.')
    else:
        w(r'\begin{itemize}[leftmargin=*,itemsep=1pt]')
        for d in ci:
            w(rf'\item Drum {d["drum_id"]}: {tex(d.get("reason", ""))}. Re-inspect when the cause is cleared.')
        for z in ns:
            w(rf'\item Aisle y\,=\,{z["aisle"]:g}, {z["lo"]:g}--{z["hi"]:g}\,m: no readings logged. '
              r'Treat as unknown until surveyed.')
        w(r'\end{itemize}')
    if spike:
        w(rf'\paragraph{{Dose event.}} At {hms(spike["t0"])} the gamma rate rose to {spike["peak"]:.1f}\,\textmu Sv/h '
          rf'(baseline {spike["base"]:.1f}). The robot backed off at {hms(spike["backed_off"])}, waited until '
          rf'{hms(spike.get("calm_since"))} and returned at {hms(spike.get("returned"))}.')

    # 5 Self-check
    if sc:
        w(r'\section{Self-check against simulation ground truth}')
        w(r'The simulation records which drums were really faulty. This file is hidden from the robot and used only here.')
        w(r'\begin{center}\begin{tabular}{@{}l r l@{}}\toprule')
        w(rf'Faulty drums in the round & {sc["faulty"]} & \\')
        w(rf'Found (Confirmed or Suspect) & {sc["found"]} & \\')
        w(rf'Missed & {len(sc["missed"])} & {", ".join(sc["missed"]) or "--"}\\')
        w(rf'False alarms & {len(sc["false"])} & {", ".join(sc["false"]) or "--"}\\')
        w(rf'Could not inspect & {len(sc["cant"])} & {", ".join(sc["cant"]) or "--"}\\\bottomrule')
        w(r'\end{tabular}\end{center}')

    # 6 Method
    w(r'\section{Method, criteria and limits}\label{sec:method}')
    w(r'\begin{tabularx}{\textwidth}{@{}>{\bfseries}l X@{}}\toprule')
    w(r'YOLO26s & Draws boxes (\textit{drum}, \textit{corrosion}, \textit{bulge}) with a confidence. Cut-off 0.25. Decides nothing.\\')
    w(r'Rules & Deterministic code turns boxes and sensor readings into drum colours and area zones.\\')
    w(r'Cosmos Reason 2B & Explains the context of red drums only. Cannot change a status, zone or number; output is checked against the logged facts.\\')
    w(r'Report & Assembled from logged data only. Missing values are printed as \textit{n/m}.\\\bottomrule')
    w(r'\end{tabularx}\par\medskip')
    w(r'\begin{tabularx}{\textwidth}{@{}l l X@{}}\toprule Criterion & Value & Source\\\midrule')
    w(r'Restricted (gamma) & $>$7.5\,\textmu Sv/h & HSE L121 (IRR17 ACOP), reg.~17 paras 297--298; used as an instantaneous robot rule, not a controlled-area assessment.\\')
    w(r'Keep out (gamma) & $>$100\,\textmu Sv/h & HSE L121, guidance on instantaneous dose rates.\\')
    w(r'Swab & $>$0.4 / 4\,Bq/cm$^2$ & IAEA SSR-6 Rev.~2 (2025) para 508 ($\alpha$ / $\beta\gamma$ non-fixed contamination).\\')
    w(r'Heat & $\geq$5\,\textdegree C above air & Team demonstration rule; not an operational limit.\\')
    w(r'H$_2$ & not set & No cited alarm level. Readings are reported but do not change any zone.\\\bottomrule')
    w(r'\end{tabularx}\par\medskip')
    w(r'\textbf{Limits.} Simulated store; detector trained on synthetic images; dose from a simplified '
      r'inverse-square model in simulated units; rust extent estimated, not measured; surface contamination '
      r'requires a swab; label legibility from the camera only. Structure follows the themes of NDA WPS/640, '
      r'\textit{Guidance on Monitoring of Waste Packages During Storage}.')

    # Appendix
    w(r'\appendix\section{Sensor traces}')
    w(r'\begin{figure}[H]\centering\includegraphics[width=\textwidth]{traces.pdf}'
      r'\caption{Gamma dose rate (dashed: 7.5\,\textmu Sv/h; dotted: 100\,\textmu Sv/h), cumulative robot dose '
      r'(dashed: budget). Shaded: dose event. Air temperature and H$_2$ ' +
      ('shown.' if has['temp'] or has['h2'] else 'were not logged in this run.') + r'}\end{figure}')
    w(r'\section{Decision log}')
    w(r'\begin{longtable}{@{}l l p{0.2\textwidth} p{0.5\textwidth}@{}}\toprule Time & Drum & Decided by & Decision\\\midrule\endhead')
    for x in decisions:
        w(rf'\texttt{{{hms(x["t"])}}} & {tex(x.get("drum", ""))} & {tex(x.get("source", ""))} & {tex(x["text"])}\\')
    w(r'\bottomrule\end{longtable}')

    body = '\n'.join(C)
    doc = (HERE / 'template.tex').read_text().replace('%%RUNID%%', tex(run_id)).replace('%%BODY%%', body)
    (out / 'report.tex').write_text(doc)
    for _ in range(2):
        r = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 'report.tex'],
                           cwd=out, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-3000:]); raise SystemExit('pdflatex failed')
    pdf = out / f'CANIS_report_{run_id}.pdf'
    shutil.move(out / 'report.pdf', pdf)
    print(pdf)


if __name__ == '__main__':
    main()
