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
import json
import logging
import os
import re
import signal
import sqlite3
import sys
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
    pass

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
        pass
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
        pass
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

    # Fallback : retourner description complète (tronquée)
    return description[:3000]


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
    "CLINE_ACT", "CLINE_PLAN",
)


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
    try:
        import json as _j2

        _reg = _j2.loads((ROOT / "config" / "agent_identities.json")
                         .read_text(encoding="utf-8"))
        for _nom, _spec in (_reg.get("agents") or {}).items():
            if isinstance(_spec, dict) and _spec.get("mode") == "interactive":
                noms.add(str(_nom).upper())
    except Exception:  # noqa: BLE001  (registre illisible -> plancher seul)
        pass
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
    _inter = tuple(sorted(set(_interactive_clis()) | {CODE_AGENT}))
    _ph = ",".join("?" * len(_inter))
    return conn.execute(
        "SELECT id, description, agent, job_id FROM tasks"
        f" WHERE status='pending' AND upper(agent) NOT IN ({_ph})"
        " ORDER BY created_at LIMIT ?",
        (*_inter, BATCH_SIZE),
    ).fetchall()


def _mark_running(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute(
        "UPDATE tasks SET status='running', updated_at=? WHERE id=?",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), task_id),
    )
    conn.commit()


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
        pass
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
            pass

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
    return h.stdout.strip(), len([ligne for ligne in s.stdout.splitlines() if ligne.strip()])


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
            r = _sp.run(["git", "-c", "safe.directory=*", "-C", workdir, "rev-list", "--count",
                         "%s..%s" % (h_av, h_ap), "--"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=20, env=_env_git())
            # rc VERIFIE (2026-10-02, CI de reference f340e9ca4) : `int(stdout or 0)` faisait d'un
            # rev-list en ECHEC « 0 commit » -- HEAD avait bouge, l'effet etait annonce nul.
            if r.returncode == 0 and r.stdout.strip().isdigit():
                n = int(r.stdout.strip())
            else:
                n, pourquoi = -1, " [rev-list rc=%s : %s]" % (r.returncode, (r.stderr or "").strip()[:160])
        except Exception as e:  # noqa: BLE001 - illisible, dit
            n, pourquoi = -1, " [rev-list : %s]" % type(e).__name__
    return "[effet observe] commits produits : %s (%s..%s) ; fichiers non commites : %s%s" % (
        n if n >= 0 else "ILLISIBLE", h_av[:9], h_ap[:9], n_ap, pourquoi)


_INTENTS_NON_FAITS = ("NEED_HUMAN_APPROVAL", "NEED_CLARIFY", "BUDGET_EXCEEDED")


def _intent_rendu(reponse: str) -> str | None:
    """Dernier intent M2M que l'agent DECLARE dans sa reponse (`"intent": "X"`), s'il dit « pas fait ».

    2026-10-01 : AGY s'est arrete -- a bon droit -- en rendant `{"intent": "NEED_HUMAN_APPROVAL"}`
    (git hors de son bac a sable), et la delegation l'a transmis en OK_DONE / SUCCESS parce que
    l'enveloppe du CLI disait `status: SUCCESS` (le CLI a REPONDU, pas la tache FAITE)."""
    import re as _re
    trouves = _re.findall(r'"intent"\s*:\s*"([A-Z_]+)"', reponse or "")
    if not trouves:
        return None
    dernier = trouves[-1]
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
        conn = _db(); _mark_done(conn, task_id, _borner(detail), ok); conn.close()
        intent = intent or ("OK_DONE" if ok else "ERR_INTERNAL")
        try:
            _hub_call("task", {"action": "result", "task_id": task_id, "intent": intent,
                      "result": json.dumps({"intent": intent, "status_code": "SUCCESS" if ok else (
                          "NEEDS_HUMAN" if intent == "NEED_HUMAN_APPROVAL" else "FAILURE"),
                      "pointer_ref": f"tasks.db:{task_id}", "detail": detail[:220]}, ensure_ascii=False)},
                      token, timeout=30)
        except Exception:  # noqa: BLE001
            pass

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
            return _fin(False, f"workdir agy deja tenu: {_lm.dernier_refus}")
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
    cmd = [agy_bin, "--print", desc[:30000], "--add-dir", workdir,
           *_agy_permission_args(), "--output-format", "json",
           "--effort", _eff]
    if _continu:
        cmd.append("--continue")
        log.info(f"  DELEGATE {task_id[:24]} -> LOT_CONTINU : session reprise (--continue)")
    log.info(f"  DELEGATE {task_id[:24]} -> AGY agent (add-dir={workdir})")
    _avant = _etat_git(workdir)
    try:
        r = _sp.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=RELAY_TIMEOUT_S, env=env, cwd=workdir,
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
    except Exception as e:  # noqa: BLE001
        return _fin(False, f"agy exec KO: {type(e).__name__}: {str(e)[:120]}")
    finally:
        if _jeton_wd and _lm is not None:
            _lm.liberer(_jeton_wd)
    raw = (r.stdout or "").strip() or (r.stderr or "").strip()
    try:
        d = json.loads(raw)
        ok = str(d.get("status", "")).upper() == "SUCCESS"
        detail = d.get("response") or d.get("error") or raw[:400]
    except Exception:  # noqa: BLE001
        ok, detail = False, raw[:400] or "agy: sortie vide"
    effet = _effet_observe(workdir, _avant)
    rendu = _intent_rendu(str(detail))
    if rendu:
        ok = False      # l'agent dit lui-meme « pas fait » : son intent prime sur l'enveloppe du CLI
    absent = None if rendu else _artefact_declare_absent(str(detail), workdir)
    if absent:
        ok = False      # DECLARE n'est pas ACHIEVED : l'artefact pointe n'existe pas
        effet = "%s ; [artefact ABSENT] %s" % (effet, absent)
    # Garde d'ACCUSE DE RECEPTION portee sur le chemin principal (2026-10-02, bb:delegate_agy_sans_
    # garde_accuse) : le repli _relay_to_agy refusait deja de clore sur « je vais chercher... ». Ici
    # `agy --print` ne rend qu'UNE reponse, rien a attendre : une promesse sans compte rendu est un
    # echec NOMME. Une reponse qui pointe un artefact est jugee par le controle ci-dessus, pas ici.
    if (not rendu and not absent and '"pointer_ref"' not in str(detail)
            and _est_accuse_reception(str(detail))):
        ok = False
        effet = "%s ; [ACCUSE DE RECEPTION] promesse sans compte rendu" % effet
    log.info(f"  DELEGATE {task_id[:24]} -> AGY {'OK' if ok else 'KO'}{(' ' + rendu) if rendu else ''} "
             f"({len(str(detail))} chars) {effet}")
    # L'effet passe EN TETE : `_fin` tronque le detail a 220 caracteres pour le M2M.
    _fin(bool(ok), "%s | %s" % (effet, detail), intent=rendu)


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
            pass

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
        pass

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
                    conn2 = _db()
                    _mark_running(conn2, task["id"])
                    conn2.close()

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
                                _delegate_to_agy(task, token)
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
