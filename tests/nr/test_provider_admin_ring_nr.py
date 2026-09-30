# -*- coding: utf-8 -*-
"""NR — le ring d'une requete ne se DECLARE pas, il se PROUVE.

Mesure 2026-09-18 contre le hub vivant, sur un provider volontairement inexistant
(donc sans la moindre ecriture possible au coffre) :

    POST /api/providers/<x>/key   sans en-tete        -> 403
    POST /api/providers/<x>/key   X-Ring: 0           -> 200   <-- franchi
    POST /api/providers/<x>/key   Bearer <jeton hub>  -> 403   <-- refuse

`_resolve_request_ring` lisait `X-Ring`, un en-tete pose par le CLIENT, et lui
obeissait. L'identite AUTO-DECLAREE ouvrait donc l'ecriture ET la suppression de
cles dans le coffre DPAPI, pendant que l'identite PROUVEE par le jeton du coffre
etait refusee : l'inversion exacte de ce que `_HEADER_FLOOR_RING = 4` interdit
cote videur.

MORSURE de ce fichier : `test_l_entete_auto_declare_ne_donne_plus_rien`. Remettre
la lecture de `X-Ring` doit le faire rougir immediatement -- sans lui, les autres
tests resteraient verts avec le trou grand ouvert, puisqu'ils ne verifient que le
chemin legitime.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_provider_admin as PA  # noqa: E402

JETON = "jeton-temoin-de-longueur-realiste-0123456789abcdef"


class _Requete:
    """Requete minimale : uniquement ce que le code sous test consulte."""

    def __init__(self, headers=None, ring=None, path_params=None):
        self.headers = dict(headers or {})
        self.path_params = dict(path_params or {})
        if ring is not None:
            self.state = type("Etat", (), {"ring": ring})()


def _coffre(monkeypatch, valeur=JETON, casse=False):
    """Substitue le module de secrets sous SES DEUX noms d'import.

    Le module sous test tente `nokido_agent.app.forge_secrets` puis `app.forge_secrets`
    (idiome du fichier). Deux noms = deux entrees de `sys.modules` : n'en patcher
    qu'une laisse l'autre servir le VRAI coffre, et le test toucherait la machine.
    """
    faux = type(sys)("forge_secrets")

    def _get(nom, *_a, **_k):
        if casse:
            raise OSError("coffre injoignable (temoin)")
        return valeur if nom == "FORGE_MCP_TOKEN" else ""

    faux.get_secret = _get
    for nom in ("forge_secrets", "app.forge_secrets", "nokido_agent.app.forge_secrets"):
        monkeypatch.setitem(sys.modules, nom, faux)
    return faux


def test_l_entete_auto_declare_ne_donne_plus_rien(monkeypatch):
    """MORSURE — `X-Ring` est fourni par le client : il ne prouve rien.

    Chaque valeur ci-dessous ouvrait l'ecriture au coffre avant le 2026-09-18.
    """
    _coffre(monkeypatch)
    for valeur in ("0", "1", "00", " 0", "2"):
        obtenu = PA._resolve_request_ring(_Requete({"X-Ring": valeur}))
        assert obtenu > 1, (
            "X-Ring: %r rend le ring %s -- un en-tete auto-declare rouvre l'ecriture "
            "et la suppression de cles dans le coffre DPAPI" % (valeur, obtenu)
        )


def test_sans_aucun_entete_c_est_refuse(monkeypatch):
    _coffre(monkeypatch)
    assert PA._resolve_request_ring(_Requete()) > 1


def test_un_bearer_faux_est_refuse(monkeypatch):
    _coffre(monkeypatch)
    for entete in ("Bearer " + "x" * len(JETON), "Bearer ", "Basic " + JETON, JETON):
        assert PA._resolve_request_ring(_Requete({"Authorization": entete})) > 1, (
            "porteur invalide accepte : %r" % entete
        )


def test_un_bearer_egal_au_jeton_du_coffre_autorise(monkeypatch):
    """Le chemin LEGITIME doit passer, sinon on a ferme la capacite au lieu du trou.

    C'est ce chemin qu'emprunte le portail :7400, qui lit le meme jeton au coffre.
    """
    _coffre(monkeypatch)
    assert PA._resolve_request_ring(_Requete({"Authorization": "Bearer " + JETON})) <= 1
    # la casse du schema ne doit pas decider de l'acces
    assert PA._resolve_request_ring(_Requete({"Authorization": "bearer " + JETON})) <= 1


def test_un_coffre_illisible_refuse_au_lieu_d_autoriser(monkeypatch):
    """INCONNU n'est pas OUI : coffre muet => refus, jamais permission d'ecrire."""
    _coffre(monkeypatch, casse=True)
    assert PA._resolve_request_ring(_Requete({"Authorization": "Bearer " + JETON})) > 1
    _coffre(monkeypatch, valeur="")
    assert PA._resolve_request_ring(_Requete({"Authorization": "Bearer " + JETON})) > 1


def test_le_middleware_du_hub_fait_autorite(monkeypatch):
    """Un ring resolu en amont prime : c'est la seule autorite au-dessus du porteur."""
    _coffre(monkeypatch)
    assert PA._resolve_request_ring(_Requete(ring=0)) == 0
    assert PA._resolve_request_ring(_Requete({"X-Ring": "0"}, ring=4)) == 4


def _statut(coro):
    return asyncio.run(coro).status_code


def test_les_trois_routes_sensibles_sont_gardees(monkeypatch):
    """Chemin REEL des handlers, pas une lecture de leur source.

    `api_test_provider` n'avait AUCUN garde : elle fait partir une requete reseau
    avec la cle du coffre, donc elle servait d'oracle de validite de cle a tout
    process local, et consommait le quota du fournisseur.
    """
    pytest.importorskip(
        "starlette",
        reason="starlette est une dependance REELLE du hub : son absence est un fait a voir",
    )
    _coffre(monkeypatch)
    faux = {"provider": "__provider_inexistant_temoin__"}

    for nom in ("api_set_key", "api_delete_key", "api_test_provider"):
        handler = getattr(PA, nom)
        req = _Requete({"X-Ring": "0"}, path_params=faux)
        req.json = lambda: asyncio.sleep(0, result={"api_key": "x"})
        assert _statut(handler(req)) == 403, (
            "%s laisse passer un X-Ring auto-declare" % nom
        )

    for nom in ("api_set_key", "api_delete_key", "api_test_provider"):
        handler = getattr(PA, nom)
        req = _Requete({"Authorization": "Bearer " + JETON}, path_params=faux)
        req.json = lambda: asyncio.sleep(0, result={"api_key": "x"})
        assert _statut(handler(req)) != 403, (
            "%s refuse le porteur PROUVE : la capacite est fermee, pas le trou" % nom
        )
