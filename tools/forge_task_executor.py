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

ROOT = Path(__file__).resolve().parent.parent
(ROOT / "logs").mkdir(exist_ok=True)

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
POLL_INTERVAL = int(os.environ.get("TASK_EXEC_POLL_INTERVAL", "60"))
BATCH_SIZE = int(os.environ.get("TASK_EXEC_BATCH", "5"))

HUB_URL = "http://127.0.0.1:8766"

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

    # Fallback : la description COMPLETE. La coupe a 3000 caracteres etait MUETTE : une demande de
    # travail longue arrivait tronquee a agy sans que personne le sache (mesure 2026-10-14, reparation
    # du M2M autonome). La seule borne reelle est l'argv d'agy (30000, appliquee par _delegate_to_agy) ;
    # au-dela, on le DIT.
    if len(description) > 30000:
        log.warning("description de %d caracteres : agy n'en recevra que 30000 (borne argv)",
                    len(description))
    return description[:30000]


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
                      ("checkpoint", "TEXT DEFAULT '{}'"), ("progress_at", "TEXT")):
        if nom not in cols:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {nom} {decl}")
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

    def _battre() -> None:
        # Bail de MISSION : la tache reste `en vol`, `reclaim_expired` ne la reprend pas.
        try:
            touch_progress(task_id)
        except Exception as e:  # noqa: BLE001 -- battement best-effort, jamais bloquant
            log.warning(f"  battement KO pour {str(task_id)[:24]} ({type(e).__name__}): {e}")
        # Pouls de l'EXECUTEUR : le superviseur lit `travail_en_cours` et s'abstient de relancer.
        try:
            beat_daemon(hb_nom, agent=agent, travail_en_cours=True,
                        travail_depuis_s=round(time.time() - t0, 1), tache=task_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"  pouls de delegation KO pour {str(task_id)[:24]} ({type(e).__name__}): {e}")

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
    try:
        yield
    finally:
        stop.set()
        fil.join(timeout=max(1.0, float(_PROGRES_TOUTES_S)))
        try:
            beat_daemon(hb_nom, agent=agent, travail_en_cours=False, tache=task_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"  pouls de fin de delegation KO pour {str(task_id)[:24]} ({type(e).__name__}): {e}")


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


def _executeur_suspendu(agent: str) -> str | None:
    """Le motif de suspension de `agent`, ou None s'il n'est pas suspendu.

    Une suspension DECIDEE se DECLARE au registre sous `suspendu: {depuis, motif}`
    et le repli la LIT. Une decision ecrite au tableau noir que personne ne lit
    n'est pas une decision (mesure 17/10 : MISTRAL suspendu au SSoT, 0 livraison,
    mais son executeur battait et le repli lui a passe des taches -> 2 echecs)."""
    nom = (agent or "").upper()
    if not nom:
        return None
    spec = (_lire_registre().get("agents") or {}).get(nom)
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


def _mark_running(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute(
        "UPDATE tasks SET status='running', updated_at=? WHERE id=?",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), task_id),
    )
    conn.commit()
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


def _identite_executeur(agent_filter: str | None) -> dict:
    """Qui reclame ? `sub` = l'agent dont cette instance porte la file, `act` = le process executeur qui agit pour lui.
    La PREUVE (jeton de l'instance verifie par le hub, a la maniere d'une introspection RFC 7662) n'est pas encore
    cablee : `prouve` vaut False et le DIT -- jamais une identite tenue pour prouvee sur le seul drapeau --agent."""
    ident = {"sub": (agent_filter or "TASK_EXECUTOR").upper(), "act": "TASK_EXECUTOR", "prouve": False,
             "pourquoi": "sujet DECLARE par --agent, preuve par jeton d'instance verifie au hub non cablee"}
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
    cur = conn.execute(
        "UPDATE tasks SET status='running', updated_at=? WHERE id=? AND status='pending' AND upper(agent)=?",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), task_id, (agent_tache or "").upper()))
    conn.commit()
    if cur.rowcount != 1:
        log.info(f"  [claim] {str(task_id)[:24]} deja reclamee ou reaffectee : un autre executeur l'a prise")
        return False
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


def _fichiers_non_livres(*textes: str) -> list:
    """Parmi les chemins CITES par la tache, lesquels ne sont pas dans le depot ?

    Rend une liste de (chemin, etat) ou etat vaut 'modifie' ou 'non suivi'. Une
    liste vide signifie soit « tout est livre », soit « la tache ne nommait aucun
    fichier » — les deux se lisent pareil ici, et c'est voulu : on ne CRIE que sur
    une preuve, jamais sur une absence d'information.
    """
    cites = set()
    for t in textes:
        if t:
            cites.update(_RE_CHEMIN.findall(t.replace("\\", "/")))
    if not cites:
        return []
    try:
        import subprocess as _sp_git  # module-level absent ici : import local, comme ailleurs

        r = _sp_git.run(
            ["git", "-c", "safe.directory=*", "-C", str(ROOT), "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if r.returncode != 0:
            log.warning(f"[livraison] git status rc={r.returncode} — verification IMPOSSIBLE")
            return []
    except Exception as e:  # noqa: BLE001
        # Troisieme etat : on ne peut PAS voir. On le dit, on n'affirme rien.
        log.warning(f"[livraison] git injoignable ({type(e).__name__}) — verification impossible")
        return []
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


def _mark_done(conn: sqlite3.Connection, task_id: str, result: str, ok: bool) -> None:
    status = "completed" if ok else "failed"
    if ok:
        attente = _fichiers_non_livres(result)
        if attente:
            detail = ", ".join(f"{c} ({e})" for c, e in attente)
            log.warning(f"  [LIVRAISON INCOMPLETE] {task_id[:24]} se declare reussie mais "
                        f"{len(attente)} fichier(s) cite(s) ne sont PAS dans le depot : {detail}")
            result = (f"[LIVRAISON INCOMPLETE — {len(attente)} fichier(s) hors depot : "
                      f"{detail}] {result}")
    conn.execute(
        "UPDATE tasks SET status=?, result=?, updated_at=? WHERE id=?",
        (status, _borner(result), time.strftime("%Y-%m-%dT%H:%M:%S"), task_id),
    )
    conn.commit()
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
    resp = _hub_call("blackboard_read_zone", {"zone_name": zone}, token, timeout=30)
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
    conn.execute("UPDATE tasks SET status='awaiting_approval', result=?, updated_at=? WHERE id=?",
                 (_borner(note), time.strftime("%Y-%m-%dT%H:%M:%S"), task_id))
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
    conf = _os.path.join(home, "AppData", "Local", "agy")
    try:
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


def _workdir_agy() -> str:
    """Repertoire de travail d'AGY : LAFORGE_AGY_WORKDIR > son worktree dedie > racine partagee (DIT).

    2026-10-01 : l'owner a recu deux fois des invites d'approbation venant d'AGY. Cause etablie
    (reponse d'AGY + ce code) : AGY tourne en `--sandbox` confine a `--add-dir <workdir>` =
    la racine PARTAGEE, alors que la mission lui demandait son worktree
    (nokido_worktrees/antigravity) -- hors de son bac a sable, chaque commande exigeait un
    « BypassSandbox » que l'owner devait approuver. Le worktree dedie est aussi la convention
    du depot (RULES_SHARED : « le worktree protege la MESURE »)."""
    import os as _os
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
            r = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "rev-list", "--count", "--first-parent",
                         "--no-merges", plage, "--"], capture_output=True, text=True,
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


def _non_livre(effet: str, reponse: str) -> str | None:
    """Motif « NON LIVRE » si la delegation n'a produit AUCUN commit propre mais laisse du travail non committe,
    sans pointer d'artefact. None sinon.

    2026-10-13 : AGY a fusionne alpha, modifie forge_session_context.py, puis s'est arrete sur 5 fichiers non
    commites ; l'enveloppe du CLI disait SUCCESS et le drain l'a relaye. Du travail non committe dans un worktree
    n'est ni relisible par le hub (ACL) ni fusionnable : DECLARE n'est pas ACHIEVED. Une tache de rapport qui
    pointe son artefact (`pointer_ref`) est jugee par `_artefact_declare_absent`, pas ici."""
    m = re.search(r"commits produits : (\d+) \([^)]*\) ; fichiers non commites : (\d+)", effet or "")
    if not m or m.group(1) != "0" or int(m.group(2)) == 0 or '"pointer_ref"' in (reponse or ""):
        return None
    return "[NON LIVRE] aucun commit propre, %s fichier(s) non committe(s)" % m.group(2)


def _rien_produit(effet: str, reponse: str) -> str | None:
    """« [RIEN PRODUIT] » si la delegation n'a laisse ni commit ni fichier et ne pointe aucun artefact. None sinon.

    2026-10-20 (job_aa2229e3) : un diff rendu EN TEXTE, tronque a 8000 caracteres avec sa ligne finale, est sorti
    done / OK_DONE / SUCCESS -- `_non_livre` ne mord que s'il reste des fichiers non committes. Un texte sans effet
    n'est pas une livraison. Une reponse qui pointe son artefact (`pointer_ref`) reste jugee par les gardes d'artefact.
    Sans commit produit, un pointeur de commit ne designe pas la livraison (20/10, GREEN livre par MISTRAL)."""
    m = re.search(r"commits produits : (\d+) \([^)]*\) ; fichiers non commites : (\d+)", effet or "")
    refs = re.findall(r'"pointer_ref"\s*:\s*"([^"]+)"', reponse or "")
    if not m or m.group(1) != "0" or m.group(2) != "0" or (
            refs and not re.match(r"^(commit:|\S+@[0-9a-fA-F]{7,40}\b)", refs[-1].strip())):
        return None
    return "[RIEN PRODUIT] ni commit ni fichier, et aucun artefact pointe : une reponse sans effet n'est pas livree"


def _intention_finale(texte: str) -> str | None:
    """Dernier intent M2M ecrit dans un texte (`"intent": "X"`), quel qu'il soit ; None : l'agent n'a rien conclu.
    Parseur UNIQUE : _intent_rendu en est la vue « pas fait », la relance OpenCode la vue « rien conclu »."""
    trouves = re.findall(r'"intent"\s*:\s*"([A-Z_]+)"', texte or "")
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


def _artefact_declare_absent(reponse: str, workdir: str) -> str | None:
    """L'artefact que l'agent DECLARE (dernier `"pointer_ref"`) et qui n'existe PAS ; None sinon.

    2026-10-01 : AGY a rendu `{"intent": "OK_DONE", "pointer_ref": "sandbox/swarm/reponse_agy_adddir_
    2026-10-01.md"}` -- fichier absent du worktree comme de l'arbre partage, aucun fichier ecrit (l'effet
    observe le montrait), et la delegation l'a transmis en SUCCESS. Seuls se jugent un chemin de fichier
    et un `<branche>@<sha>` ; un pointeur d'un autre type (tasks.db:, URL, cle de blackboard) n'est pas
    juge, et une verification ILLISIBLE n'accuse pas (None) : une sonde muette ne fabrique pas d'echec."""
    import subprocess as _sp
    refs = re.findall(r'"pointer_ref"\s*:\s*"([^"]+)"', reponse or "")
    if not refs:
        return None
    ref = refs[-1].strip()
    if not ref or ref.startswith("tasks.db:") or "://" in ref:
        return None
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
    p = Path(ref)
    candidats = [p] if p.is_absolute() else [Path(workdir) / p, ROOT / p]
    try:
        if any(c.exists() for c in candidats):
            return None
    except OSError:  # illisible : n'accuse pas
        return None
    return "fichier declare absent : %s" % ref


def _artefact_non_produit(reponse: str, workdir: str, avant) -> str | None:
    """Motif de refus si le pointer_ref pointe vers un fichier qui existait deja avant la tache,
    sans commit ni modification. None sinon.
    Revue adverse Codex (17/10, R3) : sans commit, pointer un fichier preexistant passait."""
    import subprocess as _sp
    refs = re.findall(r'"pointer_ref"\s*:\s*"([^"]+)"', reponse or "")
    if not refs:
        return None
    ref = refs[-1].strip()
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


def _clore_delegation(task_id: str, token: str, ok: bool, detail: str, intent: str | None = None) -> None:
    """Clot une tache deleguee (AGY, CODEX) : statut en base + resultat M2M a l'emetteur. Extrait du `_fin` de
    `_delegate_to_agy` le 16/10 pour que les deux voies closent de la MEME facon. Le detail est CAVIARDE avant
    d'etre persiste ou emis (RED7 : une erreur peut citer un en-tete Authorization)."""
    detail = _caviarder(detail)
    conn = _db(); _mark_done(conn, task_id, _borner(detail), ok); conn.close()
    intent = intent or ("OK_DONE" if ok else "ERR_INTERNAL")
    try:
        _hub_call("task", {"action": "result", "task_id": task_id, "intent": intent,
                  "result": json.dumps({"intent": intent, "status_code": "SUCCESS" if ok else (
                      "NEEDS_HUMAN" if intent == "NEED_HUMAN_APPROVAL" else "FAILURE"),
                  "pointer_ref": f"tasks.db:{task_id}", "detail": detail[:220]}, ensure_ascii=False)},
                  token, timeout=30)
    except Exception as e:  # noqa: BLE001
        # La tache est close EN BASE ; c'est le compte rendu a l'emetteur qui manque -- il doit le savoir.
        log.warning(f"  resultat M2M NON emis pour {str(task_id)[:24]} ({type(e).__name__}: {str(e)[:80]}) "
                    f"-- tache close en base, emetteur non prevenu")


_CONFIG_AGENT = (".vibe/", ".agy/", ".codex/", ".opencode/", "AGENTS.md", "GEMINI.md")


def _tests_autorises(desc: str) -> list:
    """Chemins de tests que la TACHE autorise a modifier : ligne « tests_autorises: a, b » de sa description."""
    m = re.search(r"^\s*tests_autorises\s*:\s*(.+)$", str(desc or ""), re.M | re.I)
    return [c.strip().replace("\\", "/") for c in m.group(1).split(",") if c.strip()] if m else []


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

    r = _g("rev-list", "--first-parent", "--no-merges", "%s..%s" % (h_av, h_ap), "--")
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


def _juger_livraison(ok: bool, detail: str, workdir: str, avant, autorises=None) -> tuple:
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
    if (not rendu and not absent and not non_produit and '"pointer_ref"' not in str(detail)
            and _est_accuse_reception(str(detail))):
        ok = False
        effet = "%s ; [ACCUSE DE RECEPTION] promesse sans compte rendu" % effet
    nl = None if (rendu or absent or non_produit) else _non_livre(effet, str(detail))
    if nl:
        ok = False      # du travail laisse non committe n'est ni relisible ni fusionnable (2026-10-13)
        effet = "%s ; %s" % (effet, nl)
    if not rendu and "REFUSE par le scorecard" in str(detail):
        ok = False      # 20/10 (job_2a6a27b3) : le pointer_ref exemptait _non_livre ; un refus du scorecard est NOMME
        effet = "%s ; [SCORECARD REFUSE] commit de l'executeur refuse, travail laisse non livre" % effet
    rien = None if (rendu or absent or non_produit or nl) else _rien_produit(effet, str(detail))
    if rien:
        ok = False      # ni commit ni fichier ni artefact pointe : DECLARE n'est pas ACHIEVED (2026-10-20)
        effet = "%s ; %s" % (effet, rien)
    # R3 (17/10) : le CONTENU des commits, pas leur nombre -- livraison vide, tests existants touches.
    contenu = None if (rendu or absent or nl or non_produit) else _contenu_livre(workdir, avant, autorises)
    if contenu:
        ok = False
        effet = "%s ; %s" % (effet, contenu)
    elif autorises and not (rendu or absent or nl or non_produit):
        effet = "%s ; [tests modifies AUTORISES par la tache] %s" % (effet, ", ".join(autorises))
    return bool(ok), effet, rendu


# Verdict AUTOMATIQUE d'une delegation ratee (owner 18/10 : « le corps doit avoir la notion de recompense par
# resultat »). Liste BLANCHE : seul un vide PROUVE par le juge de livraison est VIDE ; une panne d'infrastructure n'est
# pas la faute du repondeur (19/10 : 429 et sessions muettes chez des modeles qui livraient la veille) -> INCONNU.
_RE_PANNE_INFRA = re.compile(r"harness MUET|erreur ACP|TimeoutError|timeout en attente|\b429\b|\b402\b|Too Many "
                             r"Requests|Payment Required|session occupee|jeton absent", re.I)
# [RIEN PRODUIT] (20/10) passe AVANT le garde [AUCUN EFFET] des voies Codex / Vibe / OpenCode : absent d'ici, il
# rabattait une livraison vide de VIDE a INCONNU.
_MARQUES_VIDE = ("[AUCUN EFFET]", "[RIEN PRODUIT]", "[LIVRAISON VIDE]", "[ACCUSE DE RECEPTION]", "[artefact ABSENT]")


def verdict_automatique(ok: bool, effet: str, detail: str, rendu) -> str | None:
    """VIDE | REJETEE | INCONNU pour un echec ; None pour une reussite (INTEGREE/PARTIELLE exigent une relecture) ou
    un rejet du scorecard deja consigne par `_committer_pour_agent`."""
    if ok:
        return None
    effet, detail = str(effet), str(detail)
    if "REFUSE par le scorecard" in detail:
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
        refus = ", ".join(str(a.get("action") or a) if isinstance(a, dict) else str(a)
                          for a in (d.get("denied_actions") or []))
        return False, "[REPONSE VIDE] agy SUCCESS sans reponse%s" % (" ; actions refusees par le bac : " + refus
                                                                     if refus else "")
    return False, reponse or str(d.get("error") or "")[:400] or str(raw)[:400]


def _delegate_to_agy(task: sqlite3.Row, token: str) -> None:
    """DÉLÉGATION-EXÉCUTION (owner : "déléguer des taches à agy") : lance AGY en
    mode AGENT (agy --print <task> --add-dir <workdir> --dangerously-skip-permissions
    --output-format json) -> AGY EXÉCUTE (tools, edits, hub gouverné) et renvoie
    l'enveloppe {status, response, usage}. Le relais sert le résultat à l'émetteur.
    Pattern delegate-agy : AGY bosse, le diff est relu (pas d'auto-merge)."""
    import subprocess as _sp
    import os as _os
    task_id = task["id"]
    desc = _extract_message(task["description"] or "") or (task["description"] or "")

    def _fin(ok: bool, detail: str, intent: str | None = None) -> None:
        _clore_delegation(task_id, token, ok, detail, intent)

    agy_bin = _os.environ.get("LAFORGE_AGY_BIN", r"%USERPROFILE%\AppData\Local\agy\bin\agy.exe")
    if not _os.path.exists(agy_bin):
        return _fin(False, f"agy introuvable: {agy_bin}")
    workdir = _workdir_agy()
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
    _eff = _os.environ.get("LAFORGE_AGY_EFFORT", "high")
    if _eff not in ("low", "high"):
        _eff = "high"
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
    cmd = [agy_bin, "--print", desc[:29000] + _CONSIGNE_SANS_COMMANDE_AGY, "--add-dir", workdir,
           *_agy_permission_args(), "--output-format", "json",
           "--effort", _eff]
    if _continu:
        cmd.append("--continue")
        log.info(f"  DELEGATE {task_id[:24]} -> LOT_CONTINU : session reprise (--continue)")
    log.info(f"  DELEGATE {task_id[:24]} -> AGY agent (add-dir={workdir})")
    _avant = _etat_git(workdir)
    _sales_avant = _chemins_status(workdir) or frozenset()
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
    raw = (r.stdout or "").strip() or (r.stderr or "").strip()
    ok, detail = lire_sortie_agy(raw)
    if ok:
        # 16/10 : sous --sandbox AGY ne lance aucune commande (RunCommand hors bac refuse) ; l'executeur committe
        # ce que la tache a PRODUIT, jamais ce qui etait deja sale avant elle.
        _note = _committer_pour_agent(workdir, task_id, str(detail), "agy", exclus=_sales_avant)
        if _note:
            detail = "%s\n[executeur] %s" % (detail, _note)
    # Jugement COMMUN (16/10) : intent rendu, artefact absent, accuse de reception (le repli _relay_to_agy
    # refusait deja de clore sur « je vais chercher... » ; `agy --print` ne rend qu'UNE reponse), non livre.
    ok, effet, rendu = _juger_livraison(bool(ok), str(detail), workdir, _avant, autorises=_tests_autorises(desc))
    log.info(f"  DELEGATE {task_id[:24]} -> AGY {'OK' if ok else 'KO'}{(' ' + rendu) if rendu else ''} "
             f"({len(str(detail))} chars) {effet}")
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


def _workdir_codex() -> Path:
    """Worktree DEDIE de Codex (creation = geste OWNER, branche agent/codex). PAS de repli sur la racine partagee,
    a la difference d'AGY : un agent qui ecrit hors de son claim empeche tout verdict de CI de se rattacher a un
    commit (RULES_SHARED, 2026-09-07)."""
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
    effort = _EFFORT_CODEX_PAR_TAILLE.get(str(taille or "").upper())
    if effort:
        args += ["-c", 'model_reasoning_effort="%s"' % effort]
    return args + ["-"]


_CONSIGNE_GIT_CODEX = (
    "\n\n[Executeur Nokido] Ne lance ni `git add` ni `git commit` : ton bac a sable tient .git en lecture seule et "
    "l'executeur committe lui-meme les fichiers que tu as modifies dans ce worktree. Termine par UNE ligne JSON "
    '{"intent":"OK_DONE"|"ERR_INTERNAL","pointer_ref":"...","commit_message":"<type(portee): resume>"}.')


_CONSIGNE_SANS_COMMANDE_AGY = (
    "\n\n[Executeur Nokido] Ton bac a sable refuse toute commande hors bac (RunCommand) : ne lance AUCUNE commande "
    "(ni git, ni pytest, ni script). Ecris seulement les fichiers demandes dans ce worktree ; l'executeur committe "
    "ce que tu as produit et Claude relance les tests a la relecture. Termine par UNE ligne JSON "
    '{"intent":"OK_DONE"|"ERR_INTERNAL","pointer_ref":"...","commit_message":"<type(portee): resume>"}.')


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


def _committer_pour_agent(wt: str, task_id, detail: str, agent: str, exclus=frozenset()) -> str | None:
    """Commit par l'executeur (session owner) de ce que l'agent a ECRIT dans son worktree -- meme resultat que les
    autres CLI (des commits sur agent/<nom>), sans retirer le bac a sable. Fichiers LISTES par `git status`, jamais
    `add -A`, et JAMAIS ceux deja sales AVANT la tache (`exclus`, 16/10 : le worktree d'AGY portait 5 dossiers sans
    rapport) ; hooks du depot normaux (scan de secrets, git-gate). Rien n'est committe si l'agent dit lui-meme
    « pas fait ». Rend une note pour l'effet observe, ou None s'il n'y a rien a committer."""
    import subprocess as _sp
    if _intent_rendu(str(detail)):
        return None
    g = ["git", "-c", "safe.directory=*", "-C", str(wt)]
    tous = _chemins_status(wt)
    if tous is None:
        return "commit executeur IMPOSSIBLE : status illisible"
    # Le marqueur d'identite du worktree (`.nokido.agent`) n'est JAMAIS une livraison : il partait dans les commits
    # (17/10 : 4 fois chez GPTOSS, 1 chez GLM) et le garde du pre-commit (demande owner R7) le bloque.
    chemins = sorted(p for p in tous - frozenset(exclus or ()) if Path(p).name != ".nokido.agent")
    if not chemins:
        return None
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
    try:
        a = _sp.run(g + ["add", "--"] + chemins, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=60, env=_env_git())
        c = _sp.run(g + ["commit", "-m", msg, "-m", corps], capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=180, env=_env_git()) if a.returncode == 0 else a
    except Exception as e:  # noqa: BLE001
        return "commit executeur ECHOUE (%s)" % type(e).__name__
    if c.returncode != 0:
        return "commit executeur REFUSE rc=%s : %s" % (c.returncode, (c.stderr or c.stdout)[-400:])
    return "commit executeur de %d fichier(s) : %s" % (len(chemins), msg)


def _delegate_to_codex(task, token: str) -> None:
    """Codex execute dans SON worktree via le harness ; le verdict porte sur ce qui est LIVRE (commits, artefact
    verifie), jamais sur sa prose : le harness rend la sortie de codex, pas un statut de reussite."""
    task_id = task["id"]
    desc = _extract_message(task["description"] or "") or (task["description"] or "")
    wt = str(_workdir_codex())
    args = (json.loads(os.environ["LAFORGE_CODEX_EXEC_ARGS"]) if os.environ.get("LAFORGE_CODEX_EXEC_ARGS")
            else _args_codex(Path(wt), _taille_tache(desc)))
    jid = "codex_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))[:80]
    job = _HARNESS_JOBS / (jid + ".json")
    _avant = _etat_git(wt)
    _sales_avant = _chemins_status(wt) or frozenset()   # 18/10 : 90bc00bee balayait les restes d'autres taches
    _purger_marqueurs_harness(job)
    job.write_text(json.dumps({"agent": "codex", "args": args, "send": desc[:29000] + _CONSIGNE_GIT_CODEX, "eof": True,
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
    ok, effet, rendu = _juger_livraison(ok, detail, wt, _avant, autorises=_tests_autorises(desc))
    m = re.search(r"commits produits\s*:\s*(\d+)", effet)
    if ok and not rendu and (m is None or int(m.group(1)) == 0) and '"pointer_ref"' not in detail:
        ok = False      # rien de livre ni de pointe : le harness a tourne, Codex n'a rien produit de verifiable
        effet = "%s ; [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable" % effet
    log.info(f"  DELEGATE {str(task_id)[:24]} -> CODEX {'OK' if ok else 'KO'} {effet}")
    _consigner_verdict_auto("CODEX", task_id, ok, effet, detail, rendu)
    motif = _motif_reaffectation_apres(ok, effet)
    if motif and _reaffecter(dict(task), motif, ordre=_palier_executeurs("M", ecrit=True)):
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
    '{"intent":"OK_DONE"|"ERR_INTERNAL","pointer_ref":"...","commit_message":"<type(portee): resume>"}.')


def _workdir_vibe() -> Path:
    """Worktree DEDIE de Mistral Vibe (creation = geste OWNER). PAS de repli sur la racine partagee."""
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


def _args_vibe(wt: Path | str, prompt_file: Path | str | None = None) -> list[str]:
    """Arguments d'invocation de Mistral Vibe en mode programmatique, bornes et sans shell."""
    raw_turns = os.environ.get("LAFORGE_VIBE_MAX_TURNS", "60")
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


_MODELE_VIBE = ("mistral", "codestral-latest")   # (fournisseur au census, modele) -- celui du gabarit ci-dessus
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


def _modele_hors_quota(fournisseur: str, modele: str, chemin=None) -> str | None:
    """Motif si le census free tier PROUVE le couple hors d'usage (0 req/min, ou mort 402/404/410), None sinon.

    Invariant bloquant (owner 19/10). Census absent, illisible ou muet sur le couple = None : INCONNU n'est pas NON, on
    delegue. Un 429 SANS limite nulle est un debit passager, pas une interdiction."""
    p = Path(chemin) if chemin else ROOT / "sandbox" / "free_tier_census.json"
    try:
        v = ((json.loads(p.read_text(encoding="utf-8")) or {}).get("verdicts") or {}).get("%s:%s" % (fournisseur, modele))
    except (OSError, ValueError, AttributeError):
        return None
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


def _delegate_to_vibe(task, token: str) -> None:
    """Mistral Vibe execute dans SON worktree via le harness ; le verdict porte sur ce qui est LIVRE (commits, artefact
    verifie), jamais sur sa prose : le harness rend la sortie de vibe, pas un statut de reussite."""
    task_id = task["id"]
    # INVARIANT (owner 19/10) : pas de delegation sur un modele que le census PROUVE hors quota -- l'essai du matin
    # (job_10971233) a rendu 429 avant toute action, mistral-medium etant a 0 req/min sur notre cle.
    _hors_quota = _modele_hors_quota(*_MODELE_VIBE)
    if _hors_quota:
        log.warning(f"  {str(task_id)[:24]} : modele de Vibe REFUSE ({_hors_quota}) -- reaffectation")
        if _reaffecter(dict(task), "MODELE HORS QUOTA : %s" % _hors_quota, ordre=_palier_executeurs("M", ecrit=True)):
            return
        _clore_delegation(task_id, token, False, "[MODELE HORS QUOTA] %s -- aucun autre executeur vivant" % _hors_quota)
        return
    desc = _extract_message(task["description"] or "") or (task["description"] or "")
    wt = str(_workdir_vibe())
    jid = "vibe_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))[:80]
    prompt_file = _HARNESS_JOBS / (jid + ".prompt.md")
    job = _HARNESS_JOBS / (jid + ".json")
    try:
        _config_mcp_vibe(wt)   # AVANT l'etat git : la config n'est jamais comptee comme un livrable de la tache
    except OSError as e:
        log.warning(f"  config MCP de Vibe NON posee dans {wt} ({type(e).__name__}) : Vibe tournera sans le hub")
    _avant = _etat_git(wt)
    _sales_avant = _chemins_status(wt) or frozenset()
    try:
        _HARNESS_JOBS.mkdir(parents=True, exist_ok=True)
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_task_executor.py', 2219, exc_info=True)
    prompt_file.write_text(desc + _CONSIGNE_GIT_VIBE, encoding="utf-8")
    args = (json.loads(os.environ["LAFORGE_VIBE_EXEC_ARGS"]) if os.environ.get("LAFORGE_VIBE_EXEC_ARGS")
            else _args_vibe(wt, prompt_file=prompt_file))
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
    ok, effet, rendu = _juger_livraison(ok, detail, wt, _avant)
    m = re.search(r"commits produits\s*:\s*(\d+)", effet)
    if ok and not rendu and (m is None or int(m.group(1)) == 0) and '"pointer_ref"' not in detail:
        ok = False      # rien de livre ni de pointe : le harness a tourne, Vibe n'a rien produit de verifiable
        effet = "%s ; [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable" % effet
    log.info(f"  DELEGATE {str(task_id)[:24]} -> VIBE {'OK' if ok else 'KO'} {effet}")
    _consigner_verdict_auto("MISTRAL", task_id, ok, effet, detail, rendu)
    motif = _motif_reaffectation_apres(ok, effet, detail)
    if motif and _reaffecter(dict(task), motif, ordre=_palier_executeurs("M", ecrit=True)):
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
_CLE_PAR_FOURNISSEUR = {"groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY", "zai": "ZHIPU_API_KEY"}


def _env_cle_fournisseur(modele: str) -> str | None:
    """Nom de la cle du SEUL fournisseur du modele ; None pour un fournisseur sans cle (opencode/...) : rien a passer."""
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
_RE_QUOTA = re.compile(r"rate limit exceeded|free-models-per-day|quota exceeded|\b429\b", re.I)
_REPLI_EN_COURS: set[str] = set()


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
    }
    # None = rien demande -> modele de l'instance ; "" = modele PAR DEFAUT d'OpenCode demande explicitement (repli).
    modele = modele if modele is not None else _instances_opencode().get(inst, {}).get("modele")
    if modele:
        cfg["model"] = modele
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
_RELANCE_OPENCODE = (
    "[Executeur Nokido] Ta reponse ne rend pas d'intention finale (ou rend ERR_PARTIAL) : reprends exactement ou tu t'es "
    "arrete, va jusqu'au critere d'arret de la consigne, puis termine par la ligne JSON finale exigee "
    "(OK_DONE avec son pointer_ref, ou un echec DIT). Ne recommence pas ce qui est deja fait.")


def _doit_relancer(texte: str) -> bool:
    return _intention_finale(texte) in (None, "ERR_PARTIAL")


def _choisir_modele(modele, session):
    """(modele_choisi | None, note). Les modeles qu'OpenCode sait servir dependent des fournisseurs connectes :
    la liste vient de la reponse session/new conservee (session["models"]["availableModels"]).
    - liste inconnue (doublure sans derniere_session, reponse sans models) -> on TENTE le modele configure, comme avant ;
    - exact -> lui ;
    - sinon UN SEUL disponible au meme nom final (apres le dernier "/") -> celui-la, note qui le dit ;
    - sinon aucun set_model : la note DIT les modeles disponibles (12 noms max, le compte au-dela)."""
    if not modele:
        return None, ""
    brut = None
    if isinstance(session, dict):
        models = session.get("models")
        if isinstance(models, dict):
            brut = models.get("availableModels")
    dispo = []
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


def _delegate_to_opencode(task, token: str, instance: str | None = None, _etat_avant: tuple | None = None) -> None:
    """Instance OpenCode executee dans SON worktree pilotee par ACPClient ; le verdict porte sur ce qui est LIVRE."""
    task_id = task["id"] if hasattr(task, "__getitem__") else getattr(task, "id")
    raw_desc = (task.get("description") if hasattr(task, "get") else task["description"]) or ""
    desc = _extract_message(raw_desc) or raw_desc
    inst = str(instance or (task.get("agent") if hasattr(task, "get") else task["agent"]) or "").upper()
    if not inst and _instances_opencode():
        inst = next(iter(_instances_opencode().keys()))
    inst_cfg = _instances_opencode().get(inst, {})
    wt = str(_workdir_opencode(inst))
    # Le repli quota se rappelle : il reprend l'etat d'AVANT le premier tour, sinon le travail de ce tour passe pour
    # des restes d'autres taches et la preservation l'exclut (job_171ef456, enquete AGY job_198d901b, 19/10).
    if _etat_avant is not None:
        _avant, _sales_avant = _etat_avant
    else:
        _avant = _etat_git(wt)
        _sales_avant = _chemins_status(wt) or frozenset()

    inst_token = _jeton_opencode_instance(inst)
    if not inst_token:
        motif_jeton = f"jeton FORGE_TOKEN_{inst} absent ou illisible au coffre"
        log.warning(f"  DELEGATE {str(task_id)[:24]} -> {inst} REFUSE : {motif_jeton}")
        # 19/10 : 4 taches DEFAUT closes ici sans reaffectation -- une demande ne se perd pas (owner)
        if _reaffecter(dict(task), motif_jeton, ordre=_palier_executeurs("M", ecrit=True)):
            return
        _clore_delegation(task_id, token, False, f"delegation refusee : {motif_jeton}")
        return

    modele = _modele_de_la_tache(desc, inst_cfg.get("modele", ""))
    note_repli = ""
    if str(task_id) in _REPLI_EN_COURS:
        modele = str(inst_cfg.get("repli_modele", "") or "")
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
    prompt_text = desc + _CONSIGNE_GIT_OPENCODE

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
        modele_choisi, note_modele = _choisir_modele(modele, getattr(client, "derniere_session", None))
        if modele_choisi:
            try:
                if callable(getattr(client, "set_model", None)):
                    client.set_model(sid, modele_choisi)
                elif callable(getattr(client, "request", None)):
                    # Le vrai ACPClient n'a pas de set_model : c'est CE chemin qui sert. OpenCode attend `modelId`
                    # (mesure 17/10 : {"model": ...} -> « modelId : expected string, received undefined »).
                    client.request("session/set_model", {"sessionId": sid, "modelId": modele_choisi}, timeout=10)
            except Exception as exc_mod:
                note_modele = f"modele {modele_choisi} non applique ({type(exc_mod).__name__})"
                log.warning(f"  [opencode] {note_modele}: {exc_mod}")
        # OpenCode n'avait AUCUN battement pendant prompt() : un tour long paraissait une mort.
        with _battement_delegation(inst, task_id):
            _t0 = time.time()
            client.silence_max = OPENCODE_SILENCE_S
            res = client.prompt(sid, prompt_text, timeout=timeout)
            detail = (res.get("text") if isinstance(res, dict) else str(res)) or ""
            tours = 1
            while _doit_relancer(detail) and tours < OPENCODE_MAX_TOURS and time.time() - _t0 < timeout:
                tours += 1
                log.info(f"  [opencode] {inst} tour {tours}/{OPENCODE_MAX_TOURS} : intention finale "
                         f"{_intention_finale(detail) or 'absente'} -- relance dans la meme session")
                res = client.prompt(sid, _RELANCE_OPENCODE, timeout=max(60, int(timeout - (time.time() - _t0))))
                suite = (res.get("text") if isinstance(res, dict) else str(res)) or ""
                detail = f"{detail}\n[tour {tours}] {suite}"
        if tours > 1 and _doit_relancer(detail):
            detail = f"{detail}\n[executeur] borne atteinte ({tours} tours) sans intention finale : livraison PARTIELLE"
        if note_modele:
            detail = f"[{note_modele}] {detail}" if detail else note_modele
        ok = bool(detail.strip())
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
        repli_a_tenter = ((bool(_RE_QUOTA.search(str(exc))) or isinstance(exc, TimeoutError))
                          and "repli_modele" in inst_cfg and str(task_id) not in _REPLI_EN_COURS)
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
    ok, effet, rendu = _juger_livraison(ok, detail, wt, _avant, autorises=_tests_autorises(desc))
    m = re.search(r"commits produits\s*:\s*(\d+)", effet)
    if ok and not rendu and (m is None or int(m.group(1)) == 0) and '"pointer_ref"' not in detail:
        ok = False      # rien de livre ni de pointe : le client a tourne, l'instance n'a rien produit de verifiable
        effet = "%s ; [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable" % effet
    log.info(f"  DELEGATE {str(task_id)[:24]} -> {inst} {'OK' if ok else 'KO'} {effet}")
    _consigner_verdict_auto(inst, task_id, ok, effet, detail, rendu)
    # Travail INACHEVE preserve sur la branche : on ne reaffecte pas (la reprise repartirait d'alpha et
    # orphelinerait le commit) -- il attend une relecture.
    motif = None if (note and "INACHEVE" in note) else _motif_reaffectation_apres(ok, effet)
    if motif and _reaffecter(dict(task), motif, ordre=_palier_executeurs("M", ecrit=True)):
        return
    _clore_delegation(task_id, token, ok, "%s | %s" % (effet, detail), intent=rendu)


# REAFFECTATION (owner 17/10 : « il faut que Nokido soit en mesure de debloquer la situation si les cli n'existent plus
# ou n'ont plus de quota » ; decision du 16/10 : quota epuise = reaffecter a la volee ET le dire). Ordre des surfaces
# autonomes ; WORKER_CODE = modeles locaux, ni CLI ni quota -- le dernier recours.
_ORDRE_REPLI = tuple(a.strip().upper() for a in os.environ.get(
    "LAFORGE_REPLI_AUTONOME", "ANTIGRAVITY,MISTRAL,CODEX,WORKER_CODE").split(",") if a.strip())


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


def _palier_executeurs(taille: str, ecrit: bool) -> tuple:
    """Ordre de preference des executeurs pour une tache de `taille` (S/M) qui `ecrit` ou non du code."""
    if str(taille).upper() == "M" and not ecrit:
        return ("ANTIGRAVITY",) + _OPENCODE_ECRITURE
    return _OPENCODE_ECRITURE


def _panne_cli(detail: str) -> str | None:
    """Motif si la sortie d'un CLI COMMENCE par une erreur de fournisseur (429, 402, rate limit...), None sinon.

    19/10 (essai Mistral job_10971233) : le harness rendait ok=True sur « Error: Client error '429 Too Many Requests' ».
    Seul le DEBUT de la sortie compte : un rapport legitime qui PARLE de 429 n'est pas une panne. Motifs reutilises de
    _RE_PANNE_INFRA (meme critere que verdict_automatique)."""
    tete = str(detail or "").lstrip()[:400]
    if not re.match(r"(error|erreur)\b", tete, re.I):
        return None
    if _RE_PANNE_INFRA.search(tete) or re.search(r"rate limit|overloaded|service unavailable", tete, re.I):
        return "PANNE FOURNISSEUR : %s" % tete.splitlines()[0][:160]
    return None


def _motif_reaffectation_apres(ok: bool, effet: str, detail: str = ""):
    """Une delegation ECHOUEE sans AUCUN commit se reaffecte ; une livraison existante (meme refusee) se RELIT ;
    effet illisible -> None (UNKNOWN n'est pas NO). Mesure du 18/10 : 8 non-livraisons reprises a la main.
    19/10 : une panne fournisseur se NOMME (et se reaffecte) au lieu de passer pour du travail non committe."""
    if ok:
        return None
    panne = _panne_cli(detail)
    if panne:
        return panne
    m = re.search(r"commits produits : (\d+)", effet or "")
    if not m or int(m.group(1)) != 0:
        return None
    return "NON LIVRE apres delegation (%s)" % (
        "travail laisse non committe" if "[NON LIVRE]" in effet else "echec sans livraison")


def _reaffecter(task: dict, motif: str, ordre=None):
    """Passe la tache au premier executeur de _ORDRE_REPLI dont le pouls est frais, jamais a un agent deja essaye (pas
    de ping-pong) ; la remet `pending` chez lui et trace {de, vers, motif, quand} dans `reaffectations`. Rend l'agent
    receveur, ou None : chaine epuisee, la tache reste ou elle est, et le journal le dit."""
    # Row du bus OU dict : les deux s'indexent et ont .keys(), seul le dict a .get (mesure 17/10) ; une tache SANS
    # agent (delegation directe, NR test_agy_worktree_et_effet / test_codex_effort) levait KeyError (2630156af, 18/10)
    de = ((task["agent"] if "agent" in task.keys() else "") or "").upper()
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
        vivants = [a for a in (ordre or _ORDRE_REPLI)
                   if a not in essayes and _executeur_bat(a) and not _executeur_suspendu(a)]
        vers = vivants[0] if vivants else None
        try:  # 19/10 OBSERVATION : ce qu'aurait choisi l'ordre hedoniste (force mesuree) -- ne decide RIEN
            from nokido_agent.app.forge_motivation import ordre_hedoniste
            classe = (task["classe"] if "classe" in task.keys() else "") or "M:ecrit"
            hedoniste = (ordre_hedoniste(vivants, classe) or [None])[0] if vivants else None
        except Exception:  # noqa: BLE001 - registre illisible : INCONNU, jamais un choix
            hedoniste = "INCONNU"
        if not vers:
            log.warning(f"  {str(task['id'])[:24]} : {de} ne peut pas la prendre ({motif}) et AUCUN autre executeur "
                        f"vivant hors {sorted(x for x in essayes if x)} -- laissee chez {de}")
            return None
        trace.append({"de": de, "vers": vers, "motif": str(motif)[:200], "quand": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "hedoniste": hedoniste})
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


def _preparer_worktree(agent: str):
    """Avant la delegation : le worktree de l'agent est rebase sur alpha par la brique EXISTANTE `forge_worktree.sync`
    (meme worktree nokido_worktrees/<agent> ; sur conflit elle abandonne le rebase, rien n'est perdu), et c'est
    journalise. Un doublon (_partir_d_alpha) avait ete ecrit ici le 17/10 sans consulter le domaine : retire (anti-dup)."""
    mapping = {
        "ANTIGRAVITY": "antigravity",
        "CODEX": "codex",
        "MISTRAL": "mistral",
        "OPENCODE_GPTOSS": "opencode_gptoss",
        "OPENCODE_NEMOTRON": "opencode_nemotron",
        "OPENCODE_GLM": "opencode_glm",
    }
    for k, v in _instances_opencode().items():
        mapping[k] = v.get("worktree", k.lower())
    nom = mapping.get((agent or "").upper())
    if not nom:
        return None
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
    return {"CODEX": _delegate_to_codex, "MISTRAL": _delegate_to_vibe}.get(ag)


def _capacite_pour(agent: str):
    ag = (agent or "").upper()
    if ag in _instances_opencode() or ag.startswith("OPENCODE_"):
        return lambda a=ag: _peut_lancer_opencode(a)
    return {"CODEX": _peut_lancer_codex, "MISTRAL": _peut_lancer_vibe}.get(ag)


def _marquer_accuse(task_id: str, texte: str) -> None:
    """Statut intermediaire VISIBLE : la tache est prise en compte, pas faite.

    Sans cet etat, un observateur ne dispose que de `running` (indiscernable d'un
    travail en cours) ou de `completed` (mensonge). Best-effort : le suivi ne doit
    jamais faire echouer le relais.
    """
    try:
        conn = _db()
        conn.execute(
            "UPDATE tasks SET status='acknowledged', result=?, updated_at=? WHERE id=?",
            (f"ACCUSE DE RECEPTION (pas un compte rendu) : {texte[:600]}",
             time.strftime("%Y-%m-%dT%H:%M:%S"), task_id))
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
        conn = _db(); _mark_done(conn, task_id, _borner(result), ok); conn.close()
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
    message = _extract_message(description)

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


def run_loop(agent_filter: str | None, once: bool) -> None:
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

    while not _stop:
        beat_daemon(_hb.stem, agent=agent_filter or "*")

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
            conn = _db()
            batch = _fetch_batch(conn, agent_filter)
            conn.close()

            if not batch:
                log.info("Aucune tâche pending — attente")
            else:
                log.info(f"{len(batch)} tâches à traiter")
                for task in batch:
                    if _stop:
                        break
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
                                           ordre=_palier_executeurs("M", ecrit=True)):  # code : jamais AGY (18/10)
                                continue
                            break
                        _cap, _pq = _capacite_pour(_agent_dedie)()
                        if not _cap:
                            if _reaffecter(task, f"{_agent_dedie} autonome INDISPONIBLE ({_pq})",
                                           ordre=_palier_executeurs("M", ecrit=True)):  # code : jamais AGY (18/10)
                                continue
                            log.warning(f"  {task['id'][:24]} : {_agent_dedie} autonome INDISPONIBLE ({_pq}) -- laissee pending")
                            break
                        conn2 = _db()
                        _pris = _reclamer(conn2, task["id"], _agent_dedie, _ident, enforce=_enforce)
                        conn2.close()
                        if not _pris:
                            continue
                        try:
                            _preparer_worktree(_agent_dedie)
                            _deleguer(task, token)
                        except Exception as _de:  # noqa: BLE001
                            log.error(f"delegation {_agent_dedie} KO {task['id'][:24]}: {_de}")
                            _clore_delegation(task["id"], token, False,
                                              f"delegation {_agent_dedie} en exception : {type(_de).__name__}: {_de}")
                        time.sleep(2)
                        continue
                    conn2 = _db()
                    _pris = _reclamer(conn2, task["id"], (task["agent"] or "").upper(), _ident, enforce=_enforce)
                    conn2.close()
                    if not _pris:
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
                        try:
                            if _cap:
                                _preparer_worktree("ANTIGRAVITY")
                                _delegate_to_agy(task, token)
                            elif _reaffecter(task, f"mode AGENT agy indisponible ({_pourquoi})"):
                                pass
                            else:
                                log.warning(
                                    f"  {task['id'][:24]} : mode AGENT indisponible "
                                    f"({_pourquoi}) -> repli RELAIS (repond, n'execute pas)")
                                _relay_to_agy(task, token)
                        except Exception as _pe:  # noqa: BLE001
                            log.error(f"delegation KO {task['id'][:24]}: {_pe}")
                        time.sleep(2)
                        continue

                    ok, result = process_task(task, token)

                    conn3 = _db()
                    _mark_done(conn3, task["id"], result, ok)
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
        while not _stop and _slept < POLL_INTERVAL:
            time.sleep(2)
            _slept += 2

    log.info("TaskExecutor arrêté")
    try:
        _hb.unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"Impossible de supprimer le heartbeat: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Nokido Task Executor Daemon")
    parser.add_argument("--once", action="store_true", help="Traiter 1 batch puis exit")
    parser.add_argument(
        "--agent", type=str, default=None, help="Filtrer par agent (ex: GEMINI, COHERE)"
    )
    args = parser.parse_args()
    run_loop(agent_filter=args.agent, once=args.once)


if __name__ == "__main__":
    main()
