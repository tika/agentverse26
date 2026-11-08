"""Read one run folder into the report's single run model.

Two input formats are supported. Add a loader here to support another; nothing else needs to change.

  framework  memory.json + telemetry.jsonl + decisions.jsonl (+ stills/, ground_truth.json)
             -- the contract in docs/report_framework/README.md
  canis.v1   report.json + log.jsonl + evidence/ (+ cosmos-responses.jsonl)
             -- the warehouse-v3 adaptive-aisle takes (out/canis_wh/<take>/canis_adaptive_aisle)

The run model only holds logged values. A field that was not logged is None, never a guess.
"""
import json
import struct
from pathlib import Path

CLASS_TO_FINDING = {'normal': None, 'ok': None, 'rust': 'corrosion', 'corrosion': 'corrosion',
                    'bulge': 'bulge', 'dent': 'bulge'}


def jl(p):
    p = Path(p)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def jload(p):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else None


def png_size(p):
    try:
        with open(p, 'rb') as f:
            head = f.read(24)
        if head[:8] == b'\x89PNG\r\n\x1a\n':
            return struct.unpack('>II', head[16:24])
    except OSError:
        pass
    return None


def detect(run):
    run = Path(run)
    if (run / 'report.json').exists() and (run / 'log.jsonl').exists():
        return 'canis.v1'
    if (run / 'memory.json').exists():
        return 'framework'
    raise SystemExit(f'{run}: no report.json+log.jsonl (canis.v1) or memory.json (framework) found')


def load(run, fmt='auto'):
    run = Path(run).resolve()
    fmt = detect(run) if fmt == 'auto' else fmt
    model = {'framework': load_framework, 'canis.v1': load_canis_v1}[fmt](run)
    model['source_format'] = fmt
    model['run_dir'] = str(run)
    return model


# ---- framework contract ----------------------------------------------------------------------------
def load_framework(run):
    mem = jload(run / 'memory.json')
    stills = mem.get('stills') or []
    drums = []
    for d in sorted(mem['drums'], key=lambda d: d['drum_id']):
        views = []
        for i, vd in enumerate(d.get('view_detail') or []):
            cls, conf = max(vd.items(), key=lambda kv: kv[1]) if vd else (None, None)
            views.append(dict(image=None, cls=cls, conf=conf, box=None, size=None, t=None, label=f'view {i + 1}'))
        for s in (x for x in stills if x.get('drum') == d['drum_id']):
            img = run / s['file']
            views.insert(0, dict(image=str(img) if img.exists() else None, cls=s.get('class'), conf=s.get('conf'),
                                 box=s.get('box') or d.get('best_box'), size=png_size(img), t=s.get('t'),
                                 label=s.get('kind', 'evidence')))
        drums.append(dict(
            drum_id=d['drum_id'], x=d.get('x'), y=d.get('y'), category=d.get('category'), status=d['status'],
            reason=d.get('reason'), finding=d.get('finding') or 'none', confidence=d.get('confidence'),
            views=d.get('views'), fault_views=d.get('fault_views'), view_list=views,
            dose_rate_at_drum_uSv_h=d.get('dose_rate_at_drum_uSv_h'), heat_rise_c=d.get('heat_rise_c'),
            swab=d.get('swab'), air_c=None, rh=None, h2=None,
            label=({'readable': d['label_readable'] != 'unreadable', 'reads': [], 'crop': None}
                   if d.get('label_readable') is not None else None)))
    tele = []
    for t in jl(run / 'telemetry.jsonl'):
        pose = t.get('pose') or t.get('truth') or [None, None]
        tele.append(dict(t=t['t'], x=pose[0], y=pose[1], gamma=t.get('dose_rate_uSv_h'), h2=t.get('hydrogen_ppm'),
                         air_c=t.get('temperature_c'), rh=t.get('relative_humidity_pct'), dose_uSv=t.get('dose_uSv')))
    events = [dict(t=x['t'], drum=x.get('drum'), kind=x.get('kind', ''), text=x.get('text', ''),
                   source=x.get('source', ''), latency_ms=x.get('latency_ms')) for x in jl(run / 'decisions.jsonl')]
    gt = jload(run / 'ground_truth.json')
    truth = None
    if gt:
        truth = {k: bool(v.get('faults')) if 'faults' in v else (v.get('rust', 0) > 0 or v.get('bulge', 0) > 0)
                 for k, v in gt['drums'].items()}
    return dict(
        id=run.name if run.name != 'run' else run.parent.name, note=mem.get('_note'),
        started=mem.get('started_utc'), duration_s=mem.get('duration_s'),
        dose_uSv=mem.get('dose_uSv'), budget_uSv=mem.get('budget_uSv'),
        expected=mem.get('expected_drums', len(drums)), aisle_length_m=mem.get('aisle_length_m'),
        drums=drums, tele=tele, events=events, truth=truth,
        tech=[('Detector', mem.get('detector')), ('Decision rule', mem.get('rule')),
              ('Detector calls', f"{mem.get('yolo_calls')} made, {mem.get('yolo_failures')} failed"
               if mem.get('yolo_calls') is not None else None)])


# ---- canis.v1 take ---------------------------------------------------------------------------------
def load_canis_v1(run):
    rep = jload(run / 'report.json')
    log = jl(run / 'log.jsonl')
    prov = rep.get('provenance') or {}
    cos = rep.get('cosmos_decisions') or []
    targets = {}
    for c in cos:
        targets.update((c.get('context') or {}).get('targets') or {})

    drums, doses = [], []
    for c in cos:
        s = (c.get('context') or {}).get('last_sensors') or {}
        if s.get('mission_dose_mSv') is not None:
            doses.append(s['mission_dose_mSv'])
    for pid, r in sorted(rep['records'].items()):
        views, fault, samples = [], 0, []
        for v in r.get('views') or []:
            p = v.get('prediction') or {}
            img = run / 'evidence' / v['image'] if v.get('image') else None
            cls = p.get('class_name')
            if CLASS_TO_FINDING.get(cls):
                fault += 1
            label = ''
            if v.get('image'):
                stage, _, k = v['image'].rsplit('.', 1)[0].split(pid + '-', 1)[-1].partition('-')
                label = f"{'retry' if stage == 'retry' else 'pass 1'} · view {k}" if k.isdigit() else stage
            s = v.get('sensor_sample') or {}
            samples.append(s)
            if s.get('mission_dose_mSv') is not None:
                doses.append(s['mission_dose_mSv'])
            views.append(dict(image=str(img) if img and img.exists() else None, cls=cls, conf=p.get('confidence'),
                              box=p.get('bbox_xyxy'), size=png_size(img) if img else None, t=s.get('time_s'),
                              label=label, pitch=v.get('body_pitch_deg'), frame=v.get('frame'),
                              sha=v.get('input_sha256'), gamma=s.get('dose_rate_uSv_h')))
        faults = sorted({CLASS_TO_FINDING[v['cls']] for v in views if CLASS_TO_FINDING.get(v['cls'])})
        finding = '+'.join(faults) if faults else 'none'
        rel = [v['conf'] for v in views if v['conf'] is not None and
               (CLASS_TO_FINDING.get(v['cls']) if faults else not CLASS_TO_FINDING.get(v['cls']))]
        verdict = r.get('verdict')
        status = {'OK': 'OK', 'Confirmed defect': 'Confirmed defect', 'Suspect': 'Suspect'}.get(verdict, "Couldn't inspect")
        reads = [x for x in r.get('plate_reads') or []]
        readable = r.get('identity') == 'verified'
        reason = None
        if status == "Couldn't inspect":
            reason = ('the drum label could not be read after a retry, so its identity is not confirmed'
                      if not readable else f'logged as {verdict}')
        crop = None
        for name in sorted((run / 'evidence').glob(f'{pid}-*plate-region.png')):
            crop = str(name)
        g = [s['dose_rate_uSv_h'] for s in samples if s.get('dose_rate_uSv_h') is not None]
        air = [s['temperature_c'] for s in samples if s.get('temperature_c') is not None]
        rh = [s['relative_humidity_pct'] for s in samples if s.get('relative_humidity_pct') is not None]
        h2v = [s['hydrogen_ppm'] for s in samples if s.get('hydrogen_ppm') is not None]
        h2s = next((s for s in samples if s.get('hydrogen_status')), {})
        tg = targets.get(pid) or [None, None, None]
        drums.append(dict(
            drum_id=pid, x=tg[0], y=tg[1], category=None, status=status, reason=reason, finding=finding,
            confidence=max(rel) if rel else None, views=len(views), fault_views=fault, view_list=views,
            dose_rate_at_drum_uSv_h=max(g) if g else None,
            heat_rise_c=None,  # provenance: surface LWIR withheld (no verified drum-pixel attribution)
            swab=None, air_c=max(air) if air else None, rh=max(rh) if rh else None,
            h2=dict(ppm=max(h2v) if h2v else None, status=h2s.get('hydrogen_status'),
                    limit=h2s.get('hydrogen_detection_limit_ppm')),
            label=dict(readable=readable, reads=reads, crop=crop)))

    tele, state = [], None
    for x in log:
        if x['kind'] == 'run_state':
            state = x
        elif x['kind'] == 'sensor_reading' and state is not None:
            pose = state.get('pose_xy') or [None, None]
            tele.append(dict(t=x['t_sim_s'], x=pose[0], y=pose[1], gamma=x.get('gamma_uSv_h'), h2=x.get('h2_ppm'),
                             air_c=x.get('air_c'), rh=None, dose_uSv=None, phase=state.get('phase')))

    events = []
    for x in log:
        k, t = x['kind'], x.get('t_sim_s')
        if k == 'cosmos_decision':
            events.append(dict(t=t, drum=x['action'] if x['action'] in rep['records'] else None,
                               kind='plan', action=x['action'], text=x.get('reason', ''),
                               source='Cosmos planner', latency_ms=x.get('latency_ms')))
        elif k == 'plate_read':
            ok = x.get('match')
            events.append(dict(t=t, drum=x.get('target'), kind='label',
                               text=f"Label read as “{x.get('read')}”: " + ('matches.' if ok else 'does not match.'),
                               source='Label reader', latency_ms=None))
        elif k == 'assessment':
            events.append(dict(t=t, drum=x.get('package_id'), kind='rating',
                               text=f"Rated {x.get('status', '').upper()} ({x.get('reason', '')}), "
                                    f"from frames {', '.join(str(i) for i in x.get('evidence_frame_ids') or [])}.",
                               source='CANIS rules', latency_ms=None))
    events.sort(key=lambda e: (e['t'] if e['t'] is not None else 0))

    return dict(
        id=run.parent.name if run.name == 'canis_adaptive_aisle' else run.name, note=None,
        started=None, duration_s=rep.get('duration_s'),
        dose_uSv=max(doses) * 1000 if doses else None, budget_uSv=None,
        expected=len(targets) or len(drums), aisle_length_m=None,
        drums=drums, tele=tele, events=events, truth=None,
        tech=[('Simulator', prov.get('simulation')),
              ('Repository base', prov.get('repository_base')),
              ('Detector', prov.get('detector')),
              ('Detector SHA-256', prov.get('detector_sha256')),
              ('Planner', prov.get('planner')),
              ('Planner record', prov.get('cosmos_transcript')),
              ('Scene seed', rep.get('scene_seed')),
              ('Camera mount', f"{rep['fixed_mount_deg']}° fixed" if rep.get('fixed_mount_deg') is not None else None),
              ('Surface temperature', prov.get('surface_lwir')),
              ('Log lines', f'{len(log)} ({sum(1 for x in log if x["kind"] == "detection")} detections, '
                            f'{sum(1 for x in log if x["kind"] == "cosmos_decision")} planner decisions)')])
