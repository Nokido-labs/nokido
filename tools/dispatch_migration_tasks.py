"""
dispatch_migration_tasks.py — Inject migration tasks dans mailbox agent_messages.

Usage :
  LAFORGE_PYTHON tools/dispatch_migration_tasks.py --sprint B.3
  LAFORGE_PYTHON tools/dispatch_migration_tasks.py --task B.3.1
  LAFORGE_PYTHON tools/dispatch_migration_tasks.py --status

LLM cibles :
  agt_master_llamacpp  → qwen-coder:7b llamacpp natif :8080 (rapide local)
  agt_qwen_ollama      → qwen2.5-coder:32b Ollama :11434 (autonome long)
  agt_gemini           → Gemini cloud (long context, refactor)
  agt_codex            → Codex CLI (frontend/SSE complexe)
  agt_deepseek         → deepseek-r1:14b (reasoning, tests)
  agt_claude           → Claude (review critique only)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : suit l'interrupteur sandbox/m2m.switch
DB = Path(m2m_path())


# ── Catalog tasks (synced avec docs/roadmap_migration_multi_llm.md) ───
TASKS = {
    # Sprint 1 — B.3 UI + SSE
    "B.3.1": {
        "phase": "B.3",
        "to_agent": "agt_master_llamacpp",
        "subject": "Port /forge/rag UI HTML serving to Deno hub_mcp/main.ts",
        "files": ["proxy_deno/hub_mcp/main.ts", "tools/nokido_hub.py"],
        "ref_lines": "tools/nokido_hub.py:1989 (rag_ui handler)",
        "acceptance": "curl http://localhost:8769/forge/rag → 200 + HTML body",
        "deadline_h": 24,
        "ring_required": 2,
        "complexity": "easy",
    },
    "B.3.2": {
        "phase": "B.3",
        "to_agent": "agt_master_llamacpp",
        "subject": "Port /api/rag/{stats,tokenize} endpoints to Deno",
        "files": ["proxy_deno/hub_mcp/main.ts"],
        "ref_lines": "tools/nokido_hub.py:1990-1991",
        "acceptance": "curl :8769/api/rag/stats → JSON valid; POST /api/rag/tokenize echoes tokens",
        "deadline_h": 24,
        "ring_required": 2,
        "complexity": "easy",
    },
    "B.3.3": {
        "phase": "B.3",
        "to_agent": "agt_codex",
        "subject": "Port /forge/network UI + SSE stream to Deno (live event push)",
        "files": ["proxy_deno/hub_mcp/main.ts"],
        "ref_lines": "tools/nokido_hub.py:1992-1994",
        "acceptance": "EventSource browser test reçoit network events live <1s latency",
        "deadline_h": 48,
        "ring_required": 2,
        "complexity": "medium",
    },
    "B.3.4": {
        "phase": "B.3",
        "to_agent": "agt_codex",
        "subject": "Port /inbox/{agent_id} SSE streaming to Deno",
        "files": ["proxy_deno/hub_mcp/main.ts"],
        "ref_lines": "tools/nokido_hub.py:2003-2004 (inbox_stream)",
        "acceptance": "TUI multi-CLI agt_claude pane reçoit msgs via Deno SSE",
        "deadline_h": 48,
        "ring_required": 2,
        "complexity": "medium",
    },
    "B.3.5": {
        "phase": "B.3",
        "to_agent": "agt_qwen_ollama",
        "subject": "Port /ingest/url + /ingest/bulk pipelines to Deno",
        "files": ["proxy_deno/hub_mcp/main.ts"],
        "ref_lines": "tools/nokido_hub.py:2005",
        "acceptance": "POST /ingest/url avec URL valide → INSERT rag_chunks visible via SQL",
        "deadline_h": 48,
        "ring_required": 2,
        "complexity": "medium",
    },
    # Sprint 2 — B.4 Refactor Hono
    "B.4.1": {
        "phase": "B.4",
        "to_agent": "agt_gemini",
        "subject": "Refactor proxy_deno/web_hub/main.ts raw Deno.serve → Hono framework",
        "files": ["proxy_deno/web_hub/main.ts"],
        "ref_lines": "actuel : 240 LOC raw routing",
        "acceptance": "LOC réduits -50% (~120), tests E2E PASS, latency same",
        "deadline_h": 72,
        "ring_required": 3,
        "complexity": "medium",
        "hint": "Use jsr:@hono/hono + jsr:@hono/zod-validator. Keep all 8 endpoints.",
    },
    "B.4.2": {
        "phase": "B.4",
        "to_agent": "agt_qwen_ollama",
        "subject": "Add Zod schemas pour 8 endpoints PUBLIC webhub",
        "files": ["proxy_deno/web_hub/main.ts"],
        "ref_lines": "after B.4.1 done",
        "acceptance": "POST invalid body (missing required field) → 400 avec error détaillé Zod",
        "deadline_h": 24,
        "ring_required": 3,
        "complexity": "easy",
    },
    "B.4.3": {
        "phase": "B.4",
        "to_agent": "agt_codex",
        "subject": "Refactor proxy_deno/hub_mcp/main.ts raw → Hono",
        "files": ["proxy_deno/hub_mcp/main.ts"],
        "ref_lines": "actuel : 300 LOC raw routing",
        "acceptance": "LOC réduits -40%, tests E2E PASS, hot path latency <5% overhead",
        "deadline_h": 48,
        "ring_required": 3,
        "complexity": "medium",
    },
    # Sprint 3 — C Daemons
    "C.1": {
        "phase": "C",
        "to_agent": "agt_gemini",
        "subject": "Port tools/gemini_poll_daemon.py → proxy_deno/daemons/gemini_poll.ts",
        "files": ["proxy_deno/daemons/gemini_poll.ts"],
        "ref_lines": "tools/gemini_poll_daemon.py (full file)",
        "acceptance": "OAuth flow + mailbox poll équivalent Python, NSSM service replaceable",
        "deadline_h": 96,
        "ring_required": 3,
        "complexity": "hard",
        "hint": "Toi-meme connais bien ce daemon — porte avec autonomie.",
    },
    "C.2": {
        "phase": "C",
        "to_agent": "agt_qwen_ollama",
        "subject": "Port app/forge_rss_watcher.py → proxy_deno/daemons/rss_watcher.ts",
        "files": ["proxy_deno/daemons/rss_watcher.ts"],
        "ref_lines": "app/forge_rss_watcher.py",
        "acceptance": "Feedparser TS equivalent, INSERT rag_chunks équivalent",
        "deadline_h": 72,
        "ring_required": 3,
        "complexity": "medium",
    },
    "C.3": {
        "phase": "C",
        "to_agent": "agt_claude",  # critical algo
        "subject": "Port app/forge_hebbian_linker.py → proxy_deno/daemons/hebbian.ts (algo Hebbian)",
        "files": ["proxy_deno/daemons/hebbian.ts"],
        "ref_lines": "app/forge_hebbian_linker.py (synaptic plasticity)",
        "acceptance": "Métriques équivalentes Python (synaptic_score, decay rates)",
        "deadline_h": 96,
        "ring_required": 3,
        "complexity": "hard",
    },
    # Sprint 4 — D IPC
    "D.1": {
        "phase": "D",
        "to_agent": "agt_codex",
        "subject": "Implement Named Pipes Windows IPC TS module",
        "files": ["proxy_deno/utils/ipc.ts"],
        "ref_lines": "Deno.connect path://./pipe/nokido_brain",
        "acceptance": "Round-trip JSON-RPC <5ms local",
        "deadline_h": 48,
        "ring_required": 3,
        "complexity": "hard",
    },
    "D.3": {
        "phase": "D",
        "to_agent": "agt_claude",  # architecture
        "subject": "Brain worker bridge (Python ZMQ ↔ TS Named Pipe)",
        "files": ["proxy_deno/utils/ipc.ts", "app/brain_worker_bridge.py"],
        "ref_lines": "app/brain_worker.py ZMQ :5557",
        "acceptance": "Embeddings ONNX NPU accessibles via Deno (round-trip <50ms)",
        "deadline_h": 96,
        "ring_required": 4,
        "complexity": "hard",
    },
    # Sprint 5 — E Deno PID 1
    "E.1": {
        "phase": "E",
        "to_agent": "agt_claude",  # critical
        "subject": "Implement Deno supervisor (spawn Python sanctuaire processes)",
        "files": ["proxy_deno/supervisor.ts"],
        "ref_lines": "Deno.Command spawn 3 sanctuaire (brain_worker, hebbian, rss_watcher)",
        "acceptance": "3 Python processes UP via Deno spawn, restart auto si crash",
        "deadline_h": 168,
        "ring_required": 4,
        "complexity": "hard",
    },
}


def dispatch_task(task_id: str) -> bool:
    """Insert task dans mailbox + log."""
    if task_id not in TASKS:
        print(f"[!] task '{task_id}' inconnu")
        return False
    task = TASKS[task_id]
    msg_id = "task_" + hashlib.sha256(f"{task_id}{time.time()}".encode()).hexdigest()[:16]
    payload = json.dumps(
        {
            "task_id": task_id,
            "phase": task["phase"],
            "subject": task["subject"],
            "files": task["files"],
            "ref_lines": task["ref_lines"],
            "acceptance": task["acceptance"],
            "deadline_h": task["deadline_h"],
            "ring_required": task["ring_required"],
            "complexity": task["complexity"],
            "hint": task.get("hint", ""),
            "dispatched_at": time.time(),
            "dispatched_by": "naarob_via_claude_orchestrator",
        },
        ensure_ascii=False,
    )
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute(
            "INSERT INTO agent_messages (id, from_agent, to_agent, method, payload, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, "agt_naarob", task["to_agent"], "task.assign", payload, "pending"),
        )
        conn.commit()
        conn.close()
        print(f"  [✓] {task_id} → {task['to_agent']} ({task['complexity']})")
        return True
    except Exception as e:
        print(f"  [✗] {task_id} dispatch failed: {e}")
        return False


def status() -> dict:
    """État dispatch : pending vs done par LLM."""
    out = {"by_agent": {}, "by_phase": {}, "total_dispatched": 0}
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute(
            "SELECT to_agent, status, payload FROM agent_messages WHERE method='task.assign'"
        ).fetchall()
        conn.close()
        for to, st, pl in rows:
            out["total_dispatched"] += 1
            out["by_agent"].setdefault(to, {}).setdefault(st, 0)
            out["by_agent"][to][st] += 1
            try:
                p = json.loads(pl)
                out["by_phase"].setdefault(p.get("phase", "?"), {}).setdefault(st, 0)
                out["by_phase"][p.get("phase", "?")][st] += 1
            except Exception:
                pass
    except Exception as e:
        out["error"] = str(e)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sprint", help="dispatch all tasks of phase (B.3, B.4, C, D, E)")
    ap.add_argument("--task", help="dispatch single task (e.g., B.3.1)")
    ap.add_argument("--first-batch", action="store_true", help="dispatch 3 first parallel tasks")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for tid, t in TASKS.items():
            print(
                f"  {tid:8} [{t['complexity']:6}] {t['phase']:4} → {t['to_agent']:24} : {t['subject'][:60]}"
            )
    elif args.status:
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif args.first_batch:
        print("=== FIRST BATCH DISPATCH (3 parallel tasks) ===")
        for tid in ["B.3.1", "B.3.5", "B.4.1"]:
            dispatch_task(tid)
    elif args.task:
        dispatch_task(args.task)
    elif args.sprint:
        print(f"=== SPRINT {args.sprint} DISPATCH ===")
        for tid, t in TASKS.items():
            if t["phase"] == args.sprint:
                dispatch_task(tid)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
