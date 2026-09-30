"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_mmap_context
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_mmap_context.py
==========================
MMap Context — "Pensée en cours" des agents en temps réel.

Les agents écrivent leur état de réflexion dans live_bridge.map.
La GUI PySide6 lit à 60fps — fluidité totale même si Windows rame.

Clés mmap réservées :
  agent.{id}.thinking    → texte partiel de réflexion (streaming tokens)
  agent.{id}.state       → IDLE|THINKING|STREAMING|WAITING
  agent.{id}.task        → description de la tâche en cours
  agent.{id}.progress    → 0-100 (pour barre de progression)
  agent.{id}.token_count → nombre de tokens émis
  agent.{id}.tokens_s    → tokens/seconde
  agent.{id}.ts          → timestamp dernière mise à jour
  resonance.last_agent   → dernier agent vérifié par le filtre
  resonance.last_action  → pass|warn|correct|block
  resonance.drift_score  → score dérive [0.0-1.0]
  adr.last_created       → ID du dernier ADR créé
  adr.total              → nombre total d'ADR

Usage agent :
    from forge_mmap_context import AgentContext
    ctx = AgentContext("CLAUDE")
    ctx.start_thinking("Analyser le bug #42")
    ctx.stream_token("def")
    ctx.stream_token(" foo")
    ctx.done()

Usage GUI (60fps via MMapPollerWorker déjà existant) :
    snap = bridge.snapshot()["json"]
    thinking_text = snap.get("agent.CLAUDE.thinking", "")
    progress      = snap.get("agent.CLAUDE.progress", 0)
"""

import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Buffer max pour "thinking" dans mmap (évite de saturer la zone JSON)
MAX_THINKING_CHARS = 2000


class AgentContext:
    """
    Context manager pour un agent — écrit dans live_bridge.map.
    Thread-safe via le lock interne de live_bridge.
    Zéro latence — écriture mmap directe.
    """

    def __init__(self) -> None:
        """Init."""
        self.lock = threading.Lock()
        self.data: dict[str, object] = {}

    def __enter__(self) -> "AgentContext":
        """Enter."""
        with self.lock:
            return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit.

        Args:
            exc_type: Description.
            exc_val: Description.
            exc_tb: Description.
        """
        with self.lock:
            pass

    def __init__(self, agent_id: str) -> None:  # noqa: F811
        """Init.

        Args:
            agent_id: Description.
        """
        self.agent_id = agent_id
        self._bridge = None
        self._prefix = f"agent.{agent_id}"
        self._buf = ""
        self._t0 = 0.0
        self._tok_cnt = 0
        self._get_bridge()

    def _get_bridge(self) -> None:
        """Get bridge."""
        try:
            import sys

            if str(ROOT / "app") not in sys.path:
                sys.path.insert(0, str(ROOT))
            from nokido_agent.app.live_bridge import bridge

            self._bridge = bridge
        except Exception:
            self._bridge = None

    def _set(self, key: str, value) -> None:
        """Set.

        Args:
            key: Description.
            value: Description.
        """
        if self._bridge:
            try:
                self._bridge.json_set(f"{self._prefix}.{key}", value)
            except Exception:
                pass

    # ── API publique ──────────────────────────────────────────────────────────

    def start_thinking(self, task: str = "", progress: int = 0) -> None:
        """Signale le début d'une réflexion."""
        self._buf = ""
        self._t0 = time.monotonic()
        self._tok_cnt = 0
        self._set("state", "THINKING")
        self._set("task", task[:80])
        self._set("thinking", "")
        self._set("progress", progress)
        self._set("token_count", 0)
        self._set("tokens_s", 0.0)
        self._set("ts", time.time())

    def stream_token(self, token: str) -> None:
        """
        Appelé pour chaque token généré.
        Accumule dans le buffer et met à jour mmap.
        Flush toutes les ~10 tokens pour éviter les writes excessifs.
        """
        self._buf += token
        self._tok_cnt += 1

        # Flush toutes les 10 tokens ou si buffer > 100 chars
        if self._tok_cnt % 10 == 0 or len(self._buf) > 100:
            elapsed = max(0.001, time.monotonic() - self._t0)
            tokens_s = self._tok_cnt / elapsed
            # Tronquer pour mmap (garder les derniers MAX_THINKING_CHARS)
            display = self._buf[-MAX_THINKING_CHARS:]
            self._set("state", "STREAMING")
            self._set("thinking", display)
            self._set("token_count", self._tok_cnt)
            self._set("tokens_s", round(tokens_s, 1))
            self._set("ts", time.time())

    def set_progress(self, pct: int) -> None:
        """Met à jour la barre de progression (0-100)."""
        self._set("progress", max(0, min(100, pct)))

    def waiting(self, reason: str = "") -> None:
        """L'agent attend une réponse externe."""
        self._set("state", "WAITING")
        self._set("thinking", "[En attente" + (": " + reason if reason else "") + "]")
        self._set("ts", time.time())

    def done(self, final_text: str = "") -> None:
        """Signale la fin — efface la pensée en cours."""
        elapsed = max(0.001, time.monotonic() - self._t0)
        tokens_s = self._tok_cnt / elapsed if self._t0 > 0 else 0
        self._set("state", "IDLE")
        self._set("thinking", "")
        self._set("task", "")
        self._set("progress", 100)
        self._set("tokens_s", round(tokens_s, 1))
        self._set("token_count", self._tok_cnt)
        self._set("ts", time.time())
        self._buf = ""

    def error(self, msg: str) -> None:
        """Signale une erreur."""
        self._set("state", "ERROR")
        self._set("thinking", "❌ " + msg[:200])
        self._set("ts", time.time())

    # ── Context manager support ───────────────────────────────────────────────

    def __enter__(self) -> object:  # noqa: F811
        """Enter."""
        self.start_thinking()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # noqa: F811
        """Exit.

        Args:
            exc_type: Description.
            exc_val: Description.
            exc_tb: Description.
        """
        if exc_type:
            self.error(str(exc_val)[:100])
        else:
            self.done()
        return False


# ── Lecteur snapshot (GUI side) ───────────────────────────────────────────────


class AgentSnapshot:
    """
    Lit l'état de tous les agents depuis mmap.
    Appelé par MMapPollerWorker à 100ms.
    Compatible avec la lecture 60fps (bridge est thread-safe).
    """

    def __init__(self) -> None:
        """Init."""
        self._bridge = None
        try:
            import sys

            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.live_bridge import bridge

            self._bridge = bridge
        except Exception:
            pass

    def get_all(self) -> dict:
        """Retourne l'état de tous les agents."""
        if not self._bridge:
            return {}
        try:
            snap = self._bridge.snapshot().get("json", {})
            agents = {}
            for key, val in snap.items():
                if key.startswith("agent."):
                    parts = key.split(".", 2)
                    if len(parts) == 3:
                        aid, field = parts[1], parts[2]
                        if aid not in agents:
                            agents[aid] = {}
                        agents[aid][field] = val
            return agents
        except Exception:
            return {}

    def get_agent(self, agent_id: str) -> dict:
        """Lit l'état d'un agent spécifique."""
        all_agents = self.get_all()
        return all_agents.get(
            agent_id,
            {
                "state": "IDLE",
                "thinking": "",
                "task": "",
                "progress": 0,
                "tokens_s": 0.0,
            },
        )

    def get_resonance(self) -> dict:
        """Lit l'état du filtre de résonance."""
        if not self._bridge:
            return {}
        try:
            snap = self._bridge.snapshot().get("json", {})
            return {
                "last_agent": snap.get("resonance.last_agent", ""),
                "last_action": snap.get("resonance.last_action", ""),
                "drift_score": snap.get("resonance.drift_score", 0.0),
                "ts": snap.get("resonance.ts", 0.0),
            }
        except Exception:
            return {}


# ── Intégration dispatch_ai ───────────────────────────────────────────────────


async def dispatch_with_resonance(
    agent_id: str,
    user_input: str,
    generate_fn,  # coroutine async qui génère la réponse
    strict: bool = False,
) -> dict:
    """
    Wrapper complet : résonance → génération → mmap → RAG sync.

    Usage dans dispatch_ai :
        from forge_mmap_context import dispatch_with_resonance
        result = await dispatch_with_resonance(
            "CLAUDE", user_input,
            lambda: orc.run_collaboration(enriched)
        )
        response = result["response"]
    """
    from nokido_agent.app.forge_resonance_filter import resonance_check

    # 1. Filtre de résonance AVANT génération
    resonance = resonance_check(agent_id, user_input, strict=strict)

    ctx = AgentContext(agent_id)
    ctx.start_thinking(user_input[:60])

    if resonance["action"] == "block":
        ctx.error("Proposition bloquée — contradiction loi absolue")
        return {
            "response": resonance["correction"],
            "blocked": True,
            "resonance": resonance,
            "agent_used": agent_id,
        }

    # 2. Utiliser le prompt enrichi si correction nécessaire
    enriched = resonance["enriched_prompt"]

    # 3. Génération
    response, agent_used = "", agent_id
    try:
        ctx.set_progress(10)
        if resonance["action"] in ("correct", "warn"):
            ctx.stream_token("[" + resonance["action"].upper() + "] ")
        result = await generate_fn(enriched)
        if isinstance(result, tuple):
            response, agent_used = result
        else:
            response = str(result)
        ctx.set_progress(90)
    except Exception as e:
        ctx.error(str(e)[:100])
        response = str(e)

    ctx.done()

    return {
        "response": response,
        "blocked": False,
        "resonance": resonance,
        "agent_used": agent_used,
    }
