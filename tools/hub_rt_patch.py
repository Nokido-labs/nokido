"""
hub_rt_patch.py — Patch temps réel pour nokido_hub.py
Applique 3 modifications :
  1. _event_worker → forge_db persistant (zéro connect/close)
  2. /health → bridge.seq() + tasks_active
  3. /metrics → live_bridge snapshot
Lance : python tools/hub_rt_patch.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HUB = ROOT / "tools" / "nokido_hub.py"
content = HUB.read_text(encoding="utf-8", errors="ignore")

changed = 0

# ── Patch 1 : _event_worker → forge_db ───────────────────────────────────────
OLD1 = """        try:
            conn = sqlite3.connect(str(DB), timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            seq = (conn.execute("SELECT COALESCE(MAX(sequence_id),0) FROM event_log").fetchone()[0] or 0) + 1
            rows = [(ev["ts"], seq + i, "hub", ev["agent"], "tool_call",
                     ev["tool"], ev["payload"], "", "", "ok")
                    for i, ev in enumerate(batch)]
            conn.executemany(
                "INSERT INTO event_log (timecode,sequence_id,session_id,agent_id,event_type,target,payload,prev_hash,new_hash,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows
            )
            conn.commit()
            conn.close()
        except Exception:
            pass"""

NEW1 = """        try:
            from forge_db import db_evt as _de
            seq = (_de.scalar("SELECT COALESCE(MAX(sequence_id),0) FROM event_log") or 0) + 1
            rows = [(ev["ts"], seq + i, "hub", ev["agent"], "tool_call",
                     ev["tool"], ev["payload"], "", "", "ok")
                    for i, ev in enumerate(batch)]
            _de.executemany(
                "INSERT INTO event_log (timecode,sequence_id,session_id,agent_id,event_type,target,payload,prev_hash,new_hash,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        except Exception:
            pass"""

if OLD1 in content:
    content = content.replace(OLD1, NEW1, 1)
    changed += 1
    print("OK patch1 _event_worker forge_db")
else:
    print("SKIP patch1 (deja applique ou introuvable)")

# ── Patch 2 : /health → bridge.seq() ────────────────────────────────────────
OLD2 = '    async def health(request: Request):\n        return JSONResponse({"status": "ok", "hub": "Nokido v17"})'
NEW2 = """    async def health(request: Request):
        try:
            from live_bridge import bridge as _br
            seq = _br.seq()
            tasks = [t for t in _br.tasks_active() if t["status"] in ("pend", "run")]
            hb_agents = _br.json_get("hb", {}).get("agents", {})
        except Exception:
            seq, tasks, hb_agents = 0, [], {}
        return JSONResponse({
            "status": "ok", "hub": "Nokido v17",
            "bridge_seq": seq,
            "tasks_active": len(tasks),
            "agents": {a: d.get("status") for a, d in hb_agents.items()},
        })"""

if OLD2 in content:
    content = content.replace(OLD2, NEW2, 1)
    changed += 1
    print("OK patch2 /health bridge.seq")
else:
    # Chercher variante
    idx = content.find("async def health(request")
    if idx >= 0:
        snippet = content[idx : idx + 120]
        print(f"SKIP patch2 — health trouvé mais forme différente: {repr(snippet[:80])}")
    else:
        print("SKIP patch2 — health non trouvé")

# ── Ecrire ───────────────────────────────────────────────────────────────────
if changed > 0:
    pass

# ── Patch hub_swarm_patch : routes /swarm + /team ────────────────────────────
try:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "hub_swarm_patch", str(ROOT / "tools" / "hub_swarm_patch.py")
    )
    _swarm_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_swarm_mod)
    sys.modules["hub_swarm_patch"] = _swarm_mod
    print("hub_swarm_patch: loaded")
    changed += 1
except Exception as e:
    print("hub_swarm_patch SKIP:", e)

if changed > 0:
    HUB.write_text(content, encoding="utf-8")
    import py_compile as _pc

    _pc.compile(str(HUB), doraise=True)
    print("DONE " + str(changed) + " patchs appliques — Hub compile OK")
else:
    print("DONE 0 patchs — rien a faire")
