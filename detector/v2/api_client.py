"""Small standard-library client; no GPU or ML libraries needed by callers."""
import argparse,json,os,urllib.request,uuid
from pathlib import Path

def predict(url,path,key,secret,confidence=.25):
    boundary='canis-'+uuid.uuid4().hex;path=Path(path);raw=path.read_bytes()
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+raw+f'\r\n--{boundary}--\r\n'.encode())
    req=urllib.request.Request(url.rstrip('/')+f'/predict?confidence={confidence}',data=body,
        headers={'Modal-Key':key,'Modal-Secret':secret,'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(req,timeout=180) as response:return json.loads(response.read())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('image');p.add_argument('--url',default=os.environ.get('CANIS_API_URL') or json.loads(Path(__file__).with_name('selected_model.json').read_text())['api_url']);p.add_argument('--confidence',type=float,default=.25);a=p.parse_args()
    if not a.url:p.error('Set CANIS_API_URL or --url')
    result=predict(a.url,a.image,os.environ['DETECTOR_API_KEY'],os.environ['DETECTOR_API_SECRET'],a.confidence)
    print(json.dumps(result,indent=2))
