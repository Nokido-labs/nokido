"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_autonomous_orchestrator
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_autonomous_orchestrator.py
AUTONOMOUS_ORCHESTRATOR_V17
Intent_to_Action_Graph — 3 steps : Parse -> DAG -> Execute
Multiplexeur OneMCP_V17 — local + cloud
"""

import asyncio, json, sys, time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


# --------------------------------------------------------------------------
# DAG Node — noeud du graphe dirige acyclique
# --------------------------------------------------------------------------


@dataclass
class DAGNode:
    id: str
    label: str
    agent: str
    task: str
    mcp_tool: str = "llm_generate"
    priority: str = "normal"
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    output: str = ""
    elapsed_ms: int = 0
    x: float = 0.0
    y: float = 0.0

    def to_dict(self) -> dict:
        """To dict."""
        return {
            "id": self.id,
            "label": self.label,
            "agent": self.agent,
            "task": self.task[:100],
            "mcp_tool": self.mcp_tool,
            "priority": self.priority,
            "depends_on": self.depends_on,
            "status": self.status,
            "output": self.output[:200],
            "elapsed_ms": self.elapsed_ms,
            "x": self.x,
            "y": self.y,
        }


@dataclass
class DAGGraph:
    id: str
    label: str
    nodes: list[DAGNode] = field(default_factory=list)
    intent: Optional[dict] = None

    def get_node(self, nid: str) -> Optional[DAGNode]:
        """Get node.

        Args:
            nid: Description.
        """
        return next((n for n in self.nodes if n.id == nid), None)

    def roots(self) -> list[DAGNode]:
        """Roots."""
        dep_ids = {d for n in self.nodes for d in n.depends_on}
        return [n for n in self.nodes if n.id not in dep_ids]

    def ready(self, done_ids: set[str]) -> list[DAGNode]:
        """Ready.

        Args:
            done_ids: Description.
        """
        return [n for n in self.nodes if n.status == "pending" and all(d in done_ids for d in n.depends_on)]

    def to_dict(self) -> dict:
        """To dict."""
        return {
            "id": self.id,
            "label": self.label,
            "nodes": [n.to_dict() for n in self.nodes],
            "intent": self.intent,
        }


# --------------------------------------------------------------------------
# DAG Builder — Step 2 : genere le graphe depuis l'intention
# --------------------------------------------------------------------------


class DAGBuilder:
    """
    Construit le DAG a partir d'une ParsedIntent.
    Utilise le DynamicPipelineConstructor si disponible,
    sinon genere directement via LLM.
    """

    AGENT_PRIORITY = {
        "critical": ["nokido_mcp", "gemini", "groq_70b", "laforge"],
        "high": ["groq_70b", "laforge", "gemini"],
        "normal": ["laforge", "llamacpp"],
        "low": ["llamacpp", "laforge"],
    }

    def build(self, intent, available_agents: list[str]) -> DAGGraph:
        """Build.

        Args:
            intent: Description.
            available_agents: Description.
        """
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))

        # forge_dynamic_pipeline supprimé — DAG minimal direct.
        return self._build_minimal(intent, available_agents)

    def _schema_to_dag(self, schema, intent, agents: list[str]) -> DAGGraph:
        """Schema to dag.

        Args:
            schema: Description.
            intent: Description.
            agents: Description.
        """
        nodes = []
        prev_id = None
        for i, sn in enumerate(schema.nodes):
            agent = sn.agent if sn.agent in agents else (agents[0] if agents else "laforge")
            # Noeud critique -> meilleur agent
            if intent.priority in ("critical", "high") and i == 0:
                candidates = self.AGENT_PRIORITY.get(intent.priority, ["laforge"])
                agent = next((c for c in candidates if c in agents), agent)
            node = DAGNode(
                id=sn.id,
                label=sn.label,
                agent=agent,
                task=intent.action + " " + intent.raw[:80],
                mcp_tool="llm_generate",
                priority=intent.priority,
                depends_on=[prev_id] if prev_id and schema.mode == "sequential" else [],
                x=sn.x,
                y=sn.y,
            )
            nodes.append(node)
            if schema.mode == "sequential":
                prev_id = sn.id
        return DAGGraph(id=schema.id, label=schema.label, nodes=nodes, intent=intent.to_dict())

    def _build_minimal(self, intent, agents: list[str]) -> DAGGraph:
        """Build minimal.

        Args:
            intent: Description.
            agents: Description.
        """
        a0 = agents[0] if agents else "laforge"
        a1 = agents[1] if len(agents) > 1 else a0
        nodes = [
            DAGNode(
                id="parse",
                label="Analyse",
                agent=a0,
                task=intent.raw,
                mcp_tool="llm_generate",
                priority=intent.priority,
                x=80,
                y=200,
            ),
            DAGNode(
                id="execute",
                label="Execution",
                agent=a1,
                task=intent.action + ": " + intent.target,
                mcp_tool="llm_generate",
                priority=intent.priority,
                depends_on=["parse"],
                x=280,
                y=200,
            ),
            DAGNode(
                id="validate",
                label="Validation",
                agent=a0,
                task="Valide le resultat: " + intent.target,
                mcp_tool="llm_generate",
                priority=intent.priority,
                depends_on=["execute"],
                x=480,
                y=200,
            ),
        ]
        return DAGGraph(id="minimal_dag", label="DAG minimal", nodes=nodes, intent=intent.to_dict())


# --------------------------------------------------------------------------
# OneMCP Multiplexer — Step 3 : execute les noeuds
# --------------------------------------------------------------------------


class OneMCPMultiplexer:
    """
    Multiplexeur OneMCP_V17.
    Execute les noeuds locaux (ollama/llamacpp) en parallele,
    les noeuds critiques (cloud) en priorite.
    Emet des callbacks temps-reel.
    """

    def __init__(self, on_node_update: Optional[Callable] = None) -> None:
        """Init.

        Args:
            on_node_update: Description.
        """
        self._on_update = on_node_update

    async def execute_dag(self, graph: DAGGraph, task: str) -> dict:
        """Execute dag.

        Args:
            graph: Description.
            task: Description.
        """
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))

        done_ids: set[str] = set()
        all_results = []
        context = ""
        max_rounds = len(graph.nodes) + 2

        for _round in range(max_rounds):
            ready = graph.ready(done_ids)
            if not ready:
                break

            # Separer local vs critique
            local = [n for n in ready if n.priority not in ("critical",)]
            critical = [n for n in ready if n.priority == "critical"]

            # Critigues en premier sequentiel
            for node in critical:
                result = await self._run_node(node, task, context)
                node.output = result
                node.status = "done"
                context = result
                done_ids.add(node.id)
                all_results.append(node.to_dict())
                if self._on_update:
                    self._on_update(node.to_dict())

            # Locaux en parallele
            if local:
                tasks = [self._run_node(n, task, context) for n in local]
                outputs = await asyncio.gather(*tasks, return_exceptions=True)
                for node, out in zip(local, outputs):
                    if isinstance(out, Exception):
                        node.output = str(out)[:200]
                        node.status = "failed"
                    else:
                        node.output = str(out)
                        node.status = "done"
                        context = str(out)
                    done_ids.add(node.id)
                    all_results.append(node.to_dict())
                    if self._on_update:
                        self._on_update(node.to_dict())

        ok_count = sum(1 for r in all_results if r.get("status") == "done")
        return {
            "graph_id": graph.id,
            "graph_label": graph.label,
            "intent": graph.intent,
            "results": all_results,
            "ok": ok_count,
            "total": len(all_results),
            "context": context[:400],
        }

    async def _run_node(self, node: DAGNode, task: str, context: str) -> str:
        """Run node.

        Args:
            node: Description.
            task: Description.
            context: Description.
        """
        from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator

        node.status = "running"
        t0 = time.time()
        if self._on_update:
            self._on_update(node.to_dict())
        try:
            team = _default_team()
            team.activate(node.agent)
            orc = LeadOrchestrator()
            node_task = node.label + ": " + (context[:400] if context else task)
            res = await orc.run(node_task, team)
            turns = res.get("results", [])
            out = str(turns[0].get("response", "")) if turns else ""
            node.elapsed_ms = int((time.time() - t0) * 1000)
            return out
        except Exception as e:
            node.elapsed_ms = int((time.time() - t0) * 1000)
            raise


# --------------------------------------------------------------------------
# AutonomousOrchestrator — facade principale
# --------------------------------------------------------------------------


class AutonomousOrchestrator:
    """
    AUTONOMOUS_ORCHESTRATOR_V17
    Facade Intent_to_Action_Graph.

    Usage:
        orc = AutonomousOrchestrator()
        result = orc.run_sync("Cree un script Python de tri rapide")
        # ou async:
        result = await orc.run("Cree un script Python de tri rapide")
    """

    def __init__(self, on_node_update: Optional[Callable] = None) -> None:
        """Init.

        Args:
            on_node_update: Description.
        """
        self._on_update = on_node_update
        self._builder = DAGBuilder()
        self._mux = OneMCPMultiplexer(on_node_update)
        self._graphs: list[DAGGraph] = []

    def _detect_agents(self) -> list[str]:
        """Detect agents."""
        available = ["laforge"]
        try:
            import urllib.request

            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        except Exception:
            pass
        try:
            if str(APP) not in sys.path:
                sys.path.insert(0, str(APP))
            from nokido_agent.app.forge_llamacpp import LlamaCppBridge

            if LlamaCppBridge().is_available():
                available.append("llamacpp")
        except Exception:
            pass
        import os

        for key, agent in [
            ("GEMINI_API_KEY", "gemini"),
            ("GROQ_API_KEY", "groq_70b"),
            ("DEEPSEEK_API_KEY", "deepseek_direct"),
        ]:
            if os.environ.get(key):
                available.append(agent)
        return list(dict.fromkeys(available))

    async def run(self, instruction: str, use_llm_parse: bool = False) -> dict:
        """Run.

        Args:
            instruction: Description.
            use_llm_parse: Description.
        """
        t0 = time.time()

        # Step 1 : Intent
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_intent_parser import parse_intent

        intent = parse_intent(instruction, use_llm=use_llm_parse)

        # Step 2 : DAG
        agents = self._detect_agents()
        graph = self._builder.build(intent, agents)
        self._graphs.append(graph)

        # Step 3 : Execute
        result = await self._mux.execute_dag(graph, instruction)
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        result["intent"] = intent.to_dict()
        result["agents"] = agents

        # Persister dans RAG
        self._persist(result)
        return result

    def run_sync(self, instruction: str, use_llm_parse: bool = False) -> dict:
        """Run sync.

        Args:
            instruction: Description.
            use_llm_parse: Description.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.run(instruction, use_llm_parse))
        finally:
            loop.close()

    def _persist(self, result: dict) -> None:
        """Persist.

        Args:
            result: Description.
        """
        try:
            import sqlite3, time as _t

            db = ROOT / "RAG" / "embeddings.db"
            conn = sqlite3.connect(str(db))
            conn.execute("PRAGMA journal_mode=WAL")
            last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
            conn.execute(
                "INSERT INTO event_log "
                "(timecode,sequence_id,session_id,agent_id,event_type,target,payload,status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    _t.strftime("%Y-%m-%dT%H:%M:%S"),
                    int(last) + 1,
                    "autonomous_orc",
                    "CLAUDE",
                    "dag_execution",
                    result.get("graph_id", ""),
                    json.dumps(
                        {
                            "ok": result.get("ok", 0),
                            "total": result.get("total", 0),
                            "elapsed_ms": result.get("elapsed_ms", 0),
                        },
                        ensure_ascii=False,
                    ),
                    "ok" if result.get("ok", 0) > 0 else "err",
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def last_graph(self) -> Optional[dict]:
        """Last graph."""
        return self._graphs[-1].to_dict() if self._graphs else None


# Singleton
_orchestrator = AutonomousOrchestrator()


def get_orchestrator(on_update=None) -> AutonomousOrchestrator:
    """Get orchestrator.

    Args:
        on_update: Description.
    """
    if on_update:
        return AutonomousOrchestrator(on_update)
    return _orchestrator


def run_autonomous(instruction: str, use_llm_parse: bool = False) -> dict:
    """Run autonomous.

    Args:
        instruction: Description.
        use_llm_parse: Description.
    """
    return _orchestrator.run_sync(instruction, use_llm_parse)
