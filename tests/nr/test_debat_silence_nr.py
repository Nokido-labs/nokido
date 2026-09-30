"""Non-regression : le SILENCE d'un agent ne doit pas se compter comme une participation.

Mesure 2026-09-02, revue croisee du checkpoint c8bcec2e9 : un tour de debat est
sorti `ok=True` avec un texte VIDE. Le drapeau venait du TRANSPORT (l'appel HTTP a
reussi), pas du CONTENU. Consequences, toutes fausses dans le sens qui arrange :

  - le taux de disponibilite d'un provider est SURESTIME ;
  - une revue sans contenu se lit comme « rien a signaler », c'est-a-dire un
    REVIEW_OK alors que la seule lecture honnete est REVIEW_UNKNOWN ;
  - un routeur qui choisirait ses cerveaux sur ce taux prefererait un provider
    muet a un provider lent.

C'est la meme famille que tout le reste de cette nuit : ne jamais conclure d'une
source qui se tait.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for sous in ("tools", "app"):
    if str(ROOT / sous) not in sys.path:
        sys.path.insert(0, str(ROOT / sous))

import forge_debate_job as dj  # noqa: E402


def _faux_one(reponse):
    async def _f(provider, prompt, max_tokens):
        return reponse
    return _f


def _tour(monkeypatch, reponse):
    """Joue un tour en remplacant l'appel provider.

    `_turn` importe `_one` DANS la fonction, depuis `forge_cli_swarm` : c'est donc
    LA qu'il faut poser le double, pas sur `forge_debate_job`. Patcher le mauvais
    module rendait un AttributeError -- un test qui n'atteint pas sa source ne
    valide rien.
    """
    import forge_cli_swarm
    monkeypatch.setattr(forge_cli_swarm, "_one", _faux_one(reponse))
    return asyncio.run(dj._turn("provider_test", "question", max_tokens=32))


def test_une_reponse_vide_n_est_pas_une_participation(monkeypatch):
    """LE cas paye : transport OK, contenu VIDE."""
    texte, ok = _tour(monkeypatch, {"ok": True, "text": ""})
    assert ok is False, "un tour vide compte encore comme reussi"
    assert "vide" in texte.lower()


def test_une_reponse_blanche_est_traitee_comme_vide(monkeypatch):
    texte, ok = _tour(monkeypatch, {"ok": True, "text": "   \n\t  "})
    assert ok is False, texte


def test_une_vraie_reponse_reste_reussie(monkeypatch):
    """Le garde ne doit pas devenir un refus general : une reponse compte."""
    texte, ok = _tour(monkeypatch, {"ok": True, "text": "AUCUN"})
    assert ok is True
    assert texte == "AUCUN"


def test_un_transport_en_echec_reste_en_echec(monkeypatch):
    texte, ok = _tour(monkeypatch, {"ok": False, "text": "reponse partielle"})
    assert ok is False, texte


def test_une_exception_du_provider_ne_casse_pas_le_debat(monkeypatch):
    """Un provider qui leve ne doit ni faire tomber l'arene, ni passer pour un avis."""
    async def _boum(provider, prompt, max_tokens):
        raise RuntimeError("provider injoignable")

    import forge_cli_swarm
    monkeypatch.setattr(forge_cli_swarm, "_one", _boum)
    texte, ok = asyncio.run(dj._turn("provider_test", "question", max_tokens=32))
    assert ok is False
    assert "ERREUR" in texte
