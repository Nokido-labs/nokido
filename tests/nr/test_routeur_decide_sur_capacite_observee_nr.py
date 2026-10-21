# -*- coding: utf-8 -*-
"""NR (bb:p2_capacite_fournisseur_observee_0925, instruit par OPENCODE_GLM docs/audit/routeur_capacite_observee_20261019.md)
-- le routeur DECIDE sur la capacite observee, sans jamais ecarter sur un inconnu.

Mesure 19/10 : forge_llm_router capte les en-tetes x-ratelimit-* a chaque appel (_capter_capacite(slot.name, ...)) et
forge_quota_tracker.capacite_observee rend FRAICHE / PERIMEE / INCONNU, mais le choix du slot (ProviderSlot._is_available)
ne la lit jamais : un fournisseur dont la capture FRAICHE dit « 0 requete restante avant reinitialisation » reste choisi
et rend un 429 (origine owner 25/09 : le 413 Groq venait des plafonds DECLARES, pas observes). Contrat :
  1. capture FRAICHE avec un compteur restant a 0 et une reinitialisation A VENIR -> slot indisponible, motif dit
     (`capacite_epuisee(nom)` rend le motif) ;
  2. INCONNU, PERIMEE, compteurs non lus, ou lecteur en panne -> le slot n'est JAMAIS ecarte (UNKNOWN != NO) ;
  3. restant > 0 -> disponible.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app import forge_llm_router as R  # noqa: E402
from nokido_agent.app import forge_quota_tracker as Q  # noqa: E402


def _cap(etat, restant_req=None, restant_tok=None, reinit_dans=30.0):
    def compteur(v):
        return {"etat": "INCONNU"} if v is None else {"etat": "CONNU", "valeur": v}
    return {"provider": "groq_test", "etat": etat, "compteurs": {"restant_requetes": compteur(restant_req),
                                                                  "restant_tokens": compteur(restant_tok)},
            "reinitialisation": {"reinit_requetes": {"etat": "CONNU", "dans_s": reinit_dans},
                                 "reinit_tokens": {"etat": "CONNU", "dans_s": reinit_dans}}}


def _slot(monkeypatch, lecteur):
    monkeypatch.setattr(Q, "capacite_observee", lecteur)
    monkeypatch.setattr(R.ProviderSlot, "is_configured", property(lambda self: True))
    s = R.ProviderSlot("groq_test", {"env_key": "GROQ_TEST_KEY"})
    monkeypatch.setattr(s, "_within_rpm", lambda: True)
    return s


@pytest.mark.parametrize("cap", [_cap("FRAICHE", restant_req=0, restant_tok=5000),
                                 _cap("FRAICHE", restant_req=12, restant_tok=0)])
def test_une_capacite_fraiche_epuisee_ecarte_le_slot(monkeypatch, cap):
    s = _slot(monkeypatch, lambda p, maintenant=None: cap)
    assert s._is_available(refresh=False) is False
    assert R.capacite_epuisee("groq_test"), "le motif de l'ecart doit etre dit"


@pytest.mark.parametrize("cap", [_cap("INCONNU"), _cap("PERIMEE", restant_req=0),
                                 _cap("FRAICHE"), _cap("FRAICHE", restant_req=7, restant_tok=900)])
def test_inconnu_perime_ou_restant_ne_l_ecarte_jamais(monkeypatch, cap):
    s = _slot(monkeypatch, lambda p, maintenant=None: cap)
    assert s._is_available(refresh=False) is True
    assert not R.capacite_epuisee("groq_test")


def test_un_lecteur_en_panne_n_ecarte_rien(monkeypatch):
    def panne(p, maintenant=None):
        raise OSError("capture illisible")
    s = _slot(monkeypatch, panne)
    assert s._is_available(refresh=False) is True
