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


def _echange_arme() -> bool:
    """INTERRUPTEUR GLOBAL de la voie d'echange cote client (30/10) : `sandbox/echange_jeton_job.switch` present.
    Le hub n'accepte le jeton echange en DPoP qu'apres SON redemarrage ; armer le client avant ferait echouer des
    appels qui marchaient (l'ancien hub ne connait que Bearer). Pose par l'agent APRES le redemarrage du hub."""
    try:
        return (Path(__file__).resolve().parents[1] / "sandbox" / "echange_jeton_job.switch").exists()
    except Exception:  # noqa: BLE001 -- muet-ok : illisible = desarme, comportement d'avant
        return False


# 30/10 (mesure reelle, journal du coffre) : resolu au CHARGEMENT, ce jeton faisait lire FORGE_TOKEN_SERVICES a tout job
# qui importe ce client ; aucun consommateur ne lit _TOKEN hors de ce module. En voie d'echange : pas de lecture.
def _identite_injectee(env=None) -> str:
    """Identite pour laquelle le LANCEUR a injecte un jeton court ('' sinon). NOKIDO_IDENTITE reste dans l'environnement ;
    NOKIDO_JETON_COURT en est retire a la premiere lecture par forge_agent_credential (qui le garde en memoire)."""
    env = os.environ if env is None else env
    ident = str(env.get("NOKIDO_IDENTITE") or "").strip().upper()
    if not ident:
        return ""
    if env.get("NOKIDO_JETON_COURT"):
        return ident
    try:
        from nokido_agent.app import forge_agent_credential as _ac
        return ident if ident in getattr(_ac, "_INJECTES", {}) else ""
    except Exception:  # noqa: BLE001 - muet-ok : module illisible = pas d'injection prouvee, chemin d'avant
        return ""


def _resolution_au_chargement(env=None) -> tuple:
    """Jeton du module au CHARGEMENT. 31/10 (COF-1, NokidoRSSWatcher) : un service a qui le lanceur a injecte un jeton
    court ne lit plus le coffre a l'import (aucun consommateur ne lit _TOKEN hors de ce module)."""
    env = os.environ if env is None else env
    if env.get("NOKIDO_JOB_SUBJECT_TOKEN") and env.get("NOKIDO_JOB_ID") and _echange_arme():
        return "", "echange_job"
    if _identite_injectee(env):
        return "", "injecte_lanceur"
    _ident = str(env.get("NOKIDO_IDENTITE") or "").strip().upper()
    if _ident:
        # 31/10 08:56:32 (NokidoRSSWatcher) : repli sur le coffre ALORS QU'une identite injectee est declaree -- cause
        # ILLISIBLE ce jour-la. On ecrit les raisons, NOMS seulement (jamais une valeur), pour la prochaine occurrence.
        try:
            import sys as _sys
            _copies = sorted(n for n in _sys.modules if n.endswith("forge_agent_credential"))
            _inj = sorted({k for n in _copies for k in getattr(_sys.modules[n], "_INJECTES", {}) or {}})
        except Exception:  # noqa: BLE001 - muet-ok : le diagnostic ne casse jamais le chargement
            _copies, _inj = ["?"], ["?"]
        _log.warning("[hub_client] repli coffre malgre NOKIDO_IDENTITE=%s : jeton_env=%s injectes=%s copies=%s",
                     _ident, bool(env.get("NOKIDO_JETON_COURT")), _inj, _copies)
    return _resoudre_jeton(_AGENT)


_TOKEN, _TOKEN_SRC = _resolution_au_chargement()


def _jeton_sujet() -> str:
    """Jeton de sujet du job par l'accesseur UNIQUE (forge_agent_credential.jeton_sujet_du_job, classe INJECTE 31/10)."""
    try:
        from nokido_agent.app.forge_agent_credential import jeton_sujet_du_job
    except ImportError:  # repli checkout
        from forge_agent_credential import jeton_sujet_du_job
    return jeton_sujet_du_job()


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
        # 30/10 (owner, option B) : porteur d'un jeton de job -> AUCUNE lecture du coffre a la construction ; chaque
        # appel d'outil echange (RFC 8693) pour sa portee exacte et part en DPoP (RFC 9449). Repli tardif DIT.
        # NR tests/nr/test_hub_client_echange_dpop_nr.py.
        self._echange_job = (token is None and bool(_jeton_sujet())
                             and bool(os.environ.get("NOKIDO_JOB_ID")) and _echange_arme())
        self._acces_par_portee: dict = {}
        self._replis_dits: set = set()
        if token is None and self._echange_job:
            self.token, self.token_src = "", "echange_job"
        elif token is None and _identite_injectee() == self.agent:
            # 31/10 (COF-1) : le lanceur a injecte le jeton court de CETTE identite -- `_jeton_courant` le sert par
            # jeton_pour ; aucune lecture du coffre. Injection au nom d'une AUTRE identite : chemin d'avant.
            self.token, self.token_src = "", "injecte_lanceur"
        elif token is None:
            self.token, self.token_src = _resoudre_jeton(self.agent)
        else:
            self.token, self.token_src = token, "explicite"
        self._src_courante = ""  # derniere provenance DITE (anti-bavardage)
        self._alive = None  # cache ping
        self._derniere_panne = ""
        if not self.token and not self._echange_job:
            _log.warning(
                "[hub_client] agent=%s SANS JETON (cherche FORGE_TOKEN_%s, "
                "FORGE_TOKEN_SERVICES, FORGE_MCP_TOKEN au coffre puis Nokido.env) | "
                "consequence: chaque appel sera rejete no_auth par le hub et comptera "
                "dans le trafic anonyme | remede: provisionner la clef "
                "(tools/forge_provision_clients.py)", self.agent, self.agent)
        elif not self._token_explicite and self.token_src.endswith(":FORGE_MCP_TOKEN"):
            # Repli maitre DIT, jamais silencieux (la valeur n'est jamais journalisee).
            _log.warning(
                "repli maitre : FORGE_TOKEN_%s absent (agent=%s presente le jeton maitre "
                "SANS nom d'agent) | remede: provisionner la clef "
                "(tools/forge_provision_clients.py)", self.agent, self.agent)

    def entetes(self, extra: Optional[dict] = None) -> dict:
        """En-tetes hub pour un appelant qui fait ses propres requetes (requests/urllib).

        Meme resolution que `_req` : jeton a bail par defaut (`_jeton_courant`), propre
        d'abord ; en repli maitre, PAS de LaForge-Agent-Name (on ne se fait pas passer
        pour <AGENT> avec le maitre)."""
        h = {"Content-Type": "application/json"}
        if extra:
            h.update(extra)
        tok, src = self._jeton_courant()
        self._dire_provenance(src)
        if "FORGE_MCP_TOKEN" not in src:
            h["LaForge-Agent-Name"] = self.agent
        if tok:
            h["Authorization"] = "Bearer " + tok
        return h

    def entetes_repli_env(self, extra: Optional[dict] = None) -> dict:
        """`entetes()` puis, SI AUCUN jeton n'est trouve (provenance AUCUN), repli sur
        LAFORGE_HUB_TOKEN de l'environnement (lancement online : compte sans acces au
        coffre reserve, le lanceur pose le maitre dans l'env). Dit au journal, sans la
        valeur ; sans LaForge-Agent-Name (jeton maitre : on ne se fait pas passer pour
        <AGENT>). Rien si l'env est vide."""
        h = self.entetes(extra)
        if "Authorization" in h:
            return h
        tok = os.environ.get("LAFORGE_HUB_TOKEN", "")
        if tok:
            h["Authorization"] = "Bearer " + tok
            h.pop("LaForge-Agent-Name", None)
            _log.warning("[hub_client] agent=%s : aucun jeton au coffre, repli sur "
                         "LAFORGE_HUB_TOKEN de l'environnement (valeur non journalisee)",
                         self.agent)
        return h

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
        if getattr(self, "_echange_job", False) and not self.token:
            # repli TARDIF (portee non accordee par l'echange) : le coffre n'est lu qu'ici, et c'est dit plus haut
            self.token, self.token_src = _resoudre_jeton(self.agent)
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

    def _echanger_portee(self, portee: str):
        """(acces, cle, expires_in) par POST /oauth/token -- echange RFC 8693 du jeton de job, preuve DPoP d'une cle
        EPHEMERE (RFC 9449) -- ou None (portee refusee, route muette). Aucune valeur n'est journalisee."""
        import urllib.parse
        try:
            from nokido_agent.app import forge_dpop as _dp
            from nokido_agent.app import forge_token_exchange as _tx
            from nokido_agent.app.forge_coffre_cloisonne import cle_ephemere
        except ImportError:
            from app import forge_dpop as _dp
            from app import forge_token_exchange as _tx
            from app.forge_coffre_cloisonne import cle_ephemere
        sujet, job = _jeton_sujet(), os.environ.get("NOKIDO_JOB_ID")
        if not sujet or not job:
            return None
        url, cle = self.base_url + "/oauth/token", cle_ephemere()
        corps = urllib.parse.urlencode({"grant_type": _tx.GRANT_TYPE, "subject_token": sujet,
                                        "subject_token_type": _tx.TYPE_JOB, "job_id": job,
                                        "audience": "hub", "scope": portee}).encode()
        req = urllib.request.Request(url, data=corps, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("DPoP", _dp.creer_preuve("POST", url, cle=cle))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                rep = json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001 -- refus (400 invalid_scope) ou route muette : repli DIT par l'appelant
            _log.info("[hub_client] agent=%s echange RFC 8693 refuse pour %s (%s)", self.agent, portee,
                      type(e).__name__)
            return None
        acces = rep.get("access_token") if isinstance(rep, dict) else None
        return (acces, cle, rep.get("expires_in", 0)) if acces else None

    def _entetes_echange(self, url: str, body: Optional[dict]):
        """En-tetes DPoP d'un APPEL D'OUTIL, pour sa portee exacte (jeton en cache jusqu'a 30 s de son expiration),
        ou None -> repli sur le chemin actuel, DIT une fois par portee (observer avant d'enforcer)."""
        import time as _t
        try:
            from nokido_agent.app import forge_dpop as _dp
            from nokido_agent.app.forge_token_exchange import portee_requise
        except ImportError:
            from app import forge_dpop as _dp
            from app.forge_token_exchange import portee_requise
        p = body.get("params") if isinstance(body, dict) and body.get("method") == "tools/call" else None
        portee = portee_requise(p.get("name", ""), p.get("arguments") or {}) if isinstance(p, dict) else "hors_outil"
        if not hasattr(self, "_acces_par_portee"):  # instance construite sans __init__ (tests, sous-classes)
            self._acces_par_portee, self._replis_dits = {}, set()
        acces, cle, fin = self._acces_par_portee.get(portee, (None, None, 0.0))
        if (not acces or fin - _t.time() < 30) and portee != "hors_outil":
            obtenu = self._echanger_portee(portee)
            if obtenu:
                acces, cle, ttl = obtenu
                fin = _t.time() + float(ttl or 0)
                self._acces_par_portee[portee] = (acces, cle, fin)
            else:
                acces = None
        if not acces:
            if portee not in self._replis_dits:
                self._replis_dits.add(portee)
                _log.warning("[hub_client] agent=%s portee %s NON accordee par echange RFC 8693 : repli sur le "
                             "chemin actuel (coffre) | remede: mesurer l'appelant, puis ajouter la portee a la "
                             "politique de son identite ou sortir l'appel du bac", self.agent, portee)
            return None
        return {"Authorization": "DPoP " + acces, "DPoP": _dp.creer_preuve("POST", url, jeton_acces=acces, cle=cle)}

    def _req(self, method: str, path: str, body: Optional[dict] = None) -> Optional[Any]:
        """Requete HTTP vers le hub. Rend None en cas d'echec — mais JAMAIS en
        silence : la premiere occurrence d'une panne est journalisee avec sa cause,
        sa consequence et son remede. Les repetitions identiques sont tues (un
        daemon en boucle noierait le journal), la GUERISON est dite aussi."""
        url = self.base_url + path
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        _h_ech = self._entetes_echange(url, body) if getattr(self, "_echange_job", False) else None
        if _h_ech:
            for _k, _v in _h_ech.items():
                req.add_header(_k, _v)
        else:
            _tok, _src = self._jeton_courant()
            self._dire_provenance(_src)
            if "FORGE_MCP_TOKEN" not in _src:  # repli maitre : pas de nom usurpe
                req.add_header("LaForge-Agent-Name", self.agent)  # canonique (RFC 6648)
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

    def appel_outil(self, name: str, args: dict, timeout: Optional[float] = None) -> Optional[dict]:
        """Reponse JSON-RPC BRUTE d'un appel d'outil, par `_req` -- donc par l'echange RFC 8693 quand il est arme --,
        ou None (echec deja journalise par `_req`). Pour les appelants qui lisaient le dict eux-memes : 30/10,
        forge_self_patcher._hub_call construisait ses propres en-tetes Bearer et relisait le coffre."""
        avant = self.timeout
        if timeout:
            self.timeout = float(timeout)
        try:
            return self._req("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                              "params": {"name": name, "arguments": args}})
        finally:
            self.timeout = avant

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
