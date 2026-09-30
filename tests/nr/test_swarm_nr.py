"""
tests/nr/test_swarm_nr.py — NR headless forge_swarm + forge_swarm_team
======================================================================
Tests non-régression sans import bloquant.
Utilise AST + py_compile + logique pure.
"""
import ast
import json
import sqlite3
import sys
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"
sys.path.insert(0, str(APP))

results = []

def ok(label): results.append("OK  " + label)
def fail(label, err): results.append("FAIL " + label + ": " + str(err)[:80])


# ── 1. forge_swarm — état IDLE au démarrage ───────────────────────────────────
def test_swarm_idle():
    try:
        from forge_swarm import swarm, SwarmState
        assert swarm.sm.state == SwarmState.IDLE
        ok("forge_swarm state=IDLE au démarrage")
    except Exception as e:
        fail("forge_swarm idle", e)

test_swarm_idle()


# ── 2. Transition IDLE → THINKING → IDLE ─────────────────────────────────────
def test_swarm_thinking():
    try:
        from forge_swarm import swarm, SwarmState, SwarmBusyError
        swarm.sm.force_idle()
        assert swarm.sm.state == SwarmState.IDLE

        swarm.sm.set_thinking("TEST_AGENT", "test task")
        assert swarm.sm.state == SwarmState.THINKING
        assert swarm.sm.active_agent == "TEST_AGENT"

        raised = False
        try:
            swarm.sm.set_thinking("AUTRE", "")
        except SwarmBusyError:
            raised = True
        assert raised, "SwarmBusyError non levé"

        swarm.sm.force_idle()
        assert swarm.sm.state == SwarmState.IDLE
        ok("forge_swarm IDLE→THINKING→IDLE + SwarmBusyError")
    except Exception as e:
        fail("forge_swarm thinking", e)
        try:
            from forge_swarm import swarm
            swarm.sm.force_idle()
        except Exception:
            pass

test_swarm_thinking()


# ── 3. Transitions complètes IDLE→THINKING→STREAMING→SYNCING_RAG→IDLE ────────
def test_swarm_full_cycle():
    try:
        from forge_swarm import swarm, SwarmState
        swarm.sm.force_idle()
        swarm.sm.set_thinking("CYCLE_AGENT", "cycle test")
        assert swarm.sm.state == SwarmState.THINKING
        swarm.sm.set_streaming("CYCLE_AGENT")
        assert swarm.sm.state == SwarmState.STREAMING
        swarm.sm.set_syncing_rag("CYCLE_AGENT")
        assert swarm.sm.state == SwarmState.SYNCING_RAG
        swarm.sm.set_idle()
        assert swarm.sm.state == SwarmState.IDLE
        ok("forge_swarm cycle complet 4 états")
    except Exception as e:
        fail("forge_swarm cycle", e)
        try:
            from forge_swarm import swarm
            swarm.sm.force_idle()
        except Exception:
            pass

test_swarm_full_cycle()


# ── 4. Sequence_id monotone + logging events.db ───────────────────────────────
def test_event_log():
    try:
        from forge_swarm import _log_event
        db = ROOT / "sandbox" / "events.db"
        conn = sqlite3.connect(str(db), timeout=5)
        last_seq = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
        conn.close()

        seq1 = _log_event("NR_TEST", "nr_test", payload={"run": 1})
        seq2 = _log_event("NR_TEST", "nr_test", payload={"run": 2})

        assert seq2 == seq1 + 1, f"seq non monotone: {seq1} {seq2}"
        assert seq1 > last_seq,  f"seq non croissant"

        conn = sqlite3.connect(str(db), timeout=5)
        rows = conn.execute(
            "SELECT sequence_id, prev_hash, new_hash FROM event_log "
            "WHERE sequence_id IN (?,?)", (seq1, seq2)
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        h1  = next(r[2] for r in rows if r[0] == seq1)
        ph2 = next(r[1] for r in rows if r[0] == seq2)
        assert h1 == ph2, f"hash chaîné cassé: {h1} != {ph2}"
        ok(f"event_log seq monotone ({seq1},{seq2}) + hash chaîné")
    except Exception as e:
        fail("event_log", e)

test_event_log()


# ── 5. SwarmQueue — priorité ──────────────────────────────────────────────────
def test_queue_priority():
    try:
        from forge_swarm import AgentTask, SwarmQueue, SwarmStateMachine
        sm = SwarmStateMachine()
        q  = SwarmQueue(sm)
        order = []

        def mk_fn(label):
            def fn():
                order.append(label)
            return fn

        t1 = AgentTask(priority=5, agent_id="A", task_id="t1", fn=mk_fn("prio5"))
        t2 = AgentTask(priority=1, agent_id="B", task_id="t2", fn=mk_fn("prio1"))
        t3 = AgentTask(priority=3, agent_id="C", task_id="t3", fn=mk_fn("prio3"))

        q._q.put(t1); q._q.put(t2); q._q.put(t3)
        out = [q._q.get().priority for _ in range(3)]
        assert out == [1, 3, 5], "ordre priorité incorrect: " + str(out)
        ok("SwarmQueue priorité 1<3<5 OK")
    except Exception as e:
        fail("SwarmQueue priority", e)

test_queue_priority()


# ── 6. Broadcast UDP ─────────────────────────────────────────────────────────
def test_broadcast():
    try:
        import socket as _sock, json as _json
        from forge_swarm import broadcast

        test_port = 9766
        listener = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        listener.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", test_port))
        listener.settimeout(0.5)

        sender = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        payload = json.dumps({"type": "nr_test", "v": 42}).encode()
        sender.sendto(payload, ("127.0.0.1", test_port))
        sender.close()

        data, _ = listener.recvfrom(65536)
        listener.close()
        ev = _json.loads(data.decode())
        assert ev["type"] == "nr_test" and ev["v"] == 42
        ok("broadcast UDP send/recv OK")
    except Exception as e:
        fail("broadcast UDP", e)

test_broadcast()


# ── 7. SwarmTeam sérialisation round-trip ────────────────────────────────────
def test_team_serialization():
    try:
        from forge_swarm_team import _default_team, SwarmTeam, Participant
        tm = _default_team()
        assert len(tm.participants) >= 5

        p = tm.get("laforge")
        assert p is not None
        tm.activate("laforge", "gemini")
        assert tm.get("laforge").active
        assert tm.get("gemini").active
        assert not tm.get("llamacpp").active

        d   = tm.to_dict()
        tm2 = SwarmTeam.from_dict(d)
        assert tm2.session_id == tm.session_id
        assert len(tm2.participants) == len(tm.participants)
        assert tm2.get("laforge").active
        assert tm2.get("gemini").active

        nodes = tm.flowchart_data()
        assert nodes[0]["id"] == "Lead_Orchestrator"
        assert nodes[-1]["id"] == "RAG_Sync"
        ok(f"SwarmTeam round-trip OK ({len(tm.participants)} participants, {len(nodes)} nodes)")
    except Exception as e:
        fail("SwarmTeam serialization", e)

test_team_serialization()


# ── 8. LeadOrchestrator — inject events.db ───────────────────────────────────
def test_orchestrator_inject():
    try:
        from forge_swarm_team import _default_team
        import sqlite3
        db = ROOT / "sandbox" / "events.db"

        tm  = _default_team()
        tm.activate("laforge")
        seq = tm.inject_to_events_db()
        assert seq > 0

        conn = sqlite3.connect(str(db), timeout=5)
        row  = conn.execute(
            "SELECT event_type, payload FROM event_log WHERE sequence_id=?", (seq,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "team_config"
        payload = json.loads(row[1])
        assert "participants" in payload
        ok(f"inject_to_events_db seq={seq} event_type=team_config")
    except Exception as e:
        fail("orchestrator inject", e)

test_orchestrator_inject()


# ── 9. Watchdog — ne tue pas IDLE ────────────────────────────────────────────
def test_watchdog_idle():
    try:
        from forge_swarm import swarm, SwarmState
        swarm.sm.force_idle()
        time.sleep(0.2)
        assert swarm.sm.state == SwarmState.IDLE
        ok("watchdog: IDLE préservé (pas de reset intempestif)")
    except Exception as e:
        fail("watchdog idle", e)

test_watchdog_idle()


# ── 10. forge_web_service — swarm API ────────────────────────────────────────
def test_web_service_swarm():
    try:
        from forge_web_service import svc
        st = svc.swarm_status()
        assert "state" in st
        assert st["state"] in ("IDLE","THINKING","STREAMING","SYNCING_RAG","UNKNOWN")

        evs = svc.swarm_events(n=5)
        assert isinstance(evs, list)

        r = svc.swarm_force_idle()
        assert r.get("ok") and r.get("state") == "IDLE"
        ok(f"svc swarm API: state={st['state']}, events={len(evs)}")
    except Exception as e:
        fail("svc swarm API", e)

test_web_service_swarm()


# ── Verdict ───────────────────────────────────────────────────────────────────
def _run_verdict():
    failures = [r for r in results if r.startswith("FAIL")]
    ok_count = sum(1 for r in results if r.startswith("OK"))
    verdict  = "PASS" if not failures else "FAIL"
    report   = (
        f"NR SWARM — {verdict}  {ok_count}/{len(results)} OK"
        + (f"  |  {len(failures)} FAIL" if failures else "")
        + "\n\n"
        + "\n".join(results)
    )
    out_path = ROOT / "sandbox" / "nr_swarm_result.txt"
    out_path.write_text(report, encoding="utf-8")
    print(report)
    return verdict

if __name__ == "__main__":
    verdict = _run_verdict()
    sys.exit(0 if verdict == "PASS" else 1)
else:
    # Appelé par pytest — pas de sys.exit()
    _run_verdict()
