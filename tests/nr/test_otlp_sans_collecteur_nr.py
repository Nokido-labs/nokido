# -*- coding: utf-8 -*-
"""NR : export OTLP sans collecteur — DESACTIVE PAR POLITIQUE, pas une panne.

Mesure 2026-10-24 : des jobs exportaient vers http://127.0.0.1:4318 alors que rien
n'y ecoutait (`WinError 10061`, « retrying », puis « Failed to export spans batch »)
dans le .err de CHAQUE job. Or Jaeger (tools/forge_obs_setup.py) est un dashboard
OPTIONNEL, lance a la demande : le collecteur absent est un CHOIX, pas un incident.

Ce NR verifie :
(a) collecteur absent -> AUCUN retry, UNE seule ligne, export desactive pour le processus ;
(b) collecteur present (faux serveur local) -> l'export est TENTE (POST /v1/traces) ;
(c) le bilan du guetteur, sur un .err qui ne porte que le bruit OTLP et rc=0, ne dit pas ECHEC ;
(d) un vrai Traceback avec rc=1 reste ECHEC, avec son motif.

Pur : sockets locaux ephemeres, aucun service, aucun reseau externe.
"""
from __future__ import annotations

import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_otel_export as OTEL  # noqa: E402  -- import DUR : absent = rouge
import forge_job_watch_cli as W  # noqa: E402

_BRUIT_OTLP = """Transient error HTTPConnectionPool(host='127.0.0.1', port=4318): Max retries exceeded with url: /v1/traces (Caused by NewConnectionError("HTTPConnection(host='127.0.0.1', port=4318): Failed to establish a new connection: [WinError 10061] Aucune connexion n'a pu etre etablie")) encountered while exporting spans batch, retrying in 1.00s.
Failed to export spans batch due to timeout, max retries or shutdown.
Traceback (most recent call last):
  File "site-packages/opentelemetry/exporter/otlp/proto/http/trace_exporter/__init__.py", line 42, in export
    resp = self._session.post(url, data=request_data, headers=headers, timeout=self._timeout)
ConnectionRefusedError: [WinError 10061] Aucune connexion n'a pu etre etablie"""


def _reset():
    OTEL._tracer = None
    OTEL._disabled_reason = None


def test_a_collecteur_absent_une_ligne_sans_retry(monkeypatch, caplog):
    _reset()
    tentatives = []

    def _refuse(adresse, timeout=None):
        tentatives.append((adresse, timeout))
        raise ConnectionRefusedError(10061, "connexion refusee")

    monkeypatch.setattr(OTEL.socket, "create_connection", _refuse)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:59999")
    with caplog.at_level(logging.INFO, logger="forge_otel_export"):
        for _ in range(3):
            OTEL.export_span("depuis_test", "abc", duration_ms=1)
    assert len(tentatives) == 1, "la sonde doit tourner UNE fois par processus, pas a chaque export"
    lignes = [r.getMessage() for r in caplog.records if "collecteur OTLP absent" in r.getMessage()]
    assert len(lignes) == 1, "UNE ligne d'information, pas une par export"
    assert lignes[0] == ("collecteur OTLP absent : export désactivé, lancer Jaeger "
                         "à la demande via tools/forge_obs_setup.py")
    assert not [r for r in caplog.records if "Failed to export" in r.getMessage()]
    st = OTEL.status()
    assert st["active"] is False
    assert "absent" in (st["disabled_reason"] or "")


def test_b_collecteur_present_export_tente(monkeypatch):
    _reset()
    recus = []

    class _H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 -- contrat BaseHTTPRequestHandler
            n = int(self.headers.get("Content-Length") or 0)
            recus.append((self.path, self.rfile.read(n)))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    # Etat dont depend le test, pose ici (la CI peut desactiver l'export / forcer un proxy).
    for var in ("OTEL_SDK_DISABLED", "OTEL_TRACES_EXPORTER", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "OTEL_EXPORTER_OTLP_PROTOCOL", "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    # set_tracer_provider n'est honore qu'UNE fois par processus : repartir d'un etat vierge.
    from opentelemetry import trace as _tr
    monkeypatch.setattr(_tr, "_TRACER_PROVIDER", None, raising=False)
    monkeypatch.setattr(_tr._TRACER_PROVIDER_SET_ONCE, "_done", False, raising=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    fil = threading.Thread(target=srv.serve_forever, daemon=True)
    fil.start()
    prov = None
    try:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT",
                           "http://127.0.0.1:%d" % srv.server_address[1])
        OTEL.export_span("depuis_test", "abcdef0123456789abcdef0123456789", duration_ms=2)
        from opentelemetry import trace

        prov = trace.get_tracer_provider()
        prov.force_flush(timeout_millis=3000)
        assert OTEL.status()["active"] is True
        assert [p for p, _ in recus] == ["/v1/traces"], "collecteur present = export TENTE"
    finally:
        srv.shutdown()
        srv.server_close()
        try:
            if prov is not None:
                prov.shutdown()
        except Exception:  # noqa: BLE001 -- nettoyage de test
            pass
        _reset()


def test_c_bruit_otlp_rc0_n_est_pas_un_echec():
    b = W.lire_bilan(_BRUIT_OTLP, "0")
    assert b["etat"] != "ECHEC", "le bruit de l'exportateur n'est pas un verdict"
    assert "ConnectionRefusedError" not in b.get("motif", "")


def test_c2_fermeture_httpx_rc0_n_est_pas_un_echec():
    texte = """Task exception was never retrieved
future: <Task finished name='Task-18' coro=<AsyncClient.aclose() done> exception=RuntimeError('Event loop is closed')>
Traceback (most recent call last):
  File "site-packages/httpx/_client.py", line 1985, in aclose
    await self._transport.aclose()
  File "asyncio/base_events.py", line 550, in _check_closed
    raise RuntimeError('Event loop is closed')
RuntimeError: Event loop is closed"""
    b = W.lire_bilan(texte, "0")
    assert b["etat"] != "ECHEC"


def test_d_vrai_traceback_rc1_reste_echec():
    texte = ('Traceback (most recent call last):\n'
             '  File "app/forge_x.py", line 3, in main\n'
             '    raise ValueError("boom")\n'
             'ValueError: boom')
    b = W.lire_bilan(texte, "1")
    assert b["etat"] == "ECHEC"
    assert "ValueError: boom" in b["motif"]
