"""Render demo HUD previews from a fabricated mid-run state, without Isaac or Modal.

    python3 tools/preview_demo_hud.py [OUT_DIR] [CAMERA_JPG]

compose_demo(frame_rgb, state) reads these `state` fields (all optional):
    title: str
    t: float                         simulation seconds
    activity: str                    'Walking', 'Scanning B-R column 05', 'Second look at B-L-07-T3'
    body_pitch_deg: float            non-zero shows the simulated body-pitch badge
    yolo_boxes: [{box: [x0,y0,x1,y1] in frame pixels, label: 'drum'|'corrosion'|'bulge', conf: float, drum_code: str}]
    statuses: {code: 'grey'|'amber'|'green'|'red'|'hidden'}   code 'B-L-07-T3', '-D2' suffix = hidden back drum
    focus_code: str                  drum ringed on the minimap
    robot_xy: (x, y) m, robot_yaw: rad (world), view_half_fov_deg: float (default 38.6)
    trail: [(x, y), ...]
    decision: {t: float, action_id: str, reason: str, source: str, evidence: [str]}
    second_looks_used: int, second_look_budget: int|None, faults_confirmed: int
    history: {gamma: [float], surface_c: [float], h2_ppm: [float], hiss: [float]}
    events: [(t, text), ...]         text containing '!' is shown red
report_card_demo(state, truth_score) also reads red_reasons: {code: str};
truth_score: {faults_total, found, false_red, missed}.
"""
import math
from pathlib import Path
import random
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'hot'))
from demo_hud import compose_demo, report_card_demo  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'out' / 'hud_preview'


def camera_frame(path=None):
    if path and Path(path).exists():
        image = Image.open(path).convert('RGB')
        side = min(image.size)
        left, top = (image.width - side) // 2, (image.height - side) // 2
        return image.crop((left, top, left + side, top + side)).resize((640, 640))
    image = Image.new('RGB', (640, 640), '#3b3f42')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 470, 640, 640), fill='#55585a')
    for tier in range(3):
        for col in range(2):
            x0, y0 = 160 + col * 170, 360 - tier * 150
            draw.rectangle((x0, y0, x0 + 150, y0 + 140), fill='#d8b423', outline='#8a7316', width=3)
    return image


def fabricate(t, second_look=False):
    rng = random.Random(7)
    statuses = {}
    robot_x = 1.3 + t * 0.06
    for side in 'LR':
        for col, x in enumerate((2.79, 3.41, 4.09, 4.71, 5.39, 6.01, 6.69, 7.31, 7.99, 8.61), 1):
            for tier in (1, 2, 3):
                code = f'B-{side}-{col:02d}-T{tier}'
                status = 'grey'
                if x < robot_x + 1.0:
                    status = rng.choices(['green', 'amber', 'red'], [0.82, 0.1, 0.08])[0]
                statuses[code] = status
                statuses[code + '-D2'] = 'hidden'
    statuses['B-L-05-T3'] = 'amber'
    if second_look:
        statuses['B-L-05-T3'] = 'red'
    trail = [(1.3 + i * 0.05, 6.0 + 0.03 * math.sin(i / 6)) for i in range(int((robot_x - 1.3) / 0.05))]
    n = 180
    history = {'gamma': [0.4 + 0.25 * math.exp(-((i - 120) / 25) ** 2) + 0.02 * rng.random() for i in range(n)],
               'surface_c': [19.5 + (9 if i > 140 else 0) * min(1, (i - 140) / 15) + 0.2 * rng.random() for i in range(n)],
               'h2_ppm': [max(0, (i - 150) * 6 + 5 * rng.random()) for i in range(n)],
               'hiss': [0.1 + 0.05 * rng.random() for i in range(n)]}
    boxes = [{'box': [150, 50, 330, 200], 'label': 'drum', 'conf': 0.94, 'drum_code': 'B-L-05-T3'},
             {'box': [330, 50, 500, 200], 'label': 'drum', 'conf': 0.91, 'drum_code': 'B-L-06-T3'},
             {'box': [150, 200, 330, 350], 'label': 'drum', 'conf': 0.95, 'drum_code': 'B-L-05-T2'},
             {'box': [190, 90, 280, 160], 'label': 'corrosion', 'conf': 0.81 if second_look else 0.52,
              'drum_code': 'B-L-05-T3'}]
    decision = ({'t': t - 1.2, 'action_id': 'second_look_B-L-05-T3', 'source': 'Cosmos Reason 2',
                 'reason': 'One weak corrosion box on B-L-05-T3 and its neighbour is clear; a closer view settles it.',
                 'evidence': ['YOLO corrosion 0.52, 1 frame', 'surface 19.8 °C (ambient 19.5)', 'no H2 near column 05',
                              'budget left: 3 of 5']}
                if second_look else
                {'t': t - 2.0, 'action_id': 'continue_patrol', 'source': 'Cosmos Reason 2',
                 'reason': 'Column 04 is clear on all three tiers in two frames each; nothing ambiguous to revisit.',
                 'evidence': ['6 drums green, 2 frames each', 'gamma 0.41 µSv/h (baseline)', 'no thermal anomaly']})
    return {'title': 'Dense hall · aisle 2 LLW · seed 7', 't': t,
            'activity': 'Second look at B-L-05-T3' if second_look else 'Scanning B-L column 05',
            'body_pitch_deg': 10.0, 'yolo_boxes': boxes, 'statuses': statuses, 'focus_code': 'B-L-05-T3',
            'robot_xy': (robot_x, 6.0), 'robot_yaw': math.radians(35), 'trail': trail, 'decision': decision,
            'second_looks_used': 2 if second_look else 1, 'second_look_budget': 5, 'faults_confirmed': 3 if second_look else 2,
            'history': history,
            'events': [(t - 9.0, 'Column 04 clear'), (t - 5.5, 'YOLO corrosion 0.52 at B-L-05-T3'),
                       (t - 1.2, 'Second look requested'), (t, 'Corrosion confirmed at B-L-05-T3!' if second_look
                                                           else 'Scanning column 05')],
            'red_reasons': {'B-L-05-T3': 'corrosion, YOLO 0.81 on 2 views',
                            'B-R-02-T1': 'bulge, YOLO 0.77 on 2 views',
                            'B-R-03-T2': 'surface +11 °C vs air, H2 140 ppm within 1 m'}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frame = camera_frame(sys.argv[2] if len(sys.argv) > 2 else None)
    compose_demo(frame, fabricate(48.0)).save(OUT / 'hud_midrun.png')
    state = fabricate(61.0, second_look=True)
    compose_demo(frame, state).save(OUT / 'hud_second_look.png')
    report_card_demo(state, {'faults_total': 5, 'found': 4, 'false_red': 0, 'missed': 1}).save(OUT / 'hud_report.png')
    print('\n'.join(str(OUT / n) for n in ('hud_midrun.png', 'hud_second_look.png', 'hud_report.png')))


if __name__ == '__main__':
    main()
