# -*- coding: utf-8 -*-
"""NR — OpenAPI 3.x : `operationId` unique dans tout le document (section 4.8.10).

Defaut mesure le 2026-09-04 par l'audit NPSC, via les journaux de CI et non via
le registre : FastAPI emettait a CHAQUE montage de l'application

    UserWarning: Duplicate Operation ID auth_logout_auth_logout_get
    UserWarning: Duplicate Operation ID auth_logout_auth_logout_post

Cause : `@app.api_route("/auth/logout", methods=["GET", "POST"])` — seul
`api_route` multi-methodes du depot. FastAPI derive l'operationId du nom de la
fonction, donc les deux operations generees portaient le meme identifiant.

Un doublon casse la generation de clients et rend `/openapi.json` non conforme.

Ce garde verifie l'EFFET sur le document reellement produit, pas la forme du
decorateur : un futur `api_route` correctement nomme resterait acceptable, et
un `@app.get` mal nomme serait attrape. C'est la propriete que la norme exige,
pas le style d'ecriture.
"""
from __future__ import annotations

import sys
import warnings
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _chemin in (ROOT / "app", ROOT):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))


def _application():
    try:
        from web_hub.app import app  # type: ignore
    except Exception as exc:  # pragma: no cover - depend de l'env de test
        pytest.skip("application web non montable ici : %s" % type(exc).__name__)
    return app


def test_aucun_operation_id_duplique():
    """EFFET : le document OpenAPI genere ne porte aucun operationId en double."""
    app = _application()
    schema = app.openapi()
    ids = []
    for chemin, operations in (schema.get("paths") or {}).items():
        for methode, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            oid = operation.get("operationId")
            if oid:
                ids.append((oid, "%s %s" % (methode.upper(), chemin)))
    assert ids, "aucun operationId dans le document : la mesure n'a rien vu"
    compte = Counter(oid for oid, _ in ids)
    doublons = {oid: [ou for o, ou in ids if o == oid] for oid, n in compte.items() if n > 1}
    assert not doublons, "operationId dupliques (OAS 3.x 4.8.10) : %s" % doublons


def test_montage_sans_avertissement_de_doublon():
    """Le warning FastAPI EST la mesure : il ne doit plus etre emis.

    On regenere le schema en capturant les avertissements, parce que FastAPI
    n'emet ce diagnostic qu'a la construction du document.
    """
    app = _application()
    app.openapi_schema = None  # force la regeneration
    with warnings.catch_warnings(record=True) as captures:
        warnings.simplefilter("always")
        app.openapi()
    fautifs = [str(c.message) for c in captures if "Duplicate Operation ID" in str(c.message)]
    assert not fautifs, "FastAPI signale encore des doublons : %s" % fautifs


def test_route_logout_expose_bien_ses_deux_methodes():
    """ANTI-REGRESSION : corriger l'unicite ne doit pas perdre une methode.

    Le remede remplace un decorateur multi-methodes par deux decorateurs. Si
    l'un des deux sautait, la conformite serait atteinte en supprimant une
    fonctionnalite — le pire des correctifs.
    """
    app = _application()
    schema = app.openapi()
    operations = (schema.get("paths") or {}).get("/auth/logout")
    assert operations, "/auth/logout absent du document OpenAPI"
    methodes = {m.lower() for m in operations if m.lower() in ("get", "post", "put", "delete")}
    assert {"get", "post"} <= methodes, "methodes perdues sur /auth/logout : %s" % methodes
