#!/usr/bin/env python3
"""
claude_capture.py — Hook Claude Code : capture UserPromptSubmit + Stop.

Lit JSON sur stdin (format Claude Code hooks), normalise puis ecrit le
tour dans agent_messages via cli_capture_lib.record_turn.

A configurer dans ~/.claude/settings.json :

  "hooks": {
    "UserPromptSubmit": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "\"%USERPROFILE%/miniforge3/python.exe\" \"%USERPROFILE%/Script python IA/LaForge/tools/claude_capture.py\" --event UserPromptSubmit",
        "timeout": 5
      }]
    }],
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "\"%USERPROFILE%/miniforge3/python.exe\" \"%USERPROFILE%/Script python IA/LaForge/tools/claude_capture.py\" --event Stop",
        "timeout": 8
      }]
    }]
  }

Sur Stop, on ne recoit pas la reponse complete dans stdin -- on lit
le transcript_path fourni par le hook payload pour extraire le dernier
tour assistant. Format JSON Claude Code (verifie 2026-05) :

  UserPromptSubmit -> {"session_id": "...", "transcript_path": "...",
                       "cwd": "...", "hook_event_name": "UserPromptSubmit",
                       "prompt": "<user text>"}
  Stop             -> {"session_id": "...", "transcript_path": "...",
                       "stop_hook_active": bool}

Si transcript_path manque ou n'est pas lisible, on log juste l'event
brut dans le canal (mieux que rien).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Resolution de cli_capture_lib peu importe le cwd
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from nokido_agent.tools.cli_capture_lib import (  # type: ignore
    _now_iso,
    normalize_anthropic_content,
    record_turn,
)


def _read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception as e:
        return {"_parse_error": str(e)}


def _last_assistant_turn_from_transcript(path: str) -> dict[str, Any] | None:
    """
    Le transcript Claude Code est un .jsonl. Chaque ligne contient un
    event ou un message. On veut le DERNIER message assistant.
    Format observe (2026-05) : lignes type {"type":"assistant","message":{...}}
    ou {"role":"assistant","content":[...]} selon version.
    """
    try:
        p = Path(path)
        if not p.exists():
            return None
        last_assistant: dict | None = None
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                # Variantes connues du schema
                role = obj.get("role")
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
                if role == "assistant":
                    last_assistant = obj
                elif msg and msg.get("role") == "assistant":
                    last_assistant = msg
                elif obj.get("type") == "assistant" and isinstance(obj.get("message"), dict):
                    last_assistant = obj["message"]
        return last_assistant
    except Exception:
        return None


def _last_user_turn_from_transcript(path: str) -> dict[str, Any] | None:
    """Idem que _last_assistant_turn_from_transcript mais cote user."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        last_user: dict | None = None
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                role = obj.get("role")
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
                if role == "user":
                    last_user = obj
                elif msg and msg.get("role") == "user":
                    last_user = msg
                elif obj.get("type") == "user" and isinstance(obj.get("message"), dict):
                    last_user = obj["message"]
        return last_user
    except Exception:
        return None


def handle_user_prompt_submit(payload: dict) -> int:
    session = payload.get("session_id") or "unknown"
    prompt = payload.get("prompt") or ""
    if not prompt:
        # Fallback : lire le dernier user du transcript
        tp = payload.get("transcript_path")
        if tp:
            last = _last_user_turn_from_transcript(tp)
            if last:
                prompt = normalize_anthropic_content(last.get("content"))
    record_turn(
        surface="claude",
        role="user",
        content=prompt,
        session=session,
        ts=_now_iso(),
        meta={
            "event": "UserPromptSubmit",
            "cwd": payload.get("cwd"),
            "transcript_path": payload.get("transcript_path"),
        },
    )
    return 0


def handle_stop(payload: dict) -> int:
    session = payload.get("session_id") or "unknown"
    tp = payload.get("transcript_path")
    content = ""
    model = None
    if tp:
        last = _last_assistant_turn_from_transcript(tp)
        if last:
            content = normalize_anthropic_content(last.get("content"))
            model = last.get("model")
    if not content:
        content = "[stop event - no transcript content captured]"
    record_turn(
        surface="claude",
        role="assistant",
        content=content,
        session=session,
        ts=_now_iso(),
        meta={
            "event": "Stop",
            "model": model,
            "transcript_path": tp,
            "stop_hook_active": payload.get("stop_hook_active"),
        },
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True, choices=["UserPromptSubmit", "Stop"])
    args = ap.parse_args()
    payload = _read_stdin_json()
    try:
        if args.event == "UserPromptSubmit":
            return handle_user_prompt_submit(payload)
        if args.event == "Stop":
            return handle_stop(payload)
    except Exception:
        # Hook MUST never block Claude Code -> swallow errors
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
