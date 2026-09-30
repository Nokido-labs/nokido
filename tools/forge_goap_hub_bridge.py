"""
tools/forge_goap_hub_bridge.py — GOAP planner wired to Nokido hub MCP API.
Gap#0 of the software-creator roadmap: Goal Oriented Action Planning -> hub tool calls.
"""

import io as _io
import os
import sys as _sys

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.app.forge_secrets import get_secret

import json as _json
import urllib.request as _urllib
from dataclasses import dataclass, field

# Chemin DERIVE du fichier (phase 0 renommage) : le test temporaire du GOAP vit dans
# tools/ du depot. Il part dans un payload destine a un shell externe, donc il ne peut
# pas etre derive sur place : il est interpole ici, une seule fois.
_GOAP_TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_goap_test.py").replace("\\", "/")

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

HUB_URL = "http://127.0.0.1:8766/mcp"
# FORGE_MCP_TOKEN is the canonical hub token; LAFORGE_HUB_TOKEN kept for compat
HUB_TOKEN = get_secret("LAFORGE_HUB_TOKEN") or get_secret("FORGE_MCP_TOKEN") or ""
LAFORGE_PYTHON = os.getenv("LAFORGE_PYTHON_BIN", "%USERPROFILE%/miniforge3/python.exe")


@dataclass
class Goal:
    name: str
    priority: int
    preconditions: dict[str, bool]
    effects: dict[str, bool]


@dataclass
class Action:
    name: str
    cost: int
    preconditions: dict[str, bool]
    effects: dict[str, bool]
    hub_tool: str
    hub_args: dict = field(default_factory=dict)


def _log_action(action: "Action", result: dict) -> None:
    """Log SYSTÉMATIQUE de TOUTE action GOAP (existante ou nouvelle) via l'event-bus —
    la méthode établie (cf. ORACLE_INVOKED). Best-effort : ne lève jamais. Toute action
    qui passe par execute_plan est tracée → aucun ajout silencieux possible."""
    try:
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from nokido_agent.app.forge_swarm_bus import publish

        publish(
            kind="GOAP_ACTION",
            data={
                "action": action.name,
                "hub_tool": action.hub_tool,
                "ok": bool(result.get("ok")),
                "err": (result.get("error") or "")[:160],
            },
            topic="goap",
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[goap] action NON publiee sur le bus (%s: %s) | consequence: cette "
            "decision du planificateur n'apparaitra dans aucune trace, et son absence "
            "se lira comme une absence de decision", type(e).__name__, str(e)[:90])


def _conf_journalisable(conf):
    """Rend la confiance sous une forme sérialisable SANS écraser le troisième état.

    `conf` vaut None quand la marge n'est pas mesurable. `float(None)` lèverait, et le
    `except` best-effort des journaux avalerait la trace — on perdrait justement la
    décision incertaine, celle qui méritait le plus d'être lue.
    """
    return None if conf is None else round(float(conf), 3)


def _log_intuition(goal, scored, conf, allowed) -> None:
    """Log de la décision d'intuition GOAP (event-bus = méthode établie). Best-effort."""
    try:
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from nokido_agent.app.forge_swarm_bus import publish

        publish(
            kind="GOAP_INTUITION",
            data={
                "goal": getattr(goal, "name", "?"),
                "confidence": _conf_journalisable(conf),
                "top": [(a.name, round(float(s), 3)) for a, s, _ in scored[:5]],
                "pruned_to": sorted(allowed) if allowed else None,
            },
            topic="goap",
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[goap] intuition NON publiee (%s: %s) | consequence: le classement des "
            "actions candidates est perdu, et un elagage ne pourra pas etre relu",
            type(e).__name__, str(e)[:90])


def _log_doubt_reflex(goal, conf) -> None:
    """Log du réflexe doute→oracle déclenché (event-bus). Best-effort."""
    try:
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from nokido_agent.app.forge_swarm_bus import publish

        publish(kind="GOAP_DOUBT_REFLEX",
                data={"goal": getattr(goal, "name", "?"), "confidence": _conf_journalisable(conf),
                      "action": "oracle inséré avant action risquée"},
                topic="goap")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # Le reflexe de doute insere un oracle AVANT une action risquee. Sa trace
        # perdue, on ne saura pas que le systeme a hesite — ni pourquoi il a insere
        # une verification.
        _lg.getLogger(__name__).warning(
            "[goap] reflexe de DOUTE non publie (%s: %s) | consequence: l'hesitation "
            "avant une action risquee ne laissera aucune trace",
            type(e).__name__, str(e)[:90])


class GOAPPlanner:
    def __init__(self):
        self.goals: list[Goal] = []
        self.actions: list[Action] = []

    def add_goal(self, goal: Goal):
        self.goals.append(goal)

    def add_action(self, action: Action):
        self.actions.append(action)

    def plan(self, world_state: dict[str, bool], goal: Goal, *, intuition: bool = True,
             providers=None, top_k: int = 4, conf_threshold: float = 0.25,
             doubt_reflex: bool = True,
             risky_effects=frozenset({"file_written", "module_generated", "python_run"})) -> list[Action]:
        """BFS forward-chaining, mais l'ordre + l'élagage des actions viennent de l'INTUITION
        (Système 1) au lieu du coût statique. Porte signal/bruit : intuition NETTE
        (confidence>=seuil) → élague aux top_k ; PLATE → garde tout. Garde-fou correctness :
        si la voie étroite de l'intuition échoue, on RÉ-ÉLARGIT (Système 2)."""
        ordered = sorted(self.actions, key=lambda a: a.cost)  # fallback déterministe
        allowed = None
        # UNKNOWN par défaut, jamais 1.0 : tant que l'intuition n'a rien MESURÉ, la
        # confiance n'existe pas. Un défaut à 1.0 faisait élaguer dur et désarmait le
        # réflexe doute→oracle sur les chemins où l'intuition ne tourne pas ou lève.
        conf = None
        if intuition and self.actions:
            try:
                _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
                from nokido_agent.app.forge_goap_intuition import intuition_rank, make_default_providers

                state_text = f"{goal.name} " + " ".join(goal.effects.keys())
                scored, conf = intuition_rank(
                    state_text, self.actions, providers=providers or make_default_providers()
                )
                ordered = [a for a, _, _ in scored]
                # conf is None = marge non mesurable : on n'élague PAS sur ce qu'on
                # n'a pas mesuré (liste blanche : n'élague que ce qui est PROUVÉ net).
                if conf is not None and conf >= conf_threshold:
                    allowed = {a.name for a in ordered[:top_k]}
                _log_intuition(goal, scored, conf, allowed)
            except Exception:  # noqa: BLE001 — l'intuition ne casse JAMAIS le planner
                ordered = sorted(self.actions, key=lambda a: a.cost)
                allowed = None
                conf = None  # l'intuition a ÉCHOUÉ : sa confiance est inconnue, pas maximale

        # RÉFLEXE doute→oracle : incertain (conf < seuil = signal PLAT/rumination) → toute action
        # à effet RISQUÉ exige d'abord hypothesis_tested (le planner insère l'oracle AVANT).
        # "Dans le doute, teste avant d'agir." conf basse ⇒ allowed=None ⇒ oracle non élagué.
        if doubt_reflex and (conf is None or conf < conf_threshold) and any(
            a.hub_tool == "oracle_python_repl" for a in self.actions
        ):
            guarded, triggered = [], False
            for a in ordered:
                if any(e in risky_effects for e in a.effects):
                    guarded.append(Action(a.name, a.cost, {**a.preconditions, "hypothesis_tested": True},
                                          a.effects, a.hub_tool, a.hub_args))
                    triggered = True
                else:
                    guarded.append(a)
            if triggered:
                ordered = guarded
                _log_doubt_reflex(goal, conf)

        result = self._bfs(world_state, goal, ordered, allowed)  # Système 1 (élagué)
        if not result and allowed is not None:  # l'intuition étroite a échoué → Système 2
            result = self._bfs(world_state, goal, ordered, None)
        return result

    def _bfs(self, world_state: dict[str, bool], goal: Goal, ordered: list[Action],
             allowed: set | None) -> list[Action]:
        """BFS forward-chaining lowest-cost. `ordered` = ordre d'expansion (intuition/coût),
        `allowed` = sous-ensemble d'actions autorisées (None = toutes)."""
        from collections import deque

        queue = deque([(world_state.copy(), [], 0)])
        visited: set = set()

        while queue:
            state, plan, cost = queue.popleft()

            if all(state.get(k) == v for k, v in goal.effects.items()):
                return plan

            if len(plan) > 6:  # depth limit
                continue

            state_key = frozenset(state.items())
            if state_key in visited:
                continue
            visited.add(state_key)

            for action in ordered:
                if allowed is not None and action.name not in allowed:
                    continue
                if not all(state.get(k) == v for k, v in action.preconditions.items()):
                    continue
                new_state = {**state}
                for k, v in action.effects.items():
                    new_state[k] = v
                queue.append((new_state, plan + [action], cost + action.cost))

        return []

    def _hub_call(self, action: Action) -> dict:
        payload = _json.dumps(
            {
                "method": "tools/call",
                "params": {
                    "name": action.hub_tool,
                    "arguments": action.hub_args,
                },
            }
        ).encode()
        req = _urllib.Request(
            HUB_URL,
            data=payload,
            headers={"Authorization": f"Bearer {HUB_TOKEN}", "Content-Type": "application/json"},
        )
        try:
            with _urllib.urlopen(req, timeout=60) as resp:
                data = _json.loads(resp.read())
            content = data.get("result", {}).get("content", [])
            text = content[0].get("text", "") if content else ""
            return {"ok": True, "text": text, "raw": data}
        except Exception as e:
            return {"ok": False, "error": str(e), "action": action.name}

    def execute_plan(self, plan: list[Action]) -> list[dict]:
        results = []
        # KEYSTONE self-play : embedder résolu 1× (online aligné si LAFORGE_GOAP_VALUE_NET=online)
        try:
            _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
            from nokido_agent.app.forge_goap_intuition import record_trajectory_step, resolve_embed_fn

            _ef = resolve_embed_fn()
        except Exception:  # noqa: BLE001
            record_trajectory_step, _ef = None, None
        done: list[str] = []
        for action in tqdm(plan, desc="executing plan", unit="action"):
            print(f"  -> {action.name} ({action.hub_tool})")
            result = self._hub_call(action)
            _log_action(action, result)  # LOG systématique (event-bus) — couvre tout nouvel ajout
            if record_trajectory_step is not None:  # PERSISTE la transition → execution_traces.db
                st = " -> ".join(done) or "start"
                act = {"name": action.name, "hub_tool": action.hub_tool,
                       "args": str(action.hub_args)[:200], "cost": action.cost}
                try:
                    record_trajectory_step(f"goap: {st}", act, f"goap: {st} -> {action.name}",
                                           bool(result.get("ok")), embed_fn=_ef)
                except Exception:  # noqa: BLE001
                    pass
            done.append(action.name)
            results.append({"action": action.name, "result": result})
        return results


# ─── Scorecard routing ────────────────────────────────────────────────────────
# Pont entre forge_mcp_registry.handle_task_result (qui ecrit
# tasks.scorecard_json via forge_scorecard.store_for_task) et le planner GOAP
# qui doit decider la suite : close / refine / ban_and_retry / judge.

# Chemin DERIVE du fichier (phase 0 du renommage vers Nokido) : le dossier du
# depot doit pouvoir etre renomme sans casser ce pont. tools/ -> parent.parent.
_TASKS_DB = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "sandbox" / "tasks.db")


def read_task_scorecard(task_id: str, db_path: str | None = None):
    """Charge la Scorecard d'une tache. Retourne None si absente ou DB KO.
    db_path=None -> resolu a runtime depuis _TASKS_DB (monkey-patchable)."""
    import sqlite3

    if db_path is None:
        db_path = _TASKS_DB
    conn = None
    row = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        row = conn.execute("SELECT scorecard_json FROM tasks WHERE id=?", (task_id,)).fetchone()
    except sqlite3.OperationalError:
        return None  # DB inexistante ou colonne scorecard_json absente
    finally:
        if conn is not None:
            conn.close()
    if not row or not row[0]:
        return None
    try:
        raw = _json.loads(row[0])
        import os as _o
        import sys as _s

        _s.path.insert(0, _o.path.join(_o.path.dirname(__file__), "..", "app"))
        from nokido_agent.app.forge_scorecard import ExecutionState, QualityGrade, Scorecard, ScoreMetrics

        return Scorecard(
            state=ExecutionState(raw.get("state", "COMPLETED")),
            grade=QualityGrade(raw.get("grade", "UNRATED")),
            confidence_score=float(raw.get("confidence_score", 0.0)),
            metrics=ScoreMetrics(**(raw.get("metrics") or {})),
            payload=raw.get("payload"),
            critique=str(raw.get("critique", "")),
        )
    except Exception:
        return None


def route_next_action(task_id: str, db_path: str | None = None) -> str:
    """Retourne l'action GOAP suivante d'apres la Scorecard.
    close | refine | ban_and_retry | judge (UNRATED -> trigger juge LLM)."""
    sc = read_task_scorecard(task_id, db_path=db_path)
    if sc is None:
        return "judge"
    import os as _o
    import sys as _s

    _s.path.insert(0, _o.path.join(_o.path.dirname(__file__), "..", "app"))
    from nokido_agent.app.forge_scorecard import next_action_for

    return next_action_for(sc)


def _default_actions() -> list[Action]:
    return [
        Action(
            "run_shell",
            cost=1,
            preconditions={"hub_up": True},
            effects={"shell_run": True},
            hub_tool="run",
            hub_args={"action": "shell", "code": "echo ok"},
        ),
        Action(
            "run_python",
            cost=1,
            preconditions={"hub_up": True},
            effects={"python_run": True},
            hub_tool="run",
            hub_args={"action": "python", "code": "print('ok')"},
        ),
        Action(
            # Oracle d'exécution déterministe : tester une hypothèse (lib/regex/format)
            # AU LIEU d'halluciner. Effet 'hypothesis_tested' = gate avant génération risquée.
            "oracle",
            cost=1,
            preconditions={"hub_up": True},
            effects={"hypothesis_tested": True},
            hub_tool="oracle_python_repl",
            hub_args={"code": "print('oracle ready')"},
        ),
        Action(
            "ask_llm",
            cost=2,
            preconditions={"hub_up": True},
            effects={"llm_response": True, "module_generated": True},
            hub_tool="ask",
            hub_args={"provider": "groq", "message": "Generate a Python module stub"},
        ),
        Action(
            "ingest_url",
            cost=2,
            preconditions={"hub_up": True},
            effects={"documentation_ingested": True},
            hub_tool="crawl",
            hub_args={"url": "https://docs.python.org/3/"},
        ),
        Action(
            "search_rag",
            cost=1,
            preconditions={"hub_up": True},
            effects={"search_results": True},
            hub_tool="rag",
            hub_args={"query": "module generation"},
        ),
        Action(
            "write_file",
            cost=1,
            preconditions={"hub_up": True},
            effects={"file_written": True},
            hub_tool="write",
            hub_args={"path": "tools/tmp_goap_out.py", "content": "# placeholder"},
        ),
        Action(
            "run_tests",
            cost=2,
            preconditions={"hub_up": True, "file_written": True},
            effects={"tests_pass": True},
            hub_tool="run",
            hub_args={
                "action": "python",
                "code": f"import subprocess,sys\nr=subprocess.run([sys.executable,'-m','pytest',r'{_GOAP_TEST}','-x','-q','-p','no:cacheprovider'],capture_output=True,text=True,timeout=30)\nprint(r.stdout)\nif r.returncode: print('STDERR:',r.stderr[-200:])",
            },
        ),
    ]


def _default_goals() -> list[Goal]:
    return [
        Goal(
            "generate_module",
            priority=1,
            preconditions={"hub_up": True},
            effects={"module_generated": True},
        ),
        Goal(
            "fix_failing_test",
            priority=2,
            preconditions={"hub_up": True},
            effects={"tests_pass": True},
        ),
        Goal(
            "ingest_documentation",
            priority=3,
            preconditions={"hub_up": True},
            effects={"documentation_ingested": True},
        ),
        Goal(
            "generate_and_test",
            priority=1,
            preconditions={"hub_up": True},
            effects={"file_written": True, "tests_pass": True},
        ),
    ]


def run_e2e_test() -> bool:
    """E2E: GOAP plans write_file + run_tests, verifies pytest passes."""

    # 1. Generate the test file content via hub write
    module_code = (
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
        "    assert add(-1, 1) == 0\n"
        "    assert add(0, 0) == 0\n"
    )

    planner = GOAPPlanner()
    # Override write_file and run_tests with E2E-specific args
    for a in _default_actions():
        if a.name == "write_file":
            a.hub_args = {"path": "tools/tmp_goap_test.py", "content": module_code}
        if a.name == "run_tests":
            a.hub_args = {
                "action": "python",
                "code": (
                    "import subprocess,sys\n"
                    "r=subprocess.run([r'%USERPROFILE%/miniforge3/python.exe','-m','pytest',"
                    f"r'{_GOAP_TEST}',"
                    "'-x','-q','-p','no:cacheprovider'],capture_output=True,text=True,timeout=30)\n"
                    "print(r.stdout)\n"
                    "if r.returncode: print('STDERR:',r.stderr[-200:])"
                ),
            }
        planner.add_action(a)

    goal = next(g for g in _default_goals() if g.name == "generate_and_test")
    world = {"hub_up": True}

    print("=== GOAP E2E: generate_and_test ===")
    plan = planner.plan(world, goal)
    if not plan:
        print("FAIL: no plan found")
        return False

    print(f"Plan ({len(plan)} actions): {' -> '.join(a.name for a in plan)}")
    results = planner.execute_plan(plan)

    ok = True
    for r in results:
        status = "✓" if r["result"].get("ok") else "✗"
        text = r["result"].get("text", r["result"].get("error", ""))[:120]
        print(f"  {status} [{r['action']}] {text}")
        if not r["result"].get("ok"):
            ok = False

    # Check pytest output in run_tests result
    for r in results:
        if r["action"] == "run_tests":
            txt = r["result"].get("text", "")
            if "passed" in txt and "error" not in txt.lower():
                print("  -> pytest PASSED")
            elif "failed" in txt or "error" in txt.lower():
                print(f"  -> pytest FAILED: {txt[:200]}")
                ok = False
            break

    print(f"\nE2E result: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    import sys as _sys

    if hasattr(_sys.stdout, "buffer"):
        _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")

    if "--e2e" in _sys.argv:
        success = run_e2e_test()
        _sys.exit(0 if success else 1)

    planner = GOAPPlanner()
    for a in _default_actions():
        planner.add_action(a)
    for g in _default_goals():
        planner.add_goal(g)

    world = {"hub_up": True}
    target = next(g for g in planner.goals if g.name == "generate_module")

    print(f"Planning for goal: {target.name}")
    plan = planner.plan(world, target)

    if not plan:
        print("No plan found for current world state.")
    else:
        print(f"Plan ({len(plan)} actions, cost={sum(a.cost for a in plan)}):")
        for i, a in enumerate(plan, 1):
            print(f"  {i}. {a.name} -> {a.hub_tool}")
        results = planner.execute_plan(plan)
        for r in results:
            txt = r["result"].get("text", r["result"].get("error", ""))[:80]
            print(f"  [{r['action']}] {txt}")
