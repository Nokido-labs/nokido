"""NR — la symbiose : compresser en local avant d'envoyer au cloud.

Regle de conscience Nokido, non negociable : « logs massifs (>2000 chars) ->
compression via SymbioticBridge (Gemma Scout) ». L'audit de branchement du
2026-08-15 a trouve `forge_symbiotic_bridge` ORPHELIN — la regle existait, le
module existait, rien ne les reliait. Le pont est desormais greffe dans
`Provider.__init_subclass__`, au meme endroit inbypassable que le firewall.

Le test qui compte le plus est celui de la TRONCATURE. `compress_context`
retombe sur `raw_data[:2000]` quand le scout ne repond pas : ce n'est pas une
compression, c'est une coupe au milieu d'une phrase. L'envoyer au cloud ferait
raisonner un modele sur un texte ampute, sans que personne le sache. Mieux vaut
payer des tokens que perdre de l'information en silence.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))


class _Cloud:
    name = "gemini"


class _Local:
    name = "ollama_local"


def _appel(provider, message: str) -> str:
    from forge_agent_proxy import Provider

    return asyncio.run(Provider._symbiose_pre(provider, message))


def test_message_court_intact():
    """Sous le seuil, rien a compresser — et surtout aucun appel local inutile."""
    court = "x" * 100
    assert _appel(_Cloud(), court) == court


def test_provider_local_intact():
    """Compresser via ollama pour economiser sur ollama n'a pas de sens."""
    long_ = "y" * 5000
    assert _appel(_Local(), long_) == long_


def test_troncature_refusee_original_preserve():
    """LE test : un prefixe brut n'est pas une compression.

    Mesure du 2026-08-15 : scout indisponible, 5000 chars -> exactement 2000,
    prefixe exact de l'original. Accepte, cela aurait envoye au cloud un texte
    coupe net sans le signaler.
    """
    import forge_symbiotic_bridge as SB

    vrai = SB.SymbioticBridge.compress_context
    SB.SymbioticBridge.compress_context = lambda self, d, target_tokens=250: d[:2000]
    try:
        long_ = "y" * 5000
        assert _appel(_Cloud(), long_) == long_        # ORIGINAL, pas les 2000
    finally:
        SB.SymbioticBridge.compress_context = vrai


def test_compression_marquee_acceptee():
    """Une vraie compression porte la marque du compresseur et est retenue."""
    import forge_symbiotic_bridge as SB

    vrai = SB.SymbioticBridge.compress_context
    SB.SymbioticBridge.compress_context = (
        lambda self, d, target_tokens=250: "[CONTEXTE COMPRESSÉ PAR GEMMA LOCAL]\nresume"
    )
    try:
        r = _appel(_Cloud(), "y" * 5000)
        assert r.startswith("[CONTEXTE COMPRES") and len(r) < 5000
    finally:
        SB.SymbioticBridge.compress_context = vrai


def test_echec_du_pont_est_fail_open():
    """La symbiose economise des tokens ; elle ne doit JAMAIS bloquer un appel."""
    import forge_symbiotic_bridge as SB

    def _explose(self, d, target_tokens=250):
        raise RuntimeError("scout injoignable")

    vrai = SB.SymbioticBridge.compress_context
    SB.SymbioticBridge.compress_context = _explose
    try:
        long_ = "y" * 5000
        assert _appel(_Cloud(), long_) == long_
    finally:
        SB.SymbioticBridge.compress_context = vrai


def test_seuil_aligne_sur_la_regle():
    """2000 chars : le chiffre vient de la regle elle-meme, pas d'un reglage."""
    import forge_agent_proxy as P

    assert P._SYMBIOSE_SEUIL == 2000
    assert "ollama" in P._SYMBIOSE_LOCAUX


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
