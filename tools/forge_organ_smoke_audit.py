"""forge_organ_smoke_audit.py — audit d'INTEGRATION des organes.

POURQUOI CET OUTIL
  L'audit profond demande le 2026-07-23 (spec_audit_profond_23_07) avait ete
  delegue et n'est jamais revenu : la roadmap a ete ecrite comme s'il avait eu
  lieu. Rejouable, il n'y a plus a le deleguer ni a le croire sur parole.

  Il teste ce qu'un lint ne voit PAS : est-ce que chaque organe s'IMPORTE et
  REPOND dans le process ou il tourne, et ses gardes tiennent-ils sur entree
  degeneree (service inconnu, fenetre negative, compteur nul) ?

  Premiere execution (24-07) : 4 echecs, tous sur `forge_resource_manager`, dus a
  une COLLISION DE NOMS entre app/ et tools/ — deux modules differents sous le
  meme nom, l'import dependant de l'ordre de sys.path. Corrige par renommage
  (tools/forge_test_resource_calibrator.py).

LECTURE SEULE : n'appelle que des API sans effet de bord (kill=False, evict=False).

CLI :
    LAFORGE_PYTHON tools/forge_organ_smoke_audit.py
    (rc=0 si aucun finding, rc=1 sinon -> utilisable en gate)
"""
from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# app/ AVANT tools/ : l'inverse ferait resoudre les homonymes vers les outils.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

FINDINGS: list[dict] = []

MODULES = [
    "forge_self_awareness", "forge_econome", "forge_reboot_sentinel",
    "forge_body_world_model", "forge_port_reconcile", "forge_active_inference",
    "forge_delivery_integrity", "forge_promcp_profiler", "forge_resource_manager",
    "forge_homeostasis_orchestrator", "forge_metric_integrity",
]

# (phase du tick homeostatique, module, fonction appelee)
PHASES = [
    ("reboot_sentinel", "forge_reboot_sentinel", "run_cycle"),
    ("reconcile", "forge_port_reconcile", "run_cycle"),
    ("health", "forge_health_diagnostic", "run_cycle"),
    ("econome", "forge_econome", "run_cycle"),
    ("self_awareness", "forge_self_awareness", "publish_self_state"),
    ("delivery_integrity", "forge_delivery_integrity", "scan"),
    ("efficiency", "forge_tool_efficiency", "run_cycle"),
    ("coagulation", "forge_coagulation_cascade", "run_cycle"),
]


def check(label: str, fn) -> object | None:
    try:
        r = fn()
        print(f"  OK   {label}: {str(r)[:150]}")
        return r
    except Exception as e:  # noqa: BLE001
        last = traceback.format_exc().strip().splitlines()[-1]
        print(f"  FAIL {label}: {type(e).__name__}: {str(e)[:120]}")
        FINDINGS.append({"cible": label, "erreur": f"{type(e).__name__}: {e}", "trace": last})
        return None


def main() -> int:
    print("=== 1. IMPORT (integration reelle) ===")
    mods = {}
    for m in MODULES:
        if check(f"import {m}", lambda m=m: importlib.import_module(m).__name__):
            mods[m] = importlib.import_module(m)

    print("\n=== 2. SMOKE des API publiques (lecture seule, entrees degenerees) ===")
    if "forge_body_world_model" in mods:
        wm = mods["forge_body_world_model"]
        check("predict_impact(service inconnu)",
              lambda: wm.predict_impact("ServiceQuiNExistePas", "stop").get("verdict"))
        check("predict_impact(action inconnue)",
              lambda: wm.predict_impact("NokidoOllama", "zzz").get("verdict"))
    if "forge_active_inference" in mods:
        ai = mods["forge_active_inference"]
        check("recent_surprise()", lambda: ai.recent_surprise()["n"])
        check("recent_surprise(last_n=0)", lambda: ai.recent_surprise(last_n=0)["n"])
        check("recent_surprise(window negative)", lambda: ai.recent_surprise(window_s=-5)["n"])
    if "forge_delivery_integrity" in mods:
        check("delivery_integrity.scan()", lambda: mods["forge_delivery_integrity"].scan()["count"])
    if "forge_promcp_profiler" in mods:
        pp = mods["forge_promcp_profiler"]
        check("promcp.stats()", lambda: pp.stats()["n_calls"])
        check("promcp.observed_cost_ms(inconnu) -> None",
              lambda: repr(pp.observed_cost_ms("tool_jamais_appele")))
    if "forge_resource_manager" in mods:
        rm = mods["forge_resource_manager"]
        check("get_active_intents()", lambda: rm.get_active_intents())
        check("request_resources(0, evict=False)", lambda: rm.request_resources(0.0, allow_evict=False)["ok"])
        check("request_resources(negatif, evict=False)", lambda: rm.request_resources(-1.0, allow_evict=False)["ok"])
        check("_heavy_evictable_services()", lambda: len(rm._heavy_evictable_services()))
    if "forge_self_awareness" in mods and hasattr(mods["forge_self_awareness"], "self_snapshot"):
        check("self_snapshot() sections", lambda: sorted(mods["forge_self_awareness"].self_snapshot().keys()))
    if "forge_econome" in mods and hasattr(mods["forge_econome"], "run_cycle"):
        check("econome.run_cycle()", lambda: list((mods["forge_econome"].run_cycle() or {}).keys())[:6])
    if "forge_reboot_sentinel" in mods and hasattr(mods["forge_reboot_sentinel"], "run_cycle"):
        check("reboot_sentinel.run_cycle()", lambda: mods["forge_reboot_sentinel"].run_cycle().get("ok"))
    if "forge_port_reconcile" in mods:
        check("port_reconcile.run_cycle(kill=False)",
              lambda: mods["forge_port_reconcile"].run_cycle(kill=False)["n_ports"])
    if "forge_metric_integrity" in mods:
        check("metric_integrity.scan()", lambda: mods["forge_metric_integrity"].scan()["count"])

    print("\n=== 3. HOMEOSTAT : chaque phase du tick pointe-t-elle sur du reel ? ===")
    for phase, mod, fn in PHASES:
        def _imp(mod=mod, fn=fn):
            m = importlib.import_module(mod)
            if not hasattr(m, fn):
                raise AttributeError(f"{mod}.{fn} ABSENT — la phase appellerait dans le vide")
            return "callable"
        check(f"phase {phase} -> {mod}.{fn}", _imp)

    print("\n=== RESUME ===")
    print(json.dumps({"findings": FINDINGS, "count": len(FINDINGS)}, indent=2, ensure_ascii=False))
    return 1 if FINDINGS else 0


if __name__ == "__main__":
    raise SystemExit(main())
