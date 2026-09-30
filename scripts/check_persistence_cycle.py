"""
check_persistence_cycle.py — Vérification cycle persistence Nokido post-1h.

Lancé via Windows Task Scheduler (one-shot ~75min après création).
Survit aux fermetures Claude/Gemini/Cline. Résultat anchor RAG +
push agent_messages → visible par TOUS les CLI LLM.

Usage manuel : LAFORGE_PYTHON scripts/check_persistence_cycle.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSIST = ROOT / "nokido_persist"
sys.path.insert(0, str(ROOT / "app"))


def check_files() -> dict:
    """Vérifie présence + fraîcheur fichiers persistence."""
    state = PERSIST / "state.json"
    wal = PERSIST / "vault_wal.jsonl"
    ckp = PERSIST / "vault_checkpoint.json"
    snaps_dir = PERSIST / "snapshots"

    result = {
        "state_present": state.exists(),
        "state_size": state.stat().st_size if state.exists() else 0,
        "wal_present": wal.exists(),
        "wal_size": wal.stat().st_size if wal.exists() else 0,
        "checkpoint_present": ckp.exists(),
        "checkpoint_age_min": None,
        "brain_snapshots": 0,
        "brain_latest_age_min": None,
    }
    if ckp.exists():
        result["checkpoint_age_min"] = (time.time() - ckp.stat().st_mtime) / 60
    if snaps_dir.exists():
        snaps = list(snaps_dir.glob("brain_*.json"))
        result["brain_snapshots"] = len(snaps)
        if snaps:
            latest = max(snaps, key=lambda p: p.stat().st_mtime)
            result["brain_latest_age_min"] = (time.time() - latest.stat().st_mtime) / 60
    return result


def check_deno_proxy() -> dict:
    """Curl /api/persist/info si proxy Deno UP."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8000/api/persist/info", timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"deno_up": False, "error": str(e)[:100]}


def push_to_agent_messages(text: str) -> bool:
    """Push résultat dans agent_messages SQLite → visible par tous CLI."""
    try:
        import hashlib
        db = ROOT / "RAG" / "embeddings.db"
        conn = sqlite3.connect(str(db))
        msg_id = "cron_" + hashlib.sha256(f"{text}{time.time()}".encode()).hexdigest()[:16]
        payload = json.dumps({"text": text, "ts": time.time()}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO agent_messages (id, from_agent, to_agent, method, payload, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, "scheduled_check", "all_cli", "broadcast.persistence_check", payload, "pending")
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"  push_failed: {e}", file=sys.stderr)
        return False


def main():
    files = check_files()
    deno = check_deno_proxy()

    # Verdict
    issues = []
    if not files["state_present"]:
        issues.append("state.json manquant")
    if not files["checkpoint_present"]:
        issues.append("vault_checkpoint.json absent (cycle 1h non passé ?)")
    elif files["wal_size"] > 1024 * 100:
        issues.append(f"WAL non tronqué après checkpoint ({files['wal_size']} bytes)")
    if files["brain_snapshots"] == 0:
        issues.append("aucun brain snapshot (setBrainSource jamais appelé côté Deno — normal phase 6)")

    ok = not issues or (len(issues) == 1 and "brain snapshot" in issues[0])
    summary = (
        f"checkpoint={files['checkpoint_present']} "
        f"wal_size={files['wal_size']}b "
        f"brain_snaps={files['brain_snapshots']} "
        f"deno_up={'deno_up' not in deno or deno.get('vault_size') is not None}"
    )
    label = "OK" if ok else "KO"
    msg = f"[CRON-PERSISTENCE] {label} : {summary}"
    if issues:
        msg += f" | issues: {'; '.join(issues)}"

    # Anchor RAG
    try:
        from forge_self_correction import anchor_solution, anchor_error
        if ok:
            anchor_solution(
                problem="Vérification cycle persistence post-1h",
                solution=f"{summary} | files={files} | deno={deno}",
                example=msg,
                domain="security",
            )
        else:
            anchor_error(
                error_msg=msg,
                context=f"check_persistence_cycle.py | files={files}",
                solution="; ".join(issues),
                domain="security",
            )
    except Exception as e:
        msg += f" | anchor_failed: {e}"

    # Notification multi-CLI
    pushed = push_to_agent_messages(msg)

    # Stdout
    print(msg)
    print(json.dumps({"files": files, "deno": deno, "pushed": pushed, "ok": ok}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
