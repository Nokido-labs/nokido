# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `entetes_organe` — En-tetes d'un ORGANE qui appelle le hub : son jeton PROPRE, sinon celui de SERVICES.
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_hub_client.py — Client léger Nokido Hub v17
===================================================
Utilisé par Nokido.py pour déléguer au Hub quand il tourne.

Usage dans Nokido.py :
    from forge_hub_client import hub, HubClient

    # Vérifier si le Hub est disponible
    if hub.alive():
        result = hub.tool("run", {"action": "github", "code": "status"})

    # GitHub Actions
    hub.github("trigger:deploy.yml:alpha")
    hub.github("log")

    # Metrics Hub
    status = hub.metrics()
"""


import json
import logging
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
_env_file = _ROOT / "Nokido.env"
_APP = str(Path(__file__).resolve().parent)
if _APP not in sys.path:
    sys.path.insert(0, _APP)

_log = logging.getLogger(__name__)

# ── REPARATION 2026-08-05 ────────────────────────────────────────────────────
# Ce client existait depuis mars et etait DORMANT : port par defaut 7400 (le hub
# ecoute sur 8766 depuis la v18), aucun en-tete d'identite, et un `except: return
# None` qui rendait la panne indistinguable d'une reponse vide. Ses SIX appelants
# (forge_at_dispatch, forge_hub_handlers x4, forge_services, nokido_core) tapaient
# donc dans le vide sans que rien ne le dise. Symptome jumeau cote daemons :
# 4 730 rejets `no_auth` en 24 h, soit la TOTALITE des 401 du hub, parce que
# forge_organ_pulse et forge_coagulation postaient sur /mcp sans Bearer et
# avalaient l'echec. Une primitive presente et non cablee est une primitive qui
# ment sur l'etat du systeme.
_PORT = 8766
_TOKEN = ""
_ENV_TOKENS: dict = {}
if _env_file.exists():
    try:
        # Tenter d'utiliser forge_hub_storage.safe_read (plus robuste sur Windows)
        from nokido_agent.app.forge_hub_storage import safe_read as _safe_read

        _content = _safe_read(_env_file)
    except ImportError:
        # Fallback : read direct
        try:
            _content = _env_file.read_text(encoding="utf-8")
        except Exception:
            _content = None
    if _content:
        for _l in _content.splitlines():
            _l = _l.strip()
            if not _l or _l.startswith("#") or "=" not in _l:
                continue
            _k, _, _v = _l.partition("=")
            _k, _v = _k.strip(), _v.split("#")[0].strip().strip('"').strip("'")
            if _k.startswith("FORGE_TOKEN_") or _k == "FORGE_MCP_TOKEN":
                _ENV_TOKENS[_k] = _v
            elif _k == "LAFORGE_HUB_PORT" and _v.isdigit():
                _PORT = int(_v)
_PORT = int(os.environ.get("LAFORGE_HUB_PORT", _PORT))
_BASE_URL = "http://127.0.0.1:%d" % _PORT

# Identite par defaut. Un process interne qui ne se nomme pas est compte `no_auth`
# par `_resolve_ring` : c'est ainsi que 44 % du trafic du hub etait anonyme.
# SERVICES (ring 4) est l'identite declaree des daemons dans agent_identities.json.
_AGENT = (os.environ.get("LAFORGE_AGENT") or "SERVICES").strip().upper()


def _resoudre_jeton(agent: str) -> tuple[str, str]:
    """Jeton du coffre pour cette identite, et D'OU il vient. Ordre : jeton propre
    a l'agent -> jeton SERVICES -> jeton maitre. Rend aussi la PROVENANCE, parce
    qu'un appel qui echoue doit pouvoir dire avec quelle clef il a essaye (jamais
    la clef elle-meme)."""
    noms = ["FORGE_TOKEN_%s" % agent, "FORGE_TOKEN_SERVICES", "FORGE_MCP_TOKEN"]
    try:
        from nokido_agent.app.forge_secrets import get_secret  # coffre DPAPI machine -> WCM -> env

        for n in noms:
            v = get_secret(n)
            if v:
                return v, "coffre:%s" % n
    except Exception as e:  # noqa: BLE001
        _log.debug("[hub_client] coffre indisponible (%s), repli Nokido.env",
                   type(e).__name__)
    for n in noms:
        if _ENV_TOKENS.get(n):
            return _ENV_TOKENS[n], "Nokido.env:%s" % n
    return "", "AUCUN"


def entetes_organe(agent: str) -> dict:
    """En-tetes d'un ORGANE qui appelle le hub : son jeton PROPRE, sinon celui de SERVICES.

    JAMAIS le maitre (chantier d'authentification, 2026-09-24) : un organe qui porte le
    maitre devient indiscernable au journal -- c'est l'impersonation qu'on eteint. Le nom
    annonce suit le jeton reellement presente : un organe sans jeton propre parle en
    SERVICES et ne se fait pas passer pour lui-meme (nommer n'est pas prouver).
    Aucun jeton lisible -> seulement le Content-Type, et le DIT au journal : le hub
    rendra 401, visiblement, au lieu d'un appel qu'on croirait authentifie.
    """
    canon = (agent or "").strip().upper()
    h = {"Content-Type": "application/json"}
    try:
        from nokido_agent.app.forge_secrets import get_secret

        for nom in ([canon] if canon else []) + ["SERVICES"]:
            v = get_secret("FORGE_TOKEN_%s" % nom)
            if v:
                h["Authorization"] = "Bearer %s" % v
                h["LaForge-Agent-Name"] = nom
                return h
    except Exception as e:  # noqa: BLE001
        _log.warning("[hub_client] coffre indisponible pour %s (%s) : appel SANS porteur",
                     canon or "?", type(e).__name__)
        return h
    _log.warning("[hub_client] aucun jeton pour %s ni SERVICES : appel SANS porteur (401 attendu)",
                 canon or "?")
    return h


_TOKEN, _TOKEN_SRC = _resoudre_jeton(_AGENT)


class HubClient:
    """
    Client synchrone vers Nokido Hub v17.
    Toutes les méthodes sont non-bloquantes avec timeout court (3s).
    En cas d'échec, retourne None silencieusement — Nokido continue sans Hub.
    """

    def __init__(self, base_url: str = _BASE_URL, token: Optional[str] = None,
                 timeout: float = 5.0, agent: str = _AGENT) -> None:
        """Initialise. `agent` = identite presentee au hub (en-tete canonique
        LaForge-Agent-Name) ; sans elle l'appelant est compte anonyme.

        Le jeton est resolu POUR CETTE IDENTITE, pas une fois pour toutes au
        chargement du module. Defaut mesure le 2026-08-05 dans ce fichier meme :
        `HubClient(agent="ORGAN_PULSE")` presentait l'en-tete ORGAN_PULSE avec le
        jeton de SERVICES -> le plancher anti-spoof du videur rabattait en ring 4 et
        rendait GATE_DENIED. Un jeton qui n'appartient pas a l'identite presentee
        DEGRADE l'identite au lieu de l'etablir (meme piege que TASK_EXECUTOR,
        2026-06-23)."""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.agent = (agent or "SERVICES").strip().upper()
        self._token_explicite = token is not None
        if token is None:
            self.token, self.token_src = _resoudre_jeton(self.agent)
        else:
            self.token, self.token_src = token, "explicite"
        self._src_courante = ""  # derniere provenance DITE (anti-bavardage)
        self._alive = None  # cache ping
        self._derniere_panne = ""
        if not self.token:
            _log.warning(
                "[hub_client] agent=%s SANS JETON (cherche FORGE_TOKEN_%s, "
                "FORGE_TOKEN_SERVICES, FORGE_MCP_TOKEN au coffre puis Nokido.env) | "
                "consequence: chaque appel sera rejete no_auth par le hub et comptera "
                "dans le trafic anonyme | remede: provisionner la clef "
                "(tools/forge_provision_clients.py)", self.agent, self.agent)

    def _jeton_courant(self) -> tuple[str, str]:
        """Jeton a presenter MAINTENANT, et sa provenance.

        Resolu A CHAQUE REQUETE, jamais fige a l'init : un jeton a bail vaut
        1800 s et un daemon vit bien plus longtemps. `jeton_pour` porte son
        propre cache thread-safe avec marge de renouvellement, donc ce chemin
        ne declenche pas une rafale de logins.

        POURQUOI ce detour plutot que le credential statique (2026-09-02) : le
        statique est PERMANENT -- ni expiration, ni revocation. Le jeton a bail
        rend les deux, et la mesure a montre que le ring resolu est IDENTIQUE
        par les deux voies, donc la bascule ne coute aucun privilege.

        Le durcissement est le DEFAUT. L'echappatoire est explicite
        (`LAFORGE_HUB_CLIENT_JETON_COURT=0`) et se lit dans la provenance : un
        repli qui se confond avec un succes est un repli qu'on ne repare jamais.
        """
        if self._token_explicite:
            return self.token, "explicite"
        if os.environ.get("LAFORGE_HUB_CLIENT_JETON_COURT", "1") == "0":
            return self.token, self.token_src + "+desarme"
        try:
            from nokido_agent.app.forge_agent_credential import jeton_pour

            court = jeton_pour(self.agent)
        except Exception as e:  # noqa: BLE001
            return self.token, self.token_src + "+repli:%s" % type(e).__name__
        if court and court != self.token:
            return court, "bail:%s" % self.agent
        # `jeton_pour` retombe lui-meme sur le statique : le dire, sinon un
        # organe non provisionne se lit comme un organe protege.
        return self.token, self.token_src + "+repli_statique"

    def _dire_provenance(self, src: str) -> None:
        """Journalise la provenance au CHANGEMENT seulement.

        Un daemon en boucle noierait le journal ; mais passer d'un bail a un
        repli statique est exactement l'evenement qu'on veut voir.
        """
        if src == self._src_courante:
            return
        ancienne, self._src_courante = self._src_courante, src
        if not ancienne:
            _log.debug("[hub_client] agent=%s credential=%s", self.agent, src)
        elif "repli" in src or "desarme" in src:
            _log.warning(
                "[hub_client] agent=%s credential %s -> %s | consequence: "
                "credential PERMANENT, ni expirable ni revocable | remede: "
                "provisionner FORGE_TOKEN_%s au coffre",
                self.agent, ancienne, src, self.agent)
        else:
            _log.info("[hub_client] agent=%s credential %s -> %s",
                      self.agent, ancienne, src)

    def _req(self, method: str, path: str, body: Optional[dict] = None) -> Optional[Any]:
        """Requete HTTP vers le hub. Rend None en cas d'echec — mais JAMAIS en
        silence : la premiere occurrence d'une panne est journalisee avec sa cause,
        sa consequence et son remede. Les repetitions identiques sont tues (un
        daemon en boucle noierait le journal), la GUERISON est dite aussi."""
        url = self.base_url + path
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("LaForge-Agent-Name", self.agent)  # canonique (RFC 6648)
        _tok, _src = self._jeton_courant()
        self._dire_provenance(_src)
        if _tok:
            req.add_header("Authorization", "Bearer " + _tok)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = json.loads(r.read().decode())
            if self._derniere_panne:
                _log.info("[hub_client] agent=%s hub %s DE NOUVEAU JOIGNABLE",
                          self.agent, self.base_url)
                self._derniere_panne = ""
            return out
        except urllib.error.HTTPError as e:
            panne = "HTTP %s" % e.code
            aide = {
                401: "identite/jeton refuses -- verifier que %s existe au coffre et "
                     "que l'agent est declare dans config/agent_identities.json" % (
                         "FORGE_TOKEN_%s" % self.agent),
                403: "identite reconnue mais RING insuffisant pour cette route",
                404: "route absente sur ce hub -- version ou port errones",
            }.get(e.code, "reponse d'erreur du hub")
            self._journalise(panne, "%s (%s)" % (aide, self.token_src), method, path)
        except urllib.error.URLError as e:
            self._journalise(
                "injoignable", "hub muet sur %s (%s) -- service arrete ou mauvais "
                "port" % (self.base_url, getattr(e, "reason", "?")), method, path)
        except Exception as e:  # noqa: BLE001
            self._journalise("%s" % type(e).__name__, str(e)[:120], method, path)
        return None

    def _journalise(self, panne: str, detail: str, method: str, path: str) -> None:
        """Une panne repetee se dit UNE fois ; son changement se redit."""
        cle = "%s|%s|%s" % (panne, method, path)
        if cle == self._derniere_panne:
            return
        self._derniere_panne = cle
        _log.warning("[hub_client] agent=%s %s %s -> %s | %s | consequence: cet appel "
                     "est PERDU, l'appelant continue sans hub",
                     self.agent, method, path, panne, detail)

    def alive(self) -> bool:
        """Ping rapide — vérifie si le Hub répond."""
        r = self._req("GET", "/health")
        self._alive = r is not None and r.get("status") == "ok"
        return self._alive

    def version(self) -> str:
        """Retourne la version du Hub ou 'unavailable'."""
        r = self._req("GET", "/health")
        return r.get("version", "unavailable") if r else "unavailable"

    def tool(self, name: str, args: dict) -> Optional[str]:
        """
        Appelle un outil MCP sur le Hub.
        Retourne le texte de la réponse ou None si erreur.
        """
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
        r = self._req("POST", "/mcp", body)
        if not r:
            return None
        if "error" in r:
            return "[Hub] Erreur: " + str(r["error"])
        content = r.get("result", {}).get("content", [])
        return content[0]["text"] if content else None

    def notify(self, message: str, to: str = "") -> Optional[str]:
        """Notification inter-agents via le hub (chokepoint unique). Remplace le
        POST maison `{"tool":..., "args":...}` que forge_organ_pulse et
        forge_coagulation envoyaient sans Bearer : ce format n'est PAS du JSON-RPC,
        donc meme authentifie il n'aurait jamais ete servi."""
        args: dict = {"action": "notify", "message": message}
        if to:
            args["to"] = to
        return self.tool("hub", args)

    def github(self, code: str) -> Optional[str]:
        """
        Raccourci GitHub API via Hub.
        code = 'status' | 'log' | 'diff' | 'actions' | 'trigger:<wf>:<ref>'
        """
        r = self._req("POST", "/github", {"code": code})
        return r.get("result") if r else None

    def metrics(self) -> Optional[dict]:
        """Retourne les métriques du Hub."""
        return self._req("GET", "/metrics")

    def query(self, sql: str) -> Optional[Any]:
        """Exécute une requête SQL sur le RAG via Hub."""
        return self.tool("query", {"sql": sql})

    def run_python(self, code: str) -> Optional[str]:
        """Exécute du Python sur le Hub (RING_0 seulement)."""
        return self.tool("run", {"action": "python", "code": code})

    def trigger_action(self, workflow: str, ref: str = "alpha", inputs: Optional[dict] = None) -> Optional[str]:
        """
        Déclenche une GitHub Action via Hub.
        workflow = nom du fichier yml (ex: 'deploy.yml')
        """
        code = "trigger:" + workflow + ":" + ref
        if inputs:
            code += ":" + json.dumps(inputs)
        return self.github(code)

    def status_report(self) -> str:
        """Rapport d'état complet Hub → affiché dans @services."""
        if not self.alive():
            return "[Hub] ❌ Hub v17 non disponible sur " + self.base_url

        m = self.metrics() or {}
        h = self._req("GET", "/health") or {}
        gh = self.github("status") or "?"

        lines = [
            "[Hub] ✅ Nokido Hub " + h.get("version", "?"),
            "  📡 " + h.get("hub_host", "?") + " | Auth: " + h.get("auth", "?"),
            "  🗃  RAG: " + str(m.get("rag_chunks", "?")) + " chunks",
            "  📋 Events: " + str(m.get("event_log", "?")) + " | Queue: " + str(m.get("queue_size", 0)),
            "  🐙 GitHub: " + str(gh).split(chr(10))[0],
        ]
        return chr(10).join(lines)


# Singleton global — importé par Nokido.py
hub = HubClient()
