"""NR -- 2b-5 : `jeton_hub(identite)`, une brique pour tous les clients du hub (2026-09-28).

Mesure du 2026-09-28 : le jeton MAITRE sert de porteur vers le hub dans des dizaines
d'outils (TUI, hooks, scripts). Les migrer un par un = reprendre tout. Une seule brique,
dans le module qui porte deja le cycle de vie des credentials (`forge_agent_credential`) :

  - identite provisionnee -> son jeton (court si possible, statique sinon : `jeton_pour`) ;
  - identite NON provisionnee -> le MAITRE, en TRANSITION jusqu'a la fermeture 2b-6 :
    mode `MAITRE_TRANSITION` dans `etat()`, dit une fois par identite ;
  - ni l'un ni l'autre -> '' (le hub repondra 401, refus lisible).
Des que l'owner provisionne `FORGE_TOKEN_<IDENTITE>`, le client quitte le maitre seul.
Premier branche : la TUI (identite neutre `OWNER_TUI` : le nom de l'owner ne figure pas
dans le code distribue).
"""
import importlib
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAITRE = "maitre-nr-2b5-hub-" + "m" * 32
PROPRE = "propre-nr-2b5-hub-" + "p" * 32


@pytest.fixture
def cred(monkeypatch):
    mod = importlib.import_module("nokido_agent.app.forge_agent_credential")
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    store = {"FORGE_MCP_TOKEN": MAITRE}
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: store.get(k))
    monkeypatch.setattr(mod, "jeton_pour", lambda agent: store.get(f"FORGE_TOKEN_{agent.upper()}", ""))
    if hasattr(mod, "_MAITRE_TRANSITION_DITE"):
        monkeypatch.setattr(mod, "_MAITRE_TRANSITION_DITE", set())
    mod._store_nr = store
    return mod


def test_identite_provisionnee_son_jeton(cred):
    cred._store_nr["FORGE_TOKEN_NR_ORGANE"] = PROPRE
    ok = cred.jeton_hub("nr_organe") == PROPRE
    assert ok


def test_identite_non_provisionnee_maitre_en_transition_dite(cred, caplog):
    with caplog.at_level(logging.WARNING):
        ok = cred.jeton_hub("NR_ORGANE") == MAITRE
    assert ok
    e = cred.etat()
    assert e["detail"].get("NR_ORGANE", {}).get("mode") == "MAITRE_TRANSITION"
    assert e["maitre_transition"] >= 1
    assert "TRANSITION" in caplog.text


def test_la_transition_n_est_dite_qu_une_fois_par_identite(cred, caplog):
    with caplog.at_level(logging.WARNING):
        cred.jeton_hub("NR_ORGANE")
        cred.jeton_hub("NR_ORGANE")
    assert caplog.text.count("TRANSITION") == 1


def test_ni_identite_ni_maitre_rien(cred):
    cred._store_nr.clear()
    assert cred.jeton_hub("NR_ORGANE") == ""


def test_la_tui_passe_par_jeton_hub():
    src = (ROOT / "tools" / "nokido_tui.py").read_text(encoding="utf-8")
    assert '_IDENTITE_HUB = "OWNER_TUI"' in src
    assert "jeton_hub(_IDENTITE_HUB)" in src
    assert '"X-Agent-Name": _IDENTITE_HUB' in src
    assert 'return get_secret("FORGE_MCP_TOKEN")' not in src
    assert "NAAROB_TUI" not in src
