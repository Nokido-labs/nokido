"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_knowledge_harvester
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_knowledge_harvester.py
KNOWLEDGE_HARVESTER_V1 — KnowledgeHarvesterNode
Trigger: On_Success_Test_Pass
Extract: Reasoning_Path | Architecture_Decision | Pitfall_Avoided | Template
Store: Ring5_RAG_Expert_System (rag_chunks + event_log)
Goal: 95% tests pass Ollama uniquement
"""

import json, sys, time, sqlite3, hashlib, re
from pathlib import Path
from dataclasses import dataclass, field


def _gs(k: str) -> str:
    """Secure secret access — WCM > .env > os.environ."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        import os as _os

        return _os.environ.get(k, "")


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DB = ROOT / "RAG" / "embeddings.db"


@dataclass
# Context:

# Context:

class KnowledgeEntry:
    """Represents a knowledge entry with metadata and content for RAG processing."""

    kind: str
    title: str
    content: str
    source_task: str = ""
    agent: str = "laforge"
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    ts: str = ""

    def __post_init__(self) -> None:
        """Initializes timestamp if not provided."""
        if not self.ts:
            self.ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_rag_text(self) -> str:
        """Converts the entry to formatted text for RAG retrieval.

        Format:
        [KIND] TITLE
        Task: SOURCE_TASK (truncated to 80 characters)
        CONTENT
        #TAG1 #TAG2 ...
        """
        tags_str = " ".join(f"#{t}" for t in self.tags)
        return f"[{self.kind.upper()}] {self.title}\nTask: {self.source_task[:80]}\n{self.content}\n{tags_str}"

    def chunk_id(self) -> str:
        """Generates a unique chunk identifier based on entry content.

        Returns:
            A string of the form 'harvest_<12_char_hash>'.
        """
        h = hashlib.md5((self.kind + self.title + self.content[:50]).encode()).hexdigest()[:12]
        return f"harvest_{h}"


class ReasoningExtractor:
    PATTERNS = {
        "reasoning_path": [
            r"(?:parce que|car|donc|ainsi|par consequent)\s+(.{30,180})",
            r"(?:l.approche|la solution|le principe)\s+(?:est|consiste)[^\n]{0,10}(.{20,180})",
            r"(?:j.ai|nous avons)\s+(?:choisi|decide|opte pour)\s+(.{20,180})",
        ],
        "pitfall_avoided": [
            r"(?:attention|eviter|ne pas|piege|erreur)\s*:?\s*(.{20,180})",
            r"(?:ne|jamais)\s+(?:pas|utiliser|faire)\s+(.{20,180})",
        ],
        "architecture_decision": [
            r"(?:architecture|design|pattern)\s*:?\s*(.{20,180})",
            r"(?:on utilise|il faut|preferer)\s+(.{20,180})",
            r"(?:ring|module|couche)\s+\d+\s*:?\s*(.{20,180})",
        ],
    }

    def extract(self, text: str, task: str, agent: str = "laforge") -> list:
        """Extract.

        Args:
            text: Description.
            task: Description.
            agent: Description.
        """
        entries = []
        norm = text.lower()
        for kind, patterns in self.PATTERNS.items():
            for pat in patterns:
                for m in list(re.finditer(pat, norm, re.IGNORECASE))[:2]:
                    snippet = m.group(1).strip()[:200]
                    if len(snippet) > 25:
                        entries.append(
                            KnowledgeEntry(
                                kind=kind,
                                title=snippet[:60],
                                content=snippet,
                                source_task=task,
                                agent=agent,
                                tags=[kind.split("_")[0], "local"],
                                score=0.75,
                            )
                        )
        # Deduplique
        seen = set()
        result = []
        for e in entries:
            h = e.chunk_id()
            if h not in seen:
                seen.add(h)
                result.append(e)
        return result


class TemplateGenerator:
    def extract_templates(self, code: str, task: str, agent: str = "laforge") -> list:
        """Extract templates.

        Args:
            code: Description.
            task: Description.
            agent: Description.
        """
        templates = []
        try:
            import ast as _ast

            tree = _ast.parse(code)
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    src = _ast.get_source_segment(code, node) or ""
                    if len(src) > 50:
                        templates.append(
                            KnowledgeEntry(
                                kind="template",
                                title="fn:" + node.name,
                                content=src[:800],
                                source_task=task,
                                agent=agent,
                                tags=["template", "python", "function"],
                                score=0.9,
                            )
                        )
                elif isinstance(node, _ast.ClassDef):
                    src = _ast.get_source_segment(code, node) or ""
                    if len(src) > 80:
                        templates.append(
                            KnowledgeEntry(
                                kind="template",
                                title="cls:" + node.name,
                                content=src[:1000],
                                source_task=task,
                                agent=agent,
                                tags=["template", "python", "class"],
                                score=0.9,
                            )
                        )
        except Exception:
            pass
        return templates[:6]


def _store_entries(entries: list) -> int:
    """
    Store a list of entries in the database.

    Args:
        entries: list of objects with attributes: ts (str), kind (str), agent (str),
                 title (str), content (str), tags (list), score (float).

    Returns:
        Number of entries successfully stored.
    """
    if not entries:
        return 0
    stored: int = 0
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA journal_mode=WAL")
        last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
        for i, e in enumerate(entries):
            conn.execute(
                "INSERT INTO event_log "
                "(timecode,sequence_id,session_id,agent_id,event_type,target,payload,status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    e.ts,
                    int(last) + i + 1,
                    "harvester",
                    e.agent,
                    "harvest:" + e.kind,
                    e.title[:80],
                    json.dumps({"content": e.content[:400], "tags": e.tags, "score": e.score}, ensure_ascii=False),
                    "ok",
                ),
            )
            stored += 1
        conn.commit()
        conn.close()
    except Exception:
        pass
    return stored


class SilentBenchmark:
    BENCH_DIR = ROOT / "RAG" / "benchmark_results"
    TASKS = [
        "Ecris une fonction Python quicksort avec tests pytest",
        "Ecris une classe Python qui lit un CSV et retourne un dict par colonne",
        "Corrige ce bug Python: def add(a,b): return a-b",
        "Genere un ADR Ring2 pour justifier SQLite en WAL mode",
    ]

    def run_task(self, task: str, agent_id: str) -> dict:
        """Run task.

        Args:
            task: Description.
            agent_id: Description.
        """
        t0 = time.time()
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator
            import asyncio

            team = _default_team()
            team.activate(agent_id)
            orc = LeadOrchestrator()
            loop = asyncio.new_event_loop()
            res = loop.run_until_complete(orc.run(task, team))
            loop.close()
            turns = res.get("results", [])
            text = str(turns[0].get("response", "")) if turns else ""
            elapsed = int((time.time() - t0) * 1000)
            code_ok = False
            if "```python" in text:
                import ast as _ast

                code = text.split("```python")[1].split("```")[0]
                try:
                    _ast.parse(code)
                    code_ok = True
                except SyntaxError:
                    pass
            return {
                "agent": agent_id,
                "elapsed_ms": elapsed,
                "code_ok": code_ok,
                "chars": len(text),
                "preview": text[:150],
            }
        except Exception as e:
            return {
                "agent": agent_id,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "code_ok": False,
                "chars": 0,
                "error": str(e)[:100],
            }

    def run_comparison(self, task_idx: int = 0) -> dict:
        """Run comparison.

        Args:
            task_idx: Description.
        """
        import os

        task = self.TASKS[task_idx % len(self.TASKS)]
        local = self.run_task(task, "laforge")
        cloud_agent = "gemini" if _gs("GEMINI_API_KEY") else "groq_70b"
        cloud = self.run_task(task, cloud_agent)
        local_ok = local["code_ok"]
        cloud_ok = cloud["code_ok"]
        winner = (
            "local"
            if local_ok and not cloud_ok
            else "cloud"
            if cloud_ok and not local_ok
            else "tie"
            if local_ok == cloud_ok
            else "none"
        )
        result = {
            "task": task[:80],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "local": local,
            "cloud": cloud,
            "winner": winner,
            "local_faster": local["elapsed_ms"] < cloud["elapsed_ms"],
        }
        self.BENCH_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        (self.BENCH_DIR / ("bench_" + ts + ".json")).write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return result

    def stats(self) -> dict:
        """Stats."""
        results = []
        if self.BENCH_DIR.exists():
            for f in sorted(self.BENCH_DIR.glob("bench_*.json"))[-20:]:
                try:
                    results.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
        if not results:
            return {"total": 0, "local_wins": 0, "score": 0.0, "goal_95": False}
        local_wins = sum(1 for r in results if r.get("local", {}).get("code_ok") and r.get("winner") != "cloud")
        score = local_wins / len(results)
        return {"total": len(results), "local_wins": local_wins, "score": round(score, 3), "goal_95": score >= 0.95}


class KnowledgeHarvesterNode:
    def __init__(self) -> None:
        """Init."""
        self._extractor = ReasoningExtractor()
        self._templater = TemplateGenerator()
        self._bench = SilentBenchmark()
        self._total = 0

    def harvest_on_success(self, task: str, agent_output: str, code: str = "", agent: str = "laforge") -> int:
        """Harvest on success.

        Args:
            task: Description.
            agent_output: Description.
            code: Description.
            agent: Description.
        """
        entries = self._extractor.extract(agent_output, task, agent)
        entries += self._templater.extract_templates(code, task, agent) if code else []
        stored = _store_entries(entries)
        self._total += stored
        return stored

    def harvest_from_debug_result(self, debug_result: dict) -> int:
        """Harvest from debug result.

        Args:
            debug_result: Description.
        """
        if not debug_result.get("passed"):
            return 0
        task = debug_result.get("task", "")
        code = debug_result.get("final_code", "")
        out = "".join(
            s.get("output", "")[:400]
            for it in debug_result.get("history", [])
            for s in it.get("steps", [])
            if s.get("step") == "Write"
        )
        return self.harvest_on_success(task, out, code)

    def benchmark(self, task_idx: int = None) -> dict:
        """Benchmark.

        Args:
            task_idx: Description.
        """
        import random

        idx = task_idx if task_idx is not None else random.randint(0, 3)
        return self._bench.run_comparison(idx)

    def get_stats(self) -> dict:
        """Get stats."""
        s = self._bench.stats()
        s["total_harvested"] = self._total
        s["goal_95_label"] = "ATTEINT" if s["goal_95"] else str(round(s["score"] * 100, 1)) + "% / 95% requis"
        return s

    def generate_report(self) -> str:
        """Generate report."""
        s = self.get_stats()
        lines = [
            "# Knowledge Harvester — Rapport",
            "Date: " + time.strftime("%Y-%m-%d %H:%M"),
            "",
            "## Benchmark Ollama vs Cloud",
            "- Tests total: " + str(s["total"]),
            "- Victoires Ollama: " + str(s["local_wins"]),
            "- Score: " + str(round(s["score"] * 100, 1)) + "%",
            "- Objectif 95%: " + s["goal_95_label"],
            "",
            "## Recolte",
            "- Entrees harvested: " + str(s["total_harvested"]),
        ]
        bench_dir = SilentBenchmark.BENCH_DIR
        if bench_dir.exists():
            recent = sorted(bench_dir.glob("bench_*.json"))[-5:]
            if recent:
                lines.append("")
                lines.append("## Derniers benchmarks")
                for f in recent:
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                        winner = d.get("winner", "?")
                        local_str = "OK" if d.get("local", {}).get("code_ok") else "FAIL"
                        cloud_str = "OK" if d.get("cloud", {}).get("code_ok") else "FAIL"
                        ts_str = d.get("ts", "")
                        lines.append(
                            "- [" + ts_str + "] winner=" + winner + " local=" + local_str + " cloud=" + cloud_str
                        )
                    except Exception:
                        pass
        return "\n".join(lines)


_harvester = KnowledgeHarvesterNode()


def get_harvester() -> KnowledgeHarvesterNode:
    """Get harvester."""
    return _harvester


# Context:

# Context:

# Context:


def harvest_on_success(task: str, output: str, code: str = "") -> int:
    """Execute harvest operation on successful task completion.

    Args:
        task: Identifier of the completed task.
        output: Result output from the task execution.
        code: Optional code snippet associated with the task (default empty string).

    Returns:
        Integer status code from the harvest operation.
    """
    return _harvester.harvest_on_success(task, output, code)


def _handle_harvest_cmd(args: str = "", **kw) -> str:
    """Handler @harvest — benchmark + rapport."""
    h = get_harvester()
    if args.strip() == "bench":
        r = h.benchmark()
        return (
            "Benchmark: winner="
            + r.get("winner", "?")
            + " local_ok="
            + str(r.get("local", {}).get("code_ok", False))
            + " cloud_ok="
            + str(r.get("cloud", {}).get("code_ok", False))
        )
    return h.generate_report()
