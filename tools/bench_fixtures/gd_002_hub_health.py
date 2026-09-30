import json
import urllib.request

r = urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=5)
print(json.loads(r.read())["status"])
