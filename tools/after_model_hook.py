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

# ── 1. Quota tracking ──────────────────────────────────────────────────────
model = os.environ.get("GEMINI_MODEL", "")
input_tok = int(get_secret("GEMINI_INPUT_TOKENS") or 0 or 0)
output_tok = int(get_secret("GEMINI_OUTPUT_TOKENS") or 0 or 0)

if model:
    state = {}
    try:
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass

    # Mapping des quotas. Chaque modèle possède son propre bucket.
    pool_map = {
        "gemini-3.1-pro-preview": "preview_pro",
        "gemini-3.1-flash-lite-preview": "preview_lite",
        "gemini-2.5-pro": "pro",
        "gemini-2.5-flash": "flash",
        "gemini-2.5-flash-lite": "flash_lite",  # corrected
    }
    pool = pool_map.get(model, "unknown")
    tokens = input_tok + output_tok
    key = f"tokens_{pool}"
    state[key] = state.get(key, 0) + tokens
    state["last_model"] = model
    state["last_tokens"] = tokens
    state["last_update"] = datetime.now().isoformat()
    state["ts"] = datetime.now().isoformat()

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


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
