"""Send a camera JPEG to the authenticated detector; credentials stay in environment."""
import argparse
import json
import mimetypes
import os
from pathlib import Path
import urllib.request
import urllib.parse
import uuid


def predict(url, image, key, secret, band='fixed', confidence=None):
    image = Path(image)
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(image.name)[0] or 'application/octet-stream'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="frame{image.suffix}"\r\n'
            f'Content-Type: {mime}\r\n\r\n').encode() + image.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    params = {'band': band}
    if confidence is not None:
        params['confidence'] = confidence
    request = urllib.request.Request(url.rstrip('/')+'/predict?'+urllib.parse.urlencode(params), data=body,
                                    headers={'Modal-Key': key, 'Modal-Secret': secret,
                                             'Content-Type': 'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('image', type=Path)
    parser.add_argument('--url', default=os.environ.get('DETECTOR_API_URL'))
    parser.add_argument('--band', choices=['fixed', 'suspect', 'confirm'], default='fixed')
    parser.add_argument('--confidence', type=float)
    args = parser.parse_args()
    if not args.url:
        parser.error('Set DETECTOR_API_URL or pass --url')
    print(json.dumps(predict(args.url, args.image, os.environ['DETECTOR_API_KEY'],
                             os.environ['DETECTOR_API_SECRET'], args.band, args.confidence), indent=2))


if __name__ == '__main__':
    main()
