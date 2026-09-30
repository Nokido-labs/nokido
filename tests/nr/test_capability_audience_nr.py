# -*- coding: utf-8 -*-
"""NR — audience du CapabilityToken (RFC 8707 / RFC 9068 / spec MCP 2026-07-28).

Un bearer sans audience prouve la POSSESSION d'un secret, jamais sa DESTINATION :
il est rejouable vers toute ressource qui partage ce secret. `aud` lie le jeton a
la ressource pour laquelle il a ete emis.

Ce test garde les quatre proprietes qui comptent, et surtout la troisieme :

  1. un jeton emis SANS audience reste accepte quand on n'en exige aucune
     (retro-compatibilite : les jetons en circulation n'ont pas ce champ) ;
  2. un jeton emis AVEC audience est accepte pour CETTE audience ;
  3. un jeton emis SANS audience est REFUSE des qu'une audience est exigee --
     « pas d'audience » n'est PAS « la bonne audience » ;
  4. une audience differente est refusee.

Et le cas qui protege du motif « garde sans emetteur » : le champ doit survivre a
un aller-retour encode/decode. Sans emission, la verification ajoutee au decodage
ne s'appliquerait jamais a rien.

Zero service externe : secret local, aucun TPM requis, aucun reseau.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from forge_integrity import CapabilityToken, IntegrityRing  # noqa: E402

SECRET = b"secret-de-test-uniquement-jamais-en-production"
RESSOURCE = "https://127.0.0.1:8766/mcp"


def _jeton(aud: str = "") -> CapabilityToken:
    maintenant = time.time()
    return CapabilityToken(
        sub="VIBE", ring=IntegrityRing.UNTRUSTED, scopes={"rag": ["read"]},
        exp=maintenant + 300, iat=maintenant, jti="jti-test", seq=1, aud=aud,
    )


def test_sans_audience_reste_accepte_si_aucune_exigee():
    """Retro-compatibilite : les jetons deja emis n'ont pas ce champ."""
    brut = _jeton().encode(SECRET)
    t = CapabilityToken.decode(brut, SECRET)
    assert t.sub == "VIBE"
    assert t.aud == ""


def test_audience_survit_a_l_aller_retour():
    """Sans EMETTEUR, la verification au decodage ne s'appliquerait a rien.

    C'est le motif « garde branche sur un signal que personne n'emet », deja paye
    deux fois : un recepteur correct ne prouve rien tant qu'une valeur non nulle
    n'a pas ete observee.
    """
    brut = _jeton(RESSOURCE).encode(SECRET)
    assert CapabilityToken.decode(brut, SECRET).aud == RESSOURCE


def test_audience_correcte_acceptee():
    brut = _jeton(RESSOURCE).encode(SECRET)
    t = CapabilityToken.decode(brut, SECRET, audience=RESSOURCE)
    assert t.aud == RESSOURCE


def test_absence_d_audience_ne_vaut_pas_correspondance():
    """LE cas central : un jeton legacy ne doit pas passer un controle d'audience."""
    brut = _jeton().encode(SECRET)
    with pytest.raises(ValueError) as e:
        CapabilityToken.decode(brut, SECRET, audience=RESSOURCE)
    assert "audience" in str(e.value).lower()


def test_audience_etrangere_refusee():
    brut = _jeton("https://autre.example/mcp").encode(SECRET)
    with pytest.raises(ValueError):
        CapabilityToken.decode(brut, SECRET, audience=RESSOURCE)


def test_signature_reste_verifiee_avec_audience():
    """L'ajout d'un champ ne doit pas ouvrir une voie de contournement HMAC."""
    brut = _jeton(RESSOURCE).encode(SECRET)
    payload, sig = brut.split(".")[0], brut.split(".")[1]
    falsifie = f"{payload}.{'0' * len(sig)}"
    with pytest.raises(ValueError):
        CapabilityToken.decode(falsifie, SECRET, audience=RESSOURCE)
