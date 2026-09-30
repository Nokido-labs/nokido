"""NR -- 2b-5 : forge_supervisor_ctl hors SYSTEM passe par le hub (decision owner 2026-09-28).

Mesure (journal de recensement) : `forge_supervisor_ctl`, lance sous un compte bac a
sable (`run`), lisait le jeton superviseur -- et le lisait EN DIRECT au coffre machine
(`vault_get`), sans voir le coffre reserve : prealable de la fermeture 2b-6.

Ce que ce NR verrouille :
  - le jeton superviseur se lit au GUICHET (`get_secret`), plus par `vault_get` ;
  - hors SYSTEM, une mutation (start/ensure/stop/restart) passe par l'outil gouverne du
    hub `nokido_ensure_service`, sans appel direct au superviseur ;
  - hub injoignable ou refus EXPLICITE -> appel direct en TRANSITION, et c'est dit ;
  - une autre reponse du hub (meme `success:false`, deja vu mentir) est rapportee SANS
    repli : jamais deux redemarrages pour un ;
  - sous SYSTEM, et pour `status` (lecture non gardee), appel direct comme avant.
"""
import importlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JETON_SUP = "jeton-superviseur-nr-2b5-" + "s" * 24


def _ctl():
    spec = importlib.util.spec_from_file_location(
        "forge_supervisor_ctl_nr_2b5", ROOT / "tools" / "forge_supervisor_ctl.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FauxHub:
    reponse = '{"success": true}'
    appels = []

    def __init__(self, *a, **kw):
        self.agent = kw.get("agent")

    def tool(self, name, args):
        _FauxHub.appels.append((name, dict(args)))
        return _FauxHub.reponse


@pytest.fixture
def ctl(monkeypatch):
    mod = _ctl()
    hc = importlib.import_module("nokido_agent.app.forge_hub_client")
    monkeypatch.setattr(hc, "HubClient", _FauxHub)
    _FauxHub.appels = []
    _FauxHub.reponse = '{"success": true}'
    directs = []
    monkeypatch.setattr(mod, "_call", lambda path, method="GET": (directs.append((method, path)) or (200, "ok")))
    mod._directs_nr = directs
    return mod


def test_le_jeton_superviseur_se_lit_au_guichet(monkeypatch):
    mod = _ctl()
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")
    directs = []
    monkeypatch.setattr(mv, "vault_get", lambda *a, **kw: directs.append(1))
    monkeypatch.setattr(fs, "get_secret",
                        lambda k, required=False: JETON_SUP if k == "LAFORGE_SUPERVISOR_TOKEN" else None)
    ok = mod._token() == JETON_SUP
    assert ok, "jeton superviseur lu hors guichet"
    assert not directs, "vault_get direct : le coffre reserve n'est jamais vu"


@pytest.mark.parametrize("action, etat", [("start", "running"), ("ensure", "running"),
                                          ("stop", "stopped"), ("restart", "restarted")])
def test_hors_system_une_mutation_passe_par_le_hub(ctl, monkeypatch, action, etat):
    monkeypatch.setattr(ctl, "_sous_system", lambda: False)
    monkeypatch.setattr("sys.argv", ["forge_supervisor_ctl.py", action, "NokidoNR"])
    assert ctl.main() == 0
    assert _FauxHub.appels == [("nokido_ensure_service", {"service": "NokidoNR", "desired_state": etat})]
    assert not ctl._directs_nr, "appel direct au superviseur alors que le hub a repondu"


def test_hub_injoignable_transition_directe_dite(ctl, monkeypatch, capsys):
    monkeypatch.setattr(ctl, "_sous_system", lambda: False)
    _FauxHub.reponse = None
    monkeypatch.setattr("sys.argv", ["forge_supervisor_ctl.py", "stop", "NokidoNR"])
    assert ctl.main() == 0
    assert ctl._directs_nr == [("POST", "/supervisor/service/stop/NokidoNR")]
    assert "TRANSITION" in capsys.readouterr().out


def test_refus_explicite_du_hub_transition_directe(ctl, monkeypatch):
    monkeypatch.setattr(ctl, "_sous_system", lambda: False)
    _FauxHub.reponse = "GATE_DENIED tool=nokido_ensure_service ring 4"
    monkeypatch.setattr("sys.argv", ["forge_supervisor_ctl.py", "start", "NokidoNR"])
    ctl.main()
    assert ctl._directs_nr == [("POST", "/supervisor/service/start/NokidoNR")]


def test_reponse_ambigue_du_hub_rapportee_sans_repli(ctl, monkeypatch):
    monkeypatch.setattr(ctl, "_sous_system", lambda: False)
    _FauxHub.reponse = '{"success": false, "detail": {"out": "HTTP 200"}}'
    monkeypatch.setattr("sys.argv", ["forge_supervisor_ctl.py", "restart", "NokidoNR"])
    ctl.main()
    assert not ctl._directs_nr, "repli direct apres une reponse du hub : double redemarrage"


def test_sous_system_et_status_restent_directs(ctl, monkeypatch):
    monkeypatch.setattr(ctl, "_sous_system", lambda: True)
    monkeypatch.setattr("sys.argv", ["forge_supervisor_ctl.py", "stop", "NokidoNR"])
    ctl.main()
    monkeypatch.setattr(ctl, "_sous_system", lambda: False)
    monkeypatch.setattr("sys.argv", ["forge_supervisor_ctl.py", "status"])
    ctl.main()
    assert ctl._directs_nr == [("POST", "/supervisor/service/stop/NokidoNR"),
                               ("GET", "/supervisor/status")]
    assert not _FauxHub.appels
