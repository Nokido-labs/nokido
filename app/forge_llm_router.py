"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_llm_router
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `repli_oauth` — AGY puis Claude Code quand la cascade est epuisee par la CAPACITE ; None si non permis ou si les deux echouent.
- `repli_oauth_autorise` — Vrai seulement si AUCUNE garde n'a parle et si CHAQUE echec est un echec de capacite.
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_llm_router.py — Routeur LLM Multi-Providers Ring 8
=============================================================
Orchestre les appels LLM en alternant les providers via LiteLLM.
Maximise le débit cumulé en cascadant les quotas gratuits.

Ordre de priorité par cas d'usage (configurable) :
  Vitesse    : groq → gemini-flash → ollama → deepseek
  Contexte   : gemini-pro (1M tokens) → deepseek → mistral
  Code       : deepseek-coder → qwen-local → hf-qwen → gemini
  EU/RGPD    : mistral → gemini → ollama (zéro données hors EU si possible)
  Gratuit max: gemini-flash → groq → mistral → hf → deepseek

Ring 8 — Exécution distante :
  Chaque provider est un "slot" avec son quota, son état et son dernier appel.
  Le routeur sélectionne le meilleur slot disponible selon le cas d'usage.
  Fallback automatique si HTTP 429 (rate limit) ou timeout.

Variables .env lues :
  GEMINI_API_KEY, GROQ_API_KEY, HF_TOKEN,
  DEEPSEEK_API_KEY, MISTRAL_API_KEY
  LITELLM_MODEL (provider par défaut)
  LAFORGE_ENV=dev → pas d'appels réels si aucune clé
"""

import os
import time
from pathlib import Path
from typing import Optional

# litellm : utiliser le cost-map LOCAL (évite un fetch github bloquant à l'import
# -> WinError 10013 socket + retry/délai par process). Doit être posé AVANT import litellm.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# litellm >= 1.96 charge l'encodage tiktoken `cl100k_base` A L'IMPORT (chaine
# compression -> token_counter -> default_encoding). Deux pieges mesures le 2026-09-07 :
#
#  1. litellm ECRASE `TIKTOKEN_CACHE_DIR` par son dossier interne. La seule variable qu'il
#     respecte est `CUSTOM_TIKTOKEN_CACHE_DIR` (cf. son default_encoding.py) -- poser
#     l'autre ne sert a RIEN, verifie.
#  2. le fichier livre dans le paquet porte le bon NOM (sha1 de l'URL) mais pas le bon
#     CONTENU pour tiktoken 0.12 : sha256 59d2daf6... contre 223921b7... attendu. tiktoken
#     le rejette donc et RETELECHARGE.
#
# Consequence sans ce garde : l'import casse sur les DEUX comptes du hub -- WinError 10013
# sous un compte sans egress, PermissionError sous un compte qui a le reseau mais pas le
# droit d'ecrire dans site-packages. Le cache verifie par empreinte vit dans
# sandbox/tiktoken_cache. S'il est absent, on ne pose rien et litellm retombe sur son
# comportement d'origine : ce garde n'ajoute aucun echec, il en retire.
_CACHE_TIKTOKEN = Path(__file__).resolve().parent.parent / "sandbox" / "tiktoken_cache"
if _CACHE_TIKTOKEN.is_dir():
    os.environ.setdefault("CUSTOM_TIKTOKEN_CACHE_DIR", str(_CACHE_TIKTOKEN))

# Stratégies de retry LLM-aware (tenacity + rate-limit headers)
try:
    from tenacity import retry, stop_after_attempt
    from nokido_agent.app.forge_retry_strategies import (
        wait_retry_after,
        wait_rpm_budget,
        retry_if_rate_limited,
        wait_exp_jitter,
        CircuitBreaker,
    )

    _HAS_TENACITY = True
except ImportError:
    _HAS_TENACITY = False

    # Fallback no-op CircuitBreaker si tenacity absent
    class CircuitBreaker:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            pass

        def allow(self):
            return True

        def record_success(self):
            pass

        def record_failure(self):
            pass

        @classmethod
        def snapshot(cls):
            return {}


ROOT = Path(__file__).resolve().parent.parent


def _emit_nervous_event(event_type: str, payload: dict) -> None:
    """Fire-and-forget POST vers Deno nervous_system :8765."""
    import threading, urllib.request, json as _json, time as _t

    def _post():
        try:
            data = _json.dumps({"type": event_type, "payload": payload, "ts": _t.time()}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:8765/event", data=data, headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=1)
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


# ── Configuration des providers ───────────────────────────────────────────────

# Un slot porteur de ce marqueur reste DECRIT ici (trace de ce qu'on a cru
# posseder) mais n'est plus jamais servi : voir chaine_active().
_PERIME_GITHUB = ("2026-08-18 : backend GitHub Models RETIRE — 410 Gone sur le "
                  "catalogue ET sur une inference reelle, avec un PAT models:read "
                  "valide (mesure tools/forge_token_probe.py)")

PROVIDERS = {
    # name : {models, env_key, base_url, rpm_limit, tpm_limit, ring, latency_ms}
    "gemini_flash": {
        # 2026-08-18 : quota gratuit compte PAR MODELE. `pro` = 429, `flash`
        # pleins = reponse vide ; seule la famille flash-lite repond (essai reel
        # sur 17 modeles, tools/forge_gemini_models_sync.py --essai --large).
        "models": ["gemini/gemini-flash-lite-latest", "gemini/gemini-3.5-flash-lite"],
        "env_key": "GEMINI_API_KEY",
        "base_url": None,
        "rpm": 15,
        "tpm": 1_000_000,
        "ring": 8,
        "latency": 800,
        "cost_tier": 1,
        "use_case": ["context", "inspect", "general"],
        "note": "1M context — idéal Inspecteur R4",
    },
    "gemini_pro": {
        # gemini-1.5-pro a disparu du catalogue ; gemini-2.5-pro est « no longer
        # available to new users » ; gemini-3.1-pro-preview rend 429 (quota).
        "models": ["gemini/gemini-3.5-flash-lite", "gemini/gemini-3.1-flash-lite"],
        "env_key": "GEMINI_API_KEY",
        "base_url": None,
        "rpm": 2,
        "tpm": 32_000,
        "ring": 8,
        "latency": 2000,
        "cost_tier": 3,
        "use_case": ["reasoning", "complex"],
        "note": "Raisonnement complexe",
    },
    "gemini_flash_lite": {
        "models": ["gemini/gemini-3.1-flash-lite", "gemini/gemini-2.5-flash-lite"],
        "env_key": "GEMINI_API_KEY",
        "base_url": None,
        "rpm": 10,
        "tpm": 250_000,
        "ring": 8,
        "latency": 600,
        "cost_tier": 1,
        "use_case": ["speed", "general", "classify_domain"],
        "note": "Flash Lite — 10 RPM, 250K ctx, léger",
    },
    "gemini_gemma": {
        # gemma-3-* ont disparu ; gemma-4-31b-it figure au catalogue mais ne rend
        # rien. On garde un flash-lite distinct des autres slots.
        "models": ["gemini/gemini-2.5-flash-lite"],
        "env_key": "GEMINI_API_KEY",
        "base_url": None,
        "rpm": 30,
        "tpm": 15_000,
        "ring": 8,
        "latency": 700,
        "cost_tier": 0,
        "use_case": ["general", "speed", "write_tests"],
        "note": "Gemma 3 open-weight — 30 RPM gratuit",
    },
    "openrouter_free": {
        # `openrouter/auto` est ABSENT du catalogue (mesure 2026-08-18). Le
        # nemotron :free, lui, est gratuit ANNONCE, appelle l'outil, 205 tok/s.
        #
        # POOL (2026-09-01) : cette liste n'est plus figee — elle est RECRITE au
        # demarrage par forge_agent_proxy.refresh_openrouter_free_slugs(), qui
        # interroge le catalogue par PRIX (entree ET sortie a zero, sortie texte,
        # tool-calling annonce). Mesure du jour : 420 modeles, 21 gratuits, 18
        # utilisables. Les valeurs ci-dessous sont le SOCLE hors ligne, pas la
        # verite : un slug code en dur est un point de defaillance unique, et les
        # slugs `:free` se font retirer sans preavis.
        #
        # models[0] = `openrouter/free`, le routeur gratuit COTE SERVEUR : seul
        # slug qui survive au retrait d'un modele. Prefixe `openrouter/` =
        # convention litellm, VERIFIEE : get_llm_provider rend ("openrouter/free",
        # "openrouter") et l'appel reel repond "pong" en 2,8 s.
        "models": ["openrouter/openrouter/free",
                   "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"],
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "cost_tier": 0,
        "ring": 8,
        "latency": 2000,
        "outils": True,          # MESURE : tool_calls conforme
        "debit_tok_s": 205,
        "mesure": "2026-08-18",
        "use_case": ["reasoning", "debate", "strategy", "tool_call"],
        "note": "nemotron :free — raisonnement, gratuit ANNONCE, appelle les outils",
    },
    "nvidia_nemotron_super": {
        # Le PLUS GROS modele du parc qui reponde reellement (audit 2026-08-28 :
        # [OK] nvidia_nim -> nvidia/nemotron-3-super-120b-a12b). Il existait comme
        # provider runtime — donc appelable a la main par `ask provider=nvidia_nim` —
        # mais n'avait AUCUN slot : le ROUTEUR ne pouvait pas le choisir, et il etait
        # donc absent de toute cascade de raisonnement. 120B contre les 30B du
        # nemotron :free d'openrouter, sur le meme role.
        "models": ["nvidia/nemotron-3-super-120b-a12b"],
        "env_key": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "openai_compat": True,   # endpoint OpenAI-compat : cf. _is_openai_compat_custom
        "cost_tier": 0,
        "ring": 8,
        "latency": 2500,
        "rpm_limit": 40,         # free dev key : 40 RPM, 1000 appels/mois
        "context": 32000,
        "use_case": ["reasoning", "debate", "strategy", "synthesis"],
        "note": "Nemotron-3-Super-120B (NVIDIA NIM free 40 RPM) — juge fort",
    },
    "groq_fast": {
        # 2026-08-18 : llama-3.1-8b-instant et llama-3.3-70b-versatile ont
        # disparu du catalogue Groq (mesure GET /openai/v1/models : 200, 13
        # modeles, aucun des deux). La cle etait valide — c'est le modele qui
        # etait mort, et la rotation accusait la cle.
        # gpt-oss-20b en TETE : mesure du 2026-08-18, c'est le seul Groq teste
        # qui APPELLE reellement un outil (359 tok/s, 0,26 s). Le 120b, lui,
        # rend un contenu vide sur budget court (modele de raisonnement).
        "models": ["groq/openai/gpt-oss-20b", "groq/openai/gpt-oss-120b"],
        "env_key": "GROQ_API_KEY",
        "base_url": None,
        "rpm": 30,
        "tpm": 6000,
        "ring": 8,
        "latency": 260,
        "outils": True,          # MESURE : tool_calls conforme, arguments JSON valides
        "debit_tok_s": 359,
        "mesure": "2026-08-18",
        "use_case": ["speed", "collab", "tool_call", "orchestration"],
        "note": "359 tok/s, 0,26 s — le plus rapide qui sache appeler un outil",
    },
    "groq_allam": {
        # 572 tok/s, 0,15 s : le plus rapide du parc entier — mais il REFUSE les
        # outils (`tool calling is not supported`). Le cabler en orchestration
        # aurait ete le pire choix possible, et c'etait le meilleur sur la seule
        # vitesse : d'ou un slot distinct plutot qu'un compromis.
        "models": ["groq/allam-2-7b"],
        "env_key": "GROQ_API_KEY",
        "base_url": None,
        "rpm": 30,
        "tpm": 6000,
        "ring": 8,
        "latency": 150,
        "outils": False,         # MESURE : refus explicite (HTTP 400)
        "debit_tok_s": 572,
        "mesure": "2026-08-18",
        "use_case": ["speed", "sentinel", "inspect"],
        "note": "572 tok/s — surveillance et classification, JAMAIS d'orchestration",
    },
    "groq_mixtral": {
        # mixtral-8x7b-32768 retire par Groq ; compound-mini est au catalogue.
        "models": ["groq/groq/compound-mini"],
        "env_key": "GROQ_API_KEY",
        "base_url": None,
        "rpm": 30,
        "tpm": 5000,
        "ring": 8,
        "latency": 300,
        "use_case": ["speed", "code"],
        "note": "MoE rapide",
    },
    # NOTE: anciens stubs DeepSeek "openrouter_gpt_oss"/"openrouter_qwen_coder"
    # supprimes (KEY_EXPIRED + dup keys ecrases plus bas par les vrais OpenRouter
    # entries lignes ~325/347). Cleanup 2026-05-02.
    "mistral_small": {
        # ministral-8b mesure le 2026-08-18 : appelle l'outil, 0,34 s, 112 tok/s.
        # `mistral-small-latest` reste en second : joignable, mais non teste sur
        # les outils — on ne promeut pas ce qu'on n'a pas mesure.
        "models": ["mistral/ministral-8b-2512", "mistral/mistral-small-latest"],
        "env_key": "MISTRAL_API_KEY",
        "base_url": None,
        "rpm": 30,
        "tpm": 100_000,
        "ring": 8,
        "latency": 340,
        "outils": True,          # MESURE : tool_calls conforme
        "debit_tok_s": 112,
        "mesure": "2026-08-18",
        "use_case": ["eu", "mesh", "tool_call", "orchestration", "general"],
        "note": "Souverain EU — appelle les outils, 0,34 s",
    },
    "mistral_codestral": {
        # MESURE 2026-09-25 (tools/forge_tool_call_probe.py --modeles) : codestral-latest
        # APPELLE l'outil. Modele de CODE, tete de la chaine `agent_code` (nokido/auto de la
        # passerelle :7777 -- opencode). Meme cle que mistral_small : quota PARTAGE.
        # Capacite (tpm, contexte) NON mesuree : non declaree ici plutot qu'inventee -- un
        # depassement se lira au 413 du fournisseur, et nokido/auto basculera.
        "models": ["mistral/codestral-latest"],
        "env_key": "MISTRAL_API_KEY",
        "base_url": None,
        "rpm": 30,
        "ring": 8,
        "outils": True,          # MESURE : tool_calls conforme (2026-09-25)
        "mesure": "2026-09-25",
        "use_case": ["code", "agent_code", "tool_call"],
        "note": "Codestral (Mistral) — code, appelle les outils",
    },
    "mistral_large": {
        "models": ["mistral/mistral-large-latest"],
        "env_key": "MISTRAL_API_KEY",
        "base_url": None,
        "rpm": 5,
        "tpm": 32_000,
        "ring": 8,
        "latency": 1500,
        "use_case": ["reasoning", "eu"],
        "note": "Raisonnement EU",
    },
    "hf_qwen_coder": {
        # Router HuggingFace v1 OpenAI-compat (2026-04)
        "models": ["openai/Qwen/Qwen2.5-Coder-32B-Instruct:novita"],
        "env_key": "HF_TOKEN",
        "base_url": "https://router.huggingface.co/v1",
        "rpm": 10,
        "tpm": 50_000,
        "ring": 8,
        "latency": 2000,
        "use_case": ["mermaid", "code"],
        "note": "Qwen coder via HF router :novita — gratuit",
    },
    "hf_llama": {
        # Router HuggingFace v1 OpenAI-compat - Llama-3.1-8B confirme OK 2026-04-17
        "models": ["openai/meta-llama/Llama-3.1-8B-Instruct:novita"],
        "env_key": "HF_TOKEN",
        "base_url": "https://router.huggingface.co/v1",
        "rpm": 10,
        "tpm": 30_000,
        "ring": 8,
        "latency": 1000,
        "use_case": ["general", "speed"],
        "note": "HF router Llama-3.1-8B — gratuit, 1s latency confirme",
    },
    "llamacpp_local": {
        # Serveur LLM local en mode OpenAI-compat.
        # llama-server Vulkan :8091 (Qwen2.5-Coder-7B + speculative decoding 1.5B draft).
        # Port configurable via env LAFORGE_LLAMACPP_PORT (defaut 8091 = llama-server Vulkan).
        # Lancer via NokidoLlamaNative NSSM ou tools/nokido_llamacpp_native.bat
        "models": [
            "laforge-coder",  # alias llama-server :8091 (Qwen2.5-Coder-7B Vulkan)
            "qwen2.5-coder",  # alias secondaire
            "openai/laforge-qwen:latest",
        ],
        "env_key": "FORGE_LLAMA_KEY",  # llama-server exige --api-key (auth obligatoire)
        "base_url": f"http://127.0.0.1:{os.environ.get('LAFORGE_LLAMACPP_PORT', '8091')}/v1",
        "rpm": 999,
        "tpm": 999_999,
        "ring": 3,
        "latency": 300,
        "use_case": ["speed", "code", "general", "collab", "debug", "synthesis", "orchestration"],
        "note": "Qwen2.5-Coder-7B Vulkan :8091 (speculative decoding, --mlock, KV q8) — prioritaire",
    },
    "lmstudio_native": {
        # `openai/local-model` etait un nom generique ; le serveur expose ses
        # vrais identifiants. Les deux mesures du 2026-08-18 APPELLENT l'outil.
        # ⚠️ Rend 401 sans `LMSTUDIO_TOKEN` — sans lui on le croit mort.
        # ⚠️ Identifiants NUS, sans prefixe `openai/` : mesure du 2026-08-18,
        # `openai/qwen2.5-7b-instruct` -> HTTP 400 en 70 ms, `qwen2.5-7b-instruct`
        # -> accepte. Le message rendu, « No models loaded. Please load a model »,
        # decrit un modele INCONNU et non un defaut de chargement : il m'a fait
        # chercher un reglage JIT pendant trois passes. Meme piege que `gemini/x`
        # contre `models/x`, documente le matin meme — un prefixe ne se suppose
        # jamais, il se lit dans `GET /v1/models`.
        "models": ["qwen2.5-7b-instruct", "qwen2.5-coder-7b-instruct"],
        "env_key": "LMSTUDIO_TOKEN",
        "base_url": "http://localhost:1234/v1",
        "rpm": 999,
        "tpm": 999_999,
        "ring": 3,
        "latency": 960,
        "outils": True,          # MESURE : tool_calls conforme
        "debit_tok_s": 15,
        "mesure": "2026-08-18",
        "use_case": ["code", "tool_call", "orchestration", "general"],
        "note": "local, sans quota ni egress — lent (15 tok/s) mais fiable",
    },
    "ollama_local": {
        "models": ["ollama/qwen2.5-coder:7b-instruct-q4_K_M", "ollama/laforge-qwen:latest"],
        "env_key": "",  # pas de clé — local
        "base_url": "http://localhost:11434",
        "rpm": 999,
        "tpm": 999_999,
        "ring": 3,
        "latency": 400,
        "use_case": ["speed", "code", "general", "collab", "debug"],
        "note": "Local fallback — toujours disponible, apres llama.cpp",
    },
    "docker_local": {
        # Docker comme backend LLM : Docker Model Runner (OpenAI-compat) OU tout conteneur
        # LLM (vLLM/LocalAI/ollama-in-docker) via env DOCKER_LLM_BASE. Sort le modèle lourd
        # de l'iGPU 780M (conteneur isolé) -> désature la VRAM partagée avec gemma + le pool.
        # Activer : `docker desktop enable model-runner --tcp 12434` + `docker model pull ai/<model>`.
        "models": ["ai/qwen2.5", "ai/llama3.2", "openai/docker-model"],
        "env_key": "",  # DMR sans auth par défaut (token optionnel via DOCKER_LLM_TOKEN côté proxy)
        "base_url": os.environ.get("DOCKER_LLM_BASE", "http://localhost:12434/engines/v1"),
        "rpm": 999,
        "tpm": 999_999,
        "ring": 3,
        "latency": 350,
        "use_case": ["speed", "code", "general", "collab", "debug", "orchestration"],
        "note": "Docker Model Runner :12434 (conteneur LLM souverain, runtime garanti forge_docker_keeper)",
    },
    "xai_grok3": {
        "models": ["xai/grok-3-latest", "xai/grok-3-mini-latest"],
        "env_key": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "rpm": 60,
        "tpm": 131_072,
        "ring": 8,
        "latency": 1500,
        "use_case": ["reasoning", "general", "context"],
        "note": "xAI Grok-3 — 131K context, raisonnement avancé",
    },
    "xai_grok3_mini": {
        "models": ["xai/grok-3-mini-latest"],
        "env_key": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "rpm": 60,
        "tpm": 131_072,
        "ring": 8,
        "latency": 800,
        "use_case": ["speed", "collab", "debate"],
        "note": "xAI Grok-3 Mini — rapide + raisonnement",
    },
    # GitHub Models free tier (ajout 2026-04-17 — 7 modeles testes OK)
    # PERIMES le 2026-08-18 : GitHub a RETIRE le backend. Mesure (forge_token_probe,
    # avec un PAT models:read valide, 200 sur /user) : catalogue 410 Gone, POST
    # d'inference 410 Gone, models.inference.ai.azure.com 404. Un 410 n'est ni un
    # 401 ni un 403 : ce n'est pas un droit qui manque, c'est le service qui n'est
    # plus la. Les slots restent ICI, marques — les supprimer effacerait la trace
    # de ce qu'on a cru posseder pendant quatre mois (regle SSoT : marquer
    # [PERIMEE], jamais supprimer).
    # Endpoint : https://models.github.ai/inference/chat/completions
    # Format model : "{publisher}/{model-id}"
    # Un SEUL GITHUB_MODELS_TOKEN avec scope models:read donne acces a TOUS
    "github_gpt41_mini": {
        "perime": _PERIME_GITHUB,
        "models": ["openai/gpt-4.1-mini"],
        "env_key": "GITHUB_MODELS_TOKEN",
        "base_url": "https://models.github.ai/inference",
        "rpm": 15,
        "tpm": 128_000,
        "ring": 8,
        "latency": 1000,
        "use_case": ["general", "speed", "collab"],
        "note": "GitHub GPT-4.1-mini — gratuit, 128K ctx, 1s latency",
    },
    "github_gpt4o_mini": {
        "perime": _PERIME_GITHUB,
        "models": ["openai/gpt-4o-mini"],
        "env_key": "GITHUB_MODELS_TOKEN",
        "base_url": "https://models.github.ai/inference",
        "rpm": 15,
        "tpm": 128_000,
        "ring": 8,
        "latency": 1800,
        "use_case": ["general", "inspect", "sentinel"],
        "note": "GitHub GPT-4o-mini — gratuit, 128K ctx, versatile",
    },
    "github_llama_70b": {
        "perime": _PERIME_GITHUB,
        "models": ["meta/Llama-3.3-70B-Instruct"],
        "env_key": "GITHUB_MODELS_TOKEN",
        "base_url": "https://models.github.ai/inference",
        "rpm": 10,
        "tpm": 128_000,
        "ring": 8,
        "latency": 1400,
        "use_case": ["reasoning", "debate", "strategy"],
        "note": "GitHub Llama-3.3-70B — gratuit, 128K ctx, 1.4s latency, raisonnement",
    },
    "github_phi4_mini": {
        "perime": _PERIME_GITHUB,
        "models": ["microsoft/Phi-4-mini-instruct"],
        "env_key": "GITHUB_MODELS_TOKEN",
        "base_url": "https://models.github.ai/inference",
        "rpm": 15,
        "tpm": 128_000,
        "ring": 8,
        "latency": 3400,
        "use_case": ["synthesis"],
        "note": "GitHub Phi-4-mini — gratuit, 128K ctx",
    },
    "github_deepseek_v3": {
        "perime": _PERIME_GITHUB,
        "models": ["deepseek/DeepSeek-V3-0324"],
        "env_key": "GITHUB_MODELS_TOKEN",
        "base_url": "https://models.github.ai/inference",
        "rpm": 10,
        "tpm": 128_000,
        "ring": 8,
        "latency": 900,
        "use_case": ["code", "mermaid"],
        "note": "GitHub DeepSeek-V3 — gratuit, 128K ctx, 0.9s latency TOP",
    },
    "github_codestral": {
        "perime": _PERIME_GITHUB,
        "models": ["mistral-ai/Codestral-2501"],
        "env_key": "GITHUB_MODELS_TOKEN",
        "base_url": "https://models.github.ai/inference",
        "rpm": 10,
        "tpm": 256_000,
        "ring": 8,
        "latency": 1400,
        "use_case": ["code", "mermaid"],
        "note": "GitHub Codestral-2501 — gratuit, 256K ctx, code dedie",
    },
    "github_cohere_rp": {
        "perime": _PERIME_GITHUB,
        "models": ["cohere/cohere-command-r-plus-08-2024"],
        "env_key": "GITHUB_MODELS_TOKEN",
        "base_url": "https://models.github.ai/inference",
        "rpm": 10,
        "tpm": 128_000,
        "ring": 8,
        "latency": 2800,
        "use_case": ["context"],
        "note": "GitHub Command R+ — gratuit, 128K ctx, RAG optimise",
    },
    # OpenRouter free tier (29 modeles gratuits, ajout 2026-04-16)
    "openrouter_gpt_oss": {
        "models": ["openrouter/openai/gpt-oss-120b:free"],
        "env_key": "OPENROUTER_API_KEY",
        "base_url": None,  # litellm gere
        "rpm": 20,
        "tpm": 131_072,
        "ring": 8,
        "latency": 1500,
        "use_case": ["general", "reasoning", "context"],
        "note": "OpenRouter GPT-OSS 120B — gratuit, 131K ctx, top pick",
    },
    "openrouter_glm_air": {
        "models": ["openrouter/z-ai/glm-4.5-air:free"],
        "env_key": "OPENROUTER_API_KEY",
        "base_url": None,
        "rpm": 20,
        "tpm": 131_072,
        "ring": 8,
        "latency": 1200,
        "use_case": ["general", "collab", "debate"],
        "note": "OpenRouter GLM 4.5 Air — gratuit, multi-langue",
    },
    "openrouter_qwen_coder": {
        # qwen3.6-35b mesure le 2026-08-18 : 262 144 tokens de contexte — le
        # SEUL du parc a cette echelle — 151 tok/s. ⚠️ Il ANNONCE `tools` et ne
        # les honore pas (« ni outil ni texte ») : exclu de l'orchestration.
        "models": ["openrouter/qwen/qwen3.6-35b-a3b"],
        "env_key": "OPENROUTER_API_KEY",
        "base_url": None,
        "rpm": 10,
        "tpm": 262_000,
        "ring": 8,
        "latency": 550,
        "outils": False,         # MESURE : annonce `tools`, n'appelle jamais
        "debit_tok_s": 151,
        "mesure": "2026-08-18",
        "use_case": ["context", "synthesis", "code"],
        "note": "262K ctx — digestion de logs ; JAMAIS d'orchestration (annonce sans honorer)",
    },
    # Cohere v2 free tier (ajout 2026-05-02 — 6 idle providers wiring)
    # https://api.cohere.com/v2/chat (OpenAI-compat via litellm "cohere/" prefix)
    "cohere_command_r_plus": {
        "models": ["cohere/command-r-08-2024"],
        "env_key": "COHERE_API_KEY",
        "base_url": None,
        "rpm": 20,
        "tpm": 128_000,
        "ring": 8,
        "latency": 1200,
        "use_case": ["context", "synthesis", "general"],
        "note": "Cohere Command R (free tier, command-r-plus=405 sur trial)",
    },
    "cohere_command_r": {
        "models": ["cohere/command-r-08-2024"],
        "env_key": "COHERE_API_KEY",
        "base_url": None,
        "rpm": 20,
        "tpm": 128_000,
        "ring": 8,
        "latency": 1200,
        "use_case": ["general", "speed", "synthesis"],
        "note": "Cohere Command R — gratuit (trial), 128K ctx, plus rapide que R+",
    },
    # SambaNova free tier (ajout 2026-05-02)
    # https://api.sambanova.ai/v1 (OpenAI-compat). Env key litterale dans Nokido.env :
    # "cloud.sambanova.ai_API_KEY" (point dans le nom — Python s'en accommode).
    "sambanova_llama_405b": {
        # 2026-08-18 : le 405B a quitte le palier gratuit SambaNova ; DeepSeek-V3.1
        # est au catalogue mesure (6 modeles).
        "models": ["sambanova/DeepSeek-V3.1"],
        "env_key": "SAMBANOVA_API_KEY",
        "base_url": "https://api.sambanova.ai/v1",
        "rpm": 10,
        "tpm": 16_000,
        "ring": 8,
        "latency": 2200,
        "use_case": ["reasoning", "debate", "strategy"],
        "note": "SambaNova Llama-3.1-405B — gratuit, 16K ctx, raisonnement lourd",
    },
    "sambanova_llama_70b": {
        # 3.1-70B remplace par 3.3-70B au catalogue.
        "models": ["sambanova/Meta-Llama-3.3-70B-Instruct"],
        "env_key": "SAMBANOVA_API_KEY",
        "base_url": "https://api.sambanova.ai/v1",
        "rpm": 20,
        "tpm": 16_000,
        "ring": 8,
        "latency": 1200,
        "use_case": ["general", "speed", "collab"],
        "note": "SambaNova Llama-3.1-70B — gratuit, ultra-rapide (Reconfigurable Dataflow)",
    },
    # NOTE: KAGGLE_API_TOKEN, SMITHERY_API : pas de chat-completion endpoint.
    # Kaggle = datasets/kernels (a router via forge_dataset_manager si besoin).
    # Smithery = MCP marketplace (a router via forge_clawhub_bridge si besoin).
    # NOTE: TAVILY_API_KEY deja wired dans app/forge_web_search.py::aggregate_search
    # (pas un LLM chat — search API).
}

def chaine_active(use_case: str = "general") -> list[str]:
    """Chaine du cas d'usage, PRIVEE de ses slots perimes.

    Mesure du 2026-08-18 : sur 16 chaines, SEPT commencaient par un slot dont le
    backend n'existe plus (`collab`, `debate`, `sentinel`, `inspect`,
    `reasoning`, `eu`, `mesh`). Chaque appel de ces cas d'usage demarrait donc
    par un echec garanti, paye en latence a chaque fois, sans que rien ne le
    dise : le routeur mesurait l'EXISTENCE d'un slot, jamais sa joignabilite.

    Filtrer ici plutot que d'amputer les 16 listes garde l'historique lisible et
    ne laisse qu'un seul endroit ou la regle s'applique.
    """
    brute = list(USE_CASE_CHAINS.get(use_case) or USE_CASE_CHAINS["general"])
    active = [n for n in brute if not (PROVIDERS.get(n) or {}).get("perime")]
    if active:
        return active
    # Une chaine entierement perimee ne doit pas rendre une liste vide (le
    # routeur tomberait sans candidat) : on rend le fallback absolu local.
    return [n for n in ("ollama_local", "llamacpp_local") if n in PROVIDERS]


# Cascades par cas d'usage (ordre = priorité)
# Reorganise 2026-04-17 selon diagnostic REEL des providers :
#   TOP : openrouter_gpt_oss + hf_qwen_coder (confirmes OK)
#   MID : openrouter_qwen_coder, openrouter_glm_air (rate-limit occasionnel mais OK)
#   GRAY: gemini_flash, groq_fast, xai (cles a regenerer, en attendant ils tombent vite en fallback)
#   LOCAL: ollama_local (toujours dispo — fallback absolu)
# ── CHAINES RECABLEES SUR MESURE, 2026-08-18 ────────────────────────────────
# L'ordre precedent datait d'avril et n'avait jamais ete confronte au reel :
# SEPT chaines sur seize demarraient par un slot dont le backend n'existe plus,
# et le seul critere disponible etait l'ordre de la liste. Chaque tete est
# desormais un slot dont la reponse a ete PROUVEE, et la mesure qui le justifie
# est ecrite a cote — pour que le prochain lecteur sache pourquoi, et puisse
# contester avec une mesure plutot qu'avec une intuition.
#
# Mesures (tools/forge_endpoint_profiling.py, tools/forge_tool_call_probe.py) :
#   groq_allam      572 tok/s · 0,15 s · REFUSE les outils
#   groq_fast       359 tok/s · 0,26 s · appelle
#   openrouter_free 205 tok/s · 0,44 s · appelle · raisonnement · gratuit annonce
#   qwen_coder      151 tok/s · 262 144 ctx · ANNONCE les outils sans les honorer
#   mistral_small   112 tok/s · 0,34 s · appelle · souverain EU
#   lmstudio         15 tok/s · local, sans quota ni egress · appelle
#
# INVARIANT : `orchestration` et `tool_call` ne contiennent QUE des slots dont
# `outils` est True. Un modele qui ignore l'outil repond une phrase polie et
# fait echouer la chaine EN SILENCE — c'est le faux-vert le plus cher.
USE_CASE_CHAINS = {
    # Court et nombreux : la vitesse prime, les outils ne servent pas.
    "speed": ["groq_allam", "groq_fast", "mistral_small", "openrouter_free",
              "lmstudio_native", "ollama_local"],
    "sentinel": ["groq_allam", "groq_fast", "gemini_flash", "mistral_small",
                 "lmstudio_native", "ollama_local"],
    "inspect": ["groq_allam", "groq_fast", "gemini_flash", "mistral_small",
                "lmstudio_native", "ollama_local"],
    # Echange soutenu : debit d'abord, puis souverainete.
    "collab": ["groq_fast", "mistral_small", "gemini_flash", "cohere_command_r",
               "lmstudio_native", "ollama_local"],
    "mesh": ["groq_fast", "mistral_small", "openrouter_free", "gemini_flash",
             "lmstudio_native", "ollama_local"],
    # Raisonnement : nemotron est un modele de RAISONNEMENT et il appelle.
    # nvidia_nemotron_super en tete : 120B mesure OK le 2026-08-28, quand la tete
    # precedente (nemotron :free, 30B) reste juste derriere en repli.
    "reasoning": ["nvidia_nemotron_super", "openrouter_free", "gemini_pro",
                  "mistral_large", "cohere_command_r_plus", "lmstudio_native",
                  "ollama_local"],
    "debate": ["nvidia_nemotron_super", "openrouter_free", "gemini_pro",
               "mistral_large", "cohere_command_r_plus", "lmstudio_native",
               "ollama_local"],
    "strategy": ["nvidia_nemotron_super", "openrouter_free", "gemini_pro",
                 "mistral_large", "cohere_command_r_plus", "lmstudio_native",
                 "ollama_local"],
    # Grande fenetre : qwen3.6-35b est le SEUL du parc a 262K.
    "context": ["openrouter_qwen_coder", "cohere_command_r_plus", "gemini_flash",
                "mistral_large", "lmstudio_native", "ollama_local"],
    "synthesis": ["openrouter_qwen_coder", "cohere_command_r_plus", "cohere_command_r",
                  "gemini_flash", "lmstudio_native", "ollama_local"],
    # Code : le local d'abord (illimite, aucun egress de source), cloud ensuite.
    "code": ["lmstudio_native", "openrouter_qwen_coder", "mistral_small",
             "openrouter_gpt_oss", "ollama_local", "llamacpp_local"],
    "mermaid": ["lmstudio_native", "openrouter_qwen_coder", "mistral_small",
                "openrouter_gpt_oss", "ollama_local", "llamacpp_local"],
    # Souverainete europeenne : Mistral, puis local. Aucun autre.
    "eu": ["mistral_small", "mistral_large", "lmstudio_native", "ollama_local",
           "llamacpp_local"],
    "general": ["mistral_small", "groq_fast", "gemini_flash", "openrouter_free",
                "cohere_command_r", "lmstudio_native", "ollama_local"],
    # INVARIANT : uniquement des slots `outils: True`, verifie par test NR.
    "orchestration": ["mistral_small", "groq_fast", "openrouter_free",
                      "lmstudio_native"],
    "tool_call": ["mistral_small", "groq_fast", "openrouter_free", "lmstudio_native"],
    # Agent de CODE (nokido/auto, passerelle :7777) : un tour = prompt + schemas d'outils
    # (~25 k jetons mesures pour opencode). Codestral en tete (code, appelle) ; groq_fast
    # (tpm 6000 declare) sera ecarte sur capacite ; lmstudio en dernier recours LOCAL.
    "agent_code": ["mistral_codestral", "mistral_small", "groq_fast", "openrouter_free",
                   "lmstudio_native"],
}


# ── Repli OAuth de fin de cascade (owner 2026-09-25) ────────────────────────────
# « Au pire tu routes vers agy oauth ou claude code. » Mesure du jour : groq 403 (cle refusee),
# deepseek/cerebras/hf 402, mistral-large/medium/small hors palier (limite 0 req/min), zai/mammouth
# 429, locaux injoignables. L'ancien repli n'agissait que si TOUS les echecs etaient des 429, via un
# `gemini.cmd` code en dur en annoncant « gemini-2.5-pro » sans preuve. Desormais : fournisseurs
# DECLARES du proxy (gemini_cli = agy.exe, puis claude_cli), modele rendu = celui du fournisseur.
_REPLI_OAUTH = ("gemini_cli", "claude_cli")
_MARGE_PONT_S = 30  # au-dela du timeout de l'appel, le pont synchrone rend la main
# Liste BLANCHE : seul un echec de CAPACITE (le fournisseur ne PEUT pas servir) autorise le repli.
# PAS de « 403 » ni « forbidden » nus (debat CLAUDE<->AGY tour 2, 26/09, ACK-AUTOAMELIO) : un 403 de
# MODERATION de contenu cote fournisseur serait lu « capacite » et le prompt reroute = contournement d'un
# refus de contenu. Un 403 ne vaut capacite qu'avec un marqueur de palier ou de cle.
_ECHEC_CAPACITE = ("429", "rate limit", "rate_limit", "ratelimit", "resourceexhausted", "quota",
                   "402", "payment", "insufficient", "tier_not_allowed", "invalid_api_key", "invalid api key",
                   "401", "unauthorized", "ecartee", "indisponible", "unavailable", "cooldown", "timeout",
                   "timed out", "connection", "refused", "refusee", "reponse vide", "502", "503", "504")
# Plafond de replis OAuth par heure (debat tour 2) : sans lui, une panne large des API gratuites
# draine le quota des abonnements OAuth. Compte les TENTATIVES de repli, pas les reussites.
_REPLI_OAUTH_PLAFOND_H = 30
_REPLIS_RECENTS: list = []
# Un refus de GARDE ne reroute JAMAIS : la garde avait restreint la chaine (au local, souvent) ;
# rerouter vers le cloud la contournerait.
_REFUS_DE_GARDE = ("secretguard", "firewall", "pare-feu", "dlp", "injection", "security", "securite")


def repli_oauth_autorise(attempts, garde_a_parle: bool) -> bool:
    """Vrai seulement si AUCUNE garde n'a parle et si CHAQUE echec est un echec de capacite.
    Une cascade entierement ecartee (quota, disjoncteur, cooldown) n'a rien refuse : repli permis."""
    if garde_a_parle:
        return False
    for _slot, err in attempts:
        e = str(err).lower()
        if any(m in e for m in _REFUS_DE_GARDE) or not any(m in e for m in _ECHEC_CAPACITE):
            return False
    return True


def _demander_au_proxy(fournisseur: str, prompt: str, system: str, max_tokens: int, timeout: int) -> dict:
    """Appel SYNCHRONE d'un fournisseur declare du proxy. `call_cascade` est synchrone : meme pont
    `asyncio.run` que lmstudio_native, dans un fil dedie si une boucle tourne deja ici."""
    import asyncio
    import importlib

    _ap = importlib.import_module("nokido_agent.app.forge_agent_proxy")
    message = f"{system}\n\n{prompt}".strip() if system else prompt

    def _appel():
        return asyncio.run(_ap.ask(fournisseur, message, rag_context=False, max_tokens=max_tokens,
                                   timeout=timeout, raw=True))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _appel()
    import concurrent.futures as _cf

    # Pas de `with` : sa sortie attend la fin du fil MEME apres l'expiration de result(timeout),
    # et la borne ne protegerait rien. Le fil abandonne finit seul (le proxy borne son appel).
    _ex = _cf.ThreadPoolExecutor(max_workers=1)
    try:
        return _ex.submit(_appel).result(timeout=timeout + _MARGE_PONT_S)
    finally:
        _ex.shutdown(wait=False)


def repli_oauth(attempts: list, garde_a_parle: bool, prompt: str, system: str, max_tokens: int,
                timeout: int, use_case: str, t0: float):
    """AGY puis Claude Code quand la cascade est epuisee par la CAPACITE. None si non permis ou si
    les deux echouent -- chaque echec est ajoute a `attempts` (dit, jamais avale)."""
    if not repli_oauth_autorise(attempts, garde_a_parle):
        return None
    maintenant = time.time()
    _REPLIS_RECENTS[:] = [t for t in _REPLIS_RECENTS if maintenant - t < 3600]
    if len(_REPLIS_RECENTS) >= _REPLI_OAUTH_PLAFOND_H:
        attempts.append(("repli_oauth", f"plafond horaire atteint ({_REPLI_OAUTH_PLAFOND_H}/h) -- pas de repli"))
        return None
    _REPLIS_RECENTS.append(maintenant)
    for fournisseur in _REPLI_OAUTH:
        try:
            r = _demander_au_proxy(fournisseur, prompt, system, max_tokens, max(timeout, 60)) or {}
        except Exception as exc:  # noqa: BLE001 - l'echec du repli est TRACE dans attempts
            attempts.append((fournisseur, f"{type(exc).__name__}: {str(exc)[:90]}"))
            continue
        texte = r.get("text") or ""
        if r.get("ok") and texte.strip():
            _emit_nervous_event("llm_response", {"provider": fournisseur, "use_case": use_case, "ok": True,
                                                 "fallback_reason": "cascade_capacite"})
            return {"ok": True, "text": texte, "provider": fournisseur, "model": r.get("model"),
                    "elapsed_ms": round((time.monotonic() - t0) * 1000, 1), "tokens": 0,
                    "use_case": use_case, "attempts": attempts,
                    "note": f"repli OAuth {fournisseur} (cascade epuisee par la capacite)"}
        attempts.append((fournisseur, str(r.get("error") or "reponse vide")[:100]))
    return None


# ── État des providers ────────────────────────────────────────────────────────


# Slots LOCAUX : leur is_available doit refleter la readiness REELLE (backend sert
# MAINTENANT), pas juste breaker/rpm. Sinon la cascade choisit un local cold ->
# cold-load 7B iGPU -> wedge (observe sur router_local, 120s). Sonde cachee 30s,
# fail-fast ; ollama = modele RESIDENT (/api/ps), autres serveurs = /models repond.
_LOCAL_SLOTS = {"ollama_local", "ollama_mimo_v2", "llamacpp_local", "lmstudio_native", "docker_local"}
_LOCAL_READY_CACHE: dict = {}
_LOCAL_READY_TTL = float(os.environ.get("LAFORGE_ROUTER_READY_TTL", "30"))


def _slot_local_ready(name: str, base_url: str, refresh: bool = True) -> bool:
    """Backend local sert MAINTENANT ? Cache (ts, ok, modele_CHARGE) TTL court.
    Capte AUSSI le modele reellement resident -> _resident_local_model l'utilise pour
    router la cascade vers LUI (pas le models[0] force = qwen-7b) => zero cold-load.

    refresh=False : chemin LISTING DE STATUT — rend le dernier verdict connu (meme
    perime) SANS sonder. Une sonde live coute jusqu'a 2s par slot froid et, sommee
    sequentiellement sur les 5 slots locaux, bloquait /api/agents >4s (et l'event-loop
    du hub, handle_list_providers n'ayant pas de to_thread). Le routage garde
    refresh=True (readiness FRAICHE avant d'envoyer du trafic vers un local)."""
    hit = _LOCAL_READY_CACHE.get(name)
    now = time.monotonic()
    if hit and now - hit[0] < _LOCAL_READY_TTL:
        return hit[1]
    if not refresh:
        return bool(hit[1]) if hit else False
    ok = False
    model = ""
    try:
        from nokido_agent.app.forge_agent_proxy import _http_ready  # reuse (lazy = pas de circular import)

        if name.startswith("ollama"):
            import json as _j
            import urllib.request as _ur

            with _ur.urlopen("http://localhost:11434/api/ps", timeout=2.0) as _r:
                _models = (_j.loads(_r.read()) or {}).get("models") or []
            # gen-ready = modele RESIDENT non purement-embedding (nomic seul != qwen pret).
            _gen = [m.get("name", "") for m in _models if "embed" not in (m.get("name", "").lower())]
            if _gen:
                ok, model = True, "ollama/" + _gen[0]  # route vers le CHARGE (LiteLLM prefix)
        elif name == "lmstudio_native":
            # LM Studio JIT-load : /v1/models = TELECHARGES, pas CHARGES. Exiger un LLM
            # reellement 'loaded' (API native) et router vers CE modele (sinon cold-load).
            import json as _j
            import urllib.request as _ur

            _tok = ""
            try:
                from nokido_agent.app.forge_secrets import get_secret as _gs

                _tok = _gs("LMSTUDIO_TOKEN") or ""
            except Exception:  # noqa: BLE001
                pass
            _b = base_url.rstrip("/").rsplit("/v1", 1)[0]
            _rq = _ur.Request(_b + "/api/v0/models", headers={"Authorization": "Bearer " + _tok} if _tok else {})
            with _ur.urlopen(_rq, timeout=2.0) as _r2:
                _ms = (_j.loads(_r2.read()) or {}).get("data") or []
            _gen = [m.get("id", "") for m in _ms if m.get("state") == "loaded" and m.get("type") != "embeddings"]
            if _gen:
                ok, model = True, _gen[0]  # id exact du modele charge dans LM Studio
        else:
            ok = _http_ready(base_url.rstrip("/") + "/models", timeout=2.0)
    except Exception:  # noqa: BLE001  (indispo = pas pret, jamais crasher le routage)
        ok, model = False, ""
    _LOCAL_READY_CACHE[name] = (now, ok, model)
    return ok


def _resident_local_model(name: str) -> str:
    """Modele local reellement CHARGE (capte par _slot_local_ready), '' sinon."""
    hit = _LOCAL_READY_CACHE.get(name)
    return hit[2] if hit and len(hit) > 2 else ""


def _capter_capacite(provider: str, source) -> None:
    """Capacite OBSERVEE du fournisseur (en-tetes x-ratelimit-*, 2026-10-02).

    Observation seule : le routage n'en depend pas. Ne leve jamais -- un capteur ne fait
    pas echouer un appel LLM (cf. forge_quota_tracker.capturer_reponse)."""
    try:
        from nokido_agent.app.forge_quota_tracker import capturer_reponse
        capturer_reponse(provider, source)
    except Exception:  # noqa: BLE001  # muet-ok : capturer_reponse journalise ses propres echecs
        pass


class ProviderSlot:
    """État runtime d'un provider — quota tracking + cooldown."""

    def __init__(self, name: str, config: dict) -> None:
        """Init.

        Args:
            name: Description.
            config: Description.
        """
        self.name = name
        self.config = config
        self._calls = []  # timestamps des appels
        self._cooldown = 0.0  # timestamp fin de cooldown (rate-limit)
        self._failures = 0
        # Circuit breaker unifie (audit Gemini 2026-04)
        # Seuil 5 failures + recovery 120s (plus permissif que l'existant 3 failures)
        self._breaker = CircuitBreaker(
            f"llm_router::{name}",
            fail_threshold=5,
            recovery_time=120.0,
        )

    @property
    def env_key_name(self) -> str:
        """Env key name."""
        return self.config.get("env_key", "")

    @property
    def api_key(self) -> str:
        """Api key (rotation-aware : 1re clé saine du pool, '' si toutes mortes)."""
        k = self.env_key_name
        if not k:
            return "local"
        try:
            from nokido_agent.app.forge_key_rotation import resolve as _rot

            _m, _rk = _rot(k)
            if _m:
                return _rk or ""
        except Exception:
            pass
        try:
            from nokido_agent.app.forge_secrets import get_secret as _gs

            return _gs(k) or ""
        except Exception:
            return os.environ.get(k, "")

    @property
    def is_configured(self) -> bool:
        """Is configured (rotation-aware : False si pool géré mais toutes les clés mortes -> skip)."""
        k = self.env_key_name
        if not k:
            return True  # local — toujours dispo
        try:
            from nokido_agent.app.forge_key_rotation import resolve as _rot

            _m, _rk = _rot(k)
            if _m:
                return bool(_rk)
        except Exception:
            pass
        try:
            from nokido_agent.app.forge_secrets import get_secret as _gs

            return bool(_gs(k))
        except Exception:
            return bool(os.environ.get(k, ""))

    @property
    def is_available(self) -> bool:
        """Dispo pour ROUTER du trafic : readiness locale FRAICHE (sonde live)."""
        return self._is_available(refresh=True)

    def _is_available(self, refresh: bool = True) -> bool:
        """Verdict de disponibilite. refresh=False = LISTING de statut (dernier etat
        connu, aucune sonde live -> non bloquant)."""
        if not self.is_configured:
            return False
        if time.monotonic() < self._cooldown:
            return False
        if self._failures >= 3:
            # Reset après 5 min
            return False
        # Circuit breaker unifie (audit Gemini 2026-04)
        if not self._breaker.allow():
            return False
        # Slots locaux : exiger la readiness REELLE (backend sert MAINTENANT) pour ne
        # jamais router vers un local cold/mort qui cold-load (7B iGPU = wedge 120s).
        if self.name in _LOCAL_SLOTS and not _slot_local_ready(
                self.name, self.config.get("base_url", ""), refresh=refresh):
            return False
        return self._within_rpm()

    def _within_rpm(self) -> bool:
        """Within rpm."""
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < 60]
        return len(self._calls) < self.config.get("rpm", 30)

    def record_call(self, ttft_ms: float = 0.0) -> None:
        """Record call."""
        self._calls.append(time.monotonic())
        self._failures = 0
        self._breaker.record_success()
        try:
            from nokido_agent.app.forge_trust_score import TrustScoreRegistry

            TrustScoreRegistry.get().record_success(self.name, ttft_ms or self.config.get("latency", 1000))
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # Chemin CHAUD : deduplication, sinon le remede noierait le journal.
            _n = getattr(self, "_pertes_trust", 0) + 1
            self._pertes_trust = _n
            if _n == 1 or _n % 200 == 0:
                _lg.getLogger(__name__).warning(
                    "[router] succes de %s NON compte au trust score (%s: %s) — %d "
                    "fois | consequence: le routage decide sur un score PERIME, et un "
                    "provider fiable peut rester deconsidere",
                    self.name, type(e).__name__, str(e)[:70], _n)

    def record_rate_limit(self, retry_after: float = 60.0) -> None:
        """Record rate limit.

        Args:
            retry_after: Description.
        """
        self._cooldown = time.monotonic() + retry_after

    def record_failure(self) -> None:
        """Record failure."""
        self._failures += 1
        self._breaker.record_failure()
        try:
            from nokido_agent.app.forge_trust_score import TrustScoreRegistry

            TrustScoreRegistry.get().record_failure(self.name)
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _n = getattr(self, "_pertes_trust", 0) + 1
            self._pertes_trust = _n
            if _n == 1 or _n % 200 == 0:
                _lg.getLogger(__name__).warning(
                    "[router] ECHEC de %s NON compte au trust score (%s: %s) — %d "
                    "fois | consequence: un provider defaillant garde un bon score et "
                    "continuera d'etre elu", self.name, type(e).__name__, str(e)[:70], _n)

    def status(self) -> dict:
        """Status."""
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < 60]
        cooldown_s = max(0, self._cooldown - now)
        return {
            "name": self.name,
            "configured": self.is_configured,
            "available": self._is_available(refresh=False),
            "calls_last_min": len(self._calls),
            "rpm_limit": self.config.get("rpm", 30),
            "cooldown_s": round(cooldown_s, 1),
            "failures": self._failures,
            "latency_ms": self.config.get("latency", 1000),
            "ring": self.config.get("ring", 8),
            "note": self.config.get("note", ""),
            "models": self.config.get("models", [])[:2],
            "breaker_status": self._breaker.status,
        }


# ── Routeur principal ─────────────────────────────────────────────────────────


class LLMRouter:
    """
    Routeur LLM Ring 8 — cascade multi-providers via LiteLLM.
    Sélectionne automatiquement le meilleur provider disponible
    selon le cas d'usage, le quota restant et la latence.
    """

    def __init__(self) -> None:
        """Init."""
        self._slots = {name: ProviderSlot(name, cfg) for name, cfg in PROVIDERS.items()}

    def _select_slot(self, use_case: str = "general", exclure=()) -> Optional[ProviderSlot]:
        """Sélectionne le slot avec meilleur TrustScore parmi les disponibles — §ROUTE:BEST.

        `exclure` : slots deja entendus, a ne pas re-servir. MESURE 2026-08-26 (premiere
        passe reelle du rendement collectif) : sans ce parametre, les N tentatives d'un
        fanout partaient TOUTES au meme modele -- la cascade rend toujours le meilleur
        slot disponible, et rien ne permettait d'en demander un autre. Comme les voix se
        comptent par FAMILLE DE MODELE (`forge_swarm_evidence.groupe_independance`),
        `voix_independantes` plafonnait a 1 et toute politique exigeant 2 voix ne pouvait
        JAMAIS conclure : 5 reponses justes sur 6, zero acceptee.

        Defaut vide : aucun appelant existant ne change de comportement.
        """
        exclus = {str(x) for x in (exclure or ())}
        chain = chaine_active(use_case)
        available = [n for n in chain
                     if n not in exclus and self._slots.get(n) and self._slots[n].is_available]
        if not available:
            # Le repli local reste, SAUF s'il a deja parle : rendre None dit « plus de
            # diversite disponible », ce qui est vrai, au lieu de re-servir une voix
            # deja entendue en la faisant passer pour une seconde.
            return None if "ollama_local" in exclus else self._slots.get("ollama_local")
        # §ROUTE:BEST — TrustScoreRegistry si >= 2 candidats
        if len(available) >= 2:
            try:
                from nokido_agent.app.forge_trust_score import TrustScoreRegistry

                best = TrustScoreRegistry.get().best_provider(available)
                return self._slots.get(best, self._slots.get(available[0]))
            except Exception:
                pass
        return self._slots.get(available[0])

    def call_cascade(
        self,
        prompt: str,
        use_case: str = "general",
        max_tokens: int = 500,
        temperature: float = 0.7,
        system: str = "",
        timeout: int = 30,
        max_attempts: int = 5,
        json_mode: bool = False,
        inject_persona: bool = True,
        session_id: str = "",
        turn: int = 0,
        force_local: bool = False,
    ) -> dict:
        """Cascade reelle : itere sur la chain entiere jusqu'a une reussite.

        Marque chaque echec via record_failure(). Si un slot est rate-limited
        ou retourne 'Invalid API Key', on passe au suivant.

        Args:
            prompt: Prompt utilisateur
            use_case: Cas d'usage (cle de USE_CASE_CHAINS)
            max_tokens, temperature, system, timeout: standard
            max_attempts: limite de slots a tenter (defaut 5)

        Returns:
            {ok, text, provider, model, elapsed_ms, tokens, attempts: [(slot, error)]}
        """
        t0 = time.monotonic()

        # ── Routage sémantique LAZY (switchboard PR-A) ─────────────────────────────────
        # use_case="auto" → semantic_route(bge-m3) déduit le use_case depuis l'intent.
        # Opt-in (sentinelle) : zéro coût embed sur les appels normaux. Fallback general.
        if use_case == "auto":
            try:
                from nokido_agent.app.forge_semantic_route import semantic_route

                use_case = semantic_route(prompt)[0]
            except Exception:
                use_case = "general"

        chain = list(chaine_active(use_case))

        # ── Priority FREE (Lot Gemini 2026-06-16) ──────────────────────────────────────
        # Si on a des slots gratuits disponibles, on peut les remonter en tête de chain
        # pour économiser les quotas Cloud payants sur les tâches courantes.
        # Bypassé si use_case=reasoning/complex ou force_local.
        if use_case not in ("reasoning", "complex") and not force_local:
            try:
                free_slots = self.usable_free()
                if free_slots:
                    # On insère les free_slots en tête s'ils font partie de la chaîne.
                    chain_free = [p for p in free_slots if p in chain]
                    chain_rest = [p for p in chain if p not in free_slots]
                    chain = chain_free + chain_rest
            except Exception:
                pass

        # ── AXE 2 : CAPACITÉ (TRANSPORT ≠ APPLICATIF) ──────────────────────────
        # Une tâche (même triviale) qui exige un PAT ou un accès réseau authentifié
        # (ex: github) n'est pas "locale". Elle doit être exécutée par un agent (Claude/Antigravity).
        import re
        if re.search(r"\b(gh_run|github|gh api|pull request|pr|issue|pat)\b", prompt, re.IGNORECASE):
            force_local = False
            _cloud_slots = ("claude_pro", "gemini_pro", "openai_gpt4")
            chain = [s for s in _cloud_slots if s in chain] + [s for s in chain if s not in _cloud_slots] or ["claude_pro"]
            import logging
            logging.getLogger("Nokido.Router").info("[capability] Tâche requiert réseau/PAT -> force_local annulé, escalade vers cloud")

        # ── force_local : grille DÉTERMINISTE (PEUT, binaire) demandée par l'appelant ──
        # Tâches stratégiques/sécurité (ex. CLI /secure) : on garde le routage qualité
        # ENTRE slots locaux (ordre de la chain préservé) mais zéro slot cloud, quelle
        # que soit la décision sémantique. Complète cortisol (quota) et firewall (DLP),
        # qui restent actifs plus bas. Cf. règle d'or sémantique vs grille déterministe.
        if force_local:
            _local_slots = ("ollama_local", "llamacpp_local", "lmstudio_native", "ollama_mimo_v2", "docker_local")
            chain = [s for s in chain if s in _local_slots] or ["ollama_local"]

        # ── Persona Nokido unifiée (AXE 8 PR-3) ───────────────────────────────────────
        # Englobe le system fourni dans la voix canonique (idempotent via marqueur).
        # La persona porte gestion-tokens + conditionnement succès/échec (mood).
        if inject_persona and "[LAFORGE_PERSONA]" not in (system or ""):
            try:
                from nokido_agent.app.forge_persona_engine import nokido_system

                system = nokido_system(role_overlay=system, ring=3, turn=turn, session_id=session_id)
            except Exception:
                pass

        # ── JSON Mode : Phase 6 Structured Agentic Trajectory ──────────────────────────
        # Force LLM to produce strict JSON-RPC 2.0 (no prose). Auto-injecté system prompt.
        if json_mode:
            try:
                from nokido_agent.app.forge_trajectory import SYSTEM_PROMPT_JSON_MODE

                system = (system + "\n\n" + SYSTEM_PROMPT_JSON_MODE).strip() if system else SYSTEM_PROMPT_JSON_MODE
                temperature = min(temperature, 0.2)  # baisse hallucination
            except ImportError:
                pass

        # ── Skip providers flagged dead_end (motivation Phase 6) ───────────────────────
        try:
            from nokido_agent.app.forge_motivation import is_dead_end

            chain = [s for s in chain if not is_dead_end(f"llm_call:{s}", use_case)]
        except ImportError:
            pass

        # ── Skip providers dont quota mensuel est epuise (post 2026-06-15) ─────────────
        # Note : forge_provider_quota check via token_usage table (source-of-truth
        # log_call). Permet d'exclure claude_agent_sdk/claude_cli en cas de quota
        # Agent SDK Anthropic atteint, sans violer leur ToS.
        try:
            from nokido_agent.app.forge_provider_quota import filter_chain as _quota_filter

            before = list(chain)
            chain = _quota_filter(chain, threshold=1.0)
            skipped = set(before) - set(chain)
            if skipped and (hasattr(self, "log") or hasattr(self, "logger")):
                _logger = getattr(self, "log", getattr(self, "logger", None))
                if _logger:
                    _logger.info(f"[QUOTA] skip {len(skipped)} providers epuises : {sorted(skipped)}")
        except ImportError:
            pass

        # ── Skip providers locaux dont le modele est trop lourd pour cet hote ─────────
        # forge_host_capabilities verifie VRAM/RAM dispo vs MODEL_FOOTPRINT_GB.
        # Ex : sur iGPU Radeon 780M, qwen32b inviable -> on prefere cloud directement
        # plutot que voir Ollama crasher OOM.
        try:
            from nokido_agent.app.forge_host_capabilities import can_run_locally

            local_providers = {"ollama_local", "llamacpp_local", "lmstudio_native", "ollama_mimo_v2"}
            local_chain = [p for p in chain if p in local_providers]
            if local_chain:
                # Map provider -> model representatif (a affiner via PROVIDER_SPECS)
                provider_default_model = {
                    "ollama_local": "qwen2.5-coder:7b-instruct-q4_K_M",
                    "llamacpp_local": "qwen2.5-coder:7b-instruct-q4_K_M",
                    "lmstudio_native": "qwen2.5-coder:7b-instruct-q4_K_M",
                    "ollama_mimo_v2": "mimo-v2-omni",
                }
                _filtered = list(chain)
                for p in local_chain:
                    model = provider_default_model.get(p, "")
                    if model:
                        ok, _reason = can_run_locally(model)
                        if not ok and p in _filtered:
                            _filtered.remove(p)
                if _filtered != chain:
                    _skipped_local = set(chain) - set(_filtered)
                    chain = _filtered
                    if hasattr(self, "log") or hasattr(self, "logger"):
                        _logger = getattr(self, "log", getattr(self, "logger", None))
                        if _logger:
                            _logger.info(f"[HOST_CAP] skip locaux trop lourds : {sorted(_skipped_local)}")
        except ImportError:
            pass

        # ── Curiosity injection auto : si frustration sur use_case, inject exploration ──
        try:
            from nokido_agent.app.forge_motivation import _list_failures_for_target, FRUSTRATION_CURIOSITY, curiosity_prompt

            fails = _list_failures_for_target(use_case)
            top_fail = max((f for f in fails), key=lambda x: x.get("count", 0), default=None)
            if top_fail and top_fail.get("count", 0) >= FRUSTRATION_CURIOSITY:
                injection = curiosity_prompt(
                    method=top_fail["method"],
                    target=use_case,
                    error=top_fail.get("last_error", ""),
                    fail_count=top_fail["count"],
                )
                system = (system + "\n\n" + injection).strip() if system else injection
        except (ImportError, Exception):
            pass

        # ── Récepteur endocrinien CORTISOL : si quotas cloud sous stress, force local ──
        # Boucle autopoïétique : forge_token_monitor.daily_report émet CORTISOL_QUOTA_CLOUD,
        # forge_health_diagnostic la propage. Quand level > 0.5, on filtre la chain
        # pour ne garder que les slots locaux. Décay automatique fait revenir cloud.
        try:
            from nokido_agent.app.forge_endocrine import read as _hormone_read

            cortisol = _hormone_read("CORTISOL_QUOTA_CLOUD")
            if cortisol > 0.5:
                # gemini_cli = AGY (agy.exe, abonnement owner = GRATUIT) : echappatoire
                # cloud-qualite sous stress budget, sans toucher au budget $ (owner 23/07).
                local_only = [s for s in chain if s in ("ollama_local", "llamacpp_local", "lmstudio_native", "docker_local", "gemini_cli")]
                if local_only:
                    chain = local_only
                    if hasattr(self, "log") or hasattr(self, "logger"):
                        getattr(self, "log", None) or getattr(self, "logger", None) and (
                            self.log if hasattr(self, "log") else self.logger
                        ).info(f"[router] CORTISOL={cortisol:.2f} > 0.5 → local-only cascade")
        except Exception:
            pass  # endocrine optional

        # ── Hybrid topology via SemanticFirewall existant (Nokido v16.5+) ──
        # Utilise le firewall 4 couches deja implemente (forge_semantic_firewall.py):
        #   - redact_text() pour PII/secrets/paths
        #   - detect_injection() pour prompt injection
        #   - canary generation pour detection leak
        # Si DLP triggered ou injection detectee, force le routage local uniquement.
        dlp_triggered = False
        injection_detected = False
        garde_a_parle = False  # vrai des que le pare-feu refuse/restreint : interdit le repli OAuth
        try:
            from nokido_agent.app.forge_semantic_firewall import get_firewall

            fw = get_firewall()
            # On route en "cloud" par defaut pour laisser le FW decider de la redaction.
            # Si une substitution DLP a lieu OU injection detectee -> chain local-only.
            pf = fw.pre_flight(prompt, context=system, ring=3, provider="auto")
            dlp_triggered = pf.dlp_triggered
            injection_detected = pf.injection
            garde_a_parle = (not pf.ok) or bool(pf.dlp_triggered) or bool(pf.injection)
            if not pf.ok or pf.dlp_triggered:
                local_only = [s for s in chain if s in ("ollama_local", "llamacpp_local")]
                if local_only:
                    chain = local_only
                else:
                    # L4 (2026-09-12) — LE REPLI QUI N'EXISTAIT PAS.
                    # Quand aucun slot local n'est dans la chaine, `chain` restait
                    # INCHANGEE : un prompt dont le DLP venait de se declencher
                    # partait au cloud EN CLAIR, sans que rien ne le dise. Et ce
                    # n'est pas un cas rare — les backends locaux sont mesures hors
                    # service (`:11434` expire, `:8091`/`:8099` fermes), donc c'est
                    # le cas NOMINAL.
                    #
                    # ⚠️ `pf.safe_task` ne peut PAS servir de repli : mesure du
                    # jour, `pre_flight` ne redige JAMAIS. Il rend `ok=False` et un
                    # `safe_task` VIDE des que le DLP mord, et le prompt original
                    # inchange sinon. C'est un garde BINAIRE, pas un redacteur —
                    # contrairement a ce qu'annonce le protocole documente
                    # (`CLAUDE.md` §5 : « safe_task [...] redige, PII remplacees par
                    # placeholders »). Suivre cette doc aurait envoye un prompt VIDE
                    # au modele a chaque detection.
                    #
                    # On redige donc avec `redact_text`, qui lui substitue vraiment
                    # (verifie : une IP devient `[IP_INTERNAL_1]`), et on part avec
                    # la version redigee plutot qu'en clair. Rediger degrade la
                    # requete ; l'envoyer en clair perd le secret.
                    # ⚠️ CE MODULE N'A PAS DE `logger` GLOBAL (il utilise `_lg`
                    # local, cf. L906/L935). Les trois appels ci-dessous, ecrits
                    # avec `logger`, levaient un NameError — au moment PRECIS ou
                    # le garde devait dire qu'une donnee sensible partait au
                    # cloud non protegee. Et le `except ImportError` englobant ne
                    # rattrape pas un NameError : le garde ne se taisait pas, il
                    # CASSAIT l'appel. Troisieme occurrence du meme defaut dans
                    # la journee (cf. `forge_tool_annotations`, garde RSS du
                    # wrapper de job) : un garde AGIT d'abord, journalise ENSUITE,
                    # et son journal NE LEVE JAMAIS.
                    import logging as _lg_dlp

                    _log_dlp = _lg_dlp.getLogger(__name__)
                    try:
                        from nokido_agent.app.forge_semantic_firewall import redact_text

                        _redige, _map = redact_text(prompt)
                        if _map:
                            _log_dlp.warning(
                                "[router] DLP declenche et AUCUN slot local disponible "
                                "— %d donnee(s) sensible(s) redigee(s) avant envoi cloud "
                                "(motif: %s)", len(_map), pf.reason or "dlp")
                            prompt = _redige
                        else:
                            _log_dlp.error(
                                "[router] DLP declenche, AUCUN slot local, et la "
                                "redaction n'a RIEN substitue — le prompt part au "
                                "cloud tel quel (motif: %s)", pf.reason or "dlp")
                    except Exception as _re:  # noqa: BLE001
                        _log_dlp.error(
                            "[router] DLP declenche, aucun slot local, redaction "
                            "INDISPONIBLE (%s: %s) — envoi cloud NON protege",
                            type(_re).__name__, str(_re)[:90])
        except ImportError:
            pass  # SemanticFirewall absent = degraded mode
        # ────────────────────────────────────────────────────────────────

        # ── DT Router : préférence apprise, priorité sur chain statique ──────
        try:
            from nokido_agent.app.forge_llm_router_dt import route_with_dt

            _dt_prov, _dt_conf, _dt_src = route_with_dt(use_case, prompt)
            if _dt_prov and _dt_conf >= 0.6 and _dt_prov in chain:
                chain = [_dt_prov] + [s for s in chain if s != _dt_prov]
        except Exception:
            pass
        # ─────────────────────────────────────────────────────────────────────

        attempts = []
        real_attempts = 0

        for slot_name in chain:
            if real_attempts >= max_attempts:
                break
            slot = self._slots.get(slot_name)
            if not slot:
                attempts.append((slot_name, "slot inexistant"))
                continue
            if not slot.is_available:
                # Cause REELLE, dans l'ordre de _is_available. Le motif
                # "RPM limit" etait un else fourre-tout : le 2026-08-16 il a
                # masque 10 jours un runner Ollama casse, les slots locaux
                # sortant available=false faute de modele RESIDENT, pas par quota.
                # Un motif qui ne decrit pas sa cause cache la prochaine panne.
                if not slot.is_configured:
                    reason = "non configure"
                elif time.monotonic() < slot._cooldown:
                    reason = "cooldown %ds" % int(slot._cooldown - time.monotonic())
                elif getattr(slot, "_failures", 0) >= 3:
                    reason = "trop d echecs (%d)" % slot._failures
                elif getattr(slot, "_breaker", None) is not None and not slot._breaker.allow():
                    reason = "circuit ouvert"
                elif slot_name in _LOCAL_SLOTS:
                    _hit = _LOCAL_READY_CACHE.get(slot_name)
                    reason = ("backend local sans modele resident"
                              if (_hit is not None and not _hit[1])
                              else "backend local non pret")
                else:
                    reason = "indisponible (cause indeterminee)"
                attempts.append((slot_name, reason))
                continue

            real_attempts += 1

            # Tentative avec ce slot
            # ── SCAN OUTBOUND (session5 — forge_secret_guard) ──────────────
            _is_local = slot_name in ("ollama_local", "llamacpp_local", "lmstudio_native", "docker_local")
            try:
                from nokido_agent.app.forge_secret_guard import scan_outbound as _scan_out

                _scan_out(prompt, provider=slot_name, local_only=_is_local)
            except ImportError:
                pass  # fail-open si module absent
            except Exception as _sge:
                attempts.append((slot_name, f"SecretGuard: {_sge}"))
                continue  # bloque ce slot, essaie le suivant
            # ────────────────────────────────────────────────────────────────
            try:
                import litellm

                # CacheAligner — stabilise le préfixe pour HIT le prompt-cache provider
                # (vars LOCALES : ne mute pas system/prompt utilisés par lmstudio/fallback).
                try:
                    from nokido_agent.app.forge_cache_aligner import align as _ca_align
                    _sys_c, _prompt_c, _ = _ca_align(system, prompt)
                except Exception:
                    _sys_c, _prompt_c = system, prompt
                messages = []
                if _sys_c:
                    messages.append({"role": "system", "content": _sys_c})
                messages.append({"role": "user", "content": _prompt_c})

                model = slot.config["models"][0]
                _mt = max_tokens
                # Option B : router vers le modele reellement CHARGE (capte par la sonde
                # readiness) au lieu du models[0] force (qwen-7b) => zero cold-load/wedge.
                # is_available=True garantit qu'un modele resident existe pour ce slot local.
                if slot_name in _LOCAL_SLOTS:
                    _rm = _resident_local_model(slot_name)
                    if _rm:
                        model = _rm
                    # Regulation : borne la generation locale. laforge-coder n'emet pas de
                    # stop-token (finish=length) => remplit max_tokens ; iGPU lent (~8 tok/s)
                    # => sans borne un max_tokens 1400 = ~170s = wedge. Cap opt-out via env.
                    # NOM LIE APRES USAGE (pyflakes 2026-08-20) : `_gs` n'etait
                    # importe qu'aux lignes 712/781/802, dans D'AUTRES fonctions.
                    # Ici il levait un NameError -> le cap n'a JAMAIS ete applique,
                    # donc la borne anti-wedge decrite juste au-dessus n'existait
                    # pas. Meme classe que l'incident hub du 19/08.
                    try:
                        from nokido_agent.app.forge_secrets import get_secret as _gs
                    except Exception:  # noqa: BLE001 — repli env, jamais de crash sur un cap
                        import os as _o

                        _gs = _o.environ.get
                    _cap = int(_gs("LAFORGE_LOCAL_MAX_TOKENS") or "384")
                    if not _mt or _mt > _cap:
                        _mt = _cap
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": _mt,
                    "temperature": temperature,
                    "timeout": timeout,
                    # FAIL-FAST : Nokido gère son propre fallback (cascade). Sans ça,
                    # litellm retente 40-100s une clé morte avant d'abandonner (cf.
                    # qualif endpoints 2026-06-08 : gemini_flash 102s, groq 40s).
                    "num_retries": 0,   # niveau litellm
                    "max_retries": 0,   # niveau SDK openai-compat (le vrai 2x20s=40s)
                }
                # Detection provider special
                _base_url = slot.config.get("base_url")

                if slot_name == "lmstudio_native":
                    import asyncio
                    from nokido_agent.app.forge_lmstudio import lms_call

                    # call_cascade est synchrone, on utilise asyncio.run
                    text = asyncio.run(
                        lms_call(messages, model=model, system=system, max_tokens=_mt, temperature=temperature)
                    )
                    if not text:
                        attempts.append((slot_name, "reponse vide ou serveur down"))
                        slot.record_failure()
                        continue
                    # Format de retour simule pour compatibilite succes
                    elapsed = round((time.monotonic() - t0) * 1000, 1)
                    _emit_nervous_event(
                        "provider_success", {"provider": slot_name, "use_case": use_case, "ms": elapsed}
                    )
                    return {
                        "ok": True,
                        "text": text,
                        "provider": slot_name,
                        "model": model,
                        "elapsed_ms": elapsed,
                        "tokens": 0,
                        "use_case": use_case,
                        "attempts": attempts,
                    }

                # llamacpp_local = llama-server OpenAI-compat (:8091) → même chemin que
                # github/hf : préfixe openai/ + api_base custom. Sinon litellm rejette
                # "LLM Provider NOT provided" (model 'laforge-coder' sans préfixe). Fix 2026-06-08.
                # La propriete se DECLARE, elle ne se DEDUIT PAS du nom. Ce test
                # portait sur le PREFIXE du slot ("github_", "hf_", llamacpp_local) :
                # tout endpoint OpenAI-compat nomme autrement tombait dans la branche
                # legacy, ou `api_base` n'est pose que pour les providers locaux —
                # litellm partait alors sur l'API publique avec un modele inconnu.
                # Mesure 2026-08-28 : c'est ce qui rendait `nvidia_nim` non routable
                # autrement qu'en le nommant `hf_*`, c'est-a-dire en mentant sur son
                # identite pour obtenir le bon comportement. Les prefixes restent
                # honores pour ne rien casser de l'existant.
                _is_openai_compat_custom = _base_url and (
                    slot.config.get("openai_compat")
                    or slot_name.startswith(("github_", "hf_"))
                    or slot_name == "llamacpp_local"
                )

                if _is_openai_compat_custom:
                    # Force litellm a utiliser le format openai/ avec base_url custom
                    # Pour github: model_id = "openai/gpt-4.1-mini", litellm detecte "openai" prefix
                    # mais on override api_base -> pointe sur GitHub/HF au lieu d'OpenAI
                    kwargs["model"] = model if model.startswith("openai/") else f"openai/{model}"
                    kwargs["api_base"] = _base_url
                    # llama-server local n'exige pas de clé réelle → factice (litellm openai exige non-vide).
                    kwargs["api_key"] = slot.api_key or "sk-local"
                    # Timeout plus court pour providers cloud custom (pas le local llamacpp).
                    if slot_name.startswith(("github_", "hf_")):
                        kwargs["timeout"] = min(timeout, 20)
                else:
                    # Logique legacy : api_base seulement pour providers locaux
                    _provider = model.split("/")[0] if "/" in model else "litellm"
                    _local_providers = {"ollama", "lm_studio", "vllm", "litellm"}
                    if slot.config.get("base_url") and _provider in _local_providers:
                        kwargs["api_base"] = slot.config["base_url"]
                    # La cle API ne doit PAS etre conditionnee au fait que le provider soit
                    # LOCAL : cette garde etait un copier-coller de celle d'api_base juste
                    # au-dessus, et elle est inversee — ce sont les locaux qui n'ont pas
                    # besoin de cle. Consequence mesuree le 2026-07-22 : pour
                    # openrouter/qwen/qwen3-coder:free, _provider vaut "openrouter", hors du
                    # set local, donc la cle n'etait jamais attachee ; litellm retombait sur
                    # la variable d'environnement et, absente du process, la requete partait
                    # sans credential -> OpenRouter 401 "No cookie auth credentials found".
                    # slot.api_key resout pourtant depuis le coffre (rotation puis secrets).
                    # Meme regle que _call_slot, qui lui ne filtre pas par provider.
                    if slot.api_key and slot.api_key != "local":
                        kwargs["api_key"] = slot.api_key

                slot.record_call()
                resp = litellm.completion(**kwargs)
                _capter_capacite(slot_name, resp)
                text = (resp.choices[0].message.content or "").strip()

                if not text:
                    attempts.append((slot_name, "reponse vide"))
                    slot.record_failure()
                    continue

                # SUCCESS (candidat) — escalade confiance-aware (inversé FrugalGPT) :
                # réponse refus/vide/très courte + provider plus fort dispo dans la
                # chaîne (faible->fort) => escalader au lieu d'accepter du médiocre.
                # Borné par chain[:max_attempts] (zéro boucle infinie). Défaut sûr.
                elapsed = round((time.monotonic() - t0) * 1000, 1)
                _t = (text or "").strip().lower()
                # Escalade UNIQUEMENT sur réponse vide ou refus explicite (2026-06-08 :
                # len<8 escaladait des réponses locales valides courtes ex "Bonjour."
                # → cassait le local-first sur prompts triviaux). Souveraineté local d'abord.
                if (not _t or any(r in _t[:200] for r in (
                        "je ne peux pas", "je ne sais pas", "i cannot", "i can't",
                        "i don't know", "as an ai", "en tant qu'ia", "unable to",
                        "i'm unable", "sorry, i can"))) and chain[chain.index(slot_name) + 1:max_attempts]:
                    attempts.append((slot_name, "low_confidence -> escalade vers plus fort"))
                    slot.record_failure()
                    continue
                _emit_nervous_event("provider_success", {"provider": slot_name, "use_case": use_case, "ms": elapsed})
                try:  # viz flux-de-réflexion (best-effort)
                    from nokido_agent.app.forge_swarm_bus import publish as _rp
                    _rp(kind="llm_provider_decision", data={"use_case": use_case, "provider": slot_name, "ok": True, "ms": elapsed}, topic="reasoning")
                except Exception:
                    pass
                _cache_stats = {}
                try:  # mesure cache provider (cached_tokens) — chiffres, pas vibes
                    from nokido_agent.app.forge_cache_aligner import cache_usage as _ca_usage
                    _cache_stats = _ca_usage(resp)
                    if _cache_stats.get("cached_tokens"):
                        _emit_nervous_event("cache_hit", {"provider": slot_name, **_cache_stats})
                except Exception:
                    pass
                return {
                    "ok": True,
                    "text": text,
                    "provider": slot_name,
                    "model": model,
                    "elapsed_ms": elapsed,
                    "tokens": getattr(resp.usage, "total_tokens", 0) if hasattr(resp, "usage") else 0,
                    "cache": _cache_stats,
                    "use_case": use_case,
                    "attempts": attempts,
                }

            except Exception as e:
                _capter_capacite(slot_name, e)  # une 429 porte AUSSI les en-tetes de limite
                err = str(e)[:150]
                attempts.append((slot_name, err))
                slot.record_failure()
                # Réactif (pas de schtask) : si l'échec = mort d'auth (≠ quota),
                # alerte re-auth via forge_auth_sentinel. Best-effort, fail-open.
                try:
                    import sys as _s
                    import os as _o
                    _t = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "tools")
                    if _t not in _s.path:
                        _s.path.append(_t)
                    from nokido_agent.tools.forge_auth_sentinel import is_auth_dead, alert as _auth_alert
                    if is_auth_dead("", err):
                        _auth_alert(slot_name, "cascade", err)
                except Exception:
                    pass
                # Si rate-limit, marquer cooldown 60s
                if "429" in err or "rate" in err.lower():
                    slot.record_rate_limit(60.0)
                continue

        # Toute la cascade a echoue — repli OAuth (AGY puis Claude Code) si elle a ete epuisee par
        # la CAPACITE et qu'aucune garde n'a parle (cf. repli_oauth, owner 2026-09-25).
        _repli = repli_oauth(attempts, garde_a_parle, prompt, system, max_tokens, timeout, use_case, t0)
        if _repli:
            return _repli

        return {
            "ok": False,
            "error": "Toute la cascade a echoue",
            "provider": None,
            "use_case": use_case,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
            "attempts": attempts,
        }

    _SLOTS_LOCAUX_SORTIE = ("ollama_local", "llamacpp_local", "lmstudio_native", "docker_local")

    def _garde_sortante(self, prompt: str, system: str, slot_name: str):
        """Gardes de SORTIE de `call()` : les MEMES que `call_cascade` (pre_flight -> redaction
        par `redact_text`, puis `SecretGuard.scan_outbound`). Rend (prompt_a_envoyer, refus|None).

        Mesure 2026-09-26 : `router_call` -> `call()` appelait litellm SANS aucun de ces gardes
        -- ils ne vivaient que dans `call_cascade` -- et ses appelants envoyaient donc au cloud
        sans DLP ni scan de secrets. `pre_flight` est BINAIRE (safe_task VIDE des que le DLP
        mord) : on redige avec `redact_text`, comme le repli L4 de la cascade (2026-09-12).
        Un slot LOCAL recoit le prompt tel quel ; le scan de secrets s'applique a tous."""
        import logging as _lg_g

        _log = _lg_g.getLogger(__name__)
        local = slot_name in self._SLOTS_LOCAUX_SORTIE
        if not local:
            try:
                from nokido_agent.app.forge_semantic_firewall import get_firewall, redact_text

                pf = get_firewall().pre_flight(prompt, context=system, ring=3, provider=slot_name)
                if (not pf.ok) or pf.dlp_triggered:
                    _redige, _map = redact_text(prompt)
                    if _map:
                        _log.warning("[router.call] DLP declenche vers %s -- %d donnee(s) redigee(s) "
                                     "avant envoi (motif: %s)", slot_name, len(_map), pf.reason or "dlp")
                        prompt = _redige
                    else:
                        _log.error("[router.call] DLP declenche vers %s et la redaction n'a RIEN "
                                   "substitue (motif: %s)", slot_name, pf.reason or "dlp")
            except ImportError:
                _log.warning("[router.call] pare-feu semantique absent -- mode degrade vers %s", slot_name)
            except Exception as _e:  # noqa: BLE001
                # Cloud + pare-feu qui leve = on n'envoie pas : ne pas savoir n'est pas « propre ».
                return prompt, "pare-feu indisponible: %s: %s" % (type(_e).__name__, str(_e)[:90])
        try:
            from nokido_agent.app.forge_secret_guard import scan_outbound as _scan_out

            _scan_out(prompt, provider=slot_name, local_only=local)
        except ImportError:
            pass  # meme politique que call_cascade : fail-open si le module manque
        except Exception as _sge:  # noqa: BLE001
            return prompt, "SecretGuard: %s" % _sge
        return prompt, None

    def call(
        self,
        prompt: str,
        use_case: str = "general",
        max_tokens: int = 500,
        temperature: float = 0.7,
        system: str = "",
        timeout: int = 30,
        exclure=(),
    ) -> dict:
        """
        Appel LLM avec cascade automatique.
        Retourne {ok, text, provider, model, elapsed_ms, tokens}.

        `exclure` : noms de slots deja entendus. Sert la DIVERSITE d'un fanout — voir
        `_select_slot`. Vide par defaut.
        """
        t0 = time.monotonic()
        slot = self._select_slot(use_case, exclure=exclure)

        if not slot:
            return {"ok": False,
                    "error": ("Aucun provider disponible hors des %d deja entendu(s)"
                              % len(exclure or ())) if exclure else "Aucun provider disponible",
                    "provider": None, "diversite_epuisee": bool(exclure)}

        prompt_origine = prompt
        prompt, refus = self._garde_sortante(prompt_origine, system, slot.name)
        if refus:
            return {"ok": False, "error": refus, "provider": slot.name, "garde_sortante": True}

        model = slot.config["models"][0]
        slot.record_call()

        try:
            import litellm

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            # Config par provider
            kwargs = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
            }
            if slot.config.get("base_url"):
                kwargs["api_base"] = slot.config["base_url"]
            if slot.api_key and slot.api_key != "local":
                kwargs["api_key"] = slot.api_key

            resp = litellm.completion(**kwargs)
            _capter_capacite(slot.name, resp)
            text = resp.choices[0].message.content or ""
            elapsed = round((time.monotonic() - t0) * 1000, 1)

            return {
                "ok": True,
                "text": text,
                "provider": slot.name,
                "model": model,
                "elapsed_ms": elapsed,
                "tokens": getattr(resp.usage, "total_tokens", 0),
                "use_case": use_case,
            }

        except Exception as e:
            _capter_capacite(slot.name, e)  # une 429 porte AUSSI les en-tetes de limite
            err = str(e)
            elapsed = round((time.monotonic() - t0) * 1000, 1)

            # Détection rate-limit précise via forge_retry_strategies
            _is_rl = (
                retry_if_rate_limited().predicate(e) if _HAS_TENACITY else ("429" in err or "rate_limit" in err.lower())
            )
            if _is_rl:
                # Lire le header Retry-After si disponible
                _retry_after = 60.0
                resp = getattr(e, "response", None)
                if resp is not None:
                    hdr = getattr(getattr(resp, "headers", {}), "get", lambda k: None)("Retry-After")
                    if hdr:
                        try:
                            _retry_after = float(hdr)
                        except (TypeError, ValueError):
                            pass
                slot.record_rate_limit(_retry_after)
                # Budget RPM partagé
                if _HAS_TENACITY:
                    wait_rpm_budget._calls.setdefault(slot.name, []).append(time.time())
            else:
                slot.record_failure()

            # Retry avec le suivant dans la chaîne
            chain = chaine_active(use_case)
            for next_name in chain:
                if next_name == slot.name:
                    continue
                next_slot = self._slots.get(next_name)
                if next_slot and next_slot.is_available:
                    # La relance repasse la garde POUR CE slot : un premier slot local n'a
                    # rien redige, et le suivant peut etre cloud.
                    p_next, refus_next = self._garde_sortante(prompt_origine, system, next_name)
                    if refus_next:
                        continue
                    # Récursion simple (une seule retry)
                    return self._call_slot(next_slot, p_next, system, max_tokens, temperature, timeout, use_case)

            return {"ok": False, "error": err[:120], "provider": slot.name, "elapsed_ms": elapsed}

    def _call_slot(
        self,
        slot: ProviderSlot,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
        timeout: int,
        use_case: str,
    ) -> dict:
        """Appel direct sur un slot spécifique."""
        t0 = time.monotonic()
        model = slot.config["models"][0]
        slot.record_call()
        try:
            import litellm

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            kwargs = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
            }
            if slot.config.get("base_url"):
                kwargs["api_base"] = slot.config["base_url"]
            if slot.api_key and slot.api_key != "local":
                kwargs["api_key"] = slot.api_key
            resp = litellm.completion(**kwargs)
            _capter_capacite(slot.name, resp)
            text = resp.choices[0].message.content or ""
            return {
                "ok": True,
                "text": text,
                "provider": slot.name,
                "model": model,
                "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
                "tokens": getattr(resp.usage, "total_tokens", 0),
                "use_case": use_case,
            }
        except Exception as e:
            slot.record_failure()
            return {"ok": False, "error": str(e)[:80], "provider": slot.name}

    def slot(self, name: str) -> Optional[ProviderSlot]:
        """Le slot NOMME (config + sante vivante), ou None. Accesseur public : la passerelle
        :7777 (nokido/auto) lit l'ordre ET la sante ici au lieu de router en parallele."""
        return self._slots.get(name)

    def available_providers(self) -> list:
        """Retourne les providers configurés et disponibles."""
        return [s.status() for s in self._slots.values() if s.is_configured]

    def usable_free(self) -> list[str]:
        """
        Retourne les noms des slots gratuits (cost_tier=0) et configurés.
        Audit 2026-06-16 : priorité à l'économie pour les tâches simples.
        """
        return [
            n for n, s in self._slots.items()
            if s.config.get("cost_tier", 1) == 0 and s.is_available
        ]

    def all_status(self) -> dict:
        """État complet de tous les slots.

        `is_configured` n'est pas un attribut : c'est une propriete qui frappe le
        coffre (resolve -> pool -> 5 lectures vault). L'evaluer dans DEUX
        comprehensions doublait le cout d'un simple etat des lieux — ~300 acces
        DPAPI synchrones sur l'event-loop pour un `list_providers` (RCA hub mort
        2026-08-16). On l'evalue UNE fois par slot.
        """
        etats = [(s, s.is_configured) for s in self._slots.values()]
        configured = [s for s, ok in etats if ok]
        missing = [s for s, ok in etats if not ok]
        return {
            "configured": [s.status() for s in configured],
            "missing_keys": [
                {"name": s.name, "key": s.env_key_name, "note": s.config.get("note", "")} for s in missing
            ],
            "use_cases": list(USE_CASE_CHAINS.keys()),
        }

    def add_key(self, provider_name: str, api_key: str, persist: bool = True) -> bool:
        """
        Ajoute une clé API à chaud — sans redémarrage.
        persist=True : écrit dans Nokido.env.
        """
        slot = self._slots.get(provider_name)
        if not slot or not slot.env_key_name:
            return False
        os.environ[slot.env_key_name] = api_key
        if persist:
            env_path = ROOT / "Nokido.env"
            src = env_path.read_text()
            key_line = slot.env_key_name + "="
            if key_line in src:
                lines = src.splitlines()
                new_lines = []
                for line in lines:
                    if line.startswith(key_line) and "=" in line and not line.split("=", 1)[1].strip():
                        new_lines.append(f"{slot.env_key_name}={api_key}")
                    else:
                        new_lines.append(line)
                env_path.write_text("\n".join(new_lines))
        return True


# ── Singleton ─────────────────────────────────────────────────────────────────

_router: Optional[LLMRouter] = None

# Context:


def get_router() -> LLMRouter:
    """Get router."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


def router_call(prompt: str, use_case: str = "general", max_tokens: int = 500,
                *, context=None, **kwargs) -> dict:
    """Point d entrée simple — timeout adaptatif selon forge_system_mood.

    `context` : SwarmRequestContext (app/forge_share_policy). PORTE ICI, et non dans
    `**kwargs`, parce qu'un champ libre s'oublie en silence : mesure du 2026-09-02,
    cette fonction est le point de convergence des sorties LLM et AUCUN de ses cinq
    appelants ne lui transmettait la classe de la donnee envoyee.

    `context` est KEYWORD-ONLY (le `*` avant lui). Sans ce marqueur, un appelant
    passant un 4e argument POSITIONNEL le verrait atterrir dans `context` au lieu
    des kwargs -- une regression silencieuse qu'aucun test en mots-cles n'attrape.
    La mesure du 2026-09-02 n'a trouve AUCUN appel a plus de 3 positionnels, donc
    le cas ne se produisait pas ; le `*` le rend desormais IMPOSSIBLE plutot que
    simplement improbable, et le cout est nul.

    Le contexte est pour l'instant OBSERVE, jamais applique : il est retire des
    kwargs (il ne doit pas atteindre le fournisseur) et journalise avec la reponse.
    L'invariant « tout appel porte un contexte » est verifie par AST dans
    tests/nr/test_share_policy_couverture_nr.py -- un test, pas une convention.
    ATTENTION : `context=None` reste accepte, sinon tout appelant historique
    leverait TypeError et le corps se tairait d'un coup.
    """
    # Adapter le timeout au mood système (energy faible → timeout court → fallback rapide)
    if "timeout" not in kwargs:
        try:
            import sys as _ms, os as _mo

            _ma = _mo.path.join(_mo.path.dirname(__file__))
            if _ma not in _ms.path:
                _ms.path.insert(0, _ma)
            from nokido_agent.app.forge_system_mood import get_mood as _gm

            kwargs["timeout"] = int(_gm().recommended_timeout(base_s=30.0))
        except Exception:
            kwargs["timeout"] = 30
    reponse = get_router().call(prompt, use_case, max_tokens, **kwargs)
    # Observation seule. Le contexte ne modifie AUCUN verdict ici : il rend visible,
    # appel par appel, si le chemin est instrumente -- c'est le denominateur sans
    # lequel on ne peut pas decider d'armer la politique de partage.
    try:
        if isinstance(reponse, dict):
            if context is None:
                reponse["contexte_partage"] = {"contexte": "ABSENT"}
            else:
                reponse["contexte_partage"] = context.resume()
        # PERSISTER, pas seulement joindre : une reponse n'est lue que par son
        # appelant. Sans agregat sur disque, le denominateur reste invisible depuis
        # l'exterieur du hub -- et sans denominateur, aucun armement possible.
        from nokido_agent.app.forge_share_policy import noter_appel as _noter

        _noter(context)
    except Exception:  # noqa: BLE001  # muet-ok : une observation ne casse jamais un appel
        pass
    return reponse


def router_status() -> dict:
    """Router status."""
    return get_router().all_status()


# ═══════════════════════════════════════════════════════════════════════════
# MONITORING GLOBAL CircuitBreaker (audit Gemini 2026-04)
# ═══════════════════════════════════════════════════════════════════════════


def get_circuit_breakers_snapshot() -> dict:
    """Retourne l etat de tous les circuit breakers des providers LLM.

    Utilise pour monitoring UI, commande @state, dashboard.

    Returns:
        Dict mapping provider_name -> {status, failures, open_since, time_since_open}
        Status possibles : CLOSED (sain), HALF_OPEN (test recovery), OPEN (defaillant).
    """
    if not _HAS_TENACITY:
        return {"_note": "tenacity indisponible - monitoring degrade"}
    try:
        snap = CircuitBreaker.snapshot()
        # Filtrer uniquement les providers LLM (prefixe llm_router::)
        return {k.replace("llm_router::", ""): v for k, v in snap.items() if k.startswith("llm_router::")}
    except Exception as e:
        return {"_error": str(e)}


def reset_circuit_breaker(provider_name: str) -> bool:
    """Reset un circuit breaker pour un provider donne (recovery manuelle).

    Args:
        provider_name: Nom du provider (ex: "gemini_flash", "groq_fast").

    Returns:
        True si reset effectue, False si provider inconnu ou tenacity absent.
    """
    if not _HAS_TENACITY:
        return False
    try:
        CircuitBreaker.reset(f"llm_router::{provider_name}")
        return True
    except Exception:
        return False
