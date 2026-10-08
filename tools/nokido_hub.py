"""
nokido_hub.py Ã¢â‚¬â€� Nokido Hub v18.3 | Network Monitor redesign
=============================================================
v18.2 : UI /forge/network entiÃƒÂ¨rement redesignÃƒÂ©e
  - mÃƒÂªme ADN visuel que forge_feed.html (monospace, #0d1117, grille)
  - agents identifiÃƒÂ©s avec badges colorÃƒÂ©s + canal STDIO/HUB/CLOUD
  - timeline rÃƒÂ©cent en haut avec tri horodatÃƒÂ©
  - vue graphe D3 pour ÃƒÂ©changes collab (sÃƒÂ©lection mode collaboration)
  - panneau logs avec accÃƒÂ¨s direct mcp_audit.log (tail live)
  - 4 onglets : Network | Graph | Logs | Settings
"""

from __future__ import annotations

import asyncio
import hmac
import importlib.util as _ilu
import json
import logging
import os
import queue
import sqlite3
import sys
import threading
import time
from datetime import UTC
from datetime import datetime as _dt
from pathlib import Path

# === SONDE BOOT (2026-06-11, "on ne voit rien / trop lent") : chrono dès la 1ere
# ligne du process — les imports lourds (forge_*/torch/faiss/RAGEngine) sont SOUVENT
# le coût réel, AVANT main(). Écrit logs/hub_boot.log en flush immédiat (survit a un
# hang : la derniere ligne ecrite = la phase ou ca a bloque). ===
_BOOT_T0 = time.perf_counter()
_BOOT_LOG = Path(__file__).resolve().parent.parent / "logs" / "hub_boot.log"
_BOOT_MARKS: list = []  # (phase, elapsed_s) — rejoué dans forge_startup_logger au boot complet


def _boot_probe(phase: str) -> None:
    el = time.perf_counter() - _BOOT_T0
    _BOOT_MARKS.append((phase, el))
    try:
        _BOOT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_BOOT_LOG, "a", encoding="utf-8") as _bf:
            _bf.write(f"{_dt.now().isoformat(timespec='milliseconds')} +{el:7.1f}s  {phase}\n")
            _bf.flush()
    except Exception:
        pass  # muet-ok : journaliser l'echec du JOURNAL lui-meme bouclerait


_boot_probe("=== HUB PROCESS START (debut import module) ===")

# === SONDE DE FIN (2026-08-26, « hub instable ») ============================
# La sonde ci-dessus tracait le BOOT phase par phase, jusqu'a « pre-serve — uvicorn
# bind :8766 »... puis PLUS RIEN. 9 945 lignes de journal, uniquement des demarrages.
# Le hub disait sa naissance et jamais sa mort : quand il tombait, on lisait « aucune
# erreur dans le log » et on en concluait « il ne crashe pas, il est arrete » — alors
# qu'on ne pouvait tout simplement RIEN savoir. Un service dont la chute ne laisse pas
# de trace se diagnostique par hypotheses, ce qui est exactement ce qu'on a fait.
#
# PORTEE REELLE, corrigee par la MESURE le jour meme — ma premiere note etait trop
# optimiste. Deux redemarrages successifs par le superviseur : ZERO ligne de fin ecrite,
# alors que le processus arrete portait bien cette sonde.
# La cause : le superviseur appelle `proc.kill("SIGTERM")` cote Deno, or **Windows n'a
# pas de SIGTERM** — Deno le traduit en `TerminateProcess`, qui detruit le processus
# sans qu'une seule ligne de code utilisateur s'execute. Aucun handler ci-dessous ne
# peut donc parler sur LE chemin d'arret le plus frequent.
# Ce qui reste couvert, et qui n'est pas rien : une sortie normale, une exception
# fatale, une annulation propre de l'event loop, un thread qui meurt.
# Ce qui NE l'est pas : tout arret brutal (superviseur, `taskkill /F`, OOM killer).
# Pour ce cas, la trace exploitable est le BATTEMENT periodique (`_battement_de_service`,
# plus bas) : il ne dit pas pourquoi le hub est mort, il dit QUAND il vivait encore.
import atexit as _atexit
import signal as _signal

_PROCESS_T0 = time.time()
_FIN_ECRITE = [False]


def _fin_probe(cause: str, detail: str = "") -> None:
    """Ecrit UNE ligne de fin dans le meme journal que le boot (ordre chronologique).

    Idempotent : un signal suivi de l'atexit ne doit pas produire deux verdicts
    contradictoires — le PREMIER (le plus proche de la cause) gagne."""
    if _FIN_ECRITE[0]:
        return
    _FIN_ECRITE[0] = True
    _boot_probe("=== HUB PROCESS FIN [%s] apres %.0f s de service %s"
                % (cause, time.time() - _PROCESS_T0, detail))


_atexit.register(lambda: _fin_probe("sortie normale"))


def _fin_sur_signal(_num, _frame):
    _fin_probe("SIGNAL %s" % _num, "(arret demande de l exterieur)")
    raise SystemExit(128 + int(_num))


for _nom_sig in ("SIGTERM", "SIGINT", "SIGBREAK"):
    _s = getattr(_signal, _nom_sig, None)
    if _s is not None:
        try:
            _signal.signal(_s, _fin_sur_signal)
        except (ValueError, OSError):
            pass  # muet-ok : pas le thread principal, ou signal indisponible ici


def _fin_sur_exception(_type, _val, _tb):
    _fin_probe("EXCEPTION FATALE", "%s: %s" % (_type.__name__, str(_val)[:180]))
    _ancien_hook(_type, _val, _tb)


_ancien_hook = sys.excepthook
sys.excepthook = _fin_sur_exception


def _fin_sur_thread(args):
    # Un thread non-daemon qui meurt peut emporter le process a la sortie : le DIRE,
    # sans marquer la fin (le process, lui, tourne peut-etre encore).
    _boot_probe("THREAD MORT [%s] %s: %s"
                % (getattr(args.thread, "name", "?"), args.exc_type.__name__,
                   str(args.exc_value)[:160]))


threading.excepthook = _fin_sur_thread
# ===========================================================================

_mw_spec = _ilu.spec_from_file_location(
    "hub_middleware_live", str(__import__("pathlib").Path(__file__).parent / "hub_middleware.py")
)
_mw_mod = _ilu.module_from_spec(_mw_spec)
_mw_spec.loader.exec_module(_mw_mod)
validate_mcp_body = _mw_mod.validate_mcp_body
ValidationError = _mw_mod.ValidationError
_boot_probe("hub_middleware charge")

try:
    from nokido_agent.app.forge_ingress_adapter import get_ingress_adapter
except Exception:
    def get_ingress_adapter(): return None
_boot_probe("forge_ingress_adapter importe")

# Lifecycle hooks middleware — server-side équivalent SessionStart/AfterModel
# par-client (Gemini/Codex/Cline...). Injection [HOOK:INBOX] dans tool responses
# si X-Agent a unread messages ou jobs interrompus.
try:
    _lc_spec = _ilu.spec_from_file_location(
        "hub_lifecycle_hooks_live",
        str(__import__("pathlib").Path(__file__).parent / "hub_lifecycle_hooks.py"),
    )
    _lc_mod = _ilu.module_from_spec(_lc_spec)
    _lc_spec.loader.exec_module(_lc_mod)
    lifecycle_wrap = _lc_mod.wrap_response
except Exception as _lc_exc:

    def lifecycle_wrap(agent, ring, tool, session_id, response_text):
        return response_text  # fallback no-op si module absent


_boot_probe("lifecycle hooks importes")


try:
    import ctypes as _ct

    _ct.windll.kernel32.SetConsoleTitleW("Nokido Hub v18.3 [:8766]")
except Exception:
    pass  # muet-ok : titre de fenetre, aucun effet sur le service

ROOT = Path(os.environ.get("LAFORGE_ROOT", Path(__file__).resolve().parent.parent))
DB = ROOT / "RAG" / "embeddings.db"
_SANDBOX = ROOT / "sandbox"
_LIVE_LOG = _SANDBOX / "hub_live.log"
_SANDBOX.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Self-heal DB au boot : si RAG/embeddings.db est corrompue (ex. -wal/-shm périmé,
# incident 2026-06-02), purge + restaure le backup sain le plus récent AVANT toute
# connexion sqlite. Casse les crash-loops sur DB malformée. Ne casse jamais le boot.
try:
    from nokido_agent.tools.forge_db_preflight import boot_db as _boot_db, relocate_if_symlink as _db_reloc

    _boot_probe("AVANT _boot_db (quick_check 8Go embeddings.db sur V: chiffre)")
    # embeddings.db : relocalise si symlink->V: + self-heal (restore backup si malformed)
    _boot_db(str(DB))
    _boot_probe("APRES _boot_db (embeddings.db)")
    # execution_traces.db : même bug symlink->V: -> relocalise en fichier réel C:.
    # PAS de self-heal (aucun backup dédié ; restaurer un backup embeddings le casserait).
    _db_reloc(str(ROOT / "RAG" / "execution_traces.db"))
except Exception as _e_db:
    # Une relocation ratee laisse les traces d'execution sur un chemin mort.
    # Le defaut ne se verrait qu'a la LECTURE, des jours plus tard, et
    # ressemblerait alors a une absence de trafic.
    _boot_probe("db preflight ECHEC: %s: %s" % (type(_e_db).__name__, _e_db))
_boot_probe("db preflight (self-heal embeddings.db)")


# Phase 28+ (2026-05-25) — load Nokido.env au boot. Sans ca, FORGE_MCP_TOKEN
# et LAFORGE_JWT_SECRET en session PS user ne se propagent PAS au service NSSM.
# Parser simple stdlib (pas python-dotenv pour eviter dep). KEY=VAL par ligne,
# # commentaire, ignore lignes invalides, NE PAS override env deja set.
def _load_dotenv(path: Path) -> int:
    # SECRETS au COFFRE, REGLAGES du fichier (decision owner 2026-10-01, GO allow_critical) :
    # ce chargeur recopiait tout le .env, secrets compris, EN CLAIR dans l'environnement du
    # hub -- herite par chaque enfant. Rend le nombre de variables posees, comme avant.
    if not path.is_file():
        return 0
    n = 0
    try:
        from nokido_agent.app.forge_secrets import injecter_env_depuis_coffre

        _b = injecter_env_depuis_coffre(path)
        n = _b["injectees"] + _b["reglages"]
        if _b["absentes"] or _b["illisibles"]:
            _boot_probe("secrets absents du coffre : %s ; illisibles : %s -> forge_env_to_vault"
                        % (_b["absentes"], _b["illisibles"]))
    except Exception as _e_env:
        # Un fichier d'env non charge n'est pas « pas de configuration » :
        # c'est une configuration ABSENTE lue comme une valeur par defaut.
        # On dit COMBIEN de cles ont ete posees avant l'arret.
        _boot_probe("env file ECHEC apres %d cle(s): %s: %s"
                    % (n, type(_e_env).__name__, _e_env))
    return n


_LAFORGE_ENV_LOADED = _load_dotenv(ROOT / "Nokido.env")
# Phase 3a rebrand Nokido : miroir env LAFORGE_ <-> NOKIDO_ (dual-read reversible)
try:
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_env_alias import apply as _apply_env_alias
    _apply_env_alias()
except Exception as _e_alias:
    # Sans le miroir LAFORGE_ <-> NOKIDO_, une moitie du corps lit une
    # variable que l'autre moitie vient de poser sous l'autre nom.
    _boot_probe("env alias NON applique: %s: %s" % (type(_e_alias).__name__, _e_alias))


HUB_HOST = os.environ.get("LAFORGE_HUB_HOST", "127.0.0.1")
HUB_PORT = int(os.environ.get("LAFORGE_HUB_PORT", "8766"))
HUB_TOKEN = os.environ.get("FORGE_MCP_TOKEN", "")
# Fallback vault DPAPI si env vide — permet de nettoyer Nokido.env apres migration
# vault sans casser le master token. get_secret() chaine cache -> DPAPI -> WCM -> env.
if not HUB_TOKEN:
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret as _gs

        HUB_TOKEN = _gs("FORGE_MCP_TOKEN") or ""
    except Exception as _e_sec:
        # Coffre indisponible : le hub demarre SANS credential maitre et se
        # comporte exactement comme si aucun n'etait configure -- ce qui est
        # un CHEMIN D'AUTORISATION different, pas un detail de demarrage.
        # LA VALEUR N'EST JAMAIS JOURNALISEE : seul le fait de l'echec l'est.
        _boot_probe("secret maitre ILLISIBLE: %s" % type(_e_sec).__name__)

# Verbosité : stderr → WARNING only (évite doublon avec mcp_audit.log)
# mcp_audit.log = source de vérité via net_log()
_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setLevel(logging.WARNING)
from logging.handlers import RotatingFileHandler as _RFH
from logging.handlers import QueueHandler as _QueueHandler, QueueListener as _QueueListener
import queue as _queue_mod

# Logging NON-BLOQUANT (incident 2026-06-05) : la racine ne porte qu'un QueueHandler
# (emit = enqueue, jamais de write bloquant sur l'event loop asyncio). Un thread
# daemon QueueListener possède les vrais handlers (stderr capturé par NSSM + fichier
# rotatif) et absorbe le write HORS de la loop. Cause du freeze récurrent du hub :
# stderr = pipe NSSM plein -> StreamHandler.emit bloquait la loop (py-spy : MainThread
# coincé dans logging.emit via enforce_explanation/byte_router à chaque dispatch).
_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
_real_log_handlers = [
    _stderr_handler,
    _RFH(
        ROOT / "sandbox" / "hub.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    ),
]
for _h in _real_log_handlers:
    _h.setFormatter(_log_fmt)
_log_queue: "_queue_mod.Queue" = _queue_mod.Queue(-1)
logging.basicConfig(level=logging.INFO, handlers=[_QueueHandler(_log_queue)])
_log_listener = _QueueListener(_log_queue, *_real_log_handlers, respect_handler_level=True)
_log_listener.start()
logger = logging.getLogger("Nokido.Hub")

_SSE_CLIENTS: list = []
_SSE_LOCK = threading.Lock()

# ── IDLE WATCHDOG ─────────────────────────────────────────────────────────────
try:
    _APP_DIR_W = str(Path(__file__).resolve().parent.parent / "app")
    if _APP_DIR_W not in sys.path:
        sys.path.insert(0, _APP_DIR_W)
    from nokido_agent.app.forge_idle_watchdog import IdleWatchdog as _IdleWatchdog

    _HUB_WATCHDOG = _IdleWatchdog(
        service_name="NokidoMCP",
        idle_timeout=int(os.environ.get("LAFORGE_IDLE_TIMEOUT", "1800")),
    )
    _HUB_WATCHDOG.start()
except Exception as _wde:
    _HUB_WATCHDOG = None
    # Non-bloquant : hub fonctionne sans watchdog

# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬
# NETWORK LOG
# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬


def _resolve_channel(agent: str, request=None) -> str:
    """
    Deduit le canal de communication depuis l identite de l agent
    et les headers de la requete.

    Canaux reconnus :
      STDIO_CLAUDE  : Claude Desktop via bridge stdio
      GEMINI_OAUTH  : Gemini CLI authentifie OAuth
      GEMINI_API    : Appel Gemini via cle API
      CLINE_MCP     : Cline VS Code
      HTTP_DIRECT   : Appel direct sans agent identifie
      INTERNAL_HUB  : Hub interne (cron, janitor, inspector)
    """
    if not agent:
        return "HTTP_DIRECT"

    ag = agent.upper()

    # Canaux agents identifies
    _CHANNEL_MAP = {
        "CLAUDE": "STDIO_CLAUDE",
        "GEMINI": "GEMINI_OAUTH",
        "GEMINI_HEADLESS": "GEMINI_API",
        "CLINE": "CLINE_MCP",
        "INSPECTOR": "INTERNAL_HUB",
        "HUB": "INTERNAL_HUB",
        "BRIDGE": "STDIO_CLAUDE",
        "SERVICES": "INTERNAL_HUB",
        "MASTER_TOKEN": "HTTP_DIRECT",
        "LOCAL": "HTTP_DIRECT",
        "COLLAB_BROKER": "INTERNAL_HUB",
        "CLAUDE_CLI": "STDIO_CLAUDE",
        "NETCFG": "CLINE_MCP",
        "CODEX": "CODEX_MCP",
    }

    if ag in _CHANNEL_MAP:
        return _CHANNEL_MAP[ag]

    # Fallback : analyse du user-agent si request disponible
    if request:
        ua = (request.headers.get("User-Agent", "") or "").lower()
        if "stdio" in ua or "bridge" in ua:
            return "STDIO_CLAUDE"
        if "gemini-cli" in ua or "gemini_cli" in ua:
            return "GEMINI_OAUTH"
        if "cline" in ua:
            return "CLINE_MCP"

    return "HTTP_DIRECT"


def _init_network_log():
    try:
        with sqlite3.connect(str(DB), timeout=10) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS network_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL, channel TEXT NOT NULL,
                    direction TEXT NOT NULL, tool TEXT, method TEXT,
                    provider TEXT, model TEXT, agent TEXT, ring INTEGER,
                    latency_ms REAL, status TEXT,
                    payload_in TEXT, payload_out TEXT,
                    meta TEXT, client_ip TEXT, session_id TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nl_ts ON network_log(ts DESC)")
            conn.commit()
    except Exception as e:
        logger.error(f"network_log init: {e}")


# Cache de resolution port source -> process. `psutil.net_connections()` coute
# 50-200 ms : a 5 requetes/min c'est negligeable, mais un flood ne doit pas
# transformer le journal en goulot. Une resolution au plus toutes les 60 s.
_ORIGINE_CACHE: dict = {"ts": 0.0, "par_port": {}}
_ORIGINE_INTERVALLE_S = 60.0


# Registre du superviseur : nom de service <- pid. Cache 120 s, l'appel se faisant
# sur le chemin SYNCHRONE du log (un superviseur lent ne doit pas retarder une
# reponse HTTP). Cf. tools/forge_patch_hub_service_par_pid.py.
_SERVICES_CACHE: dict = {"ts": 0.0, "par_pid": {}, "erreur": None}
_SERVICES_TTL_S = 120.0


def _service_du_pid(pid: int) -> str:
    """Nom du service qui porte ce PID, demande a l'organe qui l'a lance.

    Un PID n'est pas une identite : il est reattribue a chaque redemarrage (mesure
    2026-08-04, 18372 -> 18688 pour le meme service). Le superviseur, lui, tient
    des noms stables. On les lui DEMANDE plutot que de les deduire.

    Rend le nom, "inconnu" (PID vivant mais pas un service declare) ou
    "illisible:<motif>" — ne jamais confondre les trois.
    """
    # BOMBE TROUVEE 2026-08-20 (pyflakes) : `_json` etait utilise ligne ~329 sans
    # jamais etre importe DANS cette fonction — les `import json as _json` du
    # fichier sont tous locaux a d'autres fonctions, donc invisibles ici. Meme
    # classe que l'incident du 19/08 (`_gs` ligne 160, import ligne 166), mais en
    # PIRE : le NameError tombait dans le `try` ci-dessous et etait avale, donc le
    # cache pid->nom de service ne se remplissait JAMAIS et la fonction rendait
    # toujours "illisible". Un capteur mort qui se presente comme vivant.
    import json as _json
    import time as _t
    import urllib.request as _u

    cache = _SERVICES_CACHE
    if _t.time() - cache["ts"] > _SERVICES_TTL_S:
        cache["ts"] = _t.time()
        try:
            with _u.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=1.5) as _r:
                _d = _json.loads(_r.read())
            cache["par_pid"] = {
                s.get("pid"): nom
                for nom, s in (_d.get("services") or {}).items()
                if s.get("pid")
            }
            cache["erreur"] = None
        except Exception as _e:  # noqa: BLE001
            cache["erreur"] = type(_e).__name__
    if cache["erreur"] and not cache["par_pid"]:
        return "illisible:" + cache["erreur"]
    return cache["par_pid"].get(pid, "inconnu")


def _origine_appelant(port: int) -> dict:
    """Qui appelle, vu depuis le systeme. Rend le MOTIF quand on ne peut pas voir.

    Mesure 2026-08-04 : 114 406 rejets ERR:401 (44 % du trafic du hub), ~5/min au
    timer depuis 127.0.0.1, et aucun moyen de savoir qui appelle car le journal
    n'enregistrait ni en-tete, ni charge, ni port source.

    Trois etats, jamais deux : « pas trouve » et « pas pu regarder » ne sont pas la
    meme chose, et les confondre est precisement ce qui a rendu cette anomalie
    invisible.
    """
    if not port:
        return {}
    import time as _t

    cache = _ORIGINE_CACHE
    if port in cache["par_port"]:
        return cache["par_port"][port]
    maintenant = _t.time()
    # refroidissement arme UNIQUEMENT sur succes : le poser avant la tentative
    # transformait le moindre echec en silence de 60 s, donc en identification
    # jamais aboutie (mesure 2026-08-04). Tant qu'on ne sait pas QUI appelle,
    # chaque rejet redonne une chance ; des qu'on le sait, le cache par port
    # rend le cout nul.
    if cache.get("connu") and maintenant - cache["ts"] < _ORIGINE_INTERVALLE_S:
        return {"origine": "non_resolue", "raison": "cache_refroidissement"}
    try:
        import psutil as _ps
    except Exception:
        cache["ts"] = maintenant  # psutil absent : inutile de reessayer en boucle
        cache["connu"] = True
        return {"origine": "illisible", "raison": "psutil_absent"}
    try:
        trouve = None
        for _c in _ps.net_connections(kind="inet"):
            if _c.laddr and _c.laddr.port == port and _c.pid:
                trouve = _c.pid
                break
        if trouve is None:
            # Requete breve : la connexion peut deja etre fermee, port recycle.
            return {"origine": "non_resolue", "raison": "connexion_fermee"}
        _p = _ps.Process(trouve)
        info = {"origine": "resolue", "pid": trouve, "process": _p.name()}
        try:
            info["cmdline"] = " ".join(_p.cmdline())[:200]
        except Exception:
            info["cmdline"] = "<illisible: autre compte>"
        try:
            info["compte"] = _p.username()
        except Exception:
            info["compte"] = "<illisible>"
        # Le nom SURVIT au redemarrage, le PID non : c'est lui qu'on veut voir
        # dans le journal, et lui que le raisonnement doit manipuler.
        try:
            info["service"] = _service_du_pid(trouve)
        except Exception as _e:  # noqa: BLE001
            info["service"] = "illisible:" + type(_e).__name__
        cache["par_port"][port] = info
        cache["ts"] = maintenant
        cache["connu"] = True
        if len(cache["par_port"]) > 200:
            cache["par_port"].clear()
        return info
    except Exception as _e:  # noqa: BLE001
        return {"origine": "illisible", "raison": type(_e).__name__}


def _session_courante(request=None) -> "str | None":
    """Identifiant de session pour `network_log.session_id`.

    Mesure 2026-08-12 : la colonne existait, `_write_db` inserait deja
    `event.get("session_id")` — mais l'event construit ici n'a JAMAIS porte cette
    clef. Resultat : **0 ligne remplie sur 62 962**, donc aucune trajectoire
    extractible, et le graphe de dependances du routeur JIT (`tool_scope`) sans
    matiere.

    Deux sources, dans cet ordre :
      1. l'en-tete `X-Session-Id` que le handler lit deja (client-driven) ;
      2. a defaut, le trace courant du ContextVar — `session_trace_id()` chaine
         deja les appels rapproches d'une meme session/agent en un flow correle,
         et le commentaire du handler affirme que tous les sinks in-process le
         lisent sans param. On ne FABRIQUE donc rien : on inscrit la correlation
         qui etait deja calculee et jetee.
    Rend None si aucune des deux n'est disponible — une colonne vide reste
    preferable a un identifiant invente.
    """
    if request is not None:
        try:
            # En-tetes Starlette insensibles a la casse : une seule lecture suffit
            # (la seconde, `X-Session-ID`, ne pouvait rien trouver de plus).
            sid = request.headers.get("X-Session-Id", "")
            if sid:
                return sid
        except Exception as e:  # noqa: BLE001
            logger.debug("session_id: en-tete illisible (%s)", type(e).__name__)
    try:
        from nokido_agent.app.forge_trace_context import get_trace_id

        tid = get_trace_id()
        return tid or None
    except Exception as e:  # noqa: BLE001
        logger.debug("session_id: trace indisponible (%s)", type(e).__name__)
        return None


def _log_network(
    direction: str,
    method: str = None,
    tool: str = None,
    agent: str = None,
    ring: int = None,
    latency_ms: float = None,
    status: str = None,
    payload_in: str = None,
    payload_out: str = None,
    client_ip: str = None,
    channel: str = None,
    request=None,
):
    # FILTRE BRUIT : keepalive poll local -> silencieux (couvre IN et OUT)
    # "local" = daemon interne (gemini_poll_daemon, keepalive). Info nulle, 61% du volume.
    if agent in ("local",) and (tool in ("poll", None)) and (latency_ms or 0) < 5:
        return {}
    ts = _dt.now().isoformat(timespec="milliseconds")
    # Résolution du canal de provenance
    _channel = channel or _resolve_channel(agent, request)
    # Métadonnées enrichies selon le canal
    _channel_meta = {}
    if _channel == "GEMINI_OAUTH" and request:
        # Read OAuth account dynamically from ~/.gemini/google_accounts.json
        # (was hardcoded before — leaked the maintainer's personal gmail).
        try:
            import json as _j  # noqa: PLC0415
            from pathlib import Path as _P  # noqa: PLC0415

            _gconf = _P.home() / ".gemini" / "google_accounts.json"
            if _gconf.exists():
                _gdata = _j.loads(_gconf.read_text(encoding="utf-8"))
                _channel_meta["oauth_account"] = _gdata.get("active", "<unknown>")
            else:
                _channel_meta["oauth_account"] = "<not-configured>"
        except Exception:
            _channel_meta["oauth_account"] = "<read-failed>"
        _channel_meta["auth_type"] = "oauth2_personal"
    elif _channel == "GEMINI_API":
        _channel_meta["auth_type"] = "api_key"
    elif _channel == "STDIO_CLAUDE":
        _channel_meta["bridge"] = "mcp_stdio_bridge"
    elif _channel == "CLINE_MCP":
        _channel_meta["client"] = "vscode_cline"
    elif _channel == "HTTP_DIRECT" and request is not None:
        # Seul canal ou l'appelant n'est identifie par AUCUN en-tete : c'est
        # donc le seul ou il faut demander au systeme qui parle.
        try:
            _cli = getattr(request, "client", None)
            _port = getattr(_cli, "port", None) if _cli else None
            if _port:
                _channel_meta["port_source"] = _port
                _channel_meta.update(_origine_appelant(_port))
        except Exception as _e:  # noqa: BLE001
            _channel_meta["origine"] = "illisible"
            _channel_meta["raison"] = type(_e).__name__
    # Extraire tokens depuis payload_out LLM si disponibles
    _tokens_in, _tokens_out, _model, _provider = 0, 0, None, None
    if payload_out and tool in (
        "ask",
        "route_task",
        "research_agent",
        "trigger_autonomous_evolution",
    ):
        try:
            import json as _j

            _po = _j.loads(payload_out[:2000])
            if isinstance(_po, dict):
                _tokens_in = _po.get("prompt_tokens", _po.get("tokens_in", 0)) or 0
                _tokens_out = _po.get("completion_tokens", _po.get("tokens_out", 0)) or 0
                _model = _po.get("model") or None
                _provider = _po.get("provider") or None
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _n = getattr(_log_network, "_pertes_payload", 0) + 1
            _log_network._pertes_payload = _n
            if _n == 1 or _n % 200 == 0:
                _lg.getLogger("forge.hub").warning(
                    "[network_log] payload illisible (%s: %s) — %d fois | consequence: "
                    "tokens, modele et provider restent a leur defaut, la comptabilite "
                    "d'usage SOUS-ESTIME le trafic reel",
                    type(e).__name__, str(e)[:80], _n)
    event = {
        "ts": ts,
        "channel": _channel,
        "direction": direction,
        "method": method,
        "tool": tool,
        "agent": agent,
        "ring": ring,
        "latency_ms": latency_ms,
        "status": status,
        "payload_in": (payload_in or "")[:800],
        "payload_out": (payload_out or "")[:800],
        "client_ip": client_ip,
        "channel_meta": _channel_meta,
        "tokens_in": _tokens_in,
        "tokens_out": _tokens_out,
        "model": _model,
        "provider": _provider,
        "session_id": _session_courante(request),
    }
    threading.Thread(target=_write_db, args=(event,), daemon=True).start()
    _sse_broadcast(event)

    # Bus centralise
    try:
        from nokido_agent.app.forge_network_logger import Direction, NetworkChannel, net_log

        _chan_map = {"IN": Direction.IN, "OUT": Direction.OUT}
        # Mapper le canal string vers enum NetworkChannel
        _nc_map = {
            "STDIO_CLAUDE": NetworkChannel.STDIO_CLAUDE,
            "GEMINI_OAUTH": NetworkChannel.GEMINI_OAUTH,
            "GEMINI_API": NetworkChannel.GEMINI_API,
            "CLINE_MCP": NetworkChannel.CLINE_MCP,
            "HTTP_DIRECT": NetworkChannel.HTTP_DIRECT,
            "INTERNAL_HUB": NetworkChannel.INTERNAL_HUB,
            "CLOUD_ANTHROPIC": NetworkChannel.CLOUD_ANTHROPIC,
            "CLOUD_GEMINI": NetworkChannel.CLOUD_GEMINI,
            "CLOUD_MISTRAL": NetworkChannel.CLOUD_MISTRAL,
            "CLOUD_GROQ": NetworkChannel.CLOUD_GROQ,
            "CLOUD_OPENAI": NetworkChannel.CLOUD_OPENAI,
            "STDIO": NetworkChannel.STDIO,
            "HUB": NetworkChannel.HUB,
            "CLOUD": NetworkChannel.CLOUD,
            "INTERNAL": NetworkChannel.INTERNAL,
        }
        _channel_enum = _nc_map.get(_channel, NetworkChannel.HUB)
        net_log(
            _channel_enum,
            _chan_map.get(direction, Direction.IN),
            tool=tool,
            method=method,
            agent=agent,
            ring=ring,
            latency_ms=latency_ms,
            status=status,
            payload_in=payload_in,
            payload_out=payload_out,
            client_ip=client_ip,
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _n = getattr(_log_network, "_pertes", 0) + 1
        _log_network._pertes = _n
        if _n == 1 or _n % 100 == 0:
            _lg.getLogger("forge.hub").error(
                "[network_log] evenement NON journalise (%s: %s) — %d perdu(s) | "
                "consequence: un trou dans la seule source qui dise QUI appelle le "
                "hub ; toute mesure de trafic ou d'identite tiree de ce journal est "
                "alors incomplete", type(e).__name__, str(e)[:80], _n)

    return event


def _write_db(event: dict):
    # Filtre bruit : keepalive local/poll avant tout I/O disque
    if event.get("agent") in ("local",) and event.get("tool") in ("poll", None):
        return
    try:
        with sqlite3.connect(str(DB), timeout=5) as conn:
            conn.execute(
                """
                INSERT INTO network_log
                (ts,channel,direction,tool,method,provider,model,agent,ring,
                 latency_ms,status,payload_in,payload_out,meta,client_ip,session_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    event.get("ts"),
                    event.get("channel", "HUB"),
                    event.get("direction"),
                    event.get("tool"),
                    event.get("method"),
                    event.get("provider"),
                    event.get("model"),
                    event.get("agent"),
                    event.get("ring"),
                    event.get("latency_ms"),
                    event.get("status"),
                    event.get("payload_in", "")[:2000],
                    event.get("payload_out", "")[:2000],
                    json.dumps(
                        {**(event.get("meta") or {}), "channel_meta": event.get("channel_meta", {})}
                    ),
                    event.get("client_ip"),
                    event.get("session_id"),
                ),
            )
            conn.commit()
    except Exception as e:
        logger.debug(f"DB write: {e}")


def _zmq_nudge_embed(n: int = 1) -> None:
    """Reveille le daemon d'embedding apres INSERT — en VERIFIANT qu'on est ecoute.

    L'ancienne version poussait en fire-and-forget sur :5557. Mesure du 2026-08-05 :
    ce port est ferme depuis juin, et un PUSH ZMQ vers un port ferme est ACCEPTE sans
    exception — donc le `except: pass` ne se declenchait JAMAIS et le hub croyait
    avoir reveille l'embedder. Les chunks inseres restaient sans vecteur, en silence.
    """
    try:
        from nokido_agent.app.forge_nudge_embed import nudge_embed

        _tid = "system"
        try:
            from nokido_agent.app.forge_trace_context import get_trace_id

            _tid = get_trace_id()
        except Exception:  # muet-ok : sans trace_id on garde "system", pas de perte
            pass
        nudge_embed(n, source="nokido_hub",
                    payload={"cmd": "nudge", "n": n, "trace_id": _tid})
    except Exception as _e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.hub").warning(
            "[hub] reveil d'embedding impossible (%s: %s) | consequence: les chunks "
            "qui viennent d'etre inseres resteront sans vecteur jusqu'au prochain "
            "passage du drain", type(_e).__name__, str(_e)[:90])


def _sse_broadcast(event: dict):
    data = f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
    dead = []
    with _SSE_LOCK:
        for q in _SSE_CLIENTS:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                _SSE_CLIENTS.remove(q)
            except ValueError:
                pass


def _sse_trace(phase: str, abonnes: int, flux: str = "network") -> None:
    """Journalise l'ABONNEMENT SSE (ouverture/fermeture), JAMAIS la diffusion.

    Le SSE etait l'angle mort TOTAL du journal : 0 ligne sur 228 955 evenements
    au 2026-08-12, alors que `_sse_broadcast` pousse a chaque evenement.
    Journaliser la DIFFUSION bouclerait : `_log_network` appelle
    `_sse_broadcast`. On ne trace donc que les deux bords -- la ou vit la fuite.
    """
    try:
        from nokido_agent.app.forge_network_logger import Direction, NetworkChannel, net_log

        net_log(NetworkChannel.INTERNAL_HUB, Direction.OUT, tool=f"sse.{phase}",
                agent="SSE", status="ok",
                payload_out=f"flux={flux} abonnes={abonnes}")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.hub").warning(
            "[sse] abonnement %s NON journalise (%s: %s) | consequence: le flux "
            "SSE redevient un angle mort et une fuite d'abonnes repasse inapercue",
            phase, type(e).__name__, str(e)[:80])


# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬
# SECURITY
# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬

# Tokens par agent — backed by DPAPI machine vault via forge_secrets.
# Convention vault : FORGE_TOKEN_<AGENT>. Voir tools/forge_vault_seed_agent_tokens.py
# pour la migration initiale. Hub fail-closed si un agent attendu n'a pas son
# token vault (auth refusée → ring 4 / public-only).
_AGENT_LIST = (
    "ZCODE",
    "CLAUDE",
    "GEMINI",
    "CODEX",
    "CLINE",
    "BRIDGE",
    "COLLAB_BROKER",
    "GEMINI_HEADLESS",
    "CLAUDE_CLI",
    "NETCFG",
    "TRAY",
    "SERVICES",
    "LLAMACPP",
    "CLAUDE_DESKTOP",
    "VSCODE",
    "LMSTUDIO",
    "ANTIGRAVITY",
    "DSPY_ROUTER",
    "TASK_EXECUTOR",  # exec autonome (ring2) : charge FORGE_TOKEN_TASK_EXECUTOR du vault au boot
)


def _agents_a_charger() -> tuple:
    """Identites dont on charge le jeton : UNION du tuple fige et du registre VIVANT.

    `_AGENT_LIST` reste un PLANCHER (aucune regression si le registre est
    illisible), mais il n'est plus la source : `config/agent_identities.json` l'est.
    Mesure du 2026-08-05 : ORGAN_PULSE, COAGULATION et RESCUE etaient declarees au
    registre, leurs jetons provisionnes au coffre, et le hub leur rendait 401 parce
    que leur nom manquait au tuple -- une identite invisible au chargeur est une
    identite anonyme, ce que la directive owner interdit explicitement.

    Un registre illisible se DIT (log WARNING) : sans ca, « je n'ai pas pu lire »
    passerait pour « il n'y a rien de plus a charger ».
    """
    import json as _json
    import logging as _logging

    noms = list(_AGENT_LIST)
    registre = Path(__file__).resolve().parent.parent / "config" / "agent_identities.json"
    try:
        declarees = (_json.loads(registre.read_text(encoding="utf-8")) or {}).get("agents") or {}
    except Exception as exc:  # noqa: BLE001
        _logging.getLogger("forge.hub").warning(
            "[identite] registre %s ILLISIBLE (%s: %s) -- repli sur la liste figee "
            "(%d agents) ; consequence: toute identite declaree hors de ce tuple "
            "recevra 401 et comptera comme trafic anonyme",
            registre.name, type(exc).__name__, str(exc)[:80], len(noms))
        return tuple(noms)
    ajoutes = [a for a in declarees if a not in noms]
    if ajoutes:
        _logging.getLogger("forge.hub").info(
            "[identite] %d identite(s) chargee(s) depuis le registre en plus du "
            "tuple fige : %s", len(ajoutes), ", ".join(sorted(ajoutes)))
    return tuple(noms + ajoutes)


def _load_agent_tokens() -> dict[str, str]:
    """Charge les tokens agents depuis le coffre DPAPI au boot.
    Fail-closed : un agent sans token en vault = pas d'auth (ring 4 par défaut)."""
    try:
        _app_path = (
            str(ROOT / "app")
            if "ROOT" in globals()
            else str(Path(__file__).resolve().parent.parent / "app")
        )
        if _app_path not in sys.path:
            sys.path.insert(0, _app_path)
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore
    except Exception as exc:  # pragma: no cover - guard
        import logging

        logging.getLogger("forge.hub").error(f"forge_secrets import failed: {exc}")
        return {}

    tokens: dict[str, str] = {}
    missing: list[str] = []
    for agent in _agents_a_charger():
        val = get_secret(f"FORGE_TOKEN_{agent}")
        if val:
            tokens[agent] = val
        else:
            missing.append(agent)
    if missing:
        import logging

        logging.getLogger("forge.hub").warning(
            f"Vault missing agent tokens: {missing}. "
            f"Run: LAFORGE_PYTHON tools/forge_vault_seed_agent_tokens.py"
        )
    return tokens


_AGENT_TOKENS = _load_agent_tokens()
_boot_probe("agent tokens charges (vault DPAPI)")

# ── JWT Router ───────────────────────────────────────────────────────────
try:
    import os as _jos
    import sys as _jsys

    _japp = str(_jos.path.join(_jos.path.dirname(__file__), "..", "app"))
    if _japp not in _jsys.path:
        _jsys.path.insert(0, _japp)
    from nokido_agent.app.forge_jwt_router import AGENT_PRM, forge_frame_token, verify_frame_token
    from nokido_agent.app.forge_payload_cache import get as _payload_get
    from nokido_agent.app.forge_payload_cache import init as _payload_init

    _payload_init()  # pré-forge les tokens fréquents au boot
    _JWT_AVAILABLE = True
except Exception as _je:
    _JWT_AVAILABLE = False

    def forge_frame_token(*a, **kw):
        return ""

    def verify_frame_token(*a, **kw):
        return None

    def _payload_get(*a, **kw):
        return ""

    AGENT_PRM = {}

# Ring par agent — minimise le payload tools injecté dans le contexte LLM.
# Claude/Gemini sont des clients : leurs outils natifs couvrent write/run.
# Nokido = intel (RAG, search, ask, route). Cline = exécution (ring 1).
_AGENT_RING: dict = {
    "LAFORGE_CLI": 1,  # CLI direct user (tools/llama_cli.py) — surface interne Nokido, pas LLM externe
    "CLAUDE_CLI": 2,  # 11 tools : query/rag/hub/read/ask/web/route/research/biblio/task/event
    "CLAUDE": 1,  # Desktop cowork + Claude Code (.mcp.json) — élevé ring 1 (2026-06-11, GO user)
    "CLAUDE_HOOK": 4,  # hook : 3 tools publics seulement
    "GEMINI": 3,  # 6 tools : read/web_search/ask/route_task/research_agent/biblio
    "GEMINI_HOOK": 4,
    "GEMINI_HEADLESS": 3,
    "COPILOT": 3,  # GitHub Copilot CLI (BYOK + MCP .github/mcp.json) — externe collab, comme Gemini
    "COPILOT_CLI": 3,
    "COPILOT_HOOK": 4,
    "CODEX": 2,
    "TRAY": 4,
    "SERVICES": 4,
    "CLINE": 1,  # 15 tools : + run/auto_test/trigger/crawl
    "BRIDGE": 1,
    "COLLAB_BROKER": 2,
    "NETCFG": 0,  # netcfg-agent : accès complet
    "LLAMACPP": 0,  # llama-server :8091 : accès complet (agent local)
    "WATCH_EXECUTOR": 1,  # ChainExecutor/veille daemon — job interne de confiance (sinon défaut ring 4 -> SearXNG/crawl/research refusés)
    "INTERNAL_WORKER": 1,  # worker interne détaché générique (fallback jobs)
}

# ── Registre identité×canal×ring LIVE (2026-06-11, roadmap-aware) ─────────────
# _AGENT_RING ci-dessus = SEED hardcodé (défauts). Source LIVE = config/
# agent_identities.json : édité (GUI #10 / à la main) -> rechargé sur mtime SANS
# restart. Schéma extensible (agent -> {ring, channel, transport, machine}) : sert
# aussi la traçabilité read/write DB (#7-9) et le futur multi-machine (Tailscale).
_AGENT_IDENTITY_STORE = ROOT / "config" / "agent_identities.json"
_CHANNEL_SEED = {
    "BRIDGE": ("STDIO_CLAUDE", "stdio"), "CLAUDE": ("STDIO_CLAUDE", "http"),
    "CLAUDE_CLI": ("STDIO_CLAUDE", "cli"), "CLAUDE_HOOK": ("STDIO_CLAUDE", "hook"),
    "GEMINI": ("GEMINI_OAUTH", "cli"), "GEMINI_HEADLESS": ("GEMINI_OAUTH", "cli"),
    "GEMINI_HOOK": ("GEMINI_OAUTH", "hook"), "COPILOT": ("HTTP_DIRECT", "cli"),
    "COPILOT_CLI": ("HTTP_DIRECT", "cli"), "COPILOT_HOOK": ("HTTP_DIRECT", "hook"),
    "CODEX": ("HTTP_DIRECT", "cli"), "CLINE": ("CLINE_MCP", "mcp"),
    "LAFORGE_CLI": ("INTERNAL_HUB", "cli"), "NETCFG": ("INTERNAL_HUB", "mcp"),
    "LLAMACPP": ("INTERNAL_HUB", "local"), "COLLAB_BROKER": ("INTERNAL_HUB", "internal"),
    "TRAY": ("INTERNAL_HUB", "local"), "SERVICES": ("INTERNAL_HUB", "internal"),
    "WATCH_EXECUTOR": ("INTERNAL_HUB", "internal"), "INTERNAL_WORKER": ("INTERNAL_HUB", "internal"),
}
_ring_cache: dict = {"mtime": -1.0, "rings": {}, "meta": {}}


def _seed_identity_store() -> None:
    """Écrit le store JSON depuis le SEED _AGENT_RING si absent (1er boot)."""
    try:
        _AGENT_IDENTITY_STORE.parent.mkdir(parents=True, exist_ok=True)
        agents = {}
        for name, ring in _AGENT_RING.items():
            ch, tr = _CHANNEL_SEED.get(name, ("HTTP_DIRECT", "http"))
            agents[name] = {"ring": ring, "channel": ch, "transport": tr, "machine": "local"}
        _AGENT_IDENTITY_STORE.write_text(
            json.dumps({"_doc": "Registre LIVE identite x canal x ring x machine. Edite (GUI #10/main) -> reload mtime, PAS de restart. ring 0=plus de droits.",
                        "version": 1, "agents": agents}, indent=2, ensure_ascii=False),
            encoding="utf-8")
    except Exception as _e:
        logger.warning(f"[ring] seed store echec: {_e}")


def _agent_ring_map() -> dict:
    """Map agent->ring LIVE depuis le store JSON (reload sur changement mtime)."""
    try:
        if not _AGENT_IDENTITY_STORE.exists():
            _seed_identity_store()
        m = _AGENT_IDENTITY_STORE.stat().st_mtime
        if m != _ring_cache["mtime"]:
            data = json.loads(_AGENT_IDENTITY_STORE.read_text(encoding="utf-8"))
            _agents = data.get("agents", {})
            _ring_cache["rings"] = {
                k.upper(): int(v["ring"]) for k, v in _agents.items()
                if isinstance(v, dict) and v.get("ring") is not None
            }
            _ring_cache["meta"] = {k.upper(): v for k, v in _agents.items() if isinstance(v, dict)}
            _ring_cache["mtime"] = m
            logger.info(f"[ring] store recharge LIVE ({len(_ring_cache['rings'])} agents)")
    except Exception as _e:
        logger.debug(f"[ring] map load skip: {_e}")
    return _ring_cache["rings"]


def _agent_ring(agent: str, default: int) -> int:
    """Ring LIVE : store JSON (reload mtime) -> sinon SEED _AGENT_RING -> sinon défaut.
    Permet la réattribution de ring SANS restart (édition store / GUI #10)."""
    return _agent_ring_map().get((agent or "").upper(), _AGENT_RING.get(agent, default))


def _agent_meta(agent: str) -> tuple:
    """(channel, transport, machine) LIVE depuis le store identité, sinon SEED.
    Sert l'ActorContext (#7) : identité PRÉCISE par surface sur chaque action."""
    _agent_ring_map()  # garantit chargement/reload du cache (rings + meta)
    m = _ring_cache.get("meta", {}).get((agent or "").upper())
    if isinstance(m, dict):
        return (m.get("channel") or "HTTP_DIRECT", m.get("transport") or "http",
                m.get("machine") or "local")
    ch, tr = _CHANNEL_SEED.get((agent or "").upper(), ("HTTP_DIRECT", "http"))
    return ch, tr, "local"


def _ring_local_sans_preuve() -> tuple[int, str]:
    """Ring accorde a un appel LOCAL quand le hub n'a aucun jeton configure.

    FAIL-CLOSED SUR LE PRIVILEGE — revue defensive LOCAL-IPC du 2026-09-18.

    Cette branche rendait `ring 0` (SYSTEM) a toute requete locale des lors que
    le jeton du hub etait vide. Le mode « pas de jeton configure » est documente
    et assume — mais ACCEPTER un appel sans preuve n'est pas la meme chose que
    lui accorder l'ADMINISTRATION. La route reste ouverte, le privilege ne l'est
    plus.

    Ce n'est pas theorique : un jeton vide n'arrive pas qu'en installation neuve.
    Un coffre illisible depuis le compte qui lance le hub rend la MEME valeur
    vide — `RESOURCE_UNAVAILABLE` traite comme `DISABLED_BY_POLICY`, la confusion
    que la constitution semantique interdit. Le corps atteint le loopback depuis
    plusieurs comptes ; la panne de lecture devenait alors une elevation.

    Le durcissement EXISTAIT DEJA plus bas, sur le repli legacy : « une identite
    hors registre retombe sur 3, JAMAIS 0 ». Il n'avait pas ete applique ici. On
    reprend le meme plancher.

    Mesure du jour : le jeton est PRESENT au coffre, donc cette fonction n'est
    pas appelee et le changement n'a AUCUN effet en fonctionnement normal. Il ne
    mord que dans le cas degrade — exactement la ou il faut.
    """
    logger.warning(
        "[identite] jeton du hub VIDE : appel local accepte SANS preuve, au ring 3 "
        "(isole) et non plus au ring 0. Si ce n'est pas un mode de developpement "
        "voulu, c'est une lecture de coffre qui a echoue — la difference se lit "
        "dans le journal du coffre, pas ici.")
    return 3, "local_sans_preuve"


def _exiger_identite(request):
    """Route d'ORGANE : identite prouvee exigee (jeton propre, SERVICES, jeton de capacite).

    Chantier d'authentification (2026-09-24). Ces routes etaient ouvertes parce que leurs
    appelants n'envoyaient rien ; ils presentent desormais le jeton rendu par
    `forge_hub_client.entetes_organe` (jamais le maitre). La decision reste
    `_resolve_ring` -- aucune politique de plus : ring < 0 = non authentifie = 401.
    Rend None si l'appel est autorise (et pose `request.state.principal`), sinon la reponse.
    """
    ring, qui = _resolve_ring(request)
    if ring < 0:
        from starlette.responses import JSONResponse as _JRi

        return _JRi({"ok": False, "error": "unauthorized",
                     "detail": "identite d'organe requise (%s)" % qui},
                    status_code=401, headers={"WWW-Authenticate": 'Bearer realm="nokido-hub"'})
    request.state.principal = qui
    # Le ring resolu voyage avec le principal : une route qui gradue ses droits (eviction
    # deleguee, 2026-09-28) le lit ici au lieu de re-resoudre -- une seconde resolution
    # doublerait la capture du videur.
    request.state.ring = ring
    return None


def _resolve_ring(request) -> tuple[int, str]:
    auth = request.headers.get("Authorization", "")
    # LaForge-Agent-Name = canonique ORG-SCOPÉ (RFC 6648 §3 anti-collision, directive
    # ARCHITECTURE_IDENTITE 2026-06-16) ; Agent-Name (interim générique) + X-Agent-Name (legacy) = fallbacks transition.
    agent_hdr = (request.headers.get("LaForge-Agent-Name") or request.headers.get("Agent-Name")
                 or request.headers.get("X-Agent-Name") or "").upper().strip()
    client = request.client.host if request.client else "unknown"
    local = client in ("127.0.0.1", "::1", "localhost")

    if not HUB_TOKEN:
        return _ring_local_sans_preuve() if local else (-1, "no_token")

    if not auth.lower().startswith("bearer "):
        return -1, "no_auth"
    token = auth[7:].strip()

    # ── Short-lived CapabilityToken check ──────────────────────────────────────
    is_cap = False
    parts = token.split(".")
    if len(parts) in (2, 3):
        try:
            import base64
            import json
            payload_b64 = parts[0]
            pad = "=" * (-len(payload_b64) % 4)
            raw_json = base64.urlsafe_b64decode(payload_b64 + pad)
            payload = json.loads(raw_json)
            if "sub" in payload and "ring" in payload and "exp" in payload:
                is_cap = True
        except Exception as _e_cap:
            # CHAINE D'AUTORITE. Un jeton indecodable retombe en « bearer
            # brut » sans que rien ne le dise : le silence transforme une
            # ANOMALIE DE CREDENTIAL en classement par defaut.
            logger.debug("classement capability impossible: %s",
                         type(_e_cap).__name__)

    if is_cap:
        try:
            import hashlib
            from nokido_agent.app.forge_integrity import CapabilityToken, get_manager
            mgr = get_manager()
            cap_token = CapabilityToken.decode(token, mgr._secret)
            _ident = {
                "agent": cap_token.sub,
                "ring": int(cap_token.ring),
                "via": "capability_token",
                "channel": "HTTP_DIRECT",
                "transport": "http",
                "token_h": hashlib.sha256(token.encode()).hexdigest()[:16]
            }
            try:
                from nokido_agent.app.forge_videur import capture as _vcapture
                _vcapture(_ident, "_resolve_ring")
            except Exception:
                pass
            return int(cap_token.ring), cap_token.sub
        except Exception as e:
            logger.warning(f"CapabilityToken verification failed: {e}")
            return -1, "expired_or_invalid_capability_token"

    # ── VIDEUR : SOURCE UNIQUE de résolution identité×ring (forge_videur) ──────
    # Tue l'incohérence multi-chemins (même appelant vu ring 1 ET ring 4 selon le
    # tool). Capture DYNAMIQUE de l'identité + log CRYPTÉ (DPAPI, token hashé) —
    # directive user. Fallback = logique legacy (ne JAMAIS bloquer l'auth sur un
    # bug du videur). Changement de ring = via forge_videur.propose_ring_change (garde-fous).
    # LIE AVANT LE `try` — 2026-09-21, mesure P1-O.
    #
    # DEUX CAUSES d'entree dans le repli, aux consequences OPPOSEES :
    #     l'IMPORT de forge_videur echoue -> `capture` INDISPONIBLE
    #     `resolve_identity` LEVE         -> `capture` DISPONIBLE
    #
    # Sans cette liaison prealable, le repli leverait `NameError` en tentant
    # de capturer apres un import echoue : la TRACE deviendrait elle-meme une
    # seconde panne, sur le chemin de secours. `None` rend l'indisponibilite
    # TESTABLE au lieu d'explosive.
    _vcapture = None
    try:
        from nokido_agent.app.forge_videur import resolve_identity as _vresolve, capture as _vcapture

        # validité : token DOIT être un dérivé connu OU le master (sinon bad_token).
        _valid = hmac.compare_digest(token.encode(), HUB_TOKEN.encode()) or any(
            hmac.compare_digest(token.encode(), str(_t).encode()) for _t in _AGENT_TOKENS.values()
        )
        if not _valid:
            logger.warning(f"Token invalide agent={agent_hdr} ip={client}")
            return -1, "bad_token"
        _ident = _vresolve(agent_hdr, token, local=local, agent_tokens=_AGENT_TOKENS, hub_token=HUB_TOKEN)
        try:
            # ACTEUR/SUJET JUSQU'AU JOURNAL. `resolve_identity` les produit
            # (RFC 8693 : A agit POUR B, A garde son identité) mais `capture`
            # ne recopie que ses champs canoniques. Sans ce passage, A n'existe
            # au journal que fondu dans `via` sous la forme `delegated:<NOM>` —
            # une CHAÎNE, pas un champ : aucun lecteur du journal ne peut
            # demander « qui a agi » sans parser du texte. La distinction
            # mourait entre le point qui la CALCULE et celui qui l'ENREGISTRE.
            # `capture` pose `extra` EN PREMIER puis écrase avec les canoniques :
            # ce passage ne peut donc pas falsifier agent/ring/tool/token_h.
            _sup = {_k: _ident[_k] for _k in ("acteur", "sujet") if _ident.get(_k)}
            # LE MAITRE EST UNE PREUVE DE POSSESSION, PAS UNE PREUVE D'IDENTITE.
            # Mesuré le 2026-09-21 : le plancher anti-spoof ne teste que
            # `via == "header"`, donc un porteur du maître déclarant
            # `X-Agent-Name: <N>` obtient le ring REGISTRE de <N> (4 -> 1 dans
            # la mesure) et le journal l'attribue à <N>. Rien ne disait qu'un
            # porteur du maître était derrière.
            # On ne referme pas ce chemin ici — le maître est le canal des
            # lanceurs de l'owner, le plafonner est une décision de politique.
            # On le rend ATTRIBUABLE. L'acteur reste INCONNU : on écrit sa
            # CLASSE, préfixée comme `delegated:<nom>` l'est déjà, au lieu de
            # fabriquer une identité pour combler le trou (UNKNOWN != NO).
            if not _sup and _ident.get("via") == "master_token":
                _sup = {"acteur": "classe:porteur_maitre",
                        "sujet": _ident.get("agent"),
                        "sujet_prouve": False}
            _vcapture(_ident, "_resolve_ring", _sup or None)  # log crypté dynamique
        except Exception:  # noqa: BLE001
            pass
        return int(_ident["ring"]), _ident["agent"]
    except Exception as _ve:  # noqa: BLE001 - videur indispo -> fallback legacy
        logger.warning(f"[videur] fallback resolution legacy: {_ve}")

    # ── FALLBACK legacy (videur indispo) — logique d'origine, inchangée ───────
    def _capturer_repli(_agent: str, _ring, _decision: str) -> None:
        """Rend OBSERVABLE un resultat du repli, QUAND c'est possible.

        INVARIANT (P1-O) : tout resultat produit par le repli doit etre
        capture lorsque l'infrastructure de capture est disponible, sans que
        l'indisponibilite du videur devienne elle-meme bloquante.

        CE QUI N'EST PAS FABRIQUE. Le repli n'a ni `via`, ni `acteur`, ni
        `sujet` -- il ne les a JAMAIS calcules. Les inventer produirait une
        provenance fausse :

            ABSENCE_DE_DONNEE != DONNEE_RECONSTRUITE

        Une absence se voit ; une invention se croit. Seul `via` est pose, et
        il dit exactement ce qui s'est passe : `repli_legacy`.

        BEST-EFFORT STRICT : le repli a deja decide. Journaliser est un effet
        de bord, jamais une condition.
        """
        if _vcapture is None:
            return          # capture indisponible : l'absence reste, pas de 2e panne
        try:
            _vcapture(
                {"agent": _agent or "UNKNOWN", "ring": _ring,
                 "via": "repli_legacy", "token_h": ""},
                "_resolve_ring",
                {"decision": _decision, "chemin": "FALLBACK",
                 "cause": "videur indisponible ou en erreur"},
            )
        except Exception:  # noqa: BLE001
            pass  # muet-ok : une trace qui echoue ne change pas la decision

    if not agent_hdr:
        for _name, _tok in _AGENT_TOKENS.items():
            if hmac.compare_digest(token.encode(), _tok.encode()):
                agent_hdr = _name
                break
    # FAIL-CLOSED : une identite hors registre retombe sur 3 (isolee), JAMAIS 0.
    # Le chemin nominal (forge_videur) defaut a UNTRUSTED ; ce repli defaultait a
    # SYSTEM des lors que l'appel venait de la machine locale.
    expected = _AGENT_TOKENS.get(agent_hdr)
    if expected and hmac.compare_digest(token.encode(), expected.encode()):
        _ring = _agent_ring(agent_hdr, 3)
        _capturer_repli(agent_hdr, _ring, "ALLOW")
        return _ring, agent_hdr
    if hmac.compare_digest(token.encode(), HUB_TOKEN.encode()):
        agent_id = agent_hdr if agent_hdr and agent_hdr != "UNKNOWN" else "MASTER_TOKEN"
        _ring = _agent_ring(agent_id, 3)
        _capturer_repli(agent_id, _ring, "ALLOW")
        return _ring, agent_id
    logger.warning(f"Token invalide agent={agent_hdr} ip={client}")
    _capturer_repli(agent_hdr, None, "DENY")
    return -1, "bad_token"


# Heartbeat par agent Ã¢â‚¬â€� ecrit a chaque appel identifie
_SANDBOX = Path(__file__).resolve().parent.parent / "sandbox"


def _write_agent_presence(agent: str, ring: int, tool: str = None) -> None:
    """Ecrit sandbox/presence_<agent>.seen avec ts+ring+pid+last_tool.

    PRESENCE d'un CLIENT, PAS vitalite d'un organe (mandat owner 2026-07-26 :
    « le heartbeat doit emaner de Nokido, pas des clients »). L'espace
    sandbox/*.heartbeat appartient au CORPS : forge_anatomy_state y fait un
    glob, il comptait donc les CLI (codex, zcode, antigravity -- rances de
    plusieurs semaines) comme des organes morts. La convention
    presence_<agent>.seen etait DEJA attendue par forge_postal.
    facteur_is_online et forge_peer_discovery._is_online, sans personne pour
    l'alimenter : on la nourrit plutot que d'en inventer une autre.
    """
    import os as _os

    try:
        _SANDBOX.mkdir(exist_ok=True)
        hb = _SANDBOX / f"presence_{agent.lower()}.seen"
        # Retrait de l'ancien emplacement : sinon le residu reste dans le
        # glob de l'anatomie et vieillit en silence comme un organe mort.
        try:
            (_SANDBOX / f"{agent.lower()}.heartbeat").unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("forge.hub").warning(
                "[presence] ancien heartbeat de %s NON retire (%s: %s) | consequence: "
                "ce residu reste dans le glob de l'anatomie et vieillit en silence "
                "comme un organe mort", agent, type(e).__name__, str(e)[:80])
        hb.write_text(
            json.dumps(
                {
                    "agent": agent,
                    "ring": ring,
                    "ts": _dt.now().isoformat(),
                    "pid": _os.getpid(),
                    "last_tool": tool,
                }
            ),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.hub").warning(
            "[presence] presence de %s NON ecrite (%s: %s) | consequence: cet agent "
            "sera lu comme ABSENT alors qu'il vient d'appeler le hub",
            agent, type(e).__name__, str(e)[:80])


async def _tool_call(name: str, args: dict, ring: int, agent: str = "HUB", token: str = "") -> str:
    if _HUB_WATCHDOG is not None:
        _HUB_WATCHDOG.ping()
    # ── BYTE ROUTER MIDDLEWARE (session5) ─────────────────────────────────
    try:
        import os as _bros
        import sys as _brsys

        _brapp = str(_bros.path.join(_bros.path.dirname(__file__), "..", "app"))
        if _brapp not in _brsys.path:
            _brsys.path.insert(0, _brapp)

        from nokido_agent.app.forge_byte_router import ByteRouterMiddleware

        name, args = await ByteRouterMiddleware.process(name, args, agent)
    except Exception as _e_br:
        # fail-open ASSUME : l'appel continue NON route. Mais un fail-open
        # muet est indistinguable d'un routage reussi -- on le DIT.
        logger.debug("byte_router fail-open: %s", type(_e_br).__name__)
    # ──────────────────────────────────────────────────────────────────────
    # ── ÉQUIPE FLUX (forge_flow_control) — ADVISORY : mappe chaque appel à son agent de
    # flux (videur/convoyeur/.../aiguilleur) pour l'observabilité du système nerveux.
    # N'ENFORCE PAS (le hub_gate ci-dessous gouverne) — fail-open total, jamais bloquant.
    try:
        from nokido_agent.app.forge_flow_control import route_flow as _route_flow
        _fl = _route_flow(name)
        if _fl.get("role") and _fl["role"] != "aiguilleur":
            logger.debug(f"[flux] {name} -> {_fl['role']} ({_fl.get('organ', '')})")
    except Exception:
        # muet-ok : le flux est observabilite, jamais un point de blocage ;
        # et il alimente deja `logger.debug` juste au-dessus.
        pass
    try:
        # GATE DE GOUVERNANCE PARALLÈLE (forge_hub_gate) — remplace le RBAC
        # séquentiel fail-OPEN. Comble #1 fail-CLOSED, #2 break-glass AUDITÉ,
        # #4 firewall-sur-args, en PARALLÈLE (rbac+ring+switches+firewall via
        # asyncio.gather+to_thread). ByteRouter a déjà réécrit name/args plus haut.
        # Si le gate ORCHESTRATEUR lui-même throw (bug) -> log CRITICAL + fallthrough
        # sur le ring gate du registry (backstop défense-en-profondeur) : jamais de brick.
        try:
            import os as _gos
            import sys as _gsys

            _gapp = str(_gos.path.join(_gos.path.dirname(__file__), "..", "app"))
            if _gapp not in _gsys.path:
                _gsys.path.insert(0, _gapp)
            from nokido_agent.app.forge_hub_gate import resolve as _gate_resolve

            _v = await _gate_resolve(name, args, agent=agent, ring=ring, token=token)
            name, args = _v.name, _v.args
            if not _v.allow:
                logger.warning(f"GATE DENY tool={name} agent={agent}: {_v.deny_reason()}")
                return f"GATE_DENIED: {_v.deny_reason()}"
            if _v.breakglass and any(_d == "OVERRIDE" for _, _d, _ in _v.reasons):
                logger.warning(f"GATE BREAKGLASS override tool={name} agent={agent}")
        except Exception as _gate_e:  # noqa: BLE001 - jamais bricker le hub
            logger.critical(f"GATE orchestrator ERROR (fallthrough -> registry ring gate): {_gate_e}")
        from nokido_agent.app.forge_mcp_registry import get_registry

        res = await get_registry().dispatch(name, args, agent=agent, ring=ring)
        return str(res)
    except Exception as e:
        return f"ERR: {e}"


# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬
# UI HTML Ã¢â‚¬â€� /forge/network v2 (style forge_feed + Graph + Logs)
# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬

NETWORK_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Nokido Hub</title>
<link rel="icon" type="image/svg+xml" href="/static/nokido-favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<!-- Portage design system (passe 1, surface hub :8766) : tokens plats servables
     en 1 segment (la route /static/{fname} refuse l'imbriqué). Liés AVANT le
     <style> inline -> inline gagne, look préservé, tokens design dispos. -->
<link rel="stylesheet" href="/static/laforge-tokens.css">
<link rel="stylesheet" href="/static/laforge-components.css">
<style>
:root{
  /* Convergence design system : les couleurs sont pilotees par laforge-tokens.css
     (lie au-dessus). On NE redefinit plus --bg/--surface/--border/--text/--text-dim/
     --ok/--warn/--err/--orange (le DS les fournit) ; on remappe juste les noms locaux
     restants sur les tokens DS. Resultat : palette unique, violet souverain (#774AFF). */
  --surface2:var(--surface-raised);
  --text-muted:var(--text-dim);
  --primary:var(--purple);--primary-l:var(--purple);--primary-d:var(--purple-dim);
  --claude:rgba(255,151,112,0.2);--claude-t:#ff9770;
  --gemini:rgba(167,199,231,0.2);--gemini-t:#a7c7e7;
  --groq:rgba(192,132,252,0.2);--groq-t:#c084fc;
  --mistral:rgba(96,165,250,0.2);--mistral-t:#60a5fa;
  --hub:rgba(255,214,112,0.2);--hub-t:#ffd670;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',-apple-system,sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column;overflow:hidden;font-size:13px}

/* ── HEADER ── */
header{display:flex;align-items:center;padding:10px 20px;background:rgba(0,0,0,0.3);border-bottom:1px solid var(--border);backdrop-filter:blur(20px);gap:14px;flex-shrink:0;z-index:20}
.logo{font-size:16px;font-weight:700;color:var(--primary);display:flex;align-items:center;gap:8px}
.logo-dot{width:8px;height:8px;border-radius:50%;background:var(--ok);animation:pulse 2s infinite}
.logo-dot.off{background:var(--err);animation:none}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.85)}}
.hmetrics{display:flex;gap:16px;margin-left:auto;align-items:center;flex-wrap:wrap}
.hm{display:flex;flex-direction:column;align-items:center;gap:1px}
.hm-val{font-size:14px;font-weight:600;color:var(--text)}
.hm-lbl{font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px}
.hm-val.cost{color:var(--warn)}
.hm-val.err{color:var(--err)}
.hdiv{width:1px;height:28px;background:var(--border)}

/* ── MOOD BAR ── */
.mood-bar{display:flex;align-items:center;gap:12px;padding:5px 20px;background:rgba(0,0,0,0.2);border-bottom:1px solid var(--border);flex-shrink:0}
.mood-chip{display:flex;align-items:center;gap:5px;padding:2px 8px;border-radius:99px;border:1px solid var(--border);font-size:11px}
.mood-dot{width:6px;height:6px;border-radius:50%}
.mood-v{font-weight:600;color:var(--text)}
.mood-l{color:var(--text-muted)}
.mood-status{margin-left:auto;font-size:11px;font-weight:600;color:var(--ok);padding:2px 10px;border-radius:99px;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.2)}
.mood-status.stress{color:var(--err);background:rgba(239,68,68,.12);border-color:rgba(239,68,68,.2)}
.mood-timeout{font-size:10px;color:var(--text-muted)}

/* ── NAV TABS ── */
nav{display:flex;padding:0 8px;background:rgba(0,0,0,0.15);border-bottom:1px solid var(--border);flex-shrink:0;overflow-x:auto}
.tab{display:flex;align-items:center;gap:6px;padding:9px 14px;cursor:pointer;color:var(--text-muted);border-bottom:2px solid transparent;font-size:12px;font-weight:500;white-space:nowrap;transition:.15s}
.tab:hover{color:var(--text)}
.tab.active{color:var(--primary);border-bottom-color:var(--primary)}
.tab-icon{font-size:13px}

/* ── LAYOUT ── */
main{flex:1;overflow:hidden;display:flex;flex-direction:column}
.panel{flex:1;overflow:hidden;display:none;flex-direction:column}.panel.active{display:flex}

/* ── TOOLBAR ── */
.bar{display:flex;align-items:center;gap:8px;padding:8px 16px;background:rgba(0,0,0,0.2);border-bottom:1px solid var(--border);flex-shrink:0;flex-wrap:wrap}
.bar input,.bar select{background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--text);padding:5px 10px;border-radius:6px;font-family:inherit;font-size:11px}
.bar input:focus,.bar select:focus{outline:none;border-color:var(--primary)}
.btn{background:rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.3);color:var(--primary);padding:5px 12px;border-radius:6px;cursor:pointer;font-family:inherit;font-size:11px;font-weight:500;transition:.15s}
.btn:hover{background:rgba(99,102,241,.2)}
.btn.ok{background:rgba(34,197,94,.1);border-color:rgba(34,197,94,.3);color:var(--ok)}
.btn.ok:hover{background:rgba(34,197,94,.2)}
.btn.danger{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.3);color:var(--err)}
.cnt{color:var(--text-muted);font-size:11px;margin-left:auto}

/* ── NETWORK TABLE ── */
#timeline{flex:1;overflow-y:auto}
.ev-hdr,.ev-row{display:grid;grid-template-columns:64px 24px 72px 88px 80px 38px 50px 1fr;gap:4px;align-items:center;padding:5px 16px;font-size:11px}
.ev-hdr{font-size:10px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;background:rgba(0,0,0,.3);position:sticky;top:0;z-index:5;border-bottom:1px solid var(--border)}
.ev-row{border-bottom:1px solid rgba(255,255,255,.03);cursor:pointer;transition:.1s}
.ev-row:hover{background:var(--surface)}
.ev-row.sel{background:rgba(99,102,241,.08);border-left:2px solid var(--primary)}
.ev-row.err{border-left:2px solid var(--err)}
.di{color:var(--ok);font-weight:600}.do{color:#60a5fa;font-weight:600}

/* ── AGENT PILLS ── */
.pill{font-size:9px;padding:1px 6px;border-radius:99px;font-weight:600;white-space:nowrap}
.p-claude{background:var(--claude);color:var(--claude-t)}
.p-gemini{background:var(--gemini);color:var(--gemini-t)}
.p-groq{background:var(--groq);color:var(--groq-t)}
.p-mistral{background:var(--mistral);color:var(--mistral-t)}
.p-hub{background:var(--hub);color:var(--hub-t)}
.p-r0{background:rgba(255,151,112,.2);color:var(--claude-t)}
.p-r1{background:rgba(251,191,36,.2);color:var(--warn)}
.p-r3{background:rgba(108,108,141,.2);color:var(--text-muted)}

/* ── TOKEN STRIP ── */
.tok-strip{display:flex;align-items:center;gap:8px;padding:6px 16px;background:rgba(0,0,0,.25);border-top:1px solid var(--border);flex-shrink:0;flex-wrap:wrap}
.tok-card{display:flex;align-items:center;gap:6px;padding:3px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface);font-size:10px}
.tok-model{font-weight:600;color:var(--text-dim)}
.tok-n{color:var(--text)}
.tok-cost{color:var(--warn);font-weight:600}
.tok-lat{color:var(--text-muted)}

/* ── PAYLOAD PANEL ── */
.pay{width:310px;border-left:1px solid var(--border);display:none;flex-direction:column;background:rgba(0,0,0,.2);flex-shrink:0;backdrop-filter:blur(10px)}
.pay.vis{display:flex}
.pay-hdr{padding:8px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:11px;flex-shrink:0}
#payloadBody{flex:1;overflow:auto;padding:10px;font-size:10px;white-space:pre-wrap;color:var(--text-dim);line-height:1.6;font-family:'Consolas',monospace}
.pay-tok{padding:6px 12px;border-top:1px solid var(--border);font-size:10px;flex-shrink:0;display:flex;gap:10px;flex-wrap:wrap}
.pay-tok span{color:var(--text-muted)}
.pay-tok b{color:var(--text)}
.pay-tok .cost{color:var(--warn)}

/* ── DIALOGUE ── */
.dlg-list{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}
.bubble{max-width:74%;padding:9px 13px;border-radius:10px;font-size:12px;line-height:1.55}
.b-c{background:rgba(255,151,112,.1);border:1px solid rgba(255,151,112,.25);align-self:flex-start}
.b-g{background:rgba(167,199,231,.1);border:1px solid rgba(167,199,231,.25);align-self:flex-end}
.b-q{background:rgba(192,132,252,.1);border:1px solid rgba(192,132,252,.25);align-self:flex-start}
.b-m{background:rgba(96,165,250,.1);border:1px solid rgba(96,165,250,.25);align-self:flex-end}
.b-o{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.25);align-self:flex-start}
.b-h{background:rgba(255,214,112,.07);border:1px solid rgba(255,214,112,.15);align-self:center;max-width:92%;font-size:11px;color:var(--text-muted)}
.bmeta{display:flex;justify-content:space-between;margin-bottom:4px;font-size:10px;color:var(--text-muted);align-items:center}
.bagent{font-weight:700;font-size:11px}
.btok{color:var(--warn);font-size:10px}
.blat{color:var(--text-muted);font-size:10px}

/* ── ORGANISM SVG ── */
.org-wrap{flex:1;overflow:hidden;position:relative}
#org-svg{width:100%;height:100%}

/* ── COMM GRAPH ── */
#comm-svg{width:100%;height:100%}

/* ── DOC ── */
.doc-grid{flex:1;overflow-y:auto;padding:12px;display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px;align-content:start}
.doc-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;cursor:pointer;transition:.15s}
.doc-card:hover{border-color:var(--primary);background:var(--surface2);transform:translateY(-1px)}
.doc-card h3{font-size:12px;font-weight:600;color:var(--text);margin-bottom:3px;display:flex;align-items:center;gap:6px}
.doc-path{font-size:10px;color:var(--text-muted);margin-bottom:6px;font-family:'Consolas',monospace}
.doc-desc{font-size:11px;color:var(--text-dim);line-height:1.5}
.doc-role{font-size:10px;color:var(--text-muted);margin-top:6px;padding-top:6px;border-top:1px solid var(--border)}
.doc-kb{font-size:9px;padding:1px 6px;border-radius:99px;background:rgba(99,102,241,.15);color:var(--primary);margin-left:auto}
.doc-modal{position:fixed;inset:0;background:rgba(0,0,0,.75);display:none;z-index:100;align-items:center;justify-content:center;backdrop-filter:blur(5px)}
.doc-modal.vis{display:flex}
.doc-inner{background:#1a1a2e;border:1px solid var(--border);border-radius:12px;width:min(780px,90vw);max-height:85vh;display:flex;flex-direction:column}
.doc-inner-hdr{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.doc-inner-body{flex:1;overflow-y:auto;padding:18px;font-size:11px;line-height:1.8;white-space:pre-wrap;color:var(--text-dim);font-family:'Consolas',monospace}

/* ── AUDIT ── */
#logsBody{flex:1;overflow-y:auto;padding:10px 16px;font-size:10px;line-height:1.7;font-family:'Consolas',monospace}
.ll{white-space:pre-wrap;padding:1px 0}
.lok{color:var(--ok)}.lerr{color:var(--err)}.lwarn{color:var(--warn)}.linfo{color:var(--text-dim)}

/* ── SETTINGS ── */
.settings-body{flex:1;overflow-y:auto;padding:14px}
.ssec{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px}
.ssec h3{font-size:10px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
.srow{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.srow:last-child{border:none}
.slbl{font-size:12px;font-weight:500}
.sdesc{font-size:10px;color:var(--text-muted);margin-top:1px}
.badge{padding:2px 8px;border-radius:99px;font-size:10px;font-weight:600}
.bdg-r0{background:rgba(255,151,112,.15);color:var(--claude-t)}
.bdg-r3{background:rgba(108,108,141,.15);color:var(--text-muted)}
.bdg-ok{background:rgba(34,197,94,.12);color:var(--ok)}
.toggle{width:32px;height:18px;border-radius:9px;background:rgba(255,255,255,.1);border:1px solid var(--border);cursor:pointer;position:relative;transition:.2s;flex-shrink:0}
.toggle.on{background:rgba(99,102,241,.4);border-color:var(--primary)}
.toggle::after{content:'';position:absolute;width:12px;height:12px;border-radius:50%;background:var(--text-muted);top:2px;left:2px;transition:.2s}
.toggle.on::after{background:white;left:16px}
.empty{color:var(--text-muted);padding:24px;text-align:center;font-size:12px}
</style>
</head>
<body>

<header>
  <img src="/static/nokido-mark.svg" alt="Nokido" width="28" height="28" style="vertical-align:middle">
  <div class="logo">Nokido Hub</div>
  <div class="hmetrics">
    <div class="hm"><span class="hm-val" id="hv">18.3</span><span class="hm-lbl">Version</span></div>
    <div class="hdiv"></div>
    <div class="hm"><span class="hm-val" id="htot">0</span><span class="hm-lbl">Calls</span></div>
    <div class="hm"><span class="hm-val err" id="herr">0</span><span class="hm-lbl">Errors</span></div>
    <div class="hm"><span class="hm-val" id="havg">--</span><span class="hm-lbl">Avg ms</span></div>
    <div class="hdiv"></div>
    <div class="hm"><span class="hm-val" id="htok">0</span><span class="hm-lbl">Tokens</span></div>
    <div class="hm"><span class="hm-val cost" id="hcost">$0.0000</span><span class="hm-lbl">Cost</span></div>
  </div>
</header>

<div class="mood-bar">
  <div class="mood-chip"><div class="mood-dot" style="background:#22c55e"></div><span class="mood-l">Energy</span>&nbsp;<span class="mood-v" id="me">--</span></div>
  <div class="mood-chip"><div class="mood-dot" style="background:#6366f1"></div><span class="mood-l">Curiosity</span>&nbsp;<span class="mood-v" id="mc">--</span></div>
  <div class="mood-chip"><div class="mood-dot" style="background:#fbbf24"></div><span class="mood-l">Fatigue</span>&nbsp;<span class="mood-v" id="mf">--h</span></div>
  <div class="mood-chip"><div class="mood-dot" style="background:#ef4444"></div><span class="mood-l">Immune</span>&nbsp;<span class="mood-v" id="mi">--</span></div>
  <span class="mood-status" id="mst">VIVANT</span>
  <span class="mood-timeout" id="mts">-- Timeout LLM: <b id="mtout">30</b>s</span>
</div>

<nav>
  <div class="tab active" onclick="st('network',this)"><span class="tab-icon">&#9711;</span>Network</div>
  <div class="tab" onclick="st('mail',this)"><span class="tab-icon">&#128236;</span>Mail &amp; Agents</div>
  <div class="tab" onclick="st('dialog',this)"><span class="tab-icon">&#9654;</span>Dialogue LLM</div>
  <div class="tab" onclick="st('organism',this)"><span class="tab-icon">&#9898;</span>Organisme</div>
  <div class="tab" onclick="st('commgraph',this)"><span class="tab-icon">&#9854;</span>Flux</div>
  <div class="tab" onclick="st('doc',this)"><span class="tab-icon">&#9633;</span>Doc Organes</div>
  <div class="tab" onclick="st('logs',this)"><span class="tab-icon">&#9632;</span>Audit Log</div>
  <div class="tab" onclick="st('settings',this)"><span class="tab-icon">&#9881;</span>Settings</div>
</nav>

<main>

<!-- MAIL & AGENTS (regroupé : interface postale facteur/secrétaire + Chat/Schéma/essaim) -->
<div class="panel" id="panel-mail"><div class="empty">Conversations &amp; Agents vivent sur le portail :7400, qui interdit d'etre encadre (CSP frame-ancestors). <a href="/forge/postal" target="_blank" rel="noopener">Ouvrir dans un onglet</a></div></div>

<!-- NETWORK -->
<div class="panel active" id="panel-network">
  <div class="bar">
    <select id="fDir"><option value="">Direction</option><option>IN</option><option>OUT</option></select>
    <select id="fChan"><option value="">Canal</option><option>STDIO_CLAUDE</option><option>GEMINI_OAUTH</option><option>INTERNAL</option><option>CLOUD</option></select>
    <select id="fAgent"><option value="">Agent</option><option>CLAUDE</option><option>GEMINI</option><option>HUB</option><option>SYSTEM</option></select>
    <input id="fTxt" type="text" placeholder="Rechercher dans les events...">
    <button class="btn" id="btnP" onclick="togglePause()">Pause</button>
    <button class="btn danger" onclick="clrEvt()">Clear</button>
    <span class="cnt" id="fCnt">0 events</span>
  </div>
  <div style="display:flex;flex:1;overflow:hidden">
    <div style="flex:1;overflow:hidden;display:flex;flex-direction:column">
      <div class="ev-hdr"><span>Heure</span><span>Dir</span><span>Agent</span><span>Tool</span><span>Canal</span><span>Ring</span><span>Latence</span><span>Status / Tokens / Preview</span></div>
      <div id="timeline"></div>
    </div>
    <div class="pay" id="payP">
      <div class="pay-hdr">
        <span id="payId" style="color:var(--text-muted);font-size:10px">Selectionner un event</span>
        <button class="btn" onclick="closePay()" style="padding:2px 7px;font-size:11px">x</button>
      </div>
      <div id="payloadBody">Cliquer sur un event pour voir le detail.</div>
      <div class="pay-tok" id="payTok" style="display:none">
        <span>In: <b id="ptIn">0</b></span>
        <span>Out: <b id="ptOut">0</b></span>
        <span>Cost: <b class="cost" id="ptCost">$0</b></span>
        <span>Lat: <b id="ptLat">--</b>ms</span>
      </div>
    </div>
  </div>
  <div class="tok-strip" id="tokStrip">
    <span style="color:var(--text-muted);font-size:10px;font-weight:600">TOKENS</span>
    <span id="tokEmpty" style="color:var(--text-muted);font-size:10px">En attente d appels LLM...</span>
  </div>
</div>

<!-- DIALOGUE -->
<div class="panel" id="panel-dialog">
  <div class="bar">
    <select id="dProv" style="width:120px">
      <option value="groq">Groq</option><option value="mistral">Mistral</option>
      <option value="gpt4o_github">GPT-4o</option><option value="gemini">Gemini</option><option value="ollama">Ollama</option>
    </select>
    <input id="dInput" type="text" placeholder="Message direct a l agent selectionne..." style="flex:1">
    <button class="btn ok" onclick="sendMsg()">Envoyer</button>
    <button class="btn" onclick="loadDialog()">Historique</button>
    <span class="cnt">Session: <b id="dTok" style="color:var(--warn)">0</b> tok | <b id="dCost" style="color:var(--warn)">$0.0000</b></span>
  </div>
  <div class="dlg-list" id="dialogList"><div class="empty">Historique des echanges inter-LLM...</div></div>
</div>

<!-- ORGANISME -->
<div class="panel" id="panel-organism">
  <div class="bar">
    <button class="btn" onclick="renderOrganism()">Refresh</button>
    <span style="color:var(--text-muted)">Homogenese anthropomorphique - flux cognitifs temps reel</span>
    <span class="cnt"><span id="orgSt" style="color:var(--ok);font-weight:600">VIVANT</span></span>
  </div>
  <div class="org-wrap"><svg id="org-svg" viewBox="0 0 900 550" xmlns="http://www.w3.org/2000/svg"></svg></div>
</div>

<!-- FLUX GRAPH -->
<div class="panel" id="panel-commgraph">
  <div class="bar">
    <button class="btn" onclick="renderCommGraph()">Refresh</button>
    <span style="color:var(--text-muted)">Flux communication inter-agents - epaisseur=volume, couleur=latence</span>
  </div>
  <div style="flex:1;position:relative;overflow:hidden"><svg id="comm-svg"></svg></div>
</div>

<!-- DOC ORGANES -->
<div class="panel" id="panel-doc">
  <div class="bar">
    <input id="docQ" type="text" placeholder="Rechercher un organe..." style="flex:1" oninput="renderDoc()">
    <span class="cnt" id="docCnt">15 modules</span>
  </div>
  <div class="doc-grid" id="docGrid"></div>
</div>
<div class="doc-modal" id="docModal" onclick="if(event.target===this)closeDoc()">
  <div class="doc-inner">
    <div class="doc-inner-hdr">
      <span id="docMTitle" style="font-size:13px;font-weight:600">--</span>
      <button class="btn" onclick="closeDoc()">Fermer</button>
    </div>
    <div class="doc-inner-body" id="docMBody"></div>
  </div>
</div>

<!-- AUDIT LOG -->
<div class="panel" id="panel-logs">
  <div class="bar">
    <button class="btn" onclick="loadLogs()">Charger</button>
    <input id="logF" type="text" placeholder="grep..." style="flex:1" oninput="loadLogs()">
    <span class="cnt" id="logCnt">0 lignes</span>
  </div>
  <div id="logsBody"></div>
</div>

<!-- SETTINGS -->
<div class="panel" id="panel-settings">
  <div class="settings-body">
    <div class="ssec"><h3>Hub</h3>
      <div class="srow"><div><div class="slbl">Endpoint MCP</div></div><code style="font-size:10px;color:#a7c7e7;font-family:Consolas">127.0.0.1:8766/mcp</code></div>
      <div class="srow"><div><div class="slbl">Version</div></div><span id="hvS" style="color:var(--ok);font-weight:600">18.3</span></div>
      <div class="srow"><div><div class="slbl">Poll reflexe</div><div class="sdesc">Declenchement au tick d action — pas de timer fixe</div></div><span class="badge bdg-ok">Actif every_n=5</span></div>
      <div class="srow"><div><div class="slbl">Switches virtuels</div><div class="sdesc">Logique cerebrale — gates ReBAC DSL</div></div><span class="badge bdg-ok">Actif</span></div>
    </div>
    <div class="ssec"><h3>Canal stdio vs HTTP — pas de goulot</h3>
      <div class="srow"><div><div class="slbl">Claude Desktop → Hub</div><div class="sdesc">STDIO bridge → HTTP 8766 — canal dedié Claude</div></div><span class="badge bdg-ok">Fluide</span></div>
      <div class="srow"><div><div class="slbl">Gemini CLI → Hub</div><div class="sdesc">HTTP direct 8766 — pas de stdio, OAuth bearer</div></div><span class="badge bdg-ok">Fluide</span></div>
      <div class="srow"><div><div class="slbl">SearXNG</div><div class="sdesc">HTTP :8080 via forge_web_fallback — proxy natif Nokido (web_search, research_agent, watch_agent, biblio)</div></div><span class="badge bdg-ok">Via Nokido</span></div>
      <div class="srow"><div><div class="slbl">Docker MCP</div><div class="sdesc">forge_docker_supervisor → docker mcp gateway stdio — proxy Nokido (docker_* tools, ring-checked)</div></div><span class="badge bdg-ok">Via Nokido</span></div>
      <div style="margin-top:8px;padding:8px 10px;background:rgba(99,102,241,.08);border-radius:6px;font-size:11px;color:var(--text-dim);line-height:1.6">
        Nokido est l intelligence centrale. Claude Code et Gemini CLI sont clients du hub :8766. SearXNG et Docker MCP gateway sont proxifies par Nokido (forge_web_fallback + forge_docker_supervisor) — chaque acces passe par SemanticFirewall, ring-check et indexation RAG.
      </div>
    </div>
    <div class="ssec"><h3>MCP Servers</h3>
      <div id="mcpServerList"><div style="color:var(--text-muted)">Chargement...</div></div>
      <div style="margin-top:8px;display:flex;gap:8px">
        <button class="btn" onclick="loadMCPServers()">Refresh</button>
        <button class="btn ok" onclick="resetFlags()">Reset flags anti-injection</button>
      </div>
      <div id="mcpNote" style="font-size:10px;color:var(--warn);margin-top:6px"></div>
    </div>
    <div class="ssec"><h3>Rings</h3>
      <div class="srow"><div><div class="slbl">127.0.0.1 local</div></div><span class="badge bdg-r0">RING 0 Admin</span></div>
      <div class="srow"><div><div class="slbl">Remote + token valide</div></div><span class="badge bdg-r3">RING 3 Collab</span></div>
      <div class="srow"><div><div class="slbl">tools/list filtre par ring</div><div class="sdesc">R0 -> 16 tools | R3 -> 6 | R4 -> 3</div></div><span class="badge bdg-ok">Actif</span></div>
    </div>
    <div class="ssec"><h3>Modules actifs</h3>
      <div class="srow"><div><div class="slbl">forge_system_mood</div><div class="sdesc">Endocrinien — broadcast 60s</div></div><div class="toggle on"></div></div>
      <div class="srow"><div><div class="slbl">forge_access_switches</div><div class="sdesc">ReBAC DSL — gate cerebral automatique</div></div><div class="toggle on"></div></div>
      <div class="srow"><div><div class="slbl">forge_conversation_logger</div><div class="sdesc">Memoire episodique auto</div></div><div class="toggle on"></div></div>
      <div class="srow"><div><div class="slbl">forge_watch_agent</div><div class="sdesc">Veille active SearXNG — pipeline N8N</div></div><div class="toggle on"></div></div>
    </div>
  </div>
</div>

</main>
<script>
// CAMPAGNE UI 2026-09-24 (/forge/network). Trois defauts mesures dans le navigateur :
//  1. l'element #sdot n'existe plus : loadStatus et le flux levaient TypeError sur null ;
//  2. /mcp exige un porteur depuis la fermeture du chantier auth : les appels de cette page
//     (ask, SQL brut, run python, journaux) recoivent 401. Une page PUBLIQUE ne doit pas
//     obtenir ces droits -- mais le refus se DIT, au lieu de laisser des panneaux vides
//     qui se lisent « rien a montrer » ;
//  3. l'iframe postal visait une page de :7400, qui interdit d'etre encadree (CSP).
function setDot(on){const e=document.getElementById('sdot');if(e)e.className=on?'logo-dot':'logo-dot off';}
(function(){const _f=window.fetch;window.fetch=async function(u,o){const r=await _f(u,o);
  if(u==='/mcp'&&(r.status===401||r.status===403)){const e=new Error('MCP reserve aux agents authentifies (HTTP '+r.status+') : indisponible depuis cette page');e.refus=true;throw e;}
  return r;};})();
function direRefus(id,e){const el=document.getElementById(id);if(el&&e&&e.refus)el.innerHTML='<div class="empty">'+e.message+'</div>';}
// PRICING
const PC={'mistral-large-latest':{in:2,out:6,col:'#60a5fa'},'gpt-4o':{in:5,out:15,col:'#34d399'},'llama-3.3-70b-versatile':{in:.59,out:.79,col:'#c084fc'},'gemini-2.5-flash':{in:.15,out:.60,col:'#a7c7e7'},'gemini-2.5-pro':{in:1.25,out:10,col:'#a7c7e7'},'claude-sonnet-4-6':{in:3,out:15,col:'#ff9770'},'sambanova/Meta-Llama-3.3-70B-Instruct':{in:1.32,out:2.2,col:'#c084fc'}};
function cost(m,ti,to){const p=PC[m]||{in:0,out:0};return((ti||0)/1e6)*p.in+((to||0)/1e6)*p.out;}
function provCol(m){for(const[k,v]of Object.entries(PC))if(m&&m.includes(k.split('-')[0]))return v.col;return'#6c6c8d';}

// AGENT COLORS + PILL CLASS
const AC={CLAUDE:'#ff9770',GEMINI:'#a7c7e7',GROQ:'#c084fc',MISTRAL:'#60a5fa',HUB:'#ffd670',SYSTEM:'#6c6c8d'};
function agC(a){return AC[a?.toUpperCase()]||'#a4a6ba';}
function agPill(a){const m={'CLAUDE':'p-claude','GEMINI':'p-gemini','GROQ':'p-groq','MISTRAL':'p-mistral','HUB':'p-hub'};return m[a?.toUpperCase()]||'p-hub';}

// STATE
let events=[],paused=false,selEv=null,stats={tot:0,err:0,lats:[],cost:0,tok:0},provSt={},dTok=0,dCost=0;

// TABS
function st(tab,el){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('panel-'+tab).classList.add('active');
  if(tab==='logs')loadLogs();
  else if(tab==='organism')renderOrganism();
  else if(tab==='commgraph')renderCommGraph();
  else if(tab==='dialog')loadDialog();
  else if(tab==='doc')renderDoc();
  else if(tab==='settings'){loadMCPServers();loadStatus();}
}

// SSE
let es;
function startStream(){
  es=new EventSource('/api/network/stream');
  es.onmessage=e=>{if(paused)return;try{const d=JSON.parse(e.data);if(d.type==='event')addEv(d.event);}catch{}};
  es.onerror=()=>{setDot(false);setTimeout(startStream,4000);};
}
function addEv(ev){events.unshift(ev);if(events.length>1000)events.pop();updStats(ev);render();}
function updStats(ev){
  stats.tot++;if(ev.status==='ERR')stats.err++;
  if(ev.latency_ms)stats.lats.push(ev.latency_ms);
  const ti=ev.tokens_in||0,to=ev.tokens_out||0;
  if(ti||to){stats.tok+=ti+to;const c=cost(ev.model,ti,to);stats.cost+=c;
    const k=ev.model||'unknown';if(!provSt[k])provSt[k]={in:0,out:0,cost:0,calls:0,lats:[]};
    provSt[k].in+=ti;provSt[k].out+=to;provSt[k].cost+=c;provSt[k].calls++;
    if(ev.latency_ms)provSt[k].lats.push(ev.latency_ms);updTok();}
  const avg=stats.lats.length?Math.round(stats.lats.reduce((a,b)=>a+b)/stats.lats.length):0;
  document.getElementById('htot').textContent=stats.tot;
  document.getElementById('herr').textContent=stats.err;
  document.getElementById('havg').textContent=avg+'ms';
  document.getElementById('hcost').textContent='$'+stats.cost.toFixed(4);
  document.getElementById('htok').textContent=stats.tok.toLocaleString();
}
function updTok(){
  const strip=document.getElementById('tokStrip');
  const empty=document.getElementById('tokEmpty');if(empty)empty.style.display='none';
  const ex=Array.from(strip.querySelectorAll('.tok-card')).reduce((m,el)=>{m[el.dataset.k]=el;return m;},{});
  Object.entries(provSt).forEach(([k,v])=>{
    const col=provCol(k);const avgLat=v.lats.length?Math.round(v.lats.reduce((a,b)=>a+b)/v.lats.length):0;
    const sK=k.split('/').pop().split('-').slice(0,3).join('-');
    let el=ex[k];
    if(!el){el=document.createElement('div');el.className='tok-card';el.dataset.k=k;strip.appendChild(el);}
    el.style.borderColor=col+'44';
    el.innerHTML=`<span class="tok-model" style="color:${col}">${sK}</span><span class="tok-n">${(v.in+v.out).toLocaleString()}t</span><span class="tok-cost">$${v.cost.toFixed(4)}</span><span class="tok-lat">${avgLat}ms</span>`;
  });
}

// RENDER NETWORK
function filt(){const f={dir:document.getElementById('fDir').value,chan:document.getElementById('fChan').value,agent:document.getElementById('fAgent').value,txt:(document.getElementById('fTxt').value||'').toLowerCase()};
  return events.filter(ev=>(!f.dir||ev.direction===f.dir)&&(!f.chan||(ev.channel||'').includes(f.chan))&&(!f.agent||ev.agent===f.agent)&&(!f.txt||JSON.stringify(ev).toLowerCase().includes(f.txt)));}
function render(){
  const evs=filt().slice(0,500);
  document.getElementById('fCnt').textContent=evs.length+'/'+events.length+' events';
  const tl=document.getElementById('timeline');
  if(!evs.length){tl.innerHTML='<div class="empty">Aucun event</div>';return;}
  tl.innerHTML=evs.map((ev,i)=>{
    const t=(ev.ts||'').slice(11,19);
    const dir=ev.direction==='IN'?'<span class="di">&#9660;</span>':'<span class="do">&#9650;</span>';
    const ag=ev.agent||'?';
    const chan=(ev.channel||'').replace('STDIO_','S-').replace('_OAUTH','_O');
    const ring=ev.ring!=null?`<span class="pill ${ev.ring<=1?'p-r0':ev.ring<=2?'p-r1':'p-r3'}">R${ev.ring}</span>`:'';
    const lat=ev.latency_ms?Math.round(ev.latency_ms)+'ms':'';
    const latC=ev.latency_ms>5000?'color:var(--err)':ev.latency_ms>1000?'color:var(--warn)':'color:var(--text-muted)';
    const st=ev.status==='ERR'?'<span style="color:var(--err);font-weight:600">ERR</span>':'<span style="color:var(--ok)">OK</span>';
    const ti=ev.tokens_in||0,to=ev.tokens_out||0;
    const tokB=(ti||to)?`<span style="color:var(--warn);font-size:9px"> ·${(ti+to).toLocaleString()}t $${cost(ev.model,ti,to).toFixed(4)}</span>`:'';
    const prev=(ev.payload_out||ev.payload_in||'').replace(/["{}]/g,'').slice(0,55);
    return`<div class="ev-row${ev.status==='ERR'?' err':''}${selEv===i?' sel':''}" onclick="showPay(${i})">
      <span style="color:var(--text-muted)">${t}</span>
      ${dir}
      <span class="pill ${agPill(ag)}">${ag}</span>
      <span style="font-weight:500">${ev.tool||ev.method||''}</span>
      <span style="color:var(--text-muted);font-size:10px">${chan}</span>
      ${ring}
      <span style="${latC}">${lat}</span>
      <span>${st}${tokB}<span style="color:var(--text-muted);font-size:10px"> ${prev}</span></span>
    </div>`;
  }).join('');
}
function showPay(i){selEv=i;const ev=filt()[i];
  document.getElementById('payP').classList.add('vis');
  document.getElementById('payId').textContent=`${ev.agent||'?'} · ${ev.tool||''} · ${(ev.ts||'').slice(11,19)}`;
  const b=document.getElementById('payloadBody');const parts=[];
  if(ev.model)parts.push('Model: '+ev.model);
  if(ev.payload_in)try{parts.push('--- IN ---\n'+JSON.stringify(JSON.parse(ev.payload_in),null,2));}catch{parts.push(ev.payload_in);}
  if(ev.payload_out)try{parts.push('--- OUT ---\n'+JSON.stringify(JSON.parse(ev.payload_out),null,2));}catch{parts.push(ev.payload_out);}
  b.textContent=parts.join('\n\n')||JSON.stringify(ev,null,2);
  const tok=document.getElementById('payTok');
  if(ev.tokens_in||ev.tokens_out){tok.style.display='flex';
    document.getElementById('ptIn').textContent=(ev.tokens_in||0).toLocaleString();
    document.getElementById('ptOut').textContent=(ev.tokens_out||0).toLocaleString();
    document.getElementById('ptCost').textContent='$'+cost(ev.model,ev.tokens_in,ev.tokens_out).toFixed(6);
    document.getElementById('ptLat').textContent=ev.latency_ms?Math.round(ev.latency_ms):'--';
  }else tok.style.display='none';
  render();
}
function closePay(){document.getElementById('payP').classList.remove('vis');selEv=null;}
function togglePause(){paused=!paused;document.getElementById('btnP').textContent=paused?'Resume':'Pause';}
function clrEvt(){events=[];stats={tot:0,err:0,lats:[],cost:0,tok:0};provSt={};render();}
['fDir','fChan','fAgent','fTxt'].forEach(id=>{const el=document.getElementById(id);if(el)el.addEventListener('input',render);});

// DIALOGUE
function agBubble(a){const m={'CLAUDE':'b-c','GEMINI':'b-g','GROQ':'b-q','groq':'b-q','MISTRAL':'b-m','mistral':'b-m','gpt4o_github':'b-o','HUB':'b-h'};for(const[k,v]of Object.entries(m))if(a&&a.toLowerCase().includes(k.toLowerCase()))return v;return'b-h';}
async function sendMsg(){
  const prov=document.getElementById('dProv').value;
  const msg=document.getElementById('dInput').value.trim();
  if(!msg)return;document.getElementById('dInput').value='';
  addBubble({agent:'USER',_txt:msg,ts:new Date().toISOString()});
  try{
    const r=await fetch('/mcp',{method:'POST',signal:AbortSignal.timeout(30_000),headers:{'Content-Type':'application/json'},
      body:JSON.stringify({jsonrpc:'2.0',id:Date.now(),method:'tools/call',params:{name:'ask',arguments:{provider:prov,message:msg,max_tokens:500}}})});
    const d=await r.json();
    const txt=(d.result?.content?.[0]?.text||'{}');let p={};try{p=JSON.parse(txt);}catch{}
    const out={agent:prov.toUpperCase(),_txt:p.text||txt,tokens_in:p.prompt_tokens,tokens_out:p.completion_tokens,model:p.model,latency_ms:p.latency_ms};
    addBubble(out);
    if(p.prompt_tokens||p.completion_tokens){dTok+=(p.prompt_tokens||0)+(p.completion_tokens||0);dCost+=cost(p.model,p.prompt_tokens,p.completion_tokens);document.getElementById('dTok').textContent=dTok.toLocaleString();document.getElementById('dCost').textContent='$'+dCost.toFixed(4);}
  }catch(e){addBubble({agent:'SYSTEM',_txt:'Erreur: '+e.message,ts:new Date().toISOString()});}
}
function addBubble(ev){
  const list=document.getElementById('dialogList');const empty=list.querySelector('.empty');if(empty)empty.remove();
  const ag=ev.agent||'HUB';const cls=agBubble(ag);
  const t=(ev.ts||'').slice(11,19)||new Date().toTimeString().slice(0,8);
  const txt=ev._txt||(()=>{try{return JSON.parse(ev.payload_out||'{}').text||'';}catch{return ev.payload_out||'';}})();
  if(!txt)return;
  const ti=ev.tokens_in||0,to=ev.tokens_out||0;
  const tokH=(ti||to)?`<span class="btok">${(ti+to).toLocaleString()}t $${cost(ev.model,ti,to).toFixed(4)}</span>`:'';
  const latH=ev.latency_ms?`<span class="blat">${Math.round(ev.latency_ms)}ms</span>`:'';
  const d=document.createElement('div');d.className='bubble '+cls;
  d.innerHTML=`<div class="bmeta"><span class="bagent" style="color:${agC(ag)}">${ag}</span><span style="color:var(--text-muted)">${t}</span>${tokH}${latH}</div><div>${txt.slice(0,800).replace(/</g,'&lt;')}</div>`;
  list.appendChild(d);list.scrollTop=list.scrollHeight;
}
async function loadDialog(){
  // Decision owner 25/09 : lecture SEULE. Les conversations inter-agents (contenu + topologie)
  // sont CONFIDENTIELLES au classement du chantier auth : jamais publiees sans authentification
  // sur :8766 (la page les lisait par SQL brut via /mcp). Lecture seule authentifiee : le portail.
  const list=document.getElementById('dialogList');
  if(list&&!list.querySelector('.bubble'))list.innerHTML='<div class="empty">Conversations inter-agents : contenu CONFIDENTIEL, lecture seule authentifiee sur le portail :7400. <a href="/forge/postal" target="_blank" rel="noopener">Ouvrir</a></div>';
}
document.getElementById('dInput').addEventListener('keydown',e=>{if(e.key==='Enter')sendMsg();});

// MOOD
async function loadMood(){
  // Decision owner 25/09 : lecture SEULE par /api/network/mood (scalaires), au lieu d'un
  // `run action=python` envoye au hub depuis le navigateur.
  try{const r=await fetch('/api/network/mood',{signal:AbortSignal.timeout(10_000)});
  const m=await r.json();if(!r.ok||m.error)throw new Error('humeur indisponible (HTTP '+r.status+')');
  document.getElementById('me').textContent=Math.round(m.e*100)+'%';
  document.getElementById('mc').textContent=Math.round(m.c*100)+'%';
  document.getElementById('mf').textContent=m.f.toFixed(1)+'h';
  document.getElementById('mi').textContent=Math.round(m.ia*100)+'%';
  document.getElementById('mtout').textContent=Math.round(m.timeout||30);
  document.getElementById('mts').textContent=(m.ts||'').slice(11,19)+' ';
  const st=document.getElementById('mst');
  st.textContent=m.stressed?'STRESSE':m.idle?'IDLE':'VIVANT';
  st.className='mood-status'+(m.stressed?' stress':'');
  }catch(e){console.error('mood',e);const st=document.getElementById('mst');if(st){st.textContent=e.refus?'NON AUTORISE':'INDISPONIBLE';st.title=e.message;}}
}

// ORGANISM
function renderOrganism(){
  const svg=document.getElementById('org-svg');
  const e_=parseFloat(document.getElementById('me').textContent)||80;
  const ia_=parseFloat(document.getElementById('mi').textContent)||0;
  const eF=e_/100,iaF=ia_/100;
  const cC=eF>0.5?'#6366f1':'#fbbf24';const iC=iaF>0.5?'#ef4444':'#22c55e';
  svg.innerHTML=`
  <defs>
    <filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <linearGradient id="bg-grad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#0f0f1a"/><stop offset="100%" stop-color="#1a1a2e"/></linearGradient>
    <marker id="ar" markerWidth="5" markerHeight="3" refX="5" refY="1.5" orient="auto"><polygon points="0 0,5 1.5,0 3" fill="#404060"/></marker>
    <marker id="ar-ok" markerWidth="5" markerHeight="3" refX="5" refY="1.5" orient="auto"><polygon points="0 0,5 1.5,0 3" fill="#22c55e"/></marker>
    <marker id="ar-bl" markerWidth="5" markerHeight="3" refX="5" refY="1.5" orient="auto"><polygon points="0 0,5 1.5,0 3" fill="#6366f1"/></marker>
  </defs>
  <rect width="900" height="550" fill="url(#bg-grad)" rx="0"/>

  <!-- Corps central -->
  <ellipse cx="450" cy="200" rx="55" ry="80" fill="rgba(99,102,241,0.04)" stroke="rgba(99,102,241,0.15)" stroke-width="1"/>

  <!-- Cerveau / Cortex -->
  <ellipse cx="450" cy="95" rx="48" ry="38" fill="rgba(99,102,241,0.1)" stroke="${cC}" stroke-width="1.5" filter="url(#glow)"/>
  <text x="450" y="88" text-anchor="middle" fill="${cC}" font-size="10" font-weight="600" font-family="Inter">CORTEX</text>
  <text x="450" y="100" text-anchor="middle" fill="#6c6c8d" font-size="9" font-family="Inter">cognitive_router</text>
  <text x="450" y="112" text-anchor="middle" fill="#6366f1" font-size="8" font-family="Inter">RAG hippocampe</text>

  <!-- Yeux SearXNG -->
  <circle cx="408" cy="75" r="11" fill="rgba(34,211,238,0.1)" stroke="#22d3ee" stroke-width="1.5"/>
  <circle cx="408" cy="75" r="4" fill="#22d3ee"/>
  <circle cx="492" cy="75" r="11" fill="rgba(34,211,238,0.1)" stroke="#22d3ee" stroke-width="1.5"/>
  <circle cx="492" cy="75" r="4" fill="#22d3ee"/>
  <text x="390" y="59" fill="#22d3ee" font-size="8" font-family="Inter">SearXNG</text>
  <text x="476" y="59" fill="#22d3ee" font-size="8" font-family="Inter">SearXNG</text>

  <!-- Bouche biblio -->
  <rect x="426" y="125" width="48" height="13" rx="6" fill="rgba(244,114,182,0.1)" stroke="#f472b6" stroke-width="1.5"/>
  <text x="450" y="135" text-anchor="middle" fill="#f472b6" font-size="8" font-family="Inter">biblio_worker</text>

  <!-- Cervelet -->
  <ellipse cx="450" cy="168" rx="28" ry="16" fill="rgba(251,146,60,0.08)" stroke="#fb923c" stroke-width="1.5"/>
  <text x="450" y="165" text-anchor="middle" fill="#fb923c" font-size="9" font-family="Inter">CERVELET</text>
  <text x="450" y="176" text-anchor="middle" fill="#6c6c8d" font-size="8" font-family="Inter">spike_router</text>

  <!-- Moelle epiniere -->
  <rect x="446" y="184" width="8" height="110" rx="4" fill="rgba(255,214,112,0.12)" stroke="#ffd670" stroke-width="1.5"/>
  <text x="470" y="238" fill="#ffd670" font-size="8" font-family="Inter">byte_router</text>

  <!-- Coeur Hub -->
  <polygon points="450,205 468,222 450,240 432,222" fill="rgba(255,214,112,0.1)" stroke="#ffd670" stroke-width="2" filter="url(#glow)"/>
  <text x="450" y="258" text-anchor="middle" fill="#ffd670" font-size="10" font-weight="600" font-family="Inter">HUB</text>

  <!-- Immunite -->
  <ellipse cx="330" cy="225" rx="42" ry="26" fill="rgba(34,197,94,0.08)" stroke="${iC}" stroke-width="1.5"/>
  <text x="330" y="221" text-anchor="middle" fill="${iC}" font-size="9" font-weight="600" font-family="Inter">IMMUNITE</text>
  <text x="330" y="232" text-anchor="middle" fill="#6c6c8d" font-size="8" font-family="Inter">mcp_security</text>

  <!-- Endocrine -->
  <ellipse cx="570" cy="225" rx="42" ry="26" fill="rgba(251,191,36,0.08)" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="570" y="221" text-anchor="middle" fill="#fbbf24" font-size="9" font-weight="600" font-family="Inter">ENDOCRINE</text>
  <text x="570" y="232" text-anchor="middle" fill="#6c6c8d" font-size="8" font-family="Inter">system_mood</text>

  <!-- Memoire -->
  <ellipse cx="300" cy="350" rx="55" ry="30" fill="rgba(96,165,250,0.08)" stroke="#60a5fa" stroke-width="1.5"/>
  <text x="300" y="346" text-anchor="middle" fill="#60a5fa" font-size="9" font-weight="600" font-family="Inter">MEMOIRE</text>
  <text x="300" y="358" text-anchor="middle" fill="#6c6c8d" font-size="8" font-family="Inter">conv_logger + RAG</text>

  <!-- Cascade LLM -->
  <ellipse cx="600" cy="350" rx="60" ry="30" fill="rgba(192,132,252,0.08)" stroke="#c084fc" stroke-width="1.5"/>
  <text x="600" y="344" text-anchor="middle" fill="#c084fc" font-size="9" font-weight="600" font-family="Inter">CASCADE LLM</text>
  <text x="600" y="356" text-anchor="middle" fill="#6c6c8d" font-size="8" font-family="Inter">24 providers</text>
  <text x="600" y="366" text-anchor="middle" fill="#6c6c8d" font-size="8" font-family="Inter">Groq - Mistral - GPT4o</text>

  <!-- Inconscient -->
  <ellipse cx="450" cy="430" rx="75" ry="42" fill="rgba(167,139,250,0.06)" stroke="#a78bfa" stroke-width="1.5" stroke-dasharray="5,3"/>
  <text x="450" y="425" text-anchor="middle" fill="#a78bfa" font-size="10" font-weight="600" font-family="Inter">INCONSCIENT</text>
  <text x="450" y="438" text-anchor="middle" fill="#6c6c8d" font-size="8" font-family="Inter">shadow_mutation - sandbox</text>

  <!-- Veille active -->
  <rect x="650" y="90" width="100" height="38" rx="6" fill="rgba(34,197,94,0.08)" stroke="#22c55e" stroke-width="1.5"/>
  <text x="700" y="107" text-anchor="middle" fill="#22c55e" font-size="9" font-weight="600" font-family="Inter">VEILLE ACTIVE</text>
  <text x="700" y="120" text-anchor="middle" fill="#6c6c8d" font-size="8" font-family="Inter">watch_agent</text>

  <!-- Agents externes -->
  <rect x="140" y="80" width="95" height="60" rx="6" fill="rgba(255,255,255,0.02)" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="188" y="100" text-anchor="middle" fill="#ff9770" font-size="10" font-weight="600" font-family="Inter">CLAUDE</text>
  <text x="188" y="114" text-anchor="middle" fill="#a7c7e7" font-size="10" font-family="Inter">GEMINI</text>
  <text x="188" y="127" text-anchor="middle" fill="#77dd77" font-size="9" font-family="Inter">CLINE</text>

  <!-- FLUX -->
  <line x1="418" y1="80" x2="426" y2="88" stroke="#22d3ee" stroke-width="1.5" marker-end="url(#ar-ok)"/>
  <line x1="482" y1="80" x2="474" y2="88" stroke="#22d3ee" stroke-width="1.5" marker-end="url(#ar-ok)"/>
  <line x1="450" y1="133" x2="450" y2="150" stroke="#f472b6" stroke-width="1.5" stroke-dasharray="3,2" marker-end="url(#ar)"/>
  <line x1="450" y1="133" x2="380" y2="395" stroke="#f472b6" stroke-width="1" stroke-dasharray="2,4" marker-end="url(#ar)" opacity=".5"/>
  <line x1="450" y1="184" x2="450" y2="203" stroke="#6366f1" stroke-width="1.5" marker-end="url(#ar-bl)"/>
  <line x1="450" y1="240" x2="450" y2="295" stroke="#ffd670" stroke-width="1" stroke-dasharray="3,2" opacity=".6"/>
  <path d="M462 228 Q535 285 545 326" stroke="#c084fc" stroke-width="1.5" fill="none" marker-end="url(#ar)"/>
  <path d="M545 356 Q450 370 358 356" stroke="#60a5fa" stroke-width="1" fill="none" stroke-dasharray="3,3" marker-end="url(#ar)" opacity=".7"/>
  <path d="M415 430 Q355 415 335 378" stroke="#a78bfa" stroke-width="1" fill="none" stroke-dasharray="2,4" marker-end="url(#ar)" opacity=".5"/>
  <path d="M420 415 Q360 300 420 115" stroke="#a78bfa" stroke-width="1" fill="none" stroke-dasharray="2,5" marker-end="url(#ar)" opacity=".35"/>
  <line x1="438" y1="225" x2="372" y2="225" stroke="#22c55e" stroke-width="1" stroke-dasharray="3,2" opacity=".5"/>
  <line x1="462" y1="225" x2="528" y2="225" stroke="#fbbf24" stroke-width="1" stroke-dasharray="3,2" opacity=".5"/>
  <path d="M235 110 Q340 140 432 210" stroke="rgba(255,255,255,0.2)" stroke-width="1" fill="none" marker-end="url(#ar)"/>
  <path d="M650 110 Q600 140 466 215" stroke="#22c55e" stroke-width="1" fill="none" stroke-dasharray="3,2" marker-end="url(#ar)" opacity=".6"/>
  <text x="610" y="160" fill="#22c55e" font-size="8" font-family="Inter">veille</text>

  <!-- STATUS BAR -->
  <rect x="50" y="500" width="800" height="30" rx="4" fill="rgba(0,0,0,0.3)" stroke="rgba(255,255,255,0.06)"/>
  <text x="70" y="519" fill="#6c6c8d" font-size="9" font-family="Inter">Organisme:</text>
  <text x="130" y="519" fill="${eF>0.5?'#22c55e':'#ef4444'}" font-size="9" font-weight="600" font-family="Inter">${eF>0.7?'VIVANT':'STRESSE'}</text>
  <text x="200" y="519" fill="#6c6c8d" font-size="9" font-family="Inter">Energy:</text>
  <text x="242" y="519" fill="${cC}" font-size="9" font-weight="600" font-family="Inter">${Math.round(eF*100)}%</text>
  <text x="290" y="519" fill="#6c6c8d" font-size="9" font-family="Inter">Immune:</text>
  <text x="336" y="519" fill="${iC}" font-size="9" font-weight="600" font-family="Inter">${Math.round(iaF*100)}%</text>
  `;
}

// COMM GRAPH
function renderCommGraph(){
  const svg=document.getElementById('comm-svg');
  const W=svg.clientWidth||800,H=svg.clientHeight||400,cx=W/2,cy=H/2,r=Math.min(W,H)*.35;
  const agents=[...new Set(['HUB',...events.map(e=>e.agent).filter(Boolean)])].slice(0,8);
  const n=agents.length;const pos={};
  agents.forEach((a,i)=>{const ang=(i/n)*Math.PI*2-Math.PI/2;pos[a]={x:cx+Math.cos(ang)*r,y:cy+Math.sin(ang)*r};});
  const flows={};
  events.forEach(ev=>{if(!ev.agent||ev.agent==='HUB')return;const k=ev.agent+'->HUB';if(!flows[k])flows[k]={n:0,lats:[]};flows[k].n++;if(ev.latency_ms)flows[k].lats.push(ev.latency_ms);});
  let h='<defs><filter id="g2"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter><marker id="ar2" markerWidth="5" markerHeight="3" refX="5" refY="1.5" orient="auto"><polygon points="0 0,5 1.5,0 3" fill="#6c6c8d"/></marker></defs>';
  h+=`<rect width="${W}" height="${H}" fill="url(#bg-grad)"/>`;
  Object.entries(flows).forEach(([k,v])=>{
    const[from]=k.split('->');const pF=pos[from]||pos['HUB'],pT=pos['HUB'];if(!pF||!pT)return;
    const avgL=v.lats.length?v.lats.reduce((a,b)=>a+b)/v.lats.length:0;
    const col=avgL>3000?'#ef4444':avgL>1000?'#fbbf24':'#22c55e';
    const w=Math.min(6,1+v.n/8);
    h+=`<line x1="${pF.x}" y1="${pF.y}" x2="${pT.x}" y2="${pT.y}" stroke="${col}" stroke-width="${w}" stroke-opacity=".5" marker-end="url(#ar2)"/>`;
    const mx=(pF.x+pT.x)/2,my=(pF.y+pT.y)/2;
    h+=`<text x="${mx}" y="${my}" text-anchor="middle" fill="${col}" font-size="10" font-family="Inter" font-weight="600">${v.n}</text>`;
  });
  agents.forEach(a=>{const p=pos[a];if(!p)return;
    const col=agC(a);const cnt=events.filter(e=>e.agent===a).length;
    const r2=22+Math.min(12,cnt/4);
    h+=`<circle cx="${p.x}" cy="${p.y}" r="${r2}" fill="rgba(99,102,241,0.08)" stroke="${col}" stroke-width="1.5" filter="url(#g2)"/>
      <text x="${p.x}" y="${p.y-2}" text-anchor="middle" fill="${col}" font-size="10" font-weight="600" font-family="Inter">${a}</text>
      <text x="${p.x}" y="${p.y+11}" text-anchor="middle" fill="${col}" font-size="10" font-family="Inter">${cnt}</text>`;
  });
  svg.innerHTML=h;
}

// DOC
const ORGANS=[
  {key:'forge_access_switches',label:'Gates Acces (Switches)',path:'app/forge_access_switches.py',size:13494,desc:'Switches virtuels ReBAC — logique cerebrale de gate. SafeEval DSL sandboxe. check_access() a chaque dispatch MCP. Pas une UI admin — logique autonome comme un VLAN.',role:'Barriere neuronale — laisse passer ou bloque selon identite+ressource+condition.'},
  {key:'forge_system_mood',label:'Systeme Endocrinien',path:'app/forge_system_mood.py',size:9397,desc:'MoodState : energy/curiosity/fatigue/immune_alert. Broadcast EventBus 60s. Modules consommateurs ajustent timeout/intervalles.',role:'Hormone diffuse — colore toutes les decisions sans commander directement.'},
  {key:'forge_conversation_logger',label:'Memoire Episodique',path:'app/forge_conversation_logger.py',size:7858,desc:'Capture chaque echange dans conversation_log + rag_chunks (episodic_memory). Consolidation auto 10 tours -> longterm_memory.',role:'Hippocampe — encode les experiences pour les rendre recoverables cross-session.'},
  {key:'forge_byte_router',label:'Moelle Epiniere',path:'app/forge_byte_router.py',size:9401,desc:'Middleware interceptant chaque appel MCP avant dispatch. Poll reflexe au tick d action. Anticipation semantique.',role:'Canal bidirectionnel pur — transport + reflexes appris. Pas de decision.'},
  {key:'forge_cognitive_router',label:'Cortex Prefrontal',path:'app/forge_cognitive_router.py',size:15003,desc:'Anticipation des outils probables avant que le LLM ait a les deduire. INHIBITION des reflexes quand non necessaire.',role:'Decision consciente — sait quand NE PAS agir.'},
  {key:'forge_spike_router',label:'Cervelet',path:'app/forge_spike_router.py',size:11200,desc:'SNN routeur appris sur 38 challenges CTF. Decision rapide sans passer par le cortex. 12/12 routage parfait.',role:'Reflexes appris — automatismes cerebeleux, latence minimale.'},
  {key:'forge_mcp_security',label:'Systeme Immunitaire',path:'app/forge_mcp_security.py',size:19522,desc:'CRITICAL_FILES, DANGEROUS_PATTERNS, check_db_quality(). Reponse proportionnee (warn pas block). Apprend des attaques.',role:'Memoire immunitaire — signal sans paralyser.'},
  {key:'forge_watch_agent',label:'Veille Active (Yeux+Bouche)',path:'app/forge_watch_agent.py',size:16817,desc:'Pipeline N8N 6 etapes repris si interrompu. LLM keywords -> SearXNG -> LLM refine -> RAG ingest -> biblio_raw. Interface /forge/watch.',role:'Perception+ingestion — yeux (SearXNG) et bouche (biblio) automatiques.'},
  {key:'forge_biblio_worker',label:'Systeme Digestif',path:'app/forge_biblio_worker.py',size:6874,desc:'Poll biblio_raw queued -> refine_query (Groq) -> SearXNG -> reviewed. Intervalle adaptatif selon mood.',role:'Ingestion — transforme signal externe en connaissance structuree (RAG).'},
  {key:'forge_llm_router',label:'Cascade LLM',path:'app/forge_llm_router.py',size:39984,desc:'24 providers + Ollama local. Circuit breaker. router_call() timeout adaptatif via get_mood(). Fallback auto.',role:'Metabolisme — selectionne le bon substrat selon ressources disponibles.'},
  {key:'forge_mcp_registry',label:'Registre MCP',path:'app/forge_mcp_registry.py',size:71752,desc:'Dispatch tous les tools. get_tool_list(ring,agent) filtre. check_access() avant chaque tool. Commit Guard AST.',role:'Systeme nerveux peripherique — route les stimuli vers le bon organe.'},
  {key:'forge_rag_engine',label:'Hippocampe (RAG)',path:'app/forge_rag_engine.py',size:66091,desc:'Vectorisation + FTS + recherche semantique. embeddings.db. Domaines : episodic/longterm/code/admin_charter.',role:'Consolidation memorielle — encode, indexe, retrouve cross-session.'},
  {key:'forge_state_manager',label:'Etat Partage',path:'app/forge_state_manager.py',size:12539,desc:'Notifications pendantes, bridge_state.json, drain_notifications() pour poll reflexe. EventBus interne.',role:'Plasma sanguin — transporte les signaux sans les interpreter.'},
  {key:'forge_network_logger',label:'Systeme Sensoriel',path:'app/forge_network_logger.py',size:13161,desc:'NetworkChannel enum (STDIO_CLAUDE, GEMINI_OAUTH...). Canal de provenance de chaque signal. network_log table.',role:'Transduction sensorielle — encode le gradient du signal entrant.'},
  {key:'forge_biblio_core',label:'Extraction Biblio',path:'app/forge_biblio_core.py',size:13917,desc:'extract_from_text (Mistral) -> sources. insert_biblio_raw hash MD5 chain. promote_entry -> bibliography.',role:'Glandes exocrines — secretent connaissance structuree depuis texte brut.'},
];
async function renderDoc(){
  // Census RÉEL (organ_map_full.json, 714 modules) en bannière -> Doc Organes devient vrai +
  // auto-MAJ. Les cartes ci-dessous = carte biologique CURÉE (organes-clés), honnêtement labellée.
  let banner='';
  try{
    const r=await fetch('/api/organs'); const c=await r.json();
    if(c.ok){
      const top=Object.entries(c.tally||{}).sort((a,b)=>b[1]-a[1]);
      const gen=(c.provenance&&(c.provenance.generated||c.provenance.date))||'census';
      banner=`<div style="grid-column:1/-1;padding:10px 14px;background:rgba(34,197,94,.06);border:1px solid rgba(34,197,94,.22);border-radius:8px;margin-bottom:10px">
        <b style="color:#22c55e">&#128202; Census RÉEL</b> &middot; ${c.total} modules &middot; ${c.n_organs} organes &middot; <span style="color:#6c6c8d">${gen}</span>
        <div style="font-size:11px;color:#a4a6ba;margin-top:5px">${top.map(([o,n])=>o+' <b>'+n+'</b>').join(' &middot; ')}</div></div>`;
    }
  }catch(e){}
  const q=(document.getElementById('docQ').value||'').toLowerCase();
  const filt=ORGANS.filter(o=>!q||o.label.toLowerCase().includes(q)||o.desc.toLowerCase().includes(q));
  document.getElementById('docCnt').textContent=filt.length+' organes-clés (carte curée)';
  document.getElementById('docGrid').innerHTML=banner+filt.map(o=>`
    <div class="doc-card" onclick="openDoc('${o.key}')">
      <h3>${o.label}<span class="doc-kb">${Math.round(o.size/1024*10)/10}kb</span></h3>
      <div class="doc-path">${o.path}</div>
      <div class="doc-desc">${o.desc.slice(0,110)}...</div>
      <div class="doc-role">${o.role.slice(0,90)}</div>
    </div>`).join('');
}
function openDoc(key){
  const o=ORGANS.find(x=>x.key===key);if(!o)return;
  document.getElementById('docMTitle').textContent=o.label;
  document.getElementById('docMBody').textContent=`FICHIER  : ${o.path}\nTAILLE   : ${o.size} bytes\n\nROLE BIOLOGIQUE\n${'-'.repeat(36)}\n${o.role}\n\nDESCRIPTION\n${'-'.repeat(36)}\n${o.desc}\n\nPOUR LIRE\n${'-'.repeat(36)}\nNokido:read action=file path=${o.path} lines=80`;
  document.getElementById('docModal').classList.add('vis');
}
function closeDoc(){document.getElementById('docModal').classList.remove('vis');}

// AUDIT LOGS
async function loadLogs(){
  // Decision owner 25/09 : lecture SEULE par /api/network/history, route publique EXISTANTE qui
  // lit deja mcp_audit.log (net_history_from_audit) -- au lieu de l'outil `read` via /mcp.
  try{const r=await fetch('/api/network/history?limit=200',{signal:AbortSignal.timeout(10_000)});
  const rows=await r.json();if(!r.ok||!Array.isArray(rows))throw new Error('journal indisponible (HTTP '+r.status+')');
  const text=rows.map(e=>e.raw||[e.ts,(e.channel||'')+':'+(e.tool||''),e.status].join(' | ')).join('\n');
  const filt=(document.getElementById('logF').value||'').toLowerCase();
  const lines=text.split('\n').filter(l=>!filt||l.toLowerCase().includes(filt));
  document.getElementById('logCnt').textContent=lines.length;
  document.getElementById('logsBody').innerHTML=lines.map(l=>{
    const cls=l.includes('ERR')?'lerr':l.includes('WARN')||l.includes('BLOCK')||l.includes('SECRET')?'lwarn':l.includes('OK')?'lok':'linfo';
    return`<div class="ll ${cls}">${l.replace(/</g,'&lt;')}</div>`;
  }).join('');}catch(e){const el=document.getElementById('logsBody');if(el)el.innerHTML='<div class="empty">'+String(e.message).replace(/</g,'&lt;')+'</div>';}
}

// STATUS + MCP
async function loadStatus(){
  try{const r=await fetch('/health');const d=await r.json();
  setDot(true);
  document.getElementById('hv').textContent=d.version||'?';
  document.getElementById('hvS').textContent=d.version||'?';}
  catch{setDot(false);}
}
async function loadMCPServers(){
  try{const r=await fetch('/api/mcp/servers');const d=await r.json();
  if(d.error){document.getElementById('mcpServerList').innerHTML=`<div class="empty">${d.error}</div>`;return;}
  document.getElementById('mcpServerList').innerHTML=(d.servers||[]).map(s=>`
    <div class="srow">
      <div><div class="slbl">${s.name}</div><div class="sdesc">${s.url||s.command||''}</div></div>
      <div class="toggle ${s.enabled!==false?'on':''}" onclick="this.classList.toggle('on')"></div>
    </div>`).join('');}
  catch(e){document.getElementById('mcpServerList').innerHTML=`<div class="empty">Err: ${e.message}</div>`;}
}
async function resetFlags(){const r=await fetch('/api/mcp/flags',{method:'POST',credentials:'same-origin'});const d=await r.json().catch(()=>({}));document.getElementById('mcpNote').textContent=r.ok?'Flags reinitialises':('Refuse ('+r.status+') : '+(d.detail||d.error||'?'));}

// INIT
async function loadHistory(){
  try{const r=await fetch('/api/network/history?limit=300');const d=await r.json();
  (d.events||[]).reverse().forEach(e=>addEv(e));}catch{}
}
setInterval(loadMood,30000);
setInterval(()=>{if(document.getElementById('panel-organism').classList.contains('active'))renderOrganism();},15000);
loadStatus();loadHistory();loadMood();startStream();renderDoc();
</script></body></html>"""

# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬
# APP
# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬

WATCH_HTML = r"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>Nokido Watch</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Consolas','Monaco',monospace;background:#0d1117;color:#c9d1d9;font-size:12px;height:100vh;display:flex;flex-direction:column}
header{padding:8px 16px;background:#161b22;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:12px}
header h1{color:#58a6ff;font-size:14px;font-weight:700}header h1 span{color:#ff9770}
.toolbar{padding:8px 12px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
input,select{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px;font-family:inherit;font-size:11px}
.btn{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:4px 10px;border-radius:4px;cursor:pointer;font-family:inherit;font-size:11px}
.btn:hover{background:#30363d} .btn.ok{color:#56d364} .btn.danger{color:#f85149}
main{flex:1;overflow:hidden;display:flex;gap:0}
/* PIPELINE CANVAS */
.pipeline-area{flex:1;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:16px}
.job-card{background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}
.job-header{padding:10px 14px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #30363d}
.job-theme{font-weight:700;color:#c9d1d9;flex:1}
.job-id{font-size:9px;color:#8b949e}
.job-agent{font-size:10px;padding:1px 6px;border-radius:3px;background:rgba(255,151,112,.15);color:#ff9770}
/* NODES pipeline N8N style */
.pipeline-nodes{display:flex;align-items:center;padding:14px;gap:0;overflow-x:auto}
.node{display:flex;flex-direction:column;align-items:center;gap:4px;min-width:80px}
.node-circle{width:44px;height:44px;border-radius:50%;border:2px solid #30363d;background:#0d1117;display:flex;align-items:center;justify-content:center;font-size:18px;transition:.3s;position:relative}
.node-circle.active{border-color:#58a6ff;box-shadow:0 0 10px rgba(88,166,255,.4);animation:npulse 1.5s infinite}
.node-circle.done{border-color:#56d364;background:rgba(86,211,100,.1)}
.node-circle.error{border-color:#f85149;background:rgba(248,81,73,.1)}
.node-circle.pending{border-color:#30363d;opacity:.5}
@keyframes npulse{0%,100%{box-shadow:0 0 6px rgba(88,166,255,.3)}50%{box-shadow:0 0 14px rgba(88,166,255,.6)}}
.node-label{font-size:9px;color:#8b949e;text-align:center;max-width:70px}
.node-by{font-size:8px;color:#58a6ff;text-align:center}
.connector{flex:1;height:2px;background:#30363d;min-width:16px;position:relative}
.connector.active{background:linear-gradient(90deg,#56d364,#58a6ff);animation:flow 1s infinite}
@keyframes flow{0%{background-position:0%}100%{background-position:200%}}
.connector.done{background:#56d364}
/* JOB DETAILS */
.job-details{padding:8px 14px;font-size:10px;color:#8b949e;display:flex;gap:16px;border-top:1px solid #30363d;flex-wrap:wrap}
.detail-item b{color:#c9d1d9}
/* LOG PANEL */
.log-panel{width:320px;border-left:1px solid #30363d;display:flex;flex-direction:column;background:#0d1117}
.log-hdr{padding:8px 12px;border-bottom:1px solid #30363d;font-size:11px;color:#8b949e}
.log-body{flex:1;overflow-y:auto;padding:8px;font-size:10px;line-height:1.6}
.log-line{padding:2px 0;border-bottom:1px solid #161b22}
.log-step{color:#58a6ff;font-weight:700} .log-ok{color:#56d364} .log-err{color:#f85149} .log-pending{color:#8b949e}
</style></head><body>
<header><h1>Nokido <span>Watch</span></h1><span style="color:#8b949e;font-size:10px">Veille active — pipeline N8N</span></header>
<div class="toolbar">
  <input id="themeInput" type="text" placeholder="Thème de veille (ex: autopoiesis LLM architecture 2025)..." style="flex:1;min-width:200px">
  <select id="ideaId"><option value="veille_active">veille_active</option><option value="biblio_auto">biblio_auto</option></select>
  <button class="btn ok" onclick="createJob()">▶ Lancer veille</button>
  <button class="btn" onclick="loadJobs()">↻ Refresh</button>
  <span style="color:#8b949e;font-size:10px">SearXNG → LLM → RAG → biblio_raw</span>
</div>
<main>
  <div class="pipeline-area" id="pipelineArea"><div style="color:#8b949e;padding:20px;text-align:center">Aucun job actif. Lance une veille ci-dessus.</div></div>
  <div class="log-panel">
    <div class="log-hdr">Live stream</div>
    <div class="log-body" id="logBody"></div>
  </div>
</main>
<script>
const STEPS=[
  {key:'keywords', icon:'🧠', label:'Mots-clés', by:'LLM local'},
  {key:'verify_kw',icon:'✅', label:'Vérif',     by:'LLM local'},
  {key:'search',   icon:'👁', label:'SearXNG',   by:'SearXNG'},
  {key:'refine',   icon:'🔬', label:'Raffinage',  by:'LLM local'},
  {key:'ingest',   icon:'💾', label:'Vectorise',  by:'Nokido RAG'},
  {key:'store',    icon:'📚', label:'biblio_raw', by:'biblio_core'},
  {key:'done',     icon:'🏁', label:'Terminé',    by:''},
];
let jobs=[];
function nodeState(job, step){
  const si=STEPS.findIndex(s=>s.key===step);
  const ji=STEPS.findIndex(s=>s.key===job.step);
  if(job.status==='completed'||si<ji) return 'done';
  if(si===ji) return job.status==='error'?'error':'active';
  return 'pending';
}
function renderJobs(){
  const area=document.getElementById('pipelineArea');
  if(!jobs.length){area.innerHTML='<div style="color:#8b949e;padding:20px;text-align:center">Aucun job.</div>';return;}
  area.innerHTML=jobs.map(job=>{
    const nodes=STEPS.map((s,i)=>{
      const st=nodeState(job,s.key);
      const conn=i<STEPS.length-1?`<div class="connector ${st==='done'?'done':st==='active'?'active':''}"></div>`:'';
      return`<div class="node">
        <div class="node-circle ${st}">${s.icon}</div>
        <div class="node-label">${s.label}</div>
        <div class="node-by">${s.by}</div>
      </div>${conn}`;
    }).join('');
    const statusCol=job.status==='completed'?'#56d364':job.status==='error'?'#f85149':job.status==='running'?'#58a6ff':'#8b949e';
    return`<div class="job-card">
      <div class="job-header">
        <span class="job-theme">${job.theme}</span>
        <span class="job-agent">${job.agent||'SYSTEM'}</span>
        <span style="color:${statusCol};font-size:10px;font-weight:700">${job.status}</span>
        <span class="job-id">${job.id}</span>
      </div>
      <div class="pipeline-nodes">${nodes}</div>
      <div class="job-details">
        <div class="detail-item">Étape: <b>${job.step}</b></div>
        <div class="detail-item">Indexés: <b>${job.n_ingested||0}</b></div>
        <div class="detail-item">Stockés: <b>${job.n_stored||0}</b></div>
        <div class="detail-item">Créé: <b>${(job.created_at||'').slice(11,19)}</b></div>
        ${job.error?`<div class="detail-item" style="color:#f85149">Erreur: ${job.error}</div>`:''}
      </div>
    </div>`;
  }).join('');
}
async function loadJobs(){
  try{const r=await fetch('/api/watch/jobs');const d=await r.json();jobs=d.jobs||[];renderJobs();}
  catch(e){console.error(e);}
}
async function createJob(){
  const theme=document.getElementById('themeInput').value.trim();
  const ideaId=document.getElementById('ideaId').value;
  if(!theme){alert('Thème requis');return;}
  try{
    const r=await fetch('/api/watch/create',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme,idea_id:ideaId})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){alert('Refuse ('+r.status+') : '+(d.detail||d.error||'?'));return;}
    document.getElementById('themeInput').value='';
    addLog({type:'watch_step',step:'keywords',status:'pending',theme,job_id:d.job_id});
    loadJobs();
  }catch(e){alert('Erreur: '+e.message);}
}
function addLog(evt){
  const body=document.getElementById('logBody');
  const t=(evt.updated_at||evt.ts||'').slice(11,19)||new Date().toTimeString().slice(0,8);
  const cls=evt.status==='completed'?'log-ok':evt.status==='error'?'log-err':evt.status==='running'?'log-step':'log-pending';
  const div=document.createElement('div');
  div.className='log-line '+cls;
  div.textContent=`[${t}] ${evt.theme?.slice(0,25)||'?'} → ${evt.step} (${evt.status})`;
  body.appendChild(div);
  body.scrollTop=body.scrollHeight;
  if(body.children.length>200)body.removeChild(body.children[0]);
}
// SSE stream
function startStream(){
  const es=new EventSource('/api/watch/stream');
  es.onmessage=e=>{try{const d=JSON.parse(e.data);if(d.type==='watch_step'){addLog(d);loadJobs();}}catch{}};
  es.onerror=()=>setTimeout(startStream,3000);
}
setInterval(loadJobs,5000);
loadJobs();startStream();
</script></body></html>"""

# ── WATCH AGENT HANDLERS ──────────────────────────────────────────────────
import queue as _wqueue

_WATCH_SSE_CLIENTS: list = []
_WATCH_SSE_LOCK = threading.Lock()


def _watch_sse_push(event: dict):
    """Callback enregistré dans forge_watch_agent pour broadcast SSE."""
    data = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
    with _WATCH_SSE_LOCK:
        dead = []
        for q in _WATCH_SSE_CLIENTS:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            _WATCH_SSE_CLIENTS.remove(q)


# Enregistrer callback au boot
try:
    import os as _wo
    import sys as _ws

    _wapp = str(_wo.path.join(_wo.path.dirname(__file__), "..", "app"))
    if _wapp not in _ws.path:
        _ws.path.insert(0, _wapp)
    from nokido_agent.app.forge_watch_agent import register_sse_callback as _wreg
    from nokido_agent.app.forge_watch_agent import resume_pending as _wresume

    _wreg(_watch_sse_push)
    _wresume()
    logger.info("WatchAgent SSE callback enregistré + pending repris")
except Exception as _we:
    logger.debug(f"[watch_agent] boot skip: {_we}")


async def watch_ui(request):
    # HTMLResponse / JSONResponse importes localement : ce handler vit au
    # module-level, hors closure de _build_app() ou ces noms sont importes.
    from starlette.responses import HTMLResponse

    return HTMLResponse(WATCH_HTML)


async def watch_jobs_api(request):
    from starlette.responses import JSONResponse

    try:
        import os as _wo
        import sys as _ws

        _wapp = str(_wo.path.join(_wo.path.dirname(__file__), "..", "app"))
        if _wapp not in _ws.path:
            _ws.path.insert(0, _wapp)
        from nokido_agent.app.forge_watch_agent import list_jobs as _ljobs

        return JSONResponse({"jobs": _ljobs(50)})
    except Exception as e:
        return JSONResponse({"error": str(e), "jobs": []})


async def watch_create_api(request):
    from starlette.responses import JSONResponse

    try:
        body = await request.json()
        theme = body.get("theme", "").strip()
        idea_id = body.get("idea_id", "veille_active")
        # ATTRIBUTION PROUVEE (2026-09-24, AUTH-6) : le champ `agent` du corps n'est plus lu.
        # Le principal est pose par `_garde_ui` depuis la preuve (session UI ou jeton admin) ;
        # « une attribution ne se declare pas ».
        agent = getattr(request.state, "principal", None) or "INCONNU"
        if not theme:
            return JSONResponse({"error": "theme requis"}, status_code=400)
        import os as _wo
        import sys as _ws

        _wapp = str(_wo.path.join(_wo.path.dirname(__file__), "..", "app"))
        if _wapp not in _ws.path:
            _ws.path.insert(0, _wapp)
        from nokido_agent.app.forge_watch_agent import create_job as _cjob

        job_id = _cjob(theme, idea_id=idea_id, agent=agent)
        return JSONResponse({"ok": True, "job_id": job_id, "theme": theme})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def watch_stream_api(request):
    from starlette.responses import StreamingResponse

    q: _wqueue.Queue = _wqueue.Queue(maxsize=200)
    with _WATCH_SSE_LOCK:
        _WATCH_SSE_CLIENTS.append(q)
        _abonnes = len(_WATCH_SSE_CLIENTS)
    _sse_trace("open", _abonnes, flux="watch")

    async def gen():
        # JSON valide : la version precedente emettait `"{"type":"connected"}""`,
        # le JSON.parse du client echouait des le premier evenement.
        yield 'data: {"type":"connected"}\n\n'
        try:
            while True:
                try:
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: q.get(timeout=20)
                    )
                    yield data
                except Exception:
                    yield ": ping\n\n"
        finally:
            with _WATCH_SSE_LOCK:
                try:
                    _WATCH_SSE_CLIENTS.remove(q)
                except ValueError:
                    pass
                _restants = len(_WATCH_SSE_CLIENTS)
            _sse_trace("close", _restants, flux="watch")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── INBOX SSE — /inbox/<agent> long-poll ─────────────────────────────────────
# Réactivité ms : Nokido pousse dès qu'un MessageFrame arrive dans la queue.
# Le daemon n'a plus besoin de poll toutes les 20s — il garde la connexion ouverte.


def _portee_suffisante(jeton: str, scope: str, action: str):
    """La PORTEE du porteur couvre-t-elle `scope:action` ?

        True  -> CapabilityToken valide, portee suffisante
        False -> CapabilityToken valide, portee INSUFFISANTE
        None  -> ce n'est pas un CapabilityToken : l'ancien contrat decide

    `None` est ce qui rend ce cablage RETROCOMPATIBLE. Les jetons statiques ne
    portent aucune portee ; leur refuser l'acces ici couperait tous les
    appelants actuels sans rien prouver de plus. La portee ne contraint donc
    que ceux qui en ont une -- et A1 vient tout juste de rendre possible d'en
    demander une.

    `_resolve_ring` decode deja ce jeton, mais ne rend que `(ring, sub)` : ses
    `scopes` sont calcules puis JETES. On ne l'elargit pas pour autant -- il
    garde son contrat -- on redemande la portee a sa source.

        ABSENCE_DE_DONNEE != DONNEE_RECONSTRUITE

    La decision elle-meme n'est pas reecrite : `CapabilityToken.can(scope,
    action)` existe et savait deja repondre -- ses seuls appelants vivaient
    dans un fichier de TEST, jamais dans le produit.

        EXISTS != CALLED

    Fail-closed : un jeton qui SE PRESENTE comme capability (3 segments) mais
    dont la verification echoue rend False, jamais None -- sinon un jeton
    expire ou revoque retomberait sur l'ancien contrat, et le durcissement
    s'ouvrirait exactement sur les jetons qu'il doit refuser.
    """
    if not jeton or jeton.count(".") < 1:
        return None
    try:
        from nokido_agent.app.forge_integrity import CapabilityToken, get_manager
        import base64 as _b64
        import json as _json
        _tete = jeton.split(".")[0]
        _charge = _json.loads(_b64.urlsafe_b64decode(_tete + "=" * (-len(_tete) % 4)))
        if not {"sub", "ring", "exp"} <= set(_charge):
            return None                       # pas un capability : ancien contrat
    except Exception:  # noqa: BLE001
        return None                           # indecodable : ancien contrat
    try:
        cap = CapabilityToken.decode(jeton, get_manager()._secret)
    except Exception as e:  # noqa: BLE001 — fail-closed, et on le DIT
        logger.info("[portee] capability presente mais NON verifiee (%s) — refus",
                    type(e).__name__)
        return False
    return bool(cap.can(scope, action))


def _identite_inbox(request) -> dict:
    """IDENTITY PROOF — l'identite COMPLETE, `sujet_prouve` inclus.

    `_resolve_ring` ne rend que `(ring, agent)` : la preuve y est calculee puis
    PERDUE. Plutot que de la re-deriver de `(ring, agent)` -- reconstruire une
    donnee a partir de champs qui ne la portent pas -- on la redemande a sa
    SOURCE, `forge_videur.resolve_identity`.

        ABSENCE_DE_DONNEE != DONNEE_RECONSTRUITE

    `_resolve_ring` n'est PAS elargi pour autant : il garde son contrat et ne
    devient pas un resolveur universel portant tous les etats.

    L'extraction des credentials duplique la sienne. C'est assume et verrouille
    par NR : les deux chemins doivent nommer le MEME agent, sinon la duplication
    derive en silence.

    Fail-closed : toute erreur rend une identite NON prouvee.
    """
    vide = {"agent": None, "via": None, "sujet_prouve": False}
    try:
        auth = request.headers.get("Authorization", "") or ""
        if not auth.lower().startswith("bearer "):
            return vide
        jeton = auth[7:].strip()
        nom = (request.headers.get("LaForge-Agent-Name")
               or request.headers.get("Agent-Name")
               or request.headers.get("X-Agent-Name") or "").upper().strip()
        hote = request.client.host if request.client else "unknown"
        from nokido_agent.app.forge_videur import resolve_identity as _vr
        ident = _vr(nom, jeton, local=hote in ("127.0.0.1", "::1", "localhost"),
                    agent_tokens=_AGENT_TOKENS, hub_token=HUB_TOKEN)
        return ident if isinstance(ident, dict) else vide
    except Exception as e:  # noqa: BLE001 — fail-closed, et on le DIT
        logger.warning("[inbox] identite INDETERMINEE (%s) — refus, pas de repli "
                       "sur le nom declare", type(e).__name__)
        return vide


async def inbox_stream(request):
    """
    GET /inbox/{agent_id}
    Long-poll SSE : reste ouvert jusqu'à réception d'un message.
    Le daemon se reconnecte immédiatement après chaque message traité.
    """
    from starlette.responses import JSONResponse as _JR
    from starlette.responses import StreamingResponse as _SR

    agent_id = request.path_params.get("agent_id", "")
    if not agent_id:
        return _JR({"error": "agent_id requis"}, status_code=400)

    # ── OWNERSHIP AVANT EFFET (contrat owner 2026-09-22) ──────────────────
    # `_INBOX.pop()` RETIRE le message : qui connaissait un `agent_id` prenait
    # le courrier d'un autre, qui ne le recevait jamais. La decision est prise
    # ICI, avant que le generateur existe -- la placer dedans rendrait un
    # `StreamingResponse` 200, et un DENY n'y serait qu'une ligne dans un flux
    # deja ouvert.
    #
    #     DENY -> generateur NON CREE -> `pop()` JAMAIS ATTEINT
    #     et pas seulement : DENY -> reponse 403.
    try:
        from nokido_agent.app.forge_videur import peut_consommer_boite as _pcb
    except Exception as _de:  # noqa: BLE001 — fail-closed, et on le DIT
        logger.warning("[inbox] decision d'ownership INDISPONIBLE (%s) — refus",
                       type(_de).__name__)
        return _JR({"error": "ownership indecidable"}, status_code=503)
    _ident = _identite_inbox(request)
    _dec = _pcb(agent_id, sujet=_ident.get("agent"),
                sujet_prouve=bool(_ident.get("sujet_prouve")))
    if not _dec.get("allow"):
        logger.info("[inbox] DENY %s via=%s — %s", agent_id,
                    _ident.get("via"), _dec.get("reason"))
        return _JR({"error": "forbidden", "reason": _dec.get("reason")},
                   status_code=403)

    try:
        import os as _io
        import sys as _is

        _iapp = _io.path.join(_io.path.dirname(__file__), "..", "app")
        if _iapp not in _is.path:
            _is.path.insert(0, _iapp)
        from nokido_agent.app.forge_message_frame import INBOX as _INBOX
    except Exception as _ie:
        from starlette.responses import JSONResponse as _JR

        return _JR({"error": f"INBOX unavailable: {_ie}"}, status_code=503)

    async def _gen():
        NL = "\n\n"
        _conn_msg = json.dumps({"type": "connected", "agent": agent_id})
        yield "data: " + _conn_msg + NL
        while True:
            if await request.is_disconnected():
                break
            frame = await _INBOX.pop(agent_id, timeout=25.0)
            if await request.is_disconnected():
                break
            if frame is None:
                yield ": ping" + NL
                continue
            if frame.is_expired():
                _exp_msg = json.dumps({"type": "expired", "frame_id": frame.frame_id})
                yield "data: " + _exp_msg + NL
                continue
            yield "data: " + frame.to_json() + NL
            break

    return _SR(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "http://127.0.0.1:8766",
        },
    )


async def inbox_status(request):
    """GET /inbox/status — taille des queues par agent."""
    from starlette.responses import JSONResponse

    try:
        import os as _io
        import sys as _is

        _iapp = _io.path.join(_io.path.dirname(__file__), "..", "app")
        if _iapp not in _is.path:
            _is.path.insert(0, _iapp)
        from nokido_agent.app.forge_message_frame import INBOX as _INBOX

        return JSONResponse({"queues": _INBOX.all_sizes()})
    except Exception as e:
        return JSONResponse({"error": str(e)})


async def inbox_push(request):
    # 410 GONE (2026-09-24, chantier d'authentification, AUTH-5). MESURE du 21/09 : cette
    # route lisait le corps et rendait {"ok": True} SANS AUCUN EFFET, pendant que l'audit
    # la comptait comme MUTANTE sans garde. Authentifier un no-op serait du bruit de
    # securite ; on la RETIRE explicitement. Appelants mesures le 24/09 : AUCUN (seuls la
    # declaration de route et les instruments d'audit la nomment). Le 410 garde la trace
    # et empeche qu'elle redevienne silencieusement une mutation.
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": False, "error": "gone",
                         "detail": "/api/push est retiree : elle n'avait aucun effet"},
                        status_code=410)


async def auth_login(request):
    from starlette.responses import JSONResponse
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        
    role_id = body.get("role_id")
    if not role_id:
        return JSONResponse({"error": "Missing role_id"}, status_code=400)
        
    secret_id = body.get("secret_id")
    timestamp = body.get("timestamp")
    signature = body.get("signature")
    # LIEN AU PORTEUR (RFC 9449). Le demandeur peut presenter la cle publique
    # dont il prouvera la possession a chaque requete : le jeton emis porte
    # alors son empreinte (`cnf.jkt`, RFC 7638) et devient inutilisable sans la
    # cle privee correspondante. Un bearer non lie, lui, est rejouable par
    # quiconque le vole -- il prouve la connaissance d'un secret, jamais
    # l'identite du porteur.
    #
    # Champ OPTIONNEL, et volontairement : l'exiger avant qu'un seul appelant
    # sache le produire ne durcirait rien, ca rendrait le corps muet.
    dpop_jwk = body.get("dpop_jwk")
    if dpop_jwk is not None and not isinstance(dpop_jwk, dict):
        return JSONResponse(
            {"error": "dpop_jwk doit etre un objet JWK"}, status_code=400)
    
    try:
        from nokido_agent.app.forge_auth_tokens import login_agent
        token = login_agent(
            role_id=role_id,
            secret_id=secret_id,
            timestamp=timestamp,
            signature=signature,
            agent_tokens=_AGENT_TOKENS,
            dpop_jwk=dpop_jwk,
        )
        # RFC 9449 §6 exige qu'on puisse identifier DE FACON FIABLE si un jeton
        # est lie. `bound` n'est pas decoratif : un porteur qui croit son jeton
        # lie alors qu'il ne l'est pas se croit protege pour rien, et c'est
        # exactement le genre de croyance qu'on ne detecte qu'apres coup.
        return JSONResponse({"token": token, "expires_in": 1800,
                             "bound": bool(dpop_jwk)})
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=401)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return JSONResponse({"error": "Internal server error"}, status_code=500)


async def auth_login_renouveler(request):
    """`POST /api/login/renouveler` -- jeton court injecte par le superviseur (2026-09-28).

    ECHANGE DE JETON RFC 8693 : le porteur d'un jeton court encore valide en obtient un
    neuf en le presentant (`subject_token`, corps form-urlencoded), sans jamais tenir de
    secret statique. Toute la logique (boucle locale, forme RFC, revocation, ring,
    non-elevation) vit dans `forge_auth_tokens.traiter_renouvellement`, testable sans le hub."""
    from starlette.responses import JSONResponse
    # Borne d'ORIGINE posee ICI aussi (defense en profondeur, et visible de l'inventaire
    # des routes) : hors boucle locale, 403 avant tout. LOCAL_ONLY != TRUSTED -- la
    # preuve d'identite reste le `subject_token`, verifie par `renouveler`.
    ch = (request.client.host if request.client else "") or ""
    if ch not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": "access_denied", "error_description": "localhost only"},
                            status_code=403, headers={"Cache-Control": "no-store"})
    try:
        from nokido_agent.app.forge_auth_tokens import traiter_renouvellement
        statut, corps, entetes = traiter_renouvellement(
            ch, request.headers.get("content-type", ""), await request.body())
        return JSONResponse(corps, status_code=statut, headers=entetes)
    except Exception as e:  # noqa: BLE001
        logger.error("Renouvellement error: %s", type(e).__name__)
        return JSONResponse({"error": "Internal server error"}, status_code=500)


_boot_probe("=== module top-level FINI (tous imports forge_*+init) -> def _build_app ===")


async def _build_app():
    _boot_probe("_build_app: debut (construction routes/registry/RAG)")
    from starlette.applications import Starlette
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
    from starlette.routing import Route

    async def health(request: Request):
        return JSONResponse({"status": "ok", "version": "18.3", "ts": _dt.now().isoformat()})

    async def health_liveness(request: Request):
        """LIVENESS — le processus repond-il ? Rien d'autre.

        F1 de la veille (`tests litellm proxy`) : « route /health/liveness au nom
        standard, et un test qui MESURE son temps de reponse ».

        Une sonde de liveness doit etre TRIVIALE : elle ne touche aucune
        dependance, sinon une base lente fait redemarrer un process sain. C'est
        exactement ce que `/health` faisait deja — il rendait `ok` sans rien
        verifier. Le defaut n'etait pas ce comportement, c'etait son NOM : un
        orchestrateur qui lit `/health` croit interroger la sante complete.
        """
        t0 = time.monotonic()
        return JSONResponse({
            "status": "alive",
            "version": "18.3",
            "ts": _dt.now().isoformat(),
            "latency_ms": round((time.monotonic() - t0) * 1000, 3),
        })

    # `def` : un capteur de sante qui GELE est pire qu'absent -- il meurt avec
    # le patient qu'il devait ausculter. En threadpool, il repond meme quand la
    # boucle est prise. `timeout=3` ne borne que l'attente d'un VERROU SQLite,
    # pas l'ouverture d'une base de 25 Go : trois secondes dans la boucle
    # restaient trois secondes de serveur entier a l'arret. (2026-09-21)
    def health_readiness(request: Request):
        """READINESS — le hub est-il en etat de SERVIR ?

        LA distinction que l'absence de ces deux routes masquait, et qui a deja
        coute : `/health` a repondu `ok` avec **V: NON MONTE** (motif recidivant
        `statut_declare_vs_reel`). Le hub etait VIVANT et PAS PRET, et rien ne
        permettait de le dire.

        Chaque dependance rend TROIS etats, jamais deux : `ok`, `ko`, ou
        `inconnu` avec son motif. Un `inconnu` ne compte JAMAIS comme sain — on
        classe par liste BLANCHE (constitution semantique) : n'est pret que ce
        qui est PROUVE pret.

        503 quand une dependance critique est `ko` ou `inconnu` : un orchestrateur
        doit pouvoir retirer ce hub du service sans lire le corps de la reponse.
        """
        t0 = time.monotonic()
        deps: dict = {}

        # Base RAG : ouvrable en lecture ? (sans COUNT — un COUNT sur cette base
        # a couche le hub le 2026-09-03.)
        try:
            import sqlite3 as _sq3
            _db = str(ROOT / "RAG" / "embeddings.db")
            _c = _sq3.connect(_db, timeout=3)
            _c.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
            _c.close()
            deps["rag_db"] = {"etat": "ok"}
        except Exception as _e:
            deps["rag_db"] = {"etat": "ko", "motif": f"{type(_e).__name__}: {str(_e)[:90]}"}

        # Registre d'outils : charge ?
        try:
            _reg = globals().get("registry") or globals().get("REGISTRY")
            if _reg is None:
                deps["registre_outils"] = {
                    "etat": "inconnu",
                    "motif": "registre non expose dans ce module — non verifiable ici",
                }
            else:
                deps["registre_outils"] = {"etat": "ok"}
        except Exception as _e:
            deps["registre_outils"] = {"etat": "inconnu",
                                       "motif": f"{type(_e).__name__}: {str(_e)[:90]}"}

        # Liste BLANCHE : n'est pret que ce qui est PROUVE pret.
        prets = [k for k, v in deps.items() if v.get("etat") == "ok"]
        non_prets = [k for k, v in deps.items() if v.get("etat") != "ok"]
        pret = not non_prets

        return JSONResponse(
            {
                "status": "ready" if pret else "not_ready",
                "version": "18.3",
                "ts": _dt.now().isoformat(),
                "dependances": deps,
                "prouvees_pretes": prets,
                "non_prouvees": non_prets,
                "latency_ms": round((time.monotonic() - t0) * 1000, 3),
            },
            status_code=200 if pret else 503,
        )

    async def debug_stacks(request: Request):
        """IRM async SANS élévation : tâches asyncio + threads du hub en vol.

        py-spy voit les threads mais PAS les tâches asyncio ; or le hub EST
        asyncio → la saturation est un pileup de tâches. Cet endpoint expose
        asyncio.all_tasks() + leur pile + un histogramme par coroutine (le
        détecteur de pileup : 200× la même coro = goulot). Loopback uniquement.
        Query: ?frames=N (profondeur de pile, défaut 15).
        Roadmap observabilité chantier #2 (alternative no-elevation à py-spy).
        """
        ch = (request.client.host if request.client else "") or ""
        if ch not in ("127.0.0.1", "::1", "localhost"):
            return JSONResponse({"error": "localhost only"}, status_code=403)
        import asyncio as _aio
        import io as _io
        import sys as _sys
        import threading as _th
        import traceback as _tb
        from collections import Counter as _Counter

        try:
            frames = max(1, min(int(request.query_params.get("frames", "15")), 40))
        except Exception:
            frames = 15

        def _short(s: str, n: int = 90) -> str:
            return s if len(s) <= n else s[:n] + "..."

        tasks: list[dict] = []
        hist: "_Counter[str]" = _Counter()
        try:
            cur = _aio.current_task()
            for t in _aio.all_tasks():
                coro = _short(str(t.get_coro()))
                hist[coro] += 1
                buf = _io.StringIO()
                try:
                    t.print_stack(file=buf, limit=frames)
                except Exception as _e:  # noqa: BLE001
                    buf.write(f"<stack err: {_e}>")
                tasks.append({
                    "name": t.get_name(),
                    "self": t is cur,
                    "done": t.done(),
                    "coro": coro,
                    "stack": buf.getvalue().splitlines(),
                })
        except Exception as _e:  # noqa: BLE001
            tasks = [{"error": str(_e)}]

        names = {th.ident: th.name for th in _th.enumerate()}
        threads = []
        for tid, fr in _sys._current_frames().items():
            threads.append({
                "tid": tid,
                "name": names.get(tid, "?"),
                "stack": [ln.rstrip() for ln in _tb.format_stack(fr, limit=frames)],
            })

        return JSONResponse({
            "ts": _dt.now().isoformat(),
            "n_tasks": len(tasks),
            "n_threads": len(threads),
            "coro_histogram": dict(hist.most_common(15)),
            "tasks": tasks,
            "threads": threads,
        })

    async def swarm_health(request: Request):
        """Lightweight health for Tailscale-mesh edge nodes.

        Returns 200 if node can accept load, 429 if saturated.
        Body always includes telemetry snapshot from forge_resource_manager.
        """
        try:
            import os as _o
            import sys as _s

            _a = _o.path.join(_o.path.dirname(__file__), "..", "app")
            if _a not in _s.path:
                _s.path.insert(0, _a)
            from nokido_agent.app.forge_resource_manager import get_snapshot, should_throttle

            snap = get_snapshot()
            throttled = should_throttle()
            ram_free = snap.get("ram_free_gb", 0.0)
            gpu_pct = snap.get("gpu_pct") or 0.0
            can_accept = (not throttled) and ram_free > 4.0 and gpu_pct < 80.0
            body = {
                "status": "up",
                "can_accept_load": can_accept,
                "throttle_active": throttled,
                "telemetry": {
                    "ram_pct": snap.get("ram_pct"),
                    "ram_free_gb": ram_free,
                    "ram_total_gb": snap.get("ram_total_gb"),
                    "cpu_pct": snap.get("cpu_pct"),
                    "gpu_pct": gpu_pct,
                    "disk_pct": snap.get("disk_pct"),
                    # TDR exposé pour supervisor.ts GPU quarantine (RCA BSOD
                    # 2026-05-24). Sample tous les 60s côté forge_resource_manager.
                    "tdr_recent": snap.get("tdr_recent", 0),
                    "tdr_last_check_ts": snap.get("tdr_last_check_ts", 0.0),
                    "ts": snap.get("ts"),
                },
            }
            return JSONResponse(body, status_code=200 if can_accept else 429)
        except Exception as e:
            return JSONResponse(
                {"status": "error", "error": str(e), "can_accept_load": False},
                status_code=503,
            )

    # `def` : meme classe que `rag_stats` -- SQLite dans la boucle, aucun
    # `await`. Ces tables sont petites aujourd'hui (23 patterns mesures le
    # 2026-09-20) et le premier SELECT n'a pas de LIMIT : ce qui tient
    # aujourd'hui par la TAILLE des donnees, pas par une borne. (2026-09-21)
    def loops_status(request: Request):
        """Expose autonomous_loop_state + dernier audit pour TUI/dashboard."""
        try:
            import sqlite3 as _sq
            from pathlib import Path as _P

            db = _P(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
            cn = _sq.connect(str(db), timeout=3)
            cn.row_factory = _sq.Row
            state = [
                dict(r)
                for r in cn.execute(
                    "SELECT pattern, last_run, last_status, runs_total, runs_success, "
                    "enabled, substr(last_outcome,1,200) as last_outcome "
                    "FROM autonomous_loop_state ORDER BY last_run DESC"
                )
            ]
            audit = [
                dict(r)
                for r in cn.execute(
                    "SELECT pattern, ts, status, substr(outcome,1,200) as outcome "
                    "FROM autonomous_loop_audit ORDER BY ts DESC LIMIT 30"
                )
            ]
            cn.close()
            return JSONResponse(
                {"state": state, "audit_recent": audit, "patterns_count": len(state)}
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def network_ui(request: Request):
        return HTMLResponse(NETWORK_HTML, headers={"Content-Type": "text/html; charset=utf-8"})

    async def network_stream(request: Request):
        q: queue.Queue = queue.Queue(maxsize=500)
        with _SSE_LOCK:
            _SSE_CLIENTS.append(q)
            _abonnes = len(_SSE_CLIENTS)
        _sse_trace("open", _abonnes)

        async def generator():
            yield 'data: {"type":"connected"}\n\n'
            try:
                while True:
                    # `except Exception` et PAS `except:` : un except nu attrape
                    # GeneratorExit, donc la deconnexion du client serait avalee,
                    # la boucle continuerait, et la queue resterait abonnee.
                    try:
                        data = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: q.get(timeout=25)
                        )
                        yield data
                    except Exception:
                        yield ": ping\n\n"
            finally:
                # Desabonnement INCONDITIONNEL : sans lui, chaque onglet ferme
                # laisse un fantome que `_sse_broadcast` continue de remplir.
                with _SSE_LOCK:
                    try:
                        _SSE_CLIENTS.remove(q)
                    except ValueError:
                        pass
                    _restants = len(_SSE_CLIENTS)
                _sse_trace("close", _restants)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    async def network_mood(request: Request):
        """Humeur du systeme en LECTURE SEULE pour /forge/network (decision owner 2026-09-25).
        La page l'obtenait par `run action=python` envoye au hub DEPUIS LE NAVIGATEUR (execution
        de code ; 401 depuis la fermeture du chantier auth). Scalaires seulement : aucun contenu,
        aucune topologie, aucun chemin."""
        try:
            import asyncio as _aio_humeur

            from nokido_agent.app.forge_system_mood import get_mood

            m = await _aio_humeur.get_running_loop().run_in_executor(None, get_mood)
            return JSONResponse({
                "e": m.energy, "c": m.curiosity, "f": m.fatigue, "ia": m.immune_alert,
                "ts": m.ts, "stressed": m.is_stressed(), "idle": m.is_idle(),
                "timeout": m.recommended_timeout(),
            })
        except Exception as e:  # noqa: BLE001 — l'echec est rendu (503 + type), jamais avale
            return JSONResponse({"error": type(e).__name__}, status_code=503)

    async def network_history(request: Request):
        limit = int(request.query_params.get("limit", 200))
        try:
            from nokido_agent.app.forge_network_logger import net_history, net_history_from_audit

            history = net_history(limit=limit)
            if not history:
                history = net_history_from_audit(limit=limit)
            return JSONResponse(history)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def mcp_post(request: Request):
        # Spec MCP 2025-03-26 §security : valider Origin (DNS rebinding)
        origin = request.headers.get("Origin", "")
        if origin and not any(
            origin.startswith(o)
            for o in ["http://127.0.0.1", "http://localhost", "app://", "null", ""]
        ):
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)
        t0 = time.monotonic()
        ring, auth_agent = _resolve_ring(request)
        client_ip = request.client.host if request.client else "unknown"
        agent_hdr = (request.headers.get("LaForge-Agent-Name") or request.headers.get("Agent-Name")
                     or request.headers.get("X-Agent-Name") or auth_agent)  # LaForge-Agent-Name (org-scopé RFC 6648) > Agent-Name > X- legacy
        session_id = request.headers.get("X-Session-Id", "")  # insensible a la casse
        # trace_id (corrélation end-to-end) : extrait du header W3C `traceparent`
        # ou `X-Trace-Id` entrant, sinon nouveau. Posé dans le ContextVar ->
        # tous les sinks in-process (net_log, anchor_*, record_trace) le lisent
        # sans param. Isolation par requête = tâche asyncio Starlette dédiée.
        try:
            from nokido_agent.app.forge_trace_context import extract_headers, session_trace_id, set_trace_id

            # Header W3C explicite gagne (client-driven) ; sinon on chaîne les
            # appels rapprochés d'une même session/agent en un flow corrélé.
            _explicit = extract_headers(dict(request.headers))
            set_trace_id(_explicit or session_trace_id(session_id or agent_hdr or ""))
        except Exception:
            pass
        # ActorContext (#7) : identité PRÉCISE agent×canal×transport posée pour CE
        # request -> lue SANS param par l'audit DB read/write (#8) + tous les sinks.
        try:
            from nokido_agent.app.forge_trace_context import set_actor

            _ach, _atr, _amc = _agent_meta(agent_hdr)
            set_actor(agent_hdr, ring=ring, channel=_ach, transport=_atr, machine=_amc)
        except Exception:
            pass
        _write_agent_presence(agent_hdr, ring)

        if ring < 0:
            _log_network(
                "IN",
                method="UNAUTHORIZED",
                agent=agent_hdr,
                ring=ring,
                status="ERR:401",
                client_ip=client_ip,
                # `request` transmis pour que le journal dise enfin QUI appelle
                # (cf. _origine_appelant) : sans lui, 114 406 rejets anonymes.
                request=request,
            )
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        try:
            body = await request.json()
            body_str = json.dumps(body, ensure_ascii=False)
            _mw_ok, body, _mw_err = validate_mcp_body(body)
            if not _mw_ok:
                return JSONResponse({"error": _mw_err}, status_code=400)
            
            # ── INGRESS ADAPTER (Qualification Dynamique) ──
            adapter = get_ingress_adapter()
            if adapter:
                old_ring = ring
                ring = adapter.qualify_session(agent_hdr, body.get("method", ""), body.get("params", {}), ring)
                if ring != old_ring:
                    logger.info(f"[ingress] Session ring adjusted: {old_ring} -> {ring} (agent={agent_hdr})")
        except:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        method = body.get("method", "")
        bid = body.get("id")

        # ITEM 14 — enrichir IN avec tool name si tools/call
        _in_tool = None
        if method == "tools/call":
            try:
                _in_tool = body.get("params", {}).get("name")
            except Exception:
                pass
        _log_network(
            "IN",
            method=method,
            tool=_in_tool,
            agent=agent_hdr,
            ring=ring,
            payload_in=body_str[:800],
            client_ip=client_ip,
        )

        # Notifications JSON-RPC (notifications/*, ou requête sans id) : AUCUNE réponse JSON-RPC
        # (spec MCP). rmcp strict (codex) envoie notifications/initialized APRÈS initialize ->
        # y répondre une ERROR -32601 cassait le handshake -> codex désactivait nokido.
        # 202 vide = conforme. Fix rmcp-strict 2026-06-16.
        if method.startswith("notifications/") or bid is None:
            from starlette.responses import Response as _Resp

            return _Resp(status_code=202)

        # Reponse du CLIENT a une requete du hub (elicitation, 2026-09-26) : aucune `method`,
        # un `id`. Elle ne resout que la demande de SA session et de SON agent.
        try:
            from nokido_agent.app.forge_mcp_elicitation import est_reponse_client as _est_rep
        except Exception:  # noqa: BLE001 - module illisible : le hub sert quand meme
            _est_rep = None
        if _est_rep is not None and _est_rep(body):
            from starlette.responses import Response as _Resp
            from nokido_agent.app.forge_mcp_elicitation import recevoir_reponse as _rr

            _ok_rep, _pourquoi = _rr(body, request.headers.get("Mcp-Session-Id", ""), agent_hdr)
            logger.info("[mcp/elicitation] reponse client id=%s acceptee=%s (%s)",
                        str(bid)[:60], _ok_rep, _pourquoi)
            return _Resp(status_code=202 if _ok_rep else 400)

        if method == "initialize":
            # Echo la protocolVersion demandée par le client (rmcp négocie sa version ; hardcoder
            # 2025-03-26 cassait si codex envoyait une version différente).
            # NEGOCIATION (2026-09-24, veille lot_B_20) : l'echo AVEUGLE acquiescait a
            # n'importe quelle version. Spec MCP : la version demandee si supportee,
            # sinon la plus recente supportee — et le client decide. Logique pure et
            # testee dans app/forge_mcp_protocole.py (NR test_mcp_protocole_nr).
            from nokido_agent.app.forge_mcp_protocole import (
                INSTRUCTIONS_SERVEUR as _consignes, negocier_version as _negocier)
            _pv, _pv_avert = _negocier((body.get("params") or {}).get("protocolVersion"))
            if _pv_avert:
                logger.warning("[mcp/initialize] %s", _pv_avert)
            # QUI SUPPORTE QUOI — mesure, pas supposition (2026-08-20).
            # La spec 2026-07-28 introduit `elicitation` : le SERVEUR peut demander
            # une confirmation a l'utilisateur (`elicitation/create`, pattern MRTR).
            # Ce serait la bonne place pour « confirmer l'irreversible » : la garde
            # emanerait du hub au lieu de dependre de la politesse de chaque client.
            # MAIS elle n'a d'effet que si le CLIENT declare la capability — sinon le
            # serveur doit rendre `MissingRequiredClientCapabilityError` (-32021).
            # Le hub recevait deja ces capabilities et les JETAIT : on ne pouvait pas
            # savoir si un client saurait repondre. On les journalise donc, sans rien
            # changer au handshake. Quand un client declarera `elicitation`, ce log le
            # dira — et l'implementation cessera d'etre un pari.
            try:
                _cp = (body.get("params") or {})
                _ci = _cp.get("clientInfo") or {}
                _cc = _cp.get("capabilities") or {}
                logger.info(
                    "[mcp/initialize] client=%s v=%s protocole=%s capabilities=%s",
                    _ci.get("name", "?"), _ci.get("version", "?"), _pv,
                    sorted(_cc.keys()) or "aucune",
                )
            except Exception:  # noqa: BLE001 - muet-ok : un log ne casse jamais un handshake
                pass
            # Elicitation (2026-09-26) : l'id rendu ici est celui que le client renverra ;
            # ses capacites y sont attachees pour savoir, au tools/call, s'il sait repondre.
            _mcp_sid = __import__("uuid").uuid4().hex
            try:
                from nokido_agent.app.forge_mcp_elicitation import enregistrer_session as _es

                _es(_mcp_sid, _ci.get("name", "?"), _pv, _cc)
            except Exception as _e_es:  # noqa: BLE001 - un registre ne casse jamais un handshake
                logger.warning("[mcp/initialize] registre d'elicitation non ecrit : %s", _e_es)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": bid,
                    "result": {
                        "protocolVersion": _pv,
                        "serverInfo": {"name": "LaForge-Hub", "version": "18.3"},
                        "capabilities": {"tools": {}},
                        # Consignes COURTES (veille lot_B_15) : elles entrent dans le
                        # prompt de chaque session cliente, a chaque tour.
                        "instructions": _consignes,
                    },
                },
                # Streamable HTTP MCP : émet Mcp-Session-Id pour les clients rmcp STRICTS
                # (codex CLI) qui exigent une session pour enchaîner la notif `initialized`.
                # Claude/Gemini (stateless) ignorent ce header. Hub stateless = id non tracké.
                headers={"Mcp-Session-Id": _mcp_sid},
            )

        if method == "tools/list":
            from nokido_agent.app.forge_mcp_registry import get_registry

            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": bid,
                    "result": {"tools": get_registry().get_tool_list(ring=ring, agent=agent_hdr)},
                }
            )

        if method == "tools/call":
            params = body.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})
            accept = request.headers.get("Accept", "")
            use_sse = "text/event-stream" in accept and name in {
                "web_search",
                "web_search_rag",
                "ask_gemini",
                "ask_claude",
                "ask_agent",
                "agent_debate",
                "trigger_autonomous_evolution",
                # Tâches locales longues : heartbeat SSE -> survit au timeout bridge.
                "ask",
                "run",
                "orchestrate",
                "loop_orchestrate",
                "research_agent",
            }
            if not use_sse and "text/event-stream" in accept:
                try:
                    from nokido_agent.app.forge_mcp_elicitation import sse_requis as _sse_requis

                    use_sse = _sse_requis(name, args)
                except Exception:  # noqa: BLE001 - sans le module : liste historique
                    pass
            if use_sse:

                async def sse_gen():
                    # Ouverture = COMMENTAIRE SSE, jamais un `data:` hors JSON-RPC : le client
                    # MCP valide chaque `data:` comme un message JSON-RPC et rejetait l'ancien
                    # evenement de progression a chaque appel (2026-09-26,
                    # tools/forge_patch_hub_sse_conforme.py). Premier octet immediat conserve.
                    yield ": progress running\n\n"
                    # Heartbeat : exécute le tool en tâche de fond, émet un ping SSE
                    # (commentaire ': ping', ignoré du client) toutes les 15s tant
                    # qu'il tourne -> garde la connexion vivante pour une inférence
                    # locale longue (sinon le bridge coupe à ~30s d'inactivité).
                    # asyncio.shield = le timeout du ping ne cancel pas le tool.
                    # Elicitation (2026-09-26) : le tool tourne avec un CANAL ; ses requetes
                    # vers le client (`elicitation/create`) partent dans ce flux, entre les
                    # pings du heartbeat (15 s). Module illisible : boucle historique.
                    try:
                        from nokido_agent.app.forge_mcp_elicitation import (
                            Canal as _Canal, flux as _flux, lancer_avec_canal as _lancer)
                    except Exception:  # noqa: BLE001
                        _Canal = None
                    if _Canal is not None:
                        _canal = _Canal(request.headers.get("Mcp-Session-Id", ""), agent_hdr)
                        _tk = _lancer(_tool_call(name, args, ring, agent=agent_hdr), _canal)
                        async for _evt in _flux(_tk, _canal):
                            yield _evt
                        r2 = _tk.result()
                    else:
                        _tk = asyncio.ensure_future(_tool_call(name, args, ring, agent=agent_hdr))
                        while True:
                            try:
                                r2 = await asyncio.wait_for(asyncio.shield(_tk), timeout=15.0)
                                break
                            except asyncio.TimeoutError:
                                yield ": ping\n\n"
                    # Lifecycle hook : inject [HOOK:INBOX] si unread pour cet agent
                    r2 = lifecycle_wrap(agent_hdr, ring, name, session_id, r2)
                    lat2 = round((time.monotonic() - t0) * 1000, 1)
                    ie2 = str(r2).startswith(("ERR", "SECURITY", "SECRET GUARD"))
                    _log_network(
                        "OUT",
                        method=method,
                        tool=name,
                        agent=agent_hdr,
                        ring=ring,
                        latency_ms=lat2,
                        status="ERR" if ie2 else "OK",
                        payload_in=json.dumps(args, ensure_ascii=False)[:800],
                        payload_out=str(r2)[:800],
                        client_ip=client_ip,
                    )
                    pl = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": bid,
                            "result": {"content": [{"type": "text", "text": r2}]},
                        }
                    )
                    yield "data: " + pl + "\n\n"

                return StreamingResponse(
                    sse_gen(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            res = await _tool_call(name, args, ring, agent=agent_hdr)
            # Lifecycle hook : inject [HOOK:INBOX] si unread pour cet agent
            res = lifecycle_wrap(agent_hdr, ring, name, session_id, res)
            latency = round((time.monotonic() - t0) * 1000, 1)
            is_err = str(res).startswith(("ERR", "SECURITY", "SECRET GUARD"))
            _log_network(
                "OUT",
                method=method,
                tool=name,
                agent=agent_hdr,
                ring=ring,
                latency_ms=latency,
                status="ERR" if is_err else "OK",
                payload_in=json.dumps(args, ensure_ascii=False)[:800],
                payload_out=str(res)[:800],
                client_ip=client_ip,
            )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": bid,
                    "result": {"content": [{"type": "text", "text": res}]},
                }
            )

        # JSON-RPC notifications have no id — must NOT return a response (MCP spec)
        if bid is None:
            return Response(status_code=200)

        return JSONResponse(
            {"jsonrpc": "2.0", "id": bid, "error": {"code": -32601, "message": "Method not found"}}
        )

    async def mcp_get(request: Request):
        # Streamable HTTP MCP : canal serveur->client (SSE GET). Hub STATELESS (pas de push
        # serveur-initié) -> stream keep-alive (ping 20s) pour les clients rmcp STRICTS (codex)
        # qui ouvrent ce GET avant d'envoyer `initialized`. Avant = POST-only -> GET 405 ->
        # transport channel closed. Claude/Gemini n'ouvrent pas ce GET = zéro impact.
        ring, _agent = _resolve_ring(request)
        if ring < 0:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        async def _server_stream():
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(20)
                yield ": ping\n\n"

        return StreamingResponse(
            _server_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                     "Mcp-Session-Id": request.headers.get("Mcp-Session-Id", "")},
        )

    def _claude_cfg_path() -> Path:
        "claude_desktop_config.json au home OWNER (user), pas systemprofile (fix 500 sandbox)."
        import os as _os
        _sub = r"AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json"
        for _h in (_os.environ.get("LAFORGE_CLAUDE_HOME", ""), r"%USERPROFILE%", _os.path.expanduser("~")):
            if _h and _os.path.isfile(_os.path.join(_h, _sub)):
                return Path(_os.path.join(_h, _sub))
        return Path(_os.path.join(r"%USERPROFILE%", _sub))

    async def mcp_config_get(request: Request):
        """Retourne l etat des MCP servers depuis claude_desktop_config.json.
        Inclut les serveurs actifs ET desactives (_mcpServersDisabled)."""
        import json as _json

        cfg_path = _claude_cfg_path()
        try:
            data = _json.loads(cfg_path.read_text(encoding="utf-8"))
            result = []
            # Serveurs actifs
            for name, conf in data.get("mcpServers", {}).items():
                args = conf.get("args", [])
                cmd = conf.get("command", "?").split("/")[-1].split("\\")[-1]
                # Detecter si c'est le bridge ou le server direct
                is_bridge = any("mcp_stdio_bridge" in str(a) for a in args)
                result.append(
                    {
                        "name": name,
                        "enabled": True,
                        "bridge": is_bridge,
                        "command": cmd,
                        "args": [str(a).split("/")[-1].split("\\")[-1] for a in args[:2]],
                        "note": "via hub bridge" if is_bridge else "STDIO direct",
                    }
                )
            # Serveurs desactives
            for name, conf in data.get("_mcpServersDisabled", {}).items():
                args = conf.get("args", [])
                cmd = conf.get("command", "?").split("/")[-1].split("\\")[-1]
                result.append(
                    {
                        "name": name,
                        "enabled": False,
                        "bridge": False,
                        "command": cmd,
                        "args": [str(a).split("/")[-1].split("\\")[-1] for a in args[:2]],
                        "note": "desactive",
                    }
                )
            # `preferences` N'EST PLUS RELAYE -- 2026-09-22.
            #
            # Ce handler anonymise soigneusement ce qu'il CONSTRUIT (command et
            # args reduits au nom de fichier), puis recopiait un bloc entier
            # SANS filtre. 19 cles de `claude_desktop_config.json` partaient
            # ainsi sur une route NUE : `localAgentModeTrustedFolders` (chemins
            # absolus de l'owner), `bypassPermissionsGateByAccount`,
            # `remoteToolsDeviceName`, `coworkHipaaRestricted`...
            #
            #     ON NETTOIE CE QU'ON CONSTRUIT, ON OUBLIE CE QU'ON RELAIE
            #
            # Et personne ne les lisait. Mesure des DEUX appelants : le JS
            # inline du hub ne touche que `d.error` et `d.servers`
            # (`s.name`, `s.url`, `s.command`, `s.enabled`) ; le second est un
            # script one-shot qui ne mentionne jamais `preferences`.
            #
            #     PRODUCED != CONSUMED -- retirer ne casse aucun consommateur.
            return JSONResponse({"servers": result})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def mcp_config_toggle(request: Request):
        """Active/desactive un MCP server dans claude_desktop_config.json."""
        # PORTEUR EXIGE -- 2026-09-21, garde CONSERVEE. Meme fichier de
        # configuration que /api/mcp/flags, et un serveur MCP active sans
        # identite est un chemin d'execution ouvert.
        #
        # Correction de ma propre affirmation du matin (« aucun appelant HTTP
        # au depot ») : il en existe UN, `docs/skills/forge-android/SKILL.md`,
        # un `curl` d'EXEMPLE sans `Authorization`. Ce n'est pas un appelant
        # automatise -- c'est une DOCUMENTATION, et elle enseigne desormais un
        # geste qui rend 401. La doc est corrigee dans le meme commit ; la
        # garde, elle, reste.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        import json as _json

        cfg_path = _claude_cfg_path()
        try:
            body = await request.json()
            name = body.get("name", "")
            enabled = body.get("enabled", True)
            data = _json.loads(cfg_path.read_text(encoding="utf-8"))
            prefs = data.setdefault("preferences", {})
            disabled = set(prefs.get("_disabledMCPs", []))
            # Stocker le serveur desactive dans preferences._disabledMCPs
            # (on le deplace de mcpServers vers _mcpServersDisabled)
            servers = data.get("mcpServers", {})
            disabled_store = data.setdefault("_mcpServersDisabled", {})
            if enabled:
                # Reactiver : deplacer de _mcpServersDisabled vers mcpServers
                if name in disabled_store:
                    servers[name] = disabled_store.pop(name)
                disabled.discard(name)
            else:
                # Desactiver : deplacer de mcpServers vers _mcpServersDisabled
                if name in servers:
                    disabled_store[name] = servers.pop(name)
                disabled.add(name)
            prefs["_disabledMCPs"] = list(disabled)
            data["mcpServers"] = servers
            data["_mcpServersDisabled"] = disabled_store
            # Forcer les flags anti-injection
            prefs["launchPreviewPersistSession"] = False
            prefs["coworkScheduledTasksEnabled"] = False
            prefs["ccdScheduledTasksEnabled"] = False
            cfg_path.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            _log_network(
                "INTERNAL",
                method="mcp_toggle",
                tool=name,
                agent="NETWORK_UI",
                status="OK",
                payload_out=f"{'enabled' if enabled else 'disabled'}: {name}",
            )
            return JSONResponse(
                {
                    "ok": True,
                    "name": name,
                    "enabled": enabled,
                    "note": "Redemarrer Claude Desktop pour appliquer",
                }
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def mcp_config_flags(request: Request):
        """Force les flags anti-injection a False."""
        # GARDE RETIREE LE 2026-09-21, APRES MESURE RUNTIME — et c'est un
        # RECUL assume, pas un declassement silencieux.
        #
        # Je l'avais armee le matin meme en ecrivant « aucun appelant HTTP au
        # depot (verifie en Python, TypeScript, HTML et config) ». C'ETAIT
        # FAUX : l'appelant est a `nokido_hub.py:2072`, dans une chaine JS
        # INLINE de CE fichier --
        #     async function resetFlags(){ await fetch('/api/mcp/flags',
        #                                   {method:'POST'}); ... }
        # -- sans aucun en-tete, et sans condition. Ma recherche portait sur
        # des EXTENSIONS de fichier ; un `fetch` dans du HTML servi depuis un
        # `.py` n'y entrait pas. Le grep ne ment pas, la question etait mal
        # posee.
        #
        # Armer cette route casse donc le bouton « Flags reinitialises » de
        # l'interface du hub : « un 401 inattendu sur une route legitime est
        # une regression, pas une victoire securitaire ». C'est exactement la
        # raison pour laquelle `/api/watch/create` avait ete EXCLUE, et je
        # n'avais pas applique la meme regle ici.
        #
        # LE RISQUE RESTE REEL ET N'EST PAS EFFACE : cette route ECRIT dans la
        # configuration Claude Desktop de l'owner. Elle repasse donc dans
        # `SENSIBLES_CONNUES` avec sa raison, pour etre traitee avec son
        # appelant -- pas oubliee. La traiter demande de donner un porteur a
        # l'UI, ce qui ne se fait pas en glissant un jeton dans une page servie.
        import json as _json

        cfg_path = _claude_cfg_path()
        try:
            data = _json.loads(cfg_path.read_text(encoding="utf-8"))
            data["preferences"]["launchPreviewPersistSession"] = False
            data["preferences"]["coworkScheduledTasksEnabled"] = False
            data["preferences"]["ccdScheduledTasksEnabled"] = False
            cfg_path.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return JSONResponse({"ok": True, "flags": "reset to false"})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # `def` ET NON `async def` -- MESURE DU 2026-09-21, hub tue DEUX fois.
    #
    # Ce corps fait TROIS balayages complets de `RAG/embeddings.db` (25 Go) :
    # `SUM(LENGTH(text))` sur toute la table, un `COUNT(*)` global, et un
    # `COUNT(*) WHERE embedding IS NULL` qui n'a pas d'index. En `async def`,
    # tout cela s'executait DANS la boucle d'evenements : le serveur ENTIER
    # gelait le temps du scan, pas seulement cette requete.
    #
    # Mesure, sonde GET sans jeton, quatre routes sondees en SEQUENCE :
    #     /health/readiness   503                  (repond)
    #     /api/rag/stats      PAS_DE_STATUT_EN_12S <- LE bloqueur
    #     /api/rag/stream     PAS_DE_STATUT_EN_12S \  victimes de la file :
    #     /forge/network      PAS_DE_STATUT_EN_12S /  `network_ui` rend UNE ligne
    # puis plus aucun LISTEN sur :8766 -- `curl` en refus de connexion.
    #
    # C'est le symptome deja consigne le 2026-08-26 pour `app/web_hub/app.py`
    # (47 routes sur 62) : « on conclut quarante endpoints morts alors qu'UN
    # SEUL bloquait et que les autres attendaient leur tour ». Le remede y avait
    # ete applique ; ce fichier-ci ne l'a JAMAIS recu, et il porte 40 routes
    # `async def` sans `await`.
    #
    # En `def`, Starlette envoie l'appel dans un threadpool : la requete reste
    # aussi lente -- on ne rend pas la base plus petite -- mais elle n'empeche
    # plus le serveur de servir. Le cout n'est pas supprime, il cesse d'etre
    # PARTAGE par tous.
    #
    # CORRECTION DE MA PROPRE DESCRIPTION, 2026-09-21. Le commentaire ci-dessus
    # disait « trois scans complets ». C'ETAIT FAUX, et la mesure par requete
    # avec son PLAN le montre (base reelle, 27,3 Go, lecture seule stricte) :
    #
    #   GROUP BY domain + SUM(LENGTH(text))   SCAN USING INDEX          87,149 s
    #   GROUP BY domain seul                  SCAN USING COVERING INDEX  0,147 s
    #   COUNT(*)                              SCAN USING COVERING INDEX  0,015 s
    #   COUNT(*) WHERE embedding IS NULL      SCAN USING INDEX partiel   0,032 s
    #
    # UNE SEULE COLONNE portait 87,1 s des 87,3 s -- ratio 593x. `LENGTH(text)`
    # force SQLite a quitter l'index pour lire la LIGNE, donc le texte entier de
    # chaque enregistrement. Accuser « trois scans » etait la meme faute que
    # designer trois coupables pour un seul : on n'avait pas ISOLE.
    #
    # `chars` n'est pas supprime. On ne retire pas une mesure parce qu'elle est
    # chere : on cesse de l'imposer a qui ne la demande pas. `?chars=1` refait
    # le calcul complet. Et une valeur non mesuree vaut `None`, JAMAIS 0 --
    # « zero caractere » serait un chiffre faux et indetectable en aval.
    def rag_stats(request):
        import sqlite3 as _sq

        try:
            import tiktoken as _tk

            _tk.get_encoding("cl100k_base")
            tk_ok = True
        except:
            tk_ok = False
        conn = _sq.connect(str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"))
        try:
            _veut_chars = str(request.query_params.get("chars", "")).lower() in (
                "1", "true", "oui", "yes")
            if _veut_chars:
                doms = conn.execute(
                    "SELECT domain,COUNT(*),SUM(LENGTH(text)) FROM rag_chunks GROUP BY domain ORDER BY 2 DESC LIMIT 40"
                ).fetchall()
            else:
                doms = [
                    (d, n, None)
                    for d, n in conn.execute(
                        "SELECT domain,COUNT(*) FROM rag_chunks GROUP BY domain ORDER BY 2 DESC LIMIT 40"
                    ).fetchall()
                ]
            tot = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
            noe = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL").fetchone()[0]
        finally:
            # La connexion fuyait sur toute exception : trois scans longs sur une
            # base verrouillee sont precisement la ou une erreur survient.
            conn.close()
        return JSONResponse(
            {
                "total": tot,
                "no_embedding": noe,
                "tiktoken_ok": tk_ok,
                # `chars` vaut None quand il n'a pas ete mesure. Le rabattre sur
                # 0 ferait lire « ce domaine ne contient aucun caractere ».
                "domains": [{"name": d, "chunks": n, "chars": c} for d, n, c in doms],
                "chars_mesures": _veut_chars,
                "chars_note": None if _veut_chars else (
                    "non mesure (scan de 87 s sur 27 Go) -- ajouter ?chars=1 "
                    "pour l'obtenir ; None signifie INCONNU, pas zero"),
            }
        )

    async def rag_tokenize(request):
        try:
            import tiktoken as _tk

            body = await request.json()
            text = body.get("text", "")[:50000]
            model = body.get("model", "cl100k_base")
            enc = _tk.get_encoding(model)
            toks = enc.encode(text)
            return JSONResponse(
                {
                    "tokens": len(toks),
                    "chars": len(text),
                    "model": model,
                    "ratio": round(len(text) / max(len(toks), 1), 2),
                }
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def rag_ui(request):
        # Dedup Phase 6 (2026-07-03) : GUI humaine = web_hub :7400 (stylee, verte).
        # :8766 = API/MCP/agent -> page dupliquee redirigee ; API /api/* restent ici.
        return Response(status_code=302, headers={"Location": "http://127.0.0.1:7400/rag"})

    async def hub_index(request):
        """Landing page :8766/ — liste les UI dispos avec liens. Evite le 404."""
        html = """<!doctype html><html lang="fr" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nokido Hub :8766</title>
<link rel="icon" type="image/svg+xml" href="/static/nokido-favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<!-- Design system Nokido (claude design) - source unique de tokens. -->
<link rel="stylesheet" href="/static/laforge-tokens.css">
<link rel="stylesheet" href="/static/laforge-components.css">
<style>
  body{background:var(--bg-0);color:var(--text-primary);font-family:var(--font-sans);
       font-size:var(--text-base);line-height:var(--leading-normal);
       max-width:var(--content-max);margin:0 auto;padding:var(--space-14) var(--space-12)}
  .lf-top{display:flex;align-items:center;gap:var(--space-6);margin-bottom:var(--space-2)}
  .lf-dot{width:9px;height:9px;border-radius:50%;background:var(--prov-local);
          box-shadow:var(--prov-local-halo);animation:laforge-pulse var(--pulse-period) infinite}
  h1{margin:0;font-size:var(--text-xl);font-weight:var(--weight-bold);
     letter-spacing:var(--tracking-wide);color:var(--text-primary)}
  .lf-sub{color:var(--text-secondary);font-size:var(--text-sm);margin:var(--space-3) 0 var(--space-12)}
  h2{color:var(--text-dim);margin:var(--space-12) 0 var(--space-5);font-size:var(--text-xs);
     text-transform:uppercase;letter-spacing:var(--tracking-label);font-weight:var(--weight-semibold)}
  a{color:var(--text-secondary);text-decoration:none;display:inline-block;
    padding:var(--space-3) var(--space-6);margin:var(--space-2);background:var(--bg-2);
    border:1px solid var(--border);border-radius:var(--radius-sm);font-size:var(--text-sm);
    transition:all var(--motion-fast)}
  a:hover{background:var(--bg-3);border-color:var(--purple);color:var(--text-primary);
          box-shadow:var(--shadow-glow)}
  a.ext{border-style:dashed;border-color:var(--prov-distant-border);color:var(--prov-distant-strong)}
  a.ext:hover{border-color:var(--prov-distant);box-shadow:none}
  code{font-family:var(--font-mono);color:var(--orange);background:var(--bg-2);
       padding:2px 6px;border-radius:var(--radius-sm);font-size:var(--text-xs)}
</style></head>
<body>
<div class="lf-top"><img src="/static/nokido-mark.svg" alt="Nokido" width="32" height="32" style="vertical-align:middle"><h1>Nokido Hub MCP</h1><code>:8766</code></div>
<p class="lf-sub">Endpoint MCP : <code>POST /mcp</code> avec Bearer FORGE_TOKEN_&lt;AGENT&gt;.</p>
<h2>UI graphiques</h2>
<a href="/forge/rag">RAG Dashboard</a>
<a href="/forge/rag-stream">RAG Stream SSE</a>
<a href="/forge/network">Network log live</a>
<a href="/forge/debate">Inter-LLM Debate</a>
<a href="/forge/swarm">Swarm 5 specialists</a>
<a href="/forge/postal">Conversations & Agents live</a>
<a href="/forge/graph">Knowledge Graph</a>
<a href="/forge/watch">Watch jobs board</a>
<a href="http://127.0.0.1:7400/forge/feed">Event Feed (audit)</a>
<a href="/admin/providers">LLM Providers Admin</a>
<h2>API / endpoints utiles</h2>
<a href="/health">/health</a>
<a href="/api/rag/stats">/api/rag/stats</a>
<a href="/api/services/list">/api/services/list</a>
<a href="/api/resource/state">/api/resource/state</a>
<a href="/api/hormones/active">/api/hormones/active</a>
<a href="/api/swarm/health">/api/swarm/health</a>
<a href="/api/loops/status">/api/loops/status</a>
<a href="/api/graph/proprioception">/api/graph/proprioception</a>
<h2>Portail Web (auth-protected)</h2>
<a class="ext" href="http://127.0.0.1:7400/" target="_blank" rel="noopener">Hub Web :7400 (anatomy, feed, RBAC, launcher)</a>
<a class="ext" href="http://127.0.0.1:7500/" target="_blank" rel="noopener">netcfg-agent :7500</a>
<a class="ext" href="http://127.0.0.1:7401/health" target="_blank" rel="noopener">Deno WebHub :7401</a>
<script>
// Liens cross-port -> hote courant (marche via IP LAN / tunnel / proxy, pas que 127.0.0.1).
for(const a of document.querySelectorAll('a[href^="http://127.0.0.1:"]'))a.href=a.href.replace('127.0.0.1',location.hostname);
</script>
</body></html>"""
        return HTMLResponse(html)

    async def debate_ui(request):
        """Inter-LLM debate viz : 3 panels (ollama/groq/cerebras) en parallele.
        Injecte le token CLAUDE dans meta laforge-bearer pour appels /mcp."""
        try:
            html_path = (
                Path(__file__).resolve().parent.parent / "app" / "web_hub" / "llm_debate.html"
            )
            html = html_path.read_text(encoding="utf-8")
            tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""
            html = html.replace("__LAFORGE_BEARER__", tok)
            return HTMLResponse(html)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def graph_viz_ui(request):
        """Knowledge graph viz : vis-network rendu de /api/graph/proprioception.
        Injecte le token CLAUDE pour les appels API client-side."""
        try:
            html_path = (
                Path(__file__).resolve().parent.parent / "app" / "web_hub" / "graph_viz.html"
            )
            html = html_path.read_text(encoding="utf-8")
            tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""
            html = html.replace("__LAFORGE_BEARER__", tok)
            return HTMLResponse(html)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def recon_demo_ui(request):
        """Recon Silo workflow viz : pipeline 6-step animation (ARP/nmap/nuclei/LLM/RAG)."""
        try:
            html_path = (
                Path(__file__).resolve().parent.parent / "app" / "web_hub" / "recon_demo.html"
            )
            html = html_path.read_text(encoding="utf-8")
            tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""
            return HTMLResponse(html.replace("__LAFORGE_BEARER__", tok))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def static_serve(request):
        """Sert les fichiers JS/CSS depuis app/web_hub/static/ (vis-network, etc).
        Whitelist d extensions pour eviter path traversal."""
        from starlette.responses import FileResponse, Response

        fname = request.path_params.get("fname", "").strip()
        if not fname or ".." in fname or "/" in fname or "\\" in fname:
            return Response("forbidden", status_code=403)
        if not fname.endswith((".js", ".css", ".png", ".svg", ".woff2", ".woff", ".map")):
            return Response("forbidden ext", status_code=403)
        p = Path(__file__).resolve().parent.parent / "app" / "web_hub" / "static" / fname
        if not p.is_file():
            return Response("not found", status_code=404)
        mt = {
            "js": "application/javascript",
            "css": "text/css",
            "svg": "image/svg+xml",
            "png": "image/png",
            "woff": "font/woff",
            "woff2": "font/woff2",
            "map": "application/json",
        }[fname.rsplit(".", 1)[1]]
        return FileResponse(p, media_type=mt)

    async def favicon_serve(request):
        """/favicon.ico : l'adresse que TOUT navigateur demande par defaut. Campagne UI 25/09 :
        404 sur /forge/rings puis /forge/watch -- la route ferme la classe, pas une page."""
        from starlette.responses import FileResponse

        return FileResponse(Path(__file__).resolve().parent.parent / "app" / "web_hub" / "static"
                            / "nokido-favicon.svg", media_type="image/svg+xml")

    async def static_fonts_serve(request):
        """Polices vendorees (app/web_hub/static/fonts/). Les pages servies par le hub les
        citent en /static/fonts/<f> ; la route plate /static/{fname} ne capte pas de « / ».
        Mesure campagne UI 2026-09-24 : 7 pages de :8766 en 404 sur leurs polices.
        Memes gardes que static_serve, extensions reduites aux polices."""
        from starlette.responses import FileResponse, Response

        fname = request.path_params.get("fname", "").strip()
        if not fname or ".." in fname or "/" in fname or "\\" in fname:
            return Response("forbidden", status_code=403)
        if not fname.endswith((".woff2", ".woff")):
            return Response("forbidden ext", status_code=403)
        p = Path(__file__).resolve().parent.parent / "app" / "web_hub" / "static" / "fonts" / fname
        if not p.is_file():
            return Response("not found", status_code=404)
        return FileResponse(p, media_type="font/woff2" if fname.endswith(".woff2") else "font/woff")

    async def swarm_ui(request):
        """Swarm parallel specialists viz : 5 panels asynchrones (PLANNER /
        CODER / TESTER / REVIEWER / DOCS) avec progress bars + typewriter."""
        # Dedup Phase 6 (2026-07-03) : GUI humaine = web_hub :7400 (stylee, verte).
        # :8766 = API/MCP/agent -> page dupliquee redirigee ; API /api/* restent ici.
        return Response(status_code=302, headers={"Location": "http://127.0.0.1:7400/swarm"})

    async def postal_ui(request):
        """Vue LIVE : conversation postale (facteur/secrétaire) + agents/pools en activité.
        Réutilise la SSE /api/swarm/stream (forge_swarm_bus, topics postal+swarm)."""
        # Dedup Phase 6 (2026-07-03) : GUI humaine = web_hub :7400 (stylee, verte).
        # :8766 = API/MCP/agent -> page dupliquee redirigee ; API /api/* restent ici.
        return Response(status_code=302, headers={"Location": "http://127.0.0.1:7400/postal"})

    async def organs_ep(request):
        """Census RÉEL des organes (remplace le Doc Organes hardcodé) : lit organ_map_full.json
        (714 modules -> organe, régénéré par forge_module_census). Doc Organes devient vrai + auto-MAJ."""
        try:
            import json as _oj

            p = Path(__file__).resolve().parent.parent / "sandbox" / "workspace" / "organ_map_full.json"
            d = _oj.loads(p.read_text(encoding="utf-8"))
            mo = d.get("module_organ", {})
            tally = dict(d.get("tally") or {})
            if not tally:
                for _o in mo.values():
                    tally[_o] = tally.get(_o, 0) + 1
            return JSONResponse({"ok": True, "total": len(mo), "n_organs": len(tally),
                                 "tally": tally, "provenance": d.get("provenance")})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    async def agents_ep(request):
        """Registre identité×canal LIVE (config/agent_identities.json) -> métadonnées agents RÉELLES
        pour la vue postale (remplace le AGENTS hardcodé de postal.html, reco audit Gemini 2026-06-11)."""
        try:
            import json as _aj

            p = Path(__file__).resolve().parent.parent / "config" / "agent_identities.json"
            d = _aj.loads(p.read_text(encoding="utf-8"))
            return JSONResponse({"ok": True, "agents": d.get("agents", {})})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    async def swarm_stream(request: Request):
        """SSE live de la collaboration swarm (side-channel forge_swarm_bus).
        Additif : ne touche pas le chemin du résultat des tools."""
        import sys as _s
        from pathlib import Path as _P

        _app = _P(__file__).resolve().parent.parent / "app"
        if str(_app) not in _s.path:
            _s.path.insert(0, str(_app))
        from nokido_agent.app.forge_swarm_bus import subscribe, unsubscribe

        q = subscribe()

        async def generator():
            yield 'data: {"kind":"connected"}\n\n'
            try:
                while True:
                    try:
                        line = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: q.get(timeout=25)
                        )
                        yield "data: " + line + "\n\n"
                    except Exception:
                        yield ": ping\n\n"
            finally:
                unsubscribe(q)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    async def swarm_run(request: Request):
        """Fan-out multi-LLM RÉEL côté serveur (aucune démo simulée) : chaque
        rôle = un appel `ask` réel à un provider, événements poussés live sur
        /api/swarm/stream. Résultats ET erreurs réels — jamais scriptés."""
        auth = request.headers.get("authorization", "")
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        valid = bool(tok) and tok in set(filter(None, list(_AGENT_TOKENS.values()) + [HUB_TOKEN]))
        client = (request.client.host if request.client else "") or ""
        if not valid and client not in ("127.0.0.1", "::1", "localhost", ""):
            # TRACE DU REFUS — 2026-09-21, mesure P1-P. `_admin_tok_ok` trace
            # les siens depuis ce jour ; ces trois routes `run` refusaient sans
            # laisser la moindre ligne, alors qu'elles declenchent un fan-out
            # LLM reel sur quatre providers. Une asymetrie de tracabilite DANS
            # LE MEME FICHIER est une asymetrie de gouvernance.
            #
            # L'exemption loopback n'est PAS fermee ici : mesure faite, l'UI du
            # swarm pose son porteur SOUS CONDITION
            # (`...(TOK ? {Authorization} : {})`, swarm.html:172), donc elle
            # depend de cette exemption quand `TOK` manque. Fermer sans donner
            # un chemin a l'UI casserait le bouton -- « un 401 inattendu sur
            # une route legitime est une regression ».
            _journaliser_refus_admin(request, tok, "swarm_run_hors_loopback")
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        import sys as _s
        from pathlib import Path as _P

        _app = _P(__file__).resolve().parent.parent / "app"
        if str(_app) not in _s.path:
            _s.path.insert(0, str(_app))
        from nokido_agent.app.forge_swarm_bus import publish as _emit

        try:
            body = await request.json()
        except Exception:
            body = {}
        task = str(body.get("task") or "").strip() or (
            "Conçois un endpoint FastAPI GET /fib/{n} (fibonacci mémoïsé) : plan, code, tests, revue sécurité."
        )
        default_roles = [
            {"role": "PLANNER", "provider": "ollama", "ask": "Plan en 4 étapes, liste numérotée."},
            {"role": "CODER", "provider": "groq", "ask": "Écris le endpoint FastAPI (~15 lignes)."},
            {"role": "TESTER", "provider": "gemini", "ask": "Écris 3 tests pytest (n=0, n=10, n négatif)."},
            # 2026-09-25 (owner) : `mistral` = mistral-large-latest, HORS palier de l'abonnement (403
            # tier_not_allowed a chaque appel). Revue = jugement -> modele FORT : AGY en OAuth.
            {"role": "REVIEWER", "provider": "gemini_cli", "ask": "Checklist sécurité courte (5 points)."},
        ]
        roles = body.get("roles") or default_roles
        _emit("swarm_start", {"task": task[:200], "agents": [r["role"] for r in roles], "mode": "fanout"})

        async def _one(r):
            role, prov = r.get("role", "?"), r.get("provider", "auto")
            _emit("agent_start", {"agent": role, "provider": prov, "round": 0})
            try:
                out = str(
                    await _tool_call(
                        "ask",
                        {"prompt": f"[{role}] {task}\n{r.get('ask', '')}", "provider": prov},
                        0,
                        agent="SWARM",
                    )
                )
                err = out.startswith(("ERR", "SECURITY", "SECRET"))
                # `ask` renvoie une enveloppe JSON {ok,text,model,...} -> n'afficher
                # que la réponse réelle du modèle dans le panneau (pas l'enveloppe).
                try:
                    _d = json.loads(out)
                    if isinstance(_d, dict) and "text" in _d:
                        out = str(_d.get("text") or "")
                except Exception:
                    pass
            except Exception as e:
                out, err = f"ERR: {type(e).__name__}: {e}", True
            _emit("agent_reply", {"agent": role, "provider": prov, "chars": len(out), "text": out[:800], "error": err})
            return not err

        oks = await asyncio.gather(*[_one(r) for r in roles])
        _emit("final", {"mode": "fanout", "agents": len(roles), "ok": sum(1 for x in oks if x)})
        return JSONResponse({"ok": True, "ran": len(roles)})

    async def recon_run(request: Request):
        """Recon RÉEL : lance `research_agent` (SearXNG → LLM → RAG ingest) et
        pousse les résultats RÉELS sur le bus (topic=recon). Aucune simulation."""
        auth = request.headers.get("authorization", "")
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        valid = bool(tok) and tok in set(filter(None, list(_AGENT_TOKENS.values()) + [HUB_TOKEN]))
        client = (request.client.host if request.client else "") or ""
        if not valid and client not in ("127.0.0.1", "::1", "localhost", ""):
            # Meme trace que `swarm_run` : appelant mesure
            # `recon_demo.html:131`, porteur SOUS CONDITION lui aussi.
            _journaliser_refus_admin(request, tok, "recon_run_hors_loopback")
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        # ── A2 : PORTEE AVANT EFFET (contrat owner 2026-09-22) ───────────
        # Premier consommateur reel de la chaine construite en A1. Le scope
        # exige est `rag:ingest` et non un `recon:*` invente : l'effet de cette
        # route est `research_agent`, dont le travail est d'INGERER dans le RAG.
        # On nomme la capacite par son EFFET, pas par le nom de la route.
        #
        # PLACEE ICI, avant le premier `_emit` : dans le corps, un refus ne
        # serait qu'un message apres coup.
        #
        #     DENY -> aucune publication sur le bus, aucun `research_agent`
        #     et non pas seulement : DENY -> 403.
        #
        # Un jeton SANS portee (statique) rend `None` et suit l'ancien contrat :
        # le durcissement ne contraint que les porteurs qui ont une portee.
        if _portee_suffisante(tok, "rag", "ingest") is False:
            logger.info("[recon] DENY portee insuffisante — `rag:ingest` requis")
            return JSONResponse(
                {"ok": False, "error": "forbidden",
                 "reason": "portee insuffisante : rag:ingest requis"},
                status_code=403)

        import sys as _s
        from pathlib import Path as _P

        _app = _P(__file__).resolve().parent.parent / "app"
        if str(_app) not in _s.path:
            _s.path.insert(0, str(_app))
        from nokido_agent.app.forge_swarm_bus import publish as _emit

        try:
            body = await request.json()
        except Exception:
            body = {}
        objective = str(body.get("objective") or "").strip() or (
            "Panorama des techniques de prompt injection indirecte 2026 et défenses."
        )
        _emit("recon_start", {"objective": objective[:200]}, topic="recon")
        try:
            out = str(
                await _tool_call(
                    "research_agent",
                    {"objective": objective, "max_rounds": 2, "max_urls": 5},
                    0,
                    agent="SWARM",
                )
            )
            d = {}
            try:
                import ast as _ast

                d = _ast.literal_eval(out) if out.strip().startswith("{") else {}
            except Exception:
                d = {}
            if not isinstance(d, dict):
                d = {}
            _emit(
                "recon_result",
                {
                    "queries": d.get("queries", []),
                    "found": d.get("found"),
                    "ingested": d.get("ingested"),
                    "domain": d.get("domain"),
                    "synthesis": str(d.get("synthesis", out))[:2000],
                    "error": out.startswith(("ERR", "SECURITY", "SECRET")),
                },
                topic="recon",
            )
        except Exception as e:
            _emit("recon_result", {"error": True, "synthesis": f"ERR: {type(e).__name__}: {e}"}, topic="recon")
        _emit("recon_done", {}, topic="recon")
        return JSONResponse({"ok": True})

    async def ctf_run(request: Request):
        """CTF RÉEL, events live (topic=ctf). 2 modes :
          - web  (défaut) : ctf_solver (ReAct + Playwright Root-Me, PROUVÉ).
                             solve_ctf émet ses propres events ctf_step/ctf_flag.
          - pwn           : recon binaire RÉELLE dans Exegol (file/checksec/ltrace
                             via le bridge exegol). Aucune simulation."""
        auth = request.headers.get("authorization", "")
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        valid = bool(tok) and tok in set(filter(None, list(_AGENT_TOKENS.values()) + [HUB_TOKEN]))
        client = (request.client.host if request.client else "") or ""
        if not valid and client not in ("127.0.0.1", "::1", "localhost", ""):
            # Meme trace. PARTICULARITE MESUREE : `/api/ctf/run` n'a AUCUN
            # appelant au depot -- ni UI, ni CLI, ni script. C'est le seul
            # candidat au retrait de l'exemption, mais un client HORS depot
            # reste invisible a cette recherche : UNKNOWN, jamais « personne ».
            # La trace posee ici est precisement ce qui permettra de le savoir.
            _journaliser_refus_admin(request, tok, "ctf_run_hors_loopback")
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        import sys as _s
        from pathlib import Path as _P

        _app = _P(__file__).resolve().parent.parent / "app"
        if str(_app) not in _s.path:
            _s.path.insert(0, str(_app))
        from nokido_agent.app.forge_swarm_bus import publish as _emit

        try:
            body = await request.json()
        except Exception:
            body = {}
        mode = str(body.get("mode") or "web")

        if mode == "pwn":
            binary = str(body.get("target") or "").strip()
            container = str(body.get("container") or "").strip()
            if not binary:
                return JSONResponse({"ok": False, "error": "target binary requis (mode pwn)"}, status_code=400)
            _emit("ctf_run_start", {"mode": "pwn", "target": binary, "container": container or "auto"}, topic="ctf")
            try:
                if not container:
                    lc = str(await _tool_call("exegol", {"action": "list_containers"}, 2, agent="CTF"))
                    import re as _re

                    m = _re.search(r'"(?:name|Names?)"\s*:\s*"([^"]*exegol[^"]*)"', lc) or _re.search(
                        r'"name"\s*:\s*"([^"]+)"', lc
                    )
                    container = m.group(1) if m else ""
                for cmd in [f"file {binary}", f"checksec --file={binary}", f"ltrace -e 'puts+printf' {binary} </dev/null"]:
                    _emit("ctf_step", {"step": cmd.split()[0], "action": cmd}, topic="ctf")
                    out = str(
                        await _tool_call(
                            "exegol",
                            {"action": "exec", "container": container, "command": cmd, "timeout": 40},
                            2,
                            agent="CTF",
                        )
                    )
                    _emit("ctf_result", {"cmd": cmd, "text": out[:1500]}, topic="ctf")
            except Exception as e:
                _emit("ctf_result", {"error": True, "text": f"ERR: {type(e).__name__}: {e}"}, topic="ctf")
            _emit("ctf_done", {"mode": "pwn"}, topic="ctf")
            return JSONResponse({"ok": True, "mode": "pwn"})

        # mode web (défaut) — ctf_solver émet lui-même ctf_start/ctf_step/ctf_flag
        intent = str(body.get("intent") or body.get("target") or "résous un challenge facile Web-Client")
        category = str(body.get("category") or "Web-Client")
        provider = str(body.get("provider") or "ollama")
        _emit("ctf_run_start", {"mode": "web", "intent": intent[:160], "category": category}, topic="ctf")
        try:
            r = str(
                await _tool_call(
                    "ctf_solver",
                    {
                        "intent": intent,
                        "category": category,
                        "max_steps": int(body.get("max_steps", 12)),
                        "provider": provider,
                    },
                    2,
                    agent="CTF",
                )
            )
        except Exception as e:
            r = f"ERR: {type(e).__name__}: {e}"
        _emit("ctf_done", {"mode": "web", "result": r[:400]}, topic="ctf")
        return JSONResponse({"ok": True, "mode": "web"})

    async def rag_stream_ui(request):
        """RAG stream viz : SSE BM25 chunks streames un par un, animation slideIn."""
        try:
            html_path = (
                Path(__file__).resolve().parent.parent / "app" / "web_hub" / "rag_stream.html"
            )
            return HTMLResponse(html_path.read_text(encoding="utf-8"))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def rag_stream(request):
        """
        GET /api/rag/stream?q=<query>&limit=10&domain=<domain>
        SSE : diffuse les chunks RAG un par un via BM25 FTS5.
        Chaque event: data: <JSON chunk>\n\n
        Dernier event: data: {"done":true,"total":N}\n\n
        """
        import json as _js
        import sqlite3 as _sq

        q = request.query_params.get("q", "").strip()
        limit = min(int(request.query_params.get("limit", "10")), 50)
        domain = request.query_params.get("domain", "")
        if not q:
            return JSONResponse({"error": "q requis"}, status_code=400)

        # La question de l'utilisateur n'est JAMAIS passee brute a FTS5 : `?`, `"`, `-`, AND/OR/NEAR y sont de la
        # syntaxe. Mesure du 2026-10-07 (test d'installation sur runners) : « How do I install Nokido with pip? »
        # rendait « fts5: syntax error near "?" ». Echappement existant reutilise (mots cites, relies par OR).
        # Modification d'un CRITICAL_FILE sur GO owner du 2026-10-07.
        try:
            from nokido_agent.tools.forge_knowledge_overlap import requete_fts as _requete_fts
        except ImportError:
            from forge_knowledge_overlap import requete_fts as _requete_fts
        fts = _requete_fts(q)

        async def gen():
            if not fts:
                yield f"data: {_js.dumps({'done': True, 'total': 0, 'note': 'aucun mot exploitable dans la question'})}\n\n"
                return
            try:
                _db = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
                conn = _sq.connect(str(_db), timeout=5)
                clause = "AND domain=?" if domain else ""
                params = (fts, domain, limit) if domain else (fts, limit)
                rows = conn.execute(
                    f"SELECT bm25(rag_fts) as rank, source, substr(text,1,400), domain "
                    f"FROM rag_fts WHERE rag_fts MATCH ? {clause} ORDER BY rank LIMIT ?",
                    params,
                ).fetchall()
                conn.close()
                for i, (rank, src, txt, dom) in enumerate(rows):
                    chunk = _js.dumps(
                        {
                            "i": i,
                            "source": src,
                            "text": txt,
                            "domain": dom,
                            "score": round(float(rank), 4),
                        },
                        ensure_ascii=False,
                    )
                    yield f"data: {chunk}\n\n"
                    await asyncio.sleep(0)  # yield event loop entre chaque chunk
                yield f"data: {_js.dumps({'done': True, 'total': len(rows)})}\n\n"
            except Exception as e:
                yield f"data: {_js.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def ingest_url(request):
        """
        POST /ingest/url — Streaming atomique depuis Link Gopher (1 URL à la fois).
        Body: {url, title, source, priority}
        Insère dans biblio_raw sans notification (batch finale via /ingest/bulk).
        """
        import datetime as _dt
        import hashlib
        import sqlite3

        from starlette.responses import JSONResponse

        # PORTEUR EXIGE -- 2026-09-21. Cette route fait INSERT + commit() dans
        # RAG/embeddings.db. Mesure runtime du jour, sonde NON mutante :
        # `POST /ingest/url {}` sans jeton rendait 400 « invalid url » -- le
        # handler etait ATTEINT et EXECUTE. C'etait un ecrivain ANONYME sur la
        # base que l'owner a demande de faire CESSER DE RECEVOIR (19/09).
        # Garde REUTILISE, pas invente : `_admin_tok_ok` tient deja /admin/* et
        # son refus est mesure (401 sur /api/audit/recent le meme jour).
        # Seul appelant reel -- web_hub/wired_routes.py:536 -- porte deja un
        # `Authorization: Bearer`, donc zero regression attendue. Il ne le pose
        # toutefois que `if tok:` : coffre illisible => 401, et c'est voulu.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        try:
            body = await request.json()
            url = body.get("url", "").strip()
            title = body.get("title", url)[:200]
            src = body.get("source", "linkgopher")
            if not url or not url.startswith("http"):
                return JSONResponse({"ok": False, "error": "invalid url"}, status_code=400)
            db = str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
            uid = "blr_" + hashlib.md5(url.encode()).hexdigest()[:12]
            now = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
            conn = sqlite3.connect(db, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            cur = conn.execute(
                "INSERT OR IGNORE INTO biblio_raw"
                "(id,type,title,url,status,source_kind,payload_hash,triggered_by_idea_id,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    "url",
                    title,
                    url,
                    "unverified",
                    src,
                    hashlib.md5(f"{url}{title}".encode()).hexdigest()[:16],
                    f"bulk_{src}",
                    now,
                    now,
                ),
            )
            inserted = cur.rowcount
            conn.commit()
            conn.close()
            return JSONResponse({"ok": True, "inserted": inserted, "id": uid})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    async def ingest_bulk(request):
        """
        POST /ingest/bulk — Import massif depuis Link Gopher ou TabCopy.
        Body: [{url, title, source, priority}, ...]
        Notifie Gemini avec 1 seule MessageFrame bulk.
        """
        import datetime as _dt
        import hashlib
        import json as _j
        import sqlite3

        from starlette.responses import JSONResponse

        # PORTEUR EXIGE -- voir /ingest/url. Mesure du jour : `POST /ingest/bulk
        # {}` sans jeton rendait 400 « expected array ». Aucun appelant reel au
        # depot pour cette route : la garde ne casse personne.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        try:
            items = await request.json()
            if not isinstance(items, list):
                return JSONResponse({"ok": False, "error": "expected array"}, status_code=400)
            db = str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
            now = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
            conn = sqlite3.connect(db, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            inserted = 0
            for item in items:
                url = (item.get("url", "") or "").strip()
                title = (item.get("title", url) or url)[:200]
                src = item.get("source", "bulk")
                if not url or not url.startswith("http"):
                    continue
                uid = "blr_" + hashlib.md5(url.encode()).hexdigest()[:12]
                cur = conn.execute(
                    "INSERT OR IGNORE INTO biblio_raw"
                    "(id,type,title,url,status,source_kind,payload_hash,triggered_by_idea_id,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        uid,
                        "url",
                        title,
                        url,
                        "unverified",
                        src,
                        hashlib.md5(f"{url}{title}".encode()).hexdigest()[:16],
                        f"bulk_{src}",
                        now,
                        now,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
            conn.commit()
            total_unverified = conn.execute(
                "SELECT COUNT(*) FROM biblio_raw WHERE status='unverified'"
            ).fetchone()[0]
            # Notif unique Gemini
            mid = "blk_" + hashlib.md5(f"bulk{now}".encode()).hexdigest()[:12]
            # Scission M2M : la notification part dans la base des agent_messages
            # (interrupteur sandbox/m2m.switch) ; `conn` reste la base du RAG.
            from nokido_agent.app.forge_db_path import open_m2m as _open_m2m
            _m2m = _open_m2m(timeout=5)
            _m2m.execute(
                "INSERT OR IGNORE INTO agent_messages"
                "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (
                    mid,
                    "agt_hub",
                    "agt_gemini",
                    mid,
                    "tool.hub.arg.message",
                    _j.dumps(
                        {
                            "text": f"[GEMINI][BULK-IMPORT] {inserted} liens importés (linkgopher). "
                            f"Total unverified={total_unverified}. "
                            f"Lance: biblio action=list status_filter=unverified quand disponible."
                        }
                    ),
                    "unread",
                    now,
                ),
            )
            conn.commit()
            conn.close()
            return JSONResponse(
                {"ok": True, "inserted": inserted, "total_unverified": total_unverified}
            )
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    async def ingest_qualify(request):
        """
        POST /ingest/qualify — Qualification LLM d'un document extrait par l'extension.
        Body: {header, body: {url, title, text, meta_desc, headings, lang, source}}
        Utilise Groq (rapide) pour assigner tags + domaine + résumé → biblio_raw enrichi.
        """
        import hashlib
        import json as _j
        import sqlite3
        from datetime import datetime as _dt2

        # PORTEUR EXIGE -- voir /ingest/url. Ecrit aussi dans embeddings.db, et
        # n'a aucun appelant reel au depot. NON sondee en runtime : son chemin
        # de rejet est moins clair et une sonde pouvait declencher une ecriture
        # -- l'ignorance coutait moins cher que la mesure.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        try:
            raw = await request.json()
            body = raw.get("body", raw)
            url = body.get("url", "").strip()
            title = body.get("title", url)[:200]
            text = body.get("text", "")[:6000]
            meta = body.get("meta_desc", "")[:300]
            heads = body.get("headings", "")[:200]
            lang = body.get("lang", "")
            src = body.get("source", "linkgopher_qualify")

            if not url or not url.startswith("http"):
                return JSONResponse({"ok": False, "error": "invalid url"}, status_code=400)

            # Prompt LLM pour qualification
            qualify_prompt = f"""Analyse ce document web et réponds UNIQUEMENT en JSON valide, sans markdown.

URL: {url}
Titre: {title}
Meta: {meta}
Headings: {heads}
Texte (début): {text[:2000]}

Retourne exactement ce JSON:
{{
  "domain": "<domaine parmi: ia, code, security, network, devops, system, bibliography, neuromorphic, research, web, general, exploit, collab>",
  "tags": ["<tag1>", "<tag2>", "<tag3>"],
  "summary": "<résumé en 1-2 phrases>",
  "relevance": <score 0.0 à 1.0>,
  "lang": "<langue détectée: fr/en/de/...>"
}}"""

            # Appel LLM via hub (Groq - rapide et gratuit)
            qual = {
                "domain": "general",
                "tags": [],
                "summary": title,
                "relevance": 0.5,
                "lang": lang,
            }
            try:
                from nokido_agent.app.forge_llm_router import router_call as _llm

                # FIX wedge-class (2026-06-18, cf route_task) : _llm (router_call) est
                # une coroutine -> await DIRECT borné, jamais run_in_executor+asyncio.run
                # (nouvelle loop/appel + ThreadPool défaut + get_event_loop déprécié = wedge).
                result = await asyncio.wait_for(
                    _llm(prompt=qualify_prompt, provider="groq", max_tokens=300, temperature=0.1),
                    timeout=60,
                )
                txt = (result.get("text", "") or "").strip()
                # Parser le JSON retourné
                import re as _re

                m = _re.search(r"\{[^{}]+\}", txt, _re.DOTALL)
                if m:
                    qual = _j.loads(m.group(0))
            except Exception as _qe:
                logger.debug(f"qualify LLM error: {_qe}")

            # Insérer dans biblio_raw avec métadonnées enrichies
            db = str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
            uid = "blr_" + hashlib.md5(url.encode()).hexdigest()[:12]
            now = _dt2.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            tags_str = ", ".join(qual.get("tags", []))
            domain = qual.get("domain", "general")
            summary = qual.get("summary", title)[:500]
            relevance = float(qual.get("relevance", 0.5))

            conn = sqlite3.connect(db, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            # Upsert — si déjà présent, enrichir avec les métadonnées LLM
            cur = conn.execute(
                "INSERT INTO biblio_raw"
                "(id,type,title,url,status,source_kind,payload_hash,"
                " triggered_by_idea_id,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " status='queued', updated_at=excluded.updated_at",
                (
                    uid,
                    "url",
                    title,
                    url,
                    "queued",
                    src,
                    hashlib.md5(f"{url}{title}".encode()).hexdigest()[:16],
                    f"qualify_{src}",
                    now,
                    now,
                ),
            )

            # Stocker les métadonnées LLM dans rag_chunks directement
            if text:
                chunk_id = "qch_" + hashlib.md5(f"{url}{now}".encode()).hexdigest()[:12]
                enriched_text = f"[QUALIFY] {title}\n{summary}\nTags: {tags_str}\nDomain: {domain}\n\n{text[:4000]}"
                conn.execute(
                    "INSERT OR REPLACE INTO rag_chunks"
                    "(id,text,source,domain,role_hint,author,ingested_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (chunk_id, enriched_text, url, domain, tags_str or "web", src, now),
                )

            inserted = cur.rowcount
            conn.commit()
            if text:
                _zmq_nudge_embed(1)

            # Notifier le hub (biblio worker pourra traiter)
            notif_id = "qnt_" + hashlib.md5(f"{uid}{now}".encode()).hexdigest()[:10]
            from nokido_agent.app.forge_db_path import open_m2m as _open_m2m   # scission M2M : base des messages, pas celle du RAG
            _m2m = _open_m2m(timeout=5)
            _m2m.execute(
                "INSERT OR IGNORE INTO agent_messages"
                "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (
                    notif_id,
                    "agt_hub",
                    "agt_gemini",
                    notif_id,
                    "tool.hub.arg.message",
                    _j.dumps(
                        {
                            "text": f"[BROWSER][QUALIFY-DONE] {title[:60]} → domain:{domain} tags:[{tags_str}] "
                            f"relevance:{relevance:.2f} url:{url[:60]}"
                        }
                    ),
                    "unread",
                    now,
                ),
            )
            conn.commit()
            conn.close()

            return JSONResponse(
                {
                    "ok": True,
                    "id": uid,
                    "domain": domain,
                    "tags": qual.get("tags", []),
                    "summary": summary,
                    "relevance": relevance,
                    "inserted": inserted,
                }
            )

        except Exception as e:
            logger.error(f"ingest_qualify: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    async def api_ingest(request):
        _refus = _exiger_identite(request)
        if _refus is not None:
            return _refus
        import hashlib
        import json as _j
        import re as _re
        import sqlite3
        from datetime import datetime as _dt2

        try:
            raw = await request.json()
            header = raw.get("header", "")
            source = raw.get("source", "unknown")
            data = raw.get("data", raw)
            lf_prio = 5
            if header.startswith("LF") and "." in header:
                parts = header.split(".")
                try:
                    lf_prio = int(parts[4]) if len(parts) > 4 else 5
                except (ValueError, IndexError):  # muet-ok : priorite malformee ->
                    # on garde le defaut 5, comportement voulu et sans perte. Le
                    # `except:` NU d'avant attrapait aussi KeyboardInterrupt et
                    # SystemExit, donc il pouvait avaler un arret demande.
                    pass
            url = (data.get("url", "") or "").strip()
            text = (data.get("text", "") or "")[:8000]
            title = (data.get("title", "") or url or "")[:200]
            tags = data.get("tags", [])
            domain = data.get("domain", "") or "general"
            summary = title
            if not url and not text:
                return JSONResponse({"ok": False, "error": "url ou text requis"}, status_code=400)
            if text and lf_prio >= 5:
                try:
                    qp = (
                        "Analyse ce contenu JSON uniquement:\nURL:"
                        + url
                        + "\nTitre:"
                        + title
                        + "\nTexte:"
                        + text[:1000]
                    )
                    qp += '\n{"domain":"ia|code|security|network|devops|system|bibliography|research|web|general","tags":["t1","t2"],"summary":"phrase"}'
                    import asyncio as _aio

                    from nokido_agent.app.forge_llm_router import router_call as _llm

                    res = await _aio.get_event_loop().run_in_executor(
                        None,
                        lambda: _aio.run(
                            _llm(prompt=qp, provider="groq", max_tokens=200, temperature=0.0)
                        ),
                    )
                    m = _re.search(r"[{][^{}]+[}]", res.get("text", ""), _re.DOTALL)
                    if m:
                        q = _j.loads(m.group(0))
                        domain = q.get("domain", domain)
                        tags = tags or q.get("tags", [])
                        summary = q.get("summary", summary)
                except Exception as _qe:
                    logger.debug("qualify skip: " + str(_qe))
            db = str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
            now = _dt2.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            uid = "blr_" + hashlib.md5((url or text[:100]).encode()).hexdigest()[:12]
            phash = hashlib.md5((url + title).encode()).hexdigest()[:16]
            conn = sqlite3.connect(db, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "INSERT INTO biblio_raw(id,type,title,url,status,source_kind,"
                "payload_hash,triggered_by_idea_id,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " status=CASE WHEN status='reviewed' THEN 'reviewed' ELSE 'queued' END,"
                " updated_at=excluded.updated_at",
                (
                    uid,
                    "url" if url else "text",
                    title,
                    url or "",
                    "queued",
                    source,
                    phash,
                    "ingest_" + source,
                    now,
                    now,
                ),
            )
            if text:
                cid = "ich_" + hashlib.md5((uid + now).encode()).hexdigest()[:12]
                ts2 = ",".join(tags)
                enriched = (
                    "["
                    + source.upper()
                    + "] "
                    + title
                    + " "
                    + summary
                    + " Tags:"
                    + ts2
                    + " "
                    + text[:4000]
                )
                conn.execute(
                    "INSERT OR REPLACE INTO rag_chunks(id,text,source,domain,role_hint,author,ingested_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (cid, enriched, url or "sidebar", domain, ts2 or "web", source, now),
                )
            conn.commit()
            if text:
                _zmq_nudge_embed(1)
            _log_network(
                "IN",
                method="POST /api/ingest",
                tool="ingest",
                agent=source,
                status="OK",
                payload_in=_j.dumps({"url": url[:80], "domain": domain, "tags": tags})[:400],
            )
            conn.close()
            return JSONResponse(
                {
                    "ok": True,
                    "id": uid,
                    "domain": domain,
                    "tags": tags,
                    "summary": summary,
                    "lf_header": header,
                    "source": source,
                }
            )
        except Exception as e:
            logger.error("api_ingest: " + str(e))
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    async def sidebar_ui(request):
        """GET /gui/sidebar — Interface de chat pour la sidebar Firefox."""
        from pathlib import Path as _P

        from starlette.responses import HTMLResponse as _HR

        _f = _P(__file__).resolve().parent.parent / "app" / "web_hub" / "sidebar.html"
        _html = _f.read_text(encoding="utf-8") if _f.exists() else "<h1>sidebar.html manquant</h1>"
        return _HR(_html, headers={"Content-Type": "text/html; charset=utf-8"})

    async def graph_stats_api(request):
        """GET /api/graph/stats — edge statistics from rag_graph_edges."""
        from starlette.responses import JSONResponse as _JR

        try:
            import sys as _s

            _s.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_graph_rag import GraphRAG

            stats = GraphRAG(str(DB)).get_edge_stats()
            return _JR(stats)
        except Exception as e:
            return _JR({"error": str(e)}, status_code=500)

    async def mcp_batch(request):
        """POST /mcp/batch — execute multiple tool calls in one round-trip."""
        # PORTEUR EXIGE -- 2026-09-21. EXECUTE plusieurs appels d'outils en un
        # round-trip. C'est la route la plus directe vers de l'execution, et
        # elle n'avait aucune garde. Aucun appelant HTTP au depot.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        from starlette.responses import JSONResponse as _JR

        try:
            items = await request.json()
            if not isinstance(items, list):
                return _JR({"error": "body must be JSON array"}, status_code=400)
            results = []
            for item in items:
                tname = item.get("tool", "")
                targs = item.get("args", {})
                if not tname:
                    results.append({"error": "missing tool"})
                    continue
                try:
                    res = await _tool_call(tname, targs, ring=0, agent="HUB_BATCH")
                    results.append({"tool": tname, "result": res})
                except Exception as ex:
                    results.append({"tool": tname, "error": str(ex)})
            return _JR(results)
        except Exception as e:
            return _JR({"error": str(e)}, status_code=400)

    async def nervous_emit(request):
        """POST /nervous_system/emit — forward event JSON to Deno :8000/event."""
        import httpx as _hx
        from starlette.responses import JSONResponse as _JR

        _refus = _exiger_identite(request)
        if _refus is not None:
            return _refus
        body = await request.json()
        try:
            r = _hx.post("http://127.0.0.1:8000/event", json=body, timeout=5.0)
            return _JR({"ok": True, "deno": r.json()})
        except Exception as e:
            return _JR({"ok": False, "error": str(e)}, status_code=502)

    async def mcp_bundle(request):
        """POST /bundle — Replay bundle calls, optionally zlib compressed"""
        import base64
        import json
        import zlib

        from starlette.responses import JSONResponse as _JR

        try:
            body = await request.json()
            if "bundle_zlib" in body:
                compressed = base64.b64decode(body["bundle_zlib"])
                decompressed = zlib.decompress(compressed)
                calls = json.loads(decompressed).get("calls", [])
            else:
                calls = body.get("bundle_raw", [])

            results = []
            for item in calls:
                tname = item.get("tool", "")
                targs = item.get("args", {})
                if not tname:
                    results.append({"error": "missing tool"})
                    continue
                try:
                    res = await _tool_call(tname, targs, ring=0, agent="HUB_BUNDLE")
                    results.append({"tool": tname, "result": res})
                except Exception as ex:
                    results.append({"tool": tname, "error": str(ex)})
            return _JR({"results": results})
        except Exception as e:
            return _JR({"error": str(e)}, status_code=400)

    async def orchestrate_loop(request: Request):
        """Boucle autonome Ollama — RAG context + [READ:path] + GOAP steps. Zero round-trip Claude."""
        # PORTEUR EXIGE -- 2026-09-21. Boucle autonome : lit des fichiers
        # (`[READ:path]`) et enchaine des etapes GOAP. Aucun appelant HTTP au
        # depot.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        import re as _re
        import traceback as _tb
        import urllib.request as _ur

        try:
            body = await request.json()
            task = body.get("task", "")
            plan = body.get("plan", [])
            max_steps = int(body.get("max_steps", 20))
            model = body.get("model", "qwen2.5-coder:7b-instruct-q4_K_M")
            rag_hits = []
            files_read = []

            rag_ctx = ""
            try:
                from nokido_agent.app.forge_self_correction import preflight_check_verbose

                pf = preflight_check_verbose(task, "", limit=5)
                for h in pf.get("results", [])[:5]:
                    src = h.get("source", "")
                    rag_hits.append(src)
                    rag_ctx += f"[RAG:{src}]\n{h.get('preview', '')[:300]}\n\n"
            except Exception:
                pass

            context = f"Task: {task}\n"
            if rag_ctx:
                context += f"\n[Context]:\n{rag_ctx}\n"

            def _read_safe(path):
                try:
                    from pathlib import Path as _P

                    p = _P(path) if _P(path).is_absolute() else ROOT / path
                    if not p.exists() or p.stat().st_size > 200_000:
                        return f"[NOT FOUND: {path}]"
                    return p.read_text(encoding="utf-8", errors="replace")[:2000]
                except Exception as e:
                    return f"[READ ERROR: {e}]"

            def _ollama(prompt):
                _pl = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
                try:
                    _rq = _ur.Request(
                        "http://localhost:11434/api/generate",
                        data=_pl,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with _ur.urlopen(_rq, timeout=60) as _r:
                        return json.loads(_r.read()).get("response", "")
                except Exception as e:
                    return f"[ERROR:{e}]"

            def _write_safe(path, content):
                try:
                    from pathlib import Path as _P

                    p = _P(path) if _P(path).is_absolute() else ROOT / path
                    p.resolve().relative_to(ROOT.resolve())  # security: must stay under ROOT
                    # WorkspaceGuard — refuse fichiers critiques + secrets meme
                    # en boucle autonome (assert_can_write leve SecretGuardViolation,
                    # capturee par l'except ci-dessous -> [WRITE ERROR]).
                    try:
                        from nokido_agent.app.forge_mcp_security import assert_can_write as _acw

                        _acw(str(p.resolve()), "CLAUDE", 0)
                    except ImportError as e:
                        import logging as _lg

                        # CONTOURNEMENT DE GARDE, pas une degradation : sans ce
                        # module, l'ecriture se poursuit SANS controle d'autorisation.
                        # Un garde absent qui ne le dit pas est pire qu'un garde
                        # absent : le systeme se relit comme protege.
                        _lg.getLogger("forge.hub").error(
                            "[securite] forge_mcp_security INDISPONIBLE (%s) — "
                            "l'ecriture de %s se poursuit SANS controle "
                            "d'autorisation | consequence: le garde d'ecriture est "
                            "inactif et rien d'autre ne le signale", e, p)
                    if len(content) > 50_000:
                        return f"[TOO LARGE: {path}]"
                    if p.suffix == ".py":
                        import ast as _ast

                        _ast.parse(content)  # reject invalid Python
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content, encoding="utf-8")
                except Exception as e:
                    return f"[WRITE ERROR: {e}]"

            goap = list(plan)
            steps = 0
            retry_left = 2
            files_written = []
            # Cap wall-clock : une boucle locale (Ollama 60s/step) courrait sinon
            # illimitée (max_steps × 60s = jusqu'à ~20 min). max_seconds borne la
            # durée totale (def 300s) ; le client reçoit timed_out=True si atteint.
            _t_start = time.monotonic()
            _max_seconds = float(body.get("max_seconds", 300))
            while steps < max_steps and (time.monotonic() - _t_start) < _max_seconds:
                prompt = context + (f"\n[STEP]: {goap.pop(0)}\nProceed:" if goap else "")
                chunk = _ollama(prompt)
                if chunk.startswith("[ERROR:") and retry_left > 0:
                    retry_left -= 1
                    context += f"\n[RETRY_HINT]: Previous attempt failed: {chunk[:200]}. Correct and retry.\n"
                    continue
                for m in _re.finditer(r"\[READ:([^\]]+)\]", chunk):
                    fpath = m.group(1).strip()
                    files_read.append(fpath)
                    chunk += f"\n[FILE:{fpath}]\n{_read_safe(fpath)}\n[/FILE]"
                for m in _re.finditer(r"\[WRITE:([^\|]+)\|(.+?)\]", chunk, _re.DOTALL):
                    fpath, content_w = m.group(1).strip(), m.group(2).strip()
                    _write_safe(fpath, content_w)
                    files_written.append(fpath)
                context += chunk + "\n"
                steps += 1
                if "[DONE]" in chunk or "[FIN]" in chunk:
                    break
                if plan and not goap:
                    context += "\n[SYNTHESIS]: Summarize findings concisely.\n"
                    context += _ollama(context)
                    steps += 1
                    break

            return JSONResponse(
                {
                    "ok": True,
                    "result": context[-4000:],
                    "steps": steps,
                    "elapsed_s": round(time.monotonic() - _t_start, 1),
                    "timed_out": (time.monotonic() - _t_start) >= _max_seconds,
                    "rag_hits": rag_hits,
                    "files_read": files_read,
                    "files_written": files_written,
                }
            )
        except Exception as _e:
            return JSONResponse(
                {"ok": False, "error": str(_e), "trace": _tb.format_exc()[-1000:]}, status_code=500
            )

    # ── Generative UI endpoints ───────────────────────────────────────────────
    async def ui_generate(request):
        try:
            body = await request.json()
            description = body.get("description", "").strip()
            if not description:
                return JSONResponse({"error": "description required"}, status_code=400)
            import asyncio as _asyncio
            import sys as _sys

            _sys.path.insert(0, str(ROOT / "tools"))
            from nokido_agent.tools.forge_ui_generator import generate_component

            # LE HUB S'APPELAIT LUI-MEME ET S'ATTENDAIT — mesure 2026-09-21.
            #
            #   ui_generate (async def, DANS la boucle, AUCUN porteur exige)
            #     -> generate_component(description, save=True)
            #     -> _hub_ask(prompt, timeout=120)
            #     -> urllib.request.urlopen("http://localhost:8766/mcp", 120 s)
            #
            # La cible est CE serveur. Un handler de la boucle appelait la
            # boucle et l'attendait : `/mcp` ne pouvait pas etre servi tant que
            # `ui_generate` la tenait. Deadlock jusqu'au timeout de 120 s,
            # pendant lesquelles le hub ENTIER est muet -- et la route
            # n'exige aucun credential. Meme famille que l'incident
            # `rag_stats` du matin, sur un autre transport.
            #
            # Passer la route en `def` ne suffit PAS : `await request.json()`
            # au-dessus exige qu'elle reste une coroutine. On deporte donc
            # l'appel bloquant lui-meme, dans la forme deja employee ailleurs
            # dans ce fichier.
            #
            # Le cout n'est pas supprime -- la generation reste longue. Il
            # cesse d'etre PARTAGE par tous les appelants.
            result = await _asyncio.get_running_loop().run_in_executor(
                None, lambda: generate_component(description, save=True))
            return JSONResponse(result)
        except Exception as _e:
            return JSONResponse({"error": str(_e)}, status_code=500)

    async def ui_components(request):
        try:
            import sys as _sys

            _sys.path.insert(0, str(ROOT / "tools"))
            from nokido_agent.tools.forge_ui_generator import list_components

            return JSONResponse({"components": list_components()})
        except Exception as _e:
            return JSONResponse({"error": str(_e)}, status_code=500)

    async def ui_serve(request):
        # CONFINEMENT A LA RACINE — revue defensive LOCAL-IPC du 2026-09-18.
        #
        # `component_id` vient de l'URL et etait concatene tel quel dans un
        # `Path` : `../../..` sortait du dossier des composants, et le contenu
        # etait rendu au client. Portee REELLE, a ne pas surestimer : le suffixe
        # `.html` est force par le code, donc la lecture ne portait que sur des
        # fichiers `.html` — c'est une traversee bornee, pas un acces a `.env`
        # ou aux sources. Bornee reste exploitable : on la ferme.
        #
        # Le confinement se fait sur le chemin RESOLU, pas sur le texte : filtrer
        # « .. » dans la chaine laisserait passer les liens, les chemins absolus
        # et les encodages — c'est le meme motif qu'une liste de mots-clefs
        # interdits en SQL, un garde qu'on franchit en reecrivant son entree.
        #
        # Le refus est le MEME (404) pour « hors racine » et pour « absent » :
        # deux reponses distinctes feraient de cette route un oracle d'existence
        # de fichiers.
        component_id = request.path_params.get("component_id", "")
        base = (ROOT / "sandbox" / "ui_components").resolve()
        try:
            comp_path = (base / f"{component_id}.html").resolve()
        except (OSError, ValueError):
            # Un nom que le systeme de fichiers refuse de resoudre n'est pas un
            # composant : meme reponse que l'absence, et surtout pas une 500.
            return JSONResponse({"error": "not found"}, status_code=404)
        if not comp_path.is_relative_to(base) or not comp_path.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)
        return HTMLResponse(comp_path.read_text(encoding="utf-8"))

    async def mpc_plan(request):
        """AMI Phase 6 — full MPC loop via hub execute_fn.

        POST /mpc/plan
        Body: {"goal": str, "state": str, "max_steps": int=4}
        Returns: MPCResult as JSON.
        """
        # PORTEUR EXIGE -- 2026-09-21. Boucle MPC via `execute_fn` du hub :
        # execution. Aucun appelant HTTP au depot.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        import json as _json
        import sys as _sys
        import time as _time
        import urllib.request as _ur

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        goal_text = body.get("goal", "")
        state_text = body.get("state", "")
        max_steps = int(body.get("max_steps", 4))
        if not goal_text:
            return JSONResponse({"error": "goal required"}, status_code=400)

        _sys.path.insert(0, str(ROOT / "app"))

        def _hub_execute_fn(action_dict: dict):
            desc = action_dict.get("description", "noop")
            task_type = desc.split(":")[0]
            t0 = _time.time()
            result_text = ""
            success = False
            actual_cost = 0.6
            try:
                if task_type in ("replay_hub", "monitoring"):
                    req = _ur.Request("http://127.0.0.1:8766/health")
                    with _ur.urlopen(req, timeout=5) as r:
                        data = _json.loads(r.read())
                    ok = data.get("status") in ("ok", "healthy")
                    result_text = f"hub={'UP' if ok else 'DOWN'}"
                    success = ok
                    actual_cost = 0.05 if ok else 0.85
                elif task_type in ("replay_rag", "rag_query", "research"):
                    req = _ur.Request(
                        "http://127.0.0.1:8766/rag/query",
                        data=_json.dumps({"query": goal_text, "top_k": 3}).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with _ur.urlopen(req, timeout=8) as r:
                        data = _json.loads(r.read())
                    n = len(data.get("results", []))
                    result_text = f"rag_hits={n}"
                    success = n > 0
                    actual_cost = 0.15 if n > 1 else 0.45
                else:
                    req = _ur.Request("http://127.0.0.1:8766/health")
                    with _ur.urlopen(req, timeout=5) as r:
                        data = _json.loads(r.read())
                    ok = data.get("status") in ("ok", "healthy")
                    result_text = f"fallback_health={'UP' if ok else 'DOWN'}"
                    success = ok
                    actual_cost = 0.10 if ok else 0.80
            except Exception as e:
                result_text = f"err={str(e)[:60]}"
                actual_cost = 0.90
            elapsed_ms = int((_time.time() - t0) * 1000)
            return f"[{task_type}] {result_text} ({elapsed_ms}ms)", actual_cost, success

        try:
            from nokido_agent.app.forge_configurator import get_mpc_config
            from nokido_agent.app.forge_mpc import run_mpc_loop

            cfg = get_mpc_config(goal_text, state_text)
            loop_result = run_mpc_loop(
                goal_text=goal_text,
                state_text=state_text,
                max_steps=max_steps,
                config=cfg,
                execute_fn=_hub_execute_fn,
            )
            steps_out = [
                {
                    "action": s.action,
                    "predicted_cost": round(s.predicted_cost, 4),
                    "actual_cost": round(s.actual_cost or 0.0, 4),
                    "surprise": s.surprise,
                    "replan": s.replan,
                    "elapsed_ms": round(s.elapsed_ms, 1),
                }
                for s in loop_result.steps
            ]
            return JSONResponse(
                {
                    "success": loop_result.success,
                    "n_replans": loop_result.n_replans,
                    "total_predicted_cost": round(loop_result.total_predicted_cost, 4),
                    "total_actual_cost": round(loop_result.total_actual_cost, 4),
                    "steps": steps_out,
                    "task_type": cfg.get("task_type", "orchestration"),
                    "use_mcts": cfg.get("use_mcts", False),
                }
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def oauth_discovery(request):
        # MCP HTTP transport: Claude Code probes /.well-known/oauth-* (and path-aware
        # variants like /.well-known/oauth-authorization-server/mcp per RFC 9728)
        # before bearer auth. Return JSON 404 so the client parses it and falls back.
        return JSONResponse(
            {"error": "not_supported", "description": "This server uses Bearer token auth only"},
            status_code=404,
        )

    async def admin_restart(request):
        # Self-restart: exit the process so the supervisor (neverSleep=true)
        # revives it with fresh code. Lets agents reload the hub WITHOUT admin
        # rights — the hub runs as SYSTEM, nssm/taskkill need elevation, but
        # this endpoint is on :8766 and only needs the bearer token.
        import os as _os
        import threading
        import time as _t

        # GOUVERNANCE (2026-08-17) : cette route ne verifiait QUE le jeton maitre
        # — ni ring, ni RBAC, ni gate. Tout porteur du jeton pouvait donc tuer le
        # hub sans franchir un seul garde, alors que la voie gouvernee equivalente
        # (`run action=hub_restart`) exige le ring 0. C'etait une porte derobee
        # dans un systeme ou tout le reste est gate. On resout desormais
        # l'identite comme `_tool_call` et on exige un ring de maintenance.
        ring, agent = _resolve_ring(request)
        if ring < 0 or ring > 1:
            logger.warning("admin_restart REFUSE — agent=%s ring=%s", agent, ring)
            return JSONResponse(
                {"ok": False, "error": "ring %s insuffisant (<= 1 requis)" % ring, "agent": agent},
                status_code=403,
            )
        logger.warning("admin_restart — demande par %s (ring %s)", agent, ring)

        # HONNETETE : l'ancien message promettait « supervisor revives in ~5s ».
        # Mesure du 2026-08-17 : le superviseur a bien VU la sortie
        # (`LaForgeMCP: exited code=0 ... (restart #0)`) et n'a RIEN relance — il
        # ne re-planifie que si le service n'est pas deja `stopped`/`sleeping`
        # dans SON etat. Le hub est reste mort et il a fallu l'owner. Tant qu'une
        # voie de relance fiable n'est pas cablee, on le DIT au lieu de le promettre.
        def _bye():
            _t.sleep(0.6)
            _os._exit(0)

        threading.Thread(target=_bye, daemon=True).start()
        return JSONResponse({
            "ok": True,
            "msg": "hub arrete proprement",
            "attention": "le superviseur ne le relance PAS automatiquement — "
                         "relancer via le lanceur (nokido_start.ps1) si besoin",
            "demande_par": agent,
        })

    def _ingest_local_dir(dir_path, name: str) -> dict:
        """Walk a local dir, chunk text files, INSERT into rag_chunks. In-process
        (hub context) — so it CAN write embeddings.db, unlike the run sandbox.
        Read-only on the filesystem, no subprocess, no network."""
        import hashlib as _hl
        import sqlite3 as _sql

        TEXT_EXT = {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".cfg",
            ".ini",
            ".sh",
            ".rs",
            ".go",
            ".java",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".html",
            ".css",
            ".sql",
        }
        SKIP_DIRS = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            "dist",
            "build",
            ".idea",
            ".pytest_cache",
        }
        # never ingest secrets even if a caller points at a sensitive tree
        SENSITIVE = ("token", "cred", "secret", "password", ".key", ".pem", ".env")
        MAX_FILE, CHUNK = 200_000, 1000
        db = ROOT / "RAG" / "embeddings.db"
        domain = f"repo_{name}"
        files = []
        for p in dir_path.rglob("*"):
            if not p.is_file() or any(d in p.parts for d in SKIP_DIRS):
                continue
            if p.suffix.lower() not in TEXT_EXT:
                continue
            low = p.name.lower()
            if any(s in low for s in SENSITIVE):
                continue
            try:
                if p.stat().st_size > MAX_FILE:
                    continue   # filtre VOULU : au-dela de MAX_FILE on n'ingere pas
            except OSError as e:
                import logging as _lg

                _lg.getLogger("forge.hub").warning(
                    "[ingest] %s non examinable (%s: %s) — ecarte | consequence: ce "
                    "chemin n'est ni ingere ni compte comme refuse, il DISPARAIT du "
                    "perimetre sans laisser de trace", p, type(e).__name__, str(e)[:80])
                continue
            files.append(p)
        con = _sql.connect(str(db))
        cur = con.cursor()
        inserted = 0
        for p in files:
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("forge.hub").warning(
                    "[ingest] %s ILLISIBLE (%s: %s) — ecarte | consequence: ce fichier "
                    "n'est PAS dans l'index, et son absence des resultats ne veut pas "
                    "dire qu'il n'existe pas", p, type(e).__name__, str(e)[:80])
                continue
            rel = str(p.relative_to(dir_path)).replace("\\", "/")
            for i in range(0, len(txt), CHUNK):
                chunk = txt[i : i + CHUNK].strip()
                if len(chunk) < 50:
                    continue
                src = f"repo:{name}/{rel}"
                cid = _hl.sha256((src + chunk).encode()).hexdigest()[:16]
                try:
                    cur.execute(
                        "INSERT OR IGNORE INTO rag_chunks (id,text,source,domain,role_hint) "
                        "SELECT ?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
                        (cid, chunk, src, domain, "code", cid),
                    )
                    if cur.rowcount:
                        inserted += 1
                except Exception as e:  # noqa: BLE001
                    import logging as _lg

                    _lg.getLogger("forge.hub").warning(
                        "[ingest] chunk NON insere pour %s (%s: %s) | consequence: ce "
                        "fragment est absent de l'index, la couverture annoncee est "
                        "superieure a la couverture reelle",
                        src, type(e).__name__, str(e)[:80])
        con.commit()
        try:
            cur.execute("INSERT INTO rag_fts(rag_fts) VALUES('rebuild')")
            con.commit()
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # Le lexical PRIME dans la recherche. Un index non reconstruit sert
            # l'ANCIEN texte sans jamais lever d'erreur — mesure du 2026-07-29 :
            # lexical mort sur 99,5 % du corpus, invisible pendant des semaines.
            _lg.getLogger("forge.hub").error(
                "[ingest] reconstruction FTS ECHOUEE (%s: %s) | consequence: la "
                "recherche lexicale sert un index PERIME sur ce qui vient d'etre "
                "ingere, sans erreur visible", type(e).__name__, str(e)[:100])
        con.close()
        return {"files": len(files), "chunks_inserted": inserted, "domain": domain}

    async def admin_ingest_repo(request):
        # In-process repo ingestion — contourne le sandbox readonly proprement.
        # No clone / no subprocess / no network here: caller does `git clone`
        # separately, this only walks a local dir and writes RAG.
        import os as _os
        import re as _re

        # admin_ingest_repo : garde central, plus de copie locale. L'ancienne
        # verification faisait `if expected and tok != expected` : quand
        # FORGE_MCP_TOKEN etait absent de l'environnement, `expected` valait "" et
        # le controle entier etait SAUTE — la route passait sans jeton. Le garde
        # central `_admin_tok_ok` refuse dans ce cas (sauf LAFORGE_NO_AUTH=1, et
        # seulement depuis le loopback) : une copie d'un controle d'acces finit par
        # diverger de l'original, et ici la divergence se payait en securite.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        path = str(body.get("path", ""))
        name = str(body.get("name", ""))
        if not _re.match(r"^[\w.-]{1,40}$", name):
            return JSONResponse(
                {"ok": False, "error": "name must match [A-Za-z0-9_.-]{1,40}"}, status_code=400
            )
        try:
            p = Path(path).resolve()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad path"}, status_code=400)
        allowed = [Path("C:/tmp").resolve(), ROOT.resolve()]
        if not any(str(p) == str(a) or str(p).startswith(str(a) + _os.sep) for a in allowed):
            return JSONResponse(
                {"ok": False, "error": "path must be under C:/tmp or Nokido root"}, status_code=400
            )
        if not p.is_dir():
            return JSONResponse({"ok": False, "error": "path is not a directory"}, status_code=400)
        try:
            res = _ingest_local_dir(p, name)
            logger.info("admin_ingest_repo name=%s -> %s", name, res)
            return JSONResponse({"ok": True, **res})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)

    # Organes autorises a atteindre /admin/* avec LEUR PROPRE jeton (2026-09-20).
    #
    # LISTE BLANCHE, et surtout PAS un seuil de ring : SUPERVISOR est ring 1, mais
    # CLAUDE et GEMINI le sont AUSSI. Ouvrir /admin « aux ring <= 1 » aurait donne
    # l'administration du hub a tous les clients du corps. L'autorisation admin ne
    # se deduit pas d'un ring -- elle se declare, ici, nommement.
    _ADMIN_ORGANES = frozenset({"SUPERVISOR"})

    def _refus_401(detail: str = "unauthorized"):
        """401 CONFORME. RFC 7235 section 4.1 : « The server generating a 401
        response MUST send a WWW-Authenticate header field ». Le hub rendait un
        JSON nu (mesure du 2026-09-20, 19 sites identiques) : un client conforme
        ne pouvait pas savoir quel schema presenter. RFC 6750 section 3 fixe le
        schema `Bearer` et son `realm`."""
        return JSONResponse(
            {"ok": False, "error": detail}, status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="nokido-hub"'})

    def _journaliser_refus_admin(request, tok: str, chemin: str,
                                 required_scope: str | None = None) -> None:
        """Trace un REFUS de `_admin_tok_ok`. Jamais une acceptation.

        MESURE DU 2026-09-21 — huit questions, et elles tranchent seules :
          * 24 routes atteignent ce garde, toutes reliees ;
          * QUATRE chemins de decision (JWT · maitre · exemption loopback ·
            jeton propre d'organe) -- un refus ne disait pas LEQUEL ;
          * `_refus_401` n'avait qu'UN appelant : pas le chemin universel ;
          * la ROUTE manquait a la signature... mais `request.url.path` la
            porte : AUCUNE signature n'a eu besoin de changer.

        POURQUOI LES REFUS SEULS. Le journal chiffre CHAQUE entree (DPAPI) et
        la chaine en HMAC. Tracer les ACCEPTATIONS de 24 routes a chaque
        requete est un choix de DEBIT qu'aucune mesure ne justifie -- et le
        debit reel de ces routes n'a PAS ete mesure. Un refus est rare et
        explicatif ; c'est ce qu'on ecrit.

            ON CAPTURE CE QUI EST RARE ET EXPLICATIF, PAS CE QUI EST FREQUENT

        LE PORTEUR NE SORT JAMAIS D'ICI. Seul son hash voyage -- meme
        invariant que `forge_videur.capture`, deja verrouille par NR.

        BEST-EFFORT STRICT : une trace qui echoue ne doit pas transformer un
        refus en erreur 500. Le garde a deja decide ; journaliser est un
        effet de bord, jamais une condition.
        """
        try:
            import hashlib as _hl

            from nokido_agent.app.forge_videur import capture as _cap

            _cap(
                {
                    "agent": (request.headers.get("laforge-agent-name", "") or "").strip().upper()
                             or "UNKNOWN",
                    "ring": None,
                    "via": "admin_tok_refuse:%s" % chemin,
                    "token_h": _hl.sha256(tok.encode()).hexdigest()[:16] if tok else "",
                },
                "_admin_tok_ok",
                {
                    "decision": "DENY",
                    "route": getattr(getattr(request, "url", None), "path", "") or "",
                    "scope_requis": required_scope or "",
                    "porteur_present": bool(tok),
                },
            )
        except Exception:  # noqa: BLE001
            pass  # muet-ok : une trace qui echoue ne change pas la decision

    def _admin_tok_ok(request, required_scope: str | None = None) -> bool:
        # Phase 23C (2026-05-25) : accepte JWT HS256 ET bearer raw (backward).
        # JWT prioritaire : si token a 2 points = JWT, sinon raw bearer.
        # required_scope : check capability scope dans JWT (e.g. 'services:start',
        # 'admin:shutdown_all'). Si bearer raw = full admin (legacy).
        import hmac as _hmac
        import os as _os

        tok = request.headers.get("authorization", "")
        tok = tok[7:].strip() if tok.lower().startswith("bearer ") else tok.strip()
        # 2b-2 (2026-09-28) : le maitre se lit au GUICHET (coffre reserve d'abord sous
        # SYSTEM), plus par `getenv`. TRANSITION jusqu'a 2b-7 (purge de l'environnement,
        # go owner) : la valeur de l'environnement reste acceptee, et un accord par elle
        # SEULE se journalise -- il mesure la divergence environnement / guichet.
        try:
            from nokido_agent.app.forge_secrets import get_secret as _gs_maitre

            expected = _gs_maitre("FORGE_MCP_TOKEN") or ""
        except Exception:  # noqa: BLE001
            expected = ""  # guichet indisponible : l'environnement seul, journalise plus bas
        expected_env = _os.getenv("FORGE_MCP_TOKEN", "")
        # Path 1 : JWT (3 segments separes par '.')
        if tok and tok.count(".") == 2:
            try:
                from nokido_agent.app.forge_auth_jwt import verify_token

                claims = verify_token(tok, required_scope=required_scope)
                if claims is not None:
                    return True
                _journaliser_refus_admin(request, tok, "jwt_scope", required_scope)
                return False
            except Exception:
                pass  # fallback raw bearer
        # Path 2 : bearer raw (Phase 23A backward-compat)
        if not expected and not expected_env:
            no_auth = _os.environ.get("LAFORGE_NO_AUTH", "0") == "1"
            if not no_auth:
                _journaliser_refus_admin(request, tok, "pas_de_maitre_configure",
                                         required_scope)
                return False
            client = (request.client.host if request.client else "") or ""
            if client in ("127.0.0.1", "::1", "localhost", ""):
                return True
            _journaliser_refus_admin(request, tok, "no_auth_hors_loopback",
                                     required_scope)
            return False
        if expected and _hmac.compare_digest(tok, expected):
            return True
        if expected_env and _hmac.compare_digest(tok, expected_env):
            import logging as _lg_admin

            _lg_admin.getLogger("forge.hub").warning(
                "[admin] maitre accepte par l'ENVIRONNEMENT seul (divergence "
                "environnement / guichet) -- transition jusqu'a 2b-7")
            return True
        # Path 3 (2026-09-20) : JETON PROPRE d'un organe de la liste blanche.
        #
        # DEFAUT MESURE : `POST /admin/run_job` avec `FORGE_TOKEN_SUPERVISOR` rendait
        # 401 quand le meme appel avec le master rendait 200. Or `_hubAuthHeaders()`
        # cote superviseur fait `token = propre || master` -- il PREFERE le propre des
        # qu'il existe. Seme le 2026-09-02, ce jeton a donc remplace un master qui
        # marchait par un porteur que /admin refusait. Journal du superviseur :
        # `ok=true` jusqu'au 28/08, `job=? ok=false` les 09, 12 et 17/09 ; et
        # `snapshot memoire` n'apparait QUE dans les echecs -- il n'a jamais reussi.
        # Consequence mesuree : snapshot memoire perime de 14,25 j, arbitre en INCONNU.
        #
        # Le SSoT impose ce sens de correctif, il n'y avait pas de choix :
        # `agent_identities.json` declare pour SUPERVISOR « il ne doit PAS emprunter
        # FORGE_MCP_TOKEN -- un organe qui le porte devient indiscernable dans le
        # journal ». Rebrancher le master aurait contredit le registre.
        #
        # DEUX BORNES, et elles sont le coeur du dispositif :
        #   - le NOM seul n'ouvre rien : un porteur est EXIGE et compare en temps
        #     constant. « Nommer n'est pas autoriser » -- plancher anti-spoof du
        #     videur, applique ici aussi.
        #   - la liste est NOMMEE, jamais derivee d'un ring (cf. _ADMIN_ORGANES).
        if tok:
            nom = (request.headers.get("laforge-agent-name", "") or "").strip().upper()
            if nom in _ADMIN_ORGANES:
                try:
                    from nokido_agent.app.forge_secrets import get_secret as _gs
                    propre = _gs("FORGE_TOKEN_%s" % nom) or ""
                except Exception:  # noqa: BLE001
                    propre = ""   # coffre indisponible -> refus, JAMAIS ouverture
                if propre and _hmac.compare_digest(tok, propre):
                    # PREUVE TPM (2026-09-24, chantier d'authentification) : operation
                    # sensible -> garantie forte. La decision vit dans forge_dpop (un
                    # adaptateur, pas une politique de plus dans le hub). OBSERVATION par
                    # defaut ; APPLIQUEE sur LAFORGE_ADMIN_TPM_ENFORCE=1 (geste owner).
                    # Module indisponible : refus si applique, passage si observation.
                    try:
                        from nokido_agent.app.forge_dpop import decision_admin_tpm as _dtpm

                        _dec = _dtpm(request.headers.get("dpop", ""), request.method,
                                     request.scope["path"], nom, tok)
                    except Exception as _e_tpm:  # noqa: BLE001
                        _dec = {"autorise": _os.environ.get("LAFORGE_ADMIN_TPM_ENFORCE") != "1",
                                "etat": "INVERIFIABLE",
                                "raison": "decision TPM indisponible (%s)" % type(_e_tpm).__name__}
                    if not _dec.get("autorise"):
                        _journaliser_refus_admin(request, tok, "preuve_tpm_%s" % _dec.get("etat"),
                                                 required_scope)
                        return False
                    return True
        _journaliser_refus_admin(request, tok, "aucun_chemin_accepte", required_scope)
        return False

    def _garde_ui(handler, capacite: str):
        """MUTATION appelee depuis une page : jeton admin OU session UI du portail + origine locale.

        Chantier d'authentification (2026-09-24). Ces routes etaient ouvertes parce que leur
        seul appelant est une page, et qu'on ne glisse pas un jeton dans du HTML servi. La
        decision vit dans `forge_authz_http` (adaptateur unique) ; ce hub ne fait que la
        brancher. `_admin_tok_ok` n'est consulte que si un porteur est presente : sans lui,
        c'est la session du navigateur qui parle. Module indisponible -> REFUS (AUTH-4).
        """
        async def _garde(request):
            admin_ok = bool(request.headers.get("authorization")) and _admin_tok_ok(request)
            try:
                from nokido_agent.app.forge_authz_http import autoriser_mutation_ui as _amu

                d = _amu(request, capacite, admin_ok=admin_ok)
            except Exception as _e_ui:  # noqa: BLE001 -- adaptateur absent : jamais une ouverture
                d = {"autorise": False, "raison": "adaptateur indisponible (%s)" % type(_e_ui).__name__}
            if not d.get("autorise"):
                return JSONResponse({"ok": False, "error": "unauthorized", "detail": d.get("raison")},
                                    status_code=401)
            request.state.principal = d.get("principal")
            return await handler(request)

        _garde.__name__ = getattr(handler, "__name__", "garde_ui")
        return _garde

    async def admin_run_job(request):
        # Launch a long Python job DETACHED as the sandbox user (online=true ->
        # sandbox-online, network). Same privilege as `run network:true`, NO
        # escalation. The detached child survives a hub restart; all state in
        # files under C:/tmp/nokido_jobs. Poll GET /admin/job/{job_id}.
        import os as _os
        import sys as _sys
        import uuid as _uuid
        from datetime import datetime as _dt

        if not _admin_tok_ok(request):
            return _refus_401()
        try:
            body = await request.json()
        except Exception:
            body = {}
        script = str(body.get("script", ""))
        online = bool(body.get("online", False))
        try:
            sp = Path(script).resolve()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad script path"}, status_code=400)
        allowed = [Path("C:/tmp").resolve(), ROOT.resolve()]
        if not any(str(sp) == str(a) or str(sp).startswith(str(a) + _os.sep) for a in allowed):
            return JSONResponse(
                {"ok": False, "error": "script must be under C:/tmp or Nokido root"},
                status_code=400,
            )
        if not sp.is_file() or sp.suffix != ".py":
            return JSONResponse(
                {"ok": False, "error": "script must be an existing .py file"}, status_code=400
            )
        # MIGRE LE 2026-09-21 vers l'organe canonique du job detache.
        #
        # Cette route fabriquait ici son propre wrapper de 266 octets : trois
        # lignes qui lancaient la cible en sous-processus et ecrivaient son code
        # de sortie. Rien d'autre -- aucun garde.
        # `forge_job_runner.launch_job` porte NEUF gardes qu'il n'avait pas, et
        # chacun est ne d'un incident DATE : cap LOG 200 Mo (28/07, 3 jobs de
        # 70 Go, disque plein, hub mort) · cap RSS 6 Go (02/08, famine RAM,
        # bureau fige, redemarrage manuel) · kill de l'ARBRE (13/09, un pytest
        # de 8,6 Go survit au kill de son wrapper de 50 Mo) · .rc ecrit quoi
        # qu'il arrive (05/09, garde mort avant le .rc donc « running » a vie
        # et lane jamais relachee) · 137 non ecrase · script_args (20/08, un
        # `--once` perdu changeait un one-shot en daemon infini) · lane et son
        # release contre le bail orphelin de 2 h · identite de process au
        # registre superviseur · LAFORGE_JOB_ID pour la progression.
        #
        # Et le REPERTOIRE : JOBS_DIR a ete deplace vers sandbox/jobs EXACTEMENT
        # pour fuir C:/tmp/nokido_jobs, « la zone d'explosion » -- cette route y
        # ecrivait encore.
        #
        # `lane` n'etait PAS lue ici : l'anti-saturation ne pouvait donc pas
        # s'appliquer, quoi que demande l'appelant. `params_depuis_corps` vit
        # dans l'organe qui lance, pour qu'aucun appelant ne la relise a sa
        # facon et n'en oublie un champ.
        try:
            _sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_job_runner import launch_job, params_depuis_corps
        except Exception as e:
            return JSONResponse(
                {"ok": False, "error": f"job runner indisponible: {str(e)[:200]}"},
                status_code=500,
            )
        params = params_depuis_corps(body)
        params["script"] = str(sp)      # chemin deja resolu et valide ci-dessus
        res = launch_job(**params)
        if not res.get("ok"):
            err = str(res.get("error", ""))
            # Une faute d'appel est une requete invalide (400) ; un spawn qui
            # echoue est une panne du serveur (500). Les confondre ferait
            # chercher une panne la ou il y a une erreur de parametre.
            return JSONResponse(
                {"ok": False, "error": err},
                status_code=500 if "spawn failed" in err else 400,
            )
        logger.info(
            "admin_run_job %s pid=%s script=%s lane=%s",
            res.get("job_id"), res.get("pid"), sp.name, params["lane"] or "-",
        )
        # ACCEPTED n'est pas PRODUCED : on ne rend que ce que le spawn a
        # repondu. L'etat reel se lit par GET /admin/job/{job_id}, qui
        # reconcilie ; rien ici ne prouve qu'un travail ait commence.
        return JSONResponse({
            "ok": True, "job_id": res.get("job_id"), "pid": res.get("pid"),
            "lane": params["lane"], "etat": "ACCEPTED",
            "note": "ACCEPTED n'est pas PRODUCED : interroger GET /admin/job/{job_id}",
        })

    async def admin_job_stop(request):
        """Arrete un job detache. Le hub est leur ANCETRE, lui seul y arrive.

        BLOCKER ouvert le 2026-07-25 : aucun compte client ne peut arreter un
        processus qu'il a fait naitre (4 formes refusees, LaForgeTrusted n'ayant aucun
        privilege Windows). Le hub a CREE le job -> l'arret appartient ici.
        `kill` faux par defaut : un arret est irreversible, il se demande.
        """
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        job_id = str(request.path_params.get("job_id", ""))
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            import sys as _s

            _tools = str(ROOT / "tools")
            if _tools not in _s.path:
                _s.path.insert(0, _tools)
            from nokido_agent.tools.forge_job_stop import stop_job
        except Exception as e:
            return JSONResponse(
                {"ok": False, "error": f"forge_job_stop indisponible: {str(e)[:140]}"},
                status_code=500,
            )
        res = stop_job(
            job_id,
            kill=bool(body.get("kill", False)),
            force=bool(body.get("force", False)),
        )
        logger.info(
            "admin_job_stop %s kill=%s -> ok=%s", job_id, body.get("kill"), res.get("ok")
        )
        # 409 quand un pid a resiste : le code HTTP doit dire la verite, pas rassurer.
        _code = 200 if (res.get("ok") or res.get("dry_run")) else 409
        return JSONResponse(res, status_code=_code)

    async def admin_heap(request):
        """Qui tient la memoire du hub ? Parcours du tas BORNE, en LECTURE SEULE.

        Pourquoi cette route existe (2026-08-25) : le hub tenait 7,7 Go d'engagement
        prive et rien ne permettait de dire de QUOI. Les deux voies non intrusives sont
        fermees, mesure a l'appui — `psutil.memory_maps()` sur ce process rend
        `AccessDenied` depuis un compte non privilegie, et l'oracle Python s'execute
        dans un sandbox SEPARE, pas ici. Restait le parcours du tas depuis l'interieur.

        BORNEE PAR CONSTRUCTION. Ce parcours est du Python pur : il tient le GIL et
        ralentit donc tout le hub pendant qu'il tourne. `budget` (defaut 5 s, plafond
        30) coupe la marche et le resultat porte `complet: false`. Un resultat tronque
        QUI LE DIT vaut mieux qu'un resultat complet qui ne vient jamais — et surtout
        mieux qu'un tronque qui se fait passer pour entier.

        A savoir avant de lire les chiffres : `gc.get_objects()` alloue lui-meme une
        liste de N pointeurs (~8 octets par objet vivant), et `sys.getsizeof` ignore ce
        qu'un conteneur REFERENCE. Un dict de 1,3 million d'entrees pese donc bien plus
        que ce qui est impute a `dict`. Ces chiffres CLASSENT les suspects ; ils ne
        bouclent pas un bilan.
        """
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        import collections as _collections
        import gc as _gc
        import sys as _sys
        import time as _time

        try:
            _budget = min(30.0, max(1.0, float(request.query_params.get("budget", "5"))))
        except Exception:  # noqa: BLE001
            _budget = 5.0
        try:
            _top = min(40, max(5, int(request.query_params.get("top", "20"))))
        except Exception:  # noqa: BLE001
            _top = 20

        _t0 = _time.perf_counter()
        try:
            _objs = _gc.get_objects()
        except Exception as _e:  # noqa: BLE001
            return JSONResponse(
                {"ok": False, "error": "gc.get_objects indisponible: %s" % type(_e).__name__},
                status_code=500)

        _par_type = _collections.Counter()
        _octets = _collections.Counter()
        _total = len(_objs)
        _vus = 0
        _illisibles = 0
        _complet = True
        for _o in _objs:
            if (_vus & 0x3FFF) == 0 and (_time.perf_counter() - _t0) > _budget:
                _complet = False
                break
            _vus += 1
            try:
                _n = type(_o).__name__
                _par_type[_n] += 1
                _nb = getattr(_o, "nbytes", None)
                _octets[_n] += _nb if isinstance(_nb, int) else _sys.getsizeof(_o)
            except Exception:  # noqa: BLE001
                _illisibles += 1
        del _objs

        _res = {
            "ok": True,
            "complet": _complet,
            "budget_s": _budget,
            "duree_s": round(_time.perf_counter() - _t0, 2),
            "objets_vivants": _total,
            "objets_vus": _vus,
            "objets_illisibles": _illisibles,
            "par_nombre": [{"type": _t, "n": _n, "octets_propres": _octets[_t]}
                           for _t, _n in _par_type.most_common(_top)],
            "par_octets": [{"type": _t, "octets_propres": _v, "n": _par_type[_t]}
                           for _t, _v in _octets.most_common(_top)],
            # LIMITE PORTEE PAR LE RESULTAT LUI-MEME (mesure 2026-08-25). `gc.get_objects`
            # ne rend QUE les conteneurs suivis par le ramasse-miettes. Les `str`, les
            # `bytes`, les entiers et les tampons numpy n'y sont pas : le premier relais
            # de cette route a totalise 50 Mo pendant que le process en tenait 6 700.
            # Un chiffre qui ne dit pas ce qu'il ne voit pas se lit comme un bilan.
            # Pour la masse reelle, c'est `tracemalloc` qui repond (champ ci-dessous).
            "limites": "gc.get_objects ne voit que les conteneurs SUIVIS par le GC : "
                       "str/bytes/int et tampons numpy en sont absents. Ces chiffres "
                       "CLASSENT des suspects, ils ne bouclent aucun bilan memoire.",
        }

        # Suspect NOMME par la mesure du 2026-08-25 : le moteur RAG garde un dict par
        # chunk. On le cherche sans le deviner, et on DIT quand on ne le trouve pas.
        # La 1re version ne cherchait que dans `forge_rag_engine` et rendait
        # `trouve: false` — or l'instance est couramment tenue par `forge_context`, pas
        # par son module d'origine. Une sonde qui ne regarde qu'un endroit et rend
        # "pas trouve" fabrique exactement le faux negatif contre lequel elle previent.
        # On balaie donc TOUS les modules charges, et on dit combien on en a vus.
        _res["rag"] = {"trouve": False, "modules_balayes": 0,
                       "note": "aucune instance RAGEngine trouvee — absence de PREUVE, "
                               "pas preuve d'absence"}
        try:
            _mod0 = _sys.modules.get("forge_rag_engine")
            _cls = getattr(_mod0, "RAGEngine", None) if _mod0 is not None else None
            if _cls is None:
                _res["rag"]["note"] = ("forge_rag_engine non importe dans ce process : "
                                       "le moteur n'y vit pas, ou pas sous ce nom")
            else:
                _n_mod = 0
                _trouves = []
                for _mnom, _m in list(_sys.modules.items()):
                    if _m is None:
                        continue
                    _n_mod += 1
                    try:
                        _vars = vars(_m)
                    except Exception:  # noqa: BLE001
                        continue
                    for _nom, _val in list(_vars.items()):
                        if isinstance(_val, _cls) and hasattr(_val, "chunks"):
                            _trouves.append({"module": _mnom, "global": _nom,
                                             "chunks_en_ram": len(_val.chunks)})
                _res["rag"] = {"trouve": bool(_trouves), "modules_balayes": _n_mod,
                               "instances": _trouves[:5]}
                if not _trouves:
                    _res["rag"]["note"] = ("aucune instance sur %d modules balayes — "
                                           "absence de PREUVE, pas preuve d'absence"
                                           % _n_mod)
        except Exception as _e:  # noqa: BLE001
            _res["rag"] = {"trouve": None, "erreur": type(_e).__name__}

        # Sites d'allocation : SEULEMENT si le tracage tourne. tracemalloc ne voit que
        # ce qui suit son start(), donc sans PYTHONTRACEMALLOC pose AVANT le premier
        # import, le pic du BOOT lui echappe entierement.
        try:
            import tracemalloc as _tm

            if _tm.is_tracing():
                _cur, _pic = _tm.get_traced_memory()
                _res["tracemalloc"] = {
                    "actif": True, "suivi_octets": _cur, "pic_octets": _pic,
                    "sites": [{"site": str(_s.traceback), "octets": _s.size, "n": _s.count}
                              for _s in _tm.take_snapshot().statistics("lineno")[:_top]],
                }
            else:
                _res["tracemalloc"] = {
                    "actif": False,
                    "note": "PYTHONTRACEMALLOC absent de l'env du hub (retire le "
                            "2026-08-25, campagne close) : les SITES d'allocation sont "
                            "inconnus, seuls les TYPES le sont. Pour une campagne : "
                            "remettre la cle dans services.toml, restart, relire ici.",
                }
        except Exception as _e:  # noqa: BLE001
            _res["tracemalloc"] = {"actif": None, "erreur": type(_e).__name__}

        return JSONResponse(_res)

    async def admin_job_status(request):
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        job_id = request.path_params.get("job_id", "")
        # MIGRE LE 2026-09-21, en meme temps que la route de lancement : le
        # chemin C:/tmp/nokido_jobs etait code en dur ici, or les jobs n'y sont
        # plus. Mais le gain ne se limite pas au chemin -- `read_job` RECONCILIE
        # et PERSISTE : mesure du 02/08, le statut n'etait corrige qu'en memoire
        # et 51 fiches gardaient « running » alors que leur .rc etait deja sur
        # le disque ; tout ce qui balayait le dossier lisait un registre faux.
        # Il detecte aussi `dead` par le pid (mesure du 21/08 : un job tue par
        # le restart du hub restait « running » a vie) et joint la PROGRESSION,
        # ce que ce lecteur ne faisait ni l'un ni l'autre.
        import sys as _sys_rj
        try:
            _sys_rj.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_job_runner import read_job as _read_job
        except Exception as e:
            return JSONResponse(
                {"ok": False, "error": f"job runner indisponible: {str(e)[:200]}"},
                status_code=500,
            )
        res = _read_job(job_id, tail=4000)
        if res.get("ok"):
            return JSONResponse(res)
        # REPLI HERITAGE, explicite et temporaire : les jobs lances AVANT cette
        # migration vivent encore dans C:/tmp/nokido_jobs. Sans ce repli, migrer
        # le lecteur rendrait INTROUVABLES des jobs qui tournent -- et un job
        # introuvable se lit comme un job qui n'a jamais existe. A retirer quand
        # plus aucun n'y tourne.
        ancien = Path("C:/tmp/nokido_jobs") / f"{job_id}.json"
        if ancien.exists():
            try:
                rec = json.loads(ancien.read_text(encoding="utf-8"))
            except Exception:
                return JSONResponse(
                    {"ok": False, "error": "corrupt job record"}, status_code=500)
            rc_f = Path(rec.get("rc_file", ""))
            log_f = Path(rec.get("log", ""))
            if rc_f.exists():
                rec["status"] = "done"
                try:
                    rec["returncode"] = int(rc_f.read_text(encoding="utf-8").strip() or "-1")
                except Exception:
                    rec["returncode"] = -1
            if log_f.exists():
                try:
                    rec["log_tail"] = log_f.read_text(
                        encoding="utf-8", errors="replace")[-4000:]
                except Exception:
                    rec["log_tail"] = ""
            rec["_source"] = "heritage:C:/tmp/nokido_jobs"
            return JSONResponse({"ok": True, **rec})
        err = str(res.get("error") or "unknown job_id")
        return JSONResponse(
            {"ok": False, "error": err},
            status_code=404 if "unknown" in err or "bad job_id" in err else 500,
        )

    # ─────────────────────────────────────────────────────────────────────
    # FAÇADE LIFECYCLE — Phase 2+5 (2026-05-24)
    # Tous CLI tiers (Gemini, Codex, Claude, Cline) parlent MCP via ce hub
    # :8766 uniquement. Ces routes proxy vers supervisor Deno :8765 (source
    # de vérité unique). + exposition forge_resource_manager pour le gate
    # pre-spawn que le supervisor lui-même consomme (boucle saine).
    # ─────────────────────────────────────────────────────────────────────
    import asyncio as _asyncio
    import urllib.error as _urlerr
    import urllib.request as _urlreq

    _SUPERVISOR_URL = os.environ.get("LAFORGE_SUPERVISOR_URL", "http://127.0.0.1:8765")

    def _sup_call_sync(
        method: str, path: str, timeout: float = 5.0, trace_id: str | None = None
    ) -> dict:
        # Phase 23A : propager bearer token vers Deno supervisor.
        # Phase 29 step 2 : propager traceparent header W3C pour correlation
        # cross-process Python hub <-> Deno supervisor.
        url = _SUPERVISOR_URL.rstrip("/") + path
        _headers = {}
        # 2b-2 (2026-09-28) : jeton superviseur lu au GUICHET d'abord. TRANSITION jusqu'a
        # 2b-7 : le hub HERITE son environnement du superviseur, donc la valeur de
        # l'environnement est celle que le superviseur accepte aujourd'hui. Sur 401 avec
        # la valeur du guichet : UN rejeu avec l'environnement, et la divergence est dite.
        try:
            from nokido_agent.app.forge_secrets import get_secret as _gs_sup

            _sup_guichet = _gs_sup("LAFORGE_SUPERVISOR_TOKEN") or _gs_sup("FORGE_MCP_TOKEN") or ""
        except Exception:  # noqa: BLE001
            _sup_guichet = ""
        _sup_env = (
            os.environ.get("LAFORGE_SUPERVISOR_TOKEN") or os.environ.get("FORGE_MCP_TOKEN") or ""
        )
        _candidats = []
        for _c in (_sup_guichet, _sup_env):
            if _c and _c not in _candidats:
                _candidats.append(_c)
        if trace_id:
            try:
                from nokido_agent.app.forge_audit_log import build_traceparent

                _headers["traceparent"] = build_traceparent(trace_id)
            except Exception:
                pass
        for _rang, _sup_tok in enumerate(_candidats or [""]):
            _h = dict(_headers)
            if _sup_tok:
                _h["Authorization"] = f"Bearer {_sup_tok}"
            req = _urlreq.Request(url, method=method, headers=_h)
            try:
                with _urlreq.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    try:
                        data = json.loads(raw) if raw else {}
                    except Exception:
                        data = {"raw": raw[:500]}
                    return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": data}
            except _urlerr.HTTPError as exc:
                if exc.code == 401 and _rang + 1 < len(_candidats):
                    import logging as _lg_sup

                    _lg_sup.getLogger("forge.hub").warning(
                        "[supervisor] jeton du guichet refuse (401), rejeu avec "
                        "l'environnement -- divergence environnement / guichet (2b-7)")
                    continue
                return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}: {exc.reason}"}
            except Exception as exc:
                return {"ok": False, "status": 0, "error": f"supervisor unreachable: {exc}"}
        return {"ok": False, "status": 0, "error": "supervisor : aucun jeton candidat"}

    async def _sup_call(method: str, path: str, timeout: float = 5.0) -> dict:
        return await _asyncio.get_running_loop().run_in_executor(
            None, _sup_call_sync, method, path, timeout
        )

    async def resource_state(request):
        try:
            from nokido_agent.app.forge_resource_manager import get_snapshot

            snap = get_snapshot()
            return JSONResponse({"ok": True, "snapshot": snap})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)[:200]}, status_code=500)

    async def resource_should_spawn(request):
        # Pre-spawn gate consumed by supervisor.ts. name & essential are passed
        # so we can apply per-service rules later (LLM pool, GPU-touching, ...).
        # 2026-09-24 : identite exigee -- le superviseur porte son jeton propre
        # (`_hubAuthHeaders`) et distingue deja AUTHZ_DENIED d'un hub en panne.
        _refus = _exiger_identite(request)
        if _refus is not None:
            return _refus
        name = request.query_params.get("name", "")
        essential = request.query_params.get("essential", "false").lower() in ("1", "true", "yes")
        try:
            from nokido_agent.app.forge_resource_manager import get_snapshot, should_throttle

            if essential:
                return JSONResponse(
                    {"ok": True, "should_spawn": True, "reason": "essential bypass"}
                )
            throttled = should_throttle()
            snap = get_snapshot()
            return JSONResponse(
                {
                    "ok": True,
                    "should_spawn": not throttled,
                    "reason": "throttled" if throttled else "ok",
                    "service": name,
                    "ram_pct": snap.get("ram_pct"),
                    "cpu_pct": snap.get("cpu_pct"),
                    "gpu_pct": snap.get("gpu_pct"),
                    "tdr_recent": snap.get("tdr_recent"),
                }
            )
        except Exception as exc:
            # fail-open — never block supervisor on a hub bug
            return JSONResponse(
                {
                    "ok": True,
                    "should_spawn": True,
                    "reason": f"gate error fail-open: {str(exc)[:120]}",
                }
            )

    async def resource_request(request):
        # DELEGATION (owner 2026-09-28). Un processus hors du hub DECLARE un besoin de RAM ;
        # le hub, qui tient deja le controle du superviseur, choisit quoi rendre. Identite
        # d'organe exigee -- la voie en place, jamais un porteur de plus. La decision et ses
        # bornes (ring <= 3 pour evincer, refractaire, verrou, 403/429 RFC) vivent dans
        # `decider_demande_deleguee`, executee HORS de la boucle : l'echelle d'eviction dort
        # et fait des E/S bloquantes.
        _refus = _exiger_identite(request)
        if _refus is not None:
            return _refus
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": "invalid_request",
                                 "detail": "corps JSON attendu"}, status_code=400)
        try:
            from nokido_agent.app.forge_resource_manager import decider_demande_deleguee

            statut, data, entetes = await _asyncio.get_running_loop().run_in_executor(
                None, decider_demande_deleguee, request.state.principal,
                int(request.state.ring), corps)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": "internal", "detail": str(exc)[:200]},
                                status_code=500)
        return JSONResponse(data, status_code=statut, headers=entetes or None)

    async def services_list(request):
        _refus = _exiger_identite(request)
        if _refus is not None:
            return _refus
        r = await _sup_call("GET", "/supervisor/status")
        return JSONResponse(r)

    async def services_start(request):
        # Phase 23A enforce + Phase 23C scope JWT
        if not _admin_tok_ok(request, required_scope="services:start"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        name = request.path_params.get("name", "").strip()
        if not name:
            return JSONResponse({"ok": False, "error": "name required"}, status_code=400)
        r = await _sup_call("POST", f"/supervisor/wake/{name}")
        return JSONResponse(r, status_code=200 if r["ok"] else 502)

    async def services_stop(request):
        if not _admin_tok_ok(request, required_scope="services:stop"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        name = request.path_params.get("name", "").strip()
        if not name:
            return JSONResponse({"ok": False, "error": "name required"}, status_code=400)
        r = await _sup_call("POST", f"/supervisor/sleep/{name}")
        return JSONResponse(r, status_code=200 if r["ok"] else 502)

    async def services_restart(request):
        if not _admin_tok_ok(request, required_scope="services:restart"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        name = request.path_params.get("name", "").strip()
        if not name:
            return JSONResponse({"ok": False, "error": "name required"}, status_code=400)
        r = await _sup_call("POST", f"/supervisor/restart/{name}")
        return JSONResponse(r, status_code=200 if r["ok"] else 502)

    async def services_shutdown_all(request):
        if not _admin_tok_ok(request, required_scope="admin:shutdown_all"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        r = await _sup_call("POST", "/supervisor/shutdown")
        return JSONResponse(r, status_code=200 if r["ok"] else 502)

    async def services_boot_all(request):
        if not _admin_tok_ok(request, required_scope="admin:boot_all"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        st = await _sup_call("GET", "/supervisor/status")
        if not st["ok"]:
            return JSONResponse(st, status_code=502)
        services = (st.get("data") or {}).get("services", {})
        woken = []
        for name, info in services.items():
            if info.get("status") == "sleeping":
                rw = await _sup_call("POST", f"/supervisor/wake/{name}")
                woken.append({"name": name, "ok": rw["ok"]})
        return JSONResponse({"ok": True, "woken": woken})

    async def sandbox_spawn(request):
        """Phase 28 — Docker sandbox container isolation strict (NANO-inspired + user design).
        Admin token + scope sandbox:spawn requis. Limites materielles fixees.
        Body : {language_runtime: enum, code_to_execute: str, timeout_s: int 1-60}."""
        if not _admin_tok_ok(request, required_scope="sandbox:spawn"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        runtime = str(body.get("language_runtime", ""))
        code = str(body.get("code_to_execute", ""))
        timeout_s = int(body.get("timeout_s", 10))
        try:
            from nokido_agent.app.forge_docker_sandbox import SandboxError, spawn_sandbox
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": f"forge_docker_sandbox import: {exc}"},
                status_code=500,
            )

        def _do():
            try:
                return spawn_sandbox(runtime, code, timeout_s)
            except SandboxError as e:
                return {"success": False, "error": str(e)}

        res = await _asyncio.get_running_loop().run_in_executor(None, _do)
        return JSONResponse(res, status_code=200 if res.get("success") else 400)

    async def audit_recent(request):
        """Phase 29 — query audit log recent events. Admin scope ou ring 0."""
        if not _admin_tok_ok(request, required_scope="audit:read"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        try:
            from nokido_agent.app.forge_audit_log import query_recent
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"import: {exc}"}, status_code=500)
        verbose = request.query_params.get("verbose") == "1"
        try:
            limit = int(request.query_params.get("limit", "100"))
        except ValueError:
            limit = 100
        trace_id = request.query_params.get("trace_id")
        agent = request.query_params.get("agent")
        rows = await _asyncio.get_running_loop().run_in_executor(
            None,
            lambda: query_recent(limit=limit, trace_id=trace_id, agent=agent, verbose=verbose),
        )
        return JSONResponse({"ok": True, "count": len(rows), "events": rows})

    async def audit_trace(request):
        """Phase 29 — query events d'une trace specifique."""
        if not _admin_tok_ok(request, required_scope="audit:read"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        from nokido_agent.app.forge_audit_log import query_recent

        tid = request.path_params.get("trace_id", "")
        rows = await _asyncio.get_running_loop().run_in_executor(
            None,
            lambda: query_recent(limit=500, trace_id=tid),
        )
        return JSONResponse({"ok": True, "trace_id": tid, "count": len(rows), "events": rows})

    async def ring_buffer_stats(request):
        """Phase 37 — stats ring buffer rewind (RAM volatile)."""
        if not _admin_tok_ok(request, required_scope="audit:read"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        try:
            from nokido_agent.app.forge_ring_buffer import stats as _rb_stats

            return JSONResponse({"ok": True, **_rb_stats()})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    async def sandbox_runtimes(request):
        """GET liste runtimes whitelistes (pas d'auth, read-only)."""
        try:
            from nokido_agent.app.forge_docker_sandbox import list_allowed_runtimes

            return JSONResponse({"ok": True, "runtimes": list_allowed_runtimes()})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    async def maintenance_gc(request):
        """Phase 11 — glymphatic GC. Admin token requis. Lourd (VACUUM DB), idealement
        appele sur phase NREM3 par supervisor.ts circadianLoop."""
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            from nokido_agent.app.forge_glymphatic_gc import run_gc
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"import: {exc}"}, status_code=500)

        def _do():
            # Phase 17 patch a deja remplace VACUUM full par wal_checkpoint+
            # incremental_vacuum (non-bloquant readers). vacuum=True ici est
            # donc deja safe par construction. Plan-SPOF critique resolue
            # structurellement, pas via flag conditionnel.
            return run_gc(
                vacuum=bool(body.get("vacuum", True)),
                rotate=bool(body.get("rotate", True)),
                caches=bool(body.get("caches", True)),
                hormone=bool(body.get("hormone", True)),
            )

        res = await _asyncio.get_running_loop().run_in_executor(None, _do)
        return JSONResponse(res)

    async def hormones_release(request):
        # PORTEUR EXIGE -- 2026-09-21. Injecte un signal endocrinien : un
        # appelant anonyme pouvait influencer la regulation du corps. Aucun
        # appelant HTTP au depot.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        try:
            from nokido_agent.app.forge_hormones import release as _hrel
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"import: {exc}"}, status_code=500)
        try:
            body = await request.json()
        except Exception:
            body = {}
        h = str(body.get("hormone", "")).strip()
        level = float(body.get("level", 1.0))
        payload = body.get("payload") or {}
        receptors = body.get("receptors") or []
        r = _hrel(h, level=level, payload=payload, receptors=receptors)
        return JSONResponse(r, status_code=200 if r.get("ok") else 400)

    async def hormones_active(request):
        try:
            from nokido_agent.app.forge_hormones import active as _hact
            from nokido_agent.app.forge_hormones import system_state
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"import: {exc}"}, status_code=500)
        h = request.query_params.get("hormone")
        if h:
            return JSONResponse({"ok": True, "active": _hact(h)})
        return JSONResponse({"ok": True, "state": system_state(), "active": _hact()})

    async def hormones_receptors(request):
        try:
            from nokido_agent.app.forge_hormones import receptors_for
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"import: {exc}"}, status_code=500)
        role = request.path_params.get("role", "")
        return JSONResponse({"ok": True, "role": role, "active": receptors_for(role)})

    async def hormones_stream(request):
        """Phase 12 SSE event-driven. Push chaque release() en temps reel.
        Keep-alive : ping toutes 15s pour eviter coupure proxy/NAT.
        Drop-oldest si queue subscriber saturee (events idempotents).
        """
        from starlette.responses import StreamingResponse

        try:
            from nokido_agent.app.forge_hormones import subscribe_event_queue, unsubscribe
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"import: {exc}"}, status_code=500)
        q = subscribe_event_queue()
        client_id = request.headers.get("x-client-id", "anon")
        logger.info("hormones_stream subscribed client=%s", client_id)

        async def event_gen():
            try:
                yield f'event: connected\ndata: {{"client":"{client_id}"}}\n\n'
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        rec = await _asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"event: hormone\ndata: {json.dumps(rec, default=str)}\n\n"
                    except TimeoutError:
                        # keep-alive ping (commentaire SSE)
                        yield ": ping\n\n"
                    except Exception as inner:
                        logger.warning("hormones_stream inner err: %s", inner)
                        break
            finally:
                unsubscribe(q)
                logger.info("hormones_stream unsubscribed client=%s", client_id)

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    async def graph_proprioception(request):
        """Phase 8 Hippocampe — voisinage AST code↔code pour un fichier.
        Query params: file=<path relative to Nokido root>, depth=<1|2|3>.
        Si file absent : summary de l'index (size, age).
        """
        try:
            from nokido_agent.app.forge_ast_index import ego, get_index, summary
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": f"forge_ast_index import failed: {exc}"},
                status_code=500,
            )
        file = request.query_params.get("file", "").strip()
        depth_s = request.query_params.get("depth", "2")
        rebuild = request.query_params.get("rebuild", "").lower() in ("1", "true", "yes")
        try:
            depth = int(depth_s)
        except ValueError:
            depth = 2
        if rebuild:
            await _asyncio.get_running_loop().run_in_executor(
                None, lambda: get_index(force_rebuild=True)
            )
        if not file:
            data = await _asyncio.get_running_loop().run_in_executor(None, summary)
            return JSONResponse({"ok": True, "summary": data})
        data = await _asyncio.get_running_loop().run_in_executor(None, lambda: ego(file, depth))
        return JSONResponse(data)

    async def services_logs(request):
        # Phase 23A : enforce auth (logs peuvent contenir secrets/PII)
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        from starlette.responses import Response as _Resp

        name = request.path_params.get("name", "").strip()
        if not name:
            return JSONResponse({"ok": False, "error": "name required"}, status_code=400)
        url = _SUPERVISOR_URL.rstrip("/") + f"/supervisor/logs?name={name}"
        _sup_tok = (
            os.environ.get("LAFORGE_SUPERVISOR_TOKEN") or os.environ.get("FORGE_MCP_TOKEN") or ""
        )
        _req_logs = _urlreq.Request(url)
        if _sup_tok:
            _req_logs.add_header("Authorization", f"Bearer {_sup_tok}")

        def _get():
            try:
                with _urlreq.urlopen(_req_logs, timeout=5.0) as resp:
                    return resp.status, resp.read().decode("utf-8", "replace")
            except Exception as exc:
                return 502, f"supervisor unreachable: {exc}"

        status, body = await _asyncio.get_running_loop().run_in_executor(None, _get)
        return _Resp(body, status_code=status, media_type="text/plain; charset=utf-8")

    # ─────────────────────────────────────────────────────────────────────
    # PRESSURE-RELIEF — Phase 6 (réflexe + soupape de sûreté hydraulique)
    # Limite stricte du nombre de requêtes simultanées traitées par le hub.
    # Au-delà : 429 Retry-After. Évite l'effondrement quand un client en
    # cascade ouvre 1000 connexions → hub mange tout son event-loop.
    # Whitelist : /health, /api/resource/state, /api/services/list = toujours
    # servis pour ne pas aveugler le monitoring sous pression.
    # ─────────────────────────────────────────────────────────────────────
    from starlette.middleware.base import BaseHTTPMiddleware

    _MAX_INFLIGHT = int(os.environ.get("LAFORGE_HUB_MAX_INFLIGHT", "200"))
    _SHED_WHITELIST = {
        "/health",
        "/api/resource/state",
        "/api/services/list",
        "/supervisor/status",
    }

    class _PressureReliefMW(BaseHTTPMiddleware):
        inflight = 0
        rejected_total = 0

        async def dispatch(self, request, call_next):
            cls = type(self)
            # `scope["path"]` et non `request.url.path` : l'URL est fabriquee avec
            # l'en-tete Host (CVE-2026-48710) ; une decision ne la lit jamais.
            path = request.scope["path"]
            if path not in _SHED_WHITELIST and cls.inflight >= _MAX_INFLIGHT:
                cls.rejected_total += 1
                return JSONResponse(
                    {
                        "error": "server_overloaded",
                        "in_flight": cls.inflight,
                        "max_in_flight": _MAX_INFLIGHT,
                        "rejected_total": cls.rejected_total,
                        "hint": "back off and retry",
                    },
                    status_code=429,
                    headers={"Retry-After": "1"},
                )
            cls.inflight += 1
            try:
                return await call_next(request)
            finally:
                cls.inflight -= 1

    # Provider admin UI routes (page HTMX + API CRUD vault) — branchées côté app.
    try:
        from nokido_agent.app.forge_provider_admin import get_starlette_routes as _provider_admin_routes

        _PROVIDER_ADMIN_ROUTES = _provider_admin_routes()
    except Exception as _pa_exc:
        logger.warning(f"forge_provider_admin load failed: {_pa_exc}")
        _PROVIDER_ADMIN_ROUTES = []

    # ── GUI réattribution ring LIVE (#10) — loopback + écriture ring-0 gated ─────
    async def rings_ui(request: Request):
        ch = (request.client.host if request.client else "") or ""
        if ch not in ("127.0.0.1", "::1", "localhost"):
            return JSONResponse({"error": "localhost only"}, status_code=403)
        _ring, _ = _resolve_ring(request)
        try:
            from nokido_agent.app.forge_ring_admin import render_page

            return HTMLResponse(render_page(caller_ring=_ring))
        except Exception as _e:
            return JSONResponse({"error": str(_e)}, status_code=500)

    async def rings_set(request: Request):
        ch = (request.client.host if request.client else "") or ""
        if ch not in ("127.0.0.1", "::1", "localhost"):
            return JSONResponse({"error": "localhost only"}, status_code=403)
        _ring, _agent = _resolve_ring(request)
        try:
            _body = await request.json()
        except Exception:
            _body = {}
        try:
            from nokido_agent.app.forge_ring_admin import set_ring

            _res = set_ring(_body.get("agent", ""), _body.get("ring", 99),
                            caller_ring=_ring, caller_agent=_agent)
            return JSONResponse(_res, status_code=200 if _res.get("ok") else 403)
        except Exception as _e:
            return JSONResponse({"ok": False, "error": str(_e)}, status_code=500)

    app = Starlette(
        routes=[
            Route("/.well-known/{wk_path:path}", oauth_discovery, methods=["GET"]),
            Route("/mcp/.well-known/{wk_path:path}", oauth_discovery, methods=["GET"]),
            Route("/admin/restart", admin_restart, methods=["POST"]),
            Route("/admin/ingest_repo", admin_ingest_repo, methods=["POST"]),
            Route("/admin/run_job", admin_run_job, methods=["POST"]),
            Route("/admin/job/{job_id}", admin_job_status, methods=["GET"]),
            Route("/admin/heap", admin_heap, methods=["GET"]),
        Route("/admin/job/{job_id}/stop", admin_job_stop, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
            # F1 : noms STANDARD attendus par les orchestrateurs. `/health` seul
            # melangeait les deux notions et rendait `ok` quoi qu'il arrive.
            Route("/health/liveness", health_liveness, methods=["GET"]),
            Route("/health/readiness", health_readiness, methods=["GET"]),
            Route("/debug/stacks", debug_stacks, methods=["GET"]),
            Route("/orchestrate/loop", orchestrate_loop, methods=["POST"]),
            Route("/api/swarm/health", swarm_health, methods=["GET"]),
            Route("/api/loops/status", loops_status, methods=["GET"]),
            Route("/mcp", mcp_post, methods=["POST"]),
            Route("/mcp", mcp_get, methods=["GET"]),
            Route("/", hub_index, methods=["GET"]),
            Route("/forge/rag", rag_ui, methods=["GET"]),
            Route("/forge/debate", debate_ui, methods=["GET"]),
            Route("/forge/graph", graph_viz_ui, methods=["GET"]),
            Route("/forge/swarm", swarm_ui, methods=["GET"]),
            Route("/forge/postal", postal_ui, methods=["GET"]),
            Route("/api/organs", organs_ep, methods=["GET"]),
            Route("/api/agents", agents_ep, methods=["GET"]),
            Route("/static/{fname}", static_serve, methods=["GET"]),
            Route("/static/fonts/{fname}", static_fonts_serve, methods=["GET"]),
            Route("/favicon.ico", favicon_serve, methods=["GET"]),
            Route("/forge/recon", recon_demo_ui, methods=["GET"]),
            Route("/forge/rag-stream", rag_stream_ui, methods=["GET"]),
            Route("/api/rag/stats", rag_stats, methods=["GET"]),
            Route("/api/rag/tokenize", rag_tokenize, methods=["POST"]),
            Route("/api/rag/stream", rag_stream, methods=["GET"]),
            Route("/forge/network", network_ui, methods=["GET"]),
            Route("/forge/rings", rings_ui, methods=["GET"]),
            Route("/api/rings/set", rings_set, methods=["POST"]),
            Route("/api/network/stream", network_stream, methods=["GET"]),
            Route("/api/swarm/stream", swarm_stream, methods=["GET"]),
            Route("/api/swarm/run", swarm_run, methods=["POST"]),
            Route("/api/recon/run", recon_run, methods=["POST"]),
            Route("/api/ctf/run", ctf_run, methods=["POST"]),
            Route("/api/network/history", network_history, methods=["GET"]),
            Route("/api/network/mood", network_mood, methods=["GET"]),
            Route("/api/mcp/servers", mcp_config_get, methods=["GET"]),
            Route("/api/mcp/toggle", mcp_config_toggle, methods=["POST"]),
            Route("/api/mcp/flags", _garde_ui(mcp_config_flags, "config:mcp_flags"), methods=["POST"]),
            Route("/forge/watch", watch_ui, methods=["GET"]),
            Route("/api/watch/jobs", watch_jobs_api, methods=["GET"]),
            Route("/api/watch/create", _garde_ui(watch_create_api, "veille:creer"), methods=["POST"]),
            Route("/api/watch/stream", watch_stream_api, methods=["GET"]),
            Route("/api/push", inbox_push, methods=["POST"]),
            Route("/api/login", auth_login, methods=["POST"]),
            Route("/api/login/renouveler", auth_login_renouveler, methods=["POST"]),
            Route("/inbox/{agent_id}", inbox_stream, methods=["GET"]),
            Route("/inbox/status", inbox_status, methods=["GET"]),
            Route("/ingest/url", ingest_url, methods=["POST", "OPTIONS"]),
            Route("/ingest/bulk", ingest_bulk, methods=["POST", "OPTIONS"]),
            Route("/ingest/qualify", ingest_qualify, methods=["POST", "OPTIONS"]),
            Route("/api/ingest", api_ingest, methods=["POST", "OPTIONS"]),
            Route("/gui/sidebar", sidebar_ui, methods=["GET"]),
            Route("/api/graph/stats", graph_stats_api, methods=["GET"]),
            Route("/nervous_system/emit", nervous_emit, methods=["POST"]),
            Route("/mcp/batch", mcp_batch, methods=["POST"]),
            Route("/ui/generate", _garde_ui(ui_generate, "ui:generer"), methods=["POST"]),
            Route("/ui/components", ui_components, methods=["GET"]),
            Route("/ui/{component_id}", ui_serve, methods=["GET"]),
            Route("/mpc/plan", mpc_plan, methods=["POST"]),
            # Façade lifecycle (Phase 2+5) — proxy unifié vers supervisor :8765
            Route("/api/resource/state", resource_state, methods=["GET"]),
            Route("/api/resource/should_spawn", resource_should_spawn, methods=["GET"]),
            Route("/api/resource/request", resource_request, methods=["POST"]),
            Route("/api/services/list", services_list, methods=["GET"]),
            Route("/api/services/start/{name}", services_start, methods=["POST"]),
            Route("/api/services/stop/{name}", services_stop, methods=["POST"]),
            Route("/api/services/restart/{name}", services_restart, methods=["POST"]),
            Route("/api/services/shutdown_all", services_shutdown_all, methods=["POST"]),
            Route("/api/services/boot_all", services_boot_all, methods=["POST"]),
            Route("/api/services/logs/{name}", services_logs, methods=["GET"]),
            # Phase 8 Hippocampe — proprioception code AST
            Route("/api/graph/proprioception", graph_proprioception, methods=["GET"]),
            # Phase 9 Système endocrinien typé
            Route("/api/hormones/release", hormones_release, methods=["POST"]),
            Route("/api/hormones/active", hormones_active, methods=["GET"]),
            Route("/api/hormones/receptors/{role}", hormones_receptors, methods=["GET"]),
            # Phase 12 — SSE event-driven (consumer recv bloquant, zero polling)
            Route("/api/hormones/stream", hormones_stream, methods=["GET"]),
            # Phase 11 — glymphatic maintenance GC (admin token, lourd)
            Route("/api/maintenance/gc", maintenance_gc, methods=["POST"]),
            # Phase 28 — Docker sandbox isolation strict (NANO-inspired)
            Route("/api/sandbox/spawn", sandbox_spawn, methods=["POST"]),
            Route("/api/sandbox/runtimes", sandbox_runtimes, methods=["GET"]),
            # Phase 29 — audit log + trace ID W3C
            Route("/api/audit/recent", audit_recent, methods=["GET"]),
            Route("/api/audit/trace/{trace_id}", audit_trace, methods=["GET"]),
            # Phase 37 — ring buffer rewind (NANO-inspired)
            Route("/api/ring_buffer/stats", ring_buffer_stats, methods=["GET"]),
            # LLM provider admin (vault-backed key management) — public release UX
            *_PROVIDER_ADMIN_ROUTES,
        ],
        exception_handlers={
            404: lambda req, exc: JSONResponse(
                {"error": "not_found", "path": req.scope.get("path", "")},
                status_code=404,
            ),
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:8766",
            "http://localhost:8766",
            "app://obsidian.md",
            "null",
            "*",
        ],
        allow_headers=["*"],
        allow_methods=["*"],
        allow_credentials=False,
    )
    app.add_middleware(_PressureReliefMW)

    # -- OBSERVATION D'AUTORISATION (SHADOW) -------------------------------
    # Mesure du 2026-09-02 : sur 81 routes declarees, 41 sondables en GET, dont
    # 32 repondent 200 SANS jeton (3 sensibles). `:8766` n'a aucun middleware
    # d'authentification -- l'identite n'est resolue que dans les handlers qui
    # pensent a le faire. Avant d'armer un refus, il faut savoir QUI appelle :
    # `/api/resource/should_spawn` est appelee par le superviseur lui-meme, et
    # la refuser a l'aveugle couperait la regulation du corps.
    #
    # Ce middleware ne refuse RIEN. Il reutilise `_resolve_ring` (donc le
    # CapabilityToken puis `forge_videur`) : aucun second systeme d'identite.
    class _AuthzShadowMW(BaseHTTPMiddleware):
        """Journalise la decision qu'un enforcement RENDRAIT. Ne bloque jamais."""

        echecs = 0          # un observateur muet qui se croit actif est pire que rien

        async def dispatch(self, request, call_next):
            try:
                from nokido_agent.app import forge_authz_shadow as _az

                if _az.actif():
                    try:
                        _ring, _agent = _resolve_ring(request)
                    except Exception as _re:      # identite illisible != identite absente
                        _ring, _agent = -1, "resolve_error:%s" % type(_re).__name__
                    _auth = request.headers.get("Authorization", "")
                    # `via` ne recopie JAMAIS le jeton : seulement sa FORME.
                    # `via` doit distinguer le MAITRE du credential DERIVE :
                    # le porteur du maitre peut se declarer n'importe quel agent
                    # et heriter de son ring, le derive non. Avec un `via` calcule
                    # sur la seule FORME de l'en-tete, les deux se lisaient
                    # `bearer` et le journal ne montrait pas les passe-partout.
                    # Le jeton n'est jamais ecrit : on compare, on garde le verdict.
                    if _auth.lower().startswith("bearer "):
                        # Le classement vit dans forge_authz_shadow : le hub
                        # n'injecte que les comparateurs, parce que lui seul
                        # detient les secrets. Le jeton n'est jamais ecrit.
                        #
                        # Le decodeur separe un jeton a bail VERIFIE d'un
                        # jeton de la bonne forme mais REFUSE (expire, revoque,
                        # signature). Sans lui, les deux se lisaient comme un
                        # `bad_token` -- mesure du 2026-09-02.
                        def _est_maitre(_t: str) -> bool:
                            return bool(HUB_TOKEN) and hmac.compare_digest(
                                _t.encode(), HUB_TOKEN.encode())

                        def _est_statique(_t: str) -> bool:
                            return any(
                                hmac.compare_digest(_t.encode(), str(_s).encode())
                                for _s in _AGENT_TOKENS.values() if _s)

                        try:
                            from nokido_agent.app import forge_integrity as _fi

                            _decodeur = _fi.get_manager().decode_raw
                        except Exception:
                            # Pas de verdict possible : `classer_porteur` rendra
                            # `bearer_indecidable`, jamais un faux « inconnu ».
                            _decodeur = None
                        _via = _az.classer_porteur(
                            _auth, est_maitre=_est_maitre,
                            est_statique=_est_statique, decoder=_decodeur)
                    elif (request.headers.get("LaForge-Agent-Name")
                          or request.headers.get("X-Agent-Name")):
                        _via = "header_agent"
                    else:
                        _via = "anonyme"
                    # Decision sur `scope["path"]` (CVE-2026-48710, veille lot_B_33).
                    _verdict = _az.decider(request.scope["path"], _ring, _agent, _via)
                    # Resolution PID seulement quand ca compte : `net_connections`
                    # coute cher, et une route servie sans question n'a rien a
                    # apprendre. Les DENY/UNKNOWN sont exactement les appelants
                    # qu'il faut nommer avant d'armer quoi que ce soit.
                    if _verdict["decision"] == "SHADOW_ALLOW":
                        _qui = {"pid": None, "process": None, "parent_pid": None,
                                "service": None,
                                "raison": "non resolu : decision ALLOW, PID inutile ici"}
                    else:
                        _qui = _az.resoudre_appelant(
                            request.client.port if request.client else None)
                    if not _az.observer(_az.trace_de(
                            request.scope["path"], request.method, _ring, _agent,
                            _via, _qui, verdict=_verdict)):
                        type(self).echecs += 1
            except Exception:  # muet-ok : une OBSERVATION ne casse jamais une requete ; `echecs` porte le compte
                type(self).echecs += 1
            return await call_next(request)

    app.add_middleware(_AuthzShadowMW)

    # Phase 29 step 2 (2026-05-25) — W3C trace context middleware.
    # Extract traceparent header → request.state.trace_id. Log audit
    # entry/exit non-bloquant. Propage header dans response.
    from nokido_agent.app.forge_audit_log import (
        build_traceparent,
        parse_traceparent,
        persist_async,
    )

    class _TraceCtxMW(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            tp_hdr = request.headers.get("traceparent")
            trace_id, parent_id = parse_traceparent(tp_hdr)
            span_id = build_traceparent(trace_id).split("-")[2]
            request.state.trace_id = trace_id
            request.state.parent_id = parent_id
            request.state.span_id = span_id
            try:
                ring, agent = _resolve_ring(request)
            except Exception:
                ring, agent = -1, None
            client_ip = request.client.host if request.client else None
            t0 = time.monotonic()
            status_code = 500
            try:
                response = await call_next(request)
                status_code = response.status_code
                response.headers["traceparent"] = build_traceparent(trace_id, span_id)
                return response
            finally:
                duration_ms = int((time.monotonic() - t0) * 1000)
                try:
                    _asyncio.create_task(
                        persist_async(
                            "http.request",
                            trace_id=trace_id,
                            parent_id=parent_id,
                            agent=agent,
                            target=f"{request.method} {request.scope['path']}",
                            status=status_code,
                            duration_ms=duration_ms,
                            payload=None,
                            ring=ring,
                            client_ip=client_ip,
                        )
                    )
                except Exception:
                    pass

    app.add_middleware(_TraceCtxMW)
    return app


# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬
# TRAY
# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬


def _start_tray():
    try:
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill="#ff9770")
        draw.text((16, 18), "LF", fill="white")

        def _open(icon, item):
            import webbrowser

            webbrowser.open(f"http://{HUB_HOST}:{HUB_PORT}/forge/network")

        def _restart(icon, item):
            import subprocess

            # Golden Rule #10: restart LaForge-Master (it owns + respawns the hub),
            # NEVER `nssm restart NokidoMCP` directly (crash-loop / :8766 port conflict).
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(ROOT / "tools" / "restart_hub.ps1")]
            )

        def _quit(icon, item):
            icon.stop()

        icon = pystray.Icon(
            "Nokido",
            img,
            f"Nokido :{HUB_PORT}",
            menu=pystray.Menu(
                pystray.MenuItem("Ã°Å¸â€œÅ  Network Monitor", _open, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Ã°Å¸â€�â€ž Restart", _restart),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Ã¢Å“â€¢ Quit", _quit),
            ),
        )
        icon.run()
    except ImportError:
        pass  # muet-ok : pystray optionnel, son absence est un choix
    except Exception as e:
        logger.warning(f"Tray: {e}")


# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬
# MAIN
# Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬Ã¢â€�â‚¬


def _warmup_bge_m3() -> None:
    """Preload bge-m3 into Ollama memory so first hybrid_retrieve isn't cold (10s→<1s)."""
    import urllib.request

    try:
        payload = json.dumps({"model": "bge-m3", "prompt": "warmup", "keep_alive": -1}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30):
            pass
        logger.info("bge-m3 warmup OK — modèle chargé en mémoire")
    except Exception as e:
        logger.warning(f"bge-m3 warmup skipped: {e}")


def _boot_emit_to_analysis(ring: int = 0) -> None:
    """Branche la timeline de boot (_BOOT_MARKS) sur le système d'analyse auto
    EXISTANT : forge_startup_logger.boot_step/finalize -> insert RAG monitoring +
    anchor_error -> logs/lessons_learned.md -> forge_auto_evolution_loop scanne et
    PROPOSE des fixes. Une phase > 30s ou un boot total > 60s est marqué erreur ->
    ancré comme lesson = régression boot auto-détectée. Best-effort : ne casse jamais
    le boot (un boot qui hang n'atteint pas finalize -> hub_boot.log reste le trace
    temps-réel/anti-hang complémentaire)."""
    _SLOW_PHASE_S, _SLOW_BOOT_S = 30.0, 60.0
    try:
        from nokido_agent.app.forge_startup_logger import boot_finalize, boot_step

        prev = 0.0
        for phase, el in _BOOT_MARKS:
            dt = el - prev
            prev = el
            slow = dt > _SLOW_PHASE_S
            boot_step(
                name=phase[:48],
                ok=not slow,
                detail=f"+{dt:.1f}s (t={el:.1f}s)",
                error=(f"phase boot lente {dt:.0f}s (>{_SLOW_PHASE_S:.0f}s)" if slow else ""),
            )
        total = _BOOT_MARKS[-1][1] if _BOOT_MARKS else 0.0
        if total > _SLOW_BOOT_S:
            boot_step(
                name="boot_total",
                ok=False,
                detail=f"{total:.0f}s",
                error=f"boot hub lent {total:.0f}s (>{_SLOW_BOOT_S:.0f}s) — voir phases ci-dessus",
            )
        # Contexte topologie au boot-ready : dépendances serveur (%NOKIDO_DATA%\RAG, ollama,
        # docker) pour corréler une régression de boot OU un reboot avant montage V:.
        # Probes cheap. (Les CLIs/Desktop/VSCode/Gemini = clients runtime, connectés
        # APRÈS le boot -> suivis par le network_log/agents_online, pas ici.)
        try:
            import socket as _sk

            def _up(port, t=0.2):
                try:
                    _c = _sk.create_connection(("127.0.0.1", port), t)
                    _c.close()
                    return True
                except Exception:
                    return False

            _db_ok = os.path.exists(str(DB))
            _docker_ok = os.path.exists(r"\\.\pipe\docker_engine")
            _ollama_ok = _up(11434)
            boot_step(
                name="env_deps",
                ok=_db_ok,
                detail=f"%NOKIDO_DATA%\RAG={'up' if _db_ok else 'DOWN'} ollama={'up' if _ollama_ok else 'down'} docker={'up' if _docker_ok else 'down'}",
                error=("" if _db_ok else "%NOKIDO_DATA%\RAG indisponible au boot (volume chiffré non monté ? reboot avant mount)"),
            )
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("forge.hub").warning(
                "[boot] rapport d'analyse NON emis (%s: %s) | consequence: ce demarrage "
                "n'apparaitra pas dans l'historique de boot, et son absence se lira "
                "comme un boot qui n'a pas eu lieu", type(e).__name__, str(e)[:80])
        boot_finalize(ring=ring)
        logger.info(f"[boot] timeline -> forge_startup_logger ({len(_BOOT_MARKS)} phases -> analyse auto)")
    except Exception as _e:
        logger.debug(f"[boot] emit_to_analysis skip: {_e}")


async def main():
    import uvicorn

    # Timeline CONTINUE depuis le debut du process (cf _boot_probe module-level) —
    # pas un reset, sinon on perd le coût des imports qui precedent main().
    _boot_mark = _boot_probe
    _boot_mark("main() start (asyncio entre)")
    _init_network_log()
    _boot_mark("network_log init")
    app = await _build_app()
    _boot_mark("_build_app() RETOUR -> app prete")
    # Sentinelle lag event-loop (souverain py-spy in-process) : traque les
    # wrappers bloquants qui gèlent la boucle -> dump stack dans logs/loop_lag.log.
    try:
        from nokido_agent.app.forge_loop_sentinel import start as _loop_sentinel_start
        from nokido_agent.app.forge_loop_sentinel import start_kill_watchdog as _loop_kill_start

        _loop_sentinel_start(threshold_ms=300)
        # EFFECTEUR, enfin arme. `start_kill_watchdog` existait — thread OS dedie,
        # grace suspend/resume, opt-out LAFORGE_LOOP_KILL_S=0 — et n'etait appele
        # NULLE PART : le hub n'importait que l'observateur. D'ou des WARNING a
        # 19 760 ms sans que rien n'agisse. Un process supervise qu'on tue
        # proprement est respawne ; un hub gele emporte toutes les surfaces.
        # SEUIL = defaut du module (60 s), PAS 15. Mesure 2026-09-05 sur les 22
        # kills de logs/loop_lag.log : a 15 s, 16 kills en 2 jours, TOUS
        # "gele 16-17 s" ; a 60 s, 6 kills en 4 jours, tous de vrais wedges.
        # Cause des 16 s : handle_notify ecrit agent_messages dans embeddings.db
        # EN SYNCHRONE dans le loop avec busy_timeout=15000 (forge_mcp_registry,
        # INSERT ~L4571) : un verrou tenu par un autre ecrivain = 15 s d'attente,
        # et le kill a 15 s transforme cette attente en boucle respawn -> prewarm
        # (scan 24,9 Go) -> disque sature -> verrous plus longs -> kill suivant.
        # INVARIANT (NR tests/nr/test_loop_kill_seuil_nr.py) : le seuil de kill
        # reste STRICTEMENT superieur au plus long blocage synchrone tolere.
        _loop_kill_start(kill_after_s=float(os.environ.get("LAFORGE_LOOP_KILL_S", "60")))
        logger.info("[hub] loop-lag sentinel actif (seuil 300ms -> logs/loop_lag.log)")
    except Exception as _e:
        logger.debug(f"[hub] loop sentinel skip: {_e}")
    _boot_mark("loop sentinel started")

    def _warmup_planner():
        # Charge laforge-qwen au boot (keep_alive) -> 1er plan GOAP plus à froid
        # (sinon >120s -> fast_path -> tools jamais exécutés). Best-effort.
        try:
            from nokido_agent.app.forge_goap import warm as _planner_warm

            if _planner_warm():
                logger.info("[hub] planner LLM (laforge-qwen) préchauffé")
        except Exception as _e:
            logger.debug(f"[hub] planner warmup skip: {_e}")

    threading.Thread(target=_warmup_planner, daemon=True).start()
    threading.Thread(target=_warmup_bge_m3, daemon=True).start()
    _boot_mark("warmup threads launched (planner+bge-m3, async non-bloquant)")
    # Phase 18 (2026-05-24) hardening : assert bind loopback only sauf override
    # explicite via LAFORGE_HUB_BIND_EXTERNAL=1. Critique Plan-SPOF agent :
    # exposition accidentelle = RCE LAN si admin_tok vide.
    if HUB_HOST not in ("127.0.0.1", "::1", "localhost"):
        _allow_external = os.environ.get("LAFORGE_HUB_BIND_EXTERNAL", "0") == "1"
        if not _allow_external:
            logger.critical(
                f"HUB_HOST={HUB_HOST} non-loopback REFUSE (set LAFORGE_HUB_BIND_EXTERNAL=1 pour override). Fallback 127.0.0.1."
            )
            HUB_HOST_BIND = "127.0.0.1"
        else:
            logger.warning(f"HUB_HOST={HUB_HOST} expose non-loopback (LAFORGE_HUB_BIND_EXTERNAL=1)")
            HUB_HOST_BIND = HUB_HOST
    else:
        HUB_HOST_BIND = HUB_HOST
    logger.info(
        f"Nokido Hub v18.3 sur {HUB_HOST_BIND}:{HUB_PORT} (Nokido.env: {_LAFORGE_ENV_LOADED} vars)"
    )
    logger.info(f"  Network Monitor : http://{HUB_HOST}:{HUB_PORT}/forge/network")
    # GARDE D'EXPOSITION (2026-09-02). Le controle de HUB_HOST plus haut porte sur
    # l'INTENTION. Trois chemins exposent un port sans jamais y toucher : un
    # mapping de conteneur, un proxy place devant, un socket herite d'un parent.
    # On constate donc l'EFFET, en differe pour laisser uvicorn bind d'abord.
    # Il CRIE, il n'arrete pas : un garde qui tue le control-plane transforme une
    # exposition possible en indisponibilite certaine.
    def _controle_exposition():
        try:
            import time as _t

            _t.sleep(8)
            from nokido_agent.app.forge_bind_guard import controler as _ctrl

            _ctrl(HUB_PORT, logger)
        except Exception as _e:  # noqa: BLE001  # muet-ok : jamais bloquant au boot
            logger.debug(f"[bind_guard] non execute: {_e}")

    threading.Thread(target=_controle_exposition, daemon=True).start()

    if os.environ.get("SESSIONNAME"):
        threading.Thread(target=_start_tray, daemon=True).start()
    else:
        logger.info("Tray desactive - service sans bureau")
    _base_kwargs = dict(
        log_level="warning",
        timeout_keep_alive=120,  # keepalive HTTP longue (SSE + outils lents Ollama)
        timeout_graceful_shutdown=30,
        limit_concurrency=64,
        h11_max_incomplete_event_size=1048576,  # 1MB — payloads RAG
    )
    # DUAL-LISTEN non-cassant : HTTP reste TOUJOURS sur HUB_PORT (clients
    # existants Claude Desktop/Gemini/Cline/bridges inchanges). Si des certs TLS
    # sont fournis, on AJOUTE un listener HTTPS sur un port DISTINCT
    # (LAFORGE_HUB_TLS_PORT, def 8443) — aucun client casse, migration https opt-in.
    async def _serve_guarded(srv, label):
        # Un listener qui meurt (ex: cert TLS invalide) ne doit PAS tuer l'autre.
        try:
            await srv.serve()
        except Exception as e:
            logger.error(f"[hub] listener {label} arrete: {e}")

    _servers = []  # (uvicorn.Server, label)
    _http_cfg = uvicorn.Config(app, host=HUB_HOST_BIND, port=HUB_PORT, **_base_kwargs)
    _servers.append((uvicorn.Server(_http_cfg), f"http:{HUB_PORT}"))
    logger.info(f"[hub] HTTP loopback on :{HUB_PORT}")
    _tls_cert = os.environ.get("LAFORGE_HUB_TLS_CERT")
    _tls_key = os.environ.get("LAFORGE_HUB_TLS_KEY")
    if _tls_cert and _tls_key and os.path.isfile(_tls_cert) and os.path.isfile(_tls_key):
        _tls_port = int(os.environ.get("LAFORGE_HUB_TLS_PORT", "8443"))
        _https_cfg = uvicorn.Config(
            app, host=HUB_HOST_BIND, port=_tls_port,
            ssl_certfile=_tls_cert, ssl_keyfile=_tls_key, **_base_kwargs,
        )
        _servers.append((uvicorn.Server(_https_cfg), f"https:{_tls_port}"))
        logger.info(f"[hub] HTTPS (TLS) on :{_tls_port} — cert={_tls_cert}")
    elif _tls_cert or _tls_key:
        logger.warning("[hub] LAFORGE_HUB_TLS_CERT/KEY incomplet — HTTPS non demarre (HTTP seul)")
    _boot_mark(f"pre-serve — uvicorn bind :{HUB_PORT} (boot quasi complet)")
    _boot_emit_to_analysis(ring=0)  # timeline -> forge_startup_logger -> lessons -> evolution loop
    asyncio.create_task(_battement_de_service())
    await asyncio.gather(*(_serve_guarded(s, lbl) for s, lbl in _servers))


async def _battement_de_service(periode_s: float = 60.0) -> None:
    """Pouls PERIODIQUE du hub — la seule trace qui survive a une mort brutale.

    MESURE 2026-08-26. Le superviseur arrete le hub par `proc.kill("SIGTERM")` cote
    Deno. Or **Windows n'a pas de SIGTERM** : Deno le traduit en `TerminateProcess`,
    qui detruit le processus sans qu'une seule ligne de code utilisateur s'execute.
    La sonde de fin ajoutee plus haut (atexit / signal / excepthook) ne peut donc PAS
    parler sur ce chemin — verifie deux fois : deux redemarrages, zero ligne de fin.
    C'est le motif que ce depot connait bien : un garde branche sur un signal que
    personne n'emet.

    Un pouls periodique repond au vrai besoin. Il ne dit pas POURQUOI le hub est mort,
    il dit QUAND il vivait encore — a la minute pres — et c'est ce qui manquait pour
    instruire « hub instable » autrement que par hypotheses.

    En TACHE ASYNCIO et non en thread, volontairement : si la boucle d'evenements gele,
    le battement gele AVEC elle. Un thread continuerait de battre au-dessus d'un hub
    incapable de servir, ce qui est exactement le faux temoin qu'on veut eviter.

    `services.toml` reclamait deja ce battement (`objectif = "emis<600"`, « l'emission
    DIRECTE depuis sa propre boucle reste la cible ») : le contrat existait, l'emetteur
    manquait. Ne leve jamais — un pouls qui tue son porteur serait pire que pas de pouls.
    """
    debut = time.time()
    tours = 0
    while True:
        try:
            await asyncio.sleep(periode_s)
            tours += 1
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from nokido_agent.app.forge_heartbeat import beat_daemon

                beat_daemon("hub", uptime_s=int(time.time() - debut), tours=tours,
                            port=HUB_PORT, health="ok")
            except Exception:  # noqa: BLE001
                pass
            # Trace dans le MEME journal que le boot : la derniere ligne du fichier
            # devient « ou en etait le hub », meme s'il est detruit sans preavis.
            if tours % 10 == 0:      # ~10 min : lisible sans noyer le journal
                _boot_probe("battement +%d tours (uptime %.0f s)"
                            % (tours, time.time() - debut))
        except asyncio.CancelledError:
            _fin_probe("boucle annulee", "(arret propre de l event loop)")
            raise
        except Exception:  # noqa: BLE001
            await asyncio.sleep(periode_s)


if __name__ == "__main__":
    # Fix Windows service : SelectorEventLoop + wait port libre
    import socket
    import time as _t

    # Attendre que le port 8766 soit libre (max 15s)
    # Evite WinError 10048 quand nssm restart trop vite
    for _i in range(15):
        try:
            s = socket.socket()
            s.bind((HUB_HOST, HUB_PORT))
            s.close()
            break  # port libre
        except OSError:
            logger.info(f"Port {HUB_PORT} occupe, attente... ({_i + 1}/15)")
            if _i == 14:
                logger.critical(
                    f"Port {HUB_PORT} toujours occupé après 15s — exit pour éviter accumulation zombies"
                )
                sys.exit(1)
            # Garde anti-coma : sonder /health. Un hub SAIN répond → on sort
            # proprement (instance légitime déjà en place). Un squatteur MUET
            # est un zombie/coma — on le tue par PID, MÊME si c'est un
            # nokido_hub (un hub comateux tient le port sans servir : c'est
            # justement le cas le plus fréquent). L'ancienne garde excluait
            # les nokido_hub → elle protégeait le zombie → deadlock éternel.
            if _i == 3:  # après 3s, décision automatique
                try:
                    import re as _re
                    import subprocess as _sp
                    import urllib.request as _ur2

                    _alive = False
                    try:
                        with _ur2.urlopen(f"http://{HUB_HOST}:{HUB_PORT}/health", timeout=3) as _hr:
                            _alive = _hr.status == 200
                    except Exception:
                        _alive = False
                    if _alive:
                        logger.info(f"Hub sain déjà actif sur :{HUB_PORT} — exit propre")
                        sys.exit(0)
                    _ns = _sp.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace")
                    _pids = set(
                        _re.findall(r":%d\s+\S+\s+LISTENING\s+(\d+)" % HUB_PORT, _ns.stdout)
                    )
                    _self = str(os.getpid())
                    for _pid in _pids:
                        if _pid == _self:
                            continue
                        logger.warning(
                            f"Zombie PID {_pid} squatte :{HUB_PORT} sans répondre à /health — kill"
                        )
                        _sp.run(["taskkill", "/F", "/PID", _pid], capture_output=True)
                except Exception as _ke:
                    logger.debug(f"Garde port: {_ke}")
            _t.sleep(1)
    # MONITOR — vérifier tous les services au démarrage
    try:
        import os as _mo
        import sys as _ms

        _tools = _mo.path.join(_mo.path.dirname(__file__))
        _app = _mo.path.join(_mo.path.dirname(__file__), "..", "app")
        if _tools not in _ms.path:
            _ms.path.insert(0, _tools)
        if _app not in _ms.path:
            _ms.path.insert(0, _app)
        from nokido_agent.tools.forge_rescue import check_all_services

        # DEPORTE 2026-08-20 (mesure jalons) : +2,20 s SYNCHRONES avant le bind du
        # port, pour un scan de diagnostic dont ce bloc ne consomme PAS le
        # resultat (aucune variable, aucun branchement — juste un log de debug si
        # ca casse). Rien ne justifie de retarder l'ouverture de :8766 pour ca.
        import threading as _th

        _th.Thread(target=check_all_services, name="boot-check-services", daemon=True).start()
        _boot_probe("check_all_services LANCE EN FOND (etait +2,2 s bloquantes)")
    except Exception as _me:
        logger.debug(f"[monitor] check_all_services: {_me}")

    # PROVIDER WATCHER — surveillance providers toutes les 5min
    try:
        import os as _pw_os
        import sys as _pw_sys

        _pw_app = _pw_os.path.join(_pw_os.path.dirname(__file__), "..", "app")
        if _pw_app not in _pw_sys.path:
            _pw_sys.path.insert(0, _pw_app)
        from nokido_agent.app.forge_provider_watcher import start as _pw_start

        _pw_start()
        _boot_probe("provider_watcher start")
        logger.info("ProviderWatcher démarré — ping toutes les 5min")
    except Exception as _pwe:
        logger.debug(f"[provider_watcher] skip: {_pwe}")

    # INSPECTOR — monitoring autonome sys/réseau/zombies (toutes les 30s)
    try:
        from nokido_agent.app.forge_inspector import cleanup_now as _ins_cleanup
        from nokido_agent.app.forge_inspector import start as _ins_start

        # DEPORTE 2026-08-20 (mesure jalons) : +2,20 s SYNCHRONES (netstat +
        # taskkill) avant le bind. Le port 8766 est DEJA garanti libre par la
        # boucle d'attente en tete de ce bloc __main__ ; ce cleanup vise les
        # AUTRES ports, il n'a donc aucune raison de retarder notre ouverture.
        # L'ORDRE cleanup -> start reste strictement conserve DANS le thread.
        import threading as _th2

        def _inspector_boot():
            try:
                _c = _ins_cleanup()  # purge zombies au boot
                logger.info(
                    f"Inspector boot cleanup: killed={len(_c.get('killed', []))} "
                    f"ports={_c.get('ports', {})}"
                )
                _ins_start()
                logger.info("Inspector démarré — monitoring sys/réseau/zombies toutes les 30s")
            except Exception as _ie:  # noqa: BLE001
                logger.debug(f"[inspector] thread de boot: {_ie}")

        _th2.Thread(target=_inspector_boot, name="boot-inspector", daemon=True).start()
        _boot_probe("inspector LANCE EN FOND (etait +2,2 s bloquantes)")
    except Exception as _ine:
        logger.debug(f"[inspector] skip: {_ine}")

    # SYSTEM MOOD — système endocrinien (état global diffus, toutes les 60s)
    try:
        import os as _sm_os
        import sys as _sm_sys

        _sm_app = str(_sm_os.path.join(_sm_os.path.dirname(__file__), "..", "app"))
        if _sm_app not in _sm_sys.path:
            _sm_sys.path.insert(0, _sm_app)
        from nokido_agent.app.forge_system_mood import init_db as _mood_db
        from nokido_agent.app.forge_system_mood import start_mood_daemon as _start_mood

        _mood_db()  # crée la table si absente
        _start_mood()
        _boot_probe("system mood (endocrinien) start")
        logger.info("SystemMood daemon démarré — diffusion EventBus toutes les 60s")
    except Exception as _sme:
        logger.debug(f"[system_mood] skip: {_sme}")

    # ACCESS SWITCHES — droits dynamiques ReBAC (init table)
    try:
        from nokido_agent.app.forge_access_switches import init_db as _sw_init

        _sw_init()
        _boot_probe("_sw_init")
        logger.info("AccessSwitches initialisé — table access_switches prête")
    except Exception as _swe:
        logger.debug(f"[access_switches] skip: {_swe}")

    # HYDRATE QUEUES — reconstruction des files après restart (Gemini Ultra 2026-04-28)
    try:
        import os as _hqo
        import sys as _hqs

        _hqapp = str(_hqo.path.join(_hqo.path.dirname(__file__), "..", "app"))
        if _hqapp not in _hqs.path:
            _hqs.path.insert(0, _hqapp)
        from nokido_agent.app.forge_message_frame import hydrate_queues_on_boot as _hydrate

        _hydrated = _hydrate()
        _boot_probe("hydrate")
        logger.info(f"Inbox hydratées au boot: {_hydrated}")
    except Exception as _hqe:
        logger.debug(f"[hydrate_queues] skip: {_hqe}")

    # ZONE AVEUGLE MESUREE 2026-08-20 : les jalons s'arretaient a « module top-level
    # FINI » (+2,0 s) et reprenaient dans main() (+8,4 s). 6,4 s sur 9,4 s de boot,
    # soit 68 %, etaient NON INSTRUMENTES — stable sur 4 boots (6,4 / 5,8 / 6,6 / 6,4).
    # Tout ce bloc __main__ est SYNCHRONE et precede le bind du port : chaque jalon
    # ci-dessus dit desormais lequel de ces demarrages paie les 6,4 s.
    _boot_probe("=== bloc __main__ FINI (tous daemons pre-asyncio) -> event loop ===")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except Exception as _fatal:
        import traceback as _tb

        _crash_log = ROOT / "logs" / "hub_crash.log"
        _crash_log.parent.mkdir(exist_ok=True)
        with open(_crash_log, "a", encoding="utf-8") as _cf:
            _cf.write(f"\n{'=' * 60}\n{_dt.now().isoformat()} FATAL CRASH\n{_tb.format_exc()}\n")
        logger.critical(f"Hub crash fatal: {_fatal} — voir logs/hub_crash.log")
        raise
    finally:
        loop.close()
