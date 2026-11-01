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
import re
from datetime import datetime, timedelta
from pathlib import Path
# --- amorce namespace (point d'entree) : la RACINE avant tout import nokido_agent,
# sinon ModuleNotFoundError quand ce fichier est lance par son chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

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
                    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_auto_evolution_loop.py', 82, exc_info=True)
        else:
            _sat_since.clear()
    except Exception as e:
        logger.debug(f"[slots probe] {e}")


try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
# 25/10 : HUB_URL / HUB_TOKEN retires avec _hub_restart (seul usage) -- ne plus lire le jeton MAITRE
# du coffre a l'import d'un daemon qui n'appelle plus le hub (moindre privilege).
HEARTBEAT_GLOB = str(LAFORGE_ROOT / "sandbox" / "*.heartbeat")
LESSONS_FILE = LAFORGE_ROOT / "logs" / "lessons_learned.md"
STATE_FILE = LAFORGE_ROOT / "sandbox" / "auto_evolution.json"
PROPOSALS_DIR = LAFORGE_ROOT / "sandbox"

CHECK_INTERVAL = 600  # 10 min heartbeat check
LESSONS_INTERVAL = 1800  # 30 min lessons scan
ERROR_WINDOW = 3600  # 1h error pattern window
ERROR_THRESHOLD = 3

HEARTBEAT_STALE_S = 300  # 5 min : seuil d'observation (aucune action)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_auto_evolution_loop.py', 118, exc_info=True)
    return {
        "last_heartbeat_check": 0,
        "last_lessons_scan": 0,
        "error_patterns": {},
        "proposals_written": 0,
    }


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _to_epoch(value):
    """ISO 8601 ou epoch -> epoch (float) ; None si illisible."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        try:
            return float(s)
        except ValueError:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_auto_evolution_loop.py', 140, exc_info=True)
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def check_heartbeats(state: dict):
    """OBSERVATION seule : journalise les battements perimes, n'agit jamais."""
    now = time.time()
    files = glob.glob(HEARTBEAT_GLOB)
    stale, unknown = [], []

    for fp in tqdm(files, desc="heartbeats", unit="file", leave=False):
        name = Path(fp).stem
        try:
            data = json.loads(Path(fp).read_text())
            raw = data.get("ts", data.get("timestamp")) if isinstance(data, dict) else None
        except Exception:
            raw = None
        ts = _to_epoch(raw)
        if ts is None:
            unknown.append(name)
            logger.info("[heartbeat] %s : INCONNU (cle ts/timestamp absente ou illisible)", name)
        elif now - ts > HEARTBEAT_STALE_S:
            stale.append(name)
            logger.info("[heartbeat] %s : perime (%.0fs) — observation, aucune action", name, now - ts)

    state["last_heartbeat_check"] = now
    logger.info(
        "Heartbeat check: %d files, %d stale, %d unknown", len(files), len(stale), len(unknown)
    )


_TITLE_RE = re.compile(r"^### \[([^\]]+)\]\s*(.*)$")


def _entry_epoch(date_s: str, now: float):
    """Date de l'entree -> epoch. Date seule = fin de journee, plafonnee a now."""
    try:
        if len(date_s) <= 10:
            d = datetime.strptime(date_s, "%Y-%m-%d") + timedelta(days=1, seconds=-1)
            return min(d.timestamp(), now)
        return datetime.fromisoformat(date_s).timestamp()
    except ValueError:
        return None


def scan_lessons(state: dict):
    if not LESSONS_FILE.exists():
        state["last_lessons_scan"] = time.time()
        return

    now = time.time()
    lines = LESSONS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()

    seen = set(state.get("seen_errors", []))
    patterns = state.setdefault("error_patterns", {})
    new_errors = 0
    in_window = {}  # cle -> epoch de l'entree

    for line in lines:
        m = _TITLE_RE.match(line)
        if not m:
            continue
        date_s, title = m.group(1).strip(), m.group(2).strip()
        up = title.upper()
        if "SOLUTION" in up or not ("ERREUR" in up or "ERROR" in up):
            continue
        key = f"{date_s}|{title}"
        ep = _entry_epoch(date_s, now)
        if ep is None:
            continue
        if key not in seen:
            seen.add(key)
            new_errors += 1
            patterns[key] = {"date": date_s, "epoch": ep}
        if 0 <= now - ep < ERROR_WINDOW:
            in_window[key] = ep

    state["seen_errors"] = sorted(seen)
    # ne propose qu'une fois par ensemble d'erreurs distinctes
    proposed = set(state.get("proposed_errors", []))
    fresh = [k for k in in_window if k not in proposed]
    hot = list(in_window) if len(in_window) >= ERROR_THRESHOLD and fresh else []

    if hot:
        state["proposed_errors"] = sorted(proposed | set(hot))
        ts = int(now)
        proposal = PROPOSALS_DIR / f"evolution_proposal_{ts}.md"
        lines_out = [
            f"# Evolution Proposal — {datetime.fromtimestamp(now).isoformat()}",
            f"\n## Detected {len(hot)} recurring error patterns\n",
        ]
        for k in hot:
            lines_out.append(f"- **{k}** — distinct error in window")
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
    print(f"Lessons scan: {new_errors} new errors, {len(hot)} hot patterns")


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
