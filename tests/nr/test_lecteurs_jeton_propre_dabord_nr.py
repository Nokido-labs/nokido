"""NR etape 3 jeton maitre : GOAP/ORCHESTRATE/SELF_PATCHER/MULTI_LLM lisent leur jeton
propre d'abord ; repli sur le maitre AVEC avertissement ; jamais la valeur dans un log.
Coffre simule (monkeypatch de get_secret). Watchdog -> superviseur :8765 : NON migre
(l'API ne connait que LAFORGE_SUPERVISOR_TOKEN ?? FORGE_MCP_TOKEN)."""
import logging
import pathlib

import pytest

PROPRE = "valeur-propre-XYZ123"
MAITRE = "valeur-maitre-ABC987"
RACINE = pathlib.Path(__file__).resolve().parents[2]
NOMS = ["GOAP", "ORCHESTRATE", "SELF_PATCHER", "MULTI_LLM"]


@pytest.fixture(autouse=True)
def _import_prealable(caplog):
    """L'import de forge_hub_client cree le singleton `hub` (agent CLAUDE, sans jeton) et
    journalise un WARNING a l'import : fait module-level qui n'est pas l'objet du test.
    On force l'import ici, puis on purge caplog -> resultat independant de l'ordre."""
    import nokido_agent.app.forge_hub_client  # noqa: F401
    import nokido_agent.app.forge_secrets  # noqa: F401
    caplog.clear()
    yield


def _client(monkeypatch, contenu, nom):
    import nokido_agent.app.forge_hub_client as hc
    import nokido_agent.app.forge_secrets as fs
    monkeypatch.setattr(fs, "get_secret", lambda k, *a, **kw: contenu.get(k, ""))
    monkeypatch.setattr(hc, "_ENV_TOKENS", {})
    monkeypatch.setenv("LAFORGE_HUB_CLIENT_JETON_COURT", "0")  # statique : pas de login
    return hc.HubClient(agent=nom)


@pytest.mark.parametrize("nom", NOMS)
def test_propre_present(monkeypatch, caplog, nom):
    with caplog.at_level(logging.DEBUG):
        c = _client(monkeypatch, {"FORGE_TOKEN_" + nom: PROPRE, "FORGE_MCP_TOKEN": MAITRE}, nom)
        h = c.entetes()
    assert h["Authorization"] == "Bearer " + PROPRE
    assert h["LaForge-Agent-Name"] == nom
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert PROPRE not in caplog.text and MAITRE not in caplog.text


@pytest.mark.parametrize("nom", NOMS)
def test_repli_maitre_dit_sans_nom(monkeypatch, caplog, nom):
    with caplog.at_level(logging.DEBUG):
        c = _client(monkeypatch, {"FORGE_MCP_TOKEN": MAITRE}, nom)
        h = c.entetes()
    assert h["Authorization"] == "Bearer " + MAITRE
    assert "LaForge-Agent-Name" not in h
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("repli maitre : FORGE_TOKEN_%s absent" % nom in m for m in msgs)
    assert MAITRE not in caplog.text


def test_helpers_supprimes_de_forge_secrets():
    src = (RACINE / "app/forge_secrets.py").read_text(encoding="utf-8")
    assert "def jeton_propre_ou_maitre" not in src
    assert "def entetes_jeton_propre" not in src


@pytest.mark.parametrize("mod,nom", [
    ("tools/forge_goap_hub_bridge.py", "GOAP"),
    ("tools/forge_orchestrate_loop.py", "ORCHESTRATE"),
    ("tools/forge_orchestrate_react.py", "ORCHESTRATE"),
    ("tools/forge_self_patcher.py", "SELF_PATCHER"),
    ("tools/multi_llm_daemon.py", "MULTI_LLM"),
])
def test_lecteurs_cables(mod, nom):
    src = (RACINE / mod).read_text(encoding="utf-8")
    assert "forge_hub_client" in src and "HubClient" in src
    assert "jeton_propre_ou_maitre" not in src and "entetes_jeton_propre" not in src
    assert '"%s"' % nom in src


def test_watchdog_inchange():
    src = (RACINE / "app/forge_service_watchdog.py").read_text(encoding="utf-8")
    assert "jeton_propre_ou_maitre" not in src


@pytest.mark.parametrize("nom", ["GOAP", "SELF_PATCHER"])
def test_coffre_vide_repli_env_lancement_online(monkeypatch, caplog, nom):
    """goap_online_launch pose LAFORGE_HUB_TOKEN (maitre) : coffre vide -> l'env sert, DIT, sans valeur ni nom."""
    ENV = "valeur-env-QWE456"
    c = _client(monkeypatch, dict(), nom)
    monkeypatch.setenv("LAFORGE_HUB_TOKEN", ENV)
    with caplog.at_level(logging.DEBUG):
        h = c.entetes_repli_env()
    assert h["Authorization"] == "Bearer " + ENV
    assert "LaForge-Agent-Name" not in h
    assert [r for r in caplog.records if r.levelno == logging.WARNING and "LAFORGE_HUB_TOKEN" in r.getMessage()]
    assert ENV not in caplog.text


def test_repli_env_ignore_si_jeton_propre(monkeypatch):
    c = _client(monkeypatch, dict(FORGE_TOKEN_GOAP=PROPRE), "GOAP")
    monkeypatch.setenv("LAFORGE_HUB_TOKEN", "autre")
    h = c.entetes_repli_env()
    assert h["Authorization"] == "Bearer " + PROPRE and h["LaForge-Agent-Name"] == "GOAP"


def test_repli_env_rien_si_env_vide(monkeypatch):
    c = _client(monkeypatch, dict(), "GOAP")
    monkeypatch.delenv("LAFORGE_HUB_TOKEN", raising=False)
    assert "Authorization" not in c.entetes_repli_env()
