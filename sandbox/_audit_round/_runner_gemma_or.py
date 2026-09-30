import sys, urllib.request, json, time
from pathlib import Path
sys.path.insert(0, __import__("os").path.expanduser(r"~\Script python IA\LaForge\app"))
from forge_agent_proxy import _load_api_key

out = Path(sys.argv[1])
prompt_file = Path(sys.argv[2])
system = sys.argv[3] if len(sys.argv) > 3 else "Architecte securite IA. Tranchant, francais."
prompt = prompt_file.read_text(encoding="utf-8")

t0 = time.monotonic()
try:
    key = _load_api_key("OPENROUTER_API_KEY")
    body = json.dumps({"model":"google/gemma-4-31b-it:free",
        "messages":[{"role":"system","content":system},{"role":"user","content":prompt}],
        "max_tokens":2500,"temperature":0.4}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json",
                 "HTTP-Referer":"https://nokido.local","X-Title":"Nokido"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    txt = resp["choices"][0]["message"]["content"]
    out.write_text(txt, encoding="utf-8")
    Path(str(out)+".done").write_text(f"{time.monotonic()-t0:.1f}s", encoding="utf-8")
except Exception as e:
    Path(str(out)+".err").write_text(f"{type(e).__name__}: {e}"[:500], encoding="utf-8")
