"""forge_coagulation_cascade.py — Isolation localisée des crashes workers (cascade fibrinogène).

Mapping bio↔code (extension chantier biomimétique) :
- Brèche vasculaire   = crash worker daemon (heartbeat stale, exception)
- Plaquettes          = sentinel process témoin
- Cascade enzymatique = fibrinogène → thrombine → fibrine → caillot (séquence d'étapes)
- Caillot localisé    = isolation_record en DB, ne propage pas
- Dissolution         = restoration auto si heartbeat revient (fibrinolyse)
- Caillot trop gros   = escalation humaine (embolie = système bloqué)

PROBLÈME RÉEL ADRESSÉ
=====================
NSSM restart les workers en boucle bête sans isolation. Un worker en crash loop
sature le CPU/disk et empêche les autres organes de fonctionner. Aucun
"caillot" pour limiter la propagation.

PIPELINE
========
1. Détection brèche : heartbeat stale > 3× interval OR forge_inspector signale
2. Hémostase primaire : capture state (last 50 log lines + DB rows touchés)
3. Cascade : INSERT coagulation_events(worker, severity, state, status='active')
4. Plaquettes : sentinel surveille si le crash se répète (3 en 5 min)
5. Si embolie (>3 crashes/5min) :
   - HORMONE_ADRENALINE émise
   - Alert humain via agent_messages (to=usr_naarob)
   - DISABLE_SERVICE optionnel (opt-in via env)
6. Dissolution : si heartbeat revient pendant > 5 min → status='dissolved'
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"

DEFAULT_INTERVAL_S = int(os.environ.get("LAFORGE_COAG_INTERVAL_S", "300"))  # 5 min
HEARTBEAT_MAX_FACTOR = 3  # heartbeat stale si age > 3× interval
EMBOLIE_THRESHOLD = 3  # crashes en 5 min = embolie
EMBOLIE_WINDOW_S = 300

# Workers à surveiller (heartbeat path → name)
WATCHED_WORKERS = {
    "biblio_worker": SANDBOX / "biblio_worker.heartbeat",
    "gemini_poll": SANDBOX / "gemini_poll_daemon.heartbeat",
    "skill_enricher": SANDBOX / "skill_enricher.heartbeat",
    "hebbian_linker": SANDBOX / "hebbian_linker.heartbeat",
    "health_diagnostic": SANDBOX / "health_diagnostic.heartbeat",
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS coagulation_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        worker      TEXT NOT NULL,
        severity    TEXT NOT NULL,    -- minor / major / embolie
        state_snapshot TEXT,
        status      TEXT NOT NULL,    -- active / dissolved / escalated
        ts_detected TEXT NOT NULL,
        ts_resolved TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coag_worker ON coagulation_events(worker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coag_status ON coagulation_events(status)")
    conn.commit()


def _heartbeat_age(path: Path) -> tuple[bool, int, int]:
    """Renvoie (alive, age_s, interval_s_declare). alive=True si heartbeat fresh."""
    if not path.exists():
        return False, 99999, 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = data.get("ts") or data.get("last_run")
        interval = int(data.get("interval_s", DEFAULT_INTERVAL_S))
        if not ts:
            return False, 99999, interval
        if str(ts).isdigit():
            t = datetime.fromtimestamp(float(ts))
        else:
            t = datetime.fromisoformat(str(ts).split(".")[0])
        age = int((datetime.now() - t).total_seconds())
        return age < (interval * HEARTBEAT_MAX_FACTOR), age, interval
    except Exception:
        return False, 99999, 0


RETIRED_AGE_S = 86400  # heartbeat > 24h sans NSSM = worker retiré, skip


def _is_worker_retired(name: str, age_s: int) -> bool:
    """Worker retiré = heartbeat très stale ET pas de service NSSM associé.
    Évite faux positifs sur daemons éteints depuis longtemps."""
    if age_s < RETIRED_AGE_S:
        return False
    # Mapping nom worker -> service NSSM probable
    nssm_map = {
        "biblio_worker": ["NokidoBiblio", "NokidoBiblioWorker"],
        "skill_enricher": ["NokidoSkillEnricher", "NokidoSkill"],
        "hebbian_linker": ["NokidoHebbian"],
        "gemini_poll": ["NokidoGeminiDaemon"],
        "health_diagnostic": ["NokidoHomeostasis"],  # via orchestrateur
    }
    candidates = nssm_map.get(name, [])
    for svc in candidates:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"(Get-Service {svc} -ErrorAction SilentlyContinue).Status"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8",
                errors="replace",
            )
            if "Running" in (r.stdout or ""):
                return False  # service actif → vrai breach
        except Exception:
            pass
    return True  # > 24h ET aucun service running = retiré


def detect_breaches(conn) -> list[dict]:
    """Phase 1 : détection des brèches (workers stale).
    Skip workers retirés (heartbeat > 24h sans NSSM service actif)."""
    breaches = []
    for name, hb_path in WATCHED_WORKERS.items():
        alive, age, interval = _heartbeat_age(hb_path)
        if not alive and hb_path.exists():
            if _is_worker_retired(name, age):
                continue  # daemon mort depuis longtemps, pas un vrai breach
            breaches.append(
                {
                    "worker": name,
                    "age_s": age,
                    "interval_s": interval,
                    "heartbeat_path": str(hb_path),
                }
            )
    return breaches


def capture_state(worker: str) -> str:
    """Phase 2 : hémostase primaire — snapshot du contexte du worker en crash."""
    snap = {"worker": worker, "captured_at": datetime.now().isoformat()}
    # Last 50 log lines
    log_paths = [
        SANDBOX / f"{worker}.log",
        SANDBOX / f"{worker}.err.log",
        SANDBOX / f"{worker}_daemon.log",
    ]
    for p in log_paths:
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                snap[p.name] = lines[-50:]
            except Exception:
                pass
    # PID file si présent
    pid_path = SANDBOX / f"{worker}.pid"
    if pid_path.exists():
        try:
            snap["last_pid"] = pid_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return json.dumps(snap, ensure_ascii=False)[:8000]  # cap 8KB


def open_clot(conn, worker: str, age: int) -> dict:
    """Phase 3 : cascade fibrinogène → INSERT coagulation_events."""
    # Severity selon âge stale
    if age < 1800:
        severity = "minor"
    elif age < 7200:
        severity = "major"
    else:
        severity = "embolie"

    state = capture_state(worker)
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO coagulation_events(worker, severity, state_snapshot, status, ts_detected) "
        "VALUES (?, ?, ?, 'active', ?)",
        (worker, severity, state, now),
    )
    conn.commit()
    return {"id": cur.lastrowid, "worker": worker, "severity": severity, "ts": now}


def check_embolie(conn, worker: str) -> bool:
    """Phase 5 : si > N crashes en T min → embolie (escalation)."""
    cutoff = (datetime.now() - timedelta(seconds=EMBOLIE_WINDOW_S)).isoformat()
    n = conn.execute(
        "SELECT COUNT(*) FROM coagulation_events WHERE worker = ? AND ts_detected >= ?", (worker, cutoff)
    ).fetchone()[0]
    return n >= EMBOLIE_THRESHOLD


def dissolve_clots(conn) -> int:
    """Phase 6 : fibrinolyse — si worker heartbeat revient, dissoudre les caillots actifs."""
    n = 0
    active = conn.execute("SELECT id, worker FROM coagulation_events WHERE status='active'").fetchall()
    for clot_id, worker in active:
        hb = WATCHED_WORKERS.get(worker)
        if hb:
            alive, age, _ = _heartbeat_age(hb)
            if alive:
                conn.execute(
                    "UPDATE coagulation_events SET status='dissolved', ts_resolved=? WHERE id=?",
                    (datetime.now().isoformat(), clot_id),
                )
                n += 1
    conn.commit()
    return n


def escalate_embolie(conn, worker: str, breach: dict) -> dict:
    """Embolie : émet ADRENALINE + ALERT mailbox + mark escalated."""
    # 1. Hormone adrenaline
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_endocrine import release as hormone_release

        hormone_release(
            "ADRENALINE_HUB_PRESSURE",
            level=1.0,
            source="coagulation_cascade",
            reason=f"embolie {worker} crash >= {EMBOLIE_THRESHOLD} en {EMBOLIE_WINDOW_S}s",
        )
    except Exception:
        pass
    # 2. Alert via agent_messages
    msg_id = f"coag_embolie_{int(time.time())}"
    payload = json.dumps(
        {
            "text": f"[COAGULATION][EMBOLIE] worker={worker} stale {breach['age_s']}s "
            f"(>{EMBOLIE_THRESHOLD} crashes/{EMBOLIE_WINDOW_S}s). Alert humain requis."
        },
        ensure_ascii=False,
    )
    # Scission M2M : l'alerte part dans la base des agent_messages (interrupteur
    # sandbox/m2m.switch) ; `conn` reste la base du RAG pour coagulation_events.
    from nokido_agent.app.forge_db_path import open_m2m
    _m2m = open_m2m(timeout=10)
    _m2m.execute(
        "INSERT INTO agent_messages(id, from_agent, to_agent, correlation_id, "
        "method, payload, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            msg_id,
            "agt_coagulation",
            "agt_naarob",
            msg_id,
            "alert.embolie",
            payload,
            "unread",
            datetime.now().isoformat(),
        ),
    )
    # 3. Mark escalated
    conn.execute("UPDATE coagulation_events SET status='escalated' WHERE worker=? AND status='active'", (worker,))
    conn.commit()
    return {"escalated": True, "alert_id": msg_id}


def run_cycle() -> dict:
    conn = _conn()
    _ensure_schema(conn)
    t0 = time.time()

    # 1+2+3 : détection + capture + open clot
    breaches = detect_breaches(conn)
    new_clots = []
    for breach in breaches:
        # Skip si déjà active pour ce worker
        existing = conn.execute(
            "SELECT 1 FROM coagulation_events WHERE worker=? AND status='active' "
            "AND ts_detected > datetime('now', '-15 minutes')",
            (breach["worker"],),
        ).fetchone()
        if existing:
            continue
        clot = open_clot(conn, breach["worker"], breach["age_s"])
        new_clots.append(clot)

        # 5 : embolie ?
        if check_embolie(conn, breach["worker"]):
            escalate_embolie(conn, breach["worker"], breach)
            new_clots[-1]["escalated"] = True

    # 6 : dissolution des caillots si heartbeat revient
    dissolved = dissolve_clots(conn)

    conn.close()
    return {
        "ts": datetime.now().isoformat(),
        "duration_s": round(time.time() - t0, 2),
        "breaches_detected": len(breaches),
        "new_clots": new_clots,
        "dissolved": dissolved,
        "watched_workers": list(WATCHED_WORKERS.keys()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido coagulation cascade")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    args = ap.parse_args()

    if not args.once and not args.daemon:
        ap.error("--once ou --daemon requis")

    while True:
        out = run_cycle()
        print(
            f"[coag] cycle {out['duration_s']}s : breaches={out['breaches_detected']} "
            f"new_clots={len(out['new_clots'])} dissolved={out['dissolved']}",
            flush=True,
        )
        for c in out["new_clots"]:
            tag = "🚨" if c.get("escalated") else "🟡"
            print(f"  {tag} clot id={c['id']} worker={c['worker']} severity={c['severity']}", flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
