"""
forge_collab_broker.py — Nokido v18.5
Bridge Claude <-> Gemini via API key directe.
Zero CLI, zero OAuth, zero tool calls, zero workflow parasite.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("forge.broker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
ENV = ROOT / "Nokido.env"
HUB_URL = "http://127.0.0.1:8766"


def _env(key: str, default: str = "") -> str:
    """Secure by design — WCM > .env > os.environ via forge_secrets."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret

        val = get_secret(key)
        if val:
            return val
    except Exception:
        pass
    # Fallback minimal si forge_secrets indisponible
    if ENV.exists():
        for line in ENV.read_text(errors="replace").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(key, default)


TOKEN = _env("FORGE_MCP_TOKEN")
API_KEY = _env("GEMINI_API_KEY")
POLL_S = int(_env("BROKER_POLL_S", "15"))
MAX_CHARS = int(_env("BROKER_MAX_PROMPT", "8000"))

# Cascade modèles — du plus léger au plus puissant
# Reset quota chaque jour à minuit (heure Google)
MODEL_CASCADE = [
    "gemini-2.5-flash",  # Tier 1 — Gemini Flash (quota journalier)
    "gemini-2.5-flash-preview-05-20",  # Tier 2 — Flash preview
    "gemini-2.5-pro",  # Tier 3 — Gemini Pro
    "gemini-2.5-pro-preview-05-06",  # Tier 4 — Pro preview
    "__grok__",  # Tier 5 — xAI Grok ($25 crédits)
    "__mistral__",  # Tier 6 — Mistral (1B tokens/mois gratuit)
    "__openrouter__",  # Tier 7 — OpenRouter 29 modèles :free
    "__cohere__",  # Tier 8 — Cohere command-a (1000 req/mois)
    "__groq__",  # Tier 9 — Groq llama (fallback ultime, zéro quota)
]

_seen: set[str] = set()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _already_seen(text: str) -> bool:
    h = _hash(text)
    if h in _seen:
        return True
    _seen.add(h)
    if len(_seen) > 500:
        _seen.clear()
    return False


# ── Hub ───────────────────────────────────────────────────────────────────
def _hub(method: str, params: dict, timeout: int = 8) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    headers = {"Content-Type": "application/json", "X-Agent-Name": "COLLAB_BROKER"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"{HUB_URL}/mcp", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def hub_poll() -> list[str]:
    # ITEM 5 — Mailbox hybride : lire forge_mailbox si disponible (zero reseau)
    mailbox_msgs = []
    try:
        import os as _mo
        import sys as _ms

        _mapp = _mo.path.join(_mo.path.dirname(__file__), "..", "app")
        if _mapp not in _ms.path:
            _ms.path.insert(0, _mapp)
        from nokido_agent.app.forge_mailbox import get_code, pull

        _code = get_code(TOKEN) if TOKEN else ""
        _agent_tokens = {"COLLAB_BROKER": TOKEN} if TOKEN else {}
        if _code:
            _msgs = pull("COLLAB_BROKER", _code, _agent_tokens, limit=20)
            mailbox_msgs = [str(m.get("payload", "")) for m in _msgs if m.get("payload")]
    except Exception:
        pass
    if mailbox_msgs:
        return mailbox_msgs  # zero reseau si mailbox a des messages
    # ── Canal agent_messages (récepteur membranaire inter-agents) ────────────
    # Lit directement la table agent_messages pour agt_gemini — canal distinct
    # de tui_notifications. C'est ici que Claude et le hub écrivent les frames.
    try:
        import json as _jj
        import os as _oe
        import sqlite3 as _sq

        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_db_path import m2m_path as _m2m_path   # scission M2M : suit l'interrupteur sandbox/m2m.switch
        _db = _m2m_path()
        with _sq.connect(_db, timeout=5) as _conn:
            _rows = _conn.execute(
                "SELECT id, payload FROM agent_messages "
                "WHERE (to_agent='agt_gemini' OR to_agent='GEMINI') "
                "AND status='unread' ORDER BY created_at ASC LIMIT 10"
            ).fetchall()
            if _rows:
                _ids = [r[0] for r in _rows]
                _conn.execute(
                    f"UPDATE agent_messages SET status='read' "
                    f"WHERE id IN ({','.join('?' * len(_ids))})",
                    _ids,
                )
                _conn.commit()
                _msgs_out = []
                for _, payload in _rows:
                    try:
                        _msgs_out.append(_jj.loads(payload).get("text", payload))
                    except Exception:
                        _msgs_out.append(str(payload))
                return _msgs_out
    except Exception:
        pass
    # Fallback poll reseau classique
    res = _hub("tools/call", {"name": "hub", "arguments": {"action": "poll"}})
    try:
        raw = res.get("result", {}).get("content", [])
        text = raw[0].get("text", "") if isinstance(raw, list) else str(raw)
        if "Aucune notification" in text or not text.strip():
            return []
        return [n.strip() for n in text.split("---") if len(n.strip()) > 20]
    except Exception:
        return []


def hub_notify(msg: str) -> None:
    _hub("tools/call", {"name": "notify", "arguments": {"message": msg[:4000]}})


def hub_recv() -> list[dict]:
    """Lire les messages JSON-RPC en attente pour agt_gemini."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "hub", "arguments": {"action": "recv", "limit": 5}},
            "id": 1,
        }
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Name": "agt_gemini",
    }  # ← se déclarer comme Gemini
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"{HUB_URL}/mcp", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            res = json.loads(r.read())
        raw = res.get("result", {}).get("content", [])
        text = raw[0].get("text", "") if isinstance(raw, list) else str(raw)
        data = json.loads(text)
        return data.get("messages", [])
    except Exception as e:
        logger.debug(f"hub_recv err: {e}")
        return []


def hub_send_to_claude(reply: str, correlation_id: str = "", model: str = "") -> None:
    """Répondre à Claude via agent_messages JSON-RPC."""
    payload = json.dumps({"text": reply[:3000], "model": model})
    _hub(
        "tools/call",
        {
            "name": "hub",
            "arguments": {
                "action": "send",
                "to": "agt_claude",
                "method": "agent.reply",
                "payload": payload,
                "correlation_id": correlation_id,
            },
        },
    )


# ── Gemini API key directe ────────────────────────────────────────────────
def _call_gemini_api(model: str, prompt: str, timeout: int = 60) -> str | None:
    """Appel REST pur — x-goog-api-key, zéro CLI, zéro tool call."""
    if not API_KEY:
        return None
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={API_KEY}"
    )
    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt[:MAX_CHARS]}]}],
            "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7},
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            ],
        }
    ).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
        return resp["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 429:
            logger.info(f"  {model}: quota 429")
        else:
            logger.debug(f"  {model}: HTTP {e.code} {body[:80]}")
        return None
    except Exception as e:
        logger.debug(f"  {model}: {e}")
        return None


def _call_groq(prompt: str, timeout: int = 30) -> str | None:
    """Fallback Groq — zéro quota journalier."""
    tok = _env("GROQ_API_KEY")
    if not tok:
        return None
    body = json.dumps(
        {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt[:6000]}],
            "max_tokens": 800,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {tok}",
            "User-Agent": "curl/7.88.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Groq err: {type(e).__name__}: {e}")
        return None


def _call_mistral(prompt: str, timeout: int = 30) -> str | None:
    """Mistral AI — 1B tokens/mois gratuit."""
    tok = _env("MISTRAL_API_KEY")
    if not tok:
        return None
    body = json.dumps(
        {
            "model": "mistral-small-latest",
            "messages": [{"role": "user", "content": prompt[:8000]}],
            "max_tokens": 800,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {tok}",
            "User-Agent": "curl/7.88.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.debug(f"Mistral err: {e}")
        return None


def _call_openrouter(prompt: str, timeout: int = 30) -> str | None:
    """OpenRouter — 29 modèles :free, 200 req/j."""
    tok = _env("OPENROUTER_API_KEY")
    if not tok:
        return None
    # Modèles :free fiables en avril 2026
    for model in [
        "google/gemma-3-27b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "qwen/qwen3-coder:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "google/gemma-3-4b-it:free",
    ]:
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:8000]}],
                "max_tokens": 800,
            }
        ).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {tok}",
                "HTTP-Referer": "https://nokido.local",
                "X-Title": "Nokido",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.info(f"OpenRouter {model}: quota")
                continue
            logger.debug(f"OpenRouter {model}: HTTP {e.code}")
        except Exception as e:
            logger.debug(f"OpenRouter err: {e}")
    return None


def _call_cohere(prompt: str, timeout: int = 30) -> str | None:
    """Cohere — 1000 req/mois trial, pipeline RAG natif."""
    tok = _env("COHERE_API_KEY")
    if not tok:
        return None
    body = json.dumps(
        {
            "model": "command-a-03-2025",
            "messages": [{"role": "user", "content": prompt[:8000]}],
            "max_tokens": 800,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.cohere.com/v2/chat",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        content = data.get("message", {}).get("content", [])
        return content[0].get("text", "").strip() if content else None
    except Exception as e:
        logger.debug(f"Cohere err: {e}")
        return None


def _call_grok(prompt: str, timeout: int = 60) -> str | None:
    """xAI Grok — OpenAI-compatible endpoint. Nécessite crédits console.x.ai"""
    tok = _env("XAI_API_KEY")
    if not tok:
        return None
    # Cascade modèles xAI : grok-3-mini (rapide) → grok-3 (puissant)
    for model in ["grok-3-mini", "grok-3", "grok-4.20-reasoning"]:
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:8000]}],
                "max_tokens": 800,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body_err = e.read().decode(errors="replace")
            if "credits" in body_err.lower() or e.code == 403:
                logger.info("Grok: crédits insuffisants")
                return None
            if e.code == 429:
                logger.info(f"Grok {model}: quota")
                continue
            logger.debug(f"Grok {model}: HTTP {e.code}")
        except Exception as e:
            logger.debug(f"Grok err: {e}")
    return None


# Cache modèle fonctionnel
_cached_model: str | None = None
_cached_ts: float = 0.0
CACHE_TTL = 300  # 5 min


def call_gemini(prompt: str) -> tuple[str, str]:
    """Cascade avec cache — retourne (réponse, modèle_utilisé)."""
    global _cached_model, _cached_ts
    now = time.time()

    # Essayer le modèle en cache
    if _cached_model and (now - _cached_ts) < CACHE_TTL:
        if _cached_model == "__groq__":
            out = _call_groq(prompt)
        else:
            out = _call_gemini_api(_cached_model, prompt)
        if out:
            return out, _cached_model
        _cached_model = None

    # Cascade complète
    for model in MODEL_CASCADE:
        logger.info(f"Essai: {model}")
        if model == "__grok__":
            out = _call_grok(prompt)
        elif model == "__mistral__":
            out = _call_mistral(prompt)
        elif model == "__openrouter__":
            out = _call_openrouter(prompt)
        elif model == "__cohere__":
            out = _call_cohere(prompt)
        elif model == "__groq__":
            out = _call_groq(prompt)
        else:
            out = _call_gemini_api(model, prompt)
        if out:
            _cached_model, _cached_ts = model, now
            logger.info(f"Modele actif: {model}")
            return out, model

    return "ERR: tous les modèles en quota épuisé.", "none"


# ── Filtrage ──────────────────────────────────────────────────────────────
import re

TRIGGERS = [
    r"\[.?->?GEMINI.?\]",
    r"MISSION\s*:",
    r"Q[1-4]\s+[A-Z]",
    r"POUR GEMINI",
    r"\[CLAUDE.*GEMINI\]",
]
IGNORES = [
    r"\[GEMINI->\]",
    r"\[GEMINI/",
    r"fichier ecrit",
    r"Mode AUTO",
    r"SENTINEL",
    r"SECRET_GUARD",
]


def _should_process(notif: str) -> bool:
    if len(notif) < 30 or _already_seen(notif):
        return False
    for p in IGNORES:
        if re.search(p, notif, re.I):
            return False
    for p in TRIGGERS:
        if re.search(p, notif, re.I):
            return True
    return False


# ── RAG index ─────────────────────────────────────────────────────────────
def _rag_index(reply: str, model: str) -> None:
    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        eid = f"broker_{int(time.time())}_{_hash(reply)}"
        conn.execute(
            "INSERT OR IGNORE INTO rag_chunks(id,text,source,domain,role_hint,meta,ingested_at)"
            " VALUES(?,?,'forge_collab_broker','collab','GEMINI',?,datetime('now'))",
            # 2026-09-12 : borne des 13 896 chunks coupes pile a 2000.
            (eid, reply, json.dumps({"model": model})),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"rag_index: {e}")


# ── Prompt système ────────────────────────────────────────────────────────
SYSTEM = """Tu es Gemini, agent dans Nokido v18.5. Réponds directement et techniquement.
Outils MCP: run(python|ps1), write, read, query(sql|semantic), rag, task, hub(notify|poll), web_search, ask_claude, ask_gemini.
Format plan JSON si demandé: [{"step":N,"action":"...","tool":"...","args":{},"risk":"safe|medium|destructive"}]
Réponds en français. Pas de préambule. Vas droit au but.

"""


# ── Boucle principale ─────────────────────────────────────────────────────
def run():
    logger.info(f"Broker démarré | poll={POLL_S}s | API_KEY={'OK' if API_KEY else 'ABSENTE'}")
    logger.info(f"Cascade: {MODEL_CASCADE}")

    while True:
        try:
            # ── Canal 1 : notifications hub classiques ───────────────────
            for notif in hub_poll():
                if not _should_process(notif):
                    continue
                logger.info(f"[notify] Message reçu ({len(notif)} chars)")

                t0 = time.perf_counter()
                reply, model = call_gemini(SYSTEM + notif)
                ms = (time.perf_counter() - t0) * 1000

                logger.info(f"Réponse via {model} en {ms:.0f}ms ({len(reply)} chars)")

                ts = time.strftime("%H:%M:%S")
                hub_notify(f"[GEMINI->{model}] {ts}\n\n{reply}")
                _rag_index(reply, model)

            # ── Canal 2 : messages JSON-RPC agent_messages (full-auto) ───
            for msg in hub_recv():
                from_agent = msg.get("from", "agt_claude")
                method = msg.get("method", "")
                payload = msg.get("payload", "")
                corr_id = msg.get("id", "")

                if _already_seen(corr_id):
                    continue
                logger.info(f"[recv] {from_agent} → method={method} ({len(payload)} chars)")

                # Construire le prompt depuis le payload
                try:
                    data = json.loads(payload)
                    prompt_text = data.get("text", payload)
                except Exception:
                    prompt_text = payload

                if not prompt_text or len(prompt_text) < 5:
                    continue

                t0 = time.perf_counter()
                reply, model = call_gemini(SYSTEM + prompt_text)
                ms = (time.perf_counter() - t0) * 1000

                logger.info(f"[recv] Réponse via {model} en {ms:.0f}ms ({len(reply)} chars)")

                # Répondre via JSON-RPC send → agt_claude
                hub_send_to_claude(reply, correlation_id=corr_id, model=model)
                # Aussi notifier le TUI
                ts = time.strftime("%H:%M:%S")
                hub_notify(f"[GEMINI/{model}] {ts} (full-auto)\n\n{reply[:800]}")
                _rag_index(reply, model)

        except KeyboardInterrupt:
            logger.info("Arrêt broker")
            break
        except Exception as e:
            logger.error(f"Erreur boucle: {e}")

        time.sleep(POLL_S)


if __name__ == "__main__":
    run()
