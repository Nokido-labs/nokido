"""NR 2/11 (owner : « instruire puis retirer » la recopie des jetons hors du coffre).

Les trois hooks Claude (session_start, session_stop, precompact) prennent LEUR jeton dans cet ordre, et seulement lui :
  1. coffre DPAPI, cle FORGE_TOKEN_CLAUDE_HOOK ;
  2. variable du PROCESSUS FORGE_TOKEN_CLAUDE_HOOK (injection voulue par un parent) ;
  3. rien -> chaine vide (le hook se degrade, la session ne casse pas).
Interdits mesures le 2/11 : session_stop lisait la variable AVANT le coffre ; les trois retombaient sur
FORGE_TOKEN_CLAUDE (credential ring 1 d'un voisin, que leurs commentaires interdisent) puis sur Nokido.env
(« le .env n'est pas une source de secrets »).
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


def _charger(nom):
    spec = importlib.util.spec_from_file_location("hook_" + nom, RACINE / "tools" / (nom + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _coffre(monkeypatch, valeurs):
    fs = types.ModuleType("nokido_agent.app.forge_secrets")
    fs.get_secret = lambda k: valeurs.get(k, "")
    pkg = types.ModuleType("nokido_agent")
    app = types.ModuleType("nokido_agent.app")
    pkg.__path__, app.__path__ = [], []
    monkeypatch.setitem(sys.modules, "nokido_agent", pkg)
    monkeypatch.setitem(sys.modules, "nokido_agent.app", app)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", fs)


def _lecteurs():
    out = []
    for nom, fn in (("claude_session_start", "load_token"), ("claude_session_stop", "load_token"),
                    ("claude_precompact", "_jeton_hook")):
        out.append(pytest.param(nom, fn, id=nom))
    return out


@pytest.fixture
def propre(monkeypatch, tmp_path):
    for k in ("FORGE_TOKEN_CLAUDE_HOOK", "FORGE_TOKEN_CLAUDE", "FORGE_MCP_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


@pytest.mark.parametrize("nom,fn", _lecteurs())
def test_coffre_avant_variable(nom, fn, propre, monkeypatch):
    m = _charger(nom)
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE_HOOK": "du-coffre"})
    monkeypatch.setenv("FORGE_TOKEN_CLAUDE_HOOK", "de-la-variable")
    assert getattr(m, fn)() == "du-coffre"


@pytest.mark.parametrize("nom,fn", _lecteurs())
def test_variable_du_processus_en_repli(nom, fn, propre, monkeypatch):
    m = _charger(nom)
    _coffre(monkeypatch, {})
    monkeypatch.setenv("FORGE_TOKEN_CLAUDE_HOOK", "injecte-par-le-parent")
    assert getattr(m, fn)() == "injecte-par-le-parent"


@pytest.mark.parametrize("nom,fn", _lecteurs())
def test_jamais_le_jeton_du_voisin_ni_le_fichier_env(nom, fn, propre, monkeypatch):
    m = _charger(nom)
    _coffre(monkeypatch, {})
    monkeypatch.setenv("FORGE_TOKEN_CLAUDE", "jeton-ring-1-du-voisin")
    monkeypatch.setenv("FORGE_MCP_TOKEN", "jeton-partage")
    (propre / "Nokido.env").write_text("FORGE_TOKEN_CLAUDE_HOOK=du-fichier\nFORGE_TOKEN_CLAUDE=du-fichier-2\n"
                                       "FORGE_MCP_TOKEN=du-fichier-3\n", encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", propre)
    assert getattr(m, fn)() == ""
