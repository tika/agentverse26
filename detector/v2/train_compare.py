"""Train and independently test one of the two four-condition YOLO26 models."""
import argparse,json,time,hashlib,shutil,math
from pathlib import Path
import numpy as np

NAMES=['normal','rust','bulge','rust_and_bulge']
def write(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2,allow_nan=False));temp.replace(path)

def ious(box,boxes):
    if not len(boxes):return np.zeros(0)
    a=np.maximum(box[:2],boxes[:,:2]);b=np.minimum(box[2:],boxes[:,2:]);inter=np.prod(np.maximum(0,b-a),axis=1)
    return inter/np.maximum(1e-9,np.prod(box[2:]-box[:2])+np.prod(boxes[:,2:]-boxes[:,:2],axis=1)-inter)

def evaluate(model,data,run,split,frames):
    from PIL import Image,ImageDraw
    metric=model.val(data=str(data/'runtime.yaml'),split=split,imgsz=384,batch=32,device=0,workers=4,
                     conf=.001,iou=.7,max_det=300,plots=True,project=str(run/'evaluation'),name=split,exist_ok=True,verbose=False)
    images=sorted((data/'images'/split).glob('*.png'));lookup={f['name']:f for f in frames if f['split']==split}
    cm=np.zeros((4,4),int);miss=np.zeros(4,int);fp=np.zeros(4,int);target_cm=np.zeros((4,4),int);targets=[];saved=[]
    predictions=model.predict(source=[str(p) for p in images],stream=True,batch=32,imgsz=384,conf=.001,iou=.7,max_det=300,device=0,verbose=False)
    for image,result in zip(images,predictions):
        boxes=result.boxes.cpu();all_p=np.column_stack((boxes.xyxy.numpy(),boxes.conf.numpy(),boxes.cls.numpy())) if len(boxes) else np.zeros((0,6))
        p=all_p[all_p[:,4]>=.25];truth=[]
        for line in (data/'labels'/split/(image.stem+'.txt')).read_text().splitlines():
            c,x,y,w,h=map(float,line.split());truth.append([int(c),(x-w/2)*384,(y-h/2)*384,(x+w/2)*384,(y+h/2)*384])
        truth=np.asarray(truth);pairs=[]
        for gi,g in enumerate(truth):
            overlap=ious(g[1:],p[:,:4])
            pairs.extend((float(overlap[pi]),gi,pi) for pi in np.flatnonzero(overlap>=.5))
        used_g=set();used_p=set()
        for _,gi,pi in sorted(pairs,reverse=True):
            if gi in used_g or pi in used_p:continue
            used_g.add(gi);used_p.add(pi);cm[int(truth[gi,0]),int(p[pi,5])]+=1
        for gi,g in enumerate(truth):
            if gi not in used_g:miss[int(g[0])]+=1
        for pi,pred in enumerate(p):
            if pi not in used_p:fp[int(pred[5])]+=1
        f=lookup[image.stem];overlap=ious(np.asarray(f['target_box']),p[:,:4]);pi=int(overlap.argmax()) if len(overlap) else None
        pred=int(p[pi,5]) if pi is not None and overlap[pi]>=.5 else None
        if pred is not None:target_cm[f['condition'],pred]+=1
        target=dict(image=image.name,seed=f['seed'],condition=f['condition'],predicted=pred,correct=pred==f['condition'],
                    category=f['category'],tier=f['tier'],severity=f['severity'],source_color=f.get('source_color','yellow' if f['category']=='LLW' else 'metallic'),origin=f.get('origin','legacy'),confidence=float(p[pi,4]) if pred is not None else None)
        targets.append(target);saved.append(dict(image=image.name,boxes=all_p.tolist(),target=target))
        if not target['correct'] and len(list((run/'evaluation'/split/'errors').glob('*.jpg'))) < 10:
            dest=run/'evaluation'/split/'errors';dest.mkdir(parents=True,exist_ok=True);im=Image.open(image).convert('RGB');d=ImageDraw.Draw(im)
            d.rectangle(f['target_box'],outline='yellow',width=3)
            for box in p:d.rectangle(box[:4].tolist(),outline='red',width=2);d.text((float(box[0]),float(box[1])),NAMES[int(box[5])],fill='white',stroke_width=1,stroke_fill='black')
            im.save(dest/(image.stem+'.jpg'),quality=92)
    per_class={}
    for c,name in enumerate(NAMES):
        tp=int(cm[c,c]);per_class[name]=dict(tp=tp,false_positives=int(cm[:,c].sum()-tp+fp[c]),false_negatives=int(cm[c].sum()-tp+miss[c]),
            precision=tp/max(1,int(cm[:,c].sum()+fp[c])),recall=tp/max(1,int(cm[c].sum()+miss[c])))
    by_category={k:dict(images=sum(t['category']==k for t in targets),accuracy=sum(t['correct'] for t in targets if t['category']==k)/max(1,sum(t['category']==k for t in targets))) for k in ('LLW','ILW')}
    by_tier={str(k):dict(images=sum(t['tier']==k for t in targets),accuracy=sum(t['correct'] for t in targets if t['tier']==k)/max(1,sum(t['tier']==k for t in targets))) for k in (1,2)}
    attr={}
    for name,positive in (('rust',(1,3)),('bulge',(2,3))):
        tp=sum(t['condition'] in positive and t['predicted'] in positive for t in targets);fn=sum(t['condition'] in positive and t['predicted'] not in positive for t in targets)
        false=sum(t['condition'] not in positive and t['predicted'] in positive for t in targets)
        attr[name]=dict(precision=tp/max(1,tp+false),recall=tp/max(1,tp+fn),tp=tp,fp=false,fn=fn)
    groups={}
    for t in targets:
        key=t['origin']+'_'+t['source_color'];groups.setdefault(key,[]).append(t)
    by_source_group={k:dict(images=len(v),correct=sum(x['correct'] for x in v),accuracy=sum(x['correct'] for x in v)/len(v),missed=sum(x['predicted'] is None for x in v)) for k,v in groups.items()}
    normal=[t for t in targets if t['condition']==0]
    result=dict(images=len(images),overall={k:float(v) for k,v in metric.results_dict.items()},per_class=per_class,
                ultralytics_per_class=json.loads(json.dumps(metric.summary(),default=lambda v:v.item())),
                fixed_confidence=.25,confusion_matrix=cm.tolist(),missed_by_class=miss.tolist(),spurious_by_class=fp.tolist(),
                target_confusion_matrix=target_cm.tolist(),target_correct=sum(t['correct'] for t in targets),target_total=len(targets),
                target_accuracy=sum(t['correct'] for t in targets)/len(targets),target_missed=sum(t['predicted'] is None for t in targets),
                false_alarm_normal=sum(t['predicted'] in (1,2,3) for t in normal),normal_targets=len(normal),
                attribute_metrics=attr,by_category=by_category,by_tier=by_tier,by_source_group=by_source_group,speed_ms=metric.speed)
    write(run/'evaluation'/f'{split}_predictions.json',saved);write(run/'evaluation'/f'{split}_metrics.json',result);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--scale',choices=('n','s'),required=True);p.add_argument('--data',type=Path,required=True);p.add_argument('--run',type=Path,required=True);p.add_argument('--initial');p.add_argument('--epochs',type=int,default=50);p.add_argument('--lr',type=float,default=.001)
    a=p.parse_args();run=a.run;run.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    from ultralytics import YOLO
    import torch,ultralytics
    assert torch.cuda.device_count()==1
    hardware=dict(gpu=torch.cuda.get_device_name(0),torch=torch.__version__,ultralytics=ultralytics.__version__,cuda=torch.version.cuda)
    write(run/'hardware.json',hardware)
    (a.data/'runtime.yaml').write_text('path: '+str(a.data)+'\ntrain: '+('train.txt' if (a.data/'train.txt').exists() else 'images/train')+'\nval: images/val\ntest: images/test\nnames:\n'+''.join(f'  {i}: {v}\n' for i,v in enumerate(NAMES)))
    model=YOLO(a.initial or f'yolo26{a.scale}.pt')
    def epoch(trainer):
        status=dict(state='training',model=f'yolo26{a.scale}',epoch=min(trainer.epoch+1,trainer.epochs),epochs=trainer.epochs,
                    seconds=round(time.perf_counter()-started,2),metrics={k:float(v) for k,v in trainer.metrics.items() if math.isfinite(float(v))})
        write(run/'progress.json',status);print('TRAIN_PROGRESS '+json.dumps(status),flush=True)
    def check_sampler(trainer):
        sampler=trainer.train_loader.sampler;name=type(sampler).__name__
        info=dict(sampler=name,rect=bool(trainer.args.rect),shuffle=bool(name=='RandomSampler' or getattr(sampler,'shuffle',False)),images=len(trainer.train_loader.dataset))
        write(run/'sampler.json',info)
        assert info['shuffle'] and not info['rect'],info
    model.add_callback('on_train_start',check_sampler)
    model.add_callback('on_fit_epoch_end',epoch)
    model.train(data=str(a.data/'runtime.yaml'),imgsz=384,epochs=a.epochs,patience=12,batch=64,device=0,workers=4,cache='ram',
                project=str(run),name='train',exist_ok=True,seed=42,deterministic=True,amp=True,
                rect=False,optimizer='AdamW',lr0=a.lr,lrf=.01,weight_decay=.0005,warmup_epochs=2.,
                hsv_h=.005,hsv_s=.12,hsv_v=.15,degrees=3,translate=.04,scale=.15,fliplr=.5,flipud=0,
                mosaic=0,mixup=0,copy_paste=0,close_mosaic=0,plots=True,save=True,verbose=False)
    train_s=time.perf_counter()-started;best=run/'train/weights/best.pt';shutil.copy2(best,run/'best.pt')
    model=YOLO(str(run/'best.pt'));assert list(model.names.values())==NAMES
    frames=json.loads((a.data/'manifest.json').read_text())['frames']
    write(run/'progress.json',dict(state='evaluating',model=f'yolo26{a.scale}',training_seconds=train_s));print('TRAIN_EVALUATING '+a.scale,flush=True)
    val=evaluate(model,a.data,run,'val',frames);test=evaluate(model,a.data,run,'test',frames)
    timings=[];images=sorted((a.data/'images/test').glob('*.png'))
    for i in range(35):
        torch.cuda.synchronize();t=time.perf_counter();model.predict(images[i%len(images)],imgsz=384,conf=.25,device=0,verbose=False);torch.cuda.synchronize()
        if i>=5:timings.append((time.perf_counter()-t)*1000)
    report=dict(model=f'yolo26{a.scale}',classes=NAMES,hardware=hardware,best_sha256=hashlib.sha256((run/'best.pt').read_bytes()).hexdigest(),
                training_seconds=round(train_s,2),initial_checkpoint=a.initial or f'yolo26{a.scale}.pt',epochs_requested=a.epochs,learning_rate=a.lr,total_seconds=round(time.perf_counter()-started,2),dataset_manifest_sha256=hashlib.sha256((a.data/'manifest.json').read_bytes()).hexdigest(),
                val=val,test=test,warm_inference_ms={'median':float(np.median(timings)),'p95':float(np.percentile(timings,95))},
                scope='Synthetic warehouse frames, disjoint generation seeds; not real-world accuracy. Primary-target accuracy includes missed detections.',
                model_selection='Best validation fitness; test used only for final evaluation.',operating_confidence=.25)
    write(run/'results.json',report);write(run/'progress.json',dict(state='complete',model=f'yolo26{a.scale}',test=test['overall']))
    print('MODEL_COMPLETE '+json.dumps({k:report[k] for k in ('model','best_sha256','training_seconds','total_seconds','warm_inference_ms')}),flush=True)

if __name__=='__main__':main()
