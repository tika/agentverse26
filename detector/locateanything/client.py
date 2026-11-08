"""Call the LocateAnything API using an existing private workspace proxy token."""
import argparse
import hashlib
import json
import shlex
from pathlib import Path
import urllib.request


def credentials(path):
    config={}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,value=line.removeprefix('export ').split('=',1)
        parts=shlex.split(value);config[key.strip()]=parts[0] if parts else ''
    return config


def endpoint():
    import modal
    return modal.Cls.from_name('agentverse-locateanything','LocateAnything')().web.get_web_url()


def predict(path,url,config,timeout=900,query=None):
    raw=Path(path).read_bytes();boundary='locate-frame'
    prefix=(f'--{boundary}\r\nContent-Disposition: form-data; name="query"\r\n\r\n{query}\r\n').encode() if query else b''
    body=prefix+(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="frame.jpg"\r\n'
          'Content-Type: image/jpeg\r\n\r\n').encode()+raw+f'\r\n--{boundary}--\r\n'.encode()
    request=urllib.request.Request(url.rstrip('/')+'/predict',data=body,headers={
        'Modal-Key':config['DETECTOR_API_KEY'],'Modal-Secret':config['DETECTOR_API_SECRET'],
        'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request,timeout=timeout) as response:result=json.loads(response.read())
    assert result['input_sha256']==hashlib.sha256(raw).hexdigest(),'Input provenance mismatch'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('image',type=Path)
    parser.add_argument('--url');parser.add_argument('--credentials',default='.runtime/detector_api.env')
    parser.add_argument('--out',type=Path,default=Path('out/locateanything/smoke/result.json'))
    args=parser.parse_args();url=args.url or endpoint()
    result=predict(args.image,url,credentials(args.credentials))
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('model','model_revision','latency_ms','image','gpu')}))
    print('detections:',len(result['detections']),'barrels:',len(result['barrels']))
    print('model output:',result['raw_answer'][:1600])
