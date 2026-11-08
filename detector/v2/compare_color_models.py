"""Evaluate the old checkpoint on exactly the same test inputs as the retrain."""
import argparse,json,sys,time,hashlib
from pathlib import Path
from ultralytics import YOLO
from train_compare import evaluate,write
p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--run',type=Path,required=True);p.add_argument('--old',type=Path,required=True);a=p.parse_args()
frames=json.loads((a.data/'manifest.json').read_text())['frames'];a.run.mkdir(parents=True,exist_ok=True)
old=evaluate(YOLO(str(a.old)),a.data,a.run/'old_model','test',frames)
new=json.loads((a.run/'results.json').read_text());report={'old_checkpoint_sha256':hashlib.sha256(a.old.read_bytes()).hexdigest(),'new_checkpoint_sha256':new['best_sha256'],
 'threshold':{'confidence':.25,'iou':.5},'old':old,'new':new['test'],'groups':{},'scope':'Matched synthetic held-out inputs; original split assignments retained. Primary-target classification includes misses.'}
for k,v in old['by_source_group'].items():
 w=new['test']['by_source_group'][k];report['groups'][k]={'old':v,'new':w,'delta_percentage_points':round((w['accuracy']-v['accuracy'])*100,3)}
legacy=old['by_source_group']['legacy_yellow'];assert legacy['images']==75 and legacy['correct']==72,legacy
write(a.run/'comparison.json',report)
lines=['# Expanded-color YOLO26s comparison','', '| Test group | Images | Old accuracy | Retrained accuracy | Change |','|---|---:|---:|---:|---:|']
for k,v in report['groups'].items():lines.append(f"| {k} | {v['old']['images']} | {v['old']['accuracy']:.1%} | {v['new']['accuracy']:.1%} | {v['delta_percentage_points']:+.1f} pp |")
lines+=['','Same images, confidence 0.25 and IoU 0.5. All values are primary-barrel condition accuracy, including missed detections. The legacy yellow group is the exact unchanged 75-image subset used for the prior 96% result. Other groups are separate, newly held-out scene seeds.','',f"Retrained all-box test mAP50: {new['test']['overall']['metrics/mAP50(B)']:.4f}; mAP50–95: {new['test']['overall']['metrics/mAP50-95(B)']:.4f}.",f"Training: {new['training_seconds']:.1f} s. Training and evaluation: {new['total_seconds']:.1f} s.", '', 'All samples use warehouse context. The supplied blue-teal ILW asset pack matches the original warehouse material; earlier blue-painted LLW studio captures are excluded. Synthetic held-out performance does not establish real-world accuracy.']
(a.run/'comparison.md').write_text('\n'.join(lines)+'\n');print('MATCHED_COMPARISON '+json.dumps(report['groups']),flush=True)
