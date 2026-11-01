# -*- coding: utf-8 -*-
"""NR (31/10, choix owner « transposer OmniRoute, etape 1 ») : un BUDGET epuise ouvre le repli DANS la tache.

Mesure 31/10 14:05 (NokidoTaskExecutorOpencodeGptoss.log + job_415a29c665c2) : 3 delegations sur 7 « rien produit » ;
derniere erreur ACP « session/prompt -> {'code': -32603, 'message': 'Internal error: API budget exhausted.'} ».
_RE_QUOTA ne connaissait pas « budget exhausted » : l'erreur tombait dans _panne_cli (-32603) = panne FOURNISSEUR ->
coupe-circuit + reaffectation de toute la tache a un executeur qui tape le meme fournisseur (boucle), sans jamais
tenter le repli_modele gratuit deja prevu DANS la tache. OmniRoute (open-sse/services, ingere 31/10) : un quota
epuise fait passer a la cible suivante dans la MEME requete. Meme regle que le 26/10 (« un solde a zero est un quota
a zero ») : un budget a zero est un quota a zero.
"""
# pylint: disable=missing-function-docstring
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_task_executor as T  # noqa: E402


@pytest.mark.parametrize("detail", [
    "erreur ACP OpenCode (RuntimeError): session/prompt -> {'code': -32603, 'message': 'Internal error: API budget "
    "exhausted.', 'data': {'service': 'session'}}",
    "API budget exhausted",
    "Budget exhausted for this key",
])
def test_un_budget_epuise_est_un_quota(detail):
    assert T._RE_QUOTA.search(detail), detail


@pytest.mark.parametrize("detail", ["Internal error: connection reset", "-32603 Internal error: unexpected EOF"])
def test_une_vraie_panne_n_est_pas_un_quota(detail):
    assert not T._RE_QUOTA.search(detail)
