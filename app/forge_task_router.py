"""
forge_task_router.py v2 - Orchestrateur taches zero-token Claude
Exploite TOUS les providers Nokido disponibles.
Principe: Claude = dernier recours. Tout le reste -> gratuit/local.
"""

import json, os, asyncio
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


def _gs(k: str) -> str:
    """Secure secret access — WCM > .env > os.environ."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        import os as _os

        return _os.environ.get(k, "")


ROOT = Path(__file__).resolve().parent.parent


def _has_codex_cli() -> bool:
    try:
        from nokido_agent.app.forge_agent_proxy import CodexCLI
        return CodexCLI().is_available()
    except Exception:
        return False


# ══════════════════════════════════════════════════════
# CAPACITE PAR PROVIDER (cost=0 gratuit, 1=payant)
# ══════════════════════════════════════════════════════
PROVIDERS = {
    # LOCAL LLAMA.CPP - zero token, Vulkan 780M, x2+ vs Ollama
    "llamacpp": {
        "cost": 0,
        "speed": "fast",
        "ctx": 8192,
        "models": ["gemma-4-E4B-it-Q4_K_M", "qwen2.5-coder-7b"],
        "best_for": ["code", "complete", "analyze", "local_fast", "classify"],
        "unavailable_if": lambda: not __import__("forge_llamacpp").is_available(),
    },
    # LOCAL - zero token, zero reseau
    "ollama": {
        "cost": 0,
        "speed": "medium",
        "ctx": 32000,
        "models": ["qwen2.5-coder:32b", "qwen2.5-coder:7b"],
        "best_for": ["code", "queries", "filter", "analyze", "classify"],
        "unavailable_if": lambda: not _ping("http://127.0.0.1:11434"),
    },
    # GRATUIT - 1M tokens/jour
    "gemini": {
        "cost": 0,
        "speed": "fast",
        "ctx": 1000000,
        "models": ["gemini-2.5-flash"],
        "best_for": ["analyze_large", "report", "benchmark", "docs", "summarize"],
        "unavailable_if": lambda: not _gs("GEMINI_API_KEY"),
    },
    # GRATUIT - 14400 req/jour, ultra-rapide (inférence HW)
    "groq": {
        "cost": 0,
        "speed": "ultra",
        "ctx": 131000,
        "models": ["llama-3.3-70b-versatile", "llama-4-scout-17b-16e-instruct"],
        "best_for": ["synthesis", "classify", "filter", "review_light", "summarize"],
        "unavailable_if": lambda: not _gs("GROQ_API_KEY"),
    },
    # GRATUIT - HuggingFace router
    "hf": {
        "cost": 0,
        "speed": "medium",
        "ctx": 131000,
        "models": ["meta-llama/Llama-3.3-70B-Instruct"],
        "best_for": ["queries", "filter", "classify"],
        "unavailable_if": lambda: not os.environ.get("HF_TOKEN"),
    },
    # GRATUIT - GitHub Models (Copilot)
    "gpt4o_github": {
        "cost": 0,
        "speed": "fast",
        "ctx": 128000,
        "models": ["gpt-4o"],
        "best_for": ["code_review", "analyze", "docs"],
        "unavailable_if": lambda: not os.environ.get("GITHUB_MODELS_TOKEN"),
    },
    # GRATUIT - OpenRouter free pool (Qwen3-Coder 480B, Nemotron 120B...)
    "openrouter_free": {
        "cost": 0,
        "speed": "medium",
        "ctx": 262000,
        "models": ["qwen/qwen3-coder:free", "nvidia/nemotron-3-super-120b-a12b:free"],
        "best_for": ["code", "analyze_large", "docs"],
        "unavailable_if": lambda: not _gs("OPENROUTER_API_KEY"),
    },
    # WEB SEARCH integre - Perplexity Online
    "perplexity": {
        "cost": 1,
        "speed": "fast",
        "ctx": 128000,
        "models": ["llama-3.1-sonar-large-128k-online"],
        "best_for": ["web_search_llm", "fact_check", "current_events"],
        "unavailable_if": lambda: not os.environ.get("PERPLEXITY_API_KEY"),
    },
    # CHEAP - DeepSeek $0.01/1M tokens
    "deepseek": {
        "cost": 1,
        "speed": "fast",
        "ctx": 64000,
        "models": ["deepseek-chat"],
        "best_for": ["code", "analyze", "report"],
        "unavailable_if": lambda: not _gs("DEEPSEEK_API_KEY"),
    },
    # RESERVE - Claude uniquement pour complexite haute
    "claude": {
        "cost": 3,
        "speed": "fast",
        "ctx": 200000,
        "models": ["claude-sonnet-4"],
        "best_for": ["architecture", "critical_code", "security"],
        "unavailable_if": lambda: False,  # toujours disponible
    },
    # OpenAI Codex CLI (gpt-5.5) - zero token local
    "codex_cli": {
        "cost": 0,
        "speed": "fast",
        "ctx": 128000,
        "models": ["gpt-5.5"],
        "best_for": ["code", "complete"],
        "unavailable_if": lambda: not _has_codex_cli(),
    },
}

# ══════════════════════════════════════════════════════
# ROUTING TABLE - tache -> provider prefere
# ══════════════════════════════════════════════════════
ROUTING = {
    # Zero token - local
    "vectorize": ["ollama"],
    "py_compile": ["local"],
    "rag_search": ["local"],
    # Queries de recherche (court, rapide)
    "generate_queries": ["groq", "llamacpp", "ollama", "hf"],
    "filter_results": ["groq", "ollama", "hf"],
    "classify_domain": ["groq", "llamacpp", "ollama"],
    # Synthese et resume
    "synthesize_short": ["groq", "gemini", "ollama"],
    "summarize_log": ["groq", "gemini"],
    "summarize_long": ["gemini"],  # ctx 1M
    # Code et analyse
    "write_tests": ["llamacpp", "ollama", "gpt4o_github", "openrouter_free"],
    "write_docs": ["gemini", "ollama", "gpt4o_github"],
    "analyze_code": ["llamacpp", "ollama", "openrouter_free"],
    "code_review": ["gpt4o_github", "groq"],
    "analyze_large": ["gemini"],  # ctx 1M = fichier entier
    # Rapports
    "write_report": ["gemini", "gpt4o_github"],
    "benchmark_eval": ["gemini", "groq"],
    "write_orphans": ["gemini", "ollama"],
    "write_changelog": ["groq", "ollama"],
    # Web search
    "web_search_agent": ["perplexity"],  # web search LLM integre
    "research": ["groq", "gemini"],  # + SearXNG pipeline
    # CLAUDE UNIQUEMENT (tokens chers - justifie)
    "architecture": ["claude"],
    "critical_code": ["claude"],
    "security_audit": ["claude"],
    "design_decision": ["claude"],
}


def _ping(url: str) -> bool:
    import urllib.request

    try:
        urllib.request.urlopen(url, timeout=1)
        return True
    except:
        return False


def _load_env():
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                if k not in os.environ:
                    os.environ[k] = v.strip().strip('"').strip("'")


_load_env()


def status() -> dict:
    """Etat de tous les providers."""
    result = {}
    for name, info in PROVIDERS.items():
        unavail_fn = info.get("unavailable_if")
        try:
            unavail = unavail_fn() if unavail_fn else False
        except:
            unavail = True
        result[name] = {
            "available": not unavail,
            "cost": info["cost"],
            "speed": info["speed"],
            "models": info["models"],
            "best_for": info["best_for"][:3],
        }
    return result


def _keystone_pool_provider(task_type):
    # KEYSTONE Ph2 efferent: map forge_pool_registry.best() -> route_task provider.
    # Consomme la telemetrie pool (afferent = agy Ph1). None => fallback cascade ROUTING.
    # cf blackboard tree_locks/CLAUDE_keystone_ph2_intpoint.
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / 'tools'))
        from nokido_agent.tools.forge_pool_registry import best as _best
    except Exception:
        return None
    member = _best(task_type)
    if not member:
        return None
    m = str(member).lower()
    if m == 'cli:codex':
        return 'codex_cli'
    if m == 'cli:gemini':
        return 'gemini'
    if m.startswith('cli:'):
        # Pour les autres non-LLM (cli:agy, cli:vscode, etc.)
        return None
    for prov in ('llamacpp', 'ollama', 'groq', 'gemini', 'hf', 'gpt4o_github', 'codex_cli'):
        if prov in m:
            return prov
    return None


def select_provider(task_type: str) -> str:
    """Selectionne le meilleur provider disponible pour la tache."""
    # Anti-Goodhart (risque #1 systemique) : une tache CRITIQUE ne peut PAS etre downgradee
    # sous le plancher. Le plancher = allowlist critical-capable (set-point owner, source
    # unique forge_route_solver). Escalate-only, fail-safe (aucun capable dispo -> claude,
    # dernier recours). N'utilise PAS le tag-fit du pool (pas une mesure de qualite).
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / 'tools'))
        from nokido_agent.tools.forge_route_solver import CRITICAL_TASKS, critical_capable_providers
        if (task_type or "").lower() in CRITICAL_TASKS:
            _s = status()
            for _p in critical_capable_providers():
                if _p in _s and _s[_p].get("available"):
                    return _p
            return "claude"  # dernier recours, garanti critical-capable
    except Exception:
        pass
    # KEYSTONE Ph2 (opt-in, OFF par defaut): selection efficacite-aware via le pool d'agy ;
    # ne remplace jamais la cascade ROUTING ci-dessous (fallback A = comportement actuel).
    if os.getenv('LAFORGE_KEYSTONE_PH2') == '1':
        try:
            _kp = _keystone_pool_provider(task_type)
            if _kp:
                _s = status()
                if _kp in _s and _s[_kp].get('available'):
                    return _kp
        except Exception:
            pass
    candidates = ROUTING.get(task_type, ["groq", "ollama", "gemini"])
    if candidates == ["local"]:
        return "local"
    s = status()
    for name in candidates:
        if name in s and s[name]["available"]:
            return name
    # Fallback: premier gratuit disponible
    for name in ["groq", "gemini", "ollama", "hf", "gpt4o_github"]:
        if name in s and s[name]["available"]:
            return name
    return "claude"  # dernier recours


async def route(task_type: str, payload: dict) -> dict:
    """Route une tache vers le bon provider et l'execute."""
    # Couche DecisionTree : prédit depuis le contenu du prompt
    # Fallback automatique sur routing statique si conf < 0.6
    _prompt = payload.get("prompt") or payload.get("objective", "")
    _dt_provider = ""
    try:
        from nokido_agent.app.forge_llm_router_dt import route_with_dt, log_decision as _log_dt

        _dt_provider, _dt_conf, _dt_src = route_with_dt(task_type, _prompt)
        if _dt_src == "dt":
            import logging as _log

            _log.getLogger("Nokido.TaskRouter").debug(f"[DT] {task_type} -> {_dt_provider} conf={_dt_conf:.2f}")
    except Exception:
        pass
    prompt = payload.get("prompt") or payload.get("objective", "")
    if not prompt:
        return {"ok": False, "error": "payload.prompt requis"}

    # ── Cascade BORNÉE jamais-hang ────────────────────────────────────────────
    # Ancien défaut : un SEUL _ask, sans timeout ni fallback → un provider mort
    # (ex. ollama down) faisait hang jusqu'au cap hub (socket fermé). Désormais on
    # construit un ORDRE de candidats (forcé > DT > table routage > derniers recours
    # gratuits), on garde les DISPONIBLES (status() teste unavailable_if : _ping
    # local, clés cloud), puis on essaie chacun avec wait_for(timeout) et on cascade
    # au suivant sur échec/timeout. Principe hub-jamais-vide. claude = dernier recours.
    _forced = payload.get("provider", "")
    _avail = status()

    def _is_ok(p: str) -> bool:
        return p == "local" or _avail.get(p, {}).get("available", False)

    ordered: list = []
    for p in ([_forced] if _forced else []) + ([_dt_provider] if _dt_provider else []):
        if p and p not in ordered:
            ordered.append(p)
    for p in ROUTING.get(task_type, ["groq", "ollama", "gemini"]):
        if p not in ordered:
            ordered.append(p)
    for p in ["llamacpp", "ollama", "groq", "gemini", "gpt4o_github", "claude"]:
        if p not in ordered:
            ordered.append(p)
    # ── AXE 2 : CAPACITÉ (TRANSPORT ≠ APPLICATIF) ──────────────────────────
    # Une tâche (même triviale) qui exige un PAT ou un accès réseau authentifié
    # (ex: github) n'est pas "locale". Elle doit être exécutée par un agent avec le profil owner (Claude/Antigravity).
    import re
    if re.search(r"\b(gh_run|github|gh api|pull request|pr|issue|pat)\b", prompt, re.IGNORECASE):
        payload["force_local"] = False
        ordered = ["claude"] + [p for p in ordered if p != "claude"]
        import logging
        logging.getLogger("Nokido.TaskRouter").info("[capability] Tâche requiert réseau/PAT -> force_local ignoré, escalade vers agent cloud (claude/antigravity)")

    # force_local (opt-in) : routage SOUVERAIN — pool local SEUL, zéro cloud.
    # Logique d'appel "agentique local / pool micro-agentique" demandée : reste
    # gouverné (cascade bornée) mais ne quitte jamais la machine. Si tous les
    # locaux sont down → cascade épuisée → erreur claire (toujours pas de hang).
    if bool(payload.get("force_local")):
        _LOCAL = {"llamacpp", "ollama", "local"}
        ordered = [p for p in ordered if p in _LOCAL and (_is_ok(p) or p == "local")] or ["llamacpp", "ollama"]
    else:
        ordered = [p for p in ordered if _is_ok(p) or p == "claude"]

    _per_call = int(payload.get("timeout", 45))
    from nokido_agent.app.forge_agent_proxy import ask as _ask

    last_err = "aucun provider disponible"
    for provider_name in ordered:
        if provider_name == "local":
            return await _local(task_type, payload)
        try:
            result = await asyncio.wait_for(
                _ask(
                    provider_name=provider_name,
                    message=prompt,
                    rag_context=payload.get("rag_context", False),
                    max_tokens=payload.get("max_tokens", 500),
                ),
                timeout=_per_call,
            )
        except asyncio.TimeoutError:
            last_err = f"timeout({_per_call}s) sur {provider_name}"
            continue
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e} (sur {provider_name})"
            continue
        if result and result.get("ok"):
            result["task_type"] = task_type
            result["selected_provider"] = provider_name
            try:  # apprentissage en ligne : nourrit le DecisionTree
                from nokido_agent.app.forge_llm_router_dt import log_decision as _log_dt

                _log_dt(_prompt, task_type, provider_name, result.get("latency_ms", 0), True)
            except Exception:
                pass
            return result
        last_err = (result or {}).get("error", "") or f"réponse non-ok de {provider_name}"

    return {"ok": False, "error": f"cascade épuisée: {last_err}", "task_type": task_type, "tried": ordered}


async def _local(task_type: str, payload: dict) -> dict:
    if task_type == "py_compile":
        import py_compile

        path = str(ROOT / payload.get("filepath", ""))
        try:
            py_compile.compile(path, doraise=True)
            return {"ok": True, "filepath": payload.get("filepath")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if task_type == "vectorize":
        try:
            from sentence_transformers import SentenceTransformer
            import sqlite3, numpy as np

            db = ROOT / "RAG" / "embeddings.db"
            conn = sqlite3.connect(str(db))
            limit = payload.get("limit", 200)
            domain = payload.get("domain")
            q = "SELECT id,text FROM rag_chunks WHERE embedding IS NULL"
            params = []
            if domain:
                q += " AND domain=?"
                params.append(domain)
            q += f" LIMIT {limit}"
            rows = conn.execute(q, params).fetchall()
            if not rows:
                conn.close()
                return {"ok": True, "vectorized": 0}
            model = SentenceTransformer("BAAI/bge-small-en-v1.5")
            vecs = model.encode([r[1][:512] for r in rows], normalize_embeddings=True, show_progress_bar=False)
            for (uid, _), vec in zip(rows, vecs):
                conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (vec.astype(np.float32).tobytes(), uid))
            conn.commit()
            conn.close()
            return {"ok": True, "vectorized": len(rows), "domain": domain}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"local task inconnu: {task_type}"}


if __name__ == "__main__":
    print("=== PROVIDER STATUS ===")
    s = status()
    for name, info in s.items():
        avail = "OK" if info["available"] else "--"
        print(f"  {avail} {name:<18} cost={info['cost']} speed={info['speed']:6s} best={info['best_for']}")

    print("\n=== ROUTING EXAMPLES ===")
    for task in ["generate_queries", "synthesize_short", "write_docs", "analyze_large", "architecture", "vectorize"]:
        print(f"  {task:<22} -> {select_provider(task)}")

    print("\n=== TEST GROQ ===")
    result = asyncio.run(
        route(
            "synthesize_short",
            {
                "prompt": "Resume en 2 phrases: SearXNG est un moteur de recherche open-source qui agregge les resultats de Google, Bing, DuckDuckGo sans tracker les utilisateurs.",
                "max_tokens": 150,
            },
        )
    )
    print(f"  provider={result.get('selected_provider')} ok={result.get('ok')}")
    print(f"  {result.get('text', '')[:200]}")
