"""Read durable run progress without starting a GPU."""
import json
from pathlib import Path
import modal
root=Path(__file__).resolve().parents[2]
def main():
    pointer=root/'.runtime/condition_dataset.json'
    if pointer.exists():
        run=json.loads(pointer.read_text())['dataset_id']
        d=modal.Dict.from_name('canis-condition-generation-progress')
        states=[d.get(f'{run}/{i}') or {'state':'not_started','frames':0} for i in range(10)]
        print(json.dumps({'dataset_id':run,'frames':sum(s.get('frames',0) for s in states),'total':1500,
                          'workers':[{k:v for k,v in s.items() if k!='tail'} for s in states]},indent=2))
    pointer=root/'.runtime/condition_models.json'
    if pointer.exists():
        run=json.loads(pointer.read_text())['comparison_id'];d=modal.Dict.from_name('canis-condition-training-progress')
        print(json.dumps({'comparison_id':run,'training':{scale:d.get(f'{run}/{scale}') for scale in ('n','s')}},indent=2))
if __name__=='__main__':main()
