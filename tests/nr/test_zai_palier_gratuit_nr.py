# -*- coding: utf-8 -*-
"""NR -- zAI : la clef valide SANS solde n'est plus appelee, son palier GRATUIT a un slot (15/10).

Mesure par appels reels du 15/10 : /models zAI 200 (11 modeles) ; glm-5.2, glm-5.3-flash, glm-5.3-flashx
-> 429 code 1113 « Insufficient balance » ; glm-4.5-flash -> « OK » (22 s, modele a raisonnement) ;
glm-4.7-flash -> 429/1305 surcharge temporaire.

Contrat :
  1. `zai_glm_flash` est enregistre, gratuit (cost_tier 0), sur glm-4.5-flash, avec la MEME clef et le
     MEME endpoint que zai_glm5_2 (il en herite) ;
  2. `zai_glm5_2` est dans `SANS_SOLDE` avec sa raison, et `fournisseurs_joignables()` l'ecarte meme
     quand sa clef est presente ; `zai_glm_flash` y reste.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_agent_proxy as ap  # noqa: E402
from nokido_agent.app import forge_provider_alias as alias  # noqa: E402


def _registre():
    if not ap._PROVIDERS:
        ap._init_registry()
    return ap._PROVIDERS


def test_slot_gratuit_enregistre_meme_clef_meme_endpoint():
    p = _registre().get("zai_glm_flash")
    assert p is not None, sorted(_registre())
    assert p.model == "glm-4.5-flash" and p.cost_tier == 0
    assert isinstance(p, ap.ZaiGLM52) and p.api_key_env == ap.ZaiGLM52.api_key_env
    assert p.ask.__func__ is ap.ZaiGLM52.ask      # meme appel, meme endpoint : seul le modele change


def test_mistral_slot_du_palier_et_large_hors_palier(monkeypatch):
    """Meme schema pour Mistral (mesure 15/10) : large 403/1910 hors palier, nemo servi."""
    reg = _registre()
    p = reg.get("mistral_free")
    assert p is not None and p.model == "open-mistral-nemo" and p.cost_tier == 0
    assert isinstance(p, ap.MistralLarge) and p.ask.__func__ is ap.MistralLarge.ask
    assert "1910" in alias.SANS_SOLDE["mistral"] and "mistral_free" in alias.SANS_SOLDE["mistral"]
    for nom in ("mistral", "mistral_free"):
        monkeypatch.setattr(reg[nom], "is_available", lambda: True)
    j = ap.fournisseurs_joignables()
    assert "mistral" not in j and "mistral_free" in j


def test_sans_solde_qualifie_un_slot_jamais_un_modele():
    """Owner 15/10 : un modele injoignable par un fournisseur peut l'etre par un autre."""
    src = (RACINE / "app" / "forge_provider_alias.py").read_text(encoding="utf-8")
    assert "fournisseur x modele, JAMAIS le modele" in src
    assert all(nom in _registre() for nom in alias.SANS_SOLDE), "une entree doit nommer un SLOT enregistre"


def test_sans_solde_ecarte_des_joignables(monkeypatch):
    reg = _registre()
    assert "1113" in alias.SANS_SOLDE["zai_glm5_2"] and "zai_glm_flash" in alias.SANS_SOLDE["zai_glm5_2"]
    for nom in ("zai_glm5_2", "zai_glm_flash"):
        monkeypatch.setattr(reg[nom], "is_available", lambda: True)
    joignables = ap.fournisseurs_joignables()
    assert "zai_glm5_2" not in joignables and "zai_glm_flash" in joignables
