"""NR -- cle HMAC d'INTEGRITE partagee (decision owner du 2026-09-28).

Mesure : les signataires HMAC (ledger vectoriel, sanitizer, bus d'etat) tournent aussi
sous les comptes bac a sable, qui n'ont pas de magasin personnel (DPAPI utilisateur
impossible, err 2). Une cle reservee a SYSTEM les laissait retomber sur le MAITRE, puis
sur des valeurs DEVINABLES : sha256(chemin du projet), "default_secret".

Decision : NOKIDO_HMAC_KEY est une cle d'integrite PARTAGEE, lisible par les comptes qui
signent, DECOUPLEE du maitre ; elle n'est pas un nom reserve. Sa compromission permet de
forger une signature d'integrite, jamais un jeton.

Ce que ce NR verrouille (`forge_secrets.cle_integrite_hmac`, source unique) :
  - NOKIDO_HMAC_KEY hors des noms reserves ;
  - cle dediee d'abord ; sinon le maitre en TRANSITION, dit une fois (fermeture 2b-6) ;
    sinon LEVE -- jamais une valeur devinable ;
  - le ledger et le sanitizer passent par elle ; le bus d'etat n'a plus de
    "default_secret".
Aucune valeur reelle ; comparaisons reduites a des booleens.
"""
import hashlib
import importlib
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEDIEE = "cle-integrite-nr-" + "i" * 32
MAITRE = "maitre-integrite-nr-" + "m" * 32


@pytest.fixture
def fs(monkeypatch):
    mod = importlib.import_module("nokido_agent.app.forge_secrets")
    if hasattr(mod, "_TRANSITION_INTEGRITE_DITE"):
        monkeypatch.setitem(mod._TRANSITION_INTEGRITE_DITE, "maitre", False)
    return mod


def _lire(store):
    return lambda k, required=False: store.get(k)


def test_la_cle_d_integrite_n_est_pas_un_nom_reserve(fs):
    assert "NOKIDO_HMAC_KEY" not in fs.NOMS_RESERVES


def test_cle_dediee_d_abord(fs):
    ok = fs.cle_integrite_hmac(_lire({"NOKIDO_HMAC_KEY": DEDIEE, "FORGE_MCP_TOKEN": MAITRE})) == DEDIEE.encode()
    assert ok


def test_sans_cle_dediee_le_maitre_en_transition_dite_une_fois(fs, caplog):
    with caplog.at_level(logging.WARNING):
        a = fs.cle_integrite_hmac(_lire({"FORGE_MCP_TOKEN": MAITRE}))
        b = fs.cle_integrite_hmac(_lire({"FORGE_MCP_TOKEN": MAITRE}))
    ok = a == b == MAITRE.encode()
    assert ok
    assert caplog.text.count("TRANSITION") == 1


def test_ni_cle_ni_maitre_leve(fs):
    with pytest.raises(fs.CleIntegriteIndisponible):
        fs.cle_integrite_hmac(_lire({}))


@pytest.mark.parametrize("nom_mod, fonction", [
    ("nokido_agent.app.forge_vec_ledger", "_get_signing_key"),
    ("nokido_agent.app.forge_conv_sanitizer", "_signing_key"),
])
def test_les_signataires_ne_devinent_jamais_une_cle(nom_mod, fonction, monkeypatch, fs):
    mod = importlib.import_module(nom_mod)
    monkeypatch.setattr(mod, "get_secret", _lire({}))
    try:
        cle = getattr(mod, fonction)()
    except RuntimeError:
        cle = None
    devinable = hashlib.sha256(str(ROOT).encode()).digest()
    ok = cle is None
    assert cle != devinable, "cle derivee du chemin du projet : devinable"
    assert ok, "sans cle d'integrite ni maitre, le signataire doit lever"


def test_le_bus_d_etat_n_a_plus_de_cle_par_defaut():
    src = (ROOT / "app" / "forge_state_manager.py").read_text(encoding="utf-8")
    assert "default_secret" not in src
    assert "cle_integrite_hmac" in src
