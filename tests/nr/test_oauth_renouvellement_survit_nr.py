# -*- coding: utf-8 -*-
"""NR — un renouvellement OAuth survit au redemarrage du serveur, sans jamais etre ecrit en clair.

Mesure 2026-09-29 : une relance de NokidoPairMCP a efface les renouvellements (en memoire
seulement) et claude.ai a du se reautoriser. Decision owner : les garder. Forme retenue :
seule l'EMPREINTE sha256 est persistee, a cote du registre des clients ; la rotation tient.
"""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHEMIN = ROOT / "tools" / "forge_bridge_oauth.py"
CLIENT = SimpleNamespace(client_id="client-nr")


@pytest.fixture()
def oauth(monkeypatch, tmp_path):
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", "cle-factice-de-test-renouvellement-0123456789")
    monkeypatch.delenv("NOKIDO_BRIDGE_REVOKED", raising=False)
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", str(tmp_path / "clients.json"))
    spec = importlib.util.spec_from_file_location("forge_bridge_oauth_nr_renouvellement", CHEMIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_le_renouvellement_survit_au_redemarrage_sans_etre_ecrit(oauth):
    suite = oauth.AutoriteLocale()._delivrer("client-nr", None).refresh_token
    contenu = oauth.fichier_des_renouvellements().read_text(encoding="utf-8")
    assert suite not in contenu, "le moyen de renouvellement est ecrit EN CLAIR"
    assert oauth._empreinte(suite) in contenu
    charge = asyncio.run(oauth.AutoriteLocale().load_refresh_token(CLIENT, suite))   # nouvelle vie
    assert charge is not None and charge.token == suite and charge.client_id == "client-nr"


def test_la_rotation_tient_apres_redemarrage(oauth):
    suite = oauth.AutoriteLocale()._delivrer("client-nr", None).refresh_token
    b = oauth.AutoriteLocale()
    charge = asyncio.run(b.load_refresh_token(CLIENT, suite))
    neuf = asyncio.run(b.exchange_refresh_token(CLIENT, charge, None)).refresh_token
    c = oauth.AutoriteLocale()
    assert asyncio.run(c.load_refresh_token(CLIENT, suite)) is None, "l'ancien moyen reste rejouable"
    assert asyncio.run(c.load_refresh_token(CLIENT, neuf)) is not None


def test_un_autre_client_ou_un_moyen_echu_est_refuse(oauth, monkeypatch):
    a = oauth.AutoriteLocale()
    suite = a._delivrer("client-nr", None).refresh_token
    assert asyncio.run(a.load_refresh_token(SimpleNamespace(client_id="autre"), suite)) is None
    monkeypatch.setattr(oauth, "DUREE_RENOUVELLEMENT_S", -10)
    echu = a._delivrer("client-nr", None).refresh_token
    assert asyncio.run(oauth.AutoriteLocale().load_refresh_token(CLIENT, echu)) is None
