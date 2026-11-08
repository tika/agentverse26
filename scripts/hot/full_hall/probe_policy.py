import inspect as _insp, numpy as _pn
print('[probe] type', type(spot), type(spot).__mro__, flush=True)
for k, v in sorted(vars(spot).items()):
    try:
        a = v.numpy() if hasattr(v, 'numpy') else v
        sh = getattr(_pn.asarray(a), 'shape', None) if not isinstance(a, (str, dict, list)) else None
    except Exception:
        sh = None
    print('[probe] attr', k, type(v).__name__, sh, (repr(_pn.asarray(a).round(3).tolist())[:200] if sh and len(sh) <= 2 and _pn.asarray(a).size <= 24 else ''), flush=True)
for name in ('step', 'forward', '_compute_action', '_compute_observation', 'initialize', 'apply_action'):
    f = getattr(type(spot), name, None)
    if f:
        try:
            print('[probe] SRC', name, _insp.getsource(f)[:2500], flush=True)
        except Exception as e:
            print('[probe] nosrc', name, e)
print('[probe] dof', list(spot.articulation.dof_names), flush=True)
(OUT / 'probe.txt').write_text('ok')
