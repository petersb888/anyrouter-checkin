import os, io, zipfile, urllib.request
tok = os.environ['GH_TOK']
url = 'https://api.github.com/repos/petersb888/anyrouter-checkin/actions/runs/35420992872/logs'
req = urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'probe'})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    zf = zipfile.ZipFile(io.BytesIO(data))
    for name in zf.namelist():
        for line in zf.read(name).decode('utf-8','replace').splitlines():
            if '[probe]' in line:
                print(line.split('Z ',1)[-1].strip())
except Exception as e:
    print('ERR', type(e).__name__, e)
