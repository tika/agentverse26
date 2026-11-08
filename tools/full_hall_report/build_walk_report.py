"""CANIS walkthrough report (PDF, typeset with LaTeX) for one warehouse-v3 walk with Cosmos.

    python3 tools/full_hall_report/build_walk_report.py <run_dir>/canis_wh_full_cosmos [--commit HASH] [--out DIR]

Reads only what the run wrote: memory.json, decisions.jsonl, telemetry.jsonl, stills/ and colour_accuracy.json
(from scripts/hot/full_hall/wh_score_color.py). Written for store managers and safety staff; technical details are last.
"""
import argparse
import json
import math
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'report_assets'
START_X = 1.0                 # distances along the aisle are measured from the robot's start
SECTION_M = 2.0
SECTIONS = 9
PLANTED = {'A-L-01-T1': 'rust', 'A-R-01-T1': 'a bulge'}
CAMERA_PANEL = (0, 60, 1280, 780)
INK = '#1A1A18'
COL = {'RED': '#B3261E', 'AMBER': '#C98A00', 'GREEN': '#2E7D32', 'GREY': '#8A8A85'}
FINDING = {'corrosion': 'Rust', 'bulge': 'Bulging', 'bulge+corrosion': 'Rust and bulging', 'corrosion+bulge': 'Rust and bulging',
           'none': 'Nothing found', '': 'Nothing found'}
WASTE = {'LLW': 'Low-level', 'ILW': 'Intermediate-level'}
SHELF = {1: 'Bottom', 2: 'Middle', 3: 'Top'}
SIDE = {'L': 'Left', 'R': 'Right'}
FAULT_WORD = {'CORROSION': 'Rust', 'BULGE': 'Bulging'}
# Where each moment sits in the 58-second showcase cut, as printed by make_showcase.py.
SHOWCASE = [('0:00--0:13', 'Rust found on A-L-01-T1, then the drum above it (A-L-01-T2) cleared as normal'),
            ('0:19--0:23', 'A-L-03-T3 on the top shelf: Cosmos Reason 2 asks for a closer look'),
            ('0:26--0:37', 'The robot comes back to A-L-03-T3 and confirms rust in 7 of 8 views'),
            ('0:47--0:58', 'The last drum, then the end-of-round summary')]


def jl(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def tex(s):
    rep = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
           '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(rep.get(c, c) for c in ('' if s is None else str(s)))


def clock(t):
    t = int(round(t or 0))
    return f'{t // 60}:{t % 60:02d}'


def duration(t):
    m, s = divmod(int(round(t or 0)), 60)
    return f'{m} min {s} s' if m else f'{s} s'


def certainty(c):
    if not c:
        return '--'
    return f'{"High" if c >= 0.7 else "Medium" if c >= 0.5 else "Low"} ({c * 100:.0f}\\%)'


def colour(d):
    return {'Confirmed defect': 'RED', 'Suspect': 'AMBER', "Couldn't inspect": 'AMBER'}.get(d['status'], 'GREEN')


def finding(d):
    f = d.get('finding') or 'none'
    return FINDING.get(f, f)


def section_of(x):
    return int((x - START_X) // SECTION_M)


def where(d):
    return f'Aisle A, {SIDE[d["side"]].lower()} side, stack {d["column"]}, {SHELF[d["tier"]].lower()} shelf'


def action_for(d):
    if 'bulge' in (d.get('finding') or ''):
        return ('Limit access to this aisle. Ask an engineer to assess the drum for pressure build-up, and measure its '
                'surface temperature (not measured in this inspection).')
    return ('Ask an engineer to assess how far the rust has gone. Take a surface wipe if none was taken. '
            'Consider placing the drum in an overpack (a larger outer drum).')


def plain_step(x):
    """One plain-English line for each logged decision."""
    text = x['text']
    m = re.match(r'Cosmos: (accept|closer look) - (.*)', text)
    if m:
        verb = 'accepted the camera software\'s result' if m.group(1) == 'accept' else 'asked for a closer look'
        return f'Cosmos Reason 2 {verb}: ``{tex(m.group(2))}\'\''
    m = re.match(r'\S+ (CORROSION|BULGE) -> DEFECT \(([\d.]+), (\d+)/(\d+) views\)', text)
    if m:
        return f'{FAULT_WORD[m.group(1)]} seen in {m.group(3)} of {m.group(4)} views (how sure: {float(m.group(2)) * 100:.0f}\\%). Action needed.'
    m = re.match(r'\S+ normal \(fault (\d+)/(\d+), normal (\d+)/(\d+)\) -> OK', text)
    if m:
        return f'No damage seen ({m.group(3)} of {m.group(4)} views looked normal). No problem found.'
    return tex(text)


def setup_mpl():
    try:
        plt.rcParams.update({'text.usetex': True, 'font.family': 'sans-serif',
                             'text.latex.preamble': r'\usepackage[T1]{fontenc}\usepackage[default]{sourcesanspro}\usepackage{textcomp}'})
        fig = plt.figure(); fig.text(0.5, 0.5, 'test'); fig.savefig('/dev/null', format='pdf'); plt.close(fig)
    except Exception:
        plt.rcParams.update({'text.usetex': False, 'font.family': 'sans-serif', 'font.sans-serif': ['Helvetica', 'DejaVu Sans']})
    plt.rcParams.update({'font.size': 9, 'axes.linewidth': 0.6, 'axes.edgecolor': INK, 'axes.labelcolor': INK})


def fig_map(path, drums, zones, tele):
    fig, ax = plt.subplots(figsize=(6.6, 3.1))
    size, gap = 0.56, 0.08
    for z in zones:
        fill = '#EFCF9A' if z['zone'] == 'RESTRICTED' else '#DDDDD8'
        ax.add_patch(Rectangle((z['lo'], -0.55), SECTION_M, 1.1, facecolor=fill, edgecolor='white', lw=1.2))
        ax.text(z['lo'] + SECTION_M / 2, -0.47, z['label'], ha='center', va='bottom', fontsize=6, color='#555550')
    for d in drums:
        x = d['x'] - START_X
        sign = 1 if d['side'] == 'L' else -1
        y = sign * (1.15 + (d['tier'] - 1) * (size + gap))
        ax.add_patch(Rectangle((x - size / 2, y - size / 2), size, size, facecolor=COL[colour(d)], edgecolor=INK, lw=0.5))
        if d['drum_id'] in PLANTED:
            ax.plot([x], [y], marker='o', ms=3.2, color='white', mec='none')
        if d['tier'] == 3:
            ax.text(x, y + sign * 0.38, str(d['column']), ha='center', va='bottom' if sign > 0 else 'top', fontsize=6.5)
    for sign, name in ((1, 'Left'), (-1, 'Right')):
        for tier in (1, 2, 3):
            ax.text(-0.5, sign * (1.15 + (tier - 1) * (size + gap)), SHELF[tier], ha='right', va='center', fontsize=6.5, color='#555550')
        ax.text(-1.75, sign * 1.8, f'{name}\nside', ha='right', va='center', fontsize=7.5)
    ax.text(-1.75, 0, 'Aisle A', ha='right', va='center', fontsize=7.5)
    trace = [(r['pose'][0] - START_X, (r['pose'][1] - 5.0) * 0.45) for r in tele[::6]]
    ax.plot([p[0] for p in trace], [p[1] for p in trace], color=INK, lw=0.8)
    ax.plot([trace[0][0]], [trace[0][1]], marker='o', ms=3.5, color=INK)
    ax.text(3.0, -3.45, 'low-level waste', ha='center', fontsize=7, color='#555550')
    ax.text(15.1, -3.45, 'intermediate-level waste', ha='center', fontsize=7, color='#555550')
    ax.set_xlim(-3.1, 18.2); ax.set_ylim(-3.75, 3.2); ax.set_aspect('equal'); ax.axis('off')
    handles = [Rectangle((0, 0), 1, 1, facecolor='#EFCF9A'), Rectangle((0, 0), 1, 1, facecolor='#DDDDD8'),
               Rectangle((0, 0), 1, 1, facecolor=COL['RED']), Rectangle((0, 0), 1, 1, facecolor=COL['GREEN']),
               Line2D([], [], marker='o', ls='', mfc='white', mec=INK, ms=4), Line2D([], [], color=INK)]
    ax.legend(handles, ['Restricted area', 'Not checked', 'Drum: action needed', 'Drum: no problem', 'Fault planted on purpose', "Robot's route"],
              fontsize=7.2, ncol=6, loc='upper center', bbox_to_anchor=(0.5, 0.03), frameon=False, handlelength=1.2, columnspacing=1.0)
    fig.tight_layout(pad=0.2); fig.savefig(path); plt.close(fig)


def fig_progress(path, tele, decisions, by_code):
    fig, ax = plt.subplots(figsize=(6.6, 2.6))
    ax.plot([r['t'] for r in tele[::6]], [r['pose'][0] - START_X for r in tele[::6]], color=INK, lw=1.0)
    points = [(x['t'], by_code[x['drum']]['x'] - START_X) for x in decisions if x.get('kind') == 'confirmed']
    ax.plot([p[0] for p in points], [p[1] + 0.9 for p in points], ls='', marker='o', ms=5, mfc=COL['RED'], mec=INK, mew=0.5, label='Damage confirmed')
    ax.set_xlabel('Time into the inspection (seconds)'); ax.set_ylabel('Distance along aisle (m)')
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=7.5, loc='upper left')
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir'); ap.add_argument('--commit', default='not recorded'); ap.add_argument('--out', default=None)
    a = ap.parse_args()
    run = Path(a.run_dir); out = Path(a.out) if a.out else run / 'report'; (out / 'photos').mkdir(parents=True, exist_ok=True)
    run_id = run.parent.name
    mem = json.loads((run / 'memory.json').read_text())
    decisions = jl(run / 'decisions.jsonl'); tele = jl(run / 'telemetry.jsonl')
    scored = json.loads((run / 'colour_accuracy.json').read_text())
    truth = {r[0]: dict(category=r[1], rust=r[4], bulge=r[5], result=r[6]) for r in scored['rows']}
    drums = sorted(mem['drums'], key=lambda d: d['drum_id'])
    by_code = {d['drum_id']: d for d in drums}
    for d in drums:
        d['category'] = truth[d['drum_id']]['category']
    report = scored['report']
    reviews = mem.get('cosmos_reviews', [])
    acts = Counter(r.get('action') for r in reviews)

    walked = {section_of(r['pose'][0]) for r in tele}
    zones = []
    for k in range(SECTIONS):
        lo = k * SECTION_M
        damaged = [d['drum_id'] for d in drums if section_of(d['x']) == k and colour(d) == 'RED']
        label = f'{lo:g}--{lo + SECTION_M:g} m'
        if damaged:
            zone, why = 'RESTRICTED', f'Damaged drum here: {", ".join(damaged)}. Radiation was not measured, so this may need to be stricter.'
        elif k in walked:
            zone, why = 'NOT CHECKED', 'The robot walked here, but radiation was not measured.'
        else:
            zone, why = 'NOT CHECKED', 'The robot did not go here this time.'
        zones.append(dict(lo=lo, zone=zone, why=why, label=label if plt.rcParams['text.usetex'] else label.replace('--', '-')))

    setup_mpl()
    for z in zones:
        z['label'] = z['label'].replace('--', '-')
    fig_map(out / 'map.pdf', drums, zones, tele)
    fig_progress(out / 'progress.pdf', tele, decisions, by_code)
    shutil.copy(ASSETS / 'logo.png', out / 'logo.png')
    photo = {}
    for s in mem.get('stills', []):
        src = run / s['file']
        if s['kind'] == 'confirmed' and src.exists():
            dst = out / 'photos' / (src.stem + '.jpg')
            Image.open(src).crop(CAMERA_PANEL).convert('RGB').save(dst, quality=88)
            photo[s['drum']] = (f'photos/{dst.name}', s['t'])

    reds = [d for d in drums if colour(d) == 'RED']; ambers = [d for d in drums if colour(d) == 'AMBER']; greens = [d for d in drums if colour(d) == 'GREEN']
    zone_count = Counter(z['zone'] for z in zones)
    checked = sum(1 for d in drums if d['status'] != "Couldn't inspect")
    seconds = mem['duration_s']; store = 'Warehouse v3, aisle A (simulated)'; started = mem['started_utc']
    C = []; w = C.append

    # ---------- page 1
    w(r'\thispagestyle{first}')
    w(r'\begin{minipage}[c]{0.13\textwidth}\includegraphics[width=\linewidth]{logo.png}\end{minipage}\hfill')
    w(r'\begin{minipage}[c]{0.84\textwidth}\raggedleft')
    w(r'{\large\bfseries C.A.N.I.S.}\\[-1pt]{\small\color{muted} Corrosion And Nuclear Inspection System}\\[10pt]')
    w(r'{\fontsize{24}{28}\selectfont\bfseries Drum Store Inspection Report}\\[4pt]')
    w(rf'{{\color{{muted}} {tex(store)} \enspace\textbar\enspace {tex(started.split(" ")[0])}}}')
    w(r'\end{minipage}\par\vspace{8pt}\rule{\textwidth}{0.6pt}\par\vspace{8pt}')
    w(r'\noindent\begin{tabularx}{\textwidth}{@{}>{\color{muted}}l X >{\color{muted}}l X@{}}')
    w(rf'Store & {tex(store)} & Report number & CANIS-{tex(run_id)}\\')
    w(rf'Inspected on & {tex(started)} & Time taken & {duration(seconds)}\\')
    w(r'Inspected by & C.A.N.I.S.\ inspection robot & Status & Practice run in a simulated store\\')
    w(r'\end{tabularx}\par\vspace{10pt}')
    w(r'\begin{summarybox}{\bfseries\large Summary}\par\vspace{6pt}')
    w(r'\begin{tabularx}{\linewidth}{@{}X r@{\hspace{28pt}}X r@{}}')
    w(rf'Drums checked & \textbf{{{checked} of {len(drums)}}} & Areas safe to enter & \textbf{{{zone_count["SAFE"]}}}\\')
    w(rf'\dotR\ Need action & \textbf{{{len(reds)}}} & Areas restricted & \textbf{{{zone_count["RESTRICTED"]}}}\\')
    w(rf'\dotA\ Check again & \textbf{{{len(ambers)}}} & Areas to keep out of & \textbf{{{zone_count["KEEP OUT"]}}}\\')
    w(rf'\dotG\ No problem found & \textbf{{{len(greens)}}} & Areas not checked & \textbf{{{zone_count["NOT CHECKED"]}}}\\')
    w(rf'Radiation dose to the robot & \textbf{{not measured}} & Time taken & \textbf{{{duration(seconds)}}}\\')
    w(r'\end{tabularx}\par\vspace{8pt}')
    w(rf'{{\large {len(reds)} drums need action. {zone_count["RESTRICTED"]} aisle sections are restricted because of damaged drums. '
      r'Radiation was not measured on this round, so no part of the aisle can be called safe yet.}')
    w(r'\end{summarybox}\par\vspace{10pt}')
    w(r'{\bfseries How to read this report}\par\vspace{2pt}')
    w(r'\begin{tabularx}{\textwidth}{@{}l X@{\hspace{14pt}}l X@{}}')
    w(r'\dotR & \textbf{Action needed.} Damage seen clearly. An engineer should assess the drum. & \zone{SAFE} & Normal access.\\')
    w(r'\dotA & \textbf{Check again.} Possible damage, not yet confirmed. & \zone{RESTRICTED} & Enter only under controlled-area rules.\\')
    w(r'\dotG & \textbf{No problem found} in this inspection. & \zone{KEEP OUT} & Do not enter.\\')
    w(r' & & \zone{NOT CHECKED} & Not measured: treat as unknown.\\')
    w(r'\end{tabularx}\par\vspace{4pt}')
    w(r'{\small\color{muted} This round used the camera only. The robot carried no radiation meter, thermometer or gas sensor, and took no surface wipes. '
      r'Two drums had damage planted on purpose so the robot\textquotesingle s response shows early in the video: rust on A-L-01-T1 and a bulge on A-R-01-T1.}')

    # ---------- areas
    w(r'\clearpage\section{Who can go where}')
    w(r'The robot walked aisle A once, looking at the drums on both sides. The aisle is split into 2-metre sections. A section is only marked safe '
      r'if radiation was measured there. This round did not measure radiation, so no section is marked safe.')
    w(r'\begin{figure}[H]\centering\includegraphics[width=\textwidth]{map.pdf}\caption{Plan of aisle A. The racks on each side are drawn folded out flat: '
      r'the row nearest the aisle is the bottom shelf. Numbers are stack numbers; distances are measured from where the robot started.}\end{figure}')
    w(r'\begin{longtable}{@{}l l p{0.62\textwidth}@{}}\toprule Section & Rating & Why\\\midrule\endhead')
    for z in sorted(zones, key=lambda z: (z['zone'] != 'RESTRICTED', z['lo'])):
        w(rf'{z["lo"]:g}--{z["lo"] + SECTION_M:g} m & \zone{{{z["zone"]}}} & {tex(z["why"])}\\')
    w(r'\bottomrule\end{longtable}')

    # ---------- register
    w(r'\clearpage\section{Every drum at a glance}')
    w(rf'All {len(drums)} drums in this inspection, most urgent first.')
    w(r'\begin{longtable}{@{}l l l l l l l@{}}\toprule Drum & Waste & Side & Shelf & Result & What was seen & How sure\\\midrule\endhead')
    for d in reds + ambers + greens:
        w(rf'\textbf{{{d["drum_id"]}}} & {WASTE[d["category"]]} & {SIDE[d["side"]]}, stack {d["column"]} & {SHELF[d["tier"]]} & \result{{{colour(d)}}} & {finding(d)} & {certainty(d["confidence"])}\\')
    w(r'\bottomrule\end{longtable}')
    w(r"{\small\color{muted} ``How sure'' is how confident the camera software was in what it saw. Drum names read: aisle, side (L = left, R = right), stack number, "
      r'tier (T1 = bottom shelf). Yellow drums hold low-level waste and blue drums hold intermediate-level waste. This is the first inspection of these drums, so there is nothing to compare with yet. '
      r'Not measured in this inspection: radiation at the drum, drum surface temperature, hydrogen gas and surface wipe (swab) results.}')

    # ---------- findings
    w(r'\clearpage\section{Drums that need attention}')
    for d in reds + ambers:
        code = d['drum_id']
        w(r'\begin{finding}')
        w(rf'{{\large\bfseries Drum {code}}}\hfill\result{{{colour(d)}}}\par')
        w(rf'{{\color{{muted}} {WASTE[d["category"]]} waste \textbar\ {where(d)}}}\par\vspace{{6pt}}')
        if code in photo:
            w(rf'\begin{{center}}\includegraphics[width=0.72\linewidth]{{{photo[code][0]}}}\end{{center}}\par')
            w(rf'{{\small\color{{muted}} Robot camera view {clock(photo[code][1])} into the inspection. The thick box marks drum {code} and what the camera software saw.}}\par\vspace{{6pt}}')
        w(r'\begin{tabularx}{\linewidth}{@{}>{\leavevmode\color{muted}}p{0.22\linewidth} X@{}}')
        w(rf'What was seen & {finding(d)}\\')
        w(rf'How sure & {certainty(d["confidence"])}\\')
        w(rf'Why this rating & {finding(d)} seen in {d["fault_views"]} of {d["views"]} camera views.\\')
        w(r'Radiation at drum & Not measured\\ Surface wipe (swab) & Not taken\\ Surface temperature & Not measured\\')
        if code in PLANTED:
            w(rf'Test note & This fault ({PLANTED[code]}) was planted on purpose for the demonstration.\\')
        steps = [rf'{clock(x["t"])}\enspace {plain_step(x)}' for x in decisions if x.get('drum') == code]
        w(r'What the robot did & ' + r' \newline '.join(steps) + r'\\')
        w(r'\end{tabularx}\par\vspace{6pt}')
        w(rf'\action{{{tex(action_for(d))}}}')
        w(r'\end{finding}')

    # ---------- not checked
    w(r'\section{What was not checked}')
    w(r'\begin{itemize}[leftmargin=*,itemsep=2pt]')
    w(rf'\item The robot got a verdict on all {len(drums)} drums it was sent to look at.')
    w(r'\item Radiation, drum surface temperature and hydrogen gas were not measured anywhere on this round, and no surface wipes were taken. '
      r'Every aisle section is therefore unknown for people until a round with those sensors is done.')
    w(rf'\item This round covered {len(drums)} drums on aisle A: the low-level waste stacks near the entrance and the intermediate-level waste stacks further down. Other drums in the store were not part of this round.')
    w(r'\end{itemize}')

    # ---------- accuracy
    yellow, blue = report['yellow | all drums'], report['blue | all drums']
    yellow_x = report['yellow | excluding the 2 planted drums']
    missed = [k for k, v in truth.items() if v['result'] == 'missed']
    false = [k for k, v in truth.items() if v['result'] == 'false alarm']
    damage = lambda k: ', '.join(f'{n} {truth[k][f]:.2f}' for f, n in (('rust', 'rust'), ('bulge', 'bulge')) if truth[k][f])
    faulty = yellow['faulty_drums'] + blue['faulty_drums']; found = yellow['caught'] + blue['caught']
    w(r'\section{How accurate was the robot?}')
    w(r'This was a practice run in a simulated store, so we know which drums were really damaged. The robot was not told; the comparison is made only for this report.')
    w(r'\begin{itemize}[leftmargin=*,itemsep=2pt]')
    w(rf'\item It found {found} of the {faulty} damaged drums. Two of those {faulty} were the planted faults.')
    w(rf'\item It missed {len(missed)} damaged drums: ' + ', '.join(f'{k} ({damage(k)})' for k in missed) + '. The numbers are how severe the simulated damage was (0 to 1).')
    w(rf'\item It raised {len(false)} false alarms.' if false else r'\item It raised no false alarms: every drum it flagged was really damaged.')
    w(r'\end{itemize}')
    w(r'\begin{longtable}{@{}l r r r r r@{}}\toprule Drum colour & Drums & Correct & Accuracy & 95\% range & Damaged drums found\\\midrule\endhead')
    for name, r in (('Yellow (low-level)', yellow), ('Blue (intermediate-level)', blue)):
        low, high = r['accuracy_all_95ci']
        w(rf'{name} & {r["drums"]} & {r["caught"] + r["correct clear"]} & \textbf{{{r["accuracy_all_drums"] * 100:.1f}\%}} & {low * 100:.0f}--{high * 100:.0f}\% & {r["caught"]} of {r["faulty_drums"]}\\')
    w(r'\bottomrule\end{longtable}')
    w(rf'{{\small\color{{muted}} A drum counts as correct if it was damaged and flagged, or undamaged and cleared. Leaving out the two planted drums, yellow is {yellow_x["accuracy_all_drums"] * 100:.1f}\% '
      rf'({yellow_x["caught"] + yellow_x["correct clear"]} of {yellow_x["drums"]}); blue has no planted drums. With this few drums the 95\% ranges are wide, so small differences between the colours should not be over-read.}}\par')
    w(r'A false alarm costs a person an extra check. A missed drum is the more serious error. Blue-drum bulges were the weakest area: the robot missed both blue drums that had one.')

    # ---------- how made
    w(r'\section{How this report was made}')
    w(r'The robot walks the aisle and points its camera at each drum in turn, taking three views from the aisle. Software trained to recognise rust and bulging (swelling) on drums labels each view. '
      r'If two of the three views show damage, the drum is marked as needing action. If the views look normal, NVIDIA Cosmos Reason 2 reviews the result and either accepts it or asks for more evidence. '
      r'Top-shelf drums are seen at a steep angle, so they never get a verdict from the first three views: Cosmos Reason 2 chooses between a closer look (five more views from a second position, after which the rules decide) and marking the drum for a person to check again. '
      r'Cosmos Reason 2 can only choose from the options it is offered. It can never clear a drum or confirm damage, and it cannot change any number; fixed rules do that. Everything in this report comes from what the robot recorded during the inspection.')
    w(rf'\par On this round Cosmos Reason 2 made {len(reviews)} reviews. It accepted all {acts["accept_ok"]} results the rules had cleared, asked for a closer look at all {acts["closer_look"]} top-shelf drums, and marked no drum for a person to check.')
    w(r'\paragraph{Please note} This inspection took place in a computer-simulated store, not a real one. The damage-spotting software was trained on computer-generated images. '
      r'How far rust has spread is estimated from photos, not measured. Only a surface wipe can show contamination. The format follows the themes of the Nuclear Decommissioning Authority\textquotesingle s '
      r'\textit{Guidance on Monitoring of Waste Packages During Storage} (WPS/640).')

    # ---------- evidence video
    w(r'\section{Video evidence}')
    w(r'The whole round was recorded on video, about 7 minutes long. A 58-second showcase cut shows the moments below in real time. Everything between them is sped up about 20 times, and the clock on screen always shows true mission time.')
    w(r'\begin{longtable}{@{}l p{0.8\textwidth}@{}}\toprule In the cut & What it shows\\\midrule\endhead')
    for when, what in SHOWCASE:
        w(rf'{when} & {what}\\')
    w(r'\bottomrule\end{longtable}')

    # ---------- appendices
    w(r'\clearpage\appendix\section{The robot\textquotesingle s route over time}')
    w(r'\begin{figure}[H]\centering\includegraphics[width=\textwidth]{progress.pdf}\caption{How far down aisle A the robot was during the inspection. Dots mark when a drum was found to need action. Flat stretches are where the robot stopped to look at drums.}\end{figure}')
    w(r'\section{Step-by-step record}')
    w(r'Every decision the robot made, in order. Times are minutes:seconds into the inspection. Cosmos Reason 2 comments are shortened, exactly as the robot logged them.')
    w(r'\begin{longtable}{@{}l l p{0.68\textwidth}@{}}\toprule Time & Drum & What happened\\\midrule\endhead')
    for x in decisions:
        w(rf'{clock(x["t"])} & {tex(x["drum"])} & {plain_step(x)}\\')
    w(r'\bottomrule\end{longtable}')
    w(r'\clearpage\section{Technical details}{\small\color{muted} For engineers and auditors.}\par')
    w(r'\begin{tabularx}{\textwidth}{@{}>{\color{muted}}l X@{}}')
    w(rf'Run ID & \texttt{{{tex(run_id)}}}\\')
    w(rf'Software version & \texttt{{{tex(a.commit)}}}\\')
    w(r'Walk script & \texttt{scripts/hot/full\_hall/wh\_rigid\_walk.py} with \texttt{wh\_rigid\_full\_cosmos.py}\\')
    w(rf'Damage detector & YOLO26s whole-barrel conditions, run \texttt{{\footnotesize {tex(mem["detector"].split()[-1]).replace("_", "_" + chr(92) + "allowbreak ")}}}\\')
    w(rf'Detector weights SHA-256 & \texttt{{\footnotesize {mem["detector_sha256"][0]}}}\\')
    w(rf'Detector calls & {mem["yolo_calls"]} ({mem["yolo_failures"]} failed)\\')
    w(r'Decision rule & Side look, 3 views: fault ($\geq$0.50) in $\geq$2 views $\rightarrow$ defect; normal in $\geq$2 and no fault $\rightarrow$ OK; otherwise, and always for tier 3, a closer look (8 views in total): fault in $\geq$4, or $\geq$3 and more than normal $\rightarrow$ defect; normal in $\geq$5 and fault $\leq$1 $\rightarrow$ OK; otherwise suspect.\\')
    valid = sum(1 for r in reviews if r.get('valid'))
    slowest = max(r.get('latency_s') or 0 for r in reviews)
    w(rf'Cosmos reviews & NVIDIA Cosmos Reason 2 8B: {len(reviews)} reviews, {valid} valid, {acts["accept_ok"]} accepted, {acts["closer_look"]} closer looks, {acts["mark_suspect"]} marked suspect; slowest reply {slowest:.1f} s. Options offered: accept or closer look when the rules say OK; closer look or mark suspect when unclear or top shelf. Never offered when the rules confirm damage.\\')
    w(r'Planted faults & \texttt{A-L-01-T1} rust 0.85; \texttt{A-R-01-T1} bulge 0.85. All other faults: inventory seed 42.\\')
    w(r'Logged channels & Robot pose, camera tilt, detector boxes, decisions, Cosmos reviews. No dose rate, temperature, gas or swab.\\')
    w(r'Simulation & NVIDIA Isaac Sim, warehouse-v3\\')
    w(r'Status names & Action needed = \texttt{Confirmed defect}; Check again = \texttt{Suspect}; No problem found = \texttt{OK}; Not inspected = \texttt{Couldn\textquotesingle t inspect}\\')
    w(r'\end{tabularx}')

    doc = (ASSETS / 'template.tex').read_text().replace('%%RUNID%%', tex(run_id)).replace('%%BODY%%', '\n'.join(C))
    (out / 'report.tex').write_text(doc)
    for _ in range(2):
        r = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 'report.tex'], cwd=out, capture_output=True, text=True, errors='replace')
        if r.returncode:
            print(r.stdout[-3000:]); raise SystemExit('pdflatex failed')
    pdf = out / f'CANIS_report_{run_id}.pdf'
    shutil.move(out / 'report.pdf', pdf)
    print(pdf)


if __name__ == '__main__':
    main()
