"""
tests/nr/test_bench_http_nr.py - NR d'EFFET de tools/forge_bench_http.py.

Le module est ne de la factorisation des 6 clones `_http_post` (cliquet
duplication rompu le 2026-08-21). On mesure ce qui ARRIVE sur le fil (serveur
local ephemere), pas un import : methode, Content-Type, User-Agent anti-403
Cloudflare, body integral, merge des headers, reponse JSON rendue - et la
DELEGATION vivante depuis un runner (forge_humaneval_runner._http_post).
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from forge_bench_http import USER_AGENT, http_post  # noqa: E402


class _Capture(BaseHTTPRequestHandler):
    recu: dict = {}

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        _Capture.recu = {
            "path": self.path,
            "user_agent": self.headers.get("User-Agent"),
            "content_type": self.headers.get("Content-Type"),
            "x_custom": self.headers.get("X-Custom"),
            "body": json.loads(self.rfile.read(n) or b"{}"),
        }
        rep = json.dumps({"echo": True, "vu": _Capture.recu["body"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(rep)))
        self.end_headers()
        self.wfile.write(rep)

    def log_message(self, *a):  # silence
        pass


@pytest.fixture
def serveur():
    srv = HTTPServer(("127.0.0.1", 0), _Capture)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _Capture.recu = {}
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


class TestEffetSurLeFil:
    def test_post_json_complet(self, serveur):
        corps = {"model": "x", "messages": [{"role": "user", "content": "hé"}]}
        rep = http_post(serveur + "/v1/chat", corps, timeout=10)
        assert _Capture.recu["body"] == corps, "le body recu differe du body envoye"
        assert _Capture.recu["content_type"] == "application/json"
        assert rep == {"echo": True, "vu": corps}, "la reponse JSON n'est pas rendue parsee"

    def test_user_agent_anti_403(self, serveur):
        http_post(serveur + "/", {"a": 1}, timeout=10)
        assert _Capture.recu["user_agent"] == USER_AGENT, (
            "sans User-Agent explicite, Cloudflare rend 403 code 1010 (mesure 21/08)")

    def test_headers_custom_merges_et_prioritaires(self, serveur):
        http_post(serveur + "/", {"a": 1},
                  headers={"X-Custom": "oui", "User-Agent": "special/2.0"}, timeout=10)
        assert _Capture.recu["x_custom"] == "oui"
        assert _Capture.recu["user_agent"] == "special/2.0", (
            "un User-Agent fourni par l'appelant doit primer sur le defaut")


class TestDelegationVivante:
    def test_runner_humaneval_delegue(self, serveur):
        """La delegation du runner passe par la source unique : l'UA commun
        arrive sur le fil (preuve d'effet, pas d'import)."""
        import forge_humaneval_runner as R
        R._http_post(serveur + "/", {"via": "runner"}, timeout=10)
        assert _Capture.recu["body"] == {"via": "runner"}
        assert _Capture.recu["user_agent"] == USER_AGENT
