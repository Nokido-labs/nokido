from __future__ import annotations

import sys as _sys_bootstrap
from pathlib import Path as _Path_bootstrap

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# app/ dans le path AVANT d'importer forge_secrets (sinon ModuleNotFoundError
# quand le daemon est lance hors du launcher qui bootstrappe deja le path).
_sys_bootstrap.path.insert(0, str(_Path_bootstrap(__file__).resolve().parent.parent / "app"))
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_gemini_poll_daemon
#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.25|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: daemon polling autonome pour Gemini CLI (pattern D2 Autonomous)
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.25|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"
"""
tools/gemini_poll_daemon.py - Autonomous polling daemon pour Gemini (Pattern D2)
=================================================================================

Le probleme resolu :
  Le pattern D (collab Claude <-> Gemini via notify/poll) est asynchrone par conception.
  Gemini CLI n'execute des tools QUE quand un humain tape un prompt.
  Donc les notify envoyees par Claude restent en attente indefiniment.

Solution Pattern D2 :
  Un daemon Python qui tourne en arriere-plan et poll le Hub Nokido toutes les N
  secondes. Quand une notif est recue, 2 comportements possibles :

  Mode PASSIVE (defaut) : logge + ecrit dans ~/.gemini/inbox.md pour visibilite
                          humaine. Gemini CLI peut etre prompte a consulter l'inbox.

  Mode ACTIVE          : appelle directement l'API Gemini pour traiter la tache
                         (requiert GEMINI_API_KEY + librairie google-genai). Ecrit
                         la reponse comme nouvelle notify vers CLAUDE.

Configuration via env :
  FORGE_MCP_TOKEN         : token Bearer Hub (lu depuis Nokido.env)
  FORGE_HUB_URL           : URL Hub (defaut http://127.0.0.1:8766)
  GEMINI_POLL_INTERVAL_S  : intervalle poll en secondes (defaut 30)
  GEMINI_POLL_MODE        : passive | active (defaut passive)
  GEMINI_API_KEY          : requis en mode active
  GEMINI_MODEL            : modele (defaut gemini-2.5-flash)
  GEMINI_INBOX_PATH       : fichier markdown pour notifs recues
                            (defaut ~/.gemini/inbox.md)

Usage :
  python tools/gemini_poll_daemon.py                 # mode passive, 30s
  GEMINI_POLL_MODE=active python tools/gemini_poll_daemon.py

Integration avec forge_services_launcher :
  python tools/forge_services_launcher.py            # inclus si GEMINI_POLL_ENABLED=1
  python tools/forge_services_launcher.py --only gemini_poll

Protocole :
  1. Boucle every N seconds
  2. POST /mcp method=tools/call name=poll -> liste notifs
  3. Filter : garder celles qui mentionnent Gemini ou sont non-addressees
  4. Mode passive : append dans inbox.md avec timestamp + ID
  5. Mode active : invoke Gemini API avec le contexte, parser la reponse,
                   appeler tools/call name=notify pour repondre a Claude

Heartbeat : le daemon ecrit sa date de derniere iteration dans
sandbox/gemini_poll_daemon.heartbeat pour monitoring.
"""

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
SANDBOX.mkdir(exist_ok=True)


def _env_from_nokido(key: str, default: str = "") -> str:
    """Lit une var depuis env OS, puis Nokido.env si absent. Même pattern que load_token()."""
    val = os.environ.get(key, "")
    if val:
        return val
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith(f"{key}=") and not line.startswith("#"):
                return line.split("=", 1)[1].split("#")[0].strip()
    return default


HUB_URL = _env_from_nokido("FORGE_HUB_URL", "http://127.0.0.1:8766").rstrip("/")
POLL_INTERVAL = int(_env_from_nokido("GEMINI_POLL_INTERVAL_S", "30"))
POLL_MODE = _env_from_nokido(
    "GEMINI_POLL_MODE", "passive"
).lower()  # défaut passive: pas de traitement cloud autonome (garde-fou); GEMINI_POLL_MODE=active pour opt-in
GEMINI_MODEL = _env_from_nokido("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_CLI_MODEL = _env_from_nokido(
    "GEMINI_CLI_MODEL", "gemini-2.5-pro"
)  # flash-lite = nul pour code/raisonnement
INBOX_PATH = Path(os.environ.get("GEMINI_INBOX_PATH", str(Path.home() / ".gemini" / "inbox.md")))
HEARTBEAT = SANDBOX / "gemini_poll_daemon.heartbeat"
LOG_FILE = SANDBOX / "gemini_poll_daemon.log"

_SHUTDOWN = False
_TRIGGER_LOCK = None  # threading.Lock, init in main()
_SEEN_FRAMES: set = set()  # dedup par hash du texte


def log(msg: str, level: str = "INFO") -> None:
    """Log sur stderr + fichier."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level:>5}] {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # muet-ok : la ligne vient d'etre ecrite sur stderr juste
        # au-dessus, donc elle n'est PAS perdue — seule sa copie fichier l'est. Et
        # signaler ici passerait par le meme chemin qui vient d'echouer. Le silence
        # est DECLARE et sa perte est bornee : la trace existe ailleurs.
        pass


def load_token() -> str:
    """Lit FORGE_TOKEN_GEMINI (derive) ou FORGE_MCP_TOKEN (fallback)."""
    # Token derive GEMINI en priorite (identification forte)
    tok = get_secret("FORGE_TOKEN_GEMINI") or ""
    if tok:
        return tok
    tok = get_secret("FORGE_MCP_TOKEN") or ""
    if tok:
        return tok
    env = ROOT / "Nokido.env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FORGE_TOKEN_GEMINI="):
                return line.split("=", 1)[1].split("#")[0].strip()
            if line.startswith("FORGE_MCP_TOKEN=") and not tok:
                tok = line.split("=", 1)[1].split("#")[0].strip()
    return tok


def mcp_call(method: str, params: dict | None = None, token: str = "", timeout: int = 15) -> dict:
    """Appel JSON-RPC au Hub MCP."""
    body = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 99999, "method": method}
    if params is not None:
        body["params"] = params

    req = urllib.request.Request(
        f"{HUB_URL}/mcp",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
            "X-Agent-Name": "GEMINI",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {
            "error": {
                "code": e.code,
                "message": e.reason,
                "body": e.read().decode("utf-8", errors="replace")[:200],
            }
        }
    except Exception as e:
        return {"error": {"message": f"{type(e).__name__}: {e}"}}


def poll_notifications(token: str) -> list[str]:
    """Appelle tools/call name=poll. Retourne la liste des messages.

    ack=False — LECTURE NON-CONSOMMANTE (2026-07-29). Ce daemon est PASSIF : il AFFICHE
    le courrier, il ne le TRAITE pas. Or `poll` accuse réception par défaut, et il polle
    en tant que GEMINI : il faisait donc passer les mails de `delivered` à `acked` toutes
    les 30 s, alors que forge_gemini_autonomous_agent — qui, lui, RÉPOND — lit via
    secretaire(ack=False), lequel ne rend QUE les `delivered`.

    Une file, deux lecteurs, dont le passif vidait la boîte de l'actif. Mesuré : un mail
    actionnable posté à GEMINI était acké en 1450 ms, zéro réponse produite, journal de
    l'auto-répondeur inchangé. Un lecteur qui affiche n'accuse pas réception à la place
    de celui qui traite.
    """
    resp = mcp_call("tools/call", {"name": "poll", "arguments": {"ack": False}}, token=token)
    if "error" in resp:
        log(f"poll error: {resp['error']}", "WARN")
        return []

    content = resp.get("result", {}).get("content", [])
    if not content:
        return []

    text = content[0].get("text", "")
    # Filtre robuste : toutes variantes "Aucune notification" avec/sans point,
    # "Outil inconnu: xxx" (bug Hub pre-commit 4e7e39c qui revient parfois)
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.rstrip(".") in ("", "Aucune notification en attente", "Aucune notification"):
        return []
    if stripped.startswith("Outil inconnu:"):
        return []
    # Filtre defensif : reponses d erreur du hub ne sont PAS des notifications
    if stripped.startswith("SECURITY:") or stripped.startswith("Erreur:"):
        log(f"poll bloque par hub: {stripped[:100]}", "WARN")
        return []
    text = stripped  # normaliser pour split
    if not text:
        return []

    # Le poll retourne les messages separes par lignes vides ou prefix "[AGENT]"
    # On split par marker "[CLAUDE]", "[GEMINI]", "[ROO]", "[CLINE]" etc.
    import re

    parts = re.split(r"(?=^\[[A-Z_]+\])", text, flags=re.M)
    return [p.strip() for p in parts if p.strip()]


def send_reply(token: str, reply_text: str) -> bool:
    """Envoie une notify en reponse via hub action=notify (tool natif ring 3)."""
    resp = mcp_call(
        "tools/call",
        {"name": "hub", "arguments": {"action": "notify", "message": reply_text}},
        token=token,
    )
    return "error" not in resp


def index_in_rag(token: str, entry_id: str, text: str, tags: list) -> bool:
    """Indexe le resultat dans la RAG partagee."""
    tags_str = ",".join(tags)
    sql = (
        "INSERT INTO rag_chunks (id, text, source, domain, author, "
        "ingested_at, meta) VALUES ("
        f"'{entry_id}', '{text.replace(chr(39), chr(39) * 2)[:2000]}', "
        f"'gemini_poll_daemon', 'collab', 'GEMINI', datetime('now'), "
        f'\'{{"tags": ["{tags_str}"]}}\' )'
    )
    resp = mcp_call("tools/call", {"name": "query", "arguments": {"sql": sql}}, token=token)
    return "error" not in resp


def append_to_inbox(notifs: list[str]) -> None:
    """Append les notifs au fichier inbox.md (mode passive)."""
    INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with INBOX_PATH.open("a", encoding="utf-8") as f:
        for n in notifs:
            f.write(f"\n---\n## {ts}\n\n{n}\n")


def call_gemini_cli(prompt: str, token: str = "", timeout: int = 120) -> str:
    """Appel Gemini CLI delegate or fallback to agy.exe."""
    # Try importing forge_agent_proxy
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_agent_proxy import ask as _ask
        import asyncio
        log("[CLI] Delegating prompt to forge_agent_proxy...", "INFO")
        r = asyncio.run(_ask(provider_name="gemini_cli", message=prompt, raw=True, rag_context=False, timeout=timeout))
        if r.get("ok"):
            text = r.get("text", "")
            if text:
                log(f"[CLI] Proxy delegate succeeded: {text[:200]}", "INFO")
                return text
            log("[CLI] forge_agent_proxy returned empty text", "WARN")
    except Exception as exc:
        log(f"[CLI] Proxy delegate failed: {exc}. Trying direct agy.exe spawn.", "WARN")

    # Direct fallback to agy.exe if proxy fails or returns empty
    import subprocess as _sp

    # Chemin du binaire : variable d'environnement D'ABORD, litteral en dernier
    # recours — meme ordre que forge_task_executor._delegate_to_agy. Un chemin owner
    # code en dur rend le daemon non portable et masque une absence en « introuvable ».
    agy_bin = os.environ.get("LAFORGE_AGY_BIN", "")
    if not agy_bin or not os.path.exists(agy_bin):
        agy_bin = os.path.join(os.environ.get("LOCALAPPDATA", ""), "agy", "bin", "agy.exe")
    if not os.path.exists(agy_bin):
        agy_bin = r"%USERPROFILE%\AppData\Local\agy\bin\agy.exe"
    if not os.path.exists(agy_bin):
        log(f"[CLI] agy.exe introuvable (LAFORGE_AGY_BIN, LOCALAPPDATA, defaut)", "WARN")
        return "ERR: agy.exe introuvable — definir LAFORGE_AGY_BIN"

    user_home = os.environ.get("LAFORGE_AGY_HOME", r"%USERPROFILE%")
    env = {
        **os.environ,
        "USERPROFILE": user_home,
        "HOME": user_home,
        "LOCALAPPDATA": user_home + r"\AppData\Local",
        "APPDATA": user_home + r"\AppData\Roaming",
    }
    # PERIMETRE BORNE : `--dangerously-skip-permissions` retire les garde-fous
    # interactifs d'agy ; sans `--add-dir` son perimetre d'ecriture n'est borne par
    # RIEN. On le borne au depot, comme le fait deja forge_task_executor.
    _workdir = os.environ.get("LAFORGE_AGY_WORKDIR", str(ROOT))
    cmd = [
        agy_bin,
        "--print",
        prompt[:30000],
        "--add-dir",
        _workdir,
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
    ]
    try:
        r = _sp.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(timeout, 300),
            encoding="utf-8",
            errors="replace",
            env=env,
            # Le depot, PAS C:/tmp : owner 28-07 « plus aucune ecriture dans C:/tmp »
            # (trois logs de 70 Go y avaient rempli le disque).
            cwd=_workdir,
        )
        if r.returncode == 0:
            try:
                data = json.loads(r.stdout)
                if data.get("status") == "success" or "response" in data:
                    return data.get("response") or ""
                return data.get("error") or r.stderr or r.stdout
            except Exception:
                return r.stdout
        log(f"[CLI] Direct agy.exe failed code={r.returncode}", "WARN")
        return f"ERR: agy failed with code {r.returncode}: {r.stderr or r.stdout}"
    except Exception as e:
        log(f"[CLI] Direct agy.exe exception: {e}", "WARN")
        return f"ERR: agy invocation exception: {e}"


def call_groq_fallback(prompt: str, timeout: int = 30) -> str:
    """Fallback Groq (Llama 70B) -- gratuit, zero dependance."""
    tok = ""
    env_path = ROOT / "Nokido.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GROQ_API_KEY="):
                tok = line.split("=", 1)[1].strip()
    if not tok:
        return "ERR:GROQ_NO_KEY"
    import json as _j

    body = _j.dumps(
        {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt[:4000]}],
            "max_tokens": 500,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {tok}",
            "User-Agent": "LaForge/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _j.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERR:GROQ:{e}"


def call_llm(prompt: str, api_key: str = "", model: str = "", timeout: int = 90) -> str:
    """Cascade: API key -> CLI OAuth -> Groq fallback.
    Chaque option est gratuite ou utilise l abonnement existant.
    """
    # 1. API key Gemini (payant a l usage, le plus rapide)
    if api_key:
        result = call_gemini_api_rest(prompt, api_key, model or GEMINI_MODEL, timeout)
        if not result.startswith("ERR"):
            return result
        log(f"API key failed: {result[:80]} -- fallback CLI OAuth", "WARN")
    # 2. CLI OAuth Google One Ultra (gratuit abonnement)
    result = call_gemini_cli(prompt, timeout)
    if not result.startswith("ERR"):
        return result
    log(f"CLI OAuth failed: {result[:80]} -- fallback Groq", "WARN")
    # 3. Groq Llama 70B (gratuit, 14400 req/jour)
    result = call_groq_fallback(prompt, timeout=30)
    if not result.startswith("ERR"):
        return f"[via Groq] {result}"
    log(f"All LLM backends failed: {result[:80]}", "ERR")
    return "(aucun backend LLM disponible)"


def call_gemini_api_rest(prompt: str, api_key: str, model: str, timeout: int = 120) -> str:
    """Appel Gemini via API REST directe (GEMINI_API_KEY requis)."""

    # Format Gemini REST API v1beta : endpoint generateContent
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        candidates = data.get("candidates", [])
        if candidates:
            return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return "(reponse Gemini vide)"
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")[:500]
        return f"ERR Gemini API HTTP {e.code}: {body_err}"
    except Exception as e:
        return f"ERR Gemini API: {type(e).__name__}: {e}"


def _db_path() -> str:
    """Chemin de la base des agent_messages : suit l'interrupteur de la scission M2M."""
    from nokido_agent.app.forge_db_path import m2m_path
    return m2m_path()


def deliver_to_mailbox(
    from_agent: str, to_agent: str, method: str, payload: dict, token: str
) -> bool:
    """
    Ecrit un message dans agent_messages (boite aux lettres commune).
    Chaque agent lit SA boite via :
      query "SELECT * FROM agent_messages WHERE to_agent='<id>' AND status='unread'"
    Zero appel API externe — persistant SQLite WAL.
    """
    import hashlib as _h
    import sqlite3 as _sq

    msg_id = _h.sha256(f"{from_agent}{to_agent}{time.time()}".encode()).hexdigest()[:16]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload_json = json.dumps(payload, ensure_ascii=False)
    try:
        conn = _sq.connect(_db_path(), timeout=15)
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO agent_messages"
            "(id, from_agent, to_agent, correlation_id, method,"
            " payload, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                msg_id,
                from_agent,
                to_agent,
                f"daemon_{int(time.time())}",
                method,
                payload_json,
                "unread",
                now,
            ),
        )
        conn.commit()
        conn.close()
        log(f"Mailbox [{from_agent}→{to_agent}] {method}: {str(payload)[:80]}")
        return True
    except Exception as e:
        log(f"deliver_to_mailbox ERR: {e}", "ERR")
        return False


# Nos PROPRES services portent "gemini" dans leur chemin de script : sans exclusion,
# le critere substring ci-dessous les prend pour une session humaine. Mesure du
# 2026-07-22 : forge_gemini_autonomous_agent.py se detectait LUI-MEME -> deferral
# permanent ("deferred: gemini interactive running" a chaque tick, file jamais drainee).
# Meme famille que le keeper aveugle a son enfant : identifier par CAPACITE, pas par NOM.
_OWN_SERVICE_MARKERS = (
    "forge_gemini_autonomous_agent.py",
    "gemini_poll_daemon.py",
    "forge_gemini_ingress.py",
)


def _is_gemini_interactive_running() -> bool:
    """True seulement si une session Gemini CLI INTERACTIVE (humaine) est en cours.

    Exclut le process courant et les services Nokido dont le nom contient "gemini" :
    eux ne sont pas des sessions humaines, et les compter revient a se refuser le
    droit de travailler des qu'on travaille.
    """
    try:
        import os as _os

        import psutil as _ps

        _self = _os.getpid()
        for p in _ps.process_iter(["pid", "cmdline"]):
            try:
                if p.info.get("pid") == _self:
                    continue
                cmd = " ".join(p.info.get("cmdline") or [])
                low = cmd.lower()
                if any(marker in low for marker in _OWN_SERVICE_MARKERS):
                    continue  # service Nokido, pas une session humaine
                if "litert" in low or "lit.windows" in low:
                    continue  # skip litert process in .gemini/bin/litert
                # gemini.cmd ou node + gemini bundle, sans flag -p (= interactif)
                if "gemini" in low and "-p " not in cmd and "--prompt " not in cmd:
                    return True
            except Exception:
                continue
    except ImportError:
        pass
    return False


def process_active(notif: str, api_key: str, token: str) -> None:
    """
    Mode active : depot dans la boite aux lettres agent_messages.
    Gemini OAuth CLI lit sa boite via :
      query "SELECT payload FROM agent_messages
             WHERE to_agent='agt_gemini' AND status='unread'
             ORDER BY created_at DESC"
    Pas d appel API externe — zero token, zero cout, canal natif.
    """
    if "fichier ecrit:" in notif or "Mode AUTO" in notif:
        return
    if len(notif) < 30:
        return
    # Ignorer nos propres messages daemon pour éviter feedback loop
    if (
        notif.startswith("[DAEMON")
        or "[DAEMON→POLL]" in notif
        or "[DAEMON] Nouveau message" in notif
    ):
        return

    # Determiner l expediteur et le destinataire selon le contenu
    if "[CLAUDE]" in notif:
        from_id, to_id = "agt_claude", "agt_gemini"
    elif "[GEMINI]" in notif:
        from_id, to_id = "agt_gemini", "agt_claude"
    else:
        from_id, to_id = "agt_daemon", "agt_gemini"

    # Deposer dans la boite aux lettres
    ok = deliver_to_mailbox(
        from_agent=from_id,
        to_agent=to_id,
        method="agent.notification",
        payload={"text": notif, "source": "daemon_relay", "ts": datetime.now().isoformat()},
        token=token,
    )

    if ok:
        # Aussi envoyer un hub notify pour le poll temps reel (volatile)
        send_reply(token, f"[DAEMON→{to_id}] Message deposé en boite aux lettres")
        log(f"Delivered [{from_id}→{to_id}] via mailbox")
        # Volatile notify supplémentaire ciblée pour que Gemini voit la notif au prochain poll
        if to_id == "agt_gemini":
            import hashlib as _hlib

            frame_key = _hlib.md5(notif[:120].encode()).hexdigest()
            if frame_key in _SEEN_FRAMES:
                log("[INBOX] Dedup — frame déjà traité, skip", "INFO")
            else:
                _SEEN_FRAMES.add(frame_key)
                if len(_SEEN_FRAMES) > 200:
                    _SEEN_FRAMES.clear()
                # Vérifier si session Gemini interactive en cours → éviter conflit
                gemini_running = _is_gemini_interactive_running()
                if gemini_running:
                    # Session interactive active : volatile notify suffit
                    msg_preview = notif[:400] if len(notif) > 400 else notif
                    mcp_call(
                        "tools/call",
                        {
                            "name": "hub",
                            "arguments": {
                                "action": "notify",
                                "to": "gemini",
                                "message": f"[DAEMON→POLL] {msg_preview}",
                            },
                        },
                        token=token,
                    )
                    log(
                        "[INBOX] Session interactive détectée → volatile notify (pas de spawn)",
                        "INFO",
                    )
                else:
                    # Pas de session interactive → spawn headless
                    cli_prompt = (
                        f"Tâche: {notif[:600]}\n"
                        "Traite via hub/rag/run/task. "
                        "Réponds: hub action=notify to=claude message=<résultat>."
                    )
                    log("[INBOX] Lancement Gemini CLI headless (no interactive session)...", "INFO")
                    result = call_gemini_cli(cli_prompt, token=token)
                    log(f"[CLI] Résultat: {result[:200]}", "INFO")
    else:
        log("Mailbox delivery failed", "ERR")


def write_heartbeat(status: str, notifs_count: int = 0) -> None:
    """Ecrit heartbeat pour monitoring externe."""
    try:
        # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le
        # `pid` absent ici, sans quoi le porteur du pouls reste inattribuable.
        from nokido_agent.app.forge_heartbeat import beat_daemon

        beat_daemon(
            "gemini_poll_daemon",
            status=status,
            mode=POLL_MODE,
            interval_s=POLL_INTERVAL,
            notifs_consumed_this_cycle=notifs_count,
            hub_url=HUB_URL,
            model=GEMINI_MODEL if POLL_MODE == "active" else None,
        )
    except Exception as e:  # noqa: BLE001
        log("ERROR", "heartbeat NON ecrit (%s: %s) | consequence: ce daemon sera lu "
                     "comme MORT par le superviseur alors qu'il tourne"
                     % (type(e).__name__, str(e)[:90]))


def handle_shutdown(signum, frame):
    """SIGINT/SIGTERM handler."""
    global _SHUTDOWN
    _SHUTDOWN = True
    log(f"Signal {signum} recu, shutdown...")
    try:
        if _PIDFILE.exists() and int(_PIDFILE.read_text().strip()) == os.getpid():
            _PIDFILE.unlink()
    except Exception:
        pass


_PIDFILE = SANDBOX / "gemini_poll_daemon.pid"


def _pid_alive_win(pid: int) -> bool:
    """Hard Windows liveness check via OpenProcess (plus fiable que psutil)."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        exit_code = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(h)
        # STILL_ACTIVE = 259
        return bool(ok) and exit_code.value == 259
    except Exception:
        return False


def _acquire_pidfile() -> bool:
    """Single-instance guard via PID file. Returns False if another instance running."""
    pid = os.getpid()
    if _PIDFILE.exists():
        try:
            old_pid = int(_PIDFILE.read_text().strip())
            if old_pid != pid:
                # 1. Hard Windows check: si process mort -> pidfile perime, on prend la main.
                if os.name == "nt" and not _pid_alive_win(old_pid):
                    _PIDFILE.unlink(missing_ok=True)
                else:
                    # 2. Process vivant : verifier que c'est un gemini_poll_daemon
                    #    (sinon PID reutilise -> pidfile perime -> crash-loop).
                    try:
                        import psutil

                        if psutil.pid_exists(old_pid):
                            try:
                                _cl = " ".join(psutil.Process(old_pid).cmdline()).lower()
                            except Exception:
                                _cl = ""
                            if "gemini_poll_daemon" in _cl:
                                return False
                            # PID vivant mais autre process -> pidfile perime.
                    except ImportError:
                        import subprocess as _sp

                        r = _sp.run(
                            ["tasklist", "/FI", f"PID eq {old_pid}", "/NH", "/FO", "CSV"],
                            capture_output=True,
                            text=True,
                        errors="replace")
                        if "gemini_poll_daemon" in r.stdout.lower():
                            return False
        except Exception:
            pass
    _PIDFILE.write_text(str(pid))
    return True


def main() -> int:
    global _TRIGGER_LOCK, POLL_INTERVAL, POLL_MODE
    import threading as _thr

    _TRIGGER_LOCK = _thr.Lock()

    parser = argparse.ArgumentParser(description="Gemini autonomous polling daemon")
    parser.add_argument("--once", action="store_true", help="Un seul cycle puis exit (pour tests)")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help=f"Override GEMINI_POLL_INTERVAL_S (defaut {POLL_INTERVAL}s)",
    )
    parser.add_argument(
        "--mode", choices=["passive", "active"], default=None, help="Override GEMINI_POLL_MODE"
    )
    args = parser.parse_args()

    POLL_INTERVAL = args.interval or POLL_INTERVAL
    POLL_MODE = args.mode or POLL_MODE
    interval = POLL_INTERVAL
    mode = POLL_MODE
    # Garde-fou : mode "active" = traitement cloud autonome des notifs. Ne
    # l'autoriser que sur opt-in explicite GEMINI_ALLOW_ACTIVE=1, MEME si
    # --mode active arrive en CLI (le supervisor le passe en dur dans
    # services.toml). Sinon -> passive : le daemon ne fait qu'ecrire l'inbox,
    # zero appel cloud autonome.
    if mode == "active" and os.environ.get("GEMINI_ALLOW_ACTIVE", "") != "1":
        log(
            "mode 'active' demande mais GEMINI_ALLOW_ACTIVE!=1 "
            "-> rabattu sur 'passive' (garde-fou anti-fuite cloud)",
            "WARN",
        )
        mode = "passive"

    # Single-instance guard
    if not args.once and not _acquire_pidfile():
        log(f"Another instance already running (PID in {_PIDFILE}). Exiting.", "WARN")
        return 0

    # Setup signals
    signal.signal(signal.SIGINT, handle_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_shutdown)

    # Token
    token = load_token()
    if not token:
        log("FORGE_MCP_TOKEN absent (env ou Nokido.env). Aborting.", "ERR")
        return 2

    # API key si mode active — lit depuis env OS ou Nokido.env
    api_key = _env_from_nokido("GEMINI_API_KEY", "")
    if mode == "active" and not api_key:
        log("Mode active: GEMINI_API_KEY absent, utilisation du CLI OAuth.", "INFO")

    log(f"Gemini Poll Daemon starting | mode={mode} | interval={interval}s | hub={HUB_URL}")
    log(f"  inbox: {INBOX_PATH}")
    log(f"  heartbeat: {HEARTBEAT}")
    log(f"  log: {LOG_FILE}")

    # Ping initial : verifier que le Hub repond
    health = mcp_call("tools/list", token=token, timeout=5)
    if "error" in health:
        log(f"Hub unreachable: {health['error']}", "ERR")
        return 3
    tools_count = len(health.get("result", {}).get("tools", []))
    log(f"Hub OK, {tools_count} tools disponibles")

    write_heartbeat("starting")
    cycles = 0

    # Démarrer le listener SSE /inbox en thread parallèle
    import threading

    _inbox_stop = threading.Event()

    def _inbox_listener():
        """
        Long-poll SSE vers /inbox/agt_gemini.
        Réactivité ms au lieu de poll toutes les 20s.
        Se reconnecte automatiquement après chaque message.
        """
        import json as _ij
        import urllib.request as _ur

        inbox_url = f"{HUB_URL}/inbox/agt_gemini"
        reconnect_delay = 1
        while not _SHUTDOWN and not _inbox_stop.is_set():
            try:
                req = _ur.Request(
                    inbox_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "text/event-stream",
                        "X-Agent-Name": "GEMINI",
                    },
                )
                with _ur.urlopen(req, timeout=35) as r:
                    reconnect_delay = 1  # reset après succès
                    for raw_line in r:
                        if _SHUTDOWN or _inbox_stop.is_set():
                            break
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                frame = _ij.loads(data_str)
                                if frame.get("type") == "connected":
                                    log(f"[INBOX-SSE] Connecté à {inbox_url}", "INFO")
                                    continue
                                if frame.get("type") in ("expired", "ping"):
                                    continue
                                # Message reçu — traiter comme notif active
                                text = frame.get("text") or str(frame.get("parameters", ""))
                                if text and len(text) > 20:
                                    log(f"[INBOX-SSE] Frame reçu: {text[:80]}", "INFO")
                                    process_active(text, api_key, token)
                            except Exception as _fe:
                                log(f"[INBOX-SSE] Parse error: {_fe}", "WARN")
            except Exception as _e:
                if not _SHUTDOWN:
                    log(f"[INBOX-SSE] Reconnexion dans {reconnect_delay}s ({_e})", "WARN")
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)

    _inbox_thread = threading.Thread(target=_inbox_listener, name="InboxSSE", daemon=True)
    _inbox_thread.start()
    log(f"[INBOX-SSE] Listener démarré → {HUB_URL}/inbox/agt_gemini")

    # ── Thread D3 : poll agent_messages pour tâches agt_gemini_cli (OAuth CLI) ──
    # Toujours le bin du profil utilisateur — OAuth creds dans %USERPROFILE%\.gemini
    _GEMINI_BIN = os.environ.get(
        "GEMINI_CLI_BIN",
        __import__("os").path.expanduser(r"~\AppData\Roaming\npm\gemini.cmd"),
    )
    # Env vars pour que gemini.cmd trouve le bon profil OAuth (pas systemprofile)
    _GEMINI_ENV = {
        **os.environ,
        "USERPROFILE": __import__("os").path.expanduser(r"~"),
        "APPDATA": __import__("os").path.expanduser(r"~\AppData\Roaming"),
        "LOCALAPPDATA": __import__("os").path.expanduser(r"~\AppData\Local"),
        "HOME": __import__("os").path.expanduser(r"~"),
        "NO_COLOR": "1",
        "GEMINI_CLI_TRUST_WORKSPACE": "true",
    }
    _CLI_TIMEOUT = 120
    _DB_PATH = Path(_db_path())   # scission M2M : agent_messages, meme chemin que _db_path()
    _CLI_AGENT = "agt_gemini_cli"

    _last_interactive_seen: list = [0.0]  # mutable pour closure
    _INTERACTIVE_COOLDOWN = 45  # s après fermeture session interactive avant spawn headless

    def _poll_cli_tasks():
        """Poll agent_messages pour les tâches agt_gemini_cli, les exécute via gemini.cmd."""
        while not _SHUTDOWN:
            # Bloquer si session interactive active OU cooldown post-session
            if _is_gemini_interactive_running():
                _last_interactive_seen[0] = time.time()
                log("[D3-CLI] Session interactive détectée — skip headless spawn", "INFO")
                for _ in range(15):
                    if _SHUTDOWN:
                        break
                    time.sleep(1)
                continue
            if time.time() - _last_interactive_seen[0] < _INTERACTIVE_COOLDOWN:
                remaining = int(_INTERACTIVE_COOLDOWN - (time.time() - _last_interactive_seen[0]))
                log(f"[D3-CLI] Cooldown post-session interactive ({remaining}s restants)", "INFO")
                for _ in range(15):
                    if _SHUTDOWN:
                        break
                    time.sleep(1)
                continue

            try:
                conn = sqlite3.connect(str(_DB_PATH), timeout=15)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.row_factory = sqlite3.Row
                # Exclure in_progress pour éviter double-spawn pendant timeout 120s
                rows = conn.execute(
                    "SELECT * FROM agent_messages WHERE to_agent=? AND status='unread' ORDER BY created_at LIMIT 1",
                    (_CLI_AGENT,),
                ).fetchall()
                for row in rows:
                    if _SHUTDOWN:
                        break
                    # Double-check: si interactive s'est lancé entre select et spawn
                    if _is_gemini_interactive_running():
                        _last_interactive_seen[0] = time.time()
                        log(
                            "[D3-CLI] Session interactive détectée au dernier moment — requeue",
                            "WARN",
                        )
                        conn.close()
                        conn = None
                        break
                    # Marquer in_progress AVANT spawn pour éviter race entre cycles poll
                    conn.execute(
                        "UPDATE agent_messages SET status='in_progress', read_at=? WHERE id=? AND status='unread'",
                        (time.strftime("%Y-%m-%dT%H:%M:%S"), row["id"]),
                    )
                    conn.commit()
                    conn.close()
                    conn = None

                    payload = {}
                    try:
                        payload = json.loads(row["payload"] or "{}")
                    except Exception:
                        pass
                    prompt = (
                        payload.get("prompt")
                        or payload.get("task")
                        or payload.get("message")
                        or str(payload)
                    )
                    log(f"[D3-CLI] Task from={row['from_agent']} prompt={prompt[:60]}...")
                    try:
                        result_text = call_gemini_cli(prompt, token=token, timeout=_CLI_TIMEOUT)
                    except Exception as _ce:
                        result_text = f"[ERR] {_ce}"
                    log(f"[D3-CLI] Result: {result_text[:80]}")
                    # Écrire résultat + marquer read dans nouvelle connexion
                    conn2 = sqlite3.connect(str(_DB_PATH), timeout=15)
                    conn2.execute("PRAGMA journal_mode=WAL")
                    conn2.execute(
                        """INSERT OR REPLACE INTO agent_messages
                           (id,from_agent,to_agent,correlation_id,method,payload,result,status,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            str(uuid.uuid4()),
                            _CLI_AGENT,
                            row["from_agent"] or "agt_claude",
                            row["id"],
                            "task.result",
                            json.dumps({"original_method": row["method"]}, ensure_ascii=False),
                            result_text[:4000],
                            "unread",
                            time.strftime("%Y-%m-%dT%H:%M:%S"),
                        ),
                    )
                    conn2.execute(
                        "UPDATE agent_messages SET status='read', read_at=? WHERE id=?",
                        (time.strftime("%Y-%m-%dT%H:%M:%S"), row["id"]),
                    )
                    conn2.commit()
                    conn2.close()
                if conn:
                    conn.close()
            except Exception as _e:
                log(f"[D3-CLI] DB error: {_e}", "WARN")
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
            for _ in range(15):  # poll toutes les 15s
                if _SHUTDOWN:
                    break
                time.sleep(1)

    _cli_thread = threading.Thread(target=_poll_cli_tasks, name="CliTaskD3", daemon=True)
    _cli_thread.start()
    log(f"[D3-CLI] Thread démarré — poll agent_messages to={_CLI_AGENT} bin={_GEMINI_BIN}")

    while not _SHUTDOWN:
        cycles += 1
        try:
            notifs = poll_notifications(token)
        except Exception as e:
            log(f"Poll exception: {type(e).__name__}: {e}", "ERR")
            notifs = []

        if notifs:
            log(f"Cycle {cycles}: {len(notifs)} notification(s) recue(s)")

            if mode == "passive":
                append_to_inbox(notifs)
                log(f"  -> appended to {INBOX_PATH.name}")
            elif mode == "active":
                for notif in notifs:
                    if _SHUTDOWN:
                        break
                    try:
                        process_active(notif, api_key, token)
                    except Exception as e:
                        log(f"  process_active err: {type(e).__name__}: {e}", "ERR")

        write_heartbeat("running", len(notifs))

        if args.once:
            log("--once mode, exiting")
            _inbox_stop.set()
            break

        for _ in range(interval):
            if _SHUTDOWN:
                break
            time.sleep(1)

    _inbox_stop.set()

    write_heartbeat("stopped")
    log(f"Daemon stopped after {cycles} cycle(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
