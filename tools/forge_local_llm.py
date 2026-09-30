# -*- coding: utf-8 -*-
"""forge_local_llm.py — résolution + appel d'un LLM LOCAL qualifié, à la demande.

POURQUOI (anti-dup §3, distinct de forge_llm_router) : les HOOKS et tâches de fond
(claude_precompact, forge_background_review) ont besoin d'un LLM **LOCAL UNIQUEMENT**,
**zéro dépendance lourde**, **zéro firewall/réseau sortant**, **fail-soft** (skip si
rien). forge_llm_router = routage GOUVERNÉ (firewall + cloud + cascade) → trop lourd
et inadapté ici. Ce module = mince, local, sûr.

CAUSE RACINE corrigée : les consommateurs hardcodaient `qwen2.5-coder:7b-instruct`
(tag INEXISTANT sur cette install) → 404 → skip silencieux. Ici on RÉSOUT le modèle
parmi les modèles RÉELLEMENT INSTALLÉS (skip embed/vision), par ordre de qualité.

« Check all ways, à la demande » : ollama (auto-load au 1er appel) en primaire ;
si ollama down → on SIGNALE un wake via forge_backend_power.ensure (le daemon owner
démarre le backend). On-demand + idle-unload = gérés par forge_backend_power.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "metabolisme/provider : resolution et appel d'un LLM local qualifie"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import urllib.request

OLLAMA = "http://127.0.0.1:11434"

# Modèles chat qualifiés, par préférence (préfixe de tag). Skippe embed/vision.
PRIORITY = (
    "laforge-qwen",
    "qwen2.5-coder:7b",
    "qwen2.5-coder:32b",
    "qwen2.5-coder",
    "qwen2.5:latest",
    "qwen2.5",
    "qwen3",
    "deepseek-r1",
    "deepseek-coder",
    "gemma4",
)
_SKIP = ("embed", "nomic", "bge", "moondream", "llava", "vision", "clip")


def list_ollama_models() -> list:
    try:
        r = urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3)
        return [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return []


def pick_ollama_model() -> "str | None":
    """Meilleur modèle chat qualifié parmi les INSTALLÉS (None si aucun / ollama down)."""
    names = [n for n in list_ollama_models() if n and not any(s in n.lower() for s in _SKIP)]
    if not names:
        return None
    for pref in PRIORITY:
        for n in names:
            if n.startswith(pref):
                return n
    return names[0]  # fallback : 1er chat non-embed/vision


def _ollama_up() -> bool:
    try:
        from nokido_agent.tools import forge_backend_power as bp

        return bp._up(11434)
    except Exception:
        try:
            urllib.request.urlopen(OLLAMA + "/api/tags", timeout=2)
            return True
        except Exception:
            return False


def chat(prompt: str, json_mode: bool = True, timeout: int = 45, max_tokens: int = 600) -> "str | None":
    """Appelle un LLM LOCAL qualifié. Retourne le texte, ou None (fail-soft, jamais d'exception).

    Aucun fallback cloud (souverain). Si ollama est down → signale un wake on-demand
    (forge_backend_power.ensure) et renvoie None (l'appelant retentera plus tard).
    """
    model = pick_ollama_model()
    if not model:
        # ollama down ou aucun modèle : déclencher l'autopoïèse (daemon owner démarre)
        try:
            from nokido_agent.tools import forge_backend_power as bp

            if not _ollama_up():
                bp.ensure("ollama")
                bp.ensure("llama_native")
        except Exception:
            pass
        return None
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        req = urllib.request.Request(
            OLLAMA + "/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        return resp["choices"][0]["message"]["content"]
    except Exception:
        return None


if __name__ == "__main__":
    print("installed:", list_ollama_models())
    print("picked   :", pick_ollama_model())
    print("chat     :", (chat("Réponds en JSON: {\"ok\": true}") or "")[:200])
