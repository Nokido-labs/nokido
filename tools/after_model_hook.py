#!/usr/bin/env python3
"""
after_model_hook.py — Hook AfterModel Gemini CLI
1. Écrit les tokens consommés dans RAG/quota_state.json
2. Poll hub volatile queue → stdout = contexte injecté au prochain tour Gemini
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Windows : FORCER UTF-8 sur stdout. Sinon les messages inbox (emojis 📬, accents, CJK 一切顺利)
# -> cp1252 -> UnicodeEncodeError MID-print -> sortie tronquée/mojibake -> ParserError Gemini ->
# éjection "au bout d'un moment". errors='replace' = ceinture (jamais de crash d'encodage).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "RAG" / "quota_state.json"
HUB_URL = "http://127.0.0.1:8766/mcp"
AGENT_ID = "agt_gemini"

sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402

HUB_TOKEN = get_secret("FORGE_TOKEN_GEMINI") or ""

def resolve_caller_model() -> str:
    """Résout le modèle de l'appelant en priorité sur toute variable globale figée.

    Ordre de priorité (décision owner 15/10/2026) :
    1. Argument CLI passé au hook (ex: --model <m>, ou argument nommant un modèle)
    2. Variable d'environnement de l'appelant CLI (GEMINI_CLI_MODEL, AGY_MODEL)
    3. Configuration active du client CLI (~/.gemini/settings.json -> model.name)
    4. Variable d'environnement GEMINI_MODEL (repli)
    """
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a in ("--model", "-m") and i + 1 < len(args):
            return args[i + 1].strip()
        if a.startswith("--model="):
            return a.split("=", 1)[1].strip()
        if not a.startswith("-") and ("gemini" in a.lower() or "pro" in a.lower() or "flash" in a.lower()):
            return a.strip()

    for k in ("GEMINI_CLI_MODEL", "AGY_MODEL"):
        val = os.environ.get(k, "").strip()
        if val:
            return val

    try:
        settings_path = Path.home() / ".gemini" / "settings.json"
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            m = data.get("model", {}).get("name", "").strip()
            if m:
                return m
    except Exception:  # muet-ok : repli suit
        pass

    return os.environ.get("GEMINI_MODEL", "").strip()


def track_quota(model_name: str, input_tokens: int, output_tokens: int, state_file: Path = STATE_FILE) -> dict:
    """Comptabilise les tokens consommés sous le bucket du modèle de l'appelant."""
    if not model_name:
        return {}
    state = {}
    try:
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:  # muet-ok : state reste vide
        pass

    # Mapping des quotas. Chaque modèle possède son propre bucket.
    pool_map = {
        "gemini-3.1-pro-preview": "preview_pro",
        "gemini-3.1-flash-lite-preview": "preview_lite",
        "gemini-2.5-pro": "pro",
        "gemini-2.5-flash": "flash",
        "gemini-2.5-flash-lite": "flash_lite",
        "gemini-flash-lite-latest": "flash_lite",
    }
    pool = pool_map.get(model_name, "unknown")
    tokens = input_tokens + output_tokens
    key = f"tokens_{pool}"
    state[key] = state.get(key, 0) + tokens
    state["last_model"] = model_name
    state["last_tokens"] = tokens
    state["last_update"] = datetime.now().isoformat()
    state["ts"] = datetime.now().isoformat()

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


# ── 1. Quota tracking ──────────────────────────────────────────────────────
model = resolve_caller_model()
input_tok = int(get_secret("GEMINI_INPUT_TOKENS") or 0 or 0)
output_tok = int(get_secret("GEMINI_OUTPUT_TOKENS") or 0 or 0)

if model:
    track_quota(model, input_tok, output_tok)


# ── 2. Poll hub volatile queue → inject as Gemini context ─────────────────
def _hub_call(tool: str, args: dict) -> dict:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    req = urllib.request.Request(
        HUB_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {HUB_TOKEN}",
            "X-Agent-Name": "GEMINI",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _result_text(resp: dict) -> str:
    raw = resp.get("result", {})
    if isinstance(raw, dict):
        content = raw.get("content", [])
        return content[0].get("text", "") if content else ""
    return str(raw) if raw else ""


_NOISE = ("[DAEMON", "[DAEMON→POLL]", "Message deposé en boite")


def _is_noise(text: str) -> bool:
    return any(n in text for n in _NOISE)


def _parse_poll(text: str) -> list[str]:
    if not text or text.lower().strip(".\n ") in {"aucune notification", "", "none", "null"}:
        return []
    try:
        data = json.loads(text)
        msgs = (
            data if isinstance(data, list) else data.get("messages", data.get("notifications", []))
        )
        return [str(m) for m in msgs if m and not _is_noise(str(m))]
    except Exception:
        return [] if _is_noise(text) else [text]


def _parse_whoami(text: str) -> list[str]:
    if not text:
        return []
    out = []
    try:
        data = json.loads(text)
        # Unread messages (persistent mailbox)
        for m in data.get("unread", []):
            t = m.get("text", "") if isinstance(m, dict) else str(m)
            if t and not _is_noise(t):
                frm = m.get("from", "?") if isinstance(m, dict) else "?"
                out.append(f"[msg:{frm}] {t[:300]}")
        # Interrupted jobs
        for j in data.get("jobs_interrupted", []):
            if isinstance(j, dict):
                out.append(f"[job:{j.get('id', '?')}] {j.get('theme', '')[:120]}")
    except Exception:
        pass
    return out


try:
    lines = []

    # volatile poll queue
    poll_text = _result_text(_hub_call("hub", {"action": "poll"}))
    lines += _parse_poll(poll_text)

    # persistent mailbox
    whoami_text = _result_text(_hub_call("hub", {"action": "whoami"}))
    lines += _parse_whoami(whoami_text)

    if lines:
        print("\n[HOOK:INBOX]", flush=True)
        for ln in lines:
            print(f"  • {ln}", flush=True)
        print("[/HOOK:INBOX]\nTraite ces elements avant de continuer.", flush=True)

except urllib.error.URLError:
    pass
except Exception:
    pass
