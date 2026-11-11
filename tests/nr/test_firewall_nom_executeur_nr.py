"""NR 6/11 : un nom d'executeur reste lisible, une vraie charge base64 reste masquee.

Le motif BASE64_SUSPECT masquait 4 services NokidoTaskExecutorOpencode* dans whoami.
"""
from __future__ import annotations

from nokido_agent.app.forge_semantic_firewall import redact_tool_output

CHARGE = "QWxhZGRpbjpvcGVuIHNlc2FtZTEyMzQ1Njc4OTA"


def _masque(texte: str) -> str:
    # La fonction rend (texte, rapport) : sans [0], « not in » passerait a vide sur le tuple.
    rendu, _rapport = redact_tool_output(texte, "whoami", None)
    assert isinstance(rendu, str)
    return rendu


def test_nom_executeur_avec_chiffre_reste_lisible():
    assert "NokidoTaskExecutorOpencodeDefaut2" in _masque("service NokidoTaskExecutorOpencodeDefaut2 actif")


def test_charge_base64_reste_masquee():
    assert CHARGE not in _masque(f"valeur {CHARGE} fin")


def test_prefixe_executeur_ne_couvre_pas_une_charge_longue():
    charge = "NokidoTaskExecutor" + CHARGE
    assert charge not in _masque(f"valeur {charge} fin")
