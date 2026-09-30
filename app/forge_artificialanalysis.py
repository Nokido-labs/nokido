# -*- coding: utf-8 -*-
"""
forge_artificialanalysis.py - Wrapper API ArtificialAnalysis.ai
================================================================
Fetch metrics fraiches pour modeles LLM (pricing, speed, quality scores)
depuis https://artificialanalysis.ai/api-reference.

Usage :
  - python -m forge_artificialanalysis --refresh    # refresh cache JSON
  - python -m forge_artificialanalysis --summary    # print top providers
  - Import : get_model_metrics("claude-sonnet-4") -> dict

Cache : data/artificialanalysis_cache.json (TTL 24h)
Rate limit : 1000 req/jour free tier (large marge)

Sert a :
- Auto-update PROVIDER_SPECS pricing/context obsolete
- Quality-based routing (use_case "code" -> prefer modeles haut score coding)
- Speed-based routing (use_case "speed" -> prefer modeles haut tokens/sec)
- Comparaison cost/quality pour cascade decisions
"""

from __future__ import annotations
import datetime
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "artificialanalysis_cache.json"
API_BASE = "https://artificialanalysis.ai/api/v2"
CACHE_TTL_HOURS = 24

# Map nom provider Nokido -> slug/id ArtificialAnalysis (incremental)
PROVIDER_AA_MAP = {
    # Claude
    "claude_agent_sdk": "claude-sonnet-4",
    "claude_cli": "claude-sonnet-4",
    "claude": "claude-sonnet-4",
    "claude_github": "claude-sonnet-4",
    "claude_openrouter": "claude-sonnet-4",
    # Gemini
    "gemini": "gemini-2-5-flash",
    "gemini_flash": "gemini-2-5-flash",
    "gemini_flash_lite": "gemini-2-5-flash-lite",
    "gemini_cli": "gemini-2-5-flash",
    "gemini_pro": "gemini-2-5-pro",
    # OpenAI
    "openai": "gpt-4o",
    "gpt4o_github": "gpt-4o",
    "github_gpt41_mini": "gpt-4-1-mini",
    "github_gpt4o_mini": "gpt-4o-mini",
    # Groq
    "groq": "llama-3-3-instruct-70b",
    # Llama via providers
    "github_llama_70b": "llama-3-3-instruct-70b",
    "hf_llama": "llama-3-3-instruct-70b",
    "sambanova": "llama-3-3-instruct-70b",
    "sambanova_llama_70b": "llama-3-3-instruct-70b",
    "sambanova_llama_405b": "llama-3-1-instruct-405b",
    # DeepSeek
    "deepseek": "deepseek-v3",
    "github_deepseek_v3": "deepseek-v3",
    # Mistral
    "mistral_large": "mistral-large-2",
    "mistral_small": "mistral-small-3",
    "github_codestral": "codestral",
    # Cohere
    "cohere_command_r": "command-r",
    "cohere_command_r_plus": "command-r-plus",
    # xAI
    "xai_grok3": "grok-3",
    "xai_grok3_mini": "grok-3-mini",
    # GLM / Kimi
    "glm4": "glm-4-plus",
    "glm5": "glm-4-5",
    "kimi_k2": "kimi-k2",
    "kimi_thinking": "kimi-thinking-preview",
    # OpenRouter
    "openrouter_qwen_coder": "qwen3-coder",
    "openrouter_glm_air": "glm-4-5-air",
    "openrouter_gpt_oss": "gpt-oss-120b",
    # Decouverts via AA --discover 2026-05-23 (free tiers nouveaux)
    "openrouter_glm5": "glm-5-turbo",
    "openrouter_mimo_v2": "mimo-v2-omni",
    "ollama_mimo_v2": "mimo-v2-omni",
    # Cerebras
    "cerebras": "llama-3-3-instruct-70b",
    # NVIDIA
    "nvidia_nim": "llama-3-3-instruct-70b",
    # Perplexity
    "perplexity": "sonar-large",
    # Local (no AA equivalent direct, skip)
    "ollama_local": None,
    "llamacpp_local": None,
    "lmstudio_native": None,
}


def _load_api_key() -> Optional[str]:
    """Lit cle depuis Nokido.env. Pas d'echo cle."""
    # 1. env var direct (avec point ou underscore)
    for k in ("ARTIFICIALANALYSIS_AI", "ARTIFICIALANALYSIS.AI", "AA_API_KEY"):
        if k in os.environ:
            return os.environ[k]
    # 2. Parse Nokido.env
    env_file = ROOT / "Nokido.env"
    if not env_file.exists():
        return None
    try:
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() in ("ARTIFICIALANALYSIS.AI", "ARTIFICIALANALYSIS_AI", "AA_API_KEY"):
                return val.strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def _cache_fresh() -> bool:
    """True si cache < TTL."""
    if not CACHE_PATH.exists():
        return False
    age_h = (datetime.datetime.now().timestamp() - CACHE_PATH.stat().st_mtime) / 3600
    return age_h < CACHE_TTL_HOURS


def _load_cache() -> dict:
    """Charge cache JSON (vide si absent)."""
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def fetch_llms(force: bool = False) -> dict:
    """Fetch endpoint /data/llms/models. Retourne data + meta.

    Args:
        force: bypass cache.
    """
    if not force and _cache_fresh():
        return _load_cache()
    api_key = _load_api_key()
    if not api_key:
        return {"error": "no_api_key", "models": [], "meta": {}}
    url = f"{API_BASE}/data/llms/models"
    req = urllib.request.Request(
        url,
        headers={
            "x-api-key": api_key,
            "User-Agent": "LaForge/1.0 (forge_artificialanalysis)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        # Schema attendu : {"data": [models...]} ou liste directe
        if isinstance(data, list):
            models = data
        elif isinstance(data, dict):
            models = data.get("data", data.get("models", []))
        else:
            models = []
        payload = {
            "models": models,
            "meta": {
                "fetched_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": url,
                "count": len(models),
            },
        }
        _save_cache(payload)
        return payload
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "models": [], "meta": {}}
    except Exception as e:
        return {"error": str(e)[:200], "models": [], "meta": {}}


def get_model_metrics(model_slug: str) -> Optional[dict]:
    """Retourne metrics complets d'un modele par slug ou id AA."""
    data = fetch_llms()
    for m in data.get("models", []):
        if m.get("slug") == model_slug or m.get("id") == model_slug:
            return m
    return None


def get_provider_metrics(provider_name: str) -> Optional[dict]:
    """Retourne metrics du modele AA mappe a un provider Nokido."""
    slug = PROVIDER_AA_MAP.get(provider_name)
    if not slug:
        return None
    return get_model_metrics(slug)


def get_pricing(provider_name: str) -> Optional[dict]:
    """Extrait pricing (input/output $/1M tokens) pour un provider Nokido."""
    m = get_provider_metrics(provider_name)
    if not m:
        return None
    p = m.get("pricing", {})
    return {
        "in_usd_per_1m": p.get("price_1m_input_tokens"),
        "out_usd_per_1m": p.get("price_1m_output_tokens"),
        "blended_usd_per_1m": p.get("price_1m_blended_3_to_1"),
    }


def get_speed(provider_name: str) -> Optional[float]:
    """Tokens/sec mediane output."""
    m = get_provider_metrics(provider_name)
    if not m:
        return None
    return m.get("median_output_tokens_per_second")


def get_ttft(provider_name: str) -> Optional[float]:
    """Time to first token mediane (secondes)."""
    m = get_provider_metrics(provider_name)
    if not m:
        return None
    return m.get("median_time_to_first_token_seconds")


def get_quality_score(provider_name: str, eval_name: str = "artificial_analysis_intelligence_index") -> Optional[float]:
    """Score qualite. eval_name typique :
    - 'artificial_analysis_intelligence_index' (composite)
    - 'mmlu_pro' (general knowledge)
    - 'gpqa' (reasoning)
    - 'aime' (math)
    - 'humaneval' (coding)
    - 'lcb' (livecodebench)
    """
    m = get_provider_metrics(provider_name)
    if not m:
        return None
    evals = m.get("evaluations", {}) or {}
    return evals.get(eval_name)


def display_summary(top_n: int = 20) -> str:
    """CLI summary : top providers par intelligence index."""
    data = fetch_llms()
    if data.get("error"):
        return f"Error: {data['error']}"
    models = data.get("models", [])
    if not models:
        return "No models in cache. Run --refresh."
    # Tri par intelligence index desc
    scored = []
    for m in models:
        evals = m.get("evaluations", {}) or {}
        score = evals.get("artificial_analysis_intelligence_index")
        if score is None:
            continue
        scored.append((score, m))
    scored.sort(reverse=True, key=lambda x: x[0])
    lines = [
        f"=== ArtificialAnalysis.ai top {top_n} models (refresh {data.get('meta', {}).get('fetched_utc', '?')}) ===",
        f"{'Rank':<5}{'Model':<35}{'Score':<7}{'$/1M in':<10}{'$/1M out':<10}{'tok/s':<8}{'TTFT':<6}",
        "-" * 85,
    ]
    for i, (score, m) in enumerate(scored[:top_n], 1):
        name = (m.get("name") or m.get("slug") or "?")[:33]
        p = m.get("pricing", {}) or {}
        p_in = f"${p.get('price_1m_input_tokens', 0):.2f}"
        p_out = f"${p.get('price_1m_output_tokens', 0):.2f}"
        speed = m.get("median_output_tokens_per_second", 0) or 0
        ttft = m.get("median_time_to_first_token_seconds", 0) or 0
        lines.append(f"{i:<5}{name:<35}{score:<7.0f}{p_in:<10}{p_out:<10}{speed:<8.0f}{ttft:<6.2f}")
    return "\n".join(lines)


def best_for_use_case(use_case: str, free_only: bool = False, top_n: int = 5) -> list[dict]:
    """Retourne top providers Nokido ranked par metric appropriee au use_case.

    use_case -> eval_name mapping :
        code/mermaid -> humaneval / lcb (coding)
        reasoning/strategy -> gpqa (reasoning)
        speed -> tokens/sec (pas score)
        general -> artificial_analysis_intelligence_index
    """
    try:
        from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS, is_free as _is_free
    except ImportError:
        return []

    # Map use_case -> eval metric AA (verifie schema reel 2026-05-23)
    eval_map = {
        "code": "artificial_analysis_coding_index",
        "mermaid": "artificial_analysis_coding_index",
        "reasoning": "gpqa",
        "strategy": "gpqa",
        "synthesis": "mmlu_pro",
        "general": "artificial_analysis_intelligence_index",
        "long_doc": "artificial_analysis_intelligence_index",
        "math": "artificial_analysis_math_index",
        "agent": "tau2",
        "tool_call": "tau2",
    }
    eval_name = eval_map.get(use_case, "artificial_analysis_intelligence_index")
    scored = []
    for prov_name in PROVIDER_SPECS:
        if free_only and not _is_free(prov_name):
            continue
        m = get_provider_metrics(prov_name)
        if not m:
            continue
        if use_case == "speed":
            metric = m.get("median_output_tokens_per_second")
        else:
            metric = (m.get("evaluations") or {}).get(eval_name)
        if metric is None:
            continue
        scored.append(
            {
                "provider": prov_name,
                "model_aa": m.get("slug"),
                "metric_name": "tokens_per_second" if use_case == "speed" else eval_name,
                "metric_value": metric,
                "pricing": m.get("pricing", {}),
                "tier": PROVIDER_SPECS[prov_name].get("tier"),
            }
        )
    scored.sort(key=lambda x: x["metric_value"], reverse=True)
    return scored[:top_n]


def discover_free_providers(min_quality: float = 30.0) -> list[dict]:
    """Decouvre providers AA avec pricing=0 OU quasi-gratuit + qualite minimale.

    Filtre par :
    - pricing in/out == 0 ou < 0.1 $/1M (= free tier ou ultra-cheap)
    - intelligence_index >= min_quality (defaut 30, filtre les modeles trop faibles)
    - presence de host_providers libres (groq, sambanova, cerebras, nvidia, etc.)

    Compare avec PROVIDER_AA_MAP : si modele present dans AA mais slug pas dans
    notre map -> opportunite a integrer dans Nokido.
    """
    data = fetch_llms()
    if data.get("error"):
        return [{"error": data["error"]}]
    known_slugs = set(s for s in PROVIDER_AA_MAP.values() if s)
    candidates = []
    for m in data.get("models", []):
        slug = m.get("slug")
        if not slug:
            continue
        p = m.get("pricing", {}) or {}
        p_in = p.get("price_1m_input_tokens") or 0
        p_out = p.get("price_1m_output_tokens") or 0
        is_free_pricing = (p_in == 0 and p_out == 0) or (p_in < 0.1 and p_out < 0.1)
        if not is_free_pricing:
            continue
        evals = m.get("evaluations", {}) or {}
        quality = evals.get("artificial_analysis_intelligence_index") or 0
        if quality < min_quality:
            continue
        candidates.append(
            {
                "slug": slug,
                "name": m.get("name", slug),
                "creator": (m.get("model_creator") or {}).get("name", "?"),
                "release_date": m.get("release_date", "?"),
                "quality": quality,
                "coding_index": (m.get("evaluations") or {}).get("artificial_analysis_coding_index"),
                "math_index": (m.get("evaluations") or {}).get("artificial_analysis_math_index"),
                "price_in_1m": p_in,
                "price_out_1m": p_out,
                "tokens_per_second": m.get("median_output_tokens_per_second", 0) or 0,
                "ttft_s": m.get("median_time_to_first_token_seconds", 0) or 0,
                "in_nokido_map": slug in known_slugs,
            }
        )
    candidates.sort(key=lambda x: (not x["in_nokido_map"], -x["quality"]))
    return candidates


def discover_new_only(min_quality: float = 30.0) -> list[dict]:
    """Sous-ensemble de discover_free_providers : uniquement ceux ABSENTS du
    PROVIDER_AA_MAP actuel = opportunites concretes a integrer.
    """
    return [c for c in discover_free_providers(min_quality) if not c.get("in_nokido_map")]


def display_discovery(min_quality: float = 30.0, only_new: bool = True) -> str:
    """CLI summary discoveries : suggere providers a integrer dans Nokido."""
    rows = discover_new_only(min_quality) if only_new else discover_free_providers(min_quality)
    if not rows:
        return "Aucun candidat trouve (cache vide ? Lance --refresh)."
    if rows and "error" in rows[0]:
        return f"Error: {rows[0]['error']}"
    title = "NEW free/cheap providers AA (absents PROVIDER_AA_MAP)" if only_new else "ALL free/cheap providers AA"
    lines = [
        f"=== {title} - min_quality={min_quality} ({len(rows)} candidats) ===",
        f"{'Status':<6}{'Slug':<32}{'Creator':<16}{'Released':<12}{'Qual':<5}{'Code':<5}{'Math':<5}{'$in/1M':<8}{'$out/1M':<8}{'tok/s':<7}{'TTFT'}",
        "-" * 120,
    ]
    for r in rows:
        flag = "NEW" if not r.get("in_nokido_map") else "ok"
        code = r.get("coding_index")
        code_s = f"{code:.0f}" if code is not None else "-"
        math = r.get("math_index")
        math_s = f"{math:.0f}" if math is not None else "-"
        lines.append(
            f"{flag:<6}{r['slug'][:30]:<32}{r['creator'][:14]:<16}{r.get('release_date', '?')[:10]:<12}"
            f"{r['quality']:<5.0f}{code_s:<5}{math_s:<5}"
            f"{r['price_in_1m']:<8.3f}{r['price_out_1m']:<8.3f}"
            f"{r['tokens_per_second']:<7.0f}{r.get('ttft_s', 0):.2f}"
        )
    if only_new and rows:
        lines.append("")
        lines.append("ACTION : pricing=0 = modele open weights. Hebergement via :")
        lines.append("  - OpenRouter   : prefix 'openrouter_' + slug")
        lines.append("  - HuggingFace  : prefix 'hf_' + slug")
        lines.append("  - Ollama local : si modele dispo via 'ollama pull'")
        lines.append("  - Self-host vLLM : poids HF + GPU/CPU local")
        lines.append("Puis : ajouter dans PROVIDER_AA_MAP + Provider class + PROVIDER_SPECS")
    return "\n".join(lines)


def has_api_key() -> bool:
    return _load_api_key() is not None


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--refresh" in args:
        print("[AA] Refreshing cache...")
        data = fetch_llms(force=True)
        if data.get("error"):
            print(f"[AA] ERROR: {data['error']}")
        else:
            print(f"[AA] OK fetched {data['meta']['count']} models, saved to {CACHE_PATH}")
    elif "--summary" in args:
        print(display_summary())
    elif "--best" in args:
        use_case = args[args.index("--best") + 1] if len(args) > args.index("--best") + 1 else "general"
        free_only = "--free" in args
        rows = best_for_use_case(use_case, free_only=free_only)
        print(f"=== Best providers for use_case={use_case} (free_only={free_only}) ===")
        for r in rows:
            print(f"  {r['provider']:<25} ({r['tier']:<22}) {r['metric_name']}={r['metric_value']:.1f}")
    elif "--key-check" in args:
        print(f"API key found: {has_api_key()}")
    elif "--discover" in args:
        only_new = "--all" not in args
        min_q = 30.0
        if "--min-quality" in args:
            try:
                min_q = float(args[args.index("--min-quality") + 1])
            except Exception:
                pass
        print(display_discovery(min_quality=min_q, only_new=only_new))
    else:
        print("Usage: forge_artificialanalysis.py")
        print("  --refresh                       refresh cache 24h")
        print("  --summary                       top 20 modeles intelligence index")
        print("  --best <use_case> [--free]      best provider mappe pour use_case")
        print("  --discover [--all] [--min-quality N]   nouveaux free tiers a integrer")
        print("  --key-check                     verifie cle API")
