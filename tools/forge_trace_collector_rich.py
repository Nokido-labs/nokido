#!/usr/bin/env python3
"""forge_trace_collector_rich.py — collecteur PARALLÈLE de traces riches (text-first).

LEÇON : embed via embed_router (litellm/cloud) = fragile (Permission denied packaging,
circuit breakers cloud). Donc DÉCOUPLAGE : la boucle stocke le TEXTE riche (tasks + mood +
hormones — zéro dép lourde, robuste), embeds DIFFÉRÉS. Un passage `--reencode` remplit les
embeddings 1024d via brain_worker ZMQ direct (§13, BGE-M3 LOCAL, pas de litellm/cloud).

Table `traces_rich` (séparée du 384d live). Rows text-only = dim=0 (à ré-encoder).
Run continu (trusted, loopback OK) : `python tools/forge_trace_collector_rich.py`
Re-encode  : `python tools/forge_trace_collector_rich.py --reencode`
Test       : `python tools/forge_trace_collector_rich.py --selftest`
"""
from __future__ import annotations
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / "RAG" / "execution_traces.db")
sys.path.insert(0, str(ROOT))

INTERVAL = 30


HEARTBEAT = ROOT / "sandbox" / "trace_collector_rich.heartbeat"


def _another_instance_alive() -> bool:
    """Single-instance guard : True si un AUTRE daemon collector tourne deja (par cmdline,
    pas juste PID — cf feedback PID GC). Evite la double-collecte (superviseur vs run_job/
    manuel). Best-effort : psutil absent -> False (degrade)."""
    try:
        import os as _os
        import psutil  # type: ignore

        me = _os.getpid()
        for p in psutil.process_iter(["pid", "cmdline"]):
            if p.info["pid"] == me:
                continue
            cl = " ".join(p.info.get("cmdline") or [])
            if "forge_trace_collector_rich" in cl and "--reencode" not in cl and "--selftest" not in cl:
                return True
    except Exception:
        pass
    return False


def _beat(tick: int, dim0: int) -> None:
    """Heartbeat superviseur (observabilite + detection hang)."""
    try:
        import os as _os

        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": _os.getpid(),
            "tick": tick, "interval_s": INTERVAL, "dim0_pending": dim0}))
    except Exception:
        pass


def init_db() -> None:
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """CREATE TABLE IF NOT EXISTS traces_rich (
            id TEXT PRIMARY KEY, ts REAL,
            state_t_emb BLOB, action_json TEXT, state_t1_emb BLOB,
            state_text_rich TEXT, cost_before REAL, cost_after REAL,
            task_type TEXT, success INTEGER, dim INTEGER)"""
    )
    con.commit()
    con.close()


def _count(where: str = "") -> int:
    con = sqlite3.connect(DB)
    n = con.execute(f"SELECT count(*) FROM traces_rich {where}").fetchone()[0]
    con.close()
    return n


def _record_text(prev_text: str, curr_text: str) -> None:
    """Stocke la transition en TEXTE (embeds différés, dim=0). Robuste (zéro embed)."""
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    action = {"type": "system_tick_rich", "prev_text": prev_text[:1500], "curr_text": curr_text[:1500], "ts": time.time()}
    con.execute(
        "INSERT OR IGNORE INTO traces_rich (id, ts, state_t_emb, action_json, state_t1_emb, "
        "state_text_rich, cost_before, cost_after, task_type, success, dim) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, time.time(), None, json.dumps(action), None,
         curr_text[:2000], None, None, "monitoring_rich", None, 0),
    )
    con.commit()
    con.close()


def run(max_ticks: int | None = None, interval: int = INTERVAL) -> int:
    from nokido_agent.app.forge_state_encoder import get_current_state_text_rich

    if max_ticks is None:
        # Cede a un collector deja vivant (ex: ancien lancement run_job) : on reste VIVANT
        # (heartbeat tick=-1 -> superviseur content, PAS de quick-fail quarantine) et on prend
        # le relais des qu'il disparait. Zero double-collecte, handoff automatique au reboot.
        while _another_instance_alive():
            _beat(-1, _count("WHERE dim=0"))
            time.sleep(interval)
    init_db()
    prev_text = None
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        try:
            curr_text = get_current_state_text_rich()
            if prev_text is not None:
                _record_text(prev_text, curr_text)
            prev_text = curr_text
        except Exception as e:
            print(f"[collector_rich] tick error: {e}", file=sys.stderr)
        ticks += 1
        if max_ticks is None:
            _beat(ticks, _count("WHERE dim=0"))
        if max_ticks is None or ticks < max_ticks:
            time.sleep(interval)
    return _count("WHERE dim=0")


def _embed_llama8099(texts: list[str]) -> list | None:
    """BGE-M3 1024d via NokidoLlamaEmbed :8099 (GGUF llama.cpp GPU). urllib, zéro dép lourde
    -> évite litellm/packaging (embed_router) ET le :5557 ONNX mort. C'est l'embedder local VIVANT."""
    import urllib.request
    import numpy as np

    out = []
    for t in texts:
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8099/v1/embeddings",
                data=json.dumps({"input": t}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            emb = d.get("data", [{}])[0].get("embedding") if "data" in d else d.get("embedding")
            if emb and isinstance(emb[0], list):
                emb = emb[0]
            v = np.array(emb, dtype="float32")
            if v.shape[0] != 1024:
                return None
            out.append(v)
        except Exception:
            return None
    return out


def _embed_brainworker(texts: list[str]) -> list | None:
    """Embed BGE-M3 1024d via brain_worker ZMQ direct (§13). Local, pas de litellm/cloud."""
    try:
        import zmq
        import msgpack
        import numpy as np
    except Exception:
        return None
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 10000)
    sock.setsockopt(zmq.LINGER, 0)
    try:
        sock.connect("tcp://localhost:5557")
        sock.send(msgpack.packb({"cmd": "submit", "type": "embed", "texts": texts}, use_bin_type=True))
        tid = msgpack.unpackb(sock.recv(), raw=False).get("task_id")
        if not tid:
            return None
        for _ in range(120):
            sock.send(msgpack.packb({"cmd": "check", "task_id": tid}, use_bin_type=True))
            res = msgpack.unpackb(sock.recv(), raw=False)
            st = res.get("status", "pending")
            if st == "completed":
                data = res.get("data")
                vecs = data.get("vecs") if isinstance(data, dict) else data
                return [np.array(v, dtype="float32") for v in vecs]
            if st == "error":
                return None
            time.sleep(0.5)
    except Exception:
        return None
    finally:
        sock.close()
    return None


def reencode_pending(batch: int = 20, max_rows: int | None = None) -> int:
    """Remplit les embeddings 1024d des rows dim=0 via brain_worker (§13). Idempotent."""
    import numpy as np

    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    done = 0
    while True:
        rows = con.execute("SELECT id, action_json FROM traces_rich WHERE dim<=0 LIMIT ?", (batch,)).fetchall()
        if not rows:
            break
        for rid, aj in rows:
            try:
                a = json.loads(aj or "{}")
                pt, ct = a.get("prev_text", ""), a.get("curr_text", "")
                vecs = _embed_llama8099([pt, ct]) or _embed_brainworker([pt, ct])
                if not vecs or len(vecs) != 2 or len(vecs[0]) != 1024:
                    con.execute("UPDATE traces_rich SET dim=-1 WHERE id=?", (rid,))  # -1 = embed KO, garde le texte
                    continue
                con.execute("UPDATE traces_rich SET state_t_emb=?, state_t1_emb=?, dim=1024 WHERE id=?",
                            (vecs[0].astype("float32").tobytes(), vecs[1].astype("float32").tobytes(), rid))
                done += 1
            except Exception:
                continue
        con.commit()
        if max_rows and done >= max_rows:
            break
    con.close()
    return done


def _selftest() -> int:
    init_db()
    before = _count("WHERE dim=0")
    _record_text("tasks:prev | mood: energy=0.5", "tasks:curr | mood: energy=0.6 | hormones: CORTISOL=0.4")
    after = _count("WHERE dim=0")
    con = sqlite3.connect(DB)
    row = con.execute("SELECT dim, state_text_rich, action_json FROM traces_rich ORDER BY ts DESC LIMIT 1").fetchone()
    con.close()
    assert after > before, f"aucune trace texte ecrite ({before}->{after})"
    a = json.loads(row[2])
    assert row[0] == 0 and "prev_text" in a and "curr_text" in a, row
    print(f"COLLECTOR-RICH OK (text-first) | dim0={after} | prev='{a['prev_text'][:40]}' curr='{a['curr_text'][:40]}' | embed differe (--reencode brain_worker)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--reencode" in sys.argv:
        print(f"[collector_rich] reencode brain_worker: {reencode_pending()} rows -> 1024d")
        raise SystemExit(0)
    _mt = None
    for _a in sys.argv:
        if _a.startswith("--max-ticks="):
            _mt = int(_a.split("=")[1])
    print(f"[collector_rich] text-first start, dim0 pending now: {run(max_ticks=_mt)}")
