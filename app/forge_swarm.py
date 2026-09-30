"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_swarm
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_swarm.py — Logique de Collaboration Synchrone-Asynchrone
====================================================================
Implémente :
  1. State Machine stricte : IDLE → THINKING → STREAMING → SYNCING_RAG → IDLE
  2. Logging haute précision dans events.db (sequence_id monotone, timestamp µs)
  3. Broadcasting socket local (UDP 127.0.0.1:9765) — TUI et Streamlit écoutent
  4. Queue prioritaire anti-race-condition (PriorityQueue thread-safe)
  5. RAG update automatique après chaque bloc de pensée validé

Ancrage sur l existant :
  - live_bridge.json_set/get  → état swarm partagé cross-process
  - forge_heartbeat.beat()    → statut agent dans mmap
  - sandbox/events.db.event_log → log séquencé

Usage :
    from forge_swarm import swarm
    async with swarm.thinking("CLAUDE"):
        ...
    async with swarm.streaming("CLAUDE", token_gen):
        ...
"""

import asyncio
import json
import socket
import sqlite3
import threading
import time
import hashlib
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from queue import PriorityQueue, Empty
from typing import AsyncIterator, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
APP = Path(__file__).resolve().parent
DB_PATH = ROOT / "sandbox" / "events.db"

# ── État de la state machine ──────────────────────────────────────────────────


class SwarmState(str, Enum):
    IDLE = "IDLE"
    THINKING = "THINKING"
    STREAMING = "STREAMING"
    SYNCING_RAG = "SYNCING_RAG"


# ── Broadcasting UDP local ─────────────────────────────────────────────────────
BROADCAST_HOST = "127.0.0.1"
BROADCAST_PORT = 9765
_bcast_sock: Optional[socket.socket] = None
_bcast_lock = threading.Lock()


def _get_bcast_sock() -> socket.socket:
    """Get bcast sock."""
    global _bcast_sock
    with _bcast_lock:
        if _bcast_sock is None:
            _bcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return _bcast_sock


def broadcast(event: dict) -> None:
    """Envoie un event sur le socket UDP local — non bloquant, max 64KB."""
    try:
        payload = json.dumps(event, ensure_ascii=False)[:65000].encode("utf-8")
        _get_bcast_sock().sendto(payload, (BROADCAST_HOST, BROADCAST_PORT))
    except Exception:
        pass


def make_broadcast_listener() -> socket.socket:
    """Crée un socket UDP en écoute pour TUI / Streamlit."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((BROADCAST_HOST, BROADCAST_PORT))
    sock.settimeout(0.1)
    return sock


# ── Event log haute précision ─────────────────────────────────────────────────

_db_lock = threading.Lock()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure schema.

    Args:
        conn: Description.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS event_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timecode    TEXT    NOT NULL,
            sequence_id INTEGER NOT NULL,
            session_id  TEXT    NOT NULL DEFAULT 'swarm',
            agent_id    TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,
            target      TEXT    NOT NULL DEFAULT '',
            payload     TEXT    NOT NULL DEFAULT '{}',
            prev_hash   TEXT    NOT NULL DEFAULT '',
            new_hash    TEXT    NOT NULL DEFAULT '',
            status      TEXT    NOT NULL DEFAULT 'ok'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seq ON event_log(sequence_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent ON event_log(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_type ON event_log(event_type)")
    conn.commit()


def _log_event(
    agent_id: str,
    event_type: str,
    target: str = "",
    payload: dict | None = None,
    status: str = "ok",
) -> int:
    """
    Insère un événement dans event_log avec timestamp µs et sequence_id monotone.
    Thread-safe. Retourne le sequence_id assigné.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%S") + f".{time.time_ns() % 1_000_000_000:09d}"[:16]
    payload_str = json.dumps(payload or {}, ensure_ascii=False)

    with _db_lock:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_schema(conn)
        # Sequence_id monotone
        last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
        seq = last + 1
        # Hash chaîné (intégrité séquentielle)
        prev_row = conn.execute("SELECT new_hash FROM event_log WHERE sequence_id=?", (last,)).fetchone()
        prev_hash = prev_row[0] if prev_row else ""
        new_hash = hashlib.sha256(
            (str(seq) + agent_id + event_type + ts + payload_str + prev_hash).encode()
        ).hexdigest()[:16]
        conn.execute(
            "INSERT INTO event_log "
            "(timecode,sequence_id,session_id,agent_id,event_type,target,payload,prev_hash,new_hash,status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, seq, "swarm", agent_id, event_type, target, payload_str, prev_hash, new_hash, status),
        )
        conn.commit()
        conn.close()
    return seq


# ── State Machine ─────────────────────────────────────────────────────────────


class SwarmStateMachine:
    """
    State machine thread-safe pour le swarm d agents.
    Transitions : IDLE → THINKING(agent) → STREAMING(agent) → SYNCING_RAG → IDLE
    """

    def __init__(self) -> None:
        """Init."""
        self._lock = threading.Lock()
        self._state = SwarmState.IDLE
        self._active_agent: str = ""
        self._seq = 0

    # ── Lecture ───────────────────────────────────────────────────────────────

    @property
    def state(self) -> SwarmState:
        """State."""
        return self._state

    @property
    def active_agent(self) -> str:
        """Active agent."""
        return self._active_agent

    def snapshot(self) -> dict:
        """Snapshot."""
        return {
            "state": self._state.value,
            "active_agent": self._active_agent,
            "seq": self._seq,
            "ts": time.time(),
        }

    # ── Transitions ───────────────────────────────────────────────────────────

    def _transition(self, new_state: SwarmState, agent: str = "", payload: dict | None = None) -> None:
        """Transition.

        Args:
            new_state: Description.
            agent: Description.
            payload: Description.
        """
        old = self._state
        self._state = new_state
        self._active_agent = agent
        self._seq += 1
        ev = {
            "type": "state_transition",
            "from": old.value,
            "to": new_state.value,
            "agent": agent,
            "seq": self._seq,
            "ts": time.time(),
            **(payload or {}),
        }
        # Log + broadcast (hors lock pour éviter deadlock)
        seq_id = _log_event(agent or "swarm", "state_transition", target=new_state.value, payload=ev)
        ev["db_seq"] = seq_id
        broadcast(ev)
        # live_bridge sync
        try:
            import sys

            if str(APP) not in sys.path:
                sys.path.insert(0, str(APP))
            from nokido_agent.app.live_bridge import bridge

            bridge.json_set("swarm.state", new_state.value)
            bridge.json_set("swarm.active_agent", agent)
            bridge.json_set("swarm.seq", self._seq)
            bridge.json_set("swarm.ts", time.time())
        except Exception:
            pass

    def set_thinking(self, agent: str, task: str = "") -> None:
        """Set thinking.

        Args:
            agent: Description.
            task: Description.
        """
        with self._lock:
            if self._state != SwarmState.IDLE:
                raise SwarmBusyError(self._state, self._active_agent)
            self._transition(SwarmState.THINKING, agent, {"task": task})

    def set_streaming(self, agent: str) -> None:
        """Set streaming.

        Args:
            agent: Description.
        """
        with self._lock:
            self._transition(SwarmState.STREAMING, agent)

    def set_syncing_rag(self, agent: str) -> None:
        """Set syncing rag.

        Args:
            agent: Description.
        """
        with self._lock:
            self._transition(SwarmState.SYNCING_RAG, agent)

    def set_idle(self) -> None:
        """Set idle."""
        with self._lock:
            self._transition(SwarmState.IDLE)

    def force_idle(self) -> None:
        """Reset forcé — utiliser uniquement après timeout ou erreur."""
        with self._lock:
            _log_event("swarm", "force_idle", payload={"prev": self._state.value})
            self._state = SwarmState.IDLE
            self._active_agent = ""


class SwarmBusyError(Exception):
    def __init__(self, state: SwarmState, agent: str) -> None:
        """Init.

        Args:
            state: Description.
            agent: Description.
        """
        self.state = state
        self.agent = agent
        super().__init__(f"Swarm occupé : {state.value} par {agent}")


# ── File d attente prioritaire ─────────────────────────────────────────────────


class AgentTask:
    """Tâche agent avec priorité (1=haute, 9=basse)."""

    __slots__ = ("priority", "agent_id", "task_id", "fn", "kwargs", "created_at")

    def __init__(self, priority: int, agent_id: str, task_id: str, fn: Callable, kwargs: dict | None = None) -> None:
        """Init.

        Args:
            priority: Description.
            agent_id: Description.
            task_id: Description.
            fn: Description.
            kwargs: Description.
        """
        self.priority = priority
        self.agent_id = agent_id
        self.task_id = task_id
        self.fn = fn
        self.kwargs = kwargs or {}
        self.created_at = time.monotonic()

    def __lt__(self, other) -> object:
        """Lt.

        Args:
            other: Description.
        """
        return self.priority < other.priority


class SwarmQueue:
    """
    File d attente prioritaire thread-safe pour les tâches agents.
    Garantit l absence de race-condition : un seul agent actif à la fois.
    """

    def __init__(self, state_machine: SwarmStateMachine) -> None:
        """Init.

        Args:
            state_machine: Description.
        """
        self._q = PriorityQueue()
        self._sm = state_machine
        self._run = threading.Event()
        self._t: threading.Thread | None = None

    def submit(self, task: AgentTask) -> None:
        """Soumet une tâche. Thread-safe, non bloquant."""
        _log_event(task.agent_id, "task_submitted", task.task_id, {"priority": task.priority})
        self._q.put(task)
        broadcast({"type": "task_queued", "task_id": task.task_id, "agent": task.agent_id, "priority": task.priority})

    def start(self) -> None:
        """Start."""
        if self._t and self._t.is_alive():
            return
        self._run.set()
        self._t = threading.Thread(target=self._worker, daemon=True, name="SwarmQueue")
        self._t.start()

    def stop(self) -> None:
        """Stop."""
        self._run.clear()

    def qsize(self) -> int:
        """Qsize."""
        return self._q.qsize()

    def _worker(self) -> None:
        """Worker."""
        while self._run.is_set():
            try:
                task = self._q.get(timeout=0.5)
            except Empty:
                continue
            # Attendre IDLE (max 60s)
            t0 = time.monotonic()
            while self._sm.state != SwarmState.IDLE:
                if time.monotonic() - t0 > 60:
                    _log_event(task.agent_id, "task_timeout", task.task_id)
                    self._q.task_done()
                    break
                time.sleep(0.1)
            else:
                try:
                    self._sm.set_thinking(task.agent_id, task.task_id)
                    task.fn(**task.kwargs)
                except SwarmBusyError as e:
                    # Remettre en queue
                    self._q.put(task)
                except Exception as ex:
                    _log_event(task.agent_id, "task_error", task.task_id, {"error": str(ex)[:200]}, status="error")
                    self._sm.force_idle()
                finally:
                    self._q.task_done()


# ── Context managers async ────────────────────────────────────────────────────


class SwarmCoordinator:
    """Interface principale pour les agents — context managers async."""

    def __init__(self) -> None:
        """Init."""
        self.sm = SwarmStateMachine()
        self.queue = SwarmQueue(self.sm)
        self.queue.start()
        # Watchdog timeout — reset IDLE si bloqué > 90s
        self._watchdog = threading.Thread(target=self._run_watchdog, daemon=True)
        self._watchdog.start()

    def _run_watchdog(self) -> None:
        """Reset forcé si state machine bloquée > 90s."""
        last_seq = -1
        stuck_since = 0.0
        while True:
            time.sleep(5)
            if self.sm.state == SwarmState.IDLE:
                last_seq = self.sm._seq
                stuck_since = 0.0
                continue
            if self.sm._seq != last_seq:
                last_seq = self.sm._seq
                stuck_since = time.monotonic()
            elif stuck_since == 0.0:
                stuck_since = time.monotonic()
            elif time.monotonic() - stuck_since > 90:
                _log_event(
                    "watchdog", "force_idle", payload={"state": self.sm.state.value, "stuck_s": 90}, status="warn"
                )
                self.sm.force_idle()
                stuck_since = 0.0

    @asynccontextmanager
    async def thinking(self, agent: str, task: str = "") -> None:
        """
        async with swarm.thinking("CLAUDE", "résoudre X"):
            # réflexion — state = THINKING
        """
        t0 = time.monotonic()
        while self.sm.state != SwarmState.IDLE:
            if time.monotonic() - t0 > 30:
                raise SwarmBusyError(self.sm.state, self.sm.active_agent)
            await asyncio.sleep(0.1)
        self.sm.set_thinking(agent, task)
        try:
            from nokido_agent.app.forge_heartbeat import beat

            beat(agent, "thinking", task=task[:40])
        except Exception:
            pass
        try:
            yield
        except Exception as e:
            _log_event(agent, "thinking_error", payload={"error": str(e)[:200]}, status="error")
            self.sm.force_idle()
            raise

    async def stream(self, agent: str, gen: AsyncIterator[str]) -> AsyncIterator[str]:
        """
        Async generator — wrapper de streaming avec state machine + RAG sync.

        Usage :
            async for token in swarm.stream("CLAUDE", my_gen):
                print(token, end="", flush=True)
        """
        self.sm.set_streaming(agent)
        try:
            from nokido_agent.app.forge_heartbeat import beat

            beat(agent, "streaming")
        except Exception:
            pass
        # MMap Context — écriture pensée en cours (60fps GUI)
        _ctx = None
        try:
            from nokido_agent.app.forge_mmap_context import AgentContext

            _ctx = AgentContext(agent)
            _ctx.start_thinking("streaming", progress=5)
        except Exception:
            pass
        accumulated: list[str] = []
        try:
            async for token in gen:
                accumulated.append(token)
                # Écrire chaque token dans mmap
                if _ctx:
                    _ctx.stream_token(token)
                broadcast(
                    {
                        "type": "token",
                        "agent": agent,
                        "token": token,
                        "ts": time.time(),
                    }
                )
                yield token
        finally:
            full_text = "".join(accumulated)
            if full_text.strip():
                await self._sync_rag(agent, full_text)
            else:
                self.sm.set_idle()
                try:
                    from nokido_agent.app.forge_heartbeat import beat

                    beat(agent, "idle")
                except Exception:
                    pass
            if _ctx:
                try:
                    _ctx.done()
                except Exception:
                    pass

    async def _sync_rag(self, agent: str, text: str) -> None:
        """Met à jour le RAG après streaming — SYNCING_RAG → IDLE."""
        self.sm.set_syncing_rag(agent)
        _log_event(agent, "rag_sync_start", payload={"chars": len(text), "preview": text[:80]})
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._rag_index, agent, text)
            _log_event(agent, "rag_sync_done", payload={"chars": len(text)})
        except Exception as e:
            _log_event(agent, "rag_sync_error", payload={"error": str(e)[:200]}, status="error")
        finally:
            self.sm.set_idle()
            try:
                from nokido_agent.app.forge_heartbeat import beat

                beat(agent, "idle")
            except Exception:
                pass

    def _rag_index(self, agent: str, text: str) -> None:
        """Indexe dans rag_chunks — exécuté dans thread executor."""
        import sys, sqlite3 as _sq

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            db_p = ROOT / "RAG" / "embeddings.db"
            conn = _sq.connect(str(db_p), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            # 2026-09-12 : `text[:800]` amputait en silence et l'INSERT n'avait
            # pas de clef primaire. L'effet de CE site n'est pas chiffrable —
            # 662 118 chunks font 800 caracteres, mais c'est la taille CIBLE du
            # chunker (ses voisines sont peuplees, ratio 6,9), donc le dommage
            # propre a cette ligne est noye dans cette masse. Corrige quand meme :
            # l'absence de mesure n'est pas une preuve d'innocuite.
            from nokido_agent.app.forge_db_path import ecrire_chunk  # type: ignore

            ecrire_chunk(conn, "swarm/" + agent, "swarm", text)
            conn.commit()
            conn.close()
        except Exception:
            pass

    def recent_events(self, n: int = 20, agent: str | None = None) -> list:
        """Retourne les N derniers events depuis event_log."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            if agent:
                rows = conn.execute(
                    "SELECT timecode,sequence_id,agent_id,event_type,target,payload,status "
                    "FROM event_log WHERE agent_id=? ORDER BY sequence_id DESC LIMIT ?",
                    (agent, n),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT timecode,sequence_id,agent_id,event_type,target,payload,status "
                    "FROM event_log ORDER BY sequence_id DESC LIMIT ?",
                    (n,),
                ).fetchall()
            conn.close()
            return [
                {"ts": r[0], "seq": r[1], "agent": r[2], "type": r[3], "target": r[4], "payload": r[5], "status": r[6]}
                for r in rows
            ]
        except Exception:
            return []

    def swarm_status(self) -> dict:
        """Swarm status."""
        return {
            "state": self.sm.state.value,
            "active_agent": self.sm.active_agent,
            "queue_size": self.queue.qsize(),
            "seq": self.sm._seq,
            "recent": self.recent_events(5),
        }


# ── Singleton global ──────────────────────────────────────────────────────────
swarm = SwarmCoordinator()
