"""
__FORGE_COLOR__ : observabilité / SN végétatif (diagnostic anatomique)

forge_embolie_scanner — SCANNER D'EMBOLIES par SYSTÈME ANATOMIQUE.

Positionne des POINTS DE CONTRÔLE sur le corps de Nokido, groupés par système (comme on ausculte
un organisme), pour localiser INTELLIGEMMENT où ça bloque (embolie) :

  VASCULAIRE  (circulation données/messages) : event-loop, jobs coincés, locks DB, WAL, COURRIER EN GARE
  PULMONAIRE  (oxygénation LLM/RAG)           : backlog embed, SANTÉ PROVIDERS (clés mortes)
  CÉRÉBRAL    (hub / SNC)                      : santé hub, nerf plug
  NERVEUX     (SN / signaux / endocrine)       : critical_events, cortisol, heartbeats daemons, HOOKS
  MÉTABOLIQUE (ressources)                     : RAM, disque

ANTI-DUP : réutilise `forge_organ_pulse.pulse()` (les 12 checks existants) et ne fait que (a) les
RE-GROUPER par système, (b) AJOUTER 3 points de contrôle révélés par la session (courrier en gare,
santé providers, intégrité hooks UTF-8). Jumelle [[anti_embolie_sentinel]] / forge_nervous_map.

Usage : LAFORGE_PYTHON tools/forge_embolie_scanner.py [--json out.json]
Importable : from forge_embolie_scanner import scan
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

try:  # dogfood : stdout UTF-8 (le scanner affiche 🔴 + détails accentués) — l'embolie qu'il détecte
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

# Système anatomique de chaque point de contrôle (ceux de organ_pulse + les nouveaux).
POINT_TO_SYSTEM = {
    # vasculaire — circulation des données/messages
    "event_loop": "vasculaire", "stuck_jobs": "vasculaire", "db_locks": "vasculaire",
    "wal_bloat": "vasculaire", "postal_queue": "vasculaire",
    # pulmonaire — échange LLM / oxygénation RAG
    "embed_backlog": "pulmonaire", "provider_health": "pulmonaire",
    # cérébral — hub / SNC
    "hub_health": "cerebral", "nerve_plug": "cerebral",
    # nerveux — SN / signaux / endocrine
    "critical_signals": "nerveux", "cortisol": "nerveux", "daemon_heartbeats": "nerveux",
    "hooks_integrity": "nerveux",
    # métabolique — ressources
    "ram": "metabolique", "disk": "metabolique",
}

SYSTEMS = {
    "vasculaire": "circulation données/messages (flux)",
    "pulmonaire": "échange LLM / oxygénation RAG",
    "cerebral": "hub / cognition (SNC)",
    "nerveux": "SN / signaux / endocrine",
    "metabolique": "ressources (RAM/disque/VRAM)",
    "autre": "non classé",
}


# ── Points de contrôle NEUFS (révélés par la session) ─────────────────────────────────
def _check_postal_queue() -> dict:
    """VASCULAIRE : courrier EN GARE (queued non livré) = facteur bloqué -> com inter-agents figée."""
    try:
        from nokido_agent.app.forge_postal import channels_with_pending

        ch = channels_with_pending() or []
        n = len(ch)
        st = "embolie" if n >= 3 else ("warn" if n >= 1 else "clear")
        return {"status": st, "detail": f"{n} canal(aux) avec courrier en gare"}
    except Exception as e:  # noqa: BLE001
        return {"status": "unknown", "detail": f"err {e!r}"[:80]}


def _check_provider_health() -> dict:
    """PULMONAIRE : clés providers mortes (rotation) = cloud LLM asphyxié."""
    try:
        from nokido_agent.app.forge_key_rotation import _load_health

        h = _load_health()
        bad = [fp for fp, e in h.items() if isinstance(e, dict) and e.get("status") == "bad"]
        return {"status": "warn" if bad else "clear",
                "detail": f"{len(bad)} clé(s) provider morte(s)" if bad else "clés providers saines"}
    except Exception as e:  # noqa: BLE001
        return {"status": "unknown", "detail": f"err {e!r}"[:80]}


def _check_hooks_integrity() -> dict:
    """NERVEUX : les hooks CLI (AfterModel) forcent-ils UTF-8 ? Sinon mojibake -> ParserError ->
    éjection (l'embolie qui a fait crasher gemini)."""
    try:
        bad = []
        for h in ("tools/after_model_hook.py", "tools/hook_gate_orchestrator.py"):
            f = ROOT / h
            if not f.exists():
                continue
            txt = f.read_text(encoding="utf-8", errors="replace")
            if "reconfigure(encoding=" not in txt:
                bad.append(h.split("/")[-1])
        return {"status": "warn" if bad else "clear",
                "detail": f"hook(s) sans stdout UTF-8: {bad}" if bad else "hooks UTF-8 OK"}
    except Exception as e:  # noqa: BLE001
        return {"status": "unknown", "detail": f"err {e!r}"[:80]}


_NEW_POINTS = {
    "postal_queue": _check_postal_queue,
    "provider_health": _check_provider_health,
    "hooks_integrity": _check_hooks_integrity,
}

_EMBOLIE = ("embolie",)
_WARN = ("warn",)


def scan() -> dict:
    """Ausculte tous les points de contrôle, les groupe par système, localise les embolies."""
    points: dict = {}
    # 1. réutilise organ_pulse (les 12 checks existants)
    try:
        import sys as _s
        _t = str(ROOT / "tools")
        if _t not in _s.path:
            _s.path.insert(0, _t)
        from nokido_agent.tools.forge_organ_pulse import pulse

        points.update(pulse().get("points", {}))
    except Exception as e:  # noqa: BLE001
        points["_organ_pulse_err"] = {"status": "unknown", "detail": f"pulse indispo: {e!r}"[:90]}
    # 2. ajoute les points neufs
    for name, fn in _NEW_POINTS.items():
        try:
            points[name] = fn()
        except Exception as e:  # noqa: BLE001
            points[name] = {"status": "unknown", "detail": f"err {e!r}"[:80]}

    # 3. groupe par système anatomique
    carte: dict = {s: {} for s in SYSTEMS}
    embolies, warns = [], []
    for name, st in points.items():
        sysname = POINT_TO_SYSTEM.get(name, "autre")
        carte[sysname][name] = st
        status = (st or {}).get("status")
        if status in _EMBOLIE:
            embolies.append({"point": name, "systeme": sysname, "detail": st.get("detail")})
        elif status in _WARN:
            warns.append({"point": name, "systeme": sysname, "detail": st.get("detail")})

    # 4. verdict par système + global
    sys_verdict = {}
    for s, pts in carte.items():
        statuses = [(p or {}).get("status") for p in pts.values()]
        sys_verdict[s] = ("embolie" if any(x in _EMBOLIE for x in statuses)
                          else "warn" if any(x in _WARN for x in statuses)
                          else "clear" if pts else "n/a")
    verdict = ("embolie" if embolies else "warn" if warns else "sain")
    return {"verdict": verdict, "embolies": embolies, "warns": warns,
            "systemes": {s: {"verdict": sys_verdict[s], "desc": SYSTEMS[s], "points": carte[s]}
                         for s in SYSTEMS if carte[s]}}


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    r = scan()
    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"VERDICT GLOBAL: {r['verdict'].upper()}  ({len(r['embolies'])} embolie, {len(r['warns'])} warn)")
    for s, d in r["systemes"].items():
        mark = {"embolie": "🔴", "warn": "🟡", "clear": "🟢"}.get(d["verdict"], "⚪")
        print(f"  {mark} {s:12} [{d['verdict']}] — {d['desc']}")
        for pt, st in d["points"].items():
            if st.get("status") in ("embolie", "warn"):
                print(f"        ↳ {pt}: {st.get('status')} — {st.get('detail')}")


if __name__ == "__main__":
    main()
