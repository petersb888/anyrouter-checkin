import os, sys, urllib.request, gzip, io, zipfile
tok = os.environ['GH_TOK']
url = 'https://api.github.com/repos/petersb888/anyrouter-checkin/actions/runs/35419958091/logs'
req = urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'probe'})
for attempt in range(5):
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        print('downloaded bytes:', len(data))
        zf = zipfile.ZipFile(io.BytesIO(data))
        for name in zf.namelist():
            text = zf.read(name).decode('utf-8', 'replace')
            for line in text.splitlines():
                if '[probe]' in line:
                    print(line.split('Z ', 1)[-1].strip())
        break
    except Exception as e:
        print(f'attempt {attempt}: {type(e).__name__}: {e}')
