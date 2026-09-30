#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_flap_journal.py — Journal PERSISTANT des oscillations de services (prealable S2).

__FORGE_COLOR__ = "autoregulation/flap-journal"

POURQUOI CE MODULE EXISTE. Le superviseur compte `restarts` par service, mais ce
compteur est VOLATIL : il repart de zero a chaque boot du superviseur. Mesure
2026-07-25 23h : 52 services, 4 restarts au total, `backoffIdx` a 0 partout, uptimes
~17 min. Un flap CHRONIQUE est donc structurellement indetectable -- on ne lit qu'un
instant t alors que le fait cherche est TEMPOREL. Ce module transforme ce compteur
volatil en historique date qui survit aux redemarrages.

CE MODULE N'ESCALADE RIEN, A DESSEIN. Un amortisseur (System 2 de Beer, l'anti-
oscillateur) ne peut pas etre calibre avant qu'on sache a quoi ressemble le regime
normal ; des seuils poses d'avance seraient inventes. Il observe, il date, il persiste.
La calibration viendra du journal, pas d'une intuition.

ANTI-DUP. Le backoff de RESPAWN existe DEJA dans le superviseur (`backoffIdx`, remis a
0 sur activation) : on ne le refait pas. Ce qui manque est l'historique, et le canal
persistant existe aussi (`forge_critical_events`, append-only, survit au restart) : on
s'y branche au lieu d'ouvrir un stockage de plus.

Usage :
  LAFORGE_PYTHON app/forge_flap_journal.py          # un cycle, affiche le resultat
  from forge_flap_journal import run_cycle          # appele par l'homeostat
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "autoregulation/flap-journal"

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "sandbox" / "flap_journal.json"
SUPERVISOR_URL = "http://127.0.0.1:8765/supervisor/status"
TIMEOUT_S = 8.0


def _fetch_status() -> Optional[dict]:
    """Registre vivant du superviseur. L'echec est RENDU, jamais avale : un capteur
    qui ne peut pas voir ne doit pas se lire comme 'rien a signaler'."""
    try:
        raw = urllib.request.urlopen(SUPERVISOR_URL, timeout=TIMEOUT_S).read()
        return json.loads(raw.decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _load_baseline() -> dict:
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_baseline(obj: dict) -> None:
    try:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        tmp = BASELINE.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
        tmp.replace(BASELINE)
    except OSError as e:
        print(f"[flap] baseline NON persistee ({e}) — le prochain cycle repartira a vide",
              flush=True)


def _persist(kind: str, severity: str, payload: dict) -> None:
    try:
        from nokido_agent.app.forge_critical_events import persist

        persist(kind=kind, severity=severity, payload=payload)
    except Exception as e:  # noqa: BLE001
        print(f"[flap] evenement NON journalise ({type(e).__name__}: {e})", flush=True)


def run_cycle() -> dict[str, Any]:
    """Echantillonne le superviseur et journalise chaque redemarrage observe.

    DEUX signaux, car aucun ne suffit seul :
      - `restarts` qui AUGMENTE : le compteur du superviseur lui-meme.
      - `uptime_s` qui DIMINUE : detecte un redemarrage MEME quand le compteur a ete
        remis a zero, ce que le seul delta de compteur raterait.
    Un `restarts` qui DIMINUE signe un reboot du superviseur : on re-etalonne sans
    fabriquer de delta negatif, sinon chaque reboot produirait un faux flap.
    """
    status = _fetch_status()
    if status is None:
        return {"ok": False, "reason": "superviseur injoignable", "events": 0}

    services = status.get("services") or {}
    if not services:
        return {"ok": False, "reason": "registre vide", "events": 0}

    prev = _load_baseline()
    now: dict[str, dict] = {}
    candidates: list[dict] = []
    resets: list[str] = []
    comparable = 0

    for name, st in services.items():
        if not isinstance(st, dict):
            continue
        restarts = int(st.get("restarts") or 0)
        uptime = float(st.get("uptime_s") or 0.0)
        now[name] = {"restarts": restarts, "uptime_s": uptime}

        p = prev.get(name)
        if not isinstance(p, dict):
            continue
        comparable += 1
        p_restarts = int(p.get("restarts") or 0)
        p_uptime = float(p.get("uptime_s") or 0.0)

        if restarts < p_restarts:
            resets.append(name)
            continue

        delta = restarts - p_restarts
        if delta > 0 or uptime < p_uptime:
            candidates.append({"service": name, "delta_restarts": delta,
                               "restarts_total": restarts, "uptime_s": uptime,
                               "uptime_prev_s": p_uptime,
                               "cause": "compteur" if delta > 0 else "uptime_recule"})

    # GARDE GLOBAL, avant toute ecriture : un reboot du superviseur fait reculer l'uptime
    # de TOUS ses enfants dans le MEME echantillon. Le garde par service (`restarts` qui
    # diminue) ne peut pas le voir -- un compteur deja a 0 ne diminue jamais.
    # MESURE 2026-07-25 23h21, premier tick apres un restart owner : 47 faux flaps sur
    # 52 services, dont seulement 3 rattrapes par le garde par service (les 3 seuls qui
    # avaient des restarts non nuls). Un flap REEL touche un ou deux services ; un reboot
    # les touche presque tous. D'ou le seuil a la moitie des services comparables, avec
    # un plancher de 3 pour ne pas requalifier une petite rafale en reboot.
    affected = len(candidates) + len(resets)
    if comparable and affected >= max(3, comparable // 2):
        _persist("flap:supervisor_reboot", "info",
                 {"affectes": affected, "comparable": comparable,
                  "n_services": len(now)})
        _save_baseline(now)
        return {"ok": True, "n_services": len(now), "events": 0, "flapping": [],
                "supervisor_reboot": True, "affected": affected,
                "first_run": not prev}

    for ev in candidates:
        _persist(f"flap:{ev['service']}", "warn", ev)

    _save_baseline(now)

    if resets:
        _persist("flap:supervisor_reset", "info",
                 {"services": resets[:20], "n": len(resets)})

    return {"ok": True, "n_services": len(now), "events": len(candidates),
            "flapping": [e["service"] for e in candidates],
            "supervisor_reset": len(resets), "supervisor_reboot": False,
            "first_run": not prev}


def main() -> int:
    print(json.dumps(run_cycle(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
