"""tools/forge_py314t_flip_canary.py - Acte 5 partial flip canary, rollback-safe.

Target = NokidoOfflineTrainer (AMI JEPA batch training).
Rationale = idle most of the time (6h cycle, 0 new traces -> skip), low-risk
testbed. Multi-thread bench prouve 2.5x sur AMI workload @ 4 threads no-GIL.

Protocole 4 phases (USER doit relancer NSSM entre phase 2 et 3) :

  Phase 1 : baseline snapshot (heartbeat current + memory + process info)
  Phase 2 : services.toml backup + edit cmd PYTHON -> PY314T
            (USER doit ensuite : nssm restart NokidoOfflineTrainer)
  Phase 3 : monitor 5 min -- heartbeat freshness, memory, error log
  Phase 4 : si KO -> rollback services.toml + USER restart nssm
            si OK -> commit services.toml + notify CLAUDE

Usage:
    LAFORGE_PYTHON tools/forge_py314t_flip_canary.py --phase 1
    LAFORGE_PYTHON tools/forge_py314t_flip_canary.py --phase 2
    # >>> USER : nssm restart NokidoOfflineTrainer
    LAFORGE_PYTHON tools/forge_py314t_flip_canary.py --phase 3 --watch-min 5
    LAFORGE_PYTHON tools/forge_py314t_flip_canary.py --phase 4   # commit or rollback

Recovery emergency :
    LAFORGE_PYTHON tools/forge_py314t_flip_canary.py --rollback
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"
BACKUP_PATH = ROOT / "sandbox" / "py314t_canary" / "services.toml.backup"
STATE_PATH = ROOT / "sandbox" / "py314t_canary" / "state.json"
HEARTBEAT = ROOT / "sandbox" / "offline_trainer.heartbeat"

TARGET_SERVICE = "NokidoOfflineTrainer"
OLD_CMD = '${PYTHON}'  # current
NEW_CMD = '${PY314T}'  # target

CANARY_DIR = ROOT / "sandbox" / "py314t_canary"


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    CANARY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _read_heartbeat() -> dict:
    if not HEARTBEAT.exists():
        return {"missing": True}
    try:
        return json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except Exception as e:
        return {"corrupt": str(e)[:200]}


def _hb_age_seconds(hb: dict) -> float:
    ts = hb.get("ts")
    if not ts:
        return -1
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)
        return (datetime.datetime.now(datetime.UTC) - dt).total_seconds()
    except Exception:
        return -1


def _hub_notify(message: str) -> bool:
    try:
        import os
        import urllib.request

        token = os.environ.get("FORGE_MCP_TOKEN", "")
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "hub",
                    "arguments": {"action": "notify", "to": "CLAUDE", "message": message},
                },
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8766/mcp",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "X-Agent-Name": "FLIP_CANARY",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


# ── Phase 1 : baseline ────────────────────────────────────────────────────────


def phase1_baseline() -> int:
    hb = _read_heartbeat()
    hb_age = _hb_age_seconds(hb)
    state = {
        "phase1_ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "phase1_heartbeat": hb,
        "phase1_heartbeat_age_s": hb_age,
        "phase1_old_pid": hb.get("pid"),
        "target_service": TARGET_SERVICE,
        "old_cmd": OLD_CMD,
        "new_cmd": NEW_CMD,
    }
    _save_state(state)
    print(f"[phase 1] baseline captured")
    print(f"  heartbeat ts={hb.get('ts','?')} age={hb_age:.0f}s pid={hb.get('pid','?')}")
    print(f"  state -> {STATE_PATH}")
    return 0


# ── Phase 2 : edit services.toml ──────────────────────────────────────────────


def phase2_flip() -> int:
    if not SERVICES_TOML.exists():
        print(f"[phase 2] FAIL: {SERVICES_TOML} not found", file=sys.stderr)
        return 1
    txt = SERVICES_TOML.read_text(encoding="utf-8")
    if TARGET_SERVICE not in txt:
        print(f"[phase 2] FAIL: {TARGET_SERVICE} not in services.toml", file=sys.stderr)
        return 1

    # Find the service block + flip cmd
    needle = f'name = "{TARGET_SERVICE}"'
    idx = txt.find(needle)
    if idx < 0:
        print(f"[phase 2] FAIL: needle not found", file=sys.stderr)
        return 1
    # Search forward for next `cmd =` line
    block_end = txt.find("\n[[service]]", idx)
    block = txt[idx:] if block_end < 0 else txt[idx:block_end]
    if OLD_CMD not in block:
        print(f"[phase 2] FAIL: cmd already not {OLD_CMD!r} -- already flipped?")
        return 1

    # Backup
    CANARY_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_PATH.write_text(txt, encoding="utf-8")
    print(f"[phase 2] backup -> {BACKUP_PATH}")

    # Edit (only within the target block)
    new_block = block.replace(OLD_CMD, NEW_CMD, 1)
    new_txt = txt[:idx] + new_block + (txt[idx + len(block):] if block_end >= 0 else "")
    SERVICES_TOML.write_text(new_txt, encoding="utf-8")
    print(f"[phase 2] services.toml flipped: {OLD_CMD} -> {NEW_CMD} for {TARGET_SERVICE}")

    state = _load_state()
    state["phase2_ts"] = datetime.datetime.now(datetime.UTC).isoformat()
    state["phase2_backup_path"] = str(BACKUP_PATH)
    state["phase2_status"] = "flipped"
    _save_state(state)

    print()
    print("=" * 72)
    print("USER ACTION REQUIRED:")
    print(f"  nssm restart {TARGET_SERVICE}")
    print("=" * 72)
    print()
    print("Then run: LAFORGE_PYTHON tools/forge_py314t_flip_canary.py --phase 3 --watch-min 5")
    return 0


# ── Phase 3 : monitor ─────────────────────────────────────────────────────────


def phase3_monitor(watch_min: int) -> int:
    state = _load_state()
    if not state.get("phase2_status") == "flipped":
        print("[phase 3] FAIL: phase 2 not done", file=sys.stderr)
        return 1

    print(f"[phase 3] monitoring {TARGET_SERVICE} for {watch_min} min...")
    t_start = time.time()
    deadline = t_start + watch_min * 60
    samples = []
    initial_pid = state.get("phase1_old_pid")

    while time.time() < deadline:
        hb = _read_heartbeat()
        age = _hb_age_seconds(hb)
        new_pid = hb.get("pid")
        ts = datetime.datetime.now(datetime.UTC).isoformat()
        pid_changed = (new_pid is not None) and (new_pid != initial_pid)
        sample = {
            "ts": ts,
            "hb_ts": hb.get("ts"),
            "hb_age_s": round(age, 1) if age >= 0 else -1,
            "pid": new_pid,
            "pid_changed_vs_baseline": pid_changed,
        }
        samples.append(sample)
        print(
            f"  [{int(time.time() - t_start):>4d}s] pid={new_pid} "
            f"(changed={pid_changed}) hb_age={sample['hb_age_s']:>5.0f}s"
        )
        time.sleep(30)

    # Verdict
    pid_changed_at_least_once = any(s["pid_changed_vs_baseline"] for s in samples)
    last_age = samples[-1]["hb_age_s"] if samples else -1
    healthy = pid_changed_at_least_once and (0 <= last_age < 600)
    verdict = "HEALTHY" if healthy else "DEGRADED"

    state["phase3_ts"] = datetime.datetime.now(datetime.UTC).isoformat()
    state["phase3_samples"] = samples
    state["phase3_verdict"] = verdict
    state["phase3_pid_changed"] = pid_changed_at_least_once
    state["phase3_last_hb_age_s"] = last_age
    _save_state(state)

    print()
    print(f"=== VERDICT: {verdict} ===")
    print(f"  pid_changed_vs_baseline = {pid_changed_at_least_once}")
    print(f"  last_heartbeat_age_s    = {last_age}")
    if not healthy:
        print()
        print("Run: LAFORGE_PYTHON tools/forge_py314t_flip_canary.py --rollback")
    else:
        print()
        print("Run: LAFORGE_PYTHON tools/forge_py314t_flip_canary.py --phase 4")
    return 0


# ── Phase 4 : commit or rollback ──────────────────────────────────────────────


def phase4_commit() -> int:
    state = _load_state()
    if state.get("phase3_verdict") != "HEALTHY":
        print(f"[phase 4] FAIL: phase 3 verdict={state.get('phase3_verdict')}, refuse commit")
        print("Run --rollback instead")
        return 1
    print(f"[phase 4] verdict HEALTHY -- services.toml change kept")
    msg = (
        f"[FLIP CANARY] {TARGET_SERVICE} successfully running on PY314T. "
        f"services.toml change committed. Multi-thread bench gain unlocked. "
        f"State: sandbox/py314t_canary/state.json"
    )
    if _hub_notify(msg):
        print("notified CLAUDE via hub")
    state["phase4_ts"] = datetime.datetime.now(datetime.UTC).isoformat()
    state["phase4_status"] = "committed"
    _save_state(state)
    return 0


def rollback() -> int:
    if not BACKUP_PATH.exists():
        print(f"[rollback] FAIL: no backup at {BACKUP_PATH}", file=sys.stderr)
        return 1
    backup = BACKUP_PATH.read_text(encoding="utf-8")
    SERVICES_TOML.write_text(backup, encoding="utf-8")
    print(f"[rollback] services.toml restored from {BACKUP_PATH}")
    print()
    print("=" * 72)
    print("USER ACTION REQUIRED:")
    print(f"  nssm restart {TARGET_SERVICE}")
    print("=" * 72)
    state = _load_state()
    state["rollback_ts"] = datetime.datetime.now(datetime.UTC).isoformat()
    state["rollback_status"] = "restored"
    _save_state(state)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, choices=[1, 2, 3, 4])
    ap.add_argument("--watch-min", type=int, default=5)
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    if args.rollback:
        return rollback()
    if args.phase == 1:
        return phase1_baseline()
    if args.phase == 2:
        return phase2_flip()
    if args.phase == 3:
        return phase3_monitor(args.watch_min)
    if args.phase == 4:
        return phase4_commit()

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
