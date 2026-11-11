# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-05-18 | VER:v1_task_executor
#FORGE:[score:85|agent:claude-sonnet-4-6|temp:0.00|risk:0.20|ast:OK|test:KO|lint:OK|color:GREEN|attempt:1]

tools/forge_task_executor.py — Daemon executor pour tasks.db
=============================================================

Poll tasks.db WHERE status='pending', dispatche via hub `ask` tool,
écrit résultat + marque completed.

Agents supportés : GEMINI, COHERE, MISTRAL, GROQ, GITHUB, HF, SAMBANOVA,
                   AGT_GEMINI, AGT_GEMINI_FLASH, GEMINI_PRO, GEMINI_FLASH

Fallback provider chain pour GEMINI (OAuth 401) :
  gemini_cli → groq → mistral → cohere

Usage :
  python tools/forge_task_executor.py              # daemon 60s
  python tools/forge_task_executor.py --once       # traite 1 batch puis exit
  python tools/forge_task_executor.py --agent GEMINI --once  # filtre agent
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.forge_context_ledger import ContextLedger

try:  # levier A (23/10) : table unique modele+effort par palier ; paquet d'abord, repli checkout
    from nokido_agent.tools import forge_palier_effort as _palier
except ImportError:  # repli checkout : tools/ dans sys.path
    import forge_palier_effort as _palier

ROOT = Path(__file__).resolve().parent.parent
try:
    (ROOT / "logs").mkdir(exist_ok=True)
except OSError:  # muet-ok : dossier deja la ou non creable sous ce compte ; le FileHandler dira son propre echec
    pass

# Le fichier de log appartient au compte qui fait tourner le service ; un autre
# compte (bac a sable du hub, session owner) ne peut PAS l'ouvrir en ecriture.
# Construit en dur dans handlers=[...], le RotatingFileHandler levait alors un
# PermissionError A L'IMPORT : « import forge_task_executor » echouait tout
# entier, et avec lui toute inspection du module (mesure 24-07 : impossible de
# seulement lire _extract_message depuis le sandbox). Un journal indisponible
# doit degrader la trace, jamais empecher le code de se charger.
_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
try:
    _handlers.append(
        RotatingFileHandler(
            ROOT / "logs" / "task_executor.log", encoding="utf-8", maxBytes=10485760, backupCount=5
        )
    )
except OSError:  # PermissionError inclus — autre compte proprietaire du fichier
    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 70, exc_info=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TaskExec] %(levelname)s %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("TaskExecutor")

SANDBOX = ROOT / "sandbox"
TASKS_DB = SANDBOX / "tasks.db"
HB_FILE = SANDBOX / "task_executor.heartbeat"


def _hb_file(agent_filter: str | None) -> Path:
    """Un heartbeat PAR instance : deux executors qui ecrivent le meme fichier
    se rendent mutuellement invisibles — la mort de l'un serait masquee par la
    vie de l'autre, et le superviseur ne redemarrerait jamais le bon."""
    if not agent_filter:
        return HB_FILE
    slug = "".join(c if c.isalnum() else "_" for c in agent_filter.lower())
    return SANDBOX / f"task_executor_{slug}.heartbeat"


def _pids_enfants() -> list[int]:
    """Pids des processus enfants vivants de cet executeur (psutil.Process(os.getpid()).children(recursive=True))."""
    try:
        import psutil
        return [p.pid for p in psutil.Process(os.getpid()).children(recursive=True)]
    except Exception:
        return []
POLL_INTERVAL = int(os.environ.get("TASK_EXEC_POLL_INTERVAL", "60"))
BATCH_SIZE = int(os.environ.get("TASK_EXEC_BATCH", "5"))

HUB_URL = "http://127.0.0.1:8766"

LAFORGE_TASK_PARALLEL = int(os.environ.get("LAFORGE_TASK_PARALLEL", "2"))
_delegations_en_vol = 0
_lock_delegations = threading.Lock()
_lock_tool_scope = threading.Lock()
_pool_delegations = ThreadPoolExecutor(max_workers=max(1, LAFORGE_TASK_PARALLEL), thread_name_prefix="task_deleg")

_stop = False


def _signal_handler(sig, frame):
    global _stop
    log.info(f"Signal {sig} — arrêt propre")
    _stop = True


def _jeton_de_la_brique() -> str:
    """Jeton COURANT de TASK_EXECUTOR par `forge_agent_credential.jeton_pour` (2026-09-28) :
    injecte ou projete par le lanceur, sinon jeton court echange contre le secret propre, le
    tout renouvele. '' si la brique ne rend rien."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_agent_credential import jeton_pour

        return jeton_pour("TASK_EXECUTOR") or ""
    except Exception:  # noqa: BLE001 -- brique indisponible : le repli d'avant suit
        return ""


def _load_token() -> str:
    # 2026-09-28 : la BRIQUE d'abord (jeton injecte/projete par le lanceur, ou court).
    _brique = _jeton_de_la_brique()
    if _brique:
        return _brique
    # Token PAR-AGENT d'abord (ring2 via _AGENT_TOKENS[TASK_EXECUTOR]) — le master
    # resolvait ring4 -> GATE_DENIED sur ask (mesure 23/07). Provisionne :
    # run trusted_script tools/forge_provision_agent_secret.py TASK_EXECUTOR + restart hub.
    # NOM LIE APRES USAGE (pyflakes 2026-08-20) : `_gs` etait importe ligne ~105,
    # soit APRES cet appel -> NameError a chaque passage. Consequence probable :
    # le token PAR-AGENT n'etait jamais lu, donc retour au master en ring4 et
    # GATE_DENIED sur `ask` — le symptome que le commentaire ci-dessus dit avoir
    # corrige le 23/07 n'a donc jamais pu l'etre par ce chemin.
    try:
        from nokido_agent.app.forge_secrets import get_secret as _gs
    except Exception:  # noqa: BLE001 — repli env, le fallback suit plus bas
        import os as _o

        _gs = _o.environ.get
    _self = _gs("FORGE_TOKEN_TASK_EXECUTOR") or ""
    if _self:
        return _self
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret as _gs  # type: ignore
        _v = _gs("FORGE_TOKEN_TASK_EXECUTOR")
        if _v:
            return _v
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 148, exc_info=True)
    tok = _gs("FORGE_MCP_TOKEN") or ""
    if tok:
        return tok
    # Coffre DPAPI (canonique — doctrine: ne plus se fier au .env). Master token ->
    # X-Agent-Name=TASK_EXECUTOR resout ring 2 (sinon token vide -> floor anti-spoof ring 4
    # -> GATE_DENIED sur ask, l'executor broyait toutes les taches). cf fix b 2026-06-23.
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        v = get_secret("FORGE_MCP_TOKEN")
        if v:
            return v
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 163, exc_info=True)
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("FORGE_MCP_TOKEN=") and not line.startswith("#"):
                return line.split("=", 1)[1].split("#")[0].strip()
    return ""


def _hub_call(tool: str, args: dict, token: str, timeout: int = 120) -> dict:
    # Jeton relu A CHAQUE APPEL (2026-09-28) : `run_loop` le lisait une fois, et un jeton
    # court (30 min) du lanceur y aurait expire. Le `token` passe devient le repli.
    token = _jeton_de_la_brique() or token
    body = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 99999,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    req = urllib.request.Request(
        f"{HUB_URL}/mcp",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Agent-Name": "TASK_EXECUTOR",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": {"message": f"{type(e).__name__}: {e}"}}


def _ask(provider: str, message: str, token: str) -> tuple[bool, str]:
    """Appelle hub ask avec provider. Retourne (ok, text)."""
    resp = _hub_call("ask", {"provider": provider, "message": message}, token, timeout=180)
    if "error" in resp and "result" not in resp:
        return False, f"hub error: {resp['error']}"
    content = resp.get("result", {}).get("content", [{}])
    text = content[0].get("text", "") if content else ""
    try:
        data = json.loads(text)
        if data.get("ok"):
            return True, data.get("text", "")
        return False, data.get("error", "provider error")
    except Exception:
        return bool(text), text


def _ask_local(message: str, model: str = "qwen2.5-coder:7b", timeout: int = 300) -> tuple[bool, str]:
    """LLM LOCAL (ollama :11434) — HORS gate `ask` cloud (décision owner 23/07 :
    l'exécuteur autonome ne touche PAS le cloud ; souverain + gate intention intact).
    Utilisé par le proposeur de code. Retourne (ok, text). timeout=300 : le cold-load
    d'un coder 7b + génération dépasse 180s sur cette machine (mesure 23/07).
    keep_alive garde le modèle résident 30min pour les appels suivants."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
        txt = (resp.get("message", {}) or {}).get("content", "") or ""
        return bool(txt.strip()), txt
    except Exception as e:  # noqa: BLE001
        return False, f"ollama local err: {type(e).__name__}: {e}"


# Mapping agent → providers par ordre de préférence
PROVIDER_CHAIN: dict[str, list[str]] = {
    "GEMINI": ["groq", "mistral", "cohere"],
    "AGT_GEMINI": ["groq", "mistral", "cohere"],
    "GEMINI_PRO": ["groq", "mistral"],
    "AGT_GEMINI_FLASH": ["groq", "mistral", "cohere"],
    "GEMINI_FLASH": ["groq", "mistral"],
    "COHERE": ["cohere", "mistral", "groq"],
    "MISTRAL": ["mistral", "groq", "cohere"],
    "GROQ": ["groq", "mistral", "cohere"],
    "GITHUB": ["github", "groq", "mistral"],
    "AGT_GPT4O_GITHUB": ["github", "groq"],
    "HF": ["hf", "groq", "mistral"],
    "AGT_HF": ["hf", "groq", "mistral"],
    "SAMBANOVA": ["sambanova", "groq"],
    "AGT_SAMBANOVA": ["sambanova", "groq"],
    "CEREBRAS": ["cerebras", "groq"],
    "OPENROUTER": ["openrouter", "groq"],
    "NVIDIA": ["nvidia", "groq"],
    "CLOUDFLARE": ["cloudflare", "groq"],
    "OLLAMA": ["ollama"],
    "NOKIDO": ["ollama", "groq"],
    "WORKER": ["groq", "mistral"],
    "OPENAI": ["groq", "mistral"],
    "DEEPSEEK": ["groq", "mistral"],
    "GITHUB_DEEPSEEK_V3": ["github", "groq"],
}


def _extract_message(description: str) -> str:
    """Extrait le message de la section COMMANDES ou retourne description complète."""
    # Cherche pattern: ask provider=X message='...'
    m = re.search(
        r"ask\s+provider=\w+\s+message='(.*?)'(?:\n|$)", description, re.DOTALL | re.IGNORECASE
    )
    if m:
        return m.group(1).strip()

    # Cherche section COMMANDES:
    m2 = re.search(r"COMMANDES?:\s*\n(.*?)(?:\n\n|\Z)", description, re.DOTALL | re.IGNORECASE)
    if m2:
        cmd_section = m2.group(1).strip()
        # Retirer le ask ... wrapper, garder le message
        m3 = re.search(r"message='(.*)'", cmd_section, re.DOTALL)
        if m3:
            return m3.group(1).strip()
        return cmd_section

    # Fallback : la description COMPLETE. 9/11 (enquete AGY docs/enquetes/consigne_coupee_30000_20261109.md) : la
    # coupe a 30 000 ici bridait TOUS les executeurs (OpenCode ACP par stdin compris : lot 6 05 recu 35/40) pour une
    # borne propre a l'argv d'agy. La borne de transport vit chez l'executeur qui la subit (_borne_dite), et elle
    # est DITE a l'agent.
    return description


def _borne_dite(texte: str, borne: int, raison: str) -> str:
    """Regle « une borne dit combien » (9/11) : au-dela de `borne`, l'agent recoit en TETE combien lui est servi
    sur combien, et pourquoi ; jamais une consigne amputee en silence (lots 5 12/14 AGY livres 29/40)."""
    texte = str(texte or "")
    if len(texte) <= borne:
        return texte
    entete = ("[ATTENTION - CONSIGNE TRONQUEE : %d car. sur %d servis (%s), le reste n'est PAS servi ; "
              "ne traite que ce que tu as recu et DIS ce qui manque]\n" % (borne, len(texte), raison))
    log.warning("consigne de %d car. bornee a %d (%s) : coupe DITE a l'agent", len(texte), borne, raison)
    return entete + texte[:max(0, borne - len(entete))]


def _avec_carte_attention(desc: str) -> str:
    """Prefixe la consigne deleguee par la carte d'attention (symbiose, owner 31/10) : fichiers chauds de l'arbre
    partage, etag a reutiliser, collisions en tete. Interrupteur LAFORGE_CARTE_DELEGATION=0 (cout : quelques lignes
    par delegation). Indisponible ou vide = consigne inchangee, jamais un echec de delegation."""
    if not desc or os.environ.get("LAFORGE_CARTE_DELEGATION", "1") == "0":
        return desc
    try:
        from nokido_agent.app.forge_network_logger import consigne_attention
        return consigne_attention() + desc
    except Exception as exc:  # noqa: BLE001 - un en-tete facultatif ne casse jamais une delegation
        log.debug("carte d'attention indisponible pour la consigne (%s)", type(exc).__name__)
        return desc


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(TASKS_DB), timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ── LEASE & REPRISE DES MISSIONS ─────────────────────────────────────────────
# MESURE 2026-08-14 dans le bus VIVANT (sandbox/tasks.db) : une tache `running`
# depuis 525,9 h (22 jours, WORKER_CODE) et deux `claimed` depuis 327,5 h et
# 24,6 h. Personne ne les a jamais reprises.
#
# Le heartbeat surveille le WORKER, pas la MISSION : un CLI interactif qui meurt
# emporte sa tache avec lui, et elle reste `running` pour toujours. `reassign_stale`
# de forge_task_bus promettait de traiter les taches `assigned` mais son SQL ne
# touche que `status='pending'` et les remet a `pending` : un no-op sur les taches
# mortes. Et ce module-la ecrit dans `agent_tasks`, une table sans activite depuis
# le 2026-05-02 — corriger la n'aurait rien change au bus reellement utilise.
#
# On ajoute donc le minimum qui rend une mission REPRENABLE, sans toucher au hub
# (CRITICAL_FILE) : un bail avec expiration, un compteur de tentatives, un
# checkpoint, et un horodatage de PROGRESSION distinct de `updated_at`.
_LEASE_TIMEOUT_S = int(os.environ.get("TASK_LEASE_TIMEOUT_S", "1800"))   # 30 min
_LEASE_MAX_ATTEMPTS = int(os.environ.get("TASK_LEASE_MAX_ATTEMPTS", "3"))
_EN_VOL = ("running", "claimed", "assigned")
_PROGRES_TOUTES_S = float(os.environ.get("LAFORGE_PROGRES_TOUTES_S", "300"))
if _PROGRES_TOUTES_S >= _LEASE_TIMEOUT_S and _LEASE_TIMEOUT_S > 1:
    _PROGRES_TOUTES_S = max(1.0, float(_LEASE_TIMEOUT_S - 1))
if _PROGRES_TOUTES_S.is_integer():
    _PROGRES_TOUTES_S = int(_PROGRES_TOUTES_S)


def ensure_lease_schema(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes de bail si absentes. Idempotent, jamais destructif."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    for nom, decl in (("lease_until", "TEXT"), ("attempt", "INTEGER DEFAULT 0"),
                      ("checkpoint", "TEXT DEFAULT '{}'"), ("progress_at", "TEXT"),
                      # jeton de garde (7/11) : +1 a CHAQUE claim. Distinct de `attempt` (plafond de reprises) :
                      # une tache interrompue sans faute ne doit pas consommer son quota.
                      ("garde", "INTEGER DEFAULT 0")):
        if nom not in cols:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {nom} {decl}")
    conn.commit()


_COLONNES_TRACE = (("taille", "TEXT"), ("modele", "TEXT"), ("effort", "TEXT"),
                   ("cout_usd", "REAL"), ("cout_etat", "TEXT"), ("verdict_effet", "TEXT"))


def ensure_trace_schema(conn: sqlite3.Connection) -> None:
    """Colonnes DEDIEES de la trace de fin de tache (decision owner 23/10). ADDITIF et idempotent : rien n'est
    supprime ni reecrit, une valeur absente reste NULL (jamais 0)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    for nom, decl in _COLONNES_TRACE:
        if nom not in cols:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {nom} {decl}")
    conn.commit()


def _cout_et_etat(cout) -> tuple[float, str]:
    """(cout_usd, cout_etat) d'un `total_cost_usd` lu : MESURE s'il est connu ; sinon le FORFAIT effectivement
    facture au budget (jamais 0 : unknowable != free)."""
    if cout is None:
        return float(_CLAUDE_COUT_INCONNU_USD), "FORFAIT"
    return float(cout), "MESURE"


def ecrire_trace_tache(conn: sqlite3.Connection, task_id: str, taille=None, modele=None, effort=None,
                       cout_usd=None, cout_etat=None, verdict_effet=None) -> None:
    """Ecrit la trace de FIN de tache. Absent = NULL ; sans cout fourni, cout_etat = INCONNU (cout_usd NULL).
    Le cout vient de `_cout_claude(sortie complete)`, lu AVANT toute troncature du result."""
    ensure_trace_schema(conn)
    if cout_usd is None:
        cout_etat = "INCONNU"
    elif cout_etat is None:
        cout_etat = "MESURE"
    conn.execute(
        "UPDATE tasks SET taille=?, modele=?, effort=?, cout_usd=?, cout_etat=?, verdict_effet=? WHERE id=?",
        (taille or None, modele or None, effort or None, cout_usd, cout_etat,
         (str(verdict_effet)[:2000] if verdict_effet else None), task_id))
    conn.commit()


def touch_progress(task_id: str, checkpoint: str = "") -> None:
    """Un agent VIVANT prolonge son bail. C'est la progression de la MISSION qui
    est attestee ici, pas la survie du process : un worker peut respirer tout en
    etant bloque depuis 40 minutes."""
    try:
        conn = _db()
        try:
            ensure_lease_schema(conn)
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            jusqu = time.strftime("%Y-%m-%dT%H:%M:%S",
                                  time.localtime(time.time() + _LEASE_TIMEOUT_S))
            if checkpoint:
                conn.execute("UPDATE tasks SET progress_at=?, lease_until=?, checkpoint=? "
                             "WHERE id=?", (now, jusqu, checkpoint, task_id))
            else:
                conn.execute("UPDATE tasks SET progress_at=?, lease_until=? WHERE id=?",
                             (now, jusqu, task_id))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 -- base verrouillee : journalise, ne casse pas
        log.warning(f"  touch_progress KO pour {str(task_id)[:24]} ({type(e).__name__}): {e}")


_SERVICE_SUPERVISEUR: list = []   # cache du nom resolu (liste vide = pas encore resolu)


def _mon_service_superviseur() -> str | None:
    """Le service superviseur qui porte CE processus, lu dans services.toml d'apres son `--agent`.

    Le superviseur ne transmet pas le nom du service a l'enfant ; services.toml declare en revanche, pour chaque
    executeur, `args = [..., "--agent", X]` (sans --agent : NokidoTaskExecutor). C'est la source de verite, pas une
    table recopiee ici. TOML illisible : None, et la delegation continue sans veto (DIT au journal)."""
    if _SERVICE_SUPERVISEUR and _SERVICE_SUPERVISEUR[0][0] == tuple(sys.argv):
        return _SERVICE_SUPERVISEUR[0][1]
    argv = list(sys.argv)
    agent = argv[argv.index("--agent") + 1].upper() if "--agent" in argv[:-1] else None
    nom = None
    try:
        import tomllib

        doc = tomllib.loads((ROOT / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8"))
        for svc in doc.get("service") or []:
            args = [str(a) for a in (svc.get("args") or [])]
            if not any(a.replace("\\", "/").endswith("tools/forge_task_executor.py") for a in args):
                continue
            a_agent = args[args.index("--agent") + 1].upper() if "--agent" in args[:-1] else None
            if a_agent == agent:
                nom = svc.get("name")
                break
    except Exception as e:  # noqa: BLE001 -- sans nom, pas de veto : la delegation continue, et on le DIT
        log.warning(f"  service superviseur ILLISIBLE ({type(e).__name__}) : pas de veto de sommeil")
        return None
    _SERVICE_SUPERVISEUR[:] = [(tuple(sys.argv), nom)]
    return nom


# RECEPTEUR du palier de pression RAM (owner 24/10, bareme a 4 paliers) : Hamilton publie NORADRENALINE_PRESSION_RAM
# (niveaux 0 / 0.25 / 0.5 / 0.75 / 1) ; l'executeur RALENTIT (boucle x2), cesse de RECLAMER (GENE), GELE sa delegation
# en vol (DETRESSE) ; seul le CRITIQUE, cote Hamilton, passe outre l'intention. Absent, perime ou illisible = INCONNU,
# et l'executeur garde son comportement d'avant : ni calme ni panne fabriques.
_HORMONE_PRESSION_RAM = "NORADRENALINE_PRESSION_RAM"
_PALIER_PERIME_S = 300
_PALIER_TOUTES_S = float(os.environ.get("LAFORGE_PALIER_TOUTES_S", "10"))
_PALIERS_PAR_NIVEAU = ((0.875, "CRITIQUE"), (0.625, "DETRESSE"), (0.375, "GENE"), (0.125, "RALENTISSEMENT"))


def _palier_pression() -> str:
    """Le palier publie par Hamilton, lu au niveau d'EMISSION (fresh_level) ; INCONNU s'il manque ou a vieilli."""
    try:
        from nokido_agent.app import forge_endocrine as _en

        r = _en.read_full(_HORMONE_PRESSION_RAM)
    except Exception as e:  # noqa: BLE001 -- signal illisible : INCONNU, dit en debug (lu toutes les 10 s)
        log.debug(f"  palier de pression ILLISIBLE ({type(e).__name__})")
        return "INCONNU"
    if r is None or getattr(r, "expired", False) or float(getattr(r, "age_s", 0) or 0) > _PALIER_PERIME_S:
        return "INCONNU"
    niveau = float(getattr(r, "fresh_level", 0.0) or 0.0)
    for seuil, palier in _PALIERS_PAR_NIVEAU:
        if niveau >= seuil:
            return palier
    return "CALME"


def _reclamation_permise(palier: str) -> bool:
    """GENE et au-dela : plus de nouvelle tache (celle en vol continue, sous veto)."""
    return palier in ("CALME", "RALENTISSEMENT", "INCONNU")


def _intervalle_boucle(base, palier: str):
    """RALENTISSEMENT : la boucle de reclamation bat deux fois moins vite."""
    return base * 2 if palier == "RALENTISSEMENT" else base


def _empreinte_db(chemin=None) -> tuple:
    """mtime de tasks.db et de son WAL : change a chaque ecriture. Un stat(), aucune lecture de la base."""
    p = Path(chemin or TASKS_DB)
    out = []
    for f in (p, p.with_name(p.name + "-wal")):
        try:
            out.append(f.stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


def _taches_pending(chemin=None) -> int:
    """Taches pending ; -1 si illisible (un illisible ne reveille jamais)."""
    try:
        c = sqlite3.connect(f"file:{Path(chemin or TASKS_DB)}?mode=ro", uri=True, timeout=2)
        try:
            return int(c.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0])
        finally:
            c.close()
    except Exception:  # noqa: BLE001
        return -1


def _reveil_tache_deposee(etat: dict, chemin=None) -> bool:
    """REVEIL (owner 30/10 « c'est trop lent ») : une tache deposee pendant la sieste se prend sans attendre
    POLL_INTERVAL (jusqu'a 2 min mesurees). La base n'est relue que si son empreinte a change, et seule une HAUSSE
    du nombre de taches pending reveille (une reclamation ou une cloture ne reveille pas)."""
    e = _empreinte_db(chemin)
    if e == etat.get("empreinte"):
        return False
    etat["empreinte"] = e
    n = _taches_pending(chemin)
    avant, etat["pending"] = etat.get("pending", -1), n
    return avant >= 0 and n > avant


def _geste_delegation(palier: str, gelee: bool):
    """GELER en DETRESSE ; DEGELER des que le palier redescend -- ou devient illisible (jamais gele a l'aveugle) ;
    au CRITIQUE on reste gele, Hamilton tranche."""
    if palier == "DETRESSE":
        return None if gelee else "GELER"
    if palier == "CRITIQUE":
        return None
    return "DEGELER" if gelee else None


@contextlib.contextmanager
def _battement_delegation(agent: str, task_id: str):
    """Pendant une DELEGATION longue, DECLARE le travail au superviseur.

    Mesure 2026-10-17 : l'executeur ne bat qu'en tete de boucle ; pendant une delegation de
    plus d'une heure il paraissait fige et le superviseur le relancait EN PLEIN TRAVAIL (AGY,
    16:20:55). Le superviseur sait pourtant s'abstenir quand l'organe declare `travail_en_cours`
    et `travail_depuis_s` (proxy_deno/core/supervisor.ts:3162-3183, plafond 4 x 3600) : encore
    faut-il le declarer. On bat donc, toutes les `_PROGRES_TOUTES_S` et une PREMIERE fois tout
    de suite, le bail de MISSION (`touch_progress`) ET le pouls de l'EXECUTEUR (`beat_daemon`)
    ; a la sortie on redeclare la fin. Ne leve jamais : un battement qui casserait son porteur
    serait pire que pas de battement (doctrine de `beat_daemon`).
    """
    from nokido_agent.app.forge_heartbeat import beat_daemon

    hb_nom = _hb_file(agent).stem
    t0 = time.time()
    stop = threading.Event()
    # INTENTION > REGULATION (owner 24/10). Hamilton endormait les 13 executeurs en pleine tache (ordres
    # RESOURCE_MANAGER 20:27-20:48, supervisor_ordres.jsonl) ; un sommeil superviseur TUE le processus. Le veto de
    # sommeil, deja oppose par Hamilton et le bail, declare l'acte en cours ; renouvele a chaque battement, il
    # expire seul si l'executeur meurt sans le lever. L'eviction dure (detresse) n'en tient pas compte.
    service = _mon_service_superviseur()
    duree_veto = max(60.0, 3.0 * float(_PROGRES_TOUTES_S))

    def _battre() -> None:
        # Bail de MISSION : la tache reste `en vol`, `reclaim_expired` ne la reprend pas.
        try:
            touch_progress(task_id)
        except Exception as e:  # noqa: BLE001 -- battement best-effort, jamais bloquant
            log.warning(f"  battement KO pour {str(task_id)[:24]} ({type(e).__name__}): {e}")
        # Pouls de l'EXECUTEUR : le superviseur lit `travail_en_cours` et s'abstient de relancer.
        try:
            beat_daemon(hb_nom, agent=agent, travail_en_cours=True,
                        travail_depuis_s=round(time.time() - t0, 1), tache=task_id,
                        enfants=_pids_enfants())
        except Exception as e:  # noqa: BLE001
            log.warning(f"  pouls de delegation KO pour {str(task_id)[:24]} ({type(e).__name__}): {e}")
        # Intention declaree a la regulation RAM : un veto KO laisse la delegation continuer, et le DIT.
        if service:
            try:
                from nokido_agent.app import forge_resource_manager as _rm

                r = _rm.poser_veto_sommeil(service, "tache %s en vol (%s)" % (task_id, agent), duree_veto)
                if not (r or {}).get("ok"):
                    log.warning(f"  veto de sommeil NON pose pour {service} : {(r or {}).get('erreur')}")
            except Exception as e:  # noqa: BLE001
                log.warning(f"  veto de sommeil NON pose pour {service} ({type(e).__name__}): {e}")

    def _boucle() -> None:
        while not stop.wait(timeout=_PROGRES_TOUTES_S):
            if stop.is_set() or _stop:
                break
            _battre()

    # 1er battement SYNCHRONE, avant de rendre la main : la declaration existe des l'entree. Dans le thread, il arrivait
    # sous charge APRES la premiere lecture (CI de reference 8a10f34da, xdist 4 workers : seul echec sur 15 432).
    _battre()
    fil = threading.Thread(target=_boucle, daemon=True, name="battement-delegation")
    fil.start()

    # DETRESSE : la delegation en vol est GELEE (processus enfants suspendus), pas tuee ; reprise des que le palier
    # redescend. Veille plus rapide que le battement (300 s) : une detresse se joue en secondes.
    gel = {"gelee": False, "procs": []}

    def _degeler() -> None:
        for p in gel["procs"]:
            try:
                p.resume()
            except Exception as e:  # noqa: BLE001 -- processus deja termine : rien a reprendre, dit
                log.warning(f"  reprise de {getattr(p, 'pid', '?')} impossible ({type(e).__name__})")
        if gel["gelee"]:
            log.info(f"  delegation {str(task_id)[:24]} DEGELEE ({len(gel['procs'])} processus)")
        gel.update(gelee=False, procs=[])

    def _veille_palier() -> None:
        while not stop.wait(timeout=_PALIER_TOUTES_S):
            if stop.is_set() or _stop:
                break
            palier = _palier_pression()
            geste = _geste_delegation(palier, gel["gelee"])
            if geste == "DEGELER":
                _degeler()
            elif geste == "GELER":
                try:
                    import psutil as _ps

                    procs = _ps.Process().children(recursive=True)
                except Exception as e:  # noqa: BLE001 -- sans psutil, pas de gel : la delegation continue, dit
                    log.warning(f"  gel impossible ({type(e).__name__}) : la delegation continue en DETRESSE")
                    continue
                gel_ok = []
                for p in procs:
                    try:
                        p.suspend()
                        gel_ok.append(p)
                    except Exception as e:  # noqa: BLE001
                        log.warning(f"  gel de {getattr(p, 'pid', '?')} impossible ({type(e).__name__})")
                gel.update(gelee=True, procs=gel_ok)
                log.warning(f"  DETRESSE RAM : delegation {str(task_id)[:24]} GELEE ({len(gel_ok)} processus)")

    veille = threading.Thread(target=_veille_palier, daemon=True, name="veille-palier-delegation")
    veille.start()
    try:
        yield
    finally:
        stop.set()
        fil.join(timeout=max(1.0, float(_PROGRES_TOUTES_S)))
        veille.join(timeout=max(1.0, float(_PALIER_TOUTES_S)))
        _degeler()
        try:
            beat_daemon(hb_nom, agent=agent, travail_en_cours=False, tache=task_id,
                        enfants=_pids_enfants())
        except Exception as e:  # noqa: BLE001
            log.warning(f"  pouls de fin de delegation KO pour {str(task_id)[:24]} ({type(e).__name__}): {e}")
        if service:
            try:
                from nokido_agent.app import forge_resource_manager as _rm

                if not _rm.lever_veto_sommeil(service):
                    log.warning(f"  veto de sommeil de {service} non leve : il expirera seul")
            except Exception as e:  # noqa: BLE001
                log.warning(f"  veto de sommeil de {service} non leve ({type(e).__name__}) : il expirera seul")


def reclaim_expired(timeout_s: int = 0) -> dict:
    """Rend au bus les missions dont le bail a expire, avec leur checkpoint.

    Une tache reprise n'est PAS relancee de zero : son `checkpoint` est conserve,
    et `attempt` est incremente. Au-dela de `_LEASE_MAX_ATTEMPTS`, elle passe en
    `failed` avec un motif ecrit — une mission qui echoue 3 fois est un probleme
    a montrer, pas a reboucler indefiniment (le sawtooth Docker a coute assez cher
    pour qu'on ne le rejoue pas ici).
    """
    seuil = timeout_s or _LEASE_TIMEOUT_S
    limite = time.strftime("%Y-%m-%dT%H:%M:%S",
                           time.localtime(time.time() - seuil))
    reprises, abandonnees = [], []
    conn = _db()
    try:
        ensure_lease_schema(conn)
        marks = ",".join("?" * len(_EN_VOL))
        rows = conn.execute(
            f"SELECT id, agent, attempt, status FROM tasks WHERE status IN ({marks}) "
            f"AND COALESCE(progress_at, updated_at, created_at) < ?",
            (*_EN_VOL, limite)).fetchall()
        for r in rows:
            att = int(r["attempt"] or 0) + 1
            if att > _LEASE_MAX_ATTEMPTS:
                conn.execute(
                    "UPDATE tasks SET status='failed', attempt=?, updated_at=?, "
                    "result=COALESCE(NULLIF(result,''), ?) WHERE id=?",
                    (att, time.strftime("%Y-%m-%dT%H:%M:%S"),
                     f"[lease] abandonnee apres {att - 1} reprises sans progression",
                     r["id"]))
                abandonnees.append(r["id"])
            else:
                conn.execute(
                    "UPDATE tasks SET status='pending', attempt=?, lease_until=NULL, "
                    "updated_at=? WHERE id=?",
                    (att, time.strftime("%Y-%m-%dT%H:%M:%S"), r["id"]))
                reprises.append({"id": r["id"], "agent": r["agent"],
                                 "etait": r["status"], "attempt": att})
        conn.commit()
    finally:
        conn.close()
    for t in reprises:
        log.warning("[lease] mission REPRISE %s (%s, etait %s, tentative %d) — "
                    "l'agent n'a plus donne signe de progression depuis %d s",
                    t["id"], t["agent"], t["etait"], t["attempt"], seuil)
    for i in abandonnees:
        log.error("[lease] mission ABANDONNEE %s — trop de reprises sans progression", i)
    return {"reprises": len(reprises), "abandonnees": len(abandonnees),
            "detail": reprises}


# CLIs INTERACTIFS : leurs taches leur sont RESERVEES (claim par le CLI lui-meme via
# task action=claim). L'executor autonome (sans --agent) ne doit PAS les voler — sinon
# il les tente en ring 4 -> GATE_DENIED -> brule la tache en "completed"-echec (race
# task-queue : 1 queue, 2 consommateurs). cf fix multi-agent 2026-06-23.
# PLANCHER historique : conserve tel quel. Le registre d'identites ne declare pas
# encore `mode` pour tous ces CLI, et un nom qui en disparaitrait ferait VOLER ses
# taches -- l'erreur coute une tache brulee, jamais l'inverse. On ne retire donc
# jamais du plancher ; on ne fait qu'y AJOUTER ce que le registre declare.
_INTERACTIVE_FLOOR = (
    "CLAUDE", "CODEX", "GEMINI", "ANTIGRAVITY", "CLINE", "COPILOT",
    "CLAUDE_DESKTOP", "VSCODE", "SIXTH", "BRIDGE", "ROO_ACT", "ROO_PLAN",
    "CLINE_ACT", "CLINE_PLAN", "MISTRAL",
)


def _lire_registre() -> dict:
    """Le registre d'identites, ou {} s'il est illisible.

    UNE seule lecture pour tous les lecteurs de ce module (mode interactif,
    suspension) : deux verites qui lisent le meme fichier ne doivent pas
    pouvoir diverger en silence. Registre illisible -> {} (aucun agent declare),
    jamais une exception qui empêcherait le repli de tourner."""
    try:
        return json.loads((ROOT / "config" / "agent_identities.json")
                          .read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  (registre illisible -> aucun agent declare)
        return {}


# TTL des surfaces indisponibles. Une marque ne vaut QUE pour une duree : un
# echec d'authentification passager (token expire, rate de reseau) ne doit pas
# ecarter la surface jusqu'au redemarrage de l'executeur.
_TTL_SURFACE_INDISPO_DEFAUT_S = 1800
_SURFACES_INDISPONIBLES: dict[str, tuple[float, str]] = {}


def _ttl_surface_indispo_s() -> float:
    """TTL en secondes, lu a CHAQUE appel (jamais fige a l'import).

    Absent ou illisible -> le defaut. L'operateur peut changer la valeur sans
    redemarrer l'executeur, et un test peut la poser."""
    try:
        return float(os.environ.get("LAFORGE_SURFACE_INDISPO_TTL_S", ""))
    except (TypeError, ValueError):
        return float(_TTL_SURFACE_INDISPO_DEFAUT_S)


# 3/11 (owner « tu echoues constamment sur les delegations, regarde comment omniroute gere ca ») : comme OmniRoute, une
# surface EPUISEE (abonnement, quota mensuel) est ecartee JUSQU'A sa remise a zero, et cette memoire est PARTAGEE (fichier)
# par tous les executeurs : en memoire seule, chaque processus la reapprenait en brulant une tache (Codex x2 « usage
# limit ... try again at Nov 17th », Nemotron sur le quota MENSUEL d'Ollama Cloud, le 3/11).
# LAFORGE_SURFACES_INDISPO_FICHIER : les NR ne lisent pas le registre vivant (7/11 : Mistral marque = 13 NR rouges).
_FICHIER_INDISPO = Path(os.environ.get("LAFORGE_SURFACES_INDISPO_FICHIER")
                        or Path(__file__).resolve().parent.parent / "sandbox" / "surfaces_indisponibles.json")
INDISPO_DEFAUT_S = 6 * 3600.0     # quota epuise sans echeance lisible : on retente au bout de 6 h
_RE_QUOTA_EPUISE = re.compile(r"quota reached|usage limit|limit reached|quota exceeded|insufficient balance|credit balance is too low|"
                              r"usagelimitexceeded|please recharge|no resource package|budget exhausted|"
                              r"402 payment required", re.I)  # MISTRAL 9/11 : 4 lots routes vers un 402
_RE_REESSAYER_LE = re.compile(r"try again at\s+([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}),?\s+"
                              r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])?")
_RE_RESETS_IN = re.compile(r"resets?\s+in\s+(?:(\d+)\s*d\s*)?(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s)?", re.I)
_MOIS_EN = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                            "dec"))}


def _lire_indispo() -> dict:
    """Registre partage ; illisible ou absent -> {} (il n'ecarte alors personne : jamais de blocage sur un doute)."""
    from nokido_agent.app.forge_utils import lire_json_dict

    return lire_json_dict(_FICHIER_INDISPO)


def _est_quota_epuise(texte) -> bool:
    return bool(texte) and bool(_RE_QUOTA_EPUISE.search(str(texte)))


def echeance_quota(texte, maintenant: float | None = None) -> float:
    """Remise a zero lue dans le message (« try again at Nov 17th, 2026 1:38 PM » ou « Resets in 2h14m24s ») ;
    « monthly » -> 1er du mois suivant ; sinon maintenant + INDISPO_DEFAUT_S (une borne, jamais l'infini)."""
    from datetime import datetime as _dt

    instant = time.time() if maintenant is None else float(maintenant)
    texte = str(texte or "")
    m_res = _RE_RESETS_IN.search(texte)
    if m_res and any(m_res.groups()):
        j = int(m_res.group(1) or 0)
        h = int(m_res.group(2) or 0)
        m_ = int(m_res.group(3) or 0)
        s = int(m_res.group(4) or 0)
        delta_s = j * 86400 + h * 3600 + m_ * 60 + s
        if delta_s > 0:
            return instant + delta_s
    m = _RE_REESSAYER_LE.search(texte)
    if m and _MOIS_EN.get(m.group(1)[:3].lower()):
        h = int(m.group(4))
        if m.group(6):
            h = h % 12 + (12 if m.group(6).lower() == "pm" else 0)
        try:
            return _dt(int(m.group(3)), _MOIS_EN[m.group(1)[:3].lower()], int(m.group(2)), h, int(m.group(5))).timestamp()
        except ValueError:  # muet-ok : date impossible dans le message -> regles suivantes (mensuel, puis borne)
            pass
    if "monthly" in texte.lower() or "mensuel" in texte.lower():
        d = _dt.fromtimestamp(instant)
        an, mois = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        return _dt(an, mois, 1).timestamp()
    return instant + INDISPO_DEFAUT_S


def marquer_surface_indisponible(agent: str, motif: str = "echec authentification",
                                 jusqu_a: float | None = None) -> None:
    """Marque une surface d'execution comme indisponible (ex: echec d'authentification du CLI).

    L'heure de la marque est NOTEE : c'est elle qui portera l'expiration (TTL). Avec `jusqu_a` (quota epuise, echeance
    lue), la marque vaut jusqu'a cette date ET est ecrite dans le registre partage de tous les executeurs."""
    nom = (agent or "").upper()
    if not nom:
        return
    t = time.time()
    _SURFACES_INDISPONIBLES[nom] = (t, str(motif), jusqu_a)
    if jusqu_a is None:
        return
    _ecrire_entree_indispo(nom, {"marque": t, "motif": str(motif)[:200], "jusqu_a": float(jusqu_a)})


def _ecrire_entree_indispo(nom: str, entree: dict) -> bool:
    """UNIQUE ecrivain du registre partage (quota ET etat sain `ok`)."""
    try:
        d = _lire_indispo()
        d[nom] = entree
        _FICHIER_INDISPO.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FICHIER_INDISPO.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _FICHIER_INDISPO)
        return True
    except OSError as e:
        log.warning(f"  registre des surfaces indisponibles NON ecrit ({type(e).__name__}) : {nom} en memoire seule")
        return False


def _noter_succes_agy(modele: str | None) -> bool:
    """Une delegation AGY a REUSSI (effet observe, sans erreur de quota) sur `modele` : etat `ok` horodate, par le meme
    ecrivain que `_noter_indisponibilite`. Expire (TTL du tracker, 6 h) -> `inconnu`. S, M et L comptent pareil."""
    if not modele:
        return False
    cle = f"AGY:{str(modele).upper()}"
    _SURFACES_INDISPONIBLES.pop(cle, None)
    return _ecrire_entree_indispo(cle, {"status": "ok", "marque": time.time(), "motif": "delegation reussie", "jusqu_a": 0.0})


def surface_est_indisponible(agent: str, maintenant: float | None = None) -> str | None:
    """Rend le motif si la surface est marquee indisponible ET non expiree, None sinon.

    Expiree = `maintenant - marque >= TTL` (ou echeance `jusqu_a` passee) : la marque disparait alors et la
    surface est RETENTEE. `maintenant` est optionnel (defaut : l'heure courante) -- l'appel d'origine, a un seul
    argument, continue de marcher. Une marque absente de cette memoire est cherchee dans le registre PARTAGE."""
    nom = (agent or "").upper()
    instant = time.time() if maintenant is None else float(maintenant)
    cles = (nom, f"AGY:{nom}") if not nom.startswith("AGY:") else (nom,)
    for cle in cles:
        entree = _SURFACES_INDISPONIBLES.get(cle)
        if entree is not None:
            marque, motif = entree[0], entree[1]
            jusqu = entree[2] if len(entree) > 2 else None
            if (instant < float(jusqu)) if jusqu is not None else (instant - marque < _ttl_surface_indispo_s()):
                return motif
            _SURFACES_INDISPONIBLES.pop(cle, None)
        d = _lire_indispo().get(cle)
        if isinstance(d, dict):
            try:
                if instant < float(d.get("jusqu_a") or 0.0):
                    return str(d.get("motif") or "indisponible")
            except (TypeError, ValueError) as err:
                log.warning(f"  marque illisible dans registre indispo pour {cle} ({type(err).__name__}) : {d.get('jusqu_a')}")
    return None


surface_indisponible = surface_est_indisponible


# 3/11 (owner « vois-tu et diagnostiques-tu au moins les raisons des echecs de delegations ? ») : le CORPS classe la cause
# de chaque echec (ce soir, toutes ont ete trouvees a la main dans tasks.db). Ordre = du plus specifique au plus general :
# un rendu Codex porte a la fois « RIEN PRODUIT » et « usage limit » -- la cause est le quota.
_CAUSES_ECHEC = (
    ("HARNESS_WORKER", re.compile(r"\[HARNESS WORKER\b|harness worker pouls perime|harness MUET apres", re.I)),
    ("QUOTA", _RE_QUOTA_EPUISE),
    ("MODELE_REPLI_NON_DECLARE", re.compile(r"MODELE_REPLI_NON_DECLARE", re.I)),
    ("CONTEXTE_NON_SERVI", re.compile(r"CONTEXTE_NON_SERVI", re.I)),
    ("OUTIL_REFUSE", re.compile(r"tool_denied|denied by approval policy|actions refusees", re.I)),
    ("RING", re.compile(r"requiert ring|ring\s*=\s*0|ERR_RBAC_DENY", re.I)),
    ("DELAI", re.compile(r"print_timeout|TimeoutError|delai depasse|SilenceACP|timed out", re.I)),
    ("NON_LIVRE", re.compile(r"RIEN PRODUIT|NON LIVRE|artefact ABSENT", re.I)),
)


_RE_SESSION_EXPIREE = re.compile(r"print[ _]timeout|turn still in progress|session expiree", re.I)


def classer_cause_echec(detail) -> str:
    """Cause d'un echec de delegation lue dans son rendu : QUOTA | OUTIL_REFUSE | RING | DELAI | NON_LIVRE | INCONNU."""
    texte = str(detail or "")
    return next((nom for nom, rx in _CAUSES_ECHEC if rx.search(texte)), "INCONNU")


def _noter_cause_echec(conn, task_id: str, cause) -> None:
    """Ecrit la cause classee dans tasks.cause_echec (colonne ajoutee a la demande). Pas d'echec -> rien."""
    if not cause:
        return
    try:
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN cause_echec TEXT")
        except sqlite3.OperationalError:
            pass  # muet-ok : colonne deja presente
        conn.execute("UPDATE tasks SET cause_echec=? WHERE id=?", (str(cause), task_id))
        conn.commit()
    except Exception as e:  # noqa: BLE001 - la cause est un diagnostic : l'ecrire ne doit JAMAIS empecher la cloture
        log.warning(f"  cause d'echec NON ecrite pour {str(task_id)[:24]} ({type(e).__name__}) : {cause}")


def _noter_indisponibilite(de: str, motif, rendu="", modele: str | None = None) -> bool:
    """Un echec de QUOTA (abonnement, mensuel) marque la surface jusqu'a sa remise a zero, dans le registre partage.
    Un quota mensuel vu par OpenCode marque aussi le fournisseur OLLAMA_CLOUD (repli commun des instances).
    6/11 : quota AGY note par MODELE avec l'echeance lue dans « Resets in ... », sans ecarter tout AGY.
    6/11 : un refus de l'executeur CITE l'ancien quota ; le lire comme un nouvel epuisement prolongeait le blocage de 6 h a
    chaque refus (MISTRAL refuse a 17:08 pour une echeance de 16:06). Sans rendu reel de l'agent, ce n'est pas une mesure."""
    if not str(rendu or "").strip() and any(m in str(motif or "") for m in ("MODELE HORS QUOTA", "INDISPONIBLE (")):
        return False
    texte = "%s\n%s" % (motif or "", rendu or "")
    if not (de and _est_quota_epuise(texte)):
        return False
    ligne = next((l.strip() for l in texte.splitlines() if _RE_QUOTA_EPUISE.search(l)), str(motif or ""))[:200]
    jusqu = echeance_quota(texte)
    cible = de
    de_upper = str(de).upper()
    if de_upper in ("AGY", "ANTIGRAVITY") or de_upper.startswith("AGY:"):
        mod = modele
        if not mod and ":" in str(de):
            mod = str(de).split(":", 1)[1]
        if not mod:
            m_mod = re.search(r"(gemini-[a-zA-Z0-9.-]+|claude-[a-zA-Z0-9.-]+|gpt-oss-[a-zA-Z0-9.-]+)", texte, re.I)
            if m_mod:
                mod = m_mod.group(1)
        if mod:
            cible = f"AGY:{mod.upper()}"
        else:
            cible = "AGY"
            ligne = f"[modele inconnu] {ligne}"[:200]
    elif "monthly usage limit" in texte.lower() and ("ollama" in texte.lower() or str(de).upper().startswith("OPENCODE")):
        # Quota d'un FOURNISSEUR (repli commun des instances OpenCode) : seul le fournisseur est ecarte ; l'instance garde
        # son principal et son repli local LM Studio (_repli_du).
        cible = "OLLAMA_CLOUD"
    marquer_surface_indisponible(cible, ligne, jusqu_a=jusqu)
    log.warning(f"  {cible} INDISPONIBLE jusqu'a {time.strftime('%Y-%m-%d %H:%M', time.localtime(jusqu))} "
                f"(vu par {de}) : {ligne[:120]}")
    return True


_marquer_surface_indisponible = marquer_surface_indisponible
_surface_indisponible = surface_est_indisponible


def reinitialiser_surfaces_indisponibles() -> None:
    """Reinitialise l'etat des surfaces indisponibles (usage tests)."""
    _SURFACES_INDISPONIBLES.clear()


_reinitialiser_surfaces_indisponibles = reinitialiser_surfaces_indisponibles


def _executeur_suspendu(agent: str, maintenant: float | None = None) -> str | None:
    """Le motif de suspension de `agent`, ou None s'il n'est pas suspendu.

    Une suspension DECIDEE se DECLARE au registre sous `suspendu: {depuis, motif}`
    et le repli la LIT. Une decision ecrite au tableau noir que personne ne lit
    n'est pas une decision (mesure 17/10 : MISTRAL suspendu au SSoT, 0 livraison,
    mais son executeur battait et le repli lui a passe des taches -> 2 echecs)."""
    nom = (agent or "").upper()
    if not nom:
        return None
    motif_surface = surface_est_indisponible(nom)
    if motif_surface is not None:
        return f"surface indisponible (motif : {motif_surface})"
    repos = executeur_en_repos(nom, maintenant=maintenant)  # coupe-circuit fournisseur OpenCode (24/10)
    if repos:
        return f"en repos (coupe-circuit fournisseur) : {repos}"
    spec =(_lire_registre().get("agents") or {}).get(nom)
    if not isinstance(spec, dict):
        return None
    susp = spec.get("suspendu")
    if not susp:
        return None
    if isinstance(susp, dict):
        return f"suspendu depuis {susp.get('depuis', '?')} (motif : {susp.get('motif', '')})"
    return f"suspendu (motif : {susp})"


def _interactive_clis() -> tuple:
    """Qui est INTERACTIF ? Le registre le dit ; ce fichier ne le decide plus.

    Owner 2026-07-26 : « distinguer l'agy interactif de l'agy autonome, par leur
    identite ET leur facon d'agir ». La facon d'agir est desormais DECLAREE dans
    `config/agent_identities.json` (`mode`/`drains`/`acts`/`wake`) ; la recopier
    en dur ici, c'etait deux verites qui pouvaient diverger en silence -- et
    l'alignement doit EMANER du registre, pas d'une constante de module.

    Concretement : UN SEUL acteur, plusieurs noms, TOUS VIVANTS --
    AGY = GEMINI = ANTIGRAVITY, plus leurs variantes AGY_HEADLESS/GEMINI_HEADLESS,
    AGY_DAEMON/GEMINI_DAEMON, AGY_HOOK/GEMINI_HOOK. Ce qui a change, c'est la
    MARQUE du produit (Gemini CLI -> Antigravity), PAS les identifiants : un
    identifiant qui s'authentifie et rend 200 est vivant, et le revoquer
    couperait AGY. Ce seul acteur a DEUX facons d'agir :
      interactive  surface IDE ouverte par l'owner, draine tasks.db par claim,
                   EXECUTE -> ses taches lui sont RESERVEES (cette liste) ;
      autonomous   service, depile le POSTAL, REPOND (n'execute pas) -> aucune
                   tache ne lui est reservee ici ; l'execution passe par le
                   relais WORKER_CODE, qui lance agy en mode agent.

    Union avec le plancher, jamais remplacement : un registre illisible ou
    incomplet doit degrader vers PLUS de reservation, jamais moins.
    """
    noms = set(_INTERACTIVE_FLOOR)
    for _nom, _spec in (_lire_registre().get("agents") or {}).items():
        if isinstance(_spec, dict) and _spec.get("mode") == "interactive":
            noms.add(str(_nom).upper())
    return tuple(sorted(noms))


def _fetch_batch(conn: sqlite3.Connection, agent_filter: str | None) -> list:
    """Taches `pending` servables, SANS celles dont une entree n'est pas livree (31/10 : BLOQUE_PAR_DEPENDANCE, dit
    une fois par tache au journal ; elle repart d'elle-meme quand ses entrees passent `done`)."""
    lignes = _fetch_batch_brut(conn, agent_filter)
    pretes = []
    for r in lignes:
        ok, motif = _dependances_pretes(conn, r[0])
        if ok:
            pretes.append(r)
        elif r[0] not in _BLOQUEES_DITES:
            _BLOQUEES_DITES.add(r[0])
            if "done_en_echec" in motif:
                # Ne repartira jamais seule : WARNING visible. Non close ici : l'assigneur tranche
                # (re-assigner l'entree ou retirer depend_de).
                log.warning(f"  {str(r[0])[:24]} : {motif} -- BLOQUEE, a l'assigneur de trancher")
            else:
                log.info(f"  {str(r[0])[:24]} : {motif}")
    return pretes


def _fetch_batch_brut(conn: sqlite3.Connection, agent_filter: str | None) -> list:
    if agent_filter:
        return conn.execute(
            "SELECT id, description, agent, job_id FROM tasks"
            " WHERE status='pending' AND agent=?"
            " ORDER BY created_at LIMIT ?",
            (agent_filter, BATCH_SIZE),
        ).fetchall()
    # Autonome (sans filtre) : EXCLURE les taches ciblant un CLI interactif nomme,
    # ET celles du relais code. Mesure 2026-07-31 : sans l'OAuth agy (profil owner,
    # invisible en SYSTEM) cet executor ne peut que RELAYER vers un repondeur, qui
    # accuse reception sans executer. Une tache visiblement EN ATTENTE vaut mieux
    # qu'un relais qui ne fait rien : elle est servie par l'instance dediee
    # (NokidoTaskExecutorAgy, runAs=interactive, --agent WORKER_CODE), et le
    # silence de cette instance se lit dans son propre heartbeat.
    #
    # LISTE BLANCHE, plus liste noire (mesure 2026-10-17 16:16) : `NOT IN (CLI interactifs)` laissait toute cible
    # NOUVELLE tomber ici -- l'instance dediee OPENCODE_GPTOSS s'est fait rafler sa tache, servie par groq, qui a
    # invente un commit clos OK_DONE SUCCESS sans juge. Le generique ne prend que ce qu'il sait servir.
    _serv = tuple(sorted(_servables_par_le_generique()))
    if not _serv:
        return []
    _ph = ",".join("?" * len(_serv))
    return conn.execute(
        "SELECT id, description, agent, job_id FROM tasks"
        f" WHERE status='pending' AND upper(agent) IN ({_ph})"
        " ORDER BY created_at LIMIT ?",
        (*_serv, BATCH_SIZE),
    ).fetchall()


def _publier_tache(conn: sqlite3.Connection, kind: str, task_id: str, statut: str) -> None:
    """Publie une transition de tache sur le bus d'essaim (19/10 : le miroir sandbox/reflexion.jsonl, suivi par
    /api/swarm/stream, ne portait AUCUN task_*). Best-effort ; NOKIDO_BUS_TACHES=0 coupe (le conftest des NR le pose)."""
    if os.environ.get("NOKIDO_BUS_TACHES", "1") == "0":
        return
    try:
        row = conn.execute("SELECT agent FROM tasks WHERE id=?", (task_id,)).fetchone()
        from nokido_agent.app.forge_swarm_bus import publish
        publish(kind, {"task_id": str(task_id)[:60], "agent": str((row or [""])[0] or "?").upper(), "statut": statut})
    except Exception as e:  # noqa: BLE001 - le flux ne casse jamais la transition qu'il raconte
        log.debug(f"  bus d'essaim : {kind} non publie ({type(e).__name__})")


def _creation_processus(pid: int):
    """Heure de creation PROUVEE du pid, ou None si illisible (psutil absent, acces refuse...)."""
    try:
        import psutil
        return float(psutil.Process(int(pid)).create_time())
    except Exception:  # noqa: BLE001 - muet-ok : None = illisible, l'appelant s'abstient
        return None


def _vivacite_processus(pid, cree):
    """True = vivant (meme pid ET meme creation), False = PROUVE mort (absent ou pid recycle), None = illisible."""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return None
    try:
        if not psutil.pid_exists(int(pid)):
            return False
        vraie = float(psutil.Process(int(pid)).create_time())
    except psutil.NoSuchProcess:
        return False
    except Exception:  # noqa: BLE001
        return None
    if cree is None:
        return None
    return abs(vraie - float(cree)) <= 2.0


def _estampiller_proprietaire(conn: sqlite3.Connection, task_id: str) -> None:
    """Note pid + creation de l'executeur sur la tache qu'il vient de prendre (meilleur effort)."""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        for nom, decl in (("exec_pid", "INTEGER"), ("exec_cree", "REAL")):
            if nom not in cols:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {nom} {decl}")
        conn.execute("UPDATE tasks SET exec_pid=?, exec_cree=? WHERE id=?",
                     (os.getpid(), _creation_processus(os.getpid()), task_id))
        conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("[orpheline] proprietaire non note pour %s (%s)", task_id, e)


def requalifier_orphelines(agent_filter: str | None, vivacite=None) -> dict:
    """Au demarrage : les taches `running` de CET agent dont le proprietaire est PROUVE mort repassent `pending`
    (INTERROMPUE, journalise). Proprietaire inconnu/illisible -> abstention (jamais reprise d'une tache peut-etre vivante)."""
    vivacite = vivacite or _vivacite_processus
    requalifiees, abstenues = [], []
    conn = _db()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        if "exec_pid" not in cols or "exec_cree" not in cols:
            return {"requalifiees": [], "abstenues": []}
        q = "SELECT id, agent, exec_pid, exec_cree FROM tasks WHERE status='running'"
        args: tuple = ()
        if agent_filter:
            q += " AND upper(agent)=?"
            args = (agent_filter.upper(),)
        for r in conn.execute(q, args).fetchall():
            if r["exec_pid"] is None:
                abstenues.append(r["id"])
                log.warning("[orpheline] %s running sans proprietaire note : abstention", r["id"])
                continue
            try:
                v = vivacite(r["exec_pid"], r["exec_cree"])
            except Exception:  # noqa: BLE001
                v = None
            if v is False:
                cur = conn.execute(
                    "UPDATE tasks SET status='pending', exec_pid=NULL, exec_cree=NULL, updated_at=?, "
                    "result=COALESCE(result,'') || ? WHERE id=? AND status='running'",
                    (time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "\n[INTERROMPUE] proprietaire pid %s mort : remise en pending" % r["exec_pid"], r["id"]))
                if cur.rowcount == 1:
                    requalifiees.append(r["id"])
                    log.warning("[orpheline] %s INTERROMPUE (pid %s mort) -> pending", r["id"], r["exec_pid"])
            elif v is None:
                abstenues.append(r["id"])
                log.warning("[orpheline] %s vivacite illisible (pid %s) : abstention", r["id"], r["exec_pid"])
        conn.commit()
    finally:
        conn.close()
    return {"requalifiees": requalifiees, "abstenues": abstenues}


# Tentative retenue par CET executeur quand il prend la tache : la cloture n'est acceptee que pour elle.
_TENTATIVE_PRISE: dict[str, int] = {}


def _retenir_tentative(conn: sqlite3.Connection, task_id: str) -> None:
    try:
        r = conn.execute("SELECT attempt FROM tasks WHERE id=?", (task_id,)).fetchone()
        if r is not None:
            _TENTATIVE_PRISE[str(task_id)] = int(r[0] or 0)
    except Exception as e:  # noqa: BLE001
        log.warning(f"  [tentative] lecture KO {str(task_id)[:24]}: {type(e).__name__}: {e}")


def _ecriture_refusee(conn: sqlite3.Connection, task_id: str, attendue, action: str) -> None:
    r = conn.execute("SELECT status, attempt FROM tasks WHERE id=?", (task_id,)).fetchone()
    lu = f"status={r[0]} attempt={r[1]}" if r else "tache absente"
    log.warning(f"  [tentative] ECRITURE REFUSEE ({action}) {str(task_id)[:24]} : tentative attendue={attendue}, "
                f"etat lu: {lu} (executeur perime ; pas un echec de la tache)")


def _mark_running(conn: sqlite3.Connection, task_id: str) -> None:
    ensure_lease_schema(conn)
    conn.execute(
        "UPDATE tasks SET status='running', updated_at=?, garde=COALESCE(garde,0)+1 WHERE id=?",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), task_id),
    )
    conn.commit()
    _retenir_tentative(conn, task_id)
    _estampiller_proprietaire(conn, task_id)
    _publier_tache(conn, "task_running", task_id, "running")


# ── RECLAMER PAR LE SUJET PROUVE (owner 2026-10-17 : « les jetons devraient identifier convenablement les cibles des
# CLI si tu appliques les RFC ») ─────────────────────────────────────────────────────────────────────────────────────
# Mesure 16:16 : generique et instance dediee ont pris la MEME tache (job_dcaa1a81) -- _mark_running ne verifie pas
# qu'elle est encore pending -- et aucun claim ne disait QUI reclamait. Contrat : RFC 7519 `sub` (seul l'agent cible,
# ou un sujet a delegation declaree, reclame), RFC 8693 `act` (l'acteur est trace, jamais substitue au sujet), claim
# atomique pending -> running. L'identite non PROUVEE est refusee -- en mode applique seulement : observer d'abord.
def _servables_par_le_generique() -> frozenset:
    """Ce que l'executeur sans --agent sait servir par fournisseur texte : PROVIDER_CHAIN, hors CLI interactifs, hors
    relais code, hors agents delegues a une instance dediee (CODEX, MISTRAL -> Vibe, OPENCODE_*, AGY)."""
    exclus = set(_interactive_clis()) | {CODE_AGENT} | set(_AGY_DELEGATE_AGENTS)
    return frozenset(k for k in PROVIDER_CHAIN if k.upper() not in exclus and _delegation_pour(k) is None)


def _attester_par_le_superviseur(sub: str, declares: dict | None = None, chaine: list | None = None,
                                 services: dict | None = None) -> tuple[bool, str]:
    """(prouve, preuve) : l'identite se DEMANDE a l'organe qui lance le process, jamais a son drapeau --agent.

    30/10 (docs/enquetes/identite_executeurs_claim_20261030.md) : `prouve` valait False en dur. Preuve : ce process
    DESCEND du pid que le superviseur declare pour un service (runAs interactive : le superviseur note le LANCEUR, son
    enfant execute -- d'ou la remontee de parente, jamais l'egalite de pid), et ce service porte `--agent <sub>` dans
    services.toml (aucun --agent : sujet TASK_EXECUTOR). Superviseur muet, aucun ancetre declare, services.toml
    illisible : NON prouve, et le motif le dit (UNKNOWN n'est pas OUI). Arguments injectables pour le NR."""
    sub = (sub or "").upper()
    try:
        try:  # primitive UNIQUE d'attestation (30/10), partagee avec le coffre cloisonne (COF-1)
            from nokido_agent.tools.forge_process_inventory import service_porteur
        except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
            from forge_process_inventory import service_porteur
        service, profondeur, motif = service_porteur(declares, chaine, timeout=5.0)
    except Exception as e:  # noqa: BLE001
        return False, f"superviseur ILLISIBLE ({type(e).__name__})"
    if service is None:
        return False, motif
    if services is None:
        try:
            import tomllib
            with open(Path(__file__).resolve().parent.parent / "proxy_deno" / "core" / "services.toml", "rb") as fh:
                services = {s.get("name"): list(s.get("args") or []) for s in tomllib.load(fh).get("service", [])}
        except Exception as e:  # noqa: BLE001
            return False, f"services.toml ILLISIBLE ({type(e).__name__}) pour {service}"
    if service not in services:
        return False, f"{service} absent de services.toml"
    args = [str(a) for a in services[service]]
    declare = args[args.index("--agent") + 1].upper() if "--agent" in args[:-1] else "TASK_EXECUTOR"
    if declare != sub:
        return False, f"{service} porte --agent {declare}, pas {sub}"
    return True, f"descendant (profondeur {profondeur}) du pid declare de {service}, qui porte --agent {declare}"


def _identite_executeur(agent_filter: str | None) -> dict:
    """Qui reclame ? `sub` = l'agent dont cette instance porte la file, `act` = le process executeur qui agit pour lui.
    `prouve` ne vient QUE de `_attester_par_le_superviseur` (30/10) -- jamais du seul drapeau --agent."""
    sub = (agent_filter or "TASK_EXECUTOR").upper()
    try:
        prouve, preuve = _attester_par_le_superviseur(sub)
    except Exception as e:  # noqa: BLE001
        prouve, preuve = False, f"attestation ILLISIBLE ({type(e).__name__})"
    ident = {"sub": sub, "act": "TASK_EXECUTOR", "prouve": bool(prouve),
             "pourquoi": ("sujet ATTESTE par le superviseur : " if prouve else "sujet NON prouve : ") + preuve}
    if not agent_filter:
        ident["servables"] = sorted(_servables_par_le_generique())
    return ident


def _claim_enforce() -> bool:
    """Observer avant d'enforcer : le refus d'un sujet non prouve ne s'applique que sur LAFORGE_CLAIM_ENFORCE=1. La liste
    blanche du generique et l'atomicite du claim, elles, s'appliquent toujours."""
    return os.environ.get("LAFORGE_CLAIM_ENFORCE", "") == "1"


def _autoriser_reclamation(agent_tache: str, identite: dict | None) -> tuple[bool, str]:
    ag = (agent_tache or "").upper()
    ident = identite or {}
    sub = str(ident.get("sub") or "").upper()
    if not ident.get("prouve"):
        return False, f"identite NON PROUVEE (sujet {sub or '?'}) pour une tache {ag} : UNKNOWN n'est pas OUI"
    if sub == ag:
        act = f", acteur {ident['act']}" if ident.get("act") else ""
        return True, f"sujet prouve {sub} = agent cible{act}"
    if ag in {str(x).upper() for x in (ident.get("servables") or ())}:
        return True, f"sujet prouve {sub} habilite a servir {ag} (delegation declaree)"
    return False, f"sujet prouve {sub} n'est pas l'agent cible {ag} et n'a aucune delegation declaree pour lui"


def _reclamer(conn: sqlite3.Connection, task_id: str, agent_tache: str, identite: dict | None,
              enforce: bool = True) -> bool:
    """pending -> running UNE fois, au nom d'un sujet autorise. Rend False si le sujet est refuse (mode applique) ou si un
    autre executeur l'a deja prise (le second le sait au lieu de la traiter en double)."""
    ok, pourquoi = _autoriser_reclamation(agent_tache, identite)
    if not ok:
        if enforce:
            log.warning(f"  [claim] REFUS {str(task_id)[:24]} : {pourquoi}")
            return False
        log.info(f"  [claim][observe] refuserait {str(task_id)[:24]} : {pourquoi}")
    # 24/10 23:00:48 : sans progress_at, une tache requalifiee gardait celui de sa tentative PRECEDENTE et le
    # reclaim_expired d'une autre instance la remettait en pending 28 ms apres la reclamation. Reclamer = progresser.
    _maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
    ensure_lease_schema(conn)   # progress_at garanti, comme reclaim_expired (schema ancien : no such column)
    cur = conn.execute(
        "UPDATE tasks SET status='running', updated_at=?, progress_at=?, garde=COALESCE(garde,0)+1 "
        "WHERE id=? AND status='pending' AND upper(agent)=?",
        (_maintenant, _maintenant, task_id, (agent_tache or "").upper()))
    conn.commit()
    if cur.rowcount != 1:
        log.info(f"  [claim] {str(task_id)[:24]} deja reclamee ou reaffectee : un autre executeur l'a prise")
        return False
    _retenir_tentative(conn, task_id)
    _estampiller_proprietaire(conn, task_id)
    _publier_tache(conn, "task_running", task_id, "running")   # 19/10 : la voie AGY ne passait pas par _mark_running
    return True


# ── UN TRAVAIL DECLARE FINI DOIT ETRE DANS LE DEPOT (owner 2026-07-31) ────────
# Motif observe TROIS FOIS dans la meme soiree : (1) une tache passee a `done` en
# 20 s sur un accuse de reception, sans qu'aucune veille ne bouge ; (2) le P1 des
# topics extractifs livre par AGY — fix ET test — qui dormait en working tree non
# commite, invisible du depot et de la CI ; (3) sept fichiers modifies non commites,
# dont un daemon entier migre vers agy. A chaque fois le meme ecart : « c'est fait »
# d'un cote, `git status` de l'autre. Aucun statut ne mesure cet ecart ; git seul le
# sait. On le lui demande donc au moment EXACT ou une tache se declare reussie.
#
# CE GARDE CRIE, IL NE BLOQUE PAS. Le travail peut etre legitimement non commite
# (revue en cours, lot groupe) ; en faire un echec fabriquerait des faux negatifs
# la ou une mention visible suffit. Le cout des deux erreurs n'est pas symetrique :
# taire une non-livraison la rend invisible pour toujours, la signaler a tort coute
# une ligne de journal.
_RE_CHEMIN = re.compile(r"\b((?:app|tools|tests|config|proxy_deno|docs)/[\w./-]+\.\w{1,4})\b")


_RE_NEGATION = re.compile(r"\b(?:pas|jamais|sans|aucun|aucune|ni|not|never|no|didn't|untouched|inchang\w*|intact\w*)\b"
                          r"|n'ai\s+pas", re.IGNORECASE)
_RE_PRODUCTION = re.compile(r"\b(?:produit\w*|cree\w*|ecrit\w*|livre\w*|modifi\w*|ajout\w*|"
                            r"created|wrote|written|added|modified|delivered)\b", re.IGNORECASE)
_RE_POINTER_REF = re.compile(r'"pointer_ref"\s*:\s*"([^"\n]*)"')


def _chemins_declares(texte: str) -> set:
    """Chemins que le texte DECLARE produits : ceux du pointer_ref, et ceux des lignes affirmant une production.
    « je n'ai pas touche X » ne declare rien (faux signal 7/11 : config/agent_identities.json)."""
    texte = texte.replace("\\", "/")
    out = set()
    for ref in _RE_POINTER_REF.findall(texte):
        out.update(_RE_CHEMIN.findall(ref))
    for ligne in texte.splitlines():
        if _RE_NEGATION.search(ligne) or not _RE_PRODUCTION.search(ligne):
            continue
        out.update(_RE_CHEMIN.findall(ligne))
    return out


def _fichiers_non_livres(*textes: str, workdir=None) -> list:
    """Parmi les chemins CITES par la tache, lesquels ne sont pas dans le depot ?

    Rend une liste de (chemin, etat) ou etat vaut 'modifie' ou 'non suivi'. Une
    liste vide signifie soit « tout est livre », soit « la tache ne nommait aucun
    fichier » — les deux se lisent pareil ici, et c'est voulu : on ne CRIE que sur
    une preuve, jamais sur une absence d'information.
    """
    cites = set()
    for t in textes:
        if t:
            cites.update(_chemins_declares(t))
    if not cites:
        return []
    # Le controle porte sur le repertoire de travail de la TACHE, jamais sur ROOT (sale d'un autre auteur).
    # Repertoire absent / git en echec = ILLISIBLE : dit, journalise, jamais « rien a signaler ».
    illisible = sorted((c, "illisible") for c in cites)
    if not workdir or not Path(str(workdir)).is_dir():
        log.warning(f"[livraison] repertoire de travail absent ({workdir!r}) — verification ILLISIBLE")
        return illisible
    try:
        import subprocess as _sp_git  # module-level absent ici : import local, comme ailleurs

        r = _sp_git.run(
            ["git", "-c", "safe.directory=*", "-C", str(workdir), "status", "--porcelain", "-uall"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if r.returncode != 0:
            log.warning(f"[livraison] git status rc={r.returncode} dans {workdir} — verification ILLISIBLE")
            return illisible
    except Exception as e:  # noqa: BLE001
        log.warning(f"[livraison] git injoignable ({type(e).__name__}) — verification ILLISIBLE")
        return illisible
    sales = {}
    for ligne in (r.stdout or "").splitlines():
        if len(ligne) < 4:
            continue
        code, chemin = ligne[:2], ligne[3:].strip().strip('"').replace("\\", "/")
        sales[chemin] = "non suivi" if code == "??" else "modifie"
    return sorted((c, sales[c]) for c in cites if c in sales)


CAP_RESULTAT = 8000
"""Plafond du livrable ecrit dans `tasks.result`, cible de `pointer_ref`."""


def _borner(txt: str, cap: int = CAP_RESULTAT) -> str:
    """Borne un livrable en DISANT combien a ete jete.

    Le contrat M2M (cf. `forge_mcp_registry`, mesure du 2026-07-26) est clair :
    l'enveloppe `detail` est un ACCUSE court, et le LIVRABLE vit dans
    `tasks.result`, dont `pointer_ref` donne l'adresse. Encore faut-il que le
    livrable dise la verite sur lui-meme.

    Mesure du 2026-09-18 : quatre resultats de tri faisaient EXACTEMENT 8 000
    caracteres. Ce n'etait pas leur longueur, c'etait la borne — et rien ne le
    signalait. Un tableau de classification coupe en plein milieu de ligne se lit
    comme un tableau complet : on croit avoir trie 60 items quand on en a trie 41.
    C'est le motif `borne_trop_serree` deja paye le 2026-07-25 (`text[:3000]` avait
    detruit le corps de 377 documents de veille, en silence).

    Une borne qui se tait fabrique des resultats faux ; une borne qui se nomme
    laisse un rattrapage possible. On ne change donc PAS le plafond — on le rend
    visible, dans le livrable lui-meme, la ou le lecteur regarde.
    """
    txt = txt or ""
    if len(txt) <= cap:
        return txt
    jetes = len(txt) - cap
    return txt[:cap] + (
        f"\n\n[TRONQUE — {cap} caracteres conserves sur {len(txt)} ; "
        f"{jetes} NON enregistres. Le livrable est INCOMPLET : relancer la tache "
        f"en la decoupant, ou faire ecrire la reponse dans un fichier.]"
    )


def _mark_done(conn: sqlite3.Connection, task_id: str, result: str, ok: bool, workdir=None) -> None:
    status = "completed" if ok else "failed"
    if ok:
        attente = _fichiers_non_livres(result, workdir=workdir)
        if attente and all(e == "illisible" for _c, e in attente):
            result = (f"[LIVRAISON NON VERIFIABLE — repertoire de travail de la tache illisible ; "
                      f"{len(attente)} fichier(s) cite(s) non controles] {result}")
            attente = []
        if attente:
            detail = ", ".join(f"{c} ({e})" for c, e in attente)
            log.warning(f"  [LIVRAISON INCOMPLETE] {task_id[:24]} se declare reussie mais "
                        f"{len(attente)} fichier(s) cite(s) ne sont PAS dans le depot : {detail}")
            result = (f"[LIVRAISON INCOMPLETE — {len(attente)} fichier(s) hors depot : "
                      f"{detail}] {result}")
    att = _TENTATIVE_PRISE.get(str(task_id))
    if att is None:
        # Aucune prise dans ce processus (refus avant claim : tache encore pending) : cloture historique.
        conn.execute(
            "UPDATE tasks SET status=?, result=?, updated_at=? WHERE id=?",
            (status, _borner(result), time.strftime("%Y-%m-%dT%H:%M:%S"), task_id),
        )
        conn.commit()
        _publier_tache(conn, "task_done", task_id, status)
        return
    cur = conn.execute(
        "UPDATE tasks SET status=?, result=?, updated_at=? WHERE id=? AND status IN ('running','acknowledged') "
        "AND COALESCE(attempt,0)=?",
        (status, _borner(result), time.strftime("%Y-%m-%dT%H:%M:%S"), task_id, att),
    )
    conn.commit()
    if cur.rowcount != 1:
        _ecriture_refusee(conn, task_id, att, "cloture")
        return
    _TENTATIVE_PRISE.pop(str(task_id), None)
    _publier_tache(conn, "task_done", task_id, status)


def _emit_m2m_result(task_id: str, ok: bool, token: str) -> None:
    """Emet un task_result M2M au demandeur (postal), pas seulement _mark_done en base.

    Chainon manquant mesure 2026-07-23 : sans ceci l'executor autonome traitait
    des taches sans JAMAIS renvoyer de M2M — le demandeur devait sonder la base.
    Envelope M2M-conforme (intent + pointer_ref, champs courts). Best-effort.
    """
    intent = "OK_DONE" if ok else "ERR_INTERNAL"
    payload = json.dumps({
        "intent": intent,
        "status_code": "SUCCESS" if ok else "FAILURE",
        "pointer_ref": f"tasks.db:{task_id}",
    }, ensure_ascii=False)
    r = _hub_call("task", {"action": "result", "task_id": task_id,
                           "intent": intent, "result": payload}, token, timeout=30)
    if isinstance(r, dict) and r.get("error"):
        log.warning(f"M2M result emit KO {task_id[:24]}: {r['error']}")


# ── Executeur de code AUTONOME, mode DRY-RUN (owner 2026-07-23) ────────────────
# Ligne rouge = organe auto-modifiant. Bord choisi : l'executor PROPOSE seulement
# (plan SEARCH/REPLACE -> blackboard), n'APPLIQUE JAMAIS. L'apply = action
# humaine / ring<=1 (governed_edit, le videur). Zero ecriture autonome sur le repo.
CODE_AGENT = "WORKER_CODE"
_CODE_PLAN_ZONE = "code_proposals"
# Agents dont les taches vont au VRAI agy — delegate (agy --print, il EXECUTE et
# sa sortie JSON est redirigee) si l'OAuth est lisible, sinon relais postal vers
# l'auto-repondeur. JAMAIS un provider LLM generique. ANTIGRAVITY = le pair de
# debat : l'owner veut SON intelligence, pas groq (2026-08-13, "apifier en
# redirigeant sa sortie"). Le service interactif (--agent ANTIGRAVITY,
# runAs=interactive) voit l'OAuth -> delegate reussit (verdict "DISPONIBLE" 31/07).
_AGY_DELEGATE_AGENTS = {CODE_AGENT, "ANTIGRAVITY"}
# RELAIS AGY (owner 23/07) : l'exécuteur ne PENSE pas — il passe la tâche à AGY
# autonome, le lance, relève sa réponse, la sert à l'émetteur. L'intelligence = AGY.
RELAY_TIMEOUT_S = int(os.environ.get("TASK_EXEC_RELAY_TIMEOUT", "1500"))
RELAY_POLL_S = 5.0
# Rayon d'explosion : signaler (ne pas appliquer de toute facon) les cibles sensibles.
_SENSITIVE_HINTS = ("firewall", "rbac", "gate", "keeper", "task_executor",
                    "semantic_firewall", "membrane", "secrets", "vault", "hub")


# ── ACCUSE DE RECEPTION != COMPTE RENDU (mesure 2026-07-31) ───────────────────
# Le relais marquait SUCCESS des qu'une reponse EXISTAIT. Mesure : la tache
# « rejouer les 7 veilles nommees » est passee a done en moins de 20 s sur
# « Demande validee. Consignes bien recues et alignees. Perimetre retenu pour
# l'execution : ... » — et les 7 veilles n'avaient PAS bouge (dates inchangees,
# compteurs a zero). Un echec qui se declare succes est la pire des pannes : le
# demandeur classe la tache et personne ne refait le travail.
#
# LIMITE ASSUMEE : juger un texte reste une heuristique. Elle est calibree pour
# se tromper du bon cote — au doute on CONTINUE D'ATTENDRE plutot que de clore,
# car un accuse de reception n'est pas une fin, c'est un intermediaire. L'agent
# peut tres bien accuser reception PUIS rendre compte ; on ne perd donc rien a
# patienter, et on ne gagne rien a clore tot.
_ACCUSE_MARQUEURS = (
    "bien recu", "bien recue", "consignes recues", "demande validee",
    "perimetre retenu", "je vais", "je commence", "je procede", "j'execute",
    "sera fait", "c'est note", "compris", "acknowledged", "understood",
    "will proceed", "i will", "let me", "on y va",
)
# Signes d'un travail ACCOMPLI. Uniquement des formes VERBALES au passe ou des
# faits chiffres — jamais des noms. Mesure du 31-07 : la premiere version listait
# « rapport » et « resultat », et elle a RATE le texte meme qui avait menti, parce
# qu'il promettait un « Rapport de restitution par veille ». Un nom apparait aussi
# bien dans la promesse que dans le compte rendu ; seul le verbe accompli tranche.
_COMPTE_RENDU_MARQUEURS = (
    "j'ai ", "nous avons", "ont ete", "a ete", "termine", "acheve", "modifie",
    "cree", "supprime", "ajoute", "corrige", "n_ingested", "n_stored",
    "commit ", "traceback", "exception", "erreur", "echec", "completed", "failed",
)


# Un REFUS DU MODELE qui sert l'agent n'est pas un compte rendu — et surtout, ce
# n'est pas un travail fait.
#
# Mesure du 2026-09-18 : une revue de code demandee a ANTIGRAVITY est revenue
# avec « Sorry, I cannot fulfill your request. I am unable to perform
# vulnerability scanning... » (377 caracteres), et la tache a ete enregistree
# `status='done'`. Le garde-fou du MODELE etait servi comme LIVRABLE. Meme motif
# que le 2026-09-16, ou « User Safety: safe » etait rendu comme du HTML par la
# generation d'interface — consigne alors dans `web_hub/ui_generate.py` et nulle
# part ailleurs. Un piege consigne dans UN module ne protege que ce module : d'ou
# cette fonction, au meme endroit que son jumeau `_est_accuse_reception`, dont
# elle reprend le patron a trois conditions cumulatives.
#
# Elle rend le MOTIF, pas un booleen : « la tache a echoue » se lit mieux quand
# on sait qu'elle a ete refusee plutot que plantee. Un refus n'est pas un bug a
# chercher, c'est une formulation a reprendre.
_REFUS_MARQUEURS = (
    "i cannot fulfill", "i can't fulfill", "sorry, i cannot", "sorry, i can't",
    "i am unable to", "i'm unable to", "i cannot assist", "i can't assist",
    "unable to comply", "i cannot provide", "i can't provide",
    "as an ai language model", "user safety",
    "je ne peux pas repondre", "je ne peux pas effectuer", "je ne suis pas en mesure",
    "je ne peux pas vous aider",
)


def est_refus_du_modele(txt: str) -> str | None:
    """Le motif du refus si la reponse est un garde-fou de modele, sinon None.

    Trois conditions cumulatives, comme pour l'accuse de reception :
      - une formule de refus reconnue ;
      - AUCUN signe de travail accompli (memes marqueurs, pour ne pas mordre sur
        un rapport qui CITERAIT un refus en le commentant) ;
      - un texte court, un refus ne detaille rien.

    LIMITE ASSUMEE, et elle penche dans l'autre sens que celle de son jumeau : au
    doute on ne signale PAS. Rater un refus laisse un faux vert, le signaler a
    tort ferait echouer un vrai travail — et un garde qui crie a faux se fait
    desarmer. Le cout est donc asymetrique dans ce sens-la.
    """
    if not txt:
        return None
    import unicodedata as _ud

    plat = "".join(c for c in _ud.normalize("NFD", txt.lower())
                   if _ud.category(c) != "Mn")
    motif = next((m for m in _REFUS_MARQUEURS if m in plat), None)
    if not motif:
        return None
    if any(m in plat for m in _COMPTE_RENDU_MARQUEURS):
        return None
    if len(txt) >= 1500:
        return None
    return motif


def _est_accuse_reception(txt: str) -> bool:
    """La reponse promet-elle un travail au lieu d'en rendre compte ?

    Trois conditions cumulatives, pour ne refuser qu'a coup sur :
      - elle porte un marqueur de reception ou d'intention FUTURE ;
      - elle ne porte AUCUN signe de travail accompli ;
      - elle est courte (un vrai compte rendu de tache detaille ce qu'il a fait).
    """
    if not txt:
        return False
    import unicodedata as _ud

    plat = "".join(c for c in _ud.normalize("NFD", txt.lower())
                   if _ud.category(c) != "Mn")
    if not any(m in plat for m in _ACCUSE_MARQUEURS):
        return False
    if any(m in plat for m in _COMPTE_RENDU_MARQUEURS):
        return False
    return len(txt) < 1500


def _hub_text(resp: dict) -> str:
    """Extrait le texte d'un retour hub tools/call (result.content[0].text)."""
    try:
        c = resp.get("result", {}).get("content", [{}])
        return c[0].get("text", "") if c else ""
    except Exception:
        return ""


def _read_spec(description: str, token: str) -> tuple[str, str]:
    """Resout le pointer_ref M2M (blackboard:zone/key) -> (spec_text, target_file)."""
    pointer = ""
    try:
        d = json.loads(description) if description.strip().startswith("{") else {}
        pointer = d.get("pointer_ref", "") or ""
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 940, exc_info=True)
    m = re.search(r"blackboard:([\w-]+)/([\w./-]+)", pointer)
    if not m:
        return "", ""
    zone, key = m.group(1), m.group(2)
    # La cle cible le fait : sans elle, une grosse zone rend l'index des cles (economie contexte 1/11) et une
    # zone de plus de `limit` faits masquait un fait ancien.
    resp = _hub_call("blackboard_read_zone", {"zone_name": zone, "key": key}, token, timeout=30)
    body = _hub_text(resp)
    spec = ""
    try:
        data = json.loads(body)
        facts = data.get("facts") or data.get("zone") or data
        if isinstance(facts, dict):
            facts = list(facts.values())
        for f in (facts or []):
            fk = (f.get("key") if isinstance(f, dict) else "") or ""
            if fk == key:
                spec = f.get("fact") or f.get("value") or ""
                break
    except Exception:
        spec = body  # repli : tout le corps
    if not spec:
        spec = body
    tgt = ""
    mt = re.search(r"\b((?:app|tools|tests)/[\w./-]+\.py)\b", spec)
    if mt:
        tgt = mt.group(1)
    return spec, tgt


def _focused_context(spec: str, cur: str, window: int = 4500) -> str:
    """Contexte CIBLÉ : un gros fichier tronqué à cur[:6000] = le HAUT (imports),
    pas le code à patcher (mesure 23/07 : forge_mcp_registry 357k). On cherche dans
    le fichier le 1er identifiant distinctif nommé par la spec et on renvoie une
    fenêtre autour. Fallback = début du fichier."""
    import re as _re
    cands = _re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?", spec)
    seen = set()
    for tok in cands:
        core = tok.split(".")[-1]
        if len(core) < 6 or core in seen:
            continue
        seen.add(core)
        idx = cur.find(core)
        if idx > 6000:  # trouvé hors du haut déjà visible
            start = max(0, idx - 1500)
            return cur[start:start + window]
    return cur[:6000]


def _propose_code_change(task: sqlite3.Row, token: str) -> None:
    """DRY-RUN : lit la spec, fait planifier des blocs SEARCH/REPLACE par un LLM,
    POSTE le plan au blackboard, marque awaiting_approval, emet M2M PLAN_READY.
    N'ecrit RIEN sur le repo (apply = humain/ring<=1 via governed_edit)."""
    task_id = task["id"]

    def _fail(reason: str) -> None:
        log.warning(f"PROPOSE FAIL {task_id[:24]}: {reason}")  # le hub ecrase tasks.result via M2M
        conn = _db(); _mark_done(conn, task_id, f"PROPOSE FAIL: {reason}", False); conn.close()
        try:
            _hub_call("task", {"action": "result", "task_id": task_id, "intent": "ERR_INTERNAL",
                               "result": json.dumps({"intent": "ERR_INTERNAL",
                               "status_code": "FAILURE", "pointer_ref": f"tasks.db:{task_id}"})},
                      token, timeout=30)
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 1004, exc_info=True)

    spec, target = _read_spec(task["description"] or "", token)
    if not spec:
        return _fail("pointer_ref/spec introuvable")
    if not target:
        return _fail("spec ne nomme aucun fichier cible app|tools|tests/*.py")

    cur = _hub_text(_hub_call("read", {"action": "file", "path": target}, token, timeout=30))
    if not cur:
        return _fail(f"lecture cible KO: {target}")

    sensitive = any(h in target.lower() for h in _SENSITIVE_HINTS)
    prompt = (
        "Tu es un patcheur. Produis UNIQUEMENT des blocs SEARCH/REPLACE (format Aider) "
        "pour appliquer la spec au fichier, sans prose. Chaque bloc :\n"
        "<<<<<<< SEARCH\\n<code exact existant>\\n=======\\n<code remplace>\\n>>>>>>> REPLACE\\n\\n"
        f"FICHIER: {target}\\n\\nSPEC:\\n{spec[:2500]}\\n\\nCONTENU ACTUEL (extrait cible):\\n{_focused_context(spec, cur)}"
    )
    # LLM LOCAL (ollama) — jamais le cloud pour l'exec autonome (owner 23/07)
    ok, plan = _ask_local(prompt)
    if not (ok and plan and "SEARCH" in plan and "REPLACE" in plan):
        return _fail("LLM local sans blocs SEARCH/REPLACE: " + str(plan)[:100])

    fact = json.dumps({
        "task_id": task_id, "target": target, "sensitive": sensitive,
        "apply_via": "governed_edit(path=target, blocks=<plan>) — humain/ring<=1",
        "plan": plan[:6000],
    }, ensure_ascii=False)
    _hub_call("blackboard_propose_fact", {"zone_name": _CODE_PLAN_ZONE, "key": task_id,
              "category": "patch", "fact": fact, "trust": 0.6}, token, timeout=30)

    note = f"plan -> blackboard:{_CODE_PLAN_ZONE}/{task_id}" + (" [SENSIBLE]" if sensitive else "")
    conn = _db()
    _att = _TENTATIVE_PRISE.get(str(task_id))
    if _att is None:
        conn.execute("UPDATE tasks SET status='awaiting_approval', result=?, updated_at=? WHERE id=?",
                     (_borner(note), time.strftime("%Y-%m-%dT%H:%M:%S"), task_id))
    else:
        _c = conn.execute("UPDATE tasks SET status='awaiting_approval', result=?, updated_at=? WHERE id=? "
                          "AND status='running' AND COALESCE(attempt,0)=?",
                          (_borner(note), time.strftime("%Y-%m-%dT%H:%M:%S"), task_id, _att))
        if _c.rowcount != 1:
            _ecriture_refusee(conn, task_id, _att, "awaiting_approval")
    conn.commit(); conn.close()
    try:
        _hub_call("task", {"action": "result", "task_id": task_id, "intent": "PLAN_READY",
                           "result": json.dumps({"intent": "PLAN_READY", "status_code": "AWAITING_APPROVAL",
                           "pointer_ref": f"blackboard:{_CODE_PLAN_ZONE}/{task_id}"})}, token, timeout=30)
    except Exception as e:
        log.warning(f"M2M PLAN_READY emit KO: {e}")
    log.info(f"  PROPOSE {task_id[:24]} -> {note}")


def _peut_lancer_agy() -> tuple[bool, str]:
    """La capacite se MESURE, elle ne se declare pas.

    `_delegate_to_agy` est le seul chemin qui EXECUTE (agy en mode agent) ; il a
    ete abandonne parce que le compte de service ne voit pas l'OAuth agy, qui vit
    dans le profil owner. Plutot qu'un drapeau qui mentirait, on VERIFIE les deux
    conditions reelles : le binaire est lancable, et son dossier de configuration
    est LISIBLE depuis ce compte. Un « Acces refuse » n'est pas une absence — on
    le distingue, et on le DIT dans la raison rendue.
    """
    import os as _os

    agy_bin = _os.environ.get("LAFORGE_AGY_BIN",
                              r"%USERPROFILE%\AppData\Local\agy\bin\agy.exe")
    if not _os.path.exists(agy_bin):
        return False, f"binaire introuvable ou illisible depuis ce compte: {agy_bin}"
    if not _os.access(agy_bin, _os.X_OK):
        return False, f"binaire non executable par ce compte: {agy_bin}"
    home = _os.environ.get("LAFORGE_AGY_HOME", r"%USERPROFILE%")
    # 7/11 : agy 1.x range son profil sous ~/.gemini/antigravity-cli ; AppData/Local/agy ne porte que le binaire.
    conf = _os.path.join(home, ".gemini", "antigravity-cli")
    if not _os.path.exists(conf):
        conf = _os.path.join(home, "AppData", "Local", "agy")
    try:
        if _os.path.isdir(conf):
            _os.listdir(conf)
        elif _os.path.isfile(conf):
            with open(conf, "rb") as _f:
                _f.read(1)
        else:
            _os.listdir(conf)
    except PermissionError:
        return False, f"ACCES REFUSE au profil agy ({conf}) — compte de service, pas owner"
    except FileNotFoundError:
        return False, f"profil agy absent: {conf}"
    except Exception as e:  # noqa: BLE001
        return False, f"profil agy illisible ({type(e).__name__}): {conf}"
    return True, "binaire lancable et profil agy lisible"


def _agy_permission_args(env=None) -> list:
    """Drapeaux de PERMISSION d'agy pour une delegation non interactive.

    Veille lot_B_12 / C_02 (« quand l'agent est l'adversaire ») : la delegation lancait agy
    avec `--dangerously-skip-permissions`, qui APPROUVE TOUT. `agy --help` (releve par
    l'owner le 2026-09-24) n'offre AUCUNE politique fine : seulement ce drapeau,
    `--mode accept-edits|plan` et `--sandbox` (restrictions du terminal). Defaut retenu :
    `--sandbox --mode accept-edits` + `--print-timeout` -- les editions passent, le
    terminal est restreint, et une permission restee sans reponse en mode --print se
    termine au lieu de pendre. `LAFORGE_AGY_PERMISSIONS=legacy` restaure l'ancien
    comportement : repli EXPLICITE, jamais implicite.

    Correction 2026-10-02 : « aucune politique fine » etait FAUX -- l'aide ne la montre pas,
    mais la doc agy (antigravity.google/docs/cli/features) en decrit une, persistante, dans
    `settings.json` : `"permissions": {"allow": ["command(git)", ...], "deny": [...]}`.
    Cout mesure de `--sandbox` sous Windows : une invite UAC « ExeBox Admin Broker » A CHAQUE
    lancement (le bac est un AppContainer ; une acceptation UAC n'est jamais memorisee).
    DECISION OWNER 2026-10-02 : on GARDE `--sandbox` et l'invite par delegation, plutot que
    d'echanger le confinement du terminal contre une liste allow/deny. Ne pas reproposer sans
    fait nouveau. Consequence connue : sous AppContainer, le `.git` du worktree (dans
    Nokido/.git/worktrees) est hors du bac -- AGY s'arrete en NEED_HUMAN_APPROVAL pour committer.
    """
    import os as _os
    env = _os.environ if env is None else env
    if (env.get("LAFORGE_AGY_PERMISSIONS") or "sandbox").strip().lower() == "legacy":
        return ["--dangerously-skip-permissions"]
    borne = max(60, int(RELAY_TIMEOUT_S) - 30)
    return ["--sandbox", "--mode", "accept-edits", "--print-timeout", "%ds" % borne]


import contextvars as _contextvars

# 29/10 (GO owner) : UN WORKTREE PAR TACHE. Deux taches du meme agent partageaient son worktree (job_3a3347e0 et
# job_b6c4b5a1) : l'executeur committait les fichiers de l'une sous l'etiquette de l'autre. Le chemin de la tache
# en cours est porte par ce contexte ; tous les `_workdir_*` le rendent EN PRIORITE (claude, opencode, codex, agy,
# mistral). Hors contexte (controles de capacite) : worktrees d'agent historiques, inchanges.
_WT_TACHE: "_contextvars.ContextVar" = _contextvars.ContextVar("nokido_wt_tache", default=None)


class WorktreeTacheRefuse(RuntimeError):
    """Creation du worktree de tache impossible : la tache est REFUSEE, jamais de repli sur un arbre partage."""


def _wt_tache_arme() -> bool:
    """Interrupteur NOKIDO_WORKTREE_PAR_TACHE : ARME par defaut, `0/off/false/non` le desarme."""
    return os.environ.get("NOKIDO_WORKTREE_PAR_TACHE", "1").strip().lower() not in ("0", "off", "false", "non", "no")


def _wt_court(task_id) -> str:
    """Identifiant court UNIQUE par tache. 29/10 soir : les 12 DERNIERS caracteres valaient `detaskassign` pour
    toute tache `job_<hex>_<ts>_claude_task_assign` -> 4 taches refusees. Tete aleatoire + empreinte de l'id."""
    try:  # 31/10 : SOURCE UNIQUE dans forge_worktree (la portee de lecture du hub doit nommer le meme dossier)
        from forge_worktree import court_tache
        return court_tache(task_id)
    except ImportError:
        pass  # muet-ok : module absent (checkout partiel) -> meme calcul ci-dessous, resultat identique
    import hashlib
    s = re.sub(r"[^A-Za-z0-9]", "", str(task_id).replace("job_", "", 1))
    if len(s) <= 12:
        return s or "tache"
    return s[:8] + hashlib.sha1(str(task_id).encode("utf-8")).hexdigest()[:4]


def _depend_de(conn, task_id) -> list:
    """Entrees declarees d'une tache (colonne `depend_de`, liste JSON d'ids). Colonne absente / vide -> []."""
    try:
        row = conn.execute("SELECT depend_de FROM tasks WHERE id=?", (task_id,)).fetchone()
    except sqlite3.OperationalError:
        return []  # muet-ok : base d'avant le 31/10, aucune tache n'a d'entree
    if not row or not row[0]:
        return []
    try:
        v = json.loads(row[0])
    except (TypeError, ValueError):
        return [str(row[0])]  # illisible : garde la valeur, la porte la dira inconnue (bloque, jamais servie a tort)
    return [str(x) for x in (v if isinstance(v, list) else [v]) if str(x).strip()]


def _dependances_pretes(conn, task_id) -> tuple:
    """(True, "") si TOUTES les entrees de la tache sont livrees (`done`) ; sinon (False, motif BLOQUE_PAR_DEPENDANCE).

    Owner 31/10 : « un travail 1 et un travail 2 peuvent ensuite nourrir un travail 3 ». Une entree en cours, echouee
    ou inconnue BLOQUE la tache -- elle n'est ni servie ni declaree morte (constitution : BLOQUE_PAR_DEPENDANCE != DEAD)."""
    entrees = _depend_de(conn, task_id)
    if not entrees:
        return True, ""
    manque = []
    for dep in entrees:
        r = conn.execute("SELECT status FROM tasks WHERE id=?", (dep,)).fetchone()
        st = (r[0] if r else None) or "inconnue"
        if st != "done":
            manque.append("%s:%s" % (dep, st))
            continue
        cause = _cause_echec_de(conn, dep)
        if cause not in _CAUSES_LIVREES:
            manque.append("%s:done_en_echec(cause=%s)" % (dep, cause))
    if manque:
        return False, "BLOQUE_PAR_DEPENDANCE entree(s) non livree(s) : %s" % ", ".join(manque)
    return True, ""


# 7/11 : liste blanche. Un `done` n'est livre que si sa cause_echec est vide. `FAUX_VERT` (statut A_REVOIR : done,
# a relire) reste traite comme livre AUJOURD'HUI -- inchange. Toute autre valeur (QUOTA, DELAI, NON_LIVRE,
# INCONNU, valeur inattendue) bloque.
_CAUSES_LIVREES = ("", "FAUX_VERT")


def _cause_echec_de(conn, task_id) -> str:
    """cause_echec ('' si vide ou colonne absente : base sans echec classe)."""
    try:
        r = conn.execute("SELECT cause_echec FROM tasks WHERE id=?", (task_id,)).fetchone()
    except sqlite3.OperationalError:
        return ""
    return str((r[0] if r else "") or "").strip()


_BLOQUEES_DITES: set = set()
# Entrees fusionnees par worktree de tache (cle = chemin resolu) : la consigne de l'agent les NOMME (31/10).
_ENTREES_FUSIONNEES: dict = {}


def _texte_entrees(workdir) -> str:
    """Bloc de consigne listant les entrees fusionnees dans ce worktree ; "" sans entree (prefixe de cache intact)."""
    try:
        faits = _ENTREES_FUSIONNEES.get(str(Path(workdir).resolve()))
    except OSError:
        faits = None
    if not faits:
        return ""
    lignes = ["- %s : %s" % (dep, ("branche %s, deja FUSIONNEE dans ton repertoire" % br) if br
                              else "livree sans commit (rien a fusionner)") for dep, br in faits]
    return ("\n[Executeur Nokido] ENTREES de cette tache (travaux amont, livres) :\n" + "\n".join(lignes)
            + "\nLeurs fichiers sont DEJA dans ton repertoire de travail : lis-les la, ne les recree pas.")


def _fusionner_entrees(chemin: Path, depot: Path, task_id, entrees: list) -> list:
    """Fusionne dans le worktree de la tache la branche `tache/*/<court>` de chaque entree livree. Rend [(entree,
    branche ou None)]. Conflit -> WorktreeTacheRefuse NOMMANT l'entree (le worktree est defait par l'appelant)."""
    faits = []
    for dep in entrees:
        r = _wt_git(depot, "for-each-ref", "--format=%(refname:short)", "refs/heads/tache/*/" + _wt_court(dep))
        branches = [b for b in (r.stdout or "").split() if b]
        if not branches:
            faits.append((dep, None))  # livree sans commit (reponse seule) : rien a fusionner, et c'est dit
            continue
        m = _wt_git(chemin, "merge", "--no-ff", "--no-edit", "-m", "entree %s (%s)" % (dep, branches[0]), branches[0])
        if m.returncode != 0:
            _wt_git(chemin, "merge", "--abort")
            raise WorktreeTacheRefuse("fusion de l'entree %s (%s) impossible : %s"
                                      % (dep, branches[0], (m.stdout or m.stderr or "")[-200:]))
        faits.append((dep, branches[0]))
    return faits


def _wt_racine_taches() -> Path:
    return ROOT.parent / "nokido_worktrees" / "taches"


_WT_REPRIS: set = set()
"""Worktrees de tache REPRIS avec leur travail non committe : ce travail est celui de la tache, pas un reste
d'autrui -- il ne doit pas etre exclu du commit (7/11 : job_63bd8f5d, job_bd3bd640 `done` sans livrer)."""


class _SalesIllisibles(frozenset):
    """Etat « sale avant la tache » perdu en reprise : ensemble vide, mais `_committer_pour_agent` refuse de committer."""


_NOM_SALES_AVANT = "nokido_sales_avant.json"   # sous le .git de CE worktree : jamais suivi


def _fichier_sales_avant(wt):
    r = _wt_git(wt, "rev-parse", "--absolute-git-dir")
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    return Path(r.stdout.strip()) / _NOM_SALES_AVANT


def _sales_avant_de(wt) -> frozenset:
    """Fichiers sales AVANT la tache (exclus du commit). L'etat est pris a la PREMIERE ouverture du worktree et
    conserve sous son .git ; la reprise le relit (le travail repris reste livrable, pas le sale d'avant la tache).
    Reprise sans etat lisible = `_SalesIllisibles` : prudence, le commit sera refuse."""
    import json as _json
    reprise = False
    try:
        reprise = str(Path(wt).resolve()) in _WT_REPRIS
    except OSError as e:
        log.warning(f"  _sales_avant_de : chemin du worktree illisible ({type(e).__name__})")
    a_git = (Path(wt) / ".git").exists()
    try:
        f = _fichier_sales_avant(wt) if a_git else None
    except Exception as e:  # noqa: BLE001
        log.warning(f"  _sales_avant_de : .git illisible ({type(e).__name__})")
        f = None
    if f is not None and f.is_file():
        try:
            return frozenset(str(x) for x in _json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning(f"  _sales_avant_de : etat conserve illisible ({type(e).__name__})")
            return _SalesIllisibles()
    if reprise:
        if a_git:
            log.warning("  _sales_avant_de : reprise SANS etat d'avant la tache conserve -- commit refuse")
            return _SalesIllisibles()
        return frozenset()
    etat = _chemins_status(wt) or frozenset()
    if f is not None:
        try:
            f.write_text(_json.dumps(sorted(etat)), encoding="utf-8")
        except OSError as e:
            log.warning(f"  _sales_avant_de : etat d'avant la tache NON conserve ({type(e).__name__})")
    return etat


def _wt_git(depot, *a, timeout=120):
    import subprocess as _sp
    return _sp.run(["git", "-c", "safe.directory=*", "-C", str(depot), *a], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=timeout, env=_env_git())


# Owner 30/10 « 180 000 tokens c'est encore enorme » : un tour AGY SANS outil coute 22 336 tokens (sonde
# job_ca153392), dont ~19 000 de fichiers de contexte recharges a CHAQUE tour (GEMINI.md, AGENTS.md, CLAUDE.md, et
# RULES_SHARED.md importe deux fois). La consigne de l'executeur porte deja la regle de la tache : le worktree de
# tache recoit ce texte MINIMAL, en skip-worktree (git ne le voit ni en status, ni au commit, ni au retrait).
_CONTEXTE_ALLEGE = (
    "# Tache deleguee par Nokido (contexte allege)\n\n"
    "La consigne de l'executeur fait foi. Regles permanentes :\n"
    "- aucune commande shell ; agir par les outils du hub (ou lancer ses tests via run_job tools/forge_nr_worktree.py sans jamais inventer la sortie) ;\n"
    "- lecture par pointeur : get_file_skeleton puis read_function_body, jamais un gros fichier entier ;\n"
    "- jamais de balayage de la base RAG (%NOKIDO_DATA%\embeddings.db) : `rag` ou FTS `MATCH` seulement ;\n"
    "- secrets au coffre, jamais affiches ni copies ;\n"
    "- ecrire seulement sous le repertoire de la tache, par blocs cibles ; ne modifier aucun test existant.\n")
_FICHIERS_CONTEXTE = ("GEMINI.md", "AGENTS.md", "CLAUDE.md")
# Owner 30/10 « impose et adapte selon le fonctionnement de chaque CLI » : chaque CLI lit SON fichier (AGY
# GEMINI.md ; Codex, OpenCode, Vibe AGENTS.md ; Claude headless CLAUDE.md) -- les trois sont alleges pour TOUS les
# agents delegues dans un worktree de tache (le texte minimal porte les regles permanentes).
_AGENTS_CONTEXTE_ALLEGE = frozenset({"*"})


def _retirer_fichiers_prives_worktree(chemin) -> int:
    """Retire du worktree d'un agent expose les fichiers que `sujets_prives` declare prives, en skip-worktree comme
    `_alleger_contexte_tache` : git reste propre et le commit de l'agent ne les supprime pas. Mesure du 6/11 : 65 fichiers
    prives suivis sur alpha, lisibles localement par le CLI, hors du filtre du hub. Rend le nombre retire ; un echec LEVE,
    et la tache ne part pas. Limite : les objets git restent lisibles par une commande (`git show`)."""
    from nokido_agent.app.forge_sovereign_membrane import fichiers_prives
    chemin = Path(chemin)
    r = _wt_git(chemin, "ls-files", "-z")
    if r.returncode != 0:
        raise RuntimeError("ls-files refuse (%s)" % r.returncode)
    prives = fichiers_prives([f for f in r.stdout.split("\0") if f])
    for debut in range(0, len(prives), 50):
        r = _wt_git(chemin, "update-index", "--skip-worktree", *prives[debut:debut + 50])
        if r.returncode != 0:
            raise RuntimeError("skip-worktree refuse (%s)" % r.returncode)
    for f in prives:
        (chemin / f).unlink(missing_ok=True)
    return len(prives)


def _bloc_memoire_travail(intention: str) -> str:
    """Memoire de travail servie a la tache deleguee (geste 2a cognition, owner 8/11) : le MEME rendu, borne a
    1200 caracteres, que Claude recoit a chaque tour. Un echec est DIT dans le bloc, jamais tu et jamais propage :
    une memoire muette ne casse pas la tache mais ne se fait pas passer pour un succes."""
    try:
        try:
            import nokido_agent.app.forge_memoire_active as _fma
        except Exception:  # noqa: BLE001 - checkout plat : repli sur le module voisin d'app/
            import forge_memoire_active as _fma
        mem = _fma.rendre(_fma.projeter(intention or "", budget_chars=1200))
        mem = (mem or "").strip()[:1200]
    except Exception as e:  # noqa: BLE001 - la tache part quand meme, mais l'echec est nomme
        return "\n\n# Memoire de travail (Nokido) -- ILLISIBLE (%s)\n" % type(e).__name__
    return "\n\n# Memoire de travail (Nokido)\n%s\n" % (mem or "(vide)")


def _alleger_contexte_tache(chemin, intention: str = "") -> list:
    """Remplace les fichiers de contexte SUIVIS du worktree par _CONTEXTE_ALLEGE + le bloc « Memoire de travail
    (Nokido) » (meme rendu que Claude, budget 1200 car.), en skip-worktree. Un fichier non suivi n'est jamais cree ;
    un echec laisse le fichier d'origine (cout, pas panne) et le DIT. Rend les fichiers alleges."""
    chemin = Path(chemin)
    # Pas d'intention = pas de memoire a projeter : on n'ajoute pas de bloc vide (et le contexte allege reste
    # au format d'origine). La tache deleguee, elle, porte toujours sa description.
    bloc = _bloc_memoire_travail(intention) if intention else ""
    faits = []
    for nom in _FICHIERS_CONTEXTE:
        f = chemin / nom
        try:
            if not f.is_file() or _wt_git(chemin, "ls-files", "--error-unmatch", nom).returncode != 0:
                continue
            if _wt_git(chemin, "update-index", "--skip-worktree", nom).returncode != 0:
                log.warning(f"  contexte allege : skip-worktree refuse sur {nom} -- fichier d'origine garde")
                continue
            f.write_text(_CONTEXTE_ALLEGE + bloc, encoding="utf-8")
            faits.append(nom)
        except Exception as e:  # noqa: BLE001
            log.warning(f"  contexte allege : {nom} garde ({type(e).__name__}: {e})")
    return faits


def _wt_tache_ouvrir(agent: str, task_id, depot=None, racine=None, depend_de=None) -> Path:
    """Worktree detache depuis la tete d'alpha, branche tache/<agent>/<id court>. Echec = WorktreeTacheRefuse.
    `depend_de` (31/10) : les branches des entrees livrees sont FUSIONNEES dans le worktree neuf -- un travail 3 nait
    avec les livrables des travaux 1 et 2 ; conflit = refus nomme, worktree et branche neufs defaits."""
    depot = Path(depot) if depot else ROOT
    racine = Path(racine) if racine else _wt_racine_taches()
    ag = re.sub(r"[^a-z0-9_]", "_", str(agent).lower())
    court = _wt_court(task_id)
    chemin = racine / ("%s_%s" % (ag, court))
    branche = "tache/%s/%s" % (ag, court)
    try:
        racine.mkdir(parents=True, exist_ok=True)
        # Reprise apres redemarrage : le `finally` n'a pas tourne. Le claim (running) exclut deux executions de la
        # MEME tache ; un reste PROPRE se retire (la branche garde les commits), un reste SALE est refuse (travail).
        if chemin.exists() and not _wt_tache_retirer(chemin, depot=depot):
            # 30/10 : executeur relance pendant la tache -> le travail partiel de CETTE tache bloquait sa reprise
            # (refus, puis reaffectation en boucle). Meme tache, meme branche, claim exclusif : on REPREND dedans.
            tete = _wt_git(chemin, "rev-parse", "--abbrev-ref", "HEAD")
            if tete.returncode == 0 and (tete.stdout or "").strip() == branche:
                log.warning(f"  worktree de tache {chemin.name} : REPRISE du travail non committe de cette tache")
                _WT_REPRIS.add(str(chemin.resolve()))
                return chemin
            raise WorktreeTacheRefuse("worktree de tache deja present avec du travail non committe (%s) : "
                                      "conserve, a examiner" % chemin)
        r = _wt_git(depot, "worktree", "add", "--detach", str(chemin), "alpha")
        if r.returncode != 0:
            raise WorktreeTacheRefuse("git worktree add a echoue : %s" % (r.stderr or r.stdout)[-300:])
        existe = _wt_git(depot, "rev-parse", "--verify", "-q", "refs/heads/" + branche).returncode == 0
        r = _wt_git(chemin, "checkout", "-q", branche) if existe else _wt_git(chemin, "checkout", "-q", "-b", branche)
        if r.returncode != 0:
            _wt_git(depot, "worktree", "remove", "--force", str(chemin))
            raise WorktreeTacheRefuse("branche %s impossible : %s" % (branche, (r.stderr or r.stdout)[-300:]))
        if depend_de:
            try:
                faits = _fusionner_entrees(chemin, depot, task_id, list(depend_de))
            except WorktreeTacheRefuse:
                _wt_git(depot, "worktree", "remove", "--force", str(chemin))
                if not existe:
                    _wt_git(depot, "branch", "-D", branche)
                raise
            log.info(f"  worktree de tache {chemin.name} : entrees fusionnees "
                     f"{', '.join('%s<-%s' % (d, b or 'sans commit') for d, b in faits)}")
            _ENTREES_FUSIONNEES[str(chemin.resolve())] = faits
    except WorktreeTacheRefuse:
        raise
    except Exception as e:  # noqa: BLE001 -- tout echec = refus motive
        raise WorktreeTacheRefuse("creation du worktree de tache impossible (%s: %s)" % (type(e).__name__, e)) from e
    return chemin


def _creation_interrompue(chemin) -> bool:
    """Reste d'un `worktree add` coupe avant l'extraction (pid de l'executeur mort, 30/10, job_7234db4e) : tete
    DETACHEE et index VIDE, donc toute l'arborescence vue « supprimee ». L'agent ne travaille jamais la (sa branche
    est posee avant lui) : ce reste ne porte aucun travail, il bloquait pourtant chaque nouvelle tentative."""
    try:
        if _wt_git(chemin, "symbolic-ref", "-q", "HEAD").returncode == 0:
            return False
        r = _wt_git(chemin, "ls-files")
        return r.returncode == 0 and not (r.stdout or "").strip()
    except Exception:  # noqa: BLE001 -- doute = travail possible, on garde
        return False


def _wt_tache_retirer(chemin, depot=None) -> bool:
    """Retire le worktree APRES la livraison (la branche reste). Jamais avec du travail non committe : True = retire."""
    chemin = Path(chemin)
    depot = Path(depot) if depot else ROOT
    try:
        interrompue = bool(_chemins_travail(str(chemin))) and _creation_interrompue(chemin)
        if interrompue:
            log.warning(f"  worktree de tache {chemin} : creation interrompue (tete detachee, index vide) -- retire")
        elif _chemins_travail(str(chemin)):
            log.warning(f"  worktree de tache {chemin} CONSERVE : travail non committe")
            return False
        # seule la config d'agent (non livrable) peut rester : --force ne perd alors rien. Creation interrompue :
        # git laisse le verrou « initializing », que seul un DOUBLE --force leve (mesure 30/10).
        forces = ("--force", "--force") if interrompue else ("--force",)
        r = _wt_git(depot, "worktree", "remove", *forces, str(chemin))
        if r.returncode != 0:
            log.warning(f"  worktree de tache {chemin} NON retire : {(r.stderr or r.stdout)[-200:]}")
            # 30/10 : git DESENREGISTRE le worktree puis echoue sur le dossier (« Invalid argument ») -> un reliquat
            # de ~5 100 fichiers reste. Desenregistre et sans .git : on efface le reliquat, et on DIT ce qui resiste.
            _enr = _wt_enregistres(depot)
            if _enr is not None and chemin.resolve() not in _enr and not (chemin / ".git").exists():
                ok, erreurs = _rmtree_reliquat(chemin)
                log.warning(f"  reliquat {chemin.name} : {'EFFACE' if ok else 'RESISTE'} {erreurs or ''}")
                return ok
            return False
        return True
    except Exception as e:  # noqa: BLE001
        log.warning(f"  worktree de tache {chemin} NON retire ({type(e).__name__})")
        return False


def _wt_enregistres(depot=None):
    """Chemins (resolus) des worktrees ENREGISTRES dans git ; None si git est illisible (alors on n'efface rien)."""
    try:
        r = _wt_git(Path(depot) if depot else ROOT, "worktree", "list", "--porcelain")
        if r.returncode != 0:
            return None
        return {Path(l[9:].strip()).resolve() for l in (r.stdout or "").splitlines() if l.startswith("worktree ")}
    except Exception:  # noqa: BLE001
        return None


def _rmtree_reliquat(chemin) -> tuple:
    """Efface un reliquat de worktree : leve la lecture seule et retente UNE fois ; rend (efface, {erreur: nb, ex.}).
    L'erreur Windows exacte de ce qui resiste est rendue (winerror), jamais avalee."""
    import shutil
    import stat as _stat
    from collections import Counter
    erreurs, exemples = Counter(), {}

    def _sur_erreur(fn, path, exc):
        e = exc[1] if isinstance(exc, tuple) else exc
        try:
            os.chmod(path, _stat.S_IWRITE)
            fn(path)
            return
        except Exception as e2:  # noqa: BLE001
            e = e2
        cle = "%s winerror=%s" % (type(e).__name__, getattr(e, "winerror", None))
        erreurs[cle] += 1
        exemples.setdefault(cle, str(path)[-120:])

    shutil.rmtree(chemin, False, _sur_erreur)  # 3e argument positionnel = gestionnaire d'erreur
    resume = {k: (v, exemples[k]) for k, v in erreurs.most_common(3)}
    return (not Path(chemin).exists()), resume


def _wt_orphelins(racine=None, age_h: float = 24.0) -> list:
    """Worktrees de tache plus vieux que `age_h` : SIGNALES (log), jamais supprimes.

    30/10 (owner « hygiene systematique ») : un RELIQUAT -- dossier que git a deja desenregistre, sans .git, plus
    vieux que 10 min -- n'est plus un worktree : il est EFFACE (les commits vivent sur la branche de tache), et ce qui
    resiste est DIT avec l'erreur Windows exacte. Enregistrements git illisibles : on n'efface rien."""
    racine = Path(racine) if racine else _wt_racine_taches()
    if not racine.is_dir():
        return []
    _enr = _wt_enregistres()
    if _enr is not None:
        _jeune = time.time() - 600
        for p in sorted(x for x in racine.iterdir() if x.is_dir()):
            try:
                if p.resolve() in _enr or (p / ".git").exists() or p.stat().st_mtime > _jeune:
                    continue
            except OSError as e:
                log.warning(f"  reliquat {p.name} ILLISIBLE ({e}) -- laisse en place")
                continue
            ok, erreurs = _rmtree_reliquat(p)
            log.warning(f"  reliquat de worktree {p.name} : {'EFFACE' if ok else 'RESISTE'} {erreurs or ''}")
    limite = time.time() - age_h * 3600
    vieux = sorted(p for p in racine.iterdir() if p.is_dir() and p.stat().st_mtime < limite)
    for p in vieux:
        log.warning(f"  worktree de tache ORPHELIN (> {age_h:g} h) : {p} -- a examiner, non supprime")
    return vieux


def _avec_worktree_tache(agent: str, task, token: str, fn) -> None:
    """Execute `fn()` dans un worktree dedie a la tache. Creation impossible : tache REFUSEE (pas de repli)."""
    if not _wt_tache_arme():
        fn()
        return
    try:
        _wt_orphelins()
        _c_dep = _db()
        try:
            _entrees = _depend_de(_c_dep, task["id"])
        finally:
            _c_dep.close()
        wt = _wt_tache_ouvrir(agent, task["id"], depend_de=_entrees)
    except WorktreeTacheRefuse as e:
        log.error(f"  {str(task['id'])[:24]} REFUSEE : {e}")
        _clore_delegation(task["id"], token, False, "[REFUSEE worktree par tache] %s" % e)
        return
    if (("*" in _AGENTS_CONTEXTE_ALLEGE or str(agent).upper() in _AGENTS_CONTEXTE_ALLEGE)
            and os.environ.get("LAFORGE_CONTEXTE_ALLEGE", "1") != "0"):
        _intention = (task.get("description") if hasattr(task, "get") else task["description"]) or ""
        _faits = _alleger_contexte_tache(wt, _intention)
        log.info(f"  {str(task['id'])[:24]} contexte allege : {_faits or 'aucun fichier suivi'}")
    from nokido_agent.app.forge_sovereign_membrane import agent_expose
    if agent_expose(agent):
        try:
            log.info(f"  {str(task['id'])[:24]} fichiers prives retires du worktree : {_retirer_fichiers_prives_worktree(wt)}")
        except Exception as e:  # noqa: BLE001 - la tache ne part pas avec des fichiers prives : refus dit, pas de repli
            log.error(f"  {str(task['id'])[:24]} REFUSEE : fichiers prives non retires ({type(e).__name__})")
            _wt_tache_retirer(wt)
            _clore_delegation(task["id"], token, False, "[SUJET PRIVE] fichiers prives non retires du worktree (%s)" % type(e).__name__)
            return
    jeton = _WT_TACHE.set(wt)
    try:
        fn()
    finally:
        _WT_TACHE.reset(jeton)
        _wt_tache_retirer(wt)


def _workdir_agy() -> str:
    """Repertoire de travail d'AGY : LAFORGE_AGY_WORKDIR > son worktree dedie > racine partagee (DIT).

    2026-10-01 : l'owner a recu deux fois des invites d'approbation venant d'AGY. Cause etablie
    (reponse d'AGY + ce code) : AGY tourne en `--sandbox` confine a `--add-dir <workdir>` =
    la racine PARTAGEE, alors que la mission lui demandait son worktree
    (nokido_worktrees/antigravity) -- hors de son bac a sable, chaque commande exigeait un
    « BypassSandbox » que l'owner devait approuver. Le worktree dedie est aussi la convention
    du depot (RULES_SHARED : « le worktree protege la MESURE »)."""
    import os as _os
    if _WT_TACHE.get() is not None:
        return str(_WT_TACHE.get())
    env = _os.environ.get("LAFORGE_AGY_WORKDIR")
    if env:
        return env
    wt = ROOT.parent / "nokido_worktrees" / "antigravity"
    if (wt / ".git").exists():
        return str(wt)
    log.warning(f"  DELEGATE worktree AGY absent ({wt}) -- repli sur la racine PARTAGEE")
    return str(ROOT)


def _env_git() -> dict:
    """L'environnement SANS les variables GIT_* heritees (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE...),
    que posent les hooks git ou des tests voisins : elles detournent `git -C <workdir>` vers un AUTRE
    depot. Mesure 2026-10-02 (CI de reference f340e9ca4) : HEAD avait bouge, rev-list rendait vide."""
    import os as _os
    # GIT_CEILING_DIRECTORIES est GARDEE : elle ne detourne rien, elle borne la recherche du depot.
    return {k: v for k, v in _os.environ.items()
            if not k.upper().startswith("GIT_") or k.upper() == "GIT_CEILING_DIRECTORIES"}


def _hors_alpha(workdir: str) -> list:
    """["--not", "alpha"] si la branche locale `alpha` existe dans le depot, sinon [] (comportement inchange)."""
    import subprocess as _sp
    try:
        r = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "rev-parse", "--verify", "-q",
                     "refs/heads/alpha"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=20, env=_env_git())
    except Exception:  # noqa: BLE001 - illisible : pas d'exclusion, comportement d'avant
        return []
    return ["--not", "refs/heads/alpha"] if r.returncode == 0 and r.stdout.strip() else []


class _EtatGit(tuple):
    """(HEAD, n) qui se deballe TOUJOURS en deux (lecteurs existants intacts) et porte en plus `preposes` : les chemins
    deja modifies ou non suivis AVANT la tache (`_chemins_status`). R3, 17/10 : la « livraison » de Vibe 074957e12
    n'etait que la config de l'agent + le RED pose avant la tache, emportes par l'auto-commit -- jugee SUCCESS."""

    def __new__(cls, head, n, preposes=()):
        t = super().__new__(cls, (head, n))
        t.preposes = frozenset(preposes or ())
        return t


def _etat_git(workdir: str) -> tuple:
    """(HEAD, nb de fichiers modifies ou non suivis) du workdir ; (None, None) si illisible."""
    import subprocess as _sp
    try:
        h = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "rev-parse", "HEAD"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                    env=_env_git())
        s = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "status", "--porcelain"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                    env=_env_git())
    except Exception:  # noqa: BLE001 - illisible : dit par (None, None)
        return None, None
    if h.returncode != 0 or s.returncode != 0:
        return None, None
    # 19/10 : la configuration de session d'un agent (_CONFIG_AGENT : .vibe/, .agy/...) n'est pas du TRAVAIL -- comptee,
    # elle faisait d'une panne 429 de Vibe un « travail laisse non committe ».
    config = tuple(c.lower() for c in _CONFIG_AGENT)
    travail = [ligne for ligne in s.stdout.splitlines() if ligne.strip()
               and not ligne[3:].strip().strip('"').lower().startswith(config)]
    return _EtatGit(h.stdout.strip(), len(travail), _chemins_status(workdir) or ())


def _effet_observe(workdir: str, avant: tuple) -> str:
    """Ce que la delegation a PRODUIT dans le workdir, a cote de ce qu'AGY DECLARE.

    2026-10-01 : AGY a rendu OK_DONE/SUCCESS sur une mission de trois NR sans en committer
    aucun (ACCEPTED declare, ACHIEVED absent). L'emetteur lit desormais l'effet dans le
    resultat lui-meme : commits produits (HEAD avant -> apres) et fichiers non commites."""
    import subprocess as _sp
    h_av, _n_av = avant
    h_ap, n_ap = _etat_git(workdir)
    if h_av is None or h_ap is None:
        return "[effet observe] git ILLISIBLE dans %s : rien n'est prouve" % workdir
    pourquoi = ""
    if h_av == h_ap:
        n = 0
    else:
        try:
            # `--` (2026-10-02, CI de reference 479480200, cause enfin DITE par le rc) : sans lui git
            # teste aussi la plage comme CHEMIN ; sous un worktree profond (CI), <workdir>/<a>..<b>
            # depasse MAX_PATH et le stat rend ENAMETOOLONG -- fatal, au lieu d'ENOENT -- d'ou
            # « failed to stat '<a>..<b>': Filename too long », rc 128.
            # PROPRES SEULEMENT (2026-10-13) : `--first-parent --no-merges`. Sans eux, une fusion d'alpha dans la
            # branche de l'agent comptait toute l'histoire qu'elle apporte -- « commits produits : 1338 » pour une
            # delegation qui n'avait RIEN committe de son travail (5 fichiers laisses non commites), verdict SUCCESS.
            plage = "%s..%s" % (h_av, h_ap)
            # 22/10 : un ff-only / rebase sur alpha rend alpha LINEAIRE dans HEAD ; `--not alpha` ecarte tout ce
            # qu'alpha contient deja (ce n'est pas le travail du delegue).
            r = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "rev-list", "--count", "--first-parent",
                         "--no-merges", plage, *_hors_alpha(workdir), "--"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=20, env=_env_git())
            # rc VERIFIE (2026-10-02, CI de reference f340e9ca4) : `int(stdout or 0)` faisait d'un
            # rev-list en ECHEC « 0 commit » -- HEAD avait bouge, l'effet etait annonce nul.
            if r.returncode == 0 and r.stdout.strip().isdigit():
                n = int(r.stdout.strip())
                rf = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "rev-list", "--count", "--first-parent",
                              "--merges", plage, "--"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20, env=_env_git())
                if rf.returncode == 0 and rf.stdout.strip().isdigit() and int(rf.stdout.strip()):
                    pourquoi = " [+ %s fusion(s) : l'histoire qu'elles apportent n'est PAS du travail produit]" % (
                        rf.stdout.strip())
            else:
                n, pourquoi = -1, " [rev-list rc=%s : %s]" % (r.returncode, (r.stderr or "").strip()[:160])
        except Exception as e:  # noqa: BLE001 - illisible, dit
            n, pourquoi = -1, " [rev-list : %s]" % type(e).__name__
    return "[effet observe] commits produits : %s (%s..%s) ; fichiers non commites : %s%s" % (
        n if n >= 0 else "ILLISIBLE", h_av[:9], h_ap[:9], n_ap, pourquoi)


_INTENTS_NON_FAITS = ("NEED_HUMAN_APPROVAL", "NEED_CLARIFY", "BUDGET_EXCEEDED")


_RE_POINTER = re.compile(r'\\?"pointer_ref\\?"\s*:\s*\\?"([^"]+)')
_RE_INTENT = re.compile(r'\\?"intent\\?"\s*:\s*\\?"([A-Z_]+)')


def _pointer_refs(reponse: str) -> list[str]:
    """Tous les `pointer_ref` d'une reponse, en clair OU echappes.

    22/10 : CLAUDE_HEADLESS (`claude -p` stream-json) rend le JSON final dans le champ `result` du flux, donc
    echappe ; la regex stricte etait muette -> [RIEN PRODUIT] sur un rapport existant (job_dd56ab31...)."""
    return [r.rstrip("\\") for r in _RE_POINTER.findall(reponse or "")]


def _a_pointer_ref(reponse) -> bool:
    return bool(_RE_POINTER.search(str(reponse or "")))


def _non_livre(effet: str, reponse: str) -> str | None:
    """Motif « NON LIVRE » si la delegation n'a produit AUCUN commit propre mais laisse du travail non committe,
    sans pointer d'artefact. None sinon.

    2026-10-13 : AGY a fusionne alpha, modifie forge_session_context.py, puis s'est arrete sur 5 fichiers non
    commites ; l'enveloppe du CLI disait SUCCESS et le drain l'a relaye. Du travail non committe dans un worktree
    n'est ni relisible par le hub (ACL) ni fusionnable : DECLARE n'est pas ACHIEVED. Une tache de rapport qui
    pointe son artefact (`pointer_ref`) est jugee par `_artefact_declare_absent`, pas ici."""
    m = re.search(r"commits produits : (\d+) \([^)]*\) ; fichiers non commites : (\d+)", effet or "")
    if not m or m.group(1) != "0" or int(m.group(2)) == 0 or _pointe_un_artefact(reponse):
        return None
    return "[NON LIVRE] aucun commit propre, %s fichier(s) non committe(s)" % m.group(2)


def _pointe_un_artefact(reponse) -> bool:
    """Le dernier `pointer_ref` designe-t-il un ARTEFACT (chemin, sha, autre registre) ?

    28/10 (job_22f3db0c) : OPENCODE_DEFAUT2 a rendu OK_DONE en declarant 4 fichiers crees, aucun n'existait ;
    son pointeur « forge_introspect_performance_plan » (mot nu) suffisait a sauter NON LIVRE. Un mot nu et un
    `tasks.db:` ne designent pas un livrable ; un chemin, un sha et un autre registre (bb:, rag:, URL) si."""
    refs = _pointer_refs(reponse)
    if not refs:
        return False
    for morceau in _morceaux_ref(refs[-1]):
        ref = morceau.strip()
        if not ref or ref.startswith("tasks.db:"):
            continue
        if ("://" in ref or re.search(r"[\\/]", ref) or re.search(r"\.[A-Za-z0-9]{1,6}$", ref)
                or re.search(r"(?:^|@)[0-9a-fA-F]{7,40}$", ref) or re.match(r"^[A-Za-z][A-Za-z0-9_.]{1,20}:", ref)):
            return True
    return False


# `pas` RETIRE (26/10) : « ne cree pas de systeme parallele » est une contrainte de conception, et la classait en
# lecture seule -> OK_DONE a 0 commit (job_d0021c97). NR test_juge_lecture_seule_contrainte_de_conception_nr.
_RE_LECTURE_SEULE = re.compile(r"lecture[\s-]+seule|read[\s-]?only|ne\s+(?:modifie|cree|[eé]cris)\s+(?:aucun|rien)|"
                               r"sans\s+(?:rien\s+)?(?:modifier|[eé]crire)", re.I)
_RE_LIVRABLE = re.compile(r"\bcommit|\brapport\b|\blivrable|\b[eé]cri(?:s|re|t|vez)\b|\bcr[eé]e[rz]?\b|\bfichier|"
                          r"\bmodifie[rz]?\b|\bimpl[eé]mente", re.I)


# « livrable juge sur le commit » ajoute le 27/10 (job_d0021c97 : cette formule ne nommait rien -> OK_DONE a 0 commit).
_RE_LIVRABLE_NOMME = re.compile(r"livrable\s+obligatoire|\bcommitt?[eé]e?\b|\blivrable\s*:\s*\S|pointer_ref\W{0,4}commit:|"
                                r"livrable\s+jug[eé]\s+sur\s+(?:le\s+)?commit", re.I)


def _lecture_seule(desc: str) -> bool:
    """La consigne DIT qu'elle est en lecture seule : la tache se juge alors sur son rapport (inchange)."""
    return bool(_RE_LECTURE_SEULE.search(str(desc or "")))


def _exige_livrable(desc: str) -> bool:
    """La consigne exige un livrable ECRIT (commit, fichier, rapport) et n'est pas explicitement en lecture seule."""
    d = str(desc or "")
    if _RE_LIVRABLE_NOMME.search(d):
        return True     # 24/10 (job_73a41438) : livrable NOMME > « ne modifie aucun code » (qui vise le code, pas le livrable)
    return bool(_RE_LIVRABLE.search(d)) and not _lecture_seule(d)


def _rien_produit(effet: str, reponse: str, desc: str | None = None) -> str | None:
    """« [RIEN PRODUIT] » si la delegation n'a laisse ni commit ni fichier et ne pointe aucun artefact. None sinon.

    2026-10-20 (job_aa2229e3) : un diff rendu EN TEXTE, tronque a 8000 caracteres avec sa ligne finale, est sorti
    done / OK_DONE / SUCCESS -- `_non_livre` ne mord que s'il reste des fichiers non committes. Un texte sans effet
    n'est pas une livraison. Une reponse qui pointe son artefact (`pointer_ref`) reste jugee par les gardes d'artefact.
    Sans commit produit, un pointeur de commit ne designe pas la livraison (20/10, GREEN livre par MISTRAL)."""
    m = re.search(r"commits produits : (\d+) \([^)]*\) ; fichiers non commites : (\d+)", effet or "")
    refs = _pointer_refs(reponse)
    if not m or m.group(1) != "0" or m.group(2) != "0":
        return None
    # 6/11 (lot C, job_39e9df24) : zero commit, zero fichier, 7 789 caracteres d'erreur d'outil, et SUCCESS. Un `pointer_ref` trouve
    # dans le texte faisait lacher ce garde. La consigne nomme son fichier : sans effet, il n'existe pas.
    if re.search(r'"pointer_ref"\s*:\s*"[^":<>]+\.[A-Za-z0-9]{1,6}"', str(desc or "")):
        return "[RIEN PRODUIT] (RIEN_PRODUIT) ni commit ni fichier, alors que la consigne nomme le fichier attendu"
    if refs and not re.match(r"^(commit:|\S+@[0-9a-fA-F]{7,40}\b)", refs[-1].strip()):
        # 24/10 (job_cedfb687, MISTRAL) : quand la consigne EXIGE un livrable ecrit, un pointeur sans fichier
        # (tasks.db:, bb:, texte) ne prouve rien -- seul un chemin de fichier reste juge par les gardes d'artefact.
        r = refs[-1].strip()
        chemin = (bool(re.search(r"[\\/]", r) or re.search(r"\.[A-Za-z0-9]{1,6}$", r)) and "://" not in r
                  and not r.startswith("tasks.db:") and not re.match(r"^[A-Za-z][A-Za-z0-9_.]{1,20}:(?![\\/])", r))
        if not (desc is not None and _exige_livrable(desc) and not chemin):
            return None
    return "[RIEN PRODUIT] (RIEN_PRODUIT) ni commit ni fichier, et aucun artefact pointe : une reponse sans effet n'est pas livree"


def _intention_finale(texte: str) -> str | None:
    """Dernier intent M2M ecrit dans un texte (`"intent": "X"`), quel qu'il soit ; None : l'agent n'a rien conclu.
    Parseur UNIQUE : _intent_rendu en est la vue « pas fait », la relance OpenCode la vue « rien conclu »."""
    trouves = _RE_INTENT.findall(texte or "")
    return trouves[-1] if trouves else None


def _intent_rendu(reponse: str) -> str | None:
    """Dernier intent M2M que l'agent DECLARE dans sa reponse (`"intent": "X"`), s'il dit « pas fait ».

    2026-10-01 : AGY s'est arrete -- a bon droit -- en rendant `{"intent": "NEED_HUMAN_APPROVAL"}`
    (git hors de son bac a sable), et la delegation l'a transmis en OK_DONE / SUCCESS parce que
    l'enveloppe du CLI disait `status: SUCCESS` (le CLI a REPONDU, pas la tache FAITE)."""
    dernier = _intention_finale(reponse)
    if not dernier:
        return None
    return dernier if (dernier in _INTENTS_NON_FAITS or dernier.startswith("ERR_")) else None


def _morceaux_ref(ref: str) -> list[str]:
    """Un pointer_ref COMPOSITE (« <commit> + sandbox/workspace/x.md ») en morceaux ; un seul morceau sinon."""
    morceaux = [m.strip() for m in re.split(r"\s+\+\s+", ref or "") if m.strip()]
    return morceaux or [(ref or "").strip()]


def _chemin_existe(p: Path, workdir: str) -> bool:
    """Le chemin existe-t-il DANS le workdir de l'executeur ou le depot partage ? Un chemin qui sort des deux
    (`..`, absolu etranger) n'est jamais lu : il compte absent."""
    racines = []
    for r in (workdir, ROOT):
        try:
            racines.append(Path(r).resolve())
        except OSError:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 1689, exc_info=True)
            continue
    cands = [p] if p.is_absolute() else [Path(workdir) / p, ROOT / p]
    for c in cands:
        try:
            rc = c.resolve()
            if any(rc == r or r in rc.parents for r in racines) and c.exists():
                return True
        except OSError:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 1697, exc_info=True)
            continue
    return False


def _artefact_declare_absent(reponse: str, workdir: str) -> str | None:
    """L'artefact que l'agent DECLARE (dernier `"pointer_ref"`) et qui n'existe PAS ; None sinon.

    2026-10-01 : AGY a rendu `{"intent": "OK_DONE", "pointer_ref": "sandbox/swarm/reponse_agy_adddir_
    2026-10-01.md"}` -- fichier absent du worktree comme de l'arbre partage, aucun fichier ecrit (l'effet
    observe le montrait), et la delegation l'a transmis en SUCCESS. Seuls se jugent un chemin de fichier
    et un `<branche>@<sha>` ; un pointeur d'un autre type (tasks.db:, URL, cle de blackboard) n'est pas
    juge, et une verification ILLISIBLE n'accuse pas (None) : une sonde muette ne fabrique pas d'echec."""
    import subprocess as _sp
    refs = _pointer_refs(reponse)
    if not refs:
        return None
    for morceau in _morceaux_ref(refs[-1]):
        motif = _ref_declare_absent(morceau, workdir)
        if motif:
            return motif
    return None


def _ref_declare_absent(ref: str, workdir: str) -> str | None:
    """Jugement d'UN morceau de pointer_ref (voir _artefact_declare_absent)."""
    import subprocess as _sp
    ref = ref.strip()
    if not ref or ref.startswith("tasks.db:") or "://" in ref:
        return None
    ref = re.sub(r"^commit\s+(?=[0-9a-fA-F]{7,40}$)", "", ref)
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", ref):
        ref = "@" + ref
    # 16/10 (essai partage n°2) : « bb:architecture_rules/... » etait juge comme un FICHIER absent -> livraison
    # reelle classee ERR_INTERNAL. Un pointeur a schema (bb:, commit:, gh_run:, rag:...) designe un autre registre ;
    # une lettre de lecteur (C:\...) reste un chemin.
    # 19/10 (job_55a851be) : `fichier::symbole`, `fichier:ligne`, `fichier#L1-L2` designent le FICHIER ; le suffixe
    # etait pris pour une partie du nom -> enquete d'AGY jugee « artefact ABSENT ».
    ref = re.sub(r"(::[\w.]+|#L?\d+(?:-L?\d+)?|:\d+(?:-\d+)?)$", "", ref)
    if re.match(r"^[A-Za-z][A-Za-z0-9_.]{1,20}:(?![\\/])", ref):
        return None
    m = re.search(r"@([0-9a-fA-F]{7,40})$", ref)
    if m:
        try:
            r = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "rev-parse", "--verify", "--quiet",
                         m.group(1) + "^{commit}"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=20, env=_env_git())
        except Exception:  # noqa: BLE001 - illisible : n'accuse pas
            return None
        if r.returncode == 0:
            return None
        # rc 1 = objet inconnu du depot ; tout autre code (pas un depot, git absent) = ILLISIBLE
        return "commit declare introuvable : %s" % ref if r.returncode == 1 else None
    if not re.search(r"[\\/]", ref) and not re.search(r"\.[A-Za-z0-9]{1,6}$", ref):
        return None     # ni chemin ni nom de fichier : pointeur d'un autre type
    if _chemin_existe(Path(ref), workdir):
        return None
    return "fichier declare absent : %s" % ref


def _artefact_non_produit(reponse: str, workdir: str, avant) -> str | None:
    """Motif de refus si le pointer_ref pointe vers un fichier qui existait deja avant la tache,
    sans commit ni modification. None sinon.
    Revue adverse Codex (17/10, R3) : sans commit, pointer un fichier preexistant passait."""
    import subprocess as _sp
    refs = _pointer_refs(reponse)
    if not refs:
        return None
    ref = refs[-1].strip()
    morceaux = _morceaux_ref(ref)
    if len(morceaux) > 1:   # composite : le morceau CHEMIN (un commit/texte libre ne designe pas de fichier)
        chemins = [m for m in morceaux if re.search(r"[\\/]", m) or re.search(r"\.[A-Za-z0-9]{1,6}$", m)]
        ref = chemins[-1] if chemins else ""
    if not ref or ref.startswith("tasks.db:") or "://" in ref:
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9_.]{1,20}:(?![\\/])", ref):
        return None
    if re.search(r"@([0-9a-fA-F]{7,40})$", ref):
        return None
    if not re.search(r"[\\/]", ref) and not re.search(r"\.[A-Za-z0-9]{1,6}$", ref):
        return None
    p = Path(ref)
    if p.is_absolute():
        try:
            rel = p.relative_to(Path(workdir)).as_posix()
        except Exception:
            rel = None
    else:
        rel = ref.replace("\\", "/").strip("/")
    if not rel:
        return None

    candidats = [p] if p.is_absolute() else [Path(workdir) / p, ROOT / p]
    try:
        if not any(c.exists() for c in candidats):
            return None  # fichier absent -> traite par _artefact_declare_absent
    except OSError:
        return None

    h_av = avant[0] if avant else None
    preposes = tuple(getattr(avant, "preposes", ()) or ())
    if not h_av:
        return None

    def _g(*a):
        return _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, *a],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=20, env=_env_git())

    r_ls = _g("ls-tree", "-r", "--name-only", h_av)
    files_in_git = {}
    if r_ls.returncode == 0:
        for ligne in r_ls.stdout.splitlines():
            chemin_git = ligne.strip().replace("\\", "/")
            if chemin_git:
                files_in_git[chemin_git.lower()] = chemin_git

    rel_norm = rel.lower()
    existed_in_git = rel_norm in files_in_git
    existed_in_preposes = any(rel_norm == q.replace("\\", "/").lower() for q in preposes)
    if not (existed_in_git or existed_in_preposes):
        return None  # fichier nouveau, pas preexistant

    rel_git = files_in_git.get(rel_norm, rel)

    h_ap, _ = _etat_git(workdir)
    if h_ap and h_ap != h_av:
        r_diff = _g("diff", "--name-only", "%s..%s" % (h_av, h_ap), "--", rel_git)
        if r_diff.returncode == 0 and r_diff.stdout.strip():
            return None  # committe avec modification

    r_diff_tree = _g("diff", h_av, "--", rel_git)
    if r_diff_tree.returncode == 0 and r_diff_tree.stdout.strip():
        return None  # modifie dans le worktree

    r_stat = _g("status", "--porcelain", "--", rel_git)
    if r_stat.returncode == 0 and r_stat.stdout.strip():
        return None  # modifie ou statut non propre

    return "[ARTEFACT NON PRODUIT] %s existait deja avant la tache sans commit ni modification" % ref


def _caviarder(texte) -> str:
    """Retire secrets et jetons d'un texte avant qu'il soit persiste ou emis (RED7, 19/10). Branche le redacteur
    EXISTANT (tools/forge_log_redact.redact, adosse a redact_tool_output) ; il dit lui-meme s'il est indisponible."""
    try:
        from nokido_agent.tools.forge_log_redact import redact
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        from forge_log_redact import redact
    return redact(str(texte or ""))


_WORKDIR_TACHE: dict = {}
"""task_id -> repertoire de travail de la tache, pose par la delegation avant de clore (le juge de livraison
controle CE repertoire, jamais ROOT). Absent = ILLISIBLE, dit par `_mark_done`."""


def _clore_delegation(task_id: str, token: str, ok: bool, detail: str, intent: str | None = None,
                      workdir=None) -> None:
    """Clot une tache deleguee (AGY, CODEX) : statut en base + resultat M2M a l'emetteur. Extrait du `_fin` de
    `_delegate_to_agy` le 16/10 pour que les deux voies closent de la MEME facon. Le detail est CAVIARDE avant
    d'etre persiste ou emis (RED7 : une erreur peut citer un en-tete Authorization)."""
    detail = _caviarder(detail)
    intent = intent or ("OK_DONE" if ok else "ERR_INTERNAL")
    statut = _statut_livraison(ok, detail, intent)
    # 3/11 : la cause est CLASSEE et ecrite en base (tasks.cause_echec) -- plus de diagnostic a la main.
    cause = ("FAUX_VERT" if statut == "A_REVOIR" else
             classer_cause_echec(detail) if (statut in ("FAILURE", "NEEDS_HUMAN") or not ok) else None)
    # 7/11 (job_5291da2c) : session expiree (« print timeout ... turn still in progress ») dont le travail a ete
    # sauvegarde en commit INACHEVE : jamais done/vert. Cause dediee ; le commit reste sur la branche.
    if _MARQUE_LIMITE_TOURS in _constat_executeur(detail):
        # 7/11 (job_342863a9) : limite de tours du harness lue dans son champ JSON -> cause dediee, jamais SUCCESS.
        ok, cause = False, "LIMITE_TOURS"
    elif "travail INACHEVE preserve" in detail and _RE_SESSION_EXPIREE.search(detail):
        ok, cause = False, "SESSION_EXPIREE"
    elif "MODELE_REPLI_NON_DECLARE" in detail:
        ok, cause = False, "MODELE_REPLI_NON_DECLARE"
    elif "CONTEXTE_NON_SERVI" in detail:
        ok, cause = False, "CONTEXTE_NON_SERVI"
    elif ok and statut == "FAILURE":
        # 7/11 : « done » sans effet ou avec ERR_* final : cause dediee NON_LIVRE, jamais INCONNU.
        ok, cause = False, "NON_LIVRE"
    conn = _db()
    try:
        _mark_done(conn, task_id, _borner(detail), ok,
                   workdir=workdir or _WORKDIR_TACHE.pop(str(task_id), None))
        _noter_cause_echec(conn, task_id, cause)
    finally:
        conn.close()
    try:
        _hub_call("task", {"action": "result", "task_id": task_id, "intent": intent,
                  "result": json.dumps({"intent": intent, "status_code": statut,
                  "pointer_ref": f"tasks.db:{task_id}", "detail": detail[:220]}, ensure_ascii=False)},
                  token, timeout=30)
    except Exception as e:  # noqa: BLE001
        # La tache est close EN BASE ; c'est le compte rendu a l'emetteur qui manque -- il doit le savoir.
        log.warning(f"  resultat M2M NON emis pour {str(task_id)[:24]} ({type(e).__name__}: {str(e)[:80]}) "
                    f"-- tache close en base, emetteur non prevenu")


_CONFIG_AGENT = (".vibe/", ".agy/", ".codex/", ".opencode/", "AGENTS.md", "GEMINI.md",
                 ".claude_headless_mcp.json")

# 22/10 (bb:architecture_rules/bug_juge_failure_avec_livraison_20261022) : le VERDICT d'une delegation se LIT sur
# l'ARTEFACT produit -- un commit livre, un fichier modifie non committe -- et JAMAIS sur la seule absence de commit.
# Mesure : job_0cd422a1 (1 commit livre, refuse au contenu) et job_af6dbf75 / job_818ec8d8 (travail juste, non
# committe) rendus FAILURE : le travail EXISTAIT, il s'est perdu derriere un verdict d'echec.
_LIVRE_NON_COMMITTE = "[LIVRE NON COMMITTE]"
# 7/11 (job_342863a9) : `claude -p` a fini en `error_max_turns` (is_error:true, aucun message final) et la tache
# s'affichait done [SUCCESS] parce que des commits existaient. Une limite de tours du harness n'est jamais SUCCESS :
# A_REVOIR (livraison partielle) si des commits existent, FAILURE nomme sinon ; cause LIMITE_TOURS.
_MARQUE_LIMITE_TOURS = "[LIMITE TOURS]"


def _statut_artefact(effet: str) -> tuple:
    """(commits produits, fichiers non commites) lus dans l'effet observe ; (None, None) si l'effet est illisible."""
    m = re.search(r"commits produits\s*:\s*(\d+|ILLISIBLE)\s*\([^)]*\)\s*;\s*fichiers non commites\s*:\s*(\d+)",
                  str(effet or ""))
    if not m:
        return None, None
    c = m.group(1)
    return (int(c) if c.isdigit() else None), int(m.group(2))


def _chemins_travail(workdir: str) -> list:
    """Chemins modifies ou non suivis du worktree, configuration d'agent EXCLUE (meme regle que le compte)."""
    config = tuple(c.lower() for c in _CONFIG_AGENT)
    out = []
    for p in (_chemins_status(workdir) or ()):
        rel = str(p).replace("\\", "/")
        if rel.lower().startswith(config) or rel.rsplit("/", 1)[-1] == ".nokido.agent":
            continue
        out.append(rel)
    return sorted(out)


def _livres_non_committes(workdir: str) -> str:
    """Marqueur LIVRE NON COMMITTE + la liste des fichiers du travail non committe (l'ARTEFACT, nomme)."""
    fichiers = _chemins_travail(workdir)
    if not fichiers:
        return "%s (liste indisponible)" % _LIVRE_NON_COMMITTE
    return "%s %d fichier(s) : %s" % (_LIVRE_NON_COMMITTE, len(fichiers), ", ".join(fichiers[:15]))


_MARQUES_NON_LIVRE = ("[artefact ABSENT]", "[RECOPIE CONSIGNE]", "[ACCUSE DE RECEPTION]", "[AUCUN EFFET]", "[LIVRAISON VIDE]")


_MARQUE_NOTE_EXECUTEUR = "[executeur] "


def _notes_executeur(texte: str) -> str:
    """Partie ECRITE PAR L'EXECUTEUR dans un detail : les notes ajoutees en `\\n[executeur] <note>` apres la prose
    de l'agent (seule frontiere existante, aucun format parallele). On prend la DERNIERE note et sa suite : la
    prose precede toujours. Limite : une prose qui imprimerait `[executeur] ` en debut de ligne est indiscernable."""
    t = str(texte or "")
    i = t.rfind("\n" + _MARQUE_NOTE_EXECUTEUR)
    if i >= 0:
        return t[i + 1:]
    return t if t.startswith(_MARQUE_NOTE_EXECUTEUR) else ""


def _constat_executeur(effet: str) -> str:
    """Constat de l'executeur dans un `effet` : la tete avant le premier « | » plus ses notes `[executeur]`.
    Le reste est le texte de l'agent, ou un marqueur CITE ne vaut pas verdict."""
    tete, sep, reste = str(effet or "").partition(" | ")
    notes = _notes_executeur(reste) if sep else ""
    return tete + ("\n" + notes if notes else "")


_MARQUE_ANNULEE = "ANNULEE_SANS_EXECUTEUR"


def _annulee_par_emetteur(brut: str) -> bool:
    """Annulation par l'EMETTEUR : le marqueur est dans le constat de l'executeur, ou il OUVRE le rendu (forme de
    cloture, `effet | ANNULEE_SANS_EXECUTEUR...`). 7/11 : depuis 7aa64ee12 le juge ne lisait plus que le constat et
    une annulation devenait NON_LIVRE (regression masquee par un TypeError de doublure). Une prose d'agent qui CITE le
    marqueur plus loin ne s'exempte pas : c'est une exemption, jamais auto-declarable au milieu d'un texte."""
    t = str(brut or "")
    if _MARQUE_ANNULEE in _constat_executeur(t):
        return True
    _tete, sep, reste = t.partition(" | ")
    return bool(sep) and reste.lstrip().startswith(_MARQUE_ANNULEE)


def _statut_livraison(ok: bool, effet: str, intent: str | None = None) -> str:
    """SUCCESS | PARTIEL | LIVRE_NON_COMMITTE | NEEDS_HUMAN | FAILURE -- le verdict se LIT sur l'ARTEFACT.

    22/10 : un travail LIVRE n'est JAMAIS un FAILURE. Un commit sur la branche de l'executeur -> PARTIEL (le contenu
    peut etre refuse, la livraison est la) ; des fichiers modifies non committes -> LIVRE_NON_COMMITTE (le travail
    existe : il est committe ou sauvegarde) ; ni l'un ni l'autre -> FAILURE (la, rien n'a ete livre)."""
    brut = str(effet or "")
    effet = _constat_executeur(brut)
    # 7/11 (job_342863a9) : le harness a epuise ses tours (JSON `subtype: error_max_turns`) et la tache sortait SUCCESS
    # sur ses commits. Jamais un succes : A_REVOIR (livraison partielle a relire) si des commits existent, FAILURE sinon.
    if _MARQUE_LIMITE_TOURS in effet:
        _c, _f = _statut_artefact(effet)
        return "A_REVOIR" if _c else "FAILURE"
    if _LIVRE_NON_COMMITTE in effet:
        return "LIVRE_NON_COMMITTE"
    # 30/10 (job_db32d872) : 4 traductions remplacees par un message d'erreur d'outil, commit REFUSE par le garde
    # (reecriture destructrice) -- et la tache sortait SUCCESS. Un commit refuse par l'executeur est A RELIRE.
    if "commit executeur REFUSE" in effet:
        return "NEEDS_HUMAN"
    # 30/10 (job_84c166a1) : session AGY en echec, travail commite « INACHEVE a relire » par l'executeur -- et la
    # tache sortait SUCCESS. Livre mais A RELIRE : PARTIEL, jamais un succes propre.
    if "travail INACHEVE preserve" in effet:
        return "PARTIEL"
    # 30/10 (job_9b5d2a58) : claude -p « Not logged in », l'executeur ecrit [RIEN PRODUIT] -- et la tache sortait
    # SUCCESS. Une reponse sans effet n'est pas livree.
    if "[RIEN PRODUIT]" in effet:
        return "FAILURE"
    # 3/11 (owner « faux vert refuse ») : GPT-OSS (74f27169f) et GLM (395d83b16) livraient du code faux avec « preuve RED
    # INDETERMINEE (RED NON OBSERVE ...) » -- et la tache sortait SUCCESS. Sans rouge observe : a relire.
    # 6/11 (job_2e450653) : le guet relit une tache « done » avec ok=True ; un artefact ABSENT, une recopie de la consigne ou
    # un accuse de reception portes par l'effet ne sont pas un succes, quel que soit le `ok` qu'on nous passe.
    # Seule la tete (avant le premier « | ») est le constat de l'executeur : la suite est le texte de l'agent, qui peut
    # citer ces marques sans en etre frappe (une tache sur le juge lui-meme, par exemple).
    if ok and any(m in str(effet).split(" | ", 1)[0] for m in _MARQUES_NON_LIVRE):
        ok = False
    # 7/11 (job_bce6a446, job_52e89513) : « je n'ai rien fait », 0 commit, 0 fichier, statut done -> SUCCESS sur la veille.
    # Aucun effet observe (et aucun artefact pointe), ou JSON final ERR_*, n'est jamais un succes. Une annulation par
    # l'emetteur (ANNULEE_SANS_EXECUTEUR) n'est pas un echec de l'agent.
    if ok and str(intent or "").startswith("ERR_"):
        ok = False
    annulee = _annulee_par_emetteur(brut)
    if ok and not annulee and _statut_artefact(effet) == (0, 0) and not _a_pointer_ref(brut):
        ok = False
    if ok and ("RED NON OBSERVE" in effet or "RED INDETERMINEE" in effet):
        return "A_REVOIR"
    # Revue AGY 8305283b8 : une absence d'effet observe n'est pas une preuve de reussite. Effet VIDE, ou compteurs
    # presents mais commits ILLISIBLES sans fichier : A_REVOIR. Un texte de reponse libre (sans compteurs) reste SUCCESS.
    if ok and not annulee:
        _c, _f = _statut_artefact(effet)
        if not effet.strip() or (_c is None and _f == 0):
            return "A_REVOIR"
    if ok:
        return "SUCCESS"
    if intent == "NEED_HUMAN_APPROVAL":
        return "NEEDS_HUMAN"
    c, _f = _statut_artefact(effet)
    if c:
        return "PARTIEL"
    return "FAILURE"


def _finaliser_effet(task_id, ok: bool, effet: str) -> bool:
    """Point UNIQUE de toutes les voies (claude -p, opencode, vibe, codex, agy) : ECRIT verdict_effet en base et
    rend `ok` force a False si l'effet porte RIEN_PRODUIT (0 commit, 0 fichier, aucun artefact) -> statut d'echec.
    24/10 : la voie Vibe (job_f97e4be0) calculait l'effet sans l'ecrire. Ne leve jamais."""
    effet = str(effet or "")
    if "RIEN_PRODUIT" in effet or "[RIEN PRODUIT]" in effet:
        ok = False
    try:
        conn = _db()
        try:
            ensure_trace_schema(conn)
            _att = _TENTATIVE_PRISE.get(str(task_id))
            if _att is None:
                conn.execute("UPDATE tasks SET verdict_effet=? WHERE id=?", (effet[:2000] or None, str(task_id)))
            else:   # attempt seul : le statut peut deja etre `acknowledged` (cause normale)
                _c = conn.execute("UPDATE tasks SET verdict_effet=? WHERE id=? AND COALESCE(attempt,0)=?",
                                  (effet[:2000] or None, str(task_id), _att))
                if _c.rowcount != 1:
                    _ecriture_refusee(conn, str(task_id), _att, "verdict_effet")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 -- la trace ne doit jamais faire echouer la tache
        log.warning(f"  verdict_effet NON ecrit pour {str(task_id)[:24]} ({type(e).__name__}): {e}")
    return bool(ok)


def _aucun_effet(effet: str, detail: str) -> bool:
    """VRAI si la delegation n'a produit NI commit NI fichier non committe, et ne pointe aucun artefact.

    22/10 : un travail laisse non committe EST un effet (job_af6dbf75) -- le compter comme « aucun effet » en
    faisait une livraison ratee."""
    if _a_pointer_ref(detail):
        return False
    c, f = _statut_artefact(effet)
    if c is None or f is None:
        return True      # effet illisible : rien n'est PROUVE (comportement historique)
    return c == 0 and f == 0


def _tests_autorises(desc: str) -> list:
    """Chemins de tests que la TACHE autorise a modifier : ligne « tests_autorises: a, b » de sa description."""
    m = re.search(r"^\s*tests_autorises\s*:\s*(.+)$", str(desc or ""), re.M | re.I)
    return [c.strip().replace("\\", "/") for c in m.group(1).split(",") if c.strip()] if m else []


# 6/11 (job_441754a9) : un artefact qui RECOPIE la consigne passait SUCCESS. Mesure sans LLM : part des 5-grammes de mots
# de l'artefact deja presents dans la consigne. Seuil MESURE le 6/11 (job_55583dd5f341) sur 147 textes de 300 livraisons :
# la recopie reelle vaut 0.39, le rendu legitime le plus haut 0.135 ; le 0.6 d'origine laissait passer la recopie.
# Un texte court (une consigne qui dicte un fichier de 227 octets : 0.529) ne se juge pas : sous RECOPIE_MIN_GRAMMES, on n'accuse pas.
SEUIL_RECOPIE = 0.25
RECOPIE_MIN_GRAMMES = 40
_EXT_TEXTE = (".md", ".txt", ".rst")


def _grammes(texte: str, n: int = 5) -> set:
    mots = re.findall(r"\w+", str(texte or "").lower())
    return {tuple(mots[i:i + n]) for i in range(len(mots) - n + 1)}


def mesurer_recopie(artefact: str, consigne: str) -> float:
    """Part (0..1) des 5-grammes de mots de `artefact` presents dans `consigne` ; 0.0 si l'artefact est trop court."""
    g = _grammes(artefact)
    if not g:
        return 0.0
    return len(g & _grammes(consigne)) / len(g)


def _recopie_consigne(contenus: dict, desc) -> "str | None":
    """Motif si CHAQUE artefact texte livre recopie la consigne (`contenus` = {chemin: texte}) ; None sinon."""
    if not desc or not contenus:
        return None
    if any(len(_grammes(t)) < RECOPIE_MIN_GRAMMES for t in contenus.values()):
        return None
    mesures = {p: mesurer_recopie(t, desc) for p, t in contenus.items()}
    if all(m >= SEUIL_RECOPIE for m in mesures.values()):
        return "[RECOPIE CONSIGNE] %s -- l'artefact reprend la consigne (recouvrement %s >= %.2f), il n'est pas livre" % (
            ", ".join(sorted(mesures)[:5]), "/".join("%.2f" % m for m in mesures.values()), SEUIL_RECOPIE)
    return None


def _contenu_recopie(workdir: str, avant, desc) -> "str | None":
    """[RECOPIE CONSIGNE] si les commits PROPRES de la delegation ne livrent que des artefacts TEXTE qui recopient la
    consigne ; un livrable d'une autre nature (code...) n'est jamais une recopie. Git illisible : None (on n'accuse pas)."""
    import subprocess as _sp
    h_av = avant[0] if avant else None
    h_ap, _ = _etat_git(workdir)
    if not desc or h_av is None or h_ap is None or h_av == h_ap:
        return None

    def _g(*a):
        return _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, *a], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=20, env=_env_git())

    r = _g("diff", "--name-status", "--no-renames", "%s..%s" % (h_av, h_ap), "--")
    if r.returncode != 0:
        return None
    ecrits = [l.split("\t", 1)[1].strip() for l in r.stdout.splitlines() if "\t" in l and l[:1] in ("A", "M")]
    preposes = {str(q).replace("\\", "/").lower() for q in (getattr(avant, "preposes", ()) or ())}
    config = tuple(c.lower() for c in _CONFIG_AGENT)
    livrables = [p for p in ecrits if not p.lower().startswith(config) and p.lower() not in preposes]
    if not livrables or not all(p.lower().endswith(_EXT_TEXTE) for p in livrables):
        return None
    contenus = {}
    for p in sorted(livrables):
        s = _g("show", "%s:%s" % (h_ap, p))
        if s.returncode != 0:
            return None
        contenus[p] = s.stdout
    return _recopie_consigne(contenus, desc)


def _contenu_livre(workdir: str, avant, autorises=None) -> "str | None":
    """Motif de refus si les commits PROPRES de la delegation ne livrent rien (configuration de l'agent, ou fichiers
    deja la avant la tache) ou touchent un test existant sans autorisation de la tache. None = rien a redire ; git
    illisible = DIT, sans refus (on n'accuse pas sur une mesure douteuse)."""
    import subprocess as _sp
    h_av = avant[0] if avant else None
    preposes = tuple(getattr(avant, "preposes", ()) or ())
    h_ap, _ = _etat_git(workdir)
    if h_av is None or h_ap is None or h_av == h_ap:
        return None

    def _g(*a):
        return _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, *a], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=20, env=_env_git())

    r = _g("rev-list", "--first-parent", "--no-merges", "%s..%s" % (h_av, h_ap), *_hors_alpha(workdir), "--")
    if r.returncode != 0:
        return "[CONTENU ILLISIBLE] rev-list rc=%s : rien n'est prouve sur ce qui a ete livre" % r.returncode
    statuts = {}
    for c in r.stdout.split():
        s = _g("show", "--format=", "--name-status", c, "--")
        if s.returncode != 0:
            return "[CONTENU ILLISIBLE] git show %s rc=%s" % (c[:9], s.returncode)
        for ligne in s.stdout.splitlines():
            morceaux = ligne.split("\t")
            if len(morceaux) == 2:
                statuts[morceaux[1].replace("\\", "/")] = morceaux[0][:1]
            elif len(morceaux) >= 3 and morceaux[0][:1] in ("R", "C"):
                old_p = morceaux[1].replace("\\", "/")
                new_p = morceaux[2].replace("\\", "/")
                st = morceaux[0][:1]
                statuts[old_p] = st
                statuts[new_p] = st
            elif len(morceaux) >= 2:
                statuts[morceaux[-1].replace("\\", "/")] = morceaux[0][:1]

    def _norm(chemin: str) -> str:
        return str(chemin).strip().strip('"').replace("\\", "/").lower()

    autorises_norm = {_norm(a) for a in (autorises or ())}
    touches = sorted("%s %s" % (st, p) for p, st in statuts.items()
                     if _norm(p).startswith("tests/") and _norm(p) not in autorises_norm
                     and (st in ("D", "R") or (st == "M" and _g("cat-file", "-e", "%s:%s" % (h_av, p)).returncode == 0)))
    if touches:
        return "[TESTS TOUCHES] %s -- un delegue ne reussit pas en supprimant ou en modifiant un test existant" % (
            ", ".join(touches[:8]))

    def _pre_pose(p):
        pn = _norm(p)
        return any(pn == _norm(q) or (_norm(q).endswith("/") and pn.startswith(_norm(q))) for q in preposes)

    config_agent_norm = tuple(c.lower() for c in _CONFIG_AGENT)
    livrables = [p for p in statuts if not _norm(p).startswith(config_agent_norm) and not _pre_pose(p)]
    if not livrables:
        return "[LIVRAISON VIDE] %d fichier(s) committe(s), tous configuration de l'agent ou deja la avant la tache" % (
            len(statuts))
    # 20/10 (rejeu job_499ed100, Vibe 3.0.1) : trois lignes mal indentees conclues OK_DONE -- un .py qui ne compile pas
    # n'est pas livre. Version illisible au commit = on n'accuse pas.
    import ast as _ast
    for p in sorted(p for p in livrables if p.endswith(".py") and statuts[p] != "D"):
        s = _g("show", "%s:%s" % (h_ap, p))
        if s.returncode != 0:
            continue
        try:
            _ast.parse(s.stdout, filename=p)
        except SyntaxError as e:
            return "[SYNTAXE INVALIDE] %s:%s %s -- un .py qui ne compile pas n'est pas une livraison" % (p, e.lineno, e.msg)
    return None


_RE_EXIGE_TDD = re.compile(r"\bTDD\b|\bRED\b|test d'abord|test d.abord", re.I)


def _red_non_observe(desc, workdir: str, avant) -> "str | None":
    """Motif RED_NON_OBSERVE si la consigne exige du TDD ET qu'un commit de la livraison consigne « DEJA VERTS »
    (rejeu sur le commit RED). INDETERMINE / ROUGE / sans exigence TDD : None (inchange)."""
    if not desc or not _RE_EXIGE_TDD.search(str(desc)):
        return None
    h_av = (avant or (None,))[0]
    if not h_av:
        return None
    import subprocess as _sp
    try:
        r = _sp.run(["git", "-c", "safe.directory=*", "-C", str(workdir), "log", "--format=%B", "%s..HEAD" % h_av],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=_env_git())
    except Exception:  # noqa: BLE001 - mesure douteuse : on n'accuse pas
        return None
    if r.returncode != 0 or "DEJA VERTS" not in (r.stdout or ""):
        return None
    return "[RED_NON_OBSERVE] TDD exige mais tests DEJA VERTS sur le commit RED : code ecrit avant le test"


_MARQUEUR_CONTRAT = "[LIVRABLE_CONTRAT]"
_TYPES_LIVRABLE = ("commit", "fichier", "tests_verts", "aucun")


def _contrat_livrable(desc) -> dict | None:
    """Contrat de livrable STRUCTURE pose par l'appelant (task assign). Le PREMIER marqueur fait foi.
    None si absent ou illisible (repli sur l'heuristique textuelle)."""
    d = str(desc or "")
    i = d.find(_MARQUEUR_CONTRAT)
    if i < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(d[i + len(_MARQUEUR_CONTRAT):].lstrip())
        liv = obj.get("livrable") if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001 - illisible : repli
        return None
    if not isinstance(liv, dict) or liv.get("type") not in _TYPES_LIVRABLE:
        return None
    ch = liv.get("chemins")
    return {"type": liv["type"], "chemins": [str(c) for c in ch] if isinstance(ch, list) else []}


_MARQUE_ILLISIBLE = "[ILLISIBLE]"
_REJEU_TIMEOUT_S = int(os.environ.get("LAFORGE_REJEU_TIMEOUT_S", "300"))


def _rejouer_contrat_tests(workdir: str, chemins: list, timeout: int | None = None) -> tuple:
    """Rejoue dans `workdir` les tests NOMMES par le contrat `tests_verts`. Verdict = JUnit du rejeu.
    Rend (etat, cause) : VERT | ROUGE | ILLISIBLE. Ne leve jamais. Sortie bornee (400 car.)."""
    import subprocess as _sp
    import tempfile
    import shutil
    import xml.etree.ElementTree as _ET
    nommes = [str(c) for c in (chemins or []) if str(c).strip()]
    if not nommes:
        return "ILLISIBLE", "contrat sans test nomme"
    racine = Path(workdir).resolve()
    for c in nommes:
        base = c.split("::", 1)[0]
        try:
            p = (racine / base).resolve()
            p.relative_to(racine)
        except (ValueError, OSError):
            return "ILLISIBLE", "chemin de test hors du worktree : %s" % c[:120]
        if not p.exists():
            return "ILLISIBLE", "test nomme absent du worktree : %s" % c[:120]
    palier = _palier_pression()
    if palier in ("DETRESSE", "CRITIQUE"):
        return "ILLISIBLE", "garde RAM : rejeu refuse (palier %s)" % palier
    tmp = tempfile.mkdtemp(prefix="rejeu_contrat_")
    junit = str(Path(tmp) / "rejeu.xml")
    try:
        env = _env_git()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        py = _python_des_tests()
        try:
            t = _sp.run([py, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "--junitxml", junit] + nommes,
                        cwd=str(racine), capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=timeout or _REJEU_TIMEOUT_S, env=env)
        except _sp.TimeoutExpired:
            return "ILLISIBLE", "rejeu hors delai (%ss)" % (timeout or _REJEU_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            return "ILLISIBLE", "rejeu impossible (%s)" % type(e).__name__
        lignes = ((t.stdout or "") + "\n" + (t.stderr or "")).strip().splitlines() or [""]
        extrait = " | ".join(x.strip() for x in lignes[-3:] if x.strip())[-300:]
        if not os.path.isfile(junit):
            return "ILLISIBLE", "pas de JUnit produit, pytest rc=%s : %s" % (t.returncode, extrait)
        try:
            suites = list(_ET.parse(junit).getroot().iter("testsuite"))
        except Exception as e:  # noqa: BLE001
            return "ILLISIBLE", "JUnit illisible (%s)" % type(e).__name__
        tot = sum(int(s.get("tests", 0) or 0) for s in suites)
        ko = sum(int(s.get("failures", 0) or 0) + int(s.get("errors", 0) or 0) for s in suites)
        ign = sum(int(s.get("skipped", 0) or 0) for s in suites)
        if ko > 0:
            noms = []
            for tc in _ET.parse(junit).getroot().iter("testcase"):
                if tc.find("failure") is not None or tc.find("error") is not None:
                    noms.append("%s::%s" % (tc.get("classname", ""), tc.get("name", "")))
                if len(noms) >= 3:
                    break
            return "ROUGE", ("%d/%d en echec (%s)" % (ko, tot, ", ".join(noms)))[:300]
        if tot - ign <= 0:
            return "ILLISIBLE", "0 test execute (%d collectes, %d ignores)" % (tot, ign)
        if t.returncode != 0:
            return "ILLISIBLE", "JUnit sans echec mais pytest rc=%s : %s" % (t.returncode, extrait)
        return "VERT", "%d tests passes" % (tot - ign)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _tests_verts_ok(sortie) -> bool:
    s = str(sortie or "")
    return bool(re.search(r"\bpassed\b", s)) and not re.search(r"\bfailed\b", s)


_RE_FAUSSE_REPONSE = re.compile(
    r"<think(?:ing)?>|</think(?:ing)?>|json-?rpc error|-32603|provider overloaded|surcharg|internal error", re.I)


_RE_SHA_CONTRAT = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _verdict_aucun(detail: str, workdir: str, effet: str) -> str | None:
    """Contrat `aucun` (reverification en lecture seule) : ne doit RIEN ecrire ; s'il conclut FAIT, son pointer_ref
    doit etre le SHA REEL d'un commit du depot (git cat-file -e), jamais un gabarit. Tout ecrit = RIEN_PRODUIT nomme,
    un FAIT non prouve = ILLISIBLE (defaut job_2751ecc3, 7/11 : run_tests.py ecrit et un faux SHA de gabarit)."""
    import subprocess as _sp
    m = re.search(r"commits produits : (\d+) \([^)]*\) ; fichiers non commites : (\d+)", effet or "")
    if m and (m.group(1) != "0" or m.group(2) != "0"):
        return "aucun artefact attendu (lecture seule), or %s commit(s) et %s fichier(s) produit(s)" % (
            m.group(1), m.group(2))
    txt = str(detail or "")
    # Le verdict s'ecrit en majuscules : un « fait » de prose n'est pas une conclusion (NR du 7/11).
    sans_non = re.sub(r"\bNON[ _]FAIT\b", "", txt)
    if not re.search(r"\bFAIT\b", sans_non):
        return None     # NON FAIT / ILLISIBLE : issue admise, rien a rejeter
    refs = _pointer_refs(txt)
    ref = (refs[-1] if refs else "").strip()
    sha = ""
    for morceau in _morceaux_ref(ref):
        c = re.sub(r"^commit[: ]\s*", "", morceau.strip(), flags=re.I)
        if _RE_SHA_CONTRAT.match(c):
            sha = c
            break
    if not sha:
        return "%s FAIT sans SHA reel (pointer_ref %r)" % (_MARQUE_ILLISIBLE, ref[:80])
    try:
        r = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "cat-file", "-e", sha],
                    capture_output=True, text=True, errors="replace", timeout=20, env=_env_git())
    except Exception as e:  # noqa: BLE001 - sonde muette : ni FAIT ni RIEN_PRODUIT
        return "%s git illisible (%s)" % (_MARQUE_ILLISIBLE, type(e).__name__)
    if r.returncode != 0:
        return "%s SHA inexistant dans le depot : %s" % (_MARQUE_ILLISIBLE, sha)
    return None


def _verdict_contrat(contrat: dict, detail: str, workdir: str, effet: str) -> str | None:
    """Motif de rejet (RIEN_PRODUIT) du contrat structure, ou None si respecte."""
    import subprocess as _sp
    t = contrat["type"]
    if t == "aucun":
        return _verdict_aucun(str(detail), workdir, effet)
    txt = str(detail or "")
    if not txt.strip():
        return "rapport vide"
    if _RE_FAUSSE_REPONSE.search(txt):
        return "reponse = erreur de proxy ou trace de raisonnement, pas un compte rendu"
    if t == "tests_verts":
        # 7/11 (owner) : le verdict vient d'un REJEU reel (JUnit), plus de la prose de l'agent.
        etat, cause = _rejouer_contrat_tests(workdir, contrat.get("chemins") or [])
        if etat == "VERT":
            return None
        if etat == "ROUGE":
            return "rejeu ROUGE : %s" % cause
        return "%s rejeu illisible, ni vert ni rouge : %s" % (_MARQUE_ILLISIBLE, cause)
    m = re.search(r"commits produits : (\d+)", effet or "")
    if not m or m.group(1) == "0":
        return "0 commit produit"
    for c in contrat["chemins"]:
        try:
            r = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "cat-file", "-s", "HEAD:" + c],
                        capture_output=True, text=True, errors="replace", timeout=20, env=_env_git())
        except Exception as e:  # noqa: BLE001
            return "git illisible (%s)" % type(e).__name__
        if r.returncode != 0:
            return "chemin attendu absent de l'arbre : %s" % c
        if t == "fichier" and r.stdout.strip() == "0":
            return "chemin attendu vide : %s" % c
    return None


# Le REFUS du depot seulement (hook pre-commit, gate) : « IMPOSSIBLE : status illisible » et « ECHOUE (exception) »
# restent jugees par les gardes d'effet ([AUCUN EFFET] -> VIDE), test_codex_sans_effet_n_est_pas_un_succes.
_RE_COMMIT_REFUSE = re.compile(r"commit executeur REFUSE rc=")


def _motif_refus_commit(detail: str) -> str | None:
    """Dans _notes_executeur(detail), texte apres 'commit executeur REFUSE rc=' borne a 300 car."""
    notes = _notes_executeur(detail)
    cle = "commit executeur REFUSE rc="
    idx = notes.find(cle)
    if idx < 0:
        return None
    suite = notes[idx + len(cle):].strip()
    return suite[:300] if suite else None


def _juger_livraison(ok: bool, detail: str, workdir: str, avant, autorises=None, desc: str | None = None,
                     consigne_servie: str | None = None, modele_demande: str | None = None) -> tuple:
    """Jugement COMMUN d'une delegation (AGY, CODEX) sur ce qu'elle a LIVRE, pas sur ce qu'elle dit.
    Rend (ok, effet, intent_rendu). Extrait de `_delegate_to_agy` le 16/10 : une seconde voie qui le
    recopierait divergerait de la premiere en silence."""
    effet = _effet_observe(workdir, avant)
    rendu = _intent_rendu(str(detail))
    if rendu:
        ok = False      # l'agent dit lui-meme « pas fait » : son intent prime sur l'enveloppe du CLI
    absent = None if rendu else _artefact_declare_absent(str(detail), workdir)
    if absent:
        ok = False      # DECLARE n'est pas ACHIEVED : l'artefact pointe n'existe pas
        effet = "%s ; [artefact ABSENT] %s" % (effet, absent)
    non_produit = None if (rendu or absent) else _artefact_non_produit(str(detail), workdir, avant)
    if non_produit:
        ok = False
        effet = "%s ; %s" % (effet, non_produit)
    # Garde d'ACCUSE DE RECEPTION (2026-10-02, bb:delegate_agy_sans_garde_accuse) : une promesse sans compte
    # rendu est un echec NOMME. Une reponse qui pointe un artefact est jugee par le controle ci-dessus.
    if (not rendu and not absent and not non_produit and not _a_pointer_ref(detail)
            and _est_accuse_reception(str(detail))):
        ok = False
        effet = "%s ; [ACCUSE DE RECEPTION] promesse sans compte rendu" % effet
    nl = None if (rendu or absent or non_produit) else _non_livre(effet, str(detail))
    if nl:
        # 22/10 : du travail laisse non committe n'est pas un ECHEC, c'est une livraison PARTIELLE -- le verdict se
        # LIT sur l'ARTEFACT. L'executeur le committe ou le SAUVE (`_preserver_livraison`) : il ne doit plus
        # disparaitre derriere un FAILURE (job_af6dbf75, job_818ec8d8, job_d7d57967).
        effet = "%s ; %s ; %s" % (effet, nl, _livres_non_committes(workdir))
    if not rendu and "REFUSE par le scorecard" in _notes_executeur(detail):
        ok = False      # 20/10 (job_2a6a27b3) : le pointer_ref exemptait _non_livre ; un refus du scorecard est NOMME
        effet = "%s ; [SCORECARD REFUSE] commit de l'executeur refuse, travail laisse non livre" % effet
    elif not rendu and _RE_COMMIT_REFUSE.search(_notes_executeur(detail)):
        # 24/10 : le gate qualite du pre-commit bloquait le worktree claude_headless ; 4 delegations sorties OK avec
        # 0 commit. Un commit refuse par le depot (hook, gate), echoue ou impossible est un ECHEC NOMME, pointeur ou non.
        ok = False
        m = _motif_refus_commit(detail)
        effet = "%s ; [COMMIT REFUSE] commit de l'executeur refuse par le depot, travail laisse non livre%s" % (
            effet, (" : %s" % m) if m else "")
    contrat = _contrat_livrable(desc) if desc is not None else None
    if desc is not None and contrat is None:
        logging.getLogger(__name__).warning("juge: pas de contrat de livrable structure, repli sur l'heuristique "
                                            "textuelle (livrable non declare hors bande)")
    rien = None
    if contrat is not None:
        motif = None if rendu else _verdict_contrat(contrat, str(detail), workdir, effet)
        if motif and _MARQUE_ILLISIBLE in motif:
            # ILLISIBLE : ni vert ni rouge ; hors _MARQUES_VIDE donc jamais VIDE, jamais compte reussi.
            ok = False
            effet = "%s ; %s contrat livrable %s : %s" % (effet, _MARQUE_ILLISIBLE, contrat["type"], motif)
        elif motif:
            rien = "[RIEN PRODUIT] (RIEN_PRODUIT) contrat livrable %s : %s" % (contrat["type"], motif)
    elif not (rendu or absent or non_produit or nl):
        rien = _rien_produit(effet, str(detail), desc)
    if rien:
        ok = False      # ni commit ni fichier ni artefact pointe : DECLARE n'est pas ACHIEVED (2026-10-20)
        effet = "%s ; %s" % (effet, rien)
    # R3 (17/10) : le CONTENU des commits, pas leur nombre -- livraison vide, tests existants touches.
    contenu = None if (rendu or absent or nl or non_produit) else _contenu_livre(workdir, avant, autorises)
    if not contenu and not (rendu or absent or nl or non_produit):
        contenu = _contenu_recopie(workdir, avant, desc)
    if contenu:
        ok = False
        effet = "%s ; %s" % (effet, contenu)
    elif autorises and not (rendu or absent or nl or non_produit):
        effet = "%s ; [tests modifies AUTORISES par la tache] %s" % (effet, ", ".join(autorises))
    if ok and not rendu:
        rnn = _red_non_observe(desc, workdir, avant)
        if rnn:
            ok = False      # PARTIEL (le code peut etre bon), jamais OK_DONE
            effet = "%s ; %s" % (effet, rnn)
    # 9/11 (etape 2 owner) : garde livraison contexte et modele
    _servie = consigne_servie if consigne_servie is not None else desc
    _mod = modele_demande if modele_demande is not None else ("demande" if "repli sur le modele par defaut" in str(detail).lower() else "")
    ok_ctx, cause_ctx = garde_livraison_contexte(desc, _servie, detail, _mod)
    if not ok_ctx:
        ok = False
        effet = "%s ; [%s] livraison refusee" % (effet, cause_ctx)
    return bool(ok), effet, rendu


# Verdict AUTOMATIQUE d'une delegation ratee (owner 18/10 : « le corps doit avoir la notion de recompense par
# resultat »). Liste BLANCHE : seul un vide PROUVE par le juge de livraison est VIDE ; une panne d'infrastructure n'est
# pas la faute du repondeur (19/10 : 429 et sessions muettes chez des modeles qui livraient la veille) -> INCONNU.
_RE_PANNE_INFRA = re.compile(r"harness MUET|erreur ACP|TimeoutError|timeout en attente|\b429\b|\b402\b|Too Many "
                             r"Requests|Payment Required|session occupee|jeton absent|authentication failed|not logged in|unauthorized|\b401\b", re.I)
# [RIEN PRODUIT] (20/10) passe AVANT le garde [AUCUN EFFET] des voies Codex / Vibe / OpenCode : absent d'ici, il
# rabattait une livraison vide de VIDE a INCONNU.
_MARQUES_VIDE = ("[AUCUN EFFET]", "[RIEN PRODUIT]", "[LIVRAISON VIDE]", "[ACCUSE DE RECEPTION]", "[artefact ABSENT]",
                 "[RECOPIE CONSIGNE]")


def verdict_automatique(ok: bool, effet: str, detail: str, rendu) -> str | None:
    """VIDE | REJETEE | INCONNU pour un echec ; None pour une reussite (INTEGREE/PARTIELLE exigent une relecture) ou
    un rejet du scorecard deja consigne par `_committer_pour_agent`."""
    if ok:
        return None
    effet, detail = str(effet), str(detail)
    if "REFUSE par le scorecard" in detail or "[RED_NON_OBSERVE]" in effet:
        return None
    if "[TESTS TOUCHES]" in effet or "[SYNTAXE INVALIDE]" in effet:
        return "REJETEE"
    if rendu or _panne_en_tete(detail):
        return "INCONNU"
    if any(m in effet for m in _MARQUES_VIDE):
        return "VIDE"
    return "INCONNU"


def _consigner_verdict_auto(agent: str, task_id, ok: bool, effet: str, detail: str, rendu,
                            classe: str = "M:ecrit") -> None:
    """Consigne le verdict automatique au registre de motivation, puis emet le transient d'un blocage (panne
    fournisseur ou vide prouve) ; ne casse jamais l'executeur. `NOKIDO_VERDICT_AUTO=0` coupe tout (le conftest des NR
    le pose : sans lui, les tests de delegation ecrivaient de faux verdicts dans le vrai registre, 19/10)."""
    if os.environ.get("NOKIDO_VERDICT_AUTO", "1") == "0":
        return
    try:
        v = verdict_automatique(ok, effet, detail, rendu)
    except Exception as e:  # noqa: BLE001 - le verdict ne casse jamais l'executeur
        log.warning(f"  verdict automatique ILLISIBLE ({type(e).__name__})")
        return
    if v is None:
        return
    try:
        from nokido_agent.app.forge_motivation import recompenser_resultat
        recompenser_resultat(agent, classe, v, preuve="%s : %s" % (str(task_id)[:40], str(effet)[-200:]))
    except Exception as e:  # noqa: BLE001 - le verdict ne casse jamais l'executeur
        log.warning(f"  verdict automatique NON consigne ({type(e).__name__})")
    if v == "VIDE":
        _emettre_transient(agent, task_id, "vide", effet)
    elif v == "INCONNU" and not rendu and _panne_en_tete(detail):
        _emettre_transient(agent, task_id, "panne", detail)


def _panne_en_tete(detail) -> bool:
    """19/10 (relecture pair_1df7144aae22bdf5) : une panne d'infrastructure se lit en TETE de sortie (message de
    l'executeur ou erreur du CLI), jamais au milieu d'un compte rendu qui CITE un 429 -- un vide prouve passait INCONNU."""
    return bool(_RE_PANNE_INFRA.search(str(detail or "").lstrip()[:400]))


# EMETTEUR DE TRANSIENTS (decision owner 19/10). Le canal nokido.transient.v1 existait sans emetteur de blocages : le
# bus est le tableau noir (discovered_facts, lu par les hooks d'inbox des CLI), la cle dedoublonne par agent x effet,
# `expire_at` borne la vie du signal -- pas de demon parallele.
_TRANSIENT_TTL_S = int(os.environ.get("LAFORGE_TRANSIENT_TTL_S", "1800"))


def _emettre_transient(agent: str, task_id, effet: str, resume) -> None:
    try:
        import hashlib
        from nokido_agent.app.forge_swarm_blackboard import apply_fact_sync
        # 19/10 (relecture pair_1df7144aae22bdf5) : caviarde AVANT publication -- le `detail` brut d'un CLI peut recopier
        # un en-tete d'autorisation ; `_clore_delegation` le caviardait deja, le transient non.
        resume = _caviarder(str(resume or ""))[-300:]
        t = {"intent": "TRANSIENT_OBSERVED", "schema": "nokido.transient.v1", "source": {"surface": str(agent)},
             "provenance": "forge_task_executor", "effect": effet, "source_call_id": str(task_id)[:60],
             "content_fingerprint": "F-" + hashlib.sha256(("%s|%s" % (effet, resume)).encode("utf-8")).hexdigest()[:16],
             "resume": resume, "expire_at": time.time() + _TRANSIENT_TTL_S}
        r = apply_fact_sync("discovered_facts", json.dumps(t, ensure_ascii=False),
                            key="transient_%s_%s" % (str(agent).upper(), effet), category="transient",
                            trust=0.6, source="TASK_EXECUTOR", ring=1)
        if isinstance(r, dict) and r.get("error"):
            log.warning(f"  transient {effet} de {agent} REFUSE : {str(r['error'])[:150]}")
    except Exception as e:  # noqa: BLE001 - le signal ne casse jamais l'executeur
        log.warning(f"  transient {effet} de {agent} NON emis ({type(e).__name__})")


def transients_actifs() -> list:
    """Transients non expires du tableau noir ([{cle, ...}]), du plus recent au plus ancien ; illisible -> ignore."""
    from nokido_agent.app.forge_swarm_blackboard import read_zone
    maintenant, out = time.time(), []
    for f in read_zone("discovered_facts", category="transient", limit=200) or []:
        try:
            t = json.loads(f.get("value") or "")
        except (TypeError, ValueError):
            continue    # muet-ok : valeur non JSON = pas un transient v1, ecartee
        if isinstance(t, dict) and float(t.get("expire_at") or 0) > maintenant:
            out.append(dict(t, cle=f.get("key")))
    return out


def lire_sortie_agy(raw: str) -> tuple:
    """(ok, detail) d'une sortie `agy --print` JSON. SUCCESS a reponse VIDE = echec qui nomme les actions refusees
    par le bac (19/10, job_3e380d6a : « AGY OK » sur une reponse vide, ViewFile refuse) ; sortie illisible = echec."""
    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        return False, (raw or "")[:400] or "agy: sortie vide"
    if not isinstance(d, dict):
        return False, str(raw)[:400]
    reponse = str(d.get("response") or "").strip()
    if str(d.get("status", "")).upper() == "SUCCESS":
        if reponse:
            return True, reponse
        # 31/10 (job_add2906f) : coupe par son --print-timeout en plein tour, agy rend « SUCCESS » a reponse vide ; lu
        # « REPONSE VIDE », le TIMEOUT etait masque -- et la consigne trop lourde avec lui.
        if str(d.get("finished_reason") or "").lower() == "print_timeout":
            return False, "[TIMEOUT] agy print_timeout apres %ss, tour en cours, reponse vide" % (
                int(float(d.get("duration_seconds") or 0)))
        # 30/10 : le NOM de l'outil seul (« read_file ») ne disait pas QUOI etait refuse -- 4 taches AGY perdues sans
        # savoir si le chemin sortait du worktree. Les autres champs du refus (chemin, arguments) sont rendus, tronques.
        def _un_refus(a) -> str:
            if not isinstance(a, dict):
                return str(a)[:200]
            reste = {k: v for k, v in a.items() if k != "action"}
            return "%s%s" % (a.get("action") or "?", (" " + json.dumps(reste, ensure_ascii=False)[:200]) if reste else "")

        refus = ", ".join(_un_refus(a) for a in (d.get("denied_actions") or []))
        return False, "[REPONSE VIDE] agy SUCCESS sans reponse%s" % (" ; actions refusees par le bac : " + refus
                                                                     if refus else "")
    return False, reponse or str(d.get("error") or "")[:400] or str(raw)[:400]


def _bin_agy() -> str:
    """Binaire AGY : `LAFORGE_AGY_BIN`, sinon l'installation ABSOLUE de l'owner (jamais le PATH du
    compte de service, qui ne montre pas le profil de l'owner). Source UNIQUE : la facade
    headless reprend CE binaire, elle n'en invente pas un autre."""
    return os.environ.get("LAFORGE_AGY_BIN", r"%USERPROFILE%\AppData\Local\agy\bin\agy.exe")


def _effort_agy(desc: str = "") -> str:
    """Effort AGY : `low|high` SEULEMENT (gemini-3.1-pro refuse `medium`).

    30/10 (owner : « adapter l'effort selon la tache, AGY je le paye aussi ») : une petite tache whoami a coute
    405 k tokens et 611 s sous `high`. L'effort suit la TAILLE declaree (`_taille_tache`) : L -> high ; S, M ou non
    declaree -> low. `LAFORGE_AGY_EFFORT` (low|high) reste un forcage explicite."""
    # 8/11 (mesure, journal agy_job_94f34e7a) : « --model gemini-4-argon-medium conflicts with --effort=low » ->
    # RIEN_PRODUIT. Un modele FORCE qui porte son niveau dans son nom (owner : « argon a low/medium/high ») impose
    # ce niveau a --effort ; sinon agy refuse la tache avant de la lire.
    niveau = os.environ.get("LAFORGE_AGY_MODEL", "").rsplit("-", 1)[-1]
    if niveau in ("low", "medium", "high"):
        return niveau
    force = os.environ.get("LAFORGE_AGY_EFFORT", "")
    if force in ("low", "high"):
        return force
    try:   # LA table unique (levier A, owner 23/10) : aucune valeur dispersee ici
        try:
            from forge_palier_effort import resoudre
        except ImportError:
            from tools.forge_palier_effort import resoudre
        eff = resoudre("agy", _taille_tache(desc) or "M").get("effort")
    except Exception as e:  # noqa: BLE001 - table illisible : DIT, et l'effort le plus econome
        log.warning(f"  effort AGY : table forge_palier_effort ILLISIBLE ({type(e).__name__}) -- low")
        eff = None
    return eff if eff in ("low", "medium", "high") else "low"


def _etat_quota_modele_agy(modele: str) -> str:
    """Etat du tracker pour un modele AGY : ok | quota_reached | illisible | inconnu. Tracker injoignable ou modele
    non suivi = `inconnu` (jamais `ok` par defaut)."""
    try:
        try:
            import forge_quota_tracker as _qt
        except ImportError:
            from nokido_agent.app import forge_quota_tracker as _qt
        return str((_qt._fetch_agy_models_quota().get(modele) or {}).get("status") or "inconnu")
    except Exception as e:  # noqa: BLE001 - tracker illisible : INCONNU, dit
        log.warning(f"  etat quota AGY illisible pour {modele} ({type(e).__name__}) -- traite comme inconnu")
        return "inconnu"


_L_ATTENTE_DEPUIS: dict[str, float] = {}


def _motif_attente_L(modele: str, duree_s: float) -> str:
    """Pourquoi une tache L attend : jamais une attente muette. Ce n'est ni une panne ni un echec."""
    h = int(max(0.0, duree_s) // 3600)
    m = int(max(0.0, duree_s) % 3600 // 60)
    suite = ""
    if duree_s >= 3600:
        suite = (" ATTENTE LONGUE : seule une delegation reussie en taille S ou M sur ce modele (ou en L) l'etablit ;"
                 " sans elle L attend encore.")
    return (f"AGY taille L : aucune preuve recente (< 6 h) que {modele} est sain, en attente depuis {h}h{m:02d}m ; "
            f"une tache S ou M reussie sur ce modele leve l'attente. Pas un echec, pas de reaffectation.{suite}")


def _modele_agy(desc: str = "", maintenant: float | None = None) -> str | None:
    """Modele AGY de LA table (`forge_palier_effort`) selon la taille ; `LAFORGE_AGY_MODEL` = forcage explicite.
    Si le modele de la table est hors quota/epuise, utilise le repli declare par la table.
    30/10 : sans `--model`, chaque tache AGY tournait sur le /model de l'owner (Gemini 4 Argon : vide les tokens)."""
    force = os.environ.get("LAFORGE_AGY_MODEL", "")
    if force:
        # 8/11 (owner : « quota Argon mort 162 h, retranche-toi AUTOMATIQUEMENT sur le 3.8 selon l'effort voulu ») :
        # modele force marque indisponible (registre des surfaces) ou hors quota (tracker) -> meme NIVEAU en 3.8-flash
        # (argon-medium -> gemini-3.8-flash-medium) ; --effort suit le meme suffixe (_effort_agy). Retour au modele force
        # des que le registre le relache : aucun geste a refaire.
        motif = None
        try:
            motif = surface_est_indisponible(force, maintenant)
        except Exception as e:  # noqa: BLE001 - registre illisible : on le DIT, le tracker tranche ensuite
            log.warning(f"  modele AGY force {force} : registre des surfaces illisible ({type(e).__name__})")
        if not motif and _etat_quota_modele_agy(force) == "quota_reached":
            motif = "quota_reached (tracker)"
        if motif:
            niveau = force.rsplit("-", 1)[-1]
            niveau = niveau if niveau in ("low", "medium", "high") else "medium"
            repli = os.environ.get("LAFORGE_AGY_REPLI_FORCE", "") or "gemini-3.8-flash-%s" % niveau
            log.warning(f"  modele AGY force {force} INDISPONIBLE ({motif}) -> repli automatique {repli}")
            return repli
        return force
    try:
        try:
            from forge_palier_effort import resoudre
        except ImportError:
            from tools.forge_palier_effort import resoudre
        taille = _taille_tache(desc) or "M"
        modele = resoudre("agy", taille, maintenant=maintenant).get("modele")
        if taille == "L" and modele and _etat_quota_modele_agy(modele) in ("illisible", "inconnu"):
            # UNKNOWN n'est ni sain ni epuise : pas de grosse tache, mais pas de marque de panne (None = pending)
            instant = time.time() if maintenant is None else float(maintenant)
            depuis = _L_ATTENTE_DEPUIS.setdefault(modele, instant)
            log.warning("  " + _motif_attente_L(modele, instant - depuis))
            return None
        if taille == "L" and modele:
            _L_ATTENTE_DEPUIS.pop(modele, None)
        return modele
    except Exception as e:  # noqa: BLE001 - table illisible ou modele hors quota : DIT, defaut du binaire
        log.warning(f"  modele AGY : table forge_palier_effort ILLISIBLE ou refus ({type(e).__name__}) -- defaut agy")
        return None


_PLAFOND_PRECHARGEMENT_CHARS = 4000
_RE_CIBLE_LIGNE = re.compile(
    r"(?<![\w\\/:.<>-])([A-Za-z]:[\\/][^\n\r;,'\"<>]+\.py|[A-Za-z]:[\\/][^\n\r;,'\"<>]+\.env[^\n\r;,'\"<>]*|(?:[.\w\-\\/]+[\\/])?[\w.\-]+\.py|(?:[.\w\-\\/]+[\\/])?\.env[^\s:;,'\"<>]*|\.env[^\s:;,'\"<>]*):(\d+)(?![\w:])",
    re.IGNORECASE,
)
_RE_CIBLE_FONCTION = re.compile(
    r"(?<![\w\\/:.<>-])([A-Za-z]:[\\/][^\n\r;,'\"<>]+\.py|[A-Za-z]:[\\/][^\n\r;,'\"<>]+\.env[^\n\r;,'\"<>]*|(?:[.\w\-\\/]+[\\/])?[\w.\-]+\.py|(?:[.\w\-\\/]+[\\/])?\.env[^\s:;,'\"<>]*|\.env[^\s:;,'\"<>]*)\s+([a-zA-Z_][a-zA-Z0-9_]*)(?![\w.])",
    re.IGNORECASE,
)

_MOTIFS_REFUS_PRECHARGEMENT = (
    ".env",
    "sandbox",
    "logs",
    ".git",
    "vault",
    "secret",
    "key",
    "token",
    "password",
    "credential",
)


def _verifier_chemin_prechargement(p_cible: Path, racine_depot: Path) -> tuple[bool, str]:
    """Verifie que le chemin cible est autorise pour le prechargement :
    - resolu par realpath (ni `..` ni lien symbolique sortant)
    - strictement a l'interieur de la racine du depot
    - hors `.env*`, `sandbox/`, `logs/`, `.git/`, et fichiers de cles/coffre/secrets.
    Rend (autorise: bool, motif_refus: str).
    """
    try:
        # realpath resout liens symboliques, '..' et normalise le chemin
        p_real = Path(os.path.realpath(str(p_cible)))
        r_real = Path(os.path.realpath(str(racine_depot)))
    except Exception as e:
        return False, f"erreur resolution chemin: {e}"

    # Verifie l'appartenance stricte au depot Nokido
    try:
        rel = p_real.relative_to(r_real)
    except ValueError:
        return False, "hors depot"

    # Verifie qu'il n'est pas la racine elle-meme
    parts = rel.parts
    if not parts:
        return False, "racine depot"

    # Verifie si un segment de chemin ou le nom de fichier enfreint les regles de securite
    lower_parts = [part.lower() for part in parts]
    nom_fichier = lower_parts[-1]

    # Interdiction des dossiers sandbox, logs, .git
    for dossier_interdit in ("sandbox", "logs", ".git"):
        if dossier_interdit in lower_parts:
            return False, f"dossier interdit: {dossier_interdit}"

    # Interdiction de .env ou .env.*
    for part in lower_parts:
        if part == ".env" or part.startswith(".env.") or part.startswith(".env_"):
            return False, "fichier d'environnement (.env)"

    # Interdiction des fichiers contenant des motifs sensibles
    for motif in ("vault", "secret", "key", "token", "password", "credential"):
        if motif in nom_fichier:
            return False, f"motif sensible ({motif})"

    # Liste blanche des dossiers racines autorises dans le depot Nokido
    dossier_racine = lower_parts[0]
    if dossier_racine not in ("app", "tools", "tests", "docs", "config"):
        return False, f"dossier hors liste blanche ({dossier_racine})"

    return True, ""


def _extraire_corps_ast(chemin: Path, symbole: str | None = None, ligne: int | None = None) -> tuple[str | None, str | None]:
    """Extrait le corps complet d'une fonction/classe par AST ou autour de la ligne.
    Rend (corps, motif_erreur).
    """
    try:
        source = chemin.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return None, f"impossible de lire {chemin.name}: {e}"
    try:
        tree = ast.parse(source)
    except Exception as e:
        return None, f"impossible de parser {chemin.name}: {e}"

    src_lines = source.splitlines(keepends=True)

    if ligne is not None:
        candidat = None
        cand_span = 10**9
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                end = getattr(node, "end_lineno", node.lineno)
                if node.lineno <= ligne <= end:
                    span = end - node.lineno
                    if span < cand_span:
                        candidat = node
                        cand_span = span
        if candidat is not None:
            end = getattr(candidat, "end_lineno", candidat.lineno)
            corps = "".join(src_lines[candidat.lineno - 1:end])
            return f"### {chemin.name} — {candidat.name} (L{candidat.lineno}–L{end})\n```python\n{corps.rstrip()}\n```", None
        return None, f"aucune fonction ou classe englobant la ligne {ligne} dans {chemin.name}"

    if symbole:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbole:
                    end = getattr(node, "end_lineno", node.lineno)
                    corps = "".join(src_lines[node.lineno - 1:end])
                    return f"### {chemin.name} — {symbole} (L{node.lineno}–L{end})\n```python\n{corps.rstrip()}\n```", None
        return None, f"'{symbole}' non trouve dans {chemin.name}"

    return None, "aucun symbole ni ligne specifie"


def _resoudre_cible_prechargement(f_str: str, wd: Path) -> tuple[Path, Path]:
    """Rend (chemin, racine de validation). La racine est celle dont releve la cible :
    le worktree `wd` de la tache ou le depot ROOT. Tout autre emplacement est valide
    contre ROOT (donc refuse « hors depot »)."""
    p = Path(f_str)
    if not p.is_absolute():
        if (wd / p).exists():
            return wd / p, wd
        return ROOT / p, ROOT
    pr = Path(os.path.realpath(str(p)))
    wr = Path(os.path.realpath(str(wd)))
    rr = Path(os.path.realpath(str(ROOT)))
    if wr != rr and wr in pr.parents:
        return pr, wd
    if rr in pr.parents:
        cand = wd / pr.relative_to(rr)
        if wr != rr and os.path.lexists(cand):
            return cand, wd
        return pr, ROOT
    return pr, ROOT


def precharger_corps_consigne(
    consigne: str, workdir: str | Path | None = None, max_caracteres: int = _PLAFOND_PRECHARGEMENT_CHARS
) -> str:
    """Precharge le corps des fonctions/lignes citees sous forme `fichier.py fonction` ou `fichier.py:ligne`
    dans la consigne afin de reduire les tours d'exploration des agents delegues.
    """
    if not consigne:
        return ""
    # Idempotence / double injection : ne pas reinjecter si deja present
    if "[PRECHARGEMENT corps de code cites dans la consigne]" in consigne:
        return consigne

    wd = Path(workdir) if workdir else ROOT
    blocs = []
    introuvables = []
    refuses = []
    vus = set()

    # 1. fichier.py:ligne
    for m in _RE_CIBLE_LIGNE.finditer(consigne):
        f_str, l_str = m.group(1), m.group(2)
        cle = (f_str, int(l_str))
        if cle in vus:
            continue
        vus.add(cle)

        p, racine = _resoudre_cible_prechargement(f_str, wd)
        autorise, motif_refus = _verifier_chemin_prechargement(p, racine)
        if not autorise:
            refuses.append(f"{Path(f_str).name}")
            continue

        if not p.exists() or not p.is_file():
            introuvables.append(f"{f_str}:{l_str} (fichier absent)")
            continue

        corps, err = _extraire_corps_ast(p, ligne=int(l_str))
        if corps:
            blocs.append(corps)
        else:
            introuvables.append(f"{f_str}:{l_str} ({err})")

    # 2. fichier.py fonction
    for m in _RE_CIBLE_FONCTION.finditer(consigne):
        f_str, sym = m.group(1), m.group(2)
        # Ignorer des faux positifs courants (mots de consigne ou extensions)
        if sym.lower() in ("py", "md", "txt", "json", "toml", "yaml", "yml", "rst", "et", "ou", "dans", "pour", "avec"):
            continue
        cle = (f_str, sym)
        if cle in vus:
            continue
        vus.add(cle)

        p, racine = _resoudre_cible_prechargement(f_str, wd)
        autorise, motif_refus = _verifier_chemin_prechargement(p, racine)
        if not autorise:
            refuses.append(f"{Path(f_str).name}")
            continue

        if not p.exists() or not p.is_file():
            introuvables.append(f"{f_str} {sym} (fichier absent)")
            continue

        corps, err = _extraire_corps_ast(p, symbole=sym)
        if corps:
            blocs.append(corps)
        else:
            introuvables.append(f"{f_str} {sym} ({err})")

    if not blocs and not introuvables and not refuses:
        return consigne

    lignes_ajout = ["\n\n[PRECHARGEMENT corps de code cites dans la consigne]"]
    if refuses:
        for r_nom in refuses:
            lignes_ajout.append(f"[PRECHARGEMENT refuse: {r_nom}]")

    budget_restant = max(0, int(max_caracteres))  # plafond strictement respecte

    # Prendre en compte l'empreinte des introuvables dans le budget restant
    introuvables_lignes = []
    if introuvables:
        for item in introuvables:
            lig = f"[PRECHARGEMENT introuvable: {item}]"
            introuvables_lignes.append(lig)
            budget_restant -= len(lig) + 1  # +1 pour saut de ligne

    lignes_ajout.extend(introuvables_lignes)

    blocs_ecartes = 0
    taille_ecartee = 0

    for b in blocs:
        if budget_restant <= 0:
            blocs_ecartes += 1
            taille_ecartee += len(b)
            continue

        if len(b) > budget_restant:
            suffixe = "\n... [tronque]\n```"
            garde = budget_restant - len(suffixe)
            if garde <= 0:
                blocs_ecartes += 1
                taille_ecartee += len(b)
            else:
                taille_ecartee += len(b) - garde
                lignes_ajout.append(b[:garde] + suffixe)
            budget_restant = 0
        else:
            budget_restant -= len(b) + 1
            lignes_ajout.append(b)

    if blocs_ecartes > 0 or taille_ecartee > 0:
        lignes_ajout.append(
            f"[PRECHARGEMENT plafond atteint: {blocs_ecartes} bloc(s) ecarte(s), {taille_ecartee} caractere(s) non inclus]"
        )

    ajout_texte = _caviarder("\n".join(lignes_ajout))
    return consigne + ajout_texte


_PLAFOND_DOCUMENTS_CITES_CHARS = int(os.environ.get("LAFORGE_PLAFOND_DOCUMENTS_CITES_CHARS", "16000"))
PLAFOND_DOCUMENTS_CITES_CHARS = _PLAFOND_DOCUMENTS_CITES_CHARS

_RE_DOC_CITE = re.compile(
    # Relecture 9/11 : espaces permis SEULEMENT dans un chemin absolu (C:/Script python IA/...), segments courts
    # (*?) pour s'arreter au premier document ; un chemin relatif n'avale plus le mot qui le precede.
    r"""(?<![\w\\/:.<>])("""
    r"""(?:[A-Za-z]:[\\/](?:[^\\/\r\n;,\"'`<>|*?:]+?[\\/])*?[^\\/\r\n;,\"'`<>|*?:]+?"""
    r"""|(?:\.{1,2}[\\/])?(?:[^\\/\r\n\s;,\"'`<>|*?:]+[\\/])*[^\\/\r\n\s;,\"'`<>|*?:]+)"""
    r"""\.(?:md|txt|json|rst)"""
    r""")(?=[;,\"'`<>|\s\)\].:]|\Z)""",
    re.IGNORECASE,
)









def servir_documents_cites(
    consigne: str,
    workdir: str | Path | None = None,
    racines_autorisees: list[str | Path] | None = None,
    ledger_db: str | Path | None = None,
    max_caracteres: int = _PLAFOND_DOCUMENTS_CITES_CHARS,
) -> tuple[str, dict]:
    """Extrait les documents cites (hors code) dans la consigne, les valide et les sert via le context_ledger existant."""
    if not consigne:
        return "", {"entrees": [], "refuses": []}
    if "[CONTEXTE SERVI par Nokido]" in consigne:
        return consigne, {"entrees": [], "refuses": []}

    wd = Path(workdir) if workdir else ROOT
    racines = [Path(r) for r in (racines_autorisees or [])]

    vus = set()
    refuses = []
    valides = []

    for m in _RE_DOC_CITE.finditer(consigne):
        f_str = m.group(1).rstrip(".):]")
        cle = f_str.replace("\\", "/").lower()
        if cle in vus:
            continue
        vus.add(cle)

        p = Path(f_str)
        if p.is_absolute():
            cand = p
        else:
            if (wd / p).exists():
                cand = wd / p
            else:
                cand = None
                for r in racines:
                    if (r / p).exists():
                        cand = r / p
                        break
                if cand is None:
                    cand = wd / p

        try:
            cand_real = Path(os.path.realpath(str(cand)))
        except Exception:
            refuses.append(f_str)
            continue

        autorise = False
        for r in racines:
            try:
                cand_real.relative_to(Path(os.path.realpath(str(r))))
                autorise = True
                break
            except ValueError:  # muet-ok : hors de cette racine, on essaie la suivante
                pass

        if not autorise:
            refuses.append(f_str)
            continue

        if not cand_real.is_file():
            continue

        valides.append(cand_real)

    if not valides:
        manifeste = {"entrees": []}
        if refuses:
            manifeste["refuses"] = refuses
        return consigne, manifeste

    ldb = Path(ledger_db) if ledger_db else (ROOT / "sandbox" / "context_ledger.db")
    # La db vit LÀ OÙ l'appelant l'a nommée : plus de copie temporaire dans ROOT/sandbox (un
    # compte d'exécution sans écriture y échouait, mesure 9/11). Le ledger reste borné à sa tâche.
    ledger = ContextLedger(db_path=ldb, racine=ROOT, racines_autorisees=racines, exiger_sandbox=False)
    uris_servis = []
    for doc_path in valides:
        uri = doc_path.as_posix()
        ledger.indexer(uri, essence=doc_path.name)
        uris_servis.append(uri)

    res = ledger.servir("*", budget_car=max_caracteres, uris=uris_servis)
    payload = res.get("payload", "")
    manifeste = res.get("manifeste", {})
    if refuses:
        # Fusionner : un document privé (membrane) et un chemin hors racines se disent tous deux.
        manifeste["refuses"] = list(dict.fromkeys(list(manifeste.get("refuses", [])) + refuses))

    if not payload:
        return consigne, manifeste

    # Caviarder le payload avant injection
    payload = _caviarder(payload)

    enrichie = consigne + "\n\n[CONTEXTE SERVI par Nokido]\n" + payload
    return enrichie, manifeste


def garde_livraison_contexte(
    desc: str | None,
    consigne_servie: str | None,
    rendu: str | None,
    modele_demande: str | None,
) -> tuple[bool, str]:
    """Garde de livraison contexte et modele (etape 2, owner 9/11).

    Une livraison n'est JAMAIS acceptee sur un repli de modele non declare
    ni quand les documents cites n'ont pas ete servis.
    """
    if (modele_demande or "").strip() and "repli sur le modele par defaut" in (rendu or "").lower():
        return False, "MODELE_REPLI_NON_DECLARE"
    if "[CONTEXTE SERVI par Nokido]" not in (consigne_servie or "") and _documents_cites_existants(desc):
        return False, "CONTEXTE_NON_SERVI"
    return True, ""


def _documents_cites_existants(desc: str | None) -> list:
    """Documents cites qui EXISTENT a la repartition (relatifs au depot ou absolus). Un document cite comme LIVRABLE
    (« RENDU : creer docs/x.md ») n'existe pas encore : ce n'est pas du contexte a servir (relecture 9/11)."""
    out = []
    for m in _RE_DOC_CITE.finditer(desc or ""):
        f_str = m.group(1).rstrip(".):]")
        p = Path(f_str)
        if (p if p.is_absolute() else ROOT / p).is_file():
            out.append(f_str)
    return out


_RE_CHEMIN_DEPOT = re.compile(r"(?<![\w\\/:.<>-])((?:app|tools|tests|docs|config)[\\/][\w.\-\\/]*[\w\-])")


def _absolutiser_chemins(desc: str, workdir: str) -> str:
    """Chemins RELATIFS du depot cites dans une consigne (`app/x.py`, `tests\\nr\\y.py`) -> absolus sous `workdir`.

    30/10 : `read_file` d'AGY refuse tout chemin relatif et agy s'arrete a la PREMIERE action refusee ; seule une
    consigne portant le chemin absolu complet a lu (sonde 18b65b0c6). Chemins deja absolus et URL : intacts."""
    base = str(workdir).rstrip("\\/")
    return _RE_CHEMIN_DEPOT.sub(lambda m: base + "\\" + m.group(1).replace("/", "\\"), str(desc or ""))


def _conserver_sortie_agy(task_id: str, r) -> str:
    """Ecrit la sortie BRUTE d'agy (stdout/stderr/rc) dans sandbox/jobs/agy_<tache>.json ; rend le chemin ou "".

    30/10 (sonde job_ce55a33f) : la reaffectation ecrasait le resultat dans tasks.db, et avec lui la seule preuve du
    chemin refuse par le bac. La preuve est ecrite AVANT tout jugement ; un echec d'ecriture se DIT dans le journal."""
    try:
        d = ROOT / "sandbox" / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        p = d / ("agy_%s.json" % re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))[:80])
        p.write_text(json.dumps({"rc": getattr(r, "returncode", None), "stdout": (getattr(r, "stdout", "") or "")[-200000:],
                                 "stderr": (getattr(r, "stderr", "") or "")[-50000:], "ts": time.time()},
                                ensure_ascii=False), encoding="utf-8")
        return str(p)
    except Exception as e:  # noqa: BLE001
        log.warning(f"  DELEGATE {str(task_id)[:24]} -> sortie brute agy NON conservee ({type(e).__name__})")
        return ""


def _delegate_to_agy(task: sqlite3.Row, token: str) -> None:
    """DÉLÉGATION-EXÉCUTION (owner : "déléguer des taches à agy") : lance AGY en
    mode AGENT (agy --print <task> --add-dir <workdir> --dangerously-skip-permissions
    --output-format json) -> AGY EXÉCUTE (tools, edits, hub gouverné) et renvoie
    l'enveloppe {status, response, usage}. Le relais sert le résultat à l'émetteur.
    Pattern delegate-agy : AGY bosse, le diff est relu (pas d'auto-merge)."""
    import subprocess as _sp
    import os as _os
    task_id = task["id"]
    desc = _avec_carte_attention(_extract_message(task["description"] or "") or (task["description"] or ""))

    def _fin(ok: bool, detail: str, intent: str | None = None) -> None:
        _clore_delegation(task_id, token, ok, detail, intent)

    agy_bin = _bin_agy()
    if not _os.path.exists(agy_bin):
        return _fin(False, f"agy introuvable: {agy_bin}")
    workdir = _workdir_agy()
    _WORKDIR_TACHE[str(task_id)] = str(workdir)
    desc = _absolutiser_chemins(desc, workdir)   # 30/10 : read_file d'AGY refuse les chemins relatifs
    desc = precharger_corps_consigne(desc, workdir=workdir)
    desc, _ = servir_documents_cites(desc, workdir=workdir, racines_autorisees=[ROOT, Path(workdir)], ledger_db=ROOT / "sandbox" / "context_ledger.db")
    _hors = _chemins_hors_bac(desc, workdir)
    if _hors:
        log.warning(f"  DELEGATE {task_id[:24]} -> consigne cite {len(_hors)} chemin(s) HORS du bac de lecture agy "
                    f"(read_file y sera refuse) : {', '.join(_hors[:5])}")
    # B1 (2026-09-12) — VERROU DE RESSOURCE REELLE, pas d'identite.
    # agy est lance ici avec --add-dir <workdir> + --dangerously-skip-permissions :
    # il ECRIT dans ce repertoire. Deux agy concurrents sur le MEME repertoire
    # s'ecrasent. La cle vient donc du chemin RESOLU. Quand ce workdir differe de
    # celui de la CLI — les deux surfaces lisent LAFORGE_AGY_WORKDIR avec des
    # defauts differents, C:\tmp la-bas, la racine du depot ici — les deux
    # chemins tournent en parallele : c'est le decouplage demande.
    _lm = _jeton_wd = None
    try:
        from nokido_agent.app.forge_lock_manager import cle_workdir_agy, get_lock_manager

        _lm = get_lock_manager()
        _jeton_wd = _lm.acquerir(
            cle_workdir_agy(workdir), "AGY_M2M",
            timeout=float(_os.environ.get("LAFORGE_AGY_LOCK_TIMEOUT_S", "60")),
        )
        if not _jeton_wd:
            _reporter(task, f"workdir agy deja tenu: {_lm.dernier_refus}")
            return
    except ImportError as e:  # noqa: BLE001
        # Le verrou manquant ne doit pas supprimer la capacite de deleguer, mais
        # il ne doit pas non plus passer en SILENCE : un lancement non serialise
        # se DIT, sinon on croira l'arbre protege.
        log.warning(f"  DELEGATE verrou de workdir indisponible ({e}) — lancement NON serialise")
    home = _os.environ.get("LAFORGE_AGY_HOME", r"%USERPROFILE%")
    env = {**_os.environ, "USERPROFILE": home, "HOME": home,
           "LOCALAPPDATA": home + r"\AppData\Local", "APPDATA": home + r"\AppData\Roaming"}
    for _k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        env.pop(_k, None)
    # ⚠️ gemini-3.1-pro n'accepte QUE low|high (PAS medium) : le defaut "medium"
    # faisait rendre agy "invalid model selection" (mesure 2026-08-13, 1er delegate
    # ANTIGRAVITY reussi). On borne donc aux valeurs valides, defaut "high" (qualite
    # de debat) — un effort inconnu est rabattu sur high plutot que de casser l'appel.
    _eff = _effort_agy(desc)
    # SESSION CONTINUE — PAR LOT EXPLICITE, JAMAIS PAR DEFAUT (arbitrage owner, 2026-09-18).
    #
    # Mesure du jour, agy interroge sur ses propres capacites : il n'a PAS `--experimental-acp`,
    # mais il a `--continue` / `--conversation` (session persistante), `remote-control`
    # (mode demon) et `stream-json` dans les deux sens. Chaque delegation recreait donc une
    # session complete alors que le CLI sait en reprendre une.
    #
    # POURQUOI PAS PAR DEFAUT : `--continue` fait heriter le contexte de la tache
    # PRECEDENTE. Sur un lot coherent (instruire vingt items d'une meme famille) c'est le
    # gain recherche ; sur deux taches independantes c'est une pollution -- l'agent
    # repondrait a la question d'avant, et le defaut serait invisible dans le resultat.
    # L'emetteur declare donc son intention en tete de tache, et c'est LUI qui porte la
    # responsabilite de la coherence du lot.
    _continu = desc.lstrip().upper().startswith("LOT_CONTINU")
    # 30/10 (patron « Worktree mode » de Codex, veille wj_568a0b05f9 ; mesure owner cmd-041b15585ee8) : agy tourne DANS
    # le worktree de tache, qui devient SON projet (--new-project, cwd=workdir). Avec --add-dir, son projet restait le
    # worktree habituel : lectures du worktree de tache refusees en headless, ecritures au mauvais endroit.
    # 30/10 (chasse aux tokens) : PREFIXE STABLE en tete -- regles fixes de l'executeur, puis chemin, puis la consigne
    # variable -- pour que le cache de prefixe du fournisseur serve d'une tache a l'autre ; --disable-slash-commands :
    # une tache deleguee porte sa consigne complete, les skills developpees a chaque lancement ne sont que du contexte.
    cmd = [agy_bin, "--print", _consigne_agy(workdir) + "\n\n[Tache]\n" + _borne_dite(desc, 29000, "limite de ligne de commande Windows d'agy"), "--new-project",
           "--disable-slash-commands", *_agy_permission_args(), "--output-format", "json",
           "--effort", _eff]
    _mod = _modele_agy(desc)
    if not _mod:
        log.warning(f"  DELEGATE {task_id[:24]} -> aucun modele AGY servable (hors quota, ou taille L sans preuve de "
                    f"sante, voir la ligne precedente) : tache laissee en attente (pending), ni echec ni reaffectation")
        conn = _db()
        try:
            conn.execute("UPDATE tasks SET status='pending' WHERE id=? AND status IN ('pending', 'running')", (task_id,))
            conn.commit()
        finally:
            conn.close()
        return
    cmd += ["--model", _mod]
    # 30/10 : 9 taches mortes sur « read_file » refuse sans que ni denied_actions ni stderr nomment le fichier ; le
    # journal de session d'agy (--log-file) est la seule trace du chemin refuse.
    _journal_agy = ROOT / "sandbox" / "jobs" / ("agy_%s.log" % re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))[:80])
    cmd += ["--log-file", str(_journal_agy)]
    # 30/10 (point 3, chasse aux tokens) : le catalogue MCP complet (> 80 outils) repartait a chaque tour ; une tache
    # deleguee n'a besoin que du socle + l'edition de code. Deterministe, sans embedder ; un echec se DIT.
    try:
        try:
            from nokido_agent.app.forge_tool_scope import set_scope_groupe
        except ImportError:
            from forge_tool_scope import set_scope_groupe
        with _lock_tool_scope:
            _sc = set_scope_groupe("ANTIGRAVITY", "edition_code")
        log.info(f"  DELEGATE {task_id[:24]} -> outils MCP bornes : {_sc.get('intent_code')} ({_sc.get('n_tools')})")
    except Exception as e:  # noqa: BLE001
        log.warning(f"  DELEGATE {task_id[:24]} -> scope MCP NON pose ({type(e).__name__}) : catalogue complet")
    if _continu:
        cmd.append("--continue")
        log.info(f"  DELEGATE {task_id[:24]} -> LOT_CONTINU : session reprise (--continue)")
    log.info(f"  DELEGATE {task_id[:24]} -> AGY agent (add-dir={workdir})")
    _avant = _etat_git(workdir)
    _sales_avant = _chemins_status(workdir) or frozenset()
    # 30/10 : AGY ecrit dans son worktree HABITUEL quel que soit le chemin donne ; son etat est releve AVANT la tache
    _habituel = str(ROOT.parent / "nokido_worktrees" / "antigravity")
    _habituel_avant = _chemins_status(_habituel)
    try:
        # Le battement (bail de MISSION + pouls de l'EXECUTEUR) couvre TOUTE l'execution agy :
        # sans lui, une instruction de plus d'une heure fait relancer l'executeur en plein travail.
        with _battement_delegation("ANTIGRAVITY", task_id):
            r = _sp.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=RELAY_TIMEOUT_S, env=env, cwd=workdir,
                        creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
    except Exception as e:  # noqa: BLE001
        return _fin(False, f"agy exec KO: {type(e).__name__}: {str(e)[:120]}")
    finally:
        if _jeton_wd and _lm is not None:
            _lm.liberer(_jeton_wd)
    _rapatries = _rapatrier_ecrits_hors_tache(_habituel, workdir, _habituel_avant)
    if _rapatries:
        log.info(f"  DELEGATE {task_id[:24]} -> {len(_rapatries)} fichier(s) ecrit(s) par AGY dans son worktree "
                 f"habituel, rapatries dans le worktree de tache : {', '.join(_rapatries[:6])}")
    raw = (r.stdout or "").strip() or (r.stderr or "").strip()
    _brut = _conserver_sortie_agy(task_id, r)
    ok, detail = lire_sortie_agy(raw)
    if not ok and _brut:
        detail = "%s\n[executeur] sortie brute agy : %s" % (detail, _brut)
    # 22/10 (bb:architecture_rules/bug_juge_failure_avec_livraison_20261022) : la session peut echouer APRES avoir
    # ecrit (job_af6dbf75, job_818ec8d8) -- le travail produit est alors committe (marque INACHEVE) ou COPIE, jamais
    # perdu derriere un FAILURE. `_preserver_livraison` sait deja faire les deux.
    if ok:
        # 16/10 : sous --sandbox AGY ne lance aucune commande ; l'executeur committe ce que la tache a PRODUIT, jamais ce
        # qui etait deja sale avant elle (contrat test_agy_worktree_et_effet_nr).
        _note = _committer_pour_agent(workdir, task_id, str(detail), "agy", exclus=_sales_avant)
    else:
        _note = _preserver_livraison(False, workdir, task_id, str(detail), "agy", exclus=_sales_avant)
    if _note:
        detail = "%s\n[executeur] %s" % (detail, _note)
    # Jugement COMMUN (16/10) : intent rendu, artefact absent, accuse de reception (le repli _relay_to_agy
    # refusait deja de clore sur « je vais chercher... » ; `agy --print` ne rend qu'UNE reponse), non livre.
    ok, effet, rendu = _juger_livraison(bool(ok), str(detail), workdir, _avant, autorises=_tests_autorises(desc), desc=desc)
    if hub_absent_dans_rendu(detail):
        effet = "%s ; %s" % (effet, MARQUE_HUB_ABSENT)
    ok = _finaliser_effet(task_id, ok, effet)
    # 31/10 : la longueur seule (« KO (176 chars) ») rendait la cause ILLISIBLE ; sur un KO, la TETE du rendu est ecrite.
    log.info(f"  DELEGATE {task_id[:24]} -> AGY {'OK' if ok else 'KO'}{(' ' + rendu) if rendu else ''} "
             f"({len(str(detail))} chars) {effet}" + ("" if ok else " | rendu : " + _tete_rendu(detail)))
    if ok and _mod and not _est_quota_epuise(detail):
        _noter_succes_agy(_mod)  # effet observe : preuve de sante du modele (S, M ou L)
    if not ok and _est_quota_epuise(detail):
        _noter_indisponibilite("AGY", detail, detail, modele=_mod)
        log.warning(f"  DELEGATE {task_id[:24]} -> quota AGY atteint pour {_mod} : tache laissee en attente (pending) sans reaffectation")
        conn = _db()
        try:
            conn.execute("UPDATE tasks SET status='pending' WHERE id=? AND status IN ('pending', 'running')", (task_id,))
            conn.commit()
        finally:
            conn.close()
        return
    motif = _motif_reaffectation_apres(bool(ok), effet, str(detail))
    t_reaff = dict(task)
    if not t_reaff.get("agent"):
        t_reaff["agent"] = "ANTIGRAVITY"
    if motif and _reaffecter(t_reaff, motif, ordre=_ORDRE_REPLI, rendu=str(detail)):
        return
    # L'effet passe EN TETE : `_fin` tronque le detail a 220 caracteres pour le M2M.
    _fin(bool(ok), "%s | %s" % (effet, detail), intent=rendu)


# ---------------------------------------------------------------------------------------------------------------
# CODEX AUTONOME (decision owner 15/10 : « apres la release 0.20.12, 3/jour » ; SSoT
# decision_owner_codex_autonome_apres_0212_20261015). Aucun organe neuf : l'EXECUTION passe par
# NokidoHarnessWorker (runAs interactive, profil owner -- seul compte qui voit ~/.codex), voie prouvee le 15/10
# (`codex exec -C <depot> ...`). Cet executeur ne lance donc PAS codex : il depose un job harness, l'attend (borne)
# et juge ce qui a ete LIVRE avec le meme `_juger_livraison` qu'AGY. Seule l'instance dediee (--agent CODEX,
# service NokidoTaskExecutorCodex coupe par defaut) prend ces taches : le generique les exclut (plancher).
# ---------------------------------------------------------------------------------------------------------------
CODEX_AGENT = "CODEX"
CODEX_QUOTA_JOUR = int(os.environ.get("LAFORGE_CODEX_QUOTA_JOUR", "3"))
CODEX_TIMEOUT_S = int(os.environ.get("LAFORGE_CODEX_TIMEOUT_S", "2400"))
_CODEX_QUOTA = ROOT / "sandbox" / "codex_autonome_quota.json"
_HARNESS_JOBS = ROOT / "sandbox" / "harness_jobs"
_POLL_HARNESS_S = 5
LAFORGE_HARNESS_ATTENTE_FILE_S = int(os.environ.get("LAFORGE_HARNESS_ATTENTE_FILE_S", "1800"))
_quota_codex_dit = {"jour": None}
_lock_codex_quota = threading.Lock()


def _workdir_codex() -> Path:
    """Worktree DEDIE de Codex (creation = geste OWNER, branche agent/codex). PAS de repli sur la racine partagee,
    a la difference d'AGY : un agent qui ecrit hors de son claim empeche tout verdict de CI de se rattacher a un
    commit (RULES_SHARED, 2026-09-07)."""
    if _WT_TACHE.get() is not None:
        return Path(_WT_TACHE.get())
    env = os.environ.get("LAFORGE_CODEX_WORKDIR")
    return Path(env) if env else ROOT.parent / "nokido_worktrees" / "codex"


def _quota_codex(jour: str | None = None) -> int:
    """Lancements Codex autonomes deja faits ce JOUR (heure locale). Illisible = plafond atteint : une mesure
    qu'on ne sait pas lire n'autorise rien (quota Codex NON paye, owner 15/10)."""
    jour = jour or time.strftime("%Y-%m-%d")
    try:
        d = json.loads(_CODEX_QUOTA.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 0
    except Exception:  # noqa: BLE001
        return CODEX_QUOTA_JOUR
    return int(d.get(jour, 0)) if isinstance(d, dict) else CODEX_QUOTA_JOUR


def _consommer_quota_codex(jour: str | None = None) -> int:
    """Compte un LANCEMENT (quel que soit son effet). Un seul jour est garde : le compteur repart chaque jour."""
    with _lock_codex_quota:
        jour = jour or time.strftime("%Y-%m-%d")
        n = _quota_codex(jour) + 1
        _CODEX_QUOTA.parent.mkdir(parents=True, exist_ok=True)
        _CODEX_QUOTA.write_text(json.dumps({jour: n}), encoding="utf-8")
        return n


def _peut_lancer_codex() -> tuple[bool, str]:
    """Capacite MESUREE : worktree dedie present (son fichier .git) et dossier des jobs harness accessible.
    Le plafond n'est pas juge ici : il l'est AVANT de prendre la tache, qui reste alors pending."""
    wt = _workdir_codex()
    if not (wt / ".git").exists():
        return False, f"worktree Codex absent ({wt}) -- creation = geste OWNER (branche agent/codex)"
    try:
        _HARNESS_JOBS.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"dossier des jobs harness inaccessible ({type(e).__name__})"
    return True, f"worktree {wt} present ; execution par NokidoHarnessWorker"


def _purger_marqueurs_harness(job: Path) -> None:
    """Retire `.done`, `.started` et `.result.json` d'un essai precedent du MEME job (meme tache = meme nom) : sans
    cela une re-delegation relit l'ancien resultat et le worker ne relance pas le job (19/10, job_8d8c674e)."""
    for suffixe in (".done", ".started", ".result.json"):
        Path(job).with_suffix(suffixe).unlink(missing_ok=True)


def _attendre_harness(job: Path, delai_s: float, attente_file_s: float | None = None, task_id: str | None = None) -> dict | None:
    """Resultat du job harness (`<id>.result.json` + `<id>.done`), ou None si le worker est reste MUET.
    La borne delai_s court depuis le marqueur `<job>.started` ; tant qu'il est absent on attend au plus
    attente_file_s (defaut LAFORGE_HARNESS_ATTENTE_FILE_S, 1800) puis on rend OCCUPE.
    Avec un task_id, appelle touch_progress(task_id) au plus toutes les _PROGRES_TOUTES_S pendant l'attente
    (file ET execution) ; sans task_id, ne bat pour personne."""
    job = Path(job)
    attente_file_s = LAFORGE_HARNESS_ATTENTE_FILE_S if attente_file_s is None else float(attente_file_s)
    started = job.with_suffix(".started")
    done = job.with_suffix(".done")
    dernier_battement = time.time()

    def _battre():
        nonlocal dernier_battement
        if task_id:
            try:
                touch_progress(task_id)
            except Exception as e:  # noqa: BLE001
                log.warning(f"  battement KO pour {str(task_id)[:24]} ({type(e).__name__}): {e}")
            dernier_battement = time.time()

    fin_file = time.time() + attente_file_s
    while not started.exists() and not done.exists() and not _stop:
        if time.time() >= fin_file:
            if started.exists() or done.exists():
                break
            n_s = int(attente_file_s) if attente_file_s == int(attente_file_s) else attente_file_s
            # 27/10 : l'abandon SORT le job de la file (.done + resultat) -- sinon le worker relance l'executait des
            # heures plus tard pour personne (eec0f153, a5971348) et le job vivant attendait derriere.
            try:
                job.with_suffix(".result.json").write_text(json.dumps(
                    {"ok": False, "error": "abandonne par l'executeur : jamais demarre apres %s s" % n_s}),
                    encoding="utf-8")
                done.write_text("1", encoding="utf-8")
            except OSError as e:
                log.warning(f"  job harness abandonne mais laisse en file ({type(e).__name__}): {job.name}")
            return {"ok": False, "error": f"harness OCCUPE : job jamais demarre apres {n_s} s (file sequentielle)"}
        time.sleep(_POLL_HARNESS_S)
        if task_id and (time.time() - dernier_battement >= _PROGRES_TOUTES_S):
            _battre()
    if not started.exists() and not done.exists():
        return None
    fin_exec = time.time() + delai_s
    while time.time() < fin_exec and not _stop:
        if done.exists():
            try:
                return json.loads(job.with_suffix(".result.json").read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"resultat harness illisible ({type(e).__name__})"}
        time.sleep(_POLL_HARNESS_S)
        if task_id and (time.time() - dernier_battement >= _PROGRES_TOUTES_S):
            _battre()
    if done.exists():
        try:
            return json.loads(job.with_suffix(".result.json").read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"resultat harness illisible ({type(e).__name__})"}
    return None


# Effort de raisonnement par TAILLE de tache (owner 17/10 : « des modeles plus faibles selon la complexite » ; mesure :
# une reponse exploratoire au defaut medium a coute >= 9 % du quota MENSUEL Codex Free). Taille inconnue -> aucun
# reglage : UNKNOWN n'est pas S, le defaut de la config owner reste.
_EFFORT_CODEX_PAR_TAILLE = {"S": "low", "M": "medium", "L": "high"}
_RE_TAILLE = re.compile(r"(?<![A-Za-z])taille\s*[:=]?\s*([SML])\b")


def _taille_tache(desc: str) -> str | None:
    """Taille S/M/L declaree dans la consigne (dossiers A_FAIRE, gabarit de lot), sinon None."""
    m = _RE_TAILLE.search(str(desc or ""))
    return m.group(1) if m else None


def _args_codex(wt: Path, taille: str | None = None) -> list[str]:
    """`workspace-write` exclut `.git` de chaque racine inscriptible PAR CONCEPTION (codex-rs : « .git excluded »).
    Mesure du 16/10, 2 sondes : ni sans ni avec `--add-dir` sur l'admin du worktree, Codex ne peut `git add`
    (« index.lock : Permission denied »), alors que la session owner sans bac a sable le peut. Le bac a sable reste ;
    c'est l'EXECUTEUR qui committe (`_committer_pour_codex`). L'effort suit la taille ; le prompt `-` reste dernier."""
    args = ["exec", "--skip-git-repo-check", "-C", str(wt), "-s", "workspace-write"]
    # 30/10 : UNE table modele+effort (forge_palier_effort, surface "codex", cle verifiee config-reference.md) ;
    # l'ancienne table locale reste le repli si le module est illisible.
    # Taille inconnue : AUCUN drapeau, Codex garde son defaut (contrat de test_codex_effort_selon_taille_nr).
    effort = None
    if str(taille or "").upper() in ("S", "M", "L"):
        try:
            from forge_palier_effort import resoudre as _resoudre_palier
            effort = _resoudre_palier("codex", str(taille).upper()).get("effort")
        except Exception as _e_pal:  # noqa: BLE001
            log.debug("palier codex illisible (%s) : table locale", type(_e_pal).__name__)
        effort = effort or _EFFORT_CODEX_PAR_TAILLE.get(str(taille).upper())
    if effort:
        args += ["-c", 'model_reasoning_effort="%s"' % effort]
    return args + ["-"]


# 7/11 : un delegue a contourne un refus de `governed_edit` avec `Edit` natif et son commit est passe.
# 8/11 (decision_garde_critique_a_l_integration) : le commit worktree passe marque ; l'integration dans alpha exige la derogation.
_CONSIGNE_CRITIQUE = (
    "\n[CRITICAL_FILE] Si `governed_edit` refuse un fichier critique, ce refus ne se contourne PAS par `Edit`/`Write` "
    "natif : le commit worktree passe marque mais l'integration dans alpha exige la derogation (`allow_critical` a "
    "l'assignation, ring <= 1). ARRETE-TOI sur ce point si non autorise et demande la derogation dans ton rendu.")

_CONSIGNE_GIT_CODEX = (
    "\n\n[Executeur Nokido] Ne lance ni `git add` ni `git commit` : ton bac a sable tient .git en lecture seule et "
    "l'executeur committe lui-meme les fichiers que tu as modifies dans ce worktree. Termine par UNE ligne JSON "
    '{"intent":"OK_DONE"|"ERR_INTERNAL","pointer_ref":"...","commit_message":"<type(portee): resume>"}.'
    + _CONSIGNE_CRITIQUE)


_CONSIGNE_SANS_COMMANDE_AGY = (
    "\n\n[Executeur Nokido] Ton bac a sable refuse toute commande hors bac (RunCommand) : ne lance AUCUNE commande "
    "(ni git, ni pytest, ni script). Ecris seulement les fichiers demandes dans ce worktree ; l'executeur committe "
    "ce que tu as produit et Claude relance les tests a la relecture. Termine par UNE ligne JSON "
    '{"intent":"OK_DONE"|"ERR_INTERNAL","pointer_ref":"...","commit_message":"<type(portee): resume>"}.')


# Owner 30/10 « technique du pointeur, lecture et ecriture ciblees » : une tache M relisait des fichiers entiers
# (forge_task_executor.py, 288 Ko) a chaque tour -- 340 k tokens + 11 M relus en cache. Texte FIXE, place AVANT la
# partie variable (workdir) : le prefixe reste identique d'une tache a l'autre (cache de prompt).
_CONSIGNE_POINTEURS_AGY = (
    "\n[Executeur Nokido] LECTURE PAR POINTEUR : n'ouvre JAMAIS en entier un fichier de plus de 150 lignes. "
    "D'abord get_file_skeleton (hub) pour la structure, puis read_function_body (hub) pour CHAQUE fonction citee. "
    "Relire un fichier deja lu : passe si_etag=<etag recu> au hub (reponse INCHANGE quasi vide) ; premier appel "
    "si_etag=\"0\" pour obtenir l'etag. ECRITURE CIBLEE : edit_file sur le seul bloc a changer, jamais write_file "
    "sur un fichier existant.")


# 31/10 (job_b2738b35) : read_file hors du worktree est soft-denied en headless et agy s'arrete SANS nommer le chemin.
# Texte FIXE (prefixe de cache) : toute source externe passe par les outils MCP du hub. Autorisation PAR SERVEUR dans
# le profil agy (~/.gemini/antigravity-cli/settings.json, permissions.allow `mcp(<serveur>/*)`, PAS mcp(*)) : renommer
# le serveur (3/11 : laforge-sovereign-hub -> nokido-oauth) = « mcp » auto-refuse en headless tant que l'autorisation
# du nouveau nom manque (preuve job_7aa9fb07 : rag sous OAUTH_nkc_i_6BR0 apres ajout de mcp(nokido-oauth/*)).
# 6/11 : AGY a perdu tout le hub a 11:33 (famille OAuth revoquee) et a rendu 3 h 35 de travail sans aucun outil MCP, sans
# marque. Il le disait pourtant dans sa reponse : on le lit. La marque ne change pas le verdict de livraison.
MARQUE_HUB_ABSENT = "[HUB ABSENT]"
_RE_HUB_ABSENT = re.compile(r"(?:aucun|pas\s+d['’])\s*outils?\s+(?:\S+\s+)?(?:du\s+)?hub\b"
                            r"|serveurs?\s+mcp\s+visibles?\s*:\s*aucun|aucun\s+serveur\s+mcp", re.I)


def hub_absent_dans_rendu(detail) -> bool:
    return bool(_RE_HUB_ABSENT.search(str(detail or "")))


_CONSIGNE_HORS_WORKTREE_AGY = (
    "\n[Executeur Nokido] LECTURE (meme visibilite que Claude, owner 8/11) : ce repertoire, C:\\tmp (dossiers de "
    "debat, sorties de jobs) et le depot Nokido principal en LECTURE SEULE (fichiers .env refuses). HORS DE CE "
    "REPERTOIRE et de ces deux lieux, ta lecture de fichier est REFUSEE et la session s'arrete sans reponse. Pour une "
    "source externe (depot ingere `github:...`, doc, historique), utilise les outils MCP du hub Nokido (quel que soit "
    "le nom du serveur dans ta config) : `rag` (recherche, cite [chunk:id]) ou `read` ; ne lis jamais ton profil. "
    "N'ECRIS que sous ton repertoire de travail.")

# Lectures accordees hors des worktrees par le profil agy (permissions.allow) : 31/10 = 2 docs de regles ;
# 8/11 (owner « meme ring = meme visibilite ») = C:\tmp et tout le depot principal, *.env refuses (deny).
_LECTURES_ACCORDEES_AGY = ("rules_shared.md", "rules_clients_sans_hooks.md")
_RACINE_TMP_AGY = "c:\\tmp\\"
_DEPOT_PRINCIPAL_AGY = "\\nokido\\"


def _lecture_accordee_agy(p: str) -> bool:
    """`p` = chemin normalise (antislash, minuscules). Miroir de permissions.allow/deny du profil agy."""
    if p.startswith(_RACINE_TMP_AGY):
        return True
    return _DEPOT_PRINCIPAL_AGY in p and not p.endswith(".env")


def _chemins_hors_bac(desc: str, workdir: str) -> list:
    """Chemins ABSOLUS cites par la consigne qui sortent du bac de lecture d'agy (ni sous le worktree de tache, ni
    sous nokido_worktrees, ni accordes) : le journal les NOMME avant le lancement -- agy, lui, ne dira rien."""
    base = str(workdir or "").replace("/", "\\").rstrip("\\").lower()
    hors = []
    # lettre de lecteur ISOLEE et un seul separateur : « https://x » ne donne pas le chemin « s:/x » (NR du 31/10) ;
    # un REPERTOIRE peut porter des espaces (« Script python IA\ », faux positif job_f74513a2), le dernier segment non.
    _seg = r"[^\\/\s;,\"'`<>|*?:]+"
    for m in re.finditer(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/])(?:%s(?: %s)*[\\/])*%s" % (_seg, _seg, _seg),
                         str(desc or "")):
        brut = m.group(0).rstrip(".):]")
        p = brut.replace("/", "\\").lower()
        if ((base and p.startswith(base)) or "\\nokido_worktrees\\" in p or p.endswith(_LECTURES_ACCORDEES_AGY)
                or _lecture_accordee_agy(p)):
            continue
        if brut not in hors:
            hors.append(brut)
    return hors


def _consigne_agy(workdir: str) -> str:
    """Consigne de l'executeur pour AGY, avec le chemin ABSOLU ou ecrire.

    Mesure du 29/10 : depuis le worktree par tache, agy ecrivait relativement a SON espace habituel
    (nokido_worktrees/antigravity) et non au cwd/--add-dir : 3 audits reels juges RIEN_PRODUIT.
    NR tests/nr/test_agy_chemin_absolu_worktree_tache_nr.py.
    """
    return (_CONSIGNE_SANS_COMMANDE_AGY + _CONSIGNE_POINTEURS_AGY + _CONSIGNE_HORS_WORKTREE_AGY
            + "\n[Executeur Nokido] REPERTOIRE DE TRAVAIL de cette tache : %s -- ecris "
            "tout fichier demande SOUS ce chemin absolu (un chemin relatif s'entend depuis lui), jamais dans un autre "
            "worktree : un fichier ecrit ailleurs n'est ni vu ni livre.\n[Executeur Nokido] POUR LIRE un fichier, donne "
            "TOUJOURS son chemin ABSOLU sous ce repertoire (ex. %s\\app\\forge_ssot.py) : ton outil de lecture REFUSE "
            "tout chemin relatif (« must be an absolute path », sonde du 30/10)." % (workdir, workdir)
            + _texte_entrees(workdir))


def _rapatrier_ecrits_hors_tache(habituel: str, workdir: str, avant) -> list:
    """Copie dans le worktree de TACHE ce qui est APPARU ou devenu modifie, PENDANT la tache, dans le worktree HABITUEL
    d'AGY ; rend les chemins copies.

    29-30/10 : AGY ecrit relativement a SON espace (nokido_worktrees/antigravity) quel que soit le chemin donne, meme
    absolu (_consigne_agy) -- 5 livraisons reelles jugees RIEN_PRODUIT. `avant` = etat releve AVANT la tache : ce qui y
    etait deja sale n'est pas le travail de la tache. Rien n'est supprime dans le worktree habituel.
    NR tests/nr/test_agy_rapatrie_ecrits_hors_tache_nr.py."""
    import os as _osr
    import shutil as _sh
    if not habituel or avant is None or not workdir:
        return []
    if _osr.path.normcase(_osr.path.abspath(habituel)) == _osr.path.normcase(_osr.path.abspath(workdir)):
        return []
    apres = _chemins_status(habituel)
    if apres is None:
        return []
    copies = []
    for rel in sorted(set(apres) - set(avant)):
        src = Path(habituel) / rel
        if rel.startswith("nokido_worktrees/") or not src.is_file():
            continue
        dst = Path(workdir) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        _sh.copy2(src, dst)
        copies.append(rel)
    return copies


def _chemins_status(wt: str):
    """Chemins modifies ou non suivis du worktree (git status), ou None si illisible."""
    import subprocess as _sp
    # 18/10 (mesure : 2 ci_local tues a 6 Go) : hors de la RACINE d'un worktree, git remonterait jusqu'au depot Nokido et
    # enumererait tous ses non-suivis (-uall). Pas de `.git` propre = pas d'etat propre : illisible, git non lance.
    if not (Path(wt) / ".git").exists():
        return None
    try:
        s = _sp.run(["git", "-c", "safe.directory=*", "-C", str(wt), "status", "--porcelain=v1", "-uall"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=_env_git())
    except Exception:  # noqa: BLE001 - illisible : None, l'appelant le dit
        return None
    if s.returncode != 0:
        return None
    chemins = []
    for ligne in s.stdout.splitlines():
        p = ligne[3:].strip()
        if " -> " in p:
            old_p, new_p = p.split(" -> ", 1)
            for part in (old_p, new_p):
                part = part.strip().strip('"')
                if part:
                    chemins.append(part.replace("\\", "/"))
        elif p:
            chemins.append(p.strip('"').replace("\\", "/"))
    return frozenset(chemins)


def _committer_pour_codex(wt: str, task_id, detail: str, exclus=frozenset()) -> str | None:
    return _committer_pour_agent(wt, task_id, detail, "codex", exclus=exclus)


# Copies de sauvegarde du travail qu'aucun commit ne garde (19/10 : 5 livraisons perdues au recalage sur alpha).
_SAUVEGARDES = SANDBOX / "sauvegardes_executeurs"


def _sauvegarder_travail(wt: str, task_id, agent: str, exclus=frozenset(), motif: str = "") -> str | None:
    """COPIE des fichiers produits par l'agent quand aucun commit ne les garde -- sans git, donc sans hook a
    contourner (`--no-verify` ecarte). Seuls les fichiers DU worktree, hors marqueur et hors sales d'avant ; un
    manifeste dit le motif. Rien de neuf -> None. Ne leve jamais (une sauvegarde ratee se DIT)."""
    import json as _j
    import shutil as _sh

    try:
        tous = _chemins_status(wt)
        if not tous:
            return None
        chemins = sorted(p for p in tous - frozenset(exclus or ()) if Path(p).name != ".nokido.agent")
        base = Path(wt).resolve()
        dest = Path(_SAUVEGARDES) / str(agent) / re.sub(r"[^\w.-]", "_", str(task_id))[:80]
        copies = []
        for rel in chemins:
            src = (base / rel).resolve()
            if base not in src.parents or not src.is_file():
                continue  # hors du worktree, ou supprime : rien a copier
            cible = dest / rel
            cible.parent.mkdir(parents=True, exist_ok=True)
            _sh.copy2(src, cible)
            copies.append(rel)
        if not copies:
            return None
        (dest / "manifeste.json").write_text(_j.dumps(
            {"tache": str(task_id), "agent": agent, "worktree": str(wt), "motif": str(motif)[:300],
             "fichiers": copies, "ts": time.time()}, ensure_ascii=False, indent=1), encoding="utf-8")
        return "COPIE de sauvegarde de %d fichier(s) : %s" % (len(copies), dest)
    except Exception as e:  # noqa: BLE001 -- la sauvegarde ne casse jamais l'executeur, mais son echec se dit
        log.warning(f"  COPIE de sauvegarde ECHOUEE ({type(e).__name__}) -- le travail reste dans le worktree")
        return "COPIE de sauvegarde ECHOUEE (%s)" % type(e).__name__


def _preserver_livraison(ok: bool, wt: str, task_id, detail: str, agent: str, exclus=frozenset()) -> str | None:
    """Commit du travail de l'agent, MEME si sa session a echoue (18/10).

    Mesure : deux livraisons NEMOTRON (code + NR complets) perdues en « [NON LIVRE] » -- la session OpenCode avait
    echoue APRES l'ecriture (quota/delai puis repli de modele) et seul `ok` declenchait le commit. Session reussie :
    comportement inchange. Session en echec avec travail neuf : commit sur la branche de l'agent, marque INACHEVE
    (a relire, jamais vers alpha sans relecture). Rien de neuf : None."""
    if ok:
        note = _committer_pour_agent(wt, task_id, detail, agent, exclus=exclus)
        if note is None or not note.startswith("commit executeur de"):
            # Intention d'erreur rendue, scorecard REJETE ou commit refuse : la livraison n'entre pas, mais le
            # travail produit est GARDE (19/10) -- copie, jamais un commit qui contournerait le refus.
            sauve = _sauvegarder_travail(wt, task_id, agent, exclus, motif=note or "intention d'erreur rendue")
            if sauve:
                return "%s ; %s" % (note or "aucun commit (intention d'erreur rendue)", sauve)
        return note
    marque = '"commit_message": "chore(%s): INACHEVE a relire, tache %s (session en echec)"' % (agent, str(task_id)[:30])
    note = _committer_pour_agent(wt, task_id, marque, agent, exclus=exclus)
    if not note:
        # 19/10 (AGY job_198d901b, job_a34c8407) : tous les chemins sales etaient dans `exclus` (ecrits AVANT une relance
        # du superviseur) -> rien a committer, et aucune copie. Une COPIE ne pollue aucun historique : on garde tout.
        sauve = _sauvegarder_travail(wt, task_id, agent, frozenset(), motif="session en echec, chemins sales preexistants")
        return ("travail INACHEVE NON committe (chemins preexistants a la tache) : %s" % sauve) if sauve else None
    if note.startswith("commit executeur de"):
        return "travail INACHEVE preserve : %s" % note
    sauve = _sauvegarder_travail(wt, task_id, agent, exclus, motif=note)
    # jamais dit « preserve » a tort : une copie n'est pas un commit
    return "travail INACHEVE NON committe, reste dans le worktree : %s%s" % (note, " ; " + sauve if sauve else "")


def _est_chemin_de_test(p: str) -> bool:
    """Vrai pour un fichier sous tests/ (commit RED du commit en deux temps)."""
    return str(p).replace("\\", "/").lstrip("./").startswith("tests/")


def _python_des_tests() -> str:
    """Interpreteur qui a pytest : LAFORGE_PYTHON (si fichier), puis ~/miniforge3/python.exe (si fichier), sinon sys.executable."""
    env = os.environ.get("LAFORGE_PYTHON")
    if env and os.path.isfile(env):
        return env
    mf = os.path.join(os.path.expanduser("~"), "miniforge3", "python.exe")
    return mf if os.path.isfile(mf) else sys.executable


def _module_sous_test_absent(sortie: str, fournis) -> str:
    """Nom du module qu'un import manquant reclame ET que le commit de code (`fournis`) apporte, sinon "".

    Le RED classique du TDD : le test importe le code qui n'existe pas encore (`from m import f`, m.py dans le
    commit GREEN). Ce n'est pas un crash d'outillage (pytest absent, dependance tierce manquante) : c'est le rouge
    attendu. Seul un module LIVRE par le commit de code compte ; tout autre import manquant reste INDETERMINE."""
    import re as _re
    if not fournis:
        return ""
    chemins = {str(p).replace("\\", "/").lstrip("./") for p in fournis}
    for mod in _re.findall(r"No module named '([\w.]+)'", sortie) + _re.findall(
            r"cannot import name '[\w.]+' from '([\w.]+)'", sortie):
        base = mod.replace(".", "/")
        if any(c == base + ".py" or c == base + "/__init__.py" or c.endswith("/" + base + ".py")
               or c.endswith("/" + base + "/__init__.py") for c in chemins):
            return mod
    return ""


def _rejouer_tests_sur_commit(wt: str, commit: str, tests: list, timeout: int = 300, fournis=None) -> tuple:
    """Rejoue `tests` (fichiers test_*.py) sur l'arbre de `commit` seul, dans un worktree jetable.
    Rend (etat, extrait) : etat = ROUGE | VERT | INDETERMINE. Ne leve jamais.
    `fournis` : chemins du commit de code qui suit ; un import manquant d'un de ces modules est le ROUGE attendu."""
    import subprocess as _sp
    import tempfile
    import shutil
    fichiers = [p for p in tests if p.endswith(".py") and (Path(p).name.startswith("test_") or p.endswith("_test.py"))]
    if not fichiers:
        return "INDETERMINE", "aucun fichier de test python"
    g = ["git", "-c", "safe.directory=*", "-C", str(wt)]
    tmp = tempfile.mkdtemp(prefix="red_replay_")
    cible = str(Path(tmp) / "arbre")
    ajoute = False
    try:
        r = _sp.run(g + ["worktree", "add", "--detach", cible, commit], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=120, env=_env_git())
        if r.returncode != 0:
            return "INDETERMINE", "worktree jetable impossible : %s" % (r.stderr or r.stdout)[-200:]
        ajoute = True
        env = _env_git()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # 8/11 (rejeu RED, test_rejeu_red_crash_ou_rouge_nr) : le pytest imbrique HERITE de l'environnement
        # du pytest exterieur. Sans la coupe de l'auto-chargement, il heritait des plugins installs
        # (pytest-benchmark, hypothesis) et sortait rc=2 : un [assert False -> ROUGE] passait pour un
        # « CRASH, pytest rc=2 » (INDETERMINE). La forme CI (autoload coupe) passait (lot p1 : 9 127 verts).
        # Hermetique quel que soit l'exterieur : autoload coupe, PYTEST_ADDOPTS/PYTEST_PLUGINS non herites
        # (addopts falsifie = rc=4 en interne), cache desactive. Aucun plugin -p exige de plus : le rejeu
        # n'impose ni timeout ni benchmark au test rejoue.
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        for _pv in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
            env.pop(_pv, None)
        py = _python_des_tests()
        t = _sp.run([py, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"] + fichiers,
                    cwd=cible, capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=timeout, env=env)
        # 6/11 (owner) : stderr garde et plusieurs lignes ; un test qui ne demarre pas n'est pas un rouge.
        lignes = (((t.stdout or "") + "\n" + (t.stderr or "")).strip().splitlines() or [""])
        extrait = " | ".join(x.strip() for x in lignes[-4:] if x.strip())[-400:]
        if t.returncode == 0:
            return "VERT", extrait
        # 7/11 (NR test_commit_deux_temps_red_green) : le module sous test, apporte par le commit de code, manque au
        # commit RED -> c'est le rouge du TDD, pas un crash d'outillage.
        absent = _module_sous_test_absent((t.stdout or "") + "\n" + (t.stderr or ""), fournis)
        if absent:
            return "ROUGE", "module sous test '%s' absent du commit RED, livre par le commit de code : %s" % (absent, extrait)
        # 7/11 : `python -m pytest` sans pytest rend rc=1 : un interpreteur sans pytest n'a rien prouve (pas un ROUGE).
        if "No module named" in ((t.stdout or "") + (t.stderr or "")):
            return "INDETERMINE", "CRASH, le test n'a pas tourne, pytest rc=%s (module manquant, interpreteur %s), aucun verdict : %s" % (t.returncode, py, extrait)
        if t.returncode == 1 and "error during collection" not in (t.stdout or "") and "errors during collection" not in (t.stdout or ""):
            return "ROUGE", extrait
        return "INDETERMINE", "CRASH, le test n'a pas tourne, pytest rc=%s : %s" % (t.returncode, extrait)
    except Exception as e:  # noqa: BLE001 - la preuve est un signal, jamais un refus
        return "INDETERMINE", type(e).__name__
    finally:
        if ajoute:
            try:
                _sp.run(g + ["worktree", "remove", "--force", cible], capture_output=True, timeout=60, env=_env_git())
            except Exception:  # noqa: BLE001
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 2733, exc_info=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _marque_critique(chemins, derogation: bool) -> str:
    """8/11 : marqueur ajoute a la note du commit si un fichier critique est touche."""
    try:
        try:
            from nokido_agent.tools import forge_critical_gate as _cg
        except ImportError:
            import forge_critical_gate as _cg
        crit = _cg.fichiers_critiques(chemins)
        if not crit:
            return ""
        return " [CRITICAL_FILE] %s derogation=%s" % (", ".join(crit), "oui" if derogation else "non")
    except Exception as e:  # noqa: BLE001
        log.warning(f"  garde CRITICAL_FILE INDISPONIBLE ({type(e).__name__})")
        return ""


# 8/11 (decision_garde_critique_a_l_integration) : `_refus_critique` retire. Le commit du worktree de tache passe,
# marque par `_marque_critique` ; le garde bloquant vit a l'entree dans alpha (forge_merge_gate).


def _derogation_critique(task_id) -> bool:
    """Derogation relue EN BASE (colonne `allow_critical` posee a l'assignation, ring <= 1), jamais la prose."""
    try:
        try:
            from nokido_agent.tools import forge_critical_gate as _cg
        except ImportError:
            import forge_critical_gate as _cg
        return _cg.derogation_en_base(task_id, TASKS_DB)
    except Exception:  # noqa: BLE001
        return False


def _committer_deux_temps(wt, g, tests_ch, code_ch, msg, corps, agent, derogation: bool = False) -> str:
    """(1) `test(<agent>): RED -- <msg>` avec les seuls tests, (2) le reste, dont le message consigne la preuve :
    les tests rejoues sur l'arbre du commit (1) seul etaient ROUGES (preuve) ou DEJA VERTS (alerte, pas un refus)."""
    import subprocess as _sp
    # 8/11 : plus de refus CRITICAL_FILE ici (marque en fin de note) ; le garde bloquant vit dans forge_merge_gate.

    def _run(*a, t=180):
        return _sp.run(g + list(a), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=t,
                       env=_env_git())
    msg_red = "test(%s): RED -- %s" % (agent, msg)
    try:
        a = _run("add", "--", *tests_ch, t=60)
        c = _run("commit", "-m", msg_red, "-m", corps + " Commit RED : tests seuls.") if a.returncode == 0 else a
        if c.returncode != 0:
            return "commit executeur REFUSE rc=%s : %s" % (c.returncode, (c.stderr or c.stdout)[-400:])
        sha = _run("rev-parse", "HEAD", t=30).stdout.strip()
        etat, extrait = _rejouer_tests_sur_commit(str(wt), sha, tests_ch, fournis=code_ch)
        if etat == "VERT" or (etat == "ROUGE" and not str(extrait or "").strip()):
            extrait = "RED NON OBSERVE : %s" % (str(extrait or "").strip() or "preuve vide")
            etat = "VERT" if etat == "VERT" else "VIDE"
        preuve = {"ROUGE": "preuve RED : tests ROUGES sur le commit RED seul (%s)" % extrait,
                  "VERT": "ALERTE : tests DEJA VERTS sur le commit RED seul, le test ne prouve pas le correctif (%s)"
                          % extrait}.get(etat, "preuve RED INDETERMINEE (%s)" % extrait)
        a = _run("add", "--", *code_ch, t=60)
        c = (_run("commit", "-m", msg, "-m", corps, "-m", "%s [commit RED %s]" % (preuve, sha[:9]))
             if a.returncode == 0 else a)
        if c.returncode != 0:
            return ("commit executeur REFUSE rc=%s (commit RED %s livre, code non committe) : %s"
                    % (c.returncode, sha[:9], (c.stderr or c.stdout)[-400:]))
    except Exception as e:  # noqa: BLE001
        return "commit executeur ECHOUE (%s)" % type(e).__name__
    return ("commit executeur de %d fichier(s) en 2 commits (RED %d tests, %d code) : %s ; %s" % (
        len(tests_ch) + len(code_ch), len(tests_ch), len(code_ch), msg, preuve)
        + _marque_critique(list(tests_ch) + list(code_ch), derogation))


# Fichiers qui ne sont JAMAIS une livraison : marqueur d'identite du worktree, verrou transitoire.
_TRANSITOIRES_JAMAIS_LIVRES = frozenset({".nokido.agent", "nokido.lock"})


def _jamais_livre(chemin: str) -> bool:
    """Le fichier n'est JAMAIS une livraison. 25/10 : la liste figee divergeait du gate « transitoires » du
    pre-commit -- `sandbox/idle_state.json.tmp`, laisse INDEXE par une tache, a fait refuser les 2 livraisons
    suivantes de CLAUDE_HEADLESS. On lit donc LA MEME regle que le gate (forge_git_gate._fichiers_transitoires :
    *.tmp/*.swp/*~, *.lock non legitime, .nokido.agent), plus la config MCP propre a l'executeur
    (`.<agent>_mcp.json`, ecrite par lui dans le worktree, jamais un livrable)."""
    nom = Path(chemin).name
    # 7/11 (job_64d6f1ae) : 133 fichiers sous sandbox/bt_*/pytest* (dossiers temporaires de tests) partis dans un commit.
    _parts = str(chemin).replace("\\", "/").lstrip("./").split("/")
    if len(_parts) >= 2 and _parts[0] == "sandbox" and _parts[1].startswith("bt_"):
        return True
    if nom in _TRANSITOIRES_JAMAIS_LIVRES or (nom.startswith(".") and nom.endswith("_mcp.json")):
        return True
    try:
        try:
            from nokido_agent.tools.forge_git_gate import _fichiers_transitoires
        except ImportError:
            from forge_git_gate import _fichiers_transitoires
        return bool(_fichiers_transitoires([chemin], []))
    except Exception:  # noqa: BLE001 - gate illisible : on retombe sur la liste figee (deja testee ci-dessus)
        return False


def _reecritures_destructrices(numstat: str, seuil: int = 200) -> list:
    """Fichiers qu'un diff RASE (`git diff --numstat`) : au moins `seuil` lignes retirees ET moins de la moitie
    remplacee. 30/10 : OPENCODE_DEFAUT3 a reecrit app/forge_health_diagnostic.py (-2532 / +27) en annoncant OK_DONE.
    Un vrai refactor retire et ajoute dans les memes ordres de grandeur ; un rasage, non."""
    out = []
    for ligne in str(numstat or "").splitlines():
        parts = ligne.split("\t")
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue   # binaire (« - ») ou ligne illisible : ni accuse ni absous ici
        ajout, retrait = int(parts[0]), int(parts[1])
        if retrait >= seuil and ajout * 2 < retrait:
            out.append(parts[2])
    return out


def _suivis_non_livres(g, exclus) -> str:
    """Fichiers SUIVIS encore modifies apres le commit de l'executeur (ecartes par `exclus`, « sales avant la tache »).
    7/11 (job_bf9f3606) : 2 fichiers suivis modifies sont restes hors du commit, sauves ensuite par le reconciliateur,
    et la tache affichait done [SUCCESS]. Tout fichier suivi modifie est livre, ou la tache ne reussit pas : on
    nomme ces fichiers avec le marqueur LIVRE NON COMMITTE (verdict non-SUCCESS). Illisible : dit, jamais « rien »."""
    import subprocess as _sp
    try:
        r = _sp.run(g + ["diff", "--name-only", "HEAD", "--"], capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=60, env=_env_git())
        if r.returncode != 0:
            raise RuntimeError("rc=%s" % r.returncode)
    except Exception as e:  # noqa: BLE001
        log.warning(f"  fichiers suivis restants ILLISIBLES ({type(e).__name__})")
        return " ; %s fichiers suivis restants ILLISIBLES (git diff en echec)" % _LIVRE_NON_COMMITTE
    reste = sorted(p.strip().replace("\\", "/") for p in r.stdout.splitlines() if p.strip())
    reste = [p for p in reste if not _jamais_livre(p)]
    if not reste:
        return ""
    return " ; %s %d fichier(s) suivi(s) modifie(s) NON livres par le commit : %s" % (
        _LIVRE_NON_COMMITTE, len(reste), ", ".join(reste[:15]))


def _committer_pour_agent(wt: str, task_id, detail: str, agent: str, exclus=frozenset()) -> str | None:
    """Commit par l'executeur (session owner) de ce que l'agent a ECRIT dans son worktree -- meme resultat que les
    autres CLI (des commits sur agent/<nom>), sans retirer le bac a sable. Fichiers LISTES par `git status`, jamais
    `add -A`, et JAMAIS ceux deja sales AVANT la tache (`exclus`, 16/10 : le worktree d'AGY portait 5 dossiers sans
    rapport) ; hooks du depot normaux (scan de secrets, git-gate). Rien n'est committe si l'agent dit lui-meme
    « pas fait ». Rend une note pour l'effet observe, ou None s'il n'y a rien a committer."""
    import subprocess as _sp
    if _intent_rendu(str(detail)):
        return None
    # Contrat `aucun` (reverification en lecture seule) : l'executeur ne commite RIEN pour elle (defaut
    # job_2751ecc3, 7/11 : run_tests.py ecrit par la reverification committe sous un message trompeur).
    try:
        _c = _db()
        try:
            _row = _c.execute("SELECT description FROM tasks WHERE id=?", (task_id,)).fetchone()
        finally:
            _c.close()
        _contrat = _contrat_livrable(_row[0]) if _row else None
    except Exception:  # noqa: BLE001 - description illisible : pas de refus sur une sonde muette
        _contrat = None
    if _contrat and _contrat.get("type") == "aucun":
        return "commit executeur REFUSE : contrat livrable aucun (lecture seule), rien n'est committe"
    g = ["git", "-c", "safe.directory=*", "-C", str(wt)]
    if isinstance(exclus, _SalesIllisibles):
        return ("commit executeur REFUSE rc=-1 : etat « sale avant la tache » illisible a la reprise -- "
                "travail conserve non committe")
    tous = _chemins_status(wt)
    if tous is None:
        return "commit executeur IMPOSSIBLE : status illisible"
    # Le marqueur d'identite du worktree (`.nokido.agent`) n'est JAMAIS une livraison : il partait dans les commits
    # (17/10 : 4 fois chez GPTOSS, 1 chez GLM) et le garde du pre-commit (demande owner R7) le bloque.
    # 24/10 : idem pour le verrou transitoire `nokido.lock` -- deja INDEXE par une tache precedente, il partait dans
    # chaque commit et le gate « transitoires » a refuse 5 livraisons ; on le RETIRE de l'index (fichier conserve).
    _transitoires = [p for p in tous if _jamais_livre(p)]
    if _transitoires:
        try:
            _sp.run(g + ["reset", "-q", "--"] + _transitoires, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=60, env=_env_git())
        except Exception as e:  # noqa: BLE001 - dit : le gate refusera, et on saura pourquoi
            log.warning(f"  transitoires NON retires de l'index ({type(e).__name__}): {_transitoires}")
    chemins = sorted(p for p in tous - frozenset(exclus or ()) if not _jamais_livre(p))
    if not chemins:
        return None
    _derog = _derogation_critique(task_id)
    # 8/11 : plus de refus CRITICAL_FILE ici (marque en fin de note) ; le garde bloquant vit dans forge_merge_gate.
    # 30/10 : un fichier RASE (-2532 / +27 chez OPENCODE_DEFAUT3) n'est jamais committe, quel que soit le scorecard.
    try:
        _ns = _sp.run(g + ["diff", "--numstat", "--"] + chemins, capture_output=True, text=True, encoding="utf-8",
                      errors="replace", timeout=60, env=_env_git())
        _rases = _reecritures_destructrices(_ns.stdout)
    except Exception as e:  # noqa: BLE001 - garde indisponible : DIT, le scorecard reste le juge
        log.warning(f"  garde reecriture destructrice INDISPONIBLE ({type(e).__name__})")
        _rases = []
    if _rases:
        return "commit executeur REFUSE : reecriture destructrice de %s (plus de la moitie des lignes retirees)" % (
            ", ".join(_rases[:5]))
    # Scorecard du DIFF avant tout commit (decision owner 19/10) : un diff casse n'est jamais committe, et le verdict
    # REJETEE est consigne sans relecteur (ead32585b : IndentationError committe par Mistral).
    try:
        from nokido_agent.app.forge_scorecard import QualityGrade, scorecard_de_livraison
        sc = scorecard_de_livraison(wt, chemins)
    except Exception as e:  # noqa: BLE001 - juge indisponible : DIT, le commit suit comme avant
        log.warning(f"  scorecard du diff INDISPONIBLE ({type(e).__name__}) -- commit non juge")
        sc = None
    if sc is not None and sc.grade == QualityGrade.REJECTED:
        try:
            from nokido_agent.app.forge_motivation import recompenser_resultat
            recompenser_resultat(agent, "M:ecrit", "REJETEE", preuve="%s : %s" % (str(task_id)[:40], sc.critique[:200]))
        except Exception as e:  # noqa: BLE001 - le verdict ne casse jamais l'executeur
            log.warning(f"  verdict REJETEE NON consigne ({type(e).__name__})")
        return "commit executeur REFUSE par le scorecard : %s" % sc.critique[:300]
    msg = None
    for m in re.finditer(r'"commit_message"\s*:\s*"([^"\n]{3,200})"', str(detail)):
        msg = m.group(1)
    msg = msg or "chore(%s): livraison de la tache %s" % (agent, str(task_id)[:40])
    corps = "Tache %s, executee par %s (bac a sable conserve) ; commit par l'executeur Nokido." % (task_id, agent)
    tests_ch = [p for p in chemins if _est_chemin_de_test(p)]
    code_ch = [p for p in chemins if not _est_chemin_de_test(p)]
    if tests_ch and code_ch:
        note2 = _committer_deux_temps(wt, g, tests_ch, code_ch, msg, corps, agent, derogation=_derog)
        return note2 + (_suivis_non_livres(g, exclus) if note2.startswith("commit executeur de") else "")
    try:
        a = _sp.run(g + ["add", "--"] + chemins, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=60, env=_env_git())
        c = _sp.run(g + ["commit", "-m", msg, "-m", corps], capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=180, env=_env_git()) if a.returncode == 0 else a
    except Exception as e:  # noqa: BLE001
        return "commit executeur ECHOUE (%s)" % type(e).__name__
    if c.returncode != 0:
        return "commit executeur REFUSE rc=%s : %s" % (c.returncode, (c.stderr or c.stdout)[-400:])
    note = "commit executeur de %d fichier(s) : %s" % (len(chemins), msg)
    if code_ch and not tests_ch and any(p.replace("\\", "/").startswith(("app/", "tools/")) for p in code_ch):
        note += " ; LIVRAISON SANS NR (code de production sans test)"
    note += _marque_critique(chemins, _derog)
    return note + _suivis_non_livres(g, exclus)


def _delegate_to_codex(task, token: str) -> None:
    """Codex execute dans SON worktree via le harness ; le verdict porte sur ce qui est LIVRE (commits, artefact
    verifie), jamais sur sa prose : le harness rend la sortie de codex, pas un statut de reussite."""
    task_id = task["id"]
    desc = _avec_carte_attention(_extract_message(task["description"] or "") or (task["description"] or ""))
    wt = str(_workdir_codex())
    _WORKDIR_TACHE[str(task_id)] = wt
    desc = precharger_corps_consigne(desc, workdir=wt)
    desc, _ = servir_documents_cites(desc, workdir=wt, racines_autorisees=[ROOT, Path(wt)], ledger_db=ROOT / "sandbox" / "context_ledger.db")
    args = (json.loads(os.environ["LAFORGE_CODEX_EXEC_ARGS"]) if os.environ.get("LAFORGE_CODEX_EXEC_ARGS")
            else _args_codex(Path(wt), _taille_tache(desc)))
    jid = "codex_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))[:80]
    job = _HARNESS_JOBS / (jid + ".json")
    _avant = _etat_git(wt)
    _sales_avant = _sales_avant_de(wt)   # 18/10 : 90bc00bee balayait les restes d'autres taches
    _purger_marqueurs_harness(job)
    job.write_text(json.dumps({"agent": "codex", "args": args, "send": _borne_dite(desc, 29000, "borne du job codex") + _CONSIGNE_GIT_CODEX, "eof": True,
                               "timeout": CODEX_TIMEOUT_S, "cwd": wt}, ensure_ascii=False), encoding="utf-8")
    n = _consommer_quota_codex()
    log.info(f"  DELEGATE {str(task_id)[:24]} -> CODEX via harness ({jid}, {n}/{CODEX_QUOTA_JOUR} aujourd'hui)")
    with _battement_delegation("CODEX", task_id):
        res = _attendre_harness(job, CODEX_TIMEOUT_S + 180, task_id=task_id)
    if res is None:
        ok, detail = False, (f"harness MUET apres {CODEX_TIMEOUT_S + 180} s "
                             f"(NokidoHarnessWorker arrete ou occupe ?) -- job {jid}")
    else:
        ok = bool(res.get("ok"))
        detail = str(res.get("output") or res.get("error") or "")[-6000:] or "codex : sortie vide"
        if ok and _panne_cli(detail):
            ok = False      # 19/10 : meme faux vert que Vibe (harness ok=True sur une erreur de fournisseur)
        if ok:
            note = _committer_pour_codex(wt, task_id, detail, exclus=_sales_avant)
            if note:
                detail = "%s\n[executeur] %s" % (detail, note)
    ok, effet, rendu = _juger_livraison(ok, detail, wt, _avant, autorises=_tests_autorises(desc), desc=desc)
    if ok and not rendu and _aucun_effet(effet, detail):
        ok = False      # rien de livre ni de pointe : le harness a tourne, Codex n'a rien produit de verifiable
        effet = "%s ; [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable" % effet
    ok = _finaliser_effet(task_id, ok, effet)
    log.info(f"  DELEGATE {str(task_id)[:24]} -> CODEX {'OK' if ok else 'KO'} {effet}"
             + ("" if ok else " | rendu : " + _tete_rendu(detail)))
    _consigner_verdict_auto("CODEX", task_id, ok, effet, detail, rendu)
    motif = _motif_reaffectation_apres(ok, effet, detail)
    t_reaff = dict(task)
    if not t_reaff.get("agent"):
        t_reaff["agent"] = "CODEX"
    if motif and _reaffecter(t_reaff, motif, ordre=_ordre_repli_pour(task), rendu=str(detail)):
        return
    _clore_delegation(task_id, token, ok, "%s | %s" % (effet, detail), intent=rendu)


# ---------------------------------------------------------------------------------------------------------------
# MISTRAL VIBE AUTONOME (owner 16/10 : « tu ne peux pas utiliser plus de cli ? »)
# Execution programmatique (--agent accept-edits, pas de shell). Worktree dedie nokido_worktrees/mistral.
# Aiguillage et harness branches apres certification de capacite.
# ---------------------------------------------------------------------------------------------------------------
VIBE_TIMEOUT_S = int(os.environ.get("LAFORGE_VIBE_TIMEOUT_S", "1500"))


# 20/10 (Vibe 3.0.1 / codestral) : write_file sur un fichier existant a casse l'indentation en OK_DONE ; 6 todo et un
# skill refuse ont mange les tours -- la consigne les ecarte, la borne de tours passe a 60 (_args_vibe).
_CONSIGNE_GIT_VIBE = (
    "\n\n[Executeur Nokido] Ne lance ni `git add` ni `git commit` : ton bac a sable tient .git en lecture seule et "
    "l'executeur committe lui-meme les fichiers que tu as modifies dans ce worktree. Pour modifier un fichier EXISTANT, "
    "utilise search_replace, jamais write_file (write_file reserve aux fichiers neufs) ; n'utilise ni todo ni skill ; "
    "lis les fichiers du worktree avec read_file. Termine par UNE ligne JSON "
    '{"intent":"OK_DONE"|"ERR_INTERNAL","pointer_ref":"...","commit_message":"<type(portee): resume>"}.'
    + _CONSIGNE_CRITIQUE)


def _workdir_vibe() -> Path:
    """Worktree DEDIE de Mistral Vibe (creation = geste OWNER). PAS de repli sur la racine partagee."""
    if _WT_TACHE.get() is not None:
        return Path(_WT_TACHE.get())
    env = os.environ.get("LAFORGE_VIBE_WORKDIR")
    return Path(env) if env else ROOT.parent / "nokido_worktrees" / "mistral"


def _bin_vibe() -> Path:
    """Binaire Vibe absolu (un second `vibe` npm est sur le PATH)."""
    env = os.environ.get("LAFORGE_VIBE_BIN")
    if env:
        return Path(env)
    home = os.environ.get("LAFORGE_AGENT_HOME", os.path.expanduser("~"))
    return Path(home) / ".local" / "bin" / "vibe.exe"


def _peut_lancer_vibe() -> tuple[bool, str]:
    """Capacite MESUREE : worktree dedie present (son fichier .git) et binaire vibe existant."""
    wt = _workdir_vibe()
    if not (wt / ".git").exists():
        return False, f"worktree Vibe absent ({wt}) -- creation = geste OWNER"
    bv = _bin_vibe()
    if not bv.exists():
        return False, f"binaire vibe introuvable ({bv})"
    return True, f"worktree {wt} et binaire vibe {bv} presents"


_TOURS_VIBE_PAR_TAILLE = {"S": 15, "M": 40, "L": 60}


def _args_vibe(wt: Path | str, prompt_file: Path | str | None = None, taille: str | None = None) -> list[str]:
    """Arguments d'invocation de Mistral Vibe en mode programmatique, bornes et sans shell.

    30/10 (reglages des CLI) : le plafond de tours suit la TAILLE de la tache (S 15, M 40, L 60), comme Claude headless ;
    taille inconnue = 60 (comportement d'avant) ; LAFORGE_VIBE_MAX_TURNS l'emporte toujours."""
    raw_turns = os.environ.get("LAFORGE_VIBE_MAX_TURNS", str(_TOURS_VIBE_PAR_TAILLE.get(taille or "", 60)))
    try:
        max_turns = str(int(raw_turns))
    except (ValueError, TypeError):
        max_turns = "60"
    raw_price = os.environ.get("LAFORGE_VIBE_MAX_PRICE", "1.0")
    try:
        max_price = str(float(raw_price))
    except (ValueError, TypeError):
        max_price = "1.0"
    raw_temps = os.environ.get("LAFORGE_VIBE_TIME_LIMIT", "1800")
    try:
        temps = str(int(raw_temps))
    except (ValueError, TypeError):
        temps = "1800"
    # 17/10 : `accept-edits` approuvait les editions mais ATTENDAIT une approbation a chaque outil MCP -- en headless
    # personne n'approuve (1re tache NON LIVREE, « Waiting for approval to run mcp_nokido.run »). Les shells sont RETIRES
    # du jeu d'outils (--disabled-tools, en plus de permission = never dans la config) : l'approbation totale ne porte
    # plus que sur les outils MCP (gouvernes par le hub) et les editions du worktree. --trust : automatisation, sans
    # invite de confiance ; --time-limit : une attente ne dure plus 25 min (vibe --help, 1.x).
    args = [
        "--agent", "auto-approve",
        "--workdir", str(wt),
        "--trust",
        "--output", "json",
        "--max-turns", max_turns,
        "--max-price", max_price,
        "--time-limit", temps,
        "--disabled-tools", "bash*",
        "--disabled-tools", "git_bash*",
        "--disabled-tools", "powershell*",
        # 18/10 23:08 : 31 skill.read + 31 read_file sur les skills, fichier vise jamais ouvert, 30 tours epuises
        "--disabled-tools", "skill*",
    ]
    if prompt_file:
        args.extend(["--prompt-file", str(prompt_file)])
        # 27/10 : 3 echecs Vibe lisibles seulement en fouillant le flux JSON et un vibe.log en UTC. A chaque sortie,
        # Vibe ecrit export.json (config effective, jetons, cout, raison d'arret, resultat) dans ce dossier.
        pf = Path(prompt_file)
        args.extend(["--output-dir", str(pf.with_name(pf.name.split(".")[0] + ".vibe_export"))])
    return args


_CONFIG_MCP_VIBE = """\
# Ecrit par tools/forge_task_executor.py (owner 16/10 : « il faut que vibe soit authentifie au mcp »).
# Vibe parle au hub MCP sous son identite PROPRE VIBE_HEADLESS. AUCUN jeton ici : le harness l'injecte au lancement,
# lu au coffre (FORGE_TOKEN_VIBE_HEADLESS). Lu seulement si ce worktree est approuve dans ~/.vibe/trusted_folders.toml.

# Forme b (owner 16/10) : NOTRE cle Mistral et Codestral -- mesure 125 req/min, 625 000 tokens/min ; Medium (defaut de
# Vibe) est ferme a 0 req/min sur cette cle. CLE RACINE EN TETE : en TOML, une cle placee apres un en-tete de table
# appartient a cette table (vecu 16/10 : active_model lu comme mcp_servers.auth.active_model, ignore en silence).
active_model = "codestral-nokido"

[[mcp_servers]]
name = "nokido"
transport = "streamable-http"
url = "http://127.0.0.1:8766/mcp"

[mcp_servers.auth]
type = "static"
api_key_env = "FORGE_TOKEN_VIBE_HEADLESS"
headers = { "LaForge-Agent-Name" = "VIBE_HEADLESS" }

# Fournisseur DISTINCT de « mistral » (dont la connexion navigateur interfererait), cle par la variable
# NOKIDO_MISTRAL_API_KEY que le harness lit au coffre au lancement.
[[providers]]
name = "mistral-api-nokido"
api_base = "https://api.mistral.ai/v1"
api_key_env_var = "NOKIDO_MISTRAL_API_KEY"
backend = "generic"

# 19/10 ~11 h 30 (decision owner) : RETOUR a codestral-latest. Le passage du matin a Mistral Medium garantissait un 429 :
# le census mesure medium / small / devstral a x-ratelimit-limit-req-minute: 0 sur notre cle (17/10 et 19/10, en ligne).
# Codestral : 125 req/min, outils OK. Un modele prouve hors quota est desormais REFUSE avant delegation (_modele_hors_quota).
[[models]]
name = "codestral-latest"
provider = "mistral-api-nokido"
alias = "codestral-nokido"

# Fermeture MCP-only (owner 17/10 : « les garde fous doivent emaner du hub... et pareil pour les autres cli ») : Vibe
# autonome tourne sous le compte interactif -- ses shells natifs sont fermes, l'execution passe par `run` du hub
# (gouverne, compte). Les ecritures restent permises : l'executeur committe ce que Vibe ecrit DANS son worktree.
[tools.bash]
permission = "never"

[tools.git_bash]
permission = "never"

[tools.powershell]
permission = "never"
"""


_MODELE_VIBE = ("mistral", _palier.modele_de("vibe", "M"))   # (fournisseur au census, modele) -- celui du gabarit ci-dessus
_ENTETE_CONFIG_VIBE = "# Ecrit par tools/forge_task_executor.py"


def _config_mcp_vibe(wt) -> Path:
    """Pose la config MCP de projet de Vibe dans son worktree (schema vibe 2.24.5). Une config ecrite a la main n'est
    jamais ecrasee ; celle que l'EXECUTEUR a ecrite et qui est perimee se regenere (19/10 : un changement de modele dans
    le code n'atteignait pas le worktree, qui gardait mistral-medium a quota nul)."""
    chemin = Path(wt) / ".vibe" / "config.toml"
    if chemin.exists():
        try:
            actuel = chemin.read_text(encoding="utf-8")
        except OSError:
            return chemin
        if not actuel.startswith(_ENTETE_CONFIG_VIBE) or actuel == _CONFIG_MCP_VIBE:
            return chemin
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(_CONFIG_MCP_VIBE, encoding="utf-8")
    return chemin


def _modele_hors_quota(fournisseur: str, modele: str, chemin=None, maintenant: float | None = None) -> str | None:
    """Motif si le census free tier PROUVE le couple hors d'usage (0 req/min, ou mort 402/404/410, ou quota epuise
    CONSTATE dont l'echeance court -- 29/10), None sinon.

    Invariant bloquant (owner 19/10). Census absent, illisible ou muet sur le couple = None : INCONNU n'est pas NON, on
    delegue. Un 429 SANS limite nulle est un debit passager, pas une interdiction."""
    if chemin is None:
        try:  # le fichier que le census ECRIT (SORTIE), une seule verite pour l'ecrivain et le lecteur
            from forge_free_tier_census import SORTIE as chemin
        except Exception:  # noqa: BLE001 - census non importable : son emplacement historique
            chemin = ROOT / "sandbox" / "free_tier_census.json"
    p = Path(chemin)
    try:
        v = ((json.loads(p.read_text(encoding="utf-8")) or {}).get("verdicts") or {}).get("%s:%s" % (fournisseur, modele))
    except (OSError, ValueError, AttributeError):
        return None
    try:
        from forge_free_tier_census import quota_epuise_actif
        epuise = quota_epuise_actif(v, maintenant)
    except Exception:  # noqa: BLE001 - census non importable : l'epuisement est INCONNU, pas un refus
        epuise = None
    if epuise:
        return "%s:%s %s" % (fournisseur, modele, epuise)
    if not isinstance(v, dict) or v.get("joignable") is not False:
        return None
    limites = v.get("limites") or {}
    if str(limites.get("x-ratelimit-limit-req-minute", "")).strip() == "0":
        return "%s:%s a 0 req/min sur notre cle (census %s)" % (fournisseur, modele, v.get("mesure_le", "?"))
    if re.search(r"\b(402|404|410)\b", str(v.get("motif") or "")):
        return "%s:%s mort au census (%s, %s)" % (fournisseur, modele, v.get("motif"), v.get("mesure_le", "?"))
    return None


_RE_ECHAPPEMENT = re.compile(r'\\(["\\/bfnrtu])|\\')


def _texte_final_vibe(sortie: str) -> str:
    """Le texte du DERNIER message assistant d'une transcription `vibe --output json` ; la sortie telle quelle si elle
    n'en est pas une. 19/10 (job_da317f97) : dans la transcription les guillemets sont ECHAPPES, le juge ne trouvait
    jamais "pointer_ref" et rendait AUCUN EFFET sur une reponse juste.
    20/10 (job_499ed100) : le caviardage du harness laisse `\\[EMAIL_1]`, echappement INVALIDE -- la barre orpheline
    est doublee (les paires valides consommees d'abord), sinon le meme faux AUCUN EFFET revenait."""
    try:
        entrees = json.loads(sortie)
    except (TypeError, ValueError):
        try:
            entrees = json.loads(_RE_ECHAPPEMENT.sub(lambda m: m.group(0) if m.group(1) else "\\\\", sortie))
        except (TypeError, ValueError):
            return sortie
    if not isinstance(entrees, list):
        return sortie
    for e in reversed(entrees):
        if isinstance(e, dict) and e.get("role") == "assistant" and e.get("type") == "message":
            texte = "".join(c.get("text", "") for c in (e.get("content") or []) if isinstance(c, dict))
            if texte.strip():
                return texte
    return sortie


def _cle_mistral_au_coffre() -> bool:
    """Booleen : la cle Mistral existe au coffre (valeur jamais retournee ni journalisee)."""
    try:
        from nokido_agent.app.forge_secrets import get_secret
        return bool(get_secret("MISTRAL_API_KEY"))
    except Exception:  # noqa: BLE001
        return False


def _delegate_to_vibe(task, token: str, _conseil: dict | None = None) -> None:
    """Mistral Vibe execute dans SON worktree via le harness ; le verdict porte sur ce qui est LIVRE (commits, artefact
    verifie), jamais sur sa prose : le harness rend la sortie de vibe, pas un statut de reussite."""
    task_id = task["id"]
    _vivant, _motif_hw = _harness_vivant()
    if _vivant is not True:
        # 27/10 : worker mort depuis 03 h 04, chaque delegation attendait ~28 min un harness muet puis relancait
        _attendre_harness_dependance(task, token, _motif_hw, "Vibe")
        return
    _harness_attente_oubli(task_id)
    # INVARIANT (owner 19/10) : pas de delegation sur un modele que le census PROUVE hors quota -- l'essai du matin
    # (job_10971233) a rendu 429 avant toute action, mistral-medium etant a 0 req/min sur notre cle.
    _hors_quota = _modele_hors_quota(*_MODELE_VIBE)
    if _hors_quota:
        log.warning(f"  {str(task_id)[:24]} : modele de Vibe REFUSE ({_hors_quota}) -- reaffectation")
        if _reaffecter(dict(task), "MODELE HORS QUOTA : %s" % _hors_quota, ordre=_ordre_repli_pour(task)):
            return
        _clore_delegation(task_id, token, False, "[MODELE HORS QUOTA] %s -- aucun autre executeur vivant" % _hors_quota)
        return
    if not _cle_mistral_au_coffre():
        # Decision owner 24/10 : la cle n'est plus sur disque, le harness l'injecte au seul enfant vibe depuis le
        # coffre ; absente, on echoue NOMME plutot que de lancer Vibe sans cle.
        log.warning(f"  {str(task_id)[:24]} : cle Mistral absente du coffre -- Vibe non lance")
        _clore_delegation(task_id, token, False, "[CLE MISTRAL ABSENTE] cle Mistral absente du coffre (MISTRAL_API_KEY)"
                          " -- Vibe non lance")
        return
    desc = _avec_carte_attention(_extract_message(task["description"] or "") or (task["description"] or ""))
    wt = str(_workdir_vibe())
    _WORKDIR_TACHE[str(task_id)] = wt
    desc = precharger_corps_consigne(desc, workdir=wt)
    desc, _ = servir_documents_cites(desc, workdir=wt, racines_autorisees=[ROOT, Path(wt)], ledger_db=ROOT / "sandbox" / "context_ledger.db")
    jid = "vibe_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))[:80]
    prompt_file = _HARNESS_JOBS / (jid + ".prompt.md")
    job = _HARNESS_JOBS / (jid + ".json")
    try:
        _config_mcp_vibe(wt)   # AVANT l'etat git : la config n'est jamais comptee comme un livrable de la tache
    except OSError as e:
        log.warning(f"  config MCP de Vibe NON posee dans {wt} ({type(e).__name__}) : Vibe tournera sans le hub")
    conseil = _conseil if _conseil is not None else {}
    if "etat_avant" in conseil:     # relance : on juge contre l'etat d'AVANT le premier essai
        _avant, _sales_avant = conseil["etat_avant"]
    else:
        _avant = _etat_git(wt)
        _sales_avant = _sales_avant_de(wt)
    try:
        _HARNESS_JOBS.mkdir(parents=True, exist_ok=True)
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 2219, exc_info=True)
    if _conseil is None:
        _pre = _conseil_plan(desc, "vibe", conseil)
    else:
        _pre = "Avis de revue du conseiller : %s\n\n" % conseil.get("avis_revue", "")
    prompt_file.write_text(_pre + desc + _CONSIGNE_GIT_VIBE, encoding="utf-8")
    args = (json.loads(os.environ["LAFORGE_VIBE_EXEC_ARGS"]) if os.environ.get("LAFORGE_VIBE_EXEC_ARGS")
            else _args_vibe(wt, prompt_file=prompt_file, taille=_taille_tache(desc)))
    _purger_marqueurs_harness(job)
    job.write_text(json.dumps({"agent": "vibe", "args": args,
                               "timeout": VIBE_TIMEOUT_S, "cwd": wt}, ensure_ascii=False), encoding="utf-8")
    log.info(f"  DELEGATE {str(task_id)[:24]} -> VIBE via harness ({jid})")
    with _battement_delegation("MISTRAL", task_id):
        res = _attendre_harness(job, VIBE_TIMEOUT_S + 180, task_id=task_id)
    if res is None:
        ok, detail = False, (f"harness MUET apres {VIBE_TIMEOUT_S + 180} s "
                             f"(NokidoHarnessWorker arrete ou occupe ?) -- job {jid}")
    else:
        ok = bool(res.get("ok"))
        detail = _texte_final_vibe(str(res.get("output") or res.get("error") or ""))[-6000:] or "vibe : sortie vide"
        if ok and _panne_cli(detail):
            ok = False      # 19/10 : le harness rendait ok=True sur une sortie « Error: ... 429 »
        if ok:
            note = _committer_pour_agent(wt, task_id, detail, "MISTRAL", exclus=_sales_avant)
            if note:
                detail = "%s\n[executeur] %s" % (detail, note)
    ok, effet, rendu = _juger_livraison(ok, detail, wt, _avant, desc=desc)
    if ok and not rendu and _aucun_effet(effet, detail):
        ok = False      # rien de livre ni de pointe : le harness a tourne, Vibe n'a rien produit de verifiable
        effet = "%s ; [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable" % effet
    if res is not None and _conseil_actif() and not conseil.get("revue_faite") and _conseil_a_revoir(ok, effet, detail):
        # res None = harness MUET : une relance attendrait le meme vide (27/10, 28 min x 2 par tache)
        avis = _conseil_revue(desc, "vibe", effet, wt, conseil)
        if avis:
            conseil["avis_revue"] = avis
            conseil["etat_avant"] = (_avant, _sales_avant)
            log.info("  [conseiller] VIBE : revue obtenue -- UNE relance avec l'avis")
            return _delegate_to_vibe(task, token, _conseil=conseil)
    effet = _conseil_trace(effet, conseil)
    ok = _finaliser_effet(task_id, ok, effet)
    _conseil_compter("vibe", ok, conseil)
    log.info(f"  DELEGATE {str(task_id)[:24]} -> VIBE {'OK' if ok else 'KO'} {effet}"
             + ("" if ok else " | rendu : " + _tete_rendu(detail)))
    _consigner_verdict_auto("MISTRAL", task_id, ok, effet, detail, rendu)
    motif = _motif_reaffectation_apres(ok, effet, detail)
    t_reaff = dict(task)
    if not t_reaff.get("agent"):
        t_reaff["agent"] = "MISTRAL"
    if motif and _reaffecter(t_reaff, motif, ordre=_ordre_repli_pour(task), rendu=str(detail)):
        return
    _clore_delegation(task_id, token, ok, "%s | %s" % (effet, detail), intent=rendu)


# ---------------------------------------------------------------------------------------------------------------
# CLAUDE HEADLESS (`claude -p`) -- CREDITS API, jamais le quota Max (owner 22/10)
# ---------------------------------------------------------------------------------------------------------------
# La session interactive de l'owner est connectee par le compte Max ; seul un `claude -p` lance AVEC la cle API
# (ANTHROPIC_API_KEY_ORG, au coffre, injectee par le harness sous l'identite `claude_api`) consomme les credits.
# L'agent DISTINCT `claude_api` porte cette cle ; `claude` (pilotage interactif) ne la recoit jamais.
#
# Extension des briques EXISTANTES, pas un second executeur : meme worktree dedie, meme harness, meme juge de
# livraison, meme consigne git. Le BUDGET est mesure sur `total_cost_usd` (sortie JSON de claude), avec un plafond
# JOURNALIER ; un cout INCONNU ne vaut JAMAIS 0 (unknowable != free) : il consomme un forfait.
CLAUDE_HEADLESS_AGENT = "CLAUDE_HEADLESS"
CLAUDE_TIMEOUT_S = int(os.environ.get("LAFORGE_CLAUDE_TIMEOUT_S", "1800"))
_CLAUDE_BUDGET = SANDBOX / "claude_headless_budget.json"
# Decision owner 22/10 « mesurer d'abord » : 3 $/jour pendant les essais, valeur a refonder sur le cout reel mesure.
# 22/10 (owner « fais sauter la limite de depenses ») : AUCUN plafond par defaut (inf). Le compteur journalier reste tenu
# (observabilite : cout mesure, inconnu = forfait) ; la Console Anthropic fait foi sur le credit reel (en differe).
# Un plafond se repose par LAFORGE_CLAUDE_PLAFOND_JOUR_USD. Le defaut du CODE porte la decision : un redemarrage du
# service ne relit pas l'env de services.toml (mesure 22/10).
_CLAUDE_PLAFOND_JOUR_USD = float(os.environ.get("LAFORGE_CLAUDE_PLAFOND_JOUR_USD", "inf"))
_CLAUDE_COUT_INCONNU_USD = float(os.environ.get("LAFORGE_CLAUDE_COUT_INCONNU_USD", "2.0"))

# Modele et nombre de tours par TAILLE de tache (S/M/L) : plus la tache est grosse, plus le modele est fort.
# Levier A (23/10) : modele ET effort viennent de la table UNIQUE tools/forge_palier_effort.py.
_MODELE_CLAUDE_PAR_TAILLE = {t: _palier.modele_de("claude", t) for t in ("S", "M", "L")}
_TOURS_CLAUDE_PAR_TAILLE = {"S": 15, "M": 40, "L": 80}

# Outils autorises : lecture, edition, glob, grep, et TROIS commandes motivees (git status, git diff, pytest).
# Pas de Bash libre : `Bash` sans motif = un shell entier, ce que le bac a sable du depot refuse partout ailleurs.
_OUTILS_CLAUDE = ("Read Edit Write Glob Grep "
                   "Bash(git status:*) Bash(git diff:*) Bash(python -m pytest:*) mcp__nokido")

_CONSIGNE_GIT_CLAUDE = (
    "\n\n[Executeur Nokido] Bash n'admet que `git status`, `git diff` et `python -m pytest` : ecris les fichiers avec "
    "Write/Edit (jamais `cat > f <<EOF`). Ne lance ni `git add` ni `git commit` : l'executeur committe lui-meme les "
    "fichiers que tu as modifies dans ce worktree. Si la tache exige du TDD : ecris le test, lance-le, VOIR ROUGE, "
    "puis seulement code. Termine par UNE ligne JSON "
    '{"intent":"OK_DONE"|"ERR_INTERNAL","pointer_ref":"...","commit_message":"<type(portee): resume>"}.'
    + _CONSIGNE_CRITIQUE)


def _workdir_claude() -> Path:
    """Worktree DEDIE de Claude headless (creation = geste OWNER). PAS de repli sur la racine partagee."""
    if _WT_TACHE.get() is not None:
        return Path(_WT_TACHE.get())
    env = os.environ.get("LAFORGE_CLAUDE_WORKDIR")
    return Path(env) if env else ROOT.parent / "nokido_worktrees" / "claude_headless"


def _args_claude(wt: Path | str, taille: str | None = None, escalade: str | None = None) -> list[str]:
    """Arguments d'invocation de `claude -p` : sortie JSON (c'est elle qui porte le cout), modele et tours bornes
    par la TAILLE, MCP strictement configure (le hub, rien d'autre), permission `acceptEdits` (les editions du
    worktree passent) et une liste d'outils SANS shell libre."""
    t = str(taille or "M").upper()
    modele = _MODELE_CLAUDE_PAR_TAILLE.get(t, _MODELE_CLAUDE_PAR_TAILLE["M"])
    tours = _TOURS_CLAUDE_PAR_TAILLE.get(t, _TOURS_CLAUDE_PAR_TAILLE["M"])
    effort = _palier.resoudre("claude", t if t in ("S", "M", "L") else "M", escalade=escalade)["effort"]
    # 22/10 (owner, essai mesure) : `--bare` = ni hooks, ni CLAUDE.md, ni memoire automatique de l'owner -- 5 Edit
    # natifs refuses par un hook dans le worktree (job_88af1e23) et un contexte injecte paye a chaque tache. Le hub
    # reste atteint par le --mcp-config EXPLICITE (ses gardes s'appliquent). Exige la cle API (pas d'OAuth Max).
    return [
        "-p",
        "--bare",
        "--output-format", "json",
        "--model", modele,
        "--effort", effort,
        "--max-turns", str(tours),
        "--mcp-config", str(Path(wt) / ".claude_headless_mcp.json"),
        "--strict-mcp-config",
        "--permission-mode", "acceptEdits",
        "--allowedTools", _OUTILS_CLAUDE,
        "--settings", str(ROOT / "config" / "claude_headless_settings.json"),
    ]


_PROVENANCE_RE = re.compile(r"^[A-Z0-9_]+$")


def _provenance_valide(provenance: str | None) -> str:
    """Provenance STRICTE : majuscules, [A-Z0-9_] SEULEMENT.

    Elle part dans la COMMANDE `headersHelper`, executee par un SHELL : un caractere hors
    alphabet (`&`, `"`, `|`, `;`, espace, backtick, `$()`, redirection) y est une INJECTION DE
    COMMANDE. Un caractere interdit est donc REFUSE (ValueError) -- jamais ecrit dans la
    commande, jamais « nettoye » en silence : un appelant qui veut une provenance bizarre doit
    la corriger, pas la voir rabattue sur un alphabet qui ne dit rien de l'agent."""
    prov = str(provenance or "").strip().upper()
    if not _PROVENANCE_RE.match(prov):
        raise ValueError("provenance refusee : %r (attendu : [A-Z0-9_]+)" % (provenance,))
    return prov


def _tache_valide(tache) -> str:
    """Forme courte de la tache : [A-Za-z0-9]+ SEULEMENT (elle part dans une commande de SHELL) ; autre -> ValueError."""
    t = str(tache or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", t):
        raise ValueError("tache refusee : %r (attendu : [A-Za-z0-9]+)" % (tache,))
    return t


def _config_mcp_claude(wt: Path | str, provenance: str = "TASK_EXECUTOR", tache: str | None = None) -> Path:
    """Config MCP du worktree : le hub en HTTP, jeton par VARIABLE D'ENVIRONNEMENT (`${FORGE_TOKEN_CLAUDE_HEADLESS}`)
    -- jamais un jeton ecrit sur disque (meme regle que Vibe, owner 16/10).

    `provenance` : QUI lance ce sous-processus (en-tete `LaForge-Provenance`). Elle est
    VALIDEE par `_provenance_valide` -- elle part dans une commande de SHELL."""
    chemin = Path(wt) / ".claude_headless_mcp.json"
    # 22/10 : `claude -p --mcp-config` NE remplace PAS ${VAR} dans les en-tetes -- CLAUDE_HEADLESS n'avait jamais ete
    # authentifie (16/16 en 401). headersHelper : le jeton est lu au coffre A LA CONNEXION, jamais ecrit sur disque.
    aide = '"%s" "%s" --emit-headers CLAUDE_HEADLESS --provenance %s' % (
        sys.executable, ROOT / "tools" / "forge_mcp_json_sync.py", _provenance_valide(provenance))
    if tache:
        from forge_worktree import court_tache as _court
        aide += " --tache %s" % _tache_valide(_court(tache))
    cfg = {"mcpServers": {"nokido": {
        "type": "http",
        "url": "http://127.0.0.1:8766/mcp",
        "headersHelper": aide}}}
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return chemin


def _job_claude(task_id, prompt, wt, taille: str | None = None) -> dict:
    """Job harness de `claude -p`. Le job ne porte AUCUN secret : la cle est injectee par le harness au lancement
    (table _SECRETS_PAR_AGENT de app/forge_cli_harness.py) -- meme regle que Vibe (owner 16/10)."""
    return {"agent": "claude_api",
            "args": _args_claude(wt, taille),
            "send": str(prompt) + _CONSIGNE_GIT_CLAUDE,
            "eof": True,
            "timeout": CLAUDE_TIMEOUT_S,
            "cwd": str(wt)}


def _cout_claude(sortie: str) -> float | None:
    """`total_cost_usd` de la DERNIERE ligne JSON de type `result` (sortie `claude -p --output-format json`) ;
    None si elle est illisible -- un cout INCONNU n'est jamais 0."""
    texte = str(sortie or "")
    candidats = []
    try:
        d = json.loads(texte)
        if isinstance(d, dict):
            candidats.append(d)
    except (TypeError, ValueError):  # muet-ok : ligne non JSON attendue dans la sortie de claude -p
        pass
    for ligne in texte.splitlines():
        s = ligne.strip()
        if not s.startswith("{"):
            continue
        try:
            d = json.loads(s)
        except (TypeError, ValueError):  # muet-ok : ligne non JSON attendue dans la sortie de claude -p
            continue
        if isinstance(d, dict):
            candidats.append(d)
    cout = None
    for d in candidats:
        if d.get("type") != "result":
            continue
        try:
            cout = float(d.get("total_cost_usd"))
        except (TypeError, ValueError):
            cout = None
    return cout


def _limite_de_tours(sortie: str) -> str | None:
    """Sous-type d'erreur du harness lu dans le JSON FINAL de `claude -p --output-format json` (`subtype:
    "error_max_turns"`, ou tout `is_error: true`), None si c'est un resultat normal ou illisible.

    On lit le CHAMP, jamais la prose de l'agent : une reponse qui CITE « error_max_turns » n'est pas une erreur du
    harness (meme regle que `_notes_executeur`). Mesure 7/11 (job_342863a9) : `is_error:true` + `error_max_turns`
    et aucun message final, mais des commits existaient -> la tache s'affichait done [SUCCESS]."""
    texte = str(sortie or "")
    candidats = []
    try:
        d = json.loads(texte)
        if isinstance(d, dict):
            candidats.append(d)
    except (TypeError, ValueError):  # muet-ok : sortie non JSON attendue dans la sortie de claude -p
        pass
    for ligne in texte.splitlines():
        s = ligne.strip()
        if not s.startswith("{"):
            continue
        try:
            d = json.loads(s)
        except (TypeError, ValueError):  # muet-ok : ligne non JSON attendue dans la sortie de claude -p
            continue
        if isinstance(d, dict):
            candidats.append(d)
    for d in candidats:
        if d.get("type") != "result":
            continue
        sous_type = str(d.get("subtype") or "")
        if sous_type.startswith("error_"):
            return sous_type
        if d.get("is_error"):
            return "is_error"
    return None


def _consommer_budget_claude(cout=None, jour: str | None = None, chemin=None) -> dict:
    """Consomme le budget du jour : cout MESURE s'il est connu, FORFAIT s'il est inconnu (unknowable != free).
    Rend {jour: {usd, taches, inconnus}}."""
    jour = jour or time.strftime("%Y-%m-%d")
    # Nom PROPRE et fichier `.json` nomme dans l'affectation : ce compteur n'est pas un pouls (cliquet
    # test_pouls_canon_nr -- `chemin`, reaffecte ailleurs depuis un parametre, y etait compte comme un pouls brut).
    fichier_budget = (Path(chemin) if chemin
                      else Path(_CLAUDE_BUDGET).with_name("claude_headless_budget.json"))
    try:
        etat = json.loads(fichier_budget.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        etat = {}
    if not isinstance(etat, dict):
        etat = {}
    j = etat.get(jour)
    if not isinstance(j, dict):
        j = {}
    try:
        usd = float(j.get("usd") or 0.0)
    except (TypeError, ValueError):
        usd = 0.0
    try:
        taches = int(j.get("taches") or 0)
    except (TypeError, ValueError):
        taches = 0
    try:
        inconnus = int(j.get("inconnus") or 0)
    except (TypeError, ValueError):
        inconnus = 0
    try:
        mesure = float(j.get("mesure_usd") or 0.0)
    except (TypeError, ValueError):
        mesure = 0.0
    try:
        forfait = float(j.get("forfait_usd") or 0.0)
    except (TypeError, ValueError):
        forfait = 0.0
    if cout is None:
        usd += float(_CLAUDE_COUT_INCONNU_USD)
        forfait += float(_CLAUDE_COUT_INCONNU_USD)
        inconnus += 1
    else:
        usd += float(cout)
        mesure += float(cout)
    # `usd` = mesure + forfait (total facture) ; les deux parts sont distinguees (23/10).
    jour_etat = {"usd": usd, "mesure_usd": mesure, "forfait_usd": forfait,
                 "taches": taches + 1, "inconnus": inconnus}
    etat[jour] = jour_etat
    try:
        fichier_budget.parent.mkdir(parents=True, exist_ok=True)
        fichier_budget.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning(f"  budget Claude headless NON ECRIT ({type(e).__name__}) : la depense reste non comptee")
    return {jour: jour_etat}


def _depense_claude_du_jour(jour: str | None = None) -> float | None:
    """Depense du jour en USD. None = ILLISIBLE (budget present mais illisible) : l'appelant REFUSE alors.
    Un budget ABSENT = aucune depense (0.0) -- rien n'a encore ete facture."""
    jour = jour or time.strftime("%Y-%m-%d")
    try:
        brut = Path(_CLAUDE_BUDGET).read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0.0
    except OSError:
        return None
    try:
        etat = json.loads(brut)
    except (TypeError, ValueError):
        return None
    if not isinstance(etat, dict):
        return None
    j = etat.get(jour)
    if j is None:
        return 0.0
    if not isinstance(j, dict):
        return None
    try:
        return float(j.get("usd") or 0.0)
    except (TypeError, ValueError):
        return None


def _peut_lancer_claude() -> tuple[bool, str]:
    """Capacite MESUREE : worktree dedie present, et depense du jour SOUS le plafond. Un budget illisible ou un
    plafond atteint REFUSENT le lancement -- l'argent ne se devine pas."""
    wt = _workdir_claude()
    if not (Path(wt) / ".git").exists():
        return False, f"worktree Claude headless absent ({wt}) -- creation = geste OWNER"
    depense = _depense_claude_du_jour()
    plafond = float(_CLAUDE_PLAFOND_JOUR_USD)
    if depense is None:
        return False, ("budget Claude headless ILLISIBLE (%s) : depense inconnue, lancement refuse"
                       % Path(_CLAUDE_BUDGET).name)
    if depense >= plafond:
        return False, ("PLAFOND JOURNALIER atteint : %.2f $ depenses sur %.2f $ (credits API) -- lancement refuse"
                       % (depense, plafond))
    return True, f"worktree {wt} present ; depense du jour {depense:.2f} $ / plafond {plafond:.2f} $"


_HARNESS_HEARTBEAT = _HARNESS_JOBS.parent / "harness_worker.heartbeat"
_HARNESS_POULS_MAX_S = 300  # le worker bat toutes les 3 s (--watch 3)


def _harness_vivant() -> tuple:
    """(True | False | None, motif) : le harness worker bat-il ? False = pouls PERIME (mort prouve), None = pouls absent
    ou illisible (non prouve vivant). NR test_harness_worker_vivant_avant_delegation_nr."""
    import datetime as _dt
    if os.environ.get("LAFORGE_HARNESS_POULS_IGNORE") == "1":  # tests qui simulent le harness (tests/nr/conftest.py)
        return True, "pouls ignore (test)"
    try:
        d = json.loads(_HARNESS_HEARTBEAT.read_text(encoding="utf-8"))
        ts = _dt.datetime.fromisoformat(str(d["ts"])[:19])
    except FileNotFoundError:
        return None, "pouls absent"
    except Exception as e:  # noqa: BLE001 -- muet-ok : l'etat illisible est RENDU a l'appelant
        return None, "pouls illisible (%s)" % type(e).__name__
    age = (_dt.datetime.now() - ts).total_seconds()
    if age > _HARNESS_POULS_MAX_S:
        return False, "pouls perime de %d s" % age
    return True, "pouls frais"


# 7/11 (panne 10:29-10:41) : harness perime/endormi = DEPENDANCE non satisfaite, pas un echec de la tache. Elle reste
# `pending` (ni echec, ni reaffectation, meme reservee) et on formule l'intention de reveil du harness (hub
# nokido_ensure_service). Duree bornee : 1800 s = pouls max (300 s) + cycle regulateur + relance superviseur, avec marge
# (721 s mesures ne suffisaient pas a conclure a la mort) ; au-dela le worker est tenu pour mort (cas 27/10), echec explicite.
_HARNESS_ATTENTE = ROOT / "sandbox" / "harness_attente.json"
_HARNESS_ATTENTE_MAX_S = 1800


def _harness_attente_lire() -> dict:
    try:
        d = json.loads(_HARNESS_ATTENTE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 -- muet-ok : marqueur absent/illisible = premiere attente
        return {}


def _harness_attente_ecrire(d: dict) -> None:
    try:
        _HARNESS_ATTENTE.parent.mkdir(parents=True, exist_ok=True)
        _HARNESS_ATTENTE.write_text(json.dumps(d), encoding="utf-8")
    except OSError as e:
        log.warning(f"  marqueur d'attente du harness non ecrit ({type(e).__name__})")


def _harness_attente_oubli(task_id) -> None:
    d = _harness_attente_lire()
    if d.pop(str(task_id), None) is not None:
        _harness_attente_ecrire(d)


def _attendre_harness_dependance(task, token: str, motif: str, nom: str) -> None:
    """Tache laissee `pending` tant que la duree bornee tient (+ intention de reveil), sinon echec HARNESS_WORKER."""
    task_id = str(task["id"])
    d = _harness_attente_lire()
    debut = float(d.setdefault(task_id, time.time()))
    ecoule = time.time() - debut
    if ecoule > _HARNESS_ATTENTE_MAX_S:
        d.pop(task_id, None)
        _harness_attente_ecrire(d)
        log.warning(f"  {task_id[:24]} : harness worker {motif} depuis {ecoule:.0f} s (> {_HARNESS_ATTENTE_MAX_S}) -- echec")
        _clore_delegation(task_id, token, False,
                          "[HARNESS WORKER %s] %s non lance apres %d s d'attente du harness" % (motif, nom, ecoule))
        return
    _harness_attente_ecrire(d)
    log.warning(f"  {task_id[:24]} : harness worker {motif} -- {nom} non lance, tache laissee en attente (pending) "
                f"depuis {ecoule:.0f} s, ni echec ni reaffectation ; reveil du harness demande")
    try:
        _hub_call("nokido_ensure_service", {"service": "NokidoHarnessWorker", "desired_state": "running"}, token)
    except Exception as e:  # noqa: BLE001 -- l'intention peut echouer ; le regulateur reveille aussi (demande heritee)
        log.warning(f"  intention de reveil du harness non transmise ({type(e).__name__})")
    conn = _db()
    try:
        conn.execute("UPDATE tasks SET status='pending' WHERE id=? AND status IN ('pending', 'running')", (task_id,))
        conn.commit()
    finally:
        conn.close()


def _delegate_to_claude(task, token: str) -> None:
    """`claude -p` execute dans SON worktree via le harness ; le verdict porte sur ce qui est LIVRE (commits,
    artefact verifie), jamais sur sa prose. Patron de `_delegate_to_vibe`."""
    task_id = task["id"]
    _vivant, _motif_hw = _harness_vivant()
    if _vivant is not True:
        _attendre_harness_dependance(task, token, _motif_hw, "claude -p")
        return
    _harness_attente_oubli(task_id)
    desc = _avec_carte_attention(_extract_message(task["description"] or "") or (task["description"] or ""))
    wt = str(_workdir_claude())
    _WORKDIR_TACHE[str(task_id)] = wt
    desc = precharger_corps_consigne(desc, workdir=wt)
    desc, _ = servir_documents_cites(desc, workdir=wt, racines_autorisees=[ROOT, Path(wt)], ledger_db=ROOT / "sandbox" / "context_ledger.db")
    taille = _taille_tache(desc) or "M"
    jid = "claude_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))[:80]
    job = _HARNESS_JOBS / (jid + ".json")
    try:
        _config_mcp_claude(wt, tache=task_id)   # AVANT l'etat git : la config n'est jamais comptee comme un livrable de la tache
    except OSError as e:
        log.warning(f"  config MCP de Claude headless NON posee dans {wt} ({type(e).__name__}) : claude tournera sans le hub")
    _avant = _etat_git(wt)
    _sales_avant = _sales_avant_de(wt)
    try:
        _HARNESS_JOBS.mkdir(parents=True, exist_ok=True)
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 2400, exc_info=True)
    _purger_marqueurs_harness(job)
    job.write_text(json.dumps(_job_claude(task_id, desc, wt, taille), ensure_ascii=False), encoding="utf-8")
    log.info(f"  DELEGATE {str(task_id)[:24]} -> CLAUDE_HEADLESS via harness ({jid}, taille {taille})")
    with _battement_delegation("CLAUDE_HEADLESS", task_id):
        res = _attendre_harness(job, CLAUDE_TIMEOUT_S + 180, task_id=task_id)
    if res is None:
        ok, detail = False, (f"harness MUET apres {CLAUDE_TIMEOUT_S + 180} s "
                             f"(NokidoHarnessWorker arrete ou occupe ?) -- job {jid}")
    else:
        ok = bool(res.get("ok"))
        detail = str(res.get("output") or res.get("error") or "")[-6000:] or "claude : sortie vide"
        if ok and _panne_cli(detail):
            ok = False      # le harness rendait ok=True sur une sortie « Error: ... 429 »
        if ok:
            note = _committer_pour_agent(wt, task_id, detail, "CLAUDE_HEADLESS", exclus=_sales_avant)
            if note:
                detail = "%s\n[executeur] %s" % (detail, note)
                if re.search(r"commit executeur (REFUSE|IMPOSSIBLE|ECHOUE)", note):
                    ok = False      # jamais `done` sans cause : le travail reste non committe, on le dit
                    detail = "[COMMIT_REFUSE] %s" % detail
    # BUDGET : mesure sur `total_cost_usd` de la sortie JSON ; un cout INCONNU consomme un forfait (jamais 0).
    cout = _cout_claude(str(res.get("output") or "") if res else "")
    budget = _consommer_budget_claude(cout)
    log.info(f"  DELEGATE {str(task_id)[:24]} -> cout Claude {cout} {budget}")
    # 7/11 (job_342863a9) : le champ JSON final du harness (`is_error` / `subtype`) prime sur l'enveloppe : une
    # limite de tours n'est jamais SUCCESS, meme si des commits existent. On LIT le champ, pas la prose de l'agent.
    _tours = _limite_de_tours(str(res.get("output") or "") if res else "")
    ok, effet, rendu = _juger_livraison(ok, detail, wt, _avant, desc=desc)
    if _tours:
        ok = False
        _motif_tours = ("le harness a epuise ses tours" if _tours == "error_max_turns"
                        else "le harness a fini en erreur")
        effet = "%s ; %s %s : %s, aucun message final" % (effet, _MARQUE_LIMITE_TOURS, _tours, _motif_tours)
    if ok and not rendu and _aucun_effet(effet, detail):
        ok = False      # rien de livre ni de pointe : le harness a tourne, claude n'a rien produit de verifiable
        effet = "%s ; [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable" % effet
    try:    # trace en colonnes dediees : le cout vient de la sortie COMPLETE, avant toute troncature du result
        _usd, _etat = _cout_et_etat(cout)
        _t = str(taille).upper() if str(taille).upper() in ("S", "M", "L") else "M"
        _conn_tr = _db()
        try:
            ecrire_trace_tache(_conn_tr, str(task_id), taille=_t, modele=_MODELE_CLAUDE_PAR_TAILLE.get(_t),
                               effort=_palier.resoudre("claude", _t)["effort"],
                               cout_usd=_usd, cout_etat=_etat, verdict_effet=effet)
        finally:
            _conn_tr.close()
    except Exception as e:  # noqa: BLE001 -- la trace ne doit jamais faire echouer la tache
        log.warning(f"  trace de fin de tache NON ecrite pour {str(task_id)[:24]} ({type(e).__name__}): {e}")
    ok = _finaliser_effet(task_id, ok, effet)
    log.info(f"  DELEGATE {str(task_id)[:24]} -> CLAUDE_HEADLESS {'OK' if ok else 'KO'} {effet}"
             + ("" if ok else " | rendu : " + _tete_rendu(detail)))
    _consigner_verdict_auto("CLAUDE_HEADLESS", task_id, ok, effet, detail, rendu)
    motif = _motif_reaffectation_apres(ok, effet, detail)
    if motif and _reaffecter(dict(task), motif, ordre=_ordre_repli_pour(task), rendu=str(detail)):
        return
    _clore_delegation(task_id, token, ok, "%s | %s" % (effet, detail), intent=rendu)


# ---------------------------------------------------------------------------------------------------------------
# OPENCODE AUTONOME MULTI-MODELES VIA ACP (decision owner 17/10, T2)
# Instances OPENCODE_GPTOSS, OPENCODE_NEMOTRON, OPENCODE_GLM pilotees par ACPClient.
# ---------------------------------------------------------------------------------------------------------------
OPENCODE_TIMEOUT_S = int(os.environ.get("LAFORGE_OPENCODE_TIMEOUT_S", "1500"))
# Veille de silence (decision owner 19/10) : une session sans AUCUN signe de vie (pensee, outil, texte) pendant ce
# delai est coupee -- 19/10, des sessions muettes attendaient les 1500 s entiers. Un long travail emet des updates.
OPENCODE_SILENCE_S = int(os.environ.get("LAFORGE_OPENCODE_SILENCE_S", "300"))

_CONSIGNE_GIT_OPENCODE = (
    "\n\n[Executeur Nokido] Ne lance ni `git add` ni `git commit` : ton bac a sable tient .git en lecture seule et "
    "l'executeur committe lui-meme les fichiers que tu as modifies dans ce worktree. Termine par UNE ligne JSON "
    '{"intent":"OK_DONE"|"ERR_INTERNAL","pointer_ref":"...","commit_message":"<type(portee): resume>"}.'
    + _CONSIGNE_CRITIQUE
)

try:
    from tools.forge_acp_client import ACPClient, SessionBusyError
except ImportError:
    try:
        from forge_acp_client import ACPClient, SessionBusyError
    except ImportError:
        try:
            _tools_dir = str(Path(__file__).resolve().parent)
            if _tools_dir not in sys.path:
                sys.path.insert(0, _tools_dir)
            from forge_acp_client import ACPClient, SessionBusyError
        except ImportError:
            ACPClient = None
            SessionBusyError = RuntimeError


def _instances_opencode() -> dict[str, dict]:
    """Instances OpenCode multi-modeles chargees depuis config/opencode_instances.json."""
    chemin = ROOT / "config" / "opencode_instances.json"
    env_cfg = os.environ.get("LAFORGE_OPENCODE_INSTANCES_FILE")
    if env_cfg:
        chemin = Path(env_cfg)
    fallback = {
        "OPENCODE_GPTOSS": {"modele": "groq/openai/gpt-oss-120b", "worktree": "opencode_gptoss"},
        "OPENCODE_NEMOTRON": {"modele": "openrouter/nvidia/nemotron-3-super-120b-a12b:free", "worktree": "opencode_nemotron"},
        "OPENCODE_GLM": {"modele": "zai/glm-4.7-flash", "worktree": "opencode_glm"},
    }
    if not chemin.exists():
        return fallback
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
        res = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}
        return res or fallback
    except Exception:
        return fallback


def _workdir_opencode(agent: str) -> Path:
    """Worktree DEDIE de l'instance OpenCode (creation = geste OWNER). PAS de repli sur la racine partagee."""
    if _WT_TACHE.get() is not None:
        return Path(_WT_TACHE.get())
    nom = (agent or "").upper()
    env = os.environ.get(f"LAFORGE_{nom}_WORKDIR") or os.environ.get("LAFORGE_OPENCODE_WORKDIR")
    if env:
        return Path(env)
    inst = _instances_opencode().get(nom, {})
    wt_nom = inst.get("worktree", nom.lower())
    return ROOT.parent / "nokido_worktrees" / wt_nom


def _bin_opencode(agent: str | None = None) -> Path | None:
    """Binaire OpenCode resolu via env, dossier appdata npm ou PATH."""
    nom = (agent or "").upper()
    env = os.environ.get(f"LAFORGE_{nom}_BIN") or os.environ.get("LAFORGE_OPENCODE_BIN")
    if env:
        return Path(env)
    try:
        from nokido_opencode_web import dossier_appdata, trouver_opencode
        exe = trouver_opencode(dossier_appdata())
        if exe:
            return Path(exe)
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 2328, exc_info=True)
    exe = shutil.which("opencode") or shutil.which("opencode.cmd")
    return Path(exe) if exe else None


def _peut_lancer_opencode(agent: str = "") -> tuple[bool, str]:
    """Capacite MESUREE : worktree dedie present (son fichier .git) et binaire opencode resolu."""
    nom = (agent or "OPENCODE").upper()
    repos = executeur_en_repos(nom)  # coupe-circuit (24/10) : en repos = plus choisi par defaut
    if repos:
        return False, f"en repos (coupe-circuit fournisseur) : {repos}"
    wt = _workdir_opencode(nom)
    if not (wt / ".git").exists():
        return False, f"worktree {nom} absent ({wt}) -- creation = geste OWNER"
    bv = _bin_opencode(nom)
    if not bv or not bv.exists():
        return False, f"binaire opencode introuvable ({bv})"
    return True, f"worktree {wt} et binaire opencode {bv} presents"


def _jeton_opencode_instance(inst: str) -> str | None:
    """Lit le jeton DERIVE de l'instance au coffre (nokido_agent.app.forge_secrets.get_secret("FORGE_TOKEN_" + inst)).
    Meme forme que jeton_mcp de app/forge_cli_harness.py : absent ou illisible -> None.
    Ne journalise JAMAIS la valeur du secret."""
    cle = f"FORGE_TOKEN_{inst}"
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        log.warning(f"  [opencode] coffre indisponible pour {inst} ({type(e).__name__}) : secret {cle} non lu")
        return None
    try:
        val = get_secret(cle)
        return str(val).strip() if val else None
    except Exception as e:  # noqa: BLE001
        log.warning(f"  [opencode] secret {cle} illisible au coffre ({type(e).__name__})")
        return None


# Variable d'environnement que lit OpenCode pour la cle d'un fournisseur, par le prefixe du modele « fournisseur/... »
# (mesure 17/10 : « model not found » -- le fournisseur n'etait pas configure faute de cle dans l'env de l'instance).
# 29/10 soir : « mistral » manquait -- mistral/codestral-latest echouait avant tout appel (aucune trace au journal).
_CLE_PAR_FOURNISSEUR = {"groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY", "zai": "ZHIPU_API_KEY",
                         "ollama_cloud": "OLLAMA_API_KEY", "mistral": "MISTRAL_API_KEY",
                         "lmstudio": "LMSTUDIO_TOKEN",
                         # 9/11 owner : cle OpenCode Zen au coffre ; sans elle les gratuits opencode/ partent en ANONYME
                         # et tombent sur « Free usage limit reached » (job_faee6253, cause QUOTA).
                         "opencode": "OPENCODE_API_KEY"}
# 3/11 (owner « LM Studio et OpenCode ne les oublie pas ») : palier LOCAL, gratuit et sans quota, en fin de chaine
# (OmniRoute : abonnement -> API gratuite -> local). qwen3-8b : le plus sur en appels d'outils parmi les modeles installes
# (qwen2.5-coder-7b-instruct en alternative). Charge a la demande, decharge apres LMSTUDIO_TTL_S.
LMSTUDIO_MODELE_OPENCODE = os.environ.get("LAFORGE_OPENCODE_LMSTUDIO_MODELE", "qwen3-8b")
# Owner 3/11 « opencode est un CLI seul, pourquoi passer par LM Studio, tu peux l'avoir en direct » : le palier LOCAL
# d'OpenCode est l'Ollama du corps EN DIRECT (:11434, supervise, sans cle ; fournisseur `ollama/` deja ferme au loopback).
# qwen3:8b : outils + raisonnement (mesure /api/show 3/11). LM Studio reste possible : LAFORGE_OPENCODE_REPLI_LOCAL.
REPLI_LOCAL_OPENCODE = os.environ.get("LAFORGE_OPENCODE_REPLI_LOCAL", "ollama/qwen3:8b")


def _env_cle_fournisseur(modele: str) -> str | None:
    """Nom de la cle du SEUL fournisseur du modele ; None pour un fournisseur sans cle (ollama/...) : rien a passer."""
    fournisseur = str(modele or "").split("/", 1)[0].strip().lower()
    return _CLE_PAR_FOURNISSEUR.get(fournisseur)


# Nom de la cle AU COFFRE quand il differe du nom d'env attendu par OpenCode (17/10 : tout Nokido lit ZAI_API_KEY).
_NOMS_COFFRE = {"ZHIPU_API_KEY": ("ZAI_API_KEY", "ZHIPU_API_KEY")}


def _lire_cle_fournisseur(nom: str) -> str | None:
    """Essaie les noms du coffre dans l'ordre (canonique Nokido d'abord) ; voir _lire_cle_sous."""
    for n in _NOMS_COFFRE.get(nom, (nom,)):
        v = _lire_cle_sous(n)
        if v:
            return v
    return None


def _lire_cle_sous(nom: str) -> str | None:
    """Cle fournisseur par la voie doctrinale : pool `forge_key_rotation.resolve(nom)` d'abord (une cle revoquee ou
    morte n'est jamais resservie : pool gere sans cle saine -> None, pas de repli), puis le coffre (get_secret).
    Absente ou illisible -> None. Ne journalise JAMAIS la valeur."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_key_rotation import resolve
        gere, cle = resolve(nom)
        if gere:
            return str(cle).strip() if cle else None
    except Exception as e:  # noqa: BLE001
        log.warning(f"  [opencode] rotation des cles illisible ({type(e).__name__}) : repli sur le coffre pour {nom}")
    try:
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        log.warning(f"  [opencode] coffre indisponible ({type(e).__name__}) : cle {nom} non lue")
        return None
    try:
        val = get_secret(nom)
        return str(val).strip() if val else None
    except Exception as e:  # noqa: BLE001
        log.warning(f"  [opencode] cle {nom} illisible au coffre ({type(e).__name__})")
        return None


# Tache [local] (owner 17/10 : « preserver le quota des modeles forts ... et des LLM free tiers ») : l'executeur lance un
# processus OpenCode PAR tache, sa configuration peut donc suivre la tache. Modele local = Ollama, loopback, 0 jeton cloud.
_MARQUEUR_LOCAL = re.compile(r"\[local\]", re.I)
# Quota gratuit epuise (owner 17/10 : « utilisez le quota b par jour quand dispo avant bascule ») : l'instance qui declare
# `repli_modele` relance UNE fois la tache sur ce modele. Mesure : openrouter « free-models-per-day » apres 1-2 taches.
# Solde epuise (26/10, z.ai x2 « Insufficient balance or no resource package ») : un solde a zero est un quota a zero,
# il doit ouvrir le repli FREE au lieu d'envoyer la tache hors famille. NR test_repli_sur_solde_epuise_nr.
# 28/10 : quota ChatGPT de Codex (« You've hit your usage limit », codexErrorInfo usageLimitExceeded).
# 31/10 (etape 1 OmniRoute, choix owner) : « API budget exhausted » (ACP -32603) tombait en panne FOURNISSEUR ->
# reaffectation en boucle, jamais le repli DANS la tache ; un budget a zero est un quota a zero.
# NR tests/nr/test_budget_epuise_est_un_quota_nr.py.
_RE_QUOTA = re.compile(r"rate limit exceeded|free-models-per-day|quota exceeded|\b429\b|insufficient balance|"
                       r"no resource package|please recharge|hit your usage limit|usageLimitExceeded|"
                       r"reached your (?:monthly |daily )?usage limit|free usage limit reached|"
                       r"budget exhausted", re.I)
_REPLI_EN_COURS: set[str] = set()


_RE_POINTEUR_CONSIGNE = re.compile(r"tasks\.db\s*[,:]\s*(?:id\s+)?(job_[A-Za-z0-9_]+)")
# 9/11 (choix owner) : consigne longue DEPOSEE dans sandbox/consignes/, servie en ligne par son pointeur
# « consigne:<nom>@<sha256[:12]> ». Nom sans chemin (pas de traversee) ; empreinte = le contenu revu a
# l'assignation, un fichier substitue depuis n'est jamais servi. Mesure : 17 x 24 Ko recopies = ~425 000 car.
_RE_POINTEUR_FICHIER = re.compile(r"consigne:([A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.(?:txt|md))@([0-9a-f]{12})")
# 9/11 : detecter consigne:<nom>.(txt|md) non suivi de @<sha12> pour refuser l'assignation sans consigne
# `(?<!\()` : les en-tetes deja servis « (consigne:<nom>) » (CONSIGNE RESOLUE / POINTEUR INRESOLU) ne sont pas des
# pointeurs -- une description resolue qui repasse par l'assignation (reaffectation) ne doit pas etre refusee.
_RE_POINTEUR_SANS_EMPREINTE = re.compile(
    r"(?<!\()consigne:([A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.(?:txt|md))(?!@[0-9a-f]{12})")
_CONSIGNES_DIR = Path(__file__).resolve().parent.parent / "sandbox" / "consignes"
_CONSIGNE_FICHIER_MAX = 60_000


def _resoudre_pointeurs_fichier(texte: str) -> list:
    import hashlib
    blocs = []
    for nom, empreinte in dict.fromkeys(_RE_POINTEUR_FICHIER.findall(texte)):
        contenu = None
        try:
            chemin = (_CONSIGNES_DIR / nom).resolve()
            if chemin.parent == Path(_CONSIGNES_DIR).resolve() and chemin.stat().st_size <= _CONSIGNE_FICHIER_MAX * 4:
                lu = chemin.read_text(encoding="utf-8")
                if hashlib.sha256(lu.encode("utf-8")).hexdigest()[:12] == empreinte:
                    contenu = lu[:_CONSIGNE_FICHIER_MAX]
        except (OSError, ValueError, UnicodeDecodeError):
            contenu = None
        if contenu is not None:
            blocs.append("--- CONSIGNE RESOLUE (consigne:%s) ---\n%s" % (nom, contenu))
        else:
            blocs.append("--- POINTEUR INRESOLU (consigne:%s) : fichier absent, hors dossier ou empreinte differente ; "
                         "ne pas le chercher, travailler avec la consigne ci-dessus seule ---" % nom)
    return blocs


def servir_consignes_a_l_assignation(desc: str) -> tuple:
    """9/11 (choix owner « AGY ») : seul le chemin OpenCode resolvait `consigne:<nom>@<empreinte>` ; servi a
    l'ASSIGNATION (hub), le contenu atteint TOUTES les surfaces et le pointeur est REMPLACE (jamais resolu deux fois).
    Un pointeur inresolu refuse l'assignation : la consigne n'est pas prete. Rend (description, erreur | None)."""
    texte = str(desc or "")
    sans_empreinte = list(dict.fromkeys(_RE_POINTEUR_SANS_EMPREINTE.findall(texte)))
    if sans_empreinte:
        return texte, ("consigne(s) sans empreinte a l'assignation : %s (forme attendue "
                       "`consigne:<nom>@<sha256[:12]>`)" % ", ".join("consigne:%s" % n for n in sans_empreinte))
    trouves = list(dict.fromkeys(_RE_POINTEUR_FICHIER.findall(texte)))
    if not trouves:
        return texte, None
    blocs = _resoudre_pointeurs_fichier(texte)
    inresolus = [nom for (nom, _e), b in zip(trouves, blocs) if b.startswith("--- POINTEUR INRESOLU")]
    if inresolus:
        return texte, ("consigne(s) inresolue(s) a l'assignation : %s (fichier absent de sandbox/consignes, nom "
                       "invalide ou empreinte differente)" % ", ".join(inresolus))
    sans = _RE_POINTEUR_FICHIER.sub(lambda m: "[consigne %s servie a l'assignation, ci-dessous]" % m.group(1), texte)
    return sans + "\n\n" + "\n\n".join(blocs), None


def _resoudre_pointeurs_consigne(desc: str, profondeur: int = 2) -> str:
    """29/10 : « tasks.db, id job_X » est INATTEIGNABLE pour l'agent (sandbox/ hors du worktree de tache, bash refuse,
    SQLite illisible par read) -- DEFAUT3/5 ont cherche tasks.db en boucle. Le pointeur est RESOLU ici, en ligne ;
    introuvable, il est DIT a l'agent pour qu'il ne le cherche pas."""
    texte = str(desc or "")
    ids = list(dict.fromkeys(_RE_POINTEUR_CONSIGNE.findall(texte)))
    fichiers = _resoudre_pointeurs_fichier(texte) if profondeur > 0 else []
    if not ids or profondeur <= 0:
        return texte + "\n\n" + "\n\n".join(fichiers) if fichiers else texte
    blocs = fichiers
    for tid in ids:
        try:
            c = _db()
            try:
                r = c.execute("SELECT description FROM tasks WHERE id=?", (tid,)).fetchone()
            finally:
                c.close()
        except Exception:  # noqa: BLE001 - base illisible : dit, jamais laisse a la recherche de l'agent
            r = None
        if r and r[0]:
            blocs.append("--- CONSIGNE RESOLUE (tasks.db:%s) ---\n%s" % (tid, _resoudre_pointeurs_consigne(r[0], profondeur - 1)))
        else:
            blocs.append("--- POINTEUR INRESOLU (tasks.db:%s) : ne pas chercher tasks.db, il n'est pas dans ton "
                         "worktree ; travailler avec la consigne ci-dessus seule ---" % tid)
    return texte + "\n\n" + "\n\n".join(blocs)


def _couple_du_modele(modele) -> tuple[str, str] | None:
    """`fournisseur/modele` (forme OpenCode) -> (fournisseur, modele) du census ; autre forme -> None (inconnu)."""
    f, sep, m = str(modele or "").partition("/")
    return (f, m) if sep and f and m else None


def _consigner_quota_principal(modele, detail) -> float | None:
    """29/10 (owner) : un quota epuise CONSTATE nourrit le census (echeance) ; rend l'echeance, None sinon."""
    couple = _couple_du_modele(modele)
    if not couple:
        return None
    # 29/10 soir, FAUSSE PANNE mesuree : un « quota exceeded » venu d'un AUTRE fournisseur (providerID=opencode, repli)
    # a ete impute au principal mistral:codestral-latest -- Vibe refuse « MODELE HORS QUOTA ». N'est consigne que
    # l'epuisement du fournisseur CITE ; un message sans providerID reste impute au principal, comme avant.
    m = re.search(r"providerID=([\w.-]+)", str(detail or ""))
    if m and m.group(1).lower() != couple[0].lower():
        log.warning(f"  [census] epuisement de {m.group(1)} NON impute a {couple[0]}:{couple[1]} (autre fournisseur)")
        return None
    try:
        from forge_free_tier_census import consigner_quota_epuise
        fin = consigner_quota_epuise(couple[0], couple[1], str(detail))
    except Exception:  # noqa: BLE001 - census indisponible : le constat est perdu, DIT
        log.warning(f"  [census] epuisement de {couple[0]}:{couple[1]} NON consigne (census indisponible)")
        return None
    if fin:
        log.warning(f"  [census] quota epuise consigne : {couple[0]}:{couple[1]} jusqu'a "
                    f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(fin))}")
    return fin


def _repli_du(inst_cfg: dict):
    """Modele de repli de l'instance (forme fournisseur/modele), None s'il n'y en a pas.

    3/11 : Ollama Cloud marque EPUISE (quota mensuel, registre partage) -> repli_modele, sinon le palier LOCAL LM Studio."""
    oc = str((inst_cfg or {}).get("repli_ollama_cloud", "") or "")
    if oc and not surface_est_indisponible("OLLAMA_CLOUD"):
        return "ollama_cloud/" + oc
    r = str((inst_cfg or {}).get("repli_modele", "") or "") or None
    if r:
        return r
    if not oc:
        return None
    # 8/11 (owner « pourquoi le GPU s'enflamme encore ») : Ollama Cloud epuise -> qwen3:8b LOCAL charge en silence
    # (5,2 Go VRAM a 12 h 42, relance OpenCode d'OPENCODE_DEFAUT2). Un executeur « gratuit » ne doit pas bruler le GPU
    # de l'owner sans le dire : le repli local est REFUSE par defaut, la tache suit le chemin « pas de repli » existant.
    # Opt-in explicite : LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE=1.
    if os.environ.get("LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE", "") != "1":
        log.warning(f"  repli local {REPLI_LOCAL_OPENCODE} REFUSE (GPU protege, Ollama Cloud epuise) : aucun repli")
        return None
    log.warning(f"  repli local {REPLI_LOCAL_OPENCODE} AUTORISE (LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE=1) : GPU sollicite")
    return REPLI_LOCAL_OPENCODE


def _repli_hors_quota(inst_cfg: dict) -> str | None:
    """29/10 soir : le repli n'etait jamais verifie au census -- 3 taches ont brule leur tentative sur un repli deja
    consigne hors quota (mensuel). Motif si le repli est hors quota, None sinon (inconnu = eligible)."""
    couple = _couple_du_modele(_repli_du(inst_cfg))
    return _modele_hors_quota(*couple) if couple else None


def _opencode_hors_quota(agent: str) -> str | None:
    """30/10 : la reaffectation passait la tache a OPENCODE_GPTOSS alors que groq gpt-oss etait CONSIGNE epuise (TPD)
    -> echec en 20 s, nouvelle reaffectation (ping-pong). Motif si le principal de l'instance est hors quota au census
    ET qu'aucun repli n'est disponible (absent ou hors quota) ; None sinon (inconnu = eligible)."""
    if not _est_opencode(agent):
        return None
    try:
        inst = (_instances_opencode() or {}).get(str(agent).upper()) or {}
    except Exception:  # noqa: BLE001 - instances illisibles : INCONNU = eligible, jamais un refus invente
        return None
    couple = _couple_du_modele(inst.get("modele"))
    principal = _modele_hors_quota(*couple) if couple else None
    if not principal and couple and couple[0].lower() == "ollama_cloud":
        # 7/11 : le principal Ollama Cloud est epuise au REGISTRE partage (quota mensuel note par _noter_indisponibilite)
        # meme si le census n'a pas encore le couple : le quota est CONNU, la voie n'est pas choisie.
        _motif = surface_est_indisponible("OLLAMA_CLOUD")
        principal = ("%s:%s %s" % (couple[0], couple[1], _motif)) if _motif else None
    if not principal:
        return None
    repli = _repli_hors_quota(inst) if _repli_du(inst) else "aucun repli"
    return f"principal {principal} ; repli {repli}" if repli else None


def _principal_hors_quota(modele, inst_cfg: dict) -> str | None:
    """Motif si le modele principal est hors quota au census ET qu'un repli est configure : on saute l'appel inutile."""
    couple = _couple_du_modele(modele)
    if not couple or not ("repli_modele" in (inst_cfg or {}) or (inst_cfg or {}).get("repli_ollama_cloud")):
        return None
    return _modele_hors_quota(*couple)


def _prompt_opencode_veille(client, sid, texte, timeout):
    """client.prompt + veilleur du journal OpenCode : une panne fournisseur n'y est ecrite que dans le journal
    (mesure 28/10 : SilenceACP 300 s). Panne lue -> QuotaJournalOpenCode (« quota exceeded ») -> repli immediat."""
    try:
        import forge_opencode_journal as _foj
    except ImportError:
        from tools import forge_opencode_journal as _foj
    return _foj.prompt_avec_veilleur(client, sid, texte, timeout, quota_re=_RE_QUOTA)


def _modele_de_la_tache(desc: str, modele_instance: str) -> str:
    """Modele local si la consigne porte `[local]`, sinon celui de l'instance."""
    if _MARQUEUR_LOCAL.search(str(desc or "")):
        return os.environ.get("LAFORGE_OPENCODE_MODELE_LOCAL", "ollama/qwen2.5-coder:7b")
    return modele_instance


def _config_opencode_instance(instance: str, modele: str | None = None) -> dict:
    inst = (instance or "OPENCODE").upper()
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "nokido": {
                "type": "remote",
                "url": f"{HUB_URL}/mcp",
                "enabled": True,
                "headers": {
                    "Authorization": f"Bearer {{env:FORGE_TOKEN_{inst}}}",
                    "LaForge-Agent-Name": inst,
                },
            }
        },
        "permission": {
            "bash": "deny",
        },
        # 30/10 (reglages des CLI, config.mdx d'OpenCode, verifie mot pour mot) : `prune` « Remove old tool outputs to
        # save tokens (default: false) » -- masquage des anciennes observations ; `auto` garde la compaction a saturation.
        "compaction": {"auto": True, "prune": True},
    }
    # None = rien demande -> modele de l'instance ; "" = modele PAR DEFAUT d'OpenCode demande explicitement (repli).
    modele = modele if modele is not None else _instances_opencode().get(inst, {}).get("modele")
    if modele:
        cfg["model"] = modele
    if str(modele or "").startswith("ollama_cloud/"):
        nom = modele.split("/", 1)[1]
        cfg["provider"] = {"ollama_cloud": {"npm": "@ai-sdk/openai-compatible", "name": "Ollama Cloud (FREE)",
                                            "options": {"baseURL": "https://ollama.com/v1",
                                                        "apiKey": "{env:OLLAMA_API_KEY}"},
                                            "models": {nom: {"name": nom}}}}
        cfg["small_model"] = modele
    if str(modele or "").startswith("lmstudio/"):
        # 3/11 : LM Studio LOCAL (loopback), cle LMSTUDIO_TOKEN injectee depuis le coffre comme les autres fournisseurs.
        nom = modele.split("/", 1)[1]
        cfg["provider"] = {"lmstudio": {"npm": "@ai-sdk/openai-compatible", "name": "LM Studio (local)",
                                        "options": {"baseURL": "http://127.0.0.1:%s/v1"
                                                    % os.environ.get("LAFORGE_LMSTUDIO_PORT", "1234"),
                                                    "apiKey": "{env:LMSTUDIO_TOKEN}"},
                                        "models": {nom: {"name": nom}}}}
        cfg["small_model"] = modele
    if str(modele or "").startswith("ollama/"):
        # LOCAL ferme : fournisseur ollama en loopback SEUL autorise, titres compris (small_model) -- aucun repli cloud.
        nom = modele.split("/", 1)[1]
        cfg["provider"] = {"ollama": {"npm": "@ai-sdk/openai-compatible", "name": "Ollama (local)",
                                      "options": {"baseURL": "http://127.0.0.1:%s/v1"
                                                  % os.environ.get("LAFORGE_OLLAMA_PORT", "11434")},
                                      "models": {nom: {"name": nom}}}}
        cfg["enabled_providers"] = ["ollama"]
        cfg["small_model"] = modele
    return cfg


# Relance multi-tour (mesure 17/10 16:18, OPENCODE_GLM sur l'instruction R2) : prompt() rend la main a la FIN DU TOUR ; une
# instance qui annonce « je commence » puis s'arrete (ERR_PARTIAL, 0 entree) etait close sur ce premier tour. On relance
# dans la MEME session tant que l'intention finale manque ou dit ERR_PARTIAL, borne en tours ET en temps.
OPENCODE_MAX_TOURS = int(os.environ.get("LAFORGE_OPENCODE_MAX_TOURS", "6"))
# CONSEILLER SOUVERAIN (owner 24/10, P1 etape 2) : voies GRATUITES (OpenCode, Vibe). PLAN avant delegation, UNE revue +
# UNE relance apres un echec de livraison. Interrupteur LAFORGE_CONSEILLER=0. Un conseiller en echec ne bloque jamais.
_CONSEIL_PLAN_MAX = 1500
_CONSEIL_CTX_MAX = 3000
_CONSEIL_COMPTEUR: dict = {}


def _conseil_actif() -> bool:
    return os.environ.get("LAFORGE_CONSEILLER", "1").strip() != "0"


# 29/10 : « jamais bloquant » doit valoir pour le TEMPS. Les 4 executeurs OpenCode ont appele le conseiller (Ollama Cloud
# nemotron-3-ultra) a 15:54:52 puis plus rien pendant 15 min : le creneau ne declare aucun delai.
CONSEIL_DELAI_S = float(os.environ.get("LAFORGE_CONSEIL_DELAI_S", "90"))


def _appeler_conseiller(tache: str, etape: str, contexte: str) -> dict:
    """Seul point d'appel du conseiller (doublable). Ne leve jamais, BORNE EN DUREE : echec = {avis:'', fournisseur:None}."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Delai
    try:
        try:
            from nokido_agent.app.forge_llm_router import conseiller
        except ImportError:
            from forge_llm_router import conseiller
        # PAS de bloc with : sa sortie attendrait la tache malgre le delai (C2.1, audit 29/10)
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="conseiller")
        try:
            r = pool.submit(conseiller, tache, etape, contexte).result(timeout=CONSEIL_DELAI_S) or {}
        except _Delai:
            log.warning("[conseil] %s : DELAI %.0f s depasse -- la delegation continue sans avis", etape,
                        CONSEIL_DELAI_S)
            return {"avis": "", "fournisseur": None, "escalade": [], "erreur": "DELAI %.0fs" % CONSEIL_DELAI_S}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return {"avis": str(r.get("avis") or "").strip(), "fournisseur": r.get("fournisseur"),
                "escalade": r.get("escalade") or []}
    except Exception as e:  # noqa: BLE001 - le conseil n'est jamais bloquant
        return {"avis": "", "fournisseur": None, "escalade": [], "erreur": "%s: %s" % (type(e).__name__, e)}


def _conseil_plan(desc: str, voie: str, conseil: dict) -> str:
    """Prefixe de prompt « Plan conseille : ... » ('' si desactive/KO). Remplit `conseil` (fournisseur, notes)."""
    if not _conseil_actif():
        return ""
    fichiers = sorted(set(re.findall(r"[\w./-]+\.(?:py|md|json|toml|ya?ml)", desc)))[:20]
    ctx = ("%s\nFichiers cites : %s" % (desc, ", ".join(fichiers) or "aucun"))[:_CONSEIL_CTX_MAX]
    r = _appeler_conseiller(desc[:500], "plan", ctx)
    avis = r["avis"]
    if not avis:
        conseil.setdefault("notes", []).append("conseil: indisponible, delegation SANS conseil")
        log.warning(f"  [conseiller] {voie} : plan sans avis -- delegation SANS conseil")
        return ""
    conseil["fournisseur"] = r.get("fournisseur")
    conseil["escalade"] = len(r.get("escalade") or [])
    if len(avis) > _CONSEIL_PLAN_MAX:
        avis = avis[:_CONSEIL_PLAN_MAX] + " [avis tronque]"
    return "Plan conseille : %s\n\n" % avis


def _conseil_a_revoir(ok: bool, effet: str, detail: str) -> bool:
    if ok:
        return False
    e = "%s\n%s" % (effet, str(detail)[:2000])
    return any(m in e for m in ("NON LIVRE", "RIEN_PRODUIT", "RIEN PRODUIT", "REJETEE", "BOUCLE SANS PROGRES"))


def _conseil_revue(desc: str, voie: str, effet: str, wt: str, conseil: dict) -> str:
    """UNE revue : rend le texte d'avis a injecter dans la relance ('' si indisponible). Marque revue_faite."""
    conseil["revue_faite"] = True
    import subprocess
    try:
        diff = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(wt), "diff", "HEAD"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=30).stdout
    except Exception:  # noqa: BLE001
        diff = ""
    ctx = ("Verdict : %s\nDiff :\n%s" % (effet, diff))[:_CONSEIL_CTX_MAX]
    r = _appeler_conseiller(desc[:500], "revue", ctx)
    avis = r["avis"]
    if not avis:
        conseil.setdefault("notes", []).append("conseil: revue indisponible, relance annulee")
        log.warning(f"  [conseiller] {voie} : revue sans avis -- pas de relance")
        return ""
    conseil["fournisseur"] = r.get("fournisseur") or conseil.get("fournisseur")
    conseil["escalade"] = len(r.get("escalade") or [])
    return avis[:_CONSEIL_PLAN_MAX]


def _conseil_trace(effet: str, conseil: dict) -> str:
    """Ajoute « conseil: <fournisseur> (escalade n) » (ou la note d'absence) au verdict_effet."""
    if conseil.get("fournisseur"):
        effet = "%s ; conseil: %s (escalade %s)" % (effet, conseil["fournisseur"], conseil.get("escalade", 0))
    for n in conseil.get("notes", []):
        effet = "%s ; %s" % (effet, n)
    return effet


def _conseil_compter(voie: str, ok: bool, conseil: dict) -> None:
    if not ok:
        return
    c = _CONSEIL_COMPTEUR.setdefault(voie, {"avec": 0, "sans": 0})
    c["avec" if conseil.get("fournisseur") else "sans"] += 1
    log.info(f"  [conseiller] compteur {voie} : livraisons OK avec conseil={c['avec']} sans conseil={c['sans']}")


_RELANCE_OPENCODE = (
    "[Executeur Nokido] Ta reponse ne rend pas d'intention finale (ou rend ERR_PARTIAL) : reprends exactement ou tu t'es "
    "arrete, va jusqu'au critere d'arret de la consigne, puis termine par la ligne JSON finale exigee "
    "(OK_DONE avec son pointer_ref, ou un echec DIT). Ne recommence pas ce qui est deja fait.")


def _doit_relancer(texte: str) -> bool:
    return _intention_finale(texte) in (None, "ERR_PARTIAL")


def _option_modele(session):
    """Option de configuration `model` annoncee par session/new (ACP v1 : configOptions), None si absente (legacy).
    Mesure 10/11 : OpenCode 2.2.6 ne connait plus `session/set_model` (« Method not found »)."""
    if not isinstance(session, dict):
        return None
    for o in session.get("configOptions") or []:
        if isinstance(o, dict) and (o.get("category") == "model" or o.get("id") == "model"):
            return o
    return None


def _valeurs_option(options, sortie: list) -> None:
    """Aplati les valeurs d'une option ACP select : entrees {value} ou groupes {group, options:[...]}."""
    for e in options or []:
        if isinstance(e, dict) and isinstance(e.get("options"), list):
            _valeurs_option(e["options"], sortie)
        elif isinstance(e, dict) and isinstance(e.get("value"), str) and e["value"]:
            sortie.append(e["value"])


def _appliquer_modele(client, sid, session, modele_choisi) -> None:
    """Regle le modele de la session : ACP v1 `session/set_config_option` si l'option est annoncee, sinon legacy
    `session/set_model` (OpenCode attend `modelId`, mesure 17/10). Leve l'erreur de l'agent : l'appelant la NOMME."""
    opt = _option_modele(session)
    if callable(getattr(client, "set_model", None)) and opt is None:
        client.set_model(sid, modele_choisi)
    elif opt is not None:
        client.request("session/set_config_option",
                       {"sessionId": sid, "configId": opt.get("id") or "model", "value": modele_choisi}, timeout=10)
    else:
        client.request("session/set_model", {"sessionId": sid, "modelId": modele_choisi}, timeout=10)


def _choisir_modele(modele, session):
    """(modele_choisi | None, note). Les modeles qu'OpenCode sait servir dependent des fournisseurs connectes :
    la liste vient de la reponse session/new conservee (session["models"]["availableModels"]).
    - liste inconnue (doublure sans derniere_session, reponse sans models) -> on TENTE le modele configure, comme avant ;
    - exact -> lui ;
    - sinon UN SEUL disponible au meme nom final (apres le dernier "/") -> celui-la, note qui le dit ;
    - sinon aucun set_model : la note DIT les modeles disponibles (12 noms max, le compte au-dela)."""
    if not modele:
        return None, ""
    dispo = []
    opt = _option_modele(session)
    if opt is not None:   # ACP v1 (OpenCode >= 2.2.6) : valeurs de l'option `model`, a plat ou groupees
        _valeurs_option(opt.get("options"), dispo)
    else:
        brut = None
        if isinstance(session, dict):
            models = session.get("models")
            if isinstance(models, dict):
                brut = models.get("availableModels")
        if isinstance(brut, list):
            for entree in brut:
                mid = entree.get("modelId") if isinstance(entree, dict) else entree
                if isinstance(mid, str) and mid:
                    dispo.append(mid)
    if not dispo:
        return modele, ""
    if modele in dispo:
        return modele, ""
    final = modele.rsplit("/", 1)[-1]
    jumeaux = [m for m in dispo if m.rsplit("/", 1)[-1] == final]
    if len(jumeaux) == 1:
        return jumeaux[0], (f"modele {modele} absent de la session : choisi {jumeaux[0]} "
                            f"(meme nom final {final})")
    noms = ", ".join(dispo[:12])
    if len(dispo) > 12:
        noms += f" (+{len(dispo) - 12} autres)"
    return None, f"modele {modele} absent de la session ; disponibles : {noms}"


def _delegate_to_opencode(task, token: str, instance: str | None = None, _etat_avant: tuple | None = None,
                          _conseil: dict | None = None) -> None:
    """Instance OpenCode executee dans SON worktree pilotee par ACPClient ; le verdict porte sur ce qui est LIVRE."""
    task_id = task["id"] if hasattr(task, "__getitem__") else getattr(task, "id")
    raw_desc = (task.get("description") if hasattr(task, "get") else task["description"]) or ""
    desc = _avec_carte_attention(_resoudre_pointeurs_consigne(_extract_message(raw_desc) or raw_desc))
    inst = str(instance or (task.get("agent") if hasattr(task, "get") else task["agent"]) or "").upper()
    if not inst and _instances_opencode():
        inst = next(iter(_instances_opencode().keys()))
    inst_cfg = _instances_opencode().get(inst, {})
    wt = str(_workdir_opencode(inst))
    _WORKDIR_TACHE[str(task_id)] = wt
    desc = precharger_corps_consigne(desc, workdir=wt)
    desc, _ = servir_documents_cites(desc, workdir=wt, racines_autorisees=[ROOT, Path(wt)], ledger_db=ROOT / "sandbox" / "context_ledger.db")
    # Le repli quota se rappelle : il reprend l'etat d'AVANT le premier tour, sinon le travail de ce tour passe pour
    # des restes d'autres taches et la preservation l'exclut (job_171ef456, enquete AGY job_198d901b, 19/10).
    if _etat_avant is not None:
        _avant, _sales_avant = _etat_avant
    else:
        _avant = _etat_git(wt)
        _sales_avant = _sales_avant_de(wt)

    inst_token = _jeton_opencode_instance(inst)
    if not inst_token:
        motif_jeton = f"jeton FORGE_TOKEN_{inst} absent ou illisible au coffre"
        log.warning(f"  DELEGATE {str(task_id)[:24]} -> {inst} REFUSE : {motif_jeton}")
        # 19/10 : 4 taches DEFAUT closes ici sans reaffectation -- une demande ne se perd pas (owner)
        if _reaffecter(dict(task), motif_jeton, ordre=_ordre_repli_pour(task)):
            return
        _clore_delegation(task_id, token, False, f"delegation refusee : {motif_jeton}")
        return

    modele = _modele_de_la_tache(desc, inst_cfg.get("modele", ""))
    note_repli = ""
    _saute_principal = None
    if str(task_id) not in _REPLI_EN_COURS:
        _saute_principal = _principal_hors_quota(modele, inst_cfg)
        if _saute_principal:
            log.warning(f"  [opencode] {inst} : principal SAUTE ({_saute_principal}) -> repli direct")
            _rhq = _repli_hors_quota(inst_cfg)
            if _rhq:
                motif_q = "principal ET repli hors quota (%s ; %s)" % (_saute_principal, _rhq)
                log.warning(f"  [opencode] {inst} : {motif_q} -> reaffectation sans tentative")
                if _reaffecter(dict(task), motif_q, ordre=_ordre_repli_pour(raw_desc)):
                    return
                _clore_delegation(task_id, token, False, motif_q)
                return
    if str(task_id) in _REPLI_EN_COURS or _saute_principal:
        modele = _repli_du(inst_cfg) or ""
        note_repli = "repli sur %s apres quota epuise ou delai depasse du modele principal" % (
            modele or "le modele par defaut d'OpenCode")
    repli_a_tenter = False
    cfg_dict = _config_opencode_instance(inst, modele)
    env = {
        "OPENCODE_CONFIG_CONTENT": json.dumps(cfg_dict, ensure_ascii=False),
        f"FORGE_TOKEN_{inst}": inst_token,
    }
    note_local = f"tache LOCALE ({modele}) : 0 jeton cloud" if str(modele).startswith("ollama/") else ""
    # Moindre privilege : l'instance recoit la cle de SON fournisseur, aucune autre, et jamais le jeton de l'executeur.
    note_cle = ""
    nom_cle = _env_cle_fournisseur(modele)
    if nom_cle:
        valeur_cle = _lire_cle_fournisseur(nom_cle)
        if valeur_cle:
            env[nom_cle] = valeur_cle
        else:
            note_cle = f"cle fournisseur {nom_cle} absente au coffre : le modele {modele} ne peut pas s'appliquer"
            log.warning(f"  [opencode] {inst} : {note_cle}")
    timeout = OPENCODE_TIMEOUT_S
    conseil = _conseil if _conseil is not None else {}
    if _conseil is None:
        prompt_text = _conseil_plan(desc, "opencode", conseil) + desc + _CONSIGNE_GIT_OPENCODE
    else:   # relance apres revue : l'avis de revue en prefixe, aucun nouveau plan
        prompt_text = "Avis de revue du conseiller : %s\n\n%s%s" % (conseil.get("avis_revue", ""), desc,
                                                                  _CONSIGNE_GIT_OPENCODE)

    if ACPClient is None:
        log.warning(f"  ACPClient indisponible pour {inst}")
        _clore_delegation(task_id, token, False, f"ACPClient indisponible pour {inst}")
        return

    client = ACPClient(agent="opencode", cwd=wt, env=env)
    detail = ""
    ok = False
    note_modele = ""
    try:
        client.start()
        client.initialize()
        sid = client.session_new()
        _session = getattr(client, "derniere_session", None)
        modele_choisi, note_modele = _choisir_modele(modele, _session)
        if modele_choisi:
            try:
                _appliquer_modele(client, sid, _session, modele_choisi)
            except Exception as exc_mod:
                note_modele = f"modele {modele_choisi} non applique ({type(exc_mod).__name__})"
                log.warning(f"  [opencode] {note_modele}: {exc_mod}")
        # OpenCode n'avait AUCUN battement pendant prompt() : un tour long paraissait une mort.
        with _battement_delegation(inst, task_id):
            _t0 = time.time()
            # veille de base, rallongee (24/10) pour une tache L ou un modele de raisonnement
            client.silence_max = OPENCODE_SILENCE_S + _rallonge_veille_s(_taille_tache(desc), modele_choisi or modele,
                                                                         inst_cfg)
            res = _prompt_opencode_veille(client, sid, prompt_text, timeout)
            detail = (res.get("text") if isinstance(res, dict) else str(res)) or ""
            tours = 1
            boucle_sans_progres = False
            derniere = detail.strip()
            while _doit_relancer(detail) and tours < OPENCODE_MAX_TOURS and time.time() - _t0 < timeout:
                tours += 1
                log.info(f"  [opencode] {inst} tour {tours}/{OPENCODE_MAX_TOURS} : intention finale "
                         f"{_intention_finale(detail) or 'absente'} -- relance dans la meme session")
                res = _prompt_opencode_veille(client, sid, _RELANCE_OPENCODE, max(60, int(timeout - (time.time() - _t0))))
                suite = (res.get("text") if isinstance(res, dict) else str(res)) or ""
                detail = f"{detail}\n[tour {tours}] {suite}"
                if suite.strip() == derniere:  # cliquet (24/10) : meme sortie qu'au tour d'avant = aucun progres
                    boucle_sans_progres = True
                    break
                derniere = suite.strip()
        if tours > 1 and _doit_relancer(detail):
            detail = f"{detail}\n[executeur] borne atteinte ({tours} tours) sans intention finale : livraison PARTIELLE"
        if note_modele:
            detail = f"[{note_modele}] {detail}" if detail else note_modele
        ok = bool(detail.strip())
        if boucle_sans_progres:
            ok = False
            detail = f"BOUCLE SANS PROGRES : meme sortie rendue au tour {tours}, relance coupee\n{detail}"
    except SessionBusyError as sbe:
        log.warning(f"  DELEGATE {str(task_id)[:24]} -> {inst} session occupee ({sbe}) -- report")
        _reporter(task, f"session occupee : {sbe}")
        return
    except Exception as exc:
        ok = False
        detail = f"erreur ACP OpenCode ({type(exc).__name__}): {exc}"
        if note_modele:
            detail = f"[{note_modele}] {detail}"
        # Quota epuise OU delai ACP depasse (mesure 17/10 : groq et zai x2 « timeout en attente id=4 », le modele par
        # defaut livre la meme tache ; GO owner ~22 h 50).
        if _RE_QUOTA.search(str(exc)) and str(task_id) not in _REPLI_EN_COURS and not _saute_principal:
            _consigner_quota_principal(modele, exc)
        repli_a_tenter = ((bool(_RE_QUOTA.search(str(exc))) or isinstance(exc, TimeoutError))
                          and ("repli_modele" in inst_cfg or inst_cfg.get("repli_ollama_cloud"))
                          and str(task_id) not in _REPLI_EN_COURS and not _saute_principal
                          and not _repli_hors_quota(inst_cfg))
    finally:
        try:
            client.close()
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 2625, exc_info=True)

    if repli_a_tenter:
        log.warning(f"  [opencode] {inst} : quota epuise -> repli sur le modele de repli pour {str(task_id)[:24]}")
        _REPLI_EN_COURS.add(str(task_id))
        try:
            return _delegate_to_opencode(task, token, inst, _etat_avant=(_avant, _sales_avant))
        finally:
            _REPLI_EN_COURS.discard(str(task_id))
    if note_repli:
        detail = f"[{note_repli}] {detail}" if detail else note_repli
    if note_cle:
        detail = f"[{note_cle}] {detail}" if detail else note_cle
    if note_local:
        detail = f"[{note_local}] {detail}" if detail else note_local
    note = _preserver_livraison(ok, wt, task_id, detail, inst, _sales_avant)
    if note:
        detail = "%s\n[executeur] %s" % (detail, note)
    ok, effet, rendu = _juger_livraison(ok, detail, wt, _avant, autorises=_tests_autorises(desc), desc=desc,
                                        consigne_servie=desc, modele_demande=modele)
    if ok and not rendu and _aucun_effet(effet, detail):
        ok = False      # rien de livre ni de pointe : le client a tourne, l'instance n'a rien produit de verifiable
        effet = "%s ; [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable" % effet
    if _conseil_actif() and not conseil.get("revue_faite") and _conseil_a_revoir(ok, effet, detail):
        avis = _conseil_revue(desc, "opencode", effet, wt, conseil)
        if avis:
            conseil["avis_revue"] = avis
            log.info(f"  [conseiller] {inst} : revue obtenue -- UNE relance avec l'avis")
            return _delegate_to_opencode(task, token, inst, _etat_avant=(_avant, _sales_avant), _conseil=conseil)
    effet = _conseil_trace(effet, conseil)
    ok = _finaliser_effet(task_id, ok, effet)
    _conseil_compter("opencode", ok, conseil)
    log.info(f"  DELEGATE {str(task_id)[:24]} -> {inst} {'OK' if ok else 'KO'} {effet}"
             + ("" if ok else " | rendu : " + _tete_rendu(detail)))
    _consigner_verdict_auto(inst, task_id, ok, effet, detail, rendu)
    if not ok:
        enregistrer_echec_executeur(inst, detail)  # coupe-circuit 3 etats : 2 echecs consécutifs = OPEN (15 min)
    else:
        enregistrer_succes_executeur(inst)
    if not ok and _est_panne_fournisseur(detail):
        enregistrer_panne_fournisseur(inst, detail)  # coupe-circuit (24/10) : 2 en 30 min = repos
    # Travail INACHEVE preserve sur la branche : on ne reaffecte pas (la reprise repartirait d'alpha et
    # orphelinerait le commit) -- il attend une relecture.
    motif = None if (note and "INACHEVE" in note) else _motif_reaffectation_apres(ok, effet, detail)
    t_reaff = dict(task)
    if not t_reaff.get("agent"):
        t_reaff["agent"] = inst
    if motif and _reaffecter(t_reaff, motif, ordre=_ordre_repli_pour(raw_desc), rendu=str(detail)):
        return
    _clore_delegation(task_id, token, ok, "%s | %s" % (effet, detail), intent=rendu)


# REAFFECTATION (owner 17/10 : « il faut que Nokido soit en mesure de debloquer la situation si les cli n'existent plus
# ou n'ont plus de quota » ; decision du 16/10 : quota epuise = reaffecter a la volee ET le dire). Ordre des surfaces
# autonomes ; WORKER_CODE = modeles locaux, ni CLI ni quota -- le dernier recours.
# 3/11 (owner « LM Studio et OpenCode ne les oublie pas ») : la chaine ignorait les OpenCode (gratuits) ; OmniRoute ordonne
# abonnement -> API gratuite -> local. Le palier local (LM Studio) vit dans le repli de chaque instance OpenCode (_repli_du).
_ORDRE_REPLI_DEFAUT = ("ANTIGRAVITY,MISTRAL,CODEX,WORKER_CODE,OPENCODE_GLM,OPENCODE_DEFAUT2,OPENCODE_DEFAUT3,"
                       "OPENCODE_DEFAUT4,OPENCODE_DEFAUT5,OPENCODE_GPTOSS,OPENCODE_NEMOTRON")
_ORDRE_REPLI = tuple(a.strip().upper() for a in os.environ.get(
    "LAFORGE_REPLI_AUTONOME", _ORDRE_REPLI_DEFAUT).split(",") if a.strip())


def _executeur_bat(agent: str, max_age_s: float | None = None) -> bool:
    """Le pouls de l'executeur dedie a `agent` est-il frais ? Il bat en tete de boucle (beat_daemon) : un executeur
    OCCUPE par une longue tache le laisse vieillir, et c'est voulu (il ne la prendrait pas). Absent ou illisible =
    False : on ne pousse jamais une tache vers une file dont on ne sait pas qu'elle est videe."""
    max_age_s = max_age_s or 3 * POLL_INTERVAL
    try:
        d = json.loads(_hb_file(agent).read_text(encoding="utf-8"))
        ts = time.mktime(time.strptime(str(d.get("ts")), "%Y-%m-%dT%H:%M:%S"))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    return 0 <= time.time() - ts <= max_age_s


# PALIER (decision owner 18/10) : par taille ET capacite d'ecriture. AGY et WORKER_CODE n'ecrivent pas de fichier sous
# sandbox (3 non-livraisons « SUCCESS » mesurees le 18/10) ; Codex hors chaine (quota quasi nul, owner). Le palier L
# remonte au CLI pilote (Claude) : aucun executeur autonome ne le sert.
_OPENCODE_ECRITURE = ("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM")
# 24/10 (mesure : 5 echecs OpenCode sur ~8, reaffectations en chaine GPTOSS -> GLM -> GLM) : hors de la famille
# OpenCode, la reaffectation va d'abord a CLAUDE_HEADLESS, puis a MISTRAL -- jamais a un autre OpenCode adosse au
# meme fournisseur gratuit surcharge.
_ORDRE_HORS_OPENCODE = ("CLAUDE_HEADLESS", "MISTRAL")
# 29/10 (owner : « executeurs gratuits ») : interrupteur GLOBAL lu a chaque reaffectation. Present = la reaffectation
# n'envoie jamais une tache a une surface PAYANTE (DEFAUT3 partie chez CLAUDE_HEADLESS, credit API, contre ce choix).
_FICHIER_REPLI_GRATUIT = ROOT / "sandbox" / "repli_gratuit_seul.switch"
_SURFACES_PAYANTES = ("CLAUDE_HEADLESS",)


def _repli_gratuit_seul() -> bool:
    try:
        return Path(_FICHIER_REPLI_GRATUIT).exists()
    except OSError:
        return False
# Demande EXPLICITE d'OpenCode par l'appelant : marqueur `[opencode]` (ou `[opencode_glm]`...) dans la consigne, ou
# reservation `RESERVE A OPENCODE...` en tete.
_RE_OPENCODE_EXPLICITE = re.compile(r"\[\s*opencode(?:_[A-Za-z0-9]+)?\s*\]|^\s*RESERVE\s+A\s+OPENCODE", re.I | re.M)


def _tailles_opencode_par_defaut() -> tuple:
    """Tailles confiees a OpenCode SANS demande explicite : celles ou forge_palier_effort.TABLE pose un modele OpenCode
    (aujourd'hui S, local). M/L = « modele de l'instance » (None) = fournisseur gratuit, surcharge mesuree le 24/10."""
    try:
        return tuple(t for t in _palier.TAILLES if _palier.TABLE["opencode"][t][0])
    except Exception:  # noqa: BLE001 - table illisible : la regle mesuree (S seulement), jamais « tout »
        return ("S",)


def _palier_executeurs(taille: str, ecrit: bool) -> tuple:
    """Ordre de preference des executeurs pour une tache de `taille` (S/M) qui `ecrit` ou non du code, quand OpenCode
    est ADMIS (palier du 18/10). Le choix PAR DEFAUT passe par _palier_par_defaut (regle de taille du 24/10)."""
    # 27/10 (enquete OPENCODE_DEFAUT3) : les instances CONFIGUREES au-dela des 3 nommees (OPENCODE_DEFAUT2..5) n'etaient
    # jamais candidates -> « aucun autre executeur vivant » a tort. Nommees d'abord, puis le reste du registre.
    try:
        autres = tuple(sorted(k for k in _instances_opencode() if k not in _OPENCODE_ECRITURE))
    except Exception:  # noqa: BLE001 -- muet-ok : registre illisible, l'ordre nomme reste valable
        autres = ()
    ecriture = _OPENCODE_ECRITURE + autres
    if str(taille).upper() == "M" and not ecrit:
        return ("ANTIGRAVITY",) + ecriture
    return ecriture


def _palier_par_defaut(taille: str, ecrit: bool, explicite: bool = False) -> tuple:
    """Ordre des executeurs choisis PAR DEFAUT pour une tache de `taille` (S/M/L).

    24/10 : une tache M ou L n'est PAS confiee a OpenCode par defaut (forge_palier_effort.TABLE) ; seule une demande
    `explicite` de l'appelant l'y ramene (palier du 18/10). Hors OpenCode : CLAUDE_HEADLESS puis MISTRAL."""
    t = str(taille or "M").strip().upper()
    if explicite or t in _tailles_opencode_par_defaut():
        return _palier_executeurs(t, ecrit)
    if t == "M" and not ecrit:
        return ("ANTIGRAVITY",) + _ORDRE_HORS_OPENCODE
    return _ORDRE_HORS_OPENCODE


def _opencode_demande(desc) -> bool:
    """L'appelant a-t-il EXPLICITEMENT demande OpenCode dans la consigne ?"""
    return bool(_RE_OPENCODE_EXPLICITE.search(str(desc or "")))


def _ordre_repli_pour(source, ecrit: bool = True) -> tuple:
    """Ordre de reaffectation d'une tache d'apres SA consigne : taille declaree (M par defaut) et demande explicite
    d'OpenCode. `source` = la consigne (str) ou la tache (dict / Row portant `description`)."""
    if isinstance(source, str) or source is None:
        desc = source or ""
    else:
        try:
            desc = (source["description"] if "description" in source.keys() else "") or ""
        except Exception:  # noqa: BLE001 - tache illisible : consigne vide = taille M, sans demande explicite
            desc = ""
    return _palier_par_defaut(_taille_tache(desc) or "M", ecrit=ecrit, explicite=_opencode_demande(desc))


# COUPE-CIRCUIT par executeur OpenCode (24/10). Mesure : GLM -32603 « service may be temporarily overloaded » x2,
# DEFAUT2/NEMOTRON/DEFAUT5 « SilenceACP : silence de l'agent depuis 300 s ». Trois avis externes concordent : surcharge
# du fournisseur gratuit. Apres _COUPE_CIRCUIT_SEUIL pannes FOURNISSEUR en _COUPE_CIRCUIT_FENETRE_S, l'executeur est mis
# en REPOS : plus choisi ni par la reaffectation (_executeur_suspendu) ni par defaut (_peut_lancer_opencode). L'etat est
# PARTAGE entre les processus executeurs (fichier) : celui qui reaffecte n'est pas celui qui a vu la panne.
_COUPE_CIRCUIT_SEUIL = 2
_COUPE_CIRCUIT_FENETRE_S = 1800.0
_COUPE_CIRCUIT_COOLDOWN_S = 900.0  # 15 min cooldown (patron OmniRoute plan S3)
_RE_PANNE_FOURNISSEUR = re.compile(
    r"-32603|overloaded|surcharg|\b429\b|too many requests|rate.?limit|SilenceACP|silence de l'agent|BOUCLE SANS PROGRES", re.I)


def _cooldown_coupe_circuit_s() -> float:
    try:
        return float(os.environ.get("LAFORGE_COUPE_CIRCUIT_COOLDOWN_S", "") or _COUPE_CIRCUIT_COOLDOWN_S)
    except (TypeError, ValueError):
        return _COUPE_CIRCUIT_COOLDOWN_S


def statut_coupe_circuit(agent: str, maintenant: float | None = None) -> tuple[str, str | None]:
    """Statut formel a 3 etats ('CLOSED', 'OPEN', 'HALF_OPEN') du coupe-circuit par executeur.

    - CLOSED : fonctionnement normal ;
    - OPEN : bloque apres N=2 sorties vides ou echecs/reaffectations consecutives ;
    - HALF_OPEN : cooldown ecoule (15 min), autorise une seule tache d'essai.
    Rend (etat, motif). En cas d'etat absent ou illisible -> ('CLOSED', None) (UNKNOWN != NO).
    LECTURE PURE (01/11) : ne modifie jamais l'etat sur disque. La transition vers HALF_OPEN
    se calcule dynamiquement ; l'ecriture se fait lors de autoriser_essai_half_open / enregistrer_*.
    """
    nom = (agent or "").upper()
    if not nom:
        return "CLOSED", None
    etat_global = _lire_coupe_circuit()
    e = etat_global.get(nom)
    if not isinstance(e, dict):
        return "CLOSED", None

    st = str(e.get("etat") or "").upper()
    t = time.time() if maintenant is None else float(maintenant)

    # Cooldown ecoule ?
    until = float(e.get("open_until") or e.get("repos_jusqu_a") or 0.0)
    if until and t >= until:
        if st == "OPEN":
            return "HALF_OPEN", str(e.get("motif") or "HALF_OPEN (cooldown ecoule, essai permis)")
        if not st:
            return "CLOSED", None

    # Compatibilite ancien format repos
    repos_jusqu_a = e.get("repos_jusqu_a")
    if st not in ("CLOSED", "OPEN", "HALF_OPEN"):
        if repos_jusqu_a and t < float(repos_jusqu_a):
            st = "OPEN"
        else:
            st = "CLOSED"

    if st == "OPEN":
        motif = str(e.get("motif") or "OPEN (coupe-circuit actif)")
        if "OPEN" not in motif:
            motif = f"OPEN : {motif}"
        return "OPEN", motif

    if st == "HALF_OPEN":
        return "HALF_OPEN", str(e.get("motif") or "HALF_OPEN (essai en cours ou en attente)")

    return "CLOSED", None


# 7/11 : le verrou d'essai n'avait pas d'echeance : 4 surfaces gratuites refusees 15 a 21 h sans tache en cours.
# Plafond d'une session (24 min 30) + marge. NR tests/nr/test_coupe_circuit_essai_perime_nr.py.
_ESSAI_TTL_S = 1800


def _essai_reserve_a_cette_tache(task, agent: str, maintenant: float | None = None) -> bool:
    """Vrai si `_reaffecter` vient de consommer l'essai HALF_OPEN de `agent` pour CETTE tache (dernier saut vers lui,
    de moins de _ESSAI_TTL_S). Sans cela la boucle redemandait l'essai, se le refusait et reaffectait la meme tache en
    laissant le verrou pose. Trace absente ou illisible : False, le verrou decide."""
    nom = (agent or "").upper()
    t = time.time() if maintenant is None else float(maintenant)
    try:
        try:
            brut = task["reaffectations"]
        except (KeyError, IndexError):  # la ligne du lot ne porte pas la colonne : la demander a la base
            conn = _db()
            try:
                ligne = conn.execute("SELECT reaffectations FROM tasks WHERE id=?", (task["id"],)).fetchone()
            finally:
                conn.close()
            brut = ligne[0] if ligne else None
        dernier = json.loads(brut or "[]")[-1]
        if str(dernier.get("vers") or "").upper() != nom:
            return False
        quand = time.mktime(time.strptime(str(dernier.get("quand"))[:19], "%Y-%m-%dT%H:%M:%S"))
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, sqlite3.Error):
        return False
    return 0 <= t - quand < _ESSAI_TTL_S


def autoriser_essai_half_open(agent: str, maintenant: float | None = None) -> tuple[bool, str]:
    """En HALF_OPEN, autorise une et une seule tentative de tache d'essai.

    Rend (autorise, raison). En CLOSED, autorise sans verrou d'essai. En OPEN, refuse.
    L'ecriture de transition (OPEN -> HALF_OPEN avec trial_active=True) et de verrouillage vit ici.
    """
    nom = (agent or "").upper()
    st, motif = statut_coupe_circuit(nom, maintenant=maintenant)
    if st == "CLOSED":
        return True, "circuit ferme"
    if st == "OPEN":
        return False, f"circuit ouvert : {motif}"
    if st == "HALF_OPEN":
        etat_global = _lire_coupe_circuit()
        e = etat_global.get(nom) if isinstance(etat_global.get(nom), dict) else {}
        t = time.time() if maintenant is None else float(maintenant)
        if e.get("trial_active"):
            depuis = e.get("essai_depuis")
            if isinstance(depuis, (int, float)) and t - depuis < _ESSAI_TTL_S:
                return False, f"essai en cours (HALF_OPEN verrouille) pour {nom}"
            log.warning(f"  COUPE-CIRCUIT {nom} : verrou d'essai perime (pose a {depuis}), nouvel essai accorde")
        e["etat"] = "HALF_OPEN"
        e["trial_active"] = True
        e["essai_depuis"] = t
        etat_global[nom] = e
        _ecrire_coupe_circuit(etat_global)
        return True, f"essai autorise pour {nom} en HALF_OPEN"
    return True, "statut inconnu traite comme autorise"


def enregistrer_succes_executeur(agent: str) -> None:
    """Enregistre le succes d'une tache pour `agent` : reinitialise les echecs et referme le circuit (CLOSED)."""
    nom = (agent or "").upper()
    if not nom:
        return
    etat_global = _lire_coupe_circuit()
    e = etat_global.get(nom) if isinstance(etat_global.get(nom), dict) else {}
    e["etat"] = "CLOSED"
    e["echecs_consecutifs"] = 0
    e["trial_active"] = False
    e.pop("essai_depuis", None)
    e["pannes"] = []
    e.pop("motif", None)
    e.pop("open_until", None)
    e.pop("repos_jusqu_a", None)
    etat_global[nom] = e
    _ecrire_coupe_circuit(etat_global)
    log.info(f"  COUPE-CIRCUIT {nom} referme (CLOSED) apres succes")


def enregistrer_echec_executeur(agent: str, detail: str = "", maintenant: float | None = None) -> str | None:
    """Compte un echec consecutif (sortie vide, reaffectation ou panne fournisseur).

    Apres N=2 echecs consecutifs (ou en HALF_OPEN) -> bascule en OPEN pour cooldown (15 min).
    Rend le motif si passage ou maintien en OPEN, None sinon.
    """
    nom = (agent or "").upper()
    if not nom:
        return None
    t = time.time() if maintenant is None else float(maintenant)
    etat_global = _lire_coupe_circuit()
    e = etat_global.get(nom) if isinstance(etat_global.get(nom), dict) else {}

    st, _ = statut_coupe_circuit(nom, maintenant=t)
    cpt = int(e.get("echecs_consecutifs") or 0) + 1
    e["echecs_consecutifs"] = cpt
    e["trial_active"] = False
    e.pop("essai_depuis", None)

    cooldown = _cooldown_coupe_circuit_s()
    jusqu_a = t + cooldown
    motif = None

    if st == "HALF_OPEN" or cpt >= _COUPE_CIRCUIT_SEUIL:
        tete = str(detail or "").strip().splitlines()[0][:160] if str(detail or "").strip() else "echec delegation"
        motif = (f"OPEN jusqu'a {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(jusqu_a))} : {cpt} echec(s) "
                 f"consecutifs (dernier : {tete})")
        e["etat"] = "OPEN"
        e["open_until"] = jusqu_a
        e["repos_jusqu_a"] = jusqu_a
        e["repos_depuis"] = t
        e["motif"] = motif
        log.warning(f"  COUPE-CIRCUIT {nom} bascule en OPEN -- {motif}")

    etat_global[nom] = e
    _ecrire_coupe_circuit(etat_global)
    return motif


def _est_opencode(agent: str) -> bool:
    nom = (agent or "").upper()
    if not nom:
        return False
    if nom.startswith("OPENCODE"):
        return True
    try:
        return nom in _instances_opencode()
    except Exception:  # noqa: BLE001 - registre des instances illisible : seul le prefixe fait foi
        return False


def _est_panne_fournisseur(detail) -> bool:
    """Le DEBUT du detail dit-il une panne du FOURNISSEUR (-32603, overloaded, 429, SilenceACP) ? Un echec de travail
    (NR rouges) n'en est pas une ; seul le debut compte (un rapport qui PARLE de 429 n'est pas une panne)."""
    return bool(_RE_PANNE_FOURNISSEUR.search(str(detail or "").lstrip()[:600]))


def _fichier_coupe_circuit() -> Path:
    env = os.environ.get("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE")
    return Path(env) if env else SANDBOX / "opencode_coupe_circuit.json"


def _repos_opencode_s() -> float:
    try:
        return float(os.environ.get("LAFORGE_OPENCODE_REPOS_S", "") or 1800)
    except (TypeError, ValueError):
        return 1800.0


def _lire_coupe_circuit() -> dict:
    try:
        d = json.loads(_fichier_coupe_circuit().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ecrire_coupe_circuit(etat: dict) -> None:
    chemin = _fichier_coupe_circuit()
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, chemin)
    except OSError as e:
        log.warning(f"  [coupe-circuit] etat NON ecrit ({type(e).__name__}: {e}) -- le repos ne sera pas partage")


def enregistrer_panne_fournisseur(agent: str, detail: str, maintenant: float | None = None) -> str | None:
    """Compte une panne FOURNISSEUR de `agent` ; rend le motif de REPOS s'il vient d'y passer, None sinon.

    Une panne isolee ne met pas en repos ; deux dans la fenetre (30 min) oui. Le repos est JOURNALISE."""
    nom = (agent or "").upper()
    if not nom or not _est_panne_fournisseur(detail):
        return None
    t = time.time() if maintenant is None else float(maintenant)
    etat = _lire_coupe_circuit()
    e = etat.get(nom) if isinstance(etat.get(nom), dict) else {}
    pannes = [p for p in (e.get("pannes") or [])
              if isinstance(p, (int, float)) and 0 <= t - p <= _COUPE_CIRCUIT_FENETRE_S]
    pannes.append(t)
    e["pannes"] = pannes
    motif = None
    if len(pannes) >= _COUPE_CIRCUIT_SEUIL:
        jusqu_a = t + _repos_opencode_s()
        tete = str(detail or "").strip().splitlines()[0][:160] if str(detail or "").strip() else ""
        motif = (f"REPOS jusqu'a {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(jusqu_a))} : {len(pannes)} pannes "
                 f"fournisseur en {int(_COUPE_CIRCUIT_FENETRE_S // 60)} min (derniere : {tete})")
        e.update({"repos_depuis": t, "repos_jusqu_a": jusqu_a, "motif": motif, "pannes": []})
        log.warning(f"  COUPE-CIRCUIT {nom} mis en REPOS -- {motif}")
    etat[nom] = e
    _ecrire_coupe_circuit(etat)
    return motif


def executeur_en_repos(agent: str, maintenant: float | None = None) -> str | None:
    """Motif du repos ou etat OPEN de `agent` s'il court encore, None sinon (expire, absent, etat illisible)."""
    nom = (agent or "").upper()
    st, motif = statut_coupe_circuit(nom, maintenant=maintenant)
    if st == "OPEN":
        return motif or "REPOS (coupe-circuit OPEN)"
    e = _lire_coupe_circuit().get(nom) if nom else None
    if not isinstance(e, dict):
        return None
    fin = e.get("repos_jusqu_a") or e.get("open_until")
    if not isinstance(fin, (int, float)):
        return None
    t = time.time() if maintenant is None else float(maintenant)
    if t >= fin:
        return None
    return str(e.get("motif") or "REPOS (coupe-circuit fournisseur)")


# VEILLE ACP (24/10) : 300 s par defaut ; 600 s pour une tache L ou un modele declare « raisonnement » (cle
# `raisonnement` du profil d'instance, ou identifiant de modele qui le dit).
OPENCODE_SILENCE_LONG_S = int(os.environ.get("LAFORGE_OPENCODE_SILENCE_LONG_S", "600"))
_RE_MODELE_RAISONNEMENT = re.compile(r"reasoning|raisonnement|thinking|(?<![a-z0-9])r1(?![a-z0-9])", re.I)


def _modele_raisonnement(modele: str, inst_cfg: dict | None = None) -> bool:
    cfg = inst_cfg or {}
    return bool(cfg.get("raisonnement")) or bool(_RE_MODELE_RAISONNEMENT.search(str(modele or "")))


def _silence_acp_s(taille, modele: str = "", inst_cfg: dict | None = None) -> int:
    """Veille ACP (s) avant de declarer l'agent muet : longue pour une tache L ou un modele de raisonnement."""
    if str(taille or "").strip().upper() == "L" or _modele_raisonnement(modele, inst_cfg):
        return max(OPENCODE_SILENCE_S, OPENCODE_SILENCE_LONG_S)
    return OPENCODE_SILENCE_S


def _rallonge_veille_s(taille, modele: str = "", inst_cfg: dict | None = None) -> int:
    """Ce que la veille ajoute a OPENCODE_SILENCE_S pour cette tache (0 par defaut)."""
    return _silence_acp_s(taille, modele, inst_cfg) - OPENCODE_SILENCE_S


_RE_AUTH_FAIL = re.compile(r"authentication failed|not logged in|unauthorized|\b401\b", re.I)
# 31/10 (job_81843bc6) : `\bFAILED\b` (re.I) reconnaissait la CLE JSON `"failed":0` des statistiques de `claude -p` -> tout
# echec CLAUDE_HEADLESS etait lu « echec de travail », jamais reaffecte. Une cle JSON entre guillemets n'est pas un test.
_RE_ECHEC_TRAVAIL = re.compile(r'(?<!")\bFAILED\b(?!"\s*:)|AssertionError|tests?\s+rouges?|NR\s+rouges?|\b\d+\s+failed\b',
                               re.I)
# Credit fournisseur epuise : panne de SURFACE (reaffectation + surface indisponible), pas un echec de travail.
_RE_CREDIT_EPUISE = re.compile(r"credit balance is too low|insufficient[_ ]quota|insufficient credits?|credits? "
                               r"(?:epuise|exhausted)|billing.{0,20}(?:required|hard limit)", re.I)


def _est_echec_auth(detail: str) -> bool:
    """Detecte un echec d'authentification du CLI dans le DEBUT du detail.

    22/10 (job_f0172e63) : tout le detail etait scanne ; un rapport qui PARLAIT de 401 / unauthorized (la tache
    portait sur l'authentification) a ete pris pour une panne -> reaffecte, rapport efface, surface indisponible.
    Meme critere que _panne_cli : seuls les 400 premiers caracteres disent une panne."""
    return bool(_RE_AUTH_FAIL.search(str(detail or "").lstrip()[:400]))


def _est_echec_travail(detail: str) -> bool:
    """Detecte un echec de travail (NR rouges / test failure) dans le detail."""
    return bool(_RE_ECHEC_TRAVAIL.search(str(detail or "")))


def _panne_cli(detail: str) -> str | None:
    """Motif si la sortie d'un CLI COMMENCE par une erreur de fournisseur (429, 402, rate limit...), None sinon.

    19/10 (essai Mistral job_10971233) : le harness rendait ok=True sur « Error: Client error '429 Too Many Requests' ».
    Seul le DEBUT de la sortie compte : un rapport legitime qui PARLE de 429 n'est pas une panne. Motifs reutilises de
    _RE_PANNE_INFRA (meme critere que verdict_automatique)."""
    tete = str(detail or "").lstrip()[:400]
    if not re.match(r"(error|erreur|\[NON LIVR[EÉ]\])", tete, re.I):
        return None
    if (_RE_PANNE_INFRA.search(tete)
            or re.search(r"rate limit|overloaded|surcharg|service unavailable|-32603", tete, re.I)):
        return "PANNE FOURNISSEUR : %s" % tete.splitlines()[0][:160]
    return None


def _motif_reaffectation_apres(ok: bool, effet: str, detail: str = ""):
    """Une delegation ECHOUEE sans AUCUN commit se reaffecte ; une livraison existante (meme refusee) se RELIT ;
    effet illisible -> None (UNKNOWN n'est pas NO). Mesure du 18/10 : 8 non-livraisons reprises a la main.
    19/10 : une panne fournisseur se NOMME (et se reaffecte) au lieu de passer pour du travail non committe.
    20/10 : un echec d'authentification est une indisponibilite de SURFACE (reaffectation + surface indisponible) ;
    un echec de TRAVAIL (NR rouges) reste sans reaffectation de surface."""
    if ok:
        return None
    # 9/11 (etape 2) : travail preserve, jamais reaffecte en silence sur repli non declare ou contexte non servi
    if ("MODELE_REPLI_NON_DECLARE" in (effet or "") or "CONTEXTE_NON_SERVI" in (effet or "")
            or "MODELE_REPLI_NON_DECLARE" in str(detail or "") or "CONTEXTE_NON_SERVI" in str(detail or "")):
        return None
    # 8/11 (decision_garde_critique_a_l_integration) : commit refuse avec fichiers laisses non commites -> preserver
    # et remonter, jamais reaffecter (garder la reaffectation d'un echec sans livraison).
    if "[COMMIT REFUSE]" in (effet or ""):
        m_nc = re.search(r"fichiers non commites : (\d+)", effet or "")
        if m_nc and int(m_nc.group(1)) > 0:
            return None
    # 29/10 (job_3a3347e0) : un effet a 2 commits citait des fichiers d'une tache SUR l'authentification -> « ECHEC
    # AUTHENTIFICATION », surface marquee indisponible, reaffectation a MISTRAL (RIEN_PRODUIT). Un CLI qui a committe
    # etait connecte : des commits produits excluent l'echec d'authentification.
    m_commits = re.search(r"commits produits : (\d+)", effet or "")
    a_livre = bool(m_commits and int(m_commits.group(1)) > 0)
    m_credit = None if a_livre else (_RE_CREDIT_EPUISE.search(str(detail or "")) or _RE_CREDIT_EPUISE.search(effet or ""))
    if m_credit:  # 31/10 : « Credit balance is too low » -> la tache CLAUDE_HEADLESS etait close, jamais reaffectee
        return "CREDIT EPUISE : %s" % m_credit.group(0)
    panne_auth = not a_livre and (_est_echec_auth(detail) or _est_echec_auth(effet))
    if panne_auth:
        txt = detail if _est_echec_auth(detail) else effet
        return f"ECHEC AUTHENTIFICATION : {str(txt).strip()[:160]}"
    if _est_echec_travail(detail) or _est_echec_travail(effet):
        return None
    panne = _panne_cli(detail)
    if panne:
        return panne
    m = re.search(r"commits produits : (\d+)", effet or "")
    if not m or int(m.group(1)) != 0:
        return None
    return "NON LIVRE apres delegation (%s)" % (
        "travail laisse non committe" if "[NON LIVRE]" in effet else "echec sans livraison")


_RE_RESERVEE = re.compile(r"^\s*RESERVE\s+A\s+([A-Za-z0-9_\-]+)", re.IGNORECASE)


def _reservee_a(description) -> "str | None":
    """Agent nomme par le marqueur `RESERVE A <AGENT>` en tete de description (insensible a la casse), sinon None.
    Une tache reservee n'est JAMAIS reaffectee (audit securite : pas de fournisseur cloud tiers)."""
    m = _RE_RESERVEE.match(str(description or ""))
    return m.group(1).upper() if m else None


def _refuser_reaffectation_reservee(task, agent: str, motif: str) -> None:
    """Tache reservee : agent inchange, statut failed + M2M NEED_HUMAN_APPROVAL. Ne marque aucune surface indisponible."""
    tid = task["id"]
    res = json.dumps({"intent": "NEED_HUMAN_APPROVAL", "status_code": "RESERVEE_NON_REAFFECTABLE",
                      "pointer_ref": f"tasks.db:{tid}", "detail": str(motif)[:500]}, ensure_ascii=False)
    conn = _db()
    try:
        try:
            conn.execute("UPDATE tasks SET status='failed', result=? WHERE id=?", (res, tid))
            conn.commit()
        except sqlite3.OperationalError as e:
            log.warning(f"  {str(tid)[:24]} : tache reservee, statut failed NON ecrit ({e})")
    finally:
        conn.close()
    log.warning(f"  RESERVEE {str(tid)[:24]} : reservee a {agent}, reaffectation REFUSEE ({motif}) -> failed, "
                f"NEED_HUMAN_APPROVAL")


def _vers_moins_chargee(conn, task, desc, prefere: str, vivants: list) -> str:
    """22/10 : a palier egal, l'executeur vivant a la file la plus courte (pending+running) ; a charge egale, le choix
    deja fait (`prefere`). Garde « meme fichier = meme file » : si une tache en file d'un candidat vise un fichier de
    meme empreinte (forge_roadmap_keeper.empreinte_item), on reste chez lui. Illisible -> `prefere`."""
    try:
        try:
            from nokido_agent.tools.forge_roadmap_keeper import empreinte_item, empreintes_collision
        except ImportError:
            from forge_roadmap_keeper import empreinte_item, empreintes_collision
        cands = [prefere] + [a for a in vivants if a != prefere]
        charge = {a: 0 for a in cands}
        emp = empreinte_item({"reste": desc or ""})
        meme: list = []
        rows = conn.execute("SELECT id, agent, description FROM tasks WHERE status IN ('pending','running')").fetchall()
        for r in rows:
            ag = (r[1] or "").upper()
            if ag not in charge or r[0] == task["id"]:
                continue
            charge[ag] += 1
            if emp and ag not in meme and empreintes_collision(emp, empreinte_item({"reste": r[2] or ""})):
                meme.append(ag)
        if meme:
            cands = [a for a in cands if a in meme]
        return min(cands, key=lambda a: charge[a])
    except Exception:  # noqa: BLE001 - charge illisible : le choix d'origine, jamais un classement invente
        return prefere


_RENDU_MAX = 500


def _tete_rendu(detail) -> str:
    """Tete d'un rendu sur UNE ligne, bornee a _RENDU_MAX : ce qu'un journal ou une trace garde d'une surface. Le
    pointeur de sortie brute (« sortie brute agy : <chemin> », ecrit en FIN de detail) passe devant : c'est la preuve."""
    plat = re.sub(r"\s+", " ", str(detail or "")).strip()
    m = re.search(r"sortie brute agy : \S+", plat)
    if m and len(plat) > _RENDU_MAX:
        plat = "[%s] %s" % (m.group(0), plat)
    return plat[:_RENDU_MAX]


def _candidat_eligible(a: str) -> bool:
    """Pre-vol d'une surface de repli (OmniRoute) : pouls frais, non suspendue, quota OpenCode, disjoncteur non ouvert,
    (3/11) pas marquee INDISPONIBLE dans le registre partage (quota epuise jusqu'a sa remise a zero),
    et harness worker prouve sain/vivant pour les surfaces passant par le harness."""
    if not (_executeur_bat(a) and not _executeur_suspendu(a) and not _opencode_hors_quota(a)
            and statut_coupe_circuit(a)[0] != "OPEN" and not surface_est_indisponible(a)):
        return False
    if a in ("MISTRAL", "CLAUDE_HEADLESS") and _harness_vivant()[0] is not True:
        return False
    return True


# 3/11 (owner « routage par capacite ») : une tache TDD partait chez ANTIGRAVITY puis MISTRAL, qui refusent tout shell
# -> deux echecs certains avant une surface capable. La consigne DECLARE ses exigences en tete (`exigences: shell, ring0`).
_RE_EXIGENCES = re.compile(r"^\s*exigences\s*:\s*([^\n]*)", re.I | re.M)
# MANQUES PROUVES seulement (UNKNOWN != NO) : une surface sans manque mesure reste candidate, son echec sera classe.
_MANQUES_PROUVES = {
    "ANTIGRAVITY": {"shell"},   # --sandbox : « denied_actions: unsandboxed RunCommand » (15/10, 30/10)
    "MISTRAL": {"shell"},       # Vibe : « Tool execution denied by approval policy » (tool_denied, 3/11)
}
# ring 0 (forge_lane_admission.py, bac console d'un delegue : « requiert ring=0 », 3/11) : jamais delegue.
AGENT_RING0 = "CLAUDE"


def exigences_consigne(description) -> set:
    """Exigences declarees en tete de consigne (`exigences: shell, ring0`), normalisees ; aucune -> ensemble vide."""
    m = _RE_EXIGENCES.search(str(description or "")[:600])
    if not m:
        return set()
    return {e.strip().lower().replace(" ", "") for e in re.split(r"[,;]", m.group(1)) if e.strip()}


def surface_capable(agent: str, exigences) -> bool:
    """La surface peut-elle porter ces exigences ? Non si un manque est PROUVE ; ring0 n'est porte par aucun delegue."""
    ex = set(exigences or ())
    if "ring0" in ex:
        return False
    return not (ex & _MANQUES_PROUVES.get(str(agent or "").upper(), set()))


def _choisir_parmi(vivants, classe, conn):
    """Surface retenue parmi les candidats eligibles : ordre hedoniste MESURE s'il existe, sinon l'ordre donne ;
    l'essai HALF_OPEN n'est consomme que sur la surface retenue."""
    if not vivants:
        return None
    candidats = list(vivants)
    if len(vivants) > 1:
        try:
            from nokido_agent.app.forge_motivation import ordre_hedoniste_mesure
            candidats = list(ordre_hedoniste_mesure(vivants, classe or "M:ecrit", conn) or vivants)
        except Exception:  # noqa: BLE001 - mesure illisible : ordre donne INCHANGE, jamais un classement invente
            candidats = list(vivants)
    return next((a for a in candidats if autoriser_essai_half_open(a)[0]), None)


def router_taches_auto(ordre=None) -> list:
    """3/11 (owner « ne faudrait-il pas que les delegations soient effectuees par Nokido ? ») : une tache deposee
    agent=AUTO recoit sa surface ICI -- pre-vol (_candidat_eligible), capacites (surface_capable), ordre mesure.
    `ring0` -> AGENT_RING0. Sans surface capable : reste AUTO, le journal le dit. Le garde `agent='AUTO'` de l'UPDATE
    empeche deux executeurs de router la meme tache. Rend [(id, surface)] des taches routees."""
    faits = []
    conn = _db()
    try:
        try:
            rows = conn.execute("SELECT id, description FROM tasks WHERE agent='AUTO' AND status='pending'").fetchall()
        except sqlite3.OperationalError as e:
            log.warning(f"[auto] routage ILLISIBLE ({e})")
            return faits
        if not rows:
            return faits
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN reaffectations TEXT")
        except sqlite3.OperationalError:
            pass  # muet-ok : colonne deja presente
        _gratuit = _repli_gratuit_seul()
        for tid, desc in rows:
            exig = exigences_consigne(desc)
            if "ring0" in exig:
                vivants, vers = [], AGENT_RING0
            else:
                vivants = [a for a in (ordre or _ORDRE_REPLI)
                           if not (_gratuit and a in _SURFACES_PAYANTES) and _candidat_eligible(a)
                           and surface_capable(a, exig)]
                vers = _choisir_parmi(vivants, "M:ecrit", conn)
            if not vers:
                log.warning(f"[auto] {str(tid)[:24]} : AUCUNE surface capable et disponible "
                            f"(exigences {sorted(exig) or 'aucune'}) -- reste AUTO")
                continue
            row = conn.execute("SELECT reaffectations FROM tasks WHERE id=?", (tid,)).fetchone()
            trace = json.loads(row[0]) if row and row[0] else []
            trace.append({"de": "AUTO", "vers": vers, "motif": "choix Nokido", "exigences": sorted(exig),
                          "candidats": vivants, "quand": time.strftime("%Y-%m-%dT%H:%M:%S")})
            cur = conn.execute("UPDATE tasks SET agent=?, reaffectations=? WHERE id=? AND agent='AUTO' AND "
                               "status='pending'", (vers, json.dumps(trace, ensure_ascii=False), tid))
            conn.commit()
            if cur.rowcount == 1:
                faits.append((tid, vers))
                log.warning(f"[auto] ROUTEE {str(tid)[:24]} : AUTO -> {vers} (exigences {sorted(exig) or 'aucune'})")
        return faits
    finally:
        conn.close()


def _reaffecter(task: dict, motif: str, ordre=None, rendu: str = ""):
    """Passe la tache au premier executeur de _ORDRE_REPLI dont le pouls est frais, jamais a un agent deja essaye (pas
    de ping-pong) ; la remet `pending` chez lui et trace {de, vers, motif, quand} dans `reaffectations`. Rend l'agent
    receveur, ou None : chaine epuisee, la tache reste ou elle est, et le journal le dit.

    31/10 (autopsie OmniRoute) : la reaffectation part AVANT `_fin`, le rendu de la surface n'atteignait donc jamais
    tasks.db et le receveur ecrivait ensuite le sien. `rendu` (tete bornee, avec le pointeur de sortie brute) est garde
    dans la trace : la preuve de chaque surface essayee survit."""
    # Row du bus OU dict : les deux s'indexent et ont .keys(), seul le dict a .get (mesure 17/10) ; une tache SANS
    # agent (delegation directe, NR test_agy_worktree_et_effet / test_codex_effort) levait KeyError (2630156af, 18/10)
    de = ((task["agent"] if "agent" in task.keys() else "") or "").upper()
    _desc = task["description"] if "description" in task.keys() else None
    if _desc is None:
        try:
            _c = _db()
            try:
                _r = _c.execute("SELECT description FROM tasks WHERE id=?", (task["id"],)).fetchone()
                _desc = _r[0] if _r else None
            finally:
                _c.close()
        except Exception:  # noqa: BLE001 - description illisible : non reservee faute de preuve
            _desc = None
    _res = _reservee_a(_desc)
    if _res:
        _refuser_reaffectation_reservee(task, _res, motif)
        return None
    if de and (_est_echec_auth(motif) or str(motif or "").startswith("CREDIT EPUISE")):
        marquer_surface_indisponible(de, motif)
    elif de:
        _noter_indisponibilite(de, motif, rendu)   # 3/11 : quota epuise -> ecarte jusqu'a sa remise a zero, pour tous
    if de in ("AGY", "ANTIGRAVITY") and _est_quota_epuise("%s\n%s" % (motif or "", rendu or "")):
        log.warning(f"  {str(task['id'])[:24]} : quota AGY epuise -- tache laissee en attente (pending) chez {de}, sans reaffectation")
        return None
    _exig = exigences_consigne(_desc)   # 3/11 : routage par capacite
    if "ring0" in _exig:
        log.warning(f"  {str(task['id'])[:24]} : exigence ring0 -- JAMAIS deleguee, laissee chez {de} "
                    f"(a reprendre par {AGENT_RING0})")
        return None
    if de and _est_opencode(de) and executeur_en_repos(de):
        # 24/10 : un OpenCode en REPOS (fournisseur surcharge) ne passe pas la main a un autre OpenCode
        ordre = _ORDRE_HORS_OPENCODE
        log.warning(f"  {str(task['id'])[:24]} : {de} en REPOS (coupe-circuit) -- reaffectation HORS famille "
                    f"OpenCode ({' puis '.join(ordre)})")
    conn = _db()
    try:
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN reaffectations TEXT")
        except sqlite3.OperationalError:
            pass  # muet-ok : colonne deja presente
        try:
            row = conn.execute("SELECT reaffectations FROM tasks WHERE id=?", (task["id"],)).fetchone()
        except sqlite3.OperationalError as e:  # base sans table tasks (worktree neuf de la CI de reference e6642dcf1,
            # 4 NR rouges 19/10) : la reaffectation est ILLISIBLE, elle n'est pas faite et le journal le dit
            log.warning(f"  {str(task['id'])[:24]} : reaffectation ILLISIBLE ({e}) -- laissee chez {de}")
            return None
        trace = json.loads(row[0]) if row and row[0] else []
        essayes = {de} | {t.get("de") for t in trace} | {t.get("vers") for t in trace}
        _gratuit = _repli_gratuit_seul()
        vivants = [a for a in (ordre or _ORDRE_REPLI)
                   if a not in essayes and not (_gratuit and a in _SURFACES_PAYANTES) and _candidat_eligible(a)
                   and surface_capable(a, _exig)]
        if _gratuit and any(a in _SURFACES_PAYANTES for a in (ordre or _ORDRE_REPLI)):
            log.info(f"  {str(task['id'])[:24]} : repli gratuit seul -- {', '.join(_SURFACES_PAYANTES)} ecarte(s)")
        # L'essai HALF_OPEN se CONSOMME sur le seul candidat retenu : appele dans le filtre, il verrouillait l'essai
        # de CHAQUE candidat HALF_OPEN evalue, choisi ou non (relecture 1/11 de la livraison AGY).
        vers = next((a for a in vivants if autoriser_essai_half_open(a)[0]), None)
        try:  # 19/10 OBSERVATION : ce qu'aurait choisi l'ordre hedoniste (force mesuree) -- ne decide RIEN
            from nokido_agent.app.forge_motivation import ordre_hedoniste
            classe = (task["classe"] if "classe" in task.keys() else "") or "M:ecrit"
            hedoniste = (ordre_hedoniste(vivants, classe) or [None])[0] if vivants else None
        except Exception:  # noqa: BLE001 - registre illisible : INCONNU, jamais un choix
            hedoniste = "INCONNU"
        arme = False
        if len(vivants) > 1:  # 22/10 ARME (decision owner) : l'ordre suit la MESURE de tasks.db (14 j, panne neutre)
            try:
                from nokido_agent.app.forge_motivation import ordre_hedoniste_mesure
                mesure = ordre_hedoniste_mesure(vivants, (task["classe"] if "classe" in task.keys() else "") or "M:ecrit",
                                                conn)
            except Exception:  # noqa: BLE001 - mesure illisible : ordre d'amorce INCHANGE, jamais un classement invente
                mesure = None
            if mesure:
                vers, arme = mesure[0], True
        if vers and len(vivants) > 1:
            vers = _vers_moins_chargee(conn, task, _desc, vers, vivants)
        if not vers:
            log.warning(f"  {str(task['id'])[:24]} : {de} ne peut pas la prendre ({motif}) et AUCUN autre executeur "
                        f"vivant hors {sorted(x for x in essayes if x)} -- laissee chez {de}")
            return None
        entree = {"de": de, "vers": vers, "motif": str(motif)[:200], "quand": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "hedoniste": hedoniste, "arme": arme,
                  "cause": classer_cause_echec("%s\n%s" % (motif or "", rendu or ""))}   # 3/11 : cause classee
        if rendu:
            entree["rendu"] = _tete_rendu(rendu)
        trace.append(entree)
        cur = conn.execute("UPDATE tasks SET agent=?, status='pending', reaffectations=? WHERE id=? AND status IN "
                           "('pending', 'running')", (vers, json.dumps(trace, ensure_ascii=False), task["id"]))
        conn.commit()
        if cur.rowcount != 1:
            log.warning(f"  {str(task['id'])[:24]} : reaffectation vers {vers} SANS effet (statut change entre-temps)")
            return None
        log.warning(f"  REAFFECTEE {str(task['id'])[:24]} : {de} -> {vers} ({motif})")
        return vers
    finally:
        conn.close()


_MAX_REPORTS = int(os.environ.get("LAFORGE_MAX_REPORTS", "10"))


def _reporter(task: dict, motif: str):
    """Reporte une tache dont le workdir est tenu chez le meme agent (pending, reports+1),
    jusqu'a _MAX_REPORTS. Au-dela, reaffecte pour ne jamais bloquer indefiniment."""
    task_id = task.get("id") if hasattr(task, "get") else task["id"]
    conn = _db()
    try:
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN reports INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # muet-ok : colonne deja presente
        row = conn.execute("SELECT agent, status, reports FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        agent, status, cur_reports = row[0] or "", row[1], int(row[2] or 0)
        if status not in ("pending", "running"):
            return None
        if cur_reports < _MAX_REPORTS:
            nouveau = cur_reports + 1
            cur = conn.execute(
                "UPDATE tasks SET status='pending', reports=? WHERE id=? AND status IN ('pending', 'running')",
                (nouveau, task_id),
            )
            conn.commit()
            if cur.rowcount != 1:
                return None
            log.warning(f"  REPORTEE {str(task_id)[:24]} : {agent} (report {nouveau}/{_MAX_REPORTS}) — {motif}")
            return "REPORTEE"
    finally:
        conn.close()
    if hasattr(task, "keys") and not hasattr(task, "get"):
        task = dict(task)
    if isinstance(task, dict) and "agent" not in task:
        task = {**task, "agent": agent}
    return _reaffecter(task, motif)


def _worktree_de(nom: str) -> Path:
    """Le chemin du worktree d'un agent (meme racine que `forge_worktree.WT_ROOT`)."""
    return ROOT.parent / "nokido_worktrees" / str(nom).lower()


def _sauvegarder_avant_sync(nom: str, agent: str, task_id: str = "") -> str | None:
    """22/10 (job_d7d57967) : AVANT toute synchronisation, COPIE du travail non committe du worktree.

    `forge_worktree.sync` rebase le worktree sur alpha : un travail laisse non committe peut disparaitre au
    recalage. La copie est le filet : elle vit dans sandbox/sauvegardes_executeurs, elle n'efface rien."""
    wt = _worktree_de(nom)
    marque = "sync_%s_%s" % (str(nom).lower(), time.strftime("%Y%m%d%H%M%S"))
    return _sauvegarder_travail(str(wt), marque, agent or nom, frozenset(),
                                motif="avant synchronisation du worktree (%s)" % (task_id or "sans tache"))


def _preparer_worktree(agent: str, task_id: str = ""):
    """Avant la delegation : le worktree de l'agent est rebase sur alpha par la brique EXISTANTE `forge_worktree.sync`
    (meme worktree nokido_worktrees/<agent> ; sur conflit elle abandonne le rebase, rien n'est perdu), et c'est
    journalise. Un doublon (_partir_d_alpha) avait ete ecrit ici le 17/10 sans consulter le domaine : retire (anti-dup).

    22/10 : le travail non committé est COPIE AVANT le recalage -- un travail livre ne peut plus disparaitre."""
    mapping = {
        "ANTIGRAVITY": "antigravity",
        "CODEX": "codex",
        "MISTRAL": "mistral",
        "CLAUDE_HEADLESS": "claude_headless",
        "OPENCODE_GPTOSS": "opencode_gptoss",
        "OPENCODE_NEMOTRON": "opencode_nemotron",
        "OPENCODE_GLM": "opencode_glm",
    }
    for k, v in _instances_opencode().items():
        mapping[k] = v.get("worktree", k.lower())
    nom = mapping.get((agent or "").upper())
    if not nom:
        return None
    try:    # 22/10 : le filet AVANT le recalage -- un travail non committe ne doit pas pouvoir disparaitre
        _sauvegarder_avant_sync(nom, agent, task_id)
    except Exception as e:  # noqa: BLE001 -- le filet ne doit jamais empecher la delegation
        log.warning(f"  worktree {agent} : sauvegarde avant synchro impossible ({type(e).__name__})")
    try:
        import forge_worktree as _fw

        r = _fw.sync(nom)
    except Exception as e:  # noqa: BLE001
        log.warning(f"  worktree {agent} : synchronisation impossible ({type(e).__name__}) -- delegation sur l'etat courant")
        return None
    (log.info if r.get("rebased") else log.warning)(f"  worktree {agent} : {r}")
    return r


def _delegation_pour(agent: str):
    ag = (agent or "").upper()
    if ag in _instances_opencode() or ag.startswith("OPENCODE_"):
        return _delegate_to_opencode
    return {"CODEX": _delegate_to_codex, "MISTRAL": _delegate_to_vibe,
            "CLAUDE_HEADLESS": _delegate_to_claude}.get(ag)


def _capacite_pour(agent: str):
    ag = (agent or "").upper()
    if ag in _instances_opencode() or ag.startswith("OPENCODE_"):
        return lambda a=ag: _peut_lancer_opencode(a)
    return {"CODEX": _peut_lancer_codex, "MISTRAL": _peut_lancer_vibe,
            "CLAUDE_HEADLESS": _peut_lancer_claude}.get(ag)


def _marquer_accuse(task_id: str, texte: str) -> None:
    """Statut intermediaire VISIBLE : la tache est prise en compte, pas faite.

    Sans cet etat, un observateur ne dispose que de `running` (indiscernable d'un
    travail en cours) ou de `completed` (mensonge). Best-effort : le suivi ne doit
    jamais faire echouer le relais.
    """
    try:
        conn = _db()
        _att = _TENTATIVE_PRISE.get(str(task_id))
        _msg = f"ACCUSE DE RECEPTION (pas un compte rendu) : {texte[:600]}"
        _now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if _att is None:
            conn.execute("UPDATE tasks SET status='acknowledged', result=?, updated_at=? WHERE id=?",
                         (_msg, _now, task_id))
        else:
            _c = conn.execute(
                "UPDATE tasks SET status='acknowledged', result=?, updated_at=? WHERE id=? "
                "AND status IN ('running','acknowledged') AND COALESCE(attempt,0)=?", (_msg, _now, task_id, _att))
            if _c.rowcount != 1:
                _ecriture_refusee(conn, task_id, _att, "acknowledged")
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        log.warning(f"marquage acknowledged KO {task_id[:24]}: {type(e).__name__}: {e}")


def _relay_to_agy(task: sqlite3.Row, token: str) -> None:
    """RELAIS PUR (owner 23/07) : l'exécuteur ne PENSE pas. Il (1) passe la tâche à
    AGY autonome (postal GEMINI), (2) le lance, (3) relève sa réponse, (4) la sert
    à l'émetteur en M2M. L'intelligence reste AGY (son modèle) — JAMAIS de LLM ici."""
    task_id = task["id"]
    body = _extract_message(task["description"] or "") or (task["description"] or "")

    def _fin(ok: bool, result: str) -> None:
        conn = _db(); _mark_done(conn, task_id, _borner(result), ok, workdir=ROOT); conn.close()
        intent = "OK_DONE" if ok else "ERR_TIMEOUT"
        payload = json.dumps({"intent": intent, "status_code": "SUCCESS" if ok else "TIMEOUT",
                              "pointer_ref": f"tasks.db:{task_id}", "detail": result[:180]},
                             ensure_ascii=False)
        try:
            _hub_call("task", {"action": "result", "task_id": task_id, "intent": intent,
                               "result": payload}, token, timeout=30)
        except Exception:  # noqa: BLE001
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 2881, exc_info=True)

    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_postal import post as _post, _conn as _pconn
    except Exception as e:  # noqa: BLE001
        return _fin(False, f"postal indispo: {e}")

    # (1) PASS : déposer la tâche dans l'inbox d'AGY autonome. dedup_key=task_id
    # rend CHAQUE relais unique (sinon 2 tâches au même texte -> dedup postal les
    # fusionne et la corrélation de réponse casse, mesuré 23/07).
    res = _post("TASK_EXECUTOR", "GEMINI", body, dedup_key=f"relay:{task_id}")
    mid = res.get("id")
    if not mid:
        return _fin(False, f"post AGY refuse: {res.get('reason')}")

    # (2) LAUNCH : réveiller l'auto-répondeur AGY (best-effort)
    try:
        _hub_call("nokido_ensure_service", {"service": "NokidoGeminiAutonomous",
                  "desired_state": "running"}, token, timeout=30)
    except Exception:  # noqa: BLE001
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 2902, exc_info=True)

    # (3) COLLECT : relever la réponse d'AGY (in_reply_to=mid, sender GEMINI).
    # Un ACCUSE DE RECEPTION ne termine PAS l'attente : il est journalise, la
    # tache passe en `acknowledged` (visible, distinct de `completed`), et on
    # continue d'attendre le compte rendu jusqu'au meme deadline.
    reply = None
    accuses = 0
    dernier_accuse = ""
    deadline = time.monotonic() + RELAY_TIMEOUT_S
    while time.monotonic() < deadline and not _stop:
        con = _pconn()
        try:
            r = con.execute("SELECT body FROM mail WHERE in_reply_to=? AND upper(sender)='GEMINI' "
                            "ORDER BY ts_queued DESC LIMIT 1", (mid,)).fetchone()
        finally:
            con.close()
        if r and r[0]:
            if _est_accuse_reception(r[0]):
                if r[0] != dernier_accuse:
                    accuses += 1
                    dernier_accuse = r[0]
                    log.info(f"  RELAY {task_id[:24]} -> ACCUSE DE RECEPTION #{accuses} "
                             f"({len(r[0])} chars) — on attend le compte rendu")
                    _marquer_accuse(task_id, r[0])
            else:
                reply = r[0]
                break
        time.sleep(RELAY_POLL_S)

    # (4) SERVE : compte rendu d'AGY -> émetteur. Sans compte rendu, l'echec est
    # NOMME : « a accuse reception sans rendre compte » n'est pas un timeout muet,
    # et c'est ce que le demandeur doit lire pour refaire le travail lui-meme.
    if reply:
        log.info(f"  RELAY {task_id[:24]} -> AGY a rendu compte ({len(reply)} chars)")
        _fin(True, reply)
    elif accuses:
        log.warning(f"  RELAY {task_id[:24]} -> {accuses} accuse(s) de reception, "
                    f"AUCUN compte rendu en {RELAY_TIMEOUT_S}s")
        _fin(False, f"AGY a accuse reception {accuses}x sans jamais rendre compte "
                    f"d'une execution ({RELAY_TIMEOUT_S}s). Derniere reponse : "
                    f"{dernier_accuse[:300]} — VERIFIER L'EFFET AVANT DE CROIRE "
                    f"UN STATUT, puis refaire le travail si rien n'a bouge.")
    else:
        log.warning(f"  RELAY {task_id[:24]} -> AGY sans reponse ({RELAY_TIMEOUT_S}s)")
        _fin(False, f"AGY timeout {RELAY_TIMEOUT_S}s")


def process_task(task: sqlite3.Row, token: str) -> tuple[bool, str]:
    """Traite une tâche. Retourne (ok, result_text)."""
    agent = (task["agent"] or "").upper()
    description = task["description"] or ""
    task_id = task["id"]

    # Chaine providers
    providers = PROVIDER_CHAIN.get(agent, ["groq", "mistral"])
    message = precharger_corps_consigne(_extract_message(description))

    if not message or len(message) < 20:
        return False, f"Message trop court ou non extrait: {description[:100]}"

    log.info(f"Task {task_id[:30]} [{agent}] → essaie {providers[0]} first")

    for provider in providers:
        ok, text = _ask(provider, message, token)
        # Détecter les erreurs déguisées en succès
        _err_patterns = (
            "Please set an Auth",
            "auth method",
            "Unauthenticated",
            "401",
            "ERR",
            "not authenticated",
            "GATE_DENIED",      # ring insuffisant -> faux succes masque (mesure 23/07)
            "gate denied",
            "GATE_",
            "requis",           # "ring 4 <= requis 3"
        )
        if (
            ok
            and text
            and len(text) > 30
            and not any(p.lower() in text.lower() for p in _err_patterns)
        ):
            log.info(f"  → {provider} OK ({len(text)} chars)")
            return True, f"[{provider}] {text}"
        log.warning(f"  → {provider} FAIL: {str(text)[:80]}")
        time.sleep(1)

    return False, f"Tous providers échoué: {providers}"


def _mode_enquete(desc: str) -> dict | None:
    """Reconnaît une description contenant une ligne `mode: enquete` et en extrait les paramètres."""
    if not desc:
        return None
    lignes = desc.splitlines()
    est_enquete = False
    for lig in lignes:
        if lig.strip().lower() == "mode: enquete":
            est_enquete = True
            break
    if not est_enquete:
        return None

    question = ""
    fts: list[str] = []
    sortie = ""

    for lig in lignes:
        s = lig.strip()
        if s.lower().startswith("question:"):
            if not question:
                question = s[len("question:"):].strip()
        elif s.lower().startswith("fts:"):
            val = s[len("fts:"):].strip()
            if val:
                fts.append(val)
        elif s.lower().startswith("source:"):
            val = s[len("source:"):].strip()
            if val:
                fts.append(f"source:{val}")
        elif s.lower().startswith("sortie:"):
            if not sortie:
                sortie = s[len("sortie:"):].strip()

    return {
        "question": question,
        "fts": fts,
        "sortie": sortie,
    }


def _traiter_enquete(task: sqlite3.Row | dict, token: str, params: dict) -> None:
    """Traite une tâche en mode enquête via executer_enquete et clôt la délégation."""
    from forge_enquete_sans_boucle import executer_enquete

    task_id = task["id"]
    court_id = str(task_id)[:8] if str(task_id) else "sans_id"
    sortie = params.get("sortie") or f"sandbox/workspace/enquetes/{court_id}.md"
    question = params.get("question") or ""
    fts = params.get("fts") or []

    try:
        res = executer_enquete(question, fts, [], sortie)
        ok = bool(res.get("ok"))
        if ok:
            sortie_reelle = res.get("sortie") or sortie
            resultat = json.dumps({"intent": "OK_DONE", "pointer_ref": sortie_reelle}, ensure_ascii=False)
            _clore_delegation(task_id, token, True, resultat)
        else:
            motif = res.get("erreur") or "Échec executer_enquete sans détail"
            _clore_delegation(task_id, token, False, str(motif))
    except Exception as e:
        log.error(f"Erreur traitement enquête {task_id[:24]}: {e}", exc_info=True)
        _clore_delegation(task_id, token, False, f"Exception _traiter_enquete : {type(e).__name__}: {e}")


def run_loop(agent_filter: str | None, once: bool) -> None:
    # compteur PARTAGE avec les threads de delegation : sans `global`, le `+= 1` de la boucle le rend local et
    # leve UnboundLocalError a la premiere delegation (mesure 30/10 par le NR, avant tout redemarrage)
    global _delegations_en_vol
    token = _load_token()
    if not token:
        log.error("FORGE_MCP_TOKEN manquant — abort")
        return

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    log.info(f"TaskExecutor démarré | interval={POLL_INTERVAL}s | batch={BATCH_SIZE}")
    if agent_filter:
        log.info(f"  filtre agent: {agent_filter}")
    _cap0, _why0 = _peut_lancer_agy()
    log.info(f"  mode AGENT agy: {'DISPONIBLE' if _cap0 else 'indisponible'} — {_why0}")
    _hb = _hb_file(agent_filter)
    _ident = _identite_executeur(agent_filter)
    _enforce = _claim_enforce()
    try:
        _o = requalifier_orphelines(agent_filter)
        if _o["requalifiees"] or _o["abstenues"]:
            log.warning("[orpheline] demarrage : %d requalifiee(s), %d abstention(s)",
                        len(_o["requalifiees"]), len(_o["abstenues"]))
    except Exception as _e_o:  # noqa: BLE001
        log.warning("[orpheline] requalification INDISPONIBLE (%s: %s)", type(_e_o).__name__, str(_e_o)[:90])
    # Hygiene au DEMARRAGE (30/10) : le garde-orphelins ne passait qu'au debut d'une delegation ; les reliquats de
    # worktree attendaient donc la prochaine tache. Un passage ici, sous le compte de l'executeur (proprietaire).
    if _wt_tache_arme():
        try:
            _wt_orphelins()
        except Exception as _e_w:  # noqa: BLE001
            log.warning("[worktree] garde-orphelins au demarrage INDISPONIBLE (%s)", type(_e_w).__name__)
    try:
        from tools.forge_worktree import reconcilier_orphelins_boucle
        reconcilier_orphelins_boucle()
    except Exception as _e_rec_ini:  # noqa: BLE001
        log.warning("[reconciliateur] balayage au demarrage INDISPONIBLE (%s)", type(_e_rec_ini).__name__)
    log.info(f"  identite de reclamation : sujet={_ident['sub']} prouve={_ident['prouve']} ({_ident['pourquoi']}) "
             f"| mode={'APPLIQUE' if _enforce else 'OBSERVE'}")

    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`). Ce site ecrivait une
    # date ISO NUE — ni JSON (le contrat de `service_loader.ts`), ni pid — et il
    # couvre TROIS organes (`task_executor`, `_worker_code`, `_antigravity`) parce
    # que le nom est construit par `_hb_file`. C'est precisement pour ca qu'aucune
    # analyse statique ne le voyait : le nom du signal n'existe nulle part en clair.
    #
    # POSITION INCHANGEE, a dessein : ce pouls bat en TETE de boucle. La doctrine de
    # `beat_daemon` veut qu'un pouls atteste du TRAVAIL et non de l'existence, mais
    # deplacer le battement change le COMPORTEMENT observe par le superviseur — ce
    # chantier instrumente, il ne redefinit pas ce que le pouls signifie.
    import sys as _sys
    from pathlib import Path as _Path

    _app = str(_Path(__file__).resolve().parent.parent / "app")
    if _app not in _sys.path:
        _sys.path.insert(0, _app)
    from nokido_agent.app.forge_heartbeat import beat_daemon

    _palier_vu = [None]
    while not _stop:
        beat_daemon(_hb.stem, agent=agent_filter or "*", enfants=_pids_enfants())
        _palier = "INCONNU"

        try:
            # Le bail d'abord : une mission dont l'agent a disparu doit revenir au
            # bus AVANT qu'on aille chercher du travail neuf.
            try:
                _rec = reclaim_expired()
                if _rec["reprises"] or _rec["abandonnees"]:
                    log.info("[lease] %d reprise(s), %d abandon(s)",
                             _rec["reprises"], _rec["abandonnees"])
            except Exception as _e_lease:  # noqa: BLE001
                log.warning("[lease] reprise INDISPONIBLE (%s: %s) | consequence: "
                            "une mission dont l'agent meurt reste en vol pour "
                            "toujours — c'est le defaut mesure le 2026-08-14 "
                            "(tache running depuis 22 jours)",
                            type(_e_lease).__name__, str(_e_lease)[:90])
            # 6/11 (owner) & 7/11 (v2) : boucle automatique du reconciliateur de worktree et sauvegardes (coupe par defaut, exclusif)
            try:
                from tools.forge_worktree import reconcilier_orphelins_boucle
                reconcilier_orphelins_boucle()
            except Exception as _e_rec:  # noqa: BLE001
                log.warning(f"[reconciliateur] balayage INDISPONIBLE ({type(_e_rec).__name__}: {str(_e_rec)[:90]})")
            # Palier de pression RAM (owner 24/10) : GENE et au-dela, plus de nouvelle reclamation.
            # 3/11 (owner : « que les delegations soient effectuees par Nokido ») : les taches deposees agent=AUTO
            # recoivent ici leur surface ; chaque executeur route, le garde agent='AUTO' evite le double routage.
            try:
                router_taches_auto()
            except Exception as _e_auto:  # noqa: BLE001
                log.warning(f"[auto] routage INDISPONIBLE ({type(_e_auto).__name__}: {str(_e_auto)[:90]}) -- "
                            f"les taches AUTO attendent")
            _palier = _palier_pression()
            if _palier != _palier_vu[0]:
                log.info(f"[pression] palier RAM {_palier}")
                _palier_vu[0] = _palier
            _retenue = not _reclamation_permise(_palier)
            if _retenue:
                batch = []
            else:
                conn = _db()
                batch = _fetch_batch(conn, agent_filter)
                conn.close()

            if not batch:
                if _retenue:
                    log.info(f"[pression] palier {_palier} : aucune nouvelle reclamation (taches en vol inchangees)")
                else:
                    log.info("Aucune tâche pending — attente")
            else:
                log.info(f"{len(batch)} tâches à traiter")
                for task in batch:
                    if _stop:
                        break

                    # Choix owner 6/11 : une consigne touchant un sujet prive ne part pas vers un agent expose (membrane).
                    from nokido_agent.app.forge_sovereign_membrane import refus_sujet_prive
                    _refus_prive = refus_sujet_prive(task["description"] or "", task["agent"])
                    if _refus_prive:
                        conn_sp = _db()
                        _pris = _reclamer(conn_sp, task["id"], (task["agent"] or "").upper(), _ident, enforce=_enforce)
                        conn_sp.close()
                        if _pris:
                            conn_sp = _db()
                            _mark_done(conn_sp, task["id"], _refus_prive, False)
                            conn_sp.close()
                            log.warning(f"  {task['id'][:24]} : {_refus_prive}")
                        continue

                    _params_enquete = _mode_enquete(task["description"] or "")
                    if _params_enquete is not None:
                        conn_eq = _db()
                        _pris = _reclamer(conn_eq, task["id"], (task["agent"] or "").upper(), _ident, enforce=_enforce)
                        conn_eq.close()
                        if not _pris:
                            continue
                        _traiter_enquete(task, token, _params_enquete)
                        time.sleep(2)
                        continue

                    _agent_dedie = (task["agent"] or "").upper()
                    _deleguer = _delegation_pour(_agent_dedie)
                    if _deleguer:
                        # Seules les instances DEDIEES (--agent CODEX / MISTRAL) arrivent ici : le generique les
                        # exclut (plancher interactif). Plafond et capacite se jugent AVANT de prendre la tache :
                        # refusee, elle reste pending (demain, ou apres le geste owner) -- jamais brulee.
                        if _agent_dedie == CODEX_AGENT and _quota_codex() >= CODEX_QUOTA_JOUR:
                            _jour = time.strftime("%Y-%m-%d")
                            if _quota_codex_dit["jour"] != _jour:
                                log.warning(f"  BUDGET_EXCEEDED : quota Codex du jour atteint ({_quota_codex()}/"
                                            f"{CODEX_QUOTA_JOUR}) -- les taches CODEX restent pending pour demain "
                                            f"(quota non paye, owner 15/10)")
                                _quota_codex_dit["jour"] = _jour
                            if _reaffecter(task, f"quota Codex du jour atteint ({_quota_codex()}/{CODEX_QUOTA_JOUR})",
                                           ordre=_ordre_repli_pour(task)):  # code : jamais AGY (18/10)
                                continue
                            break
                        # 3/11 (OmniRoute) : PRE-VOL -- une surface marquee epuisee (registre partage) n'est pas essayee :
                        # la tache part a la suivante AVANT de bruler une tentative.
                        _ind = surface_est_indisponible(_agent_dedie)
                        if _ind:
                            if _reaffecter(task, f"{_agent_dedie} INDISPONIBLE ({_ind})", ordre=_ordre_repli_pour(task)):
                                continue
                            log.warning(f"  {task['id'][:24]} : {_agent_dedie} INDISPONIBLE ({_ind}) -- laissee pending")
                            break
                        _cap, _pq = _capacite_pour(_agent_dedie)()
                        if not _cap:
                            if _reaffecter(task, f"{_agent_dedie} autonome INDISPONIBLE ({_pq})",
                                           ordre=_ordre_repli_pour(task)):  # code : jamais AGY (18/10)
                                continue
                            log.warning(f"  {task['id'][:24]} : {_agent_dedie} autonome INDISPONIBLE ({_pq}) -- laissee pending")
                            break
                        _permis_essai, _raison_essai = autoriser_essai_half_open(_agent_dedie)
                        if not _permis_essai and _essai_reserve_a_cette_tache(task, _agent_dedie):
                            _permis_essai = True  # l'essai a ete consomme pour cette tache par _reaffecter
                        if not _permis_essai:
                            if _reaffecter(task, f"{_agent_dedie} coupe-circuit ({_raison_essai})",
                                           ordre=_ordre_repli_pour(task)):
                                continue
                            log.warning(f"  {task['id'][:24]} : {_agent_dedie} coupe-circuit ({_raison_essai}) -- laissee pending")
                            break
                        with _lock_delegations:
                            if _delegations_en_vol >= LAFORGE_TASK_PARALLEL:
                                log.info(f"  delegations en vol ({_delegations_en_vol}/{LAFORGE_TASK_PARALLEL}) : limite atteinte -- laissee pending")
                                break
                            _delegations_en_vol += 1

                        conn2 = _db()
                        _pris = _reclamer(conn2, task["id"], _agent_dedie, _ident, enforce=_enforce)
                        conn2.close()
                        if not _pris:
                            with _lock_delegations:
                                _delegations_en_vol -= 1
                            continue

                        def _executer_delegation_dediee(_ag=_agent_dedie, _t=task, _tok=token, _del=_deleguer):
                            global _delegations_en_vol
                            try:
                                _preparer_worktree(_ag, _t["id"])
                                _avec_worktree_tache(_ag, _t, _tok, lambda: _del(_t, _tok))
                            except Exception as _de:  # noqa: BLE001
                                log.error(f"delegation {_ag} KO {_t['id'][:24]}: {_de}")
                                _clore_delegation(_t["id"], _tok, False,
                                                  f"delegation {_ag} en exception : {type(_de).__name__}: {_de}")
                            finally:
                                with _lock_delegations:
                                    _delegations_en_vol -= 1

                        _pool_delegations.submit(_executer_delegation_dediee)
                        time.sleep(2)
                        continue
                    if (task["agent"] or "").upper() in _AGY_DELEGATE_AGENTS:
                        # DEUX chemins, et le choix se fait sur une CAPACITE MESUREE.
                        # (a) _delegate_to_agy : agy en mode AGENT — il EXECUTE
                        #     (outils, editions, hub gouverne) et rend un rapport.
                        #     Exige l'OAuth agy du profil owner, donc runAs=interactive.
                        # (b) _relay_to_agy : reste le repli. Il poste au postal, ou
                        #     l'auto-repondeur REPOND sans executer — d'ou la fausse
                        #     completion mesuree le 31-07. Depuis, un accuse de
                        #     reception ne clot plus la tache, mais un repli reste un
                        #     repli : on le journalise avec SA RAISON, pour qu'un
                        #     lecteur sache pourquoi la tache n'a pas ete executee.
                        _cap, _pourquoi = _peut_lancer_agy()
                        _indisp = _executeur_suspendu("ANTIGRAVITY")
                        if _cap and not _indisp:
                            with _lock_delegations:
                                if _delegations_en_vol >= LAFORGE_TASK_PARALLEL:
                                    log.info(f"  delegations en vol ({_delegations_en_vol}/{LAFORGE_TASK_PARALLEL}) : limite atteinte -- laissee pending")
                                    break
                                _delegations_en_vol += 1

                            conn2 = _db()
                            _pris = _reclamer(conn2, task["id"], (task["agent"] or "").upper(), _ident, enforce=_enforce)
                            conn2.close()
                            if not _pris:
                                with _lock_delegations:
                                    _delegations_en_vol -= 1
                                continue

                            def _executer_delegation_agy(_t=task, _tok=token):
                                global _delegations_en_vol
                                try:
                                    _preparer_worktree("ANTIGRAVITY", _t["id"])
                                    _avec_worktree_tache("ANTIGRAVITY", _t, _tok,
                                                         lambda: _delegate_to_agy(_t, _tok))
                                except Exception as _pe:  # noqa: BLE001
                                    log.error(f"delegation KO {_t['id'][:24]}: {_pe}")
                                finally:
                                    with _lock_delegations:
                                        _delegations_en_vol -= 1

                            _pool_delegations.submit(_executer_delegation_agy)
                            time.sleep(2)
                            continue
                        elif _reaffecter(task, f"mode AGENT agy indisponible ({_indisp or _pourquoi})"):
                            pass
                        else:
                            conn2 = _db()
                            _pris = _reclamer(conn2, task["id"], (task["agent"] or "").upper(), _ident, enforce=_enforce)
                            conn2.close()
                            if not _pris:
                                continue
                            log.warning(
                                f"  {task['id'][:24]} : mode AGENT indisponible "
                                f"({_pourquoi}) -> repli RELAIS (repond, n'execute pas)")
                            try:
                                _relay_to_agy(task, token)
                            except Exception as _pe:  # noqa: BLE001
                                log.error(f"delegation KO {task['id'][:24]}: {_pe}")
                            time.sleep(2)
                            continue
                        continue

                    ok, result = process_task(task, token)

                    conn3 = _db()
                    _mark_done(conn3, task["id"], result, ok, workdir=ROOT)
                    conn3.close()

                    try:  # retour M2M au demandeur (chainon manquant 2026-07-23)
                        _emit_m2m_result(task["id"], ok, token)
                    except Exception as _me:  # noqa: BLE001
                        log.warning(f"M2M emit exc: {_me}")

                    status_str = "✓" if ok else "✗"
                    log.info(f"  {status_str} {task['id'][:30]} → {result[:80]}")
                    time.sleep(2)  # rate-limit providers

        except Exception as e:
            log.error(f"Boucle erreur: {e}", exc_info=True)

        if once:
            break
        # Sieste INTERRUPTIBLE : SIGTERM (ensure_service stopped) vu en <=2s au lieu
        # de POLL_INTERVAL (sinon l'instance lingère 60s et gobe une tâche = "race"
        # stale mesurée 23/07). Fin des instances stale qui survivent au stop.
        _slept = 0.0
        _etat_reveil = {"empreinte": _empreinte_db(), "pending": _taches_pending()}
        while not _stop and _slept < _intervalle_boucle(POLL_INTERVAL, _palier):
            time.sleep(2)
            _slept += 2
            if _reveil_tache_deposee(_etat_reveil):
                log.info("reveil : tache deposee pendant la sieste")
                break

    try:
        _pool_delegations.shutdown(wait=True)
    except Exception as e:
        log.warning(f"Arrêt du pool de délégations: {e}")

    log.info("TaskExecutor arrêté")
    try:
        _hb.unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"Impossible de supprimer le heartbeat: {e}")


def _sans_fenetre_par_defaut() -> bool:
    """INTERRUPTEUR GLOBAL (owner 31/10 « c'est quoi toutes ces fenetres que tu fais poper ? ») : l'executeur tourne SANS
    console (superviseur -> lanceur -> executeur) ; chaque sous-processus console (git, cmd, opencode, pytest) ouvrait
    donc SA fenetre -- une seule ligne sur ~30 portait CREATE_NO_WINDOW. Sous Windows, tout Popen sans creationflags
    explicite recoit CREATE_NO_WINDOW (sorties toujours capturees) ; un drapeau explicite est respecte ;
    NOKIDO_EXECUTEUR_FENETRES=1 rend le comportement d'avant. Rend True si l'enveloppe vient d'etre posee.
    NR tests/nr/test_executeur_sans_fenetre_nr.py."""
    import subprocess as _s
    drapeau = getattr(_s, "CREATE_NO_WINDOW", 0)
    if not drapeau or os.environ.get("NOKIDO_EXECUTEUR_FENETRES") == "1" or getattr(_s.Popen, "_nokido_sans_fenetre", False):
        return False
    origine = _s.Popen.__init__

    def __init__(self, *a, **k):
        if not k.get("creationflags"):
            k["creationflags"] = drapeau
        origine(self, *a, **k)

    _s.Popen.__init__ = __init__
    _s.Popen._nokido_sans_fenetre = True
    return True


def main() -> None:
    _sans_fenetre_par_defaut()
    parser = argparse.ArgumentParser(description="Nokido Task Executor Daemon")
    parser.add_argument("--once", action="store_true", help="Traiter 1 batch puis exit")
    parser.add_argument(
        "--agent", type=str, default=None, help="Filtrer par agent (ex: GEMINI, COHERE)"
    )
    args = parser.parse_args()
    run_loop(agent_filter=args.agent, once=args.once)


if __name__ == "__main__":
    main()
