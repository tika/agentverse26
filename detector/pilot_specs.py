"""Seeded pilot assignments. Printed identity and faults use independent RNG streams."""
import math
import numpy as np

CLASSES = ['drum', 'corrosion', 'bulge']


def scene_spec(seed):
    shape_rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
    id_rng = np.random.default_rng(np.random.SeedSequence([seed, 2]))
    appearance_rng = np.random.default_rng(np.random.SeedSequence([seed, 3]))
    conditions = [(False, False), (True, False), (False, True), (True, True)]
    shape_rng.shuffle(conditions)
    ids = id_rng.choice([f'{r}{i:02d}' for r in 'ABCD' for i in range(1, 8)], 4, replace=False)
    entries = []
    for i, ((rust, bulge), display_id) in enumerate(zip(conditions, ids)):
        entries.append(dict(id=f'D{i+1:02d}', display_id=str(display_id), rust=rust, bulge=bulge,
                            x=(i-1.5)*1.1, y=float(shape_rng.uniform(-.12, .12)),
                            yaw=float(shape_rng.uniform(-math.pi, math.pi)),
                            radial_fraction=float(shape_rng.uniform(.07,.09)) if bulge else 0.,
                            lid_rise_m=float(shape_rng.uniform(.065,.075)) if bulge else 0.,
                            rust_seed=int(appearance_rng.integers(100000, 2000000000))))
    return entries
