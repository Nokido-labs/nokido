"""NR - le routeur distingue le modele DEMANDE du modele SERVI, et ne deduit jamais le second (15/10).

Audit ChatGPT web du 15/10, verifie sur le code : les retours du routeur ne portaient que
`slot.config["models"][0]` (ou le resident local), jamais ce que le fournisseur dit avoir servi.
Avec un alias dynamique cote fournisseur, l'attribution des scores et des limites etait faussee.
"""
from __future__ import annotations

import types
from pathlib import Path

from nokido_agent.app import forge_llm_router as lr

SRC = (Path(__file__).resolve().parents[2] / "app" / "forge_llm_router.py").read_text(encoding="utf-8")


def test_le_modele_servi_vient_du_fournisseur():
    assert lr._modele_servi(types.SimpleNamespace(model="openai/gpt-oss-120b-2026")) == "openai/gpt-oss-120b-2026"


def test_sans_modele_rendu_c_est_unknown_jamais_la_configuration():
    assert lr._modele_servi(types.SimpleNamespace(model=None)) == "UNKNOWN"
    assert lr._modele_servi(object()) == "UNKNOWN"


def test_chaque_retour_reussi_porte_les_deux_modeles():
    # Trois chemins de retour (call, call_cascade, appel direct sur un slot) : aucun ne doit l'oublier.
    assert SRC.count('"served_model": _modele_servi(resp)') == 3
    assert SRC.count('"requested_model": model') == 3
