"""forge_goap_online_launch.py — exécute le planner GOAP en contexte RÉSEAU + DB-write pour
que (a) le value_net ONLINE (HF MiniLM 384D aligné) soit live dans l'intuition, (b) les
trajectoires soient PERSISTÉES dans execution_traces.db (keystone self-play).

À lancer en session user (réseau + write DB) :
    "<laforge_py314>/python.exe" tools/forge_goap_online_launch.py
- plan_online(goal, effects)  : planifie seulement (montre intuition + réflexe oracle).
- run_and_record(goal, effects): planifie PUIS exécute (real tool calls) → persiste les traces.

Force LAFORGE_GOAP_VALUE_NET=online et charge le token hub (vault) AVANT d'importer le bridge
(le bridge lit HUB_TOKEN à l'import). Hors réseau/token → dégrade proprement (vec-only / 401).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT / "app"), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("LAFORGE_GOAP_VALUE_NET", "online")  # intention : value_net online

# Token hub AVANT l'import du bridge (HUB_TOKEN lu au niveau module). Best-effort vault.
if not (os.getenv("LAFORGE_HUB_TOKEN") or os.getenv("FORGE_MCP_TOKEN")):
    try:
        # 2b-6 (2026-09-28) : par le guichet (transition dite), plus en direct au coffre.
        from nokido_agent.app.forge_secrets import get_secret

        _tok = get_secret("FORGE_MCP_TOKEN") or get_secret("HUB_TOKEN")
        if _tok:
            os.environ["LAFORGE_HUB_TOKEN"] = _tok
    except Exception:
        pass

from nokido_agent.tools.forge_goap_hub_bridge import Goal, GOAPPlanner, _default_actions  # noqa: E402
from nokido_agent.app.forge_goap_intuition import make_default_providers  # noqa: E402


def _planner():
    pl = GOAPPlanner()
    for a in _default_actions():
        pl.add_action(a)
    return pl


def plan_online(goal_name: str, effects: dict, world_state: dict | None = None) -> dict:
    """Planifie seulement. Rapporte les providers d'intuition actifs (value = value_net online)."""
    pl = _planner()
    providers = make_default_providers()
    plan = pl.plan(world_state or {"hub_up": True}, Goal(goal_name, 1, {}, effects))
    return {
        "goal": goal_name,
        "plan": [a.name for a in plan],
        "value_net_mode": os.environ.get("LAFORGE_GOAP_VALUE_NET"),
        "intuition_providers": list(providers),
        "value_net_online_active": "value" in providers,
    }


def _trace_count() -> int:
    import sqlite3

    try:
        db = str(_ROOT / "RAG" / "execution_traces.db")
        return sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM traces WHERE task_type='goap'").fetchone()[0]
    except Exception:
        return -1


def run_and_record(goal_name: str, effects: dict, world_state: dict | None = None) -> dict:
    """Planifie PUIS exécute (real tool calls via le hub) → execute_plan persiste chaque
    transition dans execution_traces.db (keystone). Rapporte le delta de traces GOAP."""
    pl = _planner()
    plan = pl.plan(world_state or {"hub_up": True}, Goal(goal_name, 1, {}, effects))
    before = _trace_count()
    results = pl.execute_plan(plan)  # ← record_trajectory_step persiste ici
    after = _trace_count()
    return {
        "goal": goal_name,
        "plan": [a.name for a in plan],
        "executed": [{"action": r["action"], "ok": bool(r["result"].get("ok")),
                      "error": r["result"].get("error"),
                      "text": str(r["result"].get("text", ""))[:140]} for r in results],
        "goap_traces": {"before": before, "after": after, "persisted": (after - before) if before >= 0 else None},
    }


if __name__ == "__main__":
    # Démo : goal "génère un module" (effet RISQUÉ) → intuition + réflexe doute→oracle,
    # puis exécution réelle → traces persistées (1ères données self-play).
    print(json.dumps(run_and_record("generate_module", {"module_generated": True}),
                     ensure_ascii=False, indent=1))
