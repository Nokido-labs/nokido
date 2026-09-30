"""forge_bench_http.py — couche HTTP commune des runners de bench.

Nee de la rupture du cliquet clones du 2026-08-21 : `_http_post` etait copie
dans 6 runners (bfcl, swebench, planbench, terminal_bench, multi_llm_daemon,
humaneval), en 2 variantes qui ne differaient que par le User-Agent et le
timeout par defaut. Source unique ici ; chaque runner garde une delegation
d'une ligne avec SON timeout par defaut historique.

User-Agent TOUJOURS envoye : sans lui Cloudflare (Groq/Cerebras) rend 403
error code 1010 (mesure 21/08, runner HumanEval).
"""
from __future__ import annotations

import json
import urllib.request

USER_AGENT = "nokido-bench/1.0"


def http_post(url: str, body: dict, headers: dict | None = None,
              timeout: int = 45) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                 **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())
