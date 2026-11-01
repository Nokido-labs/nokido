# -*- coding: utf-8 -*-
"""NR -- 30/10 : le routeur (nvidia_nemotron_super) avait recu le remplacant du modele NVIDIA retire, mais le
fournisseur `nvidia_nim` de forge_agent_proxy servait encore l'ancien -> `ask` refusait l'alias (« substitution
refusee »). Les deux declarent le MEME modele, et jamais l'identifiant retire. Lecture du SOURCE (pas d'import lourd)."""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
RETIRE = "nvidia/nemotron-3-super-120b-a12b"


def _modele_nim() -> str:
    src = (RACINE / "app" / "forge_agent_proxy.py").read_text(encoding="utf-8")
    bloc = src.split("class NvidiaNIM(", 1)[1].split("\nclass ", 1)[0]
    return re.search(r'^\s+model = "([^"]+)"', bloc, re.M).group(1)


def _modele_routeur() -> str:
    src = (RACINE / "app" / "forge_llm_router.py").read_text(encoding="utf-8")
    bloc = src.split('"nvidia_nemotron_super": {', 1)[1].split("},", 1)[0]
    return re.search(r'"models": \["([^"]+)"', bloc).group(1)


def test_nim_ne_sert_plus_le_modele_retire():
    assert _modele_nim() != RETIRE


def test_nim_et_routeur_alignes():
    assert _modele_nim() == _modele_routeur()
