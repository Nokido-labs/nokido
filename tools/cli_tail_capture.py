#!/usr/bin/env python3
"""
cli_tail_capture.py — Tail-watcher pour Gemini CLI + Cline.

Les deux CLIs persistent leur conversation sur disque ; ce script lit
les nouveaux tours depuis la derniere execution et les ingere dans
agent_messages via cli_capture_lib.record_turn.

Sources :
  - Gemini CLI : %USERPROFILE%/.gemini/tmp/<project>/chats/session-*.jsonl
                 (1 ligne JSON par tour, premiere ligne = metadata session)
  - Cline      : %USERPROFILE%/AppData/Roaming/Code/User/globalStorage/
                 rooveterinaryinc.roo-cline/tasks/<task_id>/
                 api_conversation_history.json (tableau JSON complet)

Cursor :
  Stocke par fichier {"size": int, "mtime": float, "count": int} dans
  sandbox/cli_capture_cursors.json. On ne reingere que les tours nouveaux.

Usage :
  one-shot :  LAFORGE_PYTHON tools/cli_tail_capture.py
  daemon   :  LAFORGE_PYTHON tools/cli_tail_capture.py --watch --interval 30
  source   :  ajouter --gemini-only ou --cline-only pour cibler
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
# RACINE aussi (2026-09-24, mesure) : `nokido_agent` est un dossier de la RACINE ; n'ajouter
# que tools/ laissait NokidoCapture mourir en ModuleNotFoundError a chaque demarrage.
_RACINE_AMORCE = str(_HERE.parent)
if _RACINE_AMORCE not in sys.path:
    sys.path.insert(0, _RACINE_AMORCE)

from datetime import UTC

from nokido_agent.tools.cli_capture_lib import (  # type: ignore
    normalize_anthropic_content,
    record_turn,
)

ROOT = _HERE.parent
CURSOR_FILE = ROOT / "sandbox" / "cli_capture_cursors.json"
CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)

GEMINI_CHATS_GLOBS = [
    __import__("os").path.expanduser("~/.gemini/tmp/*/chats/session-*.jsonl"),
]
CLINE_TASKS_DIR = Path(
    __import__("os").path.expanduser("~/AppData/Roaming/Code/User/globalStorage/rooveterinaryinc.roo-cline/tasks")
)
# Claude Code transcripts : ~/.claude/projects/<sanitized>/<session-uuid>.jsonl
CLAUDE_TRANSCRIPTS_GLOB = __import__("os").path.expanduser("~/.claude/projects/**/*.jsonl")


# ------------------------------------------------------------------ #
# Cursor persistence                                                 #
# ------------------------------------------------------------------ #


def _load_cursors() -> dict[str, dict[str, Any]]:
    if not CURSOR_FILE.exists():
        return {}
    try:
        return json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cursors(cursors: dict[str, dict[str, Any]]) -> None:
    try:
        CURSOR_FILE.write_text(
            json.dumps(cursors, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ------------------------------------------------------------------ #
# Gemini CLI                                                          #
# ------------------------------------------------------------------ #


def _gemini_session_files() -> list[Path]:
    import glob

    out: list[Path] = []
    for pattern in GEMINI_CHATS_GLOBS:
        for p in glob.glob(pattern):
            out.append(Path(p))
    return out


def _gemini_normalize_content(content: Any) -> tuple[str, str]:
    """Retourne (role, text) pour un tour Gemini.
    Schema observe : type in {user, model, tool, system, info},
    content = list[{text}] | list[functionCall] | str
    """
    if isinstance(content, str):
        return ("text", content)
    if isinstance(content, list):
        parts: list[str] = []
        for blk in content:
            if isinstance(blk, dict):
                if "text" in blk:
                    parts.append(blk["text"])
                elif "functionCall" in blk:
                    fc = blk["functionCall"]
                    parts.append(
                        f"[functionCall:{fc.get('name', '?')}] "
                        f"{json.dumps(fc.get('args', {}), ensure_ascii=False)[:500]}"
                    )
                elif "functionResponse" in blk:
                    fr = blk["functionResponse"]
                    parts.append(
                        f"[functionResponse:{fr.get('name', '?')}] "
                        f"{json.dumps(fr.get('response', {}), ensure_ascii=False)[:1000]}"
                    )
                else:
                    parts.append(json.dumps(blk, ensure_ascii=False)[:500])
            else:
                parts.append(str(blk))
        return ("text", "\n".join(p for p in parts if p))
    return ("text", json.dumps(content, ensure_ascii=False))


def capture_gemini(verbose: bool = False) -> int:
    cursors = _load_cursors()
    inserted = 0
    for fp in _gemini_session_files():
        key = f"gemini::{fp.as_posix()}"
        try:
            stat = fp.stat()
        except Exception:
            continue
        cur = cursors.get(key, {"count": 0, "size": 0, "mtime": 0.0})
        # Reset si fichier shrinked (truncate detecte)
        if stat.st_size < cur.get("size", 0):
            cur = {"count": 0, "size": 0, "mtime": 0.0}
        if stat.st_size == cur.get("size") and stat.st_mtime == cur.get("mtime"):
            continue  # rien a faire

        try:
            with fp.open("r", encoding="utf-8", errors="ignore") as f:
                lines = [l for l in f if l.strip()]
        except Exception:
            continue

        skip = cur.get("count", 0)
        session_id = fp.stem  # nom du fichier suffit
        new_count = 0
        for idx, line in enumerate(lines):
            if idx < skip:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            # Premiere ligne = metadata session, pas un tour
            if "kind" in obj and "sessionId" in obj and "type" not in obj:
                new_count += 1
                continue
            ttype = obj.get("type", "unknown")
            if ttype in ("user", "model", "tool", "assistant"):
                role_map = {"model": "assistant", "tool": "tool"}
                role = role_map.get(ttype, ttype)
                _, text = _gemini_normalize_content(obj.get("content"))
                ts = obj.get("timestamp")
                meta = {"event_id": obj.get("id"), "type": ttype}
                if record_turn(
                    surface="gemini",
                    role=role,
                    content=text,
                    session=obj.get("sessionId") or session_id,
                    ts=ts,
                    meta=meta,
                ):
                    inserted += 1
            new_count += 1

        cursors[key] = {
            "count": len(lines),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
        if verbose:
            print(f"[gemini] {fp.name}: {new_count - skip} new lines, {inserted} so far")

    _save_cursors(cursors)
    return inserted


# ------------------------------------------------------------------ #
# Cline                                                               #
# ------------------------------------------------------------------ #


def _cline_task_dirs() -> list[Path]:
    if not CLINE_TASKS_DIR.exists():
        return []
    return [
        p
        for p in CLINE_TASKS_DIR.iterdir()
        if p.is_dir() and (p / "api_conversation_history.json").exists()
    ]


def capture_cline(verbose: bool = False) -> int:
    cursors = _load_cursors()
    inserted = 0
    for task_dir in _cline_task_dirs():
        hist = task_dir / "api_conversation_history.json"
        key = f"cline::{task_dir.name}"
        try:
            stat = hist.stat()
        except Exception:
            continue
        cur = cursors.get(key, {"count": 0, "size": 0, "mtime": 0.0})
        if stat.st_size < cur.get("size", 0):
            cur = {"count": 0, "size": 0, "mtime": 0.0}
        if stat.st_size == cur.get("size") and stat.st_mtime == cur.get("mtime"):
            continue

        try:
            data = json.loads(hist.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue

        skip = cur.get("count", 0)
        new_count = 0
        for idx, entry in enumerate(data):
            if idx < skip:
                continue
            if not isinstance(entry, dict):
                new_count += 1
                continue
            role = entry.get("role", "unknown")
            text = normalize_anthropic_content(entry.get("content"))
            # Cline stocke parfois le ts en ms
            ts_raw = entry.get("ts")
            ts_iso = None
            if isinstance(ts_raw, (int, float)):
                from datetime import datetime

                ts_iso = datetime.fromtimestamp(ts_raw / 1000.0, tz=UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            if record_turn(
                surface="cline",
                role=role,
                content=text,
                session=task_dir.name,
                ts=ts_iso,
                meta={"task_id": task_dir.name, "idx": idx},
            ):
                inserted += 1
            new_count += 1

        cursors[key] = {
            "count": len(data),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
        if verbose:
            print(f"[cline] {task_dir.name}: {new_count - skip} new entries, {inserted} so far")

    _save_cursors(cursors)
    return inserted


# ------------------------------------------------------------------ #
# Claude Code                                                         #
# ------------------------------------------------------------------ #


def _claude_transcript_files() -> list[Path]:
    import glob as _glob

    out: list[Path] = []
    for p in _glob.glob(CLAUDE_TRANSCRIPTS_GLOB, recursive=True):
        fp = Path(p)
        try:
            if fp.stat().st_size > 100:
                out.append(fp)
        except Exception:
            pass
    return out


def capture_claude(verbose: bool = False) -> int:
    cursors = _load_cursors()
    inserted = 0
    for fp in _claude_transcript_files():
        key = f"claude::{fp.as_posix()}"
        try:
            stat = fp.stat()
        except Exception:
            continue
        cur = cursors.get(key, {"count": 0, "size": 0, "mtime": 0.0})
        if stat.st_size < cur.get("size", 0):
            cur = {"count": 0, "size": 0, "mtime": 0.0}
        if stat.st_size == cur.get("size") and stat.st_mtime == cur.get("mtime"):
            continue

        try:
            with fp.open("r", encoding="utf-8", errors="ignore") as f:
                lines = [ln for ln in f if ln.strip()]
        except Exception:
            continue

        skip = cur.get("count", 0)
        new_count = 0
        for idx, line in enumerate(lines):
            if idx < skip:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                new_count += 1
                continue

            # Format Claude Code : obj.type = "user"|"assistant"|"tool"|"summary"
            obj_type = obj.get("type", "")
            if obj_type not in ("user", "assistant"):
                new_count += 1
                continue

            msg = obj.get("message", {})
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                new_count += 1
                continue

            content = normalize_anthropic_content(msg.get("content", ""))
            if not content.strip():
                new_count += 1
                continue

            ts = obj.get("timestamp")
            session = obj.get("sessionId") or fp.stem

            if record_turn(
                surface="claude",
                role=role,
                content=content,
                session=session,
                ts=ts,
                meta={"uuid": obj.get("uuid"), "model": msg.get("model")},
            ):
                inserted += 1
            new_count += 1

        cursors[key] = {
            "count": len(lines),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
        if verbose:
            print(f"[claude] {fp.name}: {new_count - skip} new lines, {inserted} so far")

    _save_cursors(cursors)
    return inserted


# ------------------------------------------------------------------ #
# Main                                                                #
# ------------------------------------------------------------------ #


def run_once(do_gemini: bool, do_cline: bool, do_claude: bool, verbose: bool) -> int:
    n = 0
    if do_gemini:
        n += capture_gemini(verbose=verbose)
    if do_cline:
        n += capture_cline(verbose=verbose)
    if do_claude:
        n += capture_claude(verbose=verbose)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="boucle infinie au lieu d un one-shot")
    ap.add_argument(
        "--interval", type=int, default=30, help="secondes entre passes en mode --watch"
    )
    ap.add_argument("--gemini-only", action="store_true")
    ap.add_argument("--cline-only", action="store_true")
    ap.add_argument("--claude-only", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    exclusive = sum([args.gemini_only, args.cline_only, args.claude_only])
    do_gemini = args.gemini_only or exclusive == 0
    do_cline = args.cline_only or exclusive == 0
    do_claude = args.claude_only or exclusive == 0

    if not args.watch:
        n = run_once(do_gemini, do_cline, do_claude, args.verbose)
        print(f"[cli_tail_capture] inserted {n} new turn(s)")
        return 0

    print(
        f"[cli_tail_capture] watch mode, interval={args.interval}s "
        f"(gemini={do_gemini} cline={do_cline} claude={do_claude})"
    )
    while True:
        try:
            n = run_once(do_gemini, do_cline, do_claude, args.verbose)
            if n and args.verbose:
                print(f"[cli_tail_capture] +{n} turn(s)")
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"[cli_tail_capture] pass error: {e}", file=sys.stderr)
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
