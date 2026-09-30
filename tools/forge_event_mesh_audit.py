"""tools/forge_event_mesh_audit.py — Audit event bus existants pour event_mesh roadmap.

Avant integration mesh, mesurer ce qui existe :
- forge_event_stream.py (Manus 6-step loop)
- proxy_deno/core/nervous_system.ts (SystemBus/BloodCell)
- forge_byte_router.py (13 sentinels)
- forge_message_frame / forge_broker_base
- agent_chain_nodes table (SQL pub/sub-like)

Output : audit JSON avec throughput estime + redondance detectee.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


def scan_python_event_buses() -> dict:
    """Find files implementing event bus patterns."""
    candidates = (
        list((ROOT / "app").rglob("*event*.py"))
        + list((ROOT / "app").rglob("*broker*.py"))
        + list((ROOT / "app").rglob("*router*.py"))
        + list((ROOT / "app").rglob("*bus*.py"))
    )
    out = {}
    PATTERNS = {
        "pubsub": re.compile(r"publish\(|subscribe\(|on_message"),
        "queue": re.compile(r"asyncio\.Queue|put_nowait|get_nowait"),
        "actor": re.compile(r"actor|mailbox|send_to"),
        "topic": re.compile(r"topic\s*=|broadcast"),
        "stream": re.compile(r"async\s+for.*stream|EventStream|AsyncIterator"),
    }
    for fp in candidates:
        try:
            txt = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if len(txt) < 200:
            continue
        rel = str(fp.relative_to(ROOT))
        patterns_found = {k: bool(p.search(txt)) for k, p in PATTERNS.items()}
        out[rel] = {
            "lines": len(txt.splitlines()),
            "patterns": patterns_found,
            "has_async": "async def" in txt,
            "has_sqlite_persist": "sqlite3" in txt or "execute(" in txt,
        }
    return out


def scan_deno_event_buses() -> dict:
    """Find Deno TS files implementing event bus."""
    candidates = list((ROOT / "proxy_deno").rglob("*.ts")) if (ROOT / "proxy_deno").exists() else []
    out = {}
    for fp in candidates[:50]:
        try:
            txt = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "SystemBus" not in txt and "publish" not in txt and "subscribe" not in txt:
            continue
        rel = str(fp.relative_to(ROOT))
        out[rel] = {
            "lines": len(txt.splitlines()),
            "system_bus": "SystemBus" in txt,
            "publish": "publish(" in txt,
            "subscribe": "subscribe(" in txt,
            "blood_cell": "BloodCell" in txt,
        }
    return out


def estimate_event_throughput(window_hours: int = 24) -> dict:
    """Mesurer events recents via critical_events.db + agent_chain_nodes."""
    out = {}
    # critical_events
    ce_db = ROOT / "sandbox" / "critical_events.db"
    if ce_db.exists():
        try:
            con = sqlite3.connect(str(ce_db), timeout=3)
            cutoff = time.time() - window_hours * 3600
            n = con.execute(
                "SELECT COUNT(*) FROM forge_critical_events WHERE ts >= ?", (cutoff,)
            ).fetchone()[0]
            con.close()
            out["critical_events_24h"] = n
            out["critical_events_rate_per_h"] = round(n / max(1, window_hours), 2)
        except Exception as e:
            out["critical_events_err"] = str(e)

    # agent_chain_nodes
    if DB.exists():
        try:
            con = sqlite3.connect(str(DB), timeout=3)
            n = con.execute("SELECT COUNT(*) FROM agent_chain_nodes").fetchone()[0]
            out["chain_nodes_total"] = n
            recent = con.execute(
                "SELECT COUNT(*) FROM agent_chain_nodes WHERE done_at > datetime('now', '-1 day')"
            ).fetchone()[0]
            out["chain_nodes_done_24h"] = recent
            con.close()
        except Exception as e:
            out["chain_nodes_err"] = str(e)

    return out


def detect_redundancy(python_bus: dict, deno_bus: dict) -> list[dict]:
    """Detect functional overlap between buses."""
    issues = []

    # Multiple python pubsub implementations
    py_pubsub = [k for k, v in python_bus.items() if v["patterns"].get("pubsub")]
    if len(py_pubsub) > 1:
        issues.append(
            {
                "kind": "duplicate_pubsub",
                "files": py_pubsub,
                "advice": "Consolidate into single forge_event_mesh",
            }
        )

    # Python + Deno both have pubsub
    if py_pubsub and any(v.get("publish") for v in deno_bus.values()):
        issues.append(
            {
                "kind": "cross_runtime_duplication",
                "advice": "Decide single source of truth : Python OR Deno, bridge other",
            }
        )

    # Multiple queue implementations
    py_queue = [k for k, v in python_bus.items() if v["patterns"].get("queue")]
    if len(py_queue) > 1:
        issues.append(
            {
                "kind": "duplicate_queue",
                "files": py_queue,
            }
        )

    return issues


def audit_full() -> dict:
    py_bus = scan_python_event_buses()
    deno_bus = scan_deno_event_buses()
    throughput = estimate_event_throughput()
    redundancy = detect_redundancy(py_bus, deno_bus)

    return {
        "python_event_buses": py_bus,
        "deno_event_buses": deno_bus,
        "throughput_estimates": throughput,
        "redundancy_issues": redundancy,
        "summary": {
            "n_python_buses": len(py_bus),
            "n_deno_buses": len(deno_bus),
            "n_redundancy_issues": len(redundancy),
            "throughput_critical_per_h": throughput.get("critical_events_rate_per_h", 0),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = audit_full()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        s = result["summary"]
        print("=== Event Mesh Audit ===")
        print(f"Python buses : {s['n_python_buses']}")
        print(f"Deno buses   : {s['n_deno_buses']}")
        print(f"Redundancy issues : {s['n_redundancy_issues']}")
        print(f"Critical events rate : {s['throughput_critical_per_h']}/h")
        print()
        if result["redundancy_issues"]:
            print("ISSUES:")
            for issue in result["redundancy_issues"]:
                print(f"  - {issue['kind']}")
                if "files" in issue:
                    for f in issue["files"][:3]:
                        print(f"      {f}")


if __name__ == "__main__":
    main()
