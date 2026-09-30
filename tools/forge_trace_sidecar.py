"""
Phase A — AMI trace acceleration.
Tails mcp_audit.log, parses the line carrying each call's OUTCOME → record_trace()
(OUT for inbound channels, IN for CLOUD where OUT is the outgoing request).
Also polls worker_status every 10s (vs 30s in old daemon).
Goal: 50k real (state, action, state') traces.

Skips: poll, inspector.*, heartbeat, port — pure noise.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `succes_de` — Seul un OK -- quelle que soit sa casse (`ok` : sse.open/close) -- est un succes.
"""
import json
import logging
import re
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def configurer_journal() -> None:
    """Configure le journal. Appelee par `main()`, JAMAIS a l'import.

    POURQUOI (mesure 2026-09-16). `basicConfig` etait au niveau module : tout
    import ouvrait `logs/trace_sidecar.log` en ecriture. Sous un compte qui n'a
    pas ce droit -- un runner CI, un compte de service -- l'import echouait en
    `PermissionError`, ce qui se lisait comme « le module est casse » alors que
    seul le JOURNAL etait inaccessible. Pire : `basicConfig` configure le logger
    RACINE, donc un simple import reconfigurait le journal du process HOTE.

    Le repli console est DIT, jamais avale : un journal muet ne doit pas se
    confondre avec un daemon silencieux.
    """
    handlers = [logging.StreamHandler()]
    try:
        (ROOT / "logs").mkdir(parents=True, exist_ok=True)
        handlers.insert(0, RotatingFileHandler(
            str(ROOT / "logs" / "trace_sidecar.log"),
            maxBytes=10485760, backupCount=5))
    except OSError as exc:
        print("[trace_sidecar] journal fichier indisponible (%s: %s) -- "
              "sortie console seule" % (type(exc).__name__, exc), file=sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [trace_sidecar] %(message)s",
        handlers=handlers,
    )

from nokido_agent.app.forge_cost_module import total_cost
from nokido_agent.app.forge_execution_tracer import count_traces, init_db, record_trace
from nokido_agent.app.forge_state_encoder import encode_state, get_current_state_text

# Noise filter — skip these tool/channel patterns
SKIP_TOOLS = {
    "poll",
    "heartbeat",
    "port",
    "cycle",
    "heal",
    "inspector.heartbeat",
    "inspector.port",
    "inspector.cycle",
    "inspector.heal",
    "netcfg_ping",
}
SKIP_AGENTS = {"INSPECTOR", "OPENAI_PROXY"}

AUDIT_LOG = ROOT / "logs" / "mcp_audit.log"
STATE_INTERVAL = 10  # seconds between worker_status polls
# Horodatage du dernier pouls (liste = mutable depuis la boucle, sans global).
_last_beat = [0.0]
GOAL_TEXT = "system stable, all tasks completed, hub healthy, no errors"

# Un pouls indisponible ne se dit qu'UNE fois : le tour revient toutes les 60 s,
# journaliser chaque echec inonderait le journal qu'on cherche justement a lire.
_pouls_muet = [False]

# `init_db()` et son comptage vivaient ICI, au niveau module : importer le
# module ouvrait la base. Ils sont desormais dans `demarrer()`.

# ── Shared state ────────────────────────────────────────────────────────────
_state_lock = threading.Lock()
_state = {"text": "", "emb": None, "cost": None}
# Calcule par `demarrer()` : `encode_state` charge un modele, ce qui n'a rien a
# faire dans un import. `None` tant que le daemon n'a pas demarre.
goal_emb = None


def _refresh_state():
    if goal_emb is None:
        # `demarrer()` n'a pas tourne : sans vecteur du but, `total_cost` n'a
        # aucun sens. On s'abstient EN LE DISANT plutot que de calculer contre
        # None -- une valeur fausse vaut moins qu'une absence declaree.
        logging.debug("refresh ignore : goal_emb absent (demarrer() non appele)")
        return
    try:
        text = get_current_state_text()
        emb = encode_state(text)
        cost = total_cost(emb, goal_emb)
        with _state_lock:
            _state["text"] = text
            _state["emb"] = emb
            _state["cost"] = cost
    except Exception as e:
        logging.debug(f"state refresh err: {e}")


def _get_state():
    with _state_lock:
        return _state["emb"], _state["cost"]


# ── State refresher thread ───────────────────────────────────────────────────
def _state_loop():
    while True:
        _refresh_state()
        time.sleep(STATE_INTERVAL)


def demarrer() -> None:
    """Tous les effets de bord du sidecar, en UN endroit nomme.

    Avant (mesure 2026-09-16) ces six gestes s'executaient a l'import : le
    journal, `init_db()`, `count_traces()`, `encode_state(GOAL_TEXT)`, le thread
    d'etat et le premier `_refresh_state()`. Or le test d'appui genere se
    contente d'importer le module : chaque run de la suite demarrait donc un
    thread de fond qui vivait jusqu'a la fin du process pytest, ouvrait un
    journal et touchait une base.

    Le defaut n'etait pas « un handler de fichier » mais « le point d'entree
    est le corps du module ». Un handler se contourne ; un thread et une base,
    non.
    """
    global goal_emb
    configurer_journal()
    init_db()
    logging.info(f"sidecar start — {count_traces()} existing traces")
    goal_emb = encode_state(GOAL_TEXT)
    threading.Thread(target=_state_loop, daemon=True).start()
    _refresh_state()  # initial sync

# ── Log parser ────────────────────────────────────────────────────────────────
# Format ligne : TIMESTAMP | CHANNEL:tool | {json payload} | STATUS
# IMPORTANT : le logger d'audit TRONQUE chaque ligne (~180 char) → le JSON
# payload est coupé en plein milieu (pas de '}' fermant). On ne peut donc PAS
# faire json.loads dessus (régression qui a gelé les traces 2026-05-24). On
# extrait direction/agent/status par regex sur le partiel — record_trace n'a
# besoin que des métadonnées (l'embedding d'état vient de _get_state, pas du log).
_HEAD_RE = re.compile(r"^(\S+)\s*\|\s*([\w.]+):([\w.]+)\s*\|\s*(.*)$")
_AGENT_RE = re.compile(r'"agent"\s*:\s*"([^"]+)"')
_TRACE_RE = re.compile(r'"trace_id"\s*:\s*"([^"]+)"')
# `ERR:401` fait partie du statut (mesure 2026-09-25 : 473 lignes sur 8 Mo). L'ancien motif (lettres
# seules) ne le lisait pas et le statut retombait sur « OK » : un echec lu comme un succes.
_STATUS_RE = re.compile(r"\|\s*([A-Za-z_]{2,12}(?::[\w.-]{1,40})?)\s*$")
STATUT_ILLISIBLE = "INCONNU"


def _canal_sortant(canal: str) -> bool:
    """Canal ou le HUB appelle un tiers : la ligne OUT est la REQUETE, la ligne IN porte l'ISSUE.

    Mesure 2026-09-25 : `log_cloud_out` (OUT, status CALL) puis `log_cloud_in` (IN, OK/ERR). Pour les
    canaux entrants (HUB, STDIO...) c'est l'inverse. Ne tracer que les OUT laissait
    execution_traces avec les seules requetes des fournisseurs -- groq lu « 0 % » a 98 % de reussite.
    """
    return canal.rsplit(".", 1)[-1].startswith("CLOUD")


def succes_de(status: str) -> bool:
    """Seul un OK -- quelle que soit sa casse (`ok` : sse.open/close) -- est un succes."""
    return (status or "").upper() == "OK"
_SESSION_RE = re.compile(r'"session_id"\s*:\s*"([^"]*)"')
# Previews de secours : le journal TRONQUE les payloads, donc `json.loads` echoue
# presque toujours et les deux previews partaient vides (mesure 2026-08-14 :
# `{"args": "", "result_preview": ""}` sur 41 714 lignes). On recupere alors le
# debut du champ, tronque mais INFORMATIF — un fragment vaut mieux que rien.
_IN_RE = re.compile(r'"in"\s*:\s*"(.{0,200})')
_OUT_RE = re.compile(r'"out"\s*:\s*"(.{0,200})')


# APPARIEMENT IN/OUT — mesure 2026-08-14.
# Le journal ecrit DEUX lignes par appel : la ligne IN porte "in" (les
# arguments), la ligne OUT porte "out" (le resultat). Le sidecar ne traite que
# les OUT — il ne pouvait donc JAMAIS voir d'arguments : `args` etait vide sur
# les 41 714 lignes, et ce n'etait pas un defaut de regex mais de structure.
# On ne peut pas apparier par trace_id (caviarde des deux cotes) : on apparie
# par (outil, agent) avec une fenetre courte. Deux appels du meme agent sur le
# meme outil a moins de _APPARIEMENT_S d'ecart peuvent se confondre — c'est
# assume : un argument approximatif vaut mieux qu'une trajectoire muette, et la
# valeur reste tronquee a 200 caracteres.
_ARGS_CACHE: dict = {}
_APPARIEMENT_S = 30.0
_CACHE_MAX = 512


def _memoriser_args(tool: str, agent: str, rest: str) -> None:
    im = _IN_RE.search(rest)
    if not im:
        return
    if len(_ARGS_CACHE) > _CACHE_MAX:          # borne : jamais de fuite memoire
        _ARGS_CACHE.clear()
    _ARGS_CACHE[(tool, agent)] = (time.time(), im.group(1)[:200])


def _reprendre_args(tool: str, agent: str) -> str:
    ts_args = _ARGS_CACHE.pop((tool, agent), None)
    if not ts_args:
        return ""
    ts, args = ts_args
    return args if (time.time() - ts) <= _APPARIEMENT_S else ""


def _parse_line(line: str):
    """Returns (tool, agent, args_preview, out_preview, status) or None.

    Tolérant à la troncature du log : aucun json.loads obligatoire.
    """
    m = _HEAD_RE.match(line.strip())
    if not m:
        return None
    canal, tool, rest = m.group(2), m.group(3), m.group(4)
    sens_requete, sens_issue = (("Direction.OUT", "Direction.IN") if _canal_sortant(canal)
                                else ("Direction.IN", "Direction.OUT"))
    if sens_requete in rest:
        # On n'ecrit pas de trace pour une REQUETE — on lui prend ses arguments
        # et on attend la ligne qui porte son issue.
        am_in = _AGENT_RE.search(rest)
        _memoriser_args(tool, am_in.group(1) if am_in else "?", rest)
        return None
    if sens_issue not in rest:
        return None
    if tool in SKIP_TOOLS or tool.split(".")[0] in SKIP_TOOLS or tool.startswith("inspector."):
        return None
    am = _AGENT_RE.search(rest)
    agent = am.group(1) if am else "?"
    if agent in SKIP_AGENTS:
        return None
    sm = _STATUS_RE.search(rest)
    status = sm.group(1) if sm else STATUT_ILLISIBLE  # jamais « OK » par defaut
    tm = _TRACE_RE.search(rest)
    trace_id = tm.group(1) if tm else ""  # "" -> record_trace fallback contextvar/system
    # CORRELATION PERDUE PAR LE DLP — mesure 2026-08-14 : 41 268 lignes sur
    # 41 714 portaient le trace_id litteral "[REDACTED:key]". Un trace_id W3C est
    # une chaine de 32 hex, et le sanitizer caviarde tout hex de 32+ comme une
    # cle (forge_conv_sanitizer, regle `[0-9a-f]{32,}`). Le garde a raison sur la
    # forme et tort sur le fond : un identifiant de correlation n'ouvre AUCUN
    # acces. Resultat : toutes les trajectoires fusionnaient sous un seul id, et
    # `traces` devenait inexploitable pour mesurer un raisonnement.
    #
    # On n'affaiblit PAS le DLP pour autant : on reconstruit la correlation avec
    # ce qui reste lisible, via la fonction qui existe deja pour ca
    # (`session_trace_id` : chaine les appels d'une meme session/agent, avec
    # reset sur idle-gap). Le groupement redevient possible sans qu'un secret
    # potentiel ne soit reecrit dans un journal.
    if not trace_id or trace_id.startswith("[REDACTED"):
        sm2 = _SESSION_RE.search(rest)
        cle = (sm2.group(1) if sm2 else "") or agent or ""
        if cle:
            try:
                from nokido_agent.app.forge_trace_context import session_trace_id

                trace_id = session_trace_id(cle)
            except Exception as e:  # noqa: BLE001
                print(f"[trace_sidecar] correlation NON reconstruite ({type(e).__name__}: "
                      f"{str(e)[:70]}) | consequence: la trajectoire restera "
                      f"non groupable", flush=True)
                trace_id = ""
        else:
            trace_id = ""
    # Previews best-effort : on tente un json.loads sur le préfixe jusqu'au
    # dernier '}' si présent, sinon previews vides (JSON tronqué = normal).
    payload = {}
    if "}" in rest:
        try:
            payload = json.loads(rest[: rest.rfind("}") + 1])
        except Exception:
            payload = {}
    args_preview = str(payload.get("in", ""))[:200]
    out_preview = str(payload.get("out", ""))[:200]
    # Repli sur le fragment brut quand le JSON est tronque (cas NOMINAL ici).
    if not args_preview:
        args_preview = _reprendre_args(tool, agent)
    if not out_preview:
        om = _OUT_RE.search(rest)
        out_preview = om.group(1)[:200] if om else ""
    return tool, agent, args_preview, out_preview, status, trace_id


# ── Tail & record loop ────────────────────────────────────────────────────────

n_recorded = 0


def _tail_loop():
    global n_recorded
    if not AUDIT_LOG.exists():
        logging.warning(f"audit log not found: {AUDIT_LOG}")
        return

    with open(AUDIT_LOG, encoding="utf-8", errors="replace") as f:
        # Seek to end — only capture NEW events
        f.seek(0, 2)
        logging.info(f"tailing {AUDIT_LOG} from offset {f.tell()}")

        prev_emb, prev_cost = _get_state()

        while True:
            line = f.readline()
            if not line:
                # Pouls THROTTLE (60 s). Ce sidecar suit un log en tail : il peut
                # rester longtemps sans rien lire quand le trafic est calme, et
                # l'absence de trace n'est PAS une mort. Sans ce battement a vide,
                # un log silencieux se lirait comme un daemon mort ; en battant a
                # chaque tour (0,5 s) on ecrirait 172 800 fois par jour pour rien.
                _t_now = time.time()
                if _t_now - _last_beat[0] > 60:
                    _last_beat[0] = _t_now
                    try:
                        from nokido_agent.app.forge_heartbeat import beat_daemon

                        beat_daemon("trace_sidecar", mode="tail")
                        _pouls_muet[0] = False
                    except Exception as exc:  # noqa: BLE001
                        # Ce `pass` etait MUET. Or un pouls qui echoue en
                        # silence fait lire ce daemon comme MORT alors qu'il
                        # travaille : le superviseur ne voit que l'absence de
                        # battement, et rien ne distingue « je n'ai pas pu
                        # battre » de « je suis arrete ». On le DIT.
                        if not _pouls_muet[0]:
                            _pouls_muet[0] = True
                            logging.warning(
                                "pouls indisponible (%s: %s) -- ce daemon bat "
                                "muet : son silence ne prouve PAS sa mort",
                                type(exc).__name__, exc)
                        else:
                            logging.debug("pouls toujours indisponible: %s", exc)
                time.sleep(0.5)
                continue

            parsed = _parse_line(line)
            if not parsed:
                continue

            tool, agent, args_preview, out_preview, status, trace_id = parsed

            cur_emb, cur_cost = _get_state()
            if prev_emb is None or cur_emb is None:
                prev_emb, prev_cost = cur_emb, cur_cost
                continue

            action = {
                "type": "tool_call",
                "tool": tool,
                "agent": agent,
                "args": args_preview,
                "result_preview": out_preview[:100],
                "status": status,
            }

            try:
                record_trace(
                    state_t_emb=prev_emb,
                    action=action,
                    state_t1_emb=cur_emb,
                    cost_before=prev_cost,
                    cost_after=cur_cost,
                    task_type="tool_call",
                    success=succes_de(status),
                    trace_id=trace_id or None,  # corrélation : trace_id extrait de la ligne audit
                    event_key=line,  # idempotence : dédup sur la ligne d'audit brute
                )
                n_recorded += 1
                if n_recorded % 100 == 0:
                    total = count_traces()
                    logging.info(
                        f"traces: {total} total ({n_recorded} this session) | tool={tool} agent={agent}"
                    )
            except Exception as e:
                logging.debug(f"record_trace err: {e}")

            prev_emb, prev_cost = cur_emb, cur_cost


_SINGLETON_LOCK = ROOT / "sandbox" / "trace_sidecar.lock"


def _acquire_singleton_or_exit():
    """Single-writer via lockfile + liveness PID-GC.

    NE TUE PAS d'autre instance : un kill se bat avec le superviseur (il
    respawn la victime -> boucle de kill mutuel, vécu 2026-05-30). À la place :
    si une instance VIVANTE détient le lock -> on sort proprement (exit 0) ;
    si le lock est absent ou STALE (pid mort ou process non-sidecar) -> on
    prend le relais en y écrivant notre pid.

    Pourquoi single-writer : record_trace() insère avec un uuid aléatoire (pas
    de contrainte UNIQUE) -> 2 tailers = double insertion de chaque transition
    -> dataset AMI pollué. Cf. feedback_pid_file_gc_required (valider la cmdline
    via psutil avant de considérer un pid comme vivant, jamais par nom seul).
    """
    try:
        import os

        import psutil

        if _SINGLETON_LOCK.exists():
            try:
                old = int(_SINGLETON_LOCK.read_text().strip())
            except Exception:
                old = -1
            alive = False
            if old > 0 and old != os.getpid() and psutil.pid_exists(old):
                try:
                    alive = "forge_trace_sidecar" in " ".join(psutil.Process(old).cmdline())
                except Exception:
                    alive = False
            if alive:
                logging.warning(f"singleton: writer vivant pid={old} détient le lock — exit propre")
                raise SystemExit(0)
        _SINGLETON_LOCK.parent.mkdir(exist_ok=True)
        _SINGLETON_LOCK.write_text(str(os.getpid()))
        logging.info(f"singleton: lock acquis pid={os.getpid()}")
        # Self-heal des orphelins PRÉ-lock-guard : un vieux process sidecar qui
        # ne participe pas au protocole (ne lit/écrit pas le lock) ne peut pas
        # être délogé par lock-and-exit. On le balaie ici. SÛR car : (a) on tient
        # déjà le lock, (b) toute instance lock-aware concurrente a fait exit (pas
        # run), donc un autre sidecar VIVANT = forcément un orphelin. Borné aux
        # process plus VIEUX que nous (-3s) -> jamais un sibling fraîchement
        # spawné -> pas de kill mutuel ni de bagarre avec le superviseur.
        try:
            my_start = psutil.Process(os.getpid()).create_time()
            for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
                if p.info["pid"] == os.getpid():
                    continue
                cl = " ".join(p.info.get("cmdline") or [])
                if "forge_trace_sidecar" in cl and (p.info.get("create_time") or 0) < my_start - 3:
                    try:
                        p.kill()
                        logging.warning(f"singleton: orphelin pré-lock tué pid={p.info['pid']}")
                    except Exception as e:
                        logging.warning(f"singleton: kill orphelin {p.info['pid']}: {e}")
        except Exception as e:
            logging.debug(f"singleton orphan-sweep skipped: {e}")
    except SystemExit:
        raise
    except Exception as e:
        logging.debug(f"singleton lock skipped: {e}")


def main() -> int:
    """Chemin REEL du daemon — le NR verifie que le garde `__main__` passe ICI.

    Sans point d'entree nomme, `demarrer()` pourrait exister sans etre appelee
    par personne : un mecanisme present sans effet reel, exactement ce que
    l'audit du corps traque.
    """
    demarrer()
    _acquire_singleton_or_exit()
    logging.info("tail loop starting")
    _tail_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
