#!/usr/bin/env python3
"""forge_endpoint_registry.py — SOURCE UNIQUE d'identité des endpoints LLM de Nokido.

AVANT : 4 structures divergentes pour le MÊME endpoint ->
  - app/forge_provider_specs.py  (PROVIDER_SPECS)        métadonnée : tier/coût/quota/ctx
  - app/forge_agent_proxy.py     (_PROVIDERS)            runtime    : classe qui APPELLE
  - tools/forge_endpoint_monitor.py                      sondes online (groq/proxy_7777…)
  - tools/forge_openai_proxy.py  (MODEL_TO_PROVIDER)     alias :7777
=> `github_deepseek_v3` (spec) n'existe pas côté runtime, `mistral_small` (spec) = `mistral`
   (runtime) = "provider inconnu" / 502, et le gate s'appuie sur cost_tier ad hoc => incohérent.

CE module FÉDÈRE (anti-dup — ne duplique PAS la donnée provider, il la LIT) et ajoute la couche
manquante : identité + sécurité + gate cohérent.

  • id canonique   : "<famille>:<variante>"            ex "openrouter:glm5", "oauth:claude_cli"
  • identifiable   : RFC 6648 (entêtes org-scopées, PAS de préfixe X-) :
                       LaForge-Agent-Name  / LaForge-Endpoint-Id
                     + RFC 6750 (OAuth 2.0 Bearer Token) : Authorization: Bearer <token>
  • sécurisé       : secret_ref = OÙ vit le secret (vault DPAPI / env / oauth_dir / none-local)
  • gate cohérent  : min_ring DÉRIVÉ du tier par UNE politique unique (RING_BY_TIER).
                     Fin du "gates pas même tarif" : qui peut DÉPENSER (quota/argent) est borné
                     par le ring du tier ; ce qui FUIT reste borné par le SemanticFirewall (DLP),
                     gate orthogonal conservé.

Lecture seule / dérivé : reflète toujours l'état réel des deux registres source. Les consommateurs
(ask resolver, :7777 proxy, monitor, videur) appellent resolve()/min_ring_for() au lieu de
ré-inventer un mapping local.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── RFC : entêtes d'identification canoniques ───────────────────────────────────
IDENTITY_HEADER = "LaForge-Agent-Name"     # RFC 6648 (qui appelle)
ENDPOINT_HEADER = "LaForge-Endpoint-Id"    # RFC 6648 (quel endpoint résolu)
AUTH_SCHEME = "Bearer"                       # RFC 6750 (Authorization: Bearer <token>)

# ── politique de gate UNIQUE (le "même tarif") : tier -> min_ring requis ─────────
# ring 0 = plus privilégié, 4 = non fiable. min_ring = ring MAXIMAL toléré (caller_ring <= min_ring).
RING_BY_TIER = {
    "local": 4,                # gratuit + local, aucune dépense : ouvert à tous
    "free": 4,                 # petit quota gratuit : le user VEUT qu'on s'en serve largement
    "subscription_quota": 2,   # OAuth CLI : consomme le quota d'abonnement -> agents fiables
    "paid_api": 2,             # dépense de l'argent -> agents fiables seulement
    "unknown": 3,
}

# ── réconciliation des noms : spec (métadonnée) -> runtime (proxy qui appelle) ───
# Résout les 23 noms "spec-only". Valeur None = spec FANTÔME (aucun runtime) -> à enrichir/purger.
SPEC_TO_RUNTIME = {
    "gemini_flash": "gemini",
    "mistral_small": "mistral", "mistral_large": "mistral",
    "cohere_command_r": "cohere", "cohere_command_r_plus": "cohere",
    "xai_grok3": "grok", "xai_grok3_mini": "grok",
    "hf_llama": "hf",
    "kimi_k2": "kimi", "kimi_thinking": "kimi_think",
    "glm4": "glm",
    "ollama_local": "ollama", "llamacpp_local": "llamacpp", "lmstudio_native": "lmstudio",
    "openrouter_glm_air": "glm",
    "sambanova_llama_405b": "sambanova",
    # FANTÔMES (spec sans runtime — index à enrichir : ajouter un Provider, ou retirer la spec)
    "github_deepseek_v3": None, "github_gpt41_mini": None, "github_gpt4o_mini": None,
    "github_codestral": None, "github_llama_70b": None,
    "openrouter_gpt_oss": None, "openrouter_qwen_coder": None,
}

# familles de transport (le runtime n'expose pas de champ transport explicite)
_OAUTH_CLI = {"claude_cli", "claude_agent_sdk", "gemini_cli", "codex_cli", "copilot_cli"}
_LOCAL_HTTP = {"ollama", "lmstudio", "llamacpp", "docker", "ollama_mimo_v2"}
_INTERNAL = {"router", "router_local", "swarm", "agent", "nervous", "wasm"}
# répertoire OAuth par CLI (où vit le jeton de session)
_OAUTH_DIR = {
    "claude_cli": "~/.claude", "claude_agent_sdk": "~/.claude",
    "gemini_cli": "~/.gemini", "codex_cli": "~/.codex", "copilot_cli": "~/.copilot",
}


def _family(runtime_name: str) -> str:
    """Préfixe canonique de l'id (la 'famille' d'endpoint)."""
    if runtime_name in _OAUTH_CLI:
        return "oauth"
    if runtime_name in _LOCAL_HTTP:
        return "local"
    if runtime_name in _INTERNAL:
        return "internal"
    if runtime_name.startswith("openrouter") or runtime_name in {"glm", "glm5", "kimi", "kimi_think"}:
        return "openrouter"
    if runtime_name.startswith("gemini"):
        return "gemini"
    if runtime_name in {"gpt4o_github"}:
        return "github"
    return "api"


def _transport(runtime_name: str) -> str:
    if runtime_name in _OAUTH_CLI:
        return "oauth_cli"
    if runtime_name in _LOCAL_HTTP:
        return "local_http"
    if runtime_name in _INTERNAL:
        return "internal"
    return "http_api"


def _secret_ref(runtime_name: str, api_key_env: str | None) -> str:
    """OÙ vit le secret (jamais le secret lui-même)."""
    if runtime_name in _OAUTH_CLI:
        return f"oauth_dir:{_OAUTH_DIR.get(runtime_name, '~/.config')}"
    if runtime_name in _LOCAL_HTTP or runtime_name in _INTERNAL:
        return "none-local"
    if api_key_env:
        # _load_api_key essaie : rotation -> vault DPAPI -> env -> Nokido.env
        return f"vault:{api_key_env}"
    return "none"


def _tier_for(runtime_name: str, spec_tier: str | None, cost_tier, has_key) -> str:
    if spec_tier:
        return spec_tier
    if runtime_name in _OAUTH_CLI:
        return "subscription_quota"
    if runtime_name in _LOCAL_HTTP or runtime_name in _INTERNAL:
        return "local"
    if cost_tier == 0:
        return "free"
    if cost_tier and cost_tier >= 2:
        return "paid_api"
    return "free" if cost_tier == 1 else "unknown"


def build_inventory() -> dict:
    """Construit la table canonique dérivée des deux registres + couche identité/sécu/gate."""
    from nokido_agent.app import forge_provider_specs as S
    from nokido_agent.app import forge_agent_proxy as P

    try:
        P._init_registry()
    except Exception:
        pass
    try:
        from nokido_agent.app.forge_agent_proxy import _load_api_key
    except Exception:
        _load_api_key = None

    specs = dict(S.PROVIDER_SPECS)
    # index inverse runtime -> spec_name (via SPEC_TO_RUNTIME + identité de nom)
    rt_to_spec: dict[str, str] = {}
    for sname in specs:
        rt = SPEC_TO_RUNTIME.get(sname, sname)
        if rt:
            rt_to_spec.setdefault(rt, sname)

    endpoints: dict[str, dict] = {}
    ghosts: list[str] = [s for s, rt in SPEC_TO_RUNTIME.items() if rt is None]

    for name, prov in P._PROVIDERS.items():
        env = getattr(prov, "api_key_env", None)
        cost_tier = getattr(prov, "cost_tier", None)
        spec_name = rt_to_spec.get(name)
        spec_tier = (specs.get(spec_name) or {}).get("tier") if spec_name else specs.get(name, {}).get("tier")
        key_ok = None
        if env and _load_api_key:
            try:
                key_ok = bool(_load_api_key(env))
            except Exception:
                key_ok = None
        tier = _tier_for(name, spec_tier, cost_tier, key_ok)
        cid = f"{_family(name)}:{name}"
        # alias = tous les noms par lesquels les 4 couches désignent cet endpoint
        _aset = {name, spec_name} | {s for s, rt in SPEC_TO_RUNTIME.items() if rt == name}
        _aset.discard(None)
        aliases = sorted(_aset)
        endpoints[cid] = {
            "id": cid,
            "runtime": name,                 # nom côté forge_agent_proxy (ask)
            "spec": spec_name,               # nom côté forge_provider_specs (None si absent)
            "aliases": [a for a in aliases if a],
            "model": getattr(prov, "model", None),
            "transport": _transport(name),
            "tier": tier,
            "secret_ref": _secret_ref(name, env),
            "key_present": key_ok,           # None = local/oauth (pas de clé)
            "min_ring": RING_BY_TIER.get(tier, RING_BY_TIER["unknown"]),
            "identity_header": IDENTITY_HEADER,
            "endpoint_header": ENDPOINT_HEADER,
            "auth_scheme": AUTH_SCHEME if env else ("oauth" if name in _OAUTH_CLI else "none"),
        }

    # table de résolution : n'importe quel alias -> id canonique
    alias_index: dict[str, str] = {}
    for cid, e in endpoints.items():
        alias_index[cid] = cid
        for a in e["aliases"]:
            alias_index.setdefault(a, cid)
    # fantômes -> pointer vers None (résolvable mais signalé sans runtime)
    return {"endpoints": endpoints, "alias_index": alias_index, "ghosts": ghosts}


_CACHE: dict | None = None


def _inv() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = build_inventory()
    return _CACHE


def resolve(name: str) -> dict | None:
    """N'importe quel nom (spec / runtime / alias) -> entrée canonique, ou None si fantôme/inconnu."""
    inv = _inv()
    cid = inv["alias_index"].get(name)
    return inv["endpoints"].get(cid) if cid else None


def min_ring_for(name: str) -> int:
    """Gate cohérent : ring max toléré pour cet endpoint (politique tier unique)."""
    e = resolve(name)
    return e["min_ring"] if e else RING_BY_TIER["unknown"]


def id_headers(agent: str, endpoint_id: str) -> dict:
    """Entêtes d'identification RFC 6648 à poser sur tout appel sortant/inter-couche."""
    return {IDENTITY_HEADER: agent, ENDPOINT_HEADER: endpoint_id}


def usable_free(require_key: bool = True) -> list[str]:
    """Endpoints free/local UTILISABLES maintenant (clé présente) — pour piloter la cascade."""
    out = []
    for e in _inv()["endpoints"].values():
        if e["tier"] in ("free", "local"):
            if (not require_key) or e["key_present"] in (True, None):
                out.append(e["runtime"])
    return out


def main() -> int:
    import json
    inv = build_inventory()
    eps = inv["endpoints"]
    by_tier: dict[str, list[str]] = {}
    for e in eps.values():
        by_tier.setdefault(e["tier"], []).append(e["runtime"])
    summary = {
        "total_endpoints": len(eps),
        "by_tier": {t: sorted(v) for t, v in sorted(by_tier.items())},
        "ghosts_spec_sans_runtime": inv["ghosts"],
        "usable_free_now": sorted(usable_free()),
        "sample": {cid: {k: e[k] for k in ("runtime", "spec", "tier", "secret_ref", "min_ring", "key_present")}
                   for cid, e in list(eps.items())[:6]},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
