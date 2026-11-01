# -*- coding: utf-8 -*-
"""NR -- 30/10 : la surface Codex recoit un effort par taille, via la cle VERIFIEE dans la doc officielle
(config-reference.md) `model_reasoning_effort`, passee par `codex exec -c`. Fournisseur = openai (le rendu delegue
disait anthropic) ; modele None = profil de l'owner, aucun modele Codex mesure au census."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_palier_effort as pe  # noqa: E402


def test_codex_effort_par_taille():
    s = pe.resoudre("codex", "S")
    l = pe.resoudre("codex", "L")
    assert s["effort"] == "low" and l["effort"] == "high"
    assert "model_reasoning_effort" in s["drapeau_effort"] and s["drapeau_effort"].startswith("-c ")


def test_codex_fournisseur_openai_et_modele_du_profil():
    assert pe.FOURNISSEUR["codex"] == "openai"
    assert pe.TABLE["codex"]["M"][0] is None
