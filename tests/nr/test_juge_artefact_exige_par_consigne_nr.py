"""NR -- une consigne qui nomme son fichier attendu ne sort jamais SUCCESS sans commit ni fichier (mesure du 6/11).

Lot C (job_39e9df24) : aucun commit, aucun fichier, une reponse faite d'une erreur d'outil de 7 789 caracteres, et le statut SUCCESS.
Un `pointer_ref` trouve dans le texte suffisait a faire lacher `_rien_produit`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]
RIEN = "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 0"
UN_COMMIT = "[effet observe] commits produits : 1 (a..b) ; fichiers non commites : 0"
CONSIGNE = 'PRODUIRE : audit_C.md\nDerniere ligne : {"intent":"OK_DONE","pointer_ref":"audit_C.md"}'
ERREUR = 'The arguments are invalid : Streamable HTTP error {"intent":"X","pointer_ref":"tasks.db:job_x"} Service Unavailable'


@pytest.fixture(scope="module")
def e():
    spec = importlib.util.spec_from_file_location("juge_consigne_executeur_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["juge_consigne_executeur_nr"] = m
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("reponse", [ERREUR, 'ok {"intent":"OK_DONE","pointer_ref":"audit_C.md"}', "texte libre tres long " * 40])
def test_sans_commit_ni_fichier_la_consigne_tranche(e, reponse):
    assert "[RIEN PRODUIT]" in (e._rien_produit(RIEN, reponse, CONSIGNE) or "")


def test_un_commit_produit_reste_juge_ailleurs(e):
    assert e._rien_produit(UN_COMMIT, ERREUR, CONSIGNE) is None


@pytest.mark.parametrize("consigne", ["Donne ton avis en texte.", '{"intent":"OK_DONE","pointer_ref":"tasks.db:job_1"}', None])
def test_sans_fichier_nomme_par_la_consigne_rien_ne_change(e, consigne):
    assert e._rien_produit(RIEN, '{"intent":"OK_DONE","pointer_ref":"tasks.db:job_x"}', consigne) is None
