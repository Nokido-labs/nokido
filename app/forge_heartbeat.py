# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_heartbeat
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_heartbeat.py v2 — Heartbeat temps réel via live_bridge
============================================================
Architecture :
  - beat()         → live_bridge.json_set() — mmap, <50µs, zéro disque
  - read_heartbeat → live_bridge.json_get() — mmap, <50µs
  - heartbeat.json → écrit en background (thread daemon), jamais sur le hot path
  - _rag_stats     → forge_db persistante (pas de connect/close)

Plus aucun sqlite3.connect() ni fichier I/O sur le thread MCP stdio.
"""


import json
import logging
import os
import time
import threading
from pathlib import Path

logger = logging.getLogger("Nokido.Heartbeat")

_ROOT = Path(__file__).resolve().parent.parent
_HB_PATH = _ROOT / "sandbox" / "heartbeat.json"
_STATE_PATH = _ROOT / "sandbox" / "bridge_state.json"
_LOCK = threading.Lock()

STALE_THRESHOLD_SEC = 60


# ── Helpers légers ────────────────────────────────────────────────────────────


def beat_daemon(name: str, **extra) -> bool:
    """Pouls d'un DAEMON (distinct du heartbeat mmap du bridge MCP ci-dessous).

    Ecrit `sandbox/<name>.heartbeat`, le format que lit le superviseur via la clef
    `heartbeat` de services.toml et que scrute `forge_health_diagnostic`.

    POURQUOI ICI. Recensement du 2026-07-28 : **39 modules** avaient chacun
    reimplemente ce geste (`_heartbeat`, `_write_heartbeat`, `write_heartbeat`,
    `_save_heartbeat`...). Onze daemons SANS PORT n'en avaient aucun — leur mort est
    donc totalement silencieuse, et c'est exactement ainsi que le daemon epistemique
    a pu mourir 13 h sans temoin le meme jour. Ajouter onze implementations de plus
    aurait porte le total a cinquante : on cable sur UN seul chemin.

    A appeler APRES un cycle reussi, jamais au demarrage : le pouls doit attester du
    TRAVAIL, pas de la simple existence. Un daemon vivant mais incapable de faire son
    tour doit voir son pouls geler, pour que le superviseur le releve.

    Ne leve jamais : un pouls qui casse son porteur serait pire que pas de pouls.
    """
    try:
        p = _ROOT / "sandbox" / ("%s.heartbeat" % name)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": os.getpid()}
        payload.update(extra)
        # `default=str` : plusieurs implementations maison serialisaient ainsi, et
        # leurs charges portent des valeurs non JSON (dates, objets). Sans lui, la
        # migration vers ce chemin unique ferait lever `json.dumps`, donc `return
        # False`, donc un pouls PERDU EN SILENCE — le superviseur y lirait une mort.
        # Le canon doit accepter ce que les variantes acceptaient, sinon centraliser
        # degrade.
        p.write_text(json.dumps(payload, ensure_ascii=False, default=str),
                     encoding="utf-8")
        # CONSTATER l'emission. Ce point est le chemin UNIQUE d'ecriture des pouls
        # (39 reimplementations unifiees ici le 2026-07-28), donc l'instrumenter rend
        # mesurable la famille ENTIERE — la ou l'analyse statique ne voit qu'un nom
        # DYNAMIQUE et fabrique des artefacts (`s.heartbeat`, mesure 2026-09-04).
        #
        # Try IMBRIQUE et non partage avec l'ecriture : une base de couplage
        # verrouillee ne doit pas faire echouer le pouls, ce qui se lirait comme une
        # MORT. La sonde ne met jamais son porteur en peril.
        try:
            from nokido_agent.app.forge_signal_coupling import emit_signal

            emit_signal("%s.heartbeat" % name, emitter="forge_heartbeat.beat_daemon")
        except Exception:  # noqa: BLE001 - muet-ok : sonde, jamais un porteur
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


def demarrer_pouls_service_http(nom: str, url: str, intervalle_s: float = 60.0,
                                timeout_s: float = 5.0):
    """Pouls d'un SERVEUR HTTP, atteste par le fait qu'il SERT. Rend le thread.

    `beat_daemon` demande de battre APRES un cycle reussi, jamais au demarrage. Un
    serveur n'a pas de cycle : il attend des requetes. Deux facons de rater ce contrat :

    - battre a chaque requete recue -> un serveur SANS TRAFIC voit son pouls geler, et
      le superviseur lit une mort la ou il n'y a qu'un silence de l'utilisateur ;
    - battre depuis une boucle qui ne verifie rien -> on atteste l'EXISTENCE du process,
      pas sa capacite. C'est « SIGNAL != PREUVE DE VIE » : le pouls d'un serveur dont la
      boucle est bloquee continuerait, et couvrirait exactement la panne qu'on veut voir.

    D'ou cette forme : un fil de fond interroge le serveur sur SA propre URL et ne bat
    que si la reponse arrive. Le pouls atteste donc le chemin complet (boucle vivante +
    port accepte + reponse produite), c'est-a-dire l'APPLICATIF, pas seulement le
    TRANSPORT. Si le serveur se fige, la sonde echoue, le pouls GELE, le superviseur
    releve — ce qui est le comportement voulu.

    Le fil est `daemon` : il n'empeche jamais l'arret du porteur. Il ne leve jamais, et
    une sonde en echec est SILENCIEUSE par construction (c'est l'absence de battement
    qui parle, pas un journal).
    """
    import threading as _th
    import urllib.request as _u

    def _boucle() -> None:
        while True:
            try:
                requete = _u.Request(url, method="GET")
                with _u.urlopen(requete, timeout=timeout_s) as r:
                    # On ne rapatrie pas le corps : certaines pages pesent des dizaines
                    # de Ko et ce fil tourne en permanence. Le statut suffit a prouver
                    # que la reponse a ete PRODUITE.
                    if 200 <= r.status < 500:
                        beat_daemon(nom, sonde=url, statut=r.status)
            except Exception:  # noqa: BLE001 — muet-ok : l'absence de pouls EST le signal
                pass
            time.sleep(max(5.0, intervalle_s))

    fil = _th.Thread(target=_boucle, name="pouls-%s" % nom, daemon=True)
    fil.start()
    return fil


# Periode du RYTHME D'ECHAPPEMENT, utilisee UNIQUEMENT quand le noeud sinusal
# (`forge_cardiac_node`) est muet ou illisible. En physiologie, le noeud
# auriculo-ventriculaire prend le relais quand le sinusal defaille, a une frequence
# plus basse : le corps ralentit, il ne s'arrete pas. Reste SOUS le plus court seuil
# du superviseur (90 s, tier `fast`), sinon la defaillance du coeur ferait declarer
# figes tous les organes qu'il perfusait.
ECHAPPEMENT_S = 45


class Cadence:
    """Horloge d'un daemon : un TICK court porte le POULS, le travail lourd se
    declenche tous les N ticks.

    POURQUOI CETTE CLASSE (owner, 2026-09-03). Un daemon dont le cycle dure 6 h et
    qui ne bat qu'en fin de cycle cree DEUX temporalites : un metabolisme reel et un
    signe de vie beaucoup plus rare. Le superviseur, qui juge a 600 s, le declare
    fige et le relance -- mesure du jour : 765 relances de `forge_hebbian_linker`,
    2377 sorties de process, un organe qui refaisait son travail toutes les DIX
    MINUTES au lieu de quatre fois par jour et n'a jamais atteint la fin d'une
    attente. Les 6 h sont un rythme de MAINTENANCE, pas un rythme cardiaque.

    CE QU'ON NE CASSE PAS, et c'est le point delicat. La doctrine de `beat_daemon`
    (2026-07-28) dit : battre APRES un cycle reussi, jamais au demarrage, pour qu'un
    daemon incapable de faire son tour voie son pouls geler. Elle a raison, et elle
    n'est pas contournee ici : le pouls est emis a la FIN du tick, donc un travail
    qui bloque ou qui plante interrompt bien le pouls. Ce qu'elle ne pouvait pas
    exprimer, c'est qu'un cycle plus long que le seuil rend sa regle intenable.

    On separe donc DEUX signaux, plutot que d'en surcharger un seul -- la lecon
    `llama.wanted`, ou un drapeau disait a la fois « on me demande » et « je suis
    vivant », et produisait les deux pannes opposees :

      tick            -> LIVENESS : je tourne. Consomme par le superviseur.
      dernier_cycle_* -> PROGRESSION : mon travail avance. Consomme par le
                         diagnostic de sante, qui peut signaler un cycle en retard
                         SANS faire tuer l'organe.

    Usage :
        cad = Cadence("hebbian_linker", cycle_s=21600)
        while True:
            if cad.tour():                 # True quand le cycle est du
                out = run_cycle()
                cad.cycle_termine(resume=out)
            cad.dormir()                   # emet le pouls, puis attend un tick
    """

    def __init__(self, nom: str, cycle_s: float, echappement_s: float = ECHAPPEMENT_S) -> None:
        self.nom = nom
        self.cycle_s = max(0.0, float(cycle_s))
        # Periode de SECOURS. La periode NORMALE n'est pas ici : elle est imposee par
        # le coeur, lue a chaque tour. Un organe qui fixerait sa propre cadence serait
        # un pacemaker de plus -- c'est exactement ce qu'on retire.
        self.echappement_s = max(1.0, min(float(echappement_s),
                                          self.cycle_s or float(echappement_s)))
        self.tick_s = self.echappement_s      # derniere periode effectivement suivie
        self.tick = 0
        self.rythme = "inconnu"               # sinusal | echappement
        self.tick_coeur = None                # temps biologique commun, quand il existe
        self._du = True          # le premier tour travaille, comme avant
        self._dernier_cycle_ts: float | None = None
        self._dernier_cycle_ok: bool | None = None
        self._travail_depuis: float | None = None
        self._extra: dict = {}

    def _accorder(self) -> None:
        """Se cale sur le coeur. A defaut, passe en echappement et le DIT.

        On ne conclut jamais « le coeur est mort » : on constate qu'on ne peut pas
        s'accorder. La cause appartient au diagnostic, pas a l'organe perfuse.
        """
        try:
            from nokido_agent.app.forge_cardiac_node import lire as _lire_coeur

            pouls = _lire_coeur()
        except Exception:  # noqa: BLE001  # muet-ok : l'echec de lecture est traite
            # juste en dessous comme une absence de pouls, etat explicite et publie.
            pouls = None
        if pouls:
            self.rythme = "sinusal"
            self.tick_coeur = pouls.get("tick")
            periode = float(pouls.get("periode_s") or self.echappement_s)
            self.tick_s = max(1.0, min(periode, self.cycle_s or periode))
        else:
            self.rythme = "echappement"
            self.tick_coeur = None
            self.tick_s = self.echappement_s

    def tour(self) -> bool:
        """Avance d'un tour. Rend True quand le travail lourd est du.

        Quand il rend True, l'organe DECLARE qu'il entre en travail, et l'ecrit
        immediatement. C'est ce qui permet a un lecteur de distinguer « occupe » de
        « mort » sans thread de battement : un crawl de quatre minutes laisse une
        trace `travail_en_cours` datee, la ou l'absence de pouls seule se lisait
        « organe fige ».
        """
        self.tick += 1
        du = False
        if self._du:
            self._du = False
            du = True
        elif self.cycle_s and self._dernier_cycle_ts is not None:
            du = (time.time() - self._dernier_cycle_ts) >= self.cycle_s
        if du:
            self._travail_depuis = time.time()
            # S'accorder AVANT de declarer : sans cela, l'entree en travail publie
            # `rythme: inconnu` et `tick_coeur: null`, et un lecteur ne peut pas dire
            # si l'organe qui commence a travailler est perfuse. La declaration
            # perdrait precisement ce qu'elle sert a etablir.
            self._accorder()
            self.battre()
        return du

    def cycle_termine(self, ok: bool = True, **extra) -> None:
        """Enregistre la PROGRESSION -- un axe distinct du pouls.

        Un cycle en echec le DIT (`ok=False`) : c'est une information, pas un
        silence. Et la fin du travail est notee, pour qu'un organe au repos ne soit
        pas lu comme un organe occupe depuis des heures.
        """
        self._dernier_cycle_ts = time.time()
        self._dernier_cycle_ok = bool(ok)
        self._travail_depuis = None
        self._extra = extra

    def battre(self) -> bool:
        """Publie l'etat de l'organe sur TROIS axes qu'on ne confond jamais.

            POULS   suis-je encore perfuse ?      -> tick, tick_coeur, rythme
            PROGRES mon travail avance-t-il ?     -> progres_ts, progres_ok, progres_age_s
            TRAVAIL suis-je en train d'agir ?     -> travail_en_cours, travail_depuis_s

        INVARIANT (arbitrage owner 2026-09-03) : `heartbeat != work completed`,
        `heartbeat != healthy`, `heartbeat != progress`. Le pouls atteste de la
        PERFUSION, rien d'autre. Un cycle long ne doit donc plus se lire comme une
        mort -- c'est la lecture qui coutait 765 relances a l'organe hebbien.
        """
        charge = {"tick": self.tick, "tick_s": self.tick_s, "cycle_s": self.cycle_s,
                  "rythme": self.rythme, "tick_coeur": self.tick_coeur,
                  "travail_en_cours": self._travail_depuis is not None,
                  "progres_ok": self._dernier_cycle_ok}
        if self._travail_depuis is not None:
            charge["travail_depuis_s"] = round(time.time() - self._travail_depuis, 1)
        if self._dernier_cycle_ts is not None:
            charge["progres_ts"] = round(self._dernier_cycle_ts, 1)
            charge["progres_age_s"] = round(time.time() - self._dernier_cycle_ts, 1)
        charge.update(self._extra)
        return beat_daemon(self.nom, **charge)

    def dormir(self, stop=None) -> None:
        """Pouls de fin de tick, puis attente d'un tick.

        `stop` est un predicat optionnel consulte chaque seconde : un daemon qui
        gere SIGTERM doit rester interruptible, sinon la bascule sur le rythme du
        coeur (jusqu'a 45 s) transformerait un arret propre en attente de 45 s.

        L'ordre compte : battre APRES le travail du tick preserve la doctrine de
        `beat_daemon` -- un tick qui bloque n'emet rien, et le superviseur releve.

        La periode d'attente est celle que le COEUR impose, relue a chaque tour :
        c'est ainsi que l'adaptation du rythme (tachycardie sous pression, bradycardie
        au repos) se propage sans que le moindre organe ait a la calculer.
        """
        self._accorder()
        self.battre()
        if stop is None:
            time.sleep(self.tick_s)
            return
        fin = time.time() + self.tick_s
        while True:
            reste = fin - time.time()
            if reste <= 0 or stop():
                return
            time.sleep(min(1.0, reste))


def _now() -> str:
    """Now."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _ts() -> float:
    """Ts."""
    return time.time()


def _rag_stats_fast() -> dict:
    """forge_db persistante — zéro connect/close."""
    try:
        from nokido_agent.app.forge_db import db as _db

        chunks = _db.scalar("SELECT COUNT(*) FROM rag_chunks") or 0
        last = _db.scalar("SELECT MAX(timecode) FROM rag_snapshots") or ""
        return {"db_timestamp": last, "db_chunks": chunks}
    except Exception:
        return {"db_timestamp": "", "db_chunks": 0}


def _active_mode() -> str:
    """Active mode."""
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8")).get("active_mode", "AUTO")
    except Exception:
        return "AUTO"


def _get_bridge() -> object:
    """Retourne le singleton live_bridge — import lazy pour éviter les cycles."""
    from nokido_agent.app.live_bridge import bridge

    return bridge


# ── Écriture background heartbeat.json (non-bloquant) ─────────────────────────


def _write_hb_bg(hb: dict) -> None:
    """Flush heartbeat.json en daemon thread — ne bloque jamais le MCP."""

    def _do(data=hb) -> None:
        """Do.

        Args:
            data: Description.
        """
        try:
            _HB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    threading.Thread(target=_do, daemon=True, name="HB-Flush").start()


# ── API publique ──────────────────────────────────────────────────────────────


def beat(agent: str, status: str = "idle", progress: int = 0, task: str = "") -> dict:
    """
    Hot path : met à jour le statut de l'agent dans live_bridge (mmap).
    Retourne le snapshot complet depuis mmap.
    Zéro I/O disque sur le hot path.
    """
    now_str = _now()
    now_ts = _ts()
    br = _get_bridge()

    agent_data = {
        "last_ping": now_str,
        "status": status,
        "pid": os.getpid(),
        "progress": progress,
        "task": task,
        "ts": now_ts,
        "drift_ms": 0,
    }

    with _LOCK:
        # Lire état courant depuis mmap
        hb = br.json_get("hb") or {}

        # Initialiser structure si absente
        if "agents" not in hb:
            hb["agents"] = {}
            hb["sync_vector"] = {}
            hb["warnings"] = []

        # Mettre à jour cet agent
        hb["agents"][agent] = agent_data
        hb["sync_vector"][agent] = hb["sync_vector"].get(agent, 0) + 1
        hb["generated_at"] = now_str
        hb["active_mode"] = _active_mode()

        # Calculer dérives sans I/O
        warnings = []
        for ag, info in hb["agents"].items():
            ag_ts = info.get("ts", 0)
            if ag_ts > 0:
                drift = round((now_ts - ag_ts) * 1000)
                hb["agents"][ag]["drift_ms"] = drift
                if drift > STALE_THRESHOLD_SEC * 1000 and ag != agent:
                    warnings.append(f"{ag} stale ({drift // 1000}s)")
        hb["warnings"] = warnings

        # Écrire dans mmap — hot path, <50µs
        br.json_set("hb", hb)

        # RAG stats + flush fichier en background (non-bloquant)
        _captured_hb = dict(hb)

        def _bg_flush() -> None:
            """Background flush of heartbeat snapshot + RAG stats."""
            h = _captured_hb
            try:
                rag = _rag_stats_fast()
                h["db_timestamp"] = rag["db_timestamp"]
                h["db_chunks"] = rag["db_chunks"]
                _write_hb_bg(h)
                br.json_set("rag", rag)
            except Exception:
                pass

        threading.Thread(target=_bg_flush, daemon=True, name=f"HB-BG-{agent}").start()

    return hb


def read_heartbeat() -> dict:
    """Lit depuis mmap — fallback fichier si mmap vide."""
    try:
        br = _get_bridge()
        hb = br.json_get("hb")
        if hb:
            return hb
    except Exception:
        pass
    # Fallback fichier
    try:
        return json.loads(_HB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def kill_stale_agents(stale_seconds: int = 120) -> list:
    """Détecte et tue les process Cline orphelins via PID enregistré dans mmap."""
    import subprocess as _sp

    killed = []
    hb = read_heartbeat()
    now = _ts()
    for agent, data in hb.get("agents", {}).items():
        if "CLINE" not in agent:
            continue
        pid = data.get("pid")
        ag_ts = data.get("ts", 0)
        drift_ms = round((now - ag_ts) * 1000) if ag_ts > 0 else -1
        if not pid or drift_ms < 0:
            continue
        if drift_ms > stale_seconds * 1000:
            try:
                r = _sp.run(
                    f'tasklist /FI "PID eq {pid}" /FO CSV /NH', shell=True,
                    capture_output=True, text=True, errors="replace", timeout=5,
                )
                if str(pid) in r.stdout:
                    _sp.Popen(f"taskkill /PID {pid} /T /F", shell=True, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                    killed.append(f"{agent} PID={pid} drift={drift_ms // 1000}s")
            except Exception:
                pass
    return killed


def acquire_token(agent: str, timeout_sec: float = 5.0) -> bool:
    """Token d'écriture via mmap."""
    br = _get_bridge()
    deadline = _ts() + timeout_sec
    while _ts() < deadline:
        with _LOCK:
            holder = br.json_get("token")
            if holder is None or holder == agent:
                br.json_set("token", agent)
                return True
            # Forcer si holder stale
            hb = br.json_get("hb") or {}
            holder_ts = hb.get("agents", {}).get(holder, {}).get("ts", 0)
            if _ts() - holder_ts > STALE_THRESHOLD_SEC:
                br.json_set("token", agent)
                return True
        time.sleep(0.2)
    return False


def release_token(agent: str) -> None:
    """Release token.

    Args:
        agent: Description.
    """
    br = _get_bridge()
    with _LOCK:
        if br.json_get("token") == agent:
            br.json_set("token", None)


def get_drift(agent: str) -> int:
    """Get drift.

    Args:
        agent: Description.
    """
    hb = read_heartbeat()
    return hb.get("agents", {}).get(agent, {}).get("drift_ms", -1)


def is_in_sync(max_drift_ms: int = 5000) -> bool:
    """Is in sync.

    Args:
        max_drift_ms: Description.
    """
    hb = read_heartbeat()
    for info in hb.get("agents", {}).values():
        if info.get("status") in ("unknown", ""):
            continue
        if info.get("drift_ms", -1) > max_drift_ms:
            return False
    return True


def collab_summary() -> str:
    """Collab summary."""
    hb = read_heartbeat()
    lines = [
        f"Heartbeat Nokido — {hb.get('generated_at', '')}",
        f"Mode: {hb.get('active_mode', '?')} | DB: {hb.get('db_timestamp', '?')} ({hb.get('db_chunks', 0)} chunks)",
        f"Token: {hb.get('token_holder') or 'libre'}",
        "",
    ]
    for ag, info in hb.get("agents", {}).items():
        drift = info.get("drift_ms", -1)
        icon = "OK" if 0 <= drift < 30000 else "WARN" if drift >= 0 else "DEAD"
        lines.append(f"[{icon}] {ag} — {info.get('status', '?')} drift:{drift}ms")
    sv = hb.get("sync_vector", {})
    if sv:
        lines.append("SyncVec: " + " ".join(f"{a}={v}" for a, v in sv.items()))
    return "\n".join(lines)
