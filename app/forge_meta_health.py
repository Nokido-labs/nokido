"""
app/forge_meta_health.py — Health scoring pour daemons Nokido
Score 0-100 par daemon: heartbeat + error_rate + restarts
"""

import glob, json, os, time
from pathlib import Path
from typing import Dict

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

try:
    import urllib.request as _ur

    def _supervisor_status() -> dict:
        r = _ur.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=5)
        return json.load(r).get("services", {})
except Exception:

    def _supervisor_status():
        return {}


ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
LOGS = ROOT / "logs"

DAEMONS = {
    "homeostasis": "NokidoHomeostasis",
    "hebbian_linker": "NokidoHebbian",
    "autonomous_loops": "NokidoAutonomousLoops",
    "multi_llm_daemon": "multi_llm_daemon",
    "gemini_poll_daemon": "gemini_poll_daemon",
    "embed_trigger": "forge_embed_auto_trigger",
    "evolution_loop": "NokidoAutonomousLoops",
}


def _heartbeat_age(daemon: str) -> float:
    hb = SANDBOX / f"{daemon}.heartbeat"
    if not hb.exists():
        return float("inf")
    return time.time() - hb.stat().st_mtime


def _error_rate(daemon: str) -> float:
    logs = list(LOGS.glob(f"*{daemon}*.log"))
    if not logs:
        return 0.5
    lines = logs[0].read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return 0.0
    errors = sum(1 for l in lines if "ERROR" in l or "CRITICAL" in l)
    return min(1.0, errors / max(len(lines), 1))


def _restart_count(svc_name: str, status: dict) -> int:
    return status.get(svc_name, {}).get("restarts", 0)


def score(daemon: str) -> int:
    svc_name = DAEMONS.get(daemon, daemon)
    status = _supervisor_status()

    age = _heartbeat_age(daemon)
    err = _error_rate(daemon)
    restarts = _restart_count(svc_name, status)
    running = status.get(svc_name, {}).get("status") == "running"

    hb_score = max(0.0, 1.0 - age / 300)  # 5min threshold
    err_score = 1.0 - err
    rst_score = max(0.0, 1.0 - restarts / 10)
    run_score = 1.0 if running else 0.0

    s = int(100 * (0.3 * hb_score + 0.3 * err_score + 0.2 * rst_score + 0.2 * run_score))

    if s < 40:
        try:
            import sys

            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_self_correction import anchor_error

            anchor_error(
                error_msg=f"Daemon {daemon} health critical: {s}/100",
                context=f"heartbeat_age={age:.0f}s error_rate={err:.2f} restarts={restarts} running={running}",
                solution="Restart daemon via supervisor: POST http://127.0.0.1:8765/supervisor/restart/<name>",
                domain="systeme",
            )
        except Exception:
            pass
    return s


def get_all_scores() -> Dict[str, int]:
    return {d: score(d) for d in tqdm(list(DAEMONS), desc="scoring daemons", unit="daemon")}


def scan_all() -> dict:
    scores = get_all_scores()
    ok_count = sum(1 for s in scores.values() if s >= 60)
    total = len(scores)
    return {
        "ok": ok_count == total,
        "score": round(ok_count / total, 2) if total else 0.0,
        "daemons": [{"name": d, "score": s, "ok": s >= 60} for d, s in scores.items()],
        "ts": __import__("datetime").datetime.now().isoformat(),
    }


def get_health_report() -> str:
    result = scan_all()
    lines = [
        f"## Nokido Health — {result['ts'][:19]}",
        f"**Score global: {int(result['score'] * 100)}% ({sum(1 for d in result['daemons'] if d['ok'])}/{len(result['daemons'])} daemons OK)**",
        "",
    ]
    for d in result["daemons"]:
        icon = "✅" if d["ok"] else "❌"
        lines.append(f"- {icon} `{d['name']}` — {d['score']}/100")
    return "\n".join(lines)


if __name__ == "__main__":
    scores = get_all_scores()
    for d, s in scores.items():
        bar = "█" * (s // 10) + "░" * (10 - s // 10)
        print(f"  {d:20} [{bar}] {s:3}/100")
