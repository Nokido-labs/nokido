# -*- coding: utf-8 -*-
"""Relais AGY (AGY CLI, ex-gemini CLI) dans la SESSION OWNER -- owner 4/11 : « il faudrait pourtant » que les jobs
puissent generer avec AGY.

Mesure job_c21ccd6e8336 : le compte des jobs (LaForgeSbxOnline) n'atteint pas %USERPROFILE% (WinError 5) ; via le
hub, agy rend « authentication failed or timed out » : son OAuth est lie a la session interactive, comme l'assistant
d'identifiants de Docker. Seul ce qui tourne `runAs = "interactive"` (l'executeur AGY) l'authentifie.

Ce relais tourne dans la session owner (service NokidoAgyRelay, a la demande) et ecoute 127.0.0.1:8770 :
  POST /v1/ask {"prompt", "system_prompt"} -> {"response"} | {"error"}   ;   GET /health
GeminiCLI (app/forge_agent_proxy.py) le tente DEJA en premier (_demander_relais) : aucun appelant ne change.
Garde-fous : boucle locale seulement ; prompt <= 30 000 car. (limite argv d'agy -- au-dela : un pointeur) ; appels
SERIALISES ; chaque appel journalise (logs/agy_relay.jsonl, tailles et durees, jamais le contenu) ; arret SEUL apres
15 min sans demande (on rend ce qu'on reveille). Le relais ne se rappelle pas lui-meme (LAFORGE_AGY_RELAY_INTERNE).
NR tests/nr/test_agy_relais_session_nr.py."""
__FORGE_COLOR__ = "metabolisme/agy : relais question-reponse vers AGY CLI dans la session interactive owner"

import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE.parent), str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.append(_p)

PORT = int(os.environ.get("LAFORGE_AGY_RELAY_PORT", "8770"))
PROMPT_MAX = 30000
INACTIVITE_S = float(os.environ.get("LAFORGE_AGY_RELAY_INACTIVITE_S", "900"))
from nokido_agent.app.forge_db_path import racine_donnees  # noqa: E402

JOURNAL = racine_donnees() / "logs" / "agy_relay.jsonl"
log = logging.getLogger("forge.agy_relay")
_VERROU = threading.Lock()
_etat = {"dernier": time.time(), "appels": 0}


def adresse_autorisee(ip: str) -> bool:
    return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def inactif(dernier: float, maintenant: float, limite_s: float = INACTIVITE_S) -> bool:
    return (maintenant - dernier) >= limite_s


def traiter(corps: dict, demander) -> dict:
    """Valide la demande puis delegue a `demander(prompt, system_prompt)` ; toute erreur est DITE, jamais avalee."""
    prompt = str((corps or {}).get("prompt") or "")
    if not prompt.strip():
        return {"error": "prompt vide"}
    if len(prompt) > PROMPT_MAX:
        return {"error": "prompt de %d car. > %d (limite argv d'agy) : envoyer un pointeur fichier:ligne"
                         % (len(prompt), PROMPT_MAX)}
    try:
        return {"response": demander(prompt, (corps or {}).get("system_prompt"))}
    except Exception as e:  # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:300])}


def _demander_agy(prompt: str, system_prompt) -> str:
    os.environ["LAFORGE_AGY_RELAY_INTERNE"] = "1"   # GeminiCLI ne rappelle pas ce relais : il lance agy ici
    import asyncio

    from nokido_agent.app.forge_agent_proxy import GeminiCLI
    return asyncio.run(GeminiCLI().ask(prompt, [], system_prompt, 4000, 1500)) or ""


def _journaliser(entree: dict) -> None:
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("journal du relais non ecrit (%s)", type(e).__name__)


class _Gestion(BaseHTTPRequestHandler):
    def _repondre(self, code: int, corps: dict) -> None:
        from forge_utils import repondre_json

        repondre_json(self, code, corps)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._repondre(200, {"ok": True, "appels": _etat["appels"]})
        return self._repondre(404, {"error": "inconnu"})

    def do_POST(self):  # noqa: N802
        if not adresse_autorisee(self.client_address[0]):
            return self._repondre(403, {"error": "boucle locale seulement"})
        if self.path != "/v1/ask":
            return self._repondre(404, {"error": "inconnu"})
        try:
            corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._repondre(400, {"error": "JSON illisible"})
        t0 = time.time()
        with _VERROU:   # un seul agy a la fois (son workdir est partage)
            _etat["dernier"] = time.time()
            rep = traiter(corps, _demander_agy)
            _etat["dernier"], _etat["appels"] = time.time(), _etat["appels"] + 1
        _journaliser({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "prompt_car": len(str(corps.get("prompt") or "")),
                      "duree_s": round(time.time() - t0, 1), "ok": "response" in rep,
                      "reponse_car": len(rep.get("response") or ""), "erreur": rep.get("error")})
        return self._repondre(200, rep)

    def log_message(self, *a):  # silence du serveur HTTP ; le journal JSONL fait foi
        pass


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [agy_relay] %(levelname)s %(message)s")
    serveur = ThreadingHTTPServer(("127.0.0.1", PORT), _Gestion)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    from nokido_agent.app.forge_heartbeat import beat_daemon

    log.info("relais AGY a l'ecoute sur 127.0.0.1:%d (arret apres %.0f s sans demande)", PORT, INACTIVITE_S)
    try:
        while not inactif(_etat["dernier"], time.time()):
            if not beat_daemon("agy_relay", appels=_etat["appels"]):
                log.warning("pouls non ecrit")
            time.sleep(30)
    finally:
        serveur.shutdown()
    log.info("relais AGY arrete : %.0f s sans demande (%d appels servis)", INACTIVITE_S, _etat["appels"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
