"""NR -- plus aucune cle de chiffrement DERIVEE DU JETON MAITRE (coffre, 2026-09-28).

Mesure du jour : `forge_encrypt.get_fernet` et `forge_db_conn.resolve_key` retombaient, sans
leur cle dediee (FORGE_ENCRYPT_KEY, LAFORGE_DB_KEY), sur une cle derivee du maitre -- lu au
guichet, puis dans Nokido.env en clair. Ce repli a empeche de fermer ces deux noms hors
SYSTEM (e844c80ff) : ferme, un process aurait chiffre avec une MAUVAISE cle, en silence.

Contexte dit par l'owner le meme jour : le chiffrement au repos des bases est le VOLUME
VeraCrypt V:, pas SQLCipher (absent des deux interpreteurs, mesure) -- LAFORGE_DB_KEY ne
protege aujourd'hui aucune donnee.

Contrats :
  1. sans cle dediee, `get_fernet` LEVE (echec franc) et ne lit jamais le maitre, ni au
     guichet ni dans Nokido.env ;
  2. avec la cle dediee, rien ne change ;
  3. sans cle dediee, `resolve_key` rend None (SQLite, comme documente) sans jamais lire le
     maitre ;
  4. les deux noms sont FERMES hors SYSTEM (plus en transition).
Aucune vraie valeur : guichet et environnement substitues.
"""
from __future__ import annotations

import importlib

import pytest

ENC = "nokido_agent.app.forge_encrypt"
DBC = "nokido_agent.app.forge_db_conn"
FS = "nokido_agent.app.forge_secrets"


@pytest.fixture
def guichet(monkeypatch):
    lus: list = []
    valeurs: dict = {}

    def _get(k, required=False):
        lus.append(k)
        return valeurs.get(k)

    enc = importlib.import_module(ENC)
    dbc = importlib.import_module(DBC)
    monkeypatch.setattr(enc, "get_secret", _get)
    monkeypatch.setattr(dbc, "get_secret", _get)
    monkeypatch.setattr(enc, "_fernet_instance", None)
    for k in ("FORGE_ENCRYPT_KEY", "LAFORGE_DB_KEY", "FORGE_MCP_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return enc, dbc, lus, valeurs


def test_sans_cle_dediee_le_chiffrement_leve_et_ne_lit_jamais_le_maitre(guichet):
    enc, _dbc, lus, _v = guichet
    with pytest.raises(RuntimeError):
        enc.get_fernet()
    assert "FORGE_MCP_TOKEN" not in lus


def test_avec_la_cle_dediee_rien_ne_change(guichet):
    from cryptography.fernet import Fernet

    enc, _dbc, lus, valeurs = guichet
    valeurs["FORGE_ENCRYPT_KEY"] = Fernet.generate_key().decode()
    f = enc.get_fernet()
    ok = (f.decrypt(f.encrypt(b"x")) == b"x", "FORGE_MCP_TOKEN" in lus)
    assert ok == (True, False)


def test_sans_cle_de_base_resolve_key_rend_none_sans_lire_le_maitre(guichet):
    _enc, dbc, lus, _v = guichet
    ok = (dbc.resolve_key() is None, "FORGE_MCP_TOKEN" in lus)
    assert ok == (True, False)


def test_les_deux_cles_sont_fermees_hors_system():
    s = importlib.import_module(FS)
    ok = ({"FORGE_ENCRYPT_KEY", "LAFORGE_DB_KEY"} & s.RESERVES_EN_TRANSITION, 
          {"FORGE_ENCRYPT_KEY", "LAFORGE_DB_KEY"} <= s.NOMS_RESERVES)
    assert ok == (set(), True)
