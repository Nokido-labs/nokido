"""NR -- la sonde tool_call couvre Ollama Cloud (owner 28/10 : « il y a des modeles API avec prise en charge
d'outils, notamment sur Ollama Cloud ») : meme base et meme cle que les slots ollama_cloud_* du routeur."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app")]

import forge_tool_call_probe as P  # noqa: E402


def test_surface_ollama_cloud_presente_et_alignee_sur_le_routeur():
    surf = {e: (k, b) for e, k, b in P.SURFACES}
    assert surf.get("ollama_cloud") == ("OLLAMA_API_KEY", "https://ollama.com/v1")
    src = (ROOT / "app" / "forge_llm_router.py").read_text(encoding="utf-8")
    assert '"base_url": "https://ollama.com/v1"' in src and '"env_key": "OLLAMA_API_KEY"' in src
