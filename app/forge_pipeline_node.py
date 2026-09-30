"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_pipeline_node
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_pipeline_node.py
===========================
WORKFLOW_NODE_INTEGRATION — v17.04
MCP_Functional_Unit | OneMCP_STDIO | Sequential_Batch

Pipeline d execution :
  Trigger (FS event / API call)
    → Ring2 ADR check
    → MMap buffer write
    → LeadOrchestrator.run()
    → MMap result write
    → Node status update

Pas de chat bubbles. Status nodes uniquement.
"""

import asyncio
import time
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# ── Node Status ───────────────────────────────────────────────────────────────


class NodeStatus(str, Enum):
    IDLE = "IDLE"
    PENDING = "PENDING"  # trigger reçu, en attente
    ADR_CHECK = "ADR_CHECK"  # Ring2 validation en cours
    RUNNING = "RUNNING"  # exécution pipeline
    DONE = "DONE"  # succès
    FAILED = "FAILED"  # échec
    BLOCKED = "BLOCKED"  # bloqué par Ring0/ADR"


@dataclass
class NodeResult:
    node_id: str
    status: NodeStatus
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    elapsed_ms: int = 0
    turns: list = field(default_factory=list)
    error: str = ""
    adr_context: str = ""
    session_id: str = ""

    def to_dict(self) -> dict:
        """To dict."""
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "elapsed_ms": self.elapsed_ms,
            "turns": len(self.turns),
            "error": self.error[:200] if self.error else "",
            "session_id": self.session_id,
        }


# ── Ring2 ADR Validator ───────────────────────────────────────────────────────


class Ring2ADRValidator:
    """
    Vérifie la conformité de la tâche par rapport aux ADR actifs.
    Ring 0 = blocage absolu.
    Ring 2 = avertissement + enrichissement du contexte.
    """

    def __init__(self) -> None:
        """Init."""
        self._db_path = ROOT / "RAG" / "embeddings.db"

    def validate(self, task: str, agent_id: str = "PIPELINE") -> dict:
        """Validate.

        Args:
            task: Description.
            agent_id: Description.
        """
        result = {
            "allowed": True,
            "ring": None,
            "adrs": [],
            "context": "",
            "corrected": task,
        }
        try:
            from nokido_agent.app.forge_resonance_filter import resonance_check

            check = resonance_check(agent_id, task)
            if check["action"] == "block":
                result["allowed"] = False
                result["ring"] = 0
                result["corrected"] = check.get("correction", "")
                return result
            result["corrected"] = check.get("enriched_prompt", task)
            result["context"] = check.get("correction", "")
        except Exception as e:
            pass

        # Charger ADR actifs depuis embeddings.db
        try:
            import sqlite3

            conn = sqlite3.connect(str(self._db_path), timeout=3)
            conn.execute("PRAGMA journal_mode=WAL")
            rows = conn.execute(
                "SELECT adr_id, title, decision FROM adr_records WHERE status='Accepté' ORDER BY ring, id LIMIT 8"
            ).fetchall()
            conn.close()
            if rows:
                adrs = [f"[{r[0]}] {r[1]} → {r[2][:80]}" for r in rows]
                result["adrs"] = adrs
                result["context"] += "\n=== ADR actifs ===\n" + "\n".join(adrs)
        except Exception:
            pass

        return result


# ── MMap Buffer Interface ─────────────────────────────────────────────────────


class MMapBuffer:
    """
    Interface vers live_bridge MMap.
    Écrit le statut du noeud et les résultats partiels.
    """

    def __init__(self) -> None:
        """Init."""
        self._bridge = None

    def _get(self) -> object:
        """Get."""
        if self._bridge is None:
            try:
                from nokido_agent.app.live_bridge import bridge

                self._bridge = bridge
            except Exception:
                pass
        return self._bridge

    def write_node_status(self, node_id: str, status: NodeStatus, data: dict = None) -> None:
        """Write node status.

        Args:
            node_id: Description.
            status: Description.
            data: Description.
        """
        br = self._get()
        if not br:
            return
        try:
            br.json_set(f"node.{node_id}.status", status.value)
            br.json_set(f"node.{node_id}.ts", time.time())
            if data:
                for k, v in data.items():
                    br.json_set(f"node.{node_id}.{k}", v)
        except Exception:
            pass

    def write_result(self, node_id: str, result: NodeResult) -> None:
        """Write result.

        Args:
            node_id: Description.
            result: Description.
        """
        br = self._get()
        if not br:
            return
        try:
            br.json_set(f"node.{node_id}.status", result.status.value)
            br.json_set(f"node.{node_id}.elapsed_ms", result.elapsed_ms)
            br.json_set(f"node.{node_id}.turns", len(result.turns))
            br.json_set(f"node.{node_id}.session_id", result.session_id)
            br.json_set(f"node.{node_id}.ended_at", result.ended_at)
        except Exception:
            pass

    def read_snapshot(self, node_id: str) -> dict:
        """Read snapshot.

        Args:
            node_id: Description.
        """
        br = self._get()
        if not br:
            return {}
        try:
            snap = br.snapshot().get("json", {})
            prefix = f"node.{node_id}."
            return {k[len(prefix) :]: v for k, v in snap.items() if k.startswith(prefix)}
        except Exception:
            return {}


# ── Pipeline Node ─────────────────────────────────────────────────────────────


class PipelineNode:
    """
    Unité fonctionnelle MCP — Sequential_Batch.
    Exécute un pipeline complet :
      validate → enrich → run → store
    Pas d'UI chat. Status dans MMap.
    """

    def __init__(self, node_id: str = "pipeline_main") -> None:
        """Init.

        Args:
            node_id: Description.
        """
        self.node_id = node_id
        self._validator = Ring2ADRValidator()
        self._mmap = MMapBuffer()
        self._results: list[NodeResult] = []

    async def execute(
        self,
        task: str,
        agents: list[str],
        context: str = "",
        trigger_source: str = "API",
    ) -> NodeResult:
        """
        Point d'entrée pipeline.

        Args:
            task:           Tâche à exécuter
            agents:         Liste des IDs agents (ex: ["nokido","llamacpp"])
            context:        Contexte additionnel
            trigger_source: "API" | "FS_EVENT" | "MCP_CALL"

        Returns:
            NodeResult avec status final et turns
        """
        result = NodeResult(node_id=self.node_id, status=NodeStatus.PENDING)

        # ── 1. PENDING ────────────────────────────────────────────────────────
        self._mmap.write_node_status(
            self.node_id,
            NodeStatus.PENDING,
            {
                "trigger": trigger_source,
                "task_preview": task[:80],
                "agents": ",".join(agents),
            },
        )

        # ── 2. ADR_CHECK (Ring 2) ──────────────────────────────────────────────
        result.status = NodeStatus.ADR_CHECK
        self._mmap.write_node_status(self.node_id, NodeStatus.ADR_CHECK)

        validation = self._validator.validate(task)
        if not validation["allowed"]:
            result.status = NodeStatus.BLOCKED
            result.error = f"Ring{validation['ring']} BLOCKED: {validation['corrected'][:200]}"
            result.ended_at = time.time()
            self._mmap.write_result(self.node_id, result)
            self._results.append(result)
            return result

        enriched_task = validation["corrected"]
        result.adr_context = validation["context"]

        # ── 3. RUNNING ────────────────────────────────────────────────────────
        result.status = NodeStatus.RUNNING
        result.started_at = time.time()
        self._mmap.write_node_status(
            self.node_id,
            NodeStatus.RUNNING,
            {
                "agent_count": len(agents),
            },
        )

        try:
            import copy
            from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator

            team = _default_team()
            seen: dict[str, int] = {}
            for pid in agents:
                if pid not in seen:
                    team.activate(pid)
                    seen[pid] = 1
                else:
                    base = next((p for p in team.participants if p.id == pid), None)
                    if base:
                        clone = copy.deepcopy(base)
                        clone.id = f"{pid}_{seen[pid] + 1}"
                        clone.config = dict(base.config)
                        clone.config["system"] = (
                            "Tu es un critique rigoureux. Identifie les failles de la réponse précédente."
                        )
                        clone.active = True
                        team.participants.append(clone)
                    seen[pid] += 1

            full_context = (context + "\n" + result.adr_context).strip()
            orc = LeadOrchestrator()
            res = await orc.run(enriched_task, team, context=full_context)

            result.session_id = res.get("session_id", "")
            result.elapsed_ms = res.get("elapsed_ms", 0)
            result.turns = res.get("results", [])

            # ── 4. DONE ───────────────────────────────────────────────────────
            result.status = NodeStatus.DONE
            result.ended_at = time.time()

            # Écrire résultats dans MMap pour lecture UI
            for i, turn in enumerate(result.turns):
                self._mmap._get() and self._mmap.write_node_status(
                    self.node_id,
                    NodeStatus.DONE,
                    {
                        f"turn_{i}_agent": turn.get("participant_id", ""),
                        f"turn_{i}_ok": turn.get("ok", False),
                        f"turn_{i}_chars": len(str(turn.get("response", ""))),
                    },
                )

        except Exception as e:
            result.status = NodeStatus.FAILED
            result.error = str(e)[:300]
            result.ended_at = time.time()

        self._mmap.write_result(self.node_id, result)
        self._results.append(result)
        return result

    def execute_sync(
        self,
        task: str,
        agents: list[str],
        context: str = "",
        trigger_source: str = "API",
    ) -> NodeResult:
        """Version synchrone pour appel depuis thread non-async."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.execute(task, agents, context, trigger_source))
        finally:
            loop.close()

    def get_history(self) -> list[dict]:
        """Get history."""
        return [r.to_dict() for r in self._results]

    def last_result(self) -> NodeResult | None:
        """Last result."""
        return self._results[-1] if self._results else None


# ── Singleton global ──────────────────────────────────────────────────────────
_node = PipelineNode("main")


def get_node() -> PipelineNode:
    """Get node."""
    return _node


def run_pipeline(task: str, agents: list[str], context: str = "", source: str = "API") -> NodeResult:
    """Point d'entrée haut niveau synchrone."""
    return _node.execute_sync(task, agents, context, source)
