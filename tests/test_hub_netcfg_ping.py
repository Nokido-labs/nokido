
import urllib.request
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from forge_secrets import get_secret
token = get_secret("FORGE_TOKEN_GEMINI") or ""
url = 'http://127.0.0.1:8766/mcp'
data = {
    'jsonrpc': '2.0',
    'id': 1,
    'method': 'tools/call',
    'params': {
        'name': 'netcfg_ping',
        'arguments': {}
    }
}

req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {token}'
})

try:
    with urllib.request.urlopen(req) as res:
        print(res.read().decode())
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.reason}")
    print(e.read().decode())
except Exception as e:
    print(f"Error: {e}")
