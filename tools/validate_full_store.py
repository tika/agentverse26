"""Audit a downloaded full-store run and extract real MP4 review frames.

python3 tools/validate_full_store.py out/hot/RUN_ID
Requires numpy and opencv-python for video/trajectory checks.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import cv2
import numpy as np

root=Path(sys.argv[1]).resolve()
report=json.loads((root/'full_store/report.json').read_text())
memory=json.loads((root/'full_store/memory.json').read_text())
decisions=json.loads((root/'full_store/decisions.json').read_text())
log=[json.loads(s) for s in (root/'full_store/log.jsonl').read_text().splitlines()]
yolo=[json.loads(s) for s in (root/'yolo_requests.jsonl').read_text().splitlines()]
fallback_path=root/'cosmos_visual_checks.jsonl'
fallback=[json.loads(s) for s in fallback_path.read_text().splitlines()] if fallback_path.exists() else []
errors=[]
if len(report['drums'])!=28:errors.append('Report does not contain all 28 drums')
view_sources=Counter()
for key,e in report['coverage']['drums'].items():
    for view in e['views']:view_sources[view.get('source','unspecified')]+=1
    if not e['complete']:continue
    if len(e['views'])<2:errors.append(key+': completion without two views')
    for i,a in enumerate(e['views']):
        for b in e['views'][i+1:]:
            angle=abs((a['bearing_rad']-b['bearing_rad']+math.pi)%(2*math.pi)-math.pi)
            if math.dist(a['position_m'],b['position_m'])<.35-1e-6 or angle<math.radians(12)-1e-6:
                errors.append(key+': viewpoints are not independent')
    ident=memory[key]['checks'].get('id',{})
    if not (ident.get('result')=='match' or ident.get('confirmed')):errors.append(key+': unresolved plate marked complete')
    if not math.isfinite(memory[key]['checks'].get('thermal',{}).get('surface_c',float('nan'))):errors.append(key+': missing thermal')
    if any(v.get('review_required') for v in e['views']) and not memory[key]['checks'].get('visual',{}).get('review_required'):
        errors.append(key+': earlier uncertain visual assessment lost from memory')
video=root/'full_store.mp4';cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS);n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
if not cap.isOpened() or not fps:raise SystemExit('MP4 cannot be decoded')
duration=n/fps
if (int(cap.get(3)),int(cap.get(4)))!=(1920,1080):errors.append('Unexpected video size')
expected=len(log)+round(6*fps)
if n!=expected:errors.append(f'Frame count mismatch: {n} vs expected {expected}')
qa=root/'video_qa';qa.mkdir(exist_ok=True)
times=[0.,duration*.25,duration*.5,duration*.75,max(0,(len(log)-15)/fps),duration-1]
means=[]
for i,t in enumerate(times):
    cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read()
    if not ok:errors.append(f'Cannot decode frame at {t:.1f}s');continue
    cv2.imwrite(str(qa/f'frame_{i}_{t:.1f}s.jpg'),frame)
    means.append(float(frame[:668,:1280].mean()))
cap.release()
if means and min(means)<20:errors.append('A sampled chase view appears black')
xyz=np.array([r['truth'] for r in log]);est=np.array([r['estimate'] for r in log]);pose_error=np.linalg.norm(xyz[:,:2]-est[:,:2],axis=1)
metrics=dict(run_id=root.name,coverage=report['coverage']['counts'],end_status=report['round_status'],
    visual_assessments_needing_review=report.get('visual_assessments_needing_review'),
    yolo_requests=len(yolo),yolo_status_counts=dict(Counter(r['status'] for r in yolo)),
    yolo_model_runs=sorted({r.get('run_id','unknown') for r in yolo}),
    yolo_request_median_ms=round(float(np.median([r['wall_seconds'] for r in yolo]))*1000,1),
    planner_decisions=len(decisions['decisions']),planner_sources=dict(Counter(r['source'] for r in decisions['decisions'])),
    visual_fallback_calls=len(fallback),valid_visual_fallback_calls=sum(r.get('valid',False) for r in fallback),
    viewpoint_sources=dict(view_sources),
    pressure_screens={k:m['pressure_screen'] for k,m in memory.items() if m.get('pressure_screen',{}).get('suspected_pressurisation')},
    environment=report['environment'],estimated_travel_m=report['travelled_estimate_m'],
    ground_truth_travel_m=round(float(np.linalg.norm(np.diff(xyz[:,:2],axis=0),axis=1).sum()),2),
    localization_error_m=dict(median=round(float(np.median(pose_error)),3),max=round(float(pose_error.max()),3)),
    body_z_m=dict(min=round(float(xyz[:,2].min()),3),max=round(float(xyz[:,2].max()),3)),
    video=dict(path=str(video),duration_s=duration,fps=fps,frames=n,bytes=video.stat().st_size,
               sha256=hashlib.sha256(video.read_bytes()).hexdigest()),
    qa_frame_times_s=times,checks_passed=not errors,errors=errors)
(root/'validation.json').write_text(json.dumps(metrics,indent=2)+'\n')
print(json.dumps(metrics,indent=2))
if errors:raise SystemExit(1)
