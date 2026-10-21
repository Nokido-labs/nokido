"""Fixtures partagees des tests NR.

Ce fichier ne contient QU'UNE chose, et volontairement : la reparation d'un
decalage entre ce que les tests du hub web posent et ce que le code lit.

LE DECALAGE (mesure 2026-08-20). Les `test_hub_*.py` configurent l'auth par
`monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", ...)`. Depuis la migration des
secrets vers le coffre DPAPI, `AuthConfig.from_env()` ne lit plus
`os.environ` mais `forge_secrets.get_secret`. Les tests posaient donc un token
que la configuration IGNORAIT : elle chargeait le VRAI token de la machine, et
46 tests echouaient en 401 -- contre un secret de production, jamais contre un
defaut du code. Ils ne mesuraient plus rien.

LA REPARATION. Pour ces fichiers seulement, le coffre REND ce que
l'environnement du test pose. Le contrat verifie redevient celui que ces tests
decrivent : « un admin token configure ouvre la session, son absence ferme
tout ». La production continue de lire le coffre, et aucun autre test NR n'est
touche -- un conftest `autouse` sans garde changerait le comportement de 92
fichiers d'un coup, dont ceux qui veulent justement le vrai coffre.
"""
from __future__ import annotations

import os

import pytest


# TRACEUR D'IMPORT (19/10, plantages arrow.dll des workers de CI) : desarme sauf si NOKIDO_TRACE_IMPORT est pose
# (ci_local --trace-import pyarrow). Il journalise le test en cours au premier chargement du module surveille.
_TRACE_IMPORT = os.environ.get("NOKIDO_TRACE_IMPORT", "").strip()
if _TRACE_IMPORT:
    from nokido_agent.tools import forge_trace_import as _trace_import

    _trace_import.armer([m.strip() for m in _TRACE_IMPORT.split(",")])

    def pytest_runtest_setup(item):
        _trace_import.COURANT["test"] = item.nodeid


@pytest.fixture(autouse=True)
def _coffre_suit_l_environnement(request, monkeypatch):
    # GARDE DE PORTEE : uniquement les tests du hub web. Le nom de fichier est
    # un critere grossier, mais il est LISIBLE -- et une fixture globale muette
    # serait bien pire qu'un filtre explicite qu'on peut contester.
    nom = getattr(request.node, "fspath", None)
    if nom is None or not os.path.basename(str(nom)).startswith("test_hub_"):
        return
    try:
        import forge_secrets
    except Exception:  # noqa: BLE001 - coffre absent : les tests d'env restent valides
        return
    monkeypatch.setattr(forge_secrets, "get_secret",
                        lambda cle, *a, **kw: os.environ.get(cle) or None,
                        raising=False)


@pytest.fixture(autouse=True)
def _pas_de_verdict_reel_depuis_un_test(monkeypatch):
    """19/10 : le verdict automatique de l'executeur (recompense + transient au tableau noir) est COUPE dans tous les
    tests NR. Mesure : les NR de delegation avaient ecrit ~23 faux verdicts (job_empty_01, job_repli_01, t-vibe...)
    dans le vrai registre de recompense, dont des VIDE qui punissaient des repondeurs. Portee globale VOULUE : aucun
    test ne doit ecrire ce registre ; les NR du verdict le rallument avec leurs doublures (`setenv("1")`)."""
    monkeypatch.setenv("NOKIDO_VERDICT_AUTO", "0")
    # Meme regle pour le bus d'essaim (19/10) : aucun test n'ecrit le VRAI miroir sandbox/reflexion.jsonl.
    monkeypatch.setenv("NOKIDO_BUS_TACHES", "0")
    # Et pour le journal d'usage du RAG (19/10, extracteur de citations) : aucun test n'ecrit logs/rag_usage_signal.jsonl.
    monkeypatch.setenv("NOKIDO_RAG_SIGNAL", "0")
