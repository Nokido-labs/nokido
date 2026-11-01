# -*- coding: utf-8 -*-
"""NR (29/10) : `sleep`/`stop` verifient l'EFFET (port ferme), pas seulement l'acceptation HTTP.
Mesure : sleep Qdrant « ok » alors que qdrant.exe vivait et que :6333 ecoutait encore.
Faux superviseur + faux sondage de port + temps simule : aucun service reel."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_supervisor_ctl as ctl  # noqa: E402


def _lancer(monkeypatch, capsys, action, etat_svc, port_ouvert):
    monkeypatch.setenv("NOKIDO_CTL_DIRECT", "1")
    horloge = {"t": 0.0}

    def faux_call(path, method="GET"):
        if path == "/supervisor/status":
            return 200, json.dumps({"services": {"Svc": etat_svc}})
        return 200, json.dumps({"ok": True, "action": action})

    def faux_dormir(s):
        horloge["t"] += s

    monkeypatch.setattr(ctl, "_call", faux_call)
    monkeypatch.setattr(ctl, "_port_ouvert", lambda port: port_ouvert(horloge["t"]))
    monkeypatch.setattr(ctl, "_dormir", faux_dormir, raising=False)
    monkeypatch.setattr(ctl, "_maintenant", lambda: horloge["t"], raising=False)
    monkeypatch.setattr(sys, "argv", ["forge_supervisor_ctl.py", action, "Svc"])
    rc = ctl.main()
    out = capsys.readouterr().out
    return rc, json.loads(out.strip().splitlines()[-1]), horloge["t"]


@pytest.mark.parametrize("action", ["sleep", "stop"])
def test_port_ferme_atteint(monkeypatch, capsys, action):
    rc, j, _ = _lancer(monkeypatch, capsys, action, {"status": "sleeping", "port": 6333},
                       lambda t: False)
    assert rc == 0 and j["effet"] == "ATTEINT"
    assert j["demande"]["ok"] is True


@pytest.mark.parametrize("action", ["sleep", "stop"])
def test_port_ouvert_non_atteint(monkeypatch, capsys, action):
    rc, j, t = _lancer(monkeypatch, capsys, action, {"status": "sleeping", "port": 6333},
                       lambda t: True)
    assert rc == 3 and j["effet"] == "NON_ATTEINT"
    assert "6333" in j["preuve"] and "20 s" in j["preuve"]
    assert "wake Svc" in j["preuve"]
    assert 19 <= t <= 21


def test_port_se_ferme_en_cours_de_route(monkeypatch, capsys):
    rc, j, t = _lancer(monkeypatch, capsys, "sleep", {"port": 6333}, lambda t: t < 5)
    assert rc == 0 and j["effet"] == "ATTEINT" and t < 10


def test_sans_port_illisible(monkeypatch, capsys):
    rc, j, _ = _lancer(monkeypatch, capsys, "sleep", {"status": "sleeping"}, lambda t: False)
    assert rc == 4 and j["effet"] == "ILLISIBLE"
    assert "port" in j["preuve"]
