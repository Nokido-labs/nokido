"""NR -- `forge_supervisor_ctl reload --running` rafraichit aussi la definition des services EN MARCHE.

Mesure 29/10 10 h 37 : OLLAMA_IGPU_ENABLE ajoute a services.toml, `reload` puis `restart NokidoOllama` -> Ollama voit
la cle VIDE (« dropping integrated GPU ») : le reload par defaut garde la definition en cache des services en marche
(supervisor.ts : `?force=running` existe, le ctl ne le passait pas). Faux _call, aucun superviseur reel."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import forge_supervisor_ctl as C  # noqa: E402


def _appels(monkeypatch, argv):
    vus = []
    monkeypatch.setattr(C, "_call", lambda path, method="GET": (vus.append((path, method)) or (200, "{}")))
    monkeypatch.setenv("NOKIDO_CTL_DIRECT", "1")
    monkeypatch.setattr(sys, "argv", ["forge_supervisor_ctl.py", *argv])
    try:
        C.main()
    except SystemExit:
        pass
    return vus


def test_reload_running_passe_force_running(monkeypatch):
    """`reload --running` -> POST /supervisor/reload?force=running."""
    assert ("/supervisor/reload?force=running", "POST") in _appels(monkeypatch, ["reload", "--running"])


def test_reload_par_defaut_inchange(monkeypatch):
    """`reload` seul -> POST /supervisor/reload (comportement d'avant)."""
    assert ("/supervisor/reload", "POST") in _appels(monkeypatch, ["reload"])
