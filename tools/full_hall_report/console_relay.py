"""Play a recorded CANIS walk into Levi's C.A.N.I.S. operator console (branch levi/canis-operator-console).

The console is a read-only WebSocket client (canis.v1). This relay replays a finished Isaac Sim run:
  isaac      ws://127.0.0.1:8765  third-person camera frames + map snapshot
  robot      ws://127.0.0.1:8766  robot pose (simulator pose, labelled) + first-person camera frames
  mission    ws://127.0.0.1:8769  run state (sim clock, target drum, planned stops) + inspection ledger records
  assessment ws://127.0.0.1:8771  one assessment per drum decision (drives camera result layer + map) + defect alerts
Frames are cut from the recorded HUD video and served over http://127.0.0.1:8790.
Nothing here is live: every run_state says RECORDED RUN. No simulator truth is sent (only the robot's own decisions).

    python console_relay.py prepare <run_dir> <video.mp4> <work_dir>
    python console_relay.py serve <run_dir> <work_dir>
Then open http://localhost:5178/?mode=live&feeds=isaac=ws://127.0.0.1:8765,robot=ws://127.0.0.1:8766,mission=ws://127.0.0.1:8769,assessment=ws://127.0.0.1:8771
"""
import asyncio
import bisect
import functools
import glob
import hashlib
import http.server
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

FPS_OUT = 12            # console frame rate (every 2nd video frame)
HTTP_PORT = 8790
PORTS = {'isaac': 8765, 'robot': 8766, 'mission': 8769, 'assessment': 8771}
ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / 'sim' / 'warehouse-v3' / 'map.json'


def ffmpeg():
    hits = glob.glob(str(ROOT.parent / 'team-repo/.venv/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*'))
    return hits[0] if hits else 'ffmpeg'


def prepare(run_dir, video, work):
    work = Path(work)
    for name, vf in (('third', f'fps={FPS_OUT},crop=1280:720:0:60'),
                     ('rgb', f'fps={FPS_OUT},crop=620:620:1290:60,scale=640:640')):
        out = work / 'frames' / name
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run([ffmpeg(), '-y', '-loglevel', 'error', '-i', str(video), '-vf', vf, '-q:v', '4',
                        str(out / '%05d.jpg')], check=True)
        print(name, len(list(out.glob('*.jpg'))), 'frames')


def load(run_dir, work):
    run_dir, work = Path(run_dir), Path(work)
    tel = [json.loads(line) for line in (run_dir / 'telemetry.jsonl').read_text().splitlines() if line.strip()]
    dets = [json.loads(line) for line in (run_dir / 'detections.jsonl').read_text().splitlines() if line.strip()]
    decs = [json.loads(line) for line in (run_dir / 'decisions.jsonl').read_text().splitlines() if line.strip()]
    memory = json.loads((run_dir / 'memory.json').read_text())['drums']
    n = min(len(list((work / 'frames' / 'third').glob('*.jpg'))), len(list((work / 'frames' / 'rgb').glob('*.jpg'))))
    step = round(len(tel) / max(1, n)) or 1
    frames = []                      # (t_sim, telemetry row, frame number) at FPS_OUT
    for j in range(n):
        k = min(len(tel) - 1, j * step)
        frames.append((tel[k]['t'], tel[k], j + 1))
    run_id = 'recorded-' + run_dir.name
    times = [f[0] for f in frames]

    def frame_at(t):
        i = max(0, min(len(frames) - 1, bisect.bisect_left(times, t)))
        return f'{run_id}-f{frames[i][2]:05d}'

    ev = {feed: [] for feed in PORTS}
    base = lambda kind, src, t: {'schema': 'canis.v1', 'kind': kind, 'source': {'id': src, 'kind': src.split('-')[0]},
                                 't_sim_s': round(t, 3), 'quality': 'ok'}
    sha = hashlib.sha256(MAP.read_bytes()).hexdigest()
    layout = json.loads(MAP.read_text())
    ev['isaac'].append((0.0, {**base('map_snapshot', 'isaac-recorded', 0.0), 'frame': 'world_m_zup', 'map_sha256': sha,
                              'drum_count': len(layout['drums'])}))
    stops = sorted({(round(r['pose'][0], 1), round(r['pose'][1], 1)) for r in tel if r['phase'] == 'look'})
    for t, row, num in frames:
        fid = f'{run_id}-f{num:05d}'
        x, y, yaw = row['pose']
        ev['isaac'].append((t, {**base('camera_frame', 'isaac-recorded', t), 'camera_id': 'third_person', 'frame_id': fid,
                                'width': 1280, 'height': 720, 'fps': FPS_OUT, 'encoding': 'jpeg', 'units': 'srgb',
                                'uri': f'http://127.0.0.1:{HTTP_PORT}/frames/third/{num:05d}.jpg',
                                'caption': 'RECORDED Isaac Sim run (chase camera, HUD from the recording)'}))
        ev['robot'].append((t, {**base('robot_pose', 'robot-recorded', t), 'frame': 'world_m_zup', 'xyz_m': [x, y, 0.5],
                                'rpy_deg': [0.0, 0.0, round(math.degrees(yaw), 2)], 'pose_source': 'simulator_pose',
                                'health': 'ok', 'operating_mode': 'autonomous inspection (recorded run)'}))
        ev['robot'].append((t, {**base('camera_frame', 'robot-recorded', t), 'camera_id': 'rgb', 'frame_id': fid,
                                'width': 640, 'height': 640, 'fps': FPS_OUT, 'encoding': 'jpeg', 'units': 'srgb',
                                'uri': f'http://127.0.0.1:{HTTP_PORT}/frames/rgb/{num:05d}.jpg',
                                'caption': 'RECORDED inspection camera, 640x640 77 deg (CANIS focus overlay baked in)'}))
        rs = {**base('run_state', 'mission-recorded', t), 'mode': 'live', 'run_id': run_id, 'sim_clock_s': round(t, 3),
              'mission_state': f"RECORDED RUN · {row['phase']}", 'planned_packages': len(memory),
              'planned_path_m': [[s[0], s[1]] for s in stops] or None}
        if rs['planned_path_m'] is None:
            rs.pop('planned_path_m')
        if row.get('look'):
            rs['target_package_id'] = row['look']
        ev['mission'].append((t, rs))
    views = {}
    pos = {d['display_id']: (d['x'], d['y']) for d in layout['drums']}
    tel_t = [r['t'] for r in tel]
    for d in dets:
        fid = frame_at(d['t'])
        tb = d['target_box']
        counted = d.get('drum_box_matched') or d.get('faults') or (tb[0] > -40 and tb[1] > -40 and tb[2] < 680 and tb[3] < 680)
        if not counted:
            continue
        views.setdefault(d['drum'], []).append((d, fid))
        # view label from the real viewing angle: camera ray vs the drum's aisle-facing normal
        r = tel[max(0, min(len(tel) - 1, bisect.bisect_left(tel_t, d['t'])))]
        dx, dy = pos[d['drum']][0] - r['pose'][0], pos[d['drum']][1] - r['pose'][1]
        ang = math.degrees(math.atan2(abs(dx), abs(dy)))
        d['view_label'] = 'front' if ang < 30 else 'oblique'
        if True:
            ev['mission'].append((d['t'], {**base('inspection_record', 'mission-recorded', d['t']), 'run_id': run_id,
                                           'package_id': d['drum'], 'frame_id': fid,
                                           'view': d['view_label'],
                                           'finding': ('+'.join(d['faults']) + ' ' + json.dumps(d['conf'])) if d['faults'] else None,
                                           'evidence': [{'kind': 'camera_frame', 'ref': fid}]}))
    final_t = {}
    for x in decs:
        if 'second look' not in x['text']:
            final_t[x['drum']] = (x['t'], x['text'])
    for m in memory:
        code = m['drum_id']
        t, text = final_t.get(code, (frames[-1][0], f"{code} {m['status']}"))
        status = {'Confirmed defect': 'defect', 'OK': 'ok'}.get(m['status'], 'unsure')
        types = [c for c in ('corrosion', 'bulge') if c in m['finding']] if status == 'defect' else []
        vs = views.get(code, [])
        evidence = [fid for _, fid in vs] or [frame_at(t)]
        shapes = []
        if vs:
            d, fid = vs[-1]
            x0, y0, x1, y1 = [max(0.0, min(640.0, v)) for v in d['target_box']]
            if x1 - x0 > 4 and y1 - y0 > 4:
                shapes.append({'camera_id': 'rgb', 'frame_id': fid, 'bbox_px': [x0, y0, x1 - x0, y1 - y0]})
        ev['assessment'].append((t, {**base('assessment', 'assessment-recorded', t), 'assessment_id': f'{run_id}-{code}',
                                     'run_id': run_id, 'package_id': code, 'tier': m['tier'], 'status': status,
                                     'defect_types': types, 'reason': f"CANIS rules, recorded run: {text}",
                                     'evidence_frame_ids': sorted(set(evidence)), 'shapes': shapes}))
        if status in ('defect', 'unsure'):
            ev['assessment'].append((t, {**base('alert', 'assessment-recorded', t), 'alert_id': f'{run_id}-alert-{code}',
                                         'severity': 'alert' if status == 'defect' else 'warning',
                                         'title': f"{code} {'DEFECT' if status == 'defect' else 'SUSPECT'}"
                                                  + (f" ({'+'.join(types)})" if types else ''),
                                         'detail': text, 'package_id': code,
                                         'evidence': [{'kind': 'camera_frame', 'ref': e} for e in evidence[-2:]],
                                         'proposed_action': {'text': 'Engineer to check this package (recorded run)',
                                                             'status': 'proposed_not_sent'}}))
    for feed in ev:
        ev[feed].sort(key=lambda e: e[0])
    return ev, frames[-1][0]


class Clock:
    def __init__(self, duration):
        self.duration, self.gen, self.start, self.offset = duration, 0, time.monotonic(), 0.0

    def restart(self, keep_time=False):
        self.offset = self.offset + self.duration + 5.0 if keep_time else 0.0
        self.start, self.gen = time.monotonic(), self.gen + 1

    def now(self):
        t = time.monotonic() - self.start
        if t > self.duration + 5.0:
            self.restart(keep_time=True)
            t = 0.0
        return t


SEQ = {}


def stamp(msg, offset):
    key = (msg['source']['id'], msg['kind'], msg.get('camera_id'))
    SEQ[key] = SEQ.get(key, -1) + 1
    out = {**msg, 'seq': SEQ[key]}
    for k in ('t_sim_s', 'sim_clock_s'):
        if k in out:
            out[k] = round(out[k] + offset, 3)
    return out


async def serve(run_dir, work):
    import websockets
    ev, duration = load(run_dir, work)
    clock = Clock(duration)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(work))

    class Cors(handler.func):
        def end_headers(self):
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'max-age=3600')
            super().end_headers()

        def log_message(self, *a):
            pass
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', HTTP_PORT), functools.partial(Cors, directory=str(work)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def make(feed):
        async def h(ws):
            if feed == 'isaac':
                clock.restart()               # a fresh console page starts the recording from the beginning
            gen, i, events = clock.gen, 0, ev[feed]
            try:
                while True:
                    t = clock.now()
                    if clock.gen != gen:
                        gen, i = clock.gen, 0
                    batch = []
                    while i < len(events) and events[i][0] <= t:
                        batch.append(stamp(events[i][1], clock.offset))
                        i += 1
                    if batch:
                        await ws.send(json.dumps(batch[-40:] if feed in ('isaac', 'robot') else batch))
                    await asyncio.sleep(1 / 24)
            except websockets.ConnectionClosed:
                return
        return h
    servers = [await websockets.serve(make(f), '127.0.0.1', p, max_size=None) for f, p in PORTS.items()]
    print(f'relay up: {duration:.0f} s recording, frames on http://127.0.0.1:{HTTP_PORT}', flush=True)
    await asyncio.gather(*(s.wait_closed() for s in servers))


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        prepare(*sys.argv[2:5])
    else:
        asyncio.run(serve(sys.argv[2], sys.argv[3]))
