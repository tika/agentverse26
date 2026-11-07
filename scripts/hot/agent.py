# Cosmos-driven inspection agent. Load after sensing.py and scenario_lib.py, then a scenario file
# that only authors the world (hot drum, contamination, wrong records) and calls run_agent(...).
# Perception and navigation use onboard sensors; Cosmos Reason 2 chooses every action from the set the
# safety layer offers. Corrosion and bulge come from the YOLO26s detector API when configured
# (DETECTOR_API_URL/KEY/SECRET), otherwise from a labelled simulator-segmentation stand-in.
import time as _time

AISLE_Y = 6.0
STANDOFF = {'B': 5.62, 'C': 6.38}       # Centre-aisle standoff line for rows B and C.
CONFIG = load_config()                  # Criteria and limits: sim/inspection_config.json (see docs).
HEAT_RISE_C = CONFIG['pressure_screen']['temperature_above_ambient_c']
DOSE_AMBER, DOSE_BACKOFF = CONFIG['thresholds']['controlled_zone'], CONFIG['thresholds']['hot_spot']
SPEED_NEAR_DRUMS = CONFIG['robot']['max_speed_near_drums_mps']
H2_DETECTED_PPM = 10.0                  # Reporting floor above sensor noise; the docs set no H2 alarm level.
FOLLOWUP_TIMEOUT_S = 8.0
DETECT_EVERY_FRAMES = 6                 # 2 Hz at 12 fps; the detector API is not called every frame.

if 'ptz' not in state:
    ptz = Camera('/World/SpotCamPTZ', resolution=(640, 480))
    ptz.initialize()
    ptz.prim.GetAttribute('clippingRange').Set(Gf.Vec2f(0.05, 40))
    state['ptz'] = ptz
PTZ = state['ptz']
PTZ.prim.GetAttribute('focalLength').Set(70.0)  # Zoom for plate text.


def plate_world(drum):
    facing = ROW_FACING[drum['row']]
    return np.array([drum['x'], drum['y'] + facing * drum['radius'], drum['height'] * 0.6])


def aim_from_estimate(camera, p_true, yaw_true, estimate, target_world, mount=(0.35, 0.0, 0.45)):
    """Physical camera sits on the real body; it points using the robot's *estimated* pose."""
    c, s = math.cos(yaw_true), math.sin(yaw_true)
    eye = p_true + [c * mount[0] - s * mount[1], s * mount[0] + c * mount[1], mount[2]]
    ce_, se_ = math.cos(estimate[2]), math.sin(estimate[2])
    eye_est = estimate[:2] + [ce_ * mount[0] - se_ * mount[1], se_ * mount[0] + ce_ * mount[1]]
    rel = target_world[:2] - eye_est  # From the camera's own (estimated) position, not the body centre.
    ce, se = math.cos(-estimate[2]), math.sin(-estimate[2])
    body_dir = np.array([ce * rel[0] - se * rel[1], se * rel[0] + ce * rel[1]])
    world_dir = np.array([c * body_dir[0] - s * body_dir[1], s * body_dir[0] + c * body_dir[1]])
    _aim(camera, eye, eye + [world_dir[0], world_dir[1], target_world[2] - eye[2]])


class Agent:
    def __init__(self, number, title, scene, patrol):
        self.number, self.title, self.scene = number, title, scene
        self.patrol = [np.array(w, float) for w in patrol]
        self.route = list(self.patrol)
        self.patrol_index = 0
        self.followed_up = set()
        self.status, self.message = 'PATROL', 'Inspection round started'
        self.findings, self.decisions, self.events = {}, [], []
        self.flagged, self.ids_read, self.plates_tried = [], {}, set()
        self.history = {'gamma': [], 'h2': []}
        self.trail, self.swab_contact, self.swab_text = [], None, 'idle'
        self.mic_db, self.nearest = -60.0, ('-', 0.0)
        self.look, self.face, self.hold, self.speed = None, None, False, SPEED_NEAR_DRUMS
        self.action = {'id': 'continue_patrol', 'kind': 'patrol'}
        self.last_decision_t, self.pending_decision = -99.0, True
        self.hiss_frames, self.cosmos = 0, None
        self.data = {}
        job = scene.get('job_drums') or [d['id'] for d in inventory if d['row'] in STANDOFF and d['category'] == 'ILW']
        self.memory = InspectionMemory(job)
        self.detector = detector_available() and not state.get('yolo_vision')
        self.detections = []

    def event(self, t, text):
        self.events.append((t, text))
        print(f'[hot] {self.number} {t:4.1f}s {text}', flush=True)

    def add_finding(self, t, fid, **fields):
        if fid in self.findings:
            self.findings[fid].update(fields, last_t=round(t, 2))
            return False
        self.findings[fid] = {'id': fid, 't': round(t, 2), 'last_t': round(t, 2), **fields}
        self.pending_decision = True
        return True


STATUS_COLORS = {'inspecting': (235, 240, 245), 'good': (60, 220, 140), 'attention': (255, 190, 70),
                 'bad': (255, 80, 80)}
CHECKS = ('id', 'thermal', 'visual')  # A drum counts as inspected once all three are done.


class InspectionMemory:
    """What the robot knows about each drum on this round: checks done, evidence, and a status."""

    def __init__(self, drum_ids):
        self.drums = {d: {'checks': {}, 'status': 'none', 'reasons': [], 'last_t': None} for d in drum_ids}

    def record(self, drum_id, check, t, **evidence):
        entry = self.drums.setdefault(drum_id, {'checks': {}, 'status': 'none', 'reasons': [], 'last_t': None})
        entry['checks'][check] = {'t': round(t, 1), **evidence}
        entry['last_t'] = round(t, 1)

    def update_status(self, a):
        for drum_id, entry in self.drums.items():
            c, bad, attention = entry['checks'], [], []
            if drum_id in a.flagged:
                bad.append('alert raised')
            th = c.get('thermal')
            if th and th['delta_c'] >= HEAT_RISE_C:
                bad.append(f"surface {th['surface_c']:.0f} C, {th['delta_c']:+.0f} C vs air")
            vis = c.get('visual')
            if vis and 'rust_pct' in vis:
                rust = CONFIG['thresholds']['rust_pct']
                if vis['rust_pct'] > rust['failing']:
                    bad.append(f"rust {vis['rust_pct']:.0f}%")
                elif vis['rust_pct'] >= rust['tolerable']:
                    attention.append(f"rust {vis['rust_pct']:.0f}%")
            elif vis:
                if vis.get('rust_observed'):attention.append('YOLO visible rust; coverage not measured')
                if vis.get('bulge_observed'):attention.append('YOLO visible bulge; needs corroboration')
            ident = c.get('id')
            if ident:
                if ident['result'] == 'mismatch':
                    (bad if ident.get('confirmed') else attention).append(f"plate {ident['read']} vs record {ident['record']}")
                elif ident['result'] != 'match':
                    (bad if ident.get('tries', 1) >= 3 else attention).append(f"plate {ident['result']}")
            swab = c.get('swab')
            if swab and swab['positive']:
                bad.append(f"swab alpha {swab['alpha_bq_cm2']:.2f} Bq/cm2")
            if any(f.get('drum') == drum_id and f.get('confidence') == 'low' for f in a.findings.values()):
                attention.append('unconfirmed finding')
            done = all(k in c for k in CHECKS)
            entry['complete'] = done
            entry['reasons'] = bad or attention
            entry['missing'] = [k for k in CHECKS if k not in c]
            entry['status'] = ('bad' if bad else 'attention' if attention else 'good' if done
                               else 'inspecting' if c else 'none')

    def progress(self):
        """Compact view for Cosmos: what is done, what is missing, what is wrong."""
        return {DRUMS[d]['display_id']: {'status': e['status'], 'missing_checks': e.get('missing', list(CHECKS)),
                                         'issues': e['reasons']}
                for d, e in self.drums.items()}


def observe_for_memory(a, t, perception, reading, est):
    """Opportunistic checks while working: thermal and visual need a close enough, clear view."""
    for drum_id, px in perception['drum_px'].items():
        if drum_id not in a.memory.drums:
            continue
        d = DRUMS[drum_id]
        distance = math.dist(est[:2], (d['x'], d['y']))
        if distance < 4.5 and px >= 400 and drum_id in perception['drum_temps']:
            apparent = perception['drum_temps'][drum_id]
            surface = correct_emissivity(apparent, EMISSIVITY[d['category']], reading['temperature_c'])
            previous = a.memory.drums[drum_id]['checks'].get('thermal')
            if previous is None or distance < previous['range_m']:  # Keep the closest view.
                a.memory.record(drum_id, 'thermal', t, surface_c=round(surface, 1), apparent_c=round(apparent, 1),
                                delta_c=round(surface - reading['temperature_c'], 1), range_m=round(distance, 1))
        if not a.detector and not perception.get('yolo') and distance < 3.5 and px >= 1500:
            rust = a.data.get('rust_pct', {}).get(drum_id, 0.0)
            previous = a.memory.drums[drum_id]['checks'].get('visual')
            if previous is None or rust > previous['rust_pct']:
                a.memory.record(drum_id, 'visual', t, rust_pct=round(rust, 1), range_m=round(distance, 1),
                                detector='segmentation placeholder')
    vision=perception.get('yolo')
    if vision and vision['fresh'] and vision['status']=='ok':
        for observation in vision['associations']:
            drum_id=observation['drum_id']
            if drum_id not in a.memory.drums or observation['range_m']>4:continue
            previous=a.memory.drums[drum_id]['checks'].get('visual',{})
            a.memory.record(drum_id,'visual',t,
                rust_observed='corrosion' in observation['faults'] or previous.get('rust_observed',False),
                bulge_observed='bulge' in observation['faults'] or previous.get('bulge_observed',False),
                views=previous.get('views',0)+1,coverage_measured=False,
                range_m=round(observation['range_m'],2),detector='trained YOLO26s RGB API',model_run=vision['run_id'])


def observe_detections(a, t, per_drum, est):
    """YOLO26s results -> findings and the memory's visual check (close, clear drum box)."""
    for drum_id, entry in per_drum.items():
        d = DRUMS[drum_id]
        name = d['display_id']
        distance = math.dist(est[:2], (d['x'], d['y']))
        for kind in ('corrosion', 'bulge'):
            if entry[kind]:
                best = max(entry[kind], key=lambda e: e['confidence'])
                confidence = 'high' if any(e['band'] == 'confirm' for e in entry[kind]) else 'low'
                fid = f'{kind}_{drum_id}'
                extra = {'rust_pct_box_proxy': round(entry['rust_pct'] or 0, 1)} if kind == 'corrosion' else {}
                fresh = a.add_finding(t, fid, kind='visible_corrosion' if kind == 'corrosion' else 'bulge', drum=drum_id,
                                      detector='YOLO26s', detector_confidence=round(best['confidence'], 2),
                                      confidence=confidence, range_m=round(distance, 1), **extra)
                if fresh:
                    a.event(t, f"YOLO: {kind} on {name} ({best['confidence']:.2f}, {confidence})!")
                elif confidence == 'high':
                    a.findings[fid]['confidence'] = 'high'
        if drum_id in a.memory.drums and entry['drum_area'] >= 4000 and distance < 3.5:
            previous = a.memory.drums[drum_id]['checks'].get('visual')
            previous=previous or {}
            a.memory.record(drum_id, 'visual', t,
                            rust_observed=bool(entry['corrosion']) or previous.get('rust_observed',False),
                            bulge_observed=bool(entry['bulge']) or previous.get('bulge_observed',False),
                            coverage_measured=False, range_m=round(distance,1),
                            detector='YOLO26s', drum_confidence=round(entry['drum_conf'],2))


def draw_detections(canvas, detections):
    """Detector boxes on the first-person panel (the robot's own perception output)."""
    draw = ImageDraw.Draw(canvas)
    colors = {'drum': '#7cc4ff', 'corrosion': '#ff9f5e', 'bulge': '#ff6767'}
    for det in detections:
        x0, y0, x1, y1 = det['bbox_xyxy']
        color = colors.get(det['class_name'], 'white')
        width = 3 if det.get('decision_band') == 'confirm' else 1
        draw.rectangle((1280 + x0, y0, 1280 + x1, y1), outline=color, width=width)
        draw.text((1282 + x0, max(0, y0 - 15)), f"{det['class_name']} {det['confidence']:.2f}", font=FONT[14], fill=color)


def project_camera(camera, points):
    """World points -> pixel (u, v) and depth for a Camera, using its pose and intrinsics."""
    k = camera.get_intrinsics_matrix()
    position, quat = camera.get_world_pose(camera_axes='world')
    qw, qx, qy, qz = quat
    rot = np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                    [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                    [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
    local = (np.asarray(points) - position) @ rot  # Camera world axes: +x forward, +y left, +z up.
    depth = local[:, 0]
    u = k[0, 2] - k[0, 0] * local[:, 1] / np.maximum(depth, 1e-3)
    v = k[1, 2] - k[1, 1] * local[:, 2] / np.maximum(depth, 1e-3)
    return np.stack([u, v], 1), depth


def draw_memory_overlay(canvas, a, p):
    """Floor rings and tags per drum: none = no overlay; white in progress; green/amber/red by status."""
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    view = Image.new('RGBA', (1280, 720), (0, 0, 0, 0))  # Third-person overlay, clipped to its own panel.
    vdraw = ImageDraw.Draw(view)
    ring = np.linspace(0, 2 * math.pi, 40)
    for drum_id, entry in a.memory.drums.items():
        if entry['status'] == 'none':
            continue
        d, color = DRUMS[drum_id], STATUS_COLORS[entry['status']]
        r = d['radius'] + 0.14
        floor = np.stack([d['x'] + r * np.cos(ring), d['y'] + r * np.sin(ring), np.full_like(ring, 0.02)], 1)
        uv, depth = project_camera(THIRD, floor)
        on_screen = (uv[:, 0] > -200) & (uv[:, 0] < 1480) & (uv[:, 1] > -200) & (uv[:, 1] < 920)
        if (depth > 0.8).all() and on_screen.all():  # Skip rings too close to the chase camera to project well.
            vdraw.polygon([tuple(x) for x in uv], fill=color + (70,), outline=color + (255,), width=4)
            tag_uv, tdepth = project_camera(THIRD, [[d['x'], d['y'], d['height'] + 0.25]])
            tu, tv = tag_uv[0]
            if tdepth[0] > 0.3 and 0 <= tu < 1280 and 0 <= tv < 720:
                label = f"{d['display_id']} {entry['status'].upper()}"
                vdraw.rectangle((tu - 6 - 4.5 * len(label), tv - 14, tu + 6 + 4.5 * len(label), tv + 12), fill=(13, 19, 27, 200))
                vdraw.text((tu - 4.5 * len(label), tv - 11), label, font=FONT[16], fill=color + (255,))
        centre = project_bird(np.array([[d['x'], d['y']]]), p, d['height'])[0] + [1280, 360]
        rr = 26
        draw.ellipse((centre[0] - rr, centre[1] - rr, centre[0] + rr, centre[1] + rr), fill=color + (60,),
                     outline=color + (255,), width=4)
    layer.paste(view.crop((0, 0, 1280, 668)), (0, 0))  # Stop above the title banner.
    canvas.paste(Image.alpha_composite(canvas.convert('RGBA'), layer).convert('RGB'))
    # Job progress in the bird's-eye corner.
    draw = ImageDraw.Draw(canvas)
    counts = {k: sum(e['status'] == k for e in a.memory.drums.values()) for k in ('good', 'attention', 'bad', 'inspecting', 'none')}
    complete=sum(e.get('complete',False) for e in a.memory.drums.values())
    text = (f"JOB {complete}/{len(a.memory.drums)} checks complete   "
            f"good {counts['good']}  attention {counts['attention']}  bad {counts['bad']}")
    draw.rectangle((1284, 690, 1916, 716), fill='#0d131b')
    draw.text((1292, 694), text, font=FONT[16], fill='white')


def standoff_for(drum):
    return np.array([drum['x'], STANDOFF[drum['row']]])


def offered_actions(a, p_est, reading):
    """Safety layer: only physically sensible, safe actions are offered to Cosmos."""
    gamma_ok = reading['dose_rate_uSv_h'] <= DOSE_BACKOFF
    actions = [{'id': 'continue_patrol', 'description': 'Resume the ordered centre-aisle patrol'}]
    drums = sorted({f['drum'] for f in a.findings.values() if f.get('drum')})
    # The job: drums still missing checks can be inspected too (nearest two ahead along the round).
    todo = [d for d, e in a.memory.drums.items() if not e.get('complete',False) and d not in drums]
    todo.sort(key=lambda d: math.dist(p_est[:2], standoff_for(DRUMS[d])))
    drums += todo[:2]
    for drum_id in drums:
        drum = DRUMS[drum_id]
        name = drum['display_id']
        evidence = [f for f in a.findings.values() if f.get('drum') == drum_id]
        nearby = abs(p_est[0] - drum['x']) <= 1.5
        fresh_target = nearby and drum_id not in a.followed_up and drum_id not in a.flagged
        at_standoff = drum['row'] in STANDOFF and np.linalg.norm(p_est[:2] - standoff_for(drum)) < 0.35
        swabbed = f'swab_{drum_id}' in a.findings
        if drum['row'] in STANDOFF and not at_standoff and gamma_ok and fresh_target and any(f['kind'] != 'plate_unclear' for f in evidence):
            actions.append({'id': f'inspect_{name}', 'description': f'Walk to the 1 m standoff in front of {name}, face it, '
                            f'and measure it up close (thermal, gas, microphone, plate)'})
        low = any(f.get('confidence') == 'low' and f['kind'] != 'plate_unclear' for f in evidence)
        if low and gamma_ok and fresh_target and drum['row'] in STANDOFF:
            actions.append({'id': f'better_view_{name}', 'description':
                            f'Unsure about {name}: move to a closer or second viewing angle and re-measure (plate, thermal)'})
        if gamma_ok and at_standoff and not swabbed and drum_id not in a.flagged and any(f['kind'] == 'visible_corrosion' for f in evidence):
            actions.append({'id': f'swab_{name}', 'description': f'Stop and take a smear swab of the floor at the base of {name} (4 s)'})
        # Alerts need corroboration (two-cue principle, as in pressure_screen.py): confirmed heat plus gas or hiss
        # near the drum, a failed swab, or dose above the back-off level.
        hot = a.findings.get(f'thermal_{drum_id}', {}).get('confidence') == 'high'
        near = np.linalg.norm(p_est[:2] - [drum['x'], drum['y']]) < 3.0
        venting = near and ('gas_h2' in a.findings or 'acoustic_hiss' in a.findings)
        swab_failed = a.findings.get(f'swab_{drum_id}', {}).get('positive', False)
        if drum_id not in a.flagged and ((hot and venting) or swab_failed or not gamma_ok):
            evidence = []
            if hot:
                f = a.findings[f'thermal_{drum_id}']
                evidence.append(f"surface {f['surface_temp_c']:.0f} C, {f['surface_temp_c'] - f['air_temp_c']:+.0f} C vs air")
            if venting and 'gas_h2' in a.findings:
                evidence.append(f"H2 {a.gas.get('hydrogen_ppm', 0):.0f} ppm measured within 3 m of {name}")
            if venting and 'acoustic_hiss' in a.findings:
                evidence.append(f'sustained hiss near {name}')
            if swab_failed:
                evidence.append('swab above containment limit')
            if not gamma_ok:
                evidence.append('dose above back-off level')
            actions.append({'id': f'retreat_alert_{name}', 'description':
                            f"Raise an alert for {name} and back off. Corroborated evidence: {'; '.join(evidence)}"})
    return actions


def rules_choice(a, actions):
    """Fallback when Cosmos is unavailable: alert on heat with gas or hiss, swab corrosion, else inspect."""
    ids = {x['id'] for x in actions}
    kinds = {}
    for f in a.findings.values():
        if f.get('drum'):
            kinds.setdefault(DRUMS[f['drum']]['display_id'], set()).add(f['kind'])
    venting = {f['kind'] for f in a.findings.values()} & {'hydrogen', 'sustained_hiss'}
    for name, found in kinds.items():
        if 'thermal_hotspot' in found and venting and f'retreat_alert_{name}' in ids:
            return {'action_id': f'retreat_alert_{name}', 'reason': 'Rules: heat plus gas or hiss at standoff'}
    for name in kinds:
        if f'swab_{name}' in ids:
            return {'action_id': f'swab_{name}', 'reason': 'Rules: at standoff, sample for contamination'}
    if a.action['id'].startswith('swab_') and a.swab_contact is None:
        return {'action_id': 'continue_patrol', 'reason': 'Rules: sample complete'}
    for name in kinds:
        if f'better_view_{name}' in ids:
            return {'action_id': f'better_view_{name}', 'reason': 'Rules: low-confidence finding, get a better view'}
    for name in kinds:
        if f'inspect_{name}' in ids and not any(f'swab_{d}' in a.findings for d, e in DRUMS.items() if e['display_id'] == name):
            return {'action_id': f'inspect_{name}', 'reason': 'Rules: inspect new finding'}
    return {'action_id': 'continue_patrol', 'reason': 'Rules: nothing to inspect'}


def snapshot_for(a, t, p_est, reading):
    open_findings = [{k: v for k, v in f.items() if k not in ('last_t',)} for f in a.findings.values()]
    for f in open_findings:
        if f.get('drum'):
            f['drum'] = DRUMS[f['drum']]['display_id']
    return {'time_s': round(t, 1),
            'robot': {'estimated_position_m': [round(v, 2) for v in p_est[:2]], 'current_action': a.action['id'],
                      'stationary': a.hold, 'patrol_stops_completed': a.patrol_index,
                      'patrol_stops_total': len(a.patrol)},
            'readings': {'gamma_uSv_h': round(reading['dose_rate_uSv_h'], 1),
                         'hydrogen_ppm': round(a.gas.get('hydrogen_ppm', 0.0), 1),
                         'air_temp_c': round(reading['temperature_c'], 1),
                         'relative_humidity_pct': round(reading['relative_humidity_pct']),
                         'microphone_hiss_score': round(a.hiss['hiss_score'], 2)},
            'findings': open_findings,
            'inspection_progress': a.memory.progress(),
            'actions': a.actions}


def apply_action(a, choice, t, p_est):
    action_id = choice['action_id']
    a.action = {'id': action_id, 'since': t}
    drum = None
    for d in inventory:
        if action_id.endswith('_' + d['display_id']):
            drum = d
    if action_id == 'continue_patrol':
        a.status, a.hold, a.face, a.look, a.speed = 'PATROL', False, None, None, SPEED_NEAR_DRUMS
        a.route = a.patrol[a.patrol_index:]
        if not a.route:
            a.status = 'ROUND COMPLETE'
    elif action_id == 'hold':
        a.status, a.hold = ('ALERT' if a.flagged else 'HOLD'), True
    elif action_id.startswith('inspect_') and drum['row'] in STANDOFF:
        a.followed_up.add(drum['id'])
        a.status, a.hold, a.speed = 'INVESTIGATE', False, SPEED_NEAR_DRUMS
        a.route = [standoff_for(drum)]
        a.face = a.look = np.array([drum['x'], drum['y']])
    elif action_id.startswith('better_view_'):
        a.followed_up.add(drum['id'])
        target = standoff_for(drum)
        if np.linalg.norm(p_est[:2] - target) < 0.35:  # Already here: second angle along the aisle.
            target = target + [0.8 if p_est[0] <= drum['x'] else -0.8, 0.0]
        a.status, a.hold, a.speed = 'INVESTIGATE', False, SPEED_NEAR_DRUMS
        a.route = [target]
        a.face = a.look = np.array([drum['x'], drum['y']])
        a.data['reread'] = drum['id']
    elif action_id.startswith('swab_'):
        a.status, a.hold = 'SAMPLING', True
        centre = np.array([drum['x'], drum['y']])
        direction = (p_est[:2] - centre) / np.linalg.norm(p_est[:2] - centre)
        contact = centre + (drum['radius'] + 0.03) * direction
        a.swab_contact, a.swab_text = contact, f"smear at {drum['display_id']} base..."
        try:
            a.sensor.start_swab((float(contact[0]), float(contact[1]), 0.0), t, robot_stopped=True)
            a.data['swab_drum'] = drum['id']
        except (ValueError, RuntimeError) as error:
            a.event(t, f'Swab refused: {error}')
            a.swab_contact = None
    elif action_id.startswith('retreat_alert_'):
        a.status, a.hold, a.speed = 'RETREAT', False, SPEED_NEAR_DRUMS
        a.flagged.append(drum['id'])
        away = -1 if drum['x'] > p_est[0] else 1
        a.route = [np.array([float(np.clip(drum['x'] + away * a.scene.get('retreat_m', 3.5), 1.5, 18.0)), AISLE_Y])]
        a.face = np.array([drum['x'], drum['y']])
        a.look = a.face
        a.event(t, f"ALERT raised for {drum['display_id']}!")


def decide(a, t, frame_rgb, p_est, reading):
    a.actions = offered_actions(a, p_est, reading)
    snapshot = snapshot_for(a, t, p_est, reading)
    started = _time.perf_counter()
    if len(a.actions) == 1:
        apply_action(a, {'action_id': 'continue_patrol'}, t, p_est)
        a.last_decision_t, a.pending_decision = t, False
        a.message = 'Continuing ordered round'
        return
    answer = cosmos_call('decide', frame_rgb, snapshot) if a.use_cosmos else {}
    if not answer.get('valid') or answer.get('action_id') not in {action['id'] for action in a.actions}:
        choice = rules_choice(a, a.actions)
        source = 'rules (Cosmos ' + ('off' if not a.use_cosmos else answer.get('reason', answer.get('error', '?'))[:40]) + ')'
    else:
        choice, source = answer, 'Cosmos Reason 2'
    record = {'t': round(t, 2), 'action_id': choice['action_id'], 'reason': choice.get('reason', ''), 'source': source,
              'latency_s': round(answer.get('latency_s', _time.perf_counter() - started), 2),
              'offered': [x['id'] for x in a.actions], 'raw': answer.get('raw', '')[-600:]}
    a.decisions.append(record)
    a.cosmos = record
    if choice['action_id'] != a.action['id']:
        a.event(t, f"{'Cosmos' if source.startswith('Cosmos') else 'Rules'}: {choice['action_id']}")
    apply_action(a, choice, t, p_est)
    a.message = f"{choice['action_id']}: {choice.get('reason', '')}"
    a.last_decision_t, a.pending_decision = t, False


def read_plate_for(a, drum, t, p, yaw):
    """Point the PTZ at a drum's plate using the estimated pose and let Cosmos read it."""
    a.plates_tried.add(drum['id'])
    aim_from_estimate(PTZ, p, yaw, a.nav.fused, plate_world(drum))
    for _ in range(3):
        world.render()
    crop = _rgb(PTZ)
    Image.fromarray(crop).save(OUT / f"ptz_{drum['display_id']}_{t:04.1f}.jpg", quality=85)
    answer = cosmos_call('read_plate', crop)
    readability = answer.get('readability', 'unreadable')
    expected = a.scene['records'].get(drum['id'])  # What the inventory says is at this map position.
    plate_text = f"{answer['drum_id']} {answer['category']}" if readability == 'readable' else None
    a.ids_read[drum['id']] = plate_text
    a.data.setdefault('readability', {})[drum['id']] = readability
    tries = a.memory.drums.get(drum['id'], {}).get('checks', {}).get('id', {}).get('tries', 0) + 1
    if drum['id'] in a.memory.drums:
        result = readability if plate_text is None else ('match' if plate_text == expected else 'mismatch')
        prior = a.memory.drums[drum['id']]['checks'].get('id', {})
        a.memory.record(drum['id'], 'id', t, result=result, read=plate_text, record=expected, tries=tries,
                        confirmed=result == 'mismatch' and prior.get('read') == plate_text)
    unclear = f"plate_{drum['id']}"
    if plate_text is None:
        a.add_finding(t, unclear, kind='plate_unclear', drum=drum['id'], readability=readability,
                      raw_read=answer.get('raw_read'), confidence='low')
        a.event(t, f"Plate at {drum['display_id']} position {readability}: {answer.get('raw_read')}")
        return
    if unclear in a.findings:
        a.findings.pop(unclear)
        a.event(t, f"Plate {plate_text} read on second view")
    mismatch = f"record_{drum['id']}"
    if plate_text != expected:
        previous = a.findings.get(mismatch, {}).get('plate_read')
        confirmed = previous == plate_text  # Two agreeing reads before an inventory mismatch is believed.
        a.add_finding(t, mismatch, kind='inventory_mismatch', drum=drum['id'], plate_read=plate_text,
                      record=expected, confidence='high' if confirmed else 'low')
        a.event(t, f"Plate reads {plate_text}, record says {expected}" + ('! (confirmed)' if confirmed else ' (unconfirmed)'))
    else:
        if mismatch in a.findings:
            a.findings.pop(mismatch)
            a.event(t, f"Earlier misread cleared: plate {plate_text} matches record")
        else:
            a.event(t, f"Plate {plate_text} matches record")


def read_plates(a, t, p, yaw):
    """Spot CAM+-style PTZ zoom on the nearest unread aisle-facing plate ahead (one per frame)."""
    for drum in inventory:
        if drum['id'] in a.plates_tried or drum['row'] not in STANDOFF:
            continue
        rel = plate_world(drum)[:2] - a.nav.fused[:2]
        dist = float(np.linalg.norm(rel))
        ahead = math.cos(a.nav.fused[2]) * rel[0] + math.sin(a.nav.fused[2]) * rel[1]
        along = abs(a.nav.fused[0] - drum['x'])  # Plates face the aisle; read when roughly square to one.
        if dist < 2.5 and along < 1.0:
            read_plate_for(a, drum, t, p, yaw)
            return


def drive(a, est):
    """Lane-following controller: walk forward along the aisle centreline, turn in place when the heading
    error is large, and only turn to face a drum after arriving."""
    if a.route and np.linalg.norm(est[:2] - a.route[0]) < 0.2:
        a.route.pop(0)
        if a.status == 'PATROL':
            a.patrol_index += 1
            if not a.route:
                a.status = 'ROUND COMPLETE'
    x, y, yaw = est
    if a.route:
        goal = a.route[0]
        in_aisle = abs(goal[1] - AISLE_Y) < 0.5 and abs(y - AISLE_Y) < 0.6
        if in_aisle and abs(goal[0] - x) > 0.6:
            # Pure pursuit on the centreline: look 0.8 m ahead along the aisle towards the goal.
            ahead = x + math.copysign(min(0.8, abs(goal[0] - x)), goal[0] - x)
            track = np.array([ahead, AISLE_Y + 0.6 * (goal[1] - AISLE_Y) * (1 - min(1, abs(goal[0] - x) / 2))])
        else:
            track = goal
        heading = math.atan2(track[1] - y, track[0] - x)
        error = wrap(heading - yaw)
        distance = float(np.linalg.norm(goal - est[:2]))
        if distance < 0.5:  # Final approach: small steps without turning around.
            c, s = math.cos(yaw), math.sin(yaw)
            dx, dy = goal - est[:2]
            vx, vy = 0.8 * (c * dx + s * dy), 0.8 * (-s * dx + c * dy)
            wz = 1.2 * wrap((math.atan2(a.face[1] - y, a.face[0] - x) if a.face is not None else yaw) - yaw)
        else:
            vx = a.speed * max(0.0, math.cos(error)) if abs(error) < 0.6 else 0.0
            vy = 0.0
            wz = 1.4 * error
        return np.array([vx, vy, float(np.clip(wz, -0.8, 0.8))], dtype=np.float32)
    if a.face is not None:
        return np.array([0.0, 0.0, float(np.clip(1.2 * wrap(math.atan2(a.face[1] - y, a.face[0] - x) - yaw), -0.8, 0.8))],
                        dtype=np.float32)
    return np.zeros(3, dtype=np.float32)


def run_agent(a, name, duration=17.0, setup=None, use_cosmos=None, report_seconds=3.0):
    zero = np.zeros(3, dtype=np.float32)
    show_spills(False)
    a.use_cosmos = state.get('use_cosmos', True) if use_cosmos is None else use_cosmos
    config = copy.deepcopy(load_config())
    config['robot']['swab_duration_s'] = a.scene.get('swab_duration_s', 4.0)
    if a.scene.get('gas_vents'):
        config['gas_vents'] = a.scene['gas_vents']
    a.sensor = SensorWorld(inventory, config)
    if setup:
        setup(a)
    spot.restart_from_default_state(zero)
    world.step(render=False)
    p, yaw, _, _ = full_pose()
    a.nav = RealNav([p[0], p[1], yaw])  # Known docking pose at start; estimated from sensors afterwards.
    lagged = LaggedGas()
    frames_dir = OUT / name / 'frames'
    frames_dir.mkdir(parents=True, exist_ok=True)
    dt = spot.physics_dt
    stride = max(1, round(1 / (FPS * dt)))
    frame_dt = stride * dt
    cam_yaw = yaw
    log = []
    timing = {}
    clock = _time.perf_counter

    def lap(stage, since):
        timing[stage] = timing.get(stage, 0.0) + clock() - since
        return clock()

    for index in range(int(duration * FPS)):
        mark = clock()
        t = index * frame_dt
        p, yaw, roll, pitch = full_pose()
        a.trail.append(tuple(p[:2]))
        a.scene['look'] = a.look
        place_cameras(p, cam_yaw, a.scene, onboard_yaw=yaw)
        cam_yaw += 0.25 * wrap(yaw - cam_yaw)
        world.render()
        world.render()
        mark = lap('render', mark)
        a.nav.lidar_update(frame_dt)
        mark = lap('lidar_icp', mark)
        frames = {'third': _rgb(THIRD), 'first': _rgb(onboard), 'bird': _rgb(BIRD)}
        mark = lap('camera_readback', mark)
        reading = a.sensor.sample(np.array([p[0], p[1], 0.6]), t)   # Physical sensor at the real robot.
        a.scene['ambient_c'] = reading['temperature_c']
        a.gas = lagged.update(reading, frame_dt)
        reading = {**reading, **a.gas}
        perception = perceive(a.scene)
        if state.get('yolo_vision'):
            perception['yolo']=state['yolo_vision'].observe(frames['first'],onboard.get_depth(),p,yaw,a.nav.fused,t)
            # Segmentation remains inside the synthetic thermal sensor backend.
            # It supplies no visual corrosion evidence to the planner.
            perception['corrosion_px']={}
        mark = lap('perception', mark)
        audio = robot_audio((p[0], p[1], 0.6), t, frame_dt, a.scene.get('acoustic', []), a.nav.touchdowns)
        a.hiss = hiss_detector(audio)
        a.mic_db = a.hiss['level_dbfs']
        a.history['gamma'].append(reading['dose_rate_uSv_h'])
        a.history['h2'].append(a.gas.get('hydrogen_ppm', 0.0))
        est = a.nav.fused
        nearest = min(inventory, key=lambda d: math.dist(est[:2], (d['x'], d['y'])))
        a.nearest = (nearest['display_id'], math.dist(est[:2], (nearest['x'], nearest['y'])))
        # Findings from onboard sensing
        for f in thermal_findings(perception['thermal'], onboard.get_depth(), reading['temperature_c'], (p, yaw), est,
                                  rise=HEAT_RISE_C):
            if f['drum_id']:
                confidence = 'high' if f['pixels'] >= 400 and f['range_m'] <= 4.0 else 'low'
                fid = f"thermal_{f['drum_id']}"
                previous = a.findings.get(fid, {}).get('confidence')
                material = DRUMS[f['drum_id']]['category']
                surface = correct_emissivity(f['temp_c'], EMISSIVITY[material], reading['temperature_c'])
                if a.add_finding(t, fid, kind='thermal_hotspot', drum=f['drum_id'], surface_temp_c=round(surface, 1),
                                 apparent_temp_c=round(f['temp_c'], 1), emissivity=EMISSIVITY[material],
                                 air_temp_c=round(reading['temperature_c'], 1), range_m=round(f['range_m'], 1),
                                 confidence=confidence):
                    a.event(t, f"Thermal hotspot {DRUMS[f['drum_id']]['display_id']} {surface:.0f} C"
                               f" (apparent {f['temp_c']:.0f} C, e={EMISSIVITY[material]}; {confidence} conf)!")
                elif previous == 'low' and confidence == 'high':
                    a.findings[fid]['confidence'] = 'high'
                    a.pending_decision = True
                    a.event(t, f"Thermal on {DRUMS[f['drum_id']]['display_id']} confirmed up close!")
                elif previous == 'high':
                    a.findings[fid]['confidence'] = 'high'
        rust = a.data.setdefault('rust_pct', {})
        for drum_id, px in perception['corrosion_px'].items():
            body = perception['drum_px'].get(drum_id, 0) + px
            if body > 1500:  # Visible rust area from a close enough view (mask ratio).
                rust[drum_id] = max(rust.get(drum_id, 0.0), 100.0 * px / body)
        if a.nearest[1] < 2.0:
            peak = a.data.setdefault('peak_dose', {})
            peak[nearest['id']] = max(peak.get(nearest['id'], 0.0), reading['dose_rate_uSv_h'])
        a.data.setdefault('env', []).append((reading['temperature_c'], reading['relative_humidity_pct']))
        for drum_id, px in ({} if a.detector else perception['corrosion_px']).items():   # Stand-in when no detector.
            if px > 150 and a.add_finding(t, f'corrosion_{drum_id}', kind='visible_corrosion', drum=drum_id,
                                          detector='simulator segmentation placeholder (no trained detector yet)'):
                a.event(t, f"Corrosion on {DRUMS[drum_id]['display_id']}!")
        vision=perception.get('yolo')
        if vision and vision['fresh']:
            for observation in vision['associations']:
                drum_id=observation['drum_id']
                record=a.data.setdefault('vision_records',{}).setdefault(drum_id,{'observations':0,'conditions':[]})
                record['observations']+=1
                record['conditions']=sorted(set(record['conditions'])|set(observation['faults']))
                for fault in observation['faults']:
                    kind='visible_corrosion' if fault=='corrosion' else 'visible_bulge'
                    first=a.add_finding(t,f'{fault}_{drum_id}',kind=kind,drum=drum_id,
                        detector='trained YOLO26s RGB API',model_run=vision['run_id'],
                        association=observation['association'],range_m=round(observation['range_m'],2),
                        confidence='high' if record['observations']>=2 else 'low',
                        observations=record['observations'])
                    if first:a.event(t,f"YOLO {fault} at map {DRUMS[drum_id]['display_id']}; get a closer view")
            a.data['yolo_stats']={k:vision[k] for k in ('status','calls','failures','wall_seconds','age_s')}
        a.hiss_frames = a.hiss_frames + 1 if a.hiss['hiss_score'] > 0.5 else 0
        # Gas and microphone are omnidirectional: they give evidence near the robot, not which drum.
        if a.hiss_frames == 6 and a.add_finding(t, 'acoustic_hiss', kind='sustained_hiss', score=round(a.hiss['hiss_score'], 2),
                                                robot_position_m=[round(v, 1) for v in est[:2]]):
            a.event(t, 'Sustained hiss on microphone!')
        if 'gas_h2' in a.findings:
            a.findings['gas_h2']['ppm'] = round(a.gas.get('hydrogen_ppm', 0))
        if a.gas.get('hydrogen_ppm', 0) > H2_DETECTED_PPM and a.add_finding(t, 'gas_h2', kind='hydrogen', ppm=round(a.gas['hydrogen_ppm']),
                                                                           robot_position_m=[round(v, 1) for v in est[:2]]):
            a.event(t, f"H2 {a.gas['hydrogen_ppm']:.0f} ppm!")
        if a.swab_contact is not None:
            result = a.sensor.poll_swab(t)
            if result['status'] == 'complete':
                drum_id = a.data.pop('swab_drum')
                limits = a.sensor.config['thresholds']['swab_bq_cm2']
                positive = result['alpha_bq_cm2'] > limits['alpha'] or result['beta_gamma_bq_cm2'] > limits['beta_gamma']
                a.add_finding(t, f'swab_{drum_id}', kind='smear_swab', drum=drum_id,
                              alpha_bq_cm2=round(result['alpha_bq_cm2'], 2), beta_gamma_bq_cm2=round(result['beta_gamma_bq_cm2'], 1),
                              alpha_limit=limits['alpha'], positive=positive)
                if drum_id in a.memory.drums:
                    a.memory.record(drum_id, 'swab', t, alpha_bq_cm2=round(result['alpha_bq_cm2'], 2),
                                    beta_gamma_bq_cm2=round(result['beta_gamma_bq_cm2'], 1), positive=positive)
                a.swab_text = f"a {result['alpha_bq_cm2']:.2f}  b/g {result['beta_gamma_bq_cm2']:.1f} Bq/cm2"
                a.event(t, f"Swab {DRUMS[drum_id]['display_id']}: alpha {result['alpha_bq_cm2']:.2f} Bq/cm2" + ('!' if positive else ''))
                a.swab_contact = None
        if a.detector and index % DETECT_EVERY_FRAMES == 0:
            result = detect_frame(frames['first'])
            if result.get('error'):
                a.event(t, f"Detector error: {result['error'][:60]}")
            a.detections = result.get('detections', [])
            observe_detections(a, t, associate_detections(a.detections, onboard.get_depth(), (p, yaw), est), est)
        observe_for_memory(a, t, perception, reading, est)
        a.memory.update_status(a)
        mark = lap('sensing_findings', mark)
        if a.use_cosmos and a.status != 'RETREAT':
            read_plates(a, t, p, yaw)
        mark = lap('plate_reads', mark)
        # Finish a follow-up before considering another. The hard dose stop can interrupt it.
        arrived = a.status in ('INVESTIGATE', 'RETREAT') and not a.route
        facing_target = a.face is None or abs(wrap(math.atan2(a.face[1] - est[1], a.face[0] - est[0]) - est[2])) < 0.25
        if reading['dose_rate_uSv_h'] > DOSE_BACKOFF and a.status not in ('RETREAT', 'ALERT', 'DOSE STOP'):
            a.status, a.hold = 'DOSE STOP', True
            a.event(t, 'Dose limit exceeded. Motion stopped and operator review required!')
        elif arrived and a.status == 'RETREAT':
            a.status, a.hold = 'ALERT', True
        elif a.status == 'INVESTIGATE':
            if arrived and facing_target:
                if drum_id := a.data.pop('reread', None):
                    read_plate_for(a, DRUMS[drum_id], t, p, yaw)
                decide(a, t, frames['first'], est, reading)
            elif t - a.action['since'] >= FOLLOWUP_TIMEOUT_S:
                a.data.pop('reread', None)
                a.event(t, 'Follow-up timed out. Resuming round with finding unresolved.')
                apply_action(a, {'action_id': 'continue_patrol'}, t, est)
        elif a.status == 'SAMPLING' and a.swab_contact is None:
            decide(a, t, frames['first'], est, reading)
        elif a.status == 'PATROL' and (a.pending_decision or (a.findings and t - a.last_decision_t >= 3.0)):
            decide(a, t, frames['first'], est, reading)
        mark = lap('cosmos_decide', mark)
        compose_agent(a, frames, perception, reading, p, yaw, roll, pitch, t).save(frames_dir / f'{index:05d}.jpg', quality=90)
        mark = lap('compose_write', mark)
        log.append({'t': round(t, 3), 'truth': p.tolist(), 'estimate': est.tolist(), 'status': a.status, 'patrol_stops_completed': a.patrol_index,
                    'action': a.action['id'], 'h2': a.gas.get('hydrogen_ppm', 0.0), 'hiss': a.hiss['hiss_score']})
        command = drive(a, est) if not a.hold else zero
        for k in range(stride):
            spot.step(dt, command)
            world.step(render=False)
            a.nav.physics_update(dt, t + (k + 1) * dt)
        mark = lap('physics_odometry', mark)
        if index % 24 == 0:
            print(f'[hot] frame {index} t={t:.1f}s ' + ' '.join(f'{k}={v:.0f}s' for k, v in timing.items()), flush=True)
    (OUT / name / 'timing.json').write_text(json.dumps({k: round(v, 1) for k, v in timing.items()}, indent=2))
    report = build_report(a)
    (OUT / name / 'report.json').write_text(json.dumps(report, indent=2, default=float))
    (OUT / name / 'report.md').write_text(report_markdown(report))
    (OUT / name / 'memory.json').write_text(json.dumps(a.memory.drums, indent=2, default=float))
    state.setdefault('memory_log', []).append({'run': name, 'drums': a.memory.drums})  # For comparing rounds later.
    last = Image.open(frames_dir / f'{index:05d}.jpg')
    card = report_card(last, report)
    for k in range(int(report_seconds * FPS)):
        card.save(frames_dir / f'{index + 1 + k:05d}.jpg', quality=90)
    (OUT / name / 'log.jsonl').write_text(''.join(json.dumps(r, default=float) + '\n' for r in log))
    (OUT / name / 'decisions.json').write_text(json.dumps({'decisions': a.decisions, 'events': a.events,
                                                           'findings': a.findings, 'ids_read': a.ids_read}, indent=2, default=float))
    print(f'[hot] agent run {name} done: {a.status}, {len(a.decisions)} decisions', flush=True)


def compose_agent(a, frames, perception, reading, p, yaw, roll, pitch, t):
    """Reuse the scenario layout, then replace the nav and decision panels with real-sensor values."""
    a.nav.landmarks = round(a.nav.icp_inliers * 100)
    vision=perception.get('yolo')
    if vision:
        frames=dict(frames)
        view=Image.fromarray(frames['first']);vd=ImageDraw.Draw(view)
        for item in vision['detections']:
            color={'drum':'#35d7ff','corrosion':'#ff9829','bulge':'#ed67f5'}[item['class_name']]
            vd.rectangle(item['bbox_xyxy'],outline=color,width=2)
        for item in vision['associations']:
            x,y,_,_=item['box']
            vd.text((x,max(25,y)),f"map {item['display_id']} {'/'.join(item['faults']) or 'drum'}",font=FONT[14],fill='#ffffff',stroke_width=1,stroke_fill='black')
        frames['first']=np.asarray(view)
    canvas = compose(a, frames, perception, reading, a.nav.errors(p, yaw), p, yaw, roll, pitch, t)
    draw_memory_overlay(canvas, a, p)
    if a.detector:
        draw_detections(canvas, a.detections)
    draw = ImageDraw.Draw(canvas)
    y0 = 728
    draw.rectangle((0, y0, 480, y0 + 200), fill='#111822')
    draw.text((16, y0 + 8), 'NAVIGATION  RTX LiDAR + IMU + leg odometry', font=FONT[18], fill='#9fb2c4')
    odom_err, fused_err, yaw_err = a.nav.errors(p, yaw)
    lines = [f'Estimate  ({a.nav.fused[0]:5.2f}, {a.nav.fused[1]:5.2f})  yaw {math.degrees(a.nav.fused[2]):6.1f}',
             f'Error vs truth  odom {odom_err:4.2f} m | LiDAR-ICP {fused_err:4.2f} m',
             f"LiDAR {a.nav.scan_points} pts, ICP {a.nav.icp_inliers:4.0%} {'ok' if a.nav.icp_accepted else 'REJECTED'} rms {a.nav.icp_rms * 100:3.0f} cm",
             f'IMU gyro z {math.degrees(a.nav.gyro):6.1f} deg/s  az {a.nav.accel[2]:5.1f} m/s2',
             f'Leg odom {a.nav.speed:4.2f} m/s  touchdowns {len(a.nav.touchdowns)}',
             f'Mic hiss {a.hiss["hiss_score"]:.2f} ({a.hiss["band_margin_db"]:4.1f} dB over floor)']
    for i, line in enumerate(lines):
        draw.text((16, y0 + 40 + 26 * i), line, font=FONT[18], fill='white')
    draw.rectangle((1460, y0 + 84, W, H - 30), fill='#111822')
    draw.text((16, y0 + 197), f'ROUND  {a.patrol_index}/{len(a.patrol)} aisle stops  |  {a.status}',
              font=FONT[16], fill='white')
    if a.cosmos:
        c = a.cosmos
        draw.text((1460, y0 + 86), f"{c['source']} decision @ {c['t']:.1f}s", font=FONT[14], fill='#7cc4ff')
        draw.text((1460, y0 + 106), f"-> {c['action_id']}", font=FONT[18], fill='white')
        reason = c['reason']
        for i in range(3):
            draw.text((1460, y0 + 130 + 19 * i), reason[i * 50:(i + 1) * 50], font=FONT[14], fill='#d6e2ee')
    for i, (et, text) in enumerate(a.events[-5:]):
        draw.text((1460, y0 + 196 + 24 * i), f'{et:4.1f}s  {text}'[:54], font=FONT[16],
                  fill='#ff9f9f' if '!' in text else 'white')
    draw.rectangle((0, H - 28, W, H), fill='#111822')
    if vision:
        draw.text((16,974),f"YOLO26s {vision['status']} | {len(vision['associations'])} mapped drums | {len(vision['detections'])} boxes",font=FONT[16],fill='#35d7ff')
        draw.text((16,1000),f"API {vision['wall_seconds']*1000:.0f} ms | age {vision['age_s']:.2f}s | calls {vision['calls']} | errors {vision['failures']}",font=FONT[16],fill='white')
    draw.text((16, H - 26), 'RGB: trained YOLO26s + depth/map association. Navigation: LiDAR/IMU/encoders. '
              'LWIR/H2/mic/swab are simulated sensors. Cosmos chooses safety-checked actions; fallback is labelled.',
              font=FONT[14], fill='#6f8396')
    return canvas


def build_report(a):
    """Grade each inspected drum with sim/criteria.py; Cosmos writes the summary from the structured result."""
    temps = [e[0] for e in a.data.get('env', [])] or [float('nan')]
    rhs = [e[1] for e in a.data.get('env', [])] or [float('nan')]
    a.memory.update_status(a)
    actions = {'bad': ['stop', 'capture_best_angle', 'raise_alert', 'route_around_aisle'],
               'attention': ['reinspect_second_angle', 'flag_next_shift'], 'good': ['log_continue'],
               'inspecting': ['complete_inspection'], 'none': ['inspect_next_round']}
    extra = {f['drum'] for f in a.findings.values() if f.get('drum')} - set(a.memory.drums)
    drums = []
    for drum_id in sorted(set(a.memory.drums) | extra, key=lambda d: DRUMS[d]['display_id']):
        d = DRUMS[drum_id]
        entry = a.memory.drums.get(drum_id)
        if entry is None:  # Seen on the way, outside this job: report the finding, not a status.
            notes = [f"{f['kind']} seen (outside this job)" for f in a.findings.values() if f.get('drum') == drum_id]
            if drum_id in a.data.get('rust_pct', {}):
                notes = [f"rust {a.data['rust_pct'][drum_id]:.0f}% seen (outside this job)"]
            drums.append({'drum': d['display_id'], 'category': d['category'], 'plate_read': a.ids_read.get(drum_id, 'not attempted'),
                          'record': a.scene['records'].get(drum_id), 'grade': 'outside job', 'checks_done': [],
                          'missing': [], 'actions': ['schedule_inspection'], 'notes': notes})
            continue
        drums.append({'drum': d['display_id'], 'category': d['category'],
                      'plate_read': a.ids_read.get(drum_id, 'not attempted'), 'record': a.scene['records'].get(drum_id),
                      'grade': entry['status'], 'checks_done': sorted(entry['checks']), 'missing': entry.get('missing', []),
                      'complete': entry.get('complete',False),
                      'evidence': entry['checks'], 'actions': actions[entry['status']], 'notes': entry['reasons']})
    report = {'title': a.title, 'drums': drums, 'round_status': a.status,
              'patrol_stops_completed': a.patrol_index, 'patrol_stops_total': len(a.patrol),
              'environment': {'air_temp_c': round(float(np.median(temps)), 1), 'rh_pct': round(float(np.median(rhs))),
                              'max_h2_ppm': round(max(a.history['h2'] or [0])), 'max_gamma_uSv_h': round(max(a.history['gamma'] or [0]), 1)},
              'alerts': [DRUMS[d]['display_id'] for d in a.flagged],
              'decisions': [{k: d[k] for k in ('t', 'action_id', 'reason', 'source')} for d in a.decisions],
              'not_inspected': [DRUMS[d]['display_id'] for d, e in a.memory.drums.items() if not e.get('complete',False)]}
    report['summary'] = factual_summary(report)

    return report


def factual_summary(r):
    """Built from the inspection memory only; the 2B model embellished when asked to write this."""
    job = [d for d in r['drums'] if d['grade'] != 'outside job']
    count = {k: [d['drum'] for d in job if d['grade'] == k] for k in ('good', 'attention', 'bad', 'inspecting', 'none')}
    parts = [f"{sum(d.get('complete',False) for d in job)}/{len(job)} drums fully inspected: "
             f"{len(count['good'])} good, {len(count['attention'])} need attention, {len(count['bad'])} bad."]
    for d in job:
        if d['grade'] in ('bad', 'attention'):
            parts.append(f"{d['drum']} {d['grade']}: {', '.join(d['notes'])}.")
    outside = [f"{d['drum']} ({', '.join(d['notes'])})" for d in r['drums'] if d['grade'] == 'outside job']
    if outside:
        parts.append(f"Also seen outside the job: {'; '.join(outside)}.")
    e = r['environment']
    parts.append(f"H2 peaked at {e['max_h2_ppm']} ppm, gamma at {e['max_gamma_uSv_h']} uSv/h.")
    if r['not_inspected']:
        parts.append(f"Still to inspect: {', '.join(r['not_inspected'])}.")
    return ' '.join(parts)


def report_markdown(r):
    lines = [f"# Inspection report: {r['title']}", '', r['summary'], '',
             '| Drum | Cat | Status | Checks done | Missing | Plate read | Record | Issues |',
             '|---|---|---|---|---|---|---|---|']
    for d in r['drums']:
        lines.append(f"| {d['drum']} | {d['category']} | {d['grade']} | {', '.join(d['checks_done'])} | "
                     f"{', '.join(d['missing'])} | {d['plate_read']} | {d['record']} | {'; '.join(d['notes'])} |")
    e = r['environment']
    lines += ['', f"Environment: air {e['air_temp_c']} C, RH {e['rh_pct']}%, max H2 {e['max_h2_ppm']} ppm, "
                  f"max gamma {e['max_gamma_uSv_h']} uSv/h.", f"Alerts: {', '.join(r['alerts']) or 'none'}.",
              f"Not inspected this round: {', '.join(r['not_inspected']) or 'none'}.", '', '## Decisions', '']
    lines += [f"- {d['t']:.1f}s `{d['action_id']}` ({d['source']}): {d['reason']}" for d in r['decisions']]
    return '\n'.join(lines) + '\n'


def report_card(last_frame, r):
    card = Image.blend(last_frame.convert('RGB'), Image.new('RGB', last_frame.size, '#0d131b'), 0.82)
    draw = ImageDraw.Draw(card)
    draw.text((80, 50), 'INSPECTION REPORT', font=FONT[34], fill='white')
    draw.text((80, 96), r['title'], font=FONT[22], fill='#9fb2c4')
    words, line, y = r['summary'].split(), '', 140
    for word in words:
        if len(line) + len(word) > 120:
            draw.text((80, y), line, font=FONT[18], fill='#d6e2ee')
            line, y = '', y + 26
        line += word + ' '
    draw.text((80, y), line, font=FONT[18], fill='#d6e2ee')
    y += 50
    colors = {'bad': '#ff6767', 'attention': '#ffc55e', 'good': '#5fe2af', 'inspecting': '#e6ecf2',
              'none': '#6f8396', 'outside job': '#9fb2c4'}
    for x, head in ((80, 'DRUM'), (200, 'CAT'), (290, 'PLATE READ'), (480, 'RECORD'), (650, 'STATUS'), (820, 'ISSUES / MISSING CHECKS')):
        draw.text((x, y), head, font=FONT[16], fill='#9fb2c4')
    for d in r['drums'][:12]:
        y += 34
        draw.text((80, y), d['drum'], font=FONT[22], fill='white')
        draw.text((200, y), d['category'], font=FONT[22], fill='white')
        draw.text((290, y), str(d['plate_read']), font=FONT[22], fill='white')
        draw.text((480, y), str(d['record']), font=FONT[22], fill='white')
        draw.text((650, y), d['grade'].upper(), font=FONT[22], fill=colors.get(d['grade'], 'white'))
        detail = '; '.join(d['notes']) or (f"missing: {', '.join(d['missing'])}" if d['missing'] else 'all checks passed')
        draw.text((820, y), detail[:80], font=FONT[18], fill='#d6e2ee')
    e = r['environment']
    draw.text((80, y + 60), f"Air {e['air_temp_c']} C   RH {e['rh_pct']}%   max H2 {e['max_h2_ppm']} ppm   "
                            f"max gamma {e['max_gamma_uSv_h']} uSv/h   Alerts: {', '.join(r['alerts']) or 'none'}   "
                            f"Not yet inspected: {', '.join(r['not_inspected']) or 'none'}", font=FONT[18], fill='white')
    return card


print('[hot] agent loaded', flush=True)
