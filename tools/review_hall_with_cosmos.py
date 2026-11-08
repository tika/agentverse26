"""Review real static hall renders with deployed YOLO and the external Cosmos API.

This selects proposed follow-ups only; it does not execute a robot mission.
Keys are read from ignored private files and never included in saved reports.
"""
import argparse
import base64
import io
import json
from pathlib import Path
import shlex
import sys
import time
import urllib.request
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from detector.api_client import predict


def private_config(path):
    result={}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,value=line.removeprefix('export ').split('=',1)
        parts=shlex.split(value);result[key.strip()]=parts[0] if parts else ''
    return result


def extract_result(text):
    decoder=json.JSONDecoder()
    for i,char in enumerate(text):
        if char!='{':continue
        try:value,_=decoder.raw_decode(text[i:])
        except ValueError:continue
        if isinstance(value,dict) and 'next_action' in value:return value
    return None


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--captures',type=Path,default=ROOT/'sim/out/hall_barrel_v2')
    args=parser.parse_args()
    cosmos=private_config(ROOT/'.runtime/cosmos.env')
    detector=private_config(ROOT/'.runtime/detector_api.env')
    manifest=json.loads((args.captures/'report.json').read_text())
    results=dict(scope='Static-image perception and proposed follow-ups; no mission executed',
                 cosmos_endpoint=cosmos['COSMOS_URL'],model=cosmos.get('COSMOS_MODEL','cosmos'),views={})
    findings=['surface_discoloration','surface_corrosion_suspected','body_deformation_suspected',
              'lid_deformation_suspected','no_obvious_anomaly','uncertain']
    system=('You are a robot inspection decision layer reviewing one current RGB camera frame. '
            'You also receive actual YOLO detector output; it can be wrong. '
            'No temperature, radiation, pressure or gas measurements are available in this static preview. '
            'Only describe visible evidence. A swollen barrel is a shape cue, not proof of gas or pressure. '
            'Do not infer blood, liquid leaks, contamination, wall loss, structural weakness or contents from colour. '
            'Read a printed package ID only if clearly legible; otherwise return null. '
            'Choose one offered next action and give a short reason limited to visible cues and missing measurements. '
            'Return only the requested JSON schema. printed_id contains just the letter and two digits, or null.')
    actions=['inspect_closer','request_thermal_reading','take_second_view','continue_patrol']
    schema={'type':'object','properties':{
        'printed_id':{'anyOf':[{'type':'string','pattern':'^[A-D][0-9]{2}$'},{'type':'null'}]},
        'visible_findings':{'type':'array','items':{'type':'string','enum':findings},'minItems':1,'maxItems':4},
        'next_action':{'type':'string','enum':actions},
        'reason':{'type':'string','maxLength':200}},
        'required':['printed_id','visible_findings','next_action','reason'],'additionalProperties':False}
    for name in ('A03_normal_rusted','B01_bulged_clean','C02_bulged_rusted'):
        path=args.captures/manifest['views'][name]['image']
        detected=predict(detector['DETECTOR_API_URL'],path,detector['DETECTOR_API_KEY'],detector['DETECTOR_API_SECRET'])
        with Image.open(path) as source:
            image=source.convert('RGB');image.thumbnail((1024,1024))
            buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=92)
        content=[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()}},
                 {'type':'text','text':json.dumps(dict(available_actions=actions,
                    image=detected['image'],detector_model=detected['run_id'],
                    detections=detected['detections'][:40],numeric_sensor_readings='not collected'))}]
        body=json.dumps(dict(model=results['model'],messages=[{'role':'system','content':system},
            {'role':'user','content':content}],temperature=0.,max_tokens=768,
            response_format={'type':'json_schema','json_schema':{'name':'static_preview_review','schema':schema,'strict':True}})).encode()
        headers={'Content-Type':'application/json','Authorization':'Bearer '+cosmos['VLLM_API_KEY']}
        request=urllib.request.Request(cosmos['COSMOS_URL'].rstrip('/')+'/v1/chat/completions',data=body,headers=headers)
        started=time.perf_counter()
        with urllib.request.urlopen(request,timeout=180) as response:answer=json.loads(response.read())
        text=answer['choices'][0]['message']['content'];parsed=extract_result(text)
        assert parsed and parsed['next_action'] in actions,'Cosmos did not choose an offered action'
        assert all(item in findings for item in parsed['visible_findings']),'Unsupported observation category'
        parsed['visible_findings']=list(dict.fromkeys(parsed['visible_findings']))
        reason=parsed['reason'].lower()
        unsupported=any(term in reason for term in ('blood','confirmed gas','leaking','compromised','structural weakness','contaminated'))
        results['views'][name]=dict(image=str(path.relative_to(ROOT)),yolo=detected,
            cosmos=parsed,raw_response=text,cosmos_seconds=time.perf_counter()-started,
            finish_reason=answer['choices'][0].get('finish_reason'),
            review_status='rejected_unsupported_claim' if unsupported else 'structured_preview_valid')
        (args.captures/'cosmos_review.json').write_text(json.dumps(results,indent=2))
        print('COSMOS_PREVIEW '+json.dumps(dict(view=name,**parsed)),flush=True)
    print('COSMOS_PREVIEW_COMPLETE',flush=True)


if __name__=='__main__':main()
