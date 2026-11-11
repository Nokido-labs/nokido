# -*- coding: utf-8 -*-
"""NR (owner 3/11 « chargement a la demande, decharge apres 10 min ») : chaque requete de LMStudio.ask porte le ttl
JIT de LM Studio (LMSTUDIO_TTL_S, 600 s par defaut). Mesure 3/11 : un ask expire a 60 s a fait charger
qwen2.5-7b-instruct sans ttl -> 5,69 Go residents (node.exe <- llmster.exe), RAM 86 %, jobs refuses."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _classe_lmstudio() -> str:
    src = (ROOT / "app" / "forge_agent_proxy.py").read_text(encoding="utf-8")
    i = src.find("class LMStudio(")
    j = src.find("\nclass ", i + 10)
    return src[i:j]


def test_les_requetes_portent_le_ttl():
    c = _classe_lmstudio()
    assert re.search(r'"ttl":\s*int\(os\.environ\.get\("LMSTUDIO_TTL_S",\s*"600"\)\)', c), "ttl absent du corps"
    # les DEUX envois (premier essai + reprise apres chargement) utilisent le meme corps
    assert c.count('_req("POST", "/v1/chat/completions", _corps)') == 2
