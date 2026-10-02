#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_presence.py — "qui est dans la piece" : presence/heartbeat inter-CLI.

Les CLIs locaux (claude/gemini/agy/codex/cline) n'ont PAS de heartbeat de presence
dedie ; leur liveness etait implicite. TRICHE (directive user) : CHAQUE consultation
du hub passe par le gate (preflight) -> on STAMPE la presence du caller la. Resultat :
toute activite hub = un battement, gratuit, robuste, sans daemon. "au pire" = meme si
aucun mecanisme dedie ne tire, le simple fait d'appeler le hub marque la presence.

API :
    mark_seen(agent)                 # 1 ligne a cabler dans le gate/preflight
    who_present(window_s=180) -> [agents]   # qui est dans la piece
    room(window_s=180) -> {agent: age_s}    # detail
    last_seen(agent) -> age_s | None

Stockage : 1 fichier mtime par agent (sandbox/presence/<AGENT>.seen) — chaque agent
ecrit le SIEN, zero lock, cross-process. Best-effort partout (jamais lever vers le gate).
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

__FORGE_COLOR__ = "vegetatif/heartbeat : presence inter-CLI, qui est dans la piece"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DIR = ROOT / "sandbox" / "presence"
DEFAULT_WINDOW = 180  # s : un CLI vu il y a < 3 min = "dans la piece"
STAMP_THROTTLE = 30   # s : appele sur CHAQUE appel hub -> n'ecrit au plus qu'1x/30s/agent
_LAST: dict = {}      # in-process : dernier stamp disque par agent (anti-thrash)


def mark_seen(agent: str, meta: dict | None = None) -> None:
    """Stampe la presence du caller. A appeler dans le gate (preflight) sur CHAQUE appel.
    Throttle 30s/agent (pas d'I/O disque par appel). Sur transition absent->present
    ("entre dans la piece") -> _emit_arrival() enclenche la boucle ecoute/reponse.
    Best-effort absolu : ne doit JAMAIS casser le chemin d'appel hub."""
    try:
        if not agent:
            return
        a = agent.upper()
        now = time.time()
        if (now - _LAST.get(a, 0.0)) < STAMP_THROTTLE:
            return  # vu recemment (in-process) -> pas une arrivee, throttle l'I/O disque
        prev_age = last_seen(a)  # lecture disque ; None ou > fenetre = ARRIVEE
        arrived = prev_age is None or prev_age > DEFAULT_WINDOW
        _LAST[a] = now
        _DIR.mkdir(parents=True, exist_ok=True)
        (_DIR / f"{a}.seen").write_text(
            json.dumps({"ts": now, **(meta or {})}, ensure_ascii=False), encoding="utf-8"
        )
        if arrived:
            _emit_arrival(a)
    except Exception:  # noqa: BLE001
        pass


def _emit_arrival(agent: str) -> None:
    """Transition absent->present : enclenche la boucle ecoute/reponse (best-effort).
    Emet un critical_event 'cli_present' + un fait blackboard que les listeners
    (forge_secretary / coagulation) consomment pour 'taper sur l'epaule' du CLI entrant.
    Effet de bord borne au GATE (jamais dans le hot-path firewall) — sûr."""
    import sys as _sys

    try:
        _sys.path.insert(0, str(ROOT / "app"))
        import threading as _th

        # `emit` n'a jamais existe (l'API est `persist`), et le `pass` le taisait.
        # persist ecrit en SQLite SYNCHRONE : appele depuis la boucle du hub, il part
        # dans un thread pour ne jamais la figer.
        from nokido_agent.app.forge_critical_events import persist as _persist  # type: ignore

        def _ecrire() -> None:
            if not _persist("cli_present", "info", {
                    "detail": f"{agent} entre dans la piece (presence inter-CLI)",
                    "source": "forge_presence"}):
                print(f"[presence] evenement cli_present de {agent} NON persiste",
                      file=_sys.stderr, flush=True)
        _th.Thread(target=_ecrire, daemon=True, name="presence-evt").start()
    except Exception as e:  # noqa: BLE001 - best-effort, mais NE SE TAIT PAS
        print(f"[presence] evenement cli_present de {agent} NON emis ({type(e).__name__})",
              file=_sys.stderr, flush=True)
    try:
        from nokido_agent.app.forge_swarm_blackboard import apply_fact_sync  # type: ignore

        # `propose_fact` n'a jamais existe et le `pass` ci-dessous taisait l'ImportError :
        # AUCUNE arrivee n'a atteint le tableau noir. Appele depuis la boucle du hub
        # (forge_hub_gate.resolve) : apply_fact_sync y pose une tache, sans bloquer.
        r = apply_fact_sync("discovered_facts", f"{agent} present (arrived)",
                            category="presence", trust=0.6, key=f"presence_arrival_{agent}",
                            source="forge_presence", ring=2)
        if r.get("ok") is False or r.get("error"):
            print(f"[presence] arrivee de {agent} NON publiee : {str(r)[:160]}",
                  file=_sys.stderr, flush=True)
    except Exception as e:  # noqa: BLE001 - best-effort, jamais bloquant, mais NE SE TAIT PAS
        print(f"[presence] arrivee de {agent} NON publiee ({type(e).__name__}: {str(e)[:120]})",
              file=_sys.stderr, flush=True)


def _read_ts(p: Path) -> float | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return float(d.get("ts") or p.stat().st_mtime)
    except Exception:  # noqa: BLE001
        try:
            return p.stat().st_mtime
        except Exception:  # noqa: BLE001
            return None


def room(window_s: int = DEFAULT_WINDOW) -> dict:
    """{agent: age_s} pour les CLIs vus dans la fenetre = qui est dans la piece."""
    out: dict = {}
    now = time.time()
    if not _DIR.exists():
        return out
    for p in _DIR.glob("*.seen"):
        ts = _read_ts(p)
        if ts is None:
            continue
        age = now - ts
        if age <= window_s:
            out[p.stem] = round(age, 1)
    return dict(sorted(out.items(), key=lambda kv: kv[1]))


def who_present(window_s: int = DEFAULT_WINDOW) -> list:
    return list(room(window_s).keys())


def last_seen(agent: str) -> float | None:
    p = _DIR / f"{(agent or '').upper()}.seen"
    ts = _read_ts(p) if p.exists() else None
    return round(time.time() - ts, 1) if ts else None


def _main() -> int:
    import sys

    w = DEFAULT_WINDOW
    for a in sys.argv[1:]:
        if a.startswith("--window="):
            w = int(a.split("=", 1)[1])
    r = room(w)
    print(json.dumps({"window_s": w, "in_room": r, "count": len(r)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
