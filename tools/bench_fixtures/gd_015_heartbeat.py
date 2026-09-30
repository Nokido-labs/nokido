import json
from pathlib import Path

hb = Path(__import__("os").path.expanduser("~/Script python IA/LaForge/sandbox/multi_llm_daemon.heartbeat"))
d = json.loads(hb.read_text()) if hb.exists() else {}
print(d.get("status", "missing"))
