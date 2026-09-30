"""app/forge_clarification.py — Détecte ambiguïté et demande clarification."""

from __future__ import annotations

import json
import re

import requests

from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

HUB = "http://127.0.0.1:8766/mcp"
TOKEN = get_secret("FORGE_MCP_TOKEN") or ""
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

_VAGUE = re.compile(
    r"\b(ça|ca|it|truc|chose|machin|trouver|fix|update|change|modifier|améliorer|ajouter)\b",
    re.IGNORECASE,
)
_MIN_WORDS = 8  # 15 = trop agressif pour des commandes courtes légitimes


def needs_clarification(prompt: str) -> bool:
    """True si prompt trop court ET contient mot vague sans contexte technique."""
    words = prompt.split()
    if len(words) >= _MIN_WORDS:
        return False
    # Court + au moins 1 mot vague = ambiguë
    return bool(_VAGUE.search(prompt))


def build_clarification_request(prompt: str) -> str:
    """Génère question de clarification via LLM ollama."""
    q = (
        f"/no_think L'utilisateur a ecrit: '{prompt}'\n"
        "C'est trop vague pour agir. Formule UNE question de clarification courte (1 phrase, max 15 mots)."
    )
    try:
        r = requests.post(
            HUB,
            headers=HEADERS,
            json={
                "method": "tools/call",
                "params": {"name": "ask", "arguments": {"provider": "ollama", "message": q, "max_tokens": 80}},
            },
            timeout=30,
        )
        raw = r.json().get("result", {}).get("content", [{}])[0].get("text", "")
        try:
            d = json.loads(raw)
            return d.get("text", raw) if isinstance(d, dict) else raw
        except Exception:
            return raw or "Pouvez-vous préciser votre demande ?"
    except Exception:
        return "Pouvez-vous préciser votre demande ?"


def clarify_or_proceed(prompt: str, hub_url: str = HUB, token: str = TOKEN) -> dict:
    """Retourne {needs_clarif, clarification_q, original}."""
    if needs_clarification(prompt):
        return {
            "needs_clarif": True,
            "clarification_q": build_clarification_request(prompt),
            "original": prompt,
        }
    return {"needs_clarif": False, "clarification_q": None, "original": prompt}


if __name__ == "__main__":
    tests = [
        "fix ça",
        "analyse app/forge_goap.py et liste les classes publiques avec leurs méthodes",
        "update le truc",
        "lance les tests unitaires du module forge_rag_engine",
    ]
    for t in tests:
        r = clarify_or_proceed(t)
        flag = "❓" if r["needs_clarif"] else "✓"
        print(f"{flag} '{t[:50]}' → {r.get('clarification_q') or 'proceed'}")
