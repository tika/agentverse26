"""Deterministic report rules. Every colour, zone and action in the report comes from here.

The thresholds and their sources are printed in the report (see LIMITS). Change a rule here and the
report, the register and the summary all change together. No model output is read by this module.
"""
import math
import re
from collections import defaultdict

# ---- limits (printed verbatim in the report's "Limits used" table) ---------------------------------
GAMMA_RESTRICT = 7.5        # uSv/h  HSE L121, regulation 17
GAMMA_KEEPOUT = 100.0       # uSv/h  HSE L121
SWAB_ALPHA, SWAB_BG = 0.4, 4.0   # Bq/cm2  IAEA SSR-6 Rev. 2, para 508
HEAT_RISE = 5.0             # degC above air, team demo rule
SECTION_M = 2.0

LIMITS = [
    ('Restricted area', 'gamma > 7.5 µSv/h',
     'HSE, Work with ionising radiation (L121), regulation 17. Used as an instantaneous robot rule, '
     'not a legal controlled-area assessment.'),
    ('Keep out', 'gamma > 100 µSv/h', 'HSE L121 guidance on high instantaneous dose rates.'),
    ('Surface wipe', '> 0.4 / 4 Bq/cm²',
     'IAEA SSR-6 Rev. 2 (2025), para 508. Transport limits borrowed as escalation values.'),
    ('Warm drum', '≥ 5 °C above air', 'Team demo rule. Not an operational limit.'),
    ('Hydrogen', 'no level set', 'No cited alarm level yet. Readings are printed; hydrogen changes no rating.'),
]

NAME = 'C.A.N.I.S.'
EXPANSION = 'Containment Analysis & Nuclear Intelligence System'

# ---- plain words ----------------------------------------------------------------------------------
STATUS = ('Confirmed defect', 'Suspect', "Couldn't inspect", 'OK')
COLOUR_WORD = {'RED': 'Action needed', 'AMBER': 'Check again', 'GREEN': 'No problem found'}
ZONE_ORDER = ['KEEP OUT', 'RESTRICTED', 'LOW GAMMA', 'NOT CHECKED']
ZONE_WORD = {'KEEP OUT': 'Keep out', 'RESTRICTED': 'Restricted', 'LOW GAMMA': 'Low gamma',
             'NOT CHECKED': 'Not checked'}
FINDING_WORD = {'none': 'Nothing found', 'corrosion': 'Rust', 'bulge': 'Bulging',
                'corrosion+bulge': 'Rust and bulging', 'bulge+corrosion': 'Rust and bulging'}
WASTE = {'LLW': 'Low-level waste', 'ILW': 'Intermediate-level waste'}
SIDE = {'L': 'left', 'R': 'right'}
ID_RE = re.compile(r'^(?P<aisle>[A-Z])-(?P<side>[LR])-(?P<col>\d+)-T(?P<tier>\d+)$')


FAULT_CLASSES = {'rust', 'corrosion', 'bulge', 'dent'}


def is_fault_class(cls):
    return (cls or '').lower() in FAULT_CLASSES


def parse_id(drum_id):
    m = ID_RE.match(drum_id or '')
    if not m:
        return None
    return dict(aisle=m['aisle'], side=m['side'], column=int(m['col']), tier=int(m['tier']))


def tier_word(tier, max_tier):
    if max_tier <= 1:
        return 'floor'
    if tier == 1:
        return 'bottom shelf'
    if tier == max_tier:
        return 'top shelf'
    return 'middle shelf' if max_tier == 3 else f'shelf {tier}'


def where(d, max_tier=3):
    p = parse_id(d['drum_id'])
    if not p:
        return d.get('location') or 'location not logged'
    return f"Aisle {p['aisle']}, {SIDE[p['side']]} side, stack {p['column']}, {tier_word(p['tier'], max_tier)}"


def finding_word(f):
    f = f or 'none'
    return FINDING_WORD.get(f, f.replace('+', ' and ').capitalize())


def certainty(c):
    if c is None:
        return None
    return ('High' if c >= 0.7 else 'Medium' if c >= 0.5 else 'Low', round(c * 100))


def radiation_word(v):
    if v is None:
        return None
    return 'High' if v > GAMMA_KEEPOUT else 'Raised' if v > GAMMA_RESTRICT else 'Normal'


def swab_over(s):
    return bool(s) and (s.get('alpha', 0) > SWAB_ALPHA or s.get('beta_gamma', 0) > SWAB_BG)


# ---- drum colour ----------------------------------------------------------------------------------
def drum_colour(d):
    """(colour, [plain reasons]). 'Above' is strictly above, except heat which is >= by the team rule."""
    why = []
    heat, dose, f = d.get('heat_rise_c'), d.get('dose_rate_at_drum_uSv_h'), d.get('finding') or ''
    red = d['status'] == 'Confirmed defect'
    if red:
        why.append(f'{finding_word(f).lower()} confirmed in {d.get("fault_views", "?")} of {d.get("views", "?")} views')
    if swab_over(d.get('swab')):
        red = True; why.append('surface wipe above the contamination limit')
    if heat is not None and heat >= HEAT_RISE and 'bulge' in f:
        red = True; why.append('bulging drum is warmer than the air')
    if dose is not None and dose > GAMMA_KEEPOUT:
        red = True; why.append('very high radiation at the drum')
    if red:
        return 'RED', why
    amber = d['status'] in ('Suspect', "Couldn't inspect")
    if d['status'] == 'Suspect':
        why.append(f'possible {finding_word(f).lower()}, not confirmed')
    if d['status'] == "Couldn't inspect":
        why.append(d.get('reason') or 'the robot could not get a clear look')
    if heat is not None and heat >= HEAT_RISE:
        amber = True; why.append('drum is warmer than the air')
    if not amber:
        n = d.get('views')
        why.append(f'no damage seen in {n} views' if n else 'no damage seen')
    return ('AMBER' if amber else 'GREEN'), why


def action_for(d):
    f, s = d.get('finding') or '', d['status']
    if s == "Couldn't inspect":
        if d.get('label') and d['label'].get('readable') is False:
            return 'Read the drum label in person and confirm which drum this is. Then repeat the inspection.'
        return 'Inspect again once the area is clear and radiation is back to normal.'
    if swab_over(d.get('swab')):
        return 'Keep people out. Contamination control and a survey by a qualified person.'
    if s == 'Suspect':
        return 'Inspect again within 7 days, with a closer look and a surface wipe (swab).'
    if 'bulge' in f:
        h = d.get('heat_rise_c')
        if h is None:
            return ('Limit access to this aisle. Ask an engineer to assess the drum for pressure build-up, '
                    'and measure its surface temperature (not measured in this inspection).')
        if h >= HEAT_RISE:
            return 'Keep people out of this aisle section. Isolate the drum and get an urgent engineering assessment.'
        return 'Limit access to this aisle. Ask an engineer to assess the drum. Inspect again at the next round.'
    if 'corrosion' in f:
        return ('Ask an engineer to assess how far the rust has gone. Take a surface wipe if none was taken. '
                'Consider placing the drum in an overpack (a larger outer drum).')
    if d.get('heat_rise_c') is not None and d['heat_rise_c'] >= HEAT_RISE:
        return 'Measure the surface temperature again and check for gas generation.'
    return 'No action. Routine inspection.'


# ---- aisle geometry and zones ---------------------------------------------------------------------
def aisles(drums, aisle_length_m=None, aisle_start_x=None):
    """Per aisle letter: centre line y, half-width, and 2 m sections along x (from aisle_start_x if given)."""
    by = defaultdict(list)
    for d in drums:
        p = parse_id(d['drum_id'])
        if p and d.get('x') is not None:
            by[p['aisle']].append(d)
    out = {}
    for a, ds in sorted(by.items()):
        ys = [d['y'] for d in ds]
        xs = [d['x'] for d in ds]
        centre = (min(ys) + max(ys)) / 2
        half = max((max(ys) - min(ys)) / 2, 1.0)
        x0 = aisle_start_x if aisle_start_x is not None else math.floor(min(xs) - 1.0)
        x1 = x0 + aisle_length_m if aisle_length_m else max(xs) + 1.0
        n = max(1, math.ceil((x1 - x0) / SECTION_M))
        out[a] = dict(name=a, centre=centre, half=half, x0=x0, n=n, drums=ds)
    return out


def zones(tele, drums, colours, aisle_length_m=None, aisle_start_x=None):
    geo = aisles(drums, aisle_length_m, aisle_start_x)
    seen = defaultdict(list)
    for t in tele:
        if t.get('x') is None:
            continue
        a = min(geo.values(), key=lambda g: abs(g['centre'] - t['y']), default=None)
        if a is None or abs(a['centre'] - t['y']) > a['half'] + 0.6:
            continue
        k = int((t['x'] - a['x0']) // SECTION_M)
        if 0 <= k < a['n']:
            seen[(a['name'], k)].append(t)
    out = []
    for a in geo.values():
        for k in range(a['n']):
            lo, hi = a['x0'] + k * SECTION_M, a['x0'] + (k + 1) * SECTION_M
            ts = seen.get((a['name'], k), [])
            near = [d for d in a['drums'] if lo <= d['x'] < hi]
            z = dict(aisle=a['name'], k=k, lo=lo, hi=hi, part=f'{k * SECTION_M:g}–{(k + 1) * SECTION_M:g} m',
                     drums=[d['drum_id'] for d in near], samples=len(ts), gmax=None, h2max=None, t_gmax=None)
            if not ts:
                out.append(dict(z, zone='NOT CHECKED', reason='The robot did not go here this time.'))
                continue
            g = [t for t in ts if t.get('gamma') is not None]
            if g:
                top = max(g, key=lambda t: t['gamma'])
                z.update(gmax=top['gamma'], t_gmax=top['t'])
            h2 = [t['h2'] for t in ts if t.get('h2') is not None]
            z['h2max'] = max(h2) if h2 else None
            gm = z['gmax']
            reds = [d['drum_id'] for d in near if colours[d['drum_id']][0] == 'RED']
            ambers = [d['drum_id'] for d in near if colours[d['drum_id']][0] == 'AMBER']
            if gm is not None and gm > GAMMA_KEEPOUT:
                r = ('KEEP OUT', f'Gamma reached {gm:.0f} µSv/h, above the keep-out level.')
            elif any(swab_over(d.get('swab')) for d in near):
                r = ('KEEP OUT', 'A surface wipe here was above the contamination limit.')
            elif any(d.get('heat_rise_c') is not None and d['heat_rise_c'] >= HEAT_RISE and 'bulge' in (d.get('finding') or '')
                     for d in near):
                r = ('KEEP OUT', 'A bulging drum here is warmer than the air: possible pressure build-up.')
            elif gm is not None and gm > GAMMA_RESTRICT:
                r = ('RESTRICTED', f'Gamma reached {gm:.1f} µSv/h, above the restricted level.')
            elif reds:
                r = ('RESTRICTED', 'Drum needing action here: ' + ', '.join(reds) + '.')
            elif ambers:
                r = ('RESTRICTED', 'Unresolved drum here: ' + ', '.join(ambers) + '.')
            elif gm is None:
                r = ('NOT CHECKED', 'The robot walked here, but radiation was not measured.')
            else:
                r = ('LOW GAMMA', f'Highest gamma {gm:.2f} µSv/h, below the restricted level.')
            if r[0] == 'RESTRICTED' and gm is None:
                r = (r[0], r[1] + ' Radiation was not measured, so this may need to be stricter.')
            out.append(dict(z, zone=r[0], reason=r[1]))
    return out
