"""NR -- le reveil de SearXNG des veilles passe par la capacite SERVIE (forge_ensure_service), pas le seul superviseur.

Mesure 10/11 soir (Gordon, job_5f24411eeb1e) : `searxng-laforge` Exited (0) depuis 42 min alors que la veille WSL 3
(wj_6b32d6917d) et l'organe de recherche avaient appele `_ensure_searxng` : celui-ci demandait au superviseur de
lancer le PROCESSUS forge_searxng_keeper (NokidoSearxng, on-demand), qui ne redemarre pas le conteneur. La voie
qui l'a redemarre a 15 h 3x est `forge_ensure_service.ensure("searxng", "running")` (_ensure_docker puis
forge_searxng_keeper._ensure_running). Contrats :
  1. SearXNG muet -> ensure("searxng", "running") est appele ;
  2. s'il reussit, le superviseur n'est pas sollicite et le reveil aboutit des que :8080 repond.
"""
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_watch_agent as W  # noqa: E402
from nokido_agent.tools import forge_docker_keeper as K  # noqa: E402
from nokido_agent.tools import forge_ensure_service as ES  # noqa: E402
from nokido_agent.tools import forge_supervisor_ctl as SC  # noqa: E402


class _Rep:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_reveil_par_ensure_service(monkeypatch):
    etat = {"debout": False, "ensure": [], "superviseur": []}

    def _urlopen(req, timeout=None):
        if not etat["debout"]:
            raise ConnectionResetError(10054, "reset")
        return _Rep()

    def _ensure(service, state):
        etat["ensure"].append((service, state))
        etat["debout"] = True
        return {"service": service, "desired": state, "success": True, "detail": "ok"}

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(K, "claim_docker", lambda o: None)
    monkeypatch.setattr(K, "release_claim", lambda o, **k: {})
    monkeypatch.setattr(K, "ensure_docker", lambda *a, **k: None)
    monkeypatch.setattr(ES, "ensure", _ensure)
    monkeypatch.setattr(SC, "_call", lambda *a, **k: etat["superviseur"].append(a) or (200, {}))
    monkeypatch.setattr(W, "_engine_record", lambda *a, **k: None)
    monkeypatch.setattr(W, "_SEARX_LAST_ENSURE_TS", 0.0)

    assert W._ensure_searxng(wait_s=5) is True
    assert etat["ensure"] == [("searxng", "running")]
    assert etat["superviseur"] == []
