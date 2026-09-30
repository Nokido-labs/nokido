"""forge_bench_groq_test.py — Diagnostic acces cle groq pour le benchmark.

Teste : backend forge_env_crypt, dechiffrement load_secrets() sous le compte
courant, puis 1 appel groq avec la cle dechiffree. N'echo PAS la cle (longueur
+ prefixe seulement). A jeter une fois le benchmark cale.
"""

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

key = ""
try:
    from nokido_agent.app import forge_env_crypt as ec

    try:
        print("backend :", ec._detect_backend())
    except Exception as e:
        print("backend detect err :", type(e).__name__, str(e)[:120])
    s = ec.load_secrets()
    key = s.get("GROQ_API_KEY", "") or ""
    print(f"load_secrets : {len(s)} secrets | GROQ len={len(key)} prefix={key[:4]!r}")
except Exception as e:
    print("forge_env_crypt ERREUR :", type(e).__name__, "|", str(e)[:300])

if key and len(key) > 20:
    try:
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 15,
            },
            timeout=30,
        )
        print(f"groq POST status={r.status_code} body={r.text[:250]}")
    except Exception as e:
        print("groq POST err :", type(e).__name__, str(e)[:200])
else:
    print("cle inexploitable -> POST saute")
