"""forge_collab.py — Canal de discussion fichier-partagé multi-agents

Pattern : un fichier markdown par sujet dans sandbox/collab/<topic>.md.
Chaque agent (CLAUDE, GEMINI, CODEX, user, etc.) append ses messages avec
un préfixe `[<AGENT> @ ISO_TS]`. Lecture = read_text. Pas de truncation,
pas de bridge MCP, pas de notify cloud. Robuste sur reload.

Usage côté Python :
    from forge_collab import append, read, tail
    append("ui_unification", "CLAUDE", "Phase 1 livrée. Tu prends Phase 2 ?")
    msgs = read("ui_unification", since_ts="2026-04-30T00:00:00")
    tail("ui_unification", n=10)

Usage côté autre LLM (lecture brute) :
    Read sandbox/collab/<topic>.md   # via tool de lecture standard

Pourquoi ce module :
- handle_notify côté hub a un fail-open silencieux (P1 prioritaire)
- daemon Gemini reçoit un payload tronqué via tools/call name=poll
- Conséquence : briefs riches perdus, "Reply sent (14 chars)" = ACK only
- Solution : artefacts persistants ; canal de notif sert juste de pointer

Version 1.0 — 2026-04-30
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLAB_DIR = ROOT / "sandbox" / "collab"
_LOCK = threading.Lock()


def _safe_topic(topic: str) -> str:
    """Sanitize : alphanum + - + _, max 64 chars. Pas de path traversal."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in topic)[:64]
    if not safe:
        raise ValueError("topic vide après sanitize")
    return safe


def _path(topic: str) -> Path:
    COLLAB_DIR.mkdir(parents=True, exist_ok=True)
    return COLLAB_DIR / f"{_safe_topic(topic)}.md"


def append(topic: str, sender: str, message: str, *, tags: list[str] | None = None) -> dict:
    """Append un message. Crée le fichier si absent (avec entête)."""
    path = _path(topic)
    sender = (sender or "UNKNOWN").upper()
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    tag_str = " ".join(f"#{t}" for t in (tags or []))

    header_block = (
        f"# Collab — {_safe_topic(topic)}\n\n"
        f"Canal de discussion partagée multi-agents (forge_collab).\n"
        f"Format : `## [<AGENT> @ ISO_TS] [tags...]` puis contenu markdown.\n"
        f"Lire : `Read sandbox/collab/{_safe_topic(topic)}.md`.\n\n"
        f"---\n\n"
    )

    block = f"## [{sender} @ {ts}] {tag_str}".rstrip() + "\n\n"
    block += message.rstrip() + "\n\n"

    with _LOCK:
        if not path.exists():
            path.write_text(header_block + block, encoding="utf-8")
        else:
            with path.open("a", encoding="utf-8") as f:
                f.write(block)
    return {"ok": True, "path": str(path), "ts": ts, "sender": sender}


def read(topic: str, since_ts: str | None = None) -> str:
    """Renvoie le contenu complet (ou depuis since_ts ISO si filtre)."""
    path = _path(topic)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not since_ts:
        return text
    # Filtre approximatif : split sur "## [" et keep blocks where ts > since_ts
    out = []
    cursor = 0
    parts = text.split("## [")
    out.append(parts[0])
    for p in parts[1:]:
        # extraction ts entre "@ " et "]"
        try:
            head, _ = p.split("]", 1)
            _, ts_iso = head.split("@ ", 1)
            if ts_iso.strip() > since_ts:
                out.append("## [" + p)
        except ValueError:
            out.append("## [" + p)  # garbage = keep
    return "".join(out)


def tail(topic: str, n: int = 10) -> str:
    """Renvoie les n derniers blocs (par séparateur '## [')."""
    path = _path(topic)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    parts = text.split("## [")
    if len(parts) <= 1:
        return text
    # Garde l'entête + n derniers blocs
    return parts[0] + "".join("## [" + p for p in parts[-n:])


def list_topics() -> list[dict]:
    """Liste tous les topics + size + mtime."""
    if not COLLAB_DIR.exists():
        return []
    out = []
    for p in sorted(COLLAB_DIR.glob("*.md")):
        st = p.stat()
        out.append(
            {
                "topic": p.stem,
                "path": str(p),
                "size_bytes": st.st_size,
                "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
            }
        )
    return out


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(description="forge_collab — canal fichier multi-agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_app = sub.add_parser("append")
    p_app.add_argument("topic")
    p_app.add_argument("--sender", default=os.environ.get("LAFORGE_AGENT", "CLAUDE"))
    p_app.add_argument("--message", required=True)
    p_app.add_argument("--tags", nargs="*", default=[])
    p_read = sub.add_parser("read")
    p_read.add_argument("topic")
    p_read.add_argument("--since")
    p_tail = sub.add_parser("tail")
    p_tail.add_argument("topic")
    p_tail.add_argument("--n", type=int, default=10)
    sub.add_parser("list")

    args = ap.parse_args()
    if args.cmd == "append":
        print(json.dumps(append(args.topic, args.sender, args.message, tags=args.tags), indent=2))
    elif args.cmd == "read":
        print(read(args.topic, since_ts=args.since))
    elif args.cmd == "tail":
        print(tail(args.topic, n=args.n))
    elif args.cmd == "list":
        print(json.dumps(list_topics(), indent=2, ensure_ascii=False))
