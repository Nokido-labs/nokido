"""
tests/nr/test_probe_service_nr.py - NR d'EFFET de probe_service (sonde tuiles).

Doctrine live-only phase 3 : quand une tuile declare un `healthcheck`, l'etat
vient d'une sonde HTTP MESUREE - live (2xx sous le seuil), degraded (2xx lent),
error (4xx/5xx), offline (injoignable dans le budget). Sans healthcheck :
TCP seulement (live/offline) ; cible NON SONDABLE -> unknown (2026-09-17). `via` dit COMMENT l'etat a ete mesure.
Le budget de sonde est la definition operationnelle du vivant : un service qui
repond au-dela est indiscernable d'un mort, et la sonde le dit offline.
"""
from __future__ import annotations

import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.web_hub.dashboard_html import probe_service  # noqa: E402


# Le client de `/lent` ABANDONNE volontairement : c'est le sujet meme du test
# `test_2xx_lent_est_degraded` (0,30 s de reponse contre un budget de 100 ms). Sa
# deconnexion est donc le resultat ATTENDU, pas un incident serveur. Laissee libre,
# elle remonte dans le thread du serveur, ou pytest la promeut en exception non
# rattrapee -- et la suite entiere sort en erreur SANS le moindre test en echec, donc
# sans resume exploitable (mesure 2026-08-25 : deux runs CI rouges d'affilee, 67 375
# lignes de log, zero ligne `FAILED`). On ne fait taire QUE la perte de connexion :
# toute autre exception doit continuer de remonter.
_CLIENT_PARTI = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)


class _Sante(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/lent":
            time.sleep(0.30)
        try:
            if self.path == "/casse":
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"boom")
                return
            rep = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(rep)))
            self.end_headers()
            self.wfile.write(rep)
        except _CLIENT_PARTI:  # muet-ok : abandon du client = resultat attendu
            return

    def log_message(self, *a):
        pass


class _Serveur(HTTPServer):
    """Deuxieme filet : la perte de connexion peut aussi survenir hors de `do_GET`
    (ecriture des en-tetes, fermeture). `handle_error` la journalise par defaut et
    la laisse remonter comme exception de thread."""

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], _CLIENT_PARTI):
            return  # muet-ok : cf _CLIENT_PARTI
        super().handle_error(request, client_address)


@pytest.fixture
def serveur():
    srv = _Serveur(("127.0.0.1", 0), _Sante)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _cfg(port: int, hc: str | None) -> dict:
    c = {"target": f"http://127.0.0.1:{port}"}
    if hc:
        c["healthcheck"] = hc
    return c


class TestSondeHttp:
    def test_2xx_rapide_est_live(self, serveur):
        v = probe_service(_cfg(serveur, "/sante"))
        assert v["state"] == "live", v
        assert v["via"] == "http" and v["checked"] is True
        assert isinstance(v["probe_ms"], float)

    def test_2xx_lent_est_degraded(self, serveur):
        v = probe_service(_cfg(serveur, "/lent"), slow_ms=100.0)
        assert v["state"] == "degraded", v
        assert v["via"] == "http" and v["probe_ms"] > 100.0

    def test_5xx_est_error(self, serveur):
        v = probe_service(_cfg(serveur, "/casse"))
        assert v["state"] == "error", v
        assert v["via"] == "http"
        assert "500" in str(v.get("reason", "")), "la raison doit porter le code HTTP"

    def test_port_ferme_est_offline(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port_libre = s.getsockname()[1]
        s.close()
        v = probe_service(_cfg(port_libre, "/sante"))
        assert v["state"] == "offline", v

    def test_hors_budget_est_offline(self, serveur):
        """Au-dela du budget de sonde, indiscernable d'un mort : offline."""
        v = probe_service(_cfg(serveur, "/lent"), http_timeout=0.05)
        assert v["state"] == "offline", v


class TestSondeTcpSansHealthcheck:
    def test_tcp_live_via_tcp(self, serveur):
        v = probe_service(_cfg(serveur, None))
        assert v["state"] == "live" and v["via"] == "tcp" and v["checked"] is True

    def test_sans_port_local_est_unknown(self):
        """REVOQUE le 2026-09-17 (autorisation owner) ce que ce test affirmait
        sous le nom `..._presume` : `checked=False` rendait `live`, c'est-a-dire
        qu'une cible non sondable etait PRESUMEE saine. Mesure du jour : 12 des
        18 tuiles de SERVICES passaient par ce chemin, donc annoncaient une
        sante que personne n'avait verifiee. Le nom disait l'intention ; c'est
        l'intention qui etait fausse, pas son implementation.
        Contrat depuis : trois etats et jamais deux -- PAS MESURE -> unknown.
        Garde dedie : `test_probe_service_trois_etats_nr`."""
        v = probe_service({"target": "/vitals"})
        assert v["state"] == "unknown" and v["checked"] is False and v["via"] is None
