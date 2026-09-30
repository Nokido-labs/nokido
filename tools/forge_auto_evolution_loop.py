"""
tools/forge_auto_evolution_loop.py — Nokido autonomous evolution daemon.
Monitors heartbeats, scans lessons_learned.md, detects error patterns, proposes fixes.
"""

import glob
import json
import logging
import os
import sys
import time
import urllib.request as _urllib_req
from datetime import datetime
from pathlib import Path
# --- amorce namespace (point d'entree) : la RACINE avant tout import nokido_agent,
# sinon ModuleNotFoundError quand ce fichier est lance par son chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.app.forge_secrets import get_secret

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ── Probe slots llama-server ─────────────────────────────────────────────────
import json as _json_slots

_LLAMA_BASE = "http://127.0.0.1:8091"
_SLOTS_INTERVAL_S = 30
_SAT_THRESHOLD_S = 15  # secondes avant warning saturation
_last_slots_check = 0.0
_sat_since = {}  # slot_id → timestamp premier état saturé


def _check_llamacpp_slots():
    """Poll /slots. Log warning si slot saturé > _SAT_THRESHOLD_S."""
    global _last_slots_check, _sat_since
    import time as _time

    now = _time.time()
    if now - _last_slots_check < _SLOTS_INTERVAL_S:
        return
    _last_slots_check = now
    try:
        with _urllib_req.urlopen(f"{_LLAMA_BASE}/slots", timeout=5) as r:
            slots = _json_slots.loads(r.read().decode())
        if not isinstance(slots, list):
            return
        total = len(slots)
        busy = [s for s in slots if s.get("state", 0) != 0]
        # Purge slots qui ne sont plus saturés
        current_busy_ids = {s.get("id", i) for i, s in enumerate(busy)}
        for sid in list(_sat_since.keys()):
            if sid not in current_busy_ids:
                del _sat_since[sid]
        # Marquer nouveaux slots saturés
        for s in busy:
            sid = s.get("id", 0)
            if sid not in _sat_since:
                _sat_since[sid] = now
        # Warning si saturation totale depuis > seuil
        if total > 0 and len(busy) == total:
            oldest_sat = min(_sat_since.values()) if _sat_since else now
            sat_duration = now - oldest_sat
            if sat_duration > _SAT_THRESHOLD_S:
                msg = (
                    f"[slots] SATURATION {len(busy)}/{total} slots "
                    f"depuis {sat_duration:.0f}s — latence élevée possible"
                )
                logger.warning(msg)
                try:
                    from nokido_agent.app.forge_self_correction import anchor_error

                    anchor_error(
                        error_msg="llamacpp slot saturation",
                        context=f"{len(busy)}/{total} busy {sat_duration:.0f}s",
                        solution="Réduire -np ou augmenter batch, ou kill requête longue",
                        domain="systeme",
                    )
                except Exception:
                    pass
        else:
            _sat_since.clear()
    except Exception as e:
        logger.debug(f"[slots probe] {e}")


try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
HUB_URL = "http://127.0.0.1:8766/mcp"
HUB_TOKEN = get_secret("FORGE_MCP_TOKEN") or get_secret("LAFORGE_HUB_TOKEN") or ""
HEARTBEAT_GLOB = str(LAFORGE_ROOT / "sandbox" / "*.heartbeat")
LESSONS_FILE = LAFORGE_ROOT / "logs" / "lessons_learned.md"
STATE_FILE = LAFORGE_ROOT / "sandbox" / "auto_evolution.json"
PROPOSALS_DIR = LAFORGE_ROOT / "sandbox"

CHECK_INTERVAL = 600  # 10 min heartbeat check
LESSONS_INTERVAL = 1800  # 30 min lessons scan
ERROR_WINDOW = 3600  # 1h error pattern window
ERROR_THRESHOLD = 3

# Gate anti-régression
if str(LAFORGE_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(LAFORGE_ROOT))
from nokido_agent.app.forge_guarded_change import guarded_change, hub_alive


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "last_heartbeat_check": 0,
        "last_lessons_scan": 0,
        "error_patterns": {},
        "proposals_written": 0,
    }


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _hub_restart(service: str):
    payload = json.dumps(
        {
            "method": "tools/call",
            "params": {
                "name": "run",
                "arguments": {"action": "shell", "commands": [f"nssm restart {service}"]},
            },
        }
    ).encode()
    headers = {"Content-Type": "application/json", "X-Agent-Name": "AUTO_EVOLUTION"}
    if HUB_TOKEN:
        headers["Authorization"] = f"Bearer {HUB_TOKEN}"
    # Gate : un restart de service peut tuer le hub -> post_check hub_alive,
    # une régression détectée est ancrée (anchor_error) au lieu d'être muette.
    with guarded_change(f"auto_evolution: restart {service}", post_check=hub_alive):
        try:
            req = _urllib_req.Request(HUB_URL, data=payload, headers=headers)
            with _urllib_req.urlopen(req, timeout=10) as r:
                print(f"  [restart] {service} → {r.status}")
        except Exception as e:
            print(f"  [ERR] restart {service}: {e}")


def check_heartbeats(state: dict):
    now = time.time()
    stale_threshold = now - 300  # 5 min
    files = glob.glob(HEARTBEAT_GLOB)
    degraded = []

    for fp in tqdm(files, desc="heartbeats", unit="file", leave=False):
        try:
            data = json.loads(Path(fp).read_text())
            ts = data.get("timestamp", 0)
            err_rate = data.get("session_errors", 0) / max(data.get("session_embedded", 1), 1)
            if ts < stale_threshold or err_rate > 0.10:
                degraded.append(Path(fp).stem)
        except Exception:
            pass

    for svc in degraded:
        print(f"  [stale/degraded] {svc} — triggering restart")
        _hub_restart(svc)

    state["last_heartbeat_check"] = now
    print(f"Heartbeat check: {len(files)} files, {len(degraded)} degraded")


def scan_lessons(state: dict):
    if not LESSONS_FILE.exists():
        state["last_lessons_scan"] = time.time()
        return

    now = time.time()
    last = state.get("last_lessons_scan", 0)
    lines = LESSONS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()

    patterns = state.setdefault("error_patterns", {})
    new_solutions = 0

    for line in lines:
        if line.startswith("### [") and "SOLUTION" in line:
            # Extract short key from title
            key = line[6:60].strip()
            entry = patterns.setdefault(key, {"count": 0, "first_seen": now, "last_seen": now})
            entry["count"] += 1
            entry["last_seen"] = now
            new_solutions += 1

    # Check for patterns with 3+ occurrences in last hour
    hot = [
        k
        for k, v in patterns.items()
        if v["count"] >= ERROR_THRESHOLD and (now - v["first_seen"]) < ERROR_WINDOW
    ]

    if hot:
        ts = int(now)
        proposal = PROPOSALS_DIR / f"evolution_proposal_{ts}.md"
        lines_out = [
            f"# Evolution Proposal — {datetime.fromtimestamp(now).isoformat()}",
            f"\n## Detected {len(hot)} recurring error patterns\n",
        ]
        for k in hot:
            v = patterns[k]
            lines_out.append(f"- **{k}** — seen {v['count']}× in last hour")
        lines_out += [
            "\n## Suggested Actions",
            "- Review `logs/lessons_learned.md` for root causes",
            "- Run `forge_meta_health.py` for daemon health scores",
            "- Consider anchoring fixes via `anchor_solution()` in forge_self_correction.py",
        ]
        proposal.write_text("\n".join(lines_out))
        state["proposals_written"] = state.get("proposals_written", 0) + 1
        print(f"  [proposal] written: {proposal.name}")

    state["last_lessons_scan"] = now
    print(f"Lessons scan: {new_solutions} entries, {len(hot)} hot patterns")


STALE_INTERVAL = 3600  # 1h stale file scan


def check_stale_files(state: dict):
    """Scan project for stale files (>7d unchanged, no recent commit) via forge_project_state."""
    now = time.time()
    try:
        _app = str(LAFORGE_ROOT / "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_project_state import snapshot as _snap

        ps = _snap(str(LAFORGE_ROOT))
        stale = ps.stale_files
        todos = ps.open_todos
        if stale:
            ts = int(now)
            proposal = PROPOSALS_DIR / f"stale_files_{ts}.md"
            lines_out = [
                f"# Stale Files Report — {datetime.fromtimestamp(now).isoformat()}",
                f"\n## {len(stale)} files unchanged >7 days with no recent commit\n",
            ]
            for f in stale[:20]:
                lines_out.append(f"- `{f}`")
            if len(stale) > 20:
                lines_out.append(f"- …and {len(stale) - 20} more")
            lines_out += [
                f"\n## Open TODOs: {len(todos)}",
                "- Review and either delete, integrate, or document these modules.",
            ]
            proposal.write_text("\n".join(lines_out))
            state["proposals_written"] = state.get("proposals_written", 0) + 1
            print(f"  [stale] {len(stale)} stale files → {proposal.name}")
        else:
            print(f"  [stale] 0 stale files, {len(todos)} open TODOs")
    except Exception as e:
        print(f"  [ERR] check_stale_files: {e}")
    state["last_stale_check"] = now


def main():
    print(f"[auto_evolution] starting — root: {LAFORGE_ROOT}")
    state = _load_state()

    try:
        while True:
            now = time.time()
            if now - state.get("last_heartbeat_check", 0) >= CHECK_INTERVAL:
                check_heartbeats(state)
                _save_state(state)

            if now - state.get("last_lessons_scan", 0) >= LESSONS_INTERVAL:
                scan_lessons(state)
                _save_state(state)

            if now - state.get("last_stale_check", 0) >= STALE_INTERVAL:
                check_stale_files(state)
                _save_state(state)

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] cycle done — "
                f"proposals={state.get('proposals_written', 0)}"
            )
            _check_llamacpp_slots()
            time.sleep(60)

    except KeyboardInterrupt:
        print("\n[auto_evolution] stopped gracefully")
        _save_state(state)
        sys.exit(0)


if __name__ == "__main__":
    main()
