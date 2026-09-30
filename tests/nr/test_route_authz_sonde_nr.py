"""NR -- classement des sondes d'authentification (`forge_route_authz_audit`).

Cet instrument s'est trompe DEUX FOIS le 2026-09-02, et les deux fois du cote
rassurant :

1. version binaire (200 vs « refusees ») : 404, 405, 5xx et les timeouts
   comptaient comme protege. Elle SURESTIMAIT la protection.
2. sonde par `urlopen` sur des flux SSE : dix routes sortaient en
   « INJOIGNABLE », lu comme « pas 200 donc protege » -- alors que NEUF
   rendaient `200 OK` sans le moindre jeton.

Puis un troisieme piege, dans l'autre sens : trois routes rendent 302 vers une
cible protegee. Les compter comme ouvertes aurait accuse a tort.

D'ou la regle que ces tests verrouillent : **un instrument d'audit qui se
trompe doit se tromper en ACCUSANT, jamais en absolvant** -- et tout ce qui
n'est pas une preuve positive de refus reste INDETERMINE.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from forge_route_authz_audit import classer_sonde  # noqa: E402


def test_200_est_ouverte():
    assert classer_sonde(200) == "OUVERTE"


@pytest.mark.parametrize("code", [401, 403])
def test_seuls_401_403_prouvent_la_protection(code):
    assert classer_sonde(code) == "REFUSEE_AUTH"


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_les_redirections_sont_nommees(code):
    """Ni ouvertes ni refusees : le verdict est au bout de la redirection."""
    assert classer_sonde(code) == "REDIRECTION"


def test_404_est_absente():
    assert classer_sonde(404) == "ABSENTE"


@pytest.mark.parametrize("code", [405, 400, 429, 500, 502, 503])
def test_les_codes_muets_ne_prouvent_rien(code):
    """405 dit que la methode ne colle pas, 5xx que ca casse -- aucun ne dit
    que la route est protegee. C'est le defaut d'origine."""
    assert classer_sonde(code) == "INDETERMINEE"


@pytest.mark.parametrize("val", ["INJOIGNABLE:TimeoutError", "PAS_DE_STATUT_EN_12S",
                                 "AUCUNE_REPONSE", None, ""])
def test_une_non_mesure_n_est_jamais_une_protection(val):
    """Le piege exact paye sur les flux SSE : ne pas avoir pu voir ne doit
    jamais se lire comme « protege »."""
    assert classer_sonde(val) == "INDETERMINEE"


def test_aucun_code_ne_tombe_dans_refusee_par_defaut():
    """Balayage : hors 401/403, RIEN ne doit se classer comme protege."""
    for code in list(range(200, 600)):
        v = classer_sonde(code)
        if code in (401, 403):
            assert v == "REFUSEE_AUTH", code
        else:
            assert v != "REFUSEE_AUTH", (
                "code %d classe comme protege sans preuve positive" % code)


def test_seul_200_est_ouverte_parmi_les_2xx():
    """201/204 ne sont pas produits par une sonde GET ici : les ranger en
    OUVERTE serait inventer une mesure. Ils restent INDETERMINEE."""
    for code in (201, 202, 204, 206):
        assert classer_sonde(code) == "INDETERMINEE", code


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
