"""Rebuild the fixed hall from a checked-in layout or a different episode seed."""
import json
from pathlib import Path

DEFAULT=Path(__file__).with_name('layouts')/'layout_training.json'


def load_layout(path=DEFAULT,seed=None):
    from build_hall import build_scene
    from drums import set_drum_faults, INVENTORY
    from labels import label_scene
    from isaacsim.core.experimental.utils.stage import get_current_stage
    layout=json.loads(Path(path).read_text())
    episode_seed=layout['seed'] if seed is None else seed
    metrics=build_scene(episode_seed)
    for drum_id,spec in sorted(layout['drums'].items()):
        local_seed=spec.get('seed',layout['seed']+int(drum_id[1:])*97)
        # The waste is solid: no puddles, leaks or residue stains are built.
        faults=[f for f in spec['faults'] if f not in ('leak','residue')]
        set_drum_faults(drum_id,faults,local_seed+episode_seed-layout['seed'],spec.get('severity',2))
    entries=json.loads(INVENTORY.read_text())
    label_scene(get_current_stage(),entries)
    return {**metrics,'layout':str(Path(path).name),'episode_seed':episode_seed,'faulty_drums':len(layout['drums'])}
