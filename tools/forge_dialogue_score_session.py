# -*- coding: utf-8 -*-
"""
forge_dialogue_score_session.py — AXE 8 : hook fin-de-session.
================================================================
Score les NOUVEAUX échanges de la dernière session Claude CLI et émet la
récompense (dopamine/cortisol) + persiste les réussites en exemplars few-shot.

Watermark par session (sandbox/dialogue_score_watermark.json) → pas de double
comptage si le hook re-tourne (Stop fire à chaque tour). require_next=True : le
dernier assistant sans réaction user est laissé pour la passe suivante.

Lancé par le hook Stop (.claude/settings.local.json). Best-effort, jamais bloquant,
sort 0 toujours (un hook qui plante ne doit pas casser la session).

USAGE : LAFORGE_PYTHON tools/forge_dialogue_score_session.py [--agent claude]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLAUDE_HISTORY = Path.home() / ".claude" / "projects"
GEMINI_HISTORY = Path.home() / ".gemini" / "tmp"
WATERMARK = ROOT / "sandbox" / "dialogue_score_watermark.json"
CHUNK_MIN = 40


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(_extract_text(item["content"]))
        return " ".join(parts).strip()
    if isinstance(content, dict):
        return _extract_text(content.get("text") or content.get("content") or "")
    return str(content).strip()


def _latest_jsonl() -> Path | None:
    if not CLAUDE_HISTORY.exists():
        return None
    cands = list(CLAUDE_HISTORY.glob("*Nokido*")) or list(CLAUDE_HISTORY.iterdir())
    files = []
    for d in cands:
        if d.is_dir():
            files.extend(d.glob("*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _parse_turns(jsonl_path: Path):
    turns = []
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return turns
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mtype = msg.get("type", "")
        if mtype not in ("user", "assistant"):
            continue
        raw = msg.get("message", {})
        content = raw.get("content", "") if isinstance(raw, dict) else raw
        text = _extract_text(content)
        if len(text) >= CHUNK_MIN:
            turns.append((mtype, text))
    return turns


def _latest_gemini_json() -> Path | None:
    if not GEMINI_HISTORY.exists():
        return None
    files = []
    for d in GEMINI_HISTORY.iterdir():
        chats = d / "chats"
        if chats.is_dir():
            files.extend(chats.glob("session-*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _parse_gemini_turns(json_path: Path):
    turns = []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return turns
    for msg in data.get("messages", []):
        mtype = msg.get("type", "")
        if mtype not in ("user", "gemini"):
            continue
        text = _extract_text(msg.get("content", ""))
        if len(text) >= CHUNK_MIN:
            turns.append(("user" if mtype == "user" else "assistant", text))
    return turns


def _load_wm() -> dict:
    try:
        return json.loads(WATERMARK.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_wm(wm: dict) -> None:
    try:
        WATERMARK.parent.mkdir(parents=True, exist_ok=True)
        WATERMARK.write_text(json.dumps(wm, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _score_source(score_fn, path, turns, wm, label):
    """Score les nouveaux échanges d'une session (watermark par session)."""
    if not path or not turns:
        return
    sid = f"{label}:{path.stem}"
    start = int(wm.get(sid, 0))
    try:
        outs = score_fn(turns, start_index=start, require_next=True)
    except Exception:
        return
    n = len(turns)
    new_wm = n if turns[-1][0] == "user" else max(0, n - 1)
    wm[sid] = max(start, new_wm)
    print(f"[dialogue_score] {sid}: {len(outs)} nouveaux échanges scorés (wm={wm[sid]}/{n})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="both", choices=["claude", "gemini", "both"])
    args = ap.parse_args()

    try:
        from nokido_agent.app.forge_dialogue_outcome import score_session_turns
    except Exception:
        return 0

    wm = _load_wm()
    # Apprentissage CENTRAL : Claude ET Gemini nourrissent la même persona.
    if args.agent in ("claude", "both"):
        cj = _latest_jsonl()
        _score_source(score_session_turns, cj, _parse_turns(cj) if cj else [], wm, "claude")
    if args.agent in ("gemini", "both"):
        gj = _latest_gemini_json()
        _score_source(score_session_turns, gj, _parse_gemini_turns(gj) if gj else [], wm, "gemini")
    _save_wm(wm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
