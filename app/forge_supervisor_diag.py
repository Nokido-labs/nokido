"""forge_supervisor_diag.py — Supervisor autodiagnostic Nokido.

Système immunitaire : lit tous les heartbeats sandbox/*.heartbeat,
classifie FRESH/OK/STALE/DEAD, log dans critical_events si DEAD persiste.
Expose API /supervisor/status pour observability + dashboard.

Pattern : SRE Golden Signals (latency/traffic/errors/saturation) appliqué
aux daemons Nokido. Inspiré observability shift-left (Honeycomb).

Tier classification :
- FRESH : age < 300s (5 min)
- OK    : 300s <= age < 3600s (5min - 1h)
- STALE : 3600s <= age < 86400s (1h - 1j)
- DEAD  : age >= 86400s (>= 1j)

Actions :
- DEAD : log critical_event kind=daemon_dead + best-effort restart (NSSM)
- STALE : warn log + telemetry counter
- OK/FRESH : pass

API :
- scan_heartbeats() : dict {daemon_name: status_dict}
- diagnose() : summary {fresh, ok, stale, dead, total}
- alert_dead(restart=False) : ecrit critical_events + optional NSSM restart
"""

from __future__ import annotations
import json, logging, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("supervisor_diag")

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
DB = ROOT / "RAG" / "embeddings.db"

THRESHOLDS = {
    "FRESH": 300,
    "OK": 3600,
    "STALE": 86400,
    # >= 86400 = DEAD
}

# Daemons critiques : DEAD trigger restart auto (si NSSM existe)
CRITICAL_DAEMONS = (
    "watch_agent_worker",
    "embed_auto_trigger",
    "brain_worker",
    "offline_trainer",
    "consolidator",
    "self_patcher",
    "ingestion_pipeline",
    "homeostasis_orchestrator",
    "supervisor",
)

# Daemons optionnels : DEAD = warn only (pas critique)
OPTIONAL_DAEMONS = (
    "skill_enricher",
    "skill_curator",
    "biblio_worker",
    "forge_biblio_worker",
    "forge_bell",
    "embed_worker_isolated",
    "llama_worker_isolated",
    "docker_keeper",
    "searxng_keeper",
)


def classify_age(age_s: float) -> str:
    if age_s < THRESHOLDS["FRESH"]:
        return "FRESH"
    if age_s < THRESHOLDS["OK"]:
        return "OK"
    if age_s < THRESHOLDS["STALE"]:
        return "STALE"
    return "DEAD"


def scan_heartbeats() -> dict:
    """Scan sandbox/*.heartbeat + classify."""
    now = time.time()
    results = {}
    for hb in SANDBOX.glob("*.heartbeat"):
        try:
            mtime = hb.stat().st_mtime
            age = now - mtime
            name = hb.stem
            content = None
            try:
                content = json.loads(hb.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass
            results[name] = {
                "age_s": round(age, 1),
                "status": classify_age(age),
                "mtime": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                "critical": name in CRITICAL_DAEMONS,
                "optional": name in OPTIONAL_DAEMONS,
                "content_preview": (json.dumps(content)[:200] if content else None),
            }
        except Exception as e:
            results[hb.stem] = {"error": str(e)}
    # Also list heartbeat-suffixed json files
    for hb in SANDBOX.glob("*heartbeat*.json"):
        try:
            mtime = hb.stat().st_mtime
            age = now - mtime
            name = hb.stem
            if name in results:
                continue
            results[name] = {
                "age_s": round(age, 1),
                "status": classify_age(age),
                "mtime": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                "critical": name in CRITICAL_DAEMONS,
                "optional": name in OPTIONAL_DAEMONS,
            }
        except Exception:
            pass
    return results


def diagnose() -> dict:
    """High-level summary + breakdown."""
    hbs = scan_heartbeats()
    counts = {"FRESH": 0, "OK": 0, "STALE": 0, "DEAD": 0}
    critical_dead = []
    optional_dead = []
    stale_critical = []
    for name, info in hbs.items():
        st = info.get("status")
        if not st:
            continue
        counts[st] = counts.get(st, 0) + 1
        if st == "DEAD":
            if info.get("critical"):
                critical_dead.append(name)
            elif info.get("optional"):
                optional_dead.append(name)
        elif st == "STALE" and info.get("critical"):
            stale_critical.append(name)
    return {
        "total": len(hbs),
        "counts": counts,
        "critical_dead": critical_dead,
        "stale_critical": stale_critical,
        "optional_dead": optional_dead,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "heartbeats": hbs,
    }


def _write_critical_event(kind: str, payload: dict, severity: str = "warn"):
    """Wrap forge_critical_events.persist() (Phase 22 fsync + backup)."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_critical_events import persist as _persist

        rid = _persist(kind, severity, payload)
        return rid > 0
    except Exception as e:
        logger.warning(f"critical_events persist fail: {e}")
        return False


def alert_dead(restart: bool = False) -> dict:
    """Pour chaque daemon DEAD critique : log critical_event + best-effort restart NSSM."""
    diag = diagnose()
    actions = []
    for name in diag["critical_dead"]:
        evt = {"daemon": name, "age_s": diag["heartbeats"][name]["age_s"]}
        _write_critical_event("daemon_dead", evt)
        actions.append({"daemon": name, "logged": True, "restarted": False})
        if restart:
            # Try NSSM restart (best effort, requires nssm in PATH + service exists)
            try:
                import subprocess

                svc_candidates = [
                    f"Nokido{name.title().replace('_', '')}",
                    f"Nokido{name.replace('_', '')}",
                ]
                for svc in svc_candidates:
                    r = subprocess.run(
                        ["nssm", "status", svc],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    errors="replace")
                    if "SERVICE_STOPPED" in r.stdout or "SERVICE_RUNNING" in r.stdout:
                        subprocess.run(["nssm", "restart", svc], capture_output=True, timeout=10)
                        actions[-1]["restarted"] = svc
                        break
            except Exception as e:
                actions[-1]["restart_err"] = str(e)
    return {
        "n_dead_critical": len(diag["critical_dead"]),
        "n_stale_critical": len(diag["stale_critical"]),
        "actions": actions,
    }


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--restart", action="store_true", help="Auto-restart dead critical daemons via NSSM")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    diag = diagnose()
    if args.json:
        print(json.dumps(diag, indent=2, ensure_ascii=False))
        return

    print(f"=== Supervisor diag {diag['timestamp']} ===")
    print(f"Total heartbeats: {diag['total']}")
    print(
        f"FRESH={diag['counts']['FRESH']} OK={diag['counts']['OK']} "
        f"STALE={diag['counts']['STALE']} DEAD={diag['counts']['DEAD']}"
    )
    if diag["critical_dead"]:
        print(f"\n[CRITICAL DEAD] {len(diag['critical_dead'])}:")
        for d in diag["critical_dead"]:
            age = diag["heartbeats"][d]["age_s"]
            print(f"  - {d:30} age={age:.0f}s")
    if diag["stale_critical"]:
        print(f"\n[STALE CRITICAL] {len(diag['stale_critical'])}:")
        for d in diag["stale_critical"]:
            age = diag["heartbeats"][d]["age_s"]
            print(f"  - {d:30} age={age:.0f}s")
    if diag["optional_dead"]:
        print(f"\n[OPTIONAL DEAD] {len(diag['optional_dead'])}:")
        for d in diag["optional_dead"][:10]:
            print(f"  - {d}")

    if args.restart:
        print("\n[RESTART] alerting + best-effort NSSM restart...")
        result = alert_dead(restart=True)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
