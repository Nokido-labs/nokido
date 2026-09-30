
import urllib.request
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from forge_secrets import get_secret
token = get_secret("FORGE_TOKEN_GEMINI") or ""
url = 'http://127.0.0.1:8766/mcp'

# Commande de redémarrage des services via shell SYSTEM
cmd = 'nssm restart LaForgeMCP; nssm restart NokidoGeminiDaemon; nssm start NokidoCapture'

data = {
    'jsonrpc': '2.0',
    'id': 1,
    'method': 'tools/call',
    'params': {
        'name': 'run',
        'arguments': {
            'action': 'shell',
            'code': cmd
        }
    }
}

print(f"Envoi de la commande de redémarrage au Hub...")
req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {token}'
})

try:
    # Le Hub va se couper lui-même, donc on s'attend à une déconnexion
    with urllib.request.urlopen(req, timeout=5) as res:
        print(res.read().decode())
except Exception as e:
    print(f"Note: Le Hub redémarre probablement ({e})")
