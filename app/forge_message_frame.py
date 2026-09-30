# -*- coding: utf-8 -*-
"""
forge_message_frame.py — Enveloppe JSON normalisée inter-agents
================================================================
Nokido est le tronc cérébral. Claude et Gemini sont des workers périphériques.
Toute communication transite par ce format — jamais de texte libre brut.

STRUCTURE :
  MessageFrame = enveloppe complète routée par Nokido
  Inbox        = file volatile en mémoire par agent (asyncio.Queue)
  CQRS         = archive (agent_messages) ≠ inbox (volatile Queue)

FLUX :
  handle_notify(msg)
    → 1. Archive dans agent_messages (EVENTBUS_ARCHIVE — immuable)
    → 2. Parse destinataire
    → 3. Push dans INBOX_<agent> (Queue volatile)
    → 4. SSE /inbox/<agent> se réveille → push au daemon

RÉACTIVITÉ : ms (SSE long-poll) au lieu de 20s (daemon poll)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


# ── TOOL DEFINITION (pour injection dans les payloads délégués) ───────────────


@dataclass
class ToolDef:
    """Définition d'un outil MCP injectable dans une enveloppe."""

    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    min_ring: int = 0  # ring minimum requis pour recevoir ce tool

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


# ── MESSAGE FRAME ─────────────────────────────────────────────────────────────


@dataclass
class MessageFrame:
    """
    Enveloppe normalisée pour tout échange inter-agents via Nokido.

    Nokido construit l'enveloppe, la valide, l'archive et la distribue.
    Les agents périphériques (Claude, Gemini) ne se parlent JAMAIS directement.
    """

    # Identité
    job_id: str = ""  # ID du job parent (watch_job, chain_node...)
    frame_id: str = ""  # Hash unique de cette enveloppe
    from_agent: str = "agt_laforge"
    to_agent: str = ""  # agt_gemini | agt_claude | agt_daemon | agt_hub

    # Action + Intention (routage sémantique)
    action: str = "task"  # task | reply | ping | ack | error | status
    intent: str = ""  # intention machine-readable: exec_python | query_rag |
    # notify_agent | request_relay | report_status | escalate
    priority: int = 5  # 0=urgent, 5=normal, 9=background

    # Contenu — séparation signal / charge
    parameters: dict = field(default_factory=dict)  # args structurés (charge lourde)
    text: str = ""  # résumé lisible court (≤120 chars)
    payload_ref: str = ""  # pointeur vers payload lourd (RAG id ou path)
    result: Any = None  # résultat si reply

    # Outils disponibles (injectés par Nokido pour éviter les "je ne peux pas")
    tool_defs: list[dict] = field(default_factory=list)

    # État
    status: str = "pending"  # pending | delivered | read | done | error
    ttl_s: int = 0  # 0 = adaptatif (calculé par ttl_for_action)
    created_at: str = ""
    read_at: str = ""

    def __post_init__(self):
        # Normalise identites : collapse double-prefixe agt_agt_ + alias agy==antigravity
        for _f in ("from_agent", "to_agent"):
            _v = getattr(self, _f) or ""
            while _v.lower().startswith("agt_agt_"):
                _v = _v[4:]
            if _v.lower() in ("agt_agy", "agy"):
                _v = "agt_antigravity"
            setattr(self, _f, _v)
        now = datetime.now(tz=timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.frame_id:
            raw = f"{self.from_agent}{self.to_agent}{self.action}{time.time()}"
            self.frame_id = "frm_" + hashlib.md5(raw.encode()).hexdigest()[:12]
        if not self.job_id:
            self.job_id = self.frame_id
        # Signer automatiquement si destinataire connu (JWT HS256)
        if not hasattr(self, "_jwt_token"):
            try:
                import sys as _jms, os as _jmo

                _japp = str(_jmo.path.join(_jmo.path.dirname(__file__), "..", "app"))
                if _japp not in _jms.path:
                    _jms.path.insert(0, _japp)
                from nokido_agent.app.forge_jwt_router import forge_frame_token

                object.__setattr__(
                    self,
                    "_jwt_token",
                    forge_frame_token(
                        from_agent=self.from_agent,
                        to_agent=self.to_agent,
                        action=self.action,
                        priority=self.priority,
                    ),
                )
            except Exception:
                pass

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, s: str) -> "MessageFrame":
        d = json.loads(s)
        # Gérer tool_defs comme liste de dict (pas de ToolDef objects)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def is_expired(self) -> bool:
        ttl = self.ttl_s if self.ttl_s > 0 else ttl_for_action(self.action, self.parameters)
        if ttl == 0:
            return False  # permanent
        age = time.time() - datetime.fromisoformat(self.created_at).timestamp()
        return age > ttl

    def validate(self) -> tuple[bool, str]:
        """Valide la présence des champs obligatoires."""
        if not self.to_agent:
            return False, "to_agent manquant"
        if not self.action:
            return False, "action manquante"
        if self.action == "task" and not self.parameters and not self.text:
            return False, "task sans parameters ni text"
        return True, "ok"


# ── INBOX REGISTRY (files volatiles en mémoire par agent) ────────────────────


def ttl_for_action(action: str, parameters: dict) -> int:
    """
    TTL adaptatif selon la complexité de la tâche.
    Correction Gemini Ultra Web 2026-04-28 — une horloge nerveuse
    ne doit pas tuer un agent en plein crawl.
    """
    if action == "reply" or action == "ack" or action == "ping":
        return 60  # réponses courtes : 1 min
    if action == "status":
        return 120  # status check : 2 min
    if action == "task":
        # Estimer la complexité depuis les paramètres
        has_expected_output = bool(parameters.get("expected_output"))
        has_chain = bool(parameters.get("chain_id") or parameters.get("steps"))
        has_crawl = "crawl" in str(parameters).lower()
        if has_chain or (has_expected_output and has_crawl):
            return 900  # pipeline complexe (chain_executor + crawl) : 15 min
        if has_expected_output:
            return 600  # tâche avec livrable attendu : 10 min
        return 300  # tâche simple : 5 min
    return 300  # défaut : 5 min


class InboxRegistry:
    """
    Registry des files d'attente asyncio par agent.
    CQRS : séparé de l'archive SQLite (agent_messages).
    Volatile : perdu au restart, mais c'est voulu (les tâches non lues
    sont reconstruites depuis agent_messages au boot).
    """

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def get_queue(self, agent_id: str) -> asyncio.Queue:
        """Retourne la queue de l'agent, la crée si absente."""
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue(maxsize=500)
        return self._queues[agent_id]

    def push(self, frame: MessageFrame) -> bool:
        """
        Push non-bloquant dans la queue de l'agent destinataire.
        Retourne False si la queue est pleine (backpressure).
        """
        q = self.get_queue(frame.to_agent)
        try:
            q.put_nowait(frame)
            return True
        except asyncio.QueueFull:
            return False

    async def pop(self, agent_id: str, timeout: float = 30.0) -> MessageFrame | None:
        """
        Pop avec timeout (long-polling).
        Retourne None si timeout — le client SSE renvoie un ping.
        """
        q = self.get_queue(agent_id)
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def size(self, agent_id: str) -> int:
        return self._queues.get(agent_id, asyncio.Queue()).qsize()

    def all_sizes(self) -> dict[str, int]:
        return {k: q.qsize() for k, q in self._queues.items()}


# ── SINGLETON ─────────────────────────────────────────────────────────────────

INBOX = InboxRegistry()


# ── TOOL DEFS CATALOGUE (injectées par Nokido dans les délégations) ─────────

# Catalogue complet — filtré par ring dans make_task_frame()
# Correction Gemini Ultra Web : moins de bruit = moins de confusion sémantique
# ring=0 : tous les tools | ring=1 : pas write | ring=2+ : read-only
LAFORGE_TOOL_DEFS_BY_RING: dict[int, list["ToolDef"]] = {}  # peuplé après la liste

LAFORGE_TOOL_DEFS = [
    ToolDef("query", "SQL sur embeddings.db", {"sql": {"type": "string", "description": "Requête SQL"}}, min_ring=0),
    ToolDef(
        "hub",
        "Actions hub Nokido",
        {"action": {"type": "string", "enum": ["poll", "notify", "get_mode"]}, "message": {"type": "string"}},
        min_ring=0,
    ),
    ToolDef(
        "run", "Exécution Python ou setup_check", {"action": {"type": "string"}, "code": {"type": "string"}}, min_ring=0
    ),
    ToolDef(
        "write",
        "Écriture fichier (ring=0 uniquement)",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        min_ring=0,
    ),
    ToolDef("auto_test", "Vérification AST Python", {"filepath": {"type": "string"}}, min_ring=0),
    ToolDef("read", "Lecture fichier ou logs", {"action": {"type": "string"}, "path": {"type": "string"}}, min_ring=1),
    ToolDef(
        "biblio",
        "Gestion bibliographie",
        {
            "action": {"type": "string", "enum": ["list", "promote", "reject", "extract"]},
            "entry_id": {"type": "string"},
        },
        min_ring=1,
    ),
    ToolDef(
        "rag",
        "Recherche sémantique RAG",
        {"action": {"type": "string", "enum": ["search", "index"]}, "topic": {"type": "string"}},
        min_ring=2,
    ),
]


def tools_for_ring(ring: int = 0) -> list["ToolDef"]:
    """Retourne uniquement les tools accessibles pour ce ring."""
    return [t for t in LAFORGE_TOOL_DEFS if t.min_ring <= ring]


def make_task_frame(
    to_agent: str,
    action: str,
    parameters: dict,
    from_agent: str = "agt_laforge",
    job_id: str = "",
    text: str = "",
    inject_tools: bool = True,
    priority: int = 5,
    ttl_s: int = 0,  # 0 = adaptatif (ttl_for_action)
    ring: int = 0,  # ring du destinataire — filtre les tool_defs
) -> MessageFrame:
    """
    Construit une enveloppe de délégation complète depuis Nokido.
    Injecte automatiquement les tool_defs pour éviter les "je ne peux pas".
    """
    frame = MessageFrame(
        from_agent=from_agent,
        to_agent=to_agent,
        action=action,
        parameters=parameters,
        text=text,
        job_id=job_id,
        priority=priority,
        ttl_s=ttl_s,
        tool_defs=[t.to_dict() for t in tools_for_ring(ring)] if inject_tools else [],
    )
    ok, reason = frame.validate()
    if not ok:
        raise ValueError(f"MessageFrame invalide: {reason}")
    return frame


def make_reply_frame(
    original: MessageFrame,
    result: Any,
    status: str = "done",
    text: str = "",
) -> MessageFrame:
    """Construit une réponse à une enveloppe reçue."""
    return MessageFrame(
        from_agent=original.to_agent,
        to_agent=original.from_agent,
        action="reply",
        job_id=original.job_id,
        parameters={},
        result=result,
        text=text,
        status=status,
    )


# ── HYDRATION AU BOOT ─────────────────────────────────────────────────────────


def hydrate_queues_on_boot(db_path: str | None = None) -> dict[str, int]:
    """
    Reconstruit les queues volatiles depuis agent_messages au boot.
    Correction Gemini Ultra Web 2026-04-28 :
    après un crash Hub, les agents se reconnectent en SSE mais la queue
    asyncio est vide → hydrate repointe les tâches non lues.
    Appelé dans nokido_hub.py au démarrage, avant d'accepter les SSE.
    """
    import sqlite3 as _sq, json as _j
    from pathlib import Path as _P
    from datetime import datetime as _dt, timezone as _tz

    if db_path is None:
        # Scission M2M : les files se rehydratent depuis la base des agent_messages
        # (interrupteur sandbox/m2m.switch), lue au boot du hub.
        from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
        db_path = _m2m_path()

    print("[hydrate] Reconstruction des files...", flush=True)
    counts: dict[str, int] = {}
    try:
        conn = _sq.connect(db_path)
        conn.row_factory = _sq.Row
        conn.execute("PRAGMA journal_mode=WAL")
        rows = conn.execute("""
            SELECT id, from_agent, to_agent, correlation_id, payload, created_at
            FROM agent_messages
            WHERE status = 'unread'
              AND to_agent NOT IN ('EVENTBUS_ARCHIVE', 'local')
              AND datetime(created_at, '+900 seconds') > datetime('now')
            ORDER BY created_at ASC
        """).fetchall()
        for row in rows:
            try:
                data = _j.loads(row["payload"]) if row["payload"] else {}
                frame = MessageFrame(
                    frame_id=row["id"],
                    from_agent=row["from_agent"],
                    to_agent=row["to_agent"],
                    action="notification",
                    text=data.get("text", ""),
                    parameters=data,
                    job_id=row["correlation_id"] or row["id"],
                    tool_defs=[t.to_dict() for t in tools_for_ring(0)],
                    status="pending",
                    created_at=row["created_at"] or _dt.now(_tz.utc).isoformat(),
                )
                if INBOX.push(frame):
                    ag = row["to_agent"]
                    counts[ag] = counts.get(ag, 0) + 1
            except Exception as _fe:
                pass
        conn.close()
    except Exception as _e:
        print(f"[hydrate] ERR: {_e}", flush=True)
    total = sum(counts.values())
    print(f"[hydrate] {total} messages repoussés: {counts}", flush=True)
    return counts
