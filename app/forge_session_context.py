"""
forge_session_context.py - SessionContext moderne Nokido
==========================================================

Successeur SessionContext (Nokido_v13.6.py L2938-2995).
Différences vs v13 :
- RAG via `forge_rag_engine.RAGEngine` (singleton via `forge_app_context`)
- Anchor via `forge_self_correction.anchor_solution` (vrai canal RAG indexé)
- EventBus émission `session.*` (start / message / end)
- Persistence sandbox/session_<id>.json optionnelle
- Pas de couplage UI

API publique :
    from forge_session_context import SessionContext, get_active_session

    ctx = SessionContext(name="naarob_tui")
    ctx.add_message(role="user", text="ping gemini")
    ctx.add_message(role="assistant", text="pong")
    summary = ctx.summarize()             # truncated string
    ctx.anchor_summary(domain="systeme")  # persist en rag_chunks
    ctx.save()                            # sandbox/session_<id>.json
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"

_EVENT_BUS = None


def _emit(topic: str, kind: str, data: dict, agent: str = "SESSION") -> None:
    global _EVENT_BUS
    try:
        if _EVENT_BUS is None:
            import sys

            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_state_manager import EventBus, get_state_manager

            _EVENT_BUS = EventBus(get_state_manager())
        _EVENT_BUS.publish(topic=topic, kind=kind, data=data, agent=agent, trusted=True)
    except Exception as e:
        logger.debug(f"EventBus skipped: {e}")


@dataclass
class SessionMessage:
    role: str  # user | assistant | system | tool
    text: str
    ts: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)


@dataclass
class SessionContext:
    """Historique conversationnel + résumé + ancrage RAG.

    `messages` est un ring buffer borné (default 200).
    `summarize()` agrège un résumé concis. `anchor_summary()` persiste dans
    rag_chunks via anchor_solution (id stable, FTS5 indexé).
    """

    name: str = "session"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    messages: list[SessionMessage] = field(default_factory=list)
    max_messages: int = 200
    domain: str = "systeme"
    extra: dict = field(default_factory=dict)
    _anchored: bool = False

    def __post_init__(self) -> None:
        _emit("session.start", "info", {"name": self.name, "session_id": self.session_id})

    # ── messages ─────────────────────────────────────────────────────────
    def add_message(self, role: str, text: str, meta: Optional[dict] = None) -> SessionMessage:
        msg = SessionMessage(role=role, text=text, meta=meta or {})
        self.messages.append(msg)
        if len(self.messages) > self.max_messages:
            # drop oldest mais garde le 1er (souvent system prompt)
            self.messages = self.messages[:1] + self.messages[-(self.max_messages - 1) :]
        _emit(
            "session.message",
            "info",
            {"session_id": self.session_id, "role": role, "len": len(text), "n_messages": len(self.messages)},
        )
        return msg

    def latest(self, n: int = 10) -> list[SessionMessage]:
        return self.messages[-n:]

    # ── résumé ───────────────────────────────────────────────────────────
    def summarize(self, max_chars: int = 800) -> str:
        """Résumé extractif simple — joindre les derniers messages tronqués.
        Plus tard : pluggable LLM via forge_llm_router."""
        if not self.messages:
            return ""
        lines = []
        for m in self.messages[-20:]:
            txt = (m.text or "").replace("\n", " ").strip()[:120]
            lines.append(f"[{m.role}] {txt}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text

    # ── ancrage RAG ──────────────────────────────────────────────────────
    def anchor_summary(self, domain: Optional[str] = None, problem: str = "") -> bool:
        """Persiste le résumé dans rag_chunks via anchor_solution."""
        if not self.messages:
            return False
        try:
            import sys

            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_self_correction import anchor_solution

            summary = self.summarize(max_chars=1500)
            anchor_solution(
                problem=problem or f"Session {self.name} (n={len(self.messages)})",
                solution=summary,
                example=f"session_id={self.session_id} started={self.started_at}",
                domain=domain or self.domain,
            )
            self._anchored = True
            _emit("session.anchor", "success", {"session_id": self.session_id, "n": len(self.messages)})
            return True
        except Exception as e:
            logger.warning(f"anchor_summary fail: {e}")
            _emit("session.anchor", "error", {"session_id": self.session_id, "err": str(e)[:120]})
            return False

    # ── persistence ──────────────────────────────────────────────────────
    def _state_path(self) -> Path:
        return SANDBOX / f"session_{self.name}_{self.session_id}.json"

    def save(self) -> Optional[Path]:
        try:
            SANDBOX.mkdir(parents=True, exist_ok=True)
            data = {
                "name": self.name,
                "session_id": self.session_id,
                "started_at": self.started_at,
                "domain": self.domain,
                "max_messages": self.max_messages,
                "extra": self.extra,
                "_anchored": self._anchored,
                "messages": [asdict(m) for m in self.messages],
            }
            p = self._state_path()
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return p
        except Exception as e:
            logger.warning(f"save fail: {e}")
            return None

    @classmethod
    def load(cls, path: Path) -> Optional["SessionContext"]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        msgs = [SessionMessage(**m) for m in data.pop("messages", [])]
        ctx = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        ctx.messages = msgs
        return ctx

    def end(self, anchor: bool = True) -> None:
        if anchor and not self._anchored:
            self.anchor_summary()
        self.save()
        _emit(
            "session.end",
            "info",
            {
                "session_id": self.session_id,
                "duration_s": int(time.time() - self.started_at),
                "n_messages": len(self.messages),
            },
        )


# ── Singleton "active session" ─────────────────────────────────────────────

_active: Optional[SessionContext] = None


def get_active_session() -> Optional[SessionContext]:
    return _active


def set_active_session(ctx: SessionContext) -> None:
    global _active
    _active = ctx
