# -*- coding: utf-8 -*-
"""NR - le Funnel des pairs cloud est GARDE par le tray (owner 2026-11-03).

Mesure du 3/11 04:17 : claude.ai Nokido en 502 (« HTTP 502 at https://desktop-...ts.net »).
Le pont NokidoPairMCP (8793) etait sain, OAuth compris ; la requete n'arrivait jamais au
pont : Tailscale n'etait pas lance, le Funnel n'existait plus, et RIEN ne le surveillait
(seuls des ordres manuels tailscale-statut / funnel-ouvrir). Owner : « une prothese qui
devrait etre auto geree a la demande ».

Contrats :
  1. `verdict_funnel` (pur) : demande absente -> rien ; CLI injoignable -> lancer la GUI ;
     Stopped -> tailscale up ; NeedsLogin -> geste owner (jamais d'action) ; Running sans
     443 -> 8793 -> ouvrir ; Running avec 443 -> 8793 -> ok.
  2. La DEMANDE est lue dans services.toml : NokidoPairMCP non desactive.
  3. `--action funnel-garder` RELIT l'etat apres son geste : une commande acceptee n'est
     pas un etat atteint (rc 1 si l'etat n'est pas atteint, jamais un faux 0).
  4. Le tray ne lance le gardien qu'a sa cadence, sans console, avec l'action reelle.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

L = pytest.importorskip("nokido_launcher")

FUNNEL_OK = {"Web": {"h.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8793"}}}},
             "AllowFunnel": {"h.ts.net:443": True}}
FUNNEL_AUTRE_PORT = {"Web": {"h.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}}},
                     "AllowFunnel": {"h.ts.net:443": True}}
FUNNEL_NON_PUBLIC = {"Web": {"h.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8793"}}}},
                     "AllowFunnel": {}}


# -- 1. verdict pur -----------------------------------------------------------------------

@pytest.mark.parametrize("demande, backend, funnel, attendu", [
    (False, None, None, "rien"),
    (False, "Stopped", {}, "rien"),
    (True, None, None, "lancer_gui"),
    (True, "Stopped", {}, "tailscale_up"),
    (True, "NeedsLogin", {}, "geste_owner"),
    (True, "Running", {}, "ouvrir_funnel"),
    (True, "Running", FUNNEL_AUTRE_PORT, "ouvrir_funnel"),
    (True, "Running", FUNNEL_NON_PUBLIC, "ouvrir_funnel"),
    (True, "Running", FUNNEL_OK, "ok"),
    (True, "Starting", {}, "attendre"),
    (True, "NoState", None, "lancer_gui"),
])
def test_verdict_funnel(demande, backend, funnel, attendu):
    assert L.verdict_funnel(demande, backend, funnel) == attendu


def test_nostate_apres_boot_lance_la_gui(monkeypatch, tmp_path):
    """6/11 : apres chaque boot, tailscaled tourne en NoState tant que la GUI n'est pas lancee.
    Le gardien repondait « attendre » a chaque passage : seul un geste de l'owner relevait Tailscale."""
    exe = tmp_path / "tailscale.exe"
    gui = tmp_path / "tailscale-ipn.exe"
    exe.write_text("")
    gui.write_text("")
    lectures = iter([("NoState", None, ""), ("Running", FUNNEL_OK, "")])
    lances = []
    monkeypatch.setattr(L, "TAILSCALE_EXE", exe)
    monkeypatch.setattr(L, "TAILSCALE_GUI", gui)
    monkeypatch.setattr(L, "demande_funnel", lambda *a: True)
    monkeypatch.setattr(L, "_lire_tailscale", lambda: next(lectures))
    monkeypatch.setattr(L, "_journal_gardien", lambda e: None)
    monkeypatch.setattr(L, "_action_tailscale_statut", lambda: None)
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    monkeypatch.setattr(L.subprocess, "Popen", lambda cmd, **k: lances.append(cmd))
    assert L._action_funnel_garder() is True
    assert lances == [[str(gui)]]


def test_un_etat_inconnu_n_est_jamais_ok():
    """UNKNOWN != NO, et jamais rangé du côté sain : un BackendState inattendu attend."""
    assert L.verdict_funnel(True, "EtatInventé", FUNNEL_OK) == "attendre"


# -- 2. demande lue dans services.toml ----------------------------------------------------

def test_demande_lue_dans_services_toml():
    actif = '[[service]]\nname = "NokidoPairMCP"\nport = 8793\ndisabled = false\n'
    coupe = '[[service]]\nname = "NokidoPairMCP"\nport = 8793\ndisabled = true\n'
    autre = '[[service]]\nname = "NokidoAutre"\ndisabled = false\n'
    assert L.demande_funnel(actif) is True
    assert L.demande_funnel(coupe) is False
    assert L.demande_funnel(autre) is False
    assert L.demande_funnel("ceci n'est pas du toml [[[") is False


def test_demande_reelle_du_depot_est_lisible():
    """Le vrai services.toml se lit sans exception (bool), quel que soit l'etat declare."""
    assert isinstance(L.demande_funnel(), bool)


# -- 3. l'action relit l'etat ---------------------------------------------------------------

class _FauxTailscale:
    """Rejoue status/funnel status ; `funnel --bg` fait passer le Funnel a FUNNEL_OK si `marche`."""

    def __init__(self, backend="Running", funnel=None, marche=True):
        import json as _j
        self._j, self.backend, self.funnel, self.marche, self.appels = _j, backend, funnel or {}, marche, []

    def __call__(self, *args):
        self.appels.append(args)
        if args[:2] == ("status", "--json"):
            return subprocess.CompletedProcess(args, 0, self._j.dumps({"BackendState": self.backend}), "")
        if args[:3] == ("funnel", "status", "--json"):
            return subprocess.CompletedProcess(args, 0, self._j.dumps(self.funnel), "")
        if args[:2] == ("funnel", "--bg"):
            if self.marche:
                self.funnel = FUNNEL_OK
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def bac(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "ETAT_TAILSCALE", tmp_path / "tailscale_etat.json")
    monkeypatch.setattr(L, "JOURNAL_GARDIEN_FUNNEL", tmp_path / "gardien_funnel.jsonl")
    monkeypatch.setattr(L, "demande_funnel", lambda *a, **k: True)
    exe = tmp_path / "tailscale.exe"
    exe.write_text("")
    monkeypatch.setattr(L, "TAILSCALE_EXE", exe)
    monkeypatch.setattr(L, "time", type("T", (), {"sleep": staticmethod(lambda s: None),
                                                  "strftime": staticmethod(__import__("time").strftime),
                                                  "time": staticmethod(__import__("time").time)}))
    return tmp_path


def test_funnel_absent_est_rouvert_puis_relu(monkeypatch, bac):
    faux = _FauxTailscale(funnel={})
    monkeypatch.setattr(L, "_tailscale", faux)
    assert L._cli("funnel-garder") == 0
    assert ("funnel", "--bg", "8793") in faux.appels
    # relecture APRES le geste : le dernier appel funnel status suit le --bg
    idx_bg = faux.appels.index(("funnel", "--bg", "8793"))
    assert any(a[:3] == ("funnel", "status", "--json") for a in faux.appels[idx_bg + 1:])
    assert "ouvrir_funnel" in (bac / "gardien_funnel.jsonl").read_text(encoding="utf-8")


def test_geste_accepte_mais_etat_non_atteint_rend_1(monkeypatch, bac):
    faux = _FauxTailscale(funnel={}, marche=False)
    monkeypatch.setattr(L, "_tailscale", faux)
    assert L._cli("funnel-garder") == 1


def test_funnel_sain_ne_touche_a_rien(monkeypatch, bac):
    faux = _FauxTailscale(funnel=FUNNEL_OK)
    monkeypatch.setattr(L, "_tailscale", faux)
    assert L._cli("funnel-garder") == 0
    assert not any(a[:2] == ("funnel", "--bg") or a[:1] == ("up",) for a in faux.appels)


def test_needs_login_ne_fait_aucun_geste(monkeypatch, bac):
    faux = _FauxTailscale(backend="NeedsLogin")
    monkeypatch.setattr(L, "_tailscale", faux)
    assert L._cli("funnel-garder") == 1
    assert all(a[:2] in (("status", "--json"), ("funnel", "status")) for a in faux.appels)


def test_sans_demande_aucun_appel_tailscale(monkeypatch, bac):
    monkeypatch.setattr(L, "demande_funnel", lambda *a, **k: False)
    faux = _FauxTailscale(funnel={})
    monkeypatch.setattr(L, "_tailscale", faux)
    assert L._cli("funnel-garder") == 0
    assert faux.appels == []


def test_funnel_garder_n_est_pas_reserve_au_bureau():
    assert "funnel-garder" in L.ACTIONS
    assert "funnel-garder" not in L.ACTIONS_BUREAU_SEULEMENT


# -- 4. cadence du tray -------------------------------------------------------------------

def test_le_tray_garde_le_funnel_a_sa_cadence(monkeypatch):
    # Sans pystray, le tray fait sys.exit(1) a l'import : importorskip n'attrape pas SystemExit.
    try:
        import nokido_tray as T
    except (ImportError, SystemExit):
        pytest.skip("tray non importable ici (pystray absent)")
    lances = []
    monkeypatch.setattr(T.subprocess, "Popen", lambda cmd, **kw: lances.append((cmd, kw)))
    monkeypatch.setitem(T._state, "funnel_garde_ts", 0.0)
    assert T._garder_funnel(maintenant=10_000.0) is True
    assert T._garder_funnel(maintenant=10_000.0 + T.GARDE_FUNNEL_SEC - 1) is False
    assert T._garder_funnel(maintenant=10_000.0 + T.GARDE_FUNNEL_SEC + 1) is True
    assert len(lances) == 2
    cmd, kw = lances[0]
    assert cmd[-2:] == ["--action", "funnel-garder"] and str(T.LANCEUR) in cmd
    assert kw.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW
