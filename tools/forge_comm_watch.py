#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_comm_watch.py — veille PERMANENTE sur les briques de communication CLI.

Chaque CLI (bras arme de la Forge) a ses subtilites : config MCP, identite/token,
transport, ENSEMBLE D'OUTILS EXPOSES, modele de permission. Une migration (ex
gemini->Antigravity : modele de droits par-outil) peut casser lecture/ecriture
SANS bruit. Ce watcher SNAPSHOTE + DIFF ces surfaces et ALERTE au moindre
changement essentiel (log + critical_event + blackboard).

    LAFORGE_PYTHON tools/forge_comm_watch.py            # un passage (snapshot + diff + report)
    LAFORGE_PYTHON tools/forge_comm_watch.py --daemon   # boucle (interval s, def 900)
    LAFORGE_PYTHON tools/forge_comm_watch.py --json

Surfaces surveillees = config client (per-CLI) + cote-hub (identite/perimetre).
Etat persiste dans sandbox/comm_watch_state.json.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "vegetatif/watcher-monitor des briques de communication CLI"  # declare le 2026-09-06 (audit : REGULE sans organe)

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger("forge.comm_watch")
ROOT = Path(__file__).resolve().parent.parent


def _existe(p: Path) -> bool:
    """`Path.exists` LEVE PermissionError sur un profil interdit au compte courant (mesure le
    2026-10-01 : C:/Users/CodexSandboxOffline/.codex) -- le module ne se chargeait plus du
    tout sous ce compte. Illisible n'est pas une preuve : le profil est ecarte, pas elu."""
    try:
        return p.exists()
    except OSError:
        return False


def _owner_home() -> Path:
    """Profil de l'OWNER (ou vivent les CLI), PAS le user courant : le watcher peut
    tourner en sandbox/service sous un autre compte -> expanduser(~) serait faux."""
    cand = os.environ.get("LAFORGE_OWNER_HOME")
    if cand and _existe(Path(cand)):
        return Path(cand)
    h = Path(os.path.expanduser("~"))
    if any(_existe(h / n) for n in (".gemini", ".claude.json", ".codex")):
        return h
    drive = (os.environ.get("SystemDrive") or "C:")
    _SKIP = {"default", "default user", "public", "all users", "defaultaccount", "wdagutilityaccount"}
    users = Path(drive + "/Users")
    if _existe(users):
        for u in sorted(users.iterdir()):
            if u.name.lower() in _SKIP or not u.is_dir():
                continue
            if any(_existe(u / n) for n in (".gemini", ".codex", ".claude.json")):
                return u
    user = Path(drive + "/Users/user")  # owner de cette machine Nokido (override: LAFORGE_OWNER_HOME)
    return user if _existe(user) else h


HOME = _owner_home()
STATE = ROOT / "sandbox" / "comm_watch_state.json"
STATUS = ROOT / "sandbox" / "comm_watch_status.json"

# ── Briques de comm surveillees : (label, path, kind) ────────────────────────
# kind=file -> hash du contenu ; kind=dir -> empreinte du LISTING (set d'outils
# exposes = surface critique : un outil read/write qui apparait/disparait).
WATCHED: list[tuple[str, Path, str]] = [
    # Clients CLI (bras armes)
    ("claude_code.mcp", HOME / ".claude.json", "file"),
    ("gemini.settings", HOME / ".gemini" / "settings.json", "file"),
    ("agy.mcp_config", HOME / ".gemini" / "config" / "mcp_config.json", "file"),
    ("agy.tools_exposed", HOME / ".gemini" / "antigravity-cli" / "mcp" / "laforge-sovereign-hub", "dir"),
    ("agy.tools_exposed_alt", HOME / ".gemini" / "antigravity" / "mcp" / "laforge-sovereign-hub", "dir"),
    ("codex.config", HOME / ".codex" / "config.toml", "file"),
    ("cline.mcp", HOME / "AppData" / "Roaming" / "Code" / "User" / "globalStorage"
     / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json", "file"),
    # Cote hub : identite x ring x zones + roster d'agents admis
    ("hub.agent_identities", ROOT / "config" / "agent_identities.json", "file"),
    ("hub.agent_list_src", ROOT / "tools" / "nokido_hub.py", "file"),
    ("hub.write_paths_src", ROOT / "app" / "forge_mcp_security.py", "file"),
    ("hub.rings_src", ROOT / "app" / "forge_workspace_guard.py", "file"),
]


def _fingerprint(path: Path, kind: str) -> dict:
    """Empreinte d'une brique : existe ? + hash (file) / set d'entrees (dir)."""
    if not path.exists():
        return {"exists": False, "hash": None, "entries": None}
    if kind == "dir":
        entries = sorted(p.name for p in path.iterdir() if p.is_file())
        h = hashlib.sha256("\n".join(entries).encode("utf-8", "replace")).hexdigest()[:16]
        return {"exists": True, "hash": h, "entries": entries}
    try:
        data = path.read_bytes()
    except Exception as e:  # noqa: BLE001
        return {"exists": True, "hash": f"ERR:{e}", "entries": None}
    return {"exists": True, "hash": hashlib.sha256(data).hexdigest()[:16], "entries": None}


def snapshot() -> dict:
    return {label: _fingerprint(path, kind) for label, path, kind in WATCHED}


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(snap: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.error("save state KO: %s", e)


def diff(prev: dict, cur: dict) -> list[dict]:
    """Changements essentiels entre deux snapshots."""
    changes = []
    for label in cur:
        p, c = prev.get(label), cur[label]
        if p is None:
            changes.append({"brick": label, "change": "new", "detail": "premiere observation"})
            continue
        if p.get("exists") and not c.get("exists"):
            changes.append({"brick": label, "change": "DISPARU", "detail": "config/brique absente — comm cassee ?"})
        elif not p.get("exists") and c.get("exists"):
            changes.append({"brick": label, "change": "apparu", "detail": "nouvelle brique"})
        elif p.get("hash") != c.get("hash"):
            d = {"brick": label, "change": "modifie", "detail": f"hash {p.get('hash')} -> {c.get('hash')}"}
            if c.get("entries") is not None:  # dir = ensemble d'outils exposes
                added = sorted(set(c["entries"]) - set(p.get("entries") or []))
                removed = sorted(set(p.get("entries") or []) - set(c["entries"]))
                if added or removed:
                    d["detail"] = f"outils +{added} -{removed}"
            changes.append(d)
    return changes


def _alert(changes: list[dict]) -> None:
    """Log + critical_event + blackboard (best-effort, ne casse jamais le watcher)."""
    for ch in changes:
        log.warning("COMM-BRICK %s : %s — %s", ch["brick"], ch["change"], ch["detail"])
    try:
        sys.path.insert(0, str(ROOT))
        # `emit` n'a jamais existe (l'API est `persist`) : vu en production le 2026-10-01,
        # premier changement de brique detecte apres le correctif du tableau noir.
        from nokido_agent.app.forge_critical_events import persist  # type: ignore

        perdus = 0
        for ch in changes:
            perdus += not persist("comm_brick_change", "warn", {
                "detail": f"{ch['brick']}: {ch['change']} — {ch['detail']}",
                "source": "forge_comm_watch"})
        if perdus:  # persist ne leve jamais : 0 = evenement perdu
            raise RuntimeError(f"{perdus} evenement(s) non persiste(s)")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).error(
            "[comm_watch] changements de brique NON emis (%s: %s) — %d changement(s) "
            "detecte(s) | consequence: une modification de la couche de communication "
            "a ete VUE puis perdue, personne n'en sera averti",
            type(e).__name__, str(e)[:90], len(changes))
    try:
        from nokido_agent.app.forge_swarm_blackboard import apply_fact_sync  # type: ignore

        # `propose_fact` n'a jamais existe : 851 avertissements avant le 2026-10-01, aucun
        # changement de brique publie. discovered_facts exige ring<=2 ; un refus revient en
        # {"error": ...} SANS exception, d'ou la levee explicite vers l'avertissement.
        r = apply_fact_sync("discovered_facts", json.dumps(changes, ensure_ascii=False)[:800],
                            category="comm_brick", trust=0.6, key="comm_watch_last",
                            source="comm_watch", ring=2)
        if r.get("ok") is False or r.get("error"):
            raise RuntimeError(str(r)[:90])
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[comm_watch] fait NON publie au tableau noir (%s: %s) | consequence: les "
            "autres agents ne verront pas ce changement, et l'absence de fait se lira "
            "comme une absence de changement", type(e).__name__, str(e)[:90])


def run_once() -> list[dict]:
    cur = snapshot()
    prev = _load_state()
    changes = diff(prev, cur) if prev else []
    if changes:
        _alert(changes)
    _save_state(cur)
    try:
        STATUS.write_text(
            json.dumps({"ts": time.time(), "changes": changes, "n_bricks": len(WATCHED)}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass
    return changes


def status() -> dict:
    """Lu par les ORGANES (sentinelle/pulse/preflight) — marche HORS contexte owner :
    lit le fichier ecrit par le daemon owner. {ts, stale_s, last_changes}."""
    try:
        d = json.loads(STATUS.read_text(encoding="utf-8"))
        ts = d.get("ts")
        return {"ts": ts, "stale_s": (round(time.time() - ts) if ts else None), "last_changes": d.get("changes", [])}
    except Exception:  # noqa: BLE001
        return {"ts": None, "stale_s": None, "last_changes": []}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if "--daemon" in argv:
        interval = 900
        for a in argv:
            if a.startswith("--interval="):
                interval = int(a.split("=", 1)[1])
        log.info("comm_watch daemon : interval=%ds, %d briques", interval, len(WATCHED))
        while True:
            try:
                ch = run_once()
                if ch:
                    log.warning("%d changement(s) detecte(s)", len(ch))
                # Pouls APRES un passage reussi (recense SUPERVISE le 2026-07-28 :
                # sans heartbeat ni port, sa mort ne se voyait nulle part).
                try:
                    # Amorce LOCALE : l'import vit dans un `except` qui AVALE, donc
                    # une amorce manquante ferait disparaitre le pouls en silence —
                    # exactement la panne muette payee le 2026-09-05 sur deux autres
                    # daemons. Ne pas dependre d'un appel anterieur.
                    if str(ROOT / "app") not in sys.path:
                        sys.path.insert(0, str(ROOT))
                    from nokido_agent.app.forge_heartbeat import beat_daemon

                    beat_daemon("comm_watch", changements=len(ch or []),
                                interval_s=interval)
                except Exception:  # noqa: BLE001
                    pass
            except Exception as e:  # noqa: BLE001
                log.error("passage KO: %s", e)
            time.sleep(interval)
    changes = run_once()
    if "--json" in argv:
        print(json.dumps({"changes": changes, "n_bricks": len(WATCHED)}, ensure_ascii=False, indent=2))
        return 0
    print(f"=== forge_comm_watch — {len(WATCHED)} briques de comm ===")
    if not changes:
        print("baseline posee (1er run) ou aucun changement." if not _load_state() else "aucun changement.")
    else:
        print(f"{len(changes)} CHANGEMENT(S) :")
        for ch in changes:
            print(f"  [{ch['change']}] {ch['brick']} — {ch['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
