"""Showcase copy: key moments in real time, the rest sped up uniformly so the total is under a minute."""
import bisect, json, subprocess, sys
import cv2
SRC, TELEM, OUT, FFMPEG = sys.argv[1:5]
TARGET_S, FPS = 58.0, 24
ts = [json.loads(l)['t'] for l in open(TELEM)]          # one telemetry row per walking frame
v = cv2.VideoCapture(SRC); n = int(v.get(cv2.CAP_PROP_FRAME_COUNT))
f = lambda t: bisect.bisect_left(ts, t)
real = [('rust catch + normal drum (A-L-01-T1, T2)', f(5.6), f(18.0)),
        ('first pass unclear, Cosmos asks for closer look (A-L-03-T3)', f(145.6), f(150.0)),
        ('comes back and confirms rust (A-L-03-T3)', f(206.0), f(216.5)),
        ('very end + summary', f(418.0), n)]
fast_ranges, prev = [], 0
for _, a, b in real:
    fast_ranges.append((prev, a)); prev = b
real_frames = sum(b - a for _, a, b in real)
fast_frames = sum(b - a for a, b in fast_ranges)
speed = fast_frames / (TARGET_S * FPS - real_frames)
keep = set()
for _, a, b in real:
    keep.update(range(a, b))
for a, b in fast_ranges:
    count = max(1, round((b - a) / speed))
    keep.update(a + int(i * speed) for i in range(count) if a + int(i * speed) < b)
print(f'speed {speed:.1f}x, real-time {real_frames / FPS:.1f}s, kept {len(keep)} frames = {len(keep) / FPS:.1f}s')
order = sorted(keep); index = {frame: i for i, frame in enumerate(order)}
for name, a, b in real:
    print(f'  output {index[a] / FPS:6.1f}s - {(index[b - 1] + 1) / FPS:6.1f}s  {name}')
ff = subprocess.Popen([FFMPEG, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', '1920x1080', '-r', str(FPS), '-i', '-',
                       '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', OUT], stdin=subprocess.PIPE)
written = i = 0
while True:
    ok, frame = v.read()
    if not ok:
        break
    if i in keep:
        ff.stdin.write(frame.tobytes()); written += 1
    i += 1
ff.stdin.close(); ff.wait()
print('decoded', i, 'written', written, 'ffmpeg exit', ff.returncode)
