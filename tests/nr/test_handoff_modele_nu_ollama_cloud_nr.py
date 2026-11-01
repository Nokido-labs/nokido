"""NR -- prefixe litellm `openai/` retire selon la SURFACE (Ollama Cloud), pas selon la forme du nom.

Recette reelle 28/10 23 h 25 : `ollama_cloud_ultra` (modele routeur `openai/nemotron-3-ultra`, sans `:`) -> HTTP 404,
car le prefixe n'etait retire que pour les noms `x:tag`. `openai/gpt-oss-20b` est un VRAI identifiant Groq : intact."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "app"), str(ROOT / "tools")]

from app import forge_handoff as fh  # noqa: E402

OLLAMA = "https://ollama.com/v1"
GROQ = "https://api.groq.com/openai/v1"


def test_ollama_cloud_retire_openai_meme_sans_tag():
    """Surface ollama.com : prefixe retire, avec ou sans tag."""
    assert fh._modele_nu("openai/nemotron-3-ultra", base=OLLAMA) == "nemotron-3-ultra"
    assert fh._modele_nu("openai/gpt-oss:120b", base=OLLAMA) == "gpt-oss:120b"


def test_groq_garde_son_identifiant_openai():
    """Surface Groq : `openai/gpt-oss-20b` est le vrai identifiant, intact."""
    assert fh._modele_nu("openai/gpt-oss-20b", base=GROQ) == "openai/gpt-oss-20b"
    assert fh._modele_nu("groq/llama-3", base=GROQ) == "llama-3"


def test_sans_base_comportement_historique():
    """Sans base : regle historique (prefixe retire seulement pour un nom x:tag)."""
    assert fh._modele_nu("openai/gpt-oss:120b") == "gpt-oss:120b"
    assert fh._modele_nu("openai/gpt-oss-20b") == "openai/gpt-oss-20b"
