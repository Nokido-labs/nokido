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
