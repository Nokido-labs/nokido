import sys, urllib.request, json, time
from pathlib import Path
sys.path.insert(0, __import__("os").path.expanduser(r"~\Script python IA\LaForge\app"))
from forge_agent_proxy import _load_api_key

provider = sys.argv[1]
out = Path(sys.argv[2])
prompt_file = Path(sys.argv[3])

system = sys.argv[4] if len(sys.argv) > 4 else "Tu es architecte distributed AI. Reponse technique tranchee, francais, 600 mots max."
prompt_user = prompt_file.read_text(encoding="utf-8")

t0 = time.monotonic()
try:
    if provider == "kimi":
        key = _load_api_key("OPENROUTER_API_KEY")
        body = json.dumps({"model":"moonshotai/kimi-k2-thinking",
            "messages":[{"role":"system","content":system},{"role":"user","content":prompt_user}],
            "max_tokens":2000,"temperature":0.4}).encode()
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={"Authorization":f"Bearer {key}","Content-Type":"application/json",
                     "HTTP-Referer":"https://nokido.local","X-Title":"Nokido"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = json.loads(r.read())["choices"][0]["message"]["content"]
    elif provider == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=_load_api_key("GEMINI_API_KEY"))
        m = genai.GenerativeModel("gemini-2.5-flash-lite")
        r = m.generate_content(f"{system}\n\n{prompt_user}",
            generation_config={"max_output_tokens":2500,"temperature":0.4})
        txt = r.text
    elif provider == "gpt4o":
        key = _load_api_key("GITHUB_MODELS_TOKEN")
        body = json.dumps({"model":"gpt-4o",
            "messages":[{"role":"system","content":system},{"role":"user","content":prompt_user}],
            "max_tokens":2000,"temperature":0.3}).encode()
        req = urllib.request.Request("https://models.inference.ai.azure.com/chat/completions", data=body,
            headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = json.loads(r.read())["choices"][0]["message"]["content"]
    out.write_text(txt, encoding="utf-8")
    Path(str(out)+".done").write_text(f"{time.monotonic()-t0:.1f}s", encoding="utf-8")
except Exception as e:
    Path(str(out)+".err").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
