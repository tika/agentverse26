# Demo video HUD: onboard camera with YOLO boxes, section minimap, decision panel, sensor strip.
# Pure PIL. Exec'd into the hot namespace after scenario_lib.py, or imported standalone for previews
# (tools/preview_demo_hud.py). The agent builds a plain `state` dict per frame; see compose_demo.
import math as _hm
from PIL import Image as _HImage, ImageDraw as _HDraw, ImageFont as _HFont

HUD_W, HUD_H = 1920, 1080
HUD_COLUMNS_X = (2.79, 3.41, 4.09, 4.71, 5.39, 6.01, 6.69, 7.31, 7.99, 8.61)
HUD_BG, HUD_PANEL, HUD_LINE = '#101419', '#171d24', '#26303b'
HUD_TEXT, HUD_DIM = '#e8edf2', '#8796a5'
HUD_STATUS = {'grey': '#4a5562', 'amber': '#f2b33d', 'green': '#3ccf8e', 'red': '#ff5a52', 'hidden': '#20262d'}
HUD_STATUS_LABEL = {'grey': 'unseen', 'amber': 'suspected', 'green': 'clear', 'red': 'fault'}
HUD_BOX = {'drum': '#6fb6ff', 'corrosion': '#ff5a52', 'bulge': '#f2b33d'}
_HUD_FONTS = {}
_HUD_FONT_FILES = {
    False: ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf',
            '/Library/Fonts/Arial.ttf', 'DejaVuSans.ttf'],
    True: ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
           '/Library/Fonts/Arial Bold.ttf', 'DejaVuSans-Bold.ttf'],
}


def hud_font(size, bold=False):
    key = (size, bold)
    if key not in _HUD_FONTS:
        for path in _HUD_FONT_FILES[bold]:
            try:
                _HUD_FONTS[key] = _HFont.truetype(path, size)
                break
            except OSError:
                continue
        else:
            _HUD_FONTS[key] = _HFont.load_default(size=size)
    return _HUD_FONTS[key]


def _fit(draw, text, font, width):
    """Truncate with an ellipsis so text never runs past its panel."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + '…', font=font) > width:
        text = text[:-1]
    return text + '…'


def _wrap(draw, text, font, width, max_lines):
    lines, line = [], ''
    for word in str(text).split():
        trial = f'{line} {word}'.strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _fit(draw, lines[-1] + ' …', font, width)
    return [_fit(draw, l, font, width) for l in lines]


def _panel(draw, box, title=None):
    draw.rounded_rectangle(box, radius=10, fill=HUD_PANEL)
    if title:
        draw.text((box[0] + 18, box[1] + 12), title, font=hud_font(15, True), fill=HUD_DIM)


def _parse_code(code):
    """'B-L-07-T3' -> ('L', 7, 3, 1); '-D2' suffix means a hidden back-row drum."""
    parts = code.split('-')
    try:
        return parts[1], int(parts[2]), int(parts[3].lstrip('T')), 2 if len(parts) > 4 else 1
    except (IndexError, ValueError):
        return None


def _camera(canvas, frame_rgb, state, box):
    x0, y0, x1, y1 = box
    draw = _HDraw.Draw(canvas)
    image = frame_rgb if isinstance(frame_rgb, _HImage.Image) else _HImage.fromarray(frame_rgb)
    image = image.convert('RGB')
    side = min(x1 - x0, y1 - y0)
    scale = side / max(image.size)
    size = (round(image.size[0] * scale), round(image.size[1] * scale))
    ox, oy = x0 + (x1 - x0 - size[0]) // 2, y0
    canvas.paste(image.resize(size, _HImage.LANCZOS), (ox, oy))
    draw.rectangle((ox - 1, oy - 1, ox + size[0], oy + size[1]), outline=HUD_LINE)
    label_font = hud_font(17, True)
    for det in state.get('yolo_boxes', []):
        bx0, by0, bx1, by1 = (v * scale for v in det['box'])
        bx0, bx1, by0, by1 = ox + bx0, ox + bx1, oy + by0, oy + by1
        color = HUD_BOX.get(det.get('label'), '#ffffff')
        draw.rectangle((bx0, by0, bx1, by1), outline=color, width=4 if det.get('label') != 'drum' else 2)
        text = det.get('label', '?') + (f" {det['conf']:.2f}" if det.get('conf') is not None else '')
        if det.get('drum_code') and det.get('label') != 'drum':
            text += f"  {det['drum_code']}"
        tw = draw.textlength(text, font=label_font)
        ty = by0 - 26 if by0 - 26 > oy else by0 + 2
        tx = min(bx0, ox + size[0] - tw - 12)
        draw.rectangle((tx, ty, tx + tw + 12, ty + 24), fill=color)
        draw.text((tx + 6, ty + 2), text, font=label_font, fill='#0b0e12')
    draw.text((ox + 14, oy + 12), 'ONBOARD CAMERA  ·  fixed to body', font=hud_font(15, True), fill='#ffffff',
              stroke_width=2, stroke_fill='#000000')
    pitch = state.get('body_pitch_deg', 0) or 0
    if pitch:
        badge = f'BODY PITCH {pitch:+.0f}°  (simulated)'
        font = hud_font(18, True)
        tw = draw.textlength(badge, font=font)
        bx = ox + size[0] - tw - 34
        draw.rounded_rectangle((bx, oy + 10, bx + tw + 22, oy + 44), radius=8, fill='#2a3d55')
        draw.text((bx + 11, oy + 16), badge, font=font, fill='#bfe0ff')
    # Activity caption: the single most important line on screen.
    cy = oy + size[1] + 14
    draw.rounded_rectangle((x0, cy, x1, cy + 70), radius=10, fill=HUD_PANEL)
    activity = state.get('activity', '')
    accent = '#ff5a52' if 'fault' in activity.lower() else '#f2b33d' if 'second look' in activity.lower() else '#6fb6ff'
    draw.rounded_rectangle((x0, cy, x0 + 8, cy + 70), radius=4, fill=accent)
    draw.text((x0 + 26, cy + 9), 'NOW', font=hud_font(14, True), fill=HUD_DIM)
    draw.text((x0 + 26, cy + 27), _fit(draw, activity, hud_font(32, True), x1 - x0 - 300), font=hud_font(32, True),
              fill=HUD_TEXT)
    t = state.get('t')
    if t is not None:
        clock = f'{t:5.1f} s'
        draw.text((x1 - 24 - draw.textlength(clock, font=hud_font(28)), cy + 22), clock, font=hud_font(28), fill=HUD_DIM)


def _minimap(draw, state, box):
    x0, y0, x1, y1 = box
    _panel(draw, box, 'SECTION MAP  ·  aisle 2, LLW')
    statuses = state.get('statuses', {})
    counts = {k: 0 for k in HUD_STATUS_LABEL}
    hidden = 0
    for code, status in statuses.items():
        parsed = _parse_code(code)
        if parsed and parsed[3] == 2:
            hidden += 1
        elif status in counts:
            counts[status] += 1
    # World x maps to the panel width; each side is a block of 3 tier rows.
    mx0, mx1 = x0 + 40, x1 - 40
    xmin, xmax = 1.0, 9.4
    sx = lambda x: mx0 + (x - xmin) / (xmax - xmin) * (mx1 - mx0)
    cell, gap = 26, 4
    top_side, aisle_top = y0 + 64, y0 + 64 + 3 * (cell + gap) + 6
    aisle_bot = aisle_top + 70
    bottom_side = aisle_bot + 6
    rows = {'L': lambda tier: top_side + (3 - tier) * (cell + gap),   # Tier 3 furthest from the aisle.
            'R': lambda tier: bottom_side + (tier - 1) * (cell + gap)}
    draw.text((x0 + 18, top_side - 20), 'B-L', font=hud_font(13, True), fill=HUD_DIM)
    draw.text((x0 + 18, bottom_side + 3 * (cell + gap) - 2), 'B-R', font=hud_font(13, True), fill=HUD_DIM)
    for label, tier in (('T3', 3), ('T2', 2), ('T1', 1)):
        draw.text((x1 - 34, rows['L'](tier) + 5), label, font=hud_font(12), fill=HUD_DIM)
        draw.text((x1 - 34, rows['R'](tier) + 5), label, font=hud_font(12), fill=HUD_DIM)
    # Aisle and coordinate ticks.
    y_aisle = lambda y: aisle_top + (7.05 - y) / (7.05 - 4.95) * (aisle_bot - aisle_top)
    draw.rectangle((mx0 - 10, aisle_top, mx1 + 10, aisle_bot), fill='#12171d')
    for x in range(2, 10):
        draw.line((sx(x), aisle_bot - 6, sx(x), aisle_bot), fill=HUD_LINE)
    # Trail, view wedge, robot arrow.
    trail = state.get('trail', [])
    if len(trail) > 1:
        draw.line([(sx(x), y_aisle(y)) for x, y in trail], fill='#3d6b8f', width=3)
    if state.get('robot_xy') is not None:
        rx, ry = state['robot_xy']
        yaw = state.get('robot_yaw', 0.0)
        px, py = sx(rx), y_aisle(ry)
        # Screen y is flipped relative to world y.
        half = _hm.radians(state.get('view_half_fov_deg', 38.6))
        reach = 90
        wedge = [(px, py)] + [(px + reach * _hm.cos(yaw + a), py - reach * _hm.sin(yaw + a))
                              for a in (-half, -half / 2, 0, half / 2, half)]
        draw.polygon(wedge, fill='#1f3a52', outline='#3d6b8f')
        size = 15
        tip = (px + size * _hm.cos(yaw), py - size * _hm.sin(yaw))
        left = (px + size * 0.8 * _hm.cos(yaw + 2.5), py - size * 0.8 * _hm.sin(yaw + 2.5))
        right = (px + size * 0.8 * _hm.cos(yaw - 2.5), py - size * 0.8 * _hm.sin(yaw - 2.5))
        draw.polygon([tip, left, right], fill='#ffffff')
    focus = state.get('focus_code')
    for code, status in statuses.items():
        parsed = _parse_code(code)
        if not parsed or parsed[3] == 2:
            continue
        side, column, tier, _ = parsed
        if not 1 <= column <= len(HUD_COLUMNS_X) or side not in rows:
            continue
        cx, cy = sx(HUD_COLUMNS_X[column - 1]), rows[side](tier)
        rect = (cx - cell / 2, cy, cx + cell / 2, cy + cell)
        draw.rounded_rectangle(rect, radius=5, fill=HUD_STATUS.get(status, HUD_STATUS['grey']))
        if code == focus:
            draw.rounded_rectangle((rect[0] - 4, rect[1] - 4, rect[2] + 4, rect[3] + 4), radius=7, outline='#ffffff',
                                   width=3)
    # Legend with counts.
    ly = bottom_side + 3 * (cell + gap) + 22
    lx = x0 + 20
    font = hud_font(17)
    for key in ('grey', 'amber', 'green', 'red'):
        draw.rounded_rectangle((lx, ly + 2, lx + 18, ly + 20), radius=4, fill=HUD_STATUS[key])
        text = f'{HUD_STATUS_LABEL[key]} {counts[key]}'
        draw.text((lx + 26, ly), text, font=font, fill=HUD_TEXT)
        lx += 26 + draw.textlength(text, font=font) + 26
    if hidden:
        draw.text((lx, ly), f'+{hidden} hidden behind', font=hud_font(15), fill=HUD_DIM)


def _decision(draw, state, box):
    x0, y0, x1, y1 = box
    _panel(draw, box, 'LATEST DECISION')
    used, budget = state.get('second_looks_used', 0), state.get('second_look_budget')
    counter = f"second looks {used}" + (f" / {budget}" if budget is not None else '')
    counter += f"   ·   faults confirmed {state.get('faults_confirmed', 0)}"
    font = hud_font(15, True)
    draw.text((x1 - 18 - draw.textlength(counter, font=font), y0 + 12), counter, font=font, fill=HUD_DIM)
    decision = state.get('decision')
    if not decision:
        draw.text((x0 + 18, y0 + 48), 'No decision yet: following the fixed route.', font=hud_font(20), fill=HUD_DIM)
        return
    head = decision.get('action_id', '')
    draw.text((x0 + 18, y0 + 42), _fit(draw, head, hud_font(26, True), x1 - x0 - 200), font=hud_font(26, True),
              fill=HUD_TEXT)
    meta = f"{decision.get('source', '')} @ {decision.get('t', 0):.1f}s"
    draw.text((x1 - 18 - draw.textlength(meta, font=hud_font(15)), y0 + 50), meta, font=hud_font(15), fill=HUD_DIM)
    mid = x0 + (x1 - x0) * 0.52
    draw.text((x0 + 18, y0 + 84), 'WHY', font=hud_font(14, True), fill='#6fb6ff')
    for i, line in enumerate(_wrap(draw, decision.get('reason', ''), hud_font(18), mid - x0 - 36, 4)):
        draw.text((x0 + 18, y0 + 104 + 25 * i), line, font=hud_font(18), fill=HUD_TEXT)
    draw.line((mid, y0 + 86, mid, y1 - 16), fill=HUD_LINE, width=2)
    draw.text((mid + 18, y0 + 84), 'EVIDENCE', font=hud_font(14, True), fill='#6fb6ff')
    for i, item in enumerate(decision.get('evidence', [])[:4]):
        yy = y0 + 104 + 25 * i
        draw.ellipse((mid + 20, yy + 8, mid + 28, yy + 16), fill=HUD_DIM)
        draw.text((mid + 36, yy), _fit(draw, item, hud_font(17), x1 - mid - 54), font=hud_font(17), fill=HUD_TEXT)


def _sensors(draw, state, box):
    x0, y0, x1, y1 = box
    _panel(draw, box, 'SENSORS')
    history = state.get('history', {})
    # Minimum span per channel keeps sensor noise flat instead of autoscaling it into a fake signal.
    channels = [('gamma', 'Gamma', 'µSv/h', '{:.2f}', '#b38cff', 1.0), ('surface_c', 'Max surface', '°C', '{:.1f}', '#ff8a5c', 8.0),
                ('h2_ppm', 'Hydrogen', 'ppm', '{:.0f}', '#5cc8ff', 50.0), ('hiss', 'Hiss', 'score', '{:.2f}', '#c9d36a', 1.0)]
    width = (x1 - x0 - 36) / len(channels)
    for i, (key, name, unit, fmt, color, min_span) in enumerate(channels):
        cx0 = x0 + 18 + i * width
        cx1 = cx0 + width - 14
        values = list(history.get(key, []))[-150:]
        draw.text((cx0, y0 + 40), name, font=hud_font(15), fill=HUD_DIM)
        current = fmt.format(values[-1]) if values else '—'
        draw.text((cx0, y0 + 60), current, font=hud_font(30, True), fill=HUD_TEXT)
        draw.text((cx0 + draw.textlength(current, font=hud_font(30, True)) + 6, y0 + 74), unit, font=hud_font(14),
                  fill=HUD_DIM)
        gy0, gy1 = y0 + 104, y1 - 14
        draw.rounded_rectangle((cx0, gy0, cx1, gy1), radius=6, fill='#12171d')
        if len(values) > 1:
            lo, hi = min(values), max(values)
            span = max(hi - lo, min_span)
            pts = [(cx0 + 6 + (cx1 - cx0 - 12) * j / (len(values) - 1), gy1 - 6 - (gy1 - gy0 - 12) * (v - lo) / span)
                   for j, v in enumerate(values)]
            draw.line(pts, fill=color, width=2)


def _ticker(draw, state, box):
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill='#0c0f13')
    events = state.get('events', [])[-4:]
    if not events:
        return
    font = hud_font(17)
    slot = (x1 - x0 - 40) / 4
    for i, (t, text) in enumerate(events):
        color = '#ff8a84' if '!' in text else HUD_TEXT
        line = f'{t:5.1f}s  {text}'
        draw.text((x0 + 20 + i * slot, y0 + 11), _fit(draw, line, font, slot - 24), font=font, fill=color)


def compose_demo(frame_rgb, state):
    """One 1920x1080 HUD frame. `frame_rgb` is the onboard RGB (numpy HxWx3 or PIL); see the schema in the docstring
    of tools/preview_demo_hud.py or the T7 report. Missing fields are drawn as empty, never raise."""
    canvas = _HImage.new('RGB', (HUD_W, HUD_H), HUD_BG)
    draw = _HDraw.Draw(canvas)
    left = (24, 20, 1166, 1000)
    _camera(canvas, frame_rgb, state, (left[0], left[1], left[2], left[1] + 896))
    rx0, rx1 = 1190, 1896
    draw.text((rx0, 18), _fit(draw, state.get('title', 'Spot inspection round'), hud_font(22, True), rx1 - rx0),
              font=hud_font(22, True), fill=HUD_TEXT)
    _minimap(draw, state, (rx0, 56, rx1, 450))
    _decision(draw, state, (rx0, 466, rx1, 712))
    _sensors(draw, state, (rx0, 728, rx1, 1000))
    _ticker(draw, state, (0, 1028, HUD_W, HUD_H))
    return canvas


def report_card_demo(state, truth_score=None):
    """Final card: counts, every red drum with its reason, and the efficiency score against ground truth."""
    canvas = _HImage.new('RGB', (HUD_W, HUD_H), HUD_BG)
    draw = _HDraw.Draw(canvas)
    draw.text((90, 60), 'INSPECTION REPORT', font=hud_font(44, True), fill=HUD_TEXT)
    draw.text((90, 118), state.get('title', ''), font=hud_font(22), fill=HUD_DIM)
    statuses = state.get('statuses', {})
    visible = {c: s for c, s in statuses.items() if (_parse_code(c) or (0, 0, 0, 1))[3] == 1}
    x = 90
    for key in ('red', 'amber', 'green', 'grey'):
        n = sum(s == key for s in visible.values())
        draw.rounded_rectangle((x, 176, x + 260, 286), radius=12, fill=HUD_PANEL)
        draw.rounded_rectangle((x, 176, x + 10, 286), radius=5, fill=HUD_STATUS[key])
        draw.text((x + 30, 188), str(n), font=hud_font(48, True), fill=HUD_TEXT)
        draw.text((x + 30, 250), HUD_STATUS_LABEL[key], font=hud_font(18), fill=HUD_DIM)
        x += 290
    _panel(draw, (90, 320, 1180, 1000), 'FAULTS FOUND')
    reds = state.get('red_reasons', {})
    y = 364
    for code in sorted(c for c, s in visible.items() if s == 'red'):
        draw.text((116, y), code, font=hud_font(24, True), fill=HUD_STATUS['red'])
        draw.text((330, y + 3), _fit(draw, reds.get(code) or 'fault confirmed (no reason logged)', hud_font(20), 820), font=hud_font(20), fill=HUD_TEXT)
        y += 44
        if y > 950:
            break
    if y == 364:
        draw.text((116, y), 'No faults confirmed.', font=hud_font(22), fill=HUD_DIM)
    _panel(draw, (1210, 320, 1830, 1000), 'EFFICIENCY')
    rows = [('Drums inspected', f"{sum(s in ('green', 'red') for s in visible.values())} / {len(visible)}"),
            ('Second looks used', f"{state.get('second_looks_used', 0)}"
                                  + (f" / {state['second_look_budget']}" if state.get('second_look_budget') else '')),
            ('Faults confirmed', str(state.get('faults_confirmed', 0)))]
    if truth_score:
        rows += [('Faults in scene', str(truth_score.get('faults_total', '—'))),
                 ('Found', str(truth_score.get('found', '—'))),
                 ('False reds', str(truth_score.get('false_red', '—'))),
                 ('Missed', str(truth_score.get('missed', '—')))]
        if truth_score.get('found') is not None and state.get('second_looks_used'):
            rows.append(('Faults per second look', f"{truth_score['found'] / state['second_looks_used']:.2f}"))
    for i, (name, value) in enumerate(rows):
        yy = 370 + 62 * i
        draw.text((1240, yy), name, font=hud_font(21), fill=HUD_DIM)
        draw.text((1800 - draw.textlength(value, font=hud_font(28, True)), yy - 4), value, font=hud_font(28, True),
                  fill=HUD_TEXT)
    return canvas
