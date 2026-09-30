"""tools/forge_lats_debug_debate.py - debat multi-LLM CIBLE bug actuel LATS.

Question precise : pourquoi LATS+repo_map+Stage 0 ne produit AUCUN patch
utile sur 3 instances SWE-bench Lite, malgre le scaffolding repo_map filtre
+ stack_hint + extraction tolerante ?

Donnees factuelles a fournir au debat :
  - 3 instances astropy testees, 3 patches generes mais 0 resolved harness
  - Run #1 (pre-Stage 0) : patches existaient mais cerebras halluciné
    fichier cible (config/paths.py au lieu de modeling/test_separable.py)
  - Run #2/3 (post-Stage 0) : 0 patches generes - cerebras retourne empty
    ou non-diff format ; OU connection refused hub depuis WSL
  - Stack_hint detecte stack_files dans 1/3 instances seulement
  - filtered repo_md = 12-15 KB (plus court que original 52 KB)
  - Pour instance #12907 : stack_files=[] = pas de stacktrace explicite dans
    l issue (issue purement comportementale, pas de traceback)

3 providers consultes : cerebras gpt-oss-120b + groq llama-70b + github gpt-4o.
Arbitrage = Jaccard keyword overlap (symbolique, zero LLM juge).

Output : sandbox/lats_debate/<ts>/decision.md + raw proposals.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Reuse hub_ask + extraction
try:
    from nokido_agent.app.forge_secrets import get_secret as _get_secret
except ImportError:
    _get_secret = None
import urllib.request


def _detect_hub_url():
    import os as _os
    import platform as _pf

    if "LAFORGE_HUB_URL" in _os.environ:
        return _os.environ["LAFORGE_HUB_URL"].strip()
    try:
        if "microsoft" in _pf.uname().release.lower():
            with open("/etc/resolv.conf") as f:
                for line in f:
                    if line.startswith("nameserver"):
                        return f"http://{line.split()[1].strip()}:8766/mcp"
    except OSError:
        pass
    return "http://127.0.0.1:8766/mcp"


HUB_URL = _detect_hub_url()
OUT_DIR = ROOT / "sandbox" / "lats_debate"
OUT_DIR.mkdir(parents=True, exist_ok=True)


PROBLEM = """
LATS pipeline SWE-bench produit 0/3 patches resolus :

CONTEXTE TECHNIQUE :
- forge_swebench_lats_runner.py orchestre : clone repo cible (cache) +
  build_repo_map AST natif + filter_md par keywords distilles + LATS
  search avec n_initial=2, max_depth=1, default_apply_and_test git+pytest
- Stage 0 distillation regex extrait keywords + stack_files du
  problem_statement (deterministe, pas LLM)
- propose_fn appelle cloud LLMs (cerebras gpt-oss-120b + groq llama-70b)
  via hub :8766 ask tool
- Extraction diff toleranche : 4 patterns regex (```diff, ```patch,
  diff --git raw, --- a/ raw)

OBSERVATIONS RUN ACTUEL (3 instances astropy lite) :
- Instance 1 (astropy-12907) : kw=['separability_matrix', 'linear',
  'python', 'false', 'true'] stack_files=[] (issue comportementale sans
  traceback). Filtered repo_md=12.6 KB. 3/3 LLM calls : resp_len=51
  ms=0 - tous retournent erreur identique probable.
- Instance 2 (astropy-14182) : kw=['astropy', 'writer', 'python',
  'write', 'ascii'] stack_files=['ascii/connect.py', 'core.py', 'ui.py']
  (3 paths). Filtered=14.9 KB. Idem 0 diff.
- Instance 3 (astropy-14365) : kw=['read', 'table', 'serr', 'ascii']
  stack_files=[]. Idem.

Run PRECEDENT (sans Stage 0) : 3/3 patches existaient (cerebras a
produit du diff), mais harness Docker = 0/3 resolved (patches modifiaient
config/paths.py alors que le bug etait dans modeling/test_separable.py
- LLM avait halluciné le fichier cible).

QUESTION : quelle est la cause RACINE de l ineptie du pipeline actuel,
et quel est le LEVIER d amelioration le plus efficace en termes de
ROI (gain expected resolved / effort dev) ?
"""

CONSTRAINTS = """
Contraintes :
- Pas de fine-tune (free tier cloud seulement)
- Pas de Docker harness running local Windows (WSL+Docker requis)
- LLM choices : cerebras gpt-oss-120b / groq llama-3.3-70b / github
  gpt-4o (tous free tier, limites tokens 4-8K)
- Effort dev : max 1 jour
"""


def _hub_ask(provider: str, message: str, token: str, max_tokens: int = 8192) -> str:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ask",
                "arguments": {
                    "provider": provider,
                    "message": message,
                    "max_tokens": max_tokens,
                    "rag_context": False,
                },
            },
        }
    ).encode()
    req = urllib.request.Request(
        HUB_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Agent-Name": "LATS_DEBATE",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        text = data.get("result", {}).get("content", [{}])[0].get("text", "")
        try:
            inner = json.loads(text)
            if isinstance(inner, dict) and "text" in inner:
                text = inner["text"]
        except (json.JSONDecodeError, TypeError):
            pass
        return text
    except Exception as e:
        return f"ERR: {e}"


def _keywords(text: str) -> set[str]:
    STOP = {
        "the",
        "this",
        "that",
        "with",
        "from",
        "have",
        "should",
        "could",
        "and",
        "for",
        "are",
        "not",
        "but",
        "you",
        "your",
        "les",
        "des",
        "qui",
        "que",
        "pour",
        "dans",
    }
    return {w for w in re.findall(r"[a-zA-Z_]{4,}", text.lower()) if w not in STOP}


def _jaccard(a, b):
    return len(a & b) / max(len(a | b), 1)


def main():
    token = ""
    if _get_secret:
        try:
            token = _get_secret("FORGE_MCP_TOKEN") or ""
        except Exception:
            pass
    if not token:
        import os

        token = _get_secret("FORGE_MCP_TOKEN") or ""
    if not token:
        print("ERR : FORGE_MCP_TOKEN absent")
        return 1

    prompt = (
        "Tu es ingenieur ML/SWE-bench expert. Analyse ce probleme et propose "
        "une strategie ACTIONABLE en 2-3 paragraphes. "
        "Format : (1) ROOT_CAUSE en 1 phrase, "
        "(2) STRATEGIE en 3 etapes concretes, (3) ROI_ESTIMATED.\n\n"
        f"PROBLEME :\n{PROBLEM}\n\nCONTRAINTES :\n{CONSTRAINTS}"
    )

    print(f"[debate] hub={HUB_URL}")
    proposals = []
    for prov in ("cerebras", "groq", "github"):
        print(f"\n[debate] -> {prov}")
        t0 = time.monotonic()
        resp = _hub_ask(prov, prompt, token, max_tokens=4096)
        dt = time.monotonic() - t0
        kw = _keywords(resp)
        ok = not resp.startswith("ERR:") and len(resp) > 100
        print(f"  ms={int(dt * 1000)} len={len(resp)} kw={len(kw)} ok={ok}")
        proposals.append(
            {"provider": prov, "ok": ok, "resp": resp, "keywords": sorted(kw), "ms": int(dt * 1000)}
        )

    # Jaccard convergence
    print("\n[debate] consensus matrix :")
    for i, a in enumerate(proposals):
        if not a["ok"]:
            continue
        line = [a["provider"]]
        for j, b in enumerate(proposals):
            if i == j or not b["ok"]:
                continue
            j_sc = _jaccard(set(a["keywords"]), set(b["keywords"]))
            line.append(f"{b['provider']}={j_sc:.2f}")
        print("  " + " | ".join(line))

    # Save raw + composite
    ts = int(time.time())
    out_dir = OUT_DIR / str(ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in proposals:
        (out_dir / f"{p['provider']}.txt").write_text(p["resp"], encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(proposals, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[debate] saved -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
